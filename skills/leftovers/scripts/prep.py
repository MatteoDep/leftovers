"""Write WORK/prev_items/<sid>.json for changed sessions and print extraction batches.

Usage: prep.py WORK [BATCH_SIZE]
"""
import collections, glob, os, sys
from common import dump, load

work = sys.argv[1]; size = int(sys.argv[2]) if len(sys.argv) > 2 else 5
idx = load(os.path.join(work, "cond/index.json"))
states = {os.path.basename(f)[:-5]: (load(f) or {}).get("state") for f in glob.glob(os.path.join(work, "prev/state/*.json"))}
prev = collections.defaultdict(list)
for i in (load(os.path.join(work, "prev/meta/items.json")) or {}).get("items", []):
    prev[i["session_id"]].append({**{k: i.get(k) for k in ("id", "text", "detail", "kind", "priority", "refs")},
                                  "user_state": states.get(i["id"], "open")})
for f in glob.glob(os.path.join(work, "prev/live/*.json")):
    d = load(f) or {}
    for i in d.get("items", []):
        prev[d.get("session_id", "")].append({**{k: i.get(k) for k in ("id", "text", "detail", "kind", "priority")},
                                              "source": "added live by the session", "user_state": states.get(i["id"], "open")})
changed = [i["id"] for i in idx if i["changed"]]
for sid in changed:
    if prev[sid]: dump(prev[sid], os.path.join(work, "prev_items", sid + ".json"))
batches = [changed[n:n + size] for n in range(0, len(changed), size)]
dump(batches, os.path.join(work, "batches.json"))
for n, b in enumerate(batches): print(n, ",".join(b))
