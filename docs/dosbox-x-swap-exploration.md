# Feature Exploration: Swapping QEMU → DOSBox-X for the Legacy DOS Install Path

**Status:** Exploration / not scheduled
**Author:** captured from the abandoned `feature/dosbox-x-swap` branch
(commits `edb63e4`, `fd83bbf`, `3825840`), reconciled against `main` @ v0.9.57
**Date:** 2026-06-19 (rev 2 — added §3 QEMU-usage map + §4 features analysis)

---

## 1. Summary

dosforge installs "legacy" DOS system files (the ones whose own
`FORMAT C: /S` must lay down the boot sector + IO/MSDOS/COMMAND from
authentic install media) by booting a throwaway DOS install diskette
inside an emulator and driving `FORMAT`/`SYS` against the target disk
image. On Windows that emulator is **`qemu-system-i386.exe`**.

The proposal is to replace `qemu-system-i386` with **DOSBox-X** for the
install step, using `IMGMOUNT` + `BOOT A:` to run the install diskette,
then `IMGMOUNT C:` to receive the system files.

The motivating number: on Windows, `qemu-system-i386.exe` drags in
**~110 MB of GTK / SDL / codec / Spice / virgl / USB / NSS DLLs** that
Windows resolves at process-load time — even though dosforge only ever
launches it headless (`-display none -nic none -serial file:`). DOSBox-X
ships as a single, statically-linked **~24 MB** portable EXE.

---

## 2. Important context: DOSBox-X is already a bundled dependency

This is the single most important fact for evaluating the swap, and it
changed since the original branch was cut:

- **`main` already bundles `dosbox-x.exe`** — it is in
  `_KNOWN_BUNDLED_TOOLS` with bespoke `tool_path` resolution in
  `src/dosforge/_platform/windows.py` (it lives in
  `vendor/windows/bin/dosbox-x/` with its support files), and it is
  pinned + SHA-verified in `vendor/windows/manifest.json`.
- The codebase even contains a **DOSBox-X boot-probe harness**
  (`src/dosforge/_boot_probe.py` `run_boot_probe`) that imgmounts a
  built VHD/IMG and confirms it boots. **Caveat (verified this session):**
  that harness is currently **only called by a test**
  (`tests/test_dos_boot_smoke.py`) — it is *not* wired into the create or
  grow runtime. The "Headless boot probe" step users see in grow logs is
  the **QEMU**-based `_grow_impl._run_boot_probe`, not this DOSBox-X one
  (see §3).

**Consequence:** the swap would **not** add a new vendor dependency.
DOSBox-X is already shipped, fetched, pinned, and SHA-verified. The swap
is about *also* using it for install (and, optionally, wiring its probe
harness into the runtime), which would let us **drop** `qemu-system-i386`
+ its DLL stack entirely. The branch's "add DOSBox-X" cost is already
sunk on `main`; only the upside remains.

---

## 3. What uses `qemu-system-i386` today

> Verified by call-site audit against `main` @ v0.9.57 (2026-06-19).

First, a distinction that matters: dosforge bundles **two different QEMU
binaries**, and only one is the swap target.

| Binary | Size | Role | Swap target? |
|---|---|---|---|
| **`qemu-img`** | small | VHD allocation, footer CHS, `qemu-img info` | **No — stays.** Tiny, no DLL stack, used everywhere. |
| **`qemu-system-i386`** | ~110 MB w/ DLLs | full PC system emulator | **Yes** — this is the bloat. |

`qemu-system-i386` has exactly **three** call sites:

| # | Use | Location | Runtime? | Touches authoritative disk bytes? |
|---|---|---|---|---|
| 1 | **Legacy DOS install** — boots a throwaway install diskette (`-boot a`, floppy + target VHD attached), runs the DOS's own `FORMAT C: /S` to write the boot sector + IO/MSDOS/COMMAND from authentic media. **16 boot modes** route here (`_LEGACY_DOS_INSTALL_DESCRIPTORS`). | `legacy_dos_install.py` → `LegacyDosQemuInstaller._run_qemu` | ✅ Yes | ✅ **Yes — authenticity-critical** |
| 2 | **Grow boot-probe** — boots a grown VHD headless (`-boot c`), injects a `BOOTPRB.BAT` that echoes a marker to COM1, polls the serial log to confirm the disk still boots. | `_grow_impl.py` → `_run_boot_probe` | ✅ Yes | ❌ No — read-only verify |
| 3 | **e2e boot-probe** — serial failure-marker matcher (`"Missing operating system"`, etc.). | `e2e_emulator.py` → `qemu_boot_probe` | ❌ **Test-only** (imported by `test_e2e_emulator.py`, `test_native_linux_*`) | ❌ No |

Install harness specifics worth knowing (these are what any swap must
preserve): the install runs `-cpu 486 -m 16`, uses
`-machine pc,accel=whpx:tcg` on Windows (WHPX hardware accel, falling
back to software TCG — without it, 16-bit installs that finish in ~30 s
on Linux+KVM need 5–10 min of TCG and blow the timeout), polls a
`VHDMK.OK` marker, and has a Windows-specific re-check because `mdir`
can't open the VHD while QEMU holds an exclusive write handle.

**The size-win constraint:** `qemu-system-i386` can only be *removed from
the bundle* if **all three** uses migrate to DOSBox-X. Use #3 is
test-only (easy). Use #2 is low-risk (read-only) and a DOSBox-X probe
harness already exists. **Use #1 (install) is the blocker** — it writes
the authoritative disk and is the thing the authenticity concern is
about. Until #1 migrates, the 110 MB stays in the bundle regardless of
how many features get added.

---

## 4. Features / capabilities the switch could unlock

Beyond bundle size, DOSBox-X exposes capabilities QEMU-headless does not.
Each is tagged with **which `qemu-system-i386` use it would replace or
extend**, its **authenticity risk**, and **whether it is gated on the
risky install swap (§3 use #1)**.

| # | Capability | Replaces / extends | Authenticity risk | Gated on install swap? |
|---|---|---|---|---|
| 1 | **Interactive "Test drive this disk"** — DOSBox-X can launch a *visible* windowed session, so the GUI/TUI could add a "boot my freshly-created disk and poke at it" button. QEMU-headless in-bundle can't easily offer this on Windows. | New feature (none today) | None (read-only run) | **No** |
| 2 | **Single-emulator consolidation** — today dosforge ships *two* emulators (QEMU for install + grow probe; DOSBox-X bundled for the unused probe). Migrating probe + install to DOSBox-X means one config format, one dependency, one behavior to reason about. | #1, #2, #3 | Low for probe; high for install | Partially |
| 3 | **Deterministic scripted input** (`AUTOTYPE` / config-driven keystrokes) — could replace the brittle serial-console + marker-poll install harness with scripted input, potentially eliminating the Windows WHPX/TCG timeout fragility the current code works around. | #1 (install) | High (install path) | **Yes** |
| 4 | **Richer verification environment** — Sound Blaster, CD-ROM (`IMGMOUNT` ISO), Glide/SVGA, selectable CPU class + cycles. Moves dosforge from "make a DOS disk" toward "make + actually run/test it in a period-accurate DOS environment" (game/app smoke testing). | Extends #2 (probe) / new | None (read-only run) | **No** |
| 5 | **Cross-platform behavioral consistency** — DOSBox-X behaves identically on Windows/Linux/macOS. QEMU's accel differs per OS (WHPX vs KVM vs TCG) and has already caused Windows-specific timeout fragility. A DOSBox-X probe/install would remove that per-OS variance. | #1, #2 | Low for probe; high for install | Partially |
| 6 | **Built-in image tooling** (`IMGMAKE`, mount/convert, FAT ops) — minor; could offload some `mtools`/`qemu-img` edge cases. | Adjacent | Low–medium | No |

### The strategic point: features decouple from the risky install swap

The capabilities split cleanly into two buckets:

- **Safe, do-anytime (no authoritative-byte risk, but NO size win):**
  the interactive **Test drive** (#1), wiring the existing DOSBox-X
  **probe** into create/grow runtime (#2), and the **richer verification
  environment** (#4). None of these touch the install path, so they can
  ship without re-validating authenticity. They do **not** remove
  `qemu-system-i386` (install still needs it), so they yield **no bundle
  shrink** on their own.
- **Risky, gated (the ONLY path to the 110 MB win):** migrating the
  **install** (§3 use #1) to DOSBox-X. This is the sole change that lets
  the bundle drop `qemu-system-i386`, and it is exactly the change that
  requires full authenticity validation across all 16 install modes
  (boot in 86Box AUTO IDE, byte-compare BPB/MBR vs the QEMU reference).

So the answer to *"besides size, what do I gain?"* is: a real
**interactive test-drive / richer verification** product surface — but
those gains are independent of the swap and don't shrink the bundle. The
size win and the install-authenticity risk are inseparable from each
other and separate from the feature wins.

---

## 5. What the abandoned branch actually built

The `feature/dosbox-x-swap` branch (3 commits, ~1000 LOC) contained:

| Component | Purpose |
|---|---|
| `src/dosforge/legacy_dos_dosboxx_install.py` (NEW, ~319 LOC) | DOSBox-X install driver: reuses the QEMU installer's `_prepare_install_floppy` + `_verify_install`, generates a `.conf` with `IMGMOUNT` + `BOOT A:`, runs `dosbox-x.exe -conf <conf> -fastlaunch -exit`. |
| `_platform/base.py` | New `legacy_dos_emulator()` method, defaults to `"qemu"`. |
| `_platform/windows.py` | Returns `"dosbox-x"` when `dosbox-x.exe` is bundled, else falls back to `"qemu"`; `required_commands()` asks for whichever is selected. |
| `disk.py` | Dispatches to `LegacyDosDosBoxXInstaller` vs `LegacyDosQemuInstaller` based on `backend.legacy_dos_emulator()`. |
| `windows/vendor_allowlist.py` (NEW) | Shared 37-file allowlist (qemu-img + 7 mtools + 28 DLLs + dosbox-x); all 3 specs filter vendor inputs through it so the qemu-system DLL stack is excluded. |
| `windows/spec_helpers.py` (NEW) | `strip_bloat()` / `strip_hidden_imports()` / `post_build_cleanup()` to prune ~210 stale `_internal/` files (Cryptodome SelfTest/PublicKey/Signature, `.dist-info`, setuptools). |
| `.github/workflows/release.yml` | Smoke test asserts **no** variant ships `qemu-system-i386` and that `dosbox-x.exe` **is** present; hyphenated tags (e.g. `v0.4.0-dosbox-x-pre1`) publish as pre-releases. |
| `tests/test_dosbox_x_install.py` (NEW, ~97 LOC) | Unit tests for the `.conf` builder + backend emulator selection. |

### Measured bundle-size impact (branch's local builds, v0.3.2 baseline)

| Variant | Before | After | Δ |
|---|---|---|---|
| Full | 380 MB / 126 MB zip | 174 MB / 108 MB zip | **−206 MB / −18 MB z** |
| Lite | 313 MB / 122 MB zip | 107 MB / 50 MB zip | **−206 MB / −72 MB z** |
| CLI | 64 MB / 27 MB zip | 88 MB / 38 MB zip | **+24 MB / +11 MB z** |

The CLI variant *grew* because v0.3.2's CLI had dropped the 3 install
modes entirely; adding DOSBox-X gave them back at a +24 MB cost.

> ⚠️ These numbers are from the **v0.3.2** era. `main` is now v0.9.57 with
> many more boot modes and bundled assets, and DOSBox-X is already
> present. Re-measure before trusting any specific figure.

---

## 6. Benefits

1. **~110 MB of Windows DLL bloat becomes droppable.** `qemu-system-i386`
   is the *only* consumer of the GTK/SDL/codec/Spice/virgl/USB/NSS DLL
   stack. Remove it and the whole transitive set goes with it. Empirical
   bisection on the branch showed only ~2.4 MB was droppable from the
   stock QEMU build *without* removing the EXE — so the EXE has to go to
   realize the win.
2. **No new dependency.** DOSBox-X is already vendored + used for boot
   probe. The swap consolidates on a single emulator for both install
   *and* verification (today we ship **two** emulators).
3. **DOSBox-X is purpose-built for this.** `IMGMOUNT` + `BOOT` is its
   native idiom for installing DOS into disk images, vs. QEMU where we
   bolt a serial-console install harness onto a general-purpose VM.
4. **Smaller download = faster CI, faster user install,** especially for
   the Lite/Full GUI bundles (the −206 MB unpacked figure).
5. **Single-EXE robustness.** Statically linked (SDL2 + freetype + libpng
   + zlib), so no "missing DLL at load" failures — the exact class of
   problem the 110 MB stack exists to prevent for QEMU.

---

## 7. Drawbacks & risks

1. **Authenticity / behavioral fidelity is unproven.** This is the big
   one. QEMU emulates a real PC closely; DOSBox-X is a DOS-focused
   emulator with its own BIOS/INT-13h quirks. The branch's **outstanding
   work** was exactly this: *"End-to-end test of an actual compaq331 /
   msdos33 / msdos331 install via DOSBox-X and verifying the resulting
   VHD boots in 86Box"* — **never completed.** Until a DOSBox-X-installed
   VHD is proven byte-faithful and 86Box-bootable, the swap is a
   regression risk for dosforge's core promise (authentic DOS disks).
2. **Scope has grown ~5×.** The branch only handled **3** modes
   (`compaq331`, `msdos33`, `msdos331`). `main` now drives the QEMU
   install pipeline for **16** legacy-DOS modes — `msdos5/6/622`,
   `pcdos7/71/2000`, `pcdos3/5`, `compaq2/3`, `drdos6/7`, etc. Every one
   would need DOSBox-X validation. Several have delicate, hard-won
   install quirks (e.g. `FORMAT C: /S` double-confirm for msdos5/622/
   pcdos7, `FDISK /MBR` ordering, pre-DOS-5 CONFIG.SYS synthesis,
   PC-DOS 7.1 FAT32 `FORMAT32`) — all tuned against QEMU's behavior.
3. **Linux/Windows divergence.** The branch only swapped the **Windows**
   emulator. Linux uses QEMU via system packages (no DLL bloat problem)
   and `_LEGACY_DOS_QEMU_BOOT_MODES` is still QEMU-only. A Windows-only
   swap means **two install code paths to maintain** and per-OS
   authenticity matrices — exactly the kind of divergence that caused the
   v0.9.52 ECHS bug (Windows path lagged Linux for months).
4. **DOSBox-X version pinning churn.** The boot-probe path already pins a
   specific DOSBox-X build; making *install* depend on it too raises the
   blast radius of a DOSBox-X upgrade (a behavioral change could silently
   corrupt installs, not just flake a probe).
5. **Bundle bloat pruning is orthogonal.** The `_internal/` strip
   (~210 files / ~3 MB: Cryptodome SelfTest/PublicKey/Signature,
   `.dist-info`, setuptools) is a *separate* win that does **not** require
   the emulator swap and could be cherry-picked on its own with far lower
   risk. Bundling it into the swap conflates two unrelated changes.
6. **Stale baseline.** The branch is 188 commits behind `main`. The spec
   files, vendor manifest, and disk.py install dispatch have all moved;
   a revival is a partial rewrite, not a rebase.

---

## 8. Recommendation

Treat this as **three independent workstreams**, sequenced by risk:

### 8a. Low-risk, do-anytime: `_internal/` bloat prune
Re-implement `windows/spec_helpers.py`'s three filters
(`strip_bloat` / `strip_hidden_imports` / `post_build_cleanup`) plus the
CI regression guard, **without** touching the emulator. Pure size win,
no authenticity risk. ~3 MB + cleaner bundles. Ship as a normal patch.

### 8b. Low-risk, optional: DOSBox-X feature surface (no size win)
The capabilities in §4 buckets "safe, do-anytime" — interactive
**Test drive** (§4 #1), wiring the existing DOSBox-X **probe** into
create/grow runtime (§4 #2), and the **richer verification environment**
(§4 #4). None touch the authoritative install bytes, so they need no
authenticity re-validation. They are pure product-surface gains and do
**not** shrink the bundle (install still needs `qemu-system-i386`).

### 8c. High-risk, gated on validation: the emulator swap
Only worth pursuing if the **~110 MB** Windows win is judged worth the
authenticity-validation cost. This is the **only** workstream that
removes `qemu-system-i386` from the bundle. Required before it can ship:

1. **Prove fidelity on all 16 current QEMU-install modes** (not just the
   original 3): install via DOSBox-X, then boot the result in **86Box
   AUTO IDE** and confirm system files + `C:\>` prompt, byte-comparing
   the BPB/MBR against the QEMU-produced reference VHDs.
2. **Keep QEMU as a runtime fallback** (the branch already did this via
   `legacy_dos_emulator()` returning `"qemu"` when DOSBox-X is absent) so
   a DOSBox-X regression degrades gracefully instead of breaking builds.
3. **Decide the Linux story up front** — either swap both OSes for parity,
   or explicitly document Windows-DOSBox-X / Linux-QEMU divergence and add
   a per-OS authenticity test matrix to prevent the next ECHS-style drift.

If fidelity can't be proven across the full mode matrix, **do not ship
the swap** — the 110 MB is not worth risking authentic-disk correctness,
which is dosforge's whole reason to exist.

---

## 9. Pointers (current `main`)

- Install dispatch: `src/dosforge/disk.py` (`LegacyDosQemuInstaller`, ~line 3159)
- Install profiles/quirks: `src/dosforge/legacy_dos_install.py`
- Per-OS emulator + required tools: `src/dosforge/_platform/{windows,linux}.py`
  (`_LEGACY_DOS_QEMU_BOOT_MODES`, `_KNOWN_BUNDLED_TOOLS`, `tool_path`)
- Runtime grow boot-probe (**QEMU**): `src/dosforge/_grow_impl.py` `_run_boot_probe`
- Bundled DOSBox-X probe harness (**test-only** today): `src/dosforge/_boot_probe.py` `run_boot_probe`
- e2e boot-probe (test-only): `src/dosforge/e2e_emulator.py` `qemu_boot_probe`
- Vendor manifest / fetch: `vendor/windows/manifest.json`,
  `scripts`/`fetch-windows-vendor.py`
- PyInstaller specs: `windows/dosforge{,-lite,-cli}.spec`
- 16 legacy-DOS install modes today: `_LEGACY_DOS_INSTALL_DESCRIPTORS`
  in `src/dosforge/disk.py`
