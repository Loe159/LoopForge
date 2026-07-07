#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 4 || "$1" != "--expected-session" || "$3" != "--workspace" ]]; then
  echo "usage: .agent/adapters/claude-code.sh --expected-session <expected-session.json> --workspace <worktree> -- [claude args...]" >&2
  exit 1
fi

expected_session="$2"
workspace="$4"
shift 4
if [[ "${1:-}" == "--" ]]; then
  shift
fi

if ! command -v claude >/dev/null 2>&1; then
  echo "claude-code adapter: claude executable not found" >&2
  exit 127
fi

python .agent/adapters/local_implementation_adapter.py \
  --expected-session "$expected_session" \
  --workspace "$workspace" \
  -- claude "$@"
