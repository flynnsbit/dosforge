"""Boot asset resolution and boot preparation helpers."""

from __future__ import annotations

import base64
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
from .models import BootMode, CreateRequest, DiskFormat, FreeDOSSource, MSDOSInstallProfile
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
_OPTIONAL_FREEDOS_FILES = ("CONFIG.SYS", "AUTOEXEC.BAT", "FDCONFIG.SYS", "FDAUTO.BAT")
_REQUIRED_MSDOS_FILES = ("IO.SYS", "MSDOS.SYS", "COMMAND.COM")
_REQUIRED_MSDOS_SUPPORT_FILES = ("HIMEM.SYS", "IFSHLP.SYS")
_OPTIONAL_MSDOS_STARTUP_FILES = ("CONFIG.SYS", "AUTOEXEC.BAT")
_MSDOS71_INSTALL_PAK = "DOS71_1S.PAK"
_MSDOS71_OPTIONAL_INSTALL_PAK = "DOS71_2S.PAK"
_MSDOS71_PAK_PASSWORD = b":MSDOS"
_MSDOS71_BOOTSECTOR_SOURCES = ("SYS.COM", "FORMAT.COM")
_MSDOS71_IMAGE_SUFFIXES = (".img", ".ima")
_MSDOS71_ROOT_FILES_EXCLUDED_FROM_DOS_DIR = {
    "IO.SYS",
    "MSDOS.SYS",
    "COMMAND.COM",
    "HIMEM.SYS",
    "IFSHLP.SYS",
    "CONFIG.SYS",
    "AUTOEXEC.BAT",
}
_MSDOS71_DEFAULT_AUTOEXEC_BAT = (
    "@ECHO OFF\r\n"
    "PATH=C:\\DOS;..;.\r\n"
    "PROMPT $P$G\r\n"
    "SET DIRCMD=/4\r\n"
    "SET TEMP=C:\\DOS\\TEMP\r\n"
    "IF NOT EXIST C:\\DOS\\TEMP MD C:\\DOS\\TEMP\r\n"
    "BREAK ON\r\n"
    "ECHO.\r\n"
    "ECHO MS-DOS 7.10 ready.\r\n"
    "ECHO.\r\n"
)
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
_FREEDOS_CORE_PACKAGES = ("kernel", "freecom")
_BUILTIN_FAT16_MBR_BOOT_CODE_B64 = (
    "+jHAjtC84Hv7/I7YjsC+AHy/AAa5AAHzpeoeBgAAhNJ1ArKAiBYABr++B/YFgHUOg8cQgf/+B3LyvtQG62BX6B4AcwW+yQbrVYE+/n1VqnQFvugG60heihYABuoAfAAAHrhAAI7Yu6pVtEH5zRMfch2B+1WqdRfQ6XMTi0UIo7AHi0UKo7IHtEK+qAfrDLgBArsAfItNAop1AfnNE8PoGQC+AgfoEwAw5M0aidPNGinag/o2cvfNGOv+rITAdAm7BwC0Ds0Q6/LDUmVhZCBlcnJvcgBObyBhY3RpdmUgcGFydGl0aW9uAFZCUiBoYXMgaWxsZWdhbCBzaWduYXR1cmUALiBUcnlpbmcgbmV4dCBib290IGRldmljZS4uLg0KAJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkBAAAQAAfAAAAAAAAAAAAAA="
)
_BUILTIN_FAT16_BOOT_SECTOR_B64 = (
    "6zyQRlJET1M1LjEAAgQEAAIAAgAA+MgAEQAMAAAIAAAAHAMAgAApJXrCXE5PIE5BTUUgICAgRkFUMTYgICD6/DHAjti9AHy44B+OwInuie+5AAHzpepefOAfAABgAI7YjtCNZqD7iFYkx0bAEADHRsIBAIxexsdGxKBji3Yci34eA3YOg9cAiXbSiX7UikYQmPdmFgHGEdeJdtaJftiLXguxBdPri0YRMdL381ABxoPXAIl22ol+3ItG1otW2F/EXlrolQDEflq5CwC+8X1X86ZfJotFGnQLg8cgJoA9AHXncmVQxF5ai34Wi0bSi1bU6GcAWB4Hjl5cvwAgq4nGi1ZcAfZzA4DGEI7arYP4+HLrMcCrDh/EXlq+ACCtCcB1BYjT/25aSEiLfg2B5/8A9+cDRtoTVtzoIADr4LQOzRBerFY8AHX1w+j1/0Vycm9yIQAw5M0TzRbNGVaJRsiJVsqMhp7niZ6c5+jU/y4AtEG7qlWKViSE0nQZzRNyFdHpgdtUqnUNjXbAiV7MiV7OtELrJotOyItWyopGGPZmGpH38ZL2dhiJ0YjGhunQydDJCOFBxF7EuAECilYkzRNyiItGC1e+oGPEvpznicHzpF+xBNPoAYae54NGyAGDVsoAT3WLxJ6c517DAAAAAAAAAABLRVJORUwgIFNZUwAAVao="
)
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
_SHELL_P_SWITCH_PATTERN = re.compile(r"(?<!\S)/P(?:=[^\s]+)?(?!\S)", re.IGNORECASE)
_SHELL_D_SWITCH_PATTERN = re.compile(r"(?<!\S)/D(?!\S)", re.IGNORECASE)
_SHELL_K_SWITCH_PATTERN = re.compile(r"(?<!\S)/K(?:=[^\s]+)?(?:\s+[^\s]+)?", re.IGNORECASE)
_AUTOEXEC_A_DRIVE_PATTERN = re.compile(r"(?<![A-Za-z0-9_])A:\\", re.IGNORECASE)
_AUTOEXEC_PROMPT_PATTERN = re.compile(r"^\s*@?\s*PROMPT\s+.*$", re.IGNORECASE | re.MULTILINE)
_AUTOEXEC_PATH_PATTERN = re.compile(r"^\s*@?\s*SET\s+PATH\s*=.*$", re.IGNORECASE | re.MULTILINE)
_MSDOS_DEVICE_PATTERN = re.compile(r"^(?P<prefix>\s*DEVICE(?:HIGH)?=)(?P<driver>[^\s]+)(?P<suffix>.*)$", re.IGNORECASE)
_MSDOS_PATH_PATTERN = re.compile(r"^\s*(?:SET\s+)?PATH(?:\s*=|\s+).*$", re.IGNORECASE)
_MSDOS_DOSLFN_TABLE_PATTERN = re.compile(
    r"(?P<prefix>\bDOSLFN(?:\.COM)?\s+/Z:)(?P<table>[^\s]+)",
    re.IGNORECASE,
)
_MSDOS_INSTALL_DIR_DRIVERS = frozenset(
    {
        "DBLBUFF.SYS",
        "DISPLAY.SYS",
        "EMM386.EXE",
        "HIMEM.SYS",
        "IFSHLP.SYS",
        "RAMDRIVE.SYS",
        "SETVER.EXE",
    }
)


def normalize_msdos_config_sys(text: str, *, install_dir: str = r"C:\DOS") -> str:
    normalized = _as_dos_text(text).replace("\r\n", "\n")
    output: list[str] = []
    for raw_line in normalized.split("\n"):
        line = raw_line.rstrip("\r")
        stripped = line.strip()
        upper = stripped.upper()
        if upper.startswith("REM ") or upper == "REM" or stripped.startswith("::"):
            output.append(line)
            continue
        if _MSDOS_PATH_PATTERN.match(stripped):
            continue
        match = _MSDOS_DEVICE_PATTERN.match(line)
        if match is not None:
            driver = _normalize_msdos_driver_path(match.group("driver"), install_dir)
            line = f"{match.group('prefix')}{driver}{match.group('suffix')}"
        output.append(line)
    output.append(f"SET PATH={install_dir};..;.")
    return _as_dos_text("\r\n".join(output).rstrip("\r\n") + "\r\n")


def normalize_msdos_autoexec_bat(text: str, *, install_dir: str = r"C:\DOS") -> str:
    normalized = _as_dos_text(text).replace("\r\n", "\n")
    output: list[str] = []
    for raw_line in normalized.split("\n"):
        line = raw_line.rstrip("\r")
        if _MSDOS_PATH_PATTERN.match(line.strip()):
            continue
        line = _MSDOS_DOSLFN_TABLE_PATTERN.sub(
            lambda match: f"{match.group('prefix')}{install_dir}\\{_dos_basename(match.group('table'))}",
            line,
        )
        output.append(line)

    path_line = f"PATH={install_dir};..;."
    insert_index = 1 if output and output[0].strip().upper() == "@ECHO OFF" else 0
    output.insert(insert_index, path_line)
    return _as_dos_text("\r\n".join(output).rstrip("\r\n") + "\r\n")


def _normalize_msdos_driver_path(driver: str, install_dir: str) -> str:
    if ":" in driver or "\\" in driver or "/" in driver:
        return driver
    if driver.upper() not in _MSDOS_INSTALL_DIR_DRIVERS:
        return driver
    return f"{install_dir}\\{driver}"


def _dos_basename(path: str) -> str:
    candidate = path.replace("\\", "/").split("/")[-1]
    return candidate or "CP437UNI.TBL"


def normalize_freedos_config_sys(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        suffix = _normalize_freedos_shell_suffix(match.group("suffix"))
        return f"{match.group('prefix')}C:\\COMMAND.COM{suffix}"

    return _SHELL_COMMAND_PATTERN.sub(repl, text)


def normalize_freedos_autoexec_bat(text: str) -> str:
    normalized = _AUTOEXEC_A_DRIVE_PATTERN.sub(lambda _: "C:\\", text)
    line_ending = "\r\n"
    content = normalized.rstrip("\r\n")
    additions: list[str] = []

    if _is_minimal_freedos_autoexec(content):
        if _AUTOEXEC_PATH_PATTERN.search(content) is None:
            additions.extend(
                [
                    "SET DOSDIR=C:\\FDOS",
                    "IF EXIST C:\\FDOS\\BIN\\*.* SET PATH=C:\\FDOS\\BIN;C:\\",
                    "IF NOT EXIST C:\\FDOS\\BIN\\*.* SET PATH=C:\\",
                ]
            )
        if _AUTOEXEC_PROMPT_PATTERN.search(content) is None:
            additions.append("PROMPT $P$G")

    if not additions:
        return _as_dos_text(normalized)

    merged = content
    if merged:
        merged = f"{merged}{line_ending}"
    merged = f"{merged}{line_ending.join(additions)}"
    if normalized.endswith(("\r\n", "\n")):
        merged = f"{merged}{line_ending}"
    return _as_dos_text(merged)


def _is_minimal_freedos_autoexec(text: str) -> bool:
    saw_command = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        upper = line.upper()
        if upper.startswith("REM ") or upper == "REM" or line.startswith("::"):
            continue
        normalized = upper.lstrip("@").strip()
        if normalized in ("ECHO OFF", "CLS"):
            saw_command = True
            continue
        return False
    return saw_command


def _normalize_freedos_shell_suffix(raw_suffix: str) -> str:
    suffix = raw_suffix.rstrip()
    # /D skips AUTOEXEC processing in FreeCOM; remove forced startup switches.
    suffix = _SHELL_D_SWITCH_PATTERN.sub(" ", suffix)
    suffix = _SHELL_K_SWITCH_PATTERN.sub(" ", suffix)
    suffix = re.sub(r"[ \t]{2,}", " ", suffix).rstrip()
    if _SHELL_P_SWITCH_PATTERN.search(suffix) is None:
        suffix = f"{suffix} /P".rstrip()
    if suffix and not suffix.startswith(" "):
        suffix = f" {suffix}"
    return f"{suffix}{raw_suffix[len(raw_suffix.rstrip()):]}"


def _read_dos_text(path: Path) -> str:
    with path.open("r", encoding="latin-1", newline="") as handle:
        return handle.read()


def _write_dos_text(path: Path, content: str) -> None:
    with path.open("w", encoding="latin-1", newline="") as handle:
        handle.write(content)


def _as_dos_text(content: str) -> str:
    return content.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r\n")


@dataclass(slots=True)
class BootAssets:
    system_files: dict[str, Path]
    boot_sector_template: Path
    fdos_payload_dir: Path | None = None
    payload_target_dir: str = "FDOS"
    mbr_boot_code_template: Path | None = None


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
                assets = self._resolve_freedos_from_directory(target, request.disk_format)
            elif target.is_file():
                assets = self._resolve_freedos_from_image(target, request.disk_format)
            else:
                raise ValidationError(f"Boot assets path does not exist: {target}")
        else:
            image_url = request.freedos_download_url or FREEDOS_DEFAULT_IMAGE_URL
            image_path = self._download_freedos_image(image_url)
            assets = self._resolve_freedos_from_image(image_path, request.disk_format)

        if request.disk_format is DiskFormat.FAT16:
            search_roots: tuple[Path, ...] = (
                request.path.expanduser().resolve().parent,
                Path.cwd(),
            )
            if request.boot_assets_path is not None:
                search_roots = (*search_roots, request.boot_assets_path.expanduser().resolve().parent)
            self._apply_fat16_reference_boot_records(
                assets,
                search_roots=search_roots,
                exclude_paths=(request.path.expanduser().resolve(),),
            )
        return assets

    def _resolve_freedos_from_directory(self, directory: Path, disk_format: DiskFormat) -> BootAssets:
        files: dict[str, Path] = {}
        for name in _REQUIRED_FREEDOS_FILES:
            files[name] = self._require_file_case_insensitive(directory, name)
        for name in _OPTIONAL_FREEDOS_FILES:
            optional = self._find_file_case_insensitive(directory, name)
            if optional is not None:
                files[name] = optional
        self._populate_freedos_startup_aliases(files)

        template = self._resolve_boot_template(directory, disk_format)
        payload_dir = directory / "FDOS"
        self._prefer_freedos_core_system_files(files, payload_dir)
        mbr_template = self._resolve_mbr_boot_template(directory) if disk_format is DiskFormat.FAT16 else None
        return BootAssets(
            system_files=files,
            boot_sector_template=template,
            fdos_payload_dir=payload_dir if payload_dir.is_dir() else None,
            mbr_boot_code_template=mbr_template,
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
        self._populate_freedos_startup_aliases(files)
        payload_dir = extraction_root / "FDOS"
        self._ensure_freedos_core_payload(payload_dir)
        self._prefer_freedos_core_system_files(files, payload_dir)

        template = extraction_root / "BOOTSECT_FAT16.BIN"
        if not template.exists():
            with image_path.open("rb") as handle:
                boot_sector = handle.read(512)
            if len(boot_sector) < 512:
                raise ValidationError(f"FreeDOS image is too small to contain a boot sector: {image_path}")
            template.write_bytes(boot_sector)

        return BootAssets(
            system_files=files,
            boot_sector_template=template,
            fdos_payload_dir=payload_dir,
            mbr_boot_code_template=None,
        )

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
        self._apply_fat16_reference_boot_records(
            assets,
            search_roots=(target_dir.parent, Path.cwd()),
        )

        for file_name, source_path in assets.system_files.items():
            shutil.copy2(source_path, target_dir / file_name)
        self._normalize_freedos_startup_files(target_dir)
        shutil.copy2(assets.boot_sector_template, target_dir / "BOOTSECT_FAT16.BIN")
        if assets.mbr_boot_code_template is not None:
            shutil.copy2(assets.mbr_boot_code_template, target_dir / "MBR_FAT16.BIN")
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
                    "May include MBR_FAT16.BIN when a local FreeDOS FAT16 VHD reference is found.\n"
                    "If FDOS/ exists, its contents are copied to \\FDOS on bootable VHD creation.\n"
                ),
                encoding="utf-8",
            )
        return target_dir

    def _normalize_freedos_startup_files(self, directory: Path) -> None:
        startup_normalizers = (
            ("CONFIG.SYS", normalize_freedos_config_sys),
            ("FDCONFIG.SYS", normalize_freedos_config_sys),
            ("AUTOEXEC.BAT", normalize_freedos_autoexec_bat),
            ("FDAUTO.BAT", normalize_freedos_autoexec_bat),
        )
        for filename, normalizer in startup_normalizers:
            startup_path = directory / filename
            if not startup_path.exists() or not startup_path.is_file():
                continue
            try:
                content = _read_dos_text(startup_path)
            except OSError:
                continue

            normalized = _as_dos_text(normalizer(content))
            if normalized != content:
                _write_dos_text(startup_path, normalized)

        self._ensure_startup_alias_file(
            source=directory / "CONFIG.SYS",
            alias=directory / "FDCONFIG.SYS",
        )
        self._ensure_startup_alias_file(
            source=directory / "AUTOEXEC.BAT",
            alias=directory / "FDAUTO.BAT",
        )

    def _apply_fat16_reference_boot_records(
        self,
        assets: BootAssets,
        *,
        search_roots: tuple[Path, ...],
        exclude_paths: tuple[Path, ...] = (),
    ) -> None:
        try:
            current_boot_sector = assets.boot_sector_template.read_bytes()[:512]
        except OSError:
            current_boot_sector = b""

        needs_boot_override = not self._looks_like_freedos_fat16_boot_sector(current_boot_sector)
        needs_mbr_override = assets.mbr_boot_code_template is None
        if not needs_boot_override and not needs_mbr_override:
            return

        boot_template_path: Path | None = None
        mbr_template_path: Path | None = None
        reference = self._find_local_freedos_fat16_boot_records(
            search_roots=search_roots,
            exclude_paths=exclude_paths,
        )
        if reference is not None:
            source_path, mbr_code, boot_sector = reference
            digest = self._hash_value(str(source_path.resolve()))
            boot_template_path = self.cache_root / f"fat16-ref-{digest}-bootsect.bin"
            mbr_template_path = self.cache_root / f"fat16-ref-{digest}-mbr.bin"
            boot_template_path.write_bytes(boot_sector)
            mbr_template_path.write_bytes(mbr_code)
            self._save_cached_fat16_boot_records(mbr_code=mbr_code, boot_sector=boot_sector)
        else:
            cached = self._load_cached_fat16_boot_record_paths()
            if cached is None:
                self._seed_builtin_fat16_boot_records()
                cached = self._load_cached_fat16_boot_record_paths()
            if cached is not None:
                boot_template_path, mbr_template_path = cached

        if needs_boot_override and boot_template_path is not None:
            assets.boot_sector_template = boot_template_path
        if needs_mbr_override and mbr_template_path is not None:
            assets.mbr_boot_code_template = mbr_template_path

    def _find_local_freedos_fat16_boot_records(
        self,
        *,
        search_roots: tuple[Path, ...],
        exclude_paths: tuple[Path, ...],
    ) -> tuple[Path, bytes, bytes] | None:
        visited: set[Path] = set()
        excluded: set[Path] = set()
        for path in exclude_paths:
            try:
                excluded.add(path.expanduser().resolve())
            except OSError:
                continue

        for root in search_roots:
            resolved = root.expanduser().resolve()
            if resolved in visited or not resolved.exists() or not resolved.is_dir():
                continue
            visited.add(resolved)
            for candidate in sorted(resolved.glob("*.vhd")):
                try:
                    candidate_resolved = candidate.resolve()
                except OSError:
                    continue
                if candidate_resolved in excluded:
                    continue
                extracted = self._extract_fat16_boot_records_from_vhd(candidate)
                if extracted is not None:
                    mbr_code, boot_sector = extracted
                    return (candidate, mbr_code, boot_sector)
        return None

    def _extract_fat16_boot_records_from_vhd(self, path: Path) -> tuple[bytes, bytes] | None:
        try:
            with path.open("rb") as handle:
                mbr = handle.read(512)
                if len(mbr) < 512 or mbr[510:512] != b"\x55\xaa":
                    return None
                mbr_boot_code = mbr[:440]
                if len(mbr_boot_code) < 440 or not any(mbr_boot_code):
                    return None
                for index in range(4):
                    entry = mbr[446 + index * 16 : 446 + (index + 1) * 16]
                    partition_type = entry[4]
                    if partition_type not in (0x04, 0x06, 0x0E):
                        continue
                    start_lba = struct.unpack("<I", entry[8:12])[0]
                    if start_lba <= 0:
                        continue
                    handle.seek(start_lba * 512)
                    pbs = handle.read(512)
                    if self._looks_like_freedos_fat16_boot_sector(pbs):
                        return (mbr_boot_code, pbs)
        except OSError:
            return None
        return None

    def _looks_like_freedos_fat16_boot_sector(self, sector: bytes) -> bool:
        if len(sector) < 512 or sector[510:512] != b"\x55\xaa":
            return False
        if b"This is not a bootable disk" in sector:
            return False
        return b"FRDOS5.1" in sector and b"KERNEL  SYS" in sector

    def _cached_fat16_boot_sector_path(self) -> Path:
        return self.cache_root / "fat16-native-bootsect.bin"

    def _cached_fat16_mbr_boot_code_path(self) -> Path:
        return self.cache_root / "fat16-native-mbr.bin"

    def _seed_builtin_fat16_boot_records(self) -> None:
        mbr_code = base64.b64decode(_BUILTIN_FAT16_MBR_BOOT_CODE_B64)
        boot_sector = base64.b64decode(_BUILTIN_FAT16_BOOT_SECTOR_B64)
        self._save_cached_fat16_boot_records(mbr_code=mbr_code, boot_sector=boot_sector)

    def _save_cached_fat16_boot_records(self, *, mbr_code: bytes, boot_sector: bytes) -> None:
        if len(mbr_code) < 440 or len(boot_sector) < 512:
            return
        if not self._looks_like_freedos_fat16_boot_sector(boot_sector[:512]):
            return
        self._cached_fat16_mbr_boot_code_path().write_bytes(mbr_code[:440])
        self._cached_fat16_boot_sector_path().write_bytes(boot_sector[:512])

    def _load_cached_fat16_boot_record_paths(self) -> tuple[Path, Path] | None:
        boot_path = self._cached_fat16_boot_sector_path()
        mbr_path = self._cached_fat16_mbr_boot_code_path()
        if not boot_path.exists() or not mbr_path.exists():
            return None
        if not boot_path.is_file() or not mbr_path.is_file():
            return None
        if mbr_path.stat().st_size < 440 or boot_path.stat().st_size < 512:
            return None
        try:
            boot_sector = boot_path.read_bytes()[:512]
            mbr_code = mbr_path.read_bytes()[:440]
        except OSError:
            return None
        if not self._looks_like_freedos_fat16_boot_sector(boot_sector):
            return None
        if not any(mbr_code):
            return None
        return (boot_path, mbr_path)

    def _resolve_msdos71(self, request: CreateRequest) -> BootAssets:
        if request.boot_assets_path is None:
            raise ValidationError("MS-DOS 7.1 boot mode requires a local boot assets path.")
        directory = request.boot_assets_path.expanduser().resolve()
        if not directory.is_dir():
            raise ValidationError(f"MS-DOS asset path must be a directory: {directory}")

        direct_assets = self._try_resolve_msdos71_from_directory(
            directory,
            request.disk_format,
            install_profile=request.msdos_install_profile,
        )
        if direct_assets is not None:
            return direct_assets
        return self._resolve_msdos71_from_install_images(
            directory,
            disk_format=request.disk_format,
            install_profile=request.msdos_install_profile,
        )

    def _try_resolve_msdos71_from_directory(
        self,
        directory: Path,
        disk_format: DiskFormat,
        *,
        install_profile: MSDOSInstallProfile,
    ) -> BootAssets | None:
        files: dict[str, Path] = {}
        for name in (*_REQUIRED_MSDOS_FILES, *_REQUIRED_MSDOS_SUPPORT_FILES):
            located = self._find_file_case_insensitive(directory, name)
            if located is None:
                return None
            files[name] = located
        for name in _OPTIONAL_MSDOS_STARTUP_FILES:
            located = self._find_file_case_insensitive(directory, name)
            if located is not None:
                files[name] = located

        self._ensure_msdos_startup_files(
            files,
            defaults_root=self.cache_root / "msdos71-default-startup",
        )
        self._normalize_msdos_startup_files(
            files,
            defaults_root=self.cache_root / "msdos71-default-startup",
        )

        try:
            template = self._resolve_boot_template(directory, disk_format)
        except ValidationError:
            return None
        payload_dir: Path | None = None
        payload_target_dir = "FDOS"
        if install_profile is MSDOSInstallProfile.FULL:
            payload_dir = self._find_directory_case_insensitive(directory, "DOS")
            if payload_dir is None:
                return None
            payload_target_dir = "DOS"
        return BootAssets(
            system_files=files,
            boot_sector_template=template,
            fdos_payload_dir=payload_dir,
            payload_target_dir=payload_target_dir,
        )

    def _resolve_msdos71_from_install_images(
        self,
        directory: Path,
        *,
        disk_format: DiskFormat,
        install_profile: MSDOSInstallProfile,
    ) -> BootAssets:
        install_images = self._collect_msdos71_install_images(directory)
        if not install_images:
            raise ValidationError(
                "MS-DOS 7.1 assets were not found. Provide either direct files "
                "(IO.SYS, MSDOS.SYS, COMMAND.COM, HIMEM.SYS, IFSHLP.SYS, "
                "BOOTSECT_FAT16.BIN/BOOTSECT_FAT32.BIN) "
                "or DOS71 install disk images (*.img)."
            )

        cache_key = self._msdos71_cache_key(directory, install_images)
        extraction_root = self.cache_root / f"msdos71-{self._hash_value(cache_key)}"
        extraction_root.mkdir(parents=True, exist_ok=True)

        pak_path = extraction_root / _MSDOS71_INSTALL_PAK
        if not pak_path.exists() or pak_path.stat().st_size == 0:
            if not self._copy_msdos71_pak_from_images(install_images, _MSDOS71_INSTALL_PAK, pak_path):
                raise ValidationError(
                    "Unable to locate DOS71_1S.PAK inside the provided DOS71 disk images. "
                    "Ensure the folder contains the original MS-DOS 7.1 install disks."
                )

        self._extract_msdos71_pak_files(pak_path, extraction_root)
        files = {
            name: self._require_file_case_insensitive(extraction_root, name)
            for name in (*_REQUIRED_MSDOS_FILES, *_REQUIRED_MSDOS_SUPPORT_FILES)
        }
        for name in _OPTIONAL_MSDOS_STARTUP_FILES:
            optional = self._find_file_case_insensitive(extraction_root, name)
            if optional is not None:
                files[name] = optional

        self._ensure_msdos_startup_files(
            files,
            defaults_root=extraction_root,
        )
        self._normalize_msdos_startup_files(
            files,
            defaults_root=extraction_root,
        )

        template: Path | None = None
        template_candidates = (
            ("BOOTSECT_FAT16.BIN", "BOOTSECT.BIN")
            if disk_format is DiskFormat.FAT16
            else ("BOOTSECT_FAT32.BIN", "BOOTSECT.BIN")
        )
        for candidate in template_candidates:
            located = self._find_file_case_insensitive(directory, candidate)
            if located is None:
                continue
            self._validate_boot_sector_file(located)
            template = located
            break

        if template is None:
            template_name = "BOOTSECT_FAT16.BIN" if disk_format is DiskFormat.FAT16 else "BOOTSECT_FAT32.BIN"
            template = extraction_root / template_name
            self._write_msdos71_boot_template(
                template,
                disk_format=disk_format,
                source_candidates=tuple(extraction_root / name for name in _MSDOS71_BOOTSECTOR_SOURCES),
            )

        payload_dir: Path | None = None
        payload_target_dir = "FDOS"
        if install_profile is MSDOSInstallProfile.FULL:
            payload_dir = extraction_root / "DOS"
            self._extract_msdos71_full_payload(
                install_images=install_images,
                extraction_root=extraction_root,
                destination=payload_dir,
            )
            payload_target_dir = "DOS"

        return BootAssets(
            system_files=files,
            boot_sector_template=template,
            fdos_payload_dir=payload_dir,
            payload_target_dir=payload_target_dir,
        )

    def _collect_msdos71_install_images(self, directory: Path) -> list[Path]:
        images = [
            entry
            for entry in directory.iterdir()
            if entry.is_file() and entry.suffix.lower() in _MSDOS71_IMAGE_SUFFIXES
        ]
        return sorted(images)

    def _msdos71_cache_key(self, directory: Path, image_paths: list[Path]) -> str:
        parts = [str(directory.resolve())]
        for image_path in image_paths:
            try:
                stat = image_path.stat()
            except OSError:
                continue
            parts.append(f"{image_path.name}:{stat.st_size}:{stat.st_mtime_ns}")
        return "|".join(parts)

    def _copy_msdos71_pak_from_images(self, image_paths: list[Path], pak_name: str, destination: Path) -> bool:
        for image_path in image_paths:
            if self._copy_file_from_image_case_insensitive(image_path, pak_name, destination):
                return True
        return False

    def _copy_file_from_image_case_insensitive(self, image_path: Path, dos_name: str, destination: Path) -> bool:
        if destination.exists() and destination.stat().st_size > 0:
            return True
        destination.parent.mkdir(parents=True, exist_ok=True)
        for candidate in (dos_name, dos_name.upper(), dos_name.lower()):
            if destination.exists():
                destination.unlink()
            result = self.runner.run(
                ["mcopy", "-i", str(image_path), f"::{candidate}", str(destination)],
                check=False,
            )
            if result.returncode == 0 and destination.exists() and destination.stat().st_size > 0:
                return True
        return False

    def _extract_msdos71_pak_files(self, pak_path: Path, destination: Path) -> None:
        destination.mkdir(parents=True, exist_ok=True)
        required = (*_REQUIRED_MSDOS_FILES, *_REQUIRED_MSDOS_SUPPORT_FILES, *_MSDOS71_BOOTSECTOR_SOURCES)
        optional = _OPTIONAL_MSDOS_STARTUP_FILES
        try:
            with zipfile.ZipFile(pak_path) as archive:
                members: dict[str, str] = {}
                for info in archive.infolist():
                    normalized = info.filename.replace("\\", "/")
                    member_name = Path(normalized).name
                    if not member_name:
                        continue
                    members.setdefault(member_name.upper(), info.filename)

                for member_name in (*required, *optional):
                    output_path = destination / member_name
                    if output_path.exists() and output_path.stat().st_size > 0:
                        continue
                    archive_member = members.get(member_name.upper())
                    if archive_member is None:
                        if member_name in required:
                            raise ValidationError(
                                f"MS-DOS install archive is missing required file {member_name}: {pak_path}"
                            )
                        continue
                    self._extract_zip_member(
                        archive,
                        archive_member,
                        output_path,
                        password=_MSDOS71_PAK_PASSWORD,
                    )
        except (OSError, zipfile.BadZipFile) as exc:
            raise ValidationError(f"Unable to read MS-DOS install archive: {pak_path}") from exc

    def _ensure_msdos_startup_files(self, files: dict[str, Path], *, defaults_root: Path) -> None:
        defaults_root.mkdir(parents=True, exist_ok=True)
        for name in _OPTIONAL_MSDOS_STARTUP_FILES:
            if name in files and files[name].exists():
                continue
            default_path = defaults_root / name
            if not default_path.exists() or default_path.stat().st_size == 0:
                if name == "CONFIG.SYS":
                    content = self._default_msdos_config_sys(has_himem="HIMEM.SYS" in files)
                else:
                    content = _MSDOS71_DEFAULT_AUTOEXEC_BAT
                _write_dos_text(default_path, _as_dos_text(content))
            files[name] = default_path

    def _normalize_msdos_startup_files(self, files: dict[str, Path], *, defaults_root: Path) -> None:
        defaults_root.mkdir(parents=True, exist_ok=True)
        startup_normalizers = {
            "CONFIG.SYS": normalize_msdos_config_sys,
            "AUTOEXEC.BAT": normalize_msdos_autoexec_bat,
        }
        for name, normalizer in startup_normalizers.items():
            source = files.get(name)
            if source is None or not source.exists() or not source.is_file():
                continue
            try:
                content = _read_dos_text(source)
            except OSError:
                continue

            normalized = _as_dos_text(normalizer(content))
            target = defaults_root / name
            if target != source or normalized != content:
                _write_dos_text(target, normalized)
            files[name] = target

    def _default_msdos_config_sys(self, *, has_himem: bool) -> str:
        lines = []
        if has_himem:
            lines.append("DEVICE=HIMEM.SYS")
        lines.extend(
            [
                "DOS=HIGH,UMB,AUTO",
                "FCBS=4,0",
                "FILES=30",
                "BUFFERS=20,0",
                "LASTDRIVE=26",
                "SHELL=COMMAND.COM /P /E:640",
            ]
        )
        return "\r\n".join(lines) + "\r\n"

    def _extract_msdos71_full_payload(
        self,
        *,
        install_images: list[Path],
        extraction_root: Path,
        destination: Path,
    ) -> None:
        destination.mkdir(parents=True, exist_ok=True)
        for pak_name in (_MSDOS71_INSTALL_PAK, _MSDOS71_OPTIONAL_INSTALL_PAK):
            pak_path = extraction_root / pak_name
            if not pak_path.exists() or pak_path.stat().st_size == 0:
                copied = self._copy_msdos71_pak_from_images(install_images, pak_name, pak_path)
                if not copied:
                    if pak_name == _MSDOS71_INSTALL_PAK:
                        raise ValidationError(
                            "Unable to locate DOS71_1S.PAK inside the provided DOS71 disk images. "
                            "Ensure the folder contains the original MS-DOS 7.1 install disks."
                        )
                    continue
            self._extract_msdos71_archive_all(pak_path, destination)

    def _extract_msdos71_archive_all(self, pak_path: Path, destination: Path) -> None:
        destination_resolved = destination.resolve()
        try:
            with zipfile.ZipFile(pak_path) as archive:
                for info in archive.infolist():
                    member_name = info.filename.replace("\\", "/")
                    if not member_name or member_name.endswith("/"):
                        continue
                    root_name = Path(member_name).name.upper()
                    if (
                        "/" not in member_name
                        and root_name in _MSDOS71_ROOT_FILES_EXCLUDED_FROM_DOS_DIR
                    ):
                        continue
                    output_path = (destination_resolved / member_name).resolve()
                    if destination_resolved not in output_path.parents and output_path != destination_resolved:
                        raise ValidationError(f"Unsafe archive path in {pak_path}: {info.filename}")
                    self._extract_zip_member(
                        archive,
                        info.filename,
                        output_path,
                        password=_MSDOS71_PAK_PASSWORD,
                    )
        except (OSError, zipfile.BadZipFile) as exc:
            raise ValidationError(f"Unable to read MS-DOS install archive: {pak_path}") from exc

    def _extract_zip_member(
        self,
        archive: zipfile.ZipFile,
        member_name: str,
        destination: Path,
        *,
        password: bytes | None = None,
    ) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        archive_name = archive.filename or "<archive>"
        try:
            with archive.open(member_name, pwd=password) as source, destination.open("wb") as target:
                shutil.copyfileobj(source, target)
        except RuntimeError as exc:
            raise ValidationError(
                f"Unable to decrypt {member_name} in {archive_name}. "
                "Expected PKZIP password ':MSDOS'."
            ) from exc
        except (KeyError, OSError, NotImplementedError) as exc:
            raise ValidationError(f"Unable to extract {member_name} from {archive_name}.") from exc

    def _write_msdos71_boot_template(
        self,
        destination: Path,
        *,
        disk_format: DiskFormat,
        source_candidates: tuple[Path, ...],
    ) -> None:
        if destination.exists() and destination.stat().st_size >= 512:
            current = destination.read_bytes()[:512]
            if self._looks_like_msdos_boot_sector(current, disk_format):
                return

        for source_path in source_candidates:
            if not source_path.exists() or not source_path.is_file():
                continue
            sector = self._extract_msdos71_boot_sector_from_binary(source_path, disk_format)
            if sector is not None:
                destination.write_bytes(sector)
                return

        format_label = "FAT16" if disk_format is DiskFormat.FAT16 else "FAT32"
        raise ValidationError(
            f"Unable to derive BOOTSECT_{format_label}.BIN from DOS71 install media. "
            f"Provide BOOTSECT_{format_label}.BIN manually in the asset directory."
        )

    def _extract_msdos71_boot_sector_from_binary(self, path: Path, disk_format: DiskFormat) -> bytes | None:
        try:
            data = path.read_bytes()
        except OSError:
            return None
        if len(data) < 512:
            return None
        for offset in range(0, len(data) - 511):
            sector = data[offset : offset + 512]
            if self._looks_like_msdos_boot_sector(sector, disk_format):
                return sector
        return None

    def _extract_msdos71_fat32_boot_sector_from_binary(self, path: Path) -> bytes | None:
        return self._extract_msdos71_boot_sector_from_binary(path, DiskFormat.FAT32)

    def _extract_msdos71_fat16_boot_sector_from_binary(self, path: Path) -> bytes | None:
        return self._extract_msdos71_boot_sector_from_binary(path, DiskFormat.FAT16)

    def _looks_like_msdos_boot_sector(self, sector: bytes, disk_format: DiskFormat) -> bool:
        if disk_format is DiskFormat.FAT16:
            return self._looks_like_msdos_fat16_boot_sector(sector)
        return self._looks_like_msdos_fat32_boot_sector(sector)

    def _looks_like_msdos_fat16_boot_sector(self, sector: bytes) -> bool:
        if len(sector) < 512 or sector[510:512] != b"\x55\xaa":
            return False
        if sector[0] not in (0xEB, 0xE9):
            return False
        if sector[54:62] not in (b"FAT16   ", b"FAT12   "):
            return False
        if sector[82:90] == b"FAT32   ":
            return False
        if b"IO      SYS" not in sector:
            return False
        if b"This is not a bootable disk" in sector:
            return False
        return True

    def _looks_like_msdos_fat32_boot_sector(self, sector: bytes) -> bool:
        if len(sector) < 512 or sector[510:512] != b"\x55\xaa":
            return False
        if sector[0] not in (0xEB, 0xE9):
            return False
        if sector[82:90] != b"FAT32   ":
            return False
        if b"IO      SYS" not in sector:
            return False
        if b"This is not a bootable disk" in sector:
            return False
        return True

    def _populate_freedos_startup_aliases(self, files: dict[str, Path]) -> None:
        if "FDCONFIG.SYS" not in files and "CONFIG.SYS" in files:
            files["FDCONFIG.SYS"] = files["CONFIG.SYS"]
        if "CONFIG.SYS" not in files and "FDCONFIG.SYS" in files:
            files["CONFIG.SYS"] = files["FDCONFIG.SYS"]
        if "FDAUTO.BAT" not in files and "AUTOEXEC.BAT" in files:
            files["FDAUTO.BAT"] = files["AUTOEXEC.BAT"]
        if "AUTOEXEC.BAT" not in files and "FDAUTO.BAT" in files:
            files["AUTOEXEC.BAT"] = files["FDAUTO.BAT"]

    def _ensure_startup_alias_file(self, *, source: Path, alias: Path) -> None:
        if alias.exists() or not source.exists() or not source.is_file():
            return
        shutil.copy2(source, alias)

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

    def _ensure_freedos_core_payload(self, destination: Path) -> None:
        bin_dir = destination / "BIN"
        command_path: Path | None = None
        kernel_path: Path | None = None
        if bin_dir.is_dir():
            command_path = self._find_file_case_insensitive(bin_dir, "COMMAND.COM")
            kernel_path = self._find_file_case_insensitive(bin_dir, "KERNL386.SYS")
        if command_path is not None and kernel_path is not None:
            return

        destination.mkdir(parents=True, exist_ok=True)
        for package_url in self._freedos14_core_package_urls():
            package_path = self._download_cached_file(package_url, cache_prefix="freedos-pkg")
            self._extract_zip_archive(package_path, destination, skip_prefixes=("SOURCE/",))

    def _prefer_freedos_core_system_files(self, files: dict[str, Path], payload_dir: Path) -> None:
        if not payload_dir.is_dir():
            return
        bin_dir = payload_dir / "BIN"
        if not bin_dir.is_dir():
            return

        command = self._find_file_case_insensitive(bin_dir, "COMMAND.COM")
        if command is not None:
            files["COMMAND.COM"] = command

        kernel = self._find_file_case_insensitive(bin_dir, "KERNL386.SYS")
        if kernel is None:
            kernel = self._find_file_case_insensitive(bin_dir, "KERNEL.SYS")
        if kernel is not None:
            files["KERNEL.SYS"] = kernel

    def _freedos14_package_urls(self) -> list[str]:
        urls: list[str] = []
        urls.extend(self._freedos14_core_package_urls())
        urls.extend([f"{FREEDOS_REPOSITORY_14_URL}/apps/{name}.zip" for name in _FREEDOS_APP_PACKAGES])
        urls.extend([f"{FREEDOS_REPOSITORY_14_URL}/base/{name}.zip" for name in (*_FREEDOS_USERSPACE_TOOLS, "htmlhelp")])
        urls.extend([f"{FREEDOS_REPOSITORY_14_URL}/unix/{name}.zip" for name in _FREEDOS_UNIXLIKE_PACKAGES])
        urls.extend([f"{FREEDOS_REPOSITORY_14_URL}/util/{name}.zip" for name in _FREEDOS_UTIL_PACKAGES])
        urls.extend([f"{FREEDOS_REPOSITORY_14_URL}/net/{name}.zip" for name in _FREEDOS_NET_PACKAGES])
        urls.extend([f"{FREEDOS_REPOSITORY_14_URL}/sound/{name}.zip" for name in _FREEDOS_SOUND_PACKAGES])
        urls.extend([f"{FREEDOS_REPOSITORY_14_URL}/devel/{name}.zip" for name in _FREEDOS_DEVEL_PACKAGES])
        return urls

    def _freedos14_core_package_urls(self) -> list[str]:
        return [f"{FREEDOS_REPOSITORY_14_URL}/base/{name}.zip" for name in _FREEDOS_CORE_PACKAGES]

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

    def _resolve_mbr_boot_template(self, directory: Path) -> Path | None:
        for candidate in ("MBR_FAT16.BIN", "MBR.BIN"):
            located = self._find_file_case_insensitive(directory, candidate)
            if located is not None:
                self._validate_mbr_boot_code_file(located)
                return located
        return None

    def _validate_boot_sector_file(self, path: Path) -> None:
        data = path.read_bytes()
        if len(data) < 512:
            raise ValidationError(f"Boot sector template must be at least 512 bytes: {path}")

    def _validate_mbr_boot_code_file(self, path: Path) -> None:
        data = path.read_bytes()
        if len(data) < 440:
            raise ValidationError(f"MBR boot code template must be at least 440 bytes: {path}")

    def _find_file_case_insensitive(self, directory: Path, file_name: str) -> Path | None:
        expected = file_name.upper()
        for entry in directory.iterdir():
            if entry.is_file() and entry.name.upper() == expected:
                return entry
        return None

    def _find_directory_case_insensitive(self, directory: Path, name: str) -> Path | None:
        expected = name.upper()
        for entry in directory.iterdir():
            if entry.is_dir() and entry.name.upper() == expected:
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
        bios_chs: tuple[int, int] | None = None,
    ) -> None:
        self._write_mbr_boot_code(
            disk_device=disk_device,
            template=assets.mbr_boot_code_template,
        )
        self._write_boot_sector(
            partition_device=partition_device,
            disk_format=disk_format,
            template=assets.boot_sector_template,
            bios_chs=bios_chs,
        )
        self._copy_system_files(
            partition_device=partition_device,
            system_files=assets.system_files,
            fdos_payload_dir=assets.fdos_payload_dir,
            payload_target_dir=assets.payload_target_dir,
        )

    def _copy_system_files(
        self,
        *,
        partition_device: str,
        system_files: dict[str, Path],
        fdos_payload_dir: Path | None,
        payload_target_dir: str,
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
                self._copy_payload_via_mount(
                    partition_device=partition_device,
                    payload_dir=fdos_payload_dir,
                    payload_target_dir=payload_target_dir,
                )

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
        destination_upper = destination_name.upper()
        normalizers = {
            "CONFIG.SYS": normalize_freedos_config_sys,
            "FDCONFIG.SYS": normalize_freedos_config_sys,
            "AUTOEXEC.BAT": normalize_freedos_autoexec_bat,
            "FDAUTO.BAT": normalize_freedos_autoexec_bat,
        }
        normalizer = normalizers.get(destination_upper)
        if normalizer is None:
            return source_path
        try:
            content = _read_dos_text(source_path)
        except OSError:
            return source_path
        normalized = _as_dos_text(normalizer(content))
        if normalized == content:
            return source_path

        suffix = ".sys" if destination_upper.endswith(".SYS") else ".bat"
        stem = destination_upper.lower().replace(".", "-")
        normalized_path = self.mount_root / f"normalized-{stem}-{uuid4().hex}{suffix}"
        _write_dos_text(normalized_path, normalized)
        temp_files.append(normalized_path)
        return normalized_path

    def _copy_payload_via_mount(
        self,
        *,
        partition_device: str,
        payload_dir: Path,
        payload_target_dir: str,
    ) -> None:
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
            target_root = mountpoint / payload_target_dir
            target_root.mkdir(parents=True, exist_ok=True)
            for source in payload_dir.rglob("*"):
                relative = source.relative_to(payload_dir)
                destination = target_root / relative
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

    def _write_mbr_boot_code(self, *, disk_device: str, template: Path | None = None) -> None:
        mbr_code_path = template or self._find_mbr_boot_code()
        if not mbr_code_path.exists() or not mbr_code_path.is_file():
            raise ValidationError(f"MBR boot code file does not exist: {mbr_code_path}")
        if mbr_code_path.stat().st_size < 440:
            raise ValidationError(f"MBR boot code template must be at least 440 bytes: {mbr_code_path}")
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

    def _write_boot_sector(
        self,
        *,
        partition_device: str,
        disk_format: DiskFormat,
        template: Path,
        bios_chs: tuple[int, int] | None = None,
    ) -> None:
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
        if disk_format is DiskFormat.FAT16 and bios_chs is not None:
            self._patch_fat16_bpb_geometry(partition_device=partition_device, bios_chs=bios_chs)

    def _patch_fat16_bpb_geometry(self, *, partition_device: str, bios_chs: tuple[int, int]) -> None:
        sectors_per_track, heads = bios_chs
        if sectors_per_track <= 0 or heads <= 0:
            return

        patch_file = self.mount_root / f"fat16-geometry-{uuid4().hex}.bin"
        patch_file.write_bytes(struct.pack("<HH", sectors_per_track, heads))
        try:
            self.runner.run(
                [
                    "dd",
                    f"if={patch_file}",
                    f"of={partition_device}",
                    "bs=1",
                    "seek=24",
                    "count=4",
                    "conv=notrunc",
                ],
                sudo=True,
            )
        finally:
            if patch_file.exists():
                patch_file.unlink()
