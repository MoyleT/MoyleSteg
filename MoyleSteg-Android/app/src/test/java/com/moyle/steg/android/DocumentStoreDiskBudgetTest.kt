package com.moyle.steg.android

import android.app.Application
import android.system.ErrnoException
import android.system.OsConstants
import com.moyle.steg.core.Control
import com.moyle.steg.core.StegException
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import java.io.File
import java.io.IOException

@RunWith(RobolectricTestRunner::class)
@Config(sdk=[35])
class DocumentStoreDiskBudgetTest {
    private lateinit var app:Application
    private lateinit var store:DocumentStore
    @Before fun setup(){app=RuntimeEnvironment.getApplication();store=DocumentStore(app)}
    @After fun teardown(){store.workDirectory().listFiles().orEmpty().forEach{assertTrue(it.delete())}}
    private fun noFiles(){assertTrue("failed staging left private content",store.workDirectory().listFiles().orEmpty().isEmpty())}
    private fun spaceFailure(action:()->Unit){
        val failure=try{action();null}catch(error:Exception){error}
        assertTrue("expected explicit private-space error, got $failure",failure is StegException && failure.message.orEmpty().contains("私有空间不足"))
        noFiles()
    }
    @Test fun stagingUsesInjectedBudgetAndThirtyTwoMiBReserveBeforeWriting(){
        val data=ByteArray(65536){65}
        store=DocumentStore(app,privateSpace={data.size+32L*1024*1024-1})
        spaceFailure{store.stage(data,Control())}
        assertTrue(data.all{it==65.toByte()})
    }
    @Test fun stagingRechecksAvailableSpaceBeforeEachChunkAndCleansPartial(){
        store=DocumentStore(app,privateSpace={directory->
            if(directory.listFiles().orEmpty().any{it.length()>=65536})0L else Long.MAX_VALUE
        })
        spaceFailure{store.stage(ByteArray(200000){65},Control())}
    }
    @Test fun stagingReportsBoundedWriteProgressBeforeReadback(){
        val data=ByteArray(200000){(it*13).toByte()}
        val written=mutableListOf<Int>()
        val file=store.stage(data,Control(progress={stage,done,total->
            if(stage=="保存私有文件"){
                assertEquals(data.size,total)
                assertTrue("progress describes bytes not yet written",store.workDirectory().listFiles().orEmpty().sumOf{it.length()}>=done)
                written.add(done)
            }
        }))
        try{
            assertArrayEquals(data,file.readBytes())
            assertTrue("no bounded staging progress was emitted",written.size>=4)
            assertEquals(data.size,written.last())
            assertTrue(written.zipWithNext().all{(a,b)->b>=a && b-a<=65536})
        }finally{assertTrue(file.delete())}
    }
    @Test fun stagingMapsEnospcCauseToExplicitSpaceMessage(){
        store=DocumentStore(app,privateSpace={throw IOException("synthetic statvfs fault",ErrnoException("statvfs",OsConstants.ENOSPC))})
        spaceFailure{store.stage(byteArrayOf(1,2,3),Control())}
    }
    @Test fun stagingDoesNotMislabelOtherIoFailuresAsSpaceExhaustion(){
        store=DocumentStore(app,privateSpace={throw IOException("synthetic permission fault",ErrnoException("statvfs",OsConstants.EACCES))})
        val failure=try{store.stage(byteArrayOf(1),Control());null}catch(error:Exception){error}
        assertTrue(failure is IOException)
        assertFalse(failure!!.message.orEmpty().contains("私有空间不足"))
        noFiles()
    }
    @Test fun stagingDoesNotTreatAnEnospcFilenameAsADiskFullReason(){
        val original=java.nio.file.FileSystemException("synthetic-ENOSPC-notes.txt",null,"Permission denied")
        store=DocumentStore(app,privateSpace={throw original})
        val failure=try{store.stage(byteArrayOf(1),Control());null}catch(error:Exception){error}
        assertSame("the filename is not the operating system error reason",original,failure)
        noFiles()
    }
}
