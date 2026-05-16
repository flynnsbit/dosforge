#!/usr/bin/env bash
#
# install.sh -- one-shot installer for a dosforge release.
#
# What it does:
#   1. Detect the Linux distribution (Arch / Ubuntu / Debian).
#   2. Install the system command-line tools dosforge depends on
#      (qemu-img, qemu-nbd, qemu-system-i386, mtools, dosfstools,
#       parted, partprobe, dd, mount, xdg-open, sudo).
#   3. Install dosforge from the bundled wheel into the user's
#      Python environment via pipx (preferred) or `pip --user`.
#   4. Stage the bundled ``dosassets/`` tree into the user's home
#      so dosforge auto-resolves boot assets without a CLI flag.
#
# Re-running is idempotent: system packages already present are
# left alone; pipx upgrades the wheel in place; the dosassets/
# stage step refuses to overwrite an existing tree.
#
# Usage:
#
#     ./install.sh                 # install for the current user
#     ./install.sh --system        # install dosforge globally (pipx --global)
#     ./install.sh --no-dosassets  # skip the dosassets stage step

set -euo pipefail

install_dosassets=1
pipx_global=0

for arg in "$@"; do
  case "$arg" in
    --system)
      pipx_global=1
      ;;
    --no-dosassets)
      install_dosassets=0
      ;;
    -h|--help)
      sed -n '2,30p' "$0"
      exit 0
      ;;
    *)
      echo "install.sh: unknown argument: $arg" >&2
      exit 2
      ;;
  esac
done

script_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
cd "$script_dir"

# ------------------------------------------------------------------
# 1) Distro detection
# ------------------------------------------------------------------

distro=""
if [ -r /etc/os-release ]; then
  # shellcheck disable=SC1091
  . /etc/os-release
  case "${ID:-}" in
    arch|cachyos|endeavouros|manjaro|garuda)
      distro="arch"
      ;;
    ubuntu|debian|linuxmint|pop|elementary|kali|raspbian|zorin)
      distro="ubuntu"
      ;;
  esac
  if [ -z "$distro" ] && [ -n "${ID_LIKE:-}" ]; then
    case "$ID_LIKE" in
      *arch*) distro="arch" ;;
      *debian*|*ubuntu*) distro="ubuntu" ;;
    esac
  fi
fi

if [ -z "$distro" ]; then
  echo "install.sh: unsupported distribution (need Arch- or Debian/Ubuntu-family)." >&2
  echo "  /etc/os-release ID was: ${ID:-<unset>} (ID_LIKE=${ID_LIKE:-<unset>})" >&2
  echo "  Install the system deps listed in README.md manually, then re-run with --no-system." >&2
  exit 1
fi

echo "==> Detected distribution family: ${distro}"

# ------------------------------------------------------------------
# 2) System dependencies
# ------------------------------------------------------------------

arch_packages=(
  python python-pip python-pipx
  qemu-base qemu-system-x86
  mtools dosfstools parted util-linux coreutils xdg-utils sudo
)

ubuntu_packages=(
  python3 python3-pip pipx python3-venv
  qemu-utils qemu-system-x86
  mtools dosfstools parted util-linux coreutils xdg-utils sudo
)

case "$distro" in
  arch)
    echo "==> Installing system packages via pacman"
    sudo pacman -S --needed --noconfirm "${arch_packages[@]}"
    ;;
  ubuntu)
    echo "==> Installing system packages via apt"
    sudo apt-get update
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "${ubuntu_packages[@]}"
    ;;
esac

# Verify the runtime commands dosforge actually invokes.
required_runtime_commands=(
  python3 qemu-img qemu-nbd qemu-system-i386
  mkfs.fat mcopy mformat mattrib mtype mdir mdel
  parted partprobe dd mount umount sudo xdg-open
)
missing=()
for cmd in "${required_runtime_commands[@]}"; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    missing+=("$cmd")
  fi
done
if [ "${#missing[@]}" -gt 0 ]; then
  echo "install.sh: WARNING — the following commands are still not on PATH after package install:" >&2
  printf '    - %s\n' "${missing[@]}" >&2
  echo "    dosforge will refuse to run boot/install flows that need them." >&2
fi

# ------------------------------------------------------------------
# 3) Python package install
# ------------------------------------------------------------------

wheel="$(find "$script_dir" -maxdepth 1 -name 'dosforge-*.whl' -print -quit)"
if [ -z "$wheel" ]; then
  echo "install.sh: no dosforge wheel found alongside this script." >&2
  exit 1
fi

echo "==> Installing dosforge wheel: $(basename "$wheel")"

if command -v pipx >/dev/null 2>&1; then
  pipx ensurepath >/dev/null || true
  if [ "$pipx_global" -eq 1 ]; then
    # pipx --global was added in 1.4.x. Fall back to a sudo-elevated install
    # into /opt if --global isn't supported.
    if pipx install --help 2>&1 | grep -q -- "--global"; then
      sudo pipx install --global --force "$wheel"
    else
      sudo PIPX_HOME=/opt/pipx PIPX_BIN_DIR=/usr/local/bin \
        pipx install --force "$wheel"
    fi
  else
    pipx install --force "$wheel"
  fi
else
  echo "    pipx not found; falling back to pip install --user"
  python3 -m pip install --user --upgrade "$wheel"
fi

echo "==> Verifying"
if ! command -v dosforge >/dev/null 2>&1; then
  echo "install.sh: 'dosforge' is not on PATH after install. Re-open your shell or run:" >&2
  echo "    pipx ensurepath" >&2
  exit 1
fi
dosforge --help | head -5 || true

# ------------------------------------------------------------------
# 4) Stage dosassets/ into the user's home so dosforge's bare-name
#    lookups (e.g. --boot-assets-path msdos33) work without the user
#    having to be inside the release directory.
# ------------------------------------------------------------------

if [ "$install_dosassets" -eq 1 ] && [ -d "$script_dir/dosassets" ]; then
  user_assets="${XDG_DATA_HOME:-$HOME/.local/share}/dosforge/dosassets"
  if [ -d "$user_assets" ] && [ -n "$(ls -A "$user_assets" 2>/dev/null || true)" ]; then
    echo "==> dosassets/ already present at $user_assets (leaving untouched)."
  else
    echo "==> Copying bundled dosassets/ to $user_assets"
    mkdir -p "$user_assets"
    cp -r "$script_dir/dosassets/." "$user_assets/"
  fi
  echo "    Tip: cd to a directory containing 'dosassets/' (the install copied"
  echo "    one to ${user_assets}) or pass --boot-assets-path explicitly."
fi

echo
echo "Done. Run 'dosforge' to launch the TUI."
