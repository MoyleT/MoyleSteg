package com.moyle.steg.core

/** Decoded carrier API must preserve the same v1 protocol and its buffer ownership contract. */
object PixelCarrierRegression {
    @JvmStatic fun main(args: Array<String>) {
        var passed = 0
        val data = ByteArray(512).also { java.util.Random(61).nextBytes(it) }
        fun image(w: Int = 64, h: Int = 64) = RgbaImage(w, h,
            ByteArray(w * h * 4) { if (it % 4 == 3) 255.toByte() else (it * 13).toByte() })
        fun rejected(block: () -> Unit) {
            try { block(); error("expected rejection") } catch (_: StegException) { passed++ }
        }
        Credential.key(ByteArray(32) { it.toByte() }).use { key ->
            val original = image()
            val png = StegEngine().hidePixels(original, 500, "synthetic.bin", data, key)
            check(original.rgba.all { it == 0.toByte() }); passed++
            check(PngCodec.isPng(png)); passed++
            val restored = StegEngine().decode(png, key)
            check(restored.filename == "synthetic.bin" && restored.data.contentEquals(data)); passed++
            restored.data.fill(0)
            val small = image(8, 8)
            val plan = StegEngine().preflightPixels(small, 50, "synthetic.bin", data, true)
            check(plan.expanded && plan.fits && small.rgba.all { it == 0.toByte() }); passed++
            val expanding = image(8, 8)
            val expanded = StegEngine().hidePixels(expanding, 50, "synthetic.bin", data, key, true)
            check(PngCodec.dimensions(expanded, Limits()) == plan.width to plan.height); passed++
            check(expanding.rgba.all { it == 0.toByte() }); passed++
            val insufficient = image(8, 8)
            rejected { StegEngine().hidePixels(insufficient, 50, "synthetic.bin", data, key) }
            check(insufficient.rgba.all { it == 0.toByte() }); passed++
            val overPixels = image()
            rejected { StegEngine(Limits(maxPixels = 100)).hidePixels(overPixels, 50, "synthetic.bin", data, key) }
            check(overPixels.rgba.all { it == 0.toByte() }); passed++
            rejected { StegEngine().preflightPixels(image(), -1, "synthetic.bin", data) }
            rejected { StegEngine(Limits(maxPngWorkingBytes = 1)).preflightPixels(image(), 50, "synthetic.bin", data) }
            val cancelled = image()
            rejected { StegEngine(control = Control(cancelled = { true })).hidePixels(cancelled, 50, "synthetic.bin", data, key) }
            check(cancelled.rgba.all { it == 0.toByte() }); passed++
        }
        println("Pixel carrier regression: $passed checks passed")
    }
}
