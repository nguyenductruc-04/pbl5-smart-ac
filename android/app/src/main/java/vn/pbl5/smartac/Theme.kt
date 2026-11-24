package vn.pbl5.smartac

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.LocalContentColor
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

/**
 * Bang mau "khong khi trong phong" (docs: canvas thiet ke). Moi mau nhan mang mot nghia:
 * xanh = dieu hoa, bac ha = vung de chiu cua nguoi dung, cam = phong dang nong.
 */
data class Palette(
    val bg: Color,
    val surface: Color,
    val ink: Color,
    val ink2: Color,
    val line: Color,
    val line2: Color,
    val track: Color,
    val segSelected: Color,
    val blue: Color,          // nen nut, chu trang
    val blueStroke: Color,    // net ve, bieu tuong, chu xanh tren nen
    val blueTint: Color,
    val band: Color,          // vung de chiu
    val mintTint: Color,
    val mintText: Color,
    val mintButton: Color,
    val mintIcon: Color,
    val orange: Color,
    val orangeText: Color,
    val orangeTint: Color,
    val muted: Color,
    val isDark: Boolean,
)

val LightPalette = Palette(
    bg = Color(0xFFF2F5F6), surface = Color(0xFFFFFFFF), ink = Color(0xFF0F2A36), ink2 = Color(0xFF4A6470),
    line = Color(0xFFDCE4E7), line2 = Color(0xFFEEF2F4), track = Color(0xFFE4EBEE), segSelected = Color(0xFFFFFFFF),
    blue = Color(0xFF1667C9), blueStroke = Color(0xFF1667C9), blueTint = Color(0xFFE6F0FB),
    band = Color(0xFF9ED9D0), mintTint = Color(0xFFE3F4F1), mintText = Color(0xFF0D3B36),
    mintButton = Color(0xFF0E6B62), mintIcon = Color(0xFF138A7E),
    orange = Color(0xFFC2610F), orangeText = Color(0xFF8A4A0B), orangeTint = Color(0xFFFCEFE3),
    muted = Color(0xFF7A8F98), isDark = false,
)

val DarkPalette = Palette(
    bg = Color(0xFF0D1519), surface = Color(0xFF15212A), ink = Color(0xFFE4EDF0), ink2 = Color(0xFF9DB2BB),
    line = Color(0xFF263741), line2 = Color(0xFF1F2E37), track = Color(0xFF22323B), segSelected = Color(0xFF2A3B45),
    blue = Color(0xFF1667C9), blueStroke = Color(0xFF5BA3F5), blueTint = Color(0xFF16304D),
    band = Color(0xFF2E8C80), mintTint = Color(0xFF10302C), mintText = Color(0xFFBFEAE3),
    mintButton = Color(0xFF0E6B62), mintIcon = Color(0xFF4CC2B3),
    orange = Color(0xFFF08A3C), orangeText = Color(0xFFF2AE6B), orangeTint = Color(0xFF3A2614),
    muted = Color(0xFF6F8791), isDark = true,
)

val LocalPalette = staticCompositionLocalOf { LightPalette }

/** Be Vietnam Pro: phong chu thiet ke cho tieng Viet (SIL OFL 1.1, android/FONT-LICENSE-OFL.txt). */
val VietnamPro = FontFamily(
    Font(R.font.be_vietnam_pro_light, FontWeight.Light),
    Font(R.font.be_vietnam_pro_regular, FontWeight.Normal),
    Font(R.font.be_vietnam_pro_medium, FontWeight.Medium),
    Font(R.font.be_vietnam_pro_semibold, FontWeight.SemiBold),
)

private fun t(size: Int, weight: FontWeight = FontWeight.Normal, line: Int = (size * 1.4).toInt()) =
    TextStyle(fontFamily = VietnamPro, fontSize = size.sp, fontWeight = weight, lineHeight = line.sp)

private val AppTypography = Typography(
    displayLarge = t(76, FontWeight.Light, 80),
    displayMedium = t(64, FontWeight.Light, 66),
    headlineMedium = t(26, FontWeight.SemiBold, 32),
    headlineSmall = t(22, FontWeight.SemiBold, 28),
    titleLarge = t(20, FontWeight.Medium),
    titleMedium = t(17, FontWeight.SemiBold),
    titleSmall = t(15, FontWeight.SemiBold),
    bodyLarge = t(16),
    bodyMedium = t(15),
    bodySmall = t(13),
    labelLarge = t(15, FontWeight.Medium),
    labelMedium = t(13, FontWeight.Medium),
    labelSmall = t(12, FontWeight.Medium),
)

@Composable
fun AppTheme(content: @Composable () -> Unit) {
    val p = if (isSystemInDarkTheme()) DarkPalette else LightPalette
    val scheme = if (p.isDark) {
        darkColorScheme(
            primary = p.blue, onPrimary = Color.White, background = p.bg, onBackground = p.ink,
            surface = p.surface, onSurface = p.ink, surfaceVariant = p.track, onSurfaceVariant = p.ink2,
            outline = p.line, error = p.orange, secondaryContainer = p.blueTint, onSecondaryContainer = p.ink,
        )
    } else {
        lightColorScheme(
            primary = p.blue, onPrimary = Color.White, background = p.bg, onBackground = p.ink,
            surface = p.surface, onSurface = p.ink, surfaceVariant = p.track, onSurfaceVariant = p.ink2,
            outline = p.line, error = p.orange, secondaryContainer = p.blueTint, onSecondaryContainer = p.ink,
        )
    }
    CompositionLocalProvider(LocalPalette provides p) {
        MaterialTheme(colorScheme = scheme, typography = AppTypography) {
            // Khong co Surface o goc nen phai dat mau chu mac dinh, neu khong chu se den tren nen toi
            CompositionLocalProvider(LocalContentColor provides p.ink, content = content)
        }
    }
}
