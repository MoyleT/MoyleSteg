package com.moyle.steg.android

import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

@Composable
fun MoyleTheme(id: String,large: Boolean,content: @Composable ()->Unit) {
    val scheme=when(id){
        "blossom"->lightColorScheme(
            primary=Color(0xFFB82E66),onPrimary=Color.White,primaryContainer=Color(0xFFFBE3ED),onPrimaryContainer=Color(0xFF432B39),
            background=Color(0xFFFFF4F7),onBackground=Color(0xFF432B39),surface=Color(0xFFFFFCF8),onSurface=Color(0xFF432B39),
            surfaceVariant=Color(0xFFFFE9EF),onSurfaceVariant=Color(0xFF795665),outline=Color(0xFFAC718B),error=Color(0xFFAD334C))
        "terminal"->darkColorScheme(
            primary=Color(0xFF79E5A5),onPrimary=Color(0xFF0A2818),primaryContainer=Color(0xFF173A26),onPrimaryContainer=Color(0xFFE4F6E9),
            background=Color(0xFF080F0C),onBackground=Color(0xFFE4F6E9),surface=Color(0xFF101E17),onSurface=Color(0xFFE4F6E9),
            surfaceVariant=Color(0xFF172B20),onSurfaceVariant=Color(0xFFA0BDAB),outline=Color(0xFF597D68),error=Color(0xFFFFA7A7))
        else->darkColorScheme(
            primary=Color(0xFFB9A6FF),onPrimary=Color(0xFF201637),primaryContainer=Color(0xFF2A2549),onPrimaryContainer=Color(0xFFEEF0FF),
            background=Color(0xFF0D1020),onBackground=Color(0xFFEEF0FF),surface=Color(0xFF171C33),onSurface=Color(0xFFEEF0FF),
            surfaceVariant=Color(0xFF1E2440),onSurfaceVariant=Color(0xFFACB4D2),outline=Color(0xFF65749E),error=Color(0xFFFFABA9))
    }
    val base=Typography();val add=if(large)2 else 0
    val type=Typography(
        headlineLarge=base.headlineLarge.copy(fontSize=(28+add).sp,fontWeight=FontWeight.Bold),
        headlineMedium=base.headlineMedium.copy(fontSize=(24+add).sp,fontWeight=FontWeight.Bold),
        titleLarge=base.titleLarge.copy(fontSize=(20+add).sp,fontWeight=FontWeight.Bold),
        titleMedium=base.titleMedium.copy(fontSize=(16+add).sp,fontWeight=FontWeight.SemiBold),
        bodyLarge=base.bodyLarge.copy(fontSize=(16+add).sp),
        bodyMedium=base.bodyMedium.copy(fontSize=(14+add).sp,lineHeight=(21+add).sp),
        bodySmall=base.bodySmall.copy(fontSize=(12+add).sp,lineHeight=(18+add).sp),
        labelLarge=base.labelLarge.copy(fontSize=(14+add).sp),
        labelMedium=base.labelMedium.copy(fontSize=(12+add).sp),
        labelSmall=base.labelSmall.copy(fontSize=(11+add).sp)
    )
    MaterialTheme(colorScheme=scheme,typography=type,content=content)
}
