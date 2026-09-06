package com.moyle.steg.core

import java.io.File
import java.io.FileInputStream
import java.io.FileOutputStream
import java.io.InputStream
import java.security.MessageDigest
import org.bouncycastle.crypto.InvalidCipherTextException
import org.bouncycastle.crypto.engines.AESEngine
import org.bouncycastle.crypto.modes.GCMBlockCipher
import org.bouncycastle.crypto.params.AEADParameters
import org.bouncycastle.crypto.params.KeyParameter

/** BC's lightweight GCM emits bounded updates; JCE providers may buffer entire decryptions. */
internal object StreamGcm {
    const val CHUNK = 65536
    fun exact(input: InputStream, count: Int): ByteArray {
        val result=ByteArray(count);var at=0
        try {
            while(at<count){val n=input.read(result,at,count-at);demand(n>0,"SAES 文件被截断或读取没有进展。");at+=n}
            return result
        }catch(failure:Throwable){result.fill(0);throw failure}
    }
    fun encrypt(body: File, metadata: ByteArray, header: Header, key: ByteArray,
                destination: File, control: Control): String {
        val cipher=GCMBlockCipher.newInstance(AESEngine.newInstance())
        cipher.init(true,AEADParameters(KeyParameter(key),128,header.nonce,header.core))
        val inputBuffer=ByteArray(CHUNK);val outputBuffer=ByteArray(CHUNK+32)
        val digest=MessageDigest.getInstance("SHA-256")
        val expected=header.cipherLength.toLong()-16-metadata.size
        var cipherBytes=0L
        try {
            FileOutputStream(destination).use { output ->
                val hb=header.bytes();output.write(hb);digest.update(hb)
                fun emit(bytes:ByteArray,offset:Int,count:Int){
                    val n=cipher.processBytes(bytes,offset,count,outputBuffer,0)
                    if(n>0){output.write(outputBuffer,0,n);digest.update(outputBuffer,0,n);cipherBytes+=n}
                }
                var at=0
                while(at<metadata.size){control.check();val n=minOf(CHUNK,metadata.size-at);emit(metadata,at,n);at+=n}
                FileInputStream(body).use { input ->
                    demand(input.channel.size()==expected,"私有源副本的长度发生变化。")
                    var done=0L;control.report("流式加密",0,expected.toInt())
                    while(done<expected){
                        control.check();val n=input.read(inputBuffer,0,minOf(CHUNK.toLong(),expected-done).toInt())
                        demand(n>0,"私有源副本被截断。");emit(inputBuffer,0,n);done+=n
                        control.report("流式加密",done.toInt(),expected.toInt())
                    }
                    demand(input.read()<0,"私有源副本长度发生变化。")
                }
                control.check();val n=cipher.doFinal(outputBuffer,0)
                output.write(outputBuffer,0,n);digest.update(outputBuffer,0,n);cipherBytes+=n
                demand(cipherBytes==header.cipherLength.toLong(),"SAES 加密输出长度不符。")
                output.fd.sync()
            }
            return digest.digest().hex()
        }finally{inputBuffer.fill(0);outputBuffer.fill(0);cipher.reset()}
    }
    fun decrypt(container:File,header:Header,key:ByteArray,control:Control,stage:String,
                consume:(ByteArray,Int,Int)->Unit):String {
        val cipher=GCMBlockCipher.newInstance(AESEngine.newInstance())
        cipher.init(false,AEADParameters(KeyParameter(key),128,header.nonce,header.core))
        val inputBuffer=ByteArray(CHUNK);val outputBuffer=ByteArray(CHUNK+32)
        val digest=MessageDigest.getInstance("SHA-256")
        try {
            FileInputStream(container).use { input ->
                demand(input.channel.size()==Header.SIZE.toLong()+header.cipherLength,"私有 SAES 副本长度发生变化。")
                val hb=exact(input,Header.SIZE)
                demand(MessageDigest.isEqual(hb,header.bytes()),"私有 SAES 头部发生变化。")
                digest.update(hb)
                var done=0;control.report(stage,0,header.cipherLength)
                while(done<header.cipherLength){
                    control.check();val n=input.read(inputBuffer,0,minOf(CHUNK,header.cipherLength-done))
                    demand(n>0,"SAES 文件被截断。");digest.update(inputBuffer,0,n)
                    val count=cipher.processBytes(inputBuffer,0,n,outputBuffer,0)
                    if(count>0)consume(outputBuffer,0,count)
                    done+=n;control.report(stage,done,header.cipherLength)
                }
                demand(input.read()<0,"SAES 文件含多余尾部。");control.check()
                val count=cipher.doFinal(outputBuffer,0)
                if(count>0)consume(outputBuffer,0,count)
            }
            return digest.digest().hex()
        }catch(_:InvalidCipherTextException){throw AuthenticationException()}
        finally{inputBuffer.fill(0);outputBuffer.fill(0);cipher.reset()}
    }
}
