#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  strip-copilot-coauthor.sh --from-pre-push
  strip-copilot-coauthor.sh --range <git-range> [--apply] [--dry-run]

Behavior:
  - Removes Copilot co-author trailer lines from commit messages.
  - In pre-push mode, only HEAD can be auto-amended safely.
  - If HEAD is amended in pre-push mode, push is aborted so you can re-run push.
EOF
}

strip_trailer() {
  sed -E '/^[[:space:]]*[Cc]o-?[Aa]uthored[ -]by:[[:space:]]*[Cc]opilot[[:space:]]*<223556219\+Copilot@users\.noreply\.github\.com>[[:space:]]*$/d'
}

message_has_copilot_trailer() {
  local message="$1"
  printf '%s\n' "$message" | strip_trailer | cmp -s - <(printf '%s\n' "$message")
  local same=$?
  if [[ $same -eq 0 ]]; then
    return 1
  fi
  return 0
}

sanitize_commit_message() {
  local commit_sha="$1"
  local apply_mode="$2"
  local message cleaned
  message="$(git log -1 --pretty=%B "$commit_sha")"
  if ! message_has_copilot_trailer "$message"; then
    return 0
  fi

  cleaned="$(printf '%s\n' "$message" | strip_trailer)"
  if [[ "$apply_mode" == "1" ]]; then
    git commit --amend --no-verify -m "$cleaned" >/dev/null
    echo "Amended HEAD to remove Copilot co-author trailer."
  else
    echo "Would amend HEAD to remove Copilot co-author trailer."
  fi
}

pre_push_mode=0
apply_mode=0
dry_run=0
range=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --from-pre-push)
      pre_push_mode=1
      apply_mode=1
      shift
      ;;
    --range)
      range="${2:-}"
      if [[ -z "$range" ]]; then
        usage
        exit 2
      fi
      shift 2
      ;;
    --apply)
      apply_mode=1
      shift
      ;;
    --dry-run)
      dry_run=1
      apply_mode=0
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if [[ $pre_push_mode -eq 1 ]]; then
  head_sha="$(git rev-parse HEAD)"
  amended=0

  while read -r local_ref local_sha remote_ref remote_sha; do
    [[ -n "${local_ref:-}" ]] || continue
    [[ "$local_sha" != "0000000000000000000000000000000000000000" ]] || continue

    if [[ "$remote_sha" == "0000000000000000000000000000000000000000" ]]; then
      commit_range="${local_sha}^!"
    elif git cat-file -e "${remote_sha}^{commit}" 2>/dev/null; then
      commit_range="$remote_sha..$local_sha"
    else
      # Remote tip might be newer than local refs if user has not fetched yet.
      commit_range="${local_sha}^!"
    fi

    while read -r commit_sha; do
      [[ -n "${commit_sha:-}" ]] || continue
      message="$(git log -1 --pretty=%B "$commit_sha")"
      if ! message_has_copilot_trailer "$message"; then
        continue
      fi

      if [[ "$commit_sha" != "$head_sha" ]]; then
        echo "Found Copilot co-author trailer in non-HEAD commit: $commit_sha" >&2
        echo "Auto-removal is limited to HEAD in pre-push mode. Rewrite history first, then push again." >&2
        exit 1
      fi

      if [[ $amended -eq 0 ]]; then
        sanitize_commit_message "$commit_sha" "$apply_mode"
        amended=1
      fi
    done < <(git rev-list --reverse "$commit_range")
  done

  if [[ $amended -eq 1 ]]; then
    echo "Push aborted after amending HEAD. Re-run 'git push' now." >&2
    exit 1
  fi
  exit 0
fi

if [[ -z "$range" ]]; then
  range="HEAD"
fi

head_sha="$(git rev-parse HEAD)"
if [[ "$range" == *".."* || "$range" == *"..."* ]]; then
  target_commits="$(git rev-list --reverse "$range")"
else
  target_commits="$(git rev-list --reverse "${range}^!")"
fi
if [[ -z "$target_commits" ]]; then
  echo "No commits matched range: $range"
  exit 0
fi

while read -r commit_sha; do
  [[ -n "${commit_sha:-}" ]] || continue
  message="$(git log -1 --pretty=%B "$commit_sha")"
  if ! message_has_copilot_trailer "$message"; then
    continue
  fi
  if [[ "$commit_sha" != "$head_sha" ]]; then
    echo "Commit $commit_sha includes Copilot co-author trailer, but only HEAD can be auto-amended." >&2
    exit 1
  fi
  sanitize_commit_message "$commit_sha" "$apply_mode"
done <<< "$target_commits"

if [[ $dry_run -eq 1 ]]; then
  echo "Dry-run complete."
fi
