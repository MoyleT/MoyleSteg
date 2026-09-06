package com.moyle.steg.android

import androidx.test.platform.app.InstrumentationRegistry
import com.moyle.steg.core.*
import org.junit.Test
import org.junit.Assert.*
import java.io.File
import java.security.MessageDigest
import java.util.Random

/** Execute on a device separately; compiling this test does not count as executing it. */
class DeviceLargeFileTest {
    @Test fun streamedFileRoundTripAndVerification(){
        val context=InstrumentationRegistry.getInstrumentation().targetContext
        val work=File(context.cacheDir,"stream-device-${System.nanoTime()}").apply{check(mkdirs())}
        val source=File(work,"合成测试.bin")
        val chunk=ByteArray(65536);val random=Random(977);val digest=MessageDigest.getInstance("SHA-256")
        try{
            source.outputStream().use{out->repeat(128){random.nextBytes(chunk);out.write(chunk);digest.update(chunk)}}
            val expected=digest.digest().joinToString(""){"%02x".format(it.toInt() and 255)}
            Credential.key(ByteArray(32){it.toByte()}).use{key->
                val engine=SaesFiles()
                val encrypted=engine.encrypt(source,source.name,key,work)
                val verified=engine.verify(encrypted.output!!,key,work)
                assertNull(verified.output);assertEquals(expected,verified.payloadSha256)
                val restored=engine.decrypt(encrypted.output!!,key,work)
                assertEquals(source.length(),restored.output!!.length())
                assertEquals(source.name,restored.filename)
                val actual=MessageDigest.getInstance("SHA-256")
                restored.output!!.inputStream().use{input->while(true){val n=input.read(chunk);if(n<0)break;actual.update(chunk,0,n)}}
                assertEquals(expected,actual.digest().joinToString(""){"%02x".format(it.toInt() and 255)})
            }
        }finally{chunk.fill(0);work.listFiles().orEmpty().forEach{it.delete()};assertTrue(work.delete())}
    }
}
