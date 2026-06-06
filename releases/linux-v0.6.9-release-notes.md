# dosforge v0.6.9 — Linux

Linux benefits from the same fix shipped in Windows v0.6.9:
`src/dosforge/pcdos2000_extract.py` now extracts `.7z`/`.zip` PC-DOS
2000 archives in-process via `py7zr`/`zipfile` instead of shelling out
to an external `7z` binary. On Linux this removes the hard `p7zip`
runtime dependency for the FULL pcdos71 profile.

See `releases/windows-v0.6.9-release-notes.md` for the full Windows
story.
