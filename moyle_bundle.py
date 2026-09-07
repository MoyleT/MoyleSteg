"""Bounded interoperable multi-file ZIP payloads for MoyleSteg."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import stat
import struct
import tempfile
import zipfile
import zlib

from png_steg_aes256 import InputChangedError, OperationControl, StegError, _safe_filename

COMMENT = b"MOYLESTEG-BUNDLE-V1"
CHUNK = 64 * 1024
MAX_ENTRIES = 100
MAX_CENTRAL = 128 * 1024
UINT32_MAX = 0xffffffff


class BundleError(StegError):
    """The authenticated payload is not a supported, safe managed ZIP."""
    code = "invalid_bundle"


class BundleResourceError(StegError):
    code = "bundle_resource_limit"


@dataclass(frozen=True)
class BundleSource:
    path: Path
    name: str


@dataclass(frozen=True)
class BundleEntry:
    index: int
    name: str
    size: int
    sha256: str


@dataclass(frozen=True)
class BundleInfo:
    entries: tuple[BundleEntry, ...]
    total_bytes: int
    archive_bytes: int


@dataclass(frozen=True)
class _Member:
    index: int
    name: str
    size: int
    compressed: int
    crc: int
    method: int
    data_offset: int


def _limits(total: int, archive: int) -> None:
    if (type(total) is not int or type(archive) is not int
            or total <= 0 or archive <= 0):
        raise ValueError("Bundle budgets must be positive integers")


def _name(value: str) -> str:
    try:
        _safe_filename(value)
        length = len(value.encode("utf-8", errors="strict"))
    except (StegError, UnicodeError, AttributeError) as exc:
        raise BundleError("多文件包包含不安全的文件名") from exc
    if not 1 <= length <= 180:
        raise BundleError("多文件包文件名超过 180 字节")
    return value


def _identity(value):
    identity = (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)
    return identity + ((value.st_ctime_ns,) if os.name != "nt" else ())


def _guard(handle, path: Path, initial, control: OperationControl) -> None:
    control.check()
    try:
        if (_identity(os.fstat(handle.fileno())) != _identity(initial)
                or _identity(path.stat()) != _identity(initial)):
            raise InputChangedError()
    except OSError as exc:
        raise InputChangedError() from exc


def _read(handle, count: int) -> bytes:
    value = handle.read(count)
    if len(value) != count:
        raise BundleError("多文件包被截断")
    return value


def _has_different_zip_comment(handle, size: int, control: OperationControl) -> bool:
    """A suffix match inside an ordinary ZIP comment does not opt into our format.

    This is only a bounded EOCD probe, not a parser for the ordinary archive's
    entries. Those entries may use ZIP64 or other features this module rejects
    for managed bundles, so do not apply our profile restrictions here.
    """
    start = max(0, size - 65535 - 22)
    handle.seek(start)
    footer = handle.read(min(CHUNK, size - start))
    footer += handle.read(size - start - len(footer))
    control.check()
    cursor = 0
    while True:
        offset = footer.find(b"PK\x05\x06", cursor)
        if offset < 0:
            return False
        cursor = offset + 1
        if offset + 22 <= len(footer):
            length = struct.unpack_from("<H", footer, offset + 20)[0]
            if offset + 22 + length == len(footer) and footer[offset + 22:] != COMMENT:
                return True


def _preflight(handle, *, max_total_bytes: int, max_archive_bytes: int,
               control: OperationControl) -> tuple[tuple[_Member, ...], int] | None:
    """Read only fixed footer and bounded metadata before expanding any entry."""
    size = os.fstat(handle.fileno()).st_size
    tail_size = 22 + len(COMMENT)
    handle.seek(max(0, size - tail_size))
    tail = handle.read(tail_size)
    control.check()
    if not tail.endswith(COMMENT):
        return None
    if tail[:4] != b"PK\x05\x06":
        if _has_different_zip_comment(handle, size, control):
            return None
        handle.seek(0)
        if handle.read(4) != b"PK\x03\x04":
            return None
    if len(tail) != tail_size:
        raise BundleError("多文件包尾部无效")
    sig, disk, cd_disk, count_disk, count, cd_length, cd_offset, comment_length = struct.unpack("<4sHHHHIIH", tail[:22])
    if (sig != b"PK\x05\x06" or disk or cd_disk or count != count_disk
            or not 1 <= count <= MAX_ENTRIES or comment_length != len(COMMENT)
            or not 0 < cd_length <= MAX_CENTRAL or cd_offset == UINT32_MAX
            or cd_offset + cd_length != size - tail_size):
        raise BundleError("多文件包目录无效或格式不受支持")
    if size > max_archive_bytes:
        raise BundleResourceError("多文件包超过容器处理预算")
    handle.seek(cd_offset)
    central = _read(handle, cd_length)
    cursor, local_end, total = 0, 0, 0
    members = []
    for index in range(1, count + 1):
        control.check()
        if cursor + 46 > len(central):
            raise BundleError("多文件包目录被截断")
        fields = struct.unpack_from("<4s6H3I5H2I", central, cursor)
        (signature, made, version, flags, method, mod_time, mod_date, crc,
         compressed, expanded, name_length, extra_length, entry_comment,
         entry_disk, internal_attr, external_attr, offset) = fields
        if (signature != b"PK\x01\x02" or not 10 <= version <= 20 or method not in (0, 8)
                or flags & ~0x0808 or not flags & 0x0800 or extra_length or entry_comment
                or entry_disk or name_length < 6 or name_length > 185
                or expanded == UINT32_MAX or compressed == UINT32_MAX
                or offset != local_end or compressed > cd_offset
                or external_attr & 0x18
                or stat.S_IFMT(external_attr >> 16) not in (0, stat.S_IFREG)):
            raise BundleError("多文件包条目格式不受支持")
        cursor += 46
        if cursor + name_length > len(central):
            raise BundleError("多文件包文件名被截断")
        raw_name = central[cursor:cursor + name_length]
        cursor += name_length
        try:
            full_name = raw_name.decode("utf-8", errors="strict")
        except UnicodeError as exc:
            raise BundleError("多文件包文件名不是有效 UTF-8") from exc
        prefix = f"{index:04d}/"
        if not full_name.startswith(prefix):
            raise BundleError("多文件包条目顺序无效")
        original_name = _name(full_name[5:])
        total += expanded
        if total > max_total_bytes:
            raise BundleResourceError("多文件包展开大小超过处理预算")
        if method == 0 and compressed != expanded:
            raise BundleError("多文件包条目长度不一致")
        if offset + 30 + name_length > cd_offset:
            raise BundleError("多文件包本地目录超出范围")
        handle.seek(offset)
        local = struct.unpack("<4s5H3I2H", _read(handle, 30))
        (local_sig, local_version, local_flags, local_method, local_time, local_date,
         local_crc, local_compressed, local_size, local_name_len, local_extra) = local
        if (local_sig != b"PK\x03\x04" or local_version != version
                or local_flags != flags or local_method != method
                or local_time != mod_time or local_date != mod_date
                or local_name_len != name_length or local_extra
                or _read(handle, name_length) != raw_name):
            raise BundleError("多文件包本地与中央目录不一致")
        data_offset = handle.tell()
        local_end = data_offset + compressed
        if local_end > cd_offset:
            raise BundleError("多文件包数据超出范围")
        expected_fields = (crc, compressed, expanded)
        if flags & 0x0008:
            if ((local_crc, local_compressed, local_size) not in ((0, 0, 0), expected_fields)
                    or local_end + 12 > cd_offset):
                raise BundleError("多文件包数据描述符无效")
            handle.seek(local_end)
            descriptor = _read(handle, 12)
            # A CRC can equal the optional descriptor signature. Prefer a
            # matching unsigned descriptor before consuming four more bytes.
            if struct.unpack("<III", descriptor) == expected_fields:
                local_end += 12
            elif descriptor[:4] == b"PK\x07\x08":
                if local_end + 16 > cd_offset:
                    raise BundleError("多文件包数据描述符被截断")
                descriptor = descriptor[4:] + _read(handle, 4)
                local_end += 16
            else:
                raise BundleError("多文件包数据描述符与目录不一致")
            if struct.unpack("<III", descriptor) != expected_fields:
                raise BundleError("多文件包数据描述符与目录不一致")
        elif (local_crc, local_compressed, local_size) != expected_fields:
            raise BundleError("多文件包本地长度或摘要不一致")
        members.append(_Member(index, original_name, expanded, compressed, crc, method, data_offset))
    if cursor != cd_length or local_end != cd_offset:
        raise BundleError("多文件包包含额外目录或未索引数据")
    return tuple(members), size


def _stream_member(handle, member: _Member, control: OperationControl, sink=None) -> BundleEntry:
    handle.seek(member.data_offset)
    remaining, actual, crc = member.compressed, 0, 0
    digest = hashlib.sha256()
    inflater = zlib.decompressobj(-15) if member.method == 8 else None

    def accept(chunk):
        nonlocal actual, crc
        actual += len(chunk)
        if actual > member.size:
            raise BundleError("多文件包条目展开长度超出声明值")
        digest.update(chunk)
        crc = zlib.crc32(chunk, crc)
        if sink is not None:
            sink.write(chunk)
        control.report("bundle_entry", actual, member.size)

    control.report("bundle_entry", 0, member.size)
    while remaining:
        control.check()
        data = _read(handle, min(CHUNK, remaining))
        remaining -= len(data)
        if inflater is None:
            accept(data)
            continue
        try:
            while data:
                output = inflater.decompress(data, min(CHUNK, member.size - actual + 1))
                data = inflater.unconsumed_tail
                accept(output)
                if inflater.unused_data or (inflater.eof and (data or remaining)):
                    raise BundleError("多文件包压缩数据包含多余字节")
        except zlib.error as exc:
            raise BundleError("多文件包压缩数据损坏") from exc
    if (inflater is not None and not inflater.eof) or actual != member.size or crc & UINT32_MAX != member.crc:
        raise BundleError("多文件包条目长度或 CRC 校验失败")
    return BundleEntry(member.index, member.name, actual, digest.hexdigest())


class _UTF8Info(zipfile.ZipInfo):
    def _encodeFilenameFlags(self):
        return self.filename.encode("utf-8"), self.flag_bits | 0x800


class _LimitedWriter:
    def __init__(self, handle, limit: int, control: OperationControl):
        self.handle, self.limit, self.control = handle, limit, control

    def write(self, value):
        self.control.check()
        if self.handle.tell() + len(value) > self.limit:
            raise BundleResourceError("多文件包超过容器处理预算")
        return self.handle.write(value)

    def __getattr__(self, name):
        return getattr(self.handle, name)


def _remove_owned(path: Path, identity) -> None:
    """Never remove an unrelated file that has replaced our newly created output."""
    try:
        current = path.stat()
        if (current.st_dev, current.st_ino) == identity:
            path.unlink()
    except FileNotFoundError:
        pass


def create_bundle(sources, output: Path, *, max_total_bytes: int, max_archive_bytes: int,
                  control: OperationControl | None = None) -> BundleInfo:
    _limits(max_total_bytes, max_archive_bytes)
    ctl = control or OperationControl()
    items = []
    for source in sources:
        ctl.check()
        if len(items) >= MAX_ENTRIES:
            raise BundleError("最多支持 100 个文件")
        items.append(BundleSource(Path(source.path), _name(source.name)))
    if not items:
        raise BundleError("请至少选择一个文件")
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise FileExistsError(str(output))
    initial_stats, total = [], 0
    for source in items:
        if source.path.resolve() == output.resolve():
            raise BundleError("输出位置不能覆盖输入文件")
        value = source.path.stat()
        if not stat.S_ISREG(value.st_mode):
            raise BundleError("多文件包只支持普通文件")
        total += value.st_size
        if total > max_total_bytes or value.st_size >= UINT32_MAX:
            raise BundleResourceError("多文件包源文件总大小超过处理预算")
        initial_stats.append(value)
    ctl.check()
    owned = None
    expected_entries = []
    try:
        with output.open("xb", buffering=0) as destination:
            output_stat = os.fstat(destination.fileno())
            owned = (output_stat.st_dev, output_stat.st_ino)
            limited = _LimitedWriter(destination, min(max_archive_bytes, UINT32_MAX - 1), ctl)
            with zipfile.ZipFile(limited, "w", compression=zipfile.ZIP_DEFLATED,
                                 compresslevel=6, allowZip64=False) as archive:
                archive.comment = COMMENT
                for index, (source, initial) in enumerate(zip(items, initial_stats), 1):
                    digest, count = hashlib.sha256(), 0
                    info = _UTF8Info(f"{index:04d}/{source.name}", (1980, 1, 1, 0, 0, 0))
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.external_attr = (stat.S_IFREG | 0o600) << 16
                    info.file_size = initial.st_size
                    with source.path.open("rb", buffering=0) as origin:
                        _guard(origin, source.path, initial, ctl)
                        with archive.open(info, "w") as entry:
                            ctl.report("bundle_read", 0, initial.st_size)
                            while True:
                                data = origin.read(min(CHUNK, initial.st_size - count + 1))
                                _guard(origin, source.path, initial, ctl)
                                if not data:
                                    break
                                count += len(data)
                                if count > initial.st_size:
                                    raise InputChangedError()
                                entry.write(data)
                                digest.update(data)
                                ctl.report("bundle_read", count, initial.st_size)
                            if count != initial.st_size:
                                raise InputChangedError()
                        origin.seek(0)
                        checked, check_digest = 0, hashlib.sha256()
                        ctl.report("bundle_check_input", 0, initial.st_size)
                        while checked < initial.st_size:
                            data = origin.read(min(CHUNK, initial.st_size - checked))
                            if not data:
                                raise InputChangedError()
                            checked += len(data)
                            check_digest.update(data)
                            _guard(origin, source.path, initial, ctl)
                            ctl.report("bundle_check_input", checked, initial.st_size)
                        if origin.read(1) or check_digest.digest() != digest.digest():
                            raise InputChangedError()
                        _guard(origin, source.path, initial, ctl)
                    expected_entries.append(BundleEntry(index, source.name, count, digest.hexdigest()))
            destination.flush()
            os.fsync(destination.fileno())
        result = inspect_bundle(output, max_total_bytes=max_total_bytes,
                                max_archive_bytes=max_archive_bytes, control=ctl)
        if result is None or result.entries != tuple(expected_entries):
            raise BundleError("多文件包保存后回读校验失败")
        return result
    except Exception:
        if owned is not None:
            _remove_owned(output, owned)
        raise


def inspect_bundle(path: Path, *, max_total_bytes: int, max_archive_bytes: int,
                   control: OperationControl | None = None) -> BundleInfo | None:
    _limits(max_total_bytes, max_archive_bytes)
    path, ctl = Path(path), control or OperationControl()
    with path.open("rb", buffering=0) as handle:
        initial = os.fstat(handle.fileno())
        _guard(handle, path, initial, ctl)
        parsed = _preflight(handle, max_total_bytes=max_total_bytes,
                            max_archive_bytes=max_archive_bytes, control=ctl)
        if parsed is None:
            return None
        members, archive_bytes = parsed
        entries = []
        for member in members:
            entries.append(_stream_member(handle, member, ctl))
            _guard(handle, path, initial, ctl)
        return BundleInfo(tuple(entries), sum(e.size for e in entries), archive_bytes)


def extract_entry(path: Path, entry: BundleEntry, directory: Path, *,
                  max_total_bytes: int, max_archive_bytes: int,
                  control: OperationControl | None = None) -> Path:
    _limits(max_total_bytes, max_archive_bytes)
    path, directory, ctl = Path(path), Path(directory), control or OperationControl()
    owned = None
    output = None
    try:
        with path.open("rb", buffering=0) as handle:
            initial = os.fstat(handle.fileno())
            _guard(handle, path, initial, ctl)
            parsed = _preflight(handle, max_total_bytes=max_total_bytes,
                                max_archive_bytes=max_archive_bytes, control=ctl)
            if parsed is None:
                raise BundleError("该文件不是多文件包")
            members, _ = parsed
            if not 1 <= entry.index <= len(members):
                raise BundleError("请选择有效的多文件包条目")
            member = members[entry.index - 1]
            if member.name != entry.name or member.size != entry.size:
                raise BundleError("多文件包条目与已验证结果不一致")
            ctl.check()
            descriptor, temp_name = tempfile.mkstemp(prefix="moyle-member-", suffix=".tmp", dir=directory)
            output = Path(temp_name)
            with os.fdopen(descriptor, "wb", buffering=0) as destination:
                output_stat = os.fstat(destination.fileno())
                owned = (output_stat.st_dev, output_stat.st_ino)
                result = _stream_member(handle, member, ctl, destination)
                if result != entry:
                    raise BundleError("多文件包条目 SHA-256 校验失败")
                _guard(handle, path, initial, ctl)
                destination.flush()
                os.fsync(destination.fileno())
            ctl.check()
            return output
    except Exception:
        if output is not None and owned is not None:
            _remove_owned(output, owned)
        raise
