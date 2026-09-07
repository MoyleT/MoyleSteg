package com.moyle.steg.android

import android.content.pm.ProviderInfo
import android.net.Uri
import androidx.lifecycle.viewModelScope
import com.moyle.steg.core.*
import kotlinx.coroutines.*
import kotlinx.coroutines.test.*
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import org.robolectric.shadows.ShadowContentResolver
import android.graphics.Bitmap
import java.io.ByteArrayOutputStream
import java.io.File
import java.util.concurrent.TimeUnit

/** Real JPEG bytes enter through SAF; the public ViewModel must stage a verified PNG. */
@OptIn(ExperimentalCoroutinesApi::class)
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class JpegViewModelTest {
    private val dispatcher = StandardTestDispatcher()
    private lateinit var vm: MoyleViewModel
    private lateinit var directory: File
    private lateinit var provider: AutoExpandViewModelTest.SyntheticDocuments
    private val originals = mutableMapOf<String, ByteArray>()
    private val payload = ByteArray(1024).also { java.util.Random(913L).nextBytes(it) }
    private val keyBytes = Credential.exportKey(ByteArray(32) { it.toByte() })

    @Before fun setup() {
        Dispatchers.setMain(dispatcher)
        val app = RuntimeEnvironment.getApplication()
        directory = File.createTempFile("jpeg-vm-", ".test", app.cacheDir)
        check(directory.delete() && directory.mkdir())
        provider = AutoExpandViewModelTest.SyntheticDocuments(directory)
        provider.attachInfo(app, ProviderInfo().apply {
            authority = "jpeg.test"; packageName = app.packageName
            name = provider.javaClass.name; applicationInfo = app.applicationInfo
            exported = true; grantUriPermissions = true
        })
        ShadowContentResolver.registerProviderInternal("jpeg.test", provider)
        write("synthetic.bin", payload)
        write("synthetic.stegkey", keyBytes)
        write("cover.jpg", jpeg(96, 64))
        write("small.jpeg", jpeg(16, 16))
        // Incorrect suffix and MIME must not change content-based carrier recognition.
        write("cover.dat", originals.getValue("cover.jpg"))
        vm = MoyleViewModel(app, memoryReader = {
            MemorySnapshot(512 * MemoryPolicy.MIB, 16 * MemoryPolicy.MIB, 2_000 * MemoryPolicy.MIB)
        })
    }

    @After fun teardown() {
        try {
            vm.viewModelScope.cancel(); dispatcher.scheduler.runCurrent(); vm.clearResult()
            assertEquals(0, provider.writeRequests)
            originals.forEach { (name, bytes) -> assertArrayEquals(name, bytes, File(directory, name).readBytes()) }
        } finally {
            Dispatchers.resetMain()
            directory.listFiles()?.forEach { check(it.delete()) }; check(directory.delete())
        }
    }

    private fun write(name: String, bytes: ByteArray) { originals[name] = bytes; File(directory, name).writeBytes(bytes) }
    private fun uri(name: String) = Uri.parse("content://jpeg.test/$name")
    private fun settle() {
        val end = System.nanoTime() + TimeUnit.SECONDS.toNanos(30)
        do {
            dispatcher.scheduler.runCurrent()
            if (vm.viewModelScope.coroutineContext[Job]!!.children.none { it.isActive }) return
            Thread.sleep(5)
        } while (System.nanoTime() < end)
        fail("ViewModel task did not finish; error=${vm.state.value.error}")
    }
    private fun prepare(cover: String = "cover.jpg", useKey: Boolean = true) {
        vm.pick(DocSlot.COVER, uri(cover)); vm.pick(DocSlot.INPUT, uri("synthetic.bin")); settle()
        if (useKey) { vm.useKey(true); vm.pick(DocSlot.KEY, uri("synthetic.stegkey")); settle() }
        else { vm.setPassword("Synthetic JPEG interop 2026!"); vm.setConfirmation("Synthetic JPEG interop 2026!") }
        assertNull(vm.state.value.error)
    }
    private fun runHide(): JobResult {
        vm.run(); settle(); assertNull(vm.state.value.error)
        return vm.state.value.result ?: throw AssertionError("missing JPEG hide result")
    }
    private fun assertPng(result: JobResult, key: Boolean = true) {
        assertEquals("image/png", result.mime)
        assertEquals("moyle_hidden.png", result.suggestedName)
        val bytes = result.staged!!.readBytes()
        assertTrue(PngCodec.isPng(bytes))
        (if (key) Credential.keyFile(keyBytes) else Credential.password("Synthetic JPEG interop 2026!")).use {
            val restored = StegEngine().decode(bytes, it)
            try { assertEquals("synthetic.bin", restored.filename); assertArrayEquals(payload, restored.data) }
            finally { restored.data.fill(0) }
        }
    }

    @Test fun jpgCarrierStagesPngWithKeyAndLeavesAllInputsUnchanged() {
        prepare(); val result = runHide(); assertPng(result)
        assertEquals(96 to 64, PngCodec.dimensions(result.staged!!.readBytes(), Limits()))
    }
    @Test fun jpegContentWorksDespiteUnrecognizedExtensionAndMime() {
        prepare("cover.dat"); assertPng(runHide())
    }
    @Test fun jpegCarrierSupportsPasswordMode() {
        prepare(useKey = false); assertPng(runHide(), key = false)
    }
    @Test fun preflightAndAutomaticExpansionAgreeWithTheActualPng() {
        prepare("small.jpeg"); vm.run(capacityOnly = true); settle(); assertNull(vm.state.value.error)
        val plan = vm.state.value.result!!.preflight!!
        assertTrue(plan.expanded); assertTrue(plan.fits); assertNull(vm.state.value.result!!.staged)
        val result = runHide(); assertPng(result)
        assertEquals(plan.width to plan.height, PngCodec.dimensions(result.staged!!.readBytes(), Limits()))
    }
    @Test fun insufficientJpegWithoutExpansionFailsWithoutStaging() {
        prepare("small.jpeg"); vm.autoExpand(false); vm.run(); settle()
        assertTrue(vm.state.value.error.orEmpty().contains("容量不足"))
        assertNull(vm.state.value.result)
    }
    @Test fun recoveryOfPngRenamedJpgPreservesTheEncodedSamples() {
        Credential.keyFile(keyBytes).use { key ->
            val rgba = ByteArray(96 * 64 * 4) { if (it % 4 == 3) 0 else (it * 29).toByte() }
            write("received.jpg", StegEngine().hide(PngCodec.encode(RgbaImage(96, 64, rgba)), "synthetic.bin", payload, key))
        }
        vm.operation(Operation.RESTORE); vm.pick(DocSlot.INPUT, uri("received.jpg")); settle()
        vm.useKey(true); vm.pick(DocSlot.KEY, uri("synthetic.stegkey")); settle()
        vm.run(); settle(); assertNull(vm.state.value.error)
        assertArrayEquals(payload, vm.state.value.result!!.staged!!.readBytes())
    }

    private fun jpeg(w: Int, h: Int): ByteArray {
        val image = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888)
        try {
            for (y in 0 until h) for (x in 0 until w) image.setPixel(x, y, (255 shl 24) or ((x * 11 and 255) shl 16) or ((y * 17 and 255) shl 8) or 100)
            return ByteArrayOutputStream().use { out -> check(image.compress(Bitmap.CompressFormat.JPEG, 90, out)); out.toByteArray() }
        } finally { image.recycle() }
    }
}
