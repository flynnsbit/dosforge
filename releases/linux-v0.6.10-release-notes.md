# dosforge v0.6.10 — Linux

Parity bump with Windows v0.6.10. The mcopy destination-path change
also applies on Linux (passing `cwd=` + relative `./` is more robust
than absolute paths in mtools arguments). No behavioral change for
Linux users — the absolute path worked there because typical Linux
staging dirs don't begin with `<letter>:`.

See `releases/windows-v0.6.10-release-notes.md` for the full Windows
story.
