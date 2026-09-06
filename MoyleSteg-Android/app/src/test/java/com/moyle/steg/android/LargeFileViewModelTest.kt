package com.moyle.steg.android

import android.content.pm.ProviderInfo
import android.net.Uri
import androidx.lifecycle.viewModelScope
import com.moyle.steg.core.*
import kotlinx.coroutines.*
import kotlinx.coroutines.test.*
import org.junit.*
import org.junit.Assert.*
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import org.robolectric.shadows.ShadowContentResolver
import java.io.File
import java.util.Random
import java.util.concurrent.TimeUnit

@OptIn(ExperimentalCoroutinesApi::class)
@RunWith(RobolectricTestRunner::class)
@Config(sdk=[35])
class LargeFileViewModelTest {
    private val dispatcher=StandardTestDispatcher()
    private lateinit var vm:MoyleViewModel
    private lateinit var directory:File
    private lateinit var provider:AutoExpandViewModelTest.SyntheticDocuments
    private var snapshot=MemorySnapshot(256L shl 20,32L shl 20,8L shl 30)
    @Before fun setup(){
        Dispatchers.setMain(dispatcher)
        val app=RuntimeEnvironment.getApplication()
        directory=File.createTempFile("large-vm-",".test",app.cacheDir)
        check(directory.delete() && directory.mkdir())
        provider=AutoExpandViewModelTest.SyntheticDocuments(directory)
        provider.attachInfo(app,ProviderInfo().apply{authority="largevm.test";packageName=app.packageName;name=provider.javaClass.name;applicationInfo=app.applicationInfo;exported=true})
        ShadowContentResolver.registerProviderInternal("largevm.test",provider)
        File(directory,"synthetic.stegkey").writeBytes(Credential.exportKey(ByteArray(32){it.toByte()}))
        vm=MoyleViewModel(app){snapshot}
    }
    @After fun cleanup(){
        vm.viewModelScope.cancel();dispatcher.scheduler.runCurrent();vm.clearResult()
        assertEquals(0,provider.writeRequests)
        directory.listFiles().orEmpty().forEach{assertTrue(it.delete())};assertTrue(directory.delete())
        Dispatchers.resetMain()
    }
    private fun uri(name:String)=Uri.parse("content://largevm.test/$name")
    private fun settle(){
        val deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(40)
        do{dispatcher.scheduler.runCurrent();if(vm.viewModelScope.coroutineContext[Job]!!.children.none{it.isActive})return;Thread.sleep(5)}while(System.nanoTime()<deadline)
        fail("unfinished: ${vm.state.value.stage}")
    }
    private fun select(name:String){vm.pick(DocSlot.INPUT,uri(name));settle()}
    private fun key(){vm.useKey(true);vm.pick(DocSlot.KEY,uri("synthetic.stegkey"));settle()}
    private fun runResult():JobResult{vm.run();settle();assertNull(vm.state.value.error);return requireNotNull(vm.state.value.result)}

    @Test fun fileLargerThanOldLimitEncryptsRestoresAndVerifiesBySignature(){
        val bytes=ByteArray(8*1024*1024).also{Random(731).nextBytes(it)}
        val source=File(directory,"source.bin").apply{writeBytes(bytes)}
        vm.operation(Operation.ENCRYPT);select(source.name);key()
        val encrypted=runResult()
        assertEquals(sha256(bytes),encrypted.contentHash)
        assertTrue(encrypted.staged!!.length()>4*1024*1024)
        val container=File(directory,"wrong-extension.png");encrypted.staged.copyTo(container)
        vm.operation(Operation.RESTORE);select(container.name)
        assertEquals("saes",vm.state.value.inputProbe?.format)
        val restored=runResult()
        assertEquals("source.bin",restored.suggestedName)
        assertArrayEquals(bytes,restored.staged!!.readBytes())
        vm.operation(Operation.VERIFY)
        val verified=runResult()
        assertNull(verified.staged)
        assertEquals(sha256(bytes),verified.contentHash)
        assertEquals(sha256(container.readBytes()),verified.containerHash)
        assertArrayEquals(bytes,source.readBytes())
    }
    @Test fun probeReadsRealPngDimensionsDespiteJpgSuffix(){
        File(directory,"received.jpg").writeBytes(PngCodec.encode(RgbaImage(96,64,ByteArray(96*64*4))))
        select("received.jpg")
        assertEquals(DocumentProbe(File(directory,"received.jpg").length(),"png",96,64),vm.state.value.inputProbe)
        assertNull(vm.state.value.result)
    }
    @Test fun manualMemoryNeedsCurrentConfirmationAndClearsOldResult(){
        vm.operation(Operation.KEYGEN);assertNotNull(runResult().staged)
        vm.manualMemory(true);vm.manualMemoryMiB("96")
        assertNull(vm.state.value.result)
        vm.run();assertFalse(vm.state.value.busy);assertNotNull(vm.state.value.error)
        vm.acknowledgeResources(true);runResult()
        assertFalse(vm.state.value.resourceAcknowledged)
    }
    @Test fun changingInputOrBudgetRevokesConfirmation(){
        File(directory,"source.bin").writeBytes(byteArrayOf(1,2,3))
        vm.manualMemory(true);vm.acknowledgeResources(true)
        select("source.bin");assertFalse(vm.state.value.resourceAcknowledged)
        vm.acknowledgeResources(true);vm.manualMemoryMiB("100")
        assertFalse(vm.state.value.resourceAcknowledged)
    }
    @Test fun budgetReevaluatedBeforeJobAndCannotBypassActualHeap(){
        vm.operation(Operation.KEYGEN);vm.manualMemory(true);vm.manualMemoryMiB("128");vm.acknowledgeResources(true)
        snapshot=MemorySnapshot(128L shl 20,96L shl 20,8L shl 30)
        vm.run();settle()
        assertNull(vm.state.value.result);assertNotNull(vm.state.value.error)
    }
    @Test fun busyJobIgnoresResourceChanges(){
        vm.operation(Operation.KEYGEN);vm.run();assertTrue(vm.state.value.busy)
        vm.manualMemory(true);vm.manualMemoryMiB("200")
        assertFalse(vm.state.value.manualMemory);assertEquals("128",vm.state.value.manualMemoryMiB)
        settle();assertNull(vm.state.value.error)
    }
    @Test fun cancellationLeavesNoPrivateInputOrOutput(){
        File(directory,"source.bin").writeBytes(ByteArray(5*1024*1024))
        vm.operation(Operation.ENCRYPT);select("source.bin");key();vm.run();vm.requestCancel();settle()
        assertNull(vm.state.value.result)
        val work=File(RuntimeEnvironment.getApplication().noBackupFilesDir,"moyle-work")
        assertTrue(work.listFiles().orEmpty().isEmpty())
    }
    @Test fun unknownProviderSizeCannotBypassManualCaptureBudget(){
        val file=File(directory,"unknown.png")
        file.outputStream().use{out->
            out.write(PngCodec.encode(RgbaImage(96,64,ByteArray(96*64*4))))
            val chunk=ByteArray(65536)
            repeat(640){out.write(chunk)}
        }
        provider.reportSize=false
        vm.operation(Operation.RESTORE);select(file.name);key()
        vm.manualMemory(true);vm.manualMemoryMiB("32");vm.acknowledgeResources(true)
        vm.run();settle()
        assertNull(vm.state.value.result)
        assertTrue("capture must stop at budget before format decode: ${vm.state.value.error}",vm.state.value.error.orEmpty().contains("读取预算"))
    }
}
