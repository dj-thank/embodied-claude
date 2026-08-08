#!/usr/bin/env bash
set -uo pipefail

umask 077

ACTION_POLICY_DIR="${1:-}"
if [[ -z "$ACTION_POLICY_DIR" && -n "${CLAUDE_PROJECT_DIR:-}" ]]; then
  ACTION_POLICY_DIR="$CLAUDE_PROJECT_DIR/action-policy"
fi

if [[ -z "$ACTION_POLICY_DIR" || ! -d "$ACTION_POLICY_DIR" ]]; then
  echo "action gate project directory is unavailable" >&2
  exit 2
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "action gate runtime is unavailable" >&2
  exit 2
fi

if ! output="$(
  uv run --locked --no-sync \
    --directory "$ACTION_POLICY_DIR" \
    embodied-action-gate 2>/dev/null
)"; then
  echo "action gate evaluation failed" >&2
  exit 2
fi

if [[ "$output" != '{"hookSpecificOutput":'* ]]; then
  echo "action gate returned an invalid decision" >&2
  exit 2
fi

printf '%s\n' "$output"
