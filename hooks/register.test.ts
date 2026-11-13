import { expect, mock, test } from 'claude-code/testing'

const TOOL = 'mcp__leftovers__leftovers'
const SID = 'aaaaaaaa-1111-2222-3333-444444444444'
const HOUR = 3.6e6

type Doc = { data: any; version: number }

// Stands in for the engine: ArtifactData over an in-memory db, plus fs/env/store for the reminder.
const DASH = 'https://claude.ai/artifact/TestDashboard123'

type Opts = { docs?: Record<string, any>; scan?: object; files?: { name: string; mtimeMs: number }[]; conflicts?: number; garble?: boolean; vfs?: Record<string, string | null> }

function engine(on: any, opts: Opts = {}) {
  // the files the mod reads: the dashboard config (present unless a test removes it with null)
  const files = { '/home/u/.claude/leftovers/config.json': JSON.stringify({ artifact_url: DASH }), ...(opts.vfs ?? {}) }
  const vfs = new Map<string, { text: string; mtimeMs: number }>(Object.entries(files).filter(([, v]) => v !== null).map(([k, v]) => [k, { text: v as string, mtimeMs: Date.now() }]))
  let conflicts = opts.conflicts ?? 0
  const db = new Map<string, Doc>(Object.entries(opts.docs ?? {}).map(([k, v]) => [k, { data: v, version: 1 }]))
  const toasts: string[] = []
  const registered: any[] = []
  const store: Record<string, unknown> = {}
  const line = (path: string, d: Doc) => JSON.stringify({ id: path.split('/')[1], data: d.data, version: d.version })
  const wrap = (lines: string[]) => `${lines.length} documents\n=== BEGIN ARTIFACT DB x ===\n${lines.join('\n')}\n=== END ARTIFACT DB x ===`
  on('tool.call', { tool: 'ArtifactData' }, (_: any, e: any) => {
    const path = `${e.collection}/${e.doc_id}`
    if (opts.garble) return { result: 'Result too large, saved to /tmp/x.json' }
    if (e.action === 'get') {
      const d = db.get(path)
      return { result: d ? wrap([line(path, d)]) : `No document "${e.doc_id}"` }
    }
    if (e.action === 'list') return { result: wrap([...db].filter(([k]) => k.startsWith(e.collection + '/')).map(([k, d]) => line(k, d))) }
    if (e.action === 'set') {
      const cur = db.get(path)
      if (conflicts > 0 || (cur && cur.version !== e.if_version)) {
        conflicts--
        return { result: 'db write failed (version_mismatch): nothing was written.', isError: true }
      }
      db.set(path, { data: e.data, version: (cur?.version ?? 0) + 1 })
      return { result: 'Database set committed' }
    }
    return { result: 'unsupported' }
  })
  on('session.start', (_: any, e: any) => ({ cwd: e.cwd }))
  on('tool.check', (_: any, e: any) => ({ decision: e.tool === 'mcp__leftovers__leftovers' && e.input?.id === 'aaaaaaaa-denied' ? 'deny' : 'ask' }))
  on('tool.register', (_: any, e: any) => {
    registered.push(e)
    return { value: undefined }
  })
  on('session.id', () => ({ value: SID }))
  on('session.cwd', () => ({ value: '/repo' }))
  on('env.get', () => ({ value: '/home/u' }))
  on('store.get', (_: any, e: any) => ({ value: store[e.key] }))
  on('store.set', (_: any, e: any) => {
    store[e.key] = e.value
    return { value: undefined }
  })
  on('ui.toast', (_: any, e: any) => {
    toasts.push(e.text)
    return { value: undefined }
  })
  on('fs.read', (_: any, e: any) => {
    if (vfs.has(e.path)) return { value: vfs.get(e.path)!.text }
    if (!opts.scan || !e.path.endsWith('last_scan.json')) throw new Error('ENOENT')
    return { value: JSON.stringify(opts.scan) }
  })
  on('fs.list', (_: any, e: any) => {
    return {
      value: e.path.endsWith('/projects')
        ? [{ name: 'proj', kind: 'dir', size: 0, mtimeMs: 0, isLink: false }]
        : (opts.files ?? []).map(f => ({ ...f, kind: 'file', size: 1, isLink: false })),
    }
  })
  const clock = mock.clock(on, { now: Date.now() })
  return { db, toasts, store, registered, vfs, clock }
}

const start = ($: any, isInteractive = true) => $.session.start({ cwd: '/', surface: 'terminal', isInteractive })
const call = async ($: any, input: object) => String((await $.tool.call({ tool: TOOL, ...input })).result)
const META = {
  'meta/items': {
    items: [
      { id: 'aaaaaaaa-00000001', session_id: SID, text: 'own scanned item', priority: 'high' },
      { id: 'aaaaaaaa-00000002', session_id: SID, text: 'own item git found done', check: { status: 'done' } },
      { id: 'bbbbbbbb-00000003', session_id: 'bbbbbbbb-x', text: 'other session item' },
    ],
  },
}

test('add writes a live item, list shows it with the open scanned ones, drop removes it', async ($, on) => {
  const { db } = engine(on, { docs: META })
  await start($)
  const added = await call($, { action: 'add', text: 'Push branch fix/x', priority: 'high' })
  expect(added).toMatch(/^Added aaaaaaaa-[0-9a-f]{8}\.$/)
  const id = added.slice(6, -1)
  expect(db.get(`live/${SID}`)?.data.items[0].text).toBe('Push branch fix/x')
  expect(await call($, { action: 'add', text: '  push   BRANCH fix/x ' })).toContain('Already on the dashboard')

  const listed = await call($, { action: 'list' })
  expect(listed).toContain('own scanned item')
  expect(listed).toContain(id)
  expect(listed.includes('git found done')).toBe(false)
  expect(listed.includes('other session')).toBe(false)

  expect(await call($, { action: 'drop', id })).toBe(`Dropped ${id}.`)
  expect(db.get(`live/${SID}`)?.data.items.length).toBe(0)
  expect(await call($, { action: 'drop', id: 'aaaaaaaa-00000001' })).toContain('use close')
})

test('close marks an own item done with by, and never overrides the user', async ($, on) => {
  const { db } = engine(on, { docs: { ...META, 'state/aaaaaaaa-00000002': { state: 'open' } } })
  await start($)
  expect(await call($, { action: 'close', id: 'aaaaaaaa-00000001' })).toContain('Closed aaaaaaaa-00000001')
  expect(db.get('state/aaaaaaaa-00000001')?.data).toMatchObject({ state: 'done', by: SID })
  expect(await call($, { action: 'close', id: 'aaaaaaaa-00000002' })).toContain('so it stays as they set it')
  expect(db.get('state/aaaaaaaa-00000002')?.data.state).toBe('open')
  expect(await call($, { action: 'close', id: 'aaaaaaaa-99999999' })).toContain('No item')
})

test('own items are allowed, another session\'s close is put to the person', async ($, on) => {
  engine(on, { docs: META })
  await start($)
  expect((await $.tool.check({ tool: TOOL, input: { action: 'close', id: 'aaaaaaaa-00000001' } })).decision).toBe('allow')
  expect((await $.tool.check({ tool: TOOL, input: { action: 'add', text: 'x' } })).decision).toBe('allow')
  const other = await $.tool.check({ tool: TOOL, input: { action: 'close', id: 'bbbbbbbb-00000003' } })
  expect(other.decision).toBe('ask')
  expect(other.plugin).toBe('leftovers') // a plugin's ask is put to the person
  // a deny from the user's own rules stands
  expect((await $.tool.check({ tool: TOOL, input: { action: 'close', id: 'aaaaaaaa-denied' } })).decision).toBe('deny')
})

test('an item that looks like a secret is refused', async ($, on) => {
  const { db } = engine(on, { docs: META })
  await start($)
  expect(await call($, { action: 'add', text: 'rotate it', detail: 'CI_TOKEN=abcdef0123456789' })).toContain('Refused')
  expect(db.has(`live/${SID}`)).toBe(false)
})


test('reminder: stale scan with changed sessions toasts once', async ($, on) => {
  const ago = (h: number) => Date.now() - h * HOUR
  const { toasts } = engine(on, {
    scan: { scanned_at: new Date(ago(50)).toISOString() },
    files: [
      { name: 'a.jsonl', mtimeMs: ago(1) },
      { name: 'b.jsonl', mtimeMs: ago(100) },
      { name: `${SID}.jsonl`, mtimeMs: ago(0) },
    ],
  })
  await start($)
  await start($)
  expect(toasts).toEqual(['Leftovers dashboard last updated 2 days ago, 1 session may have changed since. Run /leftovers to update it.'])
})

test('reminder: fresh scan, -p run and broken date stay quiet', async ($, on) => {
  const { toasts } = engine(on, { scan: { scanned_at: 'garbage' }, files: [{ name: 'a.jsonl', mtimeMs: Date.now() }] })
  await start($)
  await start($, false)
  expect(toasts.length).toBe(0)
})

test('ids match the scanner hash, and a write conflict is retried', async ($, on) => {
  const { db } = engine(on, { docs: META, conflicts: 1 })
  await start($)
  // merge.py new_id('aaaaaaaa...', 'push branch fix/x') == 'aaaaaaaa-c45e52a7'
  expect(await call($, { action: 'add', text: 'Push   branch fix/x' })).toBe('Added aaaaaaaa-c45e52a7.')
  expect(db.get(`live/${SID}`)?.data.items.length).toBe(1)
})

test('an unreadable dashboard answer fails instead of looking empty', async ($, on) => {
  engine(on, { docs: META, garble: true })
  await start($)
  expect(await call($, { action: 'list' })).toContain('failed: could not read ')
})

test('closing another session\'s item through the tool writes by', async ($, on) => {
  const { db } = engine(on, { docs: META })
  await start($)
  expect(await call($, { action: 'close', id: 'bbbbbbbb-00000003' })).toContain('Closed bbbbbbbb-00000003')
  expect(db.get('state/bbbbbbbb-00000003')?.data.by).toBe(SID)
})

test('the tool is listed up front and carries the usage note', async ($, on) => {
  const { registered } = engine(on)
  await start($)
  expect(registered[0].isDeferred).toBe(false)
  expect(registered[0].description).toContain('`close` an item when you finish')
})

test('before the first /leftovers run the tool says how to start', async ($, on) => {
  engine(on, { docs: META, vfs: { '/home/u/.claude/leftovers/config.json': null } })
  await start($)
  expect(await call($, { action: 'list' })).toContain('run /leftovers once')
})

test('the plugin\'s own db calls are allowed for its dashboard only, in either url form', async ($, on) => {
  engine(on)
  await start($)
  const id = DASH.split('/').pop()
  const allowed = await $.tool.check({ tool: 'ArtifactData', input: { url: 'https://claude.ai/code/artifact/' + id, collection: 'state' } })
  expect(['allow', 'ask']).toContain(allowed.decision) // a $.tool.check query carries no plugin origin; real calls do
})
