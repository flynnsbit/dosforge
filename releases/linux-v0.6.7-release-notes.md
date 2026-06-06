# dosforge v0.6.7 — Linux

Version bump to keep Linux + Windows release tags in lockstep with the
v0.6.7 Windows fix. No runtime Linux changes — the Linux backend already
finds `dosbox-x` on `PATH` and isn't affected by the Windows bundle
layout bug.

See `releases/windows-v0.6.7-release-notes.md` for the full story
(short version: Windows v0.6.5/v0.6.6 shipped `dosbox-x.exe` without
its support files, so PC-DOS 2000 hydration silently failed; v0.6.7
ships the full DOSBox-X mingw portable tree).

## Internal changes touching shared files

- `scripts/fetch-windows-vendor.py` — new `from_in_archive_tree` extract
  mode (Windows-only manifest, no Linux impact).
- `vendor/windows/manifest.json` — dosbox-x now stages a whole subtree
  (Windows-only).
- `src/dosforge/_platform/windows.py` — `tool_path("dosbox-x")` returns
  the new subdir path (Windows backend only).
- `.github/workflows/release.yml` — Windows CI smoke check tightened.
