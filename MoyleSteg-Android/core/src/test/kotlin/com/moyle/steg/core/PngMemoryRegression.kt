package com.moyle.steg.core

import java.io.ByteArrayOutputStream
import java.nio.ByteBuffer
import java.util.zip.CRC32
import java.util.zip.Deflater

/** Run each large-image case in its own -Xmx128m JVM. Fixtures are synthetic. */
object PngMemoryRegression {
    @JvmStatic fun main(args: Array<String>) {
        when (args.singleOrNull() ?: "wide") {
            "wide" -> {
                val png = zeroPng(12_000_000, 1)
                check(png.size < 50_000)
                rejected("wide image decode") { PngCodec.decode(png) }
                rejected("wide image preflight") { PngCodec.dimensions(png, Limits()) }
                rejected("wide image with raised limits but insufficient heap") {
                    PngCodec.decode(png, Limits(maxPngRowBytes = 64 * 1024 * 1024, maxPngWorkingBytes = 256L * 1024 * 1024))
                }
                println("PASS extreme-width PNG is rejected with a controlled resource error")
            }
            "normal" -> {
                val image = PngCodec.decode(zeroPng(4000, 3000))
                check(image.width == 4000 && image.height == 3000)
                check(image.rgba.size == 48_000_000 && image.rgba.all { it == 0.toByte() })
                println("PASS ordinary 12-megapixel image is supported in a 128 MiB heap")
            }
            "budgets" -> {
                val png = zeroPng(64, 64)
                rejected("row budget") { PngCodec.decode(png, Limits(maxPngRowBytes = 256)) }
                rejected("working budget") { PngCodec.decode(png, Limits(maxPngWorkingBytes = 1024L * 1024)) }
                val image = PngCodec.decode(png, Limits(maxPngRowBytes = 257, maxPngWorkingBytes = 2L * 1024 * 1024))
                check(image.rgba.size == 64 * 64 * 4)
                println("PASS independent row and working-memory budgets enforce their boundaries")
            }
            "filters" -> {
                for (channels in listOf(3, 4)) for (filter in 0..4) {
                    val w = 7; val h = 5
                    val samples = ByteArray(w * h * channels) { ((it * 29 + it / 7) and 255).toByte() }
                    val rows = ByteArrayOutputStream()
                    for (y in 0 until h) {
                        rows.write(filter)
                        for (i in 0 until w * channels) {
                            val index = y * w * channels + i
                            val left = if (i >= channels) samples[index - channels].toInt() and 255 else 0
                            val up = if (y > 0) samples[index - w * channels].toInt() and 255 else 0
                            val corner = if (y > 0 && i >= channels) samples[index - w * channels - channels].toInt() and 255 else 0
                            val predictor = when (filter) {
                                0 -> 0; 1 -> left; 2 -> up; 3 -> (left + up) / 2
                                else -> {
                                    val p = left + up - corner
                                    val a = kotlin.math.abs(p - left); val b = kotlin.math.abs(p - up); val c = kotlin.math.abs(p - corner)
                                    if (a <= b && a <= c) left else if (b <= c) up else corner
                                }
                            }
                            rows.write((samples[index].toInt() and 255) - predictor)
                        }
                    }
                    val compressed = ByteArrayOutputStream()
                    java.util.zip.DeflaterOutputStream(compressed).use { it.write(rows.toByteArray()) }
                    val decoded = PngCodec.decode(pngBytes(w, h, channels, compressed.toByteArray()))
                    for (pixel in 0 until w * h) {
                        for (channel in 0..2) check(decoded.rgba[pixel * 4 + channel] == samples[pixel * channels + channel])
                        check(decoded.rgba[pixel * 4 + 3] == if (channels == 4) samples[pixel * channels + 3] else 255.toByte())
                    }
                }
                println("PASS RGB and RGBA preserve exact pixels through all five PNG filters")
            }
            "encode" -> {
                val image = RgbaImage(64, 64, ByteArray(64 * 64 * 4))
                rejected("encoding row budget") { PngCodec.encode(image, Limits(maxPngRowBytes = 256)) }
                rejected("encoding working budget") { PngCodec.encode(image, Limits(maxPngWorkingBytes = 1024L * 1024)) }
                check(PngCodec.decode(PngCodec.encode(image)).rgba.contentEquals(image.rgba))
                println("PASS encoder uses row and working budgets and preserves round-trip bytes")
            }
            else -> error("Unknown case")
        }
    }

    private fun rejected(label: String, action: () -> Unit) {
        try {
            action()
        } catch (e: StegException) {
            check("预算" in e.message.orEmpty()) { "$label returned an unrelated error: ${e.message}" }
            return
        } catch (e: OutOfMemoryError) {
            throw AssertionError("$label exhausted the heap instead of rejecting before allocation", e)
        }
        error("$label was accepted without a resource guard")
    }

    private fun zeroPng(width: Int, height: Int): ByteArray {
        val compressed = ByteArrayOutputStream()
        val z = Deflater(9)
        val zeros = ByteArray(32 * 1024)
        val buffer = ByteArray(8 * 1024)
        fun drain() { while (!z.needsInput()) { val n = z.deflate(buffer); compressed.write(buffer, 0, n) } }
        try {
            repeat(height) {
                z.setInput(zeros, 0, 1); drain()
                var remaining = width.toLong() * 4
                while (remaining > 0) {
                    val count = minOf(remaining, zeros.size.toLong()).toInt()
                    z.setInput(zeros, 0, count); drain(); remaining -= count
                }
            }
            z.finish()
            while (!z.finished()) { val n = z.deflate(buffer); compressed.write(buffer, 0, n) }
        } finally { z.end() }
        return pngBytes(width, height, 4, compressed.toByteArray())
    }

    private fun pngBytes(width: Int, height: Int, channels: Int, compressed: ByteArray): ByteArray {
        val output = ByteArrayOutputStream()
        output.write(byteArrayOf(137.toByte(), 80, 78, 71, 13, 10, 26, 10))
        fun chunk(name: String, bytes: ByteArray) {
            val type = name.toByteArray(Charsets.US_ASCII)
            output.write(ByteBuffer.allocate(4).putInt(bytes.size).array())
            output.write(type); output.write(bytes)
            output.write(ByteBuffer.allocate(4).putInt(CRC32().apply { update(type); update(bytes) }.value.toInt()).array())
        }
        chunk("IHDR", ByteBuffer.allocate(13).putInt(width).putInt(height).put(8).put(if (channels == 4) 6.toByte() else 2.toByte()).put(0).put(0).put(0).array())
        chunk("IDAT", compressed); chunk("IEND", byteArrayOf())
        return output.toByteArray()
    }
}
