package com.pindoustudio.app.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

private val CraftDeskScheme = lightColorScheme(
    primary = TerracottaAccent,
    onPrimary = Color(0xFFFFFDF9),
    primaryContainer = TerracottaSoft,
    onPrimaryContainer = TerracottaAccent,
    secondary = SageCompletion,
    onSecondary = Color(0xFFFFFDF9),
    secondaryContainer = SageSoft,
    onSecondaryContainer = SageCompletion,
    background = ParchmentBg,
    onBackground = InkCharcoal,
    surface = CraftSurface,
    onSurface = InkCharcoal,
    surfaceVariant = WarmMutedBg,
    onSurfaceVariant = InkMuted,
    outline = HairlineBorder
)

@Composable
fun Theme(
    content: @Composable () -> Unit
) {
    MaterialTheme(
        colorScheme = CraftDeskScheme,
        typography = Typography,
        content = content
    )
}
