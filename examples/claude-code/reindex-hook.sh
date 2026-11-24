#!/usr/bin/env bash
# PostToolUse hook (matcher Write|Edit): if the just-written file matches a
# sources or code_globs entry in sources.yaml, reindex it incrementally in the
# background. Silent on non-matches. Never blocks or errors out.
#
# Thin wrapper: the logic lives in `sqlrecall-autohook reindex` (Python, so the
# same hook works on macOS, Linux and Windows). On Windows, or anywhere without
# bash, point the hook straight at `sqlrecall-autohook reindex` instead; see
# examples/claude-code/recall-hooks.json.
command -v sqlrecall-autohook >/dev/null 2>&1 || exit 0
exec sqlrecall-autohook reindex
