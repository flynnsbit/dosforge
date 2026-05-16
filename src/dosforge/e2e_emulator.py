from __future__ import annotations

import subprocess
from pathlib import Path

_FAILURE_MARKERS = (
    "This is not a bootable disk",
    "Error loading operating system",
    "Non-System disk or disk error",
    "No bootable device",
    "Missing operating system",
    "Disk I/O error",
)
_SHELL_MARKERS = ("C:\\>", "A:\\>")


def qemu_boot_probe(
    *,
    image_path: Path,
    image_format: str = "vpc",
    timeout_seconds: int = 90,
    expect_shell_prompt: bool = False,
    boot_media: str = "hard_disk",
    diagnostics_dir: Path | None = None,
    case_id: str | None = None,
) -> tuple[bool, str]:
    boot_stage_marker = "Booting from Hard Disk" if boot_media == "hard_disk" else "Booting from Floppy"
    command = [
        "timeout",
        f"{timeout_seconds}s",
        "qemu-system-i386",
        "-machine",
        "pc",
        "-m",
        "64",
        "-nographic",
        "-monitor",
        "none",
        "-no-reboot",
        "-no-shutdown",
    ]
    if boot_media == "floppy":
        command.extend(
            [
                "-boot",
                "a",
                "-drive",
                f"if=floppy,format={image_format},file={image_path}",
            ]
        )
    else:
        command.extend(
            [
                "-boot",
                "c",
                "-drive",
                f"if=ide,format={image_format},file={image_path}",
            ]
        )
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    output = f"{completed.stdout}\n{completed.stderr}"
    output_tail = output[-4000:]
    _write_diagnostics(
        diagnostics_dir=diagnostics_dir,
        case_id=case_id,
        command=command,
        returncode=completed.returncode,
        output=output,
    )

    if any(marker in output for marker in _FAILURE_MARKERS):
        return (
            False,
            "\n".join(
                [
                    "Observed explicit boot failure marker in QEMU output.",
                    f"qemu exit code: {completed.returncode}",
                    f"output tail:\n{output_tail}",
                ]
            ),
        )
    if boot_stage_marker not in output:
        return (
            False,
            "\n".join(
                [
                    f"QEMU did not reach {boot_media.replace('_', ' ')} boot stage.",
                    f"qemu exit code: {completed.returncode}",
                    f"output tail:\n{output_tail}",
                ]
            ),
        )
    if expect_shell_prompt and not any(marker in output for marker in _SHELL_MARKERS):
        return (
            False,
            "\n".join(
                [
                    "Boot reached expected stage but no DOS shell prompt signature was observed.",
                    f"qemu exit code: {completed.returncode}",
                    f"output tail:\n{output_tail}",
                ]
            ),
        )
    return (True, "")


def _write_diagnostics(
    *,
    diagnostics_dir: Path | None,
    case_id: str | None,
    command: list[str],
    returncode: int,
    output: str,
) -> None:
    if diagnostics_dir is None:
        return
    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    base = case_id or "qemu-boot-probe"
    (diagnostics_dir / f"{base}.command.txt").write_text(" ".join(command), encoding="utf-8")
    (diagnostics_dir / f"{base}.returncode.txt").write_text(str(returncode), encoding="ascii")
    (diagnostics_dir / f"{base}.output.log").write_text(output, encoding="utf-8")
