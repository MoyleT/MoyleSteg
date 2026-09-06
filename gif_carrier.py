"""GIF89a application-extension envelope; never re-encode animation pixels.

Wire: 21 FF 0B 'MOYLESTG' '001', SAES bytes in data sub-blocks, 00.
The application identifier/version is public, not cryptographic authentication.
"""
from dataclasses import dataclass, field
from collections.abc import Callable

IDENTIFIER = b"MOYLESTG"
VERSION = b"001"
EXTENSION_HEADER = b"\x21\xff\x0b" + IDENTIFIER + VERSION
DEFAULT_MAX_CONTAINER_BYTES = 64 * 1024**2
MAX_FRAMES = 500
MAX_TOTAL_PIXELS = 100_000_000


class GifError(ValueError):
    pass


class GifResourceError(GifError):
    pass


@dataclass(frozen=True)
class GifInfo:
    width: int
    height: int
    frame_count: int
    trailer_offset: int
    payload: bytes | None = field(default=None, repr=False)
    payload_start: int | None = None
    payload_end: int | None = None


def is_gif(data: bytes) -> bool:
    return data[:6] in (b"GIF87a", b"GIF89a")


def output_size(cover_size: int, saes_size: int) -> int:
    return cover_size + saes_size + (saes_size + 254) // 255 + 15


def ciphertext_capacity(cover_size: int, container_limit: int, header_size: int = 54) -> int:
    low, high = 0, max(0, container_limit - cover_size)
    while low < high:
        middle = (low + high + 1) // 2
        if output_size(cover_size, header_size + middle) <= container_limit:
            low = middle
        else:
            high = middle - 1
    return low


def _validate_lzw(take, minimum: int, expected: int, colors: int, check) -> None:
    """Check sample counts/palette references with a fixed 4096-entry dictionary."""
    clear, end = 1 << minimum, (1 << minimum) + 1
    lengths, first, maximum = [0] * 4096, [0] * 4096, [0] * 4096
    for i in range(clear):
        lengths[i], first[i], maximum[i] = 1, i, i
    left = accumulator = bits = 0
    ended = False

    def byte():
        nonlocal left, ended
        if ended:
            return -1
        if left == 0:
            left = take(1)[0]
            if left == 0:
                ended = True
                return -1
        left -= 1
        return take(1)[0]

    size, next_code, previous = minimum + 1, end + 1, -1
    produced = codes = 0
    while True:
        if codes % 4096 == 0:
            check()
        codes += 1
        while bits < size:
            b = byte()
            if b < 0:
                raise GifError("GIF LZW 码流缺少结束码或被截断")
            accumulator |= b << bits
            bits += 8
        code = accumulator & ((1 << size) - 1)
        accumulator >>= size
        bits -= size
        if code == clear:
            size, next_code, previous = minimum + 1, end + 1, -1
            continue
        if code == end:
            if produced != expected:
                raise GifError("GIF 解码像素数量与帧尺寸不符")
            if left != 0 or byte() != -1:
                raise GifError("GIF LZW 结束码后含多余数据")
            check()
            return
        if not (code < next_code or (code == next_code and previous >= 0 and next_code < 4096)):
            raise GifError("GIF LZW 码流含无效字典索引")
        if previous < 0 and code >= clear:
            raise GifError("GIF LZW 清除后的首个码必须是颜色索引")
        count = lengths[previous] + 1 if code == next_code else lengths[code]
        start = first[previous] if code == next_code else first[code]
        max_index = maximum[previous] if code == next_code else maximum[code]
        produced += count
        if count <= 0 or produced > expected or max_index >= colors:
            raise GifError("GIF 解码像素数量或颜色索引无效")
        if previous >= 0 and next_code < 4096:
            lengths[next_code] = lengths[previous] + 1
            first[next_code] = first[previous]
            maximum[next_code] = max(maximum[previous], start)
            next_code += 1
            if next_code == (1 << size) and size < 12:
                size += 1
        previous = code


def scan(data: bytes, *, max_pixels: int, max_container_bytes: int = DEFAULT_MAX_CONTAINER_BYTES,
         max_payload_bytes: int | None = None, allow_payload: bool = True,
         require_payload: bool = False, check: Callable[[], None] = lambda: None,
         validate_payload_header: Callable[[bytes], int] | None = None) -> GifInfo:
    if not isinstance(max_container_bytes, int) or isinstance(max_container_bytes, bool) or max_container_bytes <= 0:
        raise GifError("GIF 容器预算必须为正整数")
    if len(data) > max_container_bytes:
        raise GifResourceError("GIF 完整容器超过处理资源上限")
    if not is_gif(data) or len(data) < 14:
        raise GifError("不是完整的 GIF87a/GIF89a 文件")
    width, height = int.from_bytes(data[6:8], "little"), int.from_bytes(data[8:10], "little")
    if width <= 0 or height <= 0:
        raise GifError("GIF 画布尺寸无效")
    if width * height > max_pixels:
        raise GifResourceError("GIF 图片像素超过处理资源上限")
    pos = 13
    payload = None
    payload_start = payload_end = None
    frames = 0
    pending_control = False
    transparent = None
    check()

    def take(count):
        nonlocal pos
        if count < 0 or pos + count > len(data):
            raise GifError("GIF 数据被截断")
        start = pos
        pos += count
        return memoryview(data)[start:pos]

    def subblocks(collect=False):
        buffer = bytearray() if collect else None
        expected = None
        checked_at = pos
        while True:
            size = take(1)[0]
            if size == 0:
                break
            block = take(size)
            if collect:
                limit = max_payload_bytes if max_payload_bytes is not None else max_container_bytes
                if len(buffer) + size > limit:
                    raise GifResourceError("GIF 密文超过处理资源上限")
                buffer.extend(block)
                if expected is None and len(buffer) >= 54 and validate_payload_header is not None:
                    expected = validate_payload_header(bytes(buffer[:54]))
                if expected is not None and len(buffer) > expected:
                    raise GifError("GIF 内的 SAES 长度与头部声明不一致")
            if pos - checked_at >= 65536:
                check()
                checked_at = pos
        check()
        if collect:
            if expected is not None and len(buffer) != expected:
                raise GifError("GIF 内的 SAES 被截断")
            return bytes(buffer)
        return None

    packed = data[10]
    global_colors = 1 << ((packed & 7) + 1) if packed & 0x80 else 0
    if global_colors:
        if data[11] >= global_colors:
            raise GifError("GIF 背景颜色索引无效")
        take(global_colors * 3)
    while True:
        check()
        start = pos
        tag = take(1)[0]
        if tag == 0x3B:
            if pos != len(data):
                raise GifError("GIF Trailer 后含多余数据")
            if pending_control:
                raise GifError("GIF 控制扩展后缺少图像")
            if frames == 0:
                raise GifError("GIF 不含可播放图像")
            if require_payload and payload is None:
                raise GifError("GIF 中没有 MoyleSteg 加密载荷")
            return GifInfo(width, height, frames, start, payload, payload_start, payload_end)
        if tag == 0x2C:
            descriptor = take(9)
            left, top, w, h = (int.from_bytes(descriptor[i:i+2], "little") for i in (0, 2, 4, 6))
            if w <= 0 or h <= 0 or left + w > width or top + h > height or descriptor[8] & 0x18:
                raise GifError("GIF 帧尺寸、位置或保留字段无效")
            frames += 1
            if w * h > max_pixels or frames > MAX_FRAMES or width * height * frames > MAX_TOTAL_PIXELS:
                raise GifResourceError("GIF 动画帧数或总像素超过处理资源上限")
            colors = global_colors
            if descriptor[8] & 0x80:
                colors = 1 << ((descriptor[8] & 7) + 1)
                take(colors * 3)
            if colors == 0 or (transparent is not None and transparent >= colors):
                raise GifError("GIF 帧缺少颜色表或透明索引无效")
            minimum = take(1)[0]
            if not 2 <= minimum <= 8:
                raise GifError("GIF LZW 最小码长无效")
            _validate_lzw(take, minimum, w * h, colors, check)
            pending_control = False
            transparent = None
        elif tag == 0x21:
            label = take(1)[0]
            if label == 0xF9:
                if pending_control or take(1)[0] != 4:
                    raise GifError("GIF 图形控制扩展无效")
                gce = take(4)
                if gce[0] & 0xE0 or ((gce[0] >> 2) & 7) > 3 or take(1)[0] != 0:
                    raise GifError("GIF 图形控制字段或终止符无效")
                pending_control = True
                transparent = gce[3] if gce[0] & 1 else None
            elif label == 0xFF:
                if take(1)[0] != 11:
                    raise GifError("GIF 应用扩展头必须为 11 字节")
                application = bytes(take(11))
                if application[:8] == IDENTIFIER:
                    if not allow_payload:
                        raise GifError("载体已含 MoyleSteg 载荷；请选择原始 GIF")
                    if application[8:] != VERSION:
                        raise GifError("不支持此 GIF MoyleSteg 扩展版本")
                    if payload is not None:
                        raise GifError("GIF 含多个 MoyleSteg 载荷，无法确定恢复目标")
                    payload_start = start
                    payload = subblocks(True)
                    payload_end = pos
                else:
                    subblocks()
            elif label == 0xFE:
                subblocks()
            elif label == 0x01:
                if take(1)[0] != 12:
                    raise GifError("GIF 文本扩展头无效")
                text = take(12)
                left, top, w, h = (int.from_bytes(text[i:i+2], "little") for i in (0, 2, 4, 6))
                if (w <= 0 or h <= 0 or left + w > width or top + h > height or not text[8] or not text[9]
                    or global_colors == 0 or text[10] >= global_colors or text[11] >= global_colors
                    or (transparent is not None and transparent >= global_colors)):
                    raise GifError("GIF 文本扩展尺寸或颜色表无效")
                subblocks()
                pending_control = False
                transparent = None
            else:
                if label == 0:
                    raise GifError("GIF 扩展标签无效")
                subblocks()
        else:
            raise GifError("GIF 数据块标识无效")


def embed(data: bytes, info: GifInfo, saes: bytes, *, max_container_bytes: int,
          check: Callable[[], None] = lambda: None) -> bytes:
    if info.payload is not None:
        raise GifError("载体已含 MoyleSteg 载荷；请选择原始 GIF")
    if output_size(len(data), len(saes)) > max_container_bytes:
        raise GifResourceError("GIF 输出容器超过处理资源上限")
    # Header upgrade is the only change to any existing GIF byte.
    output = bytearray(b"GIF89a")
    view = memoryview(data)
    for offset in range(6, info.trailer_offset, 65536):
        check()
        output.extend(view[offset:min(offset + 65536, info.trailer_offset)])
    output.extend(EXTENSION_HEADER)
    for offset in range(0, len(saes), 255):
        if offset % (255 * 256) == 0:
            check()
        block = saes[offset:offset + 255]
        output.append(len(block))
        output.extend(block)
    output.extend(b"\0;")
    check()
    return bytes(output)
