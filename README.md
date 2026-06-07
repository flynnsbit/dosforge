# dosforge

`dosforge` is a DOS-focused image utility that runs on **Linux**
(with a full Textual TUI + kernel-mount workflow) and **Windows**
(CLI + a Windows 11-styled **tkinter GUI with a wizard-like flow** —
no admin, no sudo, no kernel modules; single portable
`dosforge.exe` / `dosforge-gui.exe` bundle).

It can create, browse, and modify:

- fixed-size **VHD** images (FAT12/FAT16/FAT32) for **IDE** or **MFM** controllers
- floppy **IMG/IMA/VFD** images (FAT12)

with optional boot/system-file staging for **14 bootable DOS modes**
spanning 1984-1998 (Compaq DOS 2.11 through MS-DOS 7.10 / Win95 OSR2,
plus FreeDOS).

## Platform support

| Feature | Linux | Windows | Notes |
|---|:---:|:---:|---|
| Create VHD (IDE + MFM controllers) | ✅ | ✅ | every wired boot mode produces a bootable VHD |
| Create floppy IMG (8 sizes, bootable + non-bootable) | ✅ | ✅ | |
| `--dos-install-profile {minimal,full}` | ✅ | ✅ | C:\DOS\ tools tree on FULL |
| `--disk-controller {ide,mfm}` + `--bios-drive-type` + `--custom-chs` | ✅ | ✅ | controller-first VHD model (v0.7.0+) |
| `.7z` auto-extract (WinWorldPC archives) | ✅ | ✅ | drop into `dosassets/<mode>/`, transparent unpack |
| Custom-payload directory copy | ✅ | ✅ | VHD + IMG, both platforms |
| `dosforge ls / cat / get / put / rm / mkdir` | ✅ | ✅ | mtools-based, no mount required |
| `dosforge mount / unmount` | ✅ | ❌ | Linux-only (qemu-nbd + kernel mount). On Windows use the `ls/cat/get/put/rm/mkdir` verbs instead. |
| `open_in_files` | ✅ (xdg-open) | ✅ (Explorer) | |
| Textual TUI | ✅ | ⚠️ | TUI works but is iterated on the CLI surface; richer support on Linux. |
| Tkinter GUI (Windows 11 style) | ✅ | ✅ | `dosforge gui` (Linux: optional) / default on Windows |

## Supported boot modes

dosforge produces **14 bootable DOS configurations** plus `none`
(non-bootable) and `4dos` (overlay, planned).  Source media is staged
in `dosassets/<mode>/` (each mode folder ships a `readme.txt` with the
expected files / .7z names).

### Wired and verified

| Boot mode | DOS / Source | FAT support | Controller(s) | Min media |
|---|---|:---:|:---:|---|
| `freedos` | FreeDOS 1.x | 12/16/32 | IDE | LOCAL files or auto-download |
| `ibm8088` (+`--ibm-dos-version dos33`/`dos50`) | IBM PC DOS 3.3 or 5.0 | 12/16 | IDE (or MFM via Phoenix Type) | install floppies |
| `compaq2` | Microsoft MS-DOS 2.11 (Compaq OEM, 1984) | 12 | **MFM** + 360k IMG | WinWorldPC 360k .7z |
| `msdos33` | MS-DOS 3.30 | 12/16≤32MB | IDE / MFM | install floppies |
| `msdos331` | Microsoft MS-DOS 3.31 | 16≤32MB | IDE | install floppies |
| `compaq331` | Compaq DOS 3.31 (FAT16B, up to 504 MiB) | 16B | IDE | install floppies |
| `pcdos` | IBM PC-DOS 2.x/3.x/4.x (generic, pre-7.0) | 12/16 | IDE / MFM | install floppies |
| `msdos5` | MS-DOS 5.00 | 16 | IDE | install floppies |
| `msdos622` | MS-DOS 6.22 + Enhanced Tools | 16 | IDE | install floppies |
| `pcdos7` | IBM PC-DOS 7.0 (XDF / LOADDSKF-compressed) | 12/16 | IDE | XDF .DSK file |
| `pcdos2000` | IBM PC-DOS 2000 (rebranded PC-DOS 7.0 for Y2K) | 12/16 | IDE | 6-floppy 1.44MB .7z |
| `pcdos71` | IBM PC-DOS 7.1 (SGTK, FAT32 + LBA) | 16/32 | IDE | auto-downloads via `dosforge fetch-pcdos71-assets` |
| `msdos71` | **MS-DOS 7.10 / Win95 OSR2** (DOS-only boot, no GUI Setup) | 16/32 | IDE | Win95 OSR2 floppy set in `dosassets/w95/` |
| `4dos` | 4DOS shell overlay on top of a `--host-boot-mode` | — | — | planned (not yet implemented) |

### Queued (user-staged media, wiring pending)

`pcdos3` (IBM PC-DOS 3.00), `msdos6` (MS-DOS 6.0), `compaq3` (Compaq
OEM MS-DOS 3.00), `drdos6` (DR-DOS 6.0), `drdos7` (Caldera DR-DOS 7.03).

### Intentionally not implemented

`w95` retail GUI install — multi-disk CAB extraction + Setup wizard
deemed out of scope.  Use `msdos71` instead for FAT32 + DOS without
the GUI.

## Disk controllers (v0.7.0+)

VHD output is organized **controller-first**.  Pick `--disk-controller`
(or let dosforge auto-detect from boot mode), then optionally pick a
geometry source.

### Controllers

| `--disk-controller` | Era / use case | Compatible boot modes |
|---|---|---|
| `ide` (default for most boot modes) | AT-class IDE/ATA — every emulator since 1988, all modern hardware | All boot modes except those marked MFM-only |
| `mfm` | XT-class ST-506/ST-412 (1984-1990) — Western Digital WD1002A, IBM/Xebec, Adaptec 4070, etc. Works on 86Box's MFM controllers, PCem MFM, MartyPC Xebec, real WD1002A-WX1 hardware | `compaq2`, `msdos33`, `pcdos`, `ibm8088`+`dos33` |

Auto-detect rules when `--disk-controller` is omitted:
- **MFM**: `compaq2`, `msdos33`, `pcdos`, `ibm8088`+`dos33`
- **IDE**: everything else

### Geometry source (per controller)

| Flag | Purpose |
|---|---|
| `--bios-drive-type VENDOR:N` | Standard Phoenix/AMI BIOS Type 1-45 table.  127 entries (Phoenix + AMI combined).  Run `dosforge list-bios-drive-types` for the full table. |
| `--custom-chs CYL,HEAD,SPT` | Free-form geometry source — overrides `--bios-drive-type` when set.  Useful for unusual emulator presets. |
| (neither set) | IDE: canonical `16h × 63s`, size from `--size`.  MFM: defaults to **Phoenix Type 1** (306×4×17 = 10 MiB) — adjust with `--bios-drive-type` or `--custom-chs`. |

### Common geometry examples

| Slug | CHS | Size | Era | Best controller |
|---|---|---:|---|---|
| `phoenix:1` | 306×4×17 | 10 MiB | 1984 | MFM (ST-225) |
| `phoenix:2` | 615×4×17 | 20 MiB | 1984 | MFM (ST-225 large) |
| `phoenix:3` | 615×6×17 | 30 MiB | 1985 | MFM (ST-238) |
| `phoenix:4` | 940×8×17 | 40 MiB | 1986 | MFM (ST-251) |
| `phoenix:9` | 900×15×17 | ~117 MiB | late 80s | IDE |
| `--custom-chs 1024,16,63` | 1024×16×63 | 504 MiB | 90s | IDE (canonical NORMAL cap) |
| `--custom-chs 4096,4,16` | 4096×4×16 | 128 MiB | 90s | IDE |

### Build examples

```bash
# Default — IDE controller, canonical 16h/63s geometry, FAT16, 64 MiB
dosforge create --media-type vhd --boot-mode msdos622 \
    --format fat16 --size 64M \
    --path ~/vhd/msdos622.vhd

# MFM controller with authentic ST-225 geometry for Compaq DOS 2.11
dosforge create --media-type vhd --boot-mode compaq2 \
    --format fat12 \
    --disk-controller mfm --bios-drive-type phoenix:1 \
    --path ~/vhd/compaq2-mfm.vhd

# Custom CHS for an unusual emulator preset (XT-IDE 504 MiB cap)
dosforge create --media-type vhd --boot-mode msdos5 \
    --format fat16 \
    --custom-chs 1024,16,63 \
    --path ~/vhd/msdos5-xtide.vhd

# Authentic floppy IMG — 360k DSDD Compaq DOS 2.11
dosforge create --media-type img --boot-mode compaq2 \
    --format fat12 --floppy-type 360k --img-system-format \
    --path ~/floppy/compaq2.img
```

## Floppy presets

`160K`, `180K`, `360K`, `720K`, `1.84M (XDF)`, `1.2M`, `1.44M`, `2.88M`.

Floppy IMG formatting uses explicit DOS geometry/BPB settings per preset:

| Preset | Tracks | Heads | Sectors/track | Total sectors | Media byte |
|---|---:|---:|---:|---:|---:|
| 160K | 40 | 1 | 8 | 320 | `0xFE` |
| 180K | 40 | 1 | 9 | 360 | `0xFC` |
| 360K | 40 | 2 | 9 | 720 | `0xFD` |
| 720K | 80 | 2 | 9 | 1440 | `0xF9` |
| 1.84M (XDF) | 80 | 2 | 23 | 3680 | `0xF0` |
| 1.2M | 80 | 2 | 15 | 2400 | `0xF9` |
| 1.44M | 80 | 2 | 18 | 2880 | `0xF0` |
| 2.88M | 80 | 2 | 36 | 5760 | `0xF0` |

## Requirements

Base runtime (Linux):

- `mkfs.fat`
- `mount`, `umount`
- `sudo` (one-time auth, no NOPASSWD rules required)
- `xdg-open`

VHD runtime (Linux):

- `qemu-img`, `qemu-nbd`, `qemu-system-i386`
- `parted`, `partprobe`
- `modprobe` (kmod)
- `mcopy`, `mattrib`, `mformat`, `mdir` (mtools)
- `p7zip-full` / `p7zip` (auto .7z extraction)

Windows: all tools are bundled inside the PyInstaller distribution
(`_internal/vendor/windows/bin/`).  No system installs required.

## Install

### Linux

#### Option A — One-line installer (recommended)

```bash
curl -fsSL https://raw.githubusercontent.com/flynnsbit/dosforge/main/scripts/install.sh | bash
```

That's it.  The installer:

1. Detects your distro (Debian/Ubuntu/Mint/Pop/Fedora/RHEL/Arch/openSUSE)
   and installs the system tools dosforge shells out to
   (`qemu-system-x86`, `mtools`, `p7zip`, `innoextract`, etc.) via your
   native package manager.  Will prompt for sudo.
2. Downloads the **latest** dosforge release tarball from
   [GitHub Releases](https://github.com/flynnsbit/dosforge/releases/latest)
   — no version pin, always grabs whatever's current.
3. Creates an isolated venv under
   `~/.local/share/dosforge/<version>/venv` (multiple versions can
   coexist; `~/.local/share/dosforge/current` is a symlink to the
   most recently installed).
4. Symlinks `~/.local/bin/dosforge` so it's on your `PATH` after the
   first install (if `~/.local/bin` isn't on your `PATH` already,
   the installer warns you and shows what to add to your shell rc).
5. Hydrates the `~/.local/share/dosforge/dosassets/` folder
   skeleton (one folder + `readme.txt` per supported DOS mode).
6. Smoke-tests `dosforge --help` before finishing.

Want to review the script before running it?

```bash
curl -fsSL https://raw.githubusercontent.com/flynnsbit/dosforge/main/scripts/install.sh -o install-dosforge.sh
less install-dosforge.sh   # review
bash install-dosforge.sh
```

Useful flags (pass after `bash install-dosforge.sh`):

| Flag | Effect |
|---|---|
| `--no-system-deps` | Skip the `apt`/`dnf`/`pacman` step (use if you've already got qemu/mtools/etc. installed) |
| `--no-init-assets` | Skip the `dosforge init-assets` step |
| `--no-symlink` | Skip the `~/.local/bin/dosforge` symlink |
| `--prefix DIR` | Use DIR as the install root (default: `~/.local/share/dosforge`) |
| `--tag v0.7.2` | Install a specific tag instead of the latest |
| `--keep-tarball` | Keep the downloaded `.tar.gz` after install |

After install:

```bash
dosforge --help              # full reference
dosforge create --help       # create command reference
dosforge where-assets        # show dosassets resolution order
dosforge fetch-pcdos71-assets   # download IBM PC-DOS 7.1 from archive.org
```

#### Option B — From source (developers)

```bash
git clone https://github.com/flynnsbit/dosforge.git
cd dosforge
python3 -m venv .venv
. .venv/bin/activate
pip install -e .[dev]

# System tools (same packages the installer above would pull in)
sudo apt install qemu-system-x86 qemu-utils nbd-client \
    mtools p7zip-full innoextract python3-tk
```

When installed editable from a checkout, the repo's own `dosassets/`
directory is the search root — just run `dosforge` from the repo and
drop install media into `dosassets/<mode>/` as usual.

You can also run `dosforge init-assets` from an editable install to
hydrate `~/.local/share/dosforge/dosassets/` with the per-mode folder +
readme.txt skeleton; the readmes ship inside the wheel so it works
from any working directory.

#### Where to put DOS install media

dosforge looks for install diskettes in this order (highest priority first):

1. `$DOSFORGE_DOSASSETS_DIR` — export this to override everything
2. `$PWD/dosassets/` — wins when you `cd` into the extracted bundle or repo
3. `$XDG_DATA_HOME/dosforge/dosassets/`
   (defaults to `~/.local/share/dosforge/dosassets/`)
4. `~/.dosforge/dosassets/`
5. `/usr/local/share/dosforge/dosassets/`
6. `/usr/share/dosforge/dosassets/` — for distro packagers

Run `dosforge where-assets` at any time to see which of these paths
currently exist on your machine.

#### IBM PC-DOS 7.1 specifically (FAT32 + LBA)

PC-DOS 7.1 was only ever distributed inside the IBM ServerGuide
Scripting Toolkit. ibm.com no longer hosts it but the Internet Archive
preserves a verified mirror. dosforge ships a fetcher that downloads,
verifies, and stages the required files. Three equivalent entry
points (all call the same library):

```bash
# 1. Recommended: dosforge CLI (works from any directory once installed).
dosforge fetch-pcdos71-assets

# 2. Or from the TUI: open New Disk → Step 3, set boot-mode=pcdos71,
#    click "Fetch IBM PC-DOS 7.1 assets (SGTK download)".

# 3. Or the standalone script (no dosforge install required — useful in CI).
python3 scripts/fetch-pcdos71-assets.py
```

All three download the IBM installer (SHA-1 verified) and unpack the
required files into `~/.local/share/dosforge/dosassets/pcdos71/` (or
the path `dosforge where-assets` reports first, or wherever
`DOSFORGE_DOSASSETS_DIR` points if set) with per-file SHA-256
verification against community-published reference hashes.

Optional flags:
- `--force` — re-extract even if the SGTK cache looks fresh.
- `--keep-extract` — leave the extracted SGTK tree in the cache dir.
- `--target DIR` — override the staging directory.

### Windows

Two ways to run dosforge on Windows:

#### Option A — Release bundle (recommended)

Download the latest Windows release zip from
[GitHub Releases](https://github.com/flynnsbit/dosforge/releases/latest)
(look for `dosforge-<version>-windows.zip`). Each release ships **two
EXEs sharing one bundle**:

- `dosforge.exe` — CLI / TUI entry point
- `dosforge-gui.exe` — Windows 11-styled tkinter GUI

```powershell
# 1. Extract the zip somewhere outside Program Files (avoids UAC weirdness)
Expand-Archive dosforge-windows.zip -DestinationPath C:\Apps\DosForge

# 2. Stage your DOS install media (one folder per supported mode)
#    Drop .7z archives or pre-extracted floppies into
#    C:\Apps\DosForge\dosassets\<mode>\

# 3. Run
C:\Apps\DosForge\dosforge.exe create --help
C:\Apps\DosForge\dosforge.exe ls C:\path\to\image.vhd /
C:\Apps\DosForge\dosforge-gui.exe   # double-click for GUI
```

The Windows bundle ships QEMU, mtools, and DOSBox-X (for LOADDSKF
unpacking) inside `_internal/vendor/windows/bin/`.  No external
dependencies, no admin rights required.

#### Option B — From source

```powershell
# One-time setup (fetches QEMU + mtools + py7zr into vendor/windows/bin/
# and builds the PyInstaller bundle under dist\dosforge\).
.\.venv\Scripts\python.exe -m pip install -e .[dev]
.\.venv\Scripts\python.exe scripts\fetch-windows-vendor.py
.\.venv\Scripts\python.exe -m PyInstaller windows\dosforge.spec --noconfirm

# Run from the repo root.
.\dist\dosforge\dosforge.exe ls testimages\vhd-msdos622-128m.vhd /
.\dist\dosforge\dosforge.exe create --media-type vhd --format fat32 --size 2G ^
    --boot-mode pcdos71 --path C:\temp\pcdos71.vhd
```

The root-level `dosforge.bat` / `dosforge.ps1` are thin wrappers that
forward every argument to `dist\dosforge\dosforge.exe`.

## Run

```bash
dosforge        # Linux: launches the TUI (sudo auth happens up-front)
.\dosforge      # Windows: launches the TUI (or `dosforge gui` for tkinter)
```

`dosforge` performs startup sudo auth for the TUI (`sudo -v`) on Linux
so credential prompts happen up front. The same one-time prompt fires
for headless CLI invocations of `create`, `mount`, and `unmount` too.
A background keep-alive thread refreshes the kernel sudo timestamp
cache once a minute while a build is running so long operations
(PC-DOS 7.1 + FAT32 install, Win95 OSR2 SYS) don't expire mid-flight.
No `NOPASSWD` sudoers rules are required.  The Windows backend reports
`requires_sudo_for_disk_ops=False`, so no sudo prompts ever appear there.

## TUI usage

1. Launch `dosforge`
2. In **Create disk image**:
   - choose **Media type** (`VHD` or `IMG`)
   - choose **Boot mode** (filters disk controller + FAT options)
   - set **Disk controller** (`Auto`, `IDE`, or `MFM`) and **Geometry source** if VHD
   - set path / size or floppy preset
   - optionally enable DOS install profile + provide assets
3. Click **Create + format ...**
4. Select image in browser and click **Mount selected image** (Linux only)
5. Image opens in GUI file manager automatically (Linux + Windows)

The file browser accepts `.vhd`, `.img`, `.ima`.

## CLI quick start

```bash
# Check dependencies (all VHD paths by default)
dosforge check-deps

# Check IMG-only dependencies
dosforge check-deps --media-type img

# Sudo/privilege diagnostics
dosforge sudo-check

# List the full BIOS Type 1-45 geometry table
dosforge list-bios-drive-types

# Create fixed-size FAT16 VHD on default IDE controller
dosforge create --path ~/vhd/demo.vhd --size 512M --format fat16

# Create IBM DOS 5.0 VHD (8088/V20 profile) on auto-detected IDE
dosforge create \
  --path ~/vhd/xt-dos5.vhd \
  --size 32M \
  --format fat16 \
  --boot-mode ibm8088 \
  --ibm-dos-version dos50 \
  --boot-assets-path ./dos5

# Create Compaq DOS 2.11 VHD on MFM controller with ST-225 geometry
dosforge create \
  --path ~/vhd/compaq2-mfm.vhd \
  --format fat12 \
  --boot-mode compaq2 \
  --disk-controller mfm --bios-drive-type phoenix:1

# Create non-bootable 1.44M floppy IMG
dosforge create --path ~/floppy/tools.img --media-type img --floppy-type 1440k

# Create bootable 360k Compaq DOS 2.11 floppy IMG
dosforge create \
  --path ~/floppy/compaq2.img \
  --media-type img \
  --floppy-type 360k \
  --img-system-format \
  --boot-mode compaq2

# Create bootable 720K PC-DOS floppy IMG
dosforge create \
  --path ~/floppy/pcdos-boot.img \
  --media-type img \
  --floppy-type 720k \
  --img-system-format \
  --boot-mode pcdos \
  --boot-assets-path ./pcdos

# Create bootable 1.84M XDF-style PC-DOS 7.0 floppy IMG
dosforge create \
  --path ~/floppy/pcdos7-boot.img \
  --media-type img \
  --floppy-type 1840k \
  --img-system-format \
  --boot-mode pcdos7 \
  --boot-assets-path ./pcdos7

# Create FAT32 PC-DOS 7.1 / MS-DOS 7.10 VHD with FULL DOS tools tree
dosforge create \
  --path ~/vhd/pcdos71-1g.vhd \
  --size 1G \
  --format fat32 \
  --boot-mode pcdos71 \
  --dos-install-profile full

# MS-DOS 7.10 / Win95 OSR2 (DOS-only boot, FAT32)
dosforge create \
  --path ~/vhd/msdos71-2g.vhd \
  --size 2G \
  --format fat32 \
  --boot-mode msdos71 \
  --boot-assets-path ./w95   # Win95 OSR2 floppy set

# Create DOS disk with core \DOS utilities + startup files
dosforge create \
  --path ~/vhd/msdos622-full.vhd \
  --size 512M \
  --format fat16 \
  --boot-mode msdos622 \
  --boot-assets-path ./msdos622 \
  --dos-install-profile full

# Create VHD from a custom payload directory (auto-sizes VHD to fit payload)
dosforge create \
  --path ~/vhd/apps.vhd \
  --format fat16 \
  --custom-payload-path ./payload

# Add payload files while system-formatting a floppy IMG (fails if payload won't fit)
dosforge create \
  --path ~/floppy/custom-dos.img \
  --media-type img \
  --floppy-type 1440k \
  --img-system-format \
  --boot-mode msdos622 \
  --boot-assets-path ./msdos622 \
  --custom-payload-path ./payload

# Mount + open (Linux only)
dosforge mount --path ~/vhd/demo.vhd --open
dosforge mount --path ~/floppy/tools.img --open

# Unmount
dosforge unmount --mount-point ~/.local/state/dosforge/mounts/demo-xxxxxxxx
```

## Boot assets (local media)

dosforge looks for install media under a top-level `dosassets/` folder.
Each boot mode has its own subdirectory with a `readme.txt` documenting
which diskette images (or `.7z` archive) to drop in.  A full layout
covering every wired mode:

```
dosassets/
├── compaq2/        # boot-mode=compaq2     (Compaq OEM MS-DOS 2.11 .7z, 360k)
├── compaq331/      # boot-mode=compaq331   (Compaq DOS 3.31 .7z, 720k)
├── freedos/        # boot-mode=freedos     (KERNEL.SYS + COMMAND.COM + boot template)
├── ibmpcdos401/    # boot-mode=pcdos       (IBM PC-DOS 4.01)
├── msdos33/        # boot-mode=msdos33  /  ibm8088+dos33
├── msdos331/       # boot-mode=msdos331    (Microsoft MS-DOS 3.31)
├── msdos5/         # boot-mode=msdos5   /  ibm8088+dos50
├── msdos622/       # boot-mode=msdos622    (DOS 6.22 + Enhanced Tools)
├── msdos71/        # legacy DOS71_1S.PAK location (deprecated — see w95/)
├── pcdos7/         # boot-mode=pcdos7      (IBM PC-DOS 7.0 XDF .DSK)
├── pcdos2000/      # boot-mode=pcdos2000   (IBM PC-DOS 2000 6-floppy .7z)
├── pcdos71/        # boot-mode=pcdos71     (auto-fetched IBM SGTK)
└── w95/            # boot-mode=msdos71     (Win95 OSR2 floppy set for FAT32 DOS)
```

Pass `--boot-assets-path <name>` (a bare name like `msdos33`) and
dosforge will resolve it to `./dosassets/<name>/`.  Pass a full path
(`./foo/bar` or `/abs/path`) to use any other location.  Omit the flag
entirely and dosforge auto-resolves the boot mode's default subdirectory.

**Typical workflow**: download the WinWorldPC `.7z` for the DOS version,
drop it into the matching subdirectory (no manual extraction needed —
dosforge unpacks `.7z` archives transparently via `py7zr`), then run
dosforge.

### Per-mode notes

#### FreeDOS

- Local dir or image with `KERNEL.SYS`, `COMMAND.COM`, boot template
  (`BOOTSECT_FAT16.BIN` / `BOOTSECT_FAT32.BIN`)
- Or auto-download path for FreeDOS image (`--freedos-source auto`)
- FreeDOS bootable VHDs use a curated payload filter that ships
  authentic minimal DOS files (~85 files vs 1388 from a full
  install) for fast builds.

#### Compaq DOS 2.11 (compaq2)

- IMG output (360k floppy): authentic 1984 Compaq DOS 2.11 medium,
  boots in any emulator with a 5.25" 360k or 1.2M drive.
- VHD output: **requires** `--disk-controller mfm` because DOS 2.x's
  1984 boot code depends on Compaq-specific BIOS extensions that no
  modern emulator's AT-class IDE BIOS provides.  Use
  `--bios-drive-type phoenix:1` (10 MiB ST-225) or `phoenix:2`
  (20 MiB ST-225).  Boots in MartyPC with Xebec Type 1 preset
  (other MFM-capable emulators may need experimentation).

#### MS-DOS 7.10 / Win95 OSR2 (msdos71)

- MS-DOS 7.10 was never sold as a standalone product — it shipped only
  inside Windows 95 OSR2/OSR2.1/OSR2.5 (build 4.00.1111+) and Windows 98.
- dosforge sources install files from a Win95 OSR2 floppy set in
  `dosassets/w95/` (see that folder's readme.txt for layout).
- Produces a DOS-only boot — no Win95 GUI Setup, just IO.SYS / MSDOS.SYS /
  COMMAND.COM + a CONFIG.SYS that bypasses WIN.COM.
- Supports FAT16 (≤2 GiB) and FAT32 (above) on IDE controllers.

#### IBM PC-DOS 7.1 (pcdos71)

- The only PC-DOS variant with FAT32 + LBA support.
- Uses a QEMU-driven `FORMAT32 /S` install (see
  [vogons.org/viewtopic.php?t=93030](https://www.vogons.org/viewtopic.php?t=93030)).
- FULL install profile hydrates `C:\DOS\` with PC-DOS 2000 utilities
  merged into the SGTK base (EMM386, DOSSHELL, MEMMAKER, etc.) — the
  *one* exception to dosforge's no-cross-DOS-borrowing rule.

#### IBM DOS 3.3 / 5.0 (ibm8088)

- FAT16-only legacy profile.
- `dos33` max 32 MiB; `dos50` max ~504 MiB.
- Assets can be direct files or floppy images.
- DOS 3.3 IMG system-format auto-aligns to install-media geometry and
  stages only core system files.

#### MS-DOS 3.3 / 3.31 / 5.0 / 6.22

Resolver accepts either:
- `IO.SYS` + `MSDOS.SYS` + `COMMAND.COM`, or
- `IBMBIO.COM` + `IBMDOS.COM` + `COMMAND.COM`

plus `BOOTSECT_FAT16.BIN`, or install images (`*.img` / `*.ima` /
`*.dsk` / `*.xdf`), or a WinWorldPC `.7z` (auto-extracted).

For **VHD** targets sourced from install images, dosforge keeps DOS
mode behavior strict and normalizes legacy floppy-style FAT12 boot
sectors to a DOS HDD-compatible FAT16 VBR for `IO.SYS`/`MSDOS.SYS`
profiles before boot staging.

`--dos-install-profile`:
- `minimal` (default): stage boot-critical system files only.
- `full`: stage root `CONFIG.SYS` / `AUTOEXEC.BAT` (from media when
  available, otherwise generated defaults) plus a curated core DOS
  utility set under `\DOS` (e.g. `EDIT`, `QBASIC`, `E`, `CHKDSK`,
  `SUBST`, `FDISK`, `FORMAT`, `SYS`, `XCOPY`).  Compressed `*_` install
  files are expanded; `CONFIG.SYS`/`AUTOEXEC.BAT`-referenced
  commands/drivers are prioritized for inclusion.

#### PC-DOS / PC-DOS 7.0 / PC-DOS 2000 / Compaq DOS 3.31

Same resolver as the MS-DOS family.  For PC-DOS 7.0 install sets,
SaveDskF-wrapped `.DSK` sources are unpacked to raw floppy payload
automatically.  When install images are present in the assets
directory, PC-DOS 7.0 system files are extracted live at create-time
(preferred over stale pre-extracted files).  PC-DOS 7.0 system-format
keeps the user-selected floppy geometry.

`--dos-install-profile` works for these modes too.

## Compatibility guardrails

- FAT12 IMG: **160 KiB .. 2.88 MiB** (floppy presets only)
- FAT12 VHD: **MFM controller only** + ≤16 MiB partition (DOS 2.x era)
- FAT16 VHD: **16 MiB .. 2 GiB**
- FAT32 VHD: **64 MiB minimum** (up to 2 TiB)
- IMG mode uses fixed floppy capacities and FAT12 geometry with
  explicit BPB/media profile checks
- Legacy DOS profiles enforce FAT16-compatible boot workflows on IDE
- MFM controller restricts to XT-era DOS (compaq2 / msdos33 / pcdos /
  ibm8088+dos33) — anything else raises a clear `ValidationError`

## Custom payload directory

- Use `--custom-payload-path <directory>` to copy that directory's
  **contents** into the created filesystem root.
- Directory structure is preserved recursively, including hidden entries.
- For **IMG/IMA**, dosforge checks available free space on the formatted
  image and errors if payload does not fit.
- For **VHD**, if the requested size is too small, dosforge automatically
  grows the VHD size to fit payload + safety buffer.
- When combined with DOS system-format, boot/system files are installed
  first, then custom payload content is copied.
- VCS metadata (`.git*`, `.DS_Store`, `Thumbs.db`, `__pycache__/`,
  `.svn/`, `.hg/`, etc.) is automatically filtered out.

## State paths

- Linux: `~/.local/state/dosforge/state.json`,
  mount points under `~/.local/state/dosforge/mounts/`
- Windows: `%LOCALAPPDATA%\dosforge\` (state + asset cache)

List active mounts:

```bash
dosforge list-mounts
```

## Development

Run tests:

```bash
pytest -q
```

Run native Linux floppy integration tests (real loop-mount + fsck checks):

```bash
DOSFORGE_RUN_NATIVE_IMG_TESTS=1 pytest -q -m native_linux
```

Run native VHD/IMG boot integration matrix tests (QEMU boot-stage + failure-signature probes):

```bash
# Optional if assets are not in ./freedos
export DOSFORGE_NATIVE_FREEDOS_ASSETS=/path/to/freedos-assets

pytest -q -m native_boot
```

Run 86Box parity lane (external command contract):

```bash
# The command must include {image} and print emulator console/log
# output to stdout/stderr.
export DOSFORGE_86BOX_BOOT_COMMAND='86Box --headless --config /path/to/86box.cfg --image {image}'
pytest -q -m native_86box
```

### Native boot matrix test plan

1. Create bootable media from a generated matrix:
   - VHD: all supported boot modes across FAT16/FAT32 where valid,
     IDE + MFM controllers.
   - IMG: system-format floppy combinations across supported boot
     modes/geometries.
2. Boot each artifact in QEMU (`qemu-system-i386`) via `-nographic`
   for a bounded window.
3. Require expected boot stage (`Booting from Hard Disk` or
   `Booting from Floppy`) and fail on explicit boot-failure signatures.
4. Fail immediately if known boot failure signatures appear (e.g.
   `This is not a bootable disk`, `Non-System disk or disk error`,
   `Disk I/O error`).
5. Include QEMU output tail in failure details for quick triage.
6. Persist per-case diagnostics in each test tmp path
   (`*.command.txt`, `*.returncode.txt`, `*.output.log`).

`native_86box` remains the prompt-proof lane.  When
`DOSFORGE_86BOX_BOOT_COMMAND` is configured, the test is active and
must reach a DOS prompt marker.

### Trailer cleanup hooks (optional)

The trailer-cleanup script itself lives in the shared
[`~/Projects/shared-scripts/`](../shared-scripts/) folder so it can be
reused across repos. Set `SHARED_SCRIPTS` to override the default
`$HOME/Projects/shared-scripts` location.

If you want local hooks that strip the Copilot co-author trailer on
commit (`commit-msg`) and also enforce cleanup before push:

```bash
./scripts/install-githooks.sh
```

Manual dry-run check:

```bash
~/Projects/shared-scripts/strip-copilot-coauthor.sh --range HEAD --dry-run
```

## Version

dosforge tags follow `v<X.Y.Z>` (single combined tag — was
`linux-v<X.Y.Z>` + `windows-v<X.Y.Z>` before v0.7.2).  Every release
produces one GitHub release with all platforms' assets attached:

- `dosforge-<X.Y.Z>-linux.tar.gz` — Linux bundle (wheel + sdist + installer)
- `dosforge-<X.Y.Z>-py3-none-any.whl` — Linux pip wheel
- `dosforge-<X.Y.Z>-windows-x64.zip` — Windows full bundle (CLI + GUI + DOSBox-X + QEMU)
- `dosforge-<X.Y.Z>-cli-windows-x64.zip` — Windows CLI-only bundle

Browse the latest release at
[github.com/flynnsbit/dosforge/releases/latest](https://github.com/flynnsbit/dosforge/releases/latest)
or grab specific release notes from
[`releases/v<X.Y.Z>-release-notes.md`](releases/).
