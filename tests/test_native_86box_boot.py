from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

import pytest

from vhdmaker.disk import DiskManager
from vhdmaker.models import BootMode, CreateRequest, DiskFormat, MediaType


def _native_86box_ready() -> tuple[bool, str]:
    command_template = os.environ.get("VHDMAKER_86BOX_BOOT_COMMAND", "").strip()
    if not command_template:
        return (
            False,
            "Set VHDMAKER_86BOX_BOOT_COMMAND to enable required native 86Box boot checks.",
        )
    if "{image}" not in command_template:
        return (False, "VHDMAKER_86BOX_BOOT_COMMAND must include {image} placeholder.")
    return (True, "")


_NATIVE_86BOX_READY, _NATIVE_86BOX_REASON = _native_86box_ready()

pytestmark = [
    pytest.mark.native_linux,
    pytest.mark.native_boot,
    pytest.mark.native_86box,
    pytest.mark.skipif(not _NATIVE_86BOX_READY, reason=_NATIVE_86BOX_REASON),
]


def test_native_86box_boot_contract_msdos71_fat32(tmp_path: Path) -> None:
    assets_root = (Path.cwd() / "msdos7").resolve()
    if not assets_root.exists():
        pytest.skip(f"MS-DOS 7.1 assets directory not found: {assets_root}")

    manager = DiskManager()
    image_path = tmp_path / "msdos71-fat32-86box.vhd"
    request = CreateRequest(
        path=image_path,
        size_bytes=300 * 1024 * 1024,
        disk_format=DiskFormat.FAT32,
        media_type=MediaType.VHD,
        boot_mode=BootMode.MSDOS71,
        boot_assets_path=assets_root,
        overwrite=True,
    )
    manager.create_and_prepare(request)

    command_template = os.environ["VHDMAKER_86BOX_BOOT_COMMAND"]
    command = shlex.split(command_template.format(image=str(image_path)))
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    output = f"{completed.stdout}\n{completed.stderr}"
    prompt_markers = ("C:\\>", "A:\\>")
    failure_markers = (
        "Disk I/O error",
        "Non-System disk or disk error",
        "No bootable device",
        "Missing operating system",
    )

    assert not any(marker in output for marker in failure_markers), output[-4000:]
    assert any(marker in output for marker in prompt_markers), output[-4000:]
