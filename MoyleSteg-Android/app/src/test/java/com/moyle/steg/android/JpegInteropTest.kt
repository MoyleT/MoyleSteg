package com.moyle.steg.android

import com.moyle.steg.core.*
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import java.io.File

/** Native Android JPEG decoding on the host, with independent Windows/Python fixtures. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class JpegInteropTest {
    private fun read(path: String) = javaClass.classLoader!!.getResourceAsStream("jpeg/$path")!!.use { it.readBytes() }

    @Test fun allJpegVariantsProduceV1PngForDesktopRecoveryAndDecodeDesktopOutputs() {
        val output = File("build/jpeg-interop").absoluteFile.apply { check(isDirectory || mkdirs()) }
        val data = read("interop/source.bin")
        val password = String(read("interop/password.txt"), Charsets.UTF_8).trimEnd('\r', '\n')
        val keyFile = read("interop/synthetic.stegkey")
        val rows = String(read("interop/cases.tsv"), Charsets.UTF_8).trim().lines().drop(1)
        var generated = 0
        for (row in rows) {
            val fields = row.split('\t')
            val name = fields[0]
            val expectedDimensions = fields[1].toInt() to fields[2].toInt()
            val suffix = if (name in listOf("progressive", "grayscale")) "jpeg" else "jpg"
            val jpeg = read("$name.$suffix")
            for (mode in listOf("key", "password")) {
                (if (mode == "key") Credential.keyFile(keyFile) else Credential.password(password)).use { credential ->
                    val engine = StegEngine()
                    // Consume the actual Windows-produced PNG, independent of Android's JPEG decoder.
                    val windowsPng = read("interop/${name}_$mode.png")
                    val fromWindows = engine.decode(windowsPng, credential)
                    try {
                        assertEquals("jpeg-互通.bin", fromWindows.filename)
                        assertArrayEquals(data, fromWindows.data)
                    } finally { fromWindows.data.fill(0) }
                    val pixels = JpegCarrier.decode(jpeg, Limits(), Control(), data.size.toLong())
                    assertEquals(expectedDimensions, pixels.width to pixels.height)
                    val png = engine.hidePixels(pixels, jpeg.size, "jpeg-互通.bin", data, credential)
                    assertTrue(pixels.rgba.all { it == 0.toByte() })
                    assertTrue(PngCodec.isPng(png))
                    assertEquals(expectedDimensions, PngCodec.dimensions(png, Limits()))
                    val saved = File(output, "${name}_$mode.png")
                    saved.writeBytes(png)
                    val roundtrip = engine.decode(saved.readBytes(), credential)
                    try { assertArrayEquals(data, roundtrip.data) } finally { roundtrip.data.fill(0) }
                    generated++
                }
            }
        }
        assertEquals(22, generated)
    }
}
