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
#   --keep-tarball     Don't delete the downloaded tarball after install.
#   --tag TAG          Install a specific tag (e.g. v0.7.2) instead of
#                      the latest.
#   --help             Print this help.
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

# ----- pretty helpers ------------------------------------------------
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

    # Workspace under PREFIX/<version>/ so multiple versions can coexist.
    local versioned="${PREFIX}/${version}"
    mkdir -p "$versioned"
    say "Install root: ${versioned}"

    local tarball="${versioned}/dosforge-${version}-linux.tar.gz"
    say "Downloading bundle..."
    curl -fL --progress-bar -o "$tarball" "$asset_url"

    say "Extracting bundle..."
    tar xzf "$tarball" -C "$versioned" --strip-components=1

    local wheel="${versioned}/dosforge-${version}-py3-none-any.whl"
    [[ -f "$wheel" ]] || fatal "Wheel not found in extracted bundle: ${wheel}"

    local venv="${versioned}/venv"
    say "Creating venv at ${venv}..."
    python3 -m venv "$venv"
    "${venv}/bin/pip" install --upgrade pip >/dev/null
    "${venv}/bin/pip" install "$wheel"

    say "Verifying installation..."
    "${venv}/bin/dosforge" --help >/dev/null \
        || fatal "dosforge --help failed after pip install."

    # Update a "current" symlink so ~/.local/bin/dosforge always points
    # at the most recently installed version.
    ln -sfn "$versioned" "${PREFIX}/current"

    if (( DO_SYMLINK )); then
        local bindir="$HOME/.local/bin"
        mkdir -p "$bindir"
        local link="${bindir}/dosforge"
        say "Linking ${link} -> ${PREFIX}/current/venv/bin/dosforge"
        ln -sf "${PREFIX}/current/venv/bin/dosforge" "$link"
        if [[ ":${PATH}:" != *":${bindir}:"* ]]; then
            warn "${bindir} is not on your PATH."
            warn "Add this to your shell rc (~/.bashrc, ~/.zshrc, etc.):"
            warn "    export PATH=\"\$HOME/.local/bin:\$PATH\""
        fi
    fi

    if (( DO_INIT_ASSETS )); then
        say "Hydrating ~/.local/share/dosforge/dosassets/ skeleton..."
        "${venv}/bin/dosforge" init-assets >/dev/null
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
    echo "    ${XDG_DATA_HOME:-$HOME/.local/share}/dosforge/dosassets/<mode>/"
    echo
    echo "For IBM PC-DOS 7.1 (FAT32 + LBA), run:"
    echo "    dosforge fetch-pcdos71-assets"
}

main
