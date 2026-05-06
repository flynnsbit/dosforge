#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
hook_path="$repo_root/.githooks"

if [[ ! -d "$hook_path" ]]; then
  echo "Missing hook directory: $hook_path" >&2
  exit 1
fi

chmod +x "$repo_root/.githooks/pre-push" "$repo_root/scripts/strip-copilot-coauthor.sh"
git -C "$repo_root" config core.hooksPath .githooks
echo "Configured core.hooksPath=.githooks"
echo "Pre-push hook is now active."
