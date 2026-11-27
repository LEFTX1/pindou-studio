package com.pindoustudio.app

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Surface
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Modifier
import androidx.lifecycle.viewmodel.compose.viewModel
import com.pindoustudio.app.ui.PindouStudioScreen
import com.pindoustudio.app.ui.PindouViewModel
import com.pindoustudio.app.ui.theme.ParchmentBg
import com.pindoustudio.app.ui.theme.Theme

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        val testManifestUrl = intent?.getStringExtra("test_update_manifest_url")
        setContent {
            Theme {
                Surface(modifier = Modifier.fillMaxSize(), color = ParchmentBg) {
                    val vm: PindouViewModel = viewModel()
                    LaunchedEffect(testManifestUrl) {
                        if (!testManifestUrl.isNullOrBlank()) {
                            vm.checkForUpdate(manual = true, overrideManifestUrl = testManifestUrl)
                        }
                    }
                    PindouStudioScreen(vm)
                }
            }
        }
    }
}
