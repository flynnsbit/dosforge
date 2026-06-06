# dosforge linux-v0.6.13 — parity bump for Windows FreeDOS FAT32 fix

Linux parity release accompanying `windows-v0.6.13`. The Windows fix
removes a stale `freedos + fat32` guard from the Windows VHD pipeline
that has been a "known limitation" on Windows since `windows-v0.6.0`.

**Linux is unaffected** — the Linux VHD pipeline
(`_create_and_prepare_vhd_with_nbd`) routes FreeDOS FAT32 through
`parted` + `mkfs.fat -F 32` + the shared
`BootInstaller.make_partition_bootable` helper, which has always
handled FAT32 correctly. No code changes here.

This release ships purely so:

1. Linux and Windows versioning stay in lockstep.
2. The `releases/<tag>-release-notes.md` convention has a notes file
   when CI auto-creates the GitHub release.
3. Users grepping the changelog see the Windows fix mentioned.

## Same code as `linux-v0.6.12`

Every feature and fix from `linux-v0.6.12` ships unchanged.

## Upgrade

```bash
cd releases/v0.6.13
chmod +x install.sh
./install.sh
```

Or in-place:

```bash
python -m pip install --user --upgrade releases/v0.6.13/dosforge-0.6.13-py3-none-any.whl
```

## See also

- `releases/windows-v0.6.13-release-notes.md` — the actual fix.
