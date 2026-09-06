package com.moyle.steg.core

/** APIs consume one captured byte sequence. UI/file providers must enforce bounded capture. */
class StegEngine(private val limits: Limits=Limits(),private val control: Control=Control()) {
    fun encrypt(filename: String,data: ByteArray,credential: Credential): ByteArray {
        val packed=Payload.build(filename,data,limits,control)
        try {
            val h=Header.create(credential.mode,Crypto.random(16),Crypto.random(12),packed.bytes.size+16)
            admitCrypto(data.size.toLong()+packed.bytes.size,h,"SAES 加密")
            control.report("派生密钥")
            Crypto.derive(credential,h).use { keys ->
                control.report("加密")
                val output=h.bytes()+Crypto.encrypt(packed.bytes,h,keys.encryption)
                demand(output.size<=limits.maxContainerBytes,"输出容器超过预算。")
                return output
            }
        }finally{packed.bytes.fill(0)}
    }
    fun decode(container: ByteArray,credential: Credential): Decoded {
        demand(container.size<=limits.maxContainerBytes,"完整容器超过处理预算；不要缩放或重新保存已有隐写图。")
        return if(PngCodec.isPng(container) || GifCarrier.isGif(container))extract(container,credential) else decrypt(container,credential)
    }
    fun decrypt(container: ByteArray,credential: Credential): Decoded = decryptResident(container,credential,0L)
    private fun decryptResident(container: ByteArray,credential: Credential,retainedBytes: Long): Decoded {
        control.check();demand(container.size<=limits.maxContainerBytes && container.size>=Header.SIZE,"SAES 容器长度无效或超过预算。")
        val h=Header.parse(container.copyOfRange(0,Header.SIZE),limits)
        demand(Header.SIZE.toLong()+h.cipherLength==container.size.toLong(),"SAES 文件被截断或含多余尾部。")
        val resident=retainedBytes+container.size
        admitCrypto(resident,h,"容器认证与解密")
        control.report("派生密钥")
        Crypto.derive(credential,h).use { keys ->
            MemoryChecks.admit(resident,3L*h.cipherLength+MemoryChecks.BUFFER_OVERHEAD,limits,"容器认证与解密")
            control.report("认证与解密")
            val cipher=container.copyOfRange(Header.SIZE,container.size)
            try {
                val plain=Crypto.decrypt(cipher,h,keys.encryption)
                return try{Payload.parse(plain,h.mode,limits,control,resident+cipher.size)}finally{plain.fill(0)}
            } finally { cipher.fill(0) }
        }
    }
    fun preflight(cover: ByteArray,filename: String,data: ByteArray,autoExpand: Boolean=false): Preflight {
        if (GifCarrier.isGif(cover)) {
            val info = GifCarrier.coverInfo(cover, limits, control)
            val p = Payload.build(filename, data, limits, control)
            return try { GifCarrier.plan(cover, info, p.bytes.size, data.size, p.compressed, limits) }
            finally { p.bytes.fill(0) }
        }
        // Parse the full PNG as well: unsupported/invalid files must not get a positive preflight.
        val image=PngCodec.decode(cover,limits,control)
        try {
            val p=Payload.build(filename,data,limits,control)
            return try{CoverExpansion.plan(image,cover.size,p.bytes.size+16,data.size,p.compressed,autoExpand,limits)}
            finally{p.bytes.fill(0)}
        } finally{image.rgba.fill(0)}
    }
    fun hide(cover: ByteArray,filename: String,data: ByteArray,credential: Credential,autoExpand: Boolean=false): ByteArray {
        if (GifCarrier.isGif(cover)) {
            val info = GifCarrier.coverInfo(cover, limits, control)
            val p = Payload.build(filename, data, limits, control)
            try {
                val plan = GifCarrier.plan(cover, info, p.bytes.size, data.size, p.compressed, limits)
                demand(plan.fits, "GIF 输出容器超过处理预算；请使用独立 SAES。")
                val h = Header.create(credential.mode, Crypto.random(16), Crypto.random(12), p.bytes.size + 16)
                admitCrypto(cover.size.toLong()+data.size+p.bytes.size,h,"GIF 加密")
                control.report("派生密钥")
                Crypto.derive(credential, h).use { keys ->
                    control.report("加密")
                    val saes = h.bytes() + Crypto.encrypt(p.bytes, h, keys.encryption)
                    return try { GifCarrier.embedValidated(cover, saes, limits, control) } finally { saes.fill(0) }
                }
            } finally { p.bytes.fill(0) }
        }
        var image=PngCodec.decode(cover,limits,control)
        try {
          val p=Payload.build(filename,data,limits,control)
          try{
            val plan=CoverExpansion.plan(image,cover.size,p.bytes.size+16,data.size,p.compressed,autoExpand,limits)
            demand(plan.fits,"载体容量不足；请开启自动扩容、选择更大载体，或使用独立 SAES。")
            if(plan.expanded){
                val old=image
                image=CoverExpansion.resize(old,plan,control)
                old.rgba.fill(0)
            }
            val h=Header.create(credential.mode,Crypto.random(16),Crypto.random(12),p.bytes.size+16)
            admitCrypto(cover.size.toLong()+data.size+image.rgba.size+p.bytes.size,h,
                "PNG ${image.width}×${image.height}（${image.width.toLong()*image.height} 像素）加密")
            control.report("派生密钥")
            Crypto.derive(credential,h).use { keys ->
                control.report("加密")
                val cipher=Crypto.encrypt(p.bytes,h,keys.encryption)
                val head=h.bytes()
                for(bit in 0 until Header.BITS)setBit(image.rgba,bit,(head[bit/8].toInt() ushr(7-bit%8)) and 1)
                var i=0
                Layout.positions(image.width*image.height*3-Header.BITS,cipher.size*8,keys.layout,control){p0 ->
                    if(i%32768==0)control.report("写入像素",i/8,cipher.size)
                    setBit(image.rgba,p0+Header.BITS,(cipher[i/8].toInt() ushr(7-i%8)) and 1);i++
                }
            }
            return PngCodec.encode(image,limits,control)
          }finally{p.bytes.fill(0)}
        }finally{image.rgba.fill(0)}
    }
    fun extract(container: ByteArray,credential: Credential): Decoded {
        if (GifCarrier.isGif(container)) {
            val saes = GifCarrier.inspect(container, limits, control).payload
            demand(saes != null, "GIF 中未找到 MoyleSteg 载荷。")
            return try { decryptResident(saes!!, credential,container.size.toLong()) } finally { saes!!.fill(0) }
        }
        val image=PngCodec.decode(container,limits,control)
        try{
            demand(image.width.toLong()*image.height*3>=Header.BITS,"图片太小，不能含 MoyleSteg 头部。")
            val hb=ByteArray(Header.SIZE)
            for(i in 0 until Header.BITS) hb[i/8]=(hb[i/8].toInt() or ((image.rgba[Layout.rawIndex(i)].toInt() and 1) shl(7-i%8))).toByte()
            val h=Header.parse(hb,limits)
            demand(h.cipherLength<=capacity(image.width,image.height),"隐写长度超过图片容量。")
            val resident=container.size.toLong()+image.rgba.size
            val stage="PNG ${image.width}×${image.height}（${image.width.toLong()*image.height} 像素）提取"
            // Header length is known before any cipher/plain allocation or layout traversal.
            admitCrypto(resident,h,stage)
            control.report("派生密钥")
            Crypto.derive(credential,h).use { keys ->
                MemoryChecks.admit(resident,3L*h.cipherLength+MemoryChecks.BUFFER_OVERHEAD,limits,stage)
                val cipher=ByteArray(h.cipherLength);var i=0
                try {
                    Layout.positions(image.width*image.height*3-Header.BITS,cipher.size*8,keys.layout,control){p0 ->
                        if(i%32768==0)control.report("提取像素",i/8,cipher.size)
                        cipher[i/8]=(cipher[i/8].toInt() or ((image.rgba[Layout.rawIndex(p0+Header.BITS)].toInt() and 1) shl(7-i%8))).toByte();i++
                    }
                    MemoryChecks.admit(resident+cipher.size,2L*h.cipherLength+MemoryChecks.BUFFER_OVERHEAD,limits,stage)
                    control.report("认证与解密")
                    val plain=Crypto.decrypt(cipher,h,keys.encryption)
                    return try{Payload.parse(plain,h.mode,limits,control,resident+cipher.size)}finally{plain.fill(0)}
                } finally { cipher.fill(0) }
            }
        }finally{image.rgba.fill(0)}
    }
    private fun admitCrypto(resident: Long,header: Header,stage: String) {
        // AES providers may retain an input buffer and a plaintext/output copy.
        // scrypt's fixed N=32768,r=8 profile uses about 32 MiB plus array overhead.
        val aes=3L*header.cipherLength+MemoryChecks.BUFFER_OVERHEAD
        val derive=if(header.mode==1)40L*1024*1024 else MemoryChecks.BUFFER_OVERHEAD
        MemoryChecks.admit(resident,maxOf(aes,derive),limits,stage)
    }
    companion object {
        fun capacity(w: Int,h: Int): Int {val n=(w.toLong()*h*3-Header.BITS)/8;return maxOf(0,minOf(Int.MAX_VALUE.toLong(),n)).toInt()}
        private fun setBit(raw: ByteArray,logical: Int,bit: Int){val p=Layout.rawIndex(logical);raw[p]=((raw[p].toInt() and 254) or bit).toByte()}
    }
}
