"""``dosforge grow`` — enlarge a fixed VHD and optionally stage content.

Grows an existing FAT16 / FAT32 VHD to a new size and can append
staging content (e.g. eXoDOS games). Implementation is extract →
rebuild via ``create_and_prepare`` → reinject (see
:mod:`dosforge._grow_impl`); user files and CONFIG/AUTOEXEC survive.
Custom hand-patched MBR/VBR is replaced with dosforge's standard
bootstrap for the chosen mode.

Public surface:

* :class:`GrowManifest` — the JSON-friendly request contract.
* :func:`load_manifest_from_json` — parse + validate a manifest file.
* :func:`validate_grow_request` — surface-level invariants
  (supported boot mode, growth direction, source existence).
* :func:`grow_vhd` — full pipeline entrypoint.

Supported boot modes (deliberately narrow — covers FAT16 BIGDOS plus
FAT32 LBA, the two formats worth growing):

* ``BootMode.COMPAQ331`` — FAT16 ≤ 504 MiB
* ``BootMode.MSDOS622`` — FAT16 ≤ 2 GiB
* ``BootMode.MSDOS71`` — FAT32 ≤ 32 GiB practical
* ``BootMode.FREEDOS`` — FAT32 ≤ 32 GiB practical

Every other boot mode either caps at 32 MiB (DOS 3.x / 2.x) or carries
quirks that don't justify the maintenance cost (DR-DOS, PC-DOS 7.1
SGTK, etc.).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .errors import ValidationError
from .models import BootMode
from .size import FAT16_MAX_BYTES, FAT32_MAX_BYTES, parse_size


GROWABLE_BOOT_MODES: frozenset[BootMode] = frozenset({
    BootMode.COMPAQ331,
    BootMode.MSDOS622,
    BootMode.MSDOS71,
    BootMode.FREEDOS,
})
"""Boot modes that ``dosforge grow`` will accept.

See module docstring for the rationale. Any boot mode not in this set
must be rebuilt via ``dosforge create`` -- in-place grow is not
supported for it.
"""


MANIFEST_SCHEMA_VERSION = 1
"""Bump when GrowManifest fields are added / renamed / removed in a
backward-incompatible way. exodosconverter should pin to this value."""


@dataclass(frozen=True, slots=True)
class StagingSource:
    """A single staging directory to be copied into the grown VHD."""

    src: Path
    """Host-side directory whose contents will be copied verbatim."""

    dest: str
    """Target path on the VHD's C: drive (e.g. ``C:\\GAMES`` or
    ``\\GAMES``). Must be an absolute DOS path. Leading drive letter
    is optional and ignored -- everything stages to C:."""


@dataclass(frozen=True, slots=True)
class GrowManifest:
    """Request envelope for ``dosforge grow``.

    Mirrors the JSON contract callers serialize on disk. All path
    fields are stored as :class:`pathlib.Path` after parsing.
    """

    target_vhd: Path
    """Existing fixed-format VHD to grow in place."""

    new_size_bytes: int
    """Desired final disk size in bytes (must be > current size).
    Use :func:`dosforge.size.parse_size` to parse human-friendly
    inputs like ``"2G"`` or ``"512M"``."""

    boot_mode: BootMode | None = None
    """Boot mode the VHD was originally built with.  When ``None``
    (the default), :func:`grow_vhd` auto-detects from root system
    files: KERNEL.SYS → FreeDOS; MSDOS.SYS text ``[Paths]`` →
    MS-DOS 7.10; IO.SYS/MSDOS.SYS binary → MS-DOS 6.22.
    IBMBIO.COM/IBMDOS.COM are ambiguous (Compaq 3.31 / PC-DOS /
    DR-DOS / …) and require an explicit ``--boot-mode``.  Must be in
    :data:`GROWABLE_BOOT_MODES` when set."""

    staging_sources: tuple[StagingSource, ...] = ()
    """Zero or more directories to copy into the grown VHD. Empty
    tuple is valid (resize-only)."""

    boot_probe: bool = True
    """When True (default), boot the grown VHD in headless QEMU
    before atomically replacing the old VHD. Catches bootability
    regressions before the user loses their original disk."""

    keep_backup: bool = True
    """When True (default), the original VHD is renamed to
    ``<target>.bak`` instead of deleted. exodosconverter may set
    this to False if it's already snapshotting the source disk."""

    schema_version: int = MANIFEST_SCHEMA_VERSION
    """Pinned schema version. Manifests with a different version are
    rejected (no silent best-effort upgrades)."""

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dict.  Round-trip safe via
        :func:`load_manifest_from_dict`."""

        return {
            "schema_version": self.schema_version,
            "target_vhd": str(self.target_vhd),
            "new_size_bytes": self.new_size_bytes,
            "boot_mode": self.boot_mode.value if self.boot_mode else None,
            "staging_sources": [
                {"src": str(s.src), "dest": s.dest}
                for s in self.staging_sources
            ],
            "boot_probe": self.boot_probe,
            "keep_backup": self.keep_backup,
        }


def load_manifest_from_dict(payload: dict[str, Any]) -> GrowManifest:
    """Parse a manifest dict (already JSON-decoded) into a
    :class:`GrowManifest`.

    Raises :class:`ValidationError` for malformed input. Does NOT
    perform on-disk validation -- call :func:`validate_grow_request`
    separately for that.
    """

    if not isinstance(payload, dict):
        raise ValidationError("Grow manifest must be a JSON object.")

    version = payload.get("schema_version", MANIFEST_SCHEMA_VERSION)
    if version != MANIFEST_SCHEMA_VERSION:
        raise ValidationError(
            f"Unsupported grow manifest schema_version {version!r} "
            f"(dosforge supports {MANIFEST_SCHEMA_VERSION})."
        )

    required = ("target_vhd", "new_size_bytes")
    missing = [k for k in required if k not in payload]
    if missing:
        raise ValidationError(
            f"Grow manifest is missing required field(s): {', '.join(missing)}."
        )

    boot_mode: BootMode | None = None
    raw_boot_mode = payload.get("boot_mode")
    if raw_boot_mode:
        try:
            boot_mode = BootMode(raw_boot_mode)
        except ValueError as exc:
            raise ValidationError(
                f"Unknown boot_mode in grow manifest: {raw_boot_mode!r}."
            ) from exc

    raw_size = payload["new_size_bytes"]
    if isinstance(raw_size, str):
        new_size_bytes = parse_size(raw_size)
    elif isinstance(raw_size, int) and not isinstance(raw_size, bool):
        new_size_bytes = raw_size
    else:
        raise ValidationError(
            "Grow manifest 'new_size_bytes' must be an integer (bytes) or "
            "a size string like '2G'."
        )

    raw_sources = payload.get("staging_sources", []) or []
    if not isinstance(raw_sources, list):
        raise ValidationError("Grow manifest 'staging_sources' must be a list.")
    sources: list[StagingSource] = []
    for entry in raw_sources:
        if not isinstance(entry, dict) or "src" not in entry or "dest" not in entry:
            raise ValidationError(
                "Each staging_sources entry must be an object with "
                "'src' and 'dest' fields."
            )
        sources.append(StagingSource(src=Path(entry["src"]), dest=str(entry["dest"])))

    return GrowManifest(
        target_vhd=Path(payload["target_vhd"]),
        new_size_bytes=new_size_bytes,
        boot_mode=boot_mode,
        staging_sources=tuple(sources),
        boot_probe=bool(payload.get("boot_probe", True)),
        keep_backup=bool(payload.get("keep_backup", True)),
    )


def load_manifest_from_json(path: Path) -> GrowManifest:
    """Read + parse a JSON grow manifest from disk."""

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValidationError(f"Cannot read grow manifest {path}: {exc}") from exc
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"Grow manifest {path} is not valid JSON: {exc}") from exc
    return load_manifest_from_dict(payload)


def validate_grow_request(manifest: GrowManifest) -> None:
    """Surface-level validation that does NOT touch the on-disk
    filesystem layout of the VHD.

    Checks:
    - ``boot_mode`` is in :data:`GROWABLE_BOOT_MODES`
    - target VHD exists and is a fixed-format VHD (size > 512 and the
      last 512 bytes start with the ``conectix`` magic)
    - ``new_size_bytes`` is strictly larger than the existing VHD's
      data area
    - ``new_size_bytes`` is within the chosen filesystem's hard cap
    - every staging source exists and is a directory
    - every staging dest looks like an absolute DOS path

    Raises :class:`ValidationError` with an actionable message on the
    first failure encountered.
    """

    if manifest.boot_mode is not None and manifest.boot_mode not in GROWABLE_BOOT_MODES:
        supported = ", ".join(sorted(m.value for m in GROWABLE_BOOT_MODES))
        raise ValidationError(
            f"dosforge grow does not support boot mode "
            f"{manifest.boot_mode.value!r}. Supported: {supported}. "
            "Use 'dosforge create' to rebuild from scratch in another mode."
        )

    target = manifest.target_vhd
    if not target.exists():
        raise ValidationError(f"Target VHD does not exist: {target}")
    if not target.is_file():
        raise ValidationError(f"Target VHD is not a regular file: {target}")
    try:
        file_size = target.stat().st_size
    except OSError as exc:
        raise ValidationError(f"Cannot stat target VHD {target}: {exc}") from exc
    if file_size < 1024:
        raise ValidationError(
            f"Target VHD {target} is too small to be a valid fixed VHD."
        )

    try:
        with target.open("rb") as fh:
            fh.seek(file_size - 512)
            footer_magic = fh.read(8)
    except OSError as exc:
        raise ValidationError(f"Cannot read VHD footer of {target}: {exc}") from exc
    if footer_magic != b"conectix":
        raise ValidationError(
            f"Target VHD {target} does not carry a 'conectix' fixed-VHD "
            "footer. dosforge grow only supports fixed-format VHDs."
        )

    # Data area excludes the 512-byte footer.
    current_data_size = file_size - 512
    if manifest.new_size_bytes <= current_data_size:
        raise ValidationError(
            f"new_size_bytes ({manifest.new_size_bytes}) must be strictly "
            f"larger than current VHD data size ({current_data_size}). "
            "dosforge grow does not shrink."
        )

    fat32_modes = {BootMode.MSDOS71, BootMode.FREEDOS}
    # When boot_mode is unspecified (will be auto-detected at grow
    # time), conservatively use the FAT32 cap so we don't refuse
    # valid grows up-front.  perform_grow re-checks size against the
    # detected mode after detection.
    if manifest.boot_mode is None or manifest.boot_mode in fat32_modes:
        max_bytes = FAT32_MAX_BYTES
        fs_label = "FAT32"
    else:
        max_bytes = FAT16_MAX_BYTES
        fs_label = "FAT16"
    if manifest.new_size_bytes > max_bytes:
        mode_label = manifest.boot_mode.value if manifest.boot_mode else "<auto-detect>"
        raise ValidationError(
            f"new_size_bytes ({manifest.new_size_bytes}) exceeds the "
            f"{fs_label} hard cap of {max_bytes} bytes for boot mode "
            f"{mode_label}."
        )

    for staging in manifest.staging_sources:
        if not staging.src.exists():
            raise ValidationError(
                f"Staging source does not exist: {staging.src}"
            )
        if not staging.src.is_dir():
            raise ValidationError(
                f"Staging source must be a directory: {staging.src}"
            )
        if not _looks_like_dos_absolute_path(staging.dest):
            raise ValidationError(
                f"Staging dest {staging.dest!r} must be an absolute DOS path "
                "(e.g. 'C:\\\\GAMES' or '\\\\GAMES')."
            )


def _looks_like_dos_absolute_path(dest: str) -> bool:
    """Loose check that ``dest`` looks like ``C:\\FOO`` or ``\\FOO``."""

    if not dest:
        return False
    stripped = dest.replace("/", "\\")
    if len(stripped) >= 3 and stripped[1] == ":" and stripped[2] == "\\":
        return True
    if stripped.startswith("\\"):
        return True
    return False


def grow_vhd(
    manifest: GrowManifest,
    *,
    progress_callback: "Callable[[str], None] | None" = None,
) -> None:
    """Apply a grow operation to ``manifest.target_vhd``.

    v1 implementation:

    1. Snapshot the existing VHD (MBR + first partition BPB).
    2. Validate the target size stays within the existing cluster
       band (FAT16/FAT32 ``mformat`` defaults).  Crossing a
       cluster-size boundary requires relaying out every file's
       cluster chain and is out of scope for v1 -- the caller is
       told to ``dosforge create`` a fresh VHD instead.
    3. Extract every file from the old partition to a host scratch
       directory via mtools (preserves mtime + hidden/system bits).
    4. Build a fresh empty bootable VHD at the new size with the
       same boot mode + filesystem format.
    5. Re-inject the extracted tree, skipping protected root-level
       system files (IO.SYS, COMMAND.COM, ...) so the fresh VHD's
       authentic bootstrap stays intact.
    6. Stage every ``manifest.staging_sources`` entry into its
       target DOS path.
    7. Optional: headless QEMU boot probe (default on, disable via
       ``--no-boot-probe``).  Temporarily injects an AUTOEXEC marker
       into the temp VHD, boots in QEMU, looks for the marker, then
       restores AUTOEXEC.  Probe failure aborts the grow with the
       original VHD intact.
    8. Crash-safe replace: fully write the new image beside the
       target, then rename into place (optionally moving the
       original to ``<target>.bak``). The original is never removed
       before the new image is complete.

    v1 limitations (tracked for v2):

    * The new VHD ships dosforge's standard MBR / VBR for the chosen
      boot mode -- any custom boot code the user hand-patched is
      lost.  All four supported modes (COMPAQ331 / MSDOS622 /
      MSDOS71 / FREEDOS) get the same authentic bootstrap they
      originally received, so this is a no-op for 99% of users.
    * ``IO.SYS`` cluster-2 contiguity isn't explicitly enforced
      (the fresh VHD's ``FORMAT C: /S`` step guarantees it for
      MS-DOS family, FreeDOS's kernel is FAT-chain-tolerant).

    ``progress_callback`` is invoked with short human-readable
    stage labels (e.g. ``"Extracting source VHD..."``) as
    :func:`perform_grow` walks through its 8-step pipeline.  Pass
    ``None`` (the default) for the silent CLI path.
    """

    validate_grow_request(manifest)

    from ._grow_impl import perform_grow

    perform_grow(manifest, progress_callback=progress_callback)


__all__ = [
    "GROWABLE_BOOT_MODES",
    "MANIFEST_SCHEMA_VERSION",
    "GrowManifest",
    "StagingSource",
    "grow_vhd",
    "load_manifest_from_dict",
    "load_manifest_from_json",
    "validate_grow_request",
]
