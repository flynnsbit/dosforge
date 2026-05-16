from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from dosforge.errors import ValidationError
from dosforge.models import MountRecord
from dosforge.state import StateStore


def _record(vhd: str, mount: str, nbd: str = "/dev/nbd0") -> MountRecord:
    return MountRecord(
        vhd_path=Path(vhd),
        nbd_device=nbd,
        partition_device=f"{nbd}p1",
        mount_point=Path(mount),
        mounted_at=datetime.now(timezone.utc),
    )


def test_state_add_list_remove(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    first = _record("/tmp/a.vhd", "/mnt/a")
    second = _record("/tmp/b.vhd", "/mnt/b", nbd="/dev/nbd1")

    store.add_mount(first)
    store.add_mount(second)
    mounts = store.list_mounts()
    assert len(mounts) == 2
    assert {str(item.mount_point) for item in mounts} == {"/mnt/a", "/mnt/b"}

    removed = store.remove_mount(Path("/mnt/a"))
    assert str(removed.vhd_path) == "/tmp/a.vhd"
    mounts_after = store.list_mounts()
    assert len(mounts_after) == 1
    assert str(mounts_after[0].mount_point) == "/mnt/b"


def test_state_remove_unknown_mount_raises(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    with pytest.raises(ValidationError):
        store.remove_mount(Path("/mnt/missing"))
