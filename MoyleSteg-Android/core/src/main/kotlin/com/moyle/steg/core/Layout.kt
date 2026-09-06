package com.moyle.steg.core

import java.nio.ByteBuffer

/** Exact desktop layout v1. Do not replace with Kotlin Random or a global shuffle. */
internal object Layout {
    private class CounterRandom(private val key: ByteArray,private val context: ByteArray) {
        private var counter=0L;private var block=ByteArray(0);private var cursor=0
        private fun nextByte(): Int {
            if(cursor==block.size){block=Crypto.hmac(key,context+ByteBuffer.allocate(8).putLong(counter++).array());cursor=0}
            return block[cursor++].toInt() and 255
        }
        fun below(upper: Int): Int {
            require(upper>0)
            // Python uses upper.bit_length(), not (upper - 1).bit_length().
            val count=maxOf(1,(32-Integer.numberOfLeadingZeros(upper)+7)/8)
            val space=1L shl(count*8); val limit=space-space%upper
            while(true){var x=0L;repeat(count){x=(x shl 8) or nextByte().toLong()};if(x<limit)return (x%upper).toInt()}
        }
    }
    fun positions(total: Int,needed: Int,key: ByteArray,control: Control=Control(),visit: (Int)->Unit) {
        demand(total>=0 && needed>=0 && needed<=total && key.size>=16,"隐写位置参数错误。")
        if(needed==0)return
        var start=0
        while(start<total){
            control.check()
            val end=minOf(total,start+4096);val count=((needed.toLong()*end)/total-(needed.toLong()*start)/total).toInt()
            if(count>0){
                val offsets=IntArray(end-start){it}
                val context="PNG-STEG-AES256/layout-block/".toByteArray(Charsets.US_ASCII)+ByteBuffer.allocate(8).putLong((start/4096).toLong()).array()
                val rng=CounterRandom(key,context)
                for(i in 0 until count){val j=i+rng.below(offsets.size-i);val x=offsets[i];offsets[i]=offsets[j];offsets[j]=x;visit(start+offsets[i])}
            }
            start=end
        }
    }
    fun rawIndex(logical: Int): Int = (logical/3)*4+logical%3
}
