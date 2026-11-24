#!/usr/bin/env bash
# SessionStart hook: detect drifted (modified-on-disk-since-indexed) files
# and kick a background incremental reindex, at most once per 6h and only
# when RAG_DRIFT_THRESHOLD (3) files drifted, capped at RAG_DRIFT_MAX (25).
# Closes the report->fix loop for files edited outside the agent (IDE, git pull).
#
# Thin wrapper: the logic lives in `sqlrecall-autohook drift` (Python, so the
# same hook works on macOS, Linux and Windows). On Windows, or anywhere without
# bash, point the hook straight at `sqlrecall-autohook drift` instead; see
# examples/claude-code/recall-hooks.json.
command -v sqlrecall-autohook >/dev/null 2>&1 || exit 0
exec sqlrecall-autohook drift
