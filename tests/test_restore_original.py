"""Restore authenticated original filenames without an implicit working directory."""

from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from unittest.mock import Mock

from PIL import Image
import pytest

from moyle_steg import service
from moyle_steg.service import OperationRequest, execute, friendly_error
from png_steg_aes256 import AuthenticationError, DecodedPayload, MODE_PASSWORD


def make_container(tmp_path, operation, mode="password", filename="原始资料.中文后缀"):
    source = tmp_path / filename
    source.write_bytes("原文件内容\n".encode("utf-8") * 30)
    key = tmp_path / "key.stegkey"
    execute(OperationRequest(operation="keygen", output_path=str(key)))
    credentials = dict(credential_mode=mode, key_path=str(key),
                       password="test password", password_confirm="test password")
    container = tmp_path / ("container.png" if operation == "extract" else "container.saes")
    if operation == "extract":
        cover = tmp_path / "cover.png"
        Image.new("RGB", (100, 100), "#417b66").save(cover)
        execute(OperationRequest(operation="hide", input_path=str(source),
                                 cover_path=str(cover), output_path=str(container), **credentials))
    else:
        execute(OperationRequest(operation="encrypt", input_path=str(source),
                                 output_path=str(container), **credentials))
    request = OperationRequest(operation=operation, input_path=str(container),
                               output_directory=str(tmp_path / "恢复目录"), **credentials)
    return source, request


def fake_decoded(filename):
    data = b"authenticated plaintext"
    return DecodedPayload(filename=filename, data=data, original_size=len(data),
                          stored_size=len(data), compressed=False,
                          sha256_hex=sha256(data).hexdigest(), credential_mode=MODE_PASSWORD)


def patch_decoder(monkeypatch, operation, filename):
    decoder = Mock(return_value=fake_decoded(filename))
    monkeypatch.setattr(service, "decode_image" if operation == "extract" else "decode_encrypted_file", decoder)
    return decoder


@pytest.mark.parametrize("operation", ["extract", "decrypt"])
@pytest.mark.parametrize("mode", ["password", "key_file"])
@pytest.mark.parametrize("filename", ["主旋律.mid", "资料.中文后缀"])
def test_restore_original_filename_and_extension(tmp_path, operation, mode, filename):
    source, request = make_container(tmp_path, operation, mode, filename)
    result = execute(request)
    target = Path(request.output_directory) / filename
    assert result.output_path == str(target)
    assert target.read_bytes() == source.read_bytes()
    assert result.details["filename"] == filename
    assert result.details["sha256"] == sha256(source.read_bytes()).hexdigest()


@pytest.mark.parametrize("operation", ["extract", "decrypt"])
@pytest.mark.parametrize("mode", ["password", "key_file"])
def test_wrong_credential_never_creates_output_directory(tmp_path, operation, mode):
    _, request = make_container(tmp_path, operation, mode)
    if mode == "password":
        request.password = "wrong password"
    else:
        wrong_key = tmp_path / "wrong.stegkey"
        execute(OperationRequest(operation="keygen", output_path=str(wrong_key)))
        request.key_path = str(wrong_key)
    with pytest.raises(AuthenticationError):
        execute(request)
    assert not Path(request.output_directory).exists()


@pytest.mark.parametrize("operation", ["extract", "decrypt"])
def test_existing_original_name_is_protected_unless_force(tmp_path, operation):
    source, request = make_container(tmp_path, operation)
    directory = Path(request.output_directory)
    directory.mkdir()
    target = directory / source.name
    target.write_bytes(b"existing output")
    with pytest.raises(FileExistsError):
        execute(request)
    assert target.read_bytes() == b"existing output"
    execute(replace(request, force=True))
    assert target.read_bytes() == source.read_bytes()


@pytest.mark.parametrize("operation", ["extract", "decrypt"])
@pytest.mark.parametrize("protected_field", ["input_path", "cover_path", "key_path"])
@pytest.mark.parametrize("force", [False, True])
def test_original_name_cannot_overwrite_protected_files(tmp_path, monkeypatch, operation, protected_field, force):
    source = tmp_path / "container.bin"
    source.write_bytes(b"original container")
    protected = source if protected_field == "input_path" else tmp_path / (protected_field + ".bin")
    if protected != source:
        protected.write_bytes(b"protected original")
    decoder = patch_decoder(monkeypatch, operation, protected.name)
    kwargs = dict(input_path=str(source), output_directory=str(tmp_path),
                  password="test password", force=force)
    kwargs[protected_field] = str(protected)
    before = protected.read_bytes()
    with pytest.raises(ValueError) as error:
        execute(OperationRequest(operation=operation, **kwargs))
    assert error.value.code == "output_collision"
    assert protected.read_bytes() == before
    decoder.assert_called_once()


@pytest.mark.parametrize("filename", [
    "", ".", "..", "../outside.txt", "..\\outside.txt", "/root.txt", "C:relative.txt",
    "C:\\absolute.txt", "file.txt:stream", "dir/file.txt", "dir\\file.txt",
    "NUL", "con.txt", "COM1.log", "LPT9", "COM¹.txt", "LPT².log", "aux .txt",
    "CONIN$", "CONOUT$", "file.", "file ", "file?.txt", "file*.txt", "file|.txt",
    'file".txt', "file<.txt", "file>.txt", "file\x00.txt", "file\x1f.txt",
])
@pytest.mark.parametrize("operation", ["extract", "decrypt"])
def test_unsafe_authenticated_filename_never_creates_directory(tmp_path, monkeypatch, filename, operation):
    source = tmp_path / "container.bin"
    source.write_bytes(b"container")
    decoder = patch_decoder(monkeypatch, operation, filename)
    directory = tmp_path / "not-created"
    with pytest.raises(ValueError) as error:
        execute(OperationRequest(operation=operation, input_path=str(source),
                                 output_directory=str(directory), password="test"))
    assert error.value.code == "restore_filename_unsafe"
    assert not directory.exists()
    assert "原文件名" in friendly_error(error.value)
    assert "filename" in friendly_error(error.value, "en_US")
    decoder.assert_called_once()


@pytest.mark.parametrize("case,code", [
    ("relative", "output_directory_absolute"),
    ("both", "output_destination_conflict"),
    ("file", "output_directory_invalid"),
    ("operation", "output_directory_operation"),
])
def test_invalid_directory_destination_rejected_before_decode(tmp_path, monkeypatch, case, code):
    source = tmp_path / "container.bin"
    source.write_bytes(b"container")
    decoder = patch_decoder(monkeypatch, "decrypt", "original.txt")
    request = OperationRequest(operation="decrypt", input_path=str(source),
                               output_directory=str(tmp_path / "new"), password="test")
    if case == "relative":
        request.output_directory = "relative-folder"
    elif case == "both":
        request.output_path = str(tmp_path / "explicit.txt")
    elif case == "file":
        request.output_directory = str(source)
    else:
        request.operation = "inspect"
    with pytest.raises(ValueError) as error:
        execute(request)
    assert error.value.code == code
    assert friendly_error(error.value, "en_US") != friendly_error(error.value)
    decoder.assert_not_called()
    assert not (tmp_path / "new").exists()


@pytest.mark.parametrize("operation", ["extract", "decrypt"])
def test_directory_restore_decodes_once(tmp_path, monkeypatch, operation):
    source = tmp_path / "container.bin"
    source.write_bytes(b"container")
    decoder = patch_decoder(monkeypatch, operation, "original.pdf")
    directory = tmp_path / "new" / "nested"
    result = execute(OperationRequest(operation=operation, input_path=str(source),
                                     output_directory=str(directory), password="test"))
    decoder.assert_called_once()
    assert Path(result.output_path).read_bytes() == fake_decoded("original.pdf").data


def test_resolved_destination_must_remain_inside_directory(tmp_path, monkeypatch):
    source = tmp_path / "container.bin"
    source.write_bytes(b"container")
    patch_decoder(monkeypatch, "decrypt", "original.pdf")
    directory = tmp_path / "new"
    escaped = tmp_path / "outside" / "original.pdf"
    real_resolve = Path.resolve

    def resolve(path, *args, **kwargs):
        if path == directory / "original.pdf":
            return escaped
        return real_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve)
    with pytest.raises(ValueError) as error:
        execute(OperationRequest(operation="decrypt", input_path=str(source),
                                 output_directory=str(directory), password="test", force=True))
    assert error.value.code == "restore_destination_escape"
    assert not directory.exists()
    assert not escaped.exists()
