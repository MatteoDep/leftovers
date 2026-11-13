"""Collect read-only git and pull-request evidence for items to verify.

Usage: evidence.py WORK
Adds an `evidence` list to every item with `verify` in WORK/group_*.json, and writes
WORK/pr_urls.json ({item id: PR url}) for the dashboard's links.
Only read-only commands run here: git status/log/ls-remote/branch -r, and PR lookups through
`gh` (GitHub, when installed and logged in) or Bitbucket's REST API (GET only, when
BITBUCKET_EMAIL and BITBUCKET_API_TOKEN are set; BITBUCKET_USERNAME and BITBUCKET_APP_PASSWORD
are accepted too). The repository's host and
owner come from its local clone's `origin` remote; without a clone there is no PR access.
Remote-tracking refs are as of the last fetch in each repo.
"""
import base64, glob, json, os, re, shutil, subprocess, sys, urllib.request
from urllib.parse import quote
from common import HOME, dump, load

work = sys.argv[1]
ENV = {**os.environ, "GH_PROMPT_DISABLED": "1", "GIT_TERMINAL_PROMPT": "0"}  # never wait for a login prompt


def run(argv, cwd=None):
    try:
        r = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL, env=ENV)
        return (r.stdout.strip() or r.stderr.strip())[:600]
    except Exception as e:
        return f"error: {e}"


# refs come from model output over transcripts: only plain names may reach git or gh argv.
NAME = re.compile(r"^[A-Za-z0-9][\w.-]*$")
VALID = {"repo": NAME, "branch": re.compile(r"^[A-Za-z0-9][\w./-]*$"),
         "commit": re.compile(r"^[0-9a-f]{7,40}$"), "pr": re.compile(r"^[0-9]{1,6}$")}


def clean(refs):
    return {k: str(v) for k, v in (refs or {}).items() if k in VALID and VALID[k].match(str(v)) and ".." not in str(v)}


def parse_origin(url):
    """(host, owner, repo) from a remote URL, for github.com and bitbucket.org only.
    Credentials in the URL are never kept; other hosts and ssh host aliases give None."""
    host = r"(?:ssh\.)?(github\.com|bitbucket\.org)"  # ssh.<host> is the hosts' SSH endpoint, same repos
    m = (re.match(rf"^git@{host}:([^/\s]+)/([^/\s]+?)(?:\.git)?/?$", url)
         or re.match(rf"^(?:https|ssh)://(?:[^@/\s]+@)?{host}(?::\d+)?/([^/\s]+)/([^/\s]+?)(?:\.git)?/?$", url))
    if not m or not NAME.match(m.group(2)) or not NAME.match(m.group(3)): return None
    return m.group(1), m.group(2), m.group(3)


def repo_dir(repo, cwd):
    """The local clone of `repo`: the session's own folder, or ~/<any folder>/<repo>."""
    candidates = [cwd] + (glob.glob(os.path.join(HOME, "*", repo)) if repo else [])
    for d in filter(None, candidates):
        if not os.path.isdir(d): continue
        top = run(["git", "rev-parse", "--show-toplevel"], d)
        if not os.path.isabs(top): continue
        o = parse_origin(run(["git", "remote", "get-url", "origin"], top))
        if not repo or repo in (os.path.basename(top), o and o[2]):
            return top, o
    return None, None


def bitbucket_auth():
    """(user, secret): an Atlassian account email + API token, or the older username + app password."""
    env = os.environ.get
    if env("BITBUCKET_EMAIL") and env("BITBUCKET_API_TOKEN"): return env("BITBUCKET_EMAIL"), env("BITBUCKET_API_TOKEN")
    if env("BITBUCKET_USERNAME") and env("BITBUCKET_APP_PASSWORD"): return env("BITBUCKET_USERNAME"), env("BITBUCKET_APP_PASSWORD")
    return None


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # never resend the credentials to another address
        return None


def bitbucket(path):
    """A read-only Bitbucket API call; None when no credentials are set."""
    auth = bitbucket_auth()
    if not auth: return None
    req = urllib.request.Request("https://api.bitbucket.org/2.0" + path, method="GET")
    req.add_header("Authorization", "Basic " + base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode())
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=30) as r: return json.dumps(json.load(r))[:600]
    except Exception as e:
        return f"error: {e}"


def pr_url(o, n):
    host, owner, repo = o
    return f"https://github.com/{owner}/{repo}/pull/{n}" if host == "github.com" else f"https://bitbucket.org/{owner}/{repo}/pull-requests/{n}"


def pr_lookup(o, refs):
    """PR state from the host's own CLI: (evidence line or None, PR number or None)."""
    host, owner, repo = o
    if host == "github.com":
        if not shutil.which("gh"): return "PR check skipped: gh is not installed", refs.get("pr")
        if refs.get("pr"):
            return f"PR #{refs['pr']}: " + run(["gh", "pr", "view", refs["pr"], "-R", f"{owner}/{repo}", "--json", "state,title,updatedAt"]), refs["pr"]
        if refs.get("branch"):
            out = run(["gh", "pr", "list", "-R", f"{owner}/{repo}", "--head", refs["branch"], "--state", "all", "--json", "number,state,title"])
            m = re.search(r'"number":\s*(\d+)', out)
            return f"PRs from {refs['branch']}: {out}", m.group(1) if m else None
    else:
        base = f"/repositories/{owner}/{repo}/pullrequests"
        if not bitbucket_auth(): return "PR check skipped: BITBUCKET_EMAIL / BITBUCKET_API_TOKEN not set", refs.get("pr")
        if refs.get("pr"):
            return f"PR #{refs['pr']}: " + bitbucket(f"{base}/{refs['pr']}?fields=state,title,updated_on"), refs["pr"]
        if refs.get("branch"):
            q = quote(f'source.branch.name="{refs["branch"]}"')
            out = bitbucket(f"{base}?q={q}&state=OPEN&state=MERGED&state=DECLINED&fields=values.id,values.state,values.title")
            m = re.search(r'"id":\s*(\d+)', out)
            return f"PRs from {refs['branch']}: {out}", m.group(1) if m else None
    return None, refs.get("pr")


if __name__ == "__main__":
    urls = {}
    for gf in glob.glob(os.path.join(work, "group_*.json")):
        g = load(gf)
        cwd_of = {s["id"]: s.get("cwd") for s in g["sessions"]}
        for i in g["items"]:
            refs = clean(i.get("refs"))
            if not (i.get("verify") or refs.get("pr")): continue
            d, o = repo_dir(refs.get("repo"), cwd_of.get(i["session_id"]))
            ev = []
            if d and i.get("verify"):
                ev.append(f"repo dir {d}")
                st = run(["git", "status", "--short"], d)
                ev.append(f"git status --short: {len(st.splitlines())} changed paths" + (f": {st[:300]}" if st else ""))
                b = refs.get("branch")
                if b:
                    ev.append(f"ls-remote {b}: " + (run(["git", "ls-remote", "--heads", "origin", "--", b], d) or "branch NOT on origin"))
                    ev.append(f"local commits not on origin/{b}: " + (run(["git", "log", "--oneline", "--end-of-options", f"origin/{b}..{b}"], d) or "none"))
                c = refs.get("commit")
                if c:
                    ev.append(f"commit {c}: " + run(["git", "log", "--oneline", "-1", "--end-of-options", c], d))
                    ev.append(f"remote branches containing {c}: " + (run(["git", "branch", "-r", "--contains", c, "--"], d) or "none"))
            elif i.get("verify"):
                ev.append("no local clone found")
            number = refs.get("pr")
            if o and i.get("verify") and (refs.get("pr") or refs.get("branch")):
                line, number = pr_lookup(o, refs)
                if line: ev.append(line)
            elif i.get("verify") and not o and (refs.get("pr") or refs.get("branch")):
                ev.append("no PR access (no clone with a github.com or bitbucket.org origin)")
            if o and number: urls[i["id"]] = pr_url(o, number)
            if i.get("verify"): i["evidence"] = ev
        dump(g, gf)
        print(os.path.basename(gf), sum(bool(i.get("evidence")) for i in g["items"]), "items with evidence")
    dump(urls, os.path.join(work, "pr_urls.json"))
    print(len(urls), "PR links")
