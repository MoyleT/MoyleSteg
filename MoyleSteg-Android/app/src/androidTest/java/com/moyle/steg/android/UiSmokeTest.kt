package com.moyle.steg.android

import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import org.junit.Rule
import org.junit.Test

class UiSmokeTest {
    @get:Rule val ui=createAndroidComposeRule<MainActivity>()
    @Test fun navigationAndThemeSwitch() {
        ui.onNodeWithText("MOYLE").assertExists()
        ui.onNodeWithText("恢复",useUnmergedTree=true).performClick()
        ui.onNodeWithText("只读验证").assertExists().performClick()
        ui.onNodeWithText("设置",useUnmergedTree=true).performClick()
        ui.onNodeWithText("樱桃奶霜 · 浅粉").performScrollTo().performClick()
        ui.onNodeWithText("大字号").assertExists()
        ui.onNodeWithText("隐藏",useUnmergedTree=true).performClick()
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
}
