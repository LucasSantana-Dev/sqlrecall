#!/usr/bin/env bash
# SessionStart hook: refresh $RAG_HOME/weekly.md once per 24h in the background.
# Query sections need telemetry (RAG_QLOG=on).
#
# Thin wrapper: the logic lives in `sqlrecall-autohook report` (Python, so the
# same hook works on macOS, Linux and Windows). On Windows, or anywhere without
# bash, point the hook straight at `sqlrecall-autohook report` instead; see
# examples/claude-code/recall-hooks.json.
command -v sqlrecall-autohook >/dev/null 2>&1 || exit 0
exec sqlrecall-autohook report
