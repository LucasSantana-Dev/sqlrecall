#!/usr/bin/env bash
# UserPromptSubmit hook: inject top sqlrecall hits for the user's prompt.
# Silent on low-confidence / short / long prompts. Never blocks.
# Env dials: CLAUDE_RAG_AUTORECALL=off|quiet (cos >= 0.55, default)|loud (cos >= 0.40).
#
# Thin wrapper: the logic lives in `sqlrecall-autohook recall` (Python, so the
# same hook works on macOS, Linux and Windows). On Windows, or anywhere without
# bash, point the hook straight at `sqlrecall-autohook recall` instead; see
# examples/claude-code/recall-hooks.json.
command -v sqlrecall-autohook >/dev/null 2>&1 || exit 0
exec sqlrecall-autohook recall
