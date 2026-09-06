package com.moyle.steg.core

import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import java.io.RandomAccessFile
import java.nio.ByteBuffer
import java.security.MessageDigest
import java.util.Random

object SaesFilesRegression {
    @JvmStatic fun main(args: Array<String>) {
        val root=File(args[0]).apply { mkdirs() }
        if(args.size>1 && args[1]=="large"){large(root,args.getOrNull(2)?.toLong() ?: 64L*1024*1024);return}
        if(args.size>1 && args[1]=="lowheap"){lowHeap(root);return}
        val work=File(root,"work-${System.nanoTime()}").apply { mkdirs() }
        val source=File(root,"synthetic-input.bin")
        val container=File(root,"synthetic-container.saes")
        val sourceBytes=ByteArray(192*1024).also {Random(318).nextBytes(it)}
        var passed=0
        fun clean(){work.listFiles().orEmpty().forEach {check(it.isFile && it.delete())}}
        fun test(name:String,body:()->Unit){
            check(work.listFiles().orEmpty().isEmpty());body();passed++;println("PASS $name");clean()
        }
        fun rejects(fragment:String="",body:()->Unit){
            try{body();error("Operation unexpectedly succeeded")}
            catch(e:StegException){check(e.message.orEmpty().contains(fragment)){e.message.orEmpty()}}
            check(work.listFiles().orEmpty().isEmpty()){"Failed operation leaked private temporary files"}
        }
        val keyBytes=ByteArray(32){it.toByte()}
        Credential.key(keyBytes).use { key ->
            test("stream encryption interoperates with existing byte API"){
                source.writeBytes(sourceBytes)
                val result=SaesFiles().encrypt(source,"synthetic.bin",key,work)
                check(result.output!=null && result.output!!.isFile && result.originalBytes==sourceBytes.size.toLong())
                check(StegEngine().decode(result.output!!.readBytes(),key).data.contentEquals(sourceBytes))
                check(result.containerSha256==sha256(result.output!!.readBytes()) && result.payloadSha256==sha256(sourceBytes))
                check(work.listFiles()!!.size==1 && source.readBytes().contentEquals(sourceBytes))
                File(root,"stream-key.saes").writeBytes(result.output!!.readBytes())
                File(root,"source.bin").writeBytes(sourceBytes)
                File(root,"synthetic.stegkey").writeBytes(Credential.exportKey(keyBytes))
            }
            test("byte API encrypted SAES decrypts through streaming file API"){
                container.writeBytes(StegEngine().encrypt("合成-🍓.bin",sourceBytes,key))
                val result=SaesFiles().decrypt(container,key,work)
                check(result.filename=="合成-🍓.bin" && result.output!!.readBytes().contentEquals(sourceBytes))
                check(result.containerSha256==sha256(container.readBytes()) && work.listFiles()!!.size==1)
            }
            test("password stream encryption uses existing scrypt and HKDF format"){
                source.writeBytes(sourceBytes)
                Credential.password("synthetic-stream-password").use { password ->
                    val result=SaesFiles().encrypt(source,"synthetic.bin",password,work)
                    check(StegEngine().decode(result.output!!.readBytes(),password).data.contentEquals(sourceBytes))
                    File(root,"stream-password.saes").writeBytes(result.output!!.readBytes())
                }
            }
            test("empty and highly compressed files preserve PAY1 flags and lengths"){
                for(bytes in listOf(byteArrayOf(),ByteArray(512*1024){65})){
                    source.writeBytes(bytes)
                    val enc=SaesFiles().encrypt(source,"empty-or-compressed.bin",key,work)
                    check(enc.compressed==bytes.isNotEmpty())
                    check(enc.storedBytes<=enc.originalBytes)
                    val dec=SaesFiles().decrypt(enc.output!!,key,work)
                    check(dec.output!!.readBytes().contentEquals(bytes))
                    check(enc.payloadSha256==dec.payloadSha256 && enc.containerSha256==dec.containerSha256)
                    clean()
                }
            }
            test("verify writes only a private encrypted capture and returns no plaintext file"){
                val bytes=StegEngine().encrypt("synthetic.bin",sourceBytes,key);container.writeBytes(bytes)
                var seen=false
                val observer=Control(progress={_,_,_->
                    for(file in work.listFiles().orEmpty()){
                        if(file.length()>0){seen=true;file.inputStream().use {input->check(StreamGcm.exact(input,8).contentEquals(Header.MAGIC))}}
                    }
                })
                val result=SaesFiles(control=observer).verify(container,key,work)
                check(seen && result.output==null && result.payloadSha256==sha256(sourceBytes))
                check(work.listFiles().orEmpty().isEmpty() && container.readBytes().contentEquals(bytes))
            }
            test("wrong key is rejected before any private plaintext is created"){
                container.writeBytes(StegEngine().encrypt("synthetic.bin",sourceBytes,key))
                Credential.key(ByteArray(32){99}).use { wrong ->rejects{SaesFiles().decrypt(container,wrong,work)}}
            }
            test("wrong password and credential mode fail authentication"){
                Credential.password("correct synthetic password").use { password ->
                    container.writeBytes(StegEngine().encrypt("synthetic.bin",sourceBytes,password))
                }
                Credential.password("wrong synthetic password").use { wrong ->rejects{SaesFiles().verify(container,wrong,work)}}
                rejects{SaesFiles().decrypt(container,key,work)}
            }
            test("ciphertext bit flips tag flips truncation and trailing data leave no output"){
                val original=StegEngine().encrypt("synthetic.bin",sourceBytes,key)
                for(bytes in listOf(original.copyOf().also {it[100]=(it[100].toInt() xor 1).toByte()},
                    original.copyOf().also {it[it.lastIndex]=(it.last().toInt() xor 1).toByte()},original.copyOf(original.size-1),original+byteArrayOf(0))){
                    container.writeBytes(bytes);rejects{SaesFiles().decrypt(container,key,work)}
                }
            }
            test("header CRC and costly scrypt parameters are rejected before derivation"){
                val normal=Header.create(1,ByteArray(16),ByteArray(12),16)
                for(h in listOf(normal.bytes().also {it[10]=16},normal.copy(core=normal.core.copyOf().also {it[10]=16}).bytes())){
                    container.writeBytes(h+ByteArray(16));var derived=false
                    rejects{SaesFiles(control=Control(progress={s,_,_->if(s=="派生密钥")derived=true})).verify(container,key,work)}
                    check(!derived)
                }
            }
            test("source payload and complete container budgets reject before large work"){
                source.writeBytes(ByteArray(33))
                rejects{SaesFiles(FileLimits(maxPayloadBytes=32)).encrypt(source,"synthetic.bin",key,work)}
                container.writeBytes(StegEngine().encrypt("synthetic.bin",sourceBytes,key))
                rejects{SaesFiles(FileLimits(maxContainerBytes=container.length()-1)).verify(container,key,work)}
            }
            test("impossible output budget rejects before reading or compressing source"){
                source.writeBytes(sourceBytes);var captured=false
                val ctl=Control(progress={stage,_,_->if(stage=="捕获与压缩源文件")captured=true})
                rejects{SaesFiles(FileLimits(maxContainerBytes=64),ctl).encrypt(source,"synthetic.bin",key,work)}
                check(!captured)
            }
            test("exact final container budget succeeds and one byte less rejects"){
                source.writeBytes(sourceBytes)
                val first=SaesFiles().encrypt(source,"synthetic.bin",key,work);val length=first.output!!.length();clean()
                val equal=SaesFiles(FileLimits(maxContainerBytes=length)).encrypt(source,"synthetic.bin",key,work)
                check(equal.output!!.length()==length);clean()
                rejects{SaesFiles(FileLimits(maxContainerBytes=length-1)).encrypt(source,"synthetic.bin",key,work)}
            }
            test("one GiB header boundary validates without allocating claimed payload"){
                val maximum=(1L shl 30)+Payload.FIXED+65535+16
                val header=Header.create(2,ByteArray(16),ByteArray(12),maximum.toInt())
                check(Header.parse(header.bytes(),maximum).cipherLength.toLong()==maximum)
                rejects{Header.parse(header.bytes(),maximum-1)}
                container.writeBytes(header.bytes())
                rejects{SaesFiles().verify(container,key,work)}
                val tooLong=header.copy(core=header.core.copyOf().also {ByteBuffer.wrap(it).putLong(42,Int.MAX_VALUE.toLong()+1)})
                rejects{Header.parse(tooLong.bytes(),Long.MAX_VALUE)}
            }
            test("authenticated PAY1 size beyond one GiB fails without large allocation"){
                container.writeBytes(forge(payload(byteArrayOf(),original=(1L shl 30)+1),key))
                rejects{SaesFiles().verify(container,key,work)}
            }
            test("authenticated metadata length digest and unsupported compression are rejected"){
                val valid=payload(byteArrayOf(1,2,3))
                for(p in listOf(valid.copyOf().also {it[5]=2},valid.copyOf().also {it[24]=(it[24].toInt() xor 1).toByte()},
                    valid.copyOf().also {ByteBuffer.wrap(it).putLong(16,4)},valid.copyOf().also {it[7]=0})){
                    container.writeBytes(forge(p,key));rejects{SaesFiles().decrypt(container,key,work)}
                }
            }
            test("authenticated compression bomb refuses before writing excessive plaintext"){
                val huge=ByteArray(2*1024*1024){65};val zipped=Payload.deflate(huge,Control())
                container.writeBytes(forge(payload(zipped,original=1,compressed=true,digest=sha(byteArrayOf(65))),key))
                rejects{SaesFiles(FileLimits(maxPayloadBytes=4096)).decrypt(container,key,work)}
                rejects{SaesFiles(FileLimits(maxPayloadBytes=4096)).verify(container,key,work)}
            }
            test("zlib truncation extra trailing bytes and concatenated streams are rejected"){
                val raw=ByteArray(4096){65};val zipped=Payload.deflate(raw,Control())
                for(encoded in listOf(zipped.copyOf(zipped.size-1),zipped+byteArrayOf(0),zipped+zipped)){
                    container.writeBytes(forge(payload(encoded,original=raw.size.toLong(),compressed=true,digest=sha(raw)),key))
                    rejects{SaesFiles().verify(container,key,work)}
                }
            }
            test("authenticated path traversal metadata is rejected without using its path"){
                container.writeBytes(forge(payload(byteArrayOf(),name="../outside.bin"),key))
                rejects{SaesFiles().decrypt(container,key,work)}
            }
            test("legacy reserved filename remains metadata and output uses a fresh private name"){
                container.writeBytes(forge(payload(byteArrayOf(7),name="CON.txt"),key))
                val result=SaesFiles().decrypt(container,key,work)
                check(result.filename=="CON.txt" && result.output!!.name.startsWith("moyle-sf-") && result.output!!.readBytes().contentEquals(byteArrayOf(7)))
            }
            test("cancellation throughout encryption removes raw compressed and encrypted temporaries"){
                source.writeBytes(sourceBytes)
                for(stage in listOf("捕获与压缩源文件","复核源文件","流式加密","保存后独立回读验证")){
                    var cancelled=false
                    val ctl=Control(progress={s,_,_->if(s==stage)cancelled=true},cancelled={cancelled})
                    rejects{SaesFiles(control=ctl).encrypt(source,"synthetic.bin",key,work)}
                    check(cancelled && source.readBytes().contentEquals(sourceBytes))
                }
            }
            test("cancel capture authentication restoration and decompression cleans every temporary"){
                container.writeBytes(StegEngine().encrypt("synthetic.bin",ByteArray(512*1024){65},key))
                for(stage in listOf("捕获 SAES 容器","完整认证 SAES","完整认证通过","流式恢复","校验原始内容")){
                    var cancelled=false
                    rejects{SaesFiles(control=Control(progress={s,_,_->if(s==stage)cancelled=true},cancelled={cancelled})).decrypt(container,key,work)}
                    check(cancelled)
                }
            }
            test("cancel read-only second pass leaves no plaintext or private ciphertext"){
                container.writeBytes(StegEngine().encrypt("synthetic.bin",sourceBytes,key));var cancelled=false
                rejects{SaesFiles(control=Control(progress={s,_,_->if(s=="只读流式验证")cancelled=true},cancelled={cancelled})).verify(container,key,work)}
                check(cancelled)
            }
            test("source changes during reading are detected even with restored timestamp"){
                for(restoreTime in listOf(false,true)){
                    source.writeBytes(ByteArray(2*1024*1024){65});val oldTime=source.lastModified();var changed=false
                    val ctl=Control(progress={stage,done,_->if(stage=="捕获与压缩源文件" && done>=65536 && !changed){
                        changed=true;source.writeBytes(ByteArray(2*1024*1024){66});if(restoreTime)check(source.setLastModified(oldTime))
                    }})
                    rejects("变化"){SaesFiles(control=ctl).encrypt(source,"synthetic.bin",key,work)};check(changed)
                }
            }
            test("same-length private ciphertext mutation between authentication passes is rejected"){
                for(restore in listOf(false,true)){
                    container.writeBytes(StegEngine().encrypt("synthetic.bin",sourceBytes,key));var changed=false
                    var returned:FileResult?=null
                    val ctl=Control(progress={stage,_,_->if(stage=="完整认证通过" && !changed){
                        changed=true;val captured=work.listFiles()!!.single()
                        RandomAccessFile(captured,"rw").use {f->f.seek(f.length()-1);val b=f.read();f.seek(f.length()-1);f.write(b xor 1)}
                    }})
                    rejects{val api=SaesFiles(control=ctl);returned=if(restore)api.decrypt(container,key,work)else api.verify(container,key,work)}
                    check(changed && returned==null)
                }
            }
            test("saved SAES fault injection is caught by independent readback"){
                source.writeBytes(sourceBytes);var changed=false
                val ctl=Control(progress={stage,_,_->if(stage=="保存后独立回读验证" && !changed){
                    changed=true;val saved=work.listFiles()!!.single()
                    RandomAccessFile(saved,"rw").use {f->f.seek(f.length()-1);val b=f.read();f.seek(f.length()-1);f.write(b xor 1)}
                }})
                rejects{SaesFiles(control=ctl).encrypt(source,"synthetic.bin",key,work)};check(changed)
            }
            test("invalid private work directory causes no source modification"){
                source.writeBytes(sourceBytes)
                rejects{SaesFiles().encrypt(source,"synthetic.bin",key,source)}
                check(source.readBytes().contentEquals(sourceBytes))
            }
            test("disk admission retains thirty-two MiB and uses actual restoration length"){
                source.writeBytes(sourceBytes)
                val low=object:File(work.path){override fun getUsableSpace():Long=32L*1024*1024}
                rejects("磁盘空间不足"){SaesFiles().encrypt(source,"synthetic.bin",key,low)}
                container.writeBytes(StegEngine().encrypt("synthetic.bin",sourceBytes,key))
                rejects("磁盘空间不足"){SaesFiles().verify(container,key,low)}
                val modest=object:File(work.path){override fun getUsableSpace():Long=33L*1024*1024}
                val restored=SaesFiles().decrypt(container,key,modest)
                check(restored.originalBytes==sourceBytes.size.toLong())
            }
            test("injected mid-write IO failure cleans partially written source and encrypted captures"){
                source.writeBytes(sourceBytes)
                container.writeBytes(StegEngine().encrypt("synthetic.bin",sourceBytes,key))
                for(stage in listOf("捕获与压缩源文件","捕获 SAES 容器","流式加密","校验原始内容")){
                    var injected=false
                    val ctl=Control(progress={s,done,_->if(s==stage && done>=65536){injected=true;throw IOException("Synthetic ENOSPC during file work")}})
                    try{
                        if(stage=="捕获 SAES 容器" || stage=="校验原始内容")SaesFiles(control=ctl).decrypt(container,key,work)
                        else SaesFiles(control=ctl).encrypt(source,"synthetic.bin",key,work)
                        error("IO failure was ignored")
                    }catch(e:IOException){check(e.message!!.startsWith("Synthetic ENOSPC"))}
                    check(injected && work.listFiles().orEmpty().isEmpty())
                }
            }
            test("unlink failure preserves original cancellation or IO exception with cleanup suppressed"){
                container.writeBytes(StegEngine().encrypt("synthetic.bin",sourceBytes,key))
                for(cancelledCase in listOf(false,true)){
                    var cancelled=false;var replaced:File?=null
                    val ctl=Control(progress={stage,_,_->if(stage=="完整认证通过"){
                        val captured=work.listFiles()!!.single();check(captured.delete() && captured.mkdir())
                        File(captured,"test-held-file.txt").writeText("synthetic cleanup fault")
                        replaced=captured
                        if(cancelledCase)cancelled=true else throw IOException("Synthetic original IO failure")
                    }},cancelled={cancelled})
                    try{
                        SaesFiles(control=ctl).verify(container,key,work);error("Fault was ignored")
                    }catch(e:Exception){
                        check(if(cancelledCase)e is CancelledException else e is IOException)
                        check(e.suppressed.size==1 && e.suppressed[0] is StegException && e.suppressed[0].message!!.contains("清理失败"))
                    }finally{
                        val directory=replaced!!
                        check(File(directory,"test-held-file.txt").delete() && directory.delete())
                    }
                    check(work.listFiles().orEmpty().isEmpty())
                }
            }
            test("existing unrelated work files are preserved"){
                val sentinel=File(work,"keep-existing.txt").apply{writeText("unchanged")}
                source.writeBytes(sourceBytes);val encrypted=SaesFiles().encrypt(source,"synthetic.bin",key,work)
                check(sentinel.readText()=="unchanged" && work.listFiles()!!.size==2 && encrypted.output!=sentinel)
            }
        }
        check(work.delete());println("$passed streaming SAES regressions passed")
    }
    private fun sha(bytes:ByteArray)=MessageDigest.getInstance("SHA-256").digest(bytes)
    private fun payload(encoded:ByteArray,original:Long=encoded.size.toLong(),compressed:Boolean=false,
                        digest:ByteArray=sha(encoded),name:String="synthetic.bin"):ByteArray {
        val text=utf8(name)
        return ByteBuffer.allocate(Payload.FIXED+text.size+encoded.size).put("PAY1".toByteArray()).put(1)
            .put(if(compressed)1.toByte()else 0.toByte()).putShort(text.size.toShort())
            .putLong(original).putLong(encoded.size.toLong()).put(digest).put(text).put(encoded).array()
    }
    private fun forge(plain:ByteArray,key:Credential):ByteArray {
        val h=Header.create(key.mode,Crypto.random(16),Crypto.random(12),plain.size+16)
        return Crypto.derive(key,h).use {keys->h.bytes()+Crypto.encrypt(plain,h,keys.encryption)}
    }
    private fun large(root:File,bytes:Long){
        require(bytes in 1..(1L shl 30));val work=File(root,"large-work-${System.nanoTime()}").apply{mkdirs()}
        val source=File(root,"large-synthetic.bin");val buffer=ByteArray(65536);val random=Random(177)
        val expected=MessageDigest.getInstance("SHA-256");val started=System.nanoTime()
        FileOutputStream(source).use{out->var remaining=bytes;while(remaining>0){random.nextBytes(buffer);val n=minOf(remaining,buffer.size.toLong()).toInt();out.write(buffer,0,n);expected.update(buffer,0,n);remaining-=n}}
        val hash=expected.digest().hex();buffer.fill(0)
        Credential.key(ByteArray(32){it.toByte()}).use {key->
            val file=SaesFiles().encrypt(source,"large-synthetic.bin",key,work)
            check(file.originalBytes==bytes && file.payloadSha256==hash)
            val verified=SaesFiles().verify(file.output!!,key,work);check(verified.output==null && verified.payloadSha256==hash)
            val restored=SaesFiles().decrypt(file.output!!,key,work)
            val actual=MessageDigest.getInstance("SHA-256")
            restored.output!!.inputStream().use {input->while(true){val n=input.read(buffer);if(n<0)break;actual.update(buffer,0,n)}}
            check(restored.output!!.length()==bytes && actual.digest().hex()==hash)
            check(work.listFiles()!!.toSet()==setOf(file.output,restored.output))
            check(file.output!!.delete() && restored.output!!.delete())
        }
        check(source.delete() && work.delete())
        println("PASS $bytes-byte random SAES file roundtrip and read-only verification; heap=${Runtime.getRuntime().maxMemory()}, seconds=${(System.nanoTime()-started)/1_000_000_000.0}")
    }
    private fun lowHeap(root:File){
        check(Runtime.getRuntime().maxMemory()<56L*1024*1024){"Use a JVM heap below 56 MiB"}
        val work=File(root,"lowheap-work-${System.nanoTime()}").apply{mkdirs()}
        val source=File(root,"lowheap-source.bin").apply{writeBytes(ByteArray(16){65})}
        try {
            Credential.password("synthetic-stream-password").use {password->
                for(operation in listOf("encrypt","verify","decrypt")){
                    try {
                        val api=SaesFiles()
                        when(operation){
                            "encrypt"->api.encrypt(source,"synthetic.bin",password,work)
                            "verify"->api.verify(File(root,"stream-password.saes"),password,work)
                            else->api.decrypt(File(root,"stream-password.saes"),password,work)
                        }
                        error("Password KDF did not reject insufficient heap")
                    }catch(e:StegException){check(e.message.orEmpty().contains("堆预算"))}
                    check(work.listFiles().orEmpty().isEmpty())
                    println("PASS low-heap password $operation refuses before scrypt")
                }
            }
        }finally{work.listFiles().orEmpty().forEach{check(it.delete())};check(work.delete());check(source.delete())}
    }
}
