"""Pure, UI-agnostic form logic shared by the GUI (and unit-testable
without any display).

This module mirrors the dynamic-visibility and request-building rules that
the Textual TUI implements inline in ``app.py`` (``_sync_create_form_visibility``
and ``_request_from_form``). Keeping the rules here — as pure functions over a
plain :class:`FormState` — lets the tkinter GUI stay thin and lets us cover the
tricky create-form matrix with headless golden tests.

The Textual app is intentionally left untouched for now; these functions are a
faithful re-implementation. ``tests/test_formlogic.py`` pins the behavior so
the two cannot silently diverge for the cases that matter.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

from .errors import DosForgeError
from .models import (
    BootMode,
    CreateRequest,
    DiskFormat,
    FloppyType,
    FreeDOSSource,
    IBMDOSVersion,
    MSDOSInstallProfile,
    MachineTarget,
    MartyPCXebecDriveType,
    MediaType,
    lookup_bios_drive_type,
    lookup_martypc_at_format,
    parse_bios_drive_slug,
)
from .size import parse_size

# Field keys used by ``visible_fields`` / ``disabled_fields``. These are the
# logical control names the GUI binds to; they intentionally match the TUI's
# widget IDs (minus the wrapping rows) so the two are easy to compare.
FIELD_MEDIA_TYPE = "media-type"
FIELD_MACHINE_TARGET = "machine-target"
FIELD_MARTYPC_XEBEC = "martypc-xebec-drive-type"
FIELD_MARTYPC_AT = "martypc-at-drive-type"
FIELD_OUTPUT_PATH = "create-path"
FIELD_SIZE = "create-size"
FIELD_BIOS_DRIVE = "bios-drive-type"
FIELD_FORMAT = "create-format"
FIELD_FLOPPY = "floppy-type"
FIELD_IMG_SYSTEM_FORMAT = "img-system-format"
FIELD_BOOT_MODE = "boot-mode"
FIELD_FREEDOS_SOURCE = "freedos-source"
FIELD_FETCH_FREEDOS = "fetch-freedos-btn"
FIELD_FETCH_PCDOS71 = "fetch-pcdos71-btn"
FIELD_DOS_PROFILE = "dos-profile"
FIELD_IBM_DOS_VERSION = "ibm-dos-version"
FIELD_BOOT_ASSETS = "boot-assets"
FIELD_CUSTOM_PAYLOAD = "custom-payload"
FIELD_FREEDOS_URL = "freedos-url"
FIELD_VOLUME_LABEL = "volume-label"
FIELD_OVERWRITE = "overwrite"

# Boot modes that use the DOS install-profile dropdown (mirrors app.py).
_DOS_PROFILE_BOOT_MODES = frozenset(
    {
        BootMode.MSDOS71,
        BootMode.IBM8088,
        BootMode.MSDOS33,
        BootMode.MSDOS331,
        BootMode.MSDOS5,
        BootMode.MSDOS622,
        BootMode.PCDOS,
        BootMode.PCDOS7,
        BootMode.PCDOS2000,
        BootMode.PCDOS71,
        BootMode.COMPAQ331,
    }
)

# Boot modes compatible with a MartyPC XT (Xebec / XT-IDE) target. Anything
# outside this set snaps to MS-DOS 3.3 when such a target is chosen.
_XEBEC_XT_BOOT_MODES = frozenset(
    {
        BootMode.NONE,
        BootMode.IBM8088,
        BootMode.MSDOS33,
        BootMode.MSDOS331,
        BootMode.PCDOS,
        BootMode.COMPAQ331,
    }
)
_XEBEC_FAT12_BOOT_MODES = frozenset(
    {BootMode.MSDOS33, BootMode.IBM8088, BootMode.NONE}
)


@dataclass(frozen=True, slots=True)
class FormState:
    """Snapshot of the create-form control values.

    All enum-backed fields are stored as their ``.value`` strings, exactly as
    the corresponding ttk/Textual widgets expose them, so the state round-trips
    through the UI without conversion.
    """

    media_type: str = MediaType.VHD.value
    machine_target: str = MachineTarget.GENERIC.value
    martypc_xebec_drive_type: str = MartyPCXebecDriveType.TYPE2.value
    martypc_at_drive_type: str = ""  # default filled in factory below
    output_path: str = ""
    size_text: str = "512M"
    bios_drive_type: str = ""  # "" == Custom
    disk_format: str = DiskFormat.FAT16.value
    floppy_type: str = FloppyType.F1440K.value
    img_system_format: bool = False
    boot_mode: str = BootMode.NONE.value
    freedos_source: str = FreeDOSSource.AUTO.value
    dos_profile: str = MSDOSInstallProfile.MINIMAL.value
    ibm_dos_version: str = IBMDOSVersion.DOS33.value
    boot_assets: str = ""
    custom_payload: str = ""
    freedos_url: str = ""
    volume_label: str = ""
    overwrite: bool = False


def default_state() -> FormState:
    """Return the initial form state matching the TUI's compose defaults."""
    from .models import DEFAULT_MARTYPC_AT_FORMAT_SLUG

    return FormState(martypc_at_drive_type=DEFAULT_MARTYPC_AT_FORMAT_SLUG)


# ── Derived flags ──────────────────────────────────────────────────────────


def _is_vhd(state: FormState) -> bool:
    return MediaType(state.media_type) is MediaType.VHD


def _is_martypc_xebec(state: FormState) -> bool:
    return _is_vhd(state) and MachineTarget(state.machine_target) is MachineTarget.MARTYPC_XEBEC


def _is_martypc_at(state: FormState) -> bool:
    return _is_vhd(state) and MachineTarget(state.machine_target) in (
        MachineTarget.MARTYPC_XTIDE,
        MachineTarget.MARTYPC_JRIDE,
    )


def _is_martypc(state: FormState) -> bool:
    return _is_martypc_xebec(state) or _is_martypc_at(state)


def _boot_controls_active(state: FormState) -> bool:
    return _is_vhd(state) or state.img_system_format


def _bios_spec(state: FormState):
    """Resolve the selected BIOS preset spec, or ``None`` for Custom/invalid."""
    if not state.bios_drive_type:
        return None
    try:
        vendor, type_id = parse_bios_drive_slug(state.bios_drive_type)
        return lookup_bios_drive_type(vendor, type_id)
    except (ValueError, KeyError):
        return None


# ── Visibility / disabled ──────────────────────────────────────────────────


def visible_fields(state: FormState) -> set[str]:
    """Return the set of control keys that should be visible for ``state``.

    Faithful re-implementation of ``app.py:_sync_create_form_visibility``.
    Controls that are always visible (media type, output path, volume label,
    overwrite, the Create button) are not included in the returned set — the
    GUI shows those unconditionally.
    """
    is_vhd = _is_vhd(state)
    is_xebec = _is_martypc_xebec(state)
    is_at = _is_martypc_at(state)
    is_martypc = is_xebec or is_at
    boot_active = _boot_controls_active(state)
    boot_mode = BootMode(state.boot_mode)
    freedos_source = FreeDOSSource(state.freedos_source)

    show_freedos = boot_active and boot_mode is BootMode.FREEDOS
    show_dos_profile = boot_active and boot_mode in _DOS_PROFILE_BOOT_MODES
    show_ibm_dos_version = (
        boot_active and boot_mode is BootMode.IBM8088 and not is_xebec
    )
    show_boot_assets = show_dos_profile or (
        show_freedos and freedos_source is FreeDOSSource.LOCAL
    )
    show_freedos_url = show_freedos and freedos_source is FreeDOSSource.AUTO

    visible: set[str] = set()
    if is_vhd and not is_martypc:
        visible.add(FIELD_SIZE)
    if is_vhd and not is_xebec:
        visible.add(FIELD_FORMAT)
    if is_vhd:
        visible.add(FIELD_MACHINE_TARGET)
    if is_xebec:
        visible.add(FIELD_MARTYPC_XEBEC)
    if is_at:
        visible.add(FIELD_MARTYPC_AT)
    if is_vhd and not is_martypc:
        visible.add(FIELD_BIOS_DRIVE)
    if not is_vhd:
        visible.add(FIELD_FLOPPY)
        visible.add(FIELD_IMG_SYSTEM_FORMAT)
    if boot_active:
        visible.add(FIELD_BOOT_MODE)
    if show_freedos:
        visible.add(FIELD_FREEDOS_SOURCE)
        visible.add(FIELD_FETCH_FREEDOS)
    if show_dos_profile and boot_mode is BootMode.PCDOS71:
        # PC-DOS 7.1 (SGTK) pre-fetcher: same idea as Download FreeDOS
        # assets, but pulls the IBM ServerGuide Scripting Toolkit and
        # optionally hydrates C:\DOS\ with PC-DOS 2000 utilities when a
        # local pcdos2000 archive is available.
        visible.add(FIELD_FETCH_PCDOS71)
    if show_dos_profile:
        visible.add(FIELD_DOS_PROFILE)
    if show_ibm_dos_version:
        visible.add(FIELD_IBM_DOS_VERSION)
    if show_boot_assets:
        visible.add(FIELD_BOOT_ASSETS)
    if (is_vhd or state.img_system_format) and not is_martypc:
        visible.add(FIELD_CUSTOM_PAYLOAD)
    if show_freedos_url:
        visible.add(FIELD_FREEDOS_URL)
    return visible


def disabled_fields(state: FormState) -> set[str]:
    """Return control keys that should be visible but read-only.

    The size input is locked (and pre-filled) when a generic VHD target has a
    resolvable BIOS preset selected — the preset dictates an exact CHS/size.
    """
    disabled: set[str] = set()
    if (
        _is_vhd(state)
        and not _is_martypc(state)
        and state.bios_drive_type
        and _bios_spec(state) is not None
    ):
        disabled.add(FIELD_SIZE)
    return disabled


def effective_size_text(state: FormState) -> str:
    """Size string to display in the (possibly read-only) size input."""
    if FIELD_SIZE in disabled_fields(state):
        spec = _bios_spec(state)
        if spec is not None:
            return f"{spec.size_mb}M"
    return state.size_text


# ── Cross-field coercions (mirror app.py event handlers) ───────────────────


# Per-boot-mode media constraints. ``allowed_formats`` lists the
# DiskFormat values the boot mode supports; the form coerces the
# current selection into this set on boot-mode change. ``preferred_format``
# is what we snap TO when the user picks the boot mode (so PCDOS71
# defaults to FAT32 even if they were on FAT16 from a prior selection).
# ``max_mb`` caps VHD size for OSes that can't read above a partition
# size (32M for 8088/DOS 3.3). ``per_format_min_mb`` is an optional
# extra floor that applies only when a specific FS is picked (e.g.
# pcdos71+FAT32 needs ≥1GB even though pcdos71+FAT16 happily runs at
# 128MB).
@dataclass(frozen=True, slots=True)
class _BootMediaRule:
    allowed_formats: frozenset[DiskFormat]
    preferred_format: DiskFormat | None = None
    max_mb: int | None = None
    per_format_min_mb: dict[DiskFormat, int] = field(default_factory=dict)


_BOOT_MODE_MEDIA_RULES: dict[BootMode, _BootMediaRule] = {
    BootMode.NONE: _BootMediaRule(
        allowed_formats=frozenset({DiskFormat.FAT12, DiskFormat.FAT16, DiskFormat.FAT32}),
    ),
    BootMode.FREEDOS: _BootMediaRule(
        allowed_formats=frozenset({DiskFormat.FAT12, DiskFormat.FAT16, DiskFormat.FAT32}),
    ),
    # MS-DOS 7.1 (Win95 OSR2) supports FAT16 up to 2GB and FAT32 above.
    BootMode.MSDOS71: _BootMediaRule(
        allowed_formats=frozenset({DiskFormat.FAT16, DiskFormat.FAT32}),
    ),
    # PC-DOS 7.1: FAT32 is the headline feature (IBM SGTK was designed
    # for server-class disks). Default to FAT32 + 1 GB minimum on FAT32;
    # FAT16 stays selectable and uses the generic 32 MB FAT16 floor.
    BootMode.PCDOS71: _BootMediaRule(
        allowed_formats=frozenset({DiskFormat.FAT16, DiskFormat.FAT32}),
        preferred_format=DiskFormat.FAT32,
        per_format_min_mb={DiskFormat.FAT32: 1024},
    ),
    # 8088/V20 + DOS 3.3 / 5.0 floors: FAT16 only, max 32 MB partition.
    BootMode.IBM8088: _BootMediaRule(
        allowed_formats=frozenset({DiskFormat.FAT16}), max_mb=32,
    ),
    BootMode.MSDOS33: _BootMediaRule(
        allowed_formats=frozenset({DiskFormat.FAT16}), max_mb=32,
    ),
    BootMode.MSDOS331: _BootMediaRule(
        allowed_formats=frozenset({DiskFormat.FAT16}),
    ),
    BootMode.COMPAQ331: _BootMediaRule(
        allowed_formats=frozenset({DiskFormat.FAT16}),
    ),
    # DOS 5.0 / 6.22 — FAT16 only (no FAT32 support).
    BootMode.MSDOS5: _BootMediaRule(allowed_formats=frozenset({DiskFormat.FAT16})),
    BootMode.MSDOS622: _BootMediaRule(allowed_formats=frozenset({DiskFormat.FAT16})),
    # PC-DOS pre-7.x — FAT12/FAT16.
    BootMode.PCDOS: _BootMediaRule(
        allowed_formats=frozenset({DiskFormat.FAT12, DiskFormat.FAT16}),
    ),
    BootMode.PCDOS7: _BootMediaRule(
        allowed_formats=frozenset({DiskFormat.FAT12, DiskFormat.FAT16}),
    ),
    # IBM PC-DOS 2000 = PC-DOS 7.0 rebrand; same FAT support as PCDOS7.
    BootMode.PCDOS2000: _BootMediaRule(
        allowed_formats=frozenset({DiskFormat.FAT12, DiskFormat.FAT16}),
    ),
}


def boot_media_rule(boot_mode: BootMode) -> _BootMediaRule | None:
    """Public lookup for UI code that wants the constraints for a boot mode."""
    return _BOOT_MODE_MEDIA_RULES.get(boot_mode)


def _snap_format_for_boot_mode(state: FormState, *, force_preferred: bool) -> FormState:
    """Snap ``disk_format`` to a valid choice for the current boot mode.

    Does nothing for FAT12 on the MartyPC Xebec Type 1 path (that
    constraint is enforced by :func:`_apply_xebec_rules`).

    When ``force_preferred`` is False (the default on a format-only
    change), only rewrites the format when the current selection isn't
    in the boot mode's allowed set. When True (used on boot-mode
    change), also snaps to ``preferred_format`` if one is defined so
    e.g. picking PCDOS71 yields FAT32 not FAT16.
    """
    if _is_martypc_xebec(state):
        return state
    boot_mode = BootMode(state.boot_mode)
    rule = _BOOT_MODE_MEDIA_RULES.get(boot_mode)
    if rule is None:
        return state
    current = DiskFormat(state.disk_format)
    if force_preferred and rule.preferred_format is not None:
        if current != rule.preferred_format:
            return replace(state, disk_format=rule.preferred_format.value)
        return state
    if current in rule.allowed_formats:
        return state
    if DiskFormat.FAT16 in rule.allowed_formats:
        return replace(state, disk_format=DiskFormat.FAT16.value)
    chosen = sorted(rule.allowed_formats, key=lambda f: f.value)[0]
    return replace(state, disk_format=chosen.value)


def _snap_size_for_boot_mode(state: FormState) -> FormState:
    """Cap + floor VHD ``size_text`` for the current boot mode + FS.

    Honors three constraints in order:
      1. ``rule.max_mb`` — global per-boot-mode cap (e.g. 32 MB for
         IBM8088 / MS-DOS 3.3). Sizes above get snapped down.
      2. ``rule.per_format_min_mb[fmt]`` — per-FS minimum (e.g. 1 GB for
         pcdos71+FAT32). Sizes below get snapped up.

    Only kicks in for VHD targets; IMG floppies use ``floppy_type``
    rather than the size field. Unparseable size strings fall through
    to the floor when one applies, otherwise stay untouched.
    """
    if not _is_vhd(state):
        return state
    boot_mode = BootMode(state.boot_mode)
    rule = _BOOT_MODE_MEDIA_RULES.get(boot_mode)
    if rule is None:
        return state
    fmt = DiskFormat(state.disk_format)
    min_mb = rule.per_format_min_mb.get(fmt)
    max_mb = rule.max_mb
    try:
        size_bytes = parse_size(state.size_text)
    except DosForgeError:
        if min_mb is not None:
            return replace(state, size_text=f"{_render_mb(min_mb)}")
        if max_mb is not None:
            return replace(state, size_text=f"{max_mb}M")
        return state
    if max_mb is not None and size_bytes > max_mb * 1024 * 1024:
        return replace(state, size_text=f"{max_mb}M")
    if min_mb is not None and size_bytes < min_mb * 1024 * 1024:
        return replace(state, size_text=f"{_render_mb(min_mb)}")
    return state


def _render_mb(mb: int) -> str:
    """Render ``mb`` as the most natural human size string (M or G)."""
    if mb >= 1024 and mb % 1024 == 0:
        return f"{mb // 1024}G"
    return f"{mb}M"


def coerce_on_media_change(state: FormState) -> FormState:
    """Apply the side effects of changing the media-type select."""
    if MediaType(state.media_type) is MediaType.IMG:
        return replace(
            state,
            img_system_format=False,
            boot_mode=BootMode.NONE.value,
            machine_target=MachineTarget.GENERIC.value,
        )
    return state


def coerce_on_machine_change(state: FormState) -> FormState:
    """Apply MartyPC Xebec format/boot/version snapping on target change."""
    if MachineTarget(state.machine_target) is not MachineTarget.MARTYPC_XEBEC:
        return state
    return _apply_xebec_rules(state)


def coerce_on_xebec_drive_change(state: FormState) -> FormState:
    """Re-apply Xebec FAT12<->FAT16 + boot snapping when the drive type flips."""
    if MachineTarget(state.machine_target) is not MachineTarget.MARTYPC_XEBEC:
        return state
    drive_type = MartyPCXebecDriveType(state.martypc_xebec_drive_type)
    if drive_type is MartyPCXebecDriveType.TYPE1:
        new = replace(state, disk_format=DiskFormat.FAT12.value)
        if BootMode(new.boot_mode) not in _XEBEC_FAT12_BOOT_MODES:
            new = replace(new, boot_mode=BootMode.MSDOS33.value)
        return new
    if DiskFormat(state.disk_format) is DiskFormat.FAT12:
        return replace(state, disk_format=DiskFormat.FAT16.value)
    return state


def _apply_xebec_rules(state: FormState) -> FormState:
    drive_type = MartyPCXebecDriveType(state.martypc_xebec_drive_type)
    new = replace(
        state,
        disk_format=(
            DiskFormat.FAT12.value
            if drive_type is MartyPCXebecDriveType.TYPE1
            else DiskFormat.FAT16.value
        ),
        ibm_dos_version=IBMDOSVersion.DOS33.value,
    )
    boot_mode = BootMode(new.boot_mode)
    if drive_type is MartyPCXebecDriveType.TYPE1:
        if boot_mode not in _XEBEC_FAT12_BOOT_MODES:
            new = replace(new, boot_mode=BootMode.MSDOS33.value)
    elif boot_mode not in _XEBEC_XT_BOOT_MODES:
        new = replace(new, boot_mode=BootMode.MSDOS33.value)
    return new


def apply_ibm_default_size(state: FormState, *, force: bool) -> FormState:
    """Mirror ``_apply_ibm_default_size``: nudge VHD size to 32M for IBM8088."""
    if not _is_vhd(state):
        return state
    if force or state.size_text.strip().upper() in {"", "512M"}:
        return replace(state, size_text="32M")
    return state


def coerce_on_boot_change(state: FormState) -> FormState:
    if _is_vhd(state) and BootMode(state.boot_mode) is BootMode.IBM8088:
        state = apply_ibm_default_size(state, force=True)
    # Boot mode is the upstream constraint for filesystem + size; snap
    # both to whatever the picked OS supports so the user moves into
    # the Media step with valid prefills. ``force_preferred=True`` so
    # picking PCDOS71 lands on FAT32 (its preferred default) and the
    # downstream size snap then enforces the 1 GiB FAT32 floor.
    state = _snap_format_for_boot_mode(state, force_preferred=True)
    state = _snap_size_for_boot_mode(state)
    return state


def coerce_on_format_change(state: FormState) -> FormState:
    """Re-enforce size floors/caps after a Filesystem-dropdown change.

    The size constraints in ``_BOOT_MODE_MEDIA_RULES`` are partly
    FS-dependent (e.g. PCDOS71+FAT32 needs ≥1 GiB but PCDOS71+FAT16 is
    fine at 128 MB).  When the user flips Filesystem in Step 2 we
    re-run the size snap so they can't end up with an invalid size for
    the new FS.
    """
    return _snap_size_for_boot_mode(state)


def validate_media_step(state: FormState) -> str | None:
    """Return a user-facing error if the Media-step form would fail validation.

    Only checks the per-boot-mode FS + size constraints captured in
    :data:`_BOOT_MODE_MEDIA_RULES` (e.g. PC-DOS 7.1 FAT32 1 GiB floor,
    MSDOS33 32 MiB cap).  These mirror the rules `DiskManager._validate_create_request`
    enforces at submit time so the wizard can surface them earlier without
    duplicating the full validator.

    Returns ``None`` when the step is valid (or when no rule applies).
    """
    if not _is_vhd(state):
        return None
    try:
        boot_mode = BootMode(state.boot_mode)
    except ValueError:
        return None
    rule = _BOOT_MODE_MEDIA_RULES.get(boot_mode)
    if rule is None:
        return None
    try:
        fmt = DiskFormat(state.disk_format)
    except ValueError:
        return None
    if rule.allowed_formats and fmt not in rule.allowed_formats:
        return (
            f"{boot_mode.value} only supports "
            f"{', '.join(f.value for f in rule.allowed_formats)}."
        )
    try:
        size_bytes = parse_size(state.size_text)
    except DosForgeError as exc:
        return str(exc)
    min_mb = rule.per_format_min_mb.get(fmt)
    if min_mb is not None and size_bytes < min_mb * 1024 * 1024:
        if boot_mode is BootMode.PCDOS71 and fmt is DiskFormat.FAT32:
            return (
                "PC-DOS 7.1 FAT32 partitions must be at least 1 GiB. "
                "PC-DOS FORMAT32 rejects smaller partitions with "
                "'The drive specified is too small to use FAT32.' "
                f"Increase the size to {_render_mb(min_mb)} or pick FAT16 for smaller drives."
            )
        return (
            f"{boot_mode.value} {fmt.value} partitions must be at least "
            f"{_render_mb(min_mb)}."
        )
    if rule.max_mb is not None and size_bytes > rule.max_mb * 1024 * 1024:
        return (
            f"{boot_mode.value} partitions cannot exceed "
            f"{_render_mb(rule.max_mb)}."
        )
    return None


def build_time_hint(state: FormState) -> str | None:
    """Return a user-facing 'expect a slow build' hint for some boot modes.

    Reserved for boot modes whose build is dominated by file count or
    QEMU runtime in ways the user can't avoid. Currently returns
    ``None`` for every mode — the FreeDOS slow-build warning that
    lived here in v0.6.14 was removed in v0.6.15 once the FreeDOS
    payload filter cut staged file count from 1388 to ~85 (so the
    build is no longer noticeably slow).

    Pure function: only reads ``state``, no I/O. Returns a
    single-line message or ``None``.
    """
    try:
        boot_mode = BootMode(state.boot_mode)
    except ValueError:
        return None
    if not _is_vhd(state) and not state.img_system_format:
        return None
    return build_time_hint_for_boot_mode(boot_mode)


def build_time_hint_for_boot_mode(boot_mode: BootMode) -> str | None:
    """Lower-level :func:`build_time_hint` for callers that don't have a FormState.

    Used by the TUI's :meth:`DosForgeApp._handle_create` (which works
    against a built :class:`CreateRequest`) and the CLI's create
    subcommand. The :func:`build_time_hint` wrapper is preferred when
    a FormState is in hand because it also short-circuits on IMG
    floppies that aren't system-formatted (no DOS payload to stage).

    Returns ``None`` for every boot mode today; left in place so the
    GUI / TUI / CLI surfaces stay wired up and future slow-build
    modes can be added with a one-line edit.
    """
    return None


def coerce_on_ibm_version_change(state: FormState) -> FormState:
    if _is_vhd(state):
        return apply_ibm_default_size(state, force=False)
    return state


def coerce_on_img_system_format_change(state: FormState) -> FormState:
    if not state.img_system_format:
        return replace(state, boot_mode=BootMode.NONE.value)
    return state


# ── Request building ───────────────────────────────────────────────────────


def build_create_request(state: FormState) -> CreateRequest:
    """Build a :class:`CreateRequest` from ``state``.

    Faithful re-implementation of ``app.py:_request_from_form`` including the
    IBM8088 512M->32M coercion, MartyPC fixed-geometry sizing, BIOS-preset
    handling and IMG boot-mode suppression.
    """
    path_text = state.output_path.strip()
    if not path_text:
        raise DosForgeError("Create path is required.")

    media_type = MediaType(state.media_type)
    floppy_type = FloppyType(state.floppy_type)
    machine_target = MachineTarget(state.machine_target)
    martypc_xebec_drive_type = MartyPCXebecDriveType(state.martypc_xebec_drive_type)
    msdos_install_profile = MSDOSInstallProfile(state.dos_profile)
    ibm_dos_version = IBMDOSVersion(state.ibm_dos_version)

    size_text = state.size_text.strip()
    boot_value = state.boot_mode
    img_system_format = state.img_system_format

    boot_assets_text = state.boot_assets.strip()
    boot_assets_path = Path(boot_assets_text).expanduser() if boot_assets_text else None
    custom_payload_text = state.custom_payload.strip()
    custom_payload_path = (
        Path(custom_payload_text).expanduser() if custom_payload_text else None
    )
    freedos_url = state.freedos_url.strip() or None
    label_text = state.volume_label.strip() or None

    if (
        media_type is MediaType.VHD
        and boot_value == BootMode.IBM8088.value
        and size_text.upper() == "512M"
    ):
        size_text = "32M"

    if media_type is MediaType.VHD:
        if machine_target is MachineTarget.MARTYPC_XEBEC:
            size_bytes = martypc_xebec_drive_type.size_bytes
        elif machine_target in (
            MachineTarget.MARTYPC_XTIDE,
            MachineTarget.MARTYPC_JRIDE,
        ):
            size_bytes = lookup_martypc_at_format(state.martypc_at_drive_type).size_bytes
        elif size_text:
            size_bytes = parse_size(size_text)
        elif custom_payload_path is not None:
            size_bytes = 1
        else:
            raise DosForgeError("Create size is required.")
    else:
        size_bytes = floppy_type.size_bytes

    request_boot_mode = (
        BootMode(boot_value)
        if (media_type is MediaType.VHD or img_system_format)
        else BootMode.NONE
    )
    disk_format = (
        DiskFormat(state.disk_format) if media_type is MediaType.VHD else DiskFormat.FAT16
    )
    if machine_target is MachineTarget.MARTYPC_XEBEC:
        disk_format = (
            DiskFormat.FAT12
            if martypc_xebec_drive_type is MartyPCXebecDriveType.TYPE1
            else DiskFormat.FAT16
        )

    return CreateRequest(
        path=Path(path_text).expanduser(),
        size_bytes=size_bytes,
        disk_format=disk_format,
        media_type=media_type,
        floppy_type=floppy_type,
        img_system_format=img_system_format,
        label=label_text,
        overwrite=state.overwrite,
        boot_mode=request_boot_mode,
        freedos_source=FreeDOSSource(state.freedos_source),
        boot_assets_path=boot_assets_path,
        freedos_download_url=freedos_url,
        msdos_install_profile=msdos_install_profile,
        ibm_dos_version=ibm_dos_version,
        custom_payload_path=custom_payload_path,
        machine_target=machine_target,
        martypc_xebec_drive_type=martypc_xebec_drive_type,
        martypc_at_drive_type_slug=state.martypc_at_drive_type,
        bios_drive_type=(
            parse_bios_drive_slug(state.bios_drive_type)
            if state.bios_drive_type
            else None
        ),
    )


def build_summary(state: FormState) -> list[tuple[str, str]]:
    """Return ``(label, value)`` rows describing the effective request.

    Mirrors the TUI summary card. Uses the *effective* size (BIOS preset) so
    the user sees what they will actually get.
    """
    media_type = MediaType(state.media_type)
    boot_mode = BootMode(state.boot_mode)
    machine = MachineTarget(state.machine_target)

    path = state.output_path.strip() or "(not set)"
    size = effective_size_text(state).strip() or "(default)"
    fmt = state.disk_format
    floppy = state.floppy_type
    boot_assets = state.boot_assets.strip() or "(auto)"
    custom_payload = state.custom_payload.strip() or "(none)"
    label_text = state.volume_label.strip() or "(default)"

    if media_type is MediaType.VHD:
        media_line = f"VHD  size={size}  fs={fmt}"
    else:
        media_line = (
            f"IMG  floppy={floppy}  "
            f"bootable={'yes' if state.img_system_format else 'no'}"
        )

    boot_line = boot_mode.value if boot_mode is not BootMode.NONE else "(none)"
    if boot_mode is not BootMode.NONE and media_type is MediaType.VHD:
        boot_line += f"  profile={MSDOSInstallProfile(state.dos_profile).value}"

    rows: list[tuple[str, str]] = [
        ("Output", path),
        ("Media", media_line),
        ("Machine", machine.value),
        ("Boot", boot_line),
        ("Assets", boot_assets),
        ("Payload", custom_payload),
        ("Label", label_text),
        ("Overwrite", "yes" if state.overwrite else "no"),
    ]
    hint = build_time_hint(state)
    if hint:
        # Show a compact, scannable form of the hint in the summary
        # card so the user knows *before* clicking Create that this
        # build will take longer than usual. The full multi-line
        # explanation is reserved for the spinner / status bar where
        # there's room.
        rows.append(("Build time", "slow — see status bar"))
    return rows
