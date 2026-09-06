package com.moyle.steg.core

/** GIF application-extension carrier. Animation blocks stay byte-for-byte unchanged.
 * The enclosed SAES authenticates the secret, not the surrounding animation. */
object GifCarrier {
    private val ID = "MOYLESTG001".toByteArray(Charsets.US_ASCII)
    private val FAMILY = "MOYLESTG".toByteArray(Charsets.US_ASCII)
    data class Info(val width: Int, val height: Int, val frameCount: Int, val payload: ByteArray?)

    fun isGif(bytes: ByteArray): Boolean = bytes.size >= 6 &&
        bytes[0] == 71.toByte() && bytes[1] == 73.toByte() && bytes[2] == 70.toByte() &&
        bytes[3] == 56.toByte() && (bytes[4] == 55.toByte() || bytes[4] == 57.toByte()) && bytes[5] == 97.toByte()

    fun inspect(bytes: ByteArray, limits: Limits = Limits(), control: Control = Control()): Info =
        parse(bytes, limits, control, false)

    internal fun coverInfo(bytes: ByteArray, limits: Limits, control: Control): Info =
        parse(bytes, limits, control, true)

    /** Includes one 11-byte application identifier, framing, and 1..255-byte data subblocks. */
    internal fun outputSize(coverBytes: Int, saesBytes: Int): Long =
        coverBytes.toLong() + saesBytes + (saesBytes.toLong() + 254) / 255 + 15

    internal fun plan(cover: ByteArray, info: Info, packed: Int, original: Int, compressed: Boolean,
                      limits: Limits): Preflight {
        val cipher = packed + 16
        var low = 0; var high = maxOf(0, limits.maxContainerBytes - cover.size)
        // The capacity field retains its ciphertext-byte meaning across PNG and GIF.
        while (low < high) {
            val mid = low + (high - low + 1) / 2
            if (outputSize(cover.size, Header.SIZE + mid) <= limits.maxContainerBytes) low = mid else high = mid - 1
        }
        val output = outputSize(cover.size, Header.SIZE + cipher)
        return Preflight(info.width, info.height, low, cipher, original, compressed,
            estimatedWorkingBytes = cover.size.toLong() + output + Header.SIZE + cipher + 64 * 1024,
            format = "gif", frameCount = info.frameCount, outputBytes = output)
    }

    /** Called only after complete structural/decoder validation of the cover. */
    internal fun embedValidated(cover: ByteArray, saes: ByteArray, limits: Limits, control: Control): ByteArray {
        val size = outputSize(cover.size, saes.size)
        demand(size <= limits.maxContainerBytes && size <= Int.MAX_VALUE, "GIF 输出容器超过处理预算；请使用独立 SAES。")
        control.check()
        val runtime = Runtime.getRuntime()
        val available = runtime.maxMemory() - (runtime.totalMemory() - runtime.freeMemory())
        demand(size + 64 * 1024 + 16L * 1024 * 1024 <= available,
            "当前可用内存不足以创建 GIF 输出；请使用独立 SAES 或更小的原始载体。")
        val result = ByteArray(size.toInt())
        try {
        var copied = 0
        while (copied < cover.size - 1) {
            control.report("复制 GIF 动画", copied, cover.size - 1)
            val end = minOf(cover.size - 1, copied + 64 * 1024)
            cover.copyInto(result, copied, copied, end); copied = end
        }
        result[4] = 57 // Extensions require GIF89a; the raster/animation blocks stay unchanged.
        var out = cover.size - 1
        result[out++] = 0x21; result[out++] = 0xff.toByte(); result[out++] = 11
        ID.copyInto(result, out); out += ID.size
        var offset = 0
        while (offset < saes.size) {
            control.report("写入 GIF 容器", offset, saes.size)
            val n = minOf(255, saes.size - offset)
            result[out++] = n.toByte(); saes.copyInto(result, out, offset, offset + n)
            out += n; offset += n
        }
        result[out++] = 0; result[out] = 0x3b
        control.report("写入 GIF 容器", saes.size, saes.size)
        return result
        } catch (failure: Throwable) { result.fill(0); throw failure }
    }

    private fun parse(bytes: ByteArray, limits: Limits, control: Control, rejectPayload: Boolean): Info {
        control.check()
        demand(bytes.size <= limits.maxContainerBytes, "完整 GIF 容器超过处理预算；请勿重新保存或优化已有隐写动图。")
        demand(isGif(bytes), "需要有效的 GIF87a 或 GIF89a 文件。")
        val c = Cursor(bytes, control); c.skip(6)
        val width = c.u16(); val height = c.u16(); val packed = c.u8()
        val background = c.u8(); c.u8()
        demand(width > 0 && height > 0 && width.toLong() * height <= limits.maxPixels, "GIF 画布超过像素预算或尺寸无效。")
        val globalColors = if (packed and 0x80 != 0) 1 shl ((packed and 7) + 1) else 0
        if (globalColors > 0) {
            demand(background < globalColors, "GIF 背景颜色索引无效。")
            c.skip(globalColors * 3)
        }
        var frames = 0; var payload: ByteArray? = null
        var pendingControl = false; var transparent: Int? = null
        while (true) {
            control.check()
            when (c.u8()) {
                0x3b -> {
                    demand(c.position == bytes.size, "GIF 结束标记后存在多余数据。")
                    demand(frames > 0, "GIF 不包含可播放的图像帧。")
                    demand(!pendingControl, "GIF 图形控制块没有对应的图像或文本。")
                    return Info(width, height, frames, payload)
                }
                0x2c -> {
                    val left = c.u16(); val top = c.u16(); val w = c.u16(); val h = c.u16(); val flags = c.u8()
                    demand(w > 0 && h > 0 && left + w <= width && top + h <= height, "GIF 帧尺寸或位置无效。")
                    demand(flags and 0x18 == 0, "GIF 图像保留标志无效。")
                    frames++
                    demand(frames <= limits.maxGifFrames && width.toLong() * height * frames <= limits.maxGifTotalPixels &&
                        w.toLong() * h <= limits.maxPixels, "GIF 帧数或累计像素超过处理预算。")
                    val colors = if (flags and 0x80 != 0) (1 shl ((flags and 7) + 1)).also { c.skip(it * 3) } else globalColors
                    demand(colors > 0 && (transparent == null || transparent < colors), "GIF 调色板或透明颜色索引无效。")
                    val minimum = c.u8()
                    demand(minimum in 2..8, "GIF LZW 最小码长无效。")
                    control.report("检查 GIF 帧", frames, 0)
                    validateLzw(c, minimum, w.toLong() * h, colors, control)
                    pendingControl = false; transparent = null
                }
                0x21 -> when (val label = c.u8()) {
                    0xf9 -> {
                        demand(!pendingControl && c.u8() == 4, "GIF 图形控制块长度或顺序无效。")
                        val flags = c.u8(); c.u16(); val index = c.u8()
                        demand(flags and 0xe0 == 0 && ((flags ushr 2) and 7) <= 3 && c.u8() == 0,
                            "GIF 图形控制标志或结束标记无效。")
                        transparent = if (flags and 1 != 0) index else null; pendingControl = true
                    }
                    0xff -> {
                        demand(c.u8() == 11, "GIF 应用扩展标识长度无效。")
                        val id = c.take(11)
                        if (id.copyOfRange(0, 8).contentEquals(FAMILY)) {
                            demand(!rejectPayload, "GIF 已包含 MoyleSteg 载荷；请选择未嵌入秘密的原始动图。")
                            demand(id.contentEquals(ID), "不支持此 MoyleSteg GIF 扩展版本。")
                            demand(payload == null, "GIF 包含重复的 MoyleSteg 载荷。")
                            payload = readPayload(c, limits)
                        } else c.skipSubblocks()
                    }
                    0x01 -> {
                        demand(c.u8() == 12, "GIF 文本扩展长度无效。")
                        val left = c.u16(); val top = c.u16(); val w = c.u16(); val h = c.u16()
                        val cellW = c.u8(); val cellH = c.u8(); val foreground = c.u8(); val back = c.u8()
                        demand(w > 0 && h > 0 && left + w <= width && top + h <= height && cellW > 0 && cellH > 0 &&
                            globalColors > 0 && foreground < globalColors && back < globalColors &&
                            (transparent == null || transparent < globalColors), "GIF 文本扩展尺寸或调色板无效。")
                        c.skipSubblocks(); pendingControl = false; transparent = null
                    }
                    else -> { demand(label != 0, "GIF 扩展标签无效。"); c.skipSubblocks() }
                }
                else -> throw StegException("GIF 含未知顶层块或缺少结束标记。")
            }
        }
    }

    /** Allocates the encrypted payload only after its authenticated-format header budget checks. */
    private fun readPayload(c: Cursor, limits: Limits): ByteArray {
        var result = ByteArray(Header.SIZE); var count = 0; var expected: Int? = null
        while (true) {
            val n = c.u8(); if (n == 0) break
            c.requireBytes(n)
            var remaining = n
            while (remaining > 0) {
                val take = minOf(remaining, result.size - count)
                demand(take > 0, "GIF 内部 SAES 长度与头部不符。")
                c.copyTo(result, count, take); count += take; remaining -= take
                if (expected == null && count == Header.SIZE) {
                    val header = Header.parse(result, limits)
                    expected = Header.SIZE + header.cipherLength
                    demand(expected <= limits.maxContainerBytes, "GIF 内部 SAES 超过处理预算。")
                    MemoryChecks.admit(c.bytes.size.toLong()+result.size,expected.toLong()+MemoryChecks.BUFFER_OVERHEAD,
                        limits,"GIF 密文扩展（${expected} 字节）")
                    result = result.copyOf(expected)
                }
            }
        }
        demand(expected != null && count == expected, "GIF 内部 SAES 被截断或长度不符。")
        return result
    }

    /** Validates dictionary codes and decoded sample counts using bounded 4096-entry tables.
     * No frame or logical-screen pixel buffer is allocated. Interlacing changes only sample order. */
    private fun validateLzw(c: Cursor, minimum: Int, expected: Long, colors: Int, control: Control) {
        val clear = 1 shl minimum; val end = clear + 1
        val lengths = IntArray(4096); val first = IntArray(4096); val maximum = IntArray(4096)
        for (i in 0 until clear) { lengths[i] = 1; first[i] = i; maximum[i] = i }
        val bits = SubblockBits(c)
        var size = minimum + 1; var next = end + 1; var previous = -1
        var produced = 0L; var codes = 0
        while (true) {
            if (codes++ % 4096 == 0) control.check()
            val code = bits.code(size)
            demand(code >= 0, "GIF LZW 码流缺少结束码或被截断。")
            if (code == clear) { size = minimum + 1; next = end + 1; previous = -1; continue }
            if (code == end) {
                demand(produced == expected, "GIF 解码像素数量与帧尺寸不符。")
                bits.finish(); return
            }
            demand(code < next || (code == next && previous >= 0 && next < 4096), "GIF LZW 码流含无效字典索引。")
            demand(previous >= 0 || code < clear, "GIF LZW 清除后的首个码必须是颜色索引。")
            val count = if (code == next) lengths[previous] + 1 else lengths[code]
            val start = if (code == next) first[previous] else first[code]
            val maxIndex = if (code == next) maximum[previous] else maximum[code]
            produced += count
            demand(count > 0 && produced <= expected && maxIndex < colors, "GIF 解码像素数量或颜色索引无效。")
            if (previous >= 0 && next < 4096) {
                lengths[next] = lengths[previous] + 1; first[next] = first[previous]
                maximum[next] = maxOf(maximum[previous], start); next++
                if (next == (1 shl size) && size < 12) size++
            }
            previous = code
        }
    }

    private class Cursor(val bytes: ByteArray, val control: Control) {
        var position = 0; private set
        fun requireBytes(n: Int) { demand(n >= 0 && n <= bytes.size - position, "GIF 文件被截断。"); control.check() }
        fun u8(): Int { requireBytes(1); return bytes[position++].toInt() and 255 }
        fun u16(): Int = u8() or (u8() shl 8)
        fun skip(n: Int) { requireBytes(n); position += n }
        fun take(n: Int): ByteArray { requireBytes(n); return bytes.copyOfRange(position, position + n).also { position += n } }
        fun copyTo(target: ByteArray, offset: Int, n: Int) { requireBytes(n); bytes.copyInto(target, offset, position, position + n); position += n }
        fun skipSubblocks() { while (true) { val n = u8(); if (n == 0) return; skip(n) } }
    }

    private class SubblockBits(val c: Cursor) {
        private var left = 0; private var accumulator = 0; private var count = 0; private var ended = false
        private fun byte(): Int {
            if (ended) return -1
            if (left == 0) { left = c.u8(); if (left == 0) { ended = true; return -1 }; c.requireBytes(left) }
            left--; return c.u8()
        }
        fun code(width: Int): Int {
            while (count < width) { val b = byte(); if (b < 0) return -1; accumulator = accumulator or (b shl count); count += 8 }
            val out = accumulator and ((1 shl width) - 1); accumulator = accumulator ushr width; count -= width; return out
        }
        fun finish() {
            demand(left == 0 && byte() == -1, "GIF LZW 结束码后含多余数据。")
        }
    }
}
