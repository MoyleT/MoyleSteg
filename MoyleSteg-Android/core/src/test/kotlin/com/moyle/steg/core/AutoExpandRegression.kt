package com.moyle.steg.core

import java.io.File
import java.util.Random

/** Synthetic regression coverage for carrier planning, interpolation, limits and roundtrips. */
object AutoExpandRegression {
    @JvmStatic fun main(args: Array<String>) {
        val output = args.firstOrNull()?.let { File(it).apply { mkdirs() } }
        var passed = 0
        fun test(name: String, body: () -> Unit) { body(); passed++; println("PASS $name") }
        fun rejects(fragment: String = "", body: () -> Unit) {
            try { body(); error("input was accepted") }
            catch (e: StegException) { check(e.message.orEmpty().contains(fragment)) { e.message.orEmpty() } }
        }
        fun random(count: Int) = ByteArray(count).also { Random(19).nextBytes(it) }
        fun image(width: Int, height: Int, alpha: Int = 255): RgbaImage =
            RgbaImage(width, height, ByteArray(width * height * 4) { index ->
                if (index % 4 == 3) alpha.toByte() else ((index * 13) % 256).toByte()
            })
        val engine = StegEngine()
        val cover = PngCodec.encode(image(16, 16))
        val before = cover.copyOf()
        val data = random(4096)
        val original = data.copyOf()
        val keyBytes = ByteArray(32) { it.toByte() }
        Credential.key(keyBytes).use { key ->
            test("default preflight reports insufficient capacity without expansion") {
                val p = engine.preflight(cover, "synthetic.bin", data)
                check(!p.fits && !p.expanded && p.width == 16 && p.height == 16)
            }
            test("default and explicitly disabled hide reject insufficient capacity") {
                rejects("容量不足") { engine.hide(cover, "synthetic.bin", data, key) }
                rejects("容量不足") { engine.hide(cover, "synthetic.bin", data, key, autoExpand = false) }
            }
            test("expansion plan fits at most ninety percent and uses final capacity") {
                val p = engine.preflight(cover, "synthetic.bin", data, autoExpand = true)
                check(p.fits && p.expanded && p.originalWidth == 16 && p.originalHeight == 16)
                check(p.width >= 16 && p.height >= 16 && p.width == p.height)
                check(p.capacityBytes == StegEngine.capacity(p.width, p.height))
                check(p.occupancyPercent > 0 && p.occupancyPercent <= 90.0)
                check(p.estimatedWorkingBytes > p.width.toLong() * p.height * 4)
            }
            test("auto-expanded key PNG restores exact original and matches preflight") {
                val p = engine.preflight(cover, "synthetic.bin", data, autoExpand = true)
                val result = engine.hide(cover, "synthetic.bin", data, key, autoExpand = true)
                check(PngCodec.dimensions(result, Limits()) == p.width to p.height)
                val restored = engine.extract(result, key)
                check(restored.filename == "synthetic.bin" && restored.data.contentEquals(data))
                output?.let {
                    File(it, "expanded-key.png").writeBytes(result)
                    File(it, "expanded-source.bin").writeBytes(data)
                    File(it, "synthetic.stegkey").writeBytes(Credential.exportKey(keyBytes))
                }
            }
            test("auto-expanded password PNG remains compatible with the same format") {
                Credential.password("synthetic-autoexpand-password").use { password ->
                    val result = engine.hide(cover, "synthetic.bin", data, password, autoExpand = true)
                    check(engine.extract(result, password).data.contentEquals(data))
                    output?.let { File(it, "expanded-password.png").writeBytes(result) }
                }
            }
            test("cover and payload arrays are never modified") {
                check(cover.contentEquals(before) && data.contentEquals(original))
            }
            test("adequate high-occupancy carrier stays at the original size") {
                val enough = PngCodec.encode(image(64, 64))
                val nearlyFull = random(1350)
                val p = engine.preflight(enough, "synthetic.bin", nearlyFull, autoExpand = true)
                check(p.fits && !p.expanded && p.width == 64 && p.height == 64)
                check(p.occupancyPercent > 90)
                val result = engine.hide(enough, "synthetic.bin", nearlyFull, key, autoExpand = true)
                check(PngCodec.dimensions(result, Limits()) == 64 to 64)
                check(engine.extract(result, key).data.contentEquals(nearlyFull))
            }
            test("adequate carrier skips interpolation and preserves non-LSB samples") {
                val source = image(128, 128, 173)
                val enough = PngCodec.encode(source)
                var resized = false
                val observed = StegEngine(control = Control(progress = { stage, _, _ ->
                    if (stage == "扩容载体") resized = true
                }))
                val result = PngCodec.decode(observed.hide(enough, "synthetic.bin", data, key, true))
                check(!resized)
                for (i in source.rgba.indices) {
                    if (i % 4 == 3) check(result.rgba[i] == source.rgba[i])
                    else check((result.rgba[i].toInt() and 254) == (source.rgba[i].toInt() and 254))
                }
            }
            test("compressible payload uses actual compression and avoids unnecessary expansion") {
                val enough = PngCodec.encode(image(64, 64))
                val p = engine.preflight(enough, "repeated.txt", ByteArray(100_000) { 65 }, true)
                check(p.compressed && p.fits && !p.expanded)
            }
            test("landscape and portrait plans preserve orientation and approximate proportions") {
                for ((w, h) in listOf(64 to 16, 16 to 64)) {
                    val p = engine.preflight(PngCodec.encode(image(w, h)), "synthetic.bin", data, true)
                    check(p.expanded && p.width >= w && p.height >= h)
                    check((p.width > p.height) == (w > h))
                    check(kotlin.math.abs(p.width.toDouble() / p.height - w.toDouble() / h) < 0.05)
                }
            }
            test("one-pixel carrier can grow to fit a complete header and payload") {
                val tiny = PngCodec.encode(image(1, 1))
                val result = engine.hide(tiny, "empty.bin", byteArrayOf(), key, true)
                check(engine.extract(result, key).data.isEmpty())
            }
            test("pixel budget refuses expansion before key derivation") {
                var derived = false
                val limited = StegEngine(Limits(maxPixels = 1024), Control(progress = { stage, _, _ ->
                    if (stage == "派生密钥") derived = true
                }))
                rejects("像素") { limited.preflight(cover, "synthetic.bin", data, true) }
                rejects("像素") { limited.hide(cover, "synthetic.bin", data, key, true) }
                check(!derived)
            }
            test("row budget is checked on planned enlarged dimensions") {
                val limited = StegEngine(Limits(maxPngRowBytes = 100))
                rejects("单行") { limited.preflight(cover, "synthetic.bin", data, true) }
            }
            test("working-set budget includes enlargement and PNG encoding buffers") {
                val limited = StegEngine(Limits(maxPngWorkingBytes = 2L * 1024 * 1024))
                rejects("内存预算") { limited.preflight(cover, "synthetic.bin", random(256 * 1024), true) }
            }
            test("extreme aspect ratio rounding never bypasses maximum pixels") {
                val wide = image(300_000, 1)
                val p = CoverExpansion.plan(wide, 1000, 120_000, 120_000, false, false, Limits(maxPixels = 500_000))
                check(!p.fits)
                rejects("像素") { CoverExpansion.plan(wide, 1000, 120_000, 120_000, false, true, Limits(maxPixels = 500_000)) }
            }
            test("excessive ciphertext lengths are rejected without integer wraparound") {
                rejects("像素") { CoverExpansion.plan(image(1, 1), 1, Int.MAX_VALUE, 1, false, true, Limits()) }
            }
            test("preflight still fully validates carrier PNG before planning") {
                val malformed = cover.copyOf().also { it[it.size - 1] = (it.last().toInt() xor 1).toByte() }
                rejects("CRC") { engine.preflight(malformed, "synthetic.bin", data, true) }
            }
            test("expanded alpha samples match resizing and are not used for embedded bits") {
                val source = image(16, 16, 81)
                val encoded = PngCodec.encode(source)
                val p = engine.preflight(encoded, "synthetic.bin", data, true)
                val resized = CoverExpansion.resize(source, p, Control())
                val result = PngCodec.decode(engine.hide(encoded, "synthetic.bin", data, key, true))
                check(result.width == resized.width && result.height == resized.height)
                for (i in 3 until result.rgba.size step 4) check(result.rgba[i] == resized.rgba[i])
            }
            test("cancellation during resizing stops before key derivation and leaves inputs intact") {
                var cancelled = false
                var derived = false
                val control = Control(progress = { stage, completed, _ ->
                    if (stage == "扩容载体" && completed >= 1) cancelled = true
                    if (stage == "派生密钥") derived = true
                }, cancelled = { cancelled })
                rejects("取消") { StegEngine(control = control).hide(cover, "synthetic.bin", data, key, true) }
                check(cancelled && !derived && cover.contentEquals(before) && data.contentEquals(original))
            }
            test("resize reports monotonically increasing row work and completion") {
                val source = image(2, 2)
                val p = Preflight(5, 7, 0, 0, 0, false, 2, 2)
                val progress = mutableListOf<Pair<Int, Int>>()
                CoverExpansion.resize(source, p, Control(progress = { stage, completed, total ->
                    if (stage == "扩容载体") progress.add(completed to total)
                }))
                check(progress.isNotEmpty() && progress.first() == 0 to 7 && progress.last() == 7 to 7)
                check(progress.zipWithNext().all { (a, b) -> a.first <= b.first && b.second == 7 })
            }
            test("transparent colored neighbor cannot contaminate visible interpolation") {
                val source = RgbaImage(2, 1, byteArrayOf(255.toByte(), 0, 0, 0, 0, 0, 255.toByte(), 255.toByte()))
                val result = CoverExpansion.resize(source, Preflight(5, 1, 0, 0, 0, false, 2, 1), Control())
                check((result.rgba[8].toInt() and 255) == 0)
                check((result.rgba[10].toInt() and 255) == 255)
                check((result.rgba[11].toInt() and 255) == 128)
                check(source.rgba[0] == 255.toByte())
            }
            test("fully transparent RGBA retains interpolated hidden RGB") {
                val source = RgbaImage(1, 1, byteArrayOf(13, 27, 39, 0))
                val result = CoverExpansion.resize(source, Preflight(3, 3, 0, 0, 0, false, 1, 1), Control())
                for (i in result.rgba.indices) check(result.rgba[i] == source.rgba[i % 4])
            }
            for (size in listOf(256 * 1024, 1024 * 1024)) test("default budget supports $size-byte random payload from a small carrier") {
                val randomData = random(size)
                val p = engine.preflight(cover, "synthetic.bin", randomData, true)
                check(p.expanded && p.fits && p.occupancyPercent <= 90 && p.estimatedWorkingBytes <= Limits().maxPngWorkingBytes)
                val result = engine.hide(cover, "synthetic.bin", randomData, key, true)
                check(PngCodec.dimensions(result, Limits()) == p.width to p.height)
                check(engine.extract(result, key).data.contentEquals(randomData))
                println("DETAIL size=$size width=${p.width} height=${p.height} estimate=${p.estimatedWorkingBytes} pngBytes=${result.size}")
            }
        }
        println("$passed auto-expansion checks passed")
    }
}
