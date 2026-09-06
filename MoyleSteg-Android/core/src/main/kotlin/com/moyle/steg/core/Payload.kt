package com.moyle.steg.core

import java.io.ByteArrayOutputStream
import java.nio.ByteBuffer
import java.security.MessageDigest
import java.util.zip.Deflater
import java.util.zip.Inflater
import java.util.zip.DataFormatException

internal object Payload {
    const val FIXED=56
    data class Packed(val bytes: ByteArray,val compressed: Boolean)
    fun build(name: String,data: ByteArray,limits: Limits,control: Control): Packed {
        demand(data.size<=limits.maxPayloadBytes,"秘密文件超过手机处理预算。")
        val filename=utf8(safeFilename(name))
        control.report("压缩",0,data.size)
        val zipped=deflate(data,control)
        val useZip=zipped.size<data.size
        val stored=if(useZip)zipped else data
        val b=ByteBuffer.allocate(FIXED+filename.size+stored.size)
            .put("PAY1".toByteArray()).put(1).put(if(useZip)1.toByte() else 0.toByte()).putShort(filename.size.toShort())
            .putLong(data.size.toLong()).putLong(stored.size.toLong()).put(MessageDigest.getInstance("SHA-256").digest(data))
            .put(filename).put(stored).array()
        zipped.fill(0)
        return Packed(b,useZip)
    }
    fun parse(plain: ByteArray,mode: Int,limits: Limits,control: Control,residentBytes: Long=0L): Decoded {
        control.check()
        demand(plain.size>=FIXED,"内部数据体过短。")
        val b=ByteBuffer.wrap(plain);val magic=ByteArray(4).also(b::get)
        demand(magic.contentEquals("PAY1".toByteArray()) && b.get().toInt()==1,"内部格式无效。")
        val compression=b.get().toInt();val nameLength=b.short.toInt() and 65535;val original=b.long;val stored=b.long
        val digest=ByteArray(32).also(b::get)
        demand(compression in 0..1 && original in 0..limits.maxPayloadBytes.toLong() && stored in 0..limits.maxPayloadBytes.toLong(),"内部长度或压缩方式无效／超过预算。")
        demand(FIXED.toLong()+nameLength+stored==plain.size.toLong(),"内部长度不匹配。")
        // PAY1 is inspected only after GCM authentication by the caller. Count the
        // still-resident carrier/cipher/plain plus encoded copy and inflation output.
        val additional=stored + (if(compression==1)original else 0L) + 4L*nameLength + MemoryChecks.BUFFER_OVERHEAD
        MemoryChecks.admit(residentBytes+plain.size,additional,limits,"恢复 $original 字节文件")
        val name=metadataFilename(decodeUtf8(ByteArray(nameLength).also(b::get)))
        val encoded=ByteArray(stored.toInt()).also(b::get)
        var data: ByteArray?=null
        try {
            control.report("解压与校验")
            data=if(compression==1)inflateExact(encoded,original.toInt(),control) else encoded
            demand(data.size.toLong()==original,"恢复文件大小不匹配。")
            demand(MessageDigest.isEqual(digest,MessageDigest.getInstance("SHA-256").digest(data)),"恢复文件 SHA-256 不匹配。")
            control.check()
            return Decoded(name,data,stored.toInt(),compression==1,mode)
        } catch(error: Throwable) { data?.fill(0);encoded.fill(0);throw error }
        finally { if(compression==1)encoded.fill(0) }
    }
    fun deflate(data: ByteArray,control: Control): ByteArray {
        val d=Deflater(9);val out=ByteArrayOutputStream(minOf(data.size,65536));val buffer=ByteArray(32768)
        return try {
            d.setInput(data);d.finish()
            while(!d.finished()){control.check();val n=d.deflate(buffer);demand(n>0 || d.finished(),"压缩器没有取得进展。");out.write(buffer,0,n)}
            out.toByteArray()
        } finally {d.end();buffer.fill(0)}
    }
    fun inflateExact(data: ByteArray,expected: Int,control: Control): ByteArray {
        control.check()
        MemoryChecks.checkAdditional(expected.toLong()+MemoryChecks.BUFFER_OVERHEAD,"解压 $expected 字节文件")
        val z=Inflater();val out=ByteArray(expected);var offset=0
        try {
            z.setInput(data)
            while(offset<out.size){
                control.check();val n=z.inflate(out,offset,minOf(32768,out.size-offset))
                if(n==0)break;offset+=n
            }
            val extra=ByteArray(1);val overflow=z.inflate(extra)
            demand(offset==expected && overflow==0 && z.finished() && z.remaining==0 && !z.needsDictionary(),"压缩流截断、过量输出或存在异常尾部。")
            return out
        } catch(e: DataFormatException){out.fill(0);throw StegException("压缩数据损坏。",e)}
        catch(e: Exception){out.fill(0);throw e}
        finally {z.end()}
    }
}
