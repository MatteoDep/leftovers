"""Condense recent Claude Code transcripts for leftover extraction.

Usage: condense.py WORK --exclude SID
A session is changed when it is not on the dashboard yet (WORK/prev/meta/
sessions.json) or has activity after the last_activity recorded there.
Writes WORK/cond/<sid>.txt for changed sessions and WORK/cond/index.json
listing every in-window session with a `changed` flag.
"""
import argparse, glob, json, os, re, time
from common import WINDOW_DAYS, scrub, parse_ts, dump, load

ap = argparse.ArgumentParser()
ap.add_argument("work"); ap.add_argument("--exclude", default="")
args = ap.parse_args()
out = os.path.join(args.work, "cond"); os.makedirs(out, exist_ok=True)
prev_end = {x["id"]: parse_ts(x.get("last_activity")) for x in (load(os.path.join(args.work, "prev/meta/sessions.json")) or {}).get("sessions", [])}
exclude = set(filter(None, args.exclude.split(",")))
now = time.time()
cutoff = parse_ts(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - WINDOW_DAYS * 86400)))
HEAD, TAIL, MSG = 25000, 175000, 8000
ASK_IDS = set()
ARGS = re.compile(r"<command-name>(.*?)</command-name>.*?<command-args>(.*?)</command-args>", re.S)
SKIP = ("<local-command", "<system-reminder>", "<task-notification>", "<bash-input>", "<bash-stdout>", "<bash-stderr>", "[Request interrupted")


def clip(t):
    return t if len(t) <= MSG else t[:MSG - 2000] + "\n[...]\n" + t[-2000:]


def blocks(e):
    t = e.get("type"); c = e.get("message", {}).get("content")
    if t == "system":
        if e.get("subtype") == "away_summary": return [("RECAP", str(e.get("content", "")).replace("(disable recaps in /config)", "").strip())]
        return []
    if t == "attachment":
        a = e.get("attachment") or {}
        if a.get("type") == "queued_command" and (a.get("origin") or {}).get("kind") == "human":
            pr = a.get("prompt", "")
            if isinstance(pr, list): pr = " ".join(x.get("text", "") for x in pr if isinstance(x, dict) and x.get("type") == "text")
            return [("USER (queued while Claude worked)", str(pr))]
        return []
    if t == "user" and e.get("isCompactSummary"):
        return [("COMPACT SUMMARY (written by Claude, not the user)", (c if isinstance(c, str) else json.dumps(c))[:20000])]
    if t not in ("user", "assistant"): return []
    res = []
    for p in ([{"type": "text", "text": c}] if isinstance(c, str) else c or []):
        if not isinstance(p, dict): continue
        if p.get("type") == "text":
            x = p["text"]
            if "<command-name>" in x[:300]:
                m = ARGS.search(x)
                if m and m.group(2).strip(): res.append(("USER" if t == "user" else "CLAUDE", f"{m.group(1)} {m.group(2).strip()}"))
                continue
            if x.startswith(SKIP): continue
            res.append(("USER" if t == "user" else "CLAUDE", x))
        elif p.get("type") == "tool_use":
            n, inp = p.get("name"), p.get("input") or {}
            if n == "AskUserQuestion":
                ASK_IDS.add(p.get("id"))
                qs = "; ".join(q.get("question", "") + " [" + " | ".join(o.get("label", "") for o in q.get("options", [])) + "]" for q in inp.get("questions", []))
                res.append(("CLAUDE asked the user", qs))
            elif n in ("TodoWrite", "TaskCreate", "TaskUpdate", "ExitPlanMode"):
                res.append(("CLAUDE " + n, json.dumps(inp)[:3000]))
        elif p.get("type") == "tool_result":
            rc = p.get("content"); rs = rc if isinstance(rc, str) else " ".join(x.get("text", "") for x in rc or [] if isinstance(x, dict))
            if p.get("tool_use_id") in ASK_IDS and "doesn't want to proceed" not in rs: res.append(("USER answered", rs[:2000]))
            elif "doesn't want to proceed with this tool use" in rs:
                why = rs.split("the user said:", 1)[1].strip() if "the user said:" in rs else ""
                res.append(("USER rejected a tool call" + (" and said" if why else ""), why[:2000]))
    return [(r, x.strip()) for r, x in res if x.strip() or r.startswith("USER rejected")]


idx = []
for f in glob.glob(os.path.expanduser("~/.claude/projects/*/*.jsonl")):
    sid = os.path.basename(f)[:-6]
    if os.path.getmtime(f) < now - WINDOW_DAYS * 86400 or sid in exclude: continue
    ai_title = custom_title = cwd = branch = first_ts = last_ts = None
    lines = []
    for raw in open(f, errors="replace"):
        try: e = json.loads(raw)
        except Exception: continue
        t = e.get("type")
        if t == "ai-title": ai_title = e.get("aiTitle") or ai_title
        if t == "custom-title": custom_title = e.get("customTitle") or custom_title
        if e.get("isSidechain") or (e.get("isMeta") and not e.get("isCompactSummary")): continue
        b = blocks(e)
        if not b: continue
        ts = e.get("timestamp")
        if t in ("user", "assistant", "attachment"):
            cwd = e.get("cwd") or cwd; branch = e.get("gitBranch") or branch
            first_ts = first_ts or ts; last_ts = ts or last_ts
        for role, txt in b: lines.append(f"--- {role} {ts or ''}\n{clip(txt)}")
    end = parse_ts(last_ts)
    if not lines or not end or end < cutoff: continue
    changed = prev_end.get(sid) is None or end > prev_end[sid]
    title = custom_title or ai_title
    if changed:
        body = "\n".join(lines)
        if len(body) > HEAD + TAIL: body = body[:HEAD] + f"\n\n[... {len(body) - HEAD - TAIL} chars of the middle omitted ...]\n\n" + body[-TAIL:]
        with open(os.path.join(out, sid + ".txt"), "w") as fh:
            fh.write(scrub(f"SESSION {sid}\nTITLE {title}\nCWD {cwd}\nBRANCH {branch}\nSTART {first_ts}\nEND {last_ts}\n\n{body}"))
    idx.append({"id": sid, "title": title, "cwd": cwd, "branch": branch, "start": first_ts, "end": last_ts, "changed": changed})
idx.sort(key=lambda x: x["end"], reverse=True)
dump(idx, os.path.join(out, "index.json"))
print(f"{len(idx)} sessions in window, {sum(i['changed'] for i in idx)} changed")
for i in idx:
    if i["changed"]: print(" ", i["end"][:16], i["id"][:8], (i["cwd"] or "").replace(os.path.expanduser("~"), "~"), "|", i["title"])
