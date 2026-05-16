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
from collections import OrderedDict
from urllib.error import HTTPError, URLError
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from .commands import CommandRunner
from .errors import ValidationError
from .mscompress import compressed_variant_name, expand_dos_compressed_payload, expanded_name_from_compressed
from .models import (
    BootMode,
    CreateRequest,
    DiskFormat,
    FloppyType,
    FreeDOSSource,
    IBMDOSVersion,
    MSDOSInstallProfile,
    MediaType,
)
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
_IBM_DOS_BOOTSECTOR_SOURCES = ("SYS.COM", "FORMAT.COM")
_LEGACY_DOS_SYSTEM_FILE_SETS = (
    ("IO.SYS", "MSDOS.SYS", "COMMAND.COM"),
    ("IBMBIO.COM", "IBMDOS.COM", "COMMAND.COM"),
)
_MSDOS71_INSTALL_PAK = "DOS71_1S.PAK"
_MSDOS71_OPTIONAL_INSTALL_PAK = "DOS71_2S.PAK"
_MSDOS71_PAK_PASSWORD = b":MSDOS"
_MSDOS71_BOOTSECTOR_SOURCES = ("SYS.COM", "FORMAT.COM")
_MSDOS71_IMAGE_SUFFIXES = (".img", ".ima", ".dsk", ".xdf")
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
    "PATH=A:\\DOS\r\n"
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
_MSDOS_INSTALL_PATTERN = re.compile(r"^\s*INSTALL(?:HIGH)?=(?P<program>[^\s]+)(?P<suffix>.*)$", re.IGNORECASE)
_MSDOS_PATH_PATTERN = re.compile(r"^\s*(?:SET\s+)?PATH(?:\s*=|\s+).*$", re.IGNORECASE)
_MSDOS_COUNTRY_PATTERN = re.compile(r"^\s*COUNTRY\s*=", re.IGNORECASE)
_VALID_FAT_MEDIA_DESCRIPTORS = frozenset({0xF0, 0xF8, 0xF9, 0xFA, 0xFB, 0xFC, 0xFD, 0xFE, 0xFF})
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
_DOS_CORE_PAYLOAD_UTILITY_CANDIDATES = (
    ("EDIT.COM",),
    ("E.EXE",),
    ("CHKDSK.EXE", "CHKDSK.COM", "CHKDSK.EX_"),
    ("SUBST.EXE", "SUBST.EX_"),
    ("ATTRIB.EXE", "ATTRIB.EX_"),
    ("FDISK.EXE", "FDISK.COM", "FDISK.EX_"),
    ("FORMAT.COM", "FORMAT.EXE", "FORMAT.CO_"),
    ("SYS.COM", "SYS.EXE", "SYS.CO_"),
    ("MODE.COM", "MODE.EXE", "MODE.CO_"),
    ("MEM.EXE", "MEM.COM", "MEM.EX_"),
    ("KEYB.COM", "KEYB.EXE", "KEYB.CO_"),
    ("DEBUG.EXE", "DEBUG.COM", "DEBUG.EX_"),
    ("EDLIN.EXE", "EDLIN.COM", "EDLIN.EX_"),
    ("XCOPY.EXE", "XCOPY.COM", "XCOPY.EX_"),
    ("FIND.EXE", "FIND.COM", "FIND.EX_"),
    ("MORE.COM", "MORE.EXE", "MORE.CO_"),
    ("LABEL.EXE", "LABEL.COM", "LABEL.EX_"),
    ("DISKCOPY.COM", "DISKCOPY.EXE", "DISKCOPY.CO_"),
    ("DISKCOMP.COM", "DISKCOMP.EXE", "DISKCOMP.CO_"),
    ("QBASIC.EXE", "QBASIC.EX_"),
)
_DOS_CORE_PAYLOAD_COMPANION_FILES = {
    "EDIT.COM": ("EDIT.HLP",),
    "QBASIC.EXE": ("QBASIC.HLP",),
    "E.EXE": ("E.EX", "E.INI", "EHELP.HLP"),
}
_DOS_CORE_PAYLOAD_MIN_BYTES = 64 * 1024
_DOS_CORE_PAYLOAD_MAX_BYTES = 512 * 1024
_DOS_STARTUP_WRAPPER_COMMANDS = frozenset({"CALL", "LH", "LOADHIGH"})
_DOS_INTERNAL_COMMANDS = frozenset(
    {
        "BREAK",
        "CD",
        "CHDIR",
        "CLS",
        "COPY",
        "CTTY",
        "DATE",
        "DEL",
        "DIR",
        "ECHO",
        "ERASE",
        "FOR",
        "GOTO",
        "IF",
        "MD",
        "MKDIR",
        "PATH",
        "PAUSE",
        "PROMPT",
        "RD",
        "REM",
        "REN",
        "RENAME",
        "RMDIR",
        "SET",
        "SHIFT",
        "TIME",
        "TYPE",
        "VER",
        "VERIFY",
        "VOL",
    }
)
_DOS_BOOT_ROOT_FILES = frozenset({"COMMAND.COM", "IBMBIO.COM", "IBMDOS.COM", "IO.SYS", "KERNEL.SYS", "MSDOS.SYS"})
_DOS_SYSTEM_HIDDEN_FILES = frozenset({"IBMBIO.COM", "IBMDOS.COM", "IO.SYS", "KERNEL.SYS", "MSDOS.SYS"})
_SAVE_DSKF_HEADER_MIN = 0x2A
_SAVE_DSKF_SIGNATURE = b"\xAA\x59"
_SAVE_DSKF_SECTOR_COUNT_OFFSET = 0x22
_SAVE_DSKF_FIRST_SECTOR_OFFSET = 0x26


def normalize_msdos_config_sys(text: str, *, install_dir: str = r"A:\DOS") -> str:
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
    return _as_dos_text("\r\n".join(output).rstrip("\r\n") + "\r\n")


def normalize_msdos_autoexec_bat(text: str, *, install_dir: str = r"A:\DOS") -> str:
    _ = text
    return _as_dos_text(f"@ECHO OFF\r\nPATH={install_dir}\r\n")


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
    source_image_size_bytes: int | None = None


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
        if request.boot_mode is BootMode.MSDOS71:
            return self._resolve_msdos71(request)
        if request.boot_mode is BootMode.IBM8088:
            return self._resolve_ibm8088(request)
        if request.boot_mode is BootMode.MSDOS33:
            return self._resolve_msdos33(request)
        if request.boot_mode is BootMode.MSDOS331:
            return self._resolve_msdos331(request)
        if request.boot_mode is BootMode.MSDOS5:
            return self._resolve_msdos5(request)
        if request.boot_mode is BootMode.MSDOS622:
            return self._resolve_msdos622(request)
        if request.boot_mode is BootMode.PCDOS:
            return self._resolve_pcdos(request)
        if request.boot_mode is BootMode.PCDOS7:
            return self._resolve_pcdos7(request)
        if request.boot_mode is BootMode.COMPAQ331:
            return self._resolve_compaq331(request)
        raise ValidationError(f"Unsupported boot mode: {request.boot_mode.value}")

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
        if disk_format is DiskFormat.FAT32:
            template_sector = template.read_bytes()[:512]
            if not self._looks_like_freedos_fat32_boot_sector(template_sector):
                fat16_template = self._find_file_case_insensitive(directory, "BOOTSECT_FAT16.BIN")
                if fat16_template is None:
                    raise ValidationError(
                        "FreeDOS FAT32 boot assets include a non-bootable BOOTSECT_FAT32.BIN and no "
                        "BOOTSECT_FAT16.BIN fallback is available. Provide valid FreeDOS boot templates."
                    )
                self._validate_boot_sector_file(fat16_template)
                template = fat16_template
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
        payload_budget_bytes = (
            self._dos_core_payload_budget(request)
            if request.msdos_install_profile is MSDOSInstallProfile.FULL
            else None
        )
        return self._resolve_msdos71_from_install_images(
            directory,
            disk_format=request.disk_format,
            install_profile=request.msdos_install_profile,
            payload_budget_bytes=payload_budget_bytes,
        )

    def _resolve_ibm8088(self, request: CreateRequest) -> BootAssets:
        version_dir_name = "dos33" if request.ibm_dos_version is IBMDOSVersion.DOS33 else "dos50"
        version_label = "DOS 3.3" if request.ibm_dos_version is IBMDOSVersion.DOS33 else "DOS 5.0"
        default_asset_dirs = ("msdos33", "dos33") if request.ibm_dos_version is IBMDOSVersion.DOS33 else (
            "msdos5",
            "dos5",
            "dos50",
        )
        return self._resolve_legacy_dos(
            request=request,
            profile_label=f"IBM 8088/V20 {version_label}",
            version_subdir_name=version_dir_name,
            cache_tag=f"ibm8088-{request.ibm_dos_version.value}",
            prefer_install_image_boot_sector=request.ibm_dos_version is IBMDOSVersion.DOS33,
            default_asset_dirs=default_asset_dirs,
            install_profile=request.msdos_install_profile,
        )

    def _resolve_msdos33(self, request: CreateRequest) -> BootAssets:
        return self._resolve_legacy_dos(
            request=request,
            profile_label="MS-DOS 3.3",
            version_subdir_name="msdos33",
            cache_tag="msdos33",
            prefer_install_image_boot_sector=True,
            default_asset_dirs=("msdos33",),
            install_profile=request.msdos_install_profile,
        )

    def _resolve_msdos331(self, request: CreateRequest) -> BootAssets:
        # MS-DOS 3.31 (Compaq OEM and equivalents) introduced FAT16B with
        # uint32 total_sectors_32, so >32 MiB FAT16 partitions are supported.
        # The install diskettes are 720K floppies whose first sector is a
        # FLOPPY boot sector (OEM "IBM  3.3", total16=1440); grafting that
        # onto a hard-disk partition produces an unbootable VHD because the
        # floppy boot code expects a 720K geometry and a fully-populated
        # floppy BPB. Use prefer_install_image_boot_sector=False so vhdmaker
        # synthesizes a proper hard-disk FAT16 boot sector from SYS.COM /
        # FORMAT.COM extracted out of the install image (same as compaq331).
        return self._resolve_legacy_dos(
            request=request,
            profile_label="MS-DOS 3.31",
            version_subdir_name="msdos331",
            cache_tag="msdos331",
            prefer_install_image_boot_sector=False,
            default_asset_dirs=("msdos331", "compaq331"),
            install_profile=request.msdos_install_profile,
        )

    def _resolve_msdos5(self, request: CreateRequest) -> BootAssets:
        return self._resolve_legacy_dos(
            request=request,
            profile_label="MS-DOS 5.0",
            version_subdir_name="msdos5",
            cache_tag="msdos5",
            prefer_install_image_boot_sector=True,
            default_asset_dirs=("msdos5",),
            install_profile=request.msdos_install_profile,
        )

    def _resolve_msdos622(self, request: CreateRequest) -> BootAssets:
        return self._resolve_legacy_dos(
            request=request,
            profile_label="MS-DOS 6.22",
            version_subdir_name="msdos622",
            cache_tag="msdos622",
            prefer_install_image_boot_sector=True,
            default_asset_dirs=("msdos622",),
            install_profile=request.msdos_install_profile,
        )

    def _resolve_pcdos(self, request: CreateRequest) -> BootAssets:
        return self._resolve_legacy_dos(
            request=request,
            profile_label="PC-DOS",
            version_subdir_name="pcdos",
            cache_tag="pcdos",
            prefer_install_image_boot_sector=False,
            default_asset_dirs=("pcdos", "pcdos7"),
            install_profile=request.msdos_install_profile,
        )

    def _resolve_pcdos7(self, request: CreateRequest) -> BootAssets:
        return self._resolve_legacy_dos(
            request=request,
            profile_label="PC-DOS 7.0",
            version_subdir_name="pcdos7",
            cache_tag="pcdos7",
            prefer_install_image_boot_sector=True,
            default_asset_dirs=("pcdos7",),
            prefer_install_images_first=True,
            prefer_directory_boot_template=False,
            install_profile=request.msdos_install_profile,
        )

    def _resolve_compaq331(self, request: CreateRequest) -> BootAssets:
        return self._resolve_legacy_dos(
            request=request,
            profile_label="Compaq DOS 3.31",
            version_subdir_name="compaq331",
            cache_tag="compaq331",
            prefer_install_image_boot_sector=False,
            default_asset_dirs=("compaq331", "msdos331"),
            install_profile=request.msdos_install_profile,
        )

    def _resolve_legacy_dos(
        self,
        *,
        request: CreateRequest,
        profile_label: str,
        version_subdir_name: str | None,
        cache_tag: str,
        prefer_install_image_boot_sector: bool,
        default_asset_dirs: tuple[str, ...] = (),
        prefer_install_images_first: bool = False,
        prefer_directory_boot_template: bool = True,
        install_profile: MSDOSInstallProfile = MSDOSInstallProfile.MINIMAL,
    ) -> BootAssets:
        if request.disk_format is not DiskFormat.FAT16:
            raise ValidationError(f"{profile_label} boot mode requires FAT16 format.")
        directory = self._resolve_legacy_assets_directory(request=request, fallback_dirs=default_asset_dirs)
        if not directory.is_dir():
            raise ValidationError(f"{profile_label} asset path must be a directory: {directory}")
        payload_budget_bytes = (
            self._dos_core_payload_budget(request)
            if install_profile is MSDOSInstallProfile.FULL
            else None
        )

        candidate_directories: list[Path] = [directory]
        if version_subdir_name:
            version_subdir = self._find_directory_case_insensitive(directory, version_subdir_name)
            if version_subdir is not None and version_subdir not in candidate_directories:
                candidate_directories.append(version_subdir)

        for candidate in candidate_directories:
            if prefer_install_images_first:
                image_assets = self._try_resolve_legacy_dos_from_install_images(
                    candidate,
                    cache_tag=cache_tag,
                    prefer_install_image_boot_sector=prefer_install_image_boot_sector,
                    prefer_directory_boot_template=prefer_directory_boot_template,
                    install_profile=install_profile,
                    payload_budget_bytes=payload_budget_bytes,
                    media_type=request.media_type,
                )
                if image_assets is not None:
                    return image_assets

                direct_assets = self._try_resolve_legacy_dos_from_directory(
                    candidate,
                    install_profile=install_profile,
                )
                if direct_assets is not None:
                    return direct_assets
            else:
                direct_assets = self._try_resolve_legacy_dos_from_directory(
                    candidate,
                    install_profile=install_profile,
                )
                if direct_assets is not None:
                    if (
                        install_profile is MSDOSInstallProfile.FULL
                        and direct_assets.fdos_payload_dir is None
                    ):
                        image_assets = self._try_resolve_legacy_dos_from_install_images(
                            candidate,
                            cache_tag=cache_tag,
                            prefer_install_image_boot_sector=prefer_install_image_boot_sector,
                            prefer_directory_boot_template=prefer_directory_boot_template,
                            install_profile=install_profile,
                            payload_budget_bytes=payload_budget_bytes,
                            media_type=request.media_type,
                        )
                        if image_assets is not None:
                            return image_assets
                    return direct_assets

                image_assets = self._try_resolve_legacy_dos_from_install_images(
                    candidate,
                    cache_tag=cache_tag,
                    prefer_install_image_boot_sector=prefer_install_image_boot_sector,
                    prefer_directory_boot_template=prefer_directory_boot_template,
                    install_profile=install_profile,
                    payload_budget_bytes=payload_budget_bytes,
                    media_type=request.media_type,
                )
                if image_assets is not None:
                    return image_assets

        raise ValidationError(
            f"{profile_label} assets were not found. Provide either direct files "
            "(IO.SYS+MSDOS.SYS+COMMAND.COM or IBMBIO.COM+IBMDOS.COM+COMMAND.COM, plus BOOTSECT_FAT16.BIN/BOOTSECT.BIN) "
            f"or floppy images (*.img/*.ima/*.dsk/*.xdf) under {directory}."
        )

    def _resolve_legacy_assets_directory(self, *, request: CreateRequest, fallback_dirs: tuple[str, ...]) -> Path:
        if request.boot_assets_path is not None:
            return request.boot_assets_path.expanduser().resolve()
        for directory_name in fallback_dirs:
            candidate = (Path.cwd() / directory_name).resolve()
            if candidate.is_dir():
                return candidate
        raise ValidationError(
            "This DOS boot mode requires a local boot assets path. "
            f"Checked defaults under current directory: {', '.join(fallback_dirs) if fallback_dirs else '(none)'}"
        )

    def _try_resolve_legacy_dos_from_directory(
        self,
        directory: Path,
        *,
        install_profile: MSDOSInstallProfile = MSDOSInstallProfile.MINIMAL,
    ) -> BootAssets | None:
        files = self._collect_legacy_system_files_from_directory(directory)
        if files is None:
            return None
        for name in _OPTIONAL_MSDOS_STARTUP_FILES:
            located = self._find_file_case_insensitive(directory, name)
            if located is not None:
                files[name] = located
        startup_defaults_root = self.cache_root / f"legacy-startup-{self._hash_value(str(directory.resolve()))}"
        if any(name in files for name in _OPTIONAL_MSDOS_STARTUP_FILES):
            self._normalize_msdos_startup_files(files, defaults_root=startup_defaults_root)
        payload_dir: Path | None = None
        payload_target_dir = "FDOS"
        if install_profile is MSDOSInstallProfile.FULL:
            self._ensure_msdos_startup_files(files, defaults_root=startup_defaults_root)
            self._normalize_msdos_startup_files(files, defaults_root=startup_defaults_root)
            payload_dir = self._find_directory_case_insensitive(directory, "DOS")
            if payload_dir is not None:
                payload_target_dir = "DOS"
        self._ensure_country_sys_from_directory(files, directory)
        try:
            template = self._resolve_boot_template(directory, DiskFormat.FAT16)
        except ValidationError:
            return None
        return BootAssets(
            system_files=files,
            boot_sector_template=template,
            fdos_payload_dir=payload_dir,
            payload_target_dir=payload_target_dir,
        )

    def _try_resolve_legacy_dos_from_install_images(
        self,
        directory: Path,
        *,
        cache_tag: str,
        prefer_install_image_boot_sector: bool,
        prefer_directory_boot_template: bool = True,
        install_profile: MSDOSInstallProfile = MSDOSInstallProfile.MINIMAL,
        payload_budget_bytes: int | None = None,
        media_type: MediaType = MediaType.VHD,
    ) -> BootAssets | None:
        install_images = self._collect_msdos71_install_images(directory)
        if not install_images:
            return None

        cache_key = f"{cache_tag}|{self._msdos71_cache_key(directory, install_images)}"
        extraction_root = self.cache_root / f"{cache_tag}-{self._hash_value(cache_key)}"
        extraction_root.mkdir(parents=True, exist_ok=True)

        files = self._extract_legacy_system_files_from_images(install_images, extraction_root)
        if files is None:
            return None
        if install_profile is MSDOSInstallProfile.FULL:
            for name in _OPTIONAL_MSDOS_STARTUP_FILES:
                extracted = self._extract_file_from_images(install_images, extraction_root, name, required=False)
                if extracted is not None:
                    files[name] = extracted
            startup_defaults_root = extraction_root / "startup-defaults"
            self._ensure_msdos_startup_files(files, defaults_root=startup_defaults_root)
            self._normalize_msdos_startup_files(files, defaults_root=startup_defaults_root)
        self._ensure_country_sys_from_install_images(files, install_images, extraction_root=extraction_root)
        for name in _IBM_DOS_BOOTSECTOR_SOURCES:
            self._extract_file_from_images(install_images, extraction_root, name, required=False)

        template: Path | None = None
        if prefer_directory_boot_template:
            try:
                template = self._resolve_boot_template(directory, DiskFormat.FAT16)
            except ValidationError:
                template = None

        if template is None:
            template = extraction_root / "BOOTSECT_FAT16.BIN"
            source_candidates = tuple(extraction_root / name for name in _IBM_DOS_BOOTSECTOR_SOURCES)
            if prefer_install_image_boot_sector:
                boot_sector = self._extract_msdos_fat16_boot_sector_from_images(install_images)
                if boot_sector is not None:
                    template.write_bytes(boot_sector)
                elif any(path.exists() for path in source_candidates):
                    self._write_msdos_boot_template(
                        template,
                        disk_format=DiskFormat.FAT16,
                        source_candidates=source_candidates,
                        source_label="legacy DOS install media",
                    )
                else:
                    return None
            elif any(path.exists() for path in source_candidates):
                self._write_msdos_boot_template(
                    template,
                    disk_format=DiskFormat.FAT16,
                    source_candidates=source_candidates,
                    source_label="legacy DOS install media",
                )
            else:
                boot_sector = self._extract_msdos_fat16_boot_sector_from_images(install_images)
                if boot_sector is None:
                    return None
                template.write_bytes(boot_sector)

        if media_type is MediaType.VHD:
            self._normalize_legacy_vhd_boot_template(template=template, system_files=files)

        source_image_size_bytes = self._select_source_image_size_bytes(install_images)
        payload_dir: Path | None = None
        payload_target_dir = "FDOS"
        if install_profile is MSDOSInstallProfile.FULL:
            payload_dir = extraction_root / "DOS"
            self._extract_legacy_full_payload_from_images(
                install_images=install_images,
                destination=payload_dir,
                payload_budget_bytes=payload_budget_bytes,
                startup_files=files,
            )
            payload_target_dir = "DOS"

        return BootAssets(
            system_files=files,
            boot_sector_template=template,
            fdos_payload_dir=payload_dir,
            payload_target_dir=payload_target_dir,
            source_image_size_bytes=source_image_size_bytes,
        )

    def _extract_legacy_full_payload_from_images(
        self,
        *,
        install_images: list[Path],
        destination: Path,
        payload_budget_bytes: int | None = None,
        startup_files: dict[str, Path] | None = None,
    ) -> None:
        if destination.exists():
            shutil.rmtree(destination)
        destination.mkdir(parents=True, exist_ok=True)
        self._extract_core_payload_from_images(
            install_images=install_images,
            destination=destination,
            payload_budget_bytes=payload_budget_bytes,
            startup_files=startup_files,
        )

    def _dos_core_payload_budget(self, request: CreateRequest) -> int | None:
        if request.media_type is not MediaType.IMG and request.path.suffix.lower() not in {".img", ".ima"}:
            return None
        return min(
            _DOS_CORE_PAYLOAD_MAX_BYTES,
            max(_DOS_CORE_PAYLOAD_MIN_BYTES, request.size_bytes // 2),
        )

    def _trim_payload_to_core_files(
        self,
        *,
        payload_dir: Path,
        payload_budget_bytes: int | None,
        startup_files: dict[str, Path] | None = None,
    ) -> None:
        startup_requests = self._collect_startup_payload_requests(startup_files or {})
        selected = self._select_dos_core_payload_files(
            roots=(payload_dir,),
            payload_budget_bytes=payload_budget_bytes,
            startup_requests=startup_requests,
        )
        if not selected:
            raise ValidationError(
                "Unable to identify core DOS utilities in the provided install media for full install profile."
            )

        staged_dir = payload_dir.parent / f"{payload_dir.name}-core-{uuid4().hex[:8]}"
        if staged_dir.exists():
            shutil.rmtree(staged_dir)
        staged_dir.mkdir(parents=True, exist_ok=True)
        written: set[str] = set()
        for source in selected:
            upper_name = source.name.upper()
            if upper_name in written:
                continue
            shutil.copy2(source, staged_dir / source.name)
            written.add(upper_name)

        if payload_dir.exists():
            shutil.rmtree(payload_dir)
        staged_dir.rename(payload_dir)

    def _extract_core_payload_from_images(
        self,
        *,
        install_images: list[Path],
        destination: Path,
        payload_budget_bytes: int | None,
        startup_files: dict[str, Path] | None,
    ) -> None:
        selected_size_bytes = 0
        selected_names: set[str] = set()
        extracted_any = False
        startup_requests = self._collect_startup_payload_requests(startup_files or {})
        for startup_candidates in startup_requests:
            selected = self._extract_core_payload_file_from_images(
                install_images=install_images,
                destination=destination,
                candidate_names=startup_candidates,
                selected_names=selected_names,
                selected_size_bytes=selected_size_bytes,
                payload_budget_bytes=payload_budget_bytes,
            )
            if selected is None:
                continue
            extracted_any = True
            selected_path, selected_size = selected
            selected_names.add(selected_path.name.upper())
            selected_size_bytes += selected_size

        for utility_candidates in _DOS_CORE_PAYLOAD_UTILITY_CANDIDATES:
            selected = self._extract_core_payload_file_from_images(
                install_images=install_images,
                destination=destination,
                candidate_names=utility_candidates,
                selected_names=selected_names,
                selected_size_bytes=selected_size_bytes,
                payload_budget_bytes=payload_budget_bytes,
            )
            if selected is None:
                continue
            extracted_any = True
            selected_path, selected_size = selected
            selected_names.add(selected_path.name.upper())
            selected_size_bytes += selected_size
            for companion_name in _DOS_CORE_PAYLOAD_COMPANION_FILES.get(selected_path.name.upper(), ()):
                companion = self._extract_core_payload_file_from_images(
                    install_images=install_images,
                    destination=destination,
                    candidate_names=(companion_name,),
                    selected_names=selected_names,
                    selected_size_bytes=selected_size_bytes,
                    payload_budget_bytes=payload_budget_bytes,
                )
                if companion is None:
                    continue
                companion_path, companion_size = companion
                selected_names.add(companion_path.name.upper())
                selected_size_bytes += companion_size

        if not extracted_any:
            raise ValidationError(
                "Unable to identify core DOS utilities in the provided install media for full install profile."
            )

    def _collect_startup_payload_requests(self, system_files: dict[str, Path]) -> tuple[tuple[str, ...], ...]:
        requests: OrderedDict[tuple[str, ...], None] = OrderedDict()
        for base_name, extensions in self._parse_config_payload_references(system_files):
            self._record_startup_payload_request(requests, base_name, extensions)
        for base_name, extensions in self._parse_autoexec_payload_references(system_files):
            self._record_startup_payload_request(requests, base_name, extensions)
        return tuple(requests.keys())

    def _record_startup_payload_request(
        self,
        requests: OrderedDict[tuple[str, ...], None],
        base_name: str,
        extensions: tuple[str, ...],
    ) -> None:
        candidates: list[str] = []
        for extension in extensions:
            normalized = f"{base_name.upper()}.{extension.upper()}"
            if normalized in _DOS_BOOT_ROOT_FILES:
                continue
            candidates.append(normalized)
            compressed = compressed_variant_name(normalized)
            if compressed is not None:
                candidates.append(compressed)
        if candidates:
            requests.setdefault(tuple(candidates), None)

    def _parse_config_payload_references(self, system_files: dict[str, Path]) -> tuple[tuple[str, tuple[str, ...]], ...]:
        config = system_files.get("CONFIG.SYS")
        if config is None or not config.exists() or not config.is_file():
            return ()
        try:
            content = _read_dos_text(config)
        except OSError:
            return ()

        references: OrderedDict[tuple[str, tuple[str, ...]], None] = OrderedDict()
        for raw_line in _as_dos_text(content).splitlines():
            line = raw_line.replace("\x1a", "").strip()
            if not line:
                continue
            upper = line.upper()
            if upper.startswith("REM ") or upper == "REM" or line.startswith("::"):
                continue

            device_match = _MSDOS_DEVICE_PATTERN.match(line)
            if device_match is not None:
                reference = self._normalize_startup_payload_reference(
                    device_match.group("driver"),
                    default_extensions=("SYS",),
                )
                if reference is not None:
                    references.setdefault(reference, None)
                continue

            install_match = _MSDOS_INSTALL_PATTERN.match(line)
            if install_match is not None:
                reference = self._normalize_startup_payload_reference(
                    install_match.group("program"),
                    default_extensions=("COM", "EXE", "BAT"),
                )
                if reference is not None:
                    references.setdefault(reference, None)

        return tuple(references.keys())

    def _parse_autoexec_payload_references(self, system_files: dict[str, Path]) -> tuple[tuple[str, tuple[str, ...]], ...]:
        autoexec = system_files.get("AUTOEXEC.BAT")
        if autoexec is None or not autoexec.exists() or not autoexec.is_file():
            return ()
        try:
            content = _read_dos_text(autoexec)
        except OSError:
            return ()

        references: OrderedDict[tuple[str, tuple[str, ...]], None] = OrderedDict()
        for raw_line in _as_dos_text(content).splitlines():
            line = raw_line.replace("\x1a", "").strip()
            if not line:
                continue
            upper = line.upper()
            if upper.startswith("REM ") or upper == "REM" or line.startswith("::"):
                continue
            if _MSDOS_PATH_PATTERN.match(line):
                continue

            tokens = line.split()
            if not tokens:
                continue
            command = tokens[0].lstrip("@")
            if not command:
                continue
            if command.upper() == "IF":
                continue

            while command.upper() in _DOS_STARTUP_WRAPPER_COMMANDS and len(tokens) > 1:
                tokens = tokens[1:]
                command = tokens[0].lstrip("@")
                if not command:
                    break
            if not command:
                continue
            if command.upper() in _DOS_INTERNAL_COMMANDS:
                continue
            if "=" in command and not any(marker in command for marker in (".", "\\", "/")):
                continue

            reference = self._normalize_startup_payload_reference(
                command,
                default_extensions=("COM", "EXE", "BAT"),
            )
            if reference is None:
                continue
            references.setdefault(reference, None)

        return tuple(references.keys())

    def _normalize_startup_payload_reference(
        self,
        token: str,
        *,
        default_extensions: tuple[str, ...],
    ) -> tuple[str, tuple[str, ...]] | None:
        name = _dos_basename(token.strip().strip('"'))
        if not name:
            return None
        upper_name = name.upper()
        if upper_name in _DOS_INTERNAL_COMMANDS:
            return None
        if upper_name in {"COMMAND.COM", "IO.SYS", "MSDOS.SYS", "IBMBIO.COM", "IBMDOS.COM", "KERNEL.SYS"}:
            return None

        if "." in upper_name:
            stem, extension = upper_name.rsplit(".", 1)
            if not stem or not extension:
                return None
            return (stem, (extension,))
        return (upper_name, default_extensions)

    def _config_references_country_sys(self, system_files: dict[str, Path]) -> bool:
        config = system_files.get("CONFIG.SYS")
        if config is None or not config.exists() or not config.is_file():
            return False
        try:
            content = _read_dos_text(config)
        except OSError:
            return False
        for raw_line in _as_dos_text(content).splitlines():
            line = raw_line.replace("\x1a", "").strip()
            if not line:
                continue
            upper = line.upper()
            if upper.startswith("REM ") or upper == "REM" or line.startswith("::"):
                continue
            if _MSDOS_COUNTRY_PATTERN.match(line):
                return True
        return False

    def _ensure_country_sys_from_directory(self, system_files: dict[str, Path], directory: Path) -> None:
        if "COUNTRY.SYS" in system_files:
            return
        if not self._config_references_country_sys(system_files):
            return
        country = self._find_file_case_insensitive(directory, "COUNTRY.SYS")
        if country is not None:
            system_files["COUNTRY.SYS"] = country

    def _ensure_country_sys_from_install_images(
        self,
        system_files: dict[str, Path],
        install_images: list[Path],
        *,
        extraction_root: Path,
    ) -> None:
        if "COUNTRY.SYS" in system_files:
            return
        if not self._config_references_country_sys(system_files):
            return
        country = self._extract_file_from_images_with_compression_fallback(
            install_images,
            extraction_root,
            "COUNTRY.SYS",
            required=False,
        )
        if country is not None:
            system_files["COUNTRY.SYS"] = country

    def _extract_core_payload_file_from_images(
        self,
        *,
        install_images: list[Path],
        destination: Path,
        candidate_names: tuple[str, ...],
        selected_names: set[str],
        selected_size_bytes: int,
        payload_budget_bytes: int | None,
    ) -> tuple[Path, int] | None:
        for candidate_name in candidate_names:
            if candidate_name.upper() in selected_names:
                continue
            extracted = self._extract_file_from_images(
                install_images,
                destination,
                candidate_name,
                required=False,
            )
            if extracted is None:
                continue
            try:
                size_bytes = extracted.stat().st_size
            except OSError:
                continue
            if payload_budget_bytes is not None and selected_size_bytes + size_bytes > payload_budget_bytes:
                if extracted.exists():
                    extracted.unlink()
                continue
            return (extracted, size_bytes)
        return None

    def _select_dos_core_payload_files(
        self,
        *,
        roots: tuple[Path, ...],
        payload_budget_bytes: int | None,
        startup_requests: tuple[tuple[str, ...], ...] = (),
    ) -> list[Path]:
        lookup: dict[str, list[Path]] = {}
        for root in roots:
            if not root.exists() or not root.is_dir():
                continue
            for candidate in sorted(root.rglob("*")):
                if candidate.is_file():
                    lookup.setdefault(candidate.name.upper(), []).append(candidate)

        selected: list[Path] = []
        selected_names: set[str] = set()
        selected_size = 0

        def select_first_available(*candidate_names: str) -> Path | None:
            nonlocal selected_size
            for candidate_name in candidate_names:
                for source in lookup.get(candidate_name.upper(), ()):
                    upper_name = source.name.upper()
                    if upper_name in selected_names:
                        return source
                    try:
                        source_size = source.stat().st_size
                    except OSError:
                        continue
                    if payload_budget_bytes is not None and selected_size + source_size > payload_budget_bytes:
                        continue
                    selected.append(source)
                    selected_names.add(upper_name)
                    selected_size += source_size
                    return source
            return None

        for startup_candidates in startup_requests:
            select_first_available(*startup_candidates)

        for candidate_names in _DOS_CORE_PAYLOAD_UTILITY_CANDIDATES:
            chosen = select_first_available(*candidate_names)
            if chosen is None:
                continue
            for companion in _DOS_CORE_PAYLOAD_COMPANION_FILES.get(chosen.name.upper(), ()):
                select_first_available(companion)

        return selected

    def _collect_legacy_system_files_from_directory(self, directory: Path) -> dict[str, Path] | None:
        for required_set in _LEGACY_DOS_SYSTEM_FILE_SETS:
            files: dict[str, Path] = {}
            for name in required_set:
                located = self._find_file_case_insensitive(directory, name)
                if located is None:
                    break
                files[name] = located
            else:
                return files
        return None

    def _extract_legacy_system_files_from_images(
        self,
        install_images: list[Path],
        extraction_root: Path,
    ) -> dict[str, Path] | None:
        for required_set in _LEGACY_DOS_SYSTEM_FILE_SETS:
            files: dict[str, Path] = {}
            for name in required_set:
                extracted = self._extract_file_from_images(
                    install_images,
                    extraction_root,
                    name,
                    required=False,
                )
                if extracted is None:
                    break
                files[name] = extracted
            else:
                return files
        return None

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
        self._ensure_country_sys_from_directory(files, directory)

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
        payload_budget_bytes: int | None = None,
    ) -> BootAssets:
        install_images = self._collect_msdos71_install_images(directory)
        if not install_images:
            raise ValidationError(
                "MS-DOS 7.1 assets were not found. Provide either direct files "
                "(IO.SYS, MSDOS.SYS, COMMAND.COM, HIMEM.SYS, IFSHLP.SYS, "
                "BOOTSECT_FAT16.BIN/BOOTSECT_FAT32.BIN) "
                "or DOS71 install disk images (*.img/*.ima/*.dsk/*.xdf)."
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
        self._ensure_country_sys_from_install_images(files, install_images, extraction_root=extraction_root)

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
                payload_budget_bytes=payload_budget_bytes,
                startup_files=files,
            )
            payload_target_dir = "DOS"

        source_image_size_bytes = self._select_source_image_size_bytes(install_images)

        return BootAssets(
            system_files=files,
            boot_sector_template=template,
            fdos_payload_dir=payload_dir,
            payload_target_dir=payload_target_dir,
            source_image_size_bytes=source_image_size_bytes,
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

    def _select_source_image_size_bytes(self, image_paths: list[Path]) -> int | None:
        preferred = [path for path in image_paths if path.suffix.lower() == ".xdf"]
        ordered = [*preferred, *[path for path in image_paths if path not in preferred]]
        for image in ordered:
            normalized = self._mtools_image_path(image)
            try:
                return normalized.stat().st_size
            except OSError:
                continue
        return None

    def _copy_msdos71_pak_from_images(self, image_paths: list[Path], pak_name: str, destination: Path) -> bool:
        for image_path in image_paths:
            if self._copy_file_from_image_case_insensitive(image_path, pak_name, destination):
                return True
        return False

    def _copy_file_from_image_case_insensitive(self, image_path: Path, dos_name: str, destination: Path) -> bool:
        if destination.exists() and destination.stat().st_size > 0:
            return True
        destination.parent.mkdir(parents=True, exist_ok=True)
        mtools_image = self._mtools_image_path(image_path)
        for candidate in (dos_name, dos_name.upper(), dos_name.lower()):
            if destination.exists():
                destination.unlink()
            result = self.runner.run(
                ["mcopy", "-i", str(mtools_image), f"::{candidate}", str(destination)],
                check=False,
            )
            if result.returncode == 0 and destination.exists() and destination.stat().st_size > 0:
                return True
        return False

    def _mtools_image_path(self, image_path: Path) -> Path:
        if image_path.suffix.lower() != ".dsk":
            return image_path
        return self._convert_savedskf_image(image_path) or image_path

    def _convert_savedskf_image(self, image_path: Path) -> Path | None:
        try:
            header = image_path.read_bytes()[:_SAVE_DSKF_HEADER_MIN]
            stat = image_path.stat()
        except OSError:
            return None
        if len(header) < _SAVE_DSKF_HEADER_MIN or header[:2] != _SAVE_DSKF_SIGNATURE:
            return None

        sector_count = struct.unpack(
            "<H",
            header[_SAVE_DSKF_SECTOR_COUNT_OFFSET : _SAVE_DSKF_SECTOR_COUNT_OFFSET + 2],
        )[0]
        first_sector_offset = struct.unpack(
            "<H",
            header[_SAVE_DSKF_FIRST_SECTOR_OFFSET : _SAVE_DSKF_FIRST_SECTOR_OFFSET + 2],
        )[0]
        if sector_count <= 0 or first_sector_offset <= 0:
            return None
        raw_size = sector_count * 512
        if first_sector_offset + raw_size > stat.st_size:
            return None

        cache_key = self._hash_value(
            f"{image_path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}:{first_sector_offset}:{sector_count}"
        )
        raw_path = self.cache_root / f"savedskf-{cache_key}.img"
        if raw_path.exists() and raw_path.stat().st_size == raw_size:
            return raw_path

        try:
            with image_path.open("rb") as source:
                source.seek(first_sector_offset)
                raw_data = source.read(raw_size)
        except OSError:
            return None
        if len(raw_data) != raw_size:
            return None
        raw_path.write_bytes(raw_data)
        return raw_path

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
        payload_budget_bytes: int | None = None,
        startup_files: dict[str, Path] | None = None,
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
        self._trim_payload_to_core_files(
            payload_dir=destination,
            payload_budget_bytes=payload_budget_bytes,
            startup_files=startup_files,
        )

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

    def _write_msdos_boot_template(
        self,
        destination: Path,
        *,
        disk_format: DiskFormat,
        source_candidates: tuple[Path, ...],
        source_label: str,
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
            f"Unable to derive BOOTSECT_{format_label}.BIN from {source_label}. "
            f"Provide BOOTSECT_{format_label}.BIN manually in the asset directory."
        )

    def _write_msdos71_boot_template(
        self,
        destination: Path,
        *,
        disk_format: DiskFormat,
        source_candidates: tuple[Path, ...],
    ) -> None:
        self._write_msdos_boot_template(
            destination,
            disk_format=disk_format,
            source_candidates=source_candidates,
            source_label="DOS71 install media",
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
        has_type_label = sector[54:62] in (b"FAT16   ", b"FAT12   ")
        if not has_type_label and not self._looks_like_legacy_fat12_16_bpb(sector):
            return False
        if sector[82:90] == b"FAT32   ":
            return False
        if b"IO      SYS" not in sector and b"IBMBIO  COM" not in sector:
            return False
        if b"This is not a bootable disk" in sector:
            return False
        return True

    def _looks_like_msdos_floppy_fat12_boot_sector(self, sector: bytes) -> bool:
        if len(sector) < 512 or sector[510:512] != b"\x55\xaa":
            return False
        if sector[54:62] != b"FAT12   ":
            return False
        return sector[21] in (0xF0, 0xF9, 0xFD, 0xFC, 0xFE)

    def _normalize_legacy_vhd_boot_template(self, *, template: Path, system_files: dict[str, Path]) -> None:
        try:
            template_sector = template.read_bytes()[:512]
        except OSError:
            return
        if not self._looks_like_msdos_floppy_fat12_boot_sector(template_sector):
            return
        # IO.SYS/MSDOS.SYS profiles need HDD-capable DOS boot code on VHD targets.
        if "IO.SYS" in system_files and "MSDOS.SYS" in system_files:
            # Preserve install-image DOS loader sectors when they already target IO.SYS/MSDOS.SYS.
            if b"IO      SYS" in template_sector or b"MSDOS   SYS" in template_sector:
                return
            # FreeDOS-style floppy sectors (KERNEL.SYS loader) are not reliable for legacy HDD boot.
            if b"KERNEL  SYS" in template_sector:
                template.write_bytes(base64.b64decode(_BUILTIN_FAT16_BOOT_SECTOR_B64))

    def _looks_like_legacy_fat12_16_bpb(self, sector: bytes) -> bool:
        bytes_per_sector = struct.unpack("<H", sector[11:13])[0]
        sectors_per_cluster = sector[13]
        reserved_sectors = struct.unpack("<H", sector[14:16])[0]
        fats = sector[16]
        root_entries = struct.unpack("<H", sector[17:19])[0]
        media_descriptor = sector[21]
        sectors_per_fat = struct.unpack("<H", sector[22:24])[0]
        sectors_per_track = struct.unpack("<H", sector[24:26])[0]
        heads = struct.unpack("<H", sector[26:28])[0]

        if bytes_per_sector not in (512, 1024, 2048, 4096):
            return False
        if sectors_per_cluster == 0 or sectors_per_cluster & (sectors_per_cluster - 1):
            return False
        if reserved_sectors == 0:
            return False
        if fats not in (1, 2):
            return False
        if root_entries == 0:
            return False
        if media_descriptor not in _VALID_FAT_MEDIA_DESCRIPTORS:
            return False
        if sectors_per_fat == 0:
            return False
        if sectors_per_track == 0 or heads == 0:
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
        mtools_image = self._mtools_image_path(image_path)
        result = self.runner.run(
            ["mcopy", "-i", str(mtools_image), f"::{dos_name}", str(output_path)],
            check=False,
        )
        if result.returncode == 0 and output_path.exists():
            return output_path
        if required:
            raise ValidationError(
                f"Missing required DOS file {dos_name} in image {image_path}. "
                f"mcopy stderr: {result.stderr.strip()}"
            )
        return None

    def _extract_file_from_images(
        self,
        image_paths: list[Path],
        output_dir: Path,
        dos_name: str,
        *,
        required: bool,
    ) -> Path | None:
        for image_path in image_paths:
            extracted = self._extract_file_from_image(
                image_path,
                output_dir,
                dos_name,
                required=False,
            )
            if extracted is not None and extracted.exists():
                return extracted
        if required:
            names = ", ".join(path.name for path in image_paths)
            raise ValidationError(f"Missing required DOS file {dos_name} in provided install images: {names}")
        return None

    def _extract_file_from_images_with_compression_fallback(
        self,
        image_paths: list[Path],
        output_dir: Path,
        dos_name: str,
        *,
        required: bool,
    ) -> Path | None:
        output_path = output_dir / dos_name
        if output_path.exists() and output_path.stat().st_size > 0:
            return output_path

        extracted = self._extract_file_from_images(
            image_paths,
            output_dir,
            dos_name,
            required=False,
        )
        if extracted is not None:
            return extracted

        compressed_name = compressed_variant_name(dos_name)
        if compressed_name is None:
            if required:
                names = ", ".join(path.name for path in image_paths)
                raise ValidationError(f"Missing required DOS file {dos_name} in provided install images: {names}")
            return None

        compressed_path = self._extract_file_from_images(
            image_paths,
            output_dir,
            compressed_name,
            required=False,
        )
        if compressed_path is None:
            if required:
                names = ", ".join(path.name for path in image_paths)
                raise ValidationError(f"Missing required DOS file {dos_name} in provided install images: {names}")
            return None

        try:
            expanded_bytes = expand_dos_compressed_payload(compressed_path.read_bytes())
        except OSError as exc:
            raise ValidationError(f"Unable to read compressed DOS payload file: {compressed_path}") from exc
        except ValidationError as exc:
            raise ValidationError(f"Unable to expand compressed DOS payload file {compressed_path.name}") from exc

        output_path.write_bytes(expanded_bytes)
        return output_path

    def _extract_msdos_fat16_boot_sector_from_images(self, image_paths: list[Path]) -> bytes | None:
        for image_path in image_paths:
            try:
                normalized = self._mtools_image_path(image_path)
                with normalized.open("rb") as handle:
                    sector = handle.read(512)
            except OSError:
                continue
            if self._looks_like_msdos_fat16_boot_sector(sector):
                return sector
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
        boot_mode: BootMode = BootMode.FREEDOS,
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
            boot_mode=boot_mode,
        )

    def make_floppy_bootable(
        self,
        *,
        image_path: Path,
        assets: BootAssets,
        boot_mode: BootMode,
        floppy_type: FloppyType | None = None,
        verify_legacy_layout: bool = False,
    ) -> None:
        before_sector = self._read_first_sector(image_path)
        self._write_floppy_boot_sector(image_path=image_path, template=assets.boot_sector_template)
        after_sector = self._read_first_sector(image_path)
        self._validate_floppy_bpb_fields_preserved(
            before_sector=before_sector,
            after_sector=after_sector,
            image_path=image_path,
        )
        if floppy_type is not None and isinstance(self.runner, CommandRunner):
            self._validate_floppy_bpb_matches_type(
                image_path=image_path,
                floppy_type=floppy_type,
            )
        self._copy_system_files(
            partition_device=str(image_path),
            system_files=assets.system_files,
            fdos_payload_dir=assets.fdos_payload_dir,
            payload_target_dir=assets.payload_target_dir,
            boot_mode=boot_mode,
        )
        if verify_legacy_layout and isinstance(self.runner, CommandRunner):
            self._validate_legacy_floppy_system_layout(image_path=image_path, boot_mode=boot_mode)

    def _copy_system_files(
        self,
        *,
        partition_device: str,
        system_files: dict[str, Path],
        fdos_payload_dir: Path | None,
        payload_target_dir: str,
        boot_mode: BootMode,
    ) -> None:
        temp_files: list[Path] = []
        system_order = ("IO.SYS", "MSDOS.SYS", "IBMBIO.COM", "IBMDOS.COM", "KERNEL.SYS", "COMMAND.COM")
        system_file_names = {name.upper() for name in system_files}
        msdos_loader_profile = "IO.SYS" in system_file_names and "MSDOS.SYS" in system_file_names
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
                    boot_mode=boot_mode,
                )
                self._mcopy_file(
                    partition_device=partition_device,
                    source_path=prepared_source,
                    destination_name=name,
                )
                if name.upper() in _DOS_SYSTEM_HIDDEN_FILES:
                    self._mark_system_hidden(partition_device=partition_device, destination_name=name)
                self._normalize_command_com_for_msdos_profile(
                    partition_device=partition_device,
                    destination_name=name,
                    msdos_loader_profile=msdos_loader_profile,
                )
                written.add(name)

            for destination_name, source_path in system_files.items():
                if destination_name in written:
                    continue
                prepared_source = self._prepare_source_file(
                    destination_name=destination_name,
                    source_path=source_path,
                    temp_files=temp_files,
                    boot_mode=boot_mode,
                )
                self._mcopy_file(
                    partition_device=partition_device,
                    source_path=prepared_source,
                    destination_name=destination_name,
                )
                self._normalize_command_com_for_msdos_profile(
                    partition_device=partition_device,
                    destination_name=destination_name,
                    msdos_loader_profile=msdos_loader_profile,
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
        # Match real DOS SYS attribute output: ReadOnly + Hidden + System (0x07), Archive cleared.
        self.runner.run(
            ["mattrib", "-i", partition_device, "+r", "+s", "+h", "-a", f"::{destination_name}"],
            sudo=True,
            check=False,
        )

    def _normalize_command_com_for_msdos_profile(
        self,
        *,
        partition_device: str,
        destination_name: str,
        msdos_loader_profile: bool,
    ) -> None:
        if not msdos_loader_profile or destination_name.upper() != "COMMAND.COM":
            return
        # DOS SYS leaves COMMAND.COM as Archive only (0x20). Clear R/S/H carried over from source media.
        self.runner.run(
            ["mattrib", "-i", partition_device, "-r", "-s", "-h", f"::{destination_name}"],
            sudo=True,
            check=False,
        )

    def _prepare_source_file(
        self,
        *,
        destination_name: str,
        source_path: Path,
        temp_files: list[Path],
        boot_mode: BootMode = BootMode.FREEDOS,
    ) -> Path:
        destination_upper = destination_name.upper()
        normalizers = (
            {
                "CONFIG.SYS": normalize_freedos_config_sys,
                "FDCONFIG.SYS": normalize_freedos_config_sys,
                "AUTOEXEC.BAT": normalize_freedos_autoexec_bat,
                "FDAUTO.BAT": normalize_freedos_autoexec_bat,
            }
            if boot_mode is BootMode.FREEDOS
            else {}
        )
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
        if not partition_device.startswith("/dev/"):
            mount_options = f"loop,{mount_options}"
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
            for source in sorted(payload_dir.rglob("*")):
                relative = source.relative_to(payload_dir)
                destination = target_root / relative
                if source.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                else:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    expanded_name = expanded_name_from_compressed(source.name)
                    if expanded_name is None:
                        shutil.copy2(source, destination)
                        continue
                    expanded_destination = destination.with_name(expanded_name)
                    if expanded_destination.exists():
                        continue
                    try:
                        expanded_bytes = expand_dos_compressed_payload(source.read_bytes())
                    except OSError as exc:
                        raise ValidationError(f"Unable to read compressed DOS payload file: {source}") from exc
                    except ValidationError as exc:
                        raise ValidationError(f"Unable to expand compressed DOS payload file {source.name}") from exc
                    expanded_destination.write_bytes(expanded_bytes)
        finally:
            if mounted:
                self.runner.run(["umount", str(mountpoint)], sudo=True, check=False)
            if mountpoint.exists():
                shutil.rmtree(mountpoint)

    def write_mbr_only(self, *, disk_device: str, template: Path | None = None) -> None:
        """Write only the MBR boot code (sector 0 IPL), no VBR or system files.

        Used by boot modes (e.g. compaq331) that produce the partition boot
        sector and system files via an out-of-process step (running the
        emulator's own SYS.COM). The standard MBR boot code chains to the
        partition's VBR, which the QEMU step will write.
        """
        self._write_mbr_boot_code(disk_device=disk_device, template=template)

    def patch_fat16_bpb_geometry(
        self,
        *,
        partition_device: str,
        bios_chs: tuple[int, int],
    ) -> None:
        """Patch BPB heads/spt to match BIOS-canonical geometry.

        Public wrapper around :meth:`_patch_fat16_bpb_geometry`. Used by
        boot modes that produce their boot sector out-of-band (e.g.
        compaq331 via QEMU SYS.COM) but still need a BPB whose heads/spt
        match the VHD footer's geometry so DOS's INT 13h calls land on the
        right sectors.
        """
        self._patch_fat16_bpb_geometry(
            partition_device=partition_device,
            bios_chs=bios_chs,
        )

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
        if disk_format is DiskFormat.FAT16:
            code_offset = self._fat12_16_boot_code_offset(data)
        self.runner.run(
            ["dd", f"if={template}", f"of={partition_device}", "bs=1", "count=3", "conv=notrunc"],
            sudo=True,
        )
        if disk_format is DiskFormat.FAT16 and code_offset == 54:
            # Legacy DOS 3.x style sectors expect OEM/extended header bytes from the source template.
            self._copy_legacy_fat12_16_header(template=template, destination=partition_device)
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

    def _write_floppy_boot_sector(self, *, image_path: Path, template: Path) -> None:
        data = template.read_bytes()
        if len(data) < 512:
            raise ValidationError(f"Boot template must be at least 512 bytes: {template}")
        code_offset = self._fat12_16_boot_code_offset(data)
        self.runner.run(
            ["dd", f"if={template}", f"of={str(image_path)}", "bs=1", "count=3", "conv=notrunc"],
            sudo=True,
        )
        if code_offset == 54:
            # Legacy DOS 3.x style sectors expect OEM/extended header bytes from the source template.
            self._copy_legacy_fat12_16_header(template=template, destination=str(image_path))
        self.runner.run(
            [
                "dd",
                f"if={template}",
                f"of={str(image_path)}",
                "bs=1",
                f"skip={code_offset}",
                f"seek={code_offset}",
                f"count={510 - code_offset}",
                "conv=notrunc",
            ],
            sudo=True,
        )
        self.runner.run(
            [
                "dd",
                f"if={template}",
                f"of={str(image_path)}",
                "bs=1",
                "skip=510",
                "seek=510",
                "count=2",
                "conv=notrunc",
            ],
            sudo=True,
        )

    def _fat12_16_boot_code_offset(self, sector: bytes) -> int:
        return 62 if sector[54:62] in (b"FAT12   ", b"FAT16   ") else 54

    def _copy_legacy_fat12_16_header(self, *, template: Path, destination: str) -> None:
        self.runner.run(
            [
                "dd",
                f"if={template}",
                f"of={destination}",
                "bs=1",
                "skip=3",
                "seek=3",
                "count=8",
                "conv=notrunc",
            ],
            sudo=True,
        )
        self.runner.run(
            [
                "dd",
                f"if={template}",
                f"of={destination}",
                "bs=1",
                "skip=38",
                "seek=38",
                "count=16",
                "conv=notrunc",
            ],
            sudo=True,
        )

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

    def _read_first_sector(self, path: Path) -> bytes:
        data = path.read_bytes()[:512]
        if len(data) < 512:
            raise ValidationError(f"Image is too small to contain a boot sector: {path}")
        return data

    def _fat12_16_bpb_fields(self, sector: bytes) -> dict[str, int]:
        return {
            "bytes_per_sector": struct.unpack("<H", sector[11:13])[0],
            "sectors_per_cluster": sector[13],
            "reserved_sectors": struct.unpack("<H", sector[14:16])[0],
            "fat_count": sector[16],
            "root_entries": struct.unpack("<H", sector[17:19])[0],
            "total_sectors_16": struct.unpack("<H", sector[19:21])[0],
            "media_descriptor": sector[21],
            "sectors_per_fat": struct.unpack("<H", sector[22:24])[0],
            "sectors_per_track": struct.unpack("<H", sector[24:26])[0],
            "heads": struct.unpack("<H", sector[26:28])[0],
            "hidden_sectors": struct.unpack("<I", sector[28:32])[0],
            "total_sectors_32": struct.unpack("<I", sector[32:36])[0],
        }

    def _validate_floppy_bpb_fields_preserved(
        self,
        *,
        before_sector: bytes,
        after_sector: bytes,
        image_path: Path,
    ) -> None:
        before = self._fat12_16_bpb_fields(before_sector)
        after = self._fat12_16_bpb_fields(after_sector)
        tracked_fields = (
            "bytes_per_sector",
            "sectors_per_cluster",
            "reserved_sectors",
            "fat_count",
            "root_entries",
            "total_sectors_16",
            "media_descriptor",
            "sectors_per_fat",
            "sectors_per_track",
            "heads",
            "hidden_sectors",
            "total_sectors_32",
        )
        mismatches = [
            f"{field} changed from {before[field]} to {after[field]}"
            for field in tracked_fields
            if before[field] != after[field]
        ]
        if mismatches:
            raise ValidationError(
                f"Boot sector patch changed floppy BPB geometry for {image_path}: {'; '.join(mismatches)}"
            )

    def _validate_floppy_bpb_matches_type(self, *, image_path: Path, floppy_type: FloppyType) -> None:
        sector = self._read_first_sector(image_path)
        if sector[510:512] != b"\x55\xaa":
            raise ValidationError(f"Floppy boot sector signature is invalid in {image_path}")
        bpb = self._fat12_16_bpb_fields(sector)
        spec = floppy_type.spec
        total_sectors = bpb["total_sectors_16"] or bpb["total_sectors_32"]
        expected_pairs = (
            ("bytes_per_sector", 512, bpb["bytes_per_sector"]),
            ("sectors_per_cluster", spec.sectors_per_cluster, bpb["sectors_per_cluster"]),
            ("reserved_sectors", 1, bpb["reserved_sectors"]),
            ("fat_count", 2, bpb["fat_count"]),
            ("root_entries", spec.root_entries, bpb["root_entries"]),
            ("total_sectors", spec.total_sectors, total_sectors),
            ("media_descriptor", spec.media_descriptor, bpb["media_descriptor"]),
            ("sectors_per_fat", spec.sectors_per_fat, bpb["sectors_per_fat"]),
            ("sectors_per_track", spec.sectors_per_track, bpb["sectors_per_track"]),
            ("heads", spec.heads, bpb["heads"]),
            ("hidden_sectors", 0, bpb["hidden_sectors"]),
        )
        mismatches: list[str] = []
        for field, expected, actual in expected_pairs:
            if expected == actual:
                continue
            if field == "media_descriptor":
                mismatches.append(f"{field} expected 0x{expected:02x} got 0x{actual:02x}")
            else:
                mismatches.append(f"{field} expected {expected} got {actual}")
        if mismatches:
            raise ValidationError(
                f"Floppy BPB metadata mismatch for {image_path} ({floppy_type.value}): {'; '.join(mismatches)}"
            )

    def _validate_legacy_floppy_system_layout(self, *, image_path: Path, boot_mode: BootMode) -> None:
        if boot_mode not in {
            BootMode.MSDOS71,
            BootMode.IBM8088,
            BootMode.MSDOS33,
            BootMode.MSDOS331,
            BootMode.MSDOS5,
            BootMode.MSDOS622,
            BootMode.PCDOS,
            BootMode.PCDOS7,
            BootMode.COMPAQ331,
        }:
            return

        raw = image_path.read_bytes()
        if len(raw) < 512:
            raise ValidationError(f"Floppy image is too small for system-file validation: {image_path}")
        bpb = self._fat12_16_bpb_fields(raw[:512])
        bytes_per_sector = bpb["bytes_per_sector"]
        sectors_per_cluster = bpb["sectors_per_cluster"]
        reserved_sectors = bpb["reserved_sectors"]
        fat_count = bpb["fat_count"]
        root_entries = bpb["root_entries"]
        sectors_per_fat = bpb["sectors_per_fat"]
        if (
            bytes_per_sector <= 0
            or sectors_per_cluster <= 0
            or reserved_sectors <= 0
            or fat_count <= 0
            or root_entries <= 0
            or sectors_per_fat <= 0
        ):
            raise ValidationError(f"Floppy BPB is invalid for system-file validation: {image_path}")

        root_dir_sectors = ((root_entries * 32) + (bytes_per_sector - 1)) // bytes_per_sector
        fat_offset = reserved_sectors * bytes_per_sector
        root_offset = (reserved_sectors + (fat_count * sectors_per_fat)) * bytes_per_sector
        root_end = root_offset + (root_entries * 32)
        fat_end = fat_offset + (sectors_per_fat * bytes_per_sector)
        if root_end > len(raw) or fat_end > len(raw):
            raise ValidationError(f"Floppy layout exceeds image size during system-file validation: {image_path}")

        entries: list[dict[str, int | str | bool]] = []
        for index in range(root_entries):
            offset = root_offset + (index * 32)
            entry = raw[offset : offset + 32]
            if entry[0] == 0x00:
                break
            if entry[0] == 0xE5:
                continue
            attributes = entry[11]
            if attributes == 0x0F:
                continue
            name = f"{entry[0:8].decode('ascii', 'replace').rstrip()}.{entry[8:11].decode('ascii', 'replace').rstrip()}".rstrip(
                "."
            )
            entries.append(
                {
                    "name": name.upper(),
                    "index": index,
                    "cluster": struct.unpack("<H", entry[26:28])[0],
                    "size": struct.unpack("<I", entry[28:32])[0],
                    "is_volume_label": bool(attributes & 0x08),
                }
            )

        by_name = {str(entry["name"]): entry for entry in entries}
        if {"IO.SYS", "MSDOS.SYS"}.issubset(by_name):
            first_name, second_name = ("IO.SYS", "MSDOS.SYS")
        elif {"IBMBIO.COM", "IBMDOS.COM"}.issubset(by_name):
            first_name, second_name = ("IBMBIO.COM", "IBMDOS.COM")
        else:
            raise ValidationError(
                f"Legacy DOS system files are missing from floppy root directory: {image_path}"
            )

        first_entry = by_name[first_name]
        second_entry = by_name[second_name]
        if int(first_entry["index"]) >= int(second_entry["index"]):
            raise ValidationError(
                f"Legacy DOS system-file order is invalid in root directory: {first_name} must appear before {second_name}"
            )

        strict_modes = {
            BootMode.IBM8088,
            BootMode.MSDOS33,
            BootMode.MSDOS331,
            BootMode.MSDOS5,
            BootMode.MSDOS622,
            BootMode.PCDOS,
            BootMode.PCDOS7,
            BootMode.COMPAQ331,
        }
        if boot_mode in strict_modes:
            non_label_entries = [entry for entry in entries if not bool(entry["is_volume_label"])]
            if len(non_label_entries) < 2:
                raise ValidationError(f"Floppy root directory does not contain enough system entries: {image_path}")
            if (
                str(non_label_entries[0]["name"]) != first_name
                or str(non_label_entries[1]["name"]) != second_name
            ):
                raise ValidationError(
                    f"Legacy DOS boot expects first root entries to be {first_name}, {second_name}; found "
                    f"{non_label_entries[0]['name']}, {non_label_entries[1]['name']}"
                )

            cluster_size = sectors_per_cluster * bytes_per_sector
            first_cluster = int(first_entry["cluster"])
            second_cluster = int(second_entry["cluster"])
            first_size = int(first_entry["size"])
            if first_cluster < 2 or second_cluster < 2:
                raise ValidationError(
                    f"Legacy DOS system files were not allocated in data area for {image_path}"
                )
            first_clusters = max(1, (first_size + cluster_size - 1) // cluster_size)
            expected_second_cluster = first_cluster + first_clusters
            if second_cluster != expected_second_cluster:
                raise ValidationError(
                    f"Legacy DOS system files are not contiguous in data area for {image_path}: "
                    f"{second_name} starts at cluster {second_cluster}, expected {expected_second_cluster}"
                )

            fat = raw[fat_offset:fat_end]
            current_cluster = first_cluster
            for _ in range(first_clusters - 1):
                next_cluster = self._fat12_entry(fat, current_cluster)
                expected_next = current_cluster + 1
                if next_cluster != expected_next:
                    raise ValidationError(
                        f"Legacy DOS system file {first_name} is fragmented in FAT chain for {image_path}: "
                        f"cluster {current_cluster} points to {next_cluster}, expected {expected_next}"
                    )
                current_cluster = next_cluster
            terminal = self._fat12_entry(fat, current_cluster)
            if terminal < 0xFF8:
                raise ValidationError(
                    f"Legacy DOS system file {first_name} FAT chain is not properly terminated in {image_path}"
                )

    def _fat12_entry(self, fat: bytes, cluster: int) -> int:
        offset = cluster + (cluster // 2)
        if offset + 1 >= len(fat):
            raise ValidationError(f"FAT12 table is truncated when reading cluster {cluster}")
        if cluster & 1:
            return ((fat[offset] >> 4) | (fat[offset + 1] << 4)) & 0x0FFF
        return (fat[offset] | ((fat[offset + 1] & 0x0F) << 8)) & 0x0FFF
