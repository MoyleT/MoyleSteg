package com.moyle.steg.android

import android.net.Uri
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.*
import kotlinx.coroutines.test.*
import org.junit.*
import org.junit.Assert.*
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import java.io.File
import java.util.concurrent.TimeUnit

@OptIn(ExperimentalCoroutinesApi::class)
@RunWith(RobolectricTestRunner::class)
@Config(sdk=[35])
class NavigationRetentionTest {
    private val dispatcher=StandardTestDispatcher()
    private lateinit var vm:MoyleViewModel
    private lateinit var directory:File
    @Before fun setup(){
        Dispatchers.setMain(dispatcher)
        val app=RuntimeEnvironment.getApplication()
        directory=File.createTempFile("navigation-",".test",app.cacheDir)
        check(directory.delete() && directory.mkdir())
        vm=MoyleViewModel(app)
    }
    @After fun cleanup(){
        vm.viewModelScope.cancel();dispatcher.scheduler.runCurrent();vm.clearResult()
        directory.deleteRecursively();Dispatchers.resetMain()
    }
    private fun settle(){
        val end=System.nanoTime()+TimeUnit.SECONDS.toNanos(15)
        do{
            dispatcher.scheduler.runCurrent()
            if(vm.viewModelScope.coroutineContext[Job]!!.children.none{it.isActive})return
            Thread.sleep(5)
        }while(System.nanoTime()<end)
        fail("Unfinished navigation fixture")
    }
    private fun newKey():JobResult {
        vm.page(2);vm.operation(Operation.KEYGEN);vm.run();settle()
        assertNull(vm.state.value.error)
        return requireNotNull(vm.state.value.result)
    }
    @Test fun settingsRoundTripPreservesUnexportedKeyAndActiveOperation(){
        val result=newKey();val bytes=result.staged!!.readBytes()
        vm.setPassword("do not retain this")
        vm.page(3);vm.theme("blossom");vm.largeText(true)
        assertSame(result,vm.state.value.result)
        assertArrayEquals(bytes,result.staged.readBytes())
        assertEquals("",vm.state.value.password)
        vm.page(2)
        assertEquals(Operation.KEYGEN,vm.state.value.operation)
        assertSame(result,vm.state.value.result)
    }
    @Test fun selectingCurrentPageAndCurrentOperationNeverDiscardsKey(){
        val result=newKey()
        vm.page(2);vm.operation(Operation.KEYGEN)
        assertSame(result,vm.state.value.result)
        assertTrue(result.staged!!.isFile)
    }
    @Test fun anotherTaskCannotDiscardUnexportedKeyWithoutDecision(){
        val result=newKey()
        vm.page(1)
        assertEquals(2,vm.state.value.page)
        assertEquals(Operation.KEYGEN,vm.state.value.operation)
        assertSame(result,vm.state.value.result)
        assertTrue(result.staged!!.isFile)
        assertNotNull(vm.state.value.discardRequest)
        vm.keepCurrentWork()
        assertNull(vm.state.value.discardRequest)
        assertSame(result,vm.state.value.result)
        assertEquals(2,vm.state.value.page)
    }
    @Test fun confirmedNavigationDeletesPrivateKeyAndChangesTask(){
        val result=newKey()
        val original=File(directory,"original.txt").apply{writeText("synthetic input")}
        vm.page(1);vm.confirmDiscard()
        assertFalse(result.staged!!.exists())
        assertNull(vm.state.value.result)
        assertEquals(1,vm.state.value.page)
        assertEquals(Operation.RESTORE,vm.state.value.operation)
        assertEquals("synthetic input",original.readText())
    }
    @Test fun explicitClearRequestsDecisionAndAbandonedDecisionCannotDeleteNewKey(){
        val old=newKey()
        vm.requestClearResult()
        assertSame(old,vm.state.value.result)
        assertTrue(old.staged!!.isFile)
        vm.keepCurrentWork();vm.clearResult()
        vm.run();settle()
        val replacement=requireNotNull(vm.state.value.result)
        vm.confirmDiscard()
        assertSame(replacement,vm.state.value.result)
        assertTrue(replacement.staged!!.isFile)
        vm.requestClearResult();vm.confirmDiscard()
        assertFalse(replacement.staged.exists())
    }
    @Test fun settingsReturnsToVerifySubmode(){
        vm.operation(Operation.VERIFY)
        vm.page(3);vm.theme("terminal");vm.page(1)
        assertEquals(Operation.VERIFY,vm.state.value.operation)
    }
    @Test fun memorySettingsDoNotInvalidateAlreadyComputedOutput(){
        val result=newKey()
        vm.page(3);vm.manualMemory(true);vm.manualMemoryMiB("192")
        assertSame(result,vm.state.value.result)
        assertTrue(result.staged!!.isFile)
        assertFalse(vm.state.value.resourceAcknowledged)
    }
    @Test fun settingsAndReselectionOfTabPreserveMultipleInputUris(){
        val uris=(1..2).map{Uri.fromFile(File(directory,"input-$it.txt").apply{writeText("synthetic $it")})}
        vm.pickInputs(uris);settle()
        assertEquals(uris,vm.state.value.inputs.map{it.uri})
        vm.page(0)
        assertEquals(uris,vm.state.value.inputs.map{it.uri})
        vm.page(3);vm.largeText(true);vm.page(0)
        assertEquals(uris,vm.state.value.inputs.map{it.uri})
    }
}
