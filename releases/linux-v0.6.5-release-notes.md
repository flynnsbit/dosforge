# dosforge linux-v0.6.5 — PC-DOS 2000 hydration accepts raw IMGs

Companion to `windows-v0.6.5`. Pure improvement to the shared
PC-DOS 7.1 hydration code; Linux users who pre-extracted their IBM
PC-DOS 2000 archive into `dosassets/pcdos2000/` can now use the loose
floppies directly without re-archiving.

## What changed (shared with windows-v0.6.5)

- `pcdos2000_extract.py` gains `find_pcdos2000_source()` and
  `find_pcdos2000_disk_dir()`. The fetcher now finds the install
  source as **either**:
  - the WinWorldPC `IBM PC-DOS 2000 (3.5-1.44mb).7z` archive, OR
  - a directory containing at least 5 of `disk01.img`..`disk06.img`.
- `extract_pcdos2000_utilities()` accepts both — when handed a
  directory, it skips the 7z step and goes straight to mcopy →
  UNPACK2-in-DOSBox-X → blacklist filter.
- Cache key for the directory case is a stable hash of every disk's
  (name, size, first-64KB) so re-runs with the same six floppies hit
  the cache.
- 7-Zip is no longer a hard dependency when the user has loose IMGs.

DOSBox-X and mtools are still required for the actual UNPACK2 step
(install via your distro's package manager — `apt install dosbox-x
mtools`, `dnf install dosbox-x mtools`, `pacman -S dosbox-x mtools`).

## Carries forward

Everything from linux-v0.6.4 (no functional changes for Linux there;
that release was the Windows-bundle layout fix).

## Install

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install dosforge-0.6.5-py3-none-any.whl

# Either:
cp ~/Downloads/IBM\ PC-DOS\ 2000\ \(3.5-1.44mb\).7z dosassets/pcdos2000/
# Or:
cp ~/Downloads/pcdos2000-floppies/disk0*.img dosassets/pcdos2000/

# Then run the GUI / TUI / CLI and click "Fetch PC-DOS 7.1 (SGTK) assets"
dosforge gui
```
