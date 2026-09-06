"""Synthetic GIF carrier tests: animation bytes and authenticated payload stay separate."""
import io
import os
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

import png_steg_aes256 as core
import gif_carrier as gif

KEY = core.Credential.from_key_bytes(bytes(range(32)))
TINY = bytes.fromhex("47494638376101000100800000000000ffffff2c00000000010001000002024401003b")


def parse(data, **kwargs):
    return gif.scan(data, max_pixels=25_000_000, **kwargs)


def ext(payload, chunk=255, version=b"001"):
    output = bytearray(b"\x21\xff\x0bMOYLESTG" + version)
    for p in range(0, len(payload), chunk):
        block = payload[p:p+chunk]
        output.append(len(block)); output.extend(block)
    return bytes(output) + b"\0"


def animation_bytes():
    frames = []
    for i in range(3):
        image = Image.new("RGBA", (48, 32), (0, 0, 0, 0))
        ImageDraw.Draw(image).rectangle((4 + i * 8, 5, 15 + i * 8, 23), fill=(230, 40 + i * 50, 90, 255))
        frames.append(image)
    out = io.BytesIO()
    frames[0].save(out, "GIF", save_all=True, append_images=frames[1:],
                   duration=[40, 90, 130], loop=2, disposal=[2, 3, 2], transparency=0)
    return out.getvalue()


def prepare(tmp_path):
    cover = tmp_path / "cover.gif"
    secret = tmp_path / "秘密.txt"
    cover.write_bytes(animation_bytes())
    secret.write_bytes(("cross platform GIF!\n" * 20).encode())
    return cover, secret, tmp_path / "hidden.gif"


@pytest.mark.parametrize("credential", [core.Credential.from_password("gif-pass-2026"), core.Credential.from_key_bytes(bytes(range(32)))])
def test_gif_round_trip_preserves_animation(tmp_path, credential):
    cover, secret, output = prepare(tmp_path)
    before = cover.read_bytes()
    result = core.hide_file(cover, secret, output, credential=credential)
    decoded = core.decode_image(output, credential=credential)
    assert decoded.data == secret.read_bytes()
    assert decoded.filename == secret.name
    assert result.container_format == "gif" and result.frame_count == 3
    assert result.output_bytes == output.stat().st_size
    assert cover.read_bytes() == before
    assert output.read_bytes().startswith(before[:-1])
    with Image.open(io.BytesIO(before)) as original, Image.open(output) as modified:
        assert modified.n_frames == original.n_frames == 3
        assert modified.info["loop"] == original.info["loop"] == 2
        for i in range(3):
            original.seek(i); modified.seek(i)
            assert modified.info["duration"] == original.info["duration"]
            assert modified.disposal_method == original.disposal_method
            assert modified.convert("RGBA").tobytes() == original.convert("RGBA").tobytes()


def test_gif_preflight_uses_container_budget_not_pixel_capacity(tmp_path):
    cover, secret, output = prepare(tmp_path)
    pre = core.preflight_hide(cover, secret, auto_resize=True, max_fill=0.01, max_container_bytes=4096)
    assert pre.fits and pre.container_format == "gif" and pre.frame_count == 3
    assert (pre.image_width, pre.image_height) == (48, 32)
    result = core.hide_file(cover, secret, output, credential=core.Credential.from_key_bytes(bytes(32)),
                            auto_resize=True, max_fill=0.01, max_container_bytes=4096)
    assert result.output_bytes == pre.output_bytes == output.stat().st_size


def test_87a_upgraded_and_filename_extension_is_not_detection(tmp_path):
    cover, secret, output = prepare(tmp_path)
    cover = tmp_path / "misnamed.dat"
    cover.write_bytes(TINY)
    core.hide_file(cover, secret, output, credential=KEY)
    data = output.read_bytes()
    assert data[:6] == b"GIF89a" and data[6:len(TINY)-1] == TINY[6:-1]
    assert core.decode_image(output, credential=KEY).data == secret.read_bytes()


def test_lzw_initial_clear_is_recommended_not_required(tmp_path):
    cover, secret, output = prepare(tmp_path)
    cover.write_bytes(TINY[:30] + bytes.fromhex("0128003b"))
    core.hide_file(cover, secret, output, credential=KEY)
    assert core.decode_image(output, credential=KEY).data == secret.read_bytes()


@pytest.mark.parametrize("chunk", [1, 17, 54, 254, 255])
def test_all_legal_subblock_sizes(tmp_path, chunk):
    cover, secret, output = prepare(tmp_path)
    saes = tmp_path / "original.saes"
    core.encrypt_file(secret, saes, credential=KEY)
    output.write_bytes(TINY[:3] + b"89a" + TINY[6:-1] + ext(saes.read_bytes(), chunk) + b";")
    assert core.decode_image(output, credential=KEY).data == secret.read_bytes()


@pytest.mark.parametrize("invalid", [
    TINY + b"extra", TINY[:-1], TINY[:-3] + b";", b"GIF89a",
    TINY[:6] + b"\0\0" + TINY[8:],
    TINY[:24] + b"\x02\0" + TINY[26:],
    TINY[:29] + b"\x09" + TINY[30:],
    TINY[:31] + b"\x00\x01" + TINY[33:],
    TINY[:31] + b"\x54\x01" + TINY[33:],
    TINY[:-1] + b"\x21\xff\x0aMOYLESTG001\0;",
    TINY[:19] + b"\x21\xf9\x04\x00\0\0\0\0" + b";",
])
def test_structural_and_lzw_damage_rejected(invalid):
    with pytest.raises(gif.GifError):
        parse(invalid)


def test_500_frames_and_total_pixels_budget():
    parse(TINY[:19] + TINY[19:-1] * 500 + b";")
    with pytest.raises(gif.GifResourceError):
        parse(TINY[:19] + TINY[19:-1] * 501 + b";")
    # A valid first frame but a very large logical canvas: later frames exceed animation budget.
    canvas = TINY[:6] + (10000).to_bytes(2, "little") + (1000).to_bytes(2, "little") + TINY[10:19]
    with pytest.raises(gif.GifResourceError):
        parse(canvas + TINY[19:-1] * 11 + b";")


@pytest.mark.parametrize("kind", ["duplicate", "version", "truncated", "extra_payload", "cipher"])
def test_bad_encrypted_extension_rejected(tmp_path, kind):
    cover, secret, output = prepare(tmp_path)
    saes = tmp_path / "original.saes"
    core.encrypt_file(secret, saes, credential=KEY)
    data = saes.read_bytes()
    extension = ext(data)
    if kind == "duplicate": extension += ext(data)
    if kind == "version": extension = ext(data, version=b"002")
    if kind == "truncated": extension = ext(data[:-1])
    if kind == "extra_payload": extension = ext(data + b"x")
    if kind == "cipher": extension = ext(data[:-1] + bytes([data[-1] ^ 1]))
    output.write_bytes(TINY[:3] + b"89a" + TINY[6:-1] + extension + b";")
    with pytest.raises(core.StegError):
        core.decode_image(output, credential=KEY)


@pytest.mark.parametrize("version", [b"001", b"999"])
def test_existing_moyle_payload_never_replaced(tmp_path, version):
    cover, secret, output = prepare(tmp_path)
    cover.write_bytes(TINY[:-1] + ext(b"private-placeholder", version=version) + b";")
    before = cover.read_bytes()
    with pytest.raises(core.StegError, match="载体已含"):
        core.hide_file(cover, secret, output, credential=KEY, force=True)
    assert cover.read_bytes() == before and not output.exists()


def test_other_extension_with_fake_markers_is_preserved(tmp_path):
    cover, secret, output = prepare(tmp_path)
    text = b";MOYLESTG001;\x21\xff\x0b"
    cover.write_bytes(TINY[:-1] + b"\x21\xfe" + bytes([len(text)]) + text + b"\0;")
    before = cover.read_bytes()
    core.hide_file(cover, secret, output, credential=KEY)
    assert output.read_bytes()[6:len(before)-1] == before[6:-1]


def test_input_and_output_container_budgets(tmp_path):
    cover, secret, output = prepare(tmp_path)
    with pytest.raises(core.ContainerResourceLimitError):
        core.hide_file(cover, secret, output, credential=KEY, max_container_bytes=cover.stat().st_size-1)
    pre = core.preflight_hide(cover, secret, max_container_bytes=cover.stat().st_size + 20)
    assert not pre.fits and pre.reason == "container"
    with pytest.raises(core.ContainerResourceLimitError):
        core.hide_file(cover, secret, output, credential=KEY, max_container_bytes=cover.stat().st_size+20)
    core.hide_file(cover, secret, output, credential=KEY)
    with pytest.raises(core.ContainerResourceLimitError):
        core.decode_image(output, credential=KEY, max_container_bytes=output.stat().st_size-1)


def test_pixel_rejection_precedes_reading_secret_and_pillow(tmp_path, monkeypatch):
    cover, secret, output = prepare(tmp_path)
    monkeypatch.setattr(core, "_build_plaintext", lambda *a, **k: pytest.fail("secret read before GIF budget"))
    monkeypatch.setattr(core.Image, "open", lambda *a, **k: pytest.fail("decoder before GIF budget"))
    with pytest.raises(core.StegError, match="像素"):
        core.hide_file(cover, secret, output, credential=KEY, max_pixels=1000)


@pytest.mark.parametrize("stage", ["read_gif", "check_input", "gif_frames", "derive", "encrypt", "embed_gif", "save", "verify", "verify.gif_frames", "commit"])
def test_cancel_leaves_no_output_or_temp(tmp_path, stage):
    cover, secret, output = prepare(tmp_path)
    cancelled = False
    def progress(current, done, total):
        nonlocal cancelled
        if current == stage:
            cancelled = True
    with pytest.raises(core.OperationCancelled):
        core.hide_file(cover, secret, output, credential=KEY,
            control=core.OperationControl(progress, lambda: cancelled))
    assert not output.exists() and not list(tmp_path.glob(".moyle-*"))


def test_cover_changed_and_timestamp_restored_rejected(tmp_path):
    cover, secret, output = prepare(tmp_path)
    initial = cover.stat()
    changed = False
    def progress(stage, done, total):
        nonlocal changed
        if stage == "read_gif" and done and not changed:
            data = bytearray(cover.read_bytes()); data[11] ^= 1
            cover.write_bytes(data)
            os.utime(cover, ns=(initial.st_atime_ns, initial.st_mtime_ns))
            changed = True
    with pytest.raises(core.InputChangedError):
        core.hide_file(cover, secret, output, credential=KEY, control=core.OperationControl(progress))
    assert not output.exists()


@pytest.mark.parametrize("target", ["cover", "source", "key"])
def test_output_never_overwrites_source_or_key(tmp_path, target):
    cover, secret, output = prepare(tmp_path)
    source = tmp_path / "source.gif"
    source.write_bytes(secret.read_bytes())
    key = tmp_path / "key.gif"
    core.generate_key_file(key)
    credential = core.Credential.from_key_file(key)
    destination = {"cover": cover, "source": source, "key": key}[target]
    before = destination.read_bytes()
    with pytest.raises(core.PathConflictError):
        core.hide_file(cover, source, destination, credential=credential, force=True)
    assert destination.read_bytes() == before


def test_new_racing_output_is_not_replaced(tmp_path):
    cover, secret, output = prepare(tmp_path)
    def progress(stage, done, total):
        if stage == "commit":
            output.write_bytes(b"other writer")
    with pytest.raises(FileExistsError):
        core.hide_file(cover, secret, output, credential=KEY, control=core.OperationControl(progress))
    assert output.read_bytes() == b"other writer" and not list(tmp_path.glob(".moyle-*"))


def test_saved_gif_is_authenticated_before_commit(tmp_path, monkeypatch):
    cover, secret, output = prepare(tmp_path)
    decode = core.decode_image
    def corrupt(path, **kwargs):
        data = bytearray(path.read_bytes()); data[-3] ^= 1; path.write_bytes(data)
        return decode(path, **kwargs)
    monkeypatch.setattr(core, "decode_image", corrupt)
    with pytest.raises(core.AuthenticationError):
        core.hide_file(cover, secret, output, credential=KEY)
    assert not output.exists() and not list(tmp_path.glob(".moyle-*"))


def test_cli_capacity_hide_extract_info(tmp_path, capsys):
    cover, secret, output = prepare(tmp_path)
    key = tmp_path / "test.stegkey"
    core.generate_key_file(key)
    assert core.main(["capacity", str(cover), "--max-container-bytes", "4096"]) == 0
    assert "GIF" in capsys.readouterr().out
    assert core.main(["hide", str(cover), str(secret), str(output), "--key-file", str(key)]) == 0
    assert "GIF" in capsys.readouterr().out
    restored = tmp_path / "restored.txt"
    assert core.main(["extract", str(output), str(restored), "--key-file", str(key)]) == 0
    assert restored.read_bytes() == secret.read_bytes()
    assert core.main(["info", str(output), "--key-file", str(key)]) == 0
