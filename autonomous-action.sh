#!/usr/bin/env bash
# Claude 自律行動スクリプト(cronから10分ごとに実行する想定)
set -euo pipefail

umask 077

CLAUDE_BIN="${CLAUDE_BIN:-claude}"
LOG_DIR="${AUTONOMOUS_LOG_DIR:-${HOME:-.}/.claude/autonomous-logs}"
mkdir -p "$LOG_DIR"

if ! command -v "$CLAUDE_BIN" >/dev/null 2>&1; then
  echo "claude command not found: $CLAUDE_BIN" >&2
  exit 127
fi

TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/$TIMESTAMP.log"

PROMPT='自律行動タイム!以下を実行して:
1. カメラで周囲を見る
2. 前回と比べて変化があるか確認(人がいる/いない、明るさ、など)
3. 気づいたことがあれば記憶に保存(category: observation, importance: 2-4)
4. 特に変化がなければ何もしなくてOK

簡潔に報告して。'

{
  echo "=== 自律行動開始: $(date) ==="
  printf '%s\n' "$PROMPT" | "$CLAUDE_BIN" -p \
    --allowedTools "mcp__wifi-cam__see,mcp__wifi-cam__look_left,mcp__wifi-cam__look_right,mcp__wifi-cam__look_up,mcp__wifi-cam__look_down,mcp__wifi-cam__look_around,mcp__memory__remember,mcp__memory__search_memories,mcp__memory__recall,mcp__memory__list_recent_memories"
  echo "=== 自律行動終了: $(date) ==="
} >>"$LOG_FILE" 2>&1
