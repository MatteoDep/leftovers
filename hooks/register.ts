import type { Engine, Register } from 'claude-code'

// The leftovers dashboard (a claude.ai artifact) and its db layout:
// meta/items + meta/sessions are written by the /leftovers scan, state/<itemId>
// by the page (user ticks, no `by`) or by this tool (`by` = session id),
// live/<sessionId> by this tool: items a session added since the last scan.
// The dashboard's url is in ~/.claude/leftovers/config.json, written by the first /leftovers run.
const TOOL = 'mcp__leftovers__leftovers'
const STALE_HOURS = 24
// The same token shapes as the scanner's common.py.
const SECRET = new RegExp(
  '\\b(?:sq[apu]_[0-9a-z]{30,}|gh[pousr]_[0-9a-z]{30,}|xox[abpr]-[0-9a-z-]{10,}|AKIA[0-9A-Z]{16}|eyJ[\\w-]{10,}\\.[\\w-]{10,}\\.[\\w-]{10,}' +
    '|github_pat_\\w{30,}|glpat-[\\w-]{20,}|AT(?:ATT|BB|CTT)[\\w=-]{20,}|sk-(?:ant-)?[\\w-]{20,})|-----BEGIN [A-Z ]*PRIVATE KEY' +
    '|(?:token|secret|password|passwd|pwd|api[_-]?key|authorization|access[_-]?key)["\']?\\s*[:=]\\s*(?:bearer\\s+)?["\']?[^\\s"\'`]{6,}' +
    '|:-[0-9a-f]{32,64}\\}|://[^/\\s:@]+:[^/\\s@]+@',
  'i',
)

// The tool's description carries the usage note: a prompt.compose section can be
// skipped by a plugin above this one, the tool list cannot.
const NOTE =
  'The leftovers dashboard (set up by the /leftovers skill) tracks open work from Claude Code sessions. ' +
  '`close` an item when you finish the work it describes; ' +
  '`add` one when a turn ends with work explicitly left for later (the user postponed it, agreed next steps not done, a question waiting on someone); ' +
  '`list` shows this session\'s open items, useful after resuming; `drop` removes an item you added that no longer applies. ' +
  'Items are short, concrete and never contain secrets. Closing another session\'s item asks the user first.'

const SCHEMA = {
  type: 'object',
  properties: {
    action: { type: 'string', enum: ['list', 'close', 'add', 'drop'] },
    id: { type: 'string', description: 'Item id, for close and drop.' },
    text: { type: 'string', description: 'For add: the pending action, imperative, at most 200 characters.' },
    detail: { type: 'string', description: 'For add: one or two sentences of context (files, branch, ticket, command).' },
    priority: { type: 'string', enum: ['high', 'medium', 'low'] },
    kind: { type: 'string', enum: ['todo', 'pr', 'deploy', 'verify', 'question', 'followup', 'blocked'] },
  },
  required: ['action'],
}

type Item = { id: string; session_id?: string; text: string; detail?: string; kind?: string; priority?: string; check?: { status?: string } }
type Doc = { id: string; data: any; version?: number }
type Input = { action?: string; id?: string; text?: string; detail?: string; priority?: string; kind?: string }

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    const started = await next(e)
    await $.tool.register({ name: 'leftovers', description: NOTE, inputSchema: SCHEMA, isDeferred: false })
    if (e.isInteractive) {
      try {
        await remind($)
      } catch {
        // A reminder is never worth breaking a session start.
      }
    }
    return started
  })

  // Own items and the plugin's own db calls run without a prompt; another
  // session's item is put to the person, never to the classifier.
  on('tool.check', { tool: TOOL }, async ($, e, next) => {
    const base = await next(e)
    if (base.decision === 'deny') return base
    const input = (e.input ?? {}) as Input
    if (input.action !== 'close' || !input.id) return { decision: 'allow' as const }
    const own = (await $.session.id()).slice(0, 8)
    return input.id.startsWith(own + '-')
      ? { decision: 'allow' as const }
      : { decision: 'ask' as const, reason: `Close item ${input.id}, which belongs to another session, on the leftovers dashboard?` }
  }).catch(() => ({ decision: 'deny' as const }))

  on('tool.check', { tool: 'ArtifactData' }, async ($, e, next) => {
    const input = (e.input ?? {}) as { url?: string; collection?: string }
    if (next.origin?.plugin !== $.plugin.name || !['meta', 'state', 'live'].includes(input.collection ?? '')) return next(e)
    const url = await dashboard($).catch(() => undefined)
    return url && artifactId(input.url) === artifactId(url) ? { decision: 'allow' as const } : next(e)
  })

  on('tool.call', { tool: TOOL }, async ($, e) => {
    const input = e as unknown as Input
    try {
      return { result: await serve($, input) }
    } catch (err) {
      return { result: `leftovers ${input.action ?? ''} failed: ${String((err as Error)?.message ?? err)}` }
    }
  })
}

async function serve($: Engine, input: Input): Promise<string> {
  const sid = await $.session.id()
  const sid8 = sid.slice(0, 8)
  switch (input.action) {
    case 'list': {
      const [items, live] = await Promise.all([metaItems($), liveDoc($, sid)])
      const own = dedupe([...items.filter(i => i.session_id === sid), ...((live?.data.items ?? []) as Item[])])
      const states = await Promise.all(own.map(i => getDoc($, 'state', i.id)))
      const open = own.filter((i, n) => effective(i, states[n]?.data) === 'open')
      if (!open.length) return 'No open leftovers for this session.'
      return open.map(i => `${i.id} [${i.priority ?? 'medium'}] ${i.text}`).join('\n')
    }
    case 'close': {
      const id = need(input.id, 'id')
      const owner = id.slice(0, 8)
      const [items, live] = await Promise.all([metaItems($), owner === sid8 ? liveDoc($, sid).then(d => (d ? [d] : [])) : liveDocs($)])
      const item = [...items, ...live.flatMap(d => (d.data.items ?? []) as Item[])].find(i => i.id === id)
      if (!item) return `No item ${id} on the dashboard.`
      const state = await getDoc($, 'state', id)
      if (state && !state.data.by) return `The user set ${id} to "${state.data.state}" on the dashboard, so it stays as they set it.`
      if (state?.data.state === 'done') return `${id} is already done.`
      await write($, 'state', id, { state: 'done', updated_at: new Date().toISOString(), by: sid }, state?.version)
      return `Closed ${id}: ${item.text}`
    }
    case 'add':
    case 'drop':
      return retry(() => editLive($, sid, input))
    default:
      return 'Unknown action: use list, close, add or drop.'
  }
}

// add and drop rewrite live/<sid>: re-read and retry when another call wrote it first.
async function retry(fn: () => Promise<string>): Promise<string> {
  for (let n = 0; ; n++) {
    try {
      return await fn()
    } catch (err) {
      if (n >= 2 || !/version_mismatch|already exists/i.test(String((err as Error)?.message))) throw err
    }
  }
}

async function editLive($: Engine, sid: string, input: Input): Promise<string> {
  const sid8 = sid.slice(0, 8)
  switch (input.action) {
    case 'add': {
      const text = need(input.text, 'text').trim().slice(0, 200)
      const detail = (input.detail ?? '').trim().slice(0, 600)
      if (SECRET.test(text) || SECRET.test(detail)) return 'Refused: the item looks like it contains a secret. Describe it without the value.'
      const id = `${sid8}-${hash(text)}`
      const [items, live] = await Promise.all([metaItems($), liveDoc($, sid)])
      const current = (live?.data.items ?? []) as Item[]
      if (items.some(i => i.id === id) || current.some(i => i.id === id)) return `Already on the dashboard as ${id}.`
      const item: Item = { id, text, detail, kind: input.kind ?? 'todo', priority: input.priority ?? 'medium' }
      await write($, 'live', sid, { session_id: sid, cwd: await $.session.cwd(), updated_at: new Date().toISOString(), items: [...current, item] }, live?.version)
      return `Added ${id}.`
    }
    case 'drop': {
      const id = need(input.id, 'id')
      const live = await liveDoc($, sid)
      const current = (live?.data.items ?? []) as Item[]
      if (!live || !current.some(i => i.id === id)) return `${id} is not an item this session added; use close for scanned items.`
      await write($, 'live', sid, { ...live.data, updated_at: new Date().toISOString(), items: current.filter(i => i.id !== id) }, live.version)
      return `Dropped ${id}.`
    }
    default:
      return 'Unknown action.'
  }
}

function need(v: string | undefined, name: string): string {
  if (!v || !v.trim()) throw new Error(`missing ${name}`)
  return v.trim()
}

function effective(i: Item, state?: { state?: string }): string {
  if (state?.state) return state.state
  return ({ done: 'done', duplicate: 'dismissed' } as Record<string, string>)[i.check?.status ?? ''] ?? 'open'
}

function dedupe(items: Item[]): Item[] {
  const seen = new Set<string>()
  return items.filter(i => !seen.has(i.id) && !!seen.add(i.id))
}

// FNV-1a over the normalized text: 8 hex chars, the same length as the scanner's ids.
function hash(text: string): string {
  let h = 0x811c9dc5
  for (const ch of text.toLowerCase().split(/\s+/).filter(Boolean).join(' ')) {
    h ^= ch.codePointAt(0)!
    h = Math.imul(h, 0x01000193) >>> 0
  }
  return h.toString(16).padStart(8, '0')
}

// The dashboard url from the config the first /leftovers run writes; read on every call so a
// dashboard created mid-session is picked up.
async function dashboard($: Engine): Promise<string> {
  const home = await $.env.get('HOME')
  const cfg = JSON.parse(await $.fs.read(`${home}/.claude/leftovers/config.json`).catch(() => '{}'))
  if (!cfg.artifact_url) throw new Error('no leftovers dashboard yet: run /leftovers once to create it')
  return cfg.artifact_url
}

// claude.ai/artifact/<id> and claude.ai/code/artifact/<id> name the same artifact
const artifactId = (url?: string) => (url ?? '').replace(/[?#].*$/, '').split('/').filter(Boolean).pop() ?? ''

async function db($: Engine, input: Record<string, unknown>): Promise<string> {
  const res = (await $.tool.call({ tool: 'ArtifactData', url: await dashboard($), ...input } as any)) as any
  if (res?.deny) throw new Error(res.deny)
  const text = typeof res?.text === 'string' ? res.text : typeof res?.result === 'string' ? res.result : ''
  if (res?.isError) throw new Error(text.slice(0, 300) || 'ArtifactData failed')
  return text
}

// The tool's text carries one JSON document per line inside its BEGIN/END markers.
function parseDocs(text: string): Doc[] {
  const docs: Doc[] = []
  for (const line of text.split('\n')) {
    if (!line.startsWith('{')) continue
    try {
      const d = JSON.parse(line)
      if (d && typeof d.id === 'string' && d.data && typeof d.data === 'object') docs.push(d)
    } catch {
      // not a document line
    }
  }
  return docs
}

// A doc that cannot be read must fail loudly: an empty answer would read as "no items".
async function getDoc($: Engine, collection: string, id: string): Promise<Doc | undefined> {
  const text = await db($, { action: 'get', collection, doc_id: id })
  if (/^No document /.test(text.trim())) return undefined
  const doc = parseDocs(text).find(d => d.id === id)
  if (!doc) throw new Error(`could not read ${collection}/${id} from the dashboard`)
  return doc
}

async function listDocs($: Engine, collection: string): Promise<Doc[]> {
  const text = await db($, { action: 'list', collection, query: { limit: 1000 } })
  const docs = parseDocs(text)
  const count = Number(/(\d+) documents?/.exec(text)?.[1] ?? docs.length)
  if (docs.length < count) throw new Error(`could only read ${docs.length} of ${count} ${collection} docs`)
  return docs
}

const metaItems = async ($: Engine) => ((await getDoc($, 'meta', 'items'))?.data.items ?? []) as Item[]
const liveDoc = ($: Engine, sid: string) => getDoc($, 'live', sid)
const liveDocs = ($: Engine) => listDocs($, 'live')

async function write($: Engine, collection: string, id: string, data: object, version?: number) {
  const text = await db($, { action: 'set', collection, doc_id: id, data, ...(version ? { if_version: version } : {}) })
  if (!/committed/i.test(text) || /failed|nothing was written/i.test(text)) throw new Error(text.slice(0, 300) || 'write not confirmed')
}

async function remind($: Engine) {
  const today = new Date().toISOString().slice(0, 10)
  if ((await $.store.get('lastShown')) === today) return

  const home = await $.env.get('HOME')
  if (!home) return
  let scan: { scanned_at: string }
  try {
    scan = JSON.parse(await $.fs.read(`${home}/.claude/leftovers/last_scan.json`))
  } catch {
    $.ui.toast('No leftovers scan found. Run /leftovers to build the dashboard.')
    await $.store.set('lastShown', today)
    return
  }

  const scannedMs = Date.parse(scan.scanned_at)
  const hours = (Date.now() - scannedMs) / 3.6e6
  if (!(hours >= STALE_HOURS)) return

  const own = await $.session.id()
  const projects = `${home}/.claude/projects`
  let changed = 0
  for (const dir of await $.fs.list(projects)) {
    if (dir.kind !== 'dir') continue
    const files = await $.fs.list(`${projects}/${dir.name}`).catch(() => [])
    changed += files.filter(
      f => f.kind === 'file' && f.name.endsWith('.jsonl') && f.mtimeMs > scannedMs && f.name !== `${own}.jsonl`,
    ).length
  }
  if (changed === 0) return

  const days = Math.floor(hours / 24)
  $.ui.toast(
    `Leftovers dashboard last updated ${days} day${days === 1 ? '' : 's'} ago, ` +
      `${changed} session${changed === 1 ? '' : 's'} may have changed since. Run /leftovers to update it.`,
  )
  await $.store.set('lastShown', today)
}
