package com.moyle.steg.core

import java.nio.ByteBuffer
import java.nio.charset.CodingErrorAction
import java.security.MessageDigest
import java.security.SecureRandom
import java.util.Base64

open class StegException(message: String, cause: Throwable? = null) : Exception(message, cause)
class AuthenticationException : StegException("认证失败：口令／密钥不正确，或容器已被修改。")
class CancelledException : StegException("操作已取消；没有发布已验证的成品。")
internal fun demand(value: Boolean, message: String) { if (!value) throw StegException(message) }

data class Limits(
    val maxPayloadBytes: Int = 4 * 1024 * 1024,
    val maxPixels: Int = 12_000_000,
    val maxContainerBytes: Int = 64 * 1024 * 1024,
    /** PNG codec buffers, including its encoded input; an estimate, not a reservation. */
    val maxPngWorkingBytes: Long = 96L * 1024 * 1024,
    val maxPngRowBytes: Int = 4 * 1024 * 1024,
    val maxGifFrames: Int = 500,
    val maxGifTotalPixels: Long = 100_000_000
) {
    init {
        require(maxPayloadBytes in 1..(32 * 1024 * 1024))
        require(maxPixels in 1..100_000_000)
        require(maxContainerBytes in 1..(128 * 1024 * 1024))
        require(maxPngWorkingBytes in 1..(512L * 1024 * 1024))
        require(maxPngRowBytes in 1..(100 * 1024 * 1024))
        require(maxGifFrames in 1..500)
        require(maxGifTotalPixels in 1..100_000_000)
    }
    internal val maxCiphertext: Int get() = maxPayloadBytes + 56 + 65535 + 16
}

class Control(
    private val progress: (String, Int, Int) -> Unit = { _, _, _ -> },
    private val cancelled: () -> Boolean = { false }
) {
    fun check() { if (cancelled() || Thread.currentThread().isInterrupted) throw CancelledException() }
    fun report(stage: String, completed: Int = 0, total: Int = 0) {
        check(); progress(stage, completed, total); check()
    }
}

/** Never serialize credentials into UI saved state. close() is best-effort wiping. */
class Credential private constructor(val mode: Int, internal val secret: ByteArray) : AutoCloseable {
    private var closed = false
    internal fun ensureOpen() { demand(!closed, "凭据已清除，请重新输入。") }
    override fun close() { secret.fill(0); closed = true }
    override fun toString() = "Credential(mode=$mode, secret=<redacted>)"
    companion object {
        const val KEY_HEADER = "PNG-STEG-AES256-KEY-V1"
        fun password(value: String): Credential {
            val b = utf8(value)
            demand(b.isNotEmpty() && b.size <= 4096, "口令不能为空，且 UTF-8 长度不能超过 4096 字节。")
            return Credential(1,b)
        }
        fun key(value: ByteArray): Credential {
            demand(value.size == 32, "密钥必须为 32 字节。")
            return Credential(2,value.copyOf())
        }
        fun keyFile(value: ByteArray): Credential {
            demand(value.size <= 256 && value.all { it >= 0 }, "密钥文件格式错误。")
            val lines = String(value, Charsets.US_ASCII).replace("\r\n","\n").removeSuffix("\n").split('\n')
            demand(lines.size == 2 && lines[0] == KEY_HEADER, "不是 MoyleSteg 密钥文件。")
            val encoded = lines[1]
            demand(Regex("[A-Za-z0-9_+/\\-]{43}=").matches(encoded), "密钥 Base64 编码无效。")
            val b = try { Base64.getDecoder().decode(encoded.replace('-','+').replace('_','/')) }
                catch (e: IllegalArgumentException) { throw StegException("密钥编码无效。",e) }
            return try { key(b) } finally { b.fill(0) }
        }
        fun generateKey(): ByteArray = ByteArray(32).also { SecureRandom().nextBytes(it) }
        /** Same domain-separated fingerprint and grouping as desktop MoyleSteg. */
        fun fingerprint(value: ByteArray): String {
            demand(value.size == 32, "密钥必须为 32 字节。")
            val digest = MessageDigest.getInstance("SHA-256")
            digest.update("PNG-STEG-AES256/key-fingerprint/".toByteArray(Charsets.US_ASCII))
            return digest.digest(value).hex().take(20).chunked(4).joinToString("-")
        }
        fun exportKey(value: ByteArray): ByteArray {
            demand(value.size == 32,"密钥必须为 32 字节。")
            return "$KEY_HEADER\n${Base64.getUrlEncoder().encodeToString(value)}\n".toByteArray(Charsets.US_ASCII)
        }
    }
}

class Decoded(val filename: String, val data: ByteArray, val storedSize: Int,
              val compressed: Boolean, val credentialMode: Int) {
    val contentSha256: String get() = sha256(data)
    override fun toString() = "Decoded(filename=<private>, size=${data.size})"
}
data class Preflight(val width: Int, val height: Int, val capacityBytes: Int,
    val ciphertextBytes: Int, val originalBytes: Int, val compressed: Boolean,
    val originalWidth: Int = width, val originalHeight: Int = height,
    /** Conservative PNG working-set estimate, not a heap reservation or output-size guarantee. */
    val estimatedWorkingBytes: Long = 0,
    val format: String = "png", val frameCount: Int = 1, val outputBytes: Long? = null) {
    val fits: Boolean get() = ciphertextBytes <= capacityBytes
    val expanded: Boolean get() = width != originalWidth || height != originalHeight
    val occupancyPercent: Double get() = if (capacityBytes == 0) 0.0 else 100.0 * ciphertextBytes / capacityBytes
}
data class RgbaImage(val width: Int, val height: Int, val rgba: ByteArray) {
    init { require(width > 0 && height > 0 && width.toLong()*height*4 == rgba.size.toLong()) }
    override fun toString() = "RgbaImage(${width}x$height, pixels=<omitted>)"
}
fun sha256(bytes: ByteArray): String = MessageDigest.getInstance("SHA-256").digest(bytes).hex()
internal fun ByteArray.hex(): String = joinToString("") { "%02x".format(it.toInt() and 255) }
internal fun utf8(s: String): ByteArray = try {
    val b = Charsets.UTF_8.newEncoder().onMalformedInput(CodingErrorAction.REPORT)
        .onUnmappableCharacter(CodingErrorAction.REPORT).encode(java.nio.CharBuffer.wrap(s))
    ByteArray(b.remaining()).also { b.get(it) }
} catch(e: java.nio.charset.CharacterCodingException) { throw StegException("无效的 Unicode 文本。",e) }
internal fun decodeUtf8(bytes: ByteArray): String = try {
    Charsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
        .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(bytes)).toString()
} catch(e: java.nio.charset.CharacterCodingException) { throw StegException("文件名不是有效 UTF-8。",e) }

fun safeFilename(name: String): String {
    metadataFilename(name)
    val base=name.substringBefore('.').trimEnd(' ').uppercase(java.util.Locale.ROOT)
    val reserved=base in setOf("CON","PRN","AUX","NUL","CONIN$","CONOUT$") ||
        Regex("(COM|LPT)[1-9¹²³]").matches(base)
    demand(!reserved && !name.endsWith(' ') && !name.endsWith('.') &&
        name.none { it < ' ' || it in "<>:\"/\\|?*" },"文件名不适合跨平台保存，请重命名源文件或手动选择安全的恢复文件名。")
    demand(utf8(name).size <= 65535, "文件名过长。")
    return name
}
internal fun metadataFilename(name: String): String {
    demand(name.isNotEmpty() && name !in setOf(".","..") && name.none { it=='\u0000' || it=='/' || it=='\\' },"容器文件名无效。")
    return name
}
