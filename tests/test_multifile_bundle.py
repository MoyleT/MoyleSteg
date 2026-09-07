"""Synthetic managed ZIP profile and hostile-input regression checks."""
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import struct
import zipfile
import zlib
from dataclasses import replace

import pytest

import moyle_bundle
from moyle_bundle import BundleSource, create_bundle, inspect_bundle, extract_entry
from png_steg_aes256 import InputChangedError, OperationCancelled, OperationControl, StegError


LIMITS = dict(max_total_bytes=8 * 1024 * 1024, max_archive_bytes=9 * 1024 * 1024)


def test_kotlin_bundle_fixture_restores_identical_original_members(tmp_path):
    fixtures = Path(__file__).parent / "fixtures" / "bundle"
    expected = json.loads((fixtures / "kotlin-expected.json").read_text(encoding="utf-8"))
    path = fixtures / "kotlin-bundle.zip"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == expected["sha256"]
    info = inspect_bundle(path, **LIMITS)
    assert [entry.__dict__ for entry in info.entries] == expected["entries"]
    assert info.total_bytes == expected["total_bytes"]
    for entry in info.entries:
        restored = extract_entry(path, entry, tmp_path, **LIMITS)
        assert restored.stat().st_size == entry.size
        assert hashlib.sha256(restored.read_bytes()).hexdigest() == entry.sha256


def sources(tmp_path):
    values = [("report.txt", b"hello"), ("report.txt", b"different"), ("草莓.txt", b""), ("random.bin", bytes(range(256)))]
    result = []
    for i, (name, content) in enumerate(values):
        path = tmp_path / f"input-{i}"
        path.write_bytes(content)
        result.append(BundleSource(path, name))
    return result, values


def test_create_inspect_extract_duplicate_unicode_empty(tmp_path):
    inputs, values = sources(tmp_path)
    output = tmp_path / "bundle.zip"
    info = create_bundle(inputs, output, **LIMITS)
    assert inspect_bundle(output, **LIMITS) == info
    assert info.total_bytes == sum(len(data) for _, data in values)
    assert info.archive_bytes == output.stat().st_size
    with zipfile.ZipFile(output) as archive:
        assert archive.comment == b"MOYLESTEG-BUNDLE-V1"
        assert all(entry.flag_bits & 0x800 for entry in archive.infolist())
        assert archive.namelist() == [f"{i:04d}/{name}" for i, (name, _) in enumerate(values, 1)]
    for entry, (name, content) in zip(info.entries, values):
        assert entry.name == name
        assert entry.sha256 == hashlib.sha256(content).hexdigest()
        restored = extract_entry(output, entry, tmp_path, **LIMITS)
        assert restored.read_bytes() == content


def test_ordinary_zip_is_not_automatically_unpacked(tmp_path):
    output = tmp_path / "ordinary.zip"
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("normal.txt", b"hello")
    assert inspect_bundle(output, **LIMITS) is None


def test_ordinary_zip_comment_ending_in_marker_is_not_opted_in(tmp_path):
    output = tmp_path / "ordinary-note.zip"
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("normal.txt", b"hello")
        archive.comment = b"This is an ordinary user archive. " + moyle_bundle.COMMENT
    assert inspect_bundle(output, **LIMITS) is None


def test_damaged_managed_footer_is_rejected(tmp_path):
    output = managed(tmp_path)
    data = bytearray(output.read_bytes())
    _, footer = positions(data)
    data[footer] ^= 1
    output.write_bytes(data)
    with pytest.raises(StegError):
        inspect_bundle(output, **LIMITS)


def test_non_zip_file_ending_in_marker_is_not_opted_in(tmp_path):
    output = tmp_path / "ordinary.txt"
    output.write_bytes(b"An ordinary text file mentioning " + moyle_bundle.COMMENT)
    assert inspect_bundle(output, **LIMITS) is None


def test_existing_output_is_never_overwritten(tmp_path):
    inputs, _ = sources(tmp_path)
    output = tmp_path / "existing.zip"
    output.write_bytes(b"keep me")
    with pytest.raises((StegError, FileExistsError)):
        create_bundle(inputs, output, **LIMITS)
    assert output.read_bytes() == b"keep me"


def test_competing_output_created_after_preflight_is_not_overwritten(tmp_path, monkeypatch):
    inputs, _ = sources(tmp_path)
    target = tmp_path / "race.zip"
    original_open = Path.open
    def raced_open(path, mode="r", *args, **kwargs):
        if path == target and mode == "xb":
            with original_open(path, "wb") as competing:
                competing.write(b"other instance owns this output")
        return original_open(path, mode, *args, **kwargs)
    monkeypatch.setattr(Path, "open", raced_open)
    with pytest.raises(FileExistsError):
        create_bundle(inputs, target, **LIMITS)
    assert target.read_bytes() == b"other instance owns this output"


def test_total_limit_is_enforced_before_output_write(tmp_path):
    inputs, _ = sources(tmp_path)
    output = tmp_path / "denied.zip"
    with pytest.raises(StegError):
        create_bundle(inputs, output, max_total_bytes=1, max_archive_bytes=10000)
    assert not output.exists()


def managed(tmp_path, entries=(("0001/a.txt", b"hello"),), *, method=zipfile.ZIP_DEFLATED,
            descriptor=False):
    class NonSeeking(io.BytesIO):
        def seekable(self):
            return False
        def seek(self, *args):
            raise io.UnsupportedOperation()
    buffer = NonSeeking() if descriptor else io.BytesIO()
    with zipfile.ZipFile(buffer, "w", allowZip64=False) as archive:
        archive.comment = moyle_bundle.COMMENT
        for name, data in entries:
            info = moyle_bundle._UTF8Info(name)
            info.compress_type = method
            info.external_attr = (stat.S_IFREG | 0o600) << 16
            archive.writestr(info, data)
    path = tmp_path / "managed.zip"
    path.write_bytes(buffer.getvalue())
    return path


def positions(data):
    footer = len(data) - 22 - len(moyle_bundle.COMMENT)
    central = struct.unpack_from("<I", data, footer + 16)[0]
    return central, footer


@pytest.mark.parametrize("method", [zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED])
@pytest.mark.parametrize("descriptor", [False, True])
def test_supported_methods_and_descriptor_forms(tmp_path, method, descriptor):
    path = managed(tmp_path, method=method, descriptor=descriptor)
    result = inspect_bundle(path, **LIMITS)
    assert result.entries[0].sha256 == hashlib.sha256(b"hello").hexdigest()
    assert result.entries[0].size == 5


def test_unsigned_descriptor_is_supported(tmp_path):
    path = managed(tmp_path, descriptor=True)
    data = bytearray(path.read_bytes())
    central, footer = positions(data)
    assert data[central - 16:central - 12] == b"PK\x07\x08"
    del data[central - 16:central - 12]
    struct.pack_into("<I", data, footer - 4 + 16, central - 4)
    path.write_bytes(data)
    assert inspect_bundle(path, **LIMITS).total_bytes == 5


def test_unsigned_descriptor_crc_can_equal_optional_signature(tmp_path):
    # Solve the 32-bit linear CRC transform for a four-byte synthetic payload.
    baseline, basis = zlib.crc32(b"\0" * 4), {}
    for bit in range(32):
        value = zlib.crc32((1 << bit).to_bytes(4, "little")) ^ baseline
        mask = 1 << bit
        while value:
            pivot = value.bit_length() - 1
            if pivot not in basis:
                basis[pivot] = (value, mask)
                break
            value ^= basis[pivot][0]
            mask ^= basis[pivot][1]
    value, solution = 0x08074b50 ^ baseline, 0
    while value:
        vector, mask = basis[value.bit_length() - 1]
        value ^= vector
        solution ^= mask
    payload = solution.to_bytes(4, "little")
    assert zlib.crc32(payload) == 0x08074b50
    path = managed(tmp_path, (("0001/a.txt", payload),), descriptor=True)
    data = bytearray(path.read_bytes())
    central, footer = positions(data)
    del data[central - 16:central - 12]
    struct.pack_into("<I", data, footer - 4 + 16, central - 4)
    path.write_bytes(data)
    assert inspect_bundle(path, **LIMITS).entries[0].sha256 == hashlib.sha256(payload).hexdigest()


@pytest.mark.parametrize("name", ["../bad", "/bad", "a/b", "a\\b", "C:relative.txt", "file.txt:stream", "CON.txt", "NUL", "a.", "a ", "", "x" * 181, "草" * 61, "bad\x00name", ".", ".."])
def test_invalid_source_names_before_output_write(tmp_path, name):
    source = tmp_path / "input"
    source.write_bytes(b"safe")
    target = tmp_path / "output.zip"
    with pytest.raises(StegError):
        create_bundle([BundleSource(source, name)], target, **LIMITS)
    assert not target.exists()
    assert source.read_bytes() == b"safe"


@pytest.mark.parametrize("name", ["0001/../bad", "0001/C:bad", "0001/CON.txt", "0001/sub/a", "0002/a.txt", "0001/a/", "0001/", "0001/" + "a" * 181])
def test_invalid_authenticated_names_are_rejected(tmp_path, name):
    path = managed(tmp_path, ((name, b"hello"),))
    with pytest.raises(StegError):
        inspect_bundle(path, **LIMITS)


@pytest.mark.parametrize("where,offset,format,value", [
    ("footer", 4, "H", 1), ("footer", 6, "H", 1), ("footer", 8, "H", 2),
    ("footer", 10, "H", 0), ("footer", 10, "H", 101),
    ("footer", 12, "I", 128 * 1024 + 1), ("footer", 16, "I", 0xffffffff),
    ("central", 6, "H", 45), ("central", 6, "H", 9), ("central", 8, "H", 0),
    ("central", 8, "H", 0x801), ("central", 10, "H", 12),
    ("central", 20, "I", 0xffffffff), ("central", 24, "I", 0xffffffff),
    ("central", 30, "H", 1), ("central", 32, "H", 1),
    ("central", 34, "H", 1), ("central", 42, "I", 1),
    ("central", 38, "I", (stat.S_IFLNK | 0o777) << 16),
    ("central", 38, "I", (stat.S_IFCHR | 0o600) << 16),
    ("central", 38, "I", 0x10), ("central", 38, "I", 0x08),
    ("local", 6, "H", 0), ("local", 28, "H", 1),
    ("local", 22, "I", 12345),
])
def test_malformed_metadata_rejected_before_payload_read(tmp_path, monkeypatch, where, offset, format, value):
    path = managed(tmp_path)
    data = bytearray(path.read_bytes())
    central, footer = positions(data)
    base = {"central": central, "footer": footer, "local": 0}[where]
    struct.pack_into("<" + format, data, base + offset, value)
    path.write_bytes(data)
    def forbidden(*args, **kwargs):
        pytest.fail("must reject malformed directory before decompression")
    monkeypatch.setattr(moyle_bundle, "_stream_member", forbidden)
    with pytest.raises(StegError):
        inspect_bundle(path, **LIMITS)


def test_invalid_utf8_is_rejected(tmp_path):
    path = managed(tmp_path)
    data = bytearray(path.read_bytes())
    central, _ = positions(data)
    data[central + 46 + 5] = 255
    data[30 + 5] = 255
    path.write_bytes(data)
    with pytest.raises(StegError):
        inspect_bundle(path, **LIMITS)


def test_no_marker_does_not_construct_zip_parser(tmp_path, monkeypatch):
    path = tmp_path / "ordinary.bin"
    path.write_bytes(b"PK not a ZIP" * 100)
    monkeypatch.setattr(zipfile, "ZipFile", lambda *args, **kwargs: pytest.fail("unexpected parser"))
    assert inspect_bundle(path, max_total_bytes=1, max_archive_bytes=1) is None


@pytest.mark.parametrize("count", [0, 101])
def test_source_count_limits(tmp_path, count):
    source = tmp_path / "source.txt"
    source.write_bytes(b"a")
    target = tmp_path / "out.zip"
    with pytest.raises(StegError):
        create_bundle([BundleSource(source, "a.txt")] * count, target, **LIMITS)
    assert not target.exists()


def test_limit_100_and_maximum_filename(tmp_path):
    source = tmp_path / "source"
    source.write_bytes(b"a")
    name = "草" * 60
    target = tmp_path / "out.zip"
    result = create_bundle([BundleSource(source, name)] * 100, target, **LIMITS)
    assert len(result.entries) == 100
    assert result.entries[-1].name == name


def test_archive_budget_cleanup(tmp_path):
    inputs, _ = sources(tmp_path)
    output = tmp_path / "out.zip"
    with pytest.raises(StegError):
        create_bundle(inputs, output, max_total_bytes=10000, max_archive_bytes=80)
    assert not output.exists()


@pytest.mark.parametrize("budget", ["archive", "expanded"])
def test_inspection_budget_is_checked_before_decompression(tmp_path, monkeypatch, budget):
    path = managed(tmp_path)
    monkeypatch.setattr(moyle_bundle, "_stream_member", lambda *args: pytest.fail("expanded too early"))
    with pytest.raises(StegError):
        inspect_bundle(path, max_total_bytes=1 if budget == "expanded" else 10000,
                       max_archive_bytes=1 if budget == "archive" else 10000)


def test_stored_data_crc_corruption_rejected(tmp_path):
    path = managed(tmp_path, method=zipfile.ZIP_STORED)
    data = bytearray(path.read_bytes())
    data[30 + len("0001/a.txt")] ^= 1
    path.write_bytes(data)
    with pytest.raises(StegError):
        inspect_bundle(path, **LIMITS)


def test_forged_expanded_length_cannot_hide_extra_deflate_data(tmp_path):
    path = managed(tmp_path, (("0001/a.txt", b"A" * 100000),))
    data = bytearray(path.read_bytes())
    central, _ = positions(data)
    struct.pack_into("<I", data, central + 24, 3)
    struct.pack_into("<I", data, 22, 3)
    path.write_bytes(data)
    with pytest.raises(StegError):
        inspect_bundle(path, **LIMITS)


@pytest.mark.parametrize("phase", ["bundle_read", "bundle_check_input", "bundle_entry"])
def test_creation_cancellation_cleans_only_owned_output(tmp_path, phase):
    inputs, _ = sources(tmp_path)
    output = tmp_path / "cancelled.zip"
    unrelated = tmp_path / "keep.txt"
    unrelated.write_bytes(b"keep")
    def progress(stage, completed, total):
        if stage == phase:
            raise OperationCancelled("cancel")
    with pytest.raises(OperationCancelled):
        create_bundle(inputs, output, **LIMITS, control=OperationControl(progress=progress))
    assert not output.exists()
    assert unrelated.read_bytes() == b"keep"


def test_restored_timestamp_source_mutation_detected_by_second_pass(tmp_path):
    source = tmp_path / "changing.bin"
    source.write_bytes(b"A" * (3 * moyle_bundle.CHUNK))
    original = source.stat()
    target = tmp_path / "out.zip"
    changed = False
    def progress(stage, completed, total):
        nonlocal changed
        if stage == "bundle_read" and completed == moyle_bundle.CHUNK and not changed:
            changed = True
            source.write_bytes(b"B" * (3 * moyle_bundle.CHUNK))
            os.utime(source, ns=(original.st_atime_ns, original.st_mtime_ns))
    with pytest.raises(InputChangedError):
        create_bundle([BundleSource(source, "changing.bin")], target, **LIMITS,
                      control=OperationControl(progress=progress))
    assert changed
    assert not target.exists()


def test_authenticated_entry_digest_cannot_be_replaced(tmp_path):
    path = managed(tmp_path)
    entry = inspect_bundle(path, **LIMITS).entries[0]
    staging = tmp_path / "staging"
    staging.mkdir()
    with pytest.raises(StegError):
        extract_entry(path, replace(entry, sha256="0" * 64), staging, **LIMITS)
    assert list(staging.iterdir()) == []


def test_extraction_cancellation_cleans_private_file(tmp_path):
    path = managed(tmp_path, (("0001/a.txt", b"A" * (2 * moyle_bundle.CHUNK)),))
    entry = inspect_bundle(path, **LIMITS).entries[0]
    staging = tmp_path / "staging"
    staging.mkdir()
    def progress(stage, completed, total):
        if stage == "bundle_entry" and completed:
            raise OperationCancelled("cancel")
    with pytest.raises(OperationCancelled):
        extract_entry(path, entry, staging, **LIMITS, control=OperationControl(progress=progress))
    assert list(staging.iterdir()) == []


def test_small_fixed_temp_prefix_preserves_valid_long_name(tmp_path):
    path = managed(tmp_path, (("0001/" + "a" * 180, b"A"),))
    entry = inspect_bundle(path, **LIMITS).entries[0]
    result = extract_entry(path, entry, tmp_path, **LIMITS)
    assert len(result.name) < 50
    assert result.read_bytes() == b"A"
