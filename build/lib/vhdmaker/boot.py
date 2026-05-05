"""Boot asset resolution and boot preparation helpers."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import struct
import urllib.request
import zipfile
from urllib.error import HTTPError, URLError
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from .commands import CommandRunner
from .errors import ValidationError
from .models import BootMode, CreateRequest, DiskFormat, FreeDOSSource
from .paths import app_cache_dir, app_mount_root

FREEDOS_DEFAULT_IMAGE_URL = (
    "https://raw.githubusercontent.com/codercowboy/freedosbootdisks/master/bootdisks/freedos.boot.disk.1.4MB.img"
)
FREEDOS_FALLBACK_IMAGE_URL = (
    "https://raw.githubusercontent.com/codercowboy/freedosbootdisks/"
    "330e522bf9323ad54a6ff68c9b7cb9ae7a084cb4/bootdisks/freedos.boot.disk.1.4MB.img"
)
FREEDOS_REPOSITORY_14_URL = "https://www.ibiblio.org/pub/micro/pc-stuff/freedos/files/repositories/1.4"

_REQUIRED_FREEDOS_FILES = ("KERNEL.SYS", "COMMAND.COM")
_OPTIONAL_FREEDOS_FILES = ("CONFIG.SYS", "AUTOEXEC.BAT")
_REQUIRED_MSDOS_FILES = ("IO.SYS", "MSDOS.SYS", "COMMAND.COM")
_FREEDOS_USERSPACE_TOOLS = (
    "assign",
    "attrib",
    "choice",
    "comp",
    "debug",
    "devload",
    "display",
    "edit",
    "edlin",
    "fc",
    "fdxms",
    "find",
    "format",
    "label",
    "mem",
    "mode",
    "nansi",
    "share",
    "sort",
    "swsubst",
    "tree",
    "xcopy",
)
_FREEDOS_UNIXLIKE_PACKAGES = ("touch", "gnused", "grep", "head", "less", "tee", "which")
_FREEDOS_UTIL_PACKAGES = ("wcd", "dos32a")
_FREEDOS_NET_PACKAGES = ("curl", "gopherus", "links", "ping", "terminal")
_FREEDOS_SOUND_PACKAGES = ("dosmid", "adplay", "opencp", "sbpmixer", "playcd", "sjgplay")
_FREEDOS_DEVEL_PACKAGES = ("bwbasic",)
_FREEDOS_APP_PACKAGES = ("dn2",)
DEFAULT_MBR_BOOT_CODE_CANDIDATES = (
    Path("/usr/lib/syslinux/bios/mbr.bin"),
    Path("/usr/lib/syslinux/mbr/mbr.bin"),
    Path("/usr/share/syslinux/mbr.bin"),
    Path("/usr/lib/SYSLINUX/mbr.bin"),
)
_SHELL_COMMAND_PATTERN = re.compile(
    r"^(?P<prefix>\s*SHELL\s*=\s*)(?P<command>(?:[A-Za-z]:)?\\?COMMAND\.COM)(?P<suffix>[^\n]*)",
    re.IGNORECASE | re.MULTILINE,
)


def normalize_freedos_config_sys(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        return f"{match.group('prefix')}C:\\COMMAND.COM{match.group('suffix')}"

    return _SHELL_COMMAND_PATTERN.sub(repl, text)


@dataclass(slots=True)
class BootAssets:
    system_files: dict[str, Path]
    boot_sector_template: Path
    fdos_payload_dir: Path | None = None


class BootAssetResolver:
    def __init__(self, runner: CommandRunner, cache_root: Path | None = None) -> None:
        self.runner = runner
        self.cache_root = cache_root or (app_cache_dir() / "boot-assets")
        self.cache_root.mkdir(parents=True, exist_ok=True)

    def resolve(self, request: CreateRequest) -> BootAssets:
        if request.boot_mode is BootMode.NONE:
            raise ValidationError("Boot assets requested when boot mode is disabled.")
        if request.boot_mode is BootMode.FREEDOS:
            return self._resolve_freedos(request)
        return self._resolve_msdos71(request)

    def _resolve_freedos(self, request: CreateRequest) -> BootAssets:
        if request.freedos_source is FreeDOSSource.LOCAL:
            if request.boot_assets_path is None:
                raise ValidationError("FreeDOS local mode requires a boot assets path.")
            target = request.boot_assets_path.expanduser().resolve()
            if target.is_dir():
                return self._resolve_freedos_from_directory(target, request.disk_format)
            if target.is_file():
                return self._resolve_freedos_from_image(target, request.disk_format)
            raise ValidationError(f"Boot assets path does not exist: {target}")

        image_url = request.freedos_download_url or FREEDOS_DEFAULT_IMAGE_URL
        image_path = self._download_freedos_image(image_url)
        return self._resolve_freedos_from_image(image_path, request.disk_format)

    def _resolve_freedos_from_directory(self, directory: Path, disk_format: DiskFormat) -> BootAssets:
        files: dict[str, Path] = {}
        for name in _REQUIRED_FREEDOS_FILES:
            files[name] = self._require_file_case_insensitive(directory, name)
        for name in _OPTIONAL_FREEDOS_FILES:
            optional = self._find_file_case_insensitive(directory, name)
            if optional is not None:
                files[name] = optional

        template = self._resolve_boot_template(directory, disk_format)
        payload_dir = directory / "FDOS"
        return BootAssets(
            system_files=files,
            boot_sector_template=template,
            fdos_payload_dir=payload_dir if payload_dir.is_dir() else None,
        )

    def _resolve_freedos_from_image(self, image_path: Path, disk_format: DiskFormat) -> BootAssets:
        if disk_format is DiskFormat.FAT32:
            raise ValidationError(
                "FreeDOS auto image source only provides FAT16-style boot sector templates. "
                "Use local FreeDOS assets with BOOTSECT_FAT32.BIN for FAT32 boot mode."
            )

        extraction_root = self.cache_root / f"freedos-{self._hash_value(str(image_path.resolve()))}"
        extraction_root.mkdir(parents=True, exist_ok=True)
        files: dict[str, Path] = {}
        for name in _REQUIRED_FREEDOS_FILES:
            files[name] = self._extract_file_from_image(image_path, extraction_root, name, required=True)
        for name in _OPTIONAL_FREEDOS_FILES:
            extracted = self._extract_file_from_image(image_path, extraction_root, name, required=False)
            if extracted is not None:
                files[name] = extracted

        template = extraction_root / "BOOTSECT_FAT16.BIN"
        if not template.exists():
            with image_path.open("rb") as handle:
                boot_sector = handle.read(512)
            if len(boot_sector) < 512:
                raise ValidationError(f"FreeDOS image is too small to contain a boot sector: {image_path}")
            template.write_bytes(boot_sector)

        return BootAssets(system_files=files, boot_sector_template=template, fdos_payload_dir=None)

    def export_latest_freedos_assets(
        self,
        destination: Path,
        image_url: str | None = None,
        *,
        include_full_fdos: bool = False,
    ) -> Path:
        target_dir = destination.expanduser().resolve()
        target_dir.mkdir(parents=True, exist_ok=True)

        url = image_url or FREEDOS_DEFAULT_IMAGE_URL
        image_path = self._download_freedos_image(url)
        assets = self._resolve_freedos_from_image(image_path, DiskFormat.FAT16)

        for file_name, source_path in assets.system_files.items():
            shutil.copy2(source_path, target_dir / file_name)
        self._normalize_freedos_startup_files(target_dir)
        shutil.copy2(assets.boot_sector_template, target_dir / "BOOTSECT_FAT16.BIN")
        self._write_fat32_boot_template(
            target_dir / "BOOTSECT_FAT32.BIN",
            search_roots=(target_dir.parent, Path.cwd()),
        )

        if include_full_fdos:
            self._download_and_extract_freedos_userspace(target_dir / "FDOS")

        notice_path = target_dir / "README.txt"
        if not notice_path.exists():
            notice_path.write_text(
                (
                    "Generated by vhdmaker.\n"
                    "Contains FreeDOS boot files extracted from a GitHub-hosted FreeDOS boot image.\n"
                    "Includes BOOTSECT_FAT16.BIN.\n"
                    "Includes BOOTSECT_FAT32.BIN generated by mkfs.fat.\n"
                    "If FDOS/ exists, its contents are copied to \\FDOS on bootable VHD creation.\n"
                ),
                encoding="utf-8",
            )
        return target_dir

    def _normalize_freedos_startup_files(self, directory: Path) -> None:
        config_path = directory / "CONFIG.SYS"
        if not config_path.exists() or not config_path.is_file():
            return
        try:
            content = config_path.read_text(encoding="latin-1")
        except OSError:
            return

        normalized = normalize_freedos_config_sys(content)
        if normalized != content:
            config_path.write_text(normalized, encoding="latin-1")

    def _resolve_msdos71(self, request: CreateRequest) -> BootAssets:
        if request.disk_format is not DiskFormat.FAT32:
            raise ValidationError("MS-DOS 7.1 boot mode requires FAT32 format.")
        if request.boot_assets_path is None:
            raise ValidationError("MS-DOS 7.1 boot mode requires a local boot assets path.")
        directory = request.boot_assets_path.expanduser().resolve()
        if not directory.is_dir():
            raise ValidationError(f"MS-DOS asset path must be a directory: {directory}")

        files = {name: self._require_file_case_insensitive(directory, name) for name in _REQUIRED_MSDOS_FILES}
        template = self._resolve_boot_template(directory, request.disk_format)
        return BootAssets(system_files=files, boot_sector_template=template, fdos_payload_dir=None)

    def _download_freedos_image(self, url: str) -> Path:
        digest = self._hash_value(url)
        target = self.cache_root / f"freedos-{digest}.img"
        if target.exists() and target.stat().st_size >= 512:
            return target
        request = urllib.request.Request(url, headers={"User-Agent": "vhdmaker/0.1.0"})
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                payload = response.read()
        except (HTTPError, URLError) as primary_exc:
            if url != FREEDOS_DEFAULT_IMAGE_URL:
                raise ValidationError(f"Failed to download FreeDOS image: {url}") from primary_exc
            fallback_request = urllib.request.Request(
                FREEDOS_FALLBACK_IMAGE_URL,
                headers={"User-Agent": "vhdmaker/0.1.0"},
            )
            try:
                with urllib.request.urlopen(fallback_request, timeout=90) as response:
                    payload = response.read()
            except (HTTPError, URLError) as fallback_exc:
                raise ValidationError(
                    "Failed to download FreeDOS image from GitHub default and fallback URLs."
                ) from fallback_exc
        if len(payload) < 512:
            raise ValidationError(f"Downloaded FreeDOS image is invalid: {url}")
        target.write_bytes(payload)
        return target

    def _extract_file_from_image(
        self,
        image_path: Path,
        output_dir: Path,
        dos_name: str,
        *,
        required: bool,
    ) -> Path | None:
        output_path = output_dir / dos_name
        if output_path.exists() and output_path.stat().st_size > 0:
            return output_path
        result = self.runner.run(
            ["mcopy", "-i", str(image_path), f"::{dos_name}", str(output_path)],
            check=False,
        )
        if result.returncode == 0 and output_path.exists():
            return output_path
        if required:
            raise ValidationError(
                f"Missing required FreeDOS file {dos_name} in image {image_path}. "
                f"mcopy stderr: {result.stderr.strip()}"
            )
        return None

    def _download_and_extract_freedos_userspace(self, destination: Path) -> None:
        destination.mkdir(parents=True, exist_ok=True)
        for package_url in self._freedos14_package_urls():
            package_path = self._download_cached_file(package_url, cache_prefix="freedos-pkg")
            self._extract_zip_archive(package_path, destination, skip_prefixes=("SOURCE/",))

    def _freedos14_package_urls(self) -> list[str]:
        urls: list[str] = []
        urls.extend([f"{FREEDOS_REPOSITORY_14_URL}/base/{name}.zip" for name in ("kernel", "freecom")])
        urls.extend([f"{FREEDOS_REPOSITORY_14_URL}/apps/{name}.zip" for name in _FREEDOS_APP_PACKAGES])
        urls.extend([f"{FREEDOS_REPOSITORY_14_URL}/base/{name}.zip" for name in (*_FREEDOS_USERSPACE_TOOLS, "htmlhelp")])
        urls.extend([f"{FREEDOS_REPOSITORY_14_URL}/unix/{name}.zip" for name in _FREEDOS_UNIXLIKE_PACKAGES])
        urls.extend([f"{FREEDOS_REPOSITORY_14_URL}/util/{name}.zip" for name in _FREEDOS_UTIL_PACKAGES])
        urls.extend([f"{FREEDOS_REPOSITORY_14_URL}/net/{name}.zip" for name in _FREEDOS_NET_PACKAGES])
        urls.extend([f"{FREEDOS_REPOSITORY_14_URL}/sound/{name}.zip" for name in _FREEDOS_SOUND_PACKAGES])
        urls.extend([f"{FREEDOS_REPOSITORY_14_URL}/devel/{name}.zip" for name in _FREEDOS_DEVEL_PACKAGES])
        return urls

    def _download_cached_file(self, url: str, *, cache_prefix: str) -> Path:
        digest = self._hash_value(url)
        filename = Path(url).name or "download.bin"
        target = self.cache_root / f"{cache_prefix}-{digest}-{filename}"
        if target.exists() and target.stat().st_size > 0:
            return target

        request = urllib.request.Request(url, headers={"User-Agent": "vhdmaker/0.1.0"})
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                payload = response.read()
        except (HTTPError, URLError) as exc:
            raise ValidationError(f"Failed to download FreeDOS package: {url}") from exc

        if not payload:
            raise ValidationError(f"Downloaded FreeDOS package is empty: {url}")
        target.write_bytes(payload)
        return target

    def _extract_zip_archive(self, archive_path: Path, destination: Path, *, skip_prefixes: tuple[str, ...]) -> None:
        destination_resolved = destination.resolve()
        with zipfile.ZipFile(archive_path) as zf:
            for member in zf.infolist():
                member_name = member.filename.replace("\\", "/")
                if not member_name or member_name.endswith("/"):
                    continue
                if any(member_name.upper().startswith(prefix.upper()) for prefix in skip_prefixes):
                    continue

                output_path = (destination_resolved / member_name).resolve()
                if destination_resolved not in output_path.parents and output_path != destination_resolved:
                    raise ValidationError(f"Unsafe archive path in {archive_path}: {member.filename}")
                output_path.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as source, output_path.open("wb") as target:
                    shutil.copyfileobj(source, target)

    def _write_fat32_boot_template(
        self,
        destination: Path,
        *,
        search_roots: tuple[Path, ...] | None = None,
    ) -> None:
        if destination.exists() and destination.stat().st_size >= 512:
            current = destination.read_bytes()[:512]
            if self._looks_like_freedos_fat32_boot_sector(current):
                return

        local_source = self._find_local_freedos_fat32_boot_sector(search_roots or ())
        if local_source is not None:
            destination.write_bytes(local_source)
            return

        image_path = self.cache_root / "fat32-template.img"
        if not image_path.exists() or image_path.stat().st_size < 512:
            self.runner.run(["mkfs.fat", "-F", "32", "-C", str(image_path), "65536"])

        with image_path.open("rb") as handle:
            boot_sector = handle.read(512)
        if len(boot_sector) < 512:
            raise ValidationError(f"Unable to create FAT32 boot template from {image_path}")
        destination.write_bytes(boot_sector)

    def _find_local_freedos_fat32_boot_sector(self, search_roots: tuple[Path, ...]) -> bytes | None:
        visited: set[Path] = set()
        for root in search_roots:
            resolved = root.expanduser().resolve()
            if resolved in visited or not resolved.exists() or not resolved.is_dir():
                continue
            visited.add(resolved)
            for candidate in sorted(resolved.glob("*.vhd")):
                sector = self._extract_fat32_boot_sector_from_vhd(candidate)
                if sector is not None:
                    return sector
        return None

    def _extract_fat32_boot_sector_from_vhd(self, path: Path) -> bytes | None:
        try:
            with path.open("rb") as handle:
                mbr = handle.read(512)
                if len(mbr) < 512 or mbr[510:512] != b"\x55\xaa":
                    return None
                for index in range(4):
                    entry = mbr[446 + index * 16 : 446 + (index + 1) * 16]
                    partition_type = entry[4]
                    if partition_type not in (0x0B, 0x0C):
                        continue
                    start_lba = struct.unpack("<I", entry[8:12])[0]
                    if start_lba <= 0:
                        continue
                    handle.seek(start_lba * 512)
                    pbs = handle.read(512)
                    if self._looks_like_freedos_fat32_boot_sector(pbs):
                        return pbs
        except OSError:
            return None
        return None

    def _looks_like_freedos_fat32_boot_sector(self, sector: bytes) -> bool:
        if len(sector) < 512 or sector[510:512] != b"\x55\xaa":
            return False
        if b"This is not a bootable disk" in sector:
            return False
        return b"FRDOS5.1" in sector and b"KERNEL  SYS" in sector

    def _resolve_boot_template(self, directory: Path, disk_format: DiskFormat) -> Path:
        candidates = (
            ("BOOTSECT_FAT16.BIN", "BOOTSECT.BIN")
            if disk_format is DiskFormat.FAT16
            else ("BOOTSECT_FAT32.BIN", "BOOTSECT.BIN")
        )
        for candidate in candidates:
            located = self._find_file_case_insensitive(directory, candidate)
            if located is not None:
                self._validate_boot_sector_file(located)
                return located
        joined = ", ".join(candidates)
        raise ValidationError(
            f"Boot mode requires a boot sector template in {directory}. "
            f"Expected one of: {joined}"
        )

    def _validate_boot_sector_file(self, path: Path) -> None:
        data = path.read_bytes()
        if len(data) < 512:
            raise ValidationError(f"Boot sector template must be at least 512 bytes: {path}")

    def _find_file_case_insensitive(self, directory: Path, file_name: str) -> Path | None:
        expected = file_name.upper()
        for entry in directory.iterdir():
            if entry.is_file() and entry.name.upper() == expected:
                return entry
        return None

    def _require_file_case_insensitive(self, directory: Path, file_name: str) -> Path:
        found = self._find_file_case_insensitive(directory, file_name)
        if found is None:
            raise ValidationError(f"Required boot file not found in {directory}: {file_name}")
        return found

    def _hash_value(self, value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


class BootInstaller:
    def __init__(
        self,
        runner: CommandRunner,
        mount_root: Path | None = None,
        mbr_boot_candidates: tuple[Path, ...] | None = None,
    ) -> None:
        self.runner = runner
        self.mount_root = mount_root or (app_mount_root() / "boot-prep")
        self.mount_root.mkdir(parents=True, exist_ok=True)
        self.mbr_boot_candidates = mbr_boot_candidates or DEFAULT_MBR_BOOT_CODE_CANDIDATES

    def make_partition_bootable(
        self,
        *,
        disk_device: str,
        partition_device: str,
        disk_format: DiskFormat,
        assets: BootAssets,
    ) -> None:
        self._write_mbr_boot_code(disk_device=disk_device)
        self._write_boot_sector(
            partition_device=partition_device,
            disk_format=disk_format,
            template=assets.boot_sector_template,
        )
        self._copy_system_files(
            partition_device=partition_device,
            system_files=assets.system_files,
            fdos_payload_dir=assets.fdos_payload_dir,
        )

    def _copy_system_files(
        self,
        *,
        partition_device: str,
        system_files: dict[str, Path],
        fdos_payload_dir: Path | None,
    ) -> None:
        temp_files: list[Path] = []
        system_order = ("IO.SYS", "MSDOS.SYS", "KERNEL.SYS", "COMMAND.COM")
        written: set[str] = set()
        try:
            for name in system_order:
                source = system_files.get(name)
                if source is None:
                    continue
                prepared_source = self._prepare_source_file(
                    destination_name=name,
                    source_path=source,
                    temp_files=temp_files,
                )
                self._mcopy_file(
                    partition_device=partition_device,
                    source_path=prepared_source,
                    destination_name=name,
                )
                self._mark_system_hidden(partition_device=partition_device, destination_name=name)
                written.add(name)

            for destination_name, source_path in system_files.items():
                if destination_name in written:
                    continue
                prepared_source = self._prepare_source_file(
                    destination_name=destination_name,
                    source_path=source_path,
                    temp_files=temp_files,
                )
                self._mcopy_file(
                    partition_device=partition_device,
                    source_path=prepared_source,
                    destination_name=destination_name,
                )

            if fdos_payload_dir is not None and fdos_payload_dir.is_dir():
                self._copy_fdos_payload_via_mount(partition_device=partition_device, fdos_payload_dir=fdos_payload_dir)

            self.runner.run(["sync"], check=False)
        finally:
            for temp in temp_files:
                if temp.exists():
                    temp.unlink()

    def _mcopy_file(self, *, partition_device: str, source_path: Path, destination_name: str) -> None:
        self.runner.run(
            ["mcopy", "-o", "-i", partition_device, str(source_path), f"::{destination_name}"],
            sudo=True,
        )

    def _mark_system_hidden(self, *, partition_device: str, destination_name: str) -> None:
        self.runner.run(
            ["mattrib", "-i", partition_device, "+s", "+h", f"::{destination_name}"],
            sudo=True,
            check=False,
        )

    def _prepare_source_file(
        self,
        *,
        destination_name: str,
        source_path: Path,
        temp_files: list[Path],
    ) -> Path:
        if destination_name.upper() != "CONFIG.SYS":
            return source_path
        try:
            content = source_path.read_text(encoding="latin-1")
        except OSError:
            return source_path
        normalized = normalize_freedos_config_sys(content)
        if normalized == content:
            return source_path

        normalized_path = self.mount_root / f"normalized-config-{uuid4().hex}.sys"
        normalized_path.write_text(normalized, encoding="latin-1")
        temp_files.append(normalized_path)
        return normalized_path

    def _copy_fdos_payload_via_mount(self, *, partition_device: str, fdos_payload_dir: Path) -> None:
        mountpoint = self.mount_root / f"staging-{os.getpid()}-{uuid4().hex[:6]}"
        mountpoint.mkdir(parents=True, exist_ok=True)
        mount_options = f"uid={os.getuid()},gid={os.getgid()},umask=022,shortname=mixed"
        mounted = False
        try:
            self.runner.run(
                [
                    "mount",
                    "-t",
                    "vfat",
                    "-o",
                    mount_options,
                    partition_device,
                    str(mountpoint),
                ],
                sudo=True,
            )
            mounted = True
            target_fdos = mountpoint / "FDOS"
            target_fdos.mkdir(parents=True, exist_ok=True)
            for source in fdos_payload_dir.rglob("*"):
                relative = source.relative_to(fdos_payload_dir)
                destination = target_fdos / relative
                if source.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                else:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)
        finally:
            if mounted:
                self.runner.run(["umount", str(mountpoint)], sudo=True, check=False)
            if mountpoint.exists():
                shutil.rmtree(mountpoint)

    def _write_mbr_boot_code(self, *, disk_device: str) -> None:
        mbr_code_path = self._find_mbr_boot_code()
        self.runner.run(
            ["dd", f"if={mbr_code_path}", f"of={disk_device}", "bs=440", "count=1", "conv=notrunc"],
            sudo=True,
        )

    def _find_mbr_boot_code(self) -> Path:
        for candidate in self.mbr_boot_candidates:
            if candidate.exists() and candidate.is_file():
                return candidate
        candidates_text = ", ".join(str(path) for path in self.mbr_boot_candidates)
        raise ValidationError(
            "Unable to locate syslinux MBR boot code file. Install syslinux package and ensure one of these exists: "
            f"{candidates_text}"
        )

    def _write_boot_sector(self, *, partition_device: str, disk_format: DiskFormat, template: Path) -> None:
        data = template.read_bytes()
        if len(data) < 512:
            raise ValidationError(f"Boot template must be at least 512 bytes: {template}")

        code_offset = disk_format.boot_code_offset
        self.runner.run(
            ["dd", f"if={template}", f"of={partition_device}", "bs=1", "count=3", "conv=notrunc"],
            sudo=True,
        )
        self.runner.run(
            [
                "dd",
                f"if={template}",
                f"of={partition_device}",
                "bs=1",
                f"skip={code_offset}",
                f"seek={code_offset}",
                f"count={510 - code_offset}",
                "conv=notrunc",
            ],
            sudo=True,
        )
        self.runner.run(
            ["dd", f"if={template}", f"of={partition_device}", "bs=1", "skip=510", "seek=510", "count=2", "conv=notrunc"],
            sudo=True,
        )
