# dosforge v0.6.1 — Linux release (sudo + TUI fixes)

Focused bug-fix release on top of `linux-v0.6.0`. No backend boot-mode
changes; all 16 VHD boot modes validated in 86Box for `linux-v0.6.0`
continue to apply.

## Highlights

### Sudo handling — prompt once, keep alive

Headless CLI invocations of `dosforge create`, `dosforge mount`, and
`dosforge unmount` now run the same startup `sudo -v` prompt the
TUI/GUI have always used, so a single password entry primes the
whole command. A background `SudoKeepAlive` daemon refreshes the
kernel sudo timestamp cache every 60 seconds while a build or mount
is in progress, so long operations (PC-DOS 7.1 FAT32 install,
Win95 OSR2 SYS) no longer fail when the default 5-minute
`timestamp_timeout` expires mid-flight.

No `NOPASSWD` sudoers entries are required. Previous documentation
that recommended adding a `dosforge-mformat` sudoers drop-in was
incorrect — `mformat` and the other mtools have always run as the
user (`<image>@@<offset>` syntax). Error messages and
`dosforge sudo-check` guidance now point users at `sudo -v` instead.

### TUI dropdowns open on the first click

Replaced the wizard's `Select` widgets with a `SingleClickSelect`
subclass that opens the overlay on `MouseDown` and calls
`event.prevent_default()` from its `SelectCurrent.Toggle` handler
to suppress the parent `Select`'s default toggling handler (which
would otherwise race-close the menu on the synthesized click that
follows mouse-up). One click now opens the dropdown the way
the form has always intended.

### TUI focused buttons no longer flash inverted text

Dropped `reverse` from `Button.btn-primary:focus` and set
`ALLOW_SELECT = False` on `DosForgeApp`, so focused primary
buttons stay bold instead of swapping foreground/background, and
click-drag no longer paints a text-selection marquee across the
screen.

## Upgrade

```bash
cd releases/v0.6.1
./install.sh    # Arch + Ubuntu distro-aware system-dep installer + pip install
```

Or upgrade in place:

```bash
python -m pip install --user --upgrade releases/v0.6.1/dosforge-0.6.1-py3-none-any.whl
```

## Validated in 86Box

Same matrix as `linux-v0.6.0` — every supported boot mode × FAT
combination boots to a DOS prompt:

| Boot mode    | FAT16 (32 MiB)        | FAT32 (128 MiB+)        |
|--------------|-----------------------|-------------------------|
| `freedos`    | ✅                    | ✅                      |
| `msdos33`    | ✅                    | n/a                     |
| `msdos331`   | ✅                    | n/a                     |
| `compaq331`  | ✅                    | n/a                     |
| `msdos5`     | ✅                    | n/a                     |
| `msdos622`   | ✅                    | n/a                     |
| `msdos71`    | ✅                    | ✅                      |
| `pcdos`      | ✅                    | n/a                     |
| `pcdos7`     | ✅                    | n/a                     |
| `pcdos71`    | ✅                    | ✅ (1 GiB+)             |
| `ibm8088`    | ✅ (DOS33 + DOS50)    | n/a                     |
| `4dos`       | ✅ (overlay on host)  | ✅ (overlay on host)    |
