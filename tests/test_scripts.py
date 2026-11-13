"""Checks of the parts that decide what reaches git argv and the page's links. Run: python3 tests/test_scripts.py"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "skills", "leftovers", "scripts"))
sys.argv = ["evidence.py", "/nonexistent"]
import evidence as ev  # noqa: E402
import common  # noqa: E402
import re  # noqa: E402


def test_origin_parsing():
    assert ev.parse_origin("git@github.com:alice/tool.git") == ("github.com", "alice", "tool")
    assert ev.parse_origin("https://bob:s3cret@bitbucket.org/team/repo.git") == ("bitbucket.org", "team", "repo")  # no credentials kept
    assert ev.parse_origin("ssh://git@github.com:22/alice/tool") == ("github.com", "alice", "tool")
    assert ev.parse_origin("git@ssh.bitbucket.org:team/repo.git") == ("bitbucket.org", "team", "repo")
    assert ev.parse_origin("ssh://git@ssh.github.com:443/alice/tool.git") == ("github.com", "alice", "tool")
    assert ev.parse_origin("git@github-work:alice/tool.git") is None  # ssh host alias: unknown host
    assert ev.parse_origin("https://gitlab.com/a/b.git") is None
    assert ev.parse_origin("git@github.com:-o/x.git") is None  # owner must be a plain name


def test_pr_urls_and_refs():
    assert ev.pr_url(("github.com", "a", "r"), "12") == "https://github.com/a/r/pull/12"
    assert ev.pr_url(("bitbucket.org", "w", "r"), "7") == "https://bitbucket.org/w/r/pull-requests/7"
    assert ev.clean({"repo": "r", "branch": "--upload-pack=x", "pr": "12", "commit": "zz"}) == {"repo": "r", "pr": "12"}
    src = open(os.path.join(os.path.dirname(__file__), "..", "skills", "leftovers", "scripts", "build_seed.py")).read()
    pr_url = re.compile(re.search(r'PR_URL = re.compile\(r"(.+?)"\)', src).group(1))
    assert pr_url.match("https://github.com/a/r/pull/12") and not pr_url.match("javascript:alert(1)//https://github.com/a/r/pull/1")


def test_scrub():
    for token in ["github_pat_" + "A" * 40, "glpat-" + "b" * 20, "ghp_" + "c" * 36]:
        assert common.scrub(f"key {token} here") == "key [REDACTED] here", token


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"): fn(); print("ok", name)
