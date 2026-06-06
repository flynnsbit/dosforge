# dosforge linux-v0.6.12 — parity bump for Windows DOSBox-X fix

Linux parity release accompanying `windows-v0.6.12`. The Windows fix
swaps the bundled DOSBox-X binary from the "OS-Free" variant to the
standard MinGW64 build (which has built-in MS-DOS emulation) so the
PC-DOS 7.1 FULL profile hydration pipeline can run UNPACK2 against
PC-DOS 2000 FTCOMP pack files.

**Linux is unaffected** — it uses the distro's `dosbox-x` package
(`apt install dosbox-x` / `pacman -S dosbox-x`), which has always
been the standard build. No code changes here.

This release ships purely so:

1. Linux and Windows versioning stay in lockstep.
2. The `releases/<tag>-release-notes.md` convention has a notes file
   when CI auto-creates the GitHub release.
3. Users grepping the changelog see the Windows fix mentioned.

## Same code as `linux-v0.6.11`

Every feature and fix from `linux-v0.6.11` ships unchanged:

- `mcopy` destination passed as `.` (not `./`) — fixed v0.6.11.
- mtools cwd= + relative-path workaround for Windows drive-alias
  parser — fixed v0.6.10 (no effect on Linux, where mtools is
  POSIX-built).
- In-process `.7z` extraction via `py7zr` — fixed v0.6.9.
- PC-DOS 2000 hydration parity work — landed v0.6.5 → v0.6.11.

## Upgrade

```bash
cd releases/v0.6.12
chmod +x install.sh
./install.sh
```

Or in-place:

```bash
python -m pip install --user --upgrade releases/v0.6.12/dosforge-0.6.12-py3-none-any.whl
```

## See also

- `releases/windows-v0.6.12-release-notes.md` — the actual fix.
