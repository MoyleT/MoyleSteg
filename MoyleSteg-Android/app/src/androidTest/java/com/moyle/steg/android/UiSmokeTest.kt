package com.moyle.steg.android

import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.lifecycle.ViewModelProvider
import org.junit.After
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test

class UiSmokeTest {
    @get:Rule val ui=createAndroidComposeRule<MainActivity>()

    private fun model():MoyleViewModel=ui.runOnIdle { ViewModelProvider(ui.activity)[MoyleViewModel::class.java] }
    private fun scrollTo(text:String){
        ui.onNode(hasScrollToIndexAction()).performScrollToNode(hasText(text))
    }
    private fun createKeyFromUi():Pair<MoyleViewModel,JobResult>{
        ui.onNodeWithText("工具",useUnmergedTree=true).performClick()
        scrollTo("生成密钥")
        ui.onNodeWithText("生成密钥").performClick()
        scrollTo("生成新密钥")
        ui.onNodeWithText("生成新密钥").performClick()
        val vm=model()
        ui.waitUntil(timeoutMillis=15000){!vm.state.value.busy && (vm.state.value.result!=null || vm.state.value.error!=null)}
        val result=ui.runOnIdle {
            assertNull(vm.state.value.error)
            requireNotNull(vm.state.value.result)
        }
        assertTrue(requireNotNull(result.staged).isFile)
        return vm to result
    }
    @After fun cleanupPrivateResult(){
        val vm=model()
        ui.runOnIdle {vm.clearResult()}
    }
    @Test fun navigationAndThemeSwitch() {
        ui.onNodeWithText("MOYLE").assertExists()
        ui.onNodeWithText("恢复",useUnmergedTree=true).performClick()
        ui.onNodeWithText("只读验证").assertExists().performClick()
        ui.onNodeWithText("设置",useUnmergedTree=true).performClick()
        ui.onNodeWithText("樱桃奶霜 · 浅粉").performScrollTo().performClick()
        ui.onNodeWithText("大字号").assertExists()
        ui.onNodeWithText("恢复",useUnmergedTree=true).performClick()
        scrollTo("只读验证")
        ui.onNodeWithText("只读验证").assertIsSelected()
        ui.onNodeWithText("恢复",useUnmergedTree=true).performClick()
        ui.onNodeWithText("只读验证").assertIsSelected()
        ui.onNodeWithText("隐藏",useUnmergedTree=true).performClick()
        scrollTo("JPG／PNG／GIF 载体")
        ui.onNodeWithText("JPG／PNG／GIF 载体").assertExists()
    }
    @Test fun advancedMemoryControlsRemainReachable(){
        ui.onNodeWithText("设置",useUnmergedTree=true).performClick()
        ui.onNodeWithText("高级资源设置").performScrollTo().performClick()
        ui.onNodeWithText("手动设置").performScrollTo().performClick()
        ui.onNodeWithText("工作内存预算（MiB）").performScrollTo().performTextReplacement("96")
        ui.onNodeWithContentDescription("确认本次手动内存预算").performScrollTo().performClick()
        ui.onNodeWithText("自动评估").performScrollTo().performClick()
        ui.onNodeWithContentDescription("确认本次手动内存预算").assertDoesNotExist()
    }

    @Test fun settingsReturnAndCurrentTabKeepGeneratedKey(){
        val (vm,result)=createKeyFromUi()
        val staged=requireNotNull(result.staged)
        val contents=staged.readBytes()
        ui.onNodeWithText("工具",useUnmergedTree=true).performClick()
        ui.runOnIdle {assertSame(result,vm.state.value.result);assertNull(vm.state.value.discardRequest)}
        ui.onNodeWithText("设置",useUnmergedTree=true).performClick()
        scrollTo("樱桃奶霜 · 浅粉")
        ui.onNodeWithText("樱桃奶霜 · 浅粉").performClick()
        ui.runOnIdle {assertEquals(3,vm.state.value.page);assertSame(result,vm.state.value.result)}
        ui.runOnUiThread {ui.activity.onBackPressedDispatcher.onBackPressed()}
        scrollTo("生成密钥")
        ui.onNodeWithText("生成密钥").assertIsSelected().performClick()
        ui.runOnIdle {
            assertEquals(2,vm.state.value.page)
            assertEquals(Operation.KEYGEN,vm.state.value.operation)
            assertSame(result,vm.state.value.result)
            assertNull(vm.state.value.discardRequest)
        }
        assertArrayEquals(contents,staged.readBytes())
    }

    @Test fun switchingFunctionKeepsWorkUntilDiscardIsConfirmed(){
        val (vm,result)=createKeyFromUi()
        val staged=requireNotNull(result.staged)
        ui.onNodeWithText("隐藏",useUnmergedTree=true).performClick()
        ui.onNodeWithText("有成果尚未保存").assertIsDisplayed()
        ui.runOnIdle {assertSame(result,vm.state.value.result);assertEquals(Operation.KEYGEN,vm.state.value.operation)}
        assertTrue(staged.exists())
        ui.onNodeWithText("保留，返回保存").performClick()
        ui.onNodeWithText("有成果尚未保存").assertDoesNotExist()
        ui.runOnIdle {assertSame(result,vm.state.value.result);assertNull(vm.state.value.discardRequest)}
        ui.onNodeWithText("隐藏",useUnmergedTree=true).performClick()
        ui.onNodeWithText("丢弃并继续").performClick()
        ui.runOnIdle {
            assertEquals(Operation.HIDE,vm.state.value.operation)
            assertEquals(0,vm.state.value.page)
            assertNull(vm.state.value.result)
            assertNull(vm.state.value.discardRequest)
        }
        assertFalse(staged.exists())
        scrollTo("JPG／PNG／GIF 载体")
        ui.onNodeWithText("JPG／PNG／GIF 载体").assertIsDisplayed()
    }

    @Test fun clearResultUsesTheSameExplicitDiscardDialog(){
        val (vm,result)=createKeyFromUi()
        val staged=requireNotNull(result.staged)
        scrollTo("清空结果与私有成品")
        ui.onNodeWithText("清空结果与私有成品").performClick()
        ui.onNodeWithText("有成果尚未保存").assertIsDisplayed()
        ui.onNodeWithText("保留，返回保存").performClick()
        ui.runOnIdle {assertSame(result,vm.state.value.result)}
        assertTrue(staged.exists())
        ui.onNodeWithText("清空结果与私有成品").performClick()
        ui.onNodeWithText("丢弃并继续").performClick()
        ui.runOnIdle {
            assertEquals(Operation.KEYGEN,vm.state.value.operation)
            assertEquals(2,vm.state.value.page)
            assertNull(vm.state.value.result)
        }
        assertFalse(staged.exists())
    }
}
