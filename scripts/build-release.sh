#!/usr/bin/env bash
#
# build-release.sh -- assemble a runnable, source-free dosforge release.
#
# Reads the project version from pyproject.toml (PEP 621 `[project] version`),
# builds the wheel + sdist via `python -m build`, then assembles a
# self-contained release under ``releases/v<version>/`` containing:
#
#   - the wheel (preferred install artifact)
#   - the sdist (for users who want to build from source)
#   - dosassets/ tree (tracked files only — FreeDOS payload + per-mode readmes)
#   - install.sh (Arch + Ubuntu distro-aware system-dep installer + pip install)
#   - README.md (install + run instructions)
#   - SHA256SUMS (integrity manifest for the release contents)
#
# Usage:
#
#     ./scripts/build-release.sh           # build for the version in pyproject.toml
#     ./scripts/build-release.sh 0.1.0     # override the version explicitly
#
# Re-running the script for the same version overwrites the existing
# ``releases/v<version>/`` directory.

set -euo pipefail

repo_root="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$repo_root"

if [ "$#" -gt 0 ]; then
  version="$1"
else
  version="$(
    python3 - <<'PY'
import re
from pathlib import Path

text = Path("pyproject.toml").read_text(encoding="utf-8")
match = re.search(r'^\s*version\s*=\s*"([^"]+)"', text, re.MULTILINE)
if not match:
    raise SystemExit("Could not find version in pyproject.toml")
print(match.group(1))
PY
  )"
fi

if [ -z "$version" ]; then
  echo "build-release.sh: empty version — aborting." >&2
  exit 1
fi

release_dir="releases/v${version}"
echo "==> Building dosforge ${version} into ${release_dir}/"

# 1) Clean previous build artifacts and the target release dir.
echo "    Cleaning build/, dist/, ${release_dir}/"
find build dist -mindepth 1 -delete 2>/dev/null || true
if [ -d "$release_dir" ]; then
  find "$release_dir" -mindepth 1 -delete
fi
mkdir -p "$release_dir"

# 2) Build the wheel + sdist via PEP 517.
echo "    Running python -m build"
python3 -m pip install --quiet --upgrade build
python3 -m build --outdir dist >/dev/null

wheel="$(find dist -maxdepth 1 -name 'dosforge-*.whl' -print -quit)"
sdist="$(find dist -maxdepth 1 -name 'dosforge-*.tar.gz' -print -quit)"
if [ -z "$wheel" ] || [ -z "$sdist" ]; then
  echo "build-release.sh: missing wheel or sdist after build." >&2
  exit 1
fi
cp "$wheel" "$release_dir/"
cp "$sdist" "$release_dir/"

# 3) Stage dosassets/ from the tracked git tree. We use git ls-files so
#    only the open-source / readme content is shipped — gitignored install
#    media (WinWorldPC archives, .img/.7z) is intentionally left behind.
echo "    Staging dosassets/ from tracked files"
mkdir -p "$release_dir/dosassets"
git ls-files dosassets/ | while IFS= read -r path; do
  dest="$release_dir/${path}"
  mkdir -p "$(dirname -- "$dest")"
  cp "$path" "$dest"
done

# 4) Install script + README. These live under release-templates/ in the
#    repo so they can be versioned independently of the assembled output.
echo "    Copying install.sh + README"
cp release-templates/install.sh "$release_dir/install.sh"
chmod +x "$release_dir/install.sh"

# 4b) Desktop integration assets (launcher wrapper, icons, .desktop
#     template). Bundled under desktop/ in the release. install.sh
#     picks them up from there and copies them into the right XDG
#     locations on the install target.
if [ -d assets/desktop ] && [ -d assets/icons ]; then
  echo "    Staging desktop/ (launcher + icons + .desktop template)"
  mkdir -p "$release_dir/desktop/icons"
  cp assets/desktop/dosforge.desktop "$release_dir/desktop/dosforge.desktop"
  cp assets/desktop/dosforge-launcher "$release_dir/desktop/dosforge-launcher"
  chmod +x "$release_dir/desktop/dosforge-launcher"
  cp assets/icons/dosforge.svg "$release_dir/desktop/icons/dosforge.svg"
  for size in 16 24 32 48 64 128 256; do
    src="assets/icons/dosforge-${size}.png"
    [ -f "$src" ] && cp "$src" "$release_dir/desktop/icons/dosforge-${size}.png"
  done
fi

python3 - "$release_dir/README.md" "$version" <<'PY'
import sys
from pathlib import Path

target = Path(sys.argv[1])
version = sys.argv[2]
template = Path("release-templates/README.md").read_text(encoding="utf-8")
target.write_text(template.replace("@@VERSION@@", version), encoding="utf-8")
PY

# 5) SHA256SUMS for every file under the release dir (excluding the
#    SHA256SUMS file itself).
echo "    Computing SHA256SUMS"
( cd "$release_dir" && find . -type f ! -name SHA256SUMS -print0 \
    | xargs -0 sha256sum | sort > SHA256SUMS )

echo "==> Done. Release artifacts:"
( cd "$release_dir" && ls -lh )
