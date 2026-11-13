"""Merge fresh extractions with the previous dashboard data.

Usage: merge.py WORK
Reads WORK/prev/meta/{sessions,items}.json and WORK/prev/state/*.json (the
dashboard db), WORK/cond/index.json and WORK/out_*.json (extractions).
Writes WORK/merged.json and WORK/group_<repo>.json files for verification.

Rules:
- changed session with an extraction: its items are replaced; an item that
  carries `keep_id` of a previous item of the same session, or the same
  normalized text, keeps that id;
  previous items ticked done or dismissed but not carried over stay as they are.
- changed session without an extraction: previous data kept, reported.
- session out of the window: kept while it has an item still open.
- live items (WORK/prev/live/*.json, added by sessions through the mod) of a
  re-extracted session are folded in: matched through keep_id, or carried
  over as they are; merged.json lists those sessions in `live_absorbed`.
- `verify` marks items of re-extracted sessions without a verdict, and items
  with refs or an 'open' verdict whose last check is older than 20 hours.
"""
import collections, datetime, glob, json, os, re, sys
from common import dump, load, parse_ts, project, scrub

work = sys.argv[1]
# Items of unchanged sessions are re-checked against git at most this often.
recheck_before = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=20)
prev_s = (load(os.path.join(work, "prev/meta/sessions.json")) or {}).get("sessions", [])
prev_i = (load(os.path.join(work, "prev/meta/items.json")) or {}).get("items", [])
states = {os.path.basename(f)[:-5]: (load(f) or {}).get("state") for f in glob.glob(os.path.join(work, "prev/state/*.json"))}
idx = {i["id"]: i for i in load(os.path.join(work, "cond/index.json"))}
prev_sess = {s["id"]: s for s in prev_s}
prev_items = collections.defaultdict(list)
for i in prev_i: prev_items[i["session_id"]].append(i)
# Items a session added itself through the leftovers mod since the last scan.
live_items = collections.defaultdict(list)
for f in glob.glob(os.path.join(work, "prev/live/*.json")):
    d = load(f) or {}
    for i in d.get("items", []):
        live_items[d.get("session_id", "")].append({**i, "session_id": d.get("session_id", ""), "live": True})

outs = {}
for f in sorted(glob.glob(os.path.join(work, "out_*.json"))):
    for s in load(f): outs.setdefault(s["session_id"], s)


def effective(i):
    st = states.get(i["id"])
    if st: return st
    return {"done": "done", "duplicate": "dismissed"}.get((i.get("check") or {}).get("status"), "open")


def norm(text):
    return " ".join(text.lower().split())


def new_id(sid, text):
    """sid8 + FNV-1a of the normalized text: the same scheme as the leftovers mod."""
    h = 0x811c9dc5
    for ch in norm(text):
        h = ((h ^ ord(ch)) * 0x01000193) & 0xffffffff
    return f"{sid[:8]}-{h:08x}"


sessions, items, missing, fresh, absorbed = [], [], [], set(), []
for sid, ix in idx.items():
    s = outs.get(sid) if ix["changed"] else None
    if s is None:
        if ix["changed"]: missing.append(sid)
        if sid in prev_sess:
            sessions.append(prev_sess[sid]); items += prev_items[sid]
        continue
    fresh.add(sid)
    its = s.get("items") or []
    status = s.get("status", "open")
    if its and status == "done": status = "open"
    if not its: status = "done"
    sessions.append({"id": sid, "title": scrub(s.get("title") or ix["title"] or sid[:8]), "project": project(ix["cwd"]),
                     "branch": s.get("branch") or ix["branch"] or "", "cwd": ix["cwd"] or "", "last_activity": ix["end"],
                     "status": status, "summary": scrub(s.get("summary", ""))})
    old = {i["id"]: i for i in prev_items[sid] + live_items[sid]}
    by_text = {norm(i["text"]): i["id"] for i in old.values()}
    seen = set()
    for n, it in enumerate(its):
        iid = it.get("keep_id") if it.get("keep_id") in old else by_text.get(norm(it["text"])) or new_id(sid, it["text"])
        if iid in seen: iid = new_id(sid, it["text"] + f" #{n}")
        if iid in seen: continue
        seen.add(iid)
        item = {"id": iid, "session_id": sid, "order": n, "text": scrub(it["text"]), "detail": scrub(it.get("detail", "")),
                "kind": it.get("kind", ""), "priority": it.get("priority") if it.get("priority") in ("high", "medium", "low") else "medium",
                "refs": it.get("refs") or {}}
        if iid in old and old[iid].get("check"): item["check"] = old[iid]["check"]
        items.append(item)
    # A ticked or dismissed item the extractor did not carry over stays, so the tick is never lost;
    # so does an open item the session added live, which only the session or the user closes.
    for iid, i in old.items():
        if iid in seen or (effective(i) == "open" and not i.get("live")): continue
        items.append({k: v for k, v in i.items() if k != "live"})
    if live_items[sid]: absorbed.append(sid)

# Sessions that left the window stay while something is still open.
for sid, s in prev_sess.items():
    if sid in idx: continue
    if any(effective(i) == "open" for i in prev_items[sid]):
        sessions.append(s); items += prev_items[sid]

# Group by repo for verification; `verify` marks the items worth re-checking.
groups = collections.defaultdict(lambda: {"sessions": [], "items": []})
by_sid = {s["id"]: s for s in sessions}
for i in items:
    s = by_sid[i["session_id"]]
    key = (i.get("refs") or {}).get("repo") or os.path.basename((s.get("cwd") or "other").rstrip("/")) or "other"
    # the key becomes a file name and comes from model output: plain characters only, no leading dot
    key = re.sub(r"[^\w.-]", "_", str(key)).lstrip(".") or "other"
    c = i.get("check") or {}
    chk = c.get("status")
    checked = parse_ts(c.get("at"))
    stale = checked is None or checked < recheck_before
    i["verify"] = effective(i) == "open" and chk not in ("done", "duplicate") and (
        (i["session_id"] in fresh and "check" not in i) or ((bool(i.get("refs")) or chk == "open") and stale))
    g = groups[key]
    g["items"].append(i)
    if s not in g["sessions"]: g["sessions"].append(s)
for f in glob.glob(os.path.join(work, "group_*.json")): os.remove(f)
for k, g in groups.items():
    if any(i["verify"] for i in g["items"]): dump(g, os.path.join(work, f"group_{k}.json"))

dump({"sessions": sessions, "items": items, "fresh": sorted(fresh), "missing": missing, "live_absorbed": absorbed}, os.path.join(work, "merged.json"))
print(f"{len(sessions)} sessions, {len(items)} items, {len(fresh)} re-extracted, {sum(i['verify'] for i in items)} to verify")
if missing: print("WARNING extraction missing, kept previous data:", " ".join(m[:8] for m in missing))
for k, g in sorted(groups.items()):
    n = sum(i["verify"] for i in g["items"])
    if n: print(f"  group_{k}: {n} to verify of {len(g['items'])}")
