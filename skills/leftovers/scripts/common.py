"""Shared helpers for the leftovers scripts."""
import datetime, json, os, re

HOME = os.path.expanduser("~")
STATE_DIR = os.path.join(HOME, ".claude/leftovers")  # survives plugin updates (the plugin dir does not)
CONFIG = os.path.join(STATE_DIR, "config.json")  # {"artifact_url": ...}, written by the first /leftovers run
WINDOW_DAYS = 14


def artifact_url():
    """The dashboard this scan writes to, or None before the first run created it."""
    return (load(CONFIG) or {}).get("artifact_url")

# Token shapes that must never reach the dashboard.
SECRET = re.compile(
    r"(?i)(\b(?:sq[apu]_[0-9a-z]{30,}|gh[pousr]_[0-9a-z]{30,}|github_pat_\w{30,}|glpat-[\w-]{20,}|xox[abpr]-[0-9a-z-]{10,}|AKIA[0-9A-Z]{16}|eyJ[\w-]{10,}\.[\w-]{10,}\.[\w-]{10,}"
    r"|AT(?:ATT|BB|CTT)[\w=-]{20,}|sk-(?:ant-)?[\w-]{20,})|-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$))"
    r"|((?:token|secret|password|passwd|pwd|api[_-]?key|authorization|access[_-]?key)[\"']?\s*[:=]\s*(?:bearer\s+)?[\"']?)([^\s\"'`]{6,})"
    r"|(:-)([0-9a-f]{32,64})\}"
    r"|(://[^/\s:@]+:)([^/\s@]+)(?=@)")


def scrub(text):
    def rep(m):
        if m.group(1): return "[REDACTED]"
        if m.group(2): return m.group(2) + "[REDACTED]"
        if m.group(4): return m.group(4) + "[REDACTED]}"
        return m.group(6) + "[REDACTED]"
    return SECRET.sub(rep, text)


def parse_ts(s):
    """ISO timestamp ('...Z' or '+00:00') to aware datetime; None if empty."""
    if not s: return None
    return datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def load(path, default=None):
    try:
        with open(path) as f: return json.load(f)
    except FileNotFoundError:
        return default


def dump(obj, path):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f: json.dump(obj, f, indent=1)


def project(cwd):
    """A session's project: the name of the folder it ran in (~/.claude is "claude config")."""
    path = (cwd or "").rstrip("/")
    if path == os.path.join(HOME, ".claude"): return "claude config"
    return os.path.basename(path) or "other"
