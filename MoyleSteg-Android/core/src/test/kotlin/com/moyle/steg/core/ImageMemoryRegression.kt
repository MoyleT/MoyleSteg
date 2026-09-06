package com.moyle.steg.core

import java.io.ByteArrayOutputStream
import java.nio.ByteBuffer
import java.security.MessageDigest
import java.util.zip.CRC32
import java.util.zip.DeflaterOutputStream

/** Run scenarios separately; heap admission cases deliberately use a small JVM heap. */
object ImageMemoryRegression {
    private const val MiB = 1024 * 1024
    @JvmStatic fun main(args: Array<String>) {
        when(args.single()) {
            "pixels" -> {
                val png=zeroPng(5000,2600)
                val error=rejected { PngCodec.decode(png) }
                check("13000000" in error.message.orEmpty() && "12000000" in error.message.orEmpty())
                val image=PngCodec.decode(png,Limits(maxPixels=100_000_000,maxPngWorkingBytes=96L*MiB))
                check(image.width==5000 && image.height==2600 && image.rgba.size==52_000_000)
                image.rgba.fill(0)
            }
            "png-aes" -> {
                val raw=ByteArray(2048*1024*4)
                val header=Header.create(2,ByteArray(16),ByteArray(12),700000).bytes()
                for(bit in 0 until Header.BITS) {
                    val position=Layout.rawIndex(bit)
                    raw[position]=((header[bit/8].toInt() ushr (7-bit%8)) and 1).toByte()
                }
                val png=PngCodec.encode(RgbaImage(2048,1024,raw));raw.fill(0)
                var extracted=false
                Credential.key(ByteArray(32)).use { key ->
                    rejected {
                        StegEngine(Limits(maxPngWorkingBytes=10L*MiB),Control(progress={stage,_,_->
                            if(stage=="提取像素")extracted=true
                        })).extract(png,key)
                    }
                }
                check(!extracted) { "cipher allocation/layout began before the complete AES working budget was checked" }
            }
            "payload-budget" -> {
                val plain=compressedZeros(32*MiB)
                var expanded=false
                rejected {
                    Payload.parse(plain,2,Limits(maxPayloadBytes=32*MiB,maxPngWorkingBytes=8L*MiB),
                        Control(progress={stage,_,_->if(stage=="解压与校验")expanded=true}))
                }
                check(!expanded) { "decompression began before its authenticated output size was checked" }
            }
            "payload-heap" -> {
                val plain=compressedZeros(32*MiB)
                val resident=ByteArray(40*MiB) { 7 }
                rejected { Payload.parse(plain,2,Limits(maxPayloadBytes=32*MiB,maxPngWorkingBytes=512L*MiB),Control()) }
                check(resident[resident.lastIndex]==7.toByte())
            }
            "gif-copy" -> {
                val head=Header.create(2,ByteArray(16),ByteArray(12),32*MiB).bytes()
                val gif="GIF89a".toByteArray()+byteArrayOf(1,0,1,0,0,0,0,0x21,0xff.toByte(),11)+
                    "MOYLESTG001".toByteArray()+byteArrayOf(54)+head+byteArrayOf(0,0x3b)
                rejected { GifCarrier.inspect(gif,Limits(maxPayloadBytes=32*MiB,maxPngWorkingBytes=8L*MiB)) }
            }
            "authentication" -> {
                val plain=compressedZeros(32*MiB)
                val header=Header.create(2,ByteArray(16),ByteArray(12),plain.size+16)
                Credential.key(ByteArray(32) { 3 }).use { key ->
                    val container=Crypto.derive(key,header).use { header.bytes()+Crypto.encrypt(plain,header,it.encryption) }
                    val engine=StegEngine(Limits(maxPayloadBytes=32*MiB,maxPngWorkingBytes=8L*MiB))
                    Credential.key(ByteArray(32) { 4 }).use { wrong ->
                        try { engine.decrypt(container,wrong);error("wrong key accepted") }
                        catch(_: AuthenticationException) { }
                    }
                    rejected { engine.decrypt(container,key) }
                }
            }
            else -> error("Unknown memory scenario")
        }
        println("PASS image memory ${args.single()}")
    }

    private fun rejected(action: () -> Unit): StegException {
        try { action() }
        catch(error: StegException) {
            check("预算" in error.message.orEmpty()) { "allocation guard returned an unrelated error: ${error.message}" }
            return error
        }
        catch(error: OutOfMemoryError) { throw AssertionError("allocation exhausted heap before a controlled budget rejection",error) }
        error("operation passed without its memory guard")
    }

    /** Build an authenticated-body fixture without allocating the expanded file. */
    private fun compressedZeros(original: Int): ByteArray {
        val stored=ByteArrayOutputStream();val digest=MessageDigest.getInstance("SHA-256")
        val block=ByteArray(65536)
        DeflaterOutputStream(stored).use { output ->
            var remaining=original
            while(remaining>0) {
                val n=minOf(block.size,remaining);output.write(block,0,n);digest.update(block,0,n);remaining-=n
            }
        }
        val encoded=stored.toByteArray()
        return ByteBuffer.allocate(Payload.FIXED+1+encoded.size).put("PAY1".toByteArray()).put(1).put(1).putShort(1)
            .putLong(original.toLong()).putLong(encoded.size.toLong()).put(digest.digest()).put(120).put(encoded).array()
    }

    private fun zeroPng(width: Int,height: Int): ByteArray {
        val compressed=ByteArrayOutputStream();val block=ByteArray(65536)
        DeflaterOutputStream(compressed).use { output ->
            repeat(height) {
                output.write(0);var remaining=width*4
                while(remaining>0) { val n=minOf(remaining,block.size);output.write(block,0,n);remaining-=n }
            }
        }
        val result=ByteArrayOutputStream()
        result.write(byteArrayOf(-119,80,78,71,13,10,26,10))
        fun chunk(type: String,bytes: ByteArray) {
            val name=type.toByteArray()
            result.write(ByteBuffer.allocate(4).putInt(bytes.size).array());result.write(name);result.write(bytes)
            result.write(ByteBuffer.allocate(4).putInt(CRC32().apply { update(name);update(bytes) }.value.toInt()).array())
        }
        chunk("IHDR",ByteBuffer.allocate(13).putInt(width).putInt(height).put(8).put(6).put(0).put(0).put(0).array())
        chunk("IDAT",compressed.toByteArray());chunk("IEND",byteArrayOf())
        return result.toByteArray()
    }
}
