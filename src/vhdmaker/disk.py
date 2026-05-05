"""Core VHD creation, formatting, mount and unmount workflows."""

from __future__ import annotations

import json
import os
import re
import struct
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from uuid import uuid4

from .boot import BootAssetResolver, BootInstaller
from .commands import CommandRunner
from .dependencies import BOOT_COMMANDS, REQUIRED_COMMANDS, assert_dependencies, find_missing
from .errors import ValidationError
from .models import BootMode, CreateRequest, DiskFormat, FreeDOSSource, MountRecord
from .paths import app_mount_root
from .size import normalize_label, validate_size_for_format
from .state import StateStore


@dataclass(slots=True)
class PrivilegeCheck:
    name: str
    status: str
    detail: str


class DiskManager:
    def __init__(
        self,
        runner: CommandRunner | None = None,
        state_store: StateStore | None = None,
        boot_resolver: BootAssetResolver | None = None,
        boot_installer: BootInstaller | None = None,
        mount_root: Path | None = None,
        nbd_sys_block_root: Path | None = None,
        nbd_dev_root: Path | None = None,
        nbd_discovery_timeout: float = 5.0,
    ) -> None:
        self.runner = runner or CommandRunner()
        self.state_store = state_store or StateStore()
        self.mount_root = mount_root or app_mount_root()
        self.mount_root.mkdir(parents=True, exist_ok=True)
        self.boot_resolver = boot_resolver or BootAssetResolver(self.runner)
        self.boot_installer = boot_installer or BootInstaller(self.runner)
        self.nbd_sys_block_root = nbd_sys_block_root or Path("/sys/class/block")
        self.nbd_dev_root = nbd_dev_root or Path("/dev")
        self.nbd_discovery_timeout = nbd_discovery_timeout

    def preflight(self, request: CreateRequest | None = None) -> None:
        if request is None:
            assert_dependencies()
        else:
            assert_dependencies(boot_mode=request.boot_mode, freedos_source=request.freedos_source)
        self._ensure_sudo_ready()

    def create_and_prepare(self, request: CreateRequest) -> None:
        self.preflight(request)
        self._validate_create_request(request)

        target_path = request.path.expanduser().resolve()
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if target_path.exists():
            if request.overwrite:
                target_path.unlink()
            else:
                raise ValidationError(f"VHD already exists: {target_path}")

        self._create_fixed_vhd(target_path, request.size_bytes)
        request.path = target_path
        fat16_bios_chs = (
            self._read_vpc_bios_chs_geometry(target_path) if request.disk_format is DiskFormat.FAT16 else None
        )

        def configure(nbd_device: str) -> None:
            partition_device = self._partition_and_format(
                nbd_device=nbd_device,
                disk_format=request.disk_format,
                label=normalize_label(request.label),
            )
            if request.boot_mode is not BootMode.NONE:
                assets = self.boot_resolver.resolve(request)
                self.boot_installer.make_partition_bootable(
                    disk_device=nbd_device,
                    partition_device=partition_device,
                    disk_format=request.disk_format,
                    assets=assets,
                    bios_chs=fat16_bios_chs,
                )

        self._with_connected_nbd(target_path, configure, image_format="vpc")

    def mount_vhd(self, path: Path) -> MountRecord:
        self.preflight()
        vhd_path = path.expanduser().resolve()
        if not vhd_path.exists():
            raise ValidationError(f"VHD file does not exist: {vhd_path}")

        nbd_device = self._connect_nbd(vhd_path)
        mountpoint = self._next_mountpoint(vhd_path)
        mountpoint.mkdir(parents=True, exist_ok=True)
        mounted = False
        try:
            partition_device = self._wait_for_partition(nbd_device)
            mount_options = "uid={uid},gid={gid},umask=022,shortname=mixed".format(
                uid=os.getuid(),
                gid=os.getgid(),
            )
            self.runner.run(
                ["mount", "-t", "vfat", "-o", mount_options, partition_device, str(mountpoint)],
                sudo=True,
            )
            mounted = True
            record = MountRecord.create(
                vhd_path=vhd_path,
                nbd_device=nbd_device,
                partition_device=partition_device,
                mount_point=mountpoint,
            )
            self.state_store.add_mount(record)
            return record
        except Exception:
            if mounted:
                self.runner.run(["umount", str(mountpoint)], sudo=True, check=False)
            self._disconnect_nbd(nbd_device, check=False)
            mountpoint.rmdir()
            raise

    def unmount(self, mount_point: Path) -> MountRecord:
        self.preflight()
        record = self.state_store.find_mount(mount_point.expanduser().resolve())
        if record is None:
            raise ValidationError(f"Mount point is not tracked by vhdmaker: {mount_point}")

        self.runner.run(["umount", str(record.mount_point)], sudo=True)
        self._disconnect_nbd(record.nbd_device, check=True)
        self.state_store.remove_mount(record.mount_point)
        if record.mount_point.exists():
            record.mount_point.rmdir()
        return record

    def list_mounts(self) -> list[MountRecord]:
        return self.state_store.list_mounts()

    def privilege_diagnostics(self) -> list[PrivilegeCheck]:
        checks: list[PrivilegeCheck] = []

        missing_required = find_missing(REQUIRED_COMMANDS)
        if missing_required:
            checks.append(
                PrivilegeCheck(
                    name="Required commands",
                    status="fail",
                    detail=f"Missing: {', '.join(missing_required)}",
                )
            )
        else:
            checks.append(
                PrivilegeCheck(
                    name="Required commands",
                    status="ok",
                    detail="All base runtime commands are available.",
                )
            )

        missing_boot = find_missing(BOOT_COMMANDS)
        if missing_boot:
            checks.append(
                PrivilegeCheck(
                    name="Boot workflow tools",
                    status="warn",
                    detail=(
                        "Missing boot-only commands: "
                        f"{', '.join(missing_boot)} (needed only for bootable image preparation)"
                    ),
                )
            )
        else:
            checks.append(
                PrivilegeCheck(
                    name="Boot workflow tools",
                    status="ok",
                    detail="Boot preparation commands are available.",
                )
            )

        if "sudo" in missing_required:
            checks.append(
                PrivilegeCheck(
                    name="Non-interactive sudo readiness",
                    status="fail",
                    detail="sudo is not installed. Install sudo and configure sudoers first.",
                )
            )
        else:
            result = self.runner.run(["true"], sudo=True, check=False)
            if result.returncode == 0:
                checks.append(
                    PrivilegeCheck(
                        name="Non-interactive sudo readiness",
                        status="ok",
                        detail="sudo -n calls are currently authorized.",
                    )
                )
            else:
                detail = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
                checks.append(
                    PrivilegeCheck(
                        name="Non-interactive sudo readiness",
                        status="fail",
                        detail=(
                            f"{detail}. Run `sudo -v` before launch or configure scoped NOPASSWD sudoers rules."
                        ),
                    )
                )

        candidates = self._list_nbd_candidates()
        if not candidates:
            checks.append(
                PrivilegeCheck(
                    name="NBD device availability",
                    status="warn",
                    detail=(
                        "No nbd devices are currently visible in sysfs; app will try "
                        "`sudo modprobe nbd max_part=16` when needed."
                    ),
                )
            )
        else:
            missing_nodes = [
                candidate.name for candidate in candidates if not (self.nbd_dev_root / candidate.name).exists()
            ]
            if missing_nodes:
                checks.append(
                    PrivilegeCheck(
                        name="NBD device availability",
                        status="warn",
                        detail=(
                            "NBD devices exist in sysfs but some /dev nodes are missing: "
                            f"{', '.join(missing_nodes)}"
                        ),
                    )
                )
            else:
                checks.append(
                    PrivilegeCheck(
                        name="NBD device availability",
                        status="ok",
                        detail=f"{len(candidates)} nbd device(s) detected and mapped in /dev.",
                    )
                )

        return checks

    def privilege_diagnostics_summary(self) -> tuple[bool, str]:
        checks = self.privilege_diagnostics()
        has_failures = any(check.status == "fail" for check in checks)
        marker = {"ok": "[OK]", "warn": "[WARN]", "fail": "[FAIL]"}
        lines = [
            f"{marker.get(check.status, '[INFO]')} {check.name}: {check.detail}"
            for check in checks
        ]
        headline = (
            "Privilege diagnostics found blocking issues."
            if has_failures
            else "Privilege diagnostics completed."
        )
        return (not has_failures, "\n".join([headline, *lines]))

    def open_in_files(self, path: Path) -> None:
        target = path.expanduser().resolve()
        if not target.exists():
            raise ValidationError(f"Cannot open missing path: {target}")
        self.runner.run_detached(["xdg-open", str(target)])

    def fetch_freedos_assets(self, destination: Path | None = None, download_url: str | None = None) -> Path:
        missing = find_missing(("mcopy", "mkfs.fat"))
        if missing:
            raise ValidationError(f"Missing required tools for FreeDOS extraction: {', '.join(missing)}")
        target = destination if destination is not None else (Path.cwd() / "freedos")
        return self.boot_resolver.export_latest_freedos_assets(
            target,
            image_url=download_url,
            include_full_fdos=True,
        )

    def _validate_create_request(self, request: CreateRequest) -> None:
        validate_size_for_format(request.size_bytes, request.disk_format)
        normalize_label(request.label)
        if (
            request.boot_mode is BootMode.FREEDOS
            and request.freedos_source is FreeDOSSource.AUTO
            and request.disk_format is DiskFormat.FAT32
        ):
            raise ValidationError(
                "FreeDOS auto-download boot mode currently supports FAT16 only. "
                "For FAT32, use local FreeDOS assets with BOOTSECT_FAT32.BIN."
            )

    def _create_fixed_vhd(self, path: Path, size_bytes: int) -> None:
        self.runner.run(
            ["qemu-img", "create", "-f", "vpc", "-o", "subformat=fixed", str(path), str(size_bytes)]
        )

    def _partition_and_format(self, *, nbd_device: str, disk_format: DiskFormat, label: str | None) -> str:
        self.runner.run(["parted", "--script", nbd_device, "mklabel", "msdos"], sudo=True)
        self.runner.run(
            [
                "parted",
                "--script",
                nbd_device,
                "mkpart",
                "primary",
                disk_format.parted_fs_label,
                "1MiB",
                "100%",
            ],
            sudo=True,
        )
        self.runner.run(
            ["parted", "--script", nbd_device, "set", "1", "boot", "on"],
            sudo=True,
            check=False,
        )
        if disk_format is DiskFormat.FAT32:
            self.runner.run(
                ["parted", "--script", nbd_device, "set", "1", "lba", "on"],
                sudo=True,
                check=False,
            )

        self.runner.run(["partprobe", nbd_device], sudo=True, check=False)
        partition_device = self._wait_for_partition(nbd_device)
        command = ["mkfs.fat", "-F", disk_format.mkfs_bits]
        if label:
            command += ["-n", label]
        command.append(partition_device)
        self.runner.run(command, sudo=True)
        return partition_device

    def _with_connected_nbd(
        self,
        vhd_path: Path,
        callback: Callable[[str], None],
        *,
        image_format: str | None = None,
    ) -> None:
        nbd_device = self._connect_nbd(vhd_path, image_format=image_format)
        try:
            callback(nbd_device)
        finally:
            self._disconnect_nbd(nbd_device, check=False)

    def _connect_nbd(self, path: Path, *, image_format: str | None = None) -> str:
        nbd_device = self._find_free_nbd()
        effective_format = image_format or self._detect_image_format(path)
        self.runner.run(
            ["qemu-nbd", "--format", effective_format, "--connect", nbd_device, str(path)],
            sudo=True,
        )
        self.runner.run(["partprobe", nbd_device], sudo=True, check=False)
        return nbd_device

    def _disconnect_nbd(self, nbd_device: str, *, check: bool) -> None:
        self.runner.run(["qemu-nbd", "--disconnect", nbd_device], sudo=True, check=check)

    def _wait_for_partition(self, nbd_device: str, timeout_seconds: float = 15.0) -> str:
        partition_path = Path(f"{nbd_device}p1")
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if partition_path.exists():
                return str(partition_path)
            self.runner.run(["partprobe", nbd_device], sudo=True, check=False)
            time.sleep(0.25)
        raise ValidationError(f"Partition device did not appear for {nbd_device} within {timeout_seconds:.0f}s.")

    def _find_free_nbd(self) -> str:
        candidates = self._list_nbd_candidates()
        if not candidates:
            result = self.runner.run(["modprobe", "nbd", "max_part=16"], sudo=True, check=False)
            if result.returncode != 0:
                detail = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
                raise ValidationError(
                    "No /dev/nbd* devices are available on this host, and loading the NBD module failed. "
                    f"Tried `sudo modprobe nbd max_part=16`: {detail}"
                )

            deadline = time.monotonic() + self.nbd_discovery_timeout
            while time.monotonic() < deadline:
                candidates = self._list_nbd_candidates()
                if candidates:
                    break
                time.sleep(0.2)
            if not candidates:
                raise ValidationError(
                    "No /dev/nbd* devices appeared after loading the NBD module. "
                    "Verify kernel support and run `sudo modprobe nbd nbds_max=16 max_part=16`."
                )

        missing_dev_nodes = 0
        for candidate in candidates:
            dev_path = self.nbd_dev_root / candidate.name
            if not dev_path.exists():
                missing_dev_nodes += 1
                continue

            pid_path = candidate / "pid"
            if not pid_path.exists():
                return str(dev_path)
            try:
                pid_text = pid_path.read_text(encoding="utf-8").strip()
            except OSError:
                continue
            if not pid_text:
                return str(dev_path)

        if missing_dev_nodes == len(candidates):
            raise ValidationError(
                "NBD devices were detected in sysfs, but device nodes are missing under /dev. "
                "Ensure udev is running and retry."
            )
        raise ValidationError("All nbd devices are in use. Unmount/disconnect a device and try again.")

    def _next_mountpoint(self, vhd_path: Path) -> Path:
        safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "-", vhd_path.stem).strip("-") or "vhd"
        return self.mount_root / f"{safe_stem}-{uuid4().hex[:8]}"

    def _list_nbd_candidates(self) -> list[Path]:
        return sorted(
            [path for path in self.nbd_sys_block_root.glob("nbd*") if path.name[3:].isdigit()],
            key=lambda entry: int(entry.name[3:]),
        )

    def _detect_image_format(self, path: Path) -> str:
        result = self.runner.run(["qemu-img", "info", "--output=json", str(path)])
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise ValidationError(f"Unable to parse qemu-img info output for {path}") from exc
        image_format = payload.get("format")
        if not isinstance(image_format, str) or not image_format:
            raise ValidationError(f"Unable to determine disk format for {path}")
        if image_format == "raw" and self._has_vpc_footer(path):
            return "vpc"
        return image_format

    def _has_vpc_footer(self, path: Path) -> bool:
        try:
            with path.open("rb") as handle:
                handle.seek(-512, os.SEEK_END)
                footer = handle.read(512)
        except OSError:
            return False
        return len(footer) == 512 and footer[:8] == b"conectix"

    def _read_vpc_bios_chs_geometry(self, path: Path) -> tuple[int, int] | None:
        try:
            with path.open("rb") as handle:
                handle.seek(-512, os.SEEK_END)
                footer = handle.read(512)
        except OSError:
            return None
        if len(footer) != 512 or footer[:8] != b"conectix":
            return None

        heads = footer[58]
        sectors_per_track = footer[59]
        if heads <= 0 or sectors_per_track <= 0:
            return None
        return (sectors_per_track, heads)

    def _ensure_sudo_ready(self) -> None:
        result = self.runner.run(["true"], sudo=True, check=False)
        if result.returncode == 0:
            return
        detail = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
        raise ValidationError(
            "Sudo authentication is required for disk operations. "
            "Run `sudo -v` in a terminal, then retry. "
            "If this still fails after authentication, run `vhdmaker sudo-check` to detect sudo policy issues.\n"
            f"Details: {detail}"
        )
