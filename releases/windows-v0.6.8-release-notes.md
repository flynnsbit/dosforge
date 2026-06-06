# dosforge v0.6.8 — Windows

Follow-up to v0.6.7 that ALSO fixes the PyInstaller staging of the
DOSBox-X support files.

## What v0.6.7 missed

v0.6.7 correctly fetched the full DOSBox-X mingw portable tree into
`vendor/windows/bin/dosbox-x/`, but `windows/dosforge.spec` passed every
`rglob`'d file with target `"vendor/windows/bin"` (flat) — so PyInstaller
copied all 154 nested files into `vendor/windows/bin/` with collisions,
and `dosbox-x.exe` ended up missing entirely from the bundle. CI smoke
check caught this.

## v0.6.8 fix

`windows/dosforge.spec`: preserve relative subdirectory structure when
adding `vendor/windows/bin/` entries to `datas`, matching the pattern
already used for `dosassets/`. After this fix the bundle contains
`_internal/vendor/windows/bin/dosbox-x/dosbox-x.exe` (and its `languages/`,
`glshaders/`, `drivez/`, etc. siblings) exactly as the runtime expects.

## Verification

Same as v0.6.7 — drop your raw PC-DOS 2000 floppies into
`dosforge\dosassets\pcdos2000\`, click **Fetch PC-DOS 7.1 (SGTK) assets**,
and `C:\DOS\` should end up with ~138 files (EMM386, POWER, DOSSHELL,
DEFRAG, etc. layered over the SGTK base, SGTK wins on conflict).
