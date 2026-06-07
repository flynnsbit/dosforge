#!/usr/bin/env bash
# dosforge Linux installer
#
# Downloads + installs the latest dosforge release. Works against the
# GitHub Releases API so it never needs to know the current version
# number -- always grabs whatever ``releases/latest`` points to.
#
# Usage:
#
#   curl -fsSL https://raw.githubusercontent.com/flynnsbit/dosforge/main/scripts/install.sh | bash
#
# Or download first, review, then run:
#
#   curl -fsSL https://raw.githubusercontent.com/flynnsbit/dosforge/main/scripts/install.sh -o install-dosforge.sh
#   less install-dosforge.sh   # review it
#   bash install-dosforge.sh
#
# Flags (pass after ``bash install-dosforge.sh``):
#
#   --no-system-deps   Skip the distro-specific apt/dnf/pacman call.
#                      Use if you have qemu / mtools / etc. installed
#                      via a different package manager (nix, brew, etc.).
#   --no-init-assets   Skip ``dosforge init-assets`` at the end.
#   --no-symlink       Skip the ~/.local/bin/dosforge symlink.
#   --prefix DIR       Use DIR as the install root.  Defaults to
#                      ${XDG_DATA_HOME:-$HOME/.local/share}/dosforge.
#                      User dosassets/ ALWAYS lives at <prefix>/dosassets/
#                      regardless of which version is installed.
#   --keep-tarball     Don't delete the downloaded tarball after install.
#   --tag TAG          Install a specific tag (e.g. v0.7.2) instead of
#                      the latest.
#   --help             Print this help.
#
# Install layout (single-version, pipx-style):
#
#   <prefix>/dosforge/
#   ├── venv/        Python env (REMOVED + recreated on every upgrade)
#   ├── bundle/      Extracted release tarball (REMOVED + recreated)
#   └── dosassets/   USER DATA — NEVER touched on upgrade.  This is
#                    where DOS install media goes (auto-extracted .7z
#                    archives, raw IMG files, etc.).
#
# Older installs from v0.7.3/v0.7.4 used a versioned layout
# (<prefix>/dosforge/<version>/) which leaked disk on every upgrade;
# v0.7.5+ detects and cleans those up automatically.
#
set -euo pipefail

readonly REPO="flynnsbit/dosforge"
readonly API="https://api.github.com/repos/${REPO}/releases"

DO_SYSTEM_DEPS=1
DO_INIT_ASSETS=1
DO_SYMLINK=1
KEEP_TARBALL=0
PREFIX="${XDG_DATA_HOME:-$HOME/.local/share}/dosforge"
TAG=""

while (( $# > 0 )); do
    case "$1" in
        --no-system-deps) DO_SYSTEM_DEPS=0 ;;
        --no-init-assets) DO_INIT_ASSETS=0 ;;
        --no-symlink) DO_SYMLINK=0 ;;
        --prefix) PREFIX="$2"; shift ;;
        --keep-tarball) KEEP_TARBALL=1 ;;
        --tag) TAG="$2"; shift ;;
        --help|-h)
            sed -n '2,/^set -euo pipefail/p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *)
            echo "ERROR: unknown flag: $1" >&2
            exit 2
            ;;
    esac
    shift
done

# ----- pretty helpers (all to stderr so $(fn) captures only data) ----
say()   { printf '\033[1;36m==>\033[0m %s\n' "$*" >&2; }
warn()  { printf '\033[1;33mWARN:\033[0m %s\n' "$*" >&2; }
fatal() { printf '\033[1;31mFATAL:\033[0m %s\n' "$*" >&2; exit 1; }

require() {
    command -v "$1" >/dev/null 2>&1 \
        || fatal "Missing required command: $1 (install it via your package manager and re-run)."
}

require curl
require tar
require python3

# ----- distro detection + system-deps install ------------------------
install_system_deps() {
    if (( DO_SYSTEM_DEPS == 0 )); then
        say "Skipping system-deps install (--no-system-deps)."
        return 0
    fi
    if [[ ! -r /etc/os-release ]]; then
        warn "Can't read /etc/os-release; skipping system-deps install."
        warn "You'll need to install qemu/mtools/p7zip/innoextract manually."
        return 0
    fi
    # shellcheck source=/dev/null
    . /etc/os-release
    local distro="${ID:-unknown}"
    say "Detected distro: $distro"

    case "$distro" in
        debian|ubuntu|linuxmint|pop|raspbian|elementary|kali|zorin)
            say "Installing system deps via apt..."
            sudo apt update
            sudo apt install -y \
                qemu-system-x86 qemu-utils nbd-client \
                mtools p7zip-full innoextract python3-venv python3-tk
            ;;
        fedora|rhel|centos|rocky|almalinux)
            say "Installing system deps via dnf..."
            sudo dnf install -y \
                qemu-system-x86 qemu-img nbd mtools \
                p7zip p7zip-plugins innoextract python3-tkinter
            ;;
        arch|manjaro|endeavouros|cachyos)
            say "Installing system deps via pacman..."
            sudo pacman -S --needed --noconfirm \
                qemu-base qemu-img nbd mtools p7zip innoextract tk
            ;;
        opensuse*|suse|sles)
            say "Installing system deps via zypper..."
            sudo zypper install -y \
                qemu-x86 qemu-tools mtools p7zip-full innoextract python3-tk
            ;;
        *)
            warn "Unrecognized distro '$distro'. Install manually:"
            warn "  qemu-system-i386, qemu-img, nbd-client, mtools,"
            warn "  p7zip, innoextract, python3-venv, python3-tk."
            ;;
    esac
}

# ----- discover latest release ---------------------------------------
get_release_metadata() {
    local url
    if [[ -n "$TAG" ]]; then
        url="${API}/tags/${TAG}"
        say "Querying ${url} ..."
    else
        url="${API}/latest"
        say "Querying ${url} for the latest release..."
    fi
    curl -fsSL -H "Accept: application/vnd.github+json" "$url"
}

extract_field() {
    local json="$1" field="$2"
    printf '%s' "$json" | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(d.get('$field', ''))
"
}

extract_linux_tarball_url() {
    local json="$1"
    printf '%s' "$json" | python3 -c "
import json, sys, re
d = json.load(sys.stdin)
pat = re.compile(r'^dosforge-[\d.]+-linux\.tar\.gz$')
for a in d.get('assets', []):
    if pat.match(a['name']):
        print(a['browser_download_url'])
        break
"
}

# ----- migrate older layouts to the v0.7.5+ flat layout --------------
migrate_legacy_layout() {
    # v0.7.3 + v0.7.4 installed to <PREFIX>/<version>/venv/.  Find
    # any such version-named subdirectories and remove them.  This is
    # only a disk-space reclamation -- the user's dosassets/ lives
    # right next to them and is never touched.
    local legacy_count=0
    for entry in "$PREFIX"/*/; do
        [[ -d "$entry" ]] || continue
        local name; name="$(basename "$entry")"
        # Match purely-numeric version dirs (0.7.3, 0.7.4, etc.).
        # Don't touch venv/, bundle/, dosassets/ or the "current"
        # symlink.
        if [[ "$name" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
            say "Removing legacy install: ${entry}"
            rm -rf "$entry"
            legacy_count=$(( legacy_count + 1 ))
        fi
    done
    # v0.7.3 + v0.7.4 also created a "current" symlink pointing at the
    # latest version dir; clean it up now that the version dirs are gone.
    if [[ -L "${PREFIX}/current" ]]; then
        rm -f "${PREFIX}/current"
        say "Removed legacy 'current' symlink."
    fi
    # v0.7.5 initially shipped a duplicate dosassets/ at bundle/dosassets/
    # (from the tarball's "extract and cd" skeleton).  Clean it up so
    # users who re-run the installer don't see two dosassets folders.
    # (This is also done after the fresh extract; the explicit check
    # here covers the case where the user re-runs without a fresh
    # extract for whatever reason.)
    if [[ -d "${PREFIX}/bundle/dosassets" ]]; then
        rm -rf "${PREFIX}/bundle/dosassets"
        say "Removed duplicate bundle/dosassets/ from previous install."
    fi
    if (( legacy_count > 0 )); then
        say "Cleaned up ${legacy_count} legacy version director(ies)."
    fi
}

# ----- main flow -----------------------------------------------------
main() {
    install_system_deps

    say "Discovering latest dosforge release on github.com/${REPO}..."
    local meta
    meta="$(get_release_metadata)"
    local tag version asset_url
    tag="$(extract_field "$meta" tag_name)"
    version="${tag#v}"
    asset_url="$(extract_linux_tarball_url "$meta")"

    [[ -n "$tag" ]] || fatal "Could not determine the release tag (API returned no 'tag_name')."
    [[ -n "$asset_url" ]] || fatal "Release ${tag} has no dosforge-*-linux.tar.gz asset."

    say "Latest release: ${tag} (version ${version})"
    say "Asset URL:      ${asset_url}"

    mkdir -p "$PREFIX"
    migrate_legacy_layout

    say "Install root: ${PREFIX}"
    say "  - venv:      ${PREFIX}/venv/      (replaced on upgrade)"
    say "  - bundle:    ${PREFIX}/bundle/    (replaced on upgrade)"
    say "  - dosassets: ${PREFIX}/dosassets/ (USER DATA, NEVER touched on upgrade)"

    # Detect previous install version (for the upgrade message).
    local prev_version=""
    if [[ -x "${PREFIX}/venv/bin/dosforge" ]]; then
        prev_version="$("${PREFIX}/venv/bin/dosforge" --help 2>/dev/null | head -1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || true)"
    fi
    if [[ -n "$prev_version" ]]; then
        if [[ "$prev_version" == "$version" ]]; then
            say "Reinstalling dosforge ${version} (same version already present)."
        else
            say "Upgrading dosforge ${prev_version} -> ${version}."
        fi
    fi

    local bundle_dir="${PREFIX}/bundle"
    local tarball="${bundle_dir}/dosforge-${version}-linux.tar.gz"
    rm -rf "$bundle_dir"
    mkdir -p "$bundle_dir"

    say "Downloading bundle..."
    curl -fL --progress-bar -o "$tarball" "$asset_url"

    say "Extracting bundle..."
    tar xzf "$tarball" -C "$bundle_dir" --strip-components=1

    # The release tarball ships a ``dosassets/`` skeleton at its root
    # so the "extract and run dosforge from inside the bundle dir"
    # workflow has install media folders ready.  Our flat installer
    # uses a separate top-level <prefix>/dosassets/ instead (so
    # upgrades don't touch user data), which makes the bundled
    # skeleton a confusing duplicate.  Remove it.
    if [[ -d "${bundle_dir}/dosassets" ]]; then
        rm -rf "${bundle_dir}/dosassets"
        say "Removed duplicate ${bundle_dir}/dosassets/ (real one lives at ${PREFIX}/dosassets/)."
    fi

    local wheel="${bundle_dir}/dosforge-${version}-py3-none-any.whl"
    [[ -f "$wheel" ]] || fatal "Wheel not found in extracted bundle: ${wheel}"

    local venv="${PREFIX}/venv"
    if [[ -d "$venv" ]]; then
        say "Removing old venv at ${venv}..."
        rm -rf "$venv"
    fi
    say "Creating venv at ${venv}..."
    python3 -m venv "$venv"
    "${venv}/bin/pip" install --upgrade pip >/dev/null
    "${venv}/bin/pip" install "$wheel"

    say "Verifying installation..."
    "${venv}/bin/dosforge" --help >/dev/null \
        || fatal "dosforge --help failed after pip install."

    if (( DO_SYMLINK )); then
        local bindir="$HOME/.local/bin"
        mkdir -p "$bindir"
        local link="${bindir}/dosforge"
        say "Linking ${link} -> ${venv}/bin/dosforge"
        ln -sf "${venv}/bin/dosforge" "$link"
        if [[ ":${PATH}:" != *":${bindir}:"* ]]; then
            warn "${bindir} is not on your PATH."
            warn "Add this to your shell rc (~/.bashrc, ~/.zshrc, etc.):"
            warn "    export PATH=\"\$HOME/.local/bin:\$PATH\""
        fi

        # Sanity check: confirm `dosforge` on PATH resolves to OUR
        # symlink.  If another `dosforge` from a previous pipx /
        # global pip / asdf / mise install is taking priority, the
        # user will run a stale binary and wonder why new features
        # like ``--version`` are missing.  Print a clear diagnostic.
        local active_dosforge
        active_dosforge="$(command -v dosforge 2>/dev/null || true)"
        if [[ -n "$active_dosforge" ]]; then
            # Resolve the symlink chain so we can compare absolute paths.
            local active_resolved
            active_resolved="$(readlink -f "$active_dosforge" 2>/dev/null || echo "$active_dosforge")"
            local installed_resolved
            installed_resolved="$(readlink -f "${venv}/bin/dosforge" 2>/dev/null || echo "${venv}/bin/dosforge")"
            if [[ "$active_resolved" != "$installed_resolved" ]]; then
                warn "Another 'dosforge' is taking priority on your PATH:"
                warn "    $(command -v dosforge) -> $active_resolved"
                warn "    (this install: $installed_resolved)"
                warn ""
                warn "Common culprits:"
                warn "  - pipx install dosforge from before this installer existed"
                warn "    -> fix:  pipx uninstall dosforge"
                warn "  - global 'pip install --user dosforge' on a different Python"
                warn "    -> fix:  pip uninstall dosforge  (run with the offending Python)"
                warn "  - mise/asdf-managed shim ahead of ~/.local/bin on PATH"
                warn "    -> fix:  move 'export PATH=\"\$HOME/.local/bin:\$PATH\"' AFTER"
                warn "             the mise/asdf shim line in your shell rc"
                warn ""
                warn "Until that's fixed, run the installed version directly:"
                warn "    ${venv}/bin/dosforge --version"
            fi
        fi
    fi

    if (( DO_INIT_ASSETS )); then
        say "Hydrating ${PREFIX}/dosassets/ skeleton..."
        "${venv}/bin/dosforge" init-assets --target "${PREFIX}/dosassets" >/dev/null
    fi

    if (( KEEP_TARBALL == 0 )); then
        rm -f "$tarball"
    fi

    say "Install complete!"
    echo
    echo "Try:"
    echo "    dosforge --help"
    echo "    dosforge create --help"
    echo "    dosforge where-assets"
    echo
    echo "DOS install media goes in:"
    echo "    ${PREFIX}/dosassets/<mode>/"
    echo "(see each mode's readme.txt for expected filenames / .7z names)"
    echo
    echo "For IBM PC-DOS 7.1 (FAT32 + LBA), run:"
    echo "    dosforge fetch-pcdos71-assets"
    echo
    echo "To uninstall: rm -rf '${PREFIX}/venv' '${PREFIX}/bundle'"
    echo "(your dosassets/ stays put for the next install)"
}

main
