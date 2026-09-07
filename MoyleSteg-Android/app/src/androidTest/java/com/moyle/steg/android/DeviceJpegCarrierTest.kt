package com.moyle.steg.android

import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.moyle.steg.core.*
import org.junit.Test
import org.junit.runner.RunWith
import org.junit.Assert.*

/** Run separately on hardware: host/native-graphics tests cannot certify a phone's decoder. */
@RunWith(AndroidJUnit4::class)
class DeviceJpegCarrierTest {
    @Test fun jpegPhotosAndDesktopPngsWorkWithBothCredentialModes() {
        val assets = InstrumentationRegistry.getInstrumentation().context.assets
        fun read(path: String) = assets.open("jpeg/$path").use { it.readBytes() }
        val data = read("interop/source.bin")
        val keyFile = read("interop/synthetic.stegkey")
        val password = String(read("interop/password.txt"), Charsets.UTF_8).trimEnd('\r', '\n')
        for (row in String(read("interop/cases.tsv"), Charsets.UTF_8).trim().lines().drop(1)) {
            val fields = row.split('\t')
            val name = fields[0]
            val dimensions = fields[1].toInt() to fields[2].toInt()
            val extension = if (name in listOf("progressive", "grayscale")) "jpeg" else "jpg"
            for (mode in listOf("key", "password")) {
                (if (mode == "key") Credential.keyFile(keyFile) else Credential.password(password)).use { credential ->
                    val engine = StegEngine()
                    val pc = engine.decode(read("interop/${name}_$mode.png"), credential)
                    try { assertArrayEquals(data, pc.data) } finally { pc.data.fill(0) }
                    val bytes = read("$name.$extension")
                    val image = JpegCarrier.decode(bytes, Limits(), Control(), data.size.toLong())
                    assertEquals(dimensions, image.width to image.height)
                    val png = engine.hidePixels(image, bytes.size, "jpeg-互通.bin", data, credential)
                    assertEquals(dimensions, PngCodec.dimensions(png, Limits()))
                    val restored = engine.decode(png, credential)
                    try { assertEquals("jpeg-互通.bin", restored.filename); assertArrayEquals(data, restored.data) }
                    finally { restored.data.fill(0) }
                }
            }
        }
    }
}
