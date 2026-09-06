package com.moyle.steg.core

import kotlin.math.ceil
import kotlin.math.floor
import kotlin.math.sqrt

/** Applies only to the original carrier, before any authenticated bits are embedded. */
internal object CoverExpansion {
    private const val OVERHEAD = 1024L * 1024

    fun plan(image: RgbaImage, coverBytes: Int, ciphertextBytes: Int, originalBytes: Int,
             compressed: Boolean, autoExpand: Boolean, limits: Limits): Preflight {
        val oldPixels = image.width.toLong() * image.height
        var width = image.width
        var height = image.height
        val insufficient = ciphertextBytes > StegEngine.capacity(width, height)
        if (autoExpand && insufficient) {
            // ceil(ciphertext / 0.90), with exact integer arithmetic; the header is separate.
            val requiredCapacity = (ciphertextBytes.toLong() * 10 + 8) / 9
            val requiredPixels = (requiredCapacity * 8 + Header.BITS + 2) / 3
            demand(requiredPixels <= limits.maxPixels,
                "自动扩容所需像素超过处理预算；请使用独立 SAES，或改用资源充足的设备。")
            val scale = sqrt(requiredPixels.toDouble() / oldPixels)
            val plannedWidth = ceil(image.width * scale).toLong()
            val plannedHeight = ceil(image.height * scale).toLong()
            demand(plannedWidth in image.width.toLong()..Int.MAX_VALUE.toLong() &&
                plannedHeight in image.height.toLong()..Int.MAX_VALUE.toLong() &&
                plannedWidth * plannedHeight <= limits.maxPixels.toLong(),
                "保持载体比例后的扩容尺寸超过像素预算；请使用独立 SAES。")
            width = plannedWidth.toInt()
            height = plannedHeight.toInt()
            demand(StegEngine.capacity(width, height).toLong() * 9 >= ciphertextBytes.toLong() * 10,
                "无法在处理预算内规划足够的载体容量。")
        }
        val expanded = width != image.width || height != image.height
        val pixels = width.toLong() * height
        val rowBytes = width.toLong() * 4 + 1
        val rawBytes = pixels * 4
        // zlib's conservative compressBound formula, including PNG framing. The encoder
        // separately enforces its actual compressed size and working buffers as they grow.
        val scanBytes = rowBytes * height
        val encodedBound = scanBytes + (scanBytes shr 12) + (scanBytes shr 14) + (scanBytes shr 25) + 13 + 57
        val oldImageBytes = if (expanded) image.rgba.size.toLong() else 0L
        val estimate = coverBytes.toLong() + oldImageBytes + rawBytes + rowBytes + 32768 +
            6L * minOf(encodedBound, limits.maxContainerBytes.toLong()) + OVERHEAD
        if (expanded) {
            demand(rowBytes <= limits.maxPngRowBytes,
                "扩容后的 PNG 单行缓冲超过处理预算；请使用独立 SAES。")
            demand(estimate <= limits.maxPngWorkingBytes,
                "自动扩容预计超过 PNG 内存预算；请使用独立 SAES，或减小秘密文件。")
            // The old decoded image, input and packed payload already exist at this point.
            checkHeap(estimate - coverBytes - image.rgba.size + 2L * ciphertextBytes)
        }
        return Preflight(width, height, StegEngine.capacity(width, height), ciphertextBytes,
            originalBytes, compressed, image.width, image.height, estimate)
    }

    private fun checkHeap(additional: Long) {
        val runtime = Runtime.getRuntime()
        val used = runtime.totalMemory() - runtime.freeMemory()
        val reserve = minOf(16L * 1024 * 1024, runtime.maxMemory() / 8)
        demand(additional <= runtime.maxMemory() - used - reserve,
            "自动扩容超过当前可用内存预算；请关闭其他任务或使用独立 SAES。")
    }

    /** Bilinear interpolation in premultiplied-alpha space, with one destination array. */
    fun resize(source: RgbaImage, plan: Preflight, control: Control): RgbaImage {
        if (!plan.expanded) return source
        control.report("扩容载体", 0, plan.height)
        val size = plan.width.toLong() * plan.height * 4
        demand(size <= Int.MAX_VALUE, "扩容像素缓冲过大。")
        checkHeap(size)
        val destination = ByteArray(size.toInt())
        try {
            for (y in 0 until plan.height) {
                control.report("扩容载体", y, plan.height)
                val sy = ((y + 0.5) * source.height / plan.height - 0.5).coerceIn(0.0, (source.height - 1).toDouble())
                val y0 = floor(sy).toInt()
                val y1 = minOf(y0 + 1, source.height - 1)
                val fy = sy - y0
                for (x in 0 until plan.width) {
                    if (x % 4096 == 0) control.check()
                    val sx = ((x + 0.5) * source.width / plan.width - 0.5).coerceIn(0.0, (source.width - 1).toDouble())
                    val x0 = floor(sx).toInt()
                    val x1 = minOf(x0 + 1, source.width - 1)
                    val fx = sx - x0
                    val p00 = (y0 * source.width + x0) * 4
                    val p10 = (y0 * source.width + x1) * 4
                    val p01 = (y1 * source.width + x0) * 4
                    val p11 = (y1 * source.width + x1) * 4
                    val w00 = (1 - fx) * (1 - fy)
                    val w10 = fx * (1 - fy)
                    val w01 = (1 - fx) * fy
                    val w11 = fx * fy
                    val a00 = source.rgba[p00 + 3].toInt() and 255
                    val a10 = source.rgba[p10 + 3].toInt() and 255
                    val a01 = source.rgba[p01 + 3].toInt() and 255
                    val a11 = source.rgba[p11 + 3].toInt() and 255
                    val alpha = a00 * w00 + a10 * w10 + a01 * w01 + a11 * w11
                    val output = (y * plan.width + x) * 4
                    destination[output + 3] = (alpha + 0.5).toInt().coerceIn(0, 255).toByte()
                    for (channel in 0..2) {
                        val c00 = source.rgba[p00 + channel].toInt() and 255
                        val c10 = source.rgba[p10 + channel].toInt() and 255
                        val c01 = source.rgba[p01 + channel].toInt() and 255
                        val c11 = source.rgba[p11 + channel].toInt() and 255
                        // Preserve interpolated hidden RGB if all contributing pixels are transparent.
                        val value = if (alpha > 0) (c00 * a00 * w00 + c10 * a10 * w10 +
                            c01 * a01 * w01 + c11 * a11 * w11) / alpha
                        else c00 * w00 + c10 * w10 + c01 * w01 + c11 * w11
                        destination[output + channel] = (value + 0.5).toInt().coerceIn(0, 255).toByte()
                    }
                }
            }
            control.report("扩容载体", plan.height, plan.height)
            return RgbaImage(plan.width, plan.height, destination)
        } catch (e: Throwable) {
            destination.fill(0)
            throw e
        }
    }
}
