# dosforge windows-v0.6.12 — fix PC-DOS 7.1 hydration: swap to standard DOSBox-X build

End of the v0.6.7→v0.6.11 fix chain. The PC-DOS 7.1 FULL profile now
produces the expected ~138-file `C:\DOS\` on Windows, matching Linux.

## Root cause: wrong DOSBox-X build

`vendor/windows/manifest.json` was pointing at the **"OS-Free" variant** of
DOSBox-X 2026.06.02:

```
dosbox-x-mingw64-dosbox-x-v2026.06.02-osfree-portable.zip
```

DOSBox-X publishes two parallel Windows builds for every release:

| Variant | Built-in MS-DOS? | Typical use |
|---|---|---|
| `osfree` | **No** | Boot real DOS images (PC-DOS / MS-DOS / FreeDOS) |
| Standard (`-portable`) | **Yes** | Run DOS programs without supplying a DOS image |

dosforge's hydration pipeline drives `UNPACK2.EXE` via a DOSBox-X
`[autoexec]` script that runs `MOUNT C ...`, then `UNPACK2 C:\DOS1
D:\OUT`, etc. Those autoexec commands need built-in MS-DOS emulation,
which the OS-Free build does not provide. Result:

```
LOG: DOSBox-X OS-Free build -- Built-in MS-DOS emulation is not available
```

The autoexec section was being silently no-op'd. `D:\OUT` stayed
empty. The hydration logged `DOSBox-X UNPACK2 produced no output
files`. Every Windows v0.6.7+ build had this latent bug; the previous
fixes (PyInstaller staging, in-process .7z extraction, mcopy path
quoting, mcopy trailing-slash) all moved the pipeline forward but
couldn't surface this last problem until file harvesting actually
worked.

## Fix

Manifest now downloads the standard MinGW64 portable build:

```
dosbox-x-mingw64-2026.06.02-portable.zip
SHA-256: be4faa5edd5980159ed4dfa8c803269beb29a58f02190b6b3ee1a8f52ae57235
```

Same release tag (`dosbox-x-v2026.06.02`), same `mingw-build/mingw`
subdir layout in the archive, same on-disk files at runtime — just
with built-in DOS emulation enabled. The PyInstaller spec, the
runtime resolver, the hydration code, and the rest of the manifest
are unchanged.

## Verification on Windows

After swapping the binary into a v0.6.11 bundle (clean
`%LOCALAPPDATA%\dosforge\cache\` first):

```
== Summary ==
  DOS files staged:    40/40         (SGTK)
  Install floppy:      tk_raid.vfd
[pcdos71] hydrating_pcdos2000
  found PC-DOS 2000 source: IBM PC-DOS 2000 (3.5-1.44mb).7z
  extracting IBM PC-DOS 2000 (3.5-1.44mb).7z…
  found 6 install floppies in archive
  harvested 66 files from floppies
  unpacking DOS1, DOS2, DOS3, DOS4, SHELL1, SHELL2 via DOSBox-X…
  staged 131 PC-DOS 2000 utilities to <cache>/DOS
  merged PC-DOS 2000 utilities: 98 added, 33 skipped (SGTK wins)
done
```

Final `C:\DOS\` contents: **138 files** (40 SGTK + 98 added). 17 of
18 expected utility files present:

```
+ BACKUP.COM     + COMMAND.COM   + DEFRAG.EXE    + DOSSHELL.EXE
+ EMM386.EXE     + FORMAT.COM    + FORMAT32.COM  + HELP.COM
+ HIMEM.SYS      + IBMBIO.COM    + IBMDOS.COM    + INTERLNK.EXE
+ INTERSVR.EXE   + POWER.EXE     + PRINT.COM     + RESTORE.COM
+ UNDELETE.EXE
- MEMMAKER.EXE  (PC-DOS 2000 never shipped MEMMAKER; expected absent)
```

Full pipeline: ~97 s end-to-end with the standard build (SGTK fetch
+ PC-DOS 2000 archive extraction + 6 UNPACK2 passes inside DOSBox-X
+ merge with SGTK precedence).

## Build / run

```powershell
# Extract dosforge-0.6.12-windows-x64.zip somewhere convenient
cd dosforge

# One-time: fetch SGTK + hydrate from PC-DOS 2000 (requires the
# WinWorldPC archive in dosassets\pcdos2000\):
.\dosforge fetch-pcdos71-assets

# Build a 1 GiB PC-DOS 7.1 FAT32 VHD with the full 138-file C:\DOS\:
.\dosforge create --media-type vhd --boot-mode pcdos71 ^
    --format fat32 --size 1G ^
    --path C:\my-vhds\pcdos71-1g.vhd
```

The GUI's *Fetch PC-DOS 7.1 (SGTK) assets* button (`dosforge-gui.exe`,
New Disk → Boot card) runs the same fixed pipeline.

## Authenticity

Same exception as `windows-v0.6.7`+: PC-DOS 7.1 FULL profile is the
ONE approved cross-DOS-borrowing case — PC-DOS 2000 utilities merge
into `C:\DOS\` with SGTK winning every filename conflict, all files
authentic IBM binaries (PC-DOS 7.10 from SGTK OR PC-DOS 2000 from
WinWorldPC, never synthetic, never FreeDOS). No other boot mode
borrows.

## What's in the zip

- `dosforge.exe` — CLI + TUI launcher (full variant only).
- `dosforge-gui.exe` — Tk desktop GUI with the SGTK fetcher button.
- `_internal/vendor/windows/bin/dosbox-x/dosbox-x.exe` —
  **standard MinGW64 build with built-in DOS emulation** (23.5 MB
  instead of the 17.8 MB OS-Free build).
- `dosassets/<mode>/readme.txt` — 29 pre-populated mode folders.

## Companion Linux release

`linux-v0.6.12` parity bump (no Linux code changes — Linux uses the
distro's `dosbox-x` from `apt install dosbox-x` and was never
affected by this bug).

SHA-256 checksums listed below per artifact.
