package com.moyle.steg.core

import java.io.ByteArrayOutputStream
import java.io.File
import java.util.Random

/** Synthetic GIF block, LZW, protocol, budget and animation-preservation regressions. */
object GifRegression {
    @JvmStatic fun main(args: Array<String>) {
        val output = args.firstOrNull()?.let { File(it).apply { mkdirs() } }
        val resources = args.getOrNull(1)?.let(::File) ?: File("core/src/test/resources/gif")
        var passed = 0
        fun test(name: String, body: () -> Unit) { body(); passed++; println("PASS $name") }
        fun rejects(fragment: String = "", body: () -> Unit) {
            try { body(); error("input was accepted") }
            catch (e: StegException) { check(e.message.orEmpty().contains(fragment)) { e.message.orEmpty() } }
        }
        val tiny = minimal()
        val cover = File(resources, "cover.gif").readBytes()
        val data = ByteArray(4096).also { Random(31).nextBytes(it) }
        val originalCover = cover.copyOf(); val originalData = data.copyOf()
        val keyBytes = ByteArray(32) { it.toByte() }
        val engine = StegEngine()
        Credential.key(keyBytes).use { key ->
            val hidden = engine.hide(cover, "synthetic-gif.bin", data, key)
            val saes = GifCarrier.inspect(hidden).payload!!
            test("GIF87a and GIF89a signatures are accepted by content") {
                check(GifCarrier.isGif(tiny) && GifCarrier.isGif(tiny.copyOf().also { it[4] = 55 }))
                check(!GifCarrier.isGif(byteArrayOf(71,73,70)) && !GifCarrier.isGif(tiny.copyOf().also { it[4] = 56 }))
            }
            test("three-frame animated GIF validates with original canvas") {
                val p = GifCarrier.inspect(cover)
                check(p.width == 8 && p.height == 6 && p.frameCount == 3 && p.payload == null)
            }
            test("dictionary growth through twelve bits and reset validates") {
                check(GifCarrier.inspect(File(resources, "dictionary-growth.gif").readBytes()).frameCount == 1)
            }
            test("GIF preflight gives exact output bytes and container capacity") {
                val p = engine.preflight(cover, "synthetic-gif.bin", data)
                check(p.format == "gif" && p.frameCount == 3 && p.fits && !p.expanded)
                check(p.outputBytes == hidden.size.toLong() && p.width == 8 && p.height == 6)
                check(p.outputBytes == cover.size.toLong() + saes.size + (saes.size + 254) / 255 + 15)
                check(p.capacityBytes > StegEngine.capacity(8,6) && p.estimatedWorkingBytes > hidden.size)
            }
            test("automatic PNG expansion setting never resizes GIF") {
                val p = engine.preflight(cover, "synthetic-gif.bin", data, true)
                val result = engine.hide(cover, "synthetic-gif.bin", data, key, true)
                check(!p.expanded && result.size == hidden.size && GifCarrier.inspect(result).width == 8)
            }
            test("GIF key extraction and signature-dispatched decode restore original") {
                for (decoded in listOf(engine.extract(hidden,key),engine.decode(hidden,key))) {
                    check(decoded.filename == "synthetic-gif.bin" && decoded.data.contentEquals(data))
                }
            }
            test("GIF password path preserves current SAES protocol") {
                Credential.password("synthetic-gif-password").use { password ->
                    val result = engine.hide(cover,"synthetic-gif.bin",data,password)
                    check(engine.decode(result,password).data.contentEquals(data))
                    check(engine.decrypt(GifCarrier.inspect(result).payload!!,password).data.contentEquals(data))
                    output?.let { File(it,"gif-password.gif").writeBytes(result) }
                }
            }
            test("GIF empty Unicode filename and compressed payload roundtrip") {
                for (bytes in listOf(byteArrayOf(),ByteArray(20_000) { 65 })) {
                    val restored = engine.decode(engine.hide(tiny,"合成-🍓.txt",bytes,key),key)
                    check(restored.filename == "合成-🍓.txt" && restored.data.contentEquals(bytes))
                }
            }
            test("cover and source arrays remain unchanged") {
                check(cover.contentEquals(originalCover) && data.contentEquals(originalData))
            }
            test("all original frame palette delay transparency and loop bytes are retained") {
                check(hidden.copyOfRange(0,cover.size - 1).contentEquals(cover.copyOfRange(0,cover.size - 1)))
                check(hidden.last() == 0x3b.toByte() && GifCarrier.inspect(hidden).frameCount == 3)
            }
            test("GIF87a cover is upgraded without changing image blocks") {
                val old = tiny.copyOf().also { it[4] = 55 }
                val result = engine.hide(old,"empty.bin",byteArrayOf(),key)
                val before = old.copyOfRange(0,old.size - 1).also { it[4] = 57 }
                check(result.copyOfRange(0,before.size).contentEquals(before) && old[4] == 55.toByte())
            }
            test("wrong key and wrong credential mode do not authenticate") {
                Credential.key(ByteArray(32) { 99 }).use { wrong -> rejects { engine.decode(hidden,wrong) } }
                Credential.password("wrong").use { wrong -> rejects { engine.decode(hidden,wrong) } }
            }
            test("ciphertext corruption is rejected by AES-GCM") {
                val corrupt = saes.copyOf().also { it[it.lastIndex] = (it.last().toInt() xor 1).toByte() }
                rejects { engine.decode(withPayload(cover,corrupt),key) }
            }
            test("animation bytes are not represented as AES authenticated") {
                val changed = hidden.copyOf().also { it[13] = (it[13].toInt() xor 1).toByte() }
                check(engine.decode(changed,key).data.contentEquals(data))
            }
            test("existing Moyle payload cannot be silently overwritten") {
                rejects("已包含") { engine.hide(hidden,"next.bin",data,key) }
                rejects("已包含") { engine.preflight(hidden,"next.bin",data) }
            }
            test("unknown Moyle extension version is refused for cover and recovery") {
                val unknown = withPayload(cover,saes,id="MOYLESTG999")
                rejects("版本") { engine.decode(unknown,key) }
                rejects("已包含") { engine.hide(unknown,"next.bin",data,key) }
            }
            test("duplicate current payload extension is refused") {
                rejects("重复") { engine.decode(withPayload(hidden,saes),key) }
            }
            test("GIF without an application payload is not a successful recovery") {
                rejects("未找到") { engine.decode(cover,key) }
            }
            test("application payload accepts arbitrary legal subblock fragmentation") {
                for (block in listOf(1,7,54,254,255)) {
                    check(engine.decode(withPayload(cover,saes,block),key).data.contentEquals(data))
                }
            }
            test("GIF SAES header and length are checked before authentication") {
                for (payload in listOf(saes.copyOf(12),saes.copyOf(saes.size-1),saes+byteArrayOf(0),saes.copyOf().also {it[0]=0})) {
                    rejects { engine.decode(withPayload(cover,payload),key) }
                }
            }
            test("payload resource budget applies inside GIF") {
                rejects { StegEngine(Limits(maxPayloadBytes=32)).decode(hidden,key) }
            }
            test("exact container output budget succeeds without expansion") {
                val limited = StegEngine(Limits(maxContainerBytes=hidden.size))
                check(limited.preflight(cover,"synthetic-gif.bin",data).fits)
                check(limited.hide(cover,"synthetic-gif.bin",data,key).size == hidden.size)
            }
            test("one byte insufficient output budget refuses before key derivation") {
                var derived = false
                val limited = StegEngine(Limits(maxContainerBytes=hidden.size-1),Control(progress={ stage,_,_ -> if(stage=="派生密钥") derived=true }))
                check(!limited.preflight(cover,"synthetic-gif.bin",data).fits)
                rejects("预算") { limited.hide(cover,"synthetic-gif.bin",data,key) }
                check(!derived)
            }
            test("complete input container budget applies before parsing") {
                rejects("预算") { GifCarrier.inspect(cover,Limits(maxContainerBytes=cover.size-1)) }
                rejects("预算") { StegEngine(Limits(maxContainerBytes=hidden.size-1)).decode(hidden,key) }
            }
            test("single canvas and cumulative frame pixel budgets apply") {
                rejects("像素预算") { GifCarrier.inspect(cover,Limits(maxPixels=47)) }
                rejects("累计像素") { GifCarrier.inspect(cover,Limits(maxGifTotalPixels=143)) }
                check(GifCarrier.inspect(cover,Limits(maxPixels=48,maxGifTotalPixels=144)).frameCount==3)
            }
            test("frame count budget rejects before decoding excess frame") {
                rejects("帧数") { GifCarrier.inspect(cover,Limits(maxGifFrames=2)) }
                check(GifCarrier.inspect(cover,Limits(maxGifFrames=3)).frameCount==3)
            }
            test("cooperative cancellation during frame inspection and GIF embedding") {
                for (target in listOf("检查 GIF 帧","复制 GIF 动画","写入 GIF 容器")) {
                    var cancelled = false
                    val limited = StegEngine(control=Control(progress={ stage,_,_ -> if(stage==target) cancelled=true },cancelled={cancelled}))
                    try { limited.hide(cover,"synthetic-gif.bin",data,key); error("not cancelled") }
                    catch (_: CancelledException) { check(cancelled) }
                }
                check(cover.contentEquals(originalCover) && data.contentEquals(originalData))
            }
            test("truncating a GIF at every byte is rejected") {
                for (n in 0 until tiny.size) rejects { GifCarrier.inspect(tiny.copyOf(n)) }
            }
            test("trailer tails absent images and unknown top-level blocks are rejected") {
                rejects { GifCarrier.inspect(tiny+byteArrayOf(0)) }
                rejects { GifCarrier.inspect(tiny.copyOfRange(0,19)+byteArrayOf(59)) }
                rejects { GifCarrier.inspect(tiny.copyOf().also {it[19]=0x11}) }
            }
            test("image without active palette and out-of-canvas rectangles are rejected") {
                rejects { GifCarrier.inspect(tiny.copyOf().also {it[10]=0}.let {it.copyOfRange(0,13)+it.copyOfRange(19,it.size)}) }
                rejects { GifCarrier.inspect(tiny.copyOf().also {it[20]=1}) }
                rejects { GifCarrier.inspect(tiny.copyOf().also {it[24]=0}) }
            }
            test("invalid graphic-control application and plain-text lengths are rejected") {
                for (ext in listOf(byteArrayOf(0x21,0xf9.toByte(),3,0,0,0,0),byteArrayOf(0x21,0xff.toByte(),10),byteArrayOf(0x21,1,11))) {
                    rejects { GifCarrier.inspect(insertBeforeImage(tiny,ext)) }
                }
            }
            test("GCE flags missing terminator dangling and duplicate controls are rejected") {
                val gce = byteArrayOf(0x21,0xf9.toByte(),4,0,0,0,0,0)
                rejects { GifCarrier.inspect(insertBeforeImage(tiny,gce.copyOf().also {it[3]=0x10})) }
                rejects { GifCarrier.inspect(insertBeforeImage(tiny,gce.copyOf().also {it[7]=1})) }
                rejects { GifCarrier.inspect(tiny.dropLast(1).toByteArray()+gce+byteArrayOf(59)) }
                rejects { GifCarrier.inspect(insertBeforeImage(tiny,gce+gce)) }
            }
            test("bad background transparent index and image reserved bits are rejected") {
                rejects { GifCarrier.inspect(tiny.copyOf().also {it[11]=2}) }
                rejects { GifCarrier.inspect(insertBeforeImage(tiny,byteArrayOf(0x21,0xf9.toByte(),4,1,0,0,2,0))) }
                rejects { GifCarrier.inspect(tiny.copyOf().also {it[28]=8}) }
            }
            test("comment unrelated app and unknown extension contents are not scanned for magic") {
                val text = "MOYLESTG001;GIF89a;".toByteArray()
                val ext = byteArrayOf(0x21,0xfe.toByte(),text.size.toByte())+text+byteArrayOf(0)+
                    byteArrayOf(0x21,0xee.toByte(),1,59,0)+
                    byteArrayOf(0x21,0xff.toByte(),11)+"NOTMOYLE001".toByteArray()+byteArrayOf(1,59,0)
                val added = insertBeforeImage(tiny,ext)
                check(GifCarrier.inspect(added).payload==null)
                check(engine.decode(engine.hide(added,"empty.bin",byteArrayOf(),key),key).data.isEmpty())
            }
            test("plain text extension with valid bounded grid is retained") {
                val ext = byteArrayOf(0x21,1,12,0,0,0,0,1,0,1,0,1,1,1,0,1,65,0)
                check(GifCarrier.inspect(insertBeforeImage(tiny,ext)).frameCount==1)
                rejects { GifCarrier.inspect(insertBeforeImage(tiny,ext.copyOf().also {it[11]=0})) }
            }
            test("LZW special next-code dictionary path validates correct pixel count") {
                check(GifCarrier.inspect(minimal(3,1,codes=intArrayOf(4,0,6,5))).width==3)
            }
            test("LZW permits initial literal because initial clear is recommended") {
                check(GifCarrier.inspect(minimal(codes=intArrayOf(0,5))).frameCount==1)
            }
            test("LZW minimum and invalid dictionary indexes are rejected") {
                rejects { GifCarrier.inspect(tiny.copyOf().also {it[29]=1}) }
                for (codes in listOf(intArrayOf(7,5),intArrayOf(4,7,5),intArrayOf(4,0,7,5),intArrayOf(4,6,5))) {
                    rejects { GifCarrier.inspect(minimal(codes=codes)) }
                }
            }
            test("LZW absent end underflow overflow and palette violations are rejected") {
                for (codes in listOf(intArrayOf(4),intArrayOf(4,5),intArrayOf(4,0,0,5),intArrayOf(4,2,5))) {
                    rejects { GifCarrier.inspect(minimal(codes=codes)) }
                }
            }
            test("LZW trailing full bytes are rejected while final byte padding is allowed") {
                val packed = pack(intArrayOf(4,0,5))
                rejects { GifCarrier.inspect(minimal(compressed=packed+byteArrayOf(0))) }
                check(GifCarrier.inspect(minimal(compressed=packed.copyOf().also {it[it.lastIndex]=(it.last().toInt() or 0xfe).toByte()})).frameCount==1)
            }
            test("existing PNG and standalone SAES continue to decode") {
                check(engine.decode(engine.encrypt("synthetic-gif.bin",data,key),key).data.contentEquals(data))
                val png=PngCodec.encode(RgbaImage(128,128,ByteArray(128*128*4){127}))
                check(engine.decode(engine.hide(png,"synthetic-gif.bin",data,key),key).data.contentEquals(data))
            }
            val python = args.getOrNull(2)?.let(::File) ?: File(resources,"interop")
            val pythonSource = File(python,"source.bin").readBytes()
            test("Python desktop generated key GIF restores exact file on Kotlin") {
                val restored = engine.decode(File(python,"gif-key.gif").readBytes(),key)
                check(restored.filename=="synthetic-gif.bin" && restored.data.contentEquals(pythonSource))
            }
            test("Python desktop generated password GIF restores exact file on Kotlin") {
                Credential.password("synthetic-gif-password").use { password ->
                    val restored=engine.decode(File(python,"gif-password.gif").readBytes(),password)
                    check(restored.filename=="synthetic-gif.bin" && restored.data.contentEquals(pythonSource))
                }
            }
            output?.let {
                File(it,"animated-cover.gif").writeBytes(cover)
                File(it,"source.bin").writeBytes(data)
                File(it,"synthetic.stegkey").writeBytes(Credential.exportKey(keyBytes))
                File(it,"gif-key.gif").writeBytes(hidden)
            }
        }
        println("$passed GIF regressions passed")
    }

    private fun insertBeforeImage(gif: ByteArray, ext: ByteArray) = gif.copyOfRange(0,19)+ext+gif.copyOfRange(19,gif.size)
    private fun pack(codes: IntArray): ByteArray {
        val result = ByteArray((codes.size*3+7)/8)
        for ((index,code) in codes.withIndex()) for (bit in 0..2) if(code and (1 shl bit)!=0) {
            val at=index*3+bit; result[at/8]=(result[at/8].toInt() or (1 shl(at%8))).toByte()
        }
        return result
    }
    private fun minimal(width: Int=1,height: Int=1,codes: IntArray=intArrayOf(4,0,5),compressed: ByteArray=pack(codes)): ByteArray =
        byteArrayOf(71,73,70,56,57,97,width.toByte(),0,height.toByte(),0,0x80.toByte(),0,0,0,0,0,-1,-1,-1,
            44,0,0,0,0,width.toByte(),0,height.toByte(),0,0,2,compressed.size.toByte())+compressed+byteArrayOf(0,59)
    private fun withPayload(cover: ByteArray,saes: ByteArray,block: Int=255,id: String="MOYLESTG001"): ByteArray {
        val out=ByteArrayOutputStream();out.write(cover,0,cover.size-1)
        out.write(byteArrayOf(0x21,0xff.toByte(),11));out.write(id.toByteArray(Charsets.US_ASCII))
        var offset=0
        while(offset<saes.size){val n=minOf(block,saes.size-offset);out.write(n);out.write(saes,offset,n);offset+=n}
        out.write(0);out.write(59);return out.toByteArray()
    }
}
