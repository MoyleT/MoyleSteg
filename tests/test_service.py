"""Behavior tests for the Qt-independent desktop service boundary."""

from __future__ import annotations

import os
from pathlib import Path

from PIL import Image
import pytest

from moyle_steg.service import OperationRequest, OperationResult, execute, friendly_error
from png_steg_aes256 import AuthenticationError


def _make_cover(path: Path, size: tuple[int, int] = (256, 192)) -> None:
    image = Image.new("RGBA", size, (28, 95, 122, 255))
    image.save(path, format="PNG")


def _password_request(operation: str, **paths: str) -> OperationRequest:
    return OperationRequest(
        operation=operation,
        credential_mode="password",
        password="correct horse battery staple",
        password_confirm=(
            "correct horse battery staple" if operation in {"hide", "encrypt"} else ""
        ),
        **paths,
    )


def test_request_repr_and_result_never_expose_passwords(tmp_path: Path) -> None:
    request = OperationRequest(
        operation="encrypt",
        input_path=str(tmp_path / "plain.txt"),
        output_path=str(tmp_path / "plain.saes"),
        password="unique-primary-secret",
        password_confirm="unique-confirmation-secret",
    )

    assert "unique-primary-secret" not in repr(request)
    assert "unique-confirmation-secret" not in repr(request)
    assert "password=<hidden>" in repr(request)


def test_password_hide_inspect_and_extract_roundtrip(tmp_path: Path) -> None:
    cover = tmp_path / "cover.png"
    secret = tmp_path / "private.txt"
    hidden = tmp_path / "hidden.png"
    restored = tmp_path / "restored.txt"
    _make_cover(cover)
    payload = ("桌面隐写往返测试\n" * 160).encode("utf-8")
    secret.write_bytes(payload)

    hidden_result = execute(
        _password_request(
            "hide",
            cover_path=str(cover),
            input_path=str(secret),
            output_path=str(hidden),
        )
    )
    inspected = execute(
        _password_request("inspect", input_path=str(hidden))
    )
    extracted = execute(
        _password_request(
            "extract", input_path=str(hidden), output_path=str(restored)
        )
    )

    assert hidden_result == OperationResult(
        operation="hide",
        output_path=str(hidden),
        title="hide_success",
        details=hidden_result.details,
        input_path=str(secret),
        completed_at=hidden_result.completed_at,
    )
    assert hidden_result.details["filename"] == "private.txt"
    assert hidden_result.details["original_size"] == str(len(payload))
    assert hidden_result.details["compressed"] in {"yes", "no"}
    assert hidden_result.details["credential_mode"] == "password"
    assert hidden_result.details["algorithm"] == "AES-256-GCM"
    assert {"width", "height", "capacity", "fill_ratio", "sha256"} <= set(
        hidden_result.details
    )
    assert inspected.operation == "inspect"
    assert inspected.title == "inspect_success"
    assert inspected.output_path == ""
    assert inspected.details["filename"] == "private.txt"
    assert extracted.title == "extract_success"
    assert extracted.output_path == str(restored)
    assert restored.read_bytes() == payload
    assert all(isinstance(value, str) for value in extracted.details.values())


def test_key_file_keygen_encrypt_decrypt_and_capacity(tmp_path: Path) -> None:
    key_path = tmp_path / "vault.stegkey"
    source = tmp_path / "report.bin"
    encrypted = tmp_path / "report.saes"
    restored = tmp_path / "report-restored.bin"
    cover = tmp_path / "cover.png"
    source_bytes = os.urandom(2048) + b"compress me" * 250
    source.write_bytes(source_bytes)
    _make_cover(cover, (80, 60))

    key_result = execute(
        OperationRequest(operation="keygen", output_path=str(key_path))
    )
    encrypted_result = execute(
        OperationRequest(
            operation="encrypt",
            input_path=str(source),
            output_path=str(encrypted),
            credential_mode="key_file",
            key_path=str(key_path),
            password="ignored-secret",
            password_confirm="does-not-match",
        )
    )
    decrypted_result = execute(
        OperationRequest(
            operation="decrypt",
            input_path=str(encrypted),
            output_path=str(restored),
            credential_mode="key_file",
            key_path=str(key_path),
        )
    )
    capacity_result = execute(
        OperationRequest(operation="capacity", cover_path=str(cover))
    )

    assert key_result.title == "keygen_success"
    assert key_result.output_path == str(key_path)
    assert "PNG-STEG-AES256-KEY-V1" not in repr(key_result)
    assert encrypted_result.details["credential_mode"] == "key_file"
    assert encrypted_result.details["filename"] == "report.bin"
    assert decrypted_result.details["credential_mode"] == "key_file"
    assert restored.read_bytes() == source_bytes
    assert capacity_result == OperationResult(
        operation="capacity",
        title="capacity_success",
        details={
            "width": "80",
            "height": "60",
            "capacity": "1746",
            "algorithm": "RGB 1-LSB",
        },
        input_path=str(cover),
        completed_at=capacity_result.completed_at,
    )


@pytest.mark.parametrize("operation", ["hide", "extract", "encrypt", "decrypt"])
def test_output_may_never_collide_with_key_even_with_force(
    tmp_path: Path, operation: str
) -> None:
    key_path = tmp_path / "shared.stegkey"
    key_path.write_text(
        "PNG-STEG-AES256-KEY-V1\nMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=\n",
        encoding="ascii",
    )
    source = tmp_path / "source.bin"
    source.write_bytes(b"existing input")
    cover = tmp_path / "cover.png"
    _make_cover(cover)
    request = OperationRequest(
        operation=operation,
        input_path=str(source),
        output_path=str(key_path),
        cover_path=str(cover),
        credential_mode="key_file",
        key_path=str(key_path),
        force=True,
    )
    original_key = key_path.read_bytes()

    with pytest.raises(ValueError, match="密钥"):
        execute(request)

    assert key_path.read_bytes() == original_key


@pytest.mark.parametrize("operation", ["hide", "encrypt"])
def test_password_writes_require_matching_confirmation(
    tmp_path: Path, operation: str
) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"source")
    cover = tmp_path / "cover.png"
    _make_cover(cover)
    output = tmp_path / ("out.png" if operation == "hide" else "out.saes")

    with pytest.raises(ValueError, match="不一致"):
        execute(
            OperationRequest(
                operation=operation,
                input_path=str(source),
                output_path=str(output),
                cover_path=str(cover),
                password="first secret",
                password_confirm="second secret",
            )
        )

    assert not output.exists()


def test_missing_input_and_relative_or_implicit_outputs_fail_before_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    missing = tmp_path / "missing.bin"

    with pytest.raises(FileNotFoundError):
        execute(
            _password_request(
                "encrypt",
                input_path=str(missing),
                output_path=str(tmp_path / "never.saes"),
            )
        )
    with pytest.raises(ValueError, match="绝对"):
        execute(
            _password_request(
                "encrypt", input_path=str(missing), output_path="relative.saes"
            )
        )
    with pytest.raises(ValueError, match="明确"):
        execute(_password_request("decrypt", input_path=str(missing)))

    assert not (tmp_path / "never.saes").exists()
    assert not (tmp_path / "relative.saes").exists()


def test_existing_output_is_not_overwritten_by_default(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    output = tmp_path / "existing.saes"
    source.write_text("source", encoding="utf-8")
    output.write_bytes(b"keep this")

    with pytest.raises(FileExistsError):
        execute(
            _password_request(
                "encrypt", input_path=str(source), output_path=str(output)
            )
        )

    assert output.read_bytes() == b"keep this"


def test_wrong_password_never_creates_recovered_output(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    encrypted = tmp_path / "source.saes"
    output = tmp_path / "never.txt"
    source.write_text("authenticated data" * 100, encoding="utf-8")
    execute(
        _password_request(
            "encrypt", input_path=str(source), output_path=str(encrypted)
        )
    )

    with pytest.raises(AuthenticationError):
        execute(
            OperationRequest(
                operation="decrypt",
                input_path=str(encrypted),
                output_path=str(output),
                password="wrong password",
            )
        )

    assert not output.exists()


@pytest.mark.parametrize(
    ("error", "language", "expected", "forbidden"),
    [
        (FileNotFoundError("secret phrase"), "zh_CN", "文件", "secret phrase"),
        (AuthenticationError("认证失败"), "en_US", "Authentication failed", "认证"),
        (ValueError("两次输入的口令不一致"), "en_US", "do not match", "口令"),
    ],
)
def test_friendly_error_is_localized_and_does_not_echo_sensitive_exception_text(
    error: Exception, language: str, expected: str, forbidden: str
) -> None:
    message = friendly_error(error, language)

    assert expected in message
    assert forbidden not in message
