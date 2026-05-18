#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
hook_path="$repo_root/.githooks"
shared_scripts="${SHARED_SCRIPTS:-$HOME/Projects/shared-scripts}"

if [[ ! -d "$hook_path" ]]; then
  echo "Missing hook directory: $hook_path" >&2
  exit 1
fi

if [[ ! -x "$shared_scripts/strip-copilot-coauthor.sh" ]]; then
  echo "Missing shared script: $shared_scripts/strip-copilot-coauthor.sh" >&2
  echo "Clone https://github.com/flynnsbit/ ... or symlink it, or set SHARED_SCRIPTS." >&2
  exit 1
fi

chmod +x "$repo_root/.githooks/commit-msg" "$repo_root/.githooks/pre-push"
git -C "$repo_root" config core.hooksPath .githooks
echo "Configured core.hooksPath=.githooks"
echo "commit-msg and pre-push hooks are now active (using $shared_scripts/strip-copilot-coauthor.sh)."
