package com.moyle.steg.android

import android.app.ActivityManager
import android.content.Context
import com.moyle.steg.core.Limits
import com.moyle.steg.core.StegException
import java.util.Locale

data class MemorySnapshot(val heapLimitBytes:Long,val heapUsedBytes:Long,
    val systemAvailableBytes:Long?,val lowMemory:Boolean=false) {
    val heapAvailableBytes:Long get()=(heapLimitBytes-heapUsedBytes).coerceAtLeast(0)
}
data class MemoryPlan(val budgetBytes:Long,val maximumManualMiB:Int,val snapshot:MemorySnapshot)

/** Observations, not reservations. Device RAM never increases the managed-heap limit. */
object DeviceResources {
    fun snapshot(context:Context):MemorySnapshot {
        val runtime=Runtime.getRuntime()
        val info=ActivityManager.MemoryInfo()
        val available=runCatching {
            val manager=context.getSystemService(Context.ACTIVITY_SERVICE) as? ActivityManager
            manager?.getMemoryInfo(info)
            info.availMem.takeIf{it>0}
        }.getOrNull()
        return MemorySnapshot(runtime.maxMemory(),runtime.totalMemory()-runtime.freeMemory(),available,info.lowMemory)
    }
}

object MemoryPolicy {
    const val MIB=1024L*1024
    private const val MINIMUM=32L*MIB
    private const val MAXIMUM=512L*MIB

    fun maximumManualMiB(snapshot:MemorySnapshot):Int {
        if(snapshot.lowMemory)return 0
        val systemBound=snapshot.systemAvailableBytes?.div(4) ?: Long.MAX_VALUE
        return (minOf(MAXIMUM,snapshot.heapLimitBytes-32*MIB,
            snapshot.heapAvailableBytes-16*MIB,systemBound).coerceAtLeast(0)/MIB).toInt()
    }

    fun choose(snapshot:MemorySnapshot,manual:Boolean,manualMiB:Int):MemoryPlan {
        if(snapshot.lowMemory)throw StegException("系统当前处于低内存状态，请关闭其他任务后重试。")
        val maximum=maximumManualMiB(snapshot)
        if(maximum<32)throw StegException("当前应用可用内存不足以保留安全余量，请稍后重试。")
        val bytes=if(manual) {
            if(manualMiB !in 32..maximum)throw StegException("手动内存预算须为 32～$maximum MiB；不能突破当前应用可用堆。")
            manualMiB*MIB
        } else {
            minOf(maximum*MIB,snapshot.heapLimitBytes*65/100,snapshot.heapAvailableBytes*70/100)/MIB*MIB
        }
        if(bytes<MINIMUM)throw StegException("自动评估的可用内存不足 32 MiB，请稍后重试。")
        return MemoryPlan(bytes,maximum,snapshot)
    }

    fun imageLimits(plan:MemoryPlan)=Limits(maxPayloadBytes=32*1024*1024,
        maxPixels=100_000_000,maxContainerBytes=128*1024*1024,
        maxPngWorkingBytes=plan.budgetBytes)

    /** Conservative known-buffer estimate; encrypted original length is not yet available. */
    fun imageEstimate(containerBytes:Long,width:Int,height:Int,format:String,payloadBytes:Long=0):Long {
        if(containerBytes<0 || payloadBytes<0 || width<0 || height<0)
            throw StegException("文件尺寸信息无效。")
        return try{
            val pixelBytes=if(format=="png")Math.multiplyExact(Math.multiplyExact(width.toLong(),height.toLong()),4L) else 0L
            listOf(Math.multiplyExact(4L,containerBytes),pixelBytes,8L*width,MIB,Math.multiplyExact(6L,payloadBytes))
                .fold(0L){sum,part->Math.addExact(sum,part)}
        }catch(_:ArithmeticException){throw StegException("文件尺寸超过可计算的资源预算。")}
    }

    fun requireBytes(plan:MemoryPlan,estimated:Long,phase:String) {
        if(estimated>plan.budgetBytes)throw StegException(
            "$phase 的已知缓冲估算至少 ${mib(estimated)} MiB，超过本次 ${mib(plan.budgetBytes)} MiB 预算。"+
            "可在高级设置中检查可用范围；恢复时请勿缩放或重新保存原隐写图。")
    }

    fun requireCredential(plan:MemoryPlan,useKey:Boolean) {
        val minimum=if(useKey)32*MIB else 64*MIB
        if(plan.budgetBytes<minimum)throw StegException(
            "${if(useKey)"密钥"else "口令派生"}处理需要至少 ${minimum/MIB} MiB 工作预算，请调整高级设置或稍后重试。")
    }

    fun mib(bytes:Long)=String.format(Locale.ROOT,"%.1f",bytes.toDouble()/MIB)
}
