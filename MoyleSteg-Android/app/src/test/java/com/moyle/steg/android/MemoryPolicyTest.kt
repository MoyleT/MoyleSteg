package com.moyle.steg.android

import com.moyle.steg.core.StegException
import org.junit.Assert.*
import org.junit.Test

class MemoryPolicyTest {
    @org.junit.Test fun maliciousHugeHeaderCannotWrapEstimateIntoNegativeBudget(){
        try{MemoryPolicy.imageEstimate(Long.MAX_VALUE,Int.MAX_VALUE,Int.MAX_VALUE,"png",Long.MAX_VALUE);org.junit.Assert.fail("overflow was accepted")}
        catch(_:com.moyle.steg.core.StegException){}
    }
    private val mib=1024L*1024
    private fun phone(heap:Long=512,used:Long=64,system:Long?=8192,low:Boolean=false)=
        MemorySnapshot(heap*mib,used*mib,system?.times(mib),low)
    private fun reject(block:()->Unit){try{block();fail("Expected a bounded resource rejection")}catch(_:StegException){}}

    @Test fun totalDeviceRamNeverOverridesTheApplicationHeap() {
        val plan=MemoryPolicy.choose(phone(heap=256,used=64,system=16*1024),false,128)
        assertTrue(plan.budgetBytes < 192*mib)
        assertTrue(plan.maximumManualMiB <= 176)
    }
    @Test fun automaticBudgetFallsWhenTheApplicationUsesMoreHeap() {
        val idle=MemoryPolicy.choose(phone(used=64),false,128)
        val busy=MemoryPolicy.choose(phone(used=320),false,128)
        assertTrue(busy.budgetBytes < idle.budgetBytes)
    }
    @Test fun manualBudgetIsHonoredWithinTheCurrentBound() {
        assertEquals(96*mib,MemoryPolicy.choose(phone(),true,96).budgetBytes)
    }
    @Test fun manualCannotGrantMoreHeapThanAndroidAllows() {
        reject{MemoryPolicy.choose(phone(heap=256,used=64),true,384)}
    }
    @Test fun manualCannotConsumeTheReservedHeadroom() {
        reject{MemoryPolicy.choose(phone(heap=256,used=224),true,32)}
    }
    @Test fun invalidOrTinyManualBudgetsAreNotSilentlyRaised() {
        reject{MemoryPolicy.choose(phone(),true,-1)}
        reject{MemoryPolicy.choose(phone(),true,16)}
    }
    @Test fun systemLowMemoryRefusesANewHeavyTask() {
        reject{MemoryPolicy.choose(phone(low=true),false,128)}
    }
    @Test fun limitedSystemMemoryAlsoConstrainsTheBudget() {
        reject{MemoryPolicy.choose(phone(system=64),false,128)}
    }
    @Test fun missingSystemObservationStillUsesTheHeapBound() {
        val plan=MemoryPolicy.choose(phone(system=null),false,128)
        assertTrue(plan.budgetBytes in 32*mib..448*mib)
    }
    @Test fun anImageCanExceedBudgetEvenWithASmallEncodedFile() {
        val bytes=MemoryPolicy.imageEstimate(16*mib,6000,4000,"png")
        assertTrue(bytes > 128*mib)
        reject{MemoryPolicy.requireBytes(MemoryPolicy.choose(phone(),true,128),bytes,"图片")}
        MemoryPolicy.requireBytes(MemoryPolicy.choose(phone(),true,256),bytes,"图片")
    }
    @Test fun gifEstimatesDoNotAllocateWholeAnimationPixelBuffers() {
        assertTrue(MemoryPolicy.imageEstimate(mib,4000,3000,"gif") <
            MemoryPolicy.imageEstimate(mib,4000,3000,"png"))
    }
    @Test fun estimatesUseLongArithmeticForLargeHeaders() {
        val estimate=MemoryPolicy.imageEstimate(128*mib,100000,100000,"png")
        assertTrue(estimate > Int.MAX_VALUE.toLong())
    }
    @Test fun imageLimitsFollowTheChosenBudgetWithoutChangingSaesSize() {
        val plan=MemoryPolicy.choose(phone(),true,256)
        val limits=MemoryPolicy.imageLimits(plan)
        assertEquals(100_000_000,limits.maxPixels)
        assertEquals(256*mib,limits.maxPngWorkingBytes)
        assertEquals(32*1024*1024,limits.maxPayloadBytes)
        assertEquals(128*1024*1024,limits.maxContainerBytes)
    }
    @Test fun passwordWorkingRequirementIsSeparateFromTheFileSize() {
        val plan=MemoryPolicy.choose(phone(),true,32)
        reject{MemoryPolicy.requireCredential(plan,false)}
        MemoryPolicy.requireCredential(plan,true)
    }
}
