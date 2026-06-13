"""mtools-based image operations: ls / cat / get / put / rm / mkdir.

Lets dosforge users browse, extract, and modify DOS disk images without
mounting them. Works on both Linux and Windows since every operation
goes through ``mtools`` (mdir / mtype / mcopy / mdel / mmd) against the
image file directly via the ``@@<offset>`` syntax for partitioned VHDs
or against the file as-is for flat floppy IMG / VFD images.

The "image" in every public function below is **either**:

- a flat floppy image (``.img`` / ``.ima`` / ``.vfd``) — no MBR; the
  whole file IS the FAT12 filesystem. Resolution: bare path.
- a partitioned VHD (``.vhd``) — sector 0 is an MBR. Resolution: pick
  the first non-empty partition entry (``slot=0`` by default) and
  return ``<path>@@<first_lba*512>``. Callers can override the partition
  slot via the ``partition`` kwarg (1-indexed for the public surface).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from ._core import mbr as core_mbr
from ._platform import get_backend
from .commands import subprocess_no_window_kwargs
from .errors import ValidationError


_FLAT_IMAGE_SUFFIXES = frozenset({".img", ".ima", ".vfd", ".dsk", ".xdf"})
_VHD_SUFFIXES = frozenset({".vhd", ".vhdx"})


@dataclass(frozen=True)
class ResolvedImage:
    """Result of resolving an image path to an mtools-compatible target."""

    image_path: Path
    """Original on-disk file path."""

    mtools_target: str
    """Argument to pass to ``mcopy -i`` / ``mdir -i`` / etc. Either the
    bare path (flat image) or ``<path>@@<offset>`` (partitioned VHD)."""

    partition_offset_bytes: int
    """Byte offset to the FAT filesystem inside ``image_path``. 0 for
    flat images, multiple of 512 for partitioned VHDs."""

    is_partitioned: bool


def resolve_image(image_path: Path, *, partition: int | None = None) -> ResolvedImage:
    """Return an ``mtools_target`` string for ``image_path``.

    ``partition`` is 1-indexed and only meaningful for partitioned
    VHDs. ``None`` (default) picks the first non-empty partition entry.
    """

    resolved = image_path.expanduser().resolve()
    if not resolved.is_file():
        raise ValidationError(f"Image file not found: {resolved}")

    suffix = resolved.suffix.lower()
    if suffix in _FLAT_IMAGE_SUFFIXES:
        if partition is not None:
            raise ValidationError(
                f"Flat image {resolved.name} has no partition table; "
                "--partition is only valid for .vhd images."
            )
        return ResolvedImage(
            image_path=resolved,
            mtools_target=str(resolved),
            partition_offset_bytes=0,
            is_partitioned=False,
        )

    # Partitioned VHD path: scan slots 0..3 for the requested partition.
    if suffix in _VHD_SUFFIXES:
        slot_range = range(4) if partition is None else (partition - 1,)
        if partition is not None and not 1 <= partition <= 4:
            raise ValidationError("--partition must be in the range 1..4.")
        for slot in slot_range:
            entry = core_mbr.read_partition_entry(resolved, slot=slot)
            if entry is None:
                if partition is not None:
                    raise ValidationError(
                        f"Partition slot {partition} of {resolved.name} is empty."
                    )
                continue
            offset = entry.first_lba * 512
            return ResolvedImage(
                image_path=resolved,
                mtools_target=f"{resolved}@@{offset}",
                partition_offset_bytes=offset,
                is_partitioned=True,
            )
        raise ValidationError(
            f"{resolved.name} has no MBR partition entries. "
            "Use `dosforge create` to format a partition first."
        )

    # Last-chance fallback: try to read it as a VHD (some users name
    # VHDs without the suffix); otherwise reject.
    entry = core_mbr.read_partition_entry(resolved, slot=0)
    if entry is not None:
        offset = entry.first_lba * 512
        return ResolvedImage(
            image_path=resolved,
            mtools_target=f"{resolved}@@{offset}",
            partition_offset_bytes=offset,
            is_partitioned=True,
        )
    raise ValidationError(
        f"Unsupported image type {resolved.suffix!r}. Supported extensions: "
        + ", ".join(sorted(_FLAT_IMAGE_SUFFIXES | _VHD_SUFFIXES))
    )


def _mtool(name: str) -> str:
    return get_backend().tool_path(name)


def _normalize_dos_path(path: str) -> str:
    """Convert a user-supplied DOS path to mtools ``::path`` form.

    Accepts forward and backslash separators. A bare ``/`` or empty
    path becomes ``::/`` (root). Always returns a string starting with
    ``::`` so callers can pass it straight to mtools.

    Also tolerates DOS drive-letter prefixes (``C:\\CONFIG.SYS`` or
    ``C:CONFIG.SYS``). mtools' own drive bookkeeping is configured
    via the ``-i <image>`` flag, so any caller-supplied drive letter
    must be stripped before the path reaches mcopy — otherwise mcopy
    sees ``::/C:/CONFIG.SYS`` and reports the file not found.
    """

    cleaned = (path or "/").replace("\\", "/")
    # Strip a leading DOS drive letter ("C:", "c:", etc.). mtools
    # treats the image bound by ``-i`` as the only drive, so any
    # drive prefix the user types is redundant and breaks the path.
    if len(cleaned) >= 2 and cleaned[0].isalpha() and cleaned[1] == ":":
        cleaned = cleaned[2:] or "/"
    # Strip any leading ':' the caller may have included.
    while cleaned.startswith(":"):
        cleaned = cleaned[1:]
    if not cleaned.startswith("/"):
        cleaned = "/" + cleaned
    return "::" + cleaned


def _run_mtool(argv: list[str], *, capture: bool = False, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Run an mtool subprocess. Raises ValidationError on non-zero exit
    unless ``capture`` is True, in which case the result is returned
    for the caller to inspect (used by cat to stream stdout).
    """

    try:
        completed = subprocess.run(
            argv,
            check=False,
            capture_output=not capture,
            text=not capture,
            cwd=cwd,
            **subprocess_no_window_kwargs(),
        )
    except FileNotFoundError as exc:
        raise ValidationError(f"Missing external command: {argv[0]}") from exc

    if not capture and completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        stdout = (completed.stdout or "").strip()
        detail = stderr or stdout or f"exit code {completed.returncode}"
        raise ValidationError(f"{argv[0]} failed: {detail}")
    return completed


def ls(image_path: Path, dos_path: str = "/", *, partition: int | None = None, all_files: bool = False) -> str:
    """List the contents of ``dos_path`` in ``image_path``. Returns the
    raw mdir text so the CLI can print it directly. ``all_files=True``
    shows hidden + system files via mdir's ``-a`` flag.
    """

    resolved = resolve_image(image_path, partition=partition)
    argv = [_mtool("mdir"), "-i", resolved.mtools_target]
    if all_files:
        argv.append("-a")
    argv.append(_normalize_dos_path(dos_path))
    completed = _run_mtool(argv)
    return (completed.stdout or "").rstrip("\n")


def cat(image_path: Path, dos_path: str, *, partition: int | None = None) -> bytes:
    """Read ``dos_path`` from ``image_path`` and return its bytes.

    Uses ``mcopy -i ... ::<path> -`` (mtools' stdout sink). Returns
    the raw bytes so binary files are preserved (text-mode conversion
    is the caller's responsibility).
    """

    resolved = resolve_image(image_path, partition=partition)
    argv = [
        _mtool("mcopy"),
        "-i",
        resolved.mtools_target,
        _normalize_dos_path(dos_path),
        "-",
    ]
    try:
        completed = subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=False,
            **subprocess_no_window_kwargs(),
        )
    except FileNotFoundError as exc:
        raise ValidationError(f"Missing external command: {argv[0]}") from exc
    if completed.returncode != 0:
        detail = (completed.stderr.decode("utf-8", "replace") or f"exit {completed.returncode}").strip()
        raise ValidationError(f"mcopy failed: {detail}")
    return completed.stdout


def get(
    image_path: Path,
    dos_path: str,
    local_path: Path,
    *,
    partition: int | None = None,
) -> Path:
    """Copy ``dos_path`` out of ``image_path`` to ``local_path``.

    If ``local_path`` is an existing directory, the file is written
    inside it with its DOS basename. Returns the actual local path
    written. Passes ``cwd=parent`` + a bare filename to mtools so the
    Windows ``Drive 'C:' not supported`` parse-as-DOS-drive failure
    doesn't trigger.
    """

    resolved = resolve_image(image_path, partition=partition)
    local = local_path.expanduser().resolve()
    if local.is_dir():
        basename = dos_path.replace("\\", "/").rstrip("/").split("/")[-1] or "FILE"
        local = local / basename
    local.parent.mkdir(parents=True, exist_ok=True)
    if local.exists():
        local.unlink()
    argv = [
        _mtool("mcopy"),
        "-i",
        resolved.mtools_target,
        _normalize_dos_path(dos_path),
        local.name,
    ]
    _run_mtool(argv, cwd=local.parent)
    return local


def put(
    image_path: Path,
    local_path: Path,
    dos_path: str | None = None,
    *,
    partition: int | None = None,
    overwrite: bool = True,
) -> str:
    """Copy ``local_path`` into ``image_path`` at ``dos_path``.

    ``dos_path`` defaults to ``/<basename>`` if omitted. Returns the
    DOS path the file landed at.
    """

    resolved = resolve_image(image_path, partition=partition)
    src = local_path.expanduser().resolve()
    if not src.is_file():
        raise ValidationError(f"Source file not found: {src}")
    target_dos = dos_path or f"/{src.name}"
    argv = [_mtool("mcopy"), "-i", resolved.mtools_target]
    if overwrite:
        argv.append("-o")
    argv.extend([str(src), _normalize_dos_path(target_dos)])
    _run_mtool(argv)
    return target_dos


def rm(image_path: Path, dos_path: str, *, partition: int | None = None) -> None:
    """Delete a file at ``dos_path`` inside ``image_path``."""

    resolved = resolve_image(image_path, partition=partition)
    argv = [
        _mtool("mdel"),
        "-i",
        resolved.mtools_target,
        _normalize_dos_path(dos_path),
    ]
    _run_mtool(argv)


def mkdir(image_path: Path, dos_path: str, *, partition: int | None = None) -> None:
    """Create a directory at ``dos_path`` inside ``image_path``."""

    resolved = resolve_image(image_path, partition=partition)
    argv = [
        _mtool("mmd"),
        "-i",
        resolved.mtools_target,
        _normalize_dos_path(dos_path),
    ]
    _run_mtool(argv)
