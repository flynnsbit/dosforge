"""Pure, UI-agnostic create-form logic shared by GUI and tests."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

from .errors import DosForgeError
from .models import (
    BootMode,
    CreateRequest,
    DiskController,
    DiskFormat,
    FloppyType,
    FreeDOSSource,
    GeometrySource,
    IBMDOSVersion,
    MSDOSInstallProfile,
    MediaType,
    lookup_bios_drive_type,
    parse_bios_drive_slug,
)
from .size import (
    FAT12_MAX_BYTES,
    FAT16_MAX_BYTES,
    FAT32_MAX_BYTES,
    parse_size,
)


# Per-FAT-format effective caps (bytes -> MiB).  Used as a default
# upper bound when a boot mode doesn't pin its own ``max_mb`` (e.g.
# FreeDOS / MSDOS622 / MSDOS71) so the UI clamps to "what FAT16
# can actually hold" instead of letting the user pick 5 GiB FAT16
# and hitting the error only at Create-click time.
_FAT_FORMAT_MAX_MB: dict[DiskFormat, int] = {
    DiskFormat.FAT12: FAT12_MAX_BYTES // (1024 * 1024),
    DiskFormat.FAT16: FAT16_MAX_BYTES // (1024 * 1024),
    DiskFormat.FAT32: FAT32_MAX_BYTES // (1024 * 1024),
}


def _effective_max_mb(rule: "_BootMediaRule", fmt: DiskFormat) -> int | None:
    """Compute the tightest applicable size cap for a (rule, format) pair.

    Per-boot-mode ``rule.max_mb`` wins when it's tighter than the
    FAT-format-derived cap; otherwise the FAT-format cap (FAT12=32 MiB,
    FAT16=2 GiB, FAT32=2 TiB) applies so the UI never lets the user
    overshoot what the chosen filesystem can actually hold.
    """
    fmt_cap = _FAT_FORMAT_MAX_MB.get(fmt)
    if rule.max_mb is None:
        return fmt_cap
    if fmt_cap is None:
        return rule.max_mb
    return min(rule.max_mb, fmt_cap)

FIELD_MEDIA_TYPE = "media-type"
FIELD_DISK_CONTROLLER = "disk-controller"
FIELD_GEOMETRY_SOURCE = "geometry-source"
FIELD_CUSTOM_CHS = "custom-chs"
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

_DOS_PROFILE_BOOT_MODES = frozenset(
    {
        BootMode.MSDOS71,
        BootMode.IBM8088,
        BootMode.MSDOS33,
        BootMode.MSDOS331,
        BootMode.MSDOS5,
        BootMode.MSDOS6,
        BootMode.MSDOS622,
        BootMode.PCDOS,
        BootMode.PCDOS3,
        BootMode.COMPAQ3,
        BootMode.PCDOS7,
        BootMode.PCDOS2000,
        BootMode.PCDOS71,
        BootMode.COMPAQ2,
        BootMode.COMPAQ331,
        BootMode.DRDOS6,
        BootMode.DRDOS7,
    }
)


@dataclass(frozen=True, slots=True)
class FormState:
    media_type: str = MediaType.VHD.value
    disk_controller: str = ""
    geometry_source: str = GeometrySource.SIZE.value
    custom_chs: str = ""
    output_path: str = ""
    size_text: str = "512M"
    bios_drive_type: str = ""
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
    return FormState()


def _is_vhd(state: FormState) -> bool:
    return MediaType(state.media_type) is MediaType.VHD


def _boot_controls_active(state: FormState) -> bool:
    return _is_vhd(state) or state.img_system_format


def _bios_spec(state: FormState):
    if not state.bios_drive_type:
        return None
    try:
        vendor, type_id = parse_bios_drive_slug(state.bios_drive_type)
        return lookup_bios_drive_type(vendor, type_id)
    except (ValueError, KeyError):
        return None


def _parse_chs_text(value: str) -> tuple[int, int, int] | None:
    text = value.strip()
    if not text:
        return None
    parts = [part.strip() for part in text.split(",")]
    if len(parts) != 3:
        raise DosForgeError("Custom CHS must be CYL,HEAD,SPT (for example 306,4,17).")
    try:
        cyl, heads, spt = (int(part) for part in parts)
    except ValueError as exc:
        raise DosForgeError("Custom CHS values must be integers.") from exc
    if cyl <= 0 or heads <= 0 or spt <= 0:
        raise DosForgeError("Custom CHS values must be positive.")
    return (cyl, heads, spt)


def visible_fields(state: FormState) -> set[str]:
    is_vhd = _is_vhd(state)
    boot_active = _boot_controls_active(state)
    boot_mode = BootMode(state.boot_mode)
    freedos_source = FreeDOSSource(state.freedos_source)

    show_freedos = boot_active and boot_mode is BootMode.FREEDOS
    show_dos_profile = boot_active and boot_mode in _DOS_PROFILE_BOOT_MODES
    show_ibm_dos_version = boot_active and boot_mode is BootMode.IBM8088
    show_boot_assets = show_dos_profile or (show_freedos and freedos_source is FreeDOSSource.LOCAL)
    show_freedos_url = show_freedos and freedos_source is FreeDOSSource.AUTO

    visible: set[str] = set()
    if is_vhd:
        visible.update({FIELD_FORMAT, FIELD_DISK_CONTROLLER, FIELD_GEOMETRY_SOURCE})
        # Each geometry source surfaces ONE input. The other two stay
        # hidden so the user sees a clear "pick a source, fill its
        # field" hierarchy instead of three competing controls.
        source = _safe_geometry_source(state)
        if source is GeometrySource.SIZE:
            visible.add(FIELD_SIZE)
        elif source is GeometrySource.PRESET:
            visible.add(FIELD_BIOS_DRIVE)
        elif source is GeometrySource.CUSTOM_CHS:
            visible.add(FIELD_CUSTOM_CHS)
    else:
        visible.update({FIELD_FLOPPY, FIELD_IMG_SYSTEM_FORMAT})
    if boot_active:
        visible.add(FIELD_BOOT_MODE)
    if show_freedos:
        visible.update({FIELD_FREEDOS_SOURCE, FIELD_FETCH_FREEDOS})
    if show_dos_profile and boot_mode is BootMode.PCDOS71:
        visible.add(FIELD_FETCH_PCDOS71)
    if show_dos_profile:
        visible.add(FIELD_DOS_PROFILE)
    if show_ibm_dos_version:
        visible.add(FIELD_IBM_DOS_VERSION)
    if show_boot_assets:
        visible.add(FIELD_BOOT_ASSETS)
    if is_vhd or state.img_system_format:
        visible.add(FIELD_CUSTOM_PAYLOAD)
    if show_freedos_url:
        visible.add(FIELD_FREEDOS_URL)
    return visible


def _safe_geometry_source(state: FormState) -> GeometrySource:
    """Coerce ``state.geometry_source`` to a known enum value.

    Falls back to SIZE for unknown values so an out-of-date saved
    state never breaks the UI.  See also ``infer_geometry_source``
    which initializes the field from legacy non-geometry-source
    states (e.g. external scripts that set bios_drive_type or
    custom_chs directly).
    """
    try:
        return GeometrySource(state.geometry_source)
    except ValueError:
        return GeometrySource.SIZE


def infer_geometry_source(state: FormState) -> GeometrySource:
    """Pick the geometry source that matches the existing state.

    Precedence (matches ``CreateRequest`` validation order in
    ``disk.py``): custom CHS wins over BIOS preset wins over static
    size.  Used to initialise the geometry-source picker from saved
    states or external scripts that drove the form without setting
    ``geometry_source`` explicitly.
    """
    if state.custom_chs.strip():
        return GeometrySource.CUSTOM_CHS
    if state.bios_drive_type and _bios_spec(state) is not None:
        return GeometrySource.PRESET
    return GeometrySource.SIZE


def coerce_on_geometry_source_change(state: FormState) -> FormState:
    """Clear the inactive geometry inputs when the user picks a source.

    SIZE       -> clear bios_drive_type + custom_chs.
    PRESET     -> clear custom_chs; size_text stays as a fallback.
    CUSTOM_CHS -> clear bios_drive_type.
    """
    source = _safe_geometry_source(state)
    if source is GeometrySource.SIZE:
        return replace(state, bios_drive_type="", custom_chs="")
    if source is GeometrySource.PRESET:
        return replace(state, custom_chs="")
    if source is GeometrySource.CUSTOM_CHS:
        return replace(state, bios_drive_type="")
    return state


def geometry_preview_text(state: FormState) -> str:
    """Render a one-line preview of the effective VHD geometry.

    Used by the TUI / GUI to show a live cyl x head x spt + MB
    summary directly under the geometry-source picker, so the user
    sees what they'll get before clicking Create.  Returns '' when
    no preview is meaningful (IMG mode, empty / invalid inputs).
    """
    if not _is_vhd(state):
        return ""
    source = _safe_geometry_source(state)
    if source is GeometrySource.PRESET:
        spec = _bios_spec(state)
        if spec is None:
            return ""
        size_mb = spec.cylinders * spec.heads * spec.sectors_per_track * 512 // 1024 // 1024
        return f"-> {size_mb} MB ({spec.cylinders} cyl x {spec.heads} head x {spec.sectors_per_track} spt)"
    if source is GeometrySource.CUSTOM_CHS:
        try:
            chs = _parse_chs_text(state.custom_chs)
        except DosForgeError:
            return ""
        if chs is None:
            return ""
        cyl, heads, spt = chs
        size_mb = cyl * heads * spt * 512 // 1024 // 1024
        return f"-> {size_mb} MB ({cyl} cyl x {heads} head x {spt} spt)"
    text = state.size_text.strip()
    if not text:
        return ""
    try:
        size_bytes = parse_size(text)
    except Exception:
        return ""
    size_mb = size_bytes // 1024 // 1024
    # Append the effective cap so the user sees at a glance the
    # ceiling for the current boot mode + FAT format combination
    # (e.g. "max 2048 MB for FAT16" on FreeDOS / MSDOS622).
    suffix = ""
    try:
        rule = _BOOT_MODE_MEDIA_RULES.get(BootMode(state.boot_mode))
        fmt = DiskFormat(state.disk_format)
    except ValueError:
        rule = None
        fmt = None
    if rule is not None and fmt is not None:
        max_mb = _state_aware_max_mb(state, rule, fmt)
        if max_mb is not None:
            suffix = f" (max {_render_mb(max_mb)} for {fmt.value})"
    return f"-> {size_mb} MB (geometry auto-derived from size){suffix}"


def effective_size_text(state: FormState) -> str:
    """Return the size string the form will actually submit to disk.py.

    Uses the geometry-source picker (v0.8.0+) to pick the active
    input: BIOS preset -> derived from CHS, custom CHS -> derived
    from the CYL,HEAD,SPT triplet, plain size -> the size_text Input
    as-is.
    """
    source = _safe_geometry_source(state)
    if source is GeometrySource.PRESET:
        spec = _bios_spec(state)
        if spec is not None:
            return f"{spec.size_mb}M"
    elif source is GeometrySource.CUSTOM_CHS:
        try:
            chs = _parse_chs_text(state.custom_chs)
        except DosForgeError:
            chs = None
        if chs is not None:
            cyl, heads, spt = chs
            return f"{cyl * heads * spt * 512 // 1024 // 1024}M"
    return state.size_text


@dataclass(frozen=True, slots=True)
class _BootMediaRule:
    allowed_formats: frozenset[DiskFormat]
    preferred_format: DiskFormat | None = None
    max_mb: int | None = None
    per_format_min_mb: dict[DiskFormat, int] = field(default_factory=dict)


_BOOT_MODE_MEDIA_RULES: dict[BootMode, _BootMediaRule] = {
    BootMode.NONE: _BootMediaRule(frozenset({DiskFormat.FAT12, DiskFormat.FAT16, DiskFormat.FAT32})),
    BootMode.FREEDOS: _BootMediaRule(frozenset({DiskFormat.FAT12, DiskFormat.FAT16, DiskFormat.FAT32})),
    BootMode.MSDOS71: _BootMediaRule(frozenset({DiskFormat.FAT16, DiskFormat.FAT32})),
    BootMode.PCDOS71: _BootMediaRule(frozenset({DiskFormat.FAT16, DiskFormat.FAT32}), preferred_format=DiskFormat.FAT32, per_format_min_mb={DiskFormat.FAT32: 1024}),
    # IBM 8088/V20: cap shifts by ibm_dos_version (DOS33=32 MiB,
    # DOS50=504 MiB).  The dynamic cap is applied via
    # _state_aware_max_mb so the rule itself only enforces the
    # FAT format restriction.  ``max_mb=None`` here lets the
    # state-aware helper drive both the live snap and the
    # validate_media_step gate without being clamped by a stale
    # 32 MiB floor.
    BootMode.IBM8088: _BootMediaRule(frozenset({DiskFormat.FAT12, DiskFormat.FAT16})),
    BootMode.MSDOS33: _BootMediaRule(frozenset({DiskFormat.FAT12, DiskFormat.FAT16}), max_mb=32),
    # MS-DOS 3.31 Microsoft kernel only reads BPB.total_sectors_16
    # (uint16) -- same 32 MiB cap as MS-DOS 3.30.  Compaq DOS 3.31
    # (compaq331) has a FAT16B-capable kernel that lifts the cap to
    # ~504 MiB.
    BootMode.MSDOS331: _BootMediaRule(frozenset({DiskFormat.FAT16}), max_mb=32),
    # Compaq DOS 3.31 FAT16B (BIGDOS) supports partitions up to
    # ~504 MiB (the Compaq-specific FORMAT cap; matches
    # COMPAQ331_MAX_BYTES in size.py).
    BootMode.COMPAQ331: _BootMediaRule(frozenset({DiskFormat.FAT16}), max_mb=504),
    BootMode.MSDOS5: _BootMediaRule(frozenset({DiskFormat.FAT16})),
    BootMode.MSDOS6: _BootMediaRule(frozenset({DiskFormat.FAT16})),
    BootMode.MSDOS622: _BootMediaRule(frozenset({DiskFormat.FAT16})),
    BootMode.PCDOS: _BootMediaRule(frozenset({DiskFormat.FAT12, DiskFormat.FAT16})),
    BootMode.PCDOS7: _BootMediaRule(frozenset({DiskFormat.FAT12, DiskFormat.FAT16})),
    BootMode.PCDOS2000: _BootMediaRule(frozenset({DiskFormat.FAT12, DiskFormat.FAT16})),
    BootMode.COMPAQ2: _BootMediaRule(frozenset({DiskFormat.FAT12}), max_mb=16),
    # IBM PC-DOS 3.00 (1984): FAT12 only (FAT16 was added in PC-DOS 3.10),
    # max ~16 MiB partition.  Works on both MFM and IDE controllers but
    # defaults to MFM for 1984-authentic hardware.
    BootMode.PCDOS3: _BootMediaRule(frozenset({DiskFormat.FAT12}), max_mb=16),
    # Microsoft MS-DOS 3.00 [Compaq OEM] (1985): same constraints as
    # PCDOS3 -- FAT12 only, 16 MiB cap, defaults to MFM for
    # 1985-authentic Compaq DeskPro / Portable Plus hardware.
    BootMode.COMPAQ3: _BootMediaRule(frozenset({DiskFormat.FAT12}), max_mb=16),
    # Digital Research DR DOS 6.0 (1991): supports FAT12 and FAT16
    # (DR-DOS 6 carries an IBM-3.3-class BPB with hidden_sectors).
    # Max ~32 MiB FAT16 partition.  Works on both MFM and IDE
    # controllers; no special MFM auto-snap (1991 mainstream hardware).
    BootMode.DRDOS6: _BootMediaRule(frozenset({DiskFormat.FAT12, DiskFormat.FAT16}), max_mb=32),
    # Caldera DR-DOS 7.03 (1999): supports FAT16B (BIGDOS) up to
    # 2 GiB FAT16, plus FAT12 for floppies.  FAT32 LBA support is
    # left as a follow-up.  Works on IDE controllers.
    BootMode.DRDOS7: _BootMediaRule(frozenset({DiskFormat.FAT12, DiskFormat.FAT16}), max_mb=2048),
}


def boot_media_rule(boot_mode: BootMode) -> _BootMediaRule | None:
    return _BOOT_MODE_MEDIA_RULES.get(boot_mode)


def _state_aware_max_mb(state: FormState, rule: "_BootMediaRule", fmt: DiskFormat) -> int | None:
    """Return the effective size cap taking state-dependent extras into account.

    Some boot modes have a cap that depends on a secondary field
    (e.g. IBM8088's cap shifts from 32 MiB to 504 MiB when
    ibm_dos_version flips from DOS33 to DOS50).  Returns the
    tighter of the rule cap, the FAT-format cap, and any
    state-dependent extra cap.
    """
    base = _effective_max_mb(rule, fmt)
    try:
        boot_mode = BootMode(state.boot_mode)
    except ValueError:
        return base
    # IBM 8088/V20 mode: DOS33 -> 32 MiB, DOS50 -> 504 MiB.
    if boot_mode is BootMode.IBM8088:
        try:
            ver = IBMDOSVersion(state.ibm_dos_version)
        except ValueError:
            ver = IBMDOSVersion.DOS33
        ibm_cap = 32 if ver is IBMDOSVersion.DOS33 else 504
        if base is None:
            return ibm_cap
        return min(base, ibm_cap)
    return base


def _snap_format_for_boot_mode(state: FormState, *, force_preferred: bool) -> FormState:
    rule = _BOOT_MODE_MEDIA_RULES.get(BootMode(state.boot_mode))
    if rule is None:
        return state
    current = DiskFormat(state.disk_format)
    if force_preferred and rule.preferred_format is not None:
        return replace(state, disk_format=rule.preferred_format.value)
    if current in rule.allowed_formats:
        return state
    if DiskFormat.FAT16 in rule.allowed_formats:
        return replace(state, disk_format=DiskFormat.FAT16.value)
    return replace(state, disk_format=sorted(rule.allowed_formats, key=lambda f: f.value)[0].value)


def _render_mb(mb: int) -> str:
    if mb >= 1024 and mb % 1024 == 0:
        return f"{mb // 1024}G"
    return f"{mb}M"


def _snap_size_for_boot_mode(state: FormState) -> FormState:
    if not _is_vhd(state):
        return state
    rule = _BOOT_MODE_MEDIA_RULES.get(BootMode(state.boot_mode))
    if rule is None:
        return state
    fmt = DiskFormat(state.disk_format)
    min_mb = rule.per_format_min_mb.get(fmt)
    # Cap by the tighter of per-boot-mode max_mb, the FAT format's
    # own cap (FAT12=32 MiB, FAT16=2 GiB, FAT32=2 TiB), and any
    # state-dependent extra cap (e.g. IBM8088 DOS33=32 MiB vs
    # DOS50=504 MiB).
    max_mb = _state_aware_max_mb(state, rule, fmt)
    try:
        size_bytes = parse_size(state.size_text)
    except DosForgeError:
        if min_mb is not None:
            return replace(state, size_text=_render_mb(min_mb))
        if max_mb is not None:
            return replace(state, size_text=_render_mb(max_mb))
        return state
    if max_mb is not None and size_bytes > max_mb * 1024 * 1024:
        return replace(state, size_text=_render_mb(max_mb))
    if min_mb is not None and size_bytes < min_mb * 1024 * 1024:
        return replace(state, size_text=_render_mb(min_mb))
    return state


def coerce_on_media_change(state: FormState) -> FormState:
    if MediaType(state.media_type) is MediaType.IMG:
        return replace(
            state,
            img_system_format=False,
            boot_mode=BootMode.NONE.value,
            disk_controller="",
            custom_chs="",
            bios_drive_type="",
            geometry_source=GeometrySource.SIZE.value,
        )
    return state


def apply_ibm_default_size(state: FormState, *, force: bool) -> FormState:
    if not _is_vhd(state):
        return state
    if force or state.size_text.strip().upper() in {"", "512M"}:
        return replace(state, size_text="32M")
    return state


def default_boot_assets_for(boot_mode: BootMode) -> str:
    """Return the canonical ``dosassets/<subdir>`` name for a boot mode.

    Used to pre-populate the Boot assets directory Input in both TUI
    and GUI when the user picks a boot mode in Step 1.  The user can
    still edit the field after to point at a custom directory or full
    path; this just gives a predictable default that matches
    dosforge's ``dosassets/<mode>/`` convention.

    Empty string for ``BootMode.NONE`` since data-disk-only builds
    have no boot assets.
    """
    if boot_mode is BootMode.NONE:
        return ""
    return boot_mode.value


def coerce_on_boot_change(state: FormState) -> FormState:
    boot_mode = BootMode(state.boot_mode)
    # Snap the Boot assets path FIRST so every early-return branch
    # below inherits the right default (dataclass.replace preserves
    # boot_assets when later replace() calls only touch other fields).
    state = replace(state, boot_assets=default_boot_assets_for(boot_mode))
    if boot_mode is BootMode.COMPAQ2:
        return replace(
            state,
            media_type=MediaType.VHD.value,
            disk_controller=DiskController.MFM.value,
            disk_format=DiskFormat.FAT12.value,
            size_text="10M",
            bios_drive_type="phoenix:1",
            geometry_source=GeometrySource.PRESET.value,
            custom_chs="",
            img_system_format=False,
            ibm_dos_version=IBMDOSVersion.DOS33.value,
        )
    if boot_mode is BootMode.PCDOS3:
        return replace(
            state,
            media_type=MediaType.VHD.value,
            disk_controller=DiskController.MFM.value,
            disk_format=DiskFormat.FAT12.value,
            size_text="10M",
            bios_drive_type="phoenix:1",
            geometry_source=GeometrySource.PRESET.value,
            custom_chs="",
            img_system_format=False,
            ibm_dos_version=IBMDOSVersion.DOS33.value,
        )
    if boot_mode is BootMode.COMPAQ3:
        return replace(
            state,
            media_type=MediaType.VHD.value,
            disk_controller=DiskController.MFM.value,
            disk_format=DiskFormat.FAT12.value,
            size_text="10M",
            bios_drive_type="phoenix:1",
            geometry_source=GeometrySource.PRESET.value,
            custom_chs="",
            img_system_format=False,
            ibm_dos_version=IBMDOSVersion.DOS33.value,
        )
    if boot_mode in {BootMode.MSDOS33, BootMode.PCDOS} or (
        boot_mode is BootMode.IBM8088 and IBMDOSVersion(state.ibm_dos_version) is IBMDOSVersion.DOS33
    ):
        state = replace(state, disk_controller=DiskController.MFM.value, ibm_dos_version=IBMDOSVersion.DOS33.value)
        if _is_vhd(state):
            state = apply_ibm_default_size(state, force=True)
    else:
        state = replace(state, disk_controller="")
        if _is_vhd(state) and boot_mode is BootMode.IBM8088:
            state = apply_ibm_default_size(state, force=True)
    # Default geometry source for the non-early-return branches is
    # SIZE -- those branches snap size_text but not bios_drive_type
    # or custom_chs, so the user lands on the simple static-size
    # input.  Clear any stale preset / CHS so the state matches.
    state = replace(
        state,
        geometry_source=GeometrySource.SIZE.value,
        bios_drive_type="",
        custom_chs="",
    )
    state = _snap_format_for_boot_mode(state, force_preferred=True)
    return _snap_size_for_boot_mode(state)


def coerce_on_format_change(state: FormState) -> FormState:
    return _snap_size_for_boot_mode(state)


def validate_media_step(state: FormState) -> str | None:
    if not _is_vhd(state):
        return None
    try:
        boot_mode = BootMode(state.boot_mode)
        fmt = DiskFormat(state.disk_format)
    except ValueError:
        return None
    rule = _BOOT_MODE_MEDIA_RULES.get(boot_mode)
    if rule is None:
        return None
    if rule.allowed_formats and fmt not in rule.allowed_formats:
        return f"{boot_mode.value} only supports {', '.join(f.value for f in rule.allowed_formats)}."
    try:
        size_bytes = parse_size(state.size_text)
    except DosForgeError as exc:
        return str(exc)
    min_mb = rule.per_format_min_mb.get(fmt)
    if min_mb is not None and size_bytes < min_mb * 1024 * 1024:
        if boot_mode is BootMode.PCDOS71 and fmt is DiskFormat.FAT32:
            return (
                "PC-DOS 7.1 FAT32 partitions must be at least 1 GiB. "
                "PC-DOS FORMAT32 rejects smaller partitions with 'The drive specified is too small to use FAT32.' "
                f"Increase the size to {_render_mb(min_mb)} or pick FAT16 for smaller drives."
            )
        return f"{boot_mode.value} {fmt.value} partitions must be at least {_render_mb(min_mb)}."
    # Enforce the tighter of per-boot-mode max_mb, FAT format cap,
    # and any state-dependent extra cap so the user gets a clear
    # error at Next instead of waiting for Create to fail.
    max_mb = _state_aware_max_mb(state, rule, fmt)
    if max_mb is not None and size_bytes > max_mb * 1024 * 1024:
        if rule.max_mb is not None and rule.max_mb <= max_mb:
            return f"{boot_mode.value} partitions cannot exceed {_render_mb(rule.max_mb)}."
        if boot_mode is BootMode.IBM8088:
            try:
                ver = IBMDOSVersion(state.ibm_dos_version)
            except ValueError:
                ver = IBMDOSVersion.DOS33
            ver_label = "MS-DOS 3.3" if ver is IBMDOSVersion.DOS33 else "MS-DOS 5.0"
            return (
                f"IBM 8088/V20 + {ver_label} partitions cannot exceed "
                f"{_render_mb(max_mb)}."
            )
        return (
            f"{fmt.value} partitions cannot exceed {_render_mb(max_mb)} "
            "(the FAT format's hard cap)."
        )
    # FreeDOS auto-download bundle ships FAT16 boot assets only
    # (BOOTSECT_FAT16.BIN); FAT32 requires the LOCAL source with
    # BOOTSECT_FAT32.BIN.  Surface the gate at Next rather than
    # letting the user reach Create.
    if (
        boot_mode is BootMode.FREEDOS
        and fmt is DiskFormat.FAT32
    ):
        try:
            source = FreeDOSSource(state.freedos_source)
        except ValueError:
            source = FreeDOSSource.AUTO
        if source is FreeDOSSource.AUTO:
            return (
                "FreeDOS auto-download bundle ships FAT16 boot assets only. "
                "For FAT32, switch FreeDOS source to 'Local FreeDOS assets' "
                "(needs BOOTSECT_FAT32.BIN in your dosassets/freedos/ folder)."
            )
    return None


def build_time_hint(state: FormState) -> str | None:
    try:
        boot_mode = BootMode(state.boot_mode)
    except ValueError:
        return None
    if not _is_vhd(state) and not state.img_system_format:
        return None
    return build_time_hint_for_boot_mode(boot_mode)


def build_time_hint_for_boot_mode(boot_mode: BootMode) -> str | None:
    return None


def coerce_on_ibm_version_change(state: FormState) -> FormState:
    if _is_vhd(state):
        # Re-snap to the new ibm_dos_version's cap (DOS33=32 MiB,
        # DOS50=504 MiB) -- _snap_size_for_boot_mode reads
        # ibm_dos_version through _state_aware_max_mb so changing the
        # version now clamps size DOWN (if user goes 504->32) or
        # leaves room to grow (if user goes 32->504).
        state = apply_ibm_default_size(state, force=False)
        return _snap_size_for_boot_mode(state)
    return state


def coerce_on_img_system_format_change(state: FormState) -> FormState:
    if not state.img_system_format:
        return replace(state, boot_mode=BootMode.NONE.value)
    return state


def build_create_request(state: FormState) -> CreateRequest:
    path_text = state.output_path.strip()
    if not path_text:
        raise DosForgeError("Create path is required.")

    media_type = MediaType(state.media_type)
    floppy_type = FloppyType(state.floppy_type)
    disk_controller = DiskController(state.disk_controller) if state.disk_controller else None
    custom_chs = _parse_chs_text(state.custom_chs)
    bios_drive_type = parse_bios_drive_slug(state.bios_drive_type) if state.bios_drive_type else None

    size_text = state.size_text.strip()
    boot_value = state.boot_mode
    img_system_format = state.img_system_format
    boot_assets_text = state.boot_assets.strip()
    custom_payload_text = state.custom_payload.strip()
    custom_payload_path = Path(custom_payload_text).expanduser() if custom_payload_text else None

    if media_type is MediaType.VHD and boot_value == BootMode.IBM8088.value and size_text.upper() == "512M":
        size_text = "32M"

    if media_type is MediaType.VHD:
        if bios_drive_type is not None:
            vendor, type_id = bios_drive_type
            size_bytes = lookup_bios_drive_type(vendor, type_id).size_bytes
        elif custom_chs is not None:
            cyl, heads, spt = custom_chs
            size_bytes = cyl * heads * spt * 512
        elif size_text:
            size_bytes = parse_size(size_text)
        elif custom_payload_path is not None:
            size_bytes = 1
        else:
            raise DosForgeError("Create size is required.")
    else:
        size_bytes = floppy_type.size_bytes

    return CreateRequest(
        path=Path(path_text).expanduser(),
        size_bytes=size_bytes,
        disk_format=DiskFormat(state.disk_format) if media_type is MediaType.VHD else DiskFormat.FAT16,
        media_type=media_type,
        floppy_type=floppy_type,
        img_system_format=img_system_format,
        label=state.volume_label.strip() or None,
        overwrite=state.overwrite,
        boot_mode=BootMode(boot_value) if (media_type is MediaType.VHD or img_system_format) else BootMode.NONE,
        freedos_source=FreeDOSSource(state.freedos_source),
        boot_assets_path=Path(boot_assets_text).expanduser() if boot_assets_text else None,
        freedos_download_url=state.freedos_url.strip() or None,
        msdos_install_profile=MSDOSInstallProfile(state.dos_profile),
        ibm_dos_version=IBMDOSVersion(state.ibm_dos_version),
        custom_payload_path=custom_payload_path,
        bios_drive_type=bios_drive_type,
        disk_controller=disk_controller,
        custom_chs=custom_chs,
    )


def build_summary(state: FormState) -> list[tuple[str, str]]:
    media_type = MediaType(state.media_type)
    boot_mode = BootMode(state.boot_mode)
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
        media_line = f"IMG  floppy={floppy}  bootable={'yes' if state.img_system_format else 'no'}"
    boot_line = boot_mode.value if boot_mode is not BootMode.NONE else "(none)"
    if boot_mode is not BootMode.NONE and media_type is MediaType.VHD:
        boot_line += f"  profile={MSDOSInstallProfile(state.dos_profile).value}"
    rows = [
        ("Output", path),
        ("Media", media_line),
        ("Controller", state.disk_controller or "auto"),
        ("Boot", boot_line),
        ("Assets", boot_assets),
        ("Payload", custom_payload),
        ("Label", label_text),
        ("Overwrite", "yes" if state.overwrite else "no"),
    ]
    if build_time_hint(state):
        rows.append(("Build time", "slow - see status bar"))
    return rows
