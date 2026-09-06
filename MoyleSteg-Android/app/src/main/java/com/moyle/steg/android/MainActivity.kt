package com.moyle.steg.android

import android.os.Bundle
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels

class MainActivity: ComponentActivity() {
    private val model: MoyleViewModel by viewModels()
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
        setContent { MoyleApp(model) }
    }
    override fun onStop(){
        if(!isChangingConfigurations)model.clearPasswords()
        super.onStop()
    }
}
