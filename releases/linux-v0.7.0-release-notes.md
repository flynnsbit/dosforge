# dosforge linux-v0.7.0 — Controller-first VHD organization (BREAKING CHANGE)

Parity bump for the v0.7.0 controller-first reorganization shipped
in windows-v0.7.0.  All schema, validation, and CLI changes live
in shared modules (`models.py`, `disk.py`, `cli.py`, `formlogic.py`)
so Linux behavior matches Windows exactly.

See the windows-v0.7.0 release notes for the full migration table,
new flag reference, validation matrix, and roadmap.

## 🚨 Breaking changes (recap)

The following CLI flags are **REMOVED** in v0.7.0:
- `--machine-target`
- `--martypc-xebec-drive-type`
- `--martypc-at-drive-type`

Migrate user scripts using this mapping:

```
# Was:
dosforge create --machine-target martypc-xebec \\
    --martypc-xebec-drive-type type1 ...

# Now:
dosforge create --disk-controller mfm \\
    --bios-drive-type phoenix:1 ...
```

```
# Was:
dosforge create --machine-target martypc-xtide \\
    --martypc-at-drive-type at-1024-16-63 ...

# Now:
dosforge create --custom-chs 1024,16,63 ...
```

The breaking change is a clean break — user scripts using the old
flags will fail with ``unrecognized arguments``.  No silent
compatibility shim.

## Linux-specific notes

- All v0.7.0 behavior lives in shared modules; no Linux-only logic.
- Linux build of the new path:

  ```
  dosforge create --media-type vhd --boot-mode compaq2 \\
      --format fat12 \\
      --disk-controller mfm --bios-drive-type phoenix:1 \\
      --path ~/compaq2-mfm.vhd
  ```

- Linux NBD pipeline applies the same controller-aware MBR / BPB
  layout as the Windows VHD pipeline.

## Tests

208 focused tests pass.
