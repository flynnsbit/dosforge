"""Persistent state storage for mounted VHD records."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .errors import ValidationError
from .models import MountRecord
from .paths import app_state_file


@dataclass(slots=True)
class AppState:
    mounts: list[MountRecord] = field(default_factory=list)

    def to_json(self) -> dict[str, list[dict[str, str]]]:
        return {"mounts": [item.to_json() for item in self.mounts]}

    @classmethod
    def from_json(cls, payload: dict[str, list[dict[str, str]]]) -> "AppState":
        mounts_payload = payload.get("mounts", [])
        return cls(mounts=[MountRecord.from_json(item) for item in mounts_payload])


class StateStore:
    def __init__(self, state_file: Path | None = None) -> None:
        self.state_file = state_file or app_state_file()
        self.state_file.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> AppState:
        if not self.state_file.exists():
            return AppState()
        with self.state_file.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict):
            raise ValidationError("State file is corrupted: expected object root.")
        return AppState.from_json(payload)

    def save(self, state: AppState) -> None:
        temp_path = self.state_file.with_suffix(".tmp")
        with temp_path.open("w", encoding="utf-8") as handle:
            json.dump(state.to_json(), handle, indent=2, sort_keys=True)
        temp_path.replace(self.state_file)

    def list_mounts(self) -> list[MountRecord]:
        return list(self.load().mounts)

    def add_mount(self, record: MountRecord) -> None:
        state = self.load()
        state.mounts = [
            item
            for item in state.mounts
            if str(item.mount_point) != str(record.mount_point) and str(item.vhd_path) != str(record.vhd_path)
        ]
        state.mounts.append(record)
        self.save(state)

    def remove_mount(self, mount_point: Path) -> MountRecord:
        state = self.load()
        target = str(mount_point)
        kept: list[MountRecord] = []
        removed: MountRecord | None = None
        for item in state.mounts:
            if str(item.mount_point) == target:
                removed = item
            else:
                kept.append(item)
        if removed is None:
            raise ValidationError(f"No tracked mount record for {mount_point}")
        state.mounts = kept
        self.save(state)
        return removed

    def find_mount(self, mount_point: Path) -> MountRecord | None:
        target = str(mount_point)
        for item in self.load().mounts:
            if str(item.mount_point) == target:
                return item
        return None
