package vn.pbl5.smartac

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.graphics.vector.addPathNodes
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

// ------------------------------------------------------------------ bieu tuong (net ve 24x24, giong thiet ke)
private fun strokeIcon(name: String, vararg paths: String, width: Float = 2f): ImageVector {
    val b = ImageVector.Builder(name, 24.dp, 24.dp, 24f, 24f)
    paths.forEach { d ->
        b.addPath(
            pathData = addPathNodes(d),
            fill = null,
            stroke = SolidColor(Color.Black),
            strokeLineWidth = width,
            strokeLineCap = StrokeCap.Round,
            strokeLineJoin = StrokeJoin.Round,
        )
    }
    return b.build()
}

object Icons {
    val Home = strokeIcon("home", "M4 11l8-6 8 6v8a1 1 0 0 1-1 1h-4v-6H9v6H5a1 1 0 0 1-1-1z")
    val History = strokeIcon("history", "M4 19h16", "M5 15l4-5 4 3 6-7")
    val Settings = strokeIcon("settings", "M4 7h10M18 7h2M4 17h4M12 17h8",
        "M16 5a2 2 0 1 1 0 4a2 2 0 1 1 0-4", "M10 15a2 2 0 1 1 0 4a2 2 0 1 1 0-4")
    val Back = strokeIcon("back", "M15 5l-7 7 7 7")
    val Chevron = strokeIcon("chevron", "M9 5l7 7-7 7")
    val Plus = strokeIcon("plus", "M5 12h14M12 5v14", width = 2.2f)
    val Minus = strokeIcon("minus", "M5 12h14", width = 2.2f)
    val Power = strokeIcon("power", "M12 3v8", "M6.3 6.8a8 8 0 1 0 11.4 0", width = 2.2f)
    val Wifi = strokeIcon("wifi", "M5 12.5a10 10 0 0 1 14 0", "M8.5 16a5 5 0 0 1 7 0", "M12 19.5h.01")
    val Globe = strokeIcon("globe", "M12 3a9 9 0 1 1 0 18a9 9 0 1 1 0-18", "M3 12h18",
        "M12 3c2.5 2.7 3.8 5.7 3.8 9s-1.3 6.3-3.8 9c-2.5-2.7-3.8-5.7-3.8-9S9.5 5.7 12 3")
    val Cool = strokeIcon("cool", "M12 3v18M4.5 7.5l15 9M19.5 7.5l-15 9", width = 1.8f)
    val Dry = strokeIcon("dry", "M12 3.5c3.5 4.6 6 7.8 6 10.7a6 6 0 0 1-12 0c0-2.9 2.5-6.1 6-10.7z", width = 1.8f)
    val Fan = strokeIcon("fan", "M12 12c0-4 1-7 4-7s3 4 0 5.5M12 12c4 0 7 1 7 4s-4 3-5.5 0" +
        "M12 12c0 4-1 7-4 7s-3-4 0-5.5M12 12c-4 0-7-1-7-4s4-3 5.5 0", width = 1.8f)
    val Auto = strokeIcon("auto", "M6 19l6-14 6 14M8.5 13.5h7", width = 1.8f)
    val People = strokeIcon("people", "M16 19v-1a4 4 0 0 0-4-4H7a4 4 0 0 0-4 4v1",
        "M9.5 4a3 3 0 1 1 0 6a3 3 0 1 1 0-6", "M21 19v-1a4 4 0 0 0-3-3.9M15.5 4.1a3 3 0 0 1 0 5.8", width = 1.9f)
    val Ac = strokeIcon("ac", "M3 7h18v6H3z", "M6 13v1M10 13v3M14 13v3M18 13v1M6 10h4", width = 1.9f)
    val Remote = strokeIcon("remote", "M10 6h4a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-4a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2z",
        "M10.5 10h3M10.5 13h3M10.5 16h3", "M9 3.2a5 5 0 0 1 6 0", width = 1.6f)
    val Face = strokeIcon("face", "M12 3a9 9 0 1 1 0 18a9 9 0 1 1 0-18", "M9 10h.01M15 10h.01", width = 1.7f)
}

// ------------------------------------------------------------------ khoi dung chung
/** Khung trang: nen, le, cuon doc. */
@Composable
fun Hint(text: String, color: Color = LocalPalette.current.ink2, center: Boolean = false) {
    Text(text, style = MaterialTheme.typography.bodySmall, color = color,
        textAlign = if (center) TextAlign.Center else null)
}

@Composable
fun SectionTitle(text: String) {
    Text(text, style = MaterialTheme.typography.titleSmall, color = LocalPalette.current.ink)
}

/** The phang: nen trang (toi: xam xanh), vien manh, khong do bong. */
@Composable
fun Panel(
    modifier: Modifier = Modifier,
    radius: Dp = 24.dp,
    color: Color = LocalPalette.current.surface,
    border: Color? = LocalPalette.current.line,
    padding: PaddingValues = PaddingValues(18.dp),
    onClick: (() -> Unit)? = null,
    content: @Composable ColumnScope.() -> Unit,
) {
    val shape = RoundedCornerShape(radius)
    var m = modifier.fillMaxWidth().clip(shape).background(color)
    if (border != null) m = m.border(1.dp, border, shape)
    if (onClick != null) m = m.clickable(role = Role.Button, onClick = onClick)
    Column(m.padding(padding), verticalArrangement = Arrangement.spacedBy(12.dp), content = content)
}

@Composable
fun PrimaryButton(text: String, onClick: () -> Unit, modifier: Modifier = Modifier, enabled: Boolean = true,
                  container: Color = LocalPalette.current.blue, content: Color = Color.White, height: Dp = 52.dp) {
    Button(
        onClick = onClick, enabled = enabled, modifier = modifier.heightIn(min = height),
        shape = RoundedCornerShape(50),
        colors = ButtonDefaults.buttonColors(containerColor = container, contentColor = content),
    ) { Text(text, style = MaterialTheme.typography.labelLarge, fontWeight = FontWeight.SemiBold) }
}

@Composable
fun SecondaryButton(text: String, onClick: () -> Unit, modifier: Modifier = Modifier, enabled: Boolean = true,
                    height: Dp = 52.dp) {
    val p = LocalPalette.current
    OutlinedButton(
        onClick = onClick, enabled = enabled, modifier = modifier.heightIn(min = height),
        shape = RoundedCornerShape(50), border = BorderStroke(1.dp, p.line),
        colors = ButtonDefaults.outlinedButtonColors(containerColor = p.surface, contentColor = p.ink),
    ) { Text(text, style = MaterialTheme.typography.labelLarge) }
}

@Composable
fun QuietButton(text: String, onClick: () -> Unit, color: Color = LocalPalette.current.blueStroke) {
    TextButton(onClick = onClick, modifier = Modifier.heightIn(min = 44.dp)) {
        Text(text, style = MaterialTheme.typography.labelLarge, color = color)
    }
}

/** Nut tron vien manh chua bieu tuong (quay lai, +, -). */
@Composable
fun RoundIconButton(icon: ImageVector, label: String, onClick: () -> Unit, size: Dp = 44.dp,
                    enabled: Boolean = true) {
    val p = LocalPalette.current
    IconButton(
        onClick = onClick, enabled = enabled,
        modifier = Modifier.size(size).clip(CircleShape).background(p.surface).border(1.dp, p.line, CircleShape),
    ) { Icon(icon, contentDescription = label, tint = if (enabled) p.ink else p.muted, modifier = Modifier.size(22.dp)) }
}

@Composable
fun TopBar(title: String, subtitle: String? = null, onBack: (() -> Unit)? = null) {
    Row(Modifier.fillMaxWidth().padding(top = 8.dp), verticalAlignment = Alignment.CenterVertically) {
        if (onBack != null) RoundIconButton(Icons.Back, "Quay lại", onBack) else Box(Modifier.size(44.dp))
        Column(Modifier.weight(1f), horizontalAlignment = Alignment.CenterHorizontally) {
            Text(title, style = MaterialTheme.typography.titleMedium, maxLines = 1, overflow = TextOverflow.Ellipsis)
            if (subtitle != null) Hint(subtitle)
        }
        Box(Modifier.size(44.dp))
    }
}

/** Hang nut chon mot kieu "segmented": nen xam, muc dang chon noi len. */
@Composable
fun Segmented(options: List<Pair<String, String>>, selected: String?, enabled: Boolean = true,
              onPick: (String) -> Unit) {
    val p = LocalPalette.current
    Row(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(p.track).padding(4.dp),
        horizontalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        options.forEach { (value, label) ->
            val sel = value == selected
            Box(
                Modifier.weight(1f).height(44.dp).clip(RoundedCornerShape(12.dp))
                    .background(if (sel) p.segSelected else Color.Transparent)
                    .clickable(enabled = enabled && !sel, role = Role.RadioButton) { onPick(value) },
                contentAlignment = Alignment.Center,
            ) {
                Text(label, style = MaterialTheme.typography.labelLarge,
                    fontWeight = if (sel) FontWeight.SemiBold else FontWeight.Medium,
                    color = if (!enabled) p.muted else if (sel) p.ink else p.ink2, maxLines = 1)
            }
        }
    }
}

/** Dong trong danh sach cai dat: bieu tuong, tieu de, gia tri, mui ten. */
@Composable
fun SettingRow(icon: ImageVector, tint: Color, iconColor: Color, title: String, value: String,
               badge: String? = null, onClick: (() -> Unit)?) {
    val p = LocalPalette.current
    var m = Modifier.fillMaxWidth().heightIn(min = 68.dp)
    if (onClick != null) m = m.clickable(role = Role.Button, onClick = onClick)
    Row(m.padding(horizontal = 16.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        Box(Modifier.size(40.dp).clip(RoundedCornerShape(12.dp)).background(tint), contentAlignment = Alignment.Center) {
            Icon(icon, contentDescription = null, tint = iconColor, modifier = Modifier.size(20.dp))
        }
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.Medium)
            Hint(value)
        }
        if (badge != null) {
            Box(Modifier.heightIn(min = 22.dp).clip(RoundedCornerShape(11.dp)).background(p.orange)
                .padding(horizontal = 7.dp, vertical = 2.dp), contentAlignment = Alignment.Center) {
                Text(badge, style = MaterialTheme.typography.labelSmall, color = if (p.isDark) p.bg else Color.White)
            }
        }
        if (onClick != null) Icon(Icons.Chevron, contentDescription = null, tint = p.muted, modifier = Modifier.size(16.dp))
    }
}

@Composable
fun Divider() {
    Box(Modifier.fillMaxWidth().height(1.dp).background(LocalPalette.current.line2))
}

/** Cham tron nho bao trang thai. */
@Composable
fun Dot(color: Color, size: Dp = 8.dp) {
    Box(Modifier.size(size).clip(CircleShape).background(color))
}

fun vnNumber(v: Double?, digits: Int = 1): String =
    if (v == null) "–" else "%.${digits}f".format(v).replace('.', ',')
