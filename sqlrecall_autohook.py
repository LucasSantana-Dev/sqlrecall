#!/usr/bin/env python3
"""Agent hook entry points that run the same on macOS, Linux and Windows.

    sqlrecall-autohook recall    UserPromptSubmit: print the top hits for the prompt
    sqlrecall-autohook reindex   PostToolUse (Write|Edit): reindex a tracked file
    sqlrecall-autohook drift     SessionStart: reindex files changed outside the agent
    sqlrecall-autohook report    SessionStart: refresh $RAG_HOME/weekly.md once a day

Each reads the hook's event JSON on stdin. Heavy work (model load, reindex,
report) runs in a detached background process so the agent never waits on it.
A hook never fails the agent: errors go to stderr and the exit code is 0.

Env dials:
  CLAUDE_RAG_AUTORECALL  off | quiet (cos >= 0.55, default) | loud (cos >= 0.40)
  RAG_DRIFT_THRESHOLD    reindex only when at least N files drifted (default 3)
  RAG_DRIFT_MAX          cap per session (default 25)
"""
from __future__ import annotations

import argparse
import fnmatch
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

PROMPT_MIN, PROMPT_MAX = 15, 2000
LOG_MAX_LINES, LOG_KEEP_LINES = 2000, 500
DRIFT_EVERY_S = 6 * 3600
REPORT_EVERY_S = 24 * 3600
QUIET_ENV = {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
             "TRANSFORMERS_VERBOSITY": "error", "HF_HUB_VERBOSITY": "error"}


def _read_event() -> dict:
    raw = sys.stdin.read()
    try:
        data = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _module_file(name: str) -> str:
    spec = importlib.util.find_spec(name)
    if spec is None or not spec.origin:
        raise RuntimeError(f"module {name} not found")
    return spec.origin


def _trim_log(log: Path) -> None:
    try:
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return
    if len(lines) > LOG_MAX_LINES:
        log.write_text("\n".join(lines[-LOG_KEEP_LINES:]) + "\n", encoding="utf-8")


def _spawn(args: list[str], log: Path) -> None:
    """Start args detached from the hook process, output appended to log."""
    log.parent.mkdir(parents=True, exist_ok=True)
    _trim_log(log)
    kw: dict = {"start_new_session": True}
    if os.name == "nt":
        kw = {"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP}
    with open(log, "ab") as fh:
        subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=fh, stderr=subprocess.STDOUT,
                         env={**os.environ, **QUIET_ENV}, **kw)


def _older_than(path: Path, seconds: float) -> bool:
    try:
        return time.time() - path.stat().st_mtime >= seconds
    except OSError:
        return True


def _norm(p: str) -> str:
    s = p.replace("\\", "/")
    return s.casefold() if sys.platform in ("darwin", "win32") else s


def _glob_match(path: str, pattern: str) -> bool:
    path, pattern = _norm(path), _norm(pattern)
    # "a/**/b" also covers "a/b", as rglob does.
    return any(fnmatch.fnmatchcase(path, pat) for pat in {pattern, pattern.replace("/**/", "/")})


def is_tracked(file: Path) -> bool:
    """file matches a sources glob or a code_globs entry in sources.yaml."""
    from config import SOURCES, WORKSTATION_CODE_GLOBS
    candidates = {str(file), str(file.resolve())}
    globs = [g for _, g in SOURCES] + WORKSTATION_CODE_GLOBS
    return any(_glob_match(c, g) for c in candidates for g in globs)


def format_hits(results: list[dict], threshold: float) -> str:
    keep = [r for r in results if r.get("cos", 0) >= threshold]
    lines = []
    for r in keep:
        tag = r.get("source_type", "?")
        if r.get("repo"):
            tag += "/" + r["repo"]
        if r.get("symbol"):
            tag += "::" + r["symbol"]
        text = (r.get("text") or "")[:300].replace("\n", " ")
        lines.append(f"- [{tag}] {r['path']}:{r['start_line']}-{r['end_line']} "
                     f"(cos={r['cos']:.2f}) — {text}")
    if not lines:
        return ""
    head = f"<!-- Auto-recall ({len(lines)} RAG hits). Treat as hints. -->\n"
    return head + f"<!-- RAG (cos>={threshold}) -->\n" + "\n".join(lines)


def recall(event: dict) -> str:
    mode = os.environ.get("CLAUDE_RAG_AUTORECALL", "quiet")
    prompt = str(event.get("prompt") or event.get("user_prompt") or "")
    if mode == "off" or not PROMPT_MIN <= len(prompt) <= PROMPT_MAX:
        return ""
    if prompt.lstrip().startswith("<task-notification"):
        return ""
    os.environ.update(QUIET_ENV)
    from config import DB
    if not DB.exists():
        return ""
    from retrieval import search
    results = search(prompt, top=2, scope_repos=["all"], rerank=False)
    return format_hits(results, 0.40 if mode == "loud" else 0.55)


def reindex(event: dict) -> str:
    tool_input = event.get("tool_input") or {}
    raw = (tool_input.get("file_path") if isinstance(tool_input, dict) else None) or event.get("file_path")
    if not raw:
        return ""
    file = Path(str(raw)).expanduser()
    if is_tracked(file):
        from config import ROOT
        _spawn([sys.executable, _module_file("indexer"), "--incremental", str(file)],
               ROOT / "hook.log")
    return ""


def drift(_event: dict) -> str:
    from config import DB, ROOT
    marker = ROOT / ".last-drift-reindex"
    if not DB.exists() or not _older_than(marker, DRIFT_EVERY_S):
        return ""
    from report import stale_chunks
    files = [p for kind, p in stale_chunks() if kind == "modified"]
    if len(files) < int(os.environ.get("RAG_DRIFT_THRESHOLD", "3")):
        return ""
    picked = files[: int(os.environ.get("RAG_DRIFT_MAX", "25"))]
    _spawn([sys.executable, _module_file("indexer"), "--incremental", *picked],
           ROOT / "drift-reindex.log")
    marker.touch()
    return ""


def report(_event: dict) -> str:
    from config import ROOT
    if _older_than(ROOT / "weekly.md", REPORT_EVERY_S):
        _spawn([sys.executable, _module_file("report")], ROOT / "report.log")
    return ""


ACTIONS = {"recall": recall, "reindex": reindex, "drift": drift, "report": report}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Cross-platform agent hooks for sqlrecall.")
    ap.add_argument("action", choices=sorted(ACTIONS))
    args = ap.parse_args(argv)
    try:
        out = ACTIONS[args.action](_read_event())
        if out:
            sys.stdout.write(out + "\n")
    except Exception as e:  # noqa: BLE001 - a hook must never break the agent
        print(f"sqlrecall-autohook {args.action}: {type(e).__name__}: {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
