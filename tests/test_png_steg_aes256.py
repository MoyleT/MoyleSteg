from pathlib import Path
import hashlib

from png_steg_aes256 import generate_key_file, read_key_file


def test_generated_key_file_roundtrips_256_bit_key(tmp_path: Path) -> None:
    key_path = tmp_path / "secret.stegkey"

    generated = generate_key_file(key_path)
    loaded = read_key_file(key_path)

    assert len(generated) == 32
    assert loaded == generated
    assert key_path.read_text(encoding="ascii").startswith("PNG-STEG-AES256-KEY-V1\n")

from png_steg_aes256 import iter_scattered_positions


def test_scattered_positions_are_unique_and_cover_full_domain() -> None:
    positions = list(
        iter_scattered_positions(
            total_positions=10_000,
            needed=4_000,
            layout_key=b"L" * 32,
            block_size=1_000,
        )
    )

    assert len(positions) == 4_000
    assert len(set(positions)) == 4_000
    assert min(positions) < 1_000
    assert max(positions) >= 9_000
    # Every tenth of the image receives payload bits.
    assert {position // 1_000 for position in positions} == set(range(10))

import os
from PIL import Image
import pytest

from png_steg_aes256 import Credential, decode_image, hide_file


def _make_cover(path: Path, size: tuple[int, int] = (320, 240)) -> None:
    image = Image.new("RGBA", size)
    pixels = []
    for y in range(size[1]):
        for x in range(size[0]):
            pixels.append(((x * 7 + y) % 256, (x + y * 5) % 256, (x * 3 + y * 11) % 256, 255))
    image.putdata(pixels)
    image.save(path, format="PNG")


def test_password_mode_encrypts_and_decodes_exact_bytes(tmp_path: Path) -> None:
    cover = tmp_path / "cover.png"
    secret = tmp_path / "secret.bin"
    hidden = tmp_path / "hidden.png"
    _make_cover(cover)
    secret_bytes = os.urandom(4_000) + b"compressible" * 200
    secret.write_bytes(secret_bytes)
    credential = Credential.from_password("correct horse battery staple")

    result = hide_file(cover, secret, hidden, credential=credential)
    decoded = decode_image(hidden, credential=credential)

    assert result.algorithm == "AES-256-GCM"
    assert decoded.filename == "secret.bin"
    assert decoded.data == secret_bytes
    assert decoded.sha256_hex == hashlib.sha256(secret_bytes).hexdigest()

from png_steg_aes256 import AuthenticationError


def test_wrong_password_is_rejected_by_aes_gcm(tmp_path: Path) -> None:
    cover = tmp_path / "cover.png"
    secret = tmp_path / "secret.txt"
    hidden = tmp_path / "hidden.png"
    _make_cover(cover)
    secret.write_text("classified text" * 200, encoding="utf-8")

    hide_file(
        cover,
        secret,
        hidden,
        credential=Credential.from_password("right password"),
    )

    with pytest.raises(AuthenticationError, match="认证失败"):
        decode_image(hidden, credential=Credential.from_password("wrong password"))


def test_key_file_mode_roundtrips_without_password(tmp_path: Path) -> None:
    cover = tmp_path / "cover.png"
    secret = tmp_path / "document.pdf"
    hidden = tmp_path / "hidden.png"
    key_path = tmp_path / "private.stegkey"
    _make_cover(cover)
    secret_bytes = b"%PDF-synthetic\n" + os.urandom(6_000)
    secret.write_bytes(secret_bytes)
    generate_key_file(key_path)
    credential = Credential.from_key_file(key_path)

    result = hide_file(cover, secret, hidden, credential=credential)
    decoded = decode_image(hidden, credential=credential)

    assert result.credential_mode == 2
    assert decoded.data == secret_bytes
    assert decoded.filename == "document.pdf"


def test_auto_resize_grows_small_cover_and_respects_fill_target(tmp_path: Path) -> None:
    cover = tmp_path / "tiny.png"
    secret = tmp_path / "payload.bin"
    hidden = tmp_path / "resized.png"
    _make_cover(cover, (32, 24))
    secret_bytes = os.urandom(8_000)
    secret.write_bytes(secret_bytes)
    credential = Credential.from_password("resize test password")

    result = hide_file(
        cover,
        secret,
        hidden,
        credential=credential,
        auto_resize=True,
        max_fill=0.50,
    )
    decoded = decode_image(hidden, credential=credential)

    assert result.image_width > 32
    assert result.image_height > 24
    assert result.fill_ratio <= 0.501
    assert decoded.data == secret_bytes


def test_hiding_never_changes_alpha_channel(tmp_path: Path) -> None:
    cover = tmp_path / "alpha.png"
    secret = tmp_path / "secret.bin"
    hidden = tmp_path / "hidden.png"
    image = Image.new("RGBA", (128, 128))
    pixels = []
    for y in range(128):
        for x in range(128):
            pixels.append((x, y, (x + y) % 256, (x * 13 + y * 17) % 256))
    image.putdata(pixels)
    image.save(cover)
    secret.write_bytes(os.urandom(1_000))

    hide_file(
        cover,
        secret,
        hidden,
        credential=Credential.from_password("alpha preservation"),
    )

    with Image.open(cover) as before, Image.open(hidden) as after:
        assert before.convert("RGBA").getchannel("A").tobytes() == (
            after.convert("RGBA").getchannel("A").tobytes()
        )

from png_steg_aes256 import decrypt_encrypted_file, encrypt_file


def test_standalone_aes256_file_encrypt_and_decrypt(tmp_path: Path) -> None:
    source = tmp_path / "plain.dat"
    encrypted = tmp_path / "plain.dat.saes"
    restored = tmp_path / "restored.dat"
    source_bytes = os.urandom(12_000) + b"repeated data" * 500
    source.write_bytes(source_bytes)
    credential = Credential.from_password("standalone aes password")

    encrypted_result = encrypt_file(source, encrypted, credential=credential)
    output_path, decoded = decrypt_encrypted_file(
        encrypted,
        restored,
        credential=credential,
    )

    assert encrypted_result.algorithm == "AES-256-GCM"
    assert output_path == restored
    assert restored.read_bytes() == source_bytes
    assert decoded.filename == "plain.dat"

from png_steg_aes256 import _body_positions, _derive_keys, _logical_to_raw_index, peek_header


def test_changing_one_used_body_bit_breaks_aes_gcm_authentication(tmp_path: Path) -> None:
    cover = tmp_path / "cover.png"
    secret = tmp_path / "secret.bin"
    hidden = tmp_path / "hidden.png"
    tampered = tmp_path / "tampered.png"
    _make_cover(cover)
    secret.write_bytes(os.urandom(7_000))
    credential = Credential.from_password("tamper detection password")
    hide_file(cover, secret, hidden, credential=credential)

    header = peek_header(hidden)
    _encryption_key, layout_key = _derive_keys(credential, header)
    with Image.open(hidden) as image:
        rgba = image.convert("RGBA")
        raw = bytearray(rgba.tobytes())
        logical = next(_body_positions(rgba.width * rgba.height * 3, header.ciphertext_length, layout_key))
        raw[_logical_to_raw_index(logical)] ^= 1
        Image.frombytes("RGBA", rgba.size, bytes(raw)).save(tampered)

    with pytest.raises(AuthenticationError, match="认证失败"):
        decode_image(tampered, credential=credential)


def test_same_input_and_credential_produce_different_outputs(tmp_path: Path) -> None:
    cover = tmp_path / "cover.png"
    secret = tmp_path / "secret.txt"
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    _make_cover(cover)
    secret.write_text("same plaintext" * 300, encoding="utf-8")
    credential = Credential.from_password("nonce and salt test")

    hide_file(cover, secret, first, credential=credential)
    hide_file(cover, secret, second, credential=credential)

    assert first.read_bytes() != second.read_bytes()
    assert decode_image(first, credential=credential).data == secret.read_bytes()
    assert decode_image(second, credential=credential).data == secret.read_bytes()
