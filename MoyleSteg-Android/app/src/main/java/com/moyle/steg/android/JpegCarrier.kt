package com.moyle.steg.android

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import androidx.exifinterface.media.ExifInterface
import com.moyle.steg.core.CancelledException
import com.moyle.steg.core.Control
import com.moyle.steg.core.Limits
import com.moyle.steg.core.RgbaImage
import com.moyle.steg.core.StegException
import java.io.ByteArrayInputStream
import java.io.InputStream

data class JpegHeaderInfo(val width: Int, val height: Int, val orientation: Int,
                          val storedWidth: Int, val storedHeight: Int)

/** Original JPEG carriers only. Never use Bitmap decoding on a recovery input. */
object JpegCarrier {
    const val PROBE_LIMIT = 1024 * 1024
    private const val OVERHEAD = 2L * 1024 * 1024
    private const val HEAP_RESERVE = 16L * 1024 * 1024

    fun isJpeg(bytes: ByteArray): Boolean = bytes.size >= 3 &&
        bytes[0] == (-1).toByte() && bytes[1] == 0xd8.toByte() && bytes[2] == (-1).toByte()

    /** Borrow the stream; inspect at most 1 MiB without allocating any pixel buffer. */
    fun probe(input: InputStream, control: Control = Control()): JpegHeaderInfo? {
        control.check()
        val prefix = ByteArray(PROBE_LIMIT)
        var count = 0
        try {
            while (count < prefix.size) {
                control.check()
                val n = input.read(prefix, count, minOf(65536, prefix.size - count))
                if (n < 0) break
                if (n == 0) return null
                count += n
                try {
                    val header = structure(prefix, count, false, control)
                    return info(prefix, header, control)
                } catch (_: IncompleteHeader) {
                    // The next bounded chunk may contain the remaining header.
                }
            }
            return null
        } catch (e: CancelledException) { throw e }
        catch (_: StegException) { return null }
        finally { prefix.fill(0) }
    }

    /**
     * Return oriented opaque RGBA; its owner must clear the array when finished.
     * Budget includes captured JPEG, other retained inputs, native decoding,
     * the Bitmap, RGBA and a row buffer. Estimates never reserve memory.
     */
    fun decode(bytes: ByteArray, limits: Limits, control: Control,
               retainedBytes: Long = 0): RgbaImage {
        control.report("检查 JPEG 文件头")
        requireJpeg(bytes.size <= limits.maxContainerBytes, "JPEG 载体容器超过字节预算。")
        requireJpeg(retainedBytes >= 0 && retainedBytes <= Long.MAX_VALUE - bytes.size,
            "JPEG 内存预算估计无效。")
        val resident = retainedBytes + bytes.size
        admit(resident, OVERHEAD, limits)
        var bitmap: Bitmap? = null
        var rgba: ByteArray? = null
        var row: IntArray? = null
        try {
            val header = try { structure(bytes, bytes.size, false, control) }
                catch (_: IncompleteHeader) { throw StegException("JPEG 文件头已截断。") }
            val pixels = header.width.toLong() * header.height
            requireJpeg(pixels in 1..limits.maxPixels.toLong() && pixels * 4 <= Int.MAX_VALUE,
                "JPEG 载体像素超过处理预算。")
            val dimensions = info(bytes, header, control)
            requireJpeg(maxOf(dimensions.width, dimensions.storedWidth).toLong() * 4 + 1 <= limits.maxPngRowBytes,
                "JPEG 转换所需的单行缓冲超过内存预算。")
            // 4 B/pixel each for Bitmap and RGBA, plus conservative progressive
            // coefficient/native workspace allowance up to a further 8 B/pixel.
            val rowBytes = dimensions.storedWidth.toLong() * 4
            admit(resident, pixels * 16 + rowBytes + OVERHEAD, limits)
            val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true; inScaled = false }
            BitmapFactory.decodeByteArray(bytes, 0, bytes.size, bounds)
            control.check()
            requireJpeg(bounds.outWidth == dimensions.storedWidth && bounds.outHeight == dimensions.storedHeight &&
                bounds.outMimeType == "image/jpeg", "JPEG 文件头与原生解码尺寸不一致，或格式不受支持。")
            try { structure(bytes, bytes.size, true, control) }
            catch (_: IncompleteHeader) { throw StegException("JPEG 文件已截断。") }
            control.report("解码 JPEG 载体")
            admit(resident, pixels * 16 + rowBytes + OVERHEAD, limits)
            val options = BitmapFactory.Options().apply {
                inPreferredConfig = Bitmap.Config.ARGB_8888
                inScaled = false
                inSampleSize = 1
                inMutable = false
            }
            bitmap = BitmapFactory.decodeByteArray(bytes, 0, bytes.size, options)
                ?: throw StegException("无法解码 JPEG 载体，文件可能损坏或格式不受支持。")
            control.check()
            val decoded = bitmap
            requireJpeg(decoded.width == dimensions.storedWidth && decoded.height == dimensions.storedHeight &&
                decoded.config == Bitmap.Config.ARGB_8888, "JPEG 原生解码结果与已检查的格式不一致。")
            admit(resident + decoded.allocationByteCount.toLong(), pixels * 4 + rowBytes + OVERHEAD, limits)
            rgba = ByteArray((pixels * 4).toInt())
            row = IntArray(dimensions.storedWidth)
            val output = rgba
            val colors = row
            val width = dimensions.storedWidth
            val height = dimensions.storedHeight
            for (y in 0 until height) {
                control.report("整理 JPEG 方向", y, height)
                decoded.getPixels(colors, 0, width, 0, y, width, 1)
                for (x in 0 until width) {
                    if (x % 4096 == 0) control.check()
                    val dx: Int; val dy: Int
                    when (dimensions.orientation) {
                        2 -> { dx = width - 1 - x; dy = y }
                        3 -> { dx = width - 1 - x; dy = height - 1 - y }
                        4 -> { dx = x; dy = height - 1 - y }
                        5 -> { dx = y; dy = x }
                        6 -> { dx = height - 1 - y; dy = x }
                        7 -> { dx = height - 1 - y; dy = width - 1 - x }
                        8 -> { dx = y; dy = width - 1 - x }
                        else -> { dx = x; dy = y }
                    }
                    val index = (dy * dimensions.width + dx) * 4
                    val color = colors[x]
                    output[index] = (color shr 16).toByte()
                    output[index + 1] = (color shr 8).toByte()
                    output[index + 2] = color.toByte()
                    output[index + 3] = 0xff.toByte()
                }
            }
            control.report("整理 JPEG 方向", height, height)
            val image = RgbaImage(dimensions.width, dimensions.height, output)
            rgba = null
            return image
        } catch (e: OutOfMemoryError) {
            throw StegException("JPEG 解码期间可用内存不足，请关闭其他任务或使用更小的原始载体。", e)
        } catch (e: IllegalArgumentException) {
            throw StegException("JPEG 原生解码失败，载体可能损坏或格式不受支持。", e)
        } finally {
            row?.fill(0)
            rgba?.fill(0)
            bitmap?.recycle()
        }
    }

    private fun info(bytes: ByteArray, header: Header, control: Control): JpegHeaderInfo {
        control.check()
        val orientation = if (!header.exif) 1 else try {
            // Entropy, auxiliary images and trailer data are not needed for EXIF.
            val exif = ExifInterface(ByteArrayInputStream(bytes, 0, header.end))
            exif.getAttributeInt(ExifInterface.TAG_ORIENTATION, ExifInterface.ORIENTATION_NORMAL)
        } catch (e: Exception) { throw StegException("JPEG EXIF 信息无法读取。", e) }
        control.check()
        val normalized = if (orientation == ExifInterface.ORIENTATION_UNDEFINED) 1 else orientation
        requireJpeg(normalized in 1..8, "JPEG EXIF 方向值无效。")
        return JpegHeaderInfo(if (normalized >= 5) header.height else header.width,
            if (normalized >= 5) header.width else header.height, normalized, header.width, header.height)
    }

    private data class Header(val width: Int, val height: Int, val exif: Boolean, val end: Int)
    private class IncompleteHeader : Exception()

    /** Structural bounds only; entropy decoding remains the platform JPEG codec's job. */
    private fun structure(bytes: ByteArray, count: Int, complete: Boolean, control: Control): Header {
        fun need(offset: Int, length: Int) {
            if (offset < 0 || length < 0 || offset > count - length) throw IncompleteHeader()
        }
        fun u16(offset: Int): Int = ((bytes[offset].toInt() and 255) shl 8) or (bytes[offset + 1].toInt() and 255)
        need(0, 3)
        requireJpeg(isJpeg(bytes), "所选文件不是 JPEG 载体。")
        var pos = 2; var width = 0; var height = 0; var sawScan = false
        var exif = false; var headerEnd = 0; var entropyBytes = 0L
        while (true) {
            control.check()
            need(pos, 2)
            requireJpeg(bytes[pos] == (-1).toByte(), "JPEG 段标记无效。")
            while (pos < count && bytes[pos] == (-1).toByte()) {
                if (pos % 65536 == 0) control.check()
                pos++
            }
            need(pos, 1)
            val marker = bytes[pos++].toInt() and 255
            requireJpeg(marker != 0 && marker != 0xd8 && marker !in 0xd0..0xd7, "JPEG 段顺序无效。")
            if (marker == 0xd9) {
                requireJpeg(sawScan && width > 0 && height > 0 && entropyBytes > 0, "JPEG 缺少完整图像数据。")
                // Camera MPO/UltraHDR or other auxiliary bytes may follow the
                // primary JPEG. Decode its primary image; do not copy metadata.
                return Header(width, height, exif, headerEnd)
            }
            if (marker == 0x01) continue
            need(pos, 2)
            val length = u16(pos)
            requireJpeg(length >= 2, "JPEG 段长度无效。")
            need(pos, length)
            val end = pos + length
            if (marker in 0xc0..0xcf && marker !in listOf(0xc4, 0xc8, 0xcc)) {
                requireJpeg(!sawScan && width == 0 && length >= 11, "JPEG 图像尺寸段无效。")
                val components = bytes[pos + 7].toInt() and 255
                requireJpeg(components in 1..4 && length == 8 + 3 * components, "JPEG 分量数量或尺寸段长度无效。")
                height = u16(pos + 3); width = u16(pos + 5)
                requireJpeg(width > 0 && height > 0, "JPEG 图像尺寸无效。")
            }
            if (!sawScan && marker == 0xe1 && length >= 8 &&
                bytes[pos + 2] == 69.toByte() && bytes[pos + 3] == 120.toByte() &&
                bytes[pos + 4] == 105.toByte() && bytes[pos + 5] == 102.toByte() &&
                bytes[pos + 6] == 0.toByte() && bytes[pos + 7] == 0.toByte()) exif = true
            pos = end
            if (marker != 0xda) continue
            requireJpeg(width > 0 && height > 0 && length >= 8, "JPEG 缺少图像尺寸或扫描头无效。")
            val components = bytes[end - length + 2].toInt() and 255
            requireJpeg(components in 1..4 && length == 6 + 2 * components, "JPEG 扫描段长度无效。")
            if (!sawScan) headerEnd = end
            sawScan = true
            if (!complete) return Header(width, height, exif, headerEnd)
            while (true) {
                if (pos % 65536 == 0) control.check()
                need(pos, 1)
                if (bytes[pos] != (-1).toByte()) { entropyBytes++; pos++; continue }
                val markerStart = pos
                while (pos < count && bytes[pos] == (-1).toByte()) {
                    if (pos % 65536 == 0) control.check()
                    pos++
                }
                need(pos, 1)
                val next = bytes[pos].toInt() and 255
                if (next == 0 || next in 0xd0..0xd7) { entropyBytes++; pos++; continue }
                pos = markerStart
                break
            }
        }
    }

    private fun admit(resident: Long, additional: Long, limits: Limits) {
        requireJpeg(resident >= 0 && additional >= 0 && resident <= Long.MAX_VALUE - additional &&
            resident + additional <= limits.maxPngWorkingBytes, "JPEG 解码估算超过本次内存预算。")
        val runtime = Runtime.getRuntime()
        val available = (runtime.maxMemory() - (runtime.totalMemory() - runtime.freeMemory()) - HEAP_RESERVE).coerceAtLeast(0)
        requireJpeg(additional <= available, "JPEG 解码超过当前可用内存，已保留 16 MiB 余量。")
    }

    private fun requireJpeg(condition: Boolean, message: String) {
        if (!condition) throw StegException(message)
    }
}
