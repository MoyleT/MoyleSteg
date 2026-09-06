#!/usr/bin/env python3
"""AES-256-GCM encrypted PNG LSB steganography tool.

The encrypted payload is distributed through RGB least-significant bits using
positions derived from a separate layout key. Alpha bytes are never modified.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import getpass
import hashlib
import hmac
import io
import math
import os
import struct
import sys
import tempfile
import zlib
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from PIL import Image, ImageOps, UnidentifiedImageError
import gif_carrier

KEY_FILE_HEADER = "PNG-STEG-AES256-KEY-V1"
KEY_BYTES = 32

MAGIC = b"SGAES001"
VERSION = 1
LAYOUT_VERSION = 1
MODE_PASSWORD = 1
MODE_KEY_FILE = 2

SCRYPT_LOG_N = 15
SCRYPT_R = 8
SCRYPT_P = 1

HEADER_CORE_STRUCT = struct.Struct(">8sBBBBBB16s12sQ")
HEADER_CRC_STRUCT = struct.Struct(">I")
HEADER_SIZE = HEADER_CORE_STRUCT.size + HEADER_CRC_STRUCT.size
HEADER_BITS = HEADER_SIZE * 8

INNER_MAGIC = b"PAY1"
INNER_VERSION = 1
COMPRESSION_NONE = 0
COMPRESSION_ZLIB = 1
INNER_STRUCT = struct.Struct(">4sBBHQQ32s")

DEFAULT_BLOCK_SIZE = 4096
DEFAULT_MAX_PIXELS = 25_000_000
DEFAULT_MAX_FILE_BYTES = 256 * 1024**2
MAX_DECODED_SIZE = 8 * 1024**3
IO_CHUNK = 1024 * 1024


class StegError(Exception):
    """Base exception for expected tool errors."""


class AuthenticationError(StegError):
    """Raised when AES-GCM authentication fails."""


class ContainerResourceLimitError(StegError):
    """The complete opened container exceeds the caller's byte budget."""

    code = "container_resource_limit"

    def __init__(self) -> None:
        super().__init__("完整容器超过处理资源上限")


class ContainerBudgetError(ValueError):
    code = "container_budget_invalid"


def _check_container_budget(size: int, limit: int) -> None:
    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
        raise ContainerBudgetError("容器预算必须为正整数字节数")
    if size > limit:
        raise ContainerResourceLimitError()


class _ContainerReader:
    """Borrow one opened file; cap PNG/SAES reads without another disk copy.

    The owner closes the raw handle. Size checks use that handle, never a new
    pathname lookup. This is a resource guard, not an operating-system snapshot.
    """

    def __init__(self, handle, limit: int | None):
        self.handle = handle
        self.limit = limit
        self.check()

    def check(self):
        if self.limit is not None:
            _check_container_budget(os.fstat(self.handle.fileno()).st_size, self.limit)

    @property
    def name(self):
        return self.handle.name

    def fileno(self):
        return self.handle.fileno()

    def tell(self):
        return self.handle.tell()

    def seek(self, offset, whence=0):
        self.check()
        return self.handle.seek(offset, whence)

    def _read(self, method, size):
        self.check()
        if self.limit is not None:
            remaining = max(0, self.limit - self.tell())
            size = remaining if size < 0 else min(size, remaining)
        data = method(size)
        self.check()
        return data

    def read(self, size=-1):
        return self._read(self.handle.read, size)

    def readline(self, size=-1):
        return self._read(self.handle.readline, size)

    def readinto(self, buffer):
        data = self.read(len(buffer))
        buffer[:len(data)] = data
        return len(data)

    def close(self):
        # Pillow may close its stream while the owner still needs to check it.
        pass


class InputChangedError(StegError):
    """A bounded read observed changing file identity, metadata or content."""

    code = "input_changed"

    def __init__(self) -> None:
        super().__init__("读取期间输入文件发生变化，请等待文件保存完成后重试")


class OperationCancelled(StegError):
    """Cooperative cancellation before output publication."""


@dataclass
class OperationControl:
    progress: Callable[[str, int | None, int | None], None] | None = None
    cancelled: Callable[[], bool] | None = None

    def check(self) -> None:
        if self.cancelled is not None and self.cancelled():
            raise OperationCancelled("操作已取消")

    def report(self, stage: str, completed: int | None = None, total: int | None = None) -> None:
        self.check()
        if self.progress is not None:
            self.progress(stage, completed, total)
        self.check()

    def child(self, prefix: str) -> "OperationControl":
        return OperationControl(
            lambda stage, done, total: self.report(prefix + "." + stage, done, total),
            self.cancelled,
        )


def _control(control: OperationControl | None) -> OperationControl:
    return control if control is not None else OperationControl()


def _validate_limits(max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
                     max_pixels: int = DEFAULT_MAX_PIXELS) -> None:
    if not isinstance(max_file_bytes, int) or not 0 < max_file_bytes <= MAX_DECODED_SIZE:
        raise ValueError("文件资源上限必须大于零且不超过 8 GiB")
    if not isinstance(max_pixels, int) or max_pixels <= 0:
        raise ValueError("像素资源上限必须大于零")


def _ciphertext_limit(max_file_bytes: int) -> int:
    return max_file_bytes + INNER_STRUCT.size + 65535 + 16


@dataclass(frozen=True)
class Credential:
    mode: int
    secret: bytes = field(repr=False)
    key_path: Path | None = field(default=None, repr=False, compare=False)

    @classmethod
    def from_password(cls, password: str) -> "Credential":
        if not password:
            raise ValueError("口令不能为空")
        return cls(MODE_PASSWORD, password.encode("utf-8"))

    @classmethod
    def from_key_bytes(cls, key: bytes) -> "Credential":
        if len(key) != KEY_BYTES:
            raise ValueError("密钥必须为 256 bit（32 字节）")
        return cls(MODE_KEY_FILE, bytes(key))

    @classmethod
    def from_key_file(cls, path: Path) -> "Credential":
        return cls(MODE_KEY_FILE, read_key_file(path), Path(path).absolute())


@dataclass(frozen=True)
class Header:
    mode: int
    scrypt_log_n: int
    scrypt_r: int
    scrypt_p: int
    salt: bytes
    nonce: bytes
    ciphertext_length: int
    core: bytes


@dataclass(frozen=True)
class DecodedPayload:
    filename: str
    data: bytes
    original_size: int
    stored_size: int
    compressed: bool
    sha256_hex: str
    credential_mode: int


@dataclass(frozen=True)
class HideResult:
    output_path: Path
    image_width: int
    image_height: int
    capacity_bytes: int
    ciphertext_bytes: int
    fill_ratio: float
    compressed: bool
    original_size: int
    stored_size: int
    sha256_hex: str
    credential_mode: int
    algorithm: str = "AES-256-GCM"
    container_format: str = "png"
    frame_count: int = 1
    output_bytes: int = 0


def generate_key_file(path: Path, *, force: bool = False,
                      protected_paths: Iterable[Path] = (),
                      control: OperationControl | None = None) -> bytes:
    """Create a text key file containing a random 256-bit master key."""
    path = Path(path)
    protected_paths = tuple(protected_paths)
    validate_operation_paths(inputs=protected_paths, output=path, force=force)
    key = os.urandom(KEY_BYTES)
    encoded = base64.urlsafe_b64encode(key).decode("ascii")
    _atomic_write(path, f"{KEY_FILE_HEADER}\n{encoded}\n".encode("ascii"),
                  force=force, protected_paths=protected_paths, control=control,
                  file_mode=0o600)
    return key


def read_key_file(path: Path) -> bytes:
    path = Path(path)
    with path.open("rb") as handle:
        if os.fstat(handle.fileno()).st_size > 256:
            raise ValueError("密钥文件长度无效")
        encoded = handle.read(257)
    if len(encoded) > 256:
        raise ValueError("密钥文件长度无效")
    lines = encoded.decode("ascii").splitlines()
    if len(lines) != 2 or lines[0] != KEY_FILE_HEADER:
        raise ValueError("不是本工具生成的密钥文件")
    try:
        key = base64.b64decode(lines[1].encode("ascii"), altchars=b"-_", validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("密钥文件编码损坏") from exc
    if len(key) != KEY_BYTES:
        raise ValueError("密钥必须为 256 bit（32 字节）")
    return key


class _HmacCounterRng:
    """Deterministic CSPRNG for keyed placement; not used as the cipher."""

    def __init__(self, key: bytes, context: bytes) -> None:
        self._key = key
        self._context = context
        self._counter = 0
        self._buffer = bytearray()

    def _read(self, size: int) -> bytes:
        while len(self._buffer) < size:
            block = hmac.new(
                self._key,
                self._context + struct.pack(">Q", self._counter),
                hashlib.sha256,
            ).digest()
            self._counter += 1
            self._buffer.extend(block)
        result = bytes(self._buffer[:size])
        del self._buffer[:size]
        return result

    def randbelow(self, upper: int) -> int:
        if upper <= 0:
            raise ValueError("upper 必须为正数")
        byte_count = max(1, (upper.bit_length() + 7) // 8)
        sample_space = 1 << (8 * byte_count)
        limit = sample_space - (sample_space % upper)
        while True:
            candidate = int.from_bytes(self._read(byte_count), "big")
            if candidate < limit:
                return candidate % upper


def iter_scattered_positions(
    *,
    total_positions: int,
    needed: int,
    layout_key: bytes,
    block_size: int = DEFAULT_BLOCK_SIZE,
) -> Iterator[int]:
    """Yield unique keyed positions spread proportionally across the domain."""
    if total_positions < 0 or needed < 0:
        raise ValueError("位置数量不能为负数")
    if needed > total_positions:
        raise ValueError("需要的位置数量超过可用位置")
    if block_size <= 0:
        raise ValueError("block_size 必须为正数")
    if len(layout_key) < 16:
        raise ValueError("layout_key 过短")
    if total_positions == 0:
        return

    for block_start in range(0, total_positions, block_size):
        block_end = min(total_positions, block_start + block_size)
        block_len = block_end - block_start
        before = (needed * block_start) // total_positions
        after = (needed * block_end) // total_positions
        count = after - before
        if count == 0:
            continue

        offsets = list(range(block_len))
        rng = _HmacCounterRng(
            layout_key,
            b"PNG-STEG-AES256/layout-block/" + struct.pack(">Q", block_start // block_size),
        )
        for index in range(count):
            swap_index = index + rng.randbelow(block_len - index)
            offsets[index], offsets[swap_index] = offsets[swap_index], offsets[index]
            yield block_start + offsets[index]


def _derive_keys(credential: Credential, header: Header) -> tuple[bytes, bytes]:
    if credential.mode != header.mode:
        raise AuthenticationError("凭据类型与隐写文件不匹配")

    if header.mode == MODE_PASSWORD:
        if (
            header.scrypt_log_n != SCRYPT_LOG_N
            or header.scrypt_r != SCRYPT_R
            or header.scrypt_p != SCRYPT_P
        ):
            raise StegError("不支持的 scrypt 参数")
        master = Scrypt(
            salt=header.salt,
            length=KEY_BYTES,
            n=1 << header.scrypt_log_n,
            r=header.scrypt_r,
            p=header.scrypt_p,
        ).derive(credential.secret)
    elif header.mode == MODE_KEY_FILE:
        if any((header.scrypt_log_n, header.scrypt_r, header.scrypt_p)):
            raise StegError("密钥文件模式的头部参数无效")
        if len(credential.secret) != KEY_BYTES:
            raise AuthenticationError("密钥长度无效")
        master = credential.secret
    else:
        raise StegError("未知凭据模式")

    material = HKDF(
        algorithm=hashes.SHA256(),
        length=64,
        salt=header.salt,
        info=b"PNG-STEG-AES256/v1/enc-and-layout",
    ).derive(master)
    return material[:32], material[32:]


def _build_header(mode: int, salt: bytes, nonce: bytes, ciphertext_length: int) -> Header:
    if mode == MODE_PASSWORD:
        log_n, r, p = SCRYPT_LOG_N, SCRYPT_R, SCRYPT_P
    elif mode == MODE_KEY_FILE:
        log_n, r, p = 0, 0, 0
    else:
        raise ValueError("未知凭据模式")
    core = HEADER_CORE_STRUCT.pack(
        MAGIC,
        VERSION,
        mode,
        log_n,
        r,
        p,
        LAYOUT_VERSION,
        salt,
        nonce,
        ciphertext_length,
    )
    return Header(mode, log_n, r, p, salt, nonce, ciphertext_length, core)


def _serialize_header(header: Header) -> bytes:
    crc = zlib.crc32(header.core) & 0xFFFFFFFF
    return header.core + HEADER_CRC_STRUCT.pack(crc)


def _parse_header(data: bytes) -> Header:
    if len(data) != HEADER_SIZE:
        raise StegError("隐写头部长度错误")
    core = data[: HEADER_CORE_STRUCT.size]
    stored_crc = HEADER_CRC_STRUCT.unpack(data[HEADER_CORE_STRUCT.size :])[0]
    actual_crc = zlib.crc32(core) & 0xFFFFFFFF
    if stored_crc != actual_crc:
        raise StegError("隐写头部校验失败，图片可能已被修改")

    (
        magic,
        version,
        mode,
        log_n,
        r,
        p,
        layout_version,
        salt,
        nonce,
        ciphertext_length,
    ) = HEADER_CORE_STRUCT.unpack(core)
    if magic != MAGIC:
        raise StegError("未找到本工具生成的 AES 隐写数据")
    if version != VERSION:
        raise StegError(f"不支持的格式版本：{version}")
    if layout_version != LAYOUT_VERSION:
        raise StegError(f"不支持的布局版本：{layout_version}")
    if mode not in (MODE_PASSWORD, MODE_KEY_FILE):
        raise StegError("未知凭据模式")
    if ciphertext_length < 16:
        raise StegError("密文长度无效")
    return Header(mode, log_n, r, p, salt, nonce, ciphertext_length, core)


def _safe_filename(name: str) -> str:
    reserved = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
    reserved.update(prefix + suffix for prefix in ("COM", "LPT") for suffix in "123456789¹²³")
    if (not isinstance(name, str) or not name or name.endswith((" ", "."))
            or any(c in '<>:"/\\|?*' or ord(c) < 32 for c in name)
            or name.partition(".")[0].rstrip(" ").upper() in reserved):
        raise StegError("隐藏文件名不安全")
    return name


def _metadata_filename(name: str) -> str:
    # Legacy containers can contain POSIX names unsuitable on Windows. Permit
    # authenticated inspection and explicitly named recovery, never auto-save.
    if not name or name in {".", ".."} or "\x00" in name or "/" in name or "\\" in name:
        raise StegError("隐藏文件名不安全")
    return name


def _read_bounded(handle, limit: int, control: OperationControl, stage: str) -> bytes:
    # Callers use unbuffered files: a second pass must not reuse read-ahead data.
    # This detects observable changes; it does not provide a filesystem snapshot.
    initial = os.fstat(handle.fileno())
    start = handle.tell()
    expected = initial.st_size - start
    if expected > limit:
        raise StegError("文件超过资源上限")
    if expected < 0:
        raise InputChangedError()
    source_path = Path(handle.name).absolute()

    def identity(stat):
        result = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)
        # POSIX ctime detects metadata-restored writes; Windows ctime is birth time.
        return result + ((stat.st_ctime_ns,) if os.name != "nt" else ())

    baseline = identity(initial)

    def check_unchanged():
        control.check()
        try:
            unchanged = (identity(os.fstat(handle.fileno())) == baseline
                         and identity(source_path.stat()) == baseline)
        except OSError as exc:
            raise InputChangedError() from exc
        if not unchanged:
            raise InputChangedError()

    data = bytearray()
    control.report(stage, 0, expected)
    check_unchanged()
    while True:
        chunk = handle.read(min(IO_CHUNK, limit - len(data) + 1))
        check_unchanged()
        if not chunk:
            break
        if len(data) + len(chunk) > limit:
            raise InputChangedError()
        data.extend(chunk)
        control.report(stage, len(data), expected)
        check_unchanged()
    if len(data) != expected:
        raise InputChangedError()
    control.report(stage, len(data), len(data))
    check_unchanged()

    # Compare bounded chunks without another full-sized buffer. This also catches
    # ordinary writes when the filesystem has coarse or restored timestamps.
    handle.seek(start)
    control.report("check_input", 0, expected)
    check_unchanged()
    view = memoryview(data)
    for offset in range(0, expected, IO_CHUNK):
        chunk = handle.read(min(IO_CHUNK, expected - offset))
        if chunk != view[offset:offset + len(chunk)] or len(chunk) != min(IO_CHUNK, expected - offset):
            raise InputChangedError()
        control.report("check_input", offset + len(chunk), expected)
        check_unchanged()
    if handle.read(1):
        raise InputChangedError()
    control.report("check_input", expected, expected)
    check_unchanged()
    return bytes(data)


def _build_plaintext(secret_path: Path, *, max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
                     control: OperationControl | None = None) -> tuple[bytes, bool, int, int, str]:
    _validate_limits(max_file_bytes)
    control = _control(control)
    filename = _safe_filename(Path(secret_path).name).encode("utf-8")
    with Path(secret_path).open("rb", buffering=0) as handle:
        data = _read_bounded(handle, max_file_bytes, control, "read")
    digest = hashlib.sha256(data).digest()
    if len(filename) > 65535:
        raise ValueError("UTF-8 文件名过长")

    compressor = zlib.compressobj(level=9)
    parts = []
    control.report("compress", 0, len(data))
    for offset in range(0, len(data), IO_CHUNK):
        parts.append(compressor.compress(data[offset:offset + IO_CHUNK]))
        control.report("compress", min(offset + IO_CHUNK, len(data)), len(data))
    parts.append(compressor.flush())
    compressed = b"".join(parts)
    if len(compressed) < len(data):
        stored = compressed
        compression = COMPRESSION_ZLIB
    else:
        stored = data
        compression = COMPRESSION_NONE

    fixed = INNER_STRUCT.pack(
        INNER_MAGIC,
        INNER_VERSION,
        compression,
        len(filename),
        len(data),
        len(stored),
        digest,
    )
    return fixed + filename + stored, compression == COMPRESSION_ZLIB, len(data), len(stored), digest.hex()


def _parse_plaintext(plaintext: bytes, credential_mode: int, *,
                     max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
                     control: OperationControl | None = None) -> DecodedPayload:
    _validate_limits(max_file_bytes)
    control = _control(control)
    control.report("decompress")
    if len(plaintext) < INNER_STRUCT.size:
        raise StegError("解密后的数据体过短")
    magic, version, compression, name_len, original_size, stored_size, digest = INNER_STRUCT.unpack(
        plaintext[: INNER_STRUCT.size]
    )
    if magic != INNER_MAGIC or version != INNER_VERSION:
        raise StegError("解密后的内部格式无效")
    if compression not in (COMPRESSION_NONE, COMPRESSION_ZLIB):
        raise StegError("未知压缩方式")
    if original_size > max_file_bytes or stored_size > max_file_bytes:
        raise StegError("声明的原始文件过大，超过安全解码上限")

    expected = INNER_STRUCT.size + name_len + stored_size
    if expected != len(plaintext):
        raise StegError("解密后的数据长度不一致")
    name_start = INNER_STRUCT.size
    name_end = name_start + name_len
    try:
        filename = _metadata_filename(plaintext[name_start:name_end].decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise StegError("隐藏文件名不是有效 UTF-8") from exc
    stored = plaintext[name_end:]

    if compression == COMPRESSION_ZLIB:
        decompressor = zlib.decompressobj()
        data = decompressor.decompress(stored, original_size + 1)
        if len(data) > original_size or decompressor.unconsumed_tail:
            raise StegError("压缩数据超过声明的原始大小")
        remaining = original_size - len(data)
        data += decompressor.flush(remaining + 1)
        if (
            len(data) > original_size
            or decompressor.unused_data
            or decompressor.unconsumed_tail
            or not decompressor.eof
        ):
            raise StegError("压缩数据包含异常尾部或未完整结束")
    else:
        data = stored

    if len(data) != original_size:
        raise StegError("解码后文件大小不一致")
    control.report("hash")
    actual_digest = hashlib.sha256(data).digest()
    if not hmac.compare_digest(actual_digest, digest):
        raise StegError("SHA-256 完整性校验失败")

    return DecodedPayload(
        filename=filename,
        data=data,
        original_size=original_size,
        stored_size=stored_size,
        compressed=compression == COMPRESSION_ZLIB,
        sha256_hex=digest.hex(),
        credential_mode=credential_mode,
    )


def _check_pixels(size: tuple[int, int], max_pixels: int) -> None:
    _validate_limits(max_pixels=max_pixels)
    if size[0] * size[1] > max_pixels:
        raise StegError(f"图片像素数超过安全上限 {max_pixels:,}")


def cover_dimensions(path: Path, *, max_pixels: int = DEFAULT_MAX_PIXELS) -> tuple[int, int]:
    """Read dimensions/orientation without decoding the raster."""
    with Image.open(path) as source:
        _check_pixels(source.size, max_pixels)
        width, height = source.size
        if source.getexif().get(274, 1) in (5, 6, 7, 8):
            width, height = height, width
        return width, height


def _open_rgba_bytes(path: Path, *, max_pixels: int = DEFAULT_MAX_PIXELS,
                      max_container_bytes: int | None = None,
                      control: OperationControl | None = None) -> tuple[tuple[int, int], bytearray]:
    control = _control(control)
    try:
        with Path(path).open("rb", buffering=0) as handle:
            reader = _ContainerReader(handle, max_container_bytes)
            with Image.open(reader) as image:
                _check_pixels(image.size, max_pixels)
                control.report("image")
                reader.check()
                rgba = image.convert("RGBA")
                reader.check()
                control.check()
                return rgba.size, bytearray(rgba.tobytes())
    except UnidentifiedImageError as exc:
        raise StegError("载体不是可识别的图片") from exc


def _logical_to_raw_index(logical_position: int) -> int:
    pixel, channel = divmod(logical_position, 3)
    return pixel * 4 + channel


def _embed_bytes(raw_rgba: bytearray, positions: Iterable[int], data: bytes, *,
                 control: OperationControl | None = None) -> None:
    control = _control(control)
    position_iter = iter(positions)
    try:
        for byte_index, value in enumerate(data):
            if byte_index % 4096 == 0:
                control.report("embed", byte_index, len(data))
            for shift in range(7, -1, -1):
                logical = next(position_iter)
                raw_index = _logical_to_raw_index(logical)
                raw_rgba[raw_index] = (raw_rgba[raw_index] & 0xFE) | ((value >> shift) & 1)
        control.report("embed", len(data), len(data))
    except StopIteration as exc:
        raise StegError("嵌入位置不足") from exc


def _extract_bytes(raw_rgba: bytearray, positions: Iterable[int], byte_count: int, *,
                   control: OperationControl | None = None) -> bytes:
    control = _control(control)
    control.report("extract", 0, byte_count)
    result = bytearray(byte_count)
    position_iter = iter(positions)
    try:
        for byte_index in range(byte_count):
            if byte_index % 4096 == 0:
                control.report("extract", byte_index, byte_count)
            value = 0
            for _ in range(8):
                logical = next(position_iter)
                raw_index = _logical_to_raw_index(logical)
                value = (value << 1) | (raw_rgba[raw_index] & 1)
            result[byte_index] = value
        control.report("extract", byte_count, byte_count)
    except StopIteration as exc:
        raise StegError("提取位置不足") from exc
    return bytes(result)


def image_capacity_bytes(width: int, height: int) -> int:
    total_channels = width * height * 3
    if total_channels <= HEADER_BITS:
        return 0
    return (total_channels - HEADER_BITS) // 8


def _resize_for_payload(
    image: Image.Image,
    ciphertext_length: int,
    *,
    max_fill: float,
    max_pixels: int,
) -> Image.Image:
    dimensions = _payload_dimensions(image.size, ciphertext_length, max_fill)
    _check_pixels(dimensions, max_pixels)
    if dimensions == image.size:
        return image.convert("RGBA")
    return image.convert("RGBA").resize(dimensions, Image.Resampling.LANCZOS)


def _payload_dimensions(size: tuple[int, int], ciphertext_length: int,
                        max_fill: float) -> tuple[int, int]:
    if not (0 < max_fill <= 1.0):
        raise ValueError("max_fill 必须在 (0, 1] 范围内")
    width, height = size
    needed_body_bits = ciphertext_length * 8
    required_available_bits = math.ceil(needed_body_bits / max_fill)
    required_total_channels = HEADER_BITS + required_available_bits
    required_pixels = math.ceil(required_total_channels / 3)
    current_pixels = width * height
    if required_pixels <= current_pixels:
        return size
    scale = math.sqrt(required_pixels / current_pixels)
    new_width = max(1, math.ceil(width * scale))
    new_height = max(1, math.ceil(height * scale))
    while image_capacity_bytes(new_width, new_height) * max_fill < ciphertext_length:
        if new_width <= new_height:
            new_width += 1
        else:
            new_height += 1
    return new_width, new_height


def _body_positions(total_channels: int, ciphertext_length: int, layout_key: bytes) -> Iterator[int]:
    available = total_channels - HEADER_BITS
    needed = ciphertext_length * 8
    for relative in iter_scattered_positions(
        total_positions=available,
        needed=needed,
        layout_key=layout_key,
    ):
        yield HEADER_BITS + relative


def _same_path(left: Path, right: Path) -> bool:
    try:
        if os.path.samefile(left, right):
            return True
    except OSError:
        pass
    try:
        return os.path.normcase(str(Path(left).resolve(strict=False))) == os.path.normcase(str(Path(right).resolve(strict=False)))
    except OSError:
        return os.path.normcase(os.path.abspath(left)) == os.path.normcase(os.path.abspath(right))


class PathConflictError(ValueError):
    code = "output_collision"


def validate_operation_paths(*, inputs: Iterable[Path] = (), output: Path | None = None,
                             key_path: Path | None = None, new_key_path: Path | None = None,
                             force: bool = False, force_key: bool = False) -> None:
    """Validate the whole write set before key generation or output creation.

    A force flag only authorizes ordinary destination replacement. It never
    authorizes replacing a source, cover or credential (including aliases).
    """
    protected = tuple(Path(path) for path in inputs if path is not None)
    writes = ((output, force, protected + tuple(p for p in (key_path, new_key_path) if p is not None)),
              (new_key_path, force_key, protected + tuple(p for p in (key_path, output) if p is not None)))
    for value, overwrite, readers in writes:
        if value is None:
            continue
        path = Path(value)
        if (path.drive or path.root) and not path.is_absolute():
            raise ValueError("输出路径不能使用盘符相对或根相对形式")
        _safe_filename(path.name)
        if any(_same_path(path, reader)
               or path.resolve(strict=False) in Path(reader).resolve(strict=False).parents
               or Path(reader).resolve(strict=False) in path.resolve(strict=False).parents
               for reader in readers):
            raise PathConflictError("输出路径不能与输入、载体或密钥文件相同")
        if path.is_dir():
            raise IsADirectoryError("输出路径已是文件夹")
        if os.path.lexists(path) and not overwrite:
            raise FileExistsError(f"输出文件已存在：{path}")


def _protected(credential: Credential, *paths: Path) -> tuple[Path, ...]:
    return tuple(paths) + ((credential.key_path,) if credential.key_path is not None else ())


@dataclass(frozen=True)
class PreflightResult:
    original_size: int
    stored_size: int
    compressed: bool
    ciphertext_bytes: int
    capacity_bytes: int
    image_width: int
    image_height: int
    fill_ratio: float
    fits: bool
    estimated_peak_bytes: int
    resource_level: str
    reason: str
    exact: bool = True
    container_format: str = "png"
    frame_count: int = 1
    output_bytes: int = 0


def is_gif_file(path: Path) -> bool:
    """Signature-only dispatch; processing validates the final captured input."""
    with Path(path).open("rb", buffering=0) as handle:
        return gif_carrier.is_gif(handle.read(6))


def _gif_budget(limit: int | None) -> int:
    value = gif_carrier.DEFAULT_MAX_CONTAINER_BYTES if limit is None else limit
    _check_container_budget(0, value)
    return value


def _gif_saes_header(data: bytes, max_file_bytes: int) -> Header:
    header = _parse_header(data[:HEADER_SIZE])
    if header.ciphertext_length > _ciphertext_limit(max_file_bytes):
        raise StegError("GIF 密文超过处理资源上限")
    return header


def _capture_gif(path: Path, *, max_pixels: int, max_container_bytes: int | None,
                 max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
                 allow_payload: bool = True, require_payload: bool = False,
                 control: OperationControl) -> tuple[bytes, gif_carrier.GifInfo]:
    budget = _gif_budget(max_container_bytes)
    with Path(path).open("rb", buffering=0) as handle:
        reader = _ContainerReader(handle, budget)
        captured = _read_bounded(reader, budget, control, "read_gif")
    try:
        info = gif_carrier.scan(captured, max_pixels=max_pixels, max_container_bytes=budget,
            max_payload_bytes=HEADER_SIZE + _ciphertext_limit(max_file_bytes),
            allow_payload=allow_payload, require_payload=require_payload, check=control.check,
            validate_payload_header=lambda data: HEADER_SIZE + _gif_saes_header(data, max_file_bytes).ciphertext_length)
    except gif_carrier.GifResourceError as exc:
        raise StegError(str(exc)) from exc
    except gif_carrier.GifError as exc:
        raise StegError(str(exc)) from exc
    # Parse and apply animation budgets before a decoder can allocate frame pixels.
    try:
        with Image.open(io.BytesIO(captured)) as image:
            if image.format != "GIF":
                raise StegError("载体不是 GIF")
            for frame in range(info.frame_count):
                control.report("gif_frames", frame, info.frame_count)
                image.seek(frame)
                image.load()
            control.report("gif_frames", info.frame_count, info.frame_count)
    except (UnidentifiedImageError, EOFError, OSError, ValueError) as exc:
        raise StegError("GIF 动画数据无效或被截断") from exc
    return captured, info


def gif_cover_info(path: Path, *, max_pixels: int = DEFAULT_MAX_PIXELS,
                   max_container_bytes: int | None = None,
                   control: OperationControl | None = None) -> gif_carrier.GifInfo:
    """Read validated animation metadata; any returned payload is unauthenticated."""
    _validate_limits(DEFAULT_MAX_FILE_BYTES, max_pixels)
    return _capture_gif(path, max_pixels=max_pixels, max_container_bytes=max_container_bytes,
                        control=_control(control))[1]


def _gif_preflight(info: gif_carrier.GifInfo, cover_bytes: int, plain_bytes: int,
                   original: int, stored: int, compressed: bool, budget: int) -> PreflightResult:
    length = plain_bytes + 16
    capacity = gif_carrier.ciphertext_capacity(cover_bytes, budget, HEADER_SIZE)
    output_bytes = gif_carrier.output_size(cover_bytes, HEADER_SIZE + length)
    estimate = cover_bytes * 3 + output_bytes * 2 + original * 6 + length * 4 + info.width * info.height * 12
    level = "high" if estimate >= 1024**3 else "moderate" if estimate >= 256 * 1024**2 else "low"
    fits = output_bytes <= budget
    return PreflightResult(original, stored, compressed, length, capacity, info.width, info.height,
        length / capacity if capacity else 1.0, fits, estimate, level,
        "" if fits else "container", container_format="gif", frame_count=info.frame_count, output_bytes=output_bytes)


def _hide_gif(cover_path: Path, secret_path: Path, output_path: Path, *, credential: Credential,
              force: bool, verify: bool, max_pixels: int, max_file_bytes: int,
              max_container_bytes: int | None, protected: tuple[Path, ...],
              control: OperationControl) -> HideResult:
    budget = _gif_budget(max_container_bytes)
    captured, info = _capture_gif(cover_path, max_pixels=max_pixels, max_container_bytes=budget,
        max_file_bytes=max_file_bytes, allow_payload=False, control=control)
    plaintext, compressed, original, stored, digest = _build_plaintext(secret_path,
        max_file_bytes=max_file_bytes, control=control)
    plan = _gif_preflight(info, len(captured), len(plaintext), original, stored, compressed, budget)
    if not plan.fits:
        raise ContainerResourceLimitError()
    header = _build_header(credential.mode, os.urandom(16), os.urandom(12), plan.ciphertext_bytes)
    control.report("derive")
    encryption_key, _ = _derive_keys(credential, header)
    control.report("encrypt")
    saes = _serialize_header(header) + AESGCM(encryption_key).encrypt(header.nonce, plaintext, header.core)
    control.report("embed_gif", 0, len(saes))
    output = gif_carrier.embed(captured, info, saes, max_container_bytes=budget, check=control.check)
    control.report("embed_gif", len(saes), len(saes))

    def verify_saved(temp_path: Path) -> None:
        checked = decode_image(temp_path, credential=credential, max_pixels=max_pixels,
            max_file_bytes=max_file_bytes, max_container_bytes=budget, control=control.child("verify"))
        if checked.sha256_hex != digest or checked.original_size != original or checked.filename != secret_path.name:
            raise StegError("保存后自检失败")

    _atomic_write(output_path, output, force=force, protected_paths=protected,
        control=control, verifier=verify_saved if verify else None)
    return HideResult(output_path, info.width, info.height, plan.capacity_bytes,
        plan.ciphertext_bytes, plan.fill_ratio, compressed, original, stored, digest, credential.mode,
        container_format="gif", frame_count=info.frame_count, output_bytes=len(output))


def _decode_gif(path: Path, *, credential: Credential, max_pixels: int,
                 max_file_bytes: int, max_container_bytes: int | None,
                 control: OperationControl) -> DecodedPayload:
    _, info = _capture_gif(path, max_pixels=max_pixels, max_container_bytes=max_container_bytes,
        max_file_bytes=max_file_bytes, require_payload=True, control=control)
    container = info.payload
    header = _gif_saes_header(container, max_file_bytes)
    if len(container) != HEADER_SIZE + header.ciphertext_length:
        raise StegError("GIF 内的 SAES 长度与头部声明不一致")
    control.report("derive")
    key, _ = _derive_keys(credential, header)
    control.report("decrypt")
    try:
        plaintext = AESGCM(key).decrypt(header.nonce, container[HEADER_SIZE:], header.core)
    except InvalidTag as exc:
        raise AuthenticationError("认证失败：口令/密钥错误，或 GIF 加密载荷已损坏") from exc
    return _parse_plaintext(plaintext, header.mode, max_file_bytes=max_file_bytes, control=control)


def preflight_hide(cover_path: Path, secret_path: Path, *, auto_resize: bool = False,
                   max_fill: float = 1.0, max_pixels: int = DEFAULT_MAX_PIXELS,
                   max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
                   max_container_bytes: int | None = None,
                   control: OperationControl | None = None) -> PreflightResult:
    """Perform actual compression; memory usage remains an estimate, not a quota."""
    _validate_limits(max_file_bytes, max_pixels)
    control = _control(control)
    control.report("preflight")
    if is_gif_file(cover_path):
        captured, info = _capture_gif(cover_path, max_pixels=max_pixels,
            max_container_bytes=max_container_bytes, max_file_bytes=max_file_bytes,
            allow_payload=False, control=control)
        plaintext, compressed, original, stored, _ = _build_plaintext(
            secret_path, max_file_bytes=max_file_bytes, control=control)
        return _gif_preflight(info, len(captured), len(plaintext), original, stored,
                              compressed, _gif_budget(max_container_bytes))
    size = cover_dimensions(cover_path, max_pixels=max_pixels)
    plaintext, compressed, original, stored, _ = _build_plaintext(
        secret_path, max_file_bytes=max_file_bytes, control=control)
    length = len(plaintext) + 16
    dimensions = _payload_dimensions(size, length, max_fill) if auto_resize else size
    capacity = image_capacity_bytes(*dimensions)
    pixels = dimensions[0] * dimensions[1]
    reason = "pixels" if pixels > max_pixels else "capacity" if length > capacity else ""
    estimate = pixels * 24 + original * 6 + length * 4 + 64 * 1024**2
    level = "high" if estimate >= 1024**3 else "moderate" if estimate >= 256 * 1024**2 else "low"
    return PreflightResult(original, stored, compressed, length, capacity, *dimensions,
                           length / capacity if capacity else 1.0, not reason,
                           estimate, level, reason)


def hide_file(
    cover_path: Path,
    secret_path: Path,
    output_path: Path,
    *,
    credential: Credential,
    auto_resize: bool = False,
    max_fill: float = 1.0,
    max_pixels: int = DEFAULT_MAX_PIXELS,
    force: bool = False,
    verify: bool = True,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    max_container_bytes: int | None = None,
    control: OperationControl | None = None,
) -> HideResult:
    cover_path = Path(cover_path)
    secret_path = Path(secret_path)
    output_path = Path(output_path)
    gif_input = is_gif_file(cover_path)
    extension = ".gif" if gif_input else ".png"
    if output_path.suffix.lower() != extension:
        raise ValueError(f"输出文件必须使用 {extension} 扩展名")
    protected = _protected(credential, cover_path, secret_path)
    validate_operation_paths(inputs=protected, output=output_path, force=force)
    _validate_limits(max_file_bytes, max_pixels)
    control = _control(control)
    control.report("preflight")
    if gif_input:
        return _hide_gif(cover_path, secret_path, output_path, credential=credential,
            force=force, verify=verify, max_pixels=max_pixels, max_file_bytes=max_file_bytes,
            max_container_bytes=max_container_bytes, protected=protected, control=control)
    size = cover_dimensions(cover_path, max_pixels=max_pixels)
    plaintext, compressed, original_size, stored_size, sha256_hex = _build_plaintext(
        secret_path, max_file_bytes=max_file_bytes, control=control)
    salt = os.urandom(16)
    nonce = os.urandom(12)
    ciphertext_length = len(plaintext) + 16
    dimensions = _payload_dimensions(size, ciphertext_length, max_fill) if auto_resize else size
    _check_pixels(dimensions, max_pixels)
    if ciphertext_length > image_capacity_bytes(*dimensions):
        raise StegError("图片容量不足；请启用自动扩容或使用独立 .saes 加密")
    control.report("encrypt")
    header = _build_header(credential.mode, salt, nonce, ciphertext_length)
    encryption_key, layout_key = _derive_keys(credential, header)
    ciphertext = AESGCM(encryption_key).encrypt(nonce, plaintext, header.core)
    if len(ciphertext) != ciphertext_length:
        raise AssertionError("AES-GCM 密文长度异常")

    try:
        with Image.open(cover_path) as source:
            if source.format == "GIF":
                raise InputChangedError()
            _check_pixels(source.size, max_pixels)
            control.report("image")
            source = ImageOps.exif_transpose(source)
            if auto_resize:
                rgba = _resize_for_payload(
                    source,
                    ciphertext_length,
                    max_fill=max_fill,
                    max_pixels=max_pixels,
                )
            else:
                rgba = source.convert("RGBA")
    except UnidentifiedImageError as exc:
        raise StegError("载体不是可识别的图片") from exc

    width, height = rgba.size
    if width * height > max_pixels:
        raise StegError(f"图片像素数超过安全上限 {max_pixels:,}")
    total_channels = width * height * 3
    capacity = image_capacity_bytes(width, height)
    if ciphertext_length > capacity:
        raise StegError(
            f"图片容量不足：密文需要 {ciphertext_length:,} 字节，可用 {capacity:,} 字节；可加 --auto-resize"
        )

    raw = bytearray(rgba.tobytes())
    serialized_header = _serialize_header(header)
    _embed_bytes(raw, range(HEADER_BITS), serialized_header)
    _embed_bytes(raw, _body_positions(total_channels, ciphertext_length, layout_key), ciphertext, control=control)

    control.report("save")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    out = Image.frombytes("RGBA", (width, height), bytes(raw))
    fd, temp_name = tempfile.mkstemp(
        prefix=".moyle-",
        suffix=".png",
        dir=output_path.parent,
    )
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        out.save(temp_path, format="PNG")
        with temp_path.open("rb+") as handle:
            os.fsync(handle.fileno())
        if verify:
            decoded = decode_image(temp_path, credential=credential, max_pixels=max_pixels,
                                   max_file_bytes=max_file_bytes, control=control.child("verify"))
            if decoded.sha256_hex != sha256_hex or decoded.original_size != original_size:
                raise StegError("保存后自检失败")
        _commit_temp(temp_path, output_path, force=force, protected_paths=protected, control=control)
    except BaseException:
        try:
            temp_path.unlink()
        except OSError:
            pass
        raise

    return HideResult(
        output_path=output_path,
        image_width=width,
        image_height=height,
        capacity_bytes=capacity,
        ciphertext_bytes=ciphertext_length,
        fill_ratio=ciphertext_length / capacity if capacity else 1.0,
        compressed=compressed,
        original_size=original_size,
        stored_size=stored_size,
        sha256_hex=sha256_hex,
        credential_mode=credential.mode,
    )


def _read_header_from_raw(raw: bytearray, width: int, height: int) -> Header:
    total_channels = width * height * 3
    if total_channels < HEADER_BITS:
        raise StegError("图片太小，无法包含本工具的头部")
    serialized = _extract_bytes(raw, range(HEADER_BITS), HEADER_SIZE)
    return _parse_header(serialized)


def peek_header(image_path: Path, *, max_pixels: int = DEFAULT_MAX_PIXELS,
                max_container_bytes: int | None = None,
                control: OperationControl | None = None) -> Header:
    if is_gif_file(image_path):
        _, info = _capture_gif(image_path, max_pixels=max_pixels, max_container_bytes=max_container_bytes,
            require_payload=True, control=_control(control))
        return _gif_saes_header(info.payload, DEFAULT_MAX_FILE_BYTES)
    (width, height), raw = _open_rgba_bytes(Path(image_path), max_pixels=max_pixels,
        max_container_bytes=max_container_bytes, control=control)
    return _read_header_from_raw(raw, width, height)


def decode_image(image_path: Path, *, credential: Credential,
                 max_pixels: int = DEFAULT_MAX_PIXELS, max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
                 max_container_bytes: int | None = None,
                 control: OperationControl | None = None) -> DecodedPayload:
    _validate_limits(max_file_bytes, max_pixels)
    control = _control(control)
    if is_gif_file(image_path):
        return _decode_gif(image_path, credential=credential, max_pixels=max_pixels,
            max_file_bytes=max_file_bytes, max_container_bytes=max_container_bytes, control=control)
    (width, height), raw = _open_rgba_bytes(Path(image_path), max_pixels=max_pixels,
        max_container_bytes=max_container_bytes, control=control)
    header = _read_header_from_raw(raw, width, height)
    total_channels = width * height * 3
    available_bytes = image_capacity_bytes(width, height)
    if header.ciphertext_length > available_bytes:
        raise StegError("头部声明的密文长度超过图片容量")
    if header.ciphertext_length > _ciphertext_limit(max_file_bytes):
        raise StegError("密文超过资源上限")

    control.report("derive")
    encryption_key, layout_key = _derive_keys(credential, header)
    ciphertext = _extract_bytes(
        raw,
        _body_positions(total_channels, header.ciphertext_length, layout_key),
        header.ciphertext_length,
        control=control,
    )
    control.report("decrypt")
    try:
        plaintext = AESGCM(encryption_key).decrypt(header.nonce, ciphertext, header.core)
    except InvalidTag as exc:
        raise AuthenticationError("认证失败：口令/密钥错误，或图片像素已被修改") from exc
    return _parse_plaintext(plaintext, header.mode, max_file_bytes=max_file_bytes, control=control)


def extract_file(
    image_path: Path,
    output_path: Path | None,
    *,
    credential: Credential,
    force: bool = False,
    max_pixels: int = DEFAULT_MAX_PIXELS,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    max_container_bytes: int | None = None,
    control: OperationControl | None = None,
) -> tuple[Path, DecodedPayload]:
    image_path = Path(image_path)
    protected = _protected(credential, image_path)
    validate_operation_paths(inputs=protected, output=output_path, force=force)
    decoded = decode_image(image_path, credential=credential, max_pixels=max_pixels,
                           max_file_bytes=max_file_bytes, max_container_bytes=max_container_bytes,
                           control=control)
    destination = Path(output_path) if output_path is not None else Path(_safe_filename(decoded.filename))
    _atomic_write(destination, decoded.data, force=force, protected_paths=protected, control=control)
    return destination, decoded


# Standalone AES file-container helpers.


@dataclass(frozen=True)
class EncryptResult:
    output_path: Path
    ciphertext_bytes: int
    compressed: bool
    original_size: int
    stored_size: int
    sha256_hex: str
    credential_mode: int
    algorithm: str = "AES-256-GCM"


def _commit_temp(temp_path: Path, path: Path, *, force: bool = False,
                 protected_paths: Iterable[Path] = (), control: OperationControl | None = None) -> None:
    control = _control(control)
    control.report("commit")
    validate_operation_paths(inputs=protected_paths, output=path, force=force)
    # Cancellation stops before this point. After publication success is final.
    # Windows rename never replaces an existing destination, including exFAT.
    # POSIX link is an atomic create-if-absent; unsupported filesystems fail safely.
    if force:
        os.replace(temp_path, path)
    elif os.name == "nt":
        os.rename(temp_path, path)
    else:
        os.link(temp_path, path)
        temp_path.unlink()


def _atomic_write(path: Path, data: bytes, *, force: bool = False,
                   protected_paths: Iterable[Path] = (),
                   control: OperationControl | None = None,
                   verifier: Callable[[Path], None] | None = None,
                   file_mode: int | None = None) -> None:
    path = Path(path)
    protected_paths = tuple(protected_paths)
    validate_operation_paths(inputs=protected_paths, output=path, force=force)
    control = _control(control)
    control.report("save", 0, len(data))
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".moyle-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            for offset in range(0, len(data), IO_CHUNK):
                handle.write(data[offset:offset + IO_CHUNK])
                control.report("save", min(offset + IO_CHUNK, len(data)), len(data))
            handle.flush()
            os.fsync(handle.fileno())
        if file_mode is not None:
            # Finalize key permissions before publication so cancellation here
            # still cleans the temporary file and preserves an existing key.
            try:
                Path(temp_name).chmod(file_mode)
            except OSError:
                pass
        if verifier is not None:
            control.report("verify")
            verifier(Path(temp_name))
        _commit_temp(Path(temp_name), path, force=force, protected_paths=protected_paths, control=control)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def encrypt_file(
    source_path: Path,
    output_path: Path,
    *,
    credential: Credential,
    force: bool = False,
    verify: bool = True,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    control: OperationControl | None = None,
) -> EncryptResult:
    """Encrypt a file into a standalone authenticated .saes container."""
    source_path = Path(source_path)
    output_path = Path(output_path)
    protected = _protected(credential, source_path)
    validate_operation_paths(inputs=protected, output=output_path, force=force)
    control = _control(control)

    plaintext, compressed, original_size, stored_size, sha256_hex = _build_plaintext(
        source_path, max_file_bytes=max_file_bytes, control=control)
    salt = os.urandom(16)
    nonce = os.urandom(12)
    ciphertext_length = len(plaintext) + 16
    header = _build_header(credential.mode, salt, nonce, ciphertext_length)
    control.report("encrypt")
    encryption_key, _layout_key = _derive_keys(credential, header)
    ciphertext = AESGCM(encryption_key).encrypt(nonce, plaintext, header.core)
    def verify_saved(temp_path: Path) -> None:
        checked = decode_encrypted_file(temp_path, credential=credential,
                                        max_file_bytes=max_file_bytes, control=control.child("verify"))
        if checked.sha256_hex != sha256_hex or checked.original_size != original_size:
            raise StegError("保存后自检失败")
    container = _serialize_header(header) + ciphertext
    _atomic_write(output_path, container, force=force, protected_paths=protected,
                  control=control, verifier=verify_saved if verify else None)

    return EncryptResult(
        output_path=output_path,
        ciphertext_bytes=ciphertext_length,
        compressed=compressed,
        original_size=original_size,
        stored_size=stored_size,
        sha256_hex=sha256_hex,
        credential_mode=credential.mode,
    )


def _checked_container_header(handle, max_file_bytes: int) -> Header:
    _validate_limits(max_file_bytes)
    header = _parse_header(handle.read(HEADER_SIZE))
    if header.ciphertext_length > _ciphertext_limit(max_file_bytes):
        raise StegError("密文超过资源上限")
    if os.fstat(handle.fileno()).st_size != HEADER_SIZE + header.ciphertext_length:
        raise StegError("加密文件长度与头部声明不一致")
    return header


def peek_encrypted_header(encrypted_path: Path, *, max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
                          max_container_bytes: int | None = None,
                          control: OperationControl | None = None) -> Header:
    encrypted_path = Path(encrypted_path)
    _control(control).check()
    with encrypted_path.open("rb", buffering=0) as handle:
        reader = _ContainerReader(handle, max_container_bytes)
        return _checked_container_header(reader, max_file_bytes)


def decode_encrypted_file(encrypted_path: Path, *, credential: Credential,
                          max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
                          max_container_bytes: int | None = None,
                          control: OperationControl | None = None) -> DecodedPayload:
    encrypted_path = Path(encrypted_path)
    control = _control(control)
    with encrypted_path.open("rb", buffering=0) as handle:
        reader = _ContainerReader(handle, max_container_bytes)
        header = _checked_container_header(reader, max_file_bytes)
        ciphertext = _read_bounded(reader, header.ciphertext_length, control, "read")
        reader.check()
    if len(ciphertext) != header.ciphertext_length:
        raise StegError("加密文件长度与头部声明不一致")
    control.report("decrypt")
    encryption_key, _layout_key = _derive_keys(credential, header)
    try:
        plaintext = AESGCM(encryption_key).decrypt(header.nonce, ciphertext, header.core)
    except InvalidTag as exc:
        raise AuthenticationError("认证失败：口令/密钥错误，或加密文件已损坏") from exc
    return _parse_plaintext(plaintext, header.mode, max_file_bytes=max_file_bytes, control=control)


def decrypt_encrypted_file(
    encrypted_path: Path,
    output_path: Path | None,
    *,
    credential: Credential,
    force: bool = False,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    max_container_bytes: int | None = None,
    control: OperationControl | None = None,
) -> tuple[Path, DecodedPayload]:
    encrypted_path = Path(encrypted_path)
    protected = _protected(credential, encrypted_path)
    validate_operation_paths(inputs=protected, output=output_path, force=force)
    decoded = decode_encrypted_file(encrypted_path, credential=credential,
                                    max_file_bytes=max_file_bytes, max_container_bytes=max_container_bytes,
                                    control=control)
    destination = Path(output_path) if output_path is not None else Path(_safe_filename(decoded.filename))
    _atomic_write(destination, decoded.data, force=force, protected_paths=protected, control=control)
    return destination, decoded


def _format_bytes(value: int) -> str:
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    number = float(value)
    for unit in units:
        if number < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(number):,} B"
            return f"{number:,.2f} {unit}"
        number /= 1024
    return f"{value:,} B"


def _mode_name(mode: int) -> str:
    return "口令（scrypt）" if mode == MODE_PASSWORD else "256-bit 密钥文件"


def _key_fingerprint(key: bytes) -> str:
    digest = hashlib.sha256(b"PNG-STEG-AES256/key-fingerprint/" + key).hexdigest()
    return "-".join(digest[index : index + 4] for index in range(0, 20, 4))


def _add_credential_arguments(parser: argparse.ArgumentParser, *, allow_new_key: bool) -> None:
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--key-file", type=Path, help="本工具生成的 256-bit .stegkey 文件")
    group.add_argument(
        "--password",
        help="直接提供口令（会进入终端历史；更推荐省略后交互输入）",
    )
    if allow_new_key:
        group.add_argument(
            "--new-key-file",
            type=Path,
            help="自动生成新 256-bit 密钥文件，并立即用于本次操作",
        )


def _credential_for_write(args: argparse.Namespace) -> tuple[Credential, Path | None, str | None]:
    if getattr(args, "force_key", False):
        raise ValueError("组合任务只允许新建密钥，不支持 --force-key；替换已有密钥请单独使用 keygen --force，并先备份旧密钥")
    inputs = tuple(value for name in ("source", "secret", "cover")
                   if (value := getattr(args, name, None)) is not None)
    output = getattr(args, "output", None)
    if output is None and getattr(args, "source", None) is not None:
        output = _default_encrypted_output(args.source)
    validate_operation_paths(inputs=inputs, output=output,
                             key_path=getattr(args, "key_file", None),
                             new_key_path=getattr(args, "new_key_file", None),
                             force=getattr(args, "force", False),
                             force_key=False)
    for path in inputs:
        if not Path(path).is_file():
            raise FileNotFoundError("所选输入文件不存在")
    max_file_bytes = getattr(args, "max_file_bytes", DEFAULT_MAX_FILE_BYTES)
    _validate_limits(max_file_bytes, getattr(args, "max_pixels", DEFAULT_MAX_PIXELS))
    source = getattr(args, "source", None) or getattr(args, "secret", None)
    if source is not None:
        _safe_filename(Path(source).name)
        if Path(source).stat().st_size > max_file_bytes:
            raise StegError("文件超过资源上限")
    if getattr(args, "command", None) == "hide":
        gif_input = is_gif_file(args.cover)
        extension = ".gif" if gif_input else ".png"
        if output.suffix.lower() != extension:
            raise ValueError(f"输出文件必须使用 {extension} 扩展名")
        if gif_input:
            _capture_gif(args.cover, max_pixels=args.max_pixels,
                max_container_bytes=getattr(args, "max_container_bytes", None),
                max_file_bytes=max_file_bytes, allow_payload=False, control=OperationControl())
        else:
            cover_dimensions(args.cover, max_pixels=args.max_pixels)
    if getattr(args, "new_key_file", None) is not None:
        key_path: Path = args.new_key_file
        key = generate_key_file(key_path, force=False,
                                protected_paths=inputs + ((output,) if output is not None else ()))
        return Credential(MODE_KEY_FILE, key, key_path.absolute()), key_path, _key_fingerprint(key)
    if getattr(args, "key_file", None) is not None:
        credential = Credential.from_key_file(args.key_file)
        return credential, args.key_file, _key_fingerprint(credential.secret)
    if getattr(args, "password", None) is not None:
        return Credential.from_password(args.password), None, None

    first = getpass.getpass("输入加密口令（不会回显）：")
    second = getpass.getpass("再次输入加密口令：")
    if first != second:
        raise ValueError("两次输入的口令不一致")
    return Credential.from_password(first), None, None


def _credential_for_read(args: argparse.Namespace, expected_mode: int) -> tuple[Credential, Path | None, str | None]:
    if getattr(args, "key_file", None) is not None:
        credential = Credential.from_key_file(args.key_file)
        return credential, args.key_file, _key_fingerprint(credential.secret)
    if getattr(args, "password", None) is not None:
        return Credential.from_password(args.password), None, None

    if expected_mode == MODE_PASSWORD:
        return Credential.from_password(getpass.getpass("输入解密口令（不会回显）：")), None, None
    key_text = input("输入 .stegkey 密钥文件路径：").strip().strip('"')
    if not key_text:
        raise ValueError("未提供密钥文件")
    key_path = Path(key_text)
    credential = Credential.from_key_file(key_path)
    return credential, key_path, _key_fingerprint(credential.secret)


def _default_encrypted_output(source: Path) -> Path:
    return source.with_name(source.name + ".saes")


def _print_payload(decoded: DecodedPayload) -> None:
    print(f"文件名：{decoded.filename}")
    print(f"原始大小：{_format_bytes(decoded.original_size)}")
    print(f"加密前存储大小：{_format_bytes(decoded.stored_size)}")
    print(f"预压缩：{'是（zlib）' if decoded.compressed else '否'}")
    print(f"凭据模式：{_mode_name(decoded.credential_mode)}")
    print(f"SHA-256：{decoded.sha256_hex}")
    print("AES-GCM 认证与 SHA-256 校验：通过")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="AES-256-GCM 文件加密 + PNG LSB 隐写 / GIF 动画扩展载体",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("--version", action="version", version="png-steg-aes256 1.5.1 (format v1; GIF extension 001)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p = subparsers.add_parser("keygen", help="生成随机 256-bit 密钥文件")
    p.add_argument("output", type=Path)
    p.add_argument("--force", action="store_true", help="覆盖已有密钥文件")

    p = subparsers.add_parser("capacity", help="查看 PNG 像素容量 / GIF 容器预算容量")
    p.add_argument("image", type=Path)

    p = subparsers.add_parser("encrypt", help="仅做 AES-256-GCM 文件加密，输出 .saes")
    p.add_argument("source", type=Path)
    p.add_argument("output", type=Path, nargs="?", help="默认：源文件名.saes")
    _add_credential_arguments(p, allow_new_key=True)
    p.add_argument("--force", action="store_true", help="覆盖已有输出")
    p.add_argument("--force-key", action="store_true", help="已禁用：组合任务只能新建密钥；替换密钥请单独使用 keygen --force")

    p = subparsers.add_parser("decrypt", help="解密独立 .saes 文件")
    p.add_argument("encrypted", type=Path)
    p.add_argument("output", type=Path, nargs="?", help="默认恢复原文件名")
    _add_credential_arguments(p, allow_new_key=False)
    p.add_argument("--force", action="store_true", help="覆盖已有输出")

    p = subparsers.add_parser("hide", help="加密文件到 PNG 像素 / 可播放 GIF 应用扩展")
    p.add_argument("cover", type=Path)
    p.add_argument("secret", type=Path)
    p.add_argument("output", type=Path)
    _add_credential_arguments(p, allow_new_key=True)
    p.add_argument("--auto-resize", action="store_true", help="仅 PNG：容量不足时保持比例自动放大载体；GIF 不改变尺寸")
    p.add_argument(
        "--max-fill",
        type=float,
        default=0.75,
        help="自动放大后的最大主体容量占用率，默认 0.75",
    )
    p.add_argument(
        "--max-pixels",
        type=int,
        default=DEFAULT_MAX_PIXELS,
        help=f"允许处理的最大像素数，默认 {DEFAULT_MAX_PIXELS:,}",
    )
    p.add_argument("--force", action="store_true", help="覆盖已有输出")
    p.add_argument("--force-key", action="store_true", help="已禁用：组合任务只能新建密钥；替换密钥请单独使用 keygen --force")

    p = subparsers.add_parser("info", help="验证并查看 PNG/GIF 内的加密文件信息")
    p.add_argument("image", type=Path)
    _add_credential_arguments(p, allow_new_key=False)

    p = subparsers.add_parser("extract", help="从 PNG/GIF 提取、认证并解密文件")
    p.add_argument("image", type=Path)
    p.add_argument("output", type=Path, nargs="?", help="默认恢复原文件名")
    _add_credential_arguments(p, allow_new_key=False)
    p.add_argument("--force", action="store_true", help="覆盖已有输出")

    for name, command in subparsers.choices.items():
        if name != "keygen":
            command.add_argument("--max-file-bytes", type=int, default=DEFAULT_MAX_FILE_BYTES,
                                 help="原始文件资源上限（字节），默认 256 MiB")
        if name in {"capacity", "info", "extract"}:
            command.add_argument("--max-pixels", type=int, default=DEFAULT_MAX_PIXELS,
                                 help="图片像素资源上限，默认 25,000,000")
        if name in {"capacity", "hide", "info", "extract"}:
            command.add_argument("--max-container-bytes", type=int, default=None,
                                 help="完整容器字节预算；GIF 默认 64 MiB，输出包含扩展开销")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    generated_key_path = None

    def report_retained_key():
        if generated_key_path is not None:
            print(f"本次新建的密钥已保留：{generated_key_path}。请妥善备份；重试请使用 --key-file 指向它。", file=sys.stderr)

    try:
        if args.command == "keygen":
            key = generate_key_file(args.output, force=args.force)
            print(f"已生成密钥文件：{args.output}")
            print("密钥长度：256 bit")
            print(f"密钥指纹：{_key_fingerprint(key)}")
            print("密钥文件一旦丢失，使用它加密的数据无法恢复。不要与隐写图片只保存在同一位置。")
            return 0

        if args.command == "capacity":
            if is_gif_file(args.image):
                info = gif_cover_info(args.image, max_pixels=args.max_pixels,
                                      max_container_bytes=args.max_container_bytes)
                if info.payload is not None:
                    raise StegError("载体已含 MoyleSteg 载荷；请选择原始 GIF")
                capacity = gif_carrier.ciphertext_capacity(info.trailer_offset + 1,
                                                          _gif_budget(args.max_container_bytes), HEADER_SIZE)
                print(f"GIF 尺寸：{info.width} × {info.height}；帧数：{info.frame_count}")
                print(f"当前容器预算下可用 AES 密文容量：{_format_bytes(capacity)}")
                print("方式：GIF89a 应用扩展封装 SAES；不修改动画像素、帧时序或尺寸。")
                return 0
            try:
                width, height = cover_dimensions(args.image, max_pixels=args.max_pixels)
            except UnidentifiedImageError as exc:
                raise StegError("不是可识别的图片") from exc
            capacity = image_capacity_bytes(width, height)
            print(f"图片尺寸：{width} × {height}")
            print(f"可用 AES 密文容量：{_format_bytes(capacity)}")
            print(f"固定引导头：{HEADER_SIZE} 字节，占用 {HEADER_BITS} 个 RGB 通道")
            print("算法：RGB 每通道 1 LSB；Alpha 不修改")
            return 0

        if args.command == "encrypt":
            credential, key_path, fingerprint = _credential_for_write(args)
            if args.new_key_file is not None:
                generated_key_path = key_path.absolute()
            output = args.output or _default_encrypted_output(args.source)
            result = encrypt_file(
                args.source,
                output,
                credential=credential,
                force=args.force,
                max_file_bytes=args.max_file_bytes,
            )
            print(f"已生成 AES 加密文件：{result.output_path}")
            print(f"算法：{result.algorithm}")
            print(f"凭据模式：{_mode_name(result.credential_mode)}")
            if key_path is not None:
                print(f"密钥文件：{key_path}")
                print(f"密钥指纹：{fingerprint}")
            print(f"原始大小：{_format_bytes(result.original_size)}")
            print(f"加密前存储大小：{_format_bytes(result.stored_size)}")
            print(f"密文大小：{_format_bytes(result.ciphertext_bytes)}")
            print(f"预压缩：{'是（zlib）' if result.compressed else '否'}")
            print(f"SHA-256：{result.sha256_hex}")
            print("保存后解密自检：通过")
            return 0

        if args.command == "decrypt":
            header = peek_encrypted_header(args.encrypted, max_file_bytes=args.max_file_bytes)
            credential, key_path, fingerprint = _credential_for_read(args, header.mode)
            output, decoded = decrypt_encrypted_file(
                args.encrypted,
                args.output,
                credential=credential,
                force=args.force,
                max_file_bytes=args.max_file_bytes,
            )
            print(f"已解密：{output}")
            if key_path is not None:
                print(f"密钥文件：{key_path}")
                print(f"密钥指纹：{fingerprint}")
            _print_payload(decoded)
            return 0

        if args.command == "hide":
            credential, key_path, fingerprint = _credential_for_write(args)
            if args.new_key_file is not None:
                generated_key_path = key_path.absolute()
            result = hide_file(
                args.cover,
                args.secret,
                args.output,
                credential=credential,
                auto_resize=args.auto_resize,
                max_fill=args.max_fill,
                max_pixels=args.max_pixels,
                max_file_bytes=args.max_file_bytes,
                force=args.force,
                max_container_bytes=args.max_container_bytes,
            )
            print(f"已生成加密载体 {result.container_format.upper()}：{result.output_path}")
            print(f"算法：{result.algorithm}")
            print(f"凭据模式：{_mode_name(result.credential_mode)}")
            if key_path is not None:
                print(f"密钥文件：{key_path}")
                print(f"密钥指纹：{fingerprint}")
            print(f"输出尺寸：{result.image_width} × {result.image_height}")
            print(f"原始文件：{_format_bytes(result.original_size)}")
            print(f"加密前存储大小：{_format_bytes(result.stored_size)}")
            print(f"AES-GCM 密文：{_format_bytes(result.ciphertext_bytes)}")
            print(f"图片可用容量：{_format_bytes(result.capacity_bytes)}")
            print(f"容量占用率：{result.fill_ratio:.2%}")
            print(f"预压缩：{'是（zlib）' if result.compressed else '否'}")
            print(f"SHA-256：{result.sha256_hex}")
            if result.container_format == "gif":
                print(f"动画帧数：{result.frame_count}；完整输出：{_format_bytes(result.output_bytes)}")
                print("SAES 密文已封装到 GIF 应用扩展；动画字节保持，不使用像素 LSB。")
            else:
                print("主体密文已按独立布局密钥随机分散到全图 RGB 通道；Alpha 未修改。")
            print("保存后提取、AES-GCM 认证和 SHA-256 自检：通过")
            return 0

        if args.command == "info":
            header = peek_header(args.image, max_pixels=args.max_pixels, max_container_bytes=args.max_container_bytes)
            credential, key_path, fingerprint = _credential_for_read(args, header.mode)
            decoded = decode_image(args.image, credential=credential, max_pixels=args.max_pixels,
                                   max_file_bytes=args.max_file_bytes, max_container_bytes=args.max_container_bytes)
            if key_path is not None:
                print(f"密钥文件：{key_path}")
                print(f"密钥指纹：{fingerprint}")
            _print_payload(decoded)
            return 0

        if args.command == "extract":
            header = peek_header(args.image, max_pixels=args.max_pixels, max_container_bytes=args.max_container_bytes)
            credential, key_path, fingerprint = _credential_for_read(args, header.mode)
            output, decoded = extract_file(
                args.image,
                args.output,
                credential=credential,
                force=args.force,
                max_pixels=args.max_pixels,
                max_file_bytes=args.max_file_bytes,
                max_container_bytes=args.max_container_bytes,
            )
            print(f"已提取并解密：{output}")
            if key_path is not None:
                print(f"密钥文件：{key_path}")
                print(f"密钥指纹：{fingerprint}")
            _print_payload(decoded)
            return 0

        parser.error("未知命令")
        return 2
    except (StegError, OSError, ValueError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        report_retained_key()
        return 2
    except KeyboardInterrupt:
        print("\n操作已取消。", file=sys.stderr)
        report_retained_key()
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
