package com.moyle.steg.android

import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.moyle.steg.core.*
import org.junit.Test
import org.junit.runner.RunWith
import org.junit.Assert.*

/** Must run on Android: JVM tests do not verify Conscrypt/device behavior. */
@RunWith(AndroidJUnit4::class)
class DeviceInteropTest {
    @Test fun desktopFixturesDecodeOnDevice() {
        val assets=InstrumentationRegistry.getInstrumentation().context.assets
        fun read(name: String)=assets.open("interop/$name").use{it.readBytes()}
        val password=String(read("password.txt"),Charsets.UTF_8)
        val cover=read("cover.png")
        val engine=StegEngine()
        for(line in String(read("cases.tsv"),Charsets.UTF_8).trim().lines()){
            val (base,source,name,mode)=line.split('\t');val bytes=read(source)
            val c=if(mode=="key")Credential.keyFile(read("key.stegkey"))else Credential.password(password)
            c.use {
                for(ext in listOf("saes","png")){
                    val result=engine.decode(read("$base.$ext"),c)
                    assertEquals(name,result.filename);assertArrayEquals(bytes,result.data);result.data.fill(0)
                }
                assertArrayEquals(bytes,engine.decode(engine.encrypt(name,bytes,c),c).data)
                assertArrayEquals(bytes,engine.decode(engine.hide(cover,name,bytes,c),c).data)
            }
        }
    }
}
