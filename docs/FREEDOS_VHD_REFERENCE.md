# FreeDOS/MS-DOS VHD Reference

This documents the fixes that were implemented to make `dosforge` reliably create and mount DOS-compatible VHDs on Omarchy Linux.

## Changes made to get it working

| Area | Problem observed | Fix implemented | Main file(s) |
| --- | --- | --- | --- |
| NBD device discovery | `No /dev/nbd* devices are available` | Added automatic NBD module load attempt: `modprobe nbd max_part=16`, plus clearer failure guidance if devices still do not appear. | `src/dosforge/disk.py` |
| TUI lockups on privilege prompts | `sudo` password prompt caused hangs/errors in TUI | Switched disk operations to non-interactive sudo behavior and added preflight auth check with clear `sudo -v` guidance. | `src/dosforge/disk.py`, `README.md` |
| Mount/connect format mismatch | `qemu-nbd` guessed `raw` and restricted writes | Added explicit image format selection (`qemu-nbd --format ...`) and `qemu-img info` probing before connect. | `src/dosforge/disk.py` |
| Fixed VHD misdetected as raw | Some fixed `.vhd` images behaved like raw during attach | Forced create-flow attach as `vpc` and added VHD footer check (`conectix`) so raw-probed fixed VHDs are treated as `vpc`. | `src/dosforge/disk.py` |
| Python 3.14 TUI crash | `TypeError: Subscripted generics cannot be used with class and instance checks` from `Select[str]` in `query_one` | Replaced runtime widget queries to use `Select` (non-subscripted) and cast values after lookup. | `src/dosforge/app.py` |
| FreeDOS setup friction | Manual boot asset prep was cumbersome | Added TUI button to fetch FreeDOS assets directly into `./freedos` and auto-fill local assets path. | `src/dosforge/app.py`, `src/dosforge/disk.py`, `src/dosforge/boot.py` |
| Missing full FreeDOS payload | Needed full `C:\FDOS` style content, not only kernel/command files | Added package download/extract pipeline for FreeDOS 1.4 repositories and copy into `FDOS/` for transfer to VHD. | `src/dosforge/boot.py` |
| FAT32 template availability | FAT32 boot template handling was inconsistent | Added generation/export of `BOOTSECT_FAT32.BIN` during FreeDOS fetch and validation in boot asset resolver. | `src/dosforge/boot.py` |
| FAT32 non-bootable sectors | Generic FAT32 boot sector often displayed “This is not a bootable disk” | Added preference for extracting FAT32 boot sector from a local known-good FreeDOS FAT32 `.vhd` before fallback to generated template. | `src/dosforge/boot.py` |
| HDD boot chain incomplete | Disk still not bootable in some cases | Marked partition active and wrote syslinux MBR boot code (`mbr.bin`) to disk. | `src/dosforge/disk.py`, `src/dosforge/boot.py` |
| DOS system file semantics | Plain copy behavior was not fully DOS-like | Copied boot/system files with `mcopy` and set system+hidden attributes via `mattrib` for key system files. | `src/dosforge/boot.py` |
| Command interpreter failure at boot | `Bad or missing Command Interpreter` with `A:\COMMAND.COM` | Normalized `CONFIG.SYS` shell lines to `SHELL=C:\COMMAND.COM ...` during asset fetch and again during final file staging to VHD. | `src/dosforge/boot.py` |
| FAT16 startup stuck at `FreeDOS_` | Boot reached shell prompt but startup batch did not execute | Stopped injecting `CONFIG.SYS` shell switches that disable/override startup (`/D`, forced `/K ...`) and upgraded FAT16 boot path to prefer full FreeDOS core binaries (`FDOS\BIN\COMMAND.COM`, `KERNL386.SYS`) instead of floppy-minimal copies. | `src/dosforge/boot.py` |
| FAT16 early boot freeze from geometry mismatch | FAT16 VHDs hung around `ROOT/FAT/KERNEL/GO!` or right after `FreeDOS` in strict emulators | During FAT16 create flow, read CHS geometry from fixed VHD footer (`conectix`) and patch FAT BPB geometry fields (`sectors/track`, `heads`) after boot-sector install so BIOS geometry and BPB agree. | `src/dosforge/disk.py`, `src/dosforge/boot.py` |
| FAT16 installer-vs-template boot mismatch | Manual FreeDOS-installed FAT16 VHD booted, template-built VHD did not | Added installer-style FAT16 boot-record automation: prefer extracted VBR+MBR from local known-good FreeDOS FAT16 `.vhd`, cache for reuse, and fall back to built-in installer-style FAT16 MBR/VBR records when no reference VHD is present. | `src/dosforge/boot.py` |
| File browser UX | Browser didn’t start where app was launched | Set browser root to `Path.cwd()` so launch directory is the initial tree root. | `src/dosforge/app.py` |

## Current boot pipeline (FreeDOS)

1. Create fixed-size VHD (`qemu-img`, fixed `vpc`).
2. Connect through NBD with explicit format.
3. Partition MBR disk, create primary FAT partition, set partition boot flag.
4. Format FAT16/FAT32.
5. Write MBR boot code (prefer FAT16 asset/reference `MBR_FAT16.BIN` when available, otherwise syslinux `mbr.bin`) and partition boot sector template (prefer installer-style FAT16 reference VBR when available).
6. Copy boot files (`KERNEL.SYS`, `COMMAND.COM`, optional `CONFIG.SYS`, etc.) with DOS-aware tools (preferring `FDOS\BIN` core binaries when available).
7. Mark required system files hidden/system where applicable.
8. Copy `FDOS/` payload to `\FDOS` when present in assets.
9. Ensure `CONFIG.SYS` shell path points to `C:\COMMAND.COM` and does not contain startup-disabling `/D` or forced `/K ...` overrides.
10. For FAT16 on fixed VHDs, patch BPB geometry values from VHD footer CHS to keep boot code geometry consistent.

## Notes for FAT32 FreeDOS images

- Prefer local FreeDOS assets mode with a valid `BOOTSECT_FAT32.BIN`.
- The fetch flow now produces `BOOTSECT_FAT32.BIN`, but if a known-good local FAT32 FreeDOS `.vhd` exists in the working area, its boot sector is preferred.
- If an image boots but shell fails, inspect `CONFIG.SYS` and ensure `SHELL=C:\COMMAND.COM` is present.

## Related docs

- Main usage and troubleshooting: `README.md`
