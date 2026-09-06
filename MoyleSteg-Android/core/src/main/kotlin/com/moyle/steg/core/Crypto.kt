package com.moyle.steg.core

import java.nio.ByteBuffer
import java.security.SecureRandom
import java.util.zip.CRC32
import javax.crypto.Cipher
import javax.crypto.Mac
import javax.crypto.BadPaddingException
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec
import org.bouncycastle.crypto.generators.SCrypt

internal data class Header(val mode: Int, val salt: ByteArray, val nonce: ByteArray,
                           val cipherLength: Int, val core: ByteArray) {
    fun bytes(): ByteArray = core + ByteBuffer.allocate(4).putInt(CRC32().apply{update(core)}.value.toInt()).array()
    companion object {
        const val SIZE = 54
        const val BITS = SIZE * 8
        val MAGIC = "SGAES001".toByteArray(Charsets.US_ASCII)
        fun create(mode: Int, salt: ByteArray, nonce: ByteArray, cipherLength: Int): Header {
            demand(mode in 1..2 && salt.size == 16 && nonce.size==12 && cipherLength>=16,"头部参数无效。")
            val core=ByteBuffer.allocate(50).put(MAGIC).put(1).put(mode.toByte())
                .put(if(mode==1) 15.toByte() else 0.toByte())
                .put(if(mode==1) 8.toByte() else 0.toByte())
                .put(if(mode==1) 1.toByte() else 0.toByte()).put(1)
                .put(salt).put(nonce).putLong(cipherLength.toLong()).array()
            return Header(mode,salt.copyOf(),nonce.copyOf(),cipherLength,core)
        }
        fun parse(bytes: ByteArray, limits: Limits): Header = parse(bytes, limits.maxCiphertext.toLong())
        /** File streaming has its own bounded Long budget; pixel APIs retain their existing limits. */
        fun parse(bytes: ByteArray, maxCiphertext: Long): Header {
            demand(bytes.size==SIZE,"隐写头部长度错误。")
            val core=bytes.copyOfRange(0,50)
            val b=ByteBuffer.wrap(bytes)
            demand(CRC32().apply { update(core) }.value.toInt()==b.getInt(50),"隐写头部校验失败。")
            val magic=ByteArray(8).also(b::get)
            demand(magic.contentEquals(MAGIC) && b.get().toInt()==1,"未知文件格式或版本。")
            val mode=b.get().toInt(); val n=b.get().toInt();val r=b.get().toInt();val p=b.get().toInt()
            demand(mode in 1..2 && b.get().toInt()==1,"未知凭据或布局版本。")
            demand((mode==1 && n==15 && r==8 && p==1) || (mode==2 && n==0 && r==0 && p==0),"不支持的密钥派生参数。")
            val salt=ByteArray(16).also(b::get);val nonce=ByteArray(12).also(b::get);val size=b.long
            demand(size>=16 && size<=maxCiphertext && size<=Int.MAX_VALUE.toLong(),"密文长度超过处理预算或无效。")
            return Header(mode,salt,nonce,size.toInt(),core)
        }
    }
}
internal class DerivedKeys(val encryption: ByteArray,val layout: ByteArray) : AutoCloseable {
    override fun close(){encryption.fill(0);layout.fill(0)}
}
internal object Crypto {
    private val rng = SecureRandom()
    fun random(n: Int)=ByteArray(n).also(rng::nextBytes)
    fun hmac(key: ByteArray, data: ByteArray): ByteArray = Mac.getInstance("HmacSHA256").run {
        init(SecretKeySpec(key,"HmacSHA256"));doFinal(data)
    }
    fun derive(credential: Credential,h: Header): DerivedKeys {
        credential.ensureOpen()
        if(credential.mode != h.mode) throw AuthenticationException()
        val master=if(h.mode==1) SCrypt.generate(credential.secret,h.salt,32768,8,1,32) else credential.secret.copyOf()
        // RFC 5869 HKDF-SHA256, exactly two output blocks. No custom AES/scrypt implementation.
        val prk=hmac(h.salt,master); master.fill(0)
        val info="PNG-STEG-AES256/v1/enc-and-layout".toByteArray(Charsets.US_ASCII)
        return try {
            val first=hmac(prk,info+byteArrayOf(1))
            val second=hmac(prk,first+info+byteArrayOf(2))
            DerivedKeys(first,second)
        } finally { prk.fill(0) }
    }
    fun encrypt(plain: ByteArray,h: Header,key: ByteArray): ByteArray = cipher(Cipher.ENCRYPT_MODE,h,key).doFinal(plain)
    fun decrypt(data: ByteArray,h: Header,key: ByteArray): ByteArray = try {
        cipher(Cipher.DECRYPT_MODE,h,key).doFinal(data)
    } catch(e: BadPaddingException) { throw AuthenticationException() }
    private fun cipher(mode: Int,h: Header,key: ByteArray): Cipher = Cipher.getInstance("AES/GCM/NoPadding").apply {
        init(mode,SecretKeySpec(key,"AES"),GCMParameterSpec(128,h.nonce));updateAAD(h.core)
    }
}
