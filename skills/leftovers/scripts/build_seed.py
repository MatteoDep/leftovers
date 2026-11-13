"""Build the dashboard documents from merged.json and verify_*.json.

Usage: build_seed.py WORK --scan-start ISO
Writes WORK/meta_sessions.json, WORK/meta_items.json, WORK/live_delete.json
(live docs now folded into meta/items) and WORK/last_scan.json,
which is copied to ~/.claude/leftovers/ only after the dashboard write
succeeded. State docs (the user's ticks) are never deleted.
"""
import argparse, collections, glob, os, re
from common import WINDOW_DAYS, artifact_url, dump, load, now_iso, scrub

# the page turns refs.url into a link: only plain PR pages of the two supported hosts get through
PR_URL = re.compile(r"^https://(?:github\.com/[\w.-]+/[\w.-]+/pull|bitbucket\.org/[\w.-]+/[\w.-]+/pull-requests)/\d{1,6}$")

ap = argparse.ArgumentParser()
ap.add_argument("work"); ap.add_argument("--scan-start", required=True)
a = ap.parse_args()
m = load(os.path.join(a.work, "merged.json"))
chk = {}
for f in glob.glob(os.path.join(a.work, "verify_*.json")): chk.update(load(f))
urls = load(os.path.join(a.work, "pr_urls.json")) or {}
at = now_iso()
unchecked = []
for i in m["items"]:
    c = chk.get(i["id"])
    if c and c.get("status") in ("done", "open", "duplicate", "unknown"):
        i["check"] = {"status": c["status"], "note": scrub(c.get("note") or "")[:160], "at": at}
    elif i.get("verify"):
        unchecked.append(i["id"])
    i.pop("verify", None); i.pop("evidence", None)
    refs = dict(i.get("refs") or {})
    url = urls.get(i["id"]) or refs.pop("url", None)
    if url and PR_URL.match(url): refs["url"] = url
    if refs: i["refs"] = refs
items = m["items"]
dump({"scanned_at": a.scan_start, "window_days": WINDOW_DAYS, "sessions": m["sessions"]}, os.path.join(a.work, "meta_sessions.json"))
dump({"items": items}, os.path.join(a.work, "meta_items.json"))
dump(m.get("live_absorbed", []), os.path.join(a.work, "live_delete.json"))
dump({"scanned_at": a.scan_start, "artifact_url": artifact_url()}, os.path.join(a.work, "last_scan.json"))

size = os.path.getsize(os.path.join(a.work, "meta_items.json"))
print(f"{len(m['sessions'])} sessions, {len(items)} items, meta_items {size // 1024} KB")
print("checks:", dict(collections.Counter((i.get("check") or {}).get("status", "none") for i in items)))
if unchecked: print("WARNING no verdict for:", " ".join(unchecked))
for i in items:
    if i["session_id"] in m["fresh"]: print(f"  new/updated  {i['priority']:6} {i['id']} {i['text'][:80]}")
for i in items:
    c = i.get("check") or {}
    if c.get("at") == at and c["status"] in ("done", "duplicate"): print(f"  {c['status']:9} {i['id']} {i['text'][:60]} | {c['note']}")
