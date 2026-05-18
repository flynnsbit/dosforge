from __future__ import annotations

import pytest

import dosforge.cli as cli
from dosforge.commands import RunResult
from dosforge.errors import ValidationError
from dosforge.models import BootMode, FloppyType, IBMDOSVersion, MSDOSInstallProfile, MediaType


def test_main_tui_primes_sudo_before_running_app(monkeypatch) -> None:
    calls = {"auth": 0, "run": 0}

    def fake_auth() -> None:
        calls["auth"] += 1

    class FakeApp:
        def run(self) -> None:
            calls["run"] += 1

    monkeypatch.setattr(cli, "ensure_startup_sudo_auth", fake_auth)
    monkeypatch.setattr(cli, "DosForgeApp", FakeApp)

    assert cli.main(["tui"]) == 0
    assert calls == {"auth": 1, "run": 1}


def test_main_tui_returns_error_when_sudo_auth_fails(monkeypatch, capsys) -> None:
    def fail_auth() -> None:
        raise ValidationError("sudo auth failed")

    monkeypatch.setattr(cli, "ensure_startup_sudo_auth", fail_auth)

    assert cli.main(["tui"]) == 1
    captured = capsys.readouterr()
    assert "sudo auth failed" in captured.err


def test_sudo_check_exit_code_and_output(monkeypatch, capsys) -> None:
    class FakeManager:
        def privilege_diagnostics_summary(self) -> tuple[bool, str]:
            return (False, "Privilege diagnostics found blocking issues.")

    monkeypatch.setattr(cli, "DiskManager", lambda: FakeManager())

    assert cli.main(["sudo-check"]) == 1
    captured = capsys.readouterr()
    assert "blocking issues" in captured.out


def test_ensure_startup_sudo_auth_rejects_missing_noninteractive_session(monkeypatch) -> None:
    class Result:
        returncode = 0

    class FakeRunner:
        def run(self, command, *, sudo=False, check=True, cwd=None, env=None):
            del command, sudo, check, cwd, env
            return RunResult(command=("true",), returncode=1, stdout="", stderr="sudo: a password is required")

    class FakeBackend:
        requires_sudo_for_disk_ops = True

    monkeypatch.setattr(cli.subprocess, "run", lambda *args, **kwargs: Result())
    monkeypatch.setattr("dosforge._platform.get_backend", lambda: FakeBackend())

    with pytest.raises(ValidationError, match="non-interactive sudo is not available"):
        cli.ensure_startup_sudo_auth(runner=FakeRunner())


def test_ensure_startup_sudo_auth_is_noop_when_backend_says_no_sudo(monkeypatch) -> None:
    """On Windows (and any backend without sudo) the startup probe must skip."""

    class FakeBackend:
        requires_sudo_for_disk_ops = False

    def fail_if_called(*args, **kwargs):
        raise AssertionError("subprocess.run must not be called when sudo is not required")

    monkeypatch.setattr(cli.subprocess, "run", fail_if_called)
    monkeypatch.setattr("dosforge._platform.get_backend", lambda: FakeBackend())

    # Should return None without raising.
    cli.ensure_startup_sudo_auth()


def test_create_parses_ibm_dos_version(monkeypatch, capsys) -> None:
    captured: dict[str, object] = {}

    class FakeManager:
        def create_and_prepare(self, request) -> None:
            captured["request"] = request

    monkeypatch.setattr(cli, "DiskManager", lambda: FakeManager())

    result = cli.main(
        [
            "create",
            "--path",
            "/tmp/ibm.vhd",
            "--size",
            "32M",
            "--format",
            "fat16",
            "--boot-mode",
            "ibm8088",
            "--boot-assets-path",
            "/tmp/ibm-assets",
            "--ibm-dos-version",
            "dos50",
        ]
    )
    assert result == 0
    assert captured["request"].ibm_dos_version is IBMDOSVersion.DOS50
    output = capsys.readouterr().out
    assert "Created and prepared" in output


def test_create_img_parses_floppy_options(monkeypatch, capsys) -> None:
    captured: dict[str, object] = {}

    class FakeManager:
        def create_and_prepare(self, request) -> None:
            captured["request"] = request

    monkeypatch.setattr(cli, "DiskManager", lambda: FakeManager())

    result = cli.main(
        [
            "create",
            "--path",
            "/tmp/boot.img",
            "--media-type",
            "img",
            "--floppy-type",
            "720k",
            "--img-system-format",
            "--boot-mode",
            "pcdos",
            "--boot-assets-path",
            "/tmp/pcdos",
        ]
    )
    assert result == 0
    request = captured["request"]
    assert request.media_type is MediaType.IMG
    assert request.disk_format.value == "fat16"
    assert request.floppy_type is FloppyType.F720K
    assert request.img_system_format is True
    assert request.size_bytes == FloppyType.F720K.size_bytes
    output = capsys.readouterr().out
    assert "Created and prepared" in output


def test_create_vhd_allows_missing_size_with_custom_payload(monkeypatch, capsys) -> None:
    captured: dict[str, object] = {}

    class FakeManager:
        def create_and_prepare(self, request) -> None:
            captured["request"] = request

    monkeypatch.setattr(cli, "DiskManager", lambda: FakeManager())

    result = cli.main(
        [
            "create",
            "--path",
            "/tmp/custom.vhd",
            "--format",
            "fat16",
            "--custom-payload-path",
            "/tmp/payload",
        ]
    )
    assert result == 0
    request = captured["request"]
    assert request.size_bytes == 1
    assert request.custom_payload_path.as_posix() == "/tmp/payload"
    assert "Created and prepared" in capsys.readouterr().out


def test_create_img_parses_2880k_floppy_option(monkeypatch, capsys) -> None:
    captured: dict[str, object] = {}

    class FakeManager:
        def create_and_prepare(self, request) -> None:
            captured["request"] = request

    monkeypatch.setattr(cli, "DiskManager", lambda: FakeManager())

    result = cli.main(
        [
            "create",
            "--path",
            "/tmp/ed.img",
            "--media-type",
            "img",
            "--floppy-type",
            "2880k",
        ]
    )
    assert result == 0
    request = captured["request"]
    assert request.media_type is MediaType.IMG
    assert request.floppy_type is FloppyType.F2880K
    assert request.size_bytes == FloppyType.F2880K.size_bytes
    output = capsys.readouterr().out
    assert "Created and prepared" in output


def test_create_img_parses_pcdos7_xdf_floppy_option(monkeypatch, capsys) -> None:
    captured: dict[str, object] = {}

    class FakeManager:
        def create_and_prepare(self, request) -> None:
            captured["request"] = request

    monkeypatch.setattr(cli, "DiskManager", lambda: FakeManager())

    result = cli.main(
        [
            "create",
            "--path",
            "/tmp/pcdos7.img",
            "--media-type",
            "img",
            "--floppy-type",
            "1840k",
            "--img-system-format",
            "--boot-mode",
            "pcdos7",
            "--boot-assets-path",
            "/tmp/pcdos7",
        ]
    )
    assert result == 0
    request = captured["request"]
    assert request.media_type is MediaType.IMG
    assert request.floppy_type is FloppyType.F1840K
    assert request.img_system_format is True
    assert request.boot_mode is BootMode.PCDOS7
    assert request.size_bytes == FloppyType.F1840K.size_bytes
    output = capsys.readouterr().out
    assert "Created and prepared" in output


def test_create_parses_dos_install_profile_for_legacy_mode(monkeypatch, capsys) -> None:
    captured: dict[str, object] = {}

    class FakeManager:
        def create_and_prepare(self, request) -> None:
            captured["request"] = request

    monkeypatch.setattr(cli, "DiskManager", lambda: FakeManager())

    result = cli.main(
        [
            "create",
            "--path",
            "/tmp/dosfull.vhd",
            "--size",
            "128M",
            "--format",
            "fat16",
            "--boot-mode",
            "pcdos7",
            "--boot-assets-path",
            "/tmp/pcdos7",
            "--dos-install-profile",
            "full",
        ]
    )
    assert result == 0
    request = captured["request"]
    assert request.boot_mode is BootMode.PCDOS7
    assert request.msdos_install_profile is MSDOSInstallProfile.FULL
    assert "Created and prepared" in capsys.readouterr().out


def test_check_deps_passes_media_type(monkeypatch, capsys) -> None:
    captured: dict[str, object] = {}

    def fake_assert_dependencies(*, media_type, boot_mode, freedos_source) -> None:
        captured["media_type"] = media_type
        captured["boot_mode"] = boot_mode
        captured["freedos_source"] = freedos_source

    monkeypatch.setattr(cli, "assert_dependencies", fake_assert_dependencies)
    assert cli.main(["check-deps", "--media-type", "img", "--boot-mode", "none"]) == 0
    assert captured["media_type"] is MediaType.IMG
    assert "All required dependencies are available." in capsys.readouterr().out
