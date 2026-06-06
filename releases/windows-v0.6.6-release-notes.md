# dosforge windows-v0.6.6 — fix v0.6.5 CLI smoke check

v0.6.5's CI smoke check required `dosbox-x.exe` in **both** Windows
bundle variants. The CLI variant (`dosforge-cli.spec`) intentionally
omits it — the slim CLI bundle ships only `qemu-img.exe` + mtools
plus their direct DLL closure. Result: the FULL bundle for v0.6.5
published successfully but the CLI bundle failed to publish.

This release re-runs both variants with the smoke check corrected
to require `dosbox-x.exe` **only** in the full variant (and detect
leaks the other way for CLI).

Same functional changes as v0.6.5:
- DOSBox-X v2026.06.02 mingw64 bundled in `vendor\windows\bin\`.
- PC-DOS 2000 hydration accepts raw `disk01.img`..`disk06.img` in
  `dosassets\pcdos2000\` in addition to the WinWorldPC `.7z` archive.
- `find_pcdos2000_source()` finds either source automatically.

See `windows-v0.6.5-release-notes.md` for the full hydration details.
