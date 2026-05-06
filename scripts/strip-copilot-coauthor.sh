#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  strip-copilot-coauthor.sh --from-pre-push
  strip-copilot-coauthor.sh --range <git-range> [--apply] [--dry-run]

Notes:
  - Removes "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>" trailer lines.
  - In pre-push mode, rewrites outgoing commit messages when needed and aborts push once rewritten.
EOF
}

trailer_regex='^[[:space:]]*[Cc]o-?[Aa]uthored[ -]by:[[:space:]]*[Cc]opilot[[:space:]]*<223556219\+Copilot@users\.noreply\.github\.com>[[:space:]]*$'

has_copilot_trailer() {
  local message="$1"
  printf '%s\n' "$message" | grep -Eiq "$trailer_regex"
}

range_commits() {
  local range="$1"
  if [[ "$range" == *".."* || "$range" == *"..."* ]]; then
    git rev-list --reverse "$range"
  else
    git rev-list --reverse "${range}^!"
  fi
}

range_has_trailer() {
  local range="$1"
  local commit_sha message
  while read -r commit_sha; do
    [[ -n "${commit_sha:-}" ]] || continue
    message="$(git log -1 --pretty=%B "$commit_sha")"
    if has_copilot_trailer "$message"; then
      return 0
    fi
  done < <(range_commits "$range")
  return 1
}

rewrite_range() {
  local range="$1"
  git filter-branch -f --msg-filter "sed -E '/$trailer_regex/d'" "$range" >/dev/null 2>&1
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
  rewritten=0
  while read -r local_ref local_sha remote_ref remote_sha; do
    [[ -n "${local_ref:-}" ]] || continue
    [[ "$local_sha" != "0000000000000000000000000000000000000000" ]] || continue

    if [[ "$remote_sha" == "0000000000000000000000000000000000000000" ]]; then
      commit_range="${local_sha}^!"
    elif git cat-file -e "${remote_sha}^{commit}" 2>/dev/null; then
      commit_range="$remote_sha..$local_sha"
    else
      # Remote tip may be newer than local refs if user has not fetched.
      commit_range="${local_sha}^!"
    fi

    if ! range_has_trailer "$commit_range"; then
      continue
    fi

    if [[ $apply_mode -eq 1 ]]; then
      rewrite_range "$commit_range"
      rewritten=1
      echo "Rewrote commit messages in range $commit_range to remove Copilot co-author trailer."
    else
      echo "Would rewrite commit messages in range $commit_range."
    fi
  done || true

  if [[ $rewritten -eq 1 ]]; then
    echo "Push aborted after rewriting commit messages. Re-run 'git push' now." >&2
    exit 1
  fi
  exit 0
fi

if [[ -z "$range" ]]; then
  range="HEAD"
fi

if ! range_has_trailer "$range"; then
  echo "No Copilot co-author trailer found in range: $range"
  exit 0
fi

if [[ $apply_mode -eq 1 ]]; then
  rewrite_range "$range"
  echo "Rewrote commit messages in range: $range"
else
  echo "Would rewrite commit messages in range: $range"
fi

if [[ $dry_run -eq 1 ]]; then
  echo "Dry-run complete."
fi
