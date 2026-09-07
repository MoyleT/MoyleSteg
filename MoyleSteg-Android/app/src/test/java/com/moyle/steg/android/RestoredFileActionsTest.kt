package com.moyle.steg.android

import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.ContextWrapper
import android.content.Intent
import android.net.Uri
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config
import java.io.File
import java.io.RandomAccessFile

/** Real bounded file reads and Android intents; only failed external activity launches are faked. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class RestoredFileActionsTest {
    private lateinit var staged: File
    private val uri = Uri.parse("content://com.moyle.steg.android.restored/result/1")

    @Before fun setup() {
        staged = File.createTempFile("restored-type-", ".work", RuntimeEnvironment.getApplication().cacheDir)
    }

    @After fun teardown() {
        assertTrue(!staged.exists() || staged.delete())
    }

    @Test fun binarySignaturesRecognizeCommonFilesWithoutAnExtension() {
        val cases = listOf(
            byteArrayOf(-119, 80, 78, 71, 13, 10, 26, 10) to "image/png",
            byteArrayOf(-1, -40, -1, -32) to "image/jpeg",
            "GIF87a".toByteArray() to "image/gif",
            "GIF89a".toByteArray() to "image/gif",
            "%PDF-1.7\n".toByteArray() to "application/pdf",
            byteArrayOf(80, 75, 3, 4) to "application/zip",
            byteArrayOf(80, 75, 5, 6) to "application/zip",
            byteArrayOf(0, 0, 0, 24) + "ftypisom".toByteArray() + ByteArray(12) to "video/mp4"
        )
        for ((header, expected) in cases) {
            staged.writeBytes(header)
            assertEquals(expected, RestoredFileActions.mimeFor(staged, "restored"))
        }
    }

    @Test fun aRecognizedImageHeaderCorrectsAnUnrelatedExtension() {
        staged.writeBytes(byteArrayOf(-119, 80, 78, 71, 13, 10, 26, 10))
        assertEquals("image/png", RestoredFileActions.mimeFor(staged, "photo.JPG"))
    }

    @Test fun zipContainersKeepOfficeAndPackageTypesFromTheAuthenticatedName() {
        staged.writeBytes(byteArrayOf(80, 75, 3, 4, 20, 0, 0, 0))
        val cases = mapOf(
            "REPORT.DOCX" to "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "budget.xlsx" to "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "slides.pptx" to "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "reader.epub" to "application/epub+zip",
            "program.apk" to "application/vnd.android.package-archive",
            "archive.zip" to "application/zip"
        )
        for ((name, expected) in cases) assertEquals(expected, RestoredFileActions.mimeFor(staged, name))
    }

    @Test fun ftypDoesNotTurnAudioOrAvifImagesIntoVideos() {
        staged.writeBytes(byteArrayOf(0, 0, 0, 24) + "ftypisom".toByteArray() + ByteArray(12))
        assertEquals("audio/mp4", RestoredFileActions.mimeFor(staged, "recording.m4a"))
        staged.writeBytes(byteArrayOf(0, 0, 0, 24) + "ftypavif".toByteArray() + ByteArray(12))
        assertEquals("image/avif", RestoredFileActions.mimeFor(staged, "picture"))
    }

    @Test fun textNamesRetainUsefulSpecificTypes() {
        val cases = listOf(
            Triple("notes.TXT", "恢复后的中文文本\n", "text/plain"),
            Triple("values.csv", "name,value\na,1\n", "text/csv"),
            Triple("config.json", "{\"ready\":true}", "application/json"),
            Triple("page.HTML", "<!doctype html><html><body>hello</body></html>", "text/html"),
            Triple("config.xml", "<?xml version=\"1.0\"?><config/>", "application/xml")
        )
        for ((name, contents, expected) in cases) {
            staged.writeText(contents)
            assertEquals(expected, RestoredFileActions.mimeFor(staged, name))
        }
    }

    @Test fun unnamedUtf8IsTextButHtmlIsNotMistakenForPlainText() {
        staged.writeText("恢复文本\nSecond line\tvalue")
        assertEquals("text/plain", RestoredFileActions.mimeFor(staged, "restored"))
        staged.writeText("\uFEFF  <!DOCTYPE html><html><body>hello</body></html>")
        assertEquals("text/html", RestoredFileActions.mimeFor(staged, "restored"))
    }

    @Test fun unknownBinaryAndEmptyUnnamedFilesRemainOctetStream() {
        staged.writeBytes(byteArrayOf(0, 1, 2, 3, -1, -2))
        assertEquals("application/octet-stream", RestoredFileActions.mimeFor(staged, "data.unrecognized"))
        staged.writeBytes(byteArrayOf(-61, 40)) // Malformed UTF-8, not a text document.
        assertEquals("application/octet-stream", RestoredFileActions.mimeFor(staged, "restored"))
        staged.writeBytes(byteArrayOf())
        assertEquals("application/octet-stream", RestoredFileActions.mimeFor(staged, "restored"))
    }

    @Test fun oneGiBFileUsesOnlyItsHeaderAndIsNotModified() {
        // A sparse fixture catches readBytes/whole-file decoding regressions without allocating 1 GiB.
        RandomAccessFile(staged, "rw").use {
            it.write("%PDF-1.7\n".toByteArray())
            it.setLength(1024L * 1024 * 1024)
        }
        assertEquals("application/pdf", RestoredFileActions.mimeFor(staged, "large"))
        assertEquals(1024L * 1024 * 1024, staged.length())
        RandomAccessFile(staged, "r").use { assertEquals('%'.code, it.read()) }
    }

    @Test fun viewIntentCarriesOnlyReadAccessToTheSelectedContentUri() {
        val intent = RestoredFileActions.viewIntent(uri, "application/pdf")
        assertEquals(Intent.ACTION_VIEW, intent.action)
        assertEquals(uri, intent.data)
        assertEquals("application/pdf", intent.type)
        assertEquals(Intent.FLAG_GRANT_READ_URI_PERMISSION, intent.flags)
        assertEquals(1, intent.clipData!!.itemCount)
        assertEquals(uri, intent.clipData!!.getItemAt(0).uri)
        assertNull(intent.component)
        assertNull(intent.`package`)
    }

    @Test fun unknownTypeLetsTheUserChooseOtherApplications() {
        assertEquals("*/*", RestoredFileActions.viewIntent(uri, "application/octet-stream").type)
    }

    @Test fun apkUsesTheOrdinaryExplicitlyRequestedViewFlow() {
        val intent = RestoredFileActions.viewIntent(uri, "application/vnd.android.package-archive")
        assertEquals(Intent.ACTION_VIEW, intent.action)
        assertEquals("application/vnd.android.package-archive", intent.type)
        assertEquals(Intent.FLAG_GRANT_READ_URI_PERMISSION, intent.flags)
    }

    @Test fun fileAndWebUrisCannotEscapeTheContentSharingContract() {
        for (invalid in listOf("file:///sdcard/Download/file.pdf", "https://example.com/file.pdf")) {
            assertThrows(IllegalArgumentException::class.java) {
                RestoredFileActions.viewIntent(Uri.parse(invalid), "application/pdf")
            }
        }
    }

    @Test fun openingLaunchesAChooserWhoseTargetIsTheReadOnlyViewIntent() {
        val controller = Robolectric.buildActivity(Activity::class.java).setup()
        try {
            val activity = controller.get()
            assertEquals(OpenOutcome.ChooserStarted, RestoredFileActions.open(activity, uri, "application/pdf"))
            val chooser = shadowOf(activity).nextStartedActivity
            assertEquals(Intent.ACTION_CHOOSER, chooser.action)
            @Suppress("DEPRECATION")
            val target = chooser.getParcelableExtra<Intent>(Intent.EXTRA_INTENT)!!
            assertEquals(Intent.ACTION_VIEW, target.action)
            assertEquals(uri, target.data)
            assertEquals("application/pdf", target.type)
            assertEquals(Intent.FLAG_GRANT_READ_URI_PERMISSION, target.flags)
            assertEquals(uri, target.clipData!!.getItemAt(0).uri)
            assertEquals(Intent.FLAG_GRANT_READ_URI_PERMISSION, chooser.flags)
            assertEquals(uri, chooser.clipData!!.getItemAt(0).uri)
        } finally { controller.pause().stop().destroy() }
    }

    @Test fun applicationContextCanLaunchChooserWithoutAnActivity() {
        val application = RuntimeEnvironment.getApplication()
        assertEquals(OpenOutcome.ChooserStarted, RestoredFileActions.open(application, uri, "text/plain"))
        val chooser = shadowOf(application).nextStartedActivity
        assertTrue(chooser.flags and Intent.FLAG_ACTIVITY_NEW_TASK != 0)
        assertEquals(0, chooser.flags and Intent.FLAG_GRANT_WRITE_URI_PERMISSION)
    }

    @Test fun missingViewerLeavesTheSavedFileAndGivesRecoveryAdvice() {
        staged.writeText("already saved")
        val context = object : ContextWrapper(RuntimeEnvironment.getApplication()) {
            override fun startActivity(intent: Intent) { throw ActivityNotFoundException("No viewer") }
        }
        val outcome = RestoredFileActions.open(context, uri, "application/pdf") as OpenOutcome.Unavailable
        assertTrue(outcome.message.contains("保存位置"))
        assertTrue(outcome.message.contains("文件管理器"))
        assertEquals("already saved", staged.readText())
    }

    @Test fun deniedUriAccessBecomesAnActionableMessage() {
        val context = object : ContextWrapper(RuntimeEnvironment.getApplication()) {
            override fun startActivity(intent: Intent) { throw SecurityException("Read denied") }
        }
        val outcome = RestoredFileActions.open(context, uri, "application/pdf") as OpenOutcome.Unavailable
        assertTrue(outcome.message.contains("保存位置"))
        assertTrue(outcome.message.contains("文件管理器"))
    }
}
