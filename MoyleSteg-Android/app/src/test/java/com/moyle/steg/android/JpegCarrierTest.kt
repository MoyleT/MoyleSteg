package com.moyle.steg.android

import android.graphics.BitmapFactory
import com.moyle.steg.core.CancelledException
import com.moyle.steg.core.Control
import com.moyle.steg.core.Limits
import com.moyle.steg.core.RgbaImage
import com.moyle.steg.core.StegException
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import java.io.ByteArrayInputStream
import java.io.InputStream
import java.nio.ByteBuffer

/** Actual JPEG pixels are decoded by Robolectric's native graphics runtime. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class JpegCarrierTest {
    private val limits = Limits(maxPixels = 100_000, maxPngWorkingBytes = 64L * 1024 * 1024)
    private val colors = listOf(0xf02020, 0x20f020, 0x2020f0, 0xf0f020, 0xf020f0, 0x20f0f0)

    private fun fixture(name: String = "six-colors.jpg") =
        javaClass.classLoader!!.getResourceAsStream("jpeg/$name")!!.use { it.readBytes() }

    /** Independently constructed big-endian TIFF orientation entry, before existing JPEG markers. */
    private fun oriented(value: Int): ByteArray {
        val original = fixture()
        val app1 = ByteBuffer.allocate(36).putShort(0xffe1.toShort()).putShort(34)
            .put(byteArrayOf(69, 120, 105, 102, 0, 0)).putShort(0x4d4d).putShort(42)
            .putInt(8).putShort(1).putShort(0x112).putShort(3).putInt(1)
            .putShort(value.toShort()).putShort(0).putInt(0).array()
        return original.copyOfRange(0, 2) + app1 + original.copyOfRange(2, original.size)
    }

    private fun assertTiles(image: RgbaImage, columns: Int, expected: List<Int>) {
        assertEquals(columns * 20, image.width)
        assertEquals(expected.size / columns * 20, image.height)
        expected.forEachIndexed { index, colorIndex ->
            val at = (((index / columns) * 20 + 10) * image.width + (index % columns) * 20 + 10) * 4
            val color = colors[colorIndex]
            for (channel in 0..2) {
                val want = (color shr (16 - 8 * channel)) and 255
                val actual = image.rgba[at + channel].toInt() and 255
                assertTrue("tile $index channel $channel: $actual != $want", kotlin.math.abs(actual - want) <= 5)
            }
        }
        for (index in 3 until image.rgba.size step 4) assertEquals(255, image.rgba[index].toInt() and 255)
    }

    private fun orientation(value: Int, columns: Int, expected: List<Int>) {
        val bytes = oriented(value)
        val original = bytes.copyOf()
        val image = JpegCarrier.decode(bytes, limits, Control())
        try {
            assertTiles(image, columns, expected)
            assertArrayEquals(original, bytes)
            val info = JpegCarrier.probe(ByteArrayInputStream(bytes), Control())!!
            assertEquals(image.width, info.width); assertEquals(image.height, info.height)
            assertEquals(60, info.storedWidth); assertEquals(40, info.storedHeight)
            assertEquals(value, info.orientation)
        } finally { image.rgba.fill(0) }
    }

    @Test fun normalExifKeepsPosition() = orientation(1, 3, listOf(0, 1, 2, 3, 4, 5))
    @Test fun mirroredExifReflectsHorizontally() = orientation(2, 3, listOf(2, 1, 0, 5, 4, 3))
    @Test fun rotated180ExifMovesAllCorners() = orientation(3, 3, listOf(5, 4, 3, 2, 1, 0))
    @Test fun flippedExifReflectsVertically() = orientation(4, 3, listOf(3, 4, 5, 0, 1, 2))
    @Test fun transposedExifExchangesAxes() = orientation(5, 2, listOf(0, 3, 1, 4, 2, 5))
    @Test fun rotated90ExifMatchesDisplayedPortrait() = orientation(6, 2, listOf(3, 0, 4, 1, 5, 2))
    @Test fun transverseExifExchangesAndReflectsAxes() = orientation(7, 2, listOf(5, 2, 4, 1, 3, 0))
    @Test fun rotated270ExifMatchesDisplayedPortrait() = orientation(8, 2, listOf(2, 5, 1, 4, 0, 3))

    @Test fun missingExifAndProgressiveJpegDecodeRealOpaquePixels() {
        for (name in listOf("six-colors.jpg", "progressive.jpg")) {
            val bytes = fixture(name)
            val native = BitmapFactory.decodeByteArray(bytes, 0, bytes.size)!!
            try {
                assertEquals(60, native.width); assertEquals(40, native.height)
                assertTrue(native.getPixel(10, 10) != native.getPixel(50, 30))
            } finally { native.recycle() }
            val image = JpegCarrier.decode(bytes, limits, Control())
            try { assertTiles(image, 3, listOf(0, 1, 2, 3, 4, 5)) }
            finally { image.rgba.fill(0) }
        }
    }

    @Test fun independentExifFixtureMatchesHeaderAndPixelDirection() {
        val bytes = fixture("orientation-6.jpg")
        assertTrue(JpegCarrier.isJpeg(bytes))
        val image = JpegCarrier.decode(bytes, limits, Control())
        try { assertTiles(image, 2, listOf(3, 0, 4, 1, 5, 2)) }
        finally { image.rgba.fill(0) }
    }

    @Test fun pixelLimitRejectsBeforeImageDecodeStage() {
        val stages = mutableListOf<String>()
        rejects("像素") { JpegCarrier.decode(fixture(), limits.copy(maxPixels = 2399), Control({ stage, _, _ -> stages += stage })) }
        assertFalse(stages.contains("解码 JPEG 载体"))
    }

    @Test fun inputByteLimitRejectsBeforeImageDecodeStage() {
        val bytes = fixture(); val stages = mutableListOf<String>()
        rejects("容器") { JpegCarrier.decode(bytes, limits.copy(maxContainerBytes = bytes.size - 1), Control({ stage, _, _ -> stages += stage })) }
        assertFalse(stages.contains("解码 JPEG 载体"))
    }

    @Test fun workingBudgetIncludesDecodedBitmapAndOutputBeforeDecodeStage() {
        val stages = mutableListOf<String>()
        rejects("内存") { JpegCarrier.decode(fixture(), limits.copy(maxPngWorkingBytes = 10000), Control({ stage, _, _ -> stages += stage })) }
        assertFalse(stages.contains("解码 JPEG 载体"))
    }

    @Test fun retainedPayloadCountsAgainstWorkingBudget() {
        rejects("内存") { JpegCarrier.decode(fixture(), limits, Control(), retainedBytes = limits.maxPngWorkingBytes) }
    }

    @Test fun invalidRetainedEstimateCannotWrapBudgetChecks() {
        for (retained in listOf(-1L, Long.MAX_VALUE))
            rejects { JpegCarrier.decode(fixture(), limits, Control(), retainedBytes = retained) }
    }

    @Test fun cancelBeforeDecodeDoesNotTouchInput() {
        val bytes = fixture(); val before = bytes.copyOf()
        try { JpegCarrier.decode(bytes, limits, Control(cancelled = { true })); fail("cancel ignored") }
        catch (_: CancelledException) { assertArrayEquals(before, bytes) }
    }

    @Test fun cancelDuringPixelCopyDoesNotReturnPartialRgbaAndLaterDecodeWorks() {
        var cancelled = false
        val control = Control({ stage, completed, _ -> if (stage == "整理 JPEG 方向" && completed > 0) cancelled = true }, { cancelled })
        try { JpegCarrier.decode(oriented(6), limits, control); fail("cancel ignored") }
        catch (_: CancelledException) { assertTrue(cancelled) }
        val image = JpegCarrier.decode(fixture(), limits, Control())
        try { assertTiles(image, 3, listOf(0, 1, 2, 3, 4, 5)) }
        finally { image.rgba.fill(0) }
    }

    @Test fun malformedOrTruncatedFilesCannotBecomeCovers() {
        val valid = fixture()
        val cases = listOf(byteArrayOf(), "not a JPEG".toByteArray(), byteArrayOf(-1, -40, -1, -39),
            valid.copyOf(40), valid.copyOf(valid.size - 2),
            valid.copyOf().apply { this[4] = 0x7f; this[5] = -1 })
        for (bytes in cases) rejects { JpegCarrier.decode(bytes, limits, Control()) }
    }

    @Test fun invalidExifOrientationIsRejectedWithoutGuessing() {
        rejects { JpegCarrier.decode(oriented(9), limits, Control()) }
    }

    @Test fun auxiliaryBytesAfterPrimaryJpegAreDiscardedWhenProducingPixels() {
        val bytes = fixture() + "synthetic camera auxiliary metadata".toByteArray() + fixture()
        val original = bytes.copyOf()
        val image = JpegCarrier.decode(bytes, limits, Control())
        try { assertTiles(image, 3, listOf(0, 1, 2, 3, 4, 5)); assertArrayEquals(original, bytes) }
        finally { image.rgba.fill(0) }
    }

    @Test fun selectionProbeIsBoundedAndDoesNotCloseBorrowedStream() {
        val head = byteArrayOf(-1, -40)
        var read = 0; var closed = false
        val input = object : InputStream() {
            override fun read(): Int { check(read < 1024 * 1024); return if (read < head.size) head[read++].toInt() and 255 else { read++; 0 } }
            override fun close() { closed = true }
        }
        assertNull(JpegCarrier.probe(input, Control()))
        assertTrue(read <= 1024 * 1024); assertFalse(closed)
    }

    @Test fun selectionProbeDoesNotRequireReadingImageEntropy() {
        val bytes = fixture("orientation-6.jpg")
        val sos = (2 until bytes.size - 1).first { bytes[it] == (-1).toByte() && bytes[it + 1] == 0xda.toByte() }
        val headerLength = sos + 2 + ((bytes[sos + 2].toInt() and 255) shl 8) + (bytes[sos + 3].toInt() and 255)
        val onlyHeader = bytes.copyOf(headerLength)
        val info = JpegCarrier.probe(ByteArrayInputStream(onlyHeader), Control())!!
        assertEquals(40, info.width); assertEquals(60, info.height)
    }

    @Test fun selectionProbeRespondsToCancellation() {
        var reads = 0
        val input = object : InputStream() { override fun read(): Int { reads++; return 0 } }
        try { JpegCarrier.probe(input, Control(cancelled = { true })); fail("cancel ignored") }
        catch (_: CancelledException) { assertEquals(0, reads) }
    }

    private inline fun rejects(fragment: String = "", action: () -> Unit) {
        try { action(); fail("Malformed or over-budget JPEG accepted") }
        catch (e: StegException) { assertTrue(e.message.orEmpty(), e.message.orEmpty().contains(fragment)) }
    }
}
