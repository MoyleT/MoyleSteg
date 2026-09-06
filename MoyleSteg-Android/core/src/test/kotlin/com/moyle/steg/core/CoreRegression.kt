package com.moyle.steg.core

import java.io.File
import java.nio.ByteBuffer
import java.util.zip.CRC32

/** JVM tests have no Android or JUnit dependency; Gradle's check runs this main. */
object CoreRegression {
    @JvmStatic fun main(args: Array<String>) {
        val root = File(args[0]); val out = File(args[1]).apply { mkdirs() }
        var passed = 0
        fun test(name: String, body: () -> Unit) {
            body(); passed++; println("PASS $name")
        }
        fun rejects(body: () -> Unit) {
            var rejected = false
            try { body() } catch (_: StegException) { rejected = true }
            check(rejected) { "malformed input was accepted" }
        }
        val engine = StegEngine()
        val keyFile = File(root, "key.stegkey").readBytes()
        val password = File(root, "password.txt").readText()
        val known = File(root, "known.tsv").readLines().associate { it.split('\t').let { a -> a[0] to a[1] } }
        val cover = File(root, "cover.png").readBytes()
        val credKey = Credential.keyFile(keyFile)
        val rawKey = credKey.secret.copyOf()
        test("key file format and fingerprint") {
            check(Credential.keyFile(Credential.exportKey(rawKey)).secret.contentEquals(rawKey))
            check(Credential.generateKey().size == 32)
            rejects { Credential.keyFile(keyFile + "garbage".toByteArray()) }
        }
        for (mode in listOf("key", "password")) test("known header and derived keys $mode") {
            val c = if (mode == "key") Credential.keyFile(keyFile) else Credential.password(password)
            c.use {
                val h = Header.create(c.mode, ByteArray(16) { it.toByte() }, ByteArray(12) { it.toByte() }, 128)
                check(h.bytes().hex() == known["$mode.header"])
                val keys = Crypto.derive(c, h)
                check(keys.encryption.hex() == known["$mode.enc"])
                check(keys.layout.hex() == known["$mode.layout"]); keys.close()
            }
        }
        for ((k,v) in known.filterKeys { it.startsWith("positions.") }) test("desktop layout $k") {
            val (_,n,m) = k.split('.'); val all = mutableListOf<Int>()
            Layout.positions(n.toInt(), m.toInt(), rawKey) { all.add(it) }
            check(all.size == m.toInt() && all.distinct().size == all.size)
            val b = ByteBuffer.allocate(all.size * 4); all.forEach(b::putInt)
            check(sha256(b.array()) == v)
        }
        test("PNG preserves RGB in fully transparent pixels") {
            val image = PngCodec.decode(cover, Limits(), Control())
            check(image.rgba.contentEquals(File(root, "cover.rgba").readBytes()))
            check(PngCodec.decode(PngCodec.encode(image, Limits(), Control()), Limits(), Control()).rgba.contentEquals(image.rgba))
        }
        File(root, "cases.tsv").forEachLine { line ->
            val (base,source,name,mode) = line.split('\t')
            val expected = File(root,source).readBytes()
            val c = if (mode == "key") Credential.keyFile(keyFile) else Credential.password(password)
            c.use {
                for (ext in listOf("saes", "png")) test("Python to Kotlin $base.$ext") {
                    val r = engine.decode(File(root,"$base.$ext").readBytes(), c)
                    check(r.filename == name); check(r.data.contentEquals(expected)); r.data.fill(0)
                }
                test("Kotlin outputs and in-process roundtrip $base") {
                    val saes = engine.encrypt(name,expected,c)
                    val png = engine.hide(cover,name,expected,c)
                    File(out,"$base.saes").writeBytes(saes); File(out,"$base.png").writeBytes(png)
                    check(engine.decode(saes,c).data.contentEquals(expected))
                    check(engine.decode(png,c).data.contentEquals(expected))
                    val before = PngCodec.decode(cover,Limits(),Control()).rgba
                    val after = PngCodec.decode(png,Limits(),Control()).rgba
                    for (i in before.indices) {
                        if (i % 4 == 3) check(before[i] == after[i])
                        else check(kotlin.math.abs((before[i].toInt() and 255) - (after[i].toInt() and 255)) <= 1)
                    }
                }
            }
        }
        val sample = File(root,"random_key.saes").readBytes()
        test("wrong key rejected") { Credential.key(ByteArray(32)).use { rejects { engine.decode(sample,it) } } }
        test("wrong credential mode rejected") { Credential.password("wrong").use { rejects { engine.decode(sample,it) } } }
        test("wrong password rejected") {
            Credential.password("wrong").use { rejects { engine.decode(File(root,"random_password.saes").readBytes(),it) } }
        }
        test("ciphertext corruption rejected") { rejects { engine.decode(sample.copyOf().apply { this[lastIndex] = (this[lastIndex].toInt() xor 1).toByte() },credKey) } }
        test("truncated and appended SAES rejected") {
            rejects { engine.decode(sample.copyOf(sample.size-1),credKey) }
            rejects { engine.decode(sample + byteArrayOf(1),credKey) }
        }
        test("header CRC corruption rejected") { rejects { engine.decode(sample.copyOf().apply { this[15]++ },credKey) } }
        test("CRC-correct AAD forgery rejected") {
            val bad = sample.copyOf(); bad[15]++
            val crc = CRC32().apply { update(bad,0,50) }.value
            ByteBuffer.wrap(bad,50,4).putInt(crc.toInt())
            rejects { engine.decode(bad,credKey) }
        }
        test("untrusted huge length rejected") {
            val bad = sample.copyOf(); ByteBuffer.wrap(bad,42,8).putLong(Long.MAX_VALUE)
            ByteBuffer.wrap(bad,50,4).putInt(CRC32().apply { update(bad,0,50) }.value.toInt())
            rejects { engine.decode(bad,credKey) }
        }
        test("unsupported KDF rejected before derivation") {
            val bad = File(root,"random_password.saes").readBytes();bad[10]=30
            ByteBuffer.wrap(bad,50,4).putInt(CRC32().apply { update(bad,0,50) }.value.toInt())
            Credential.password(password).use { rejects { engine.decode(bad,it) } }
        }
        test("decoded payload budget") { rejects { StegEngine(Limits(maxPayloadBytes=1024)).decode(File(root,"compressed_key.saes").readBytes(),credKey) } }
        test("input container budget") { rejects { StegEngine(Limits(maxContainerBytes=100)).decode(sample,credKey) } }
        test("pixel budget") { rejects { PngCodec.decode(cover, Limits(maxPixels=100),Control()) } }
        test("safe output names") { for (n in listOf("../escape","CON.txt","x:y", "bad\\path", "", "x.","x ")) rejects { engine.encrypt(n,byteArrayOf(1),credKey) } }
        test("empty password rejected") { rejects { Credential.password("") } }
        test("payload input budget") { rejects { StegEngine(Limits(maxPayloadBytes=1)).encrypt("x",byteArrayOf(1,2),credKey) } }
        test("capacity preflight agrees") {
            val p = engine.preflight(cover,"x",ByteArray(1024))
            check(p.fits && p.width==384 && p.capacityBytes==36810)
        }
        test("capacity refusal without auto resize") {
            val tiny = PngCodec.encode(RgbaImage(8,8,ByteArray(256)),Limits(),Control())
            rejects { engine.hide(tiny,"x",ByteArray(1024),credKey) }
        }
        test("nonce and salt fresh per operation") {
            check(!engine.encrypt("x",byteArrayOf(1),credKey).contentEquals(engine.encrypt("x",byteArrayOf(1),credKey)))
        }
        test("cooperative cancellation") {
            var reports=0
            val stop=Control({_,_,_ -> reports++},{reports>2})
            var cancelled=false
            try { StegEngine(control=stop).hide(cover,"x",ByteArray(8192),credKey) } catch (_: CancelledException) { cancelled=true }
            check(cancelled)
        }
        // Optional independently generated filters and unsupported PNG samples.
        val filterFile=File(root,"filters.rgba")
        if(filterFile.exists()) {
            for(f in 0..4) test("PNG filter $f") {
                check(PngCodec.decode(File(root,"filter$f.png").readBytes(),Limits(),Control()).rgba.contentEquals(filterFile.readBytes()))
            }
            for(n in listOf("palette.png","gray.png","interlaced.png","badcrc.png","truncated.png","apng.png")) test("PNG rejects $n") {
                rejects { PngCodec.decode(File(root,n).readBytes(),Limits(),Control()) }
            }
        }
        for(n in listOf("rgb", "rgb-trns")) test("PNG RGB/tRNS $n") {
            check(PngCodec.decode(File(root,"$n.png").readBytes(),Limits(),Control()).rgba.contentEquals(File(root,"$n.rgba").readBytes()))
        }
        test("bounded input exact boundary") { check(BoundedIo.read(java.io.ByteArrayInputStream(ByteArray(8)),8).size==8) }
        test("bounded input over boundary") { rejects { BoundedIo.read(java.io.ByteArrayInputStream(ByteArray(9)),8) } }
        test("bounded input empty and unknown length") { check(BoundedIo.read(java.io.ByteArrayInputStream(byteArrayOf()),8).isEmpty()) }
        test("bounded input repeated zero progress") {
            rejects { BoundedIo.read(object: java.io.InputStream(){override fun read()=0;override fun read(b: ByteArray,o: Int,n: Int)=0},8) }
        }
        test("bounded hash exact and overflow") {
            check(BoundedIo.hash(java.io.ByteArrayInputStream(ByteArray(8)),8).first==sha256(ByteArray(8)))
            rejects { BoundedIo.hash(java.io.ByteArrayInputStream(ByteArray(9)),8) }
        }
        test("zlib exact and trailing bytes") {
            val data=ByteArray(10000){42};val z=Payload.deflate(data,Control())
            check(Payload.inflateExact(z,data.size,Control()).contentEquals(data))
            rejects { Payload.inflateExact(z,100,Control()) }
            rejects { Payload.inflateExact(z+byteArrayOf(1),data.size,Control()) }
            rejects { Payload.inflateExact(z.copyOf(z.size-1),data.size,Control()) }
        }
        credKey.close();rawKey.fill(0)
        println("RESULT: $passed tests passed")
        File(out,"jvm-result.txt").writeText("$passed tests passed\n")
    }
}
