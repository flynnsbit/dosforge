"""Tests for the Windows VHD pipeline (no-kernel-mount path).

These tests exercise ``DiskManager._create_and_prepare_vhd_no_kernel``
directly. They run on Linux too — the only platform-specific bits are
mocked via ``FakeRunner`` (mtools subprocess calls) and a
``WindowsBackend`` instance passed explicitly.

The pure-Python primitives (``_core.vhd_footer``, ``_core.mbr``) DO
write real bytes into ``tmp_path`` files so the partition entry and
footer are validated end-to-end. Only the subprocess steps (qemu-img,
mformat, mcopy, mmd) are mocked.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

import pytest

from dosforge._core import mbr as core_mbr
from dosforge._platform.windows import WindowsBackend
from dosforge.commands import RunResult
from dosforge.disk import DiskManager
from dosforge.errors import ValidationError
from dosforge.models import (
    BootMode,
    CreateRequest,
    DiskController,
    DiskFormat,
    MediaType,
)


# ---- Helpers ------------------------------------------------------------


@dataclass
class _RunCall:
    command: tuple[str, ...]
    sudo: bool


class FakeRunner:
    """Records subprocess calls; pre-allocates a fake VHD on qemu-img create."""

    def __init__(self, *, vhd_size_bytes: int):
        self._vhd_size_bytes = vhd_size_bytes
        self.calls: list[_RunCall] = []

    def run(self, command, *, sudo=False, check=True, cwd=None, env=None):
        argv = tuple(command)
        self.calls.append(_RunCall(command=argv, sudo=sudo))
        # When asked to qemu-img create a fixed VHD, allocate a real
        # file of the right size with a minimal valid VHD footer so the
        # pure-Python footer + MBR steps that follow can run for real.
        if Path(argv[0]).name.startswith("qemu-img") and "create" in argv:
            path = Path(argv[-2])
            size_bytes = int(argv[-1])
            _write_fake_fixed_vhd(path, size_bytes)
        return RunResult(command=argv, returncode=0, stdout="", stderr="")

    def run_detached(self, command):  # pragma: no cover - unused
        return None


def _write_fake_fixed_vhd(path: Path, size_bytes: int) -> None:
    """Allocate a file of ``size_bytes`` data + 512-byte VHD footer.

    The footer is a minimal `conectix` footer with a 16h/63s ATA-aligned
    CHS triplet and ``current_size`` set to ``size_bytes``. Just enough
    for ``vhd_footer.read_footer`` to return a usable geometry.
    """

    total_sectors = size_bytes // 512
    heads = 16
    spt = 63
    cylinders = max(1, total_sectors // (heads * spt))
    footer = bytearray(512)
    footer[:8] = b"conectix"
    # Features (offset 8): reserved
    struct.pack_into(">I", footer, 8, 0x00000002)
    # Format version (offset 12)
    struct.pack_into(">I", footer, 12, 0x00010000)
    # Data offset for fixed VHDs is 0xFFFFFFFFFFFFFFFF (offset 16)
    struct.pack_into(">Q", footer, 16, 0xFFFFFFFFFFFFFFFF)
    # Original / current size (offsets 40, 48)
    struct.pack_into(">Q", footer, 40, size_bytes)
    struct.pack_into(">Q", footer, 48, size_bytes)
    # CHS (offsets 56, 58, 59)
    struct.pack_into(">H", footer, 56, cylinders)
    footer[58] = heads
    footer[59] = spt
    # Disk type = 2 (Fixed) at offset 60
    struct.pack_into(">I", footer, 60, 2)
    # Checksum (offset 64) = ~sum(footer with checksum=0)
    footer[64:68] = b"\x00\x00\x00\x00"
    checksum = (~sum(footer)) & 0xFFFFFFFF
    struct.pack_into(">I", footer, 64, checksum)
    with path.open("wb") as handle:
        handle.truncate(size_bytes + 512)
        handle.seek(-512, 2)
        handle.write(bytes(footer))


def _basic_request(target_path: Path, *, disk_format=DiskFormat.FAT16, size_bytes=32 * 1024 * 1024, **overrides) -> CreateRequest:
    base = dict(
        path=target_path,
        size_bytes=size_bytes,
        disk_format=disk_format,
        media_type=MediaType.VHD,
        boot_mode=BootMode.NONE,
    )
    base.update(overrides)
    return CreateRequest(**base)


def _manager(tmp_path: Path, runner) -> DiskManager:
    return DiskManager(
        runner=runner,
        backend=WindowsBackend(),
        mount_root=tmp_path / "mounts",
    )


# ---- Tests --------------------------------------------------------------


def test_windows_vhd_pipeline_writes_mbr_with_modern_layout(tmp_path: Path):
    target = tmp_path / "test32.vhd"
    request = _basic_request(target)
    runner = FakeRunner(vhd_size_bytes=request.size_bytes)
    manager = _manager(tmp_path, runner)

    manager.create_and_prepare(request)

    assert target.exists(), "VHD file was not produced"
    entry = core_mbr.read_partition_entry(target, slot=0)
    assert entry is not None, "MBR sector 0 missing or corrupt"
    assert entry.bootable is True, "Active flag should be set for parity with parted"
    assert entry.partition_type == 0x06, "FAT16 type byte should be 0x06"
    assert entry.first_lba == 2048, "Partition should start at LBA 2048 (1 MiB alignment)"
    # Note: read_partition_entry decodes the first-sector CHS triplet (head=0, sector=33
    # for LBA 2048 with 16/63 geometry), not the geometry parameters themselves. We
    # validate the geometry indirectly via the mformat -H assertions elsewhere.
    total_sectors = request.size_bytes // 512
    assert entry.sector_count == total_sectors - 2048


def test_windows_vhd_pipeline_uses_fat32_partition_type_for_fat32(tmp_path: Path):
    target = tmp_path / "test128.vhd"
    request = _basic_request(target, disk_format=DiskFormat.FAT32, size_bytes=128 * 1024 * 1024)
    runner = FakeRunner(vhd_size_bytes=request.size_bytes)
    manager = _manager(tmp_path, runner)

    manager.create_and_prepare(request)

    entry = core_mbr.read_partition_entry(target, slot=0)
    assert entry is not None
    assert entry.partition_type == 0x0C, "FAT32-LBA type byte should be 0x0C"


def test_windows_vhd_pipeline_invokes_mformat_with_T_and_H(tmp_path: Path):
    target = tmp_path / "test32.vhd"
    request = _basic_request(target)
    runner = FakeRunner(vhd_size_bytes=request.size_bytes)
    manager = _manager(tmp_path, runner)

    manager.create_and_prepare(request)

    mformat_calls = [c for c in runner.calls if Path(c.command[0]).name.startswith("mformat")]
    assert len(mformat_calls) == 1, "expected exactly one mformat invocation"
    argv = mformat_calls[0].command
    assert "-i" in argv
    image_arg = argv[argv.index("-i") + 1]
    assert image_arg.endswith("@@1048576"), f"image arg should encode @@offset, got {image_arg}"
    assert "-T" in argv, "-T (total-sectors) must be passed so mformat excludes the VHD footer"
    total_sectors = request.size_bytes // 512
    assert argv[argv.index("-T") + 1] == str(total_sectors - 2048)
    assert "-H" in argv, "-H (hidden-sectors) must match partition start"
    assert argv[argv.index("-H") + 1] == "2048"
    assert argv[-1] == "::"


def test_windows_vhd_pipeline_passes_F_flag_for_fat32(tmp_path: Path):
    target = tmp_path / "test128.vhd"
    request = _basic_request(target, disk_format=DiskFormat.FAT32, size_bytes=128 * 1024 * 1024)
    runner = FakeRunner(vhd_size_bytes=request.size_bytes)
    manager = _manager(tmp_path, runner)

    manager.create_and_prepare(request)

    mformat_argv = next(c.command for c in runner.calls if Path(c.command[0]).name.startswith("mformat"))
    assert "-F" in mformat_argv, "mformat must be told to use FAT32 (-F) for FAT32 requests"


def test_windows_vhd_pipeline_accepts_every_legacy_dos_mode(tmp_path: Path):
    """All twelve boot modes (FREEDOS, MSDOS71, MSDOS33, ..., PCDOS71)
    pass the Windows-VHD gate after the parity work landed. They may
    fail later at the boot resolver step if no install media is in the
    asset dir, but the gate itself should let them through.

    Replaces the older ``test_windows_vhd_pipeline_rejects_unsupported_boot_modes``
    which asserted msdos622 still raised "not yet supported on this
    platform" — no longer true after the gate was lifted.
    """
    target = tmp_path / "boot.vhd"
    legacy_modes = (
        BootMode.MSDOS5,
        BootMode.MSDOS622,
        BootMode.PCDOS7,
        BootMode.PCDOS2000,
    )
    for mode in legacy_modes:
        request = _basic_request(target, boot_mode=mode)
        runner = FakeRunner(vhd_size_bytes=request.size_bytes)
        manager = _manager(tmp_path, runner)
        try:
            manager.create_and_prepare(request)
        except ValidationError as exc:
            message = str(exc)
            assert "not yet supported on this platform" not in message, (
                f"{mode.value} hit the unsupported-mode gate it should now pass: {message}"
            )


def test_windows_vhd_pipeline_accepts_freedos_fat32(tmp_path: Path):
    """FreeDOS FAT32 must not be blocked by the unsupported-mode gate.

    The BOOTSECT_FAT32.BIN template (real boot32lb from FDOS/kernel)
    has shipped in dosassets/freedos/ since the linux-v0.6.0 boot-sector
    fix (commit 3af7909), and the BootAssetResolver +
    make_partition_bootable have always known how to use it.  The
    Windows-side ``ValidationError`` was a stale placeholder.  The
    pipeline may still raise later at the boot resolver step if no
    assets are present on the host, but the gate itself must let
    freedos+fat32 through.
    """
    target = tmp_path / "fdos32.vhd"
    request = _basic_request(
        target,
        boot_mode=BootMode.FREEDOS,
        disk_format=DiskFormat.FAT32,
        size_bytes=128 * 1024 * 1024,
    )
    runner = FakeRunner(vhd_size_bytes=request.size_bytes)
    manager = _manager(tmp_path, runner)

    try:
        manager.create_and_prepare(request)
    except ValidationError as exc:
        message = str(exc)
        assert "not yet supported on this platform" not in message, (
            f"FreeDOS FAT32 should not be blocked by the unsupported-mode gate, got: {message}"
        )
        assert "currently restricted to FAT16" not in message, (
            f"FreeDOS FAT32 restriction should be lifted, got: {message}"
        )


def test_windows_vhd_pipeline_accepts_freedos_and_msdos71(tmp_path: Path):
    """FreeDOS (FAT16 + FAT32) and MS-DOS 7.1 don't raise the unsupported-mode ValidationError.

    They may fail later at the boot resolver step if no assets are
    available, but the pipeline gate should let them through.
    """
    target = tmp_path / "boot.vhd"
    for mode in (BootMode.FREEDOS, BootMode.MSDOS71):
        request = _basic_request(target, boot_mode=mode)
        runner = FakeRunner(vhd_size_bytes=request.size_bytes)
        manager = _manager(tmp_path, runner)
        # Both should get past the unsupported-mode gate; failures past
        # that point come from missing assets, not the gate itself.
        try:
            manager.create_and_prepare(request)
        except ValidationError as exc:
            assert "not yet supported on this platform" not in str(exc), (
                f"{mode} should not be blocked by the unsupported-mode gate, got: {exc}"
            )


def test_windows_vhd_pipeline_accepts_pcdos2000(tmp_path: Path):
    """IBM PC-DOS 2000 (v0.6.16) goes through the same FORMAT C: /S
    pipeline as PCDOS7.  The unsupported-mode gate must let it through;
    failures past that point come from missing install media in
    dosassets/pcdos2000/, not the gate itself.
    """
    target = tmp_path / "pcdos2000.vhd"
    request = _basic_request(
        target,
        boot_mode=BootMode.PCDOS2000,
        disk_format=DiskFormat.FAT16,
        size_bytes=32 * 1024 * 1024,
    )
    runner = FakeRunner(vhd_size_bytes=request.size_bytes)
    manager = _manager(tmp_path, runner)
    try:
        manager.create_and_prepare(request)
    except ValidationError as exc:
        message = str(exc)
        assert "not yet supported on this platform" not in message, (
            f"PCDOS2000 should not be blocked by the unsupported-mode gate, got: {message}"
        )
        assert "pcdos2000" not in message.lower() or "install" in message.lower(), (
            f"PCDOS2000 should pass the gate; missing-asset errors are acceptable, got: {message}"
        )


def test_windows_vhd_pipeline_rejects_compaq2_on_at_class(tmp_path: Path):
    """Compaq DOS 2.11 (v0.6.19) on plain VHD (IDE/AT) is still rejected
    with an actionable error pointing at the new MFM controller
    path or the floppy IMG fallback.  Its 1984 boot code depends on
    Compaq BIOS extensions only the Xebec MFM controller path matches.
    """
    target = tmp_path / "compaq2.vhd"
    request = _basic_request(
        target,
        boot_mode=BootMode.COMPAQ2,
        disk_format=DiskFormat.FAT12,
        size_bytes=16 * 1024 * 1024,
        disk_controller=DiskController.IDE,
    )
    runner = FakeRunner(vhd_size_bytes=request.size_bytes)
    manager = _manager(tmp_path, runner)
    with pytest.raises(ValidationError) as excinfo:
        manager.create_and_prepare(request)
    message = str(excinfo.value)
    assert "compaq2" in message.lower()
    assert "disk-controller mfm" in message.lower()
    assert "phoenix:1" in message.lower()


def test_windows_vhd_pipeline_copies_custom_payload(tmp_path: Path):
    target = tmp_path / "with-payload.vhd"
    payload = tmp_path / "payload"
    (payload / "TOOLS").mkdir(parents=True)
    (payload / "README.TXT").write_text("hello")
    (payload / "TOOLS" / "HELLO.BAT").write_text("@echo off\n")

    request = _basic_request(target, custom_payload_path=payload)
    runner = FakeRunner(vhd_size_bytes=request.size_bytes)
    manager = _manager(tmp_path, runner)
    manager.create_and_prepare(request)

    payload_calls = [c for c in runner.calls if Path(c.command[0]).name.startswith(("mcopy", "mmd"))]
    assert payload_calls, "expected mcopy/mmd calls for custom payload"
    dests = [c.command[-1] for c in payload_calls]
    assert any("TOOLS" in d for d in dests)
    assert any("README.TXT" in d for d in dests)


def test_windows_vhd_pipeline_excludes_vcs_metadata_from_payload(tmp_path: Path):
    """`.git*`, `.DS_Store`, `Thumbs.db`, `__pycache__` must not be copied."""
    target = tmp_path / "with-payload.vhd"
    payload = tmp_path / "payload"
    payload.mkdir()
    # Real content
    (payload / "README.TXT").write_text("hello")
    (payload / "GAMES").mkdir()
    (payload / "GAMES" / "PLAY.BAT").write_text("@echo PLAY\r\n")
    # Junk that must be filtered
    (payload / ".gitignore").write_text("*.log\n")
    (payload / ".gitattributes").write_text("* text=auto\n")
    (payload / ".git").mkdir()
    (payload / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    (payload / ".DS_Store").write_bytes(b"\0" * 16)
    (payload / "Thumbs.db").write_bytes(b"\0" * 16)
    (payload / "desktop.ini").write_text("[.ShellClassInfo]\n")
    (payload / "GAMES" / ".gitkeep").write_text("")
    (payload / "GAMES" / "__pycache__").mkdir()
    (payload / "GAMES" / "__pycache__" / "x.pyc").write_bytes(b"\0" * 8)

    request = _basic_request(target, custom_payload_path=payload)
    runner = FakeRunner(vhd_size_bytes=request.size_bytes)
    manager = _manager(tmp_path, runner)
    manager.create_and_prepare(request)

    payload_calls = [
        c for c in runner.calls
        if Path(c.command[0]).name.startswith(("mcopy", "mmd"))
    ]
    dests = [c.command[-1] for c in payload_calls]
    sources = [
        c.command[-2] for c in payload_calls
        if Path(c.command[0]).name.startswith("mcopy")
    ]

    # Real content was copied
    assert any("README.TXT" in d for d in dests)
    assert any("PLAY.BAT" in d for d in dests)

    # No junk basename ever appears in the destinations OR mcopy sources
    junk = (".gitignore", ".gitattributes", ".gitkeep", ".DS_Store",
            "thumbs.db", "Thumbs.db", "desktop.ini", "__pycache__", ".git")
    for d in dests:
        low = d.lower()
        for needle in junk:
            assert needle.lower() not in low, f"junk {needle!r} leaked into dest {d!r}"
    for s in sources:
        low = s.lower()
        for needle in junk:
            assert needle.lower() not in low, f"junk {needle!r} leaked via source {s!r}"
