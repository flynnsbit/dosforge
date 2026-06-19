# Feature Exploration: Swapping QEMU → DOSBox-X for the Legacy DOS Install Path

**Status:** Exploration / not scheduled
**Author:** captured from the abandoned `feature/dosbox-x-swap` branch
(commits `edb63e4`, `fd83bbf`, `3825840`), reconciled against `main` @ v0.9.57
**Date:** 2026-06-19

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

- **`main` already bundles `dosbox-x.exe`** and uses it for the
  **headless boot-probe / verification** path (`src/dosforge/_boot_probe.py`,
  the "Headless boot probe" step seen in grow/create logs). It imgmounts
  a freshly-built VHD/IMG and confirms it boots.
- `dosbox-x` is already in `_KNOWN_BUNDLED_TOOLS` and has bespoke
  `tool_path` resolution in `src/dosforge/_platform/windows.py`
  (it lives in `vendor/windows/bin/dosbox-x/` with its support files).

**Consequence:** the swap would **not** add a new vendor dependency.
DOSBox-X is already shipped, fetched, pinned, and SHA-verified. The swap
is purely about *also* using it for install, which would let us **drop**
`qemu-system-i386` + its DLL stack entirely. The branch's "add DOSBox-X"
cost is already sunk on `main`; only the upside remains.

---

## 3. What the abandoned branch actually built

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

## 4. Benefits

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

## 5. Drawbacks & risks

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

## 6. Recommendation

Treat this as **two independent workstreams**, sequenced by risk:

### 6a. Low-risk, do-anytime: `_internal/` bloat prune
Re-implement `windows/spec_helpers.py`'s three filters
(`strip_bloat` / `strip_hidden_imports` / `post_build_cleanup`) plus the
CI regression guard, **without** touching the emulator. Pure size win,
no authenticity risk. ~3 MB + cleaner bundles. Ship as a normal patch.

### 6b. High-risk, gated on validation: the emulator swap
Only worth pursuing if the **~110 MB** Windows win is judged worth the
authenticity-validation cost. Required before it can ship:

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

## 7. Pointers (current `main`)

- Install dispatch: `src/dosforge/disk.py` (`LegacyDosQemuInstaller`, ~line 3159)
- Install profiles/quirks: `src/dosforge/legacy_dos_install.py`
- Per-OS emulator + required tools: `src/dosforge/_platform/{windows,linux}.py`
  (`_LEGACY_DOS_QEMU_BOOT_MODES`, `_KNOWN_BUNDLED_TOOLS`, `tool_path`)
- Already-bundled DOSBox-X (boot probe): `src/dosforge/_boot_probe.py`
- Vendor manifest / fetch: `vendor/windows/manifest.json`,
  `scripts`/`fetch-windows-vendor.py`
- PyInstaller specs: `windows/dosforge{,-lite,-cli}.spec`
- 16 legacy-DOS install modes today: `_LEGACY_DOS_INSTALL_DESCRIPTORS`
  in `src/dosforge/disk.py`
