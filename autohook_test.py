#!/usr/bin/env python3
"""Tests for the cross-platform agent hooks (sqlrecall_autohook.py).

No model download and no real background work: retrieval.search and
autohook._spawn are replaced, so what is under test is the hook decisions
(which prompts recall, which writes reindex, when drift and report run) and
Windows-style paths.
"""

import io
import json
import os
import shutil
import sys
import tempfile
import textwrap
import time
import types
from pathlib import Path, PureWindowsPath

TMP = Path(tempfile.mkdtemp(prefix="sqlrecall-autohook-")).resolve()
os.environ["RAG_HOME"] = str(TMP)
os.environ["RAG_SOURCES"] = str(TMP / "sources.yaml")
os.environ.pop("CLAUDE_RAG_AUTORECALL", None)
NOTES = TMP / "notes"
(NOTES / "deep").mkdir(parents=True)
(TMP / "sources.yaml").write_text(textwrap.dedent(f"""\
    sources:
      - {{type: memory, glob: "{NOTES}/**/*.md"}}
    code_globs:
      - "{TMP}/scripts/*.sh"
    """))

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sqlrecall_autohook as autohook  # noqa: E402
import indexer  # noqa: E402

SPAWNED: list[list[str]] = []
autohook._spawn = lambda args, log: SPAWNED.append(args)


def run(action: str, event: dict) -> str:
    sys.stdin = io.StringIO(json.dumps(event))
    out, sys.stdout = sys.stdout, io.StringIO()
    try:
        autohook.main([action])
        return sys.stdout.getvalue()
    finally:
        sys.stdout = out


def fake_search(hits):
    mod = types.ModuleType("retrieval")
    mod.search = lambda q, **kw: hits
    sys.modules["retrieval"] = mod


HIT = {"source_type": "memory", "repo": None, "symbol": None, "path": "/n/a.md",
       "start_line": 1, "end_line": 4, "cos": 0.7, "text": "keep a tested rollback path"}


def test_recall_prints_confident_hits_only():
    (TMP / "index.sqlite").write_bytes(b"")
    fake_search([HIT, {**HIT, "path": "/n/weak.md", "cos": 0.3}])
    out = run("recall", {"prompt": "how do we roll back a bad deploy"})
    assert "/n/a.md:1-4" in out and "weak.md" not in out, out
    assert out.startswith("<!-- Auto-recall (1 RAG hits)")


def test_recall_skips_short_off_and_notifications():
    fake_search([HIT])
    assert run("recall", {"prompt": "hi"}) == ""
    assert run("recall", {"prompt": "<task-notification> something long enough"}) == ""
    os.environ["CLAUDE_RAG_AUTORECALL"] = "off"
    try:
        assert run("recall", {"prompt": "how do we roll back a bad deploy"}) == ""
    finally:
        del os.environ["CLAUDE_RAG_AUTORECALL"]


def test_reindex_only_tracked_files():
    SPAWNED.clear()
    run("reindex", {"tool_input": {"file_path": str(NOTES / "deep" / "x.md")}})
    run("reindex", {"tool_input": {"file_path": str(NOTES / "top.md")}})
    run("reindex", {"tool_input": {"file_path": str(TMP / "scripts" / "a.sh")}})
    run("reindex", {"tool_input": {"file_path": str(TMP / "elsewhere.md")}})
    run("reindex", {"tool_input": {"file_path": str(NOTES / "x.txt")}})
    targets = [a[-1] for a in SPAWNED]
    assert len(targets) == 3, targets
    assert all(a[2] == "--incremental" for a in SPAWNED)


def test_windows_paths_match_forward_slash_globs():
    pattern = "C:/Users/dev/notes/**/*.md"
    assert autohook._glob_match(r"C:\Users\Dev\notes\memory\a.md", pattern) == (sys.platform in ("darwin", "win32"))
    assert autohook._glob_match(r"C:\Users\dev\notes\memory\a.md", pattern)
    assert not autohook._glob_match(r"C:\Users\dev\other\a.md", pattern)


def test_classify_type_on_windows_paths():
    win = PureWindowsPath(r"C:\Users\dev\notes\memory\feedback_x.md")
    assert indexer.classify_type(win) == "memory"
    skill = PureWindowsPath(r"C:\Users\dev\.claude\skills\recall\SKILL.md")
    assert indexer.classify_type(skill) == "skills"


def test_drift_threshold_and_throttle():
    SPAWNED.clear()
    report = types.ModuleType("report")
    report.stale_chunks = lambda: [("modified", f"/n/{i}.md") for i in range(5)] + [("missing", "/n/gone.md")]
    sys.modules["report"] = report
    marker = TMP / ".last-drift-reindex"
    marker.unlink(missing_ok=True)
    run("drift", {})
    assert len(SPAWNED) == 1 and "/n/gone.md" not in SPAWNED[0] and len(SPAWNED[0]) == 8, SPAWNED
    run("drift", {})
    assert len(SPAWNED) == 1, "second run inside 6h must be throttled"
    del sys.modules["report"]


def test_report_once_a_day():
    SPAWNED.clear()
    weekly = TMP / "weekly.md"
    weekly.unlink(missing_ok=True)
    run("report", {})
    weekly.write_text("fresh")
    run("report", {})
    assert len(SPAWNED) == 1, SPAWNED
    old = time.time() - 2 * 86400
    os.utime(weekly, (old, old))
    run("report", {})
    assert len(SPAWNED) == 2


def test_errors_never_break_the_agent():
    mod = types.ModuleType("retrieval")
    def boom(*a, **k):
        raise RuntimeError("index locked")
    mod.search = boom
    sys.modules["retrieval"] = mod
    assert run("recall", {"prompt": "how do we roll back a bad deploy"}) == ""
    sys.stdin = io.StringIO("not json")
    assert autohook.main(["reindex"]) == 0


if __name__ == "__main__":
    tests = [(k, v) for k, v in globals().items() if k.startswith("test_")]
    try:
        for name, fn in tests:
            fn()
            print(f"ok  {name}")
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    print(f"\n{len(tests)} passed")
