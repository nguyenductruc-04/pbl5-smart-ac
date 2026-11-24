package vn.pbl5.smartac

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import org.json.JSONObject

val MODE_NAME = mapOf("cool" to "mát", "dry" to "khô", "fan" to "quạt", "auto" to "tự động", "heat" to "sưởi")
val FAN_NAME = mapOf("auto" to "quạt tự động", "low" to "quạt thấp", "mid" to "quạt vừa", "high" to "quạt cao")

@Composable
fun HomeScreen(vm: AppViewModel, openRoom: () -> Unit, openSettings: () -> Unit) {
    val p = LocalPalette.current
    val me = vm.me
    val r = vm.room
    var addRoomInfo by remember { mutableStateOf(false) }
    Page {
        Row(Modifier.fillMaxWidth().padding(top = 12.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("Chào ${me?.displayName ?: ""}", style = MaterialTheme.typography.headlineMedium)
                Hint(if (r == null) "Chưa có phòng nào" else "1 phòng")
            }
            Box(
                Modifier.size(44.dp).clip(CircleShape).background(p.ink).clickable(role = Role.Button, onClick = openSettings),
                contentAlignment = Alignment.Center,
            ) {
                Text((me?.displayName ?: "?").take(1).uppercase(), color = p.bg, fontWeight = FontWeight.SemiBold)
            }
        }
        LinkChip(vm)

        if (r == null) {
            Panel { Hint("Chưa có node nào báo về. Cắm điện node trong phòng rồi đợi khoảng một phút.") }
        } else {
            RoomCard(vm, r, openRoom)
            val s = vm.suggestion
            if (s != null && s.canApply && me?.canControl == true && r.online) {
                Panel(color = p.mintTint, border = null, radius = 22.dp) {
                    Text(s.text, style = MaterialTheme.typography.bodyMedium, color = p.mintText)
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        PrimaryButton(applyLabel(s), { vm.applySuggestion() }, container = p.mintButton, height = 44.dp,
                            enabled = !vm.busy)
                    }
                }
            }
        }
        vm.notice?.let { Hint(it) }

        Box(
            Modifier.fillMaxWidth().height(56.dp).clip(RoundedCornerShape(18.dp))
                .border(1.5.dp, p.line, RoundedCornerShape(18.dp))
                .clickable(role = Role.Button) { addRoomInfo = true },
            contentAlignment = Alignment.Center,
        ) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Icon(Icons.Plus, contentDescription = null, tint = p.ink2, modifier = Modifier.size(18.dp))
                Text("Thêm phòng", style = MaterialTheme.typography.labelLarge, color = p.ink2)
            }
        }
    }
    if (addRoomInfo) {
        AlertDialog(
            onDismissRequest = { addRoomInfo = false },
            title = { Text("Thêm phòng") },
            text = {
                Text("Mỗi phòng cần một node. Nạp firmware cho node mới, đặt ROOM_ID khác (ví dụ room02) và tạo tài khoản MQTT cho node trên Pi. Khi node gửi số đo đầu tiên, phòng tự hiện ở đây.")
            },
            confirmButton = { TextButton(onClick = { addRoomInfo = false }) { Text("Đã hiểu") } },
        )
    }
}

fun applyLabel(s: Suggestion): String {
    val t = s.target ?: return "Áp dụng"
    return when {
        t.optString("power") == "off" -> "Tắt điều hòa"
        t.has("temp") -> "Đặt ${t.optInt("temp")}°"
        else -> "Áp dụng"
    }
}

@Composable
fun LinkChip(vm: AppViewModel) {
    val p = LocalPalette.current
    val (text, color, icon) = when {
        vm.linkError != null -> Triple("Mất kết nối tới Pi, đang thử lại", p.orange, Icons.Wifi)
        vm.link == Link.INTERNET -> Triple("Kết nối qua Internet", p.blueStroke, Icons.Globe)
        vm.link == Link.BACKUP -> Triple("Đang dùng Wi-Fi riêng của Pi", p.mintIcon, Icons.Wifi)
        else -> Triple("Kết nối thẳng qua Wi-Fi nhà", p.mintIcon, Icons.Wifi)
    }
    Row(
        Modifier.clip(RoundedCornerShape(50)).background(p.surface).border(1.dp, p.line, RoundedCornerShape(50))
            .padding(horizontal = 12.dp, vertical = 7.dp),
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Icon(icon, contentDescription = null, tint = color, modifier = Modifier.size(16.dp))
        Text(text, style = MaterialTheme.typography.bodySmall, color = p.ink2)
    }
}

/** Thanh so sanh nhiet do phong voi vung de chiu (16–34 °C). */
@Composable
fun ComfortBar(room: Double?, band: Pair<Double, Double>?) {
    val p = LocalPalette.current
    val lo = 16.0
    val hi = 34.0
    fun frac(v: Double) = ((v - lo) / (hi - lo)).coerceIn(0.0, 1.0).toFloat()
    BoxWithConstraints(Modifier.fillMaxWidth().height(16.dp)) {
        val w = maxWidth
        Box(Modifier.fillMaxWidth().height(8.dp).align(Alignment.Center).clip(RoundedCornerShape(4.dp)).background(p.track))
        if (band != null) {
            Box(
                Modifier.offset(x = w * frac(band.first)).width(w * (frac(band.second) - frac(band.first)))
                    .height(8.dp).align(Alignment.CenterStart).clip(RoundedCornerShape(4.dp)).background(p.band),
            )
        }
        if (room != null) {
            Box(
                Modifier.offset(x = w * frac(room) - 8.dp).size(16.dp).align(Alignment.CenterStart).clip(CircleShape)
                    .background(p.surface).padding(3.dp).clip(CircleShape).background(p.orange),
            )
        }
    }
}

fun comfortWords(room: Double?, band: Pair<Double, Double>?): String? {
    if (room == null || band == null) return null
    val range = "${vnNumber(band.first)}–${vnNumber(band.second)}°"
    return when {
        room > band.second -> "Ấm hơn vùng dễ chịu của bạn ($range)"
        room < band.first -> "Mát hơn vùng dễ chịu của bạn ($range)"
        else -> "Trong vùng dễ chịu của bạn ($range)"
    }
}

@Composable
private fun RoomCard(vm: AppViewModel, r: RoomView, open: () -> Unit) {
    val p = LocalPalette.current
    val on = r.power == "on"
    val canControl = vm.me?.canControl == true && r.online && !vm.busy
    Panel(radius = 28.dp, padding = PaddingValues(start = 20.dp, end = 20.dp, top = 22.dp, bottom = 18.dp), onClick = open) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Text("Phòng ${r.id.removePrefix("room").trimStart('0').ifBlank { r.id }}", style = MaterialTheme.typography.titleMedium,
                modifier = Modifier.weight(1f))
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                Dot(if (!r.online) p.orange else if (r.presence == true) p.mintIcon else p.muted)
                Hint(if (!r.online) "Node mất kết nối" else if (r.presence == true) "Có người" else "Trống")
            }
        }
        Row(verticalAlignment = Alignment.Bottom, horizontalArrangement = Arrangement.spacedBy(18.dp)) {
            Text("${vnNumber(r.temp)}°", style = MaterialTheme.typography.displayMedium)
            Column(Modifier.padding(bottom = 6.dp)) {
                Hint("Độ ẩm")
                Text("${vnNumber(r.hum, 0)}%", style = MaterialTheme.typography.titleLarge)
            }
        }
        val band = vm.suggestion?.band
        val temp = r.temp
        comfortWords(temp, band)?.let { words ->
            ComfortBar(temp, band)
            val warm = temp != null && band != null && temp > band.second
            Hint(words, color = if (warm) p.orangeText else p.ink2)
        }
        Divider()
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Box(Modifier.size(44.dp).clip(RoundedCornerShape(14.dp)).background(if (on) p.blueTint else p.track),
                contentAlignment = Alignment.Center) {
                Icon(Icons.Cool, contentDescription = null, tint = if (on) p.blueStroke else p.ink2, modifier = Modifier.size(22.dp))
            }
            Column(Modifier.weight(1f)) {
                Text(if (r.power == null) "Điều hòa" else if (on) "Điều hòa đang bật" else "Điều hòa đang tắt",
                    style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.SemiBold)
                Hint(if (on) listOfNotNull(MODE_NAME[r.mode]?.replaceFirstChar { it.uppercase() },
                    r.acTemp?.let { "đặt $it°" }, FAN_NAME[r.fan]).joinToString(", ")
                else if (r.uncertain) "Trạng thái có thể đã lệch" else "Chạm để điều khiển")
            }
            Switch(
                checked = on,
                onCheckedChange = { vm.command(JSONObject().put("power", if (it) "on" else "off")) },
                enabled = canControl,
                colors = SwitchDefaults.colors(checkedTrackColor = p.blue, checkedThumbColor = Color.White,
                    uncheckedTrackColor = p.track, uncheckedBorderColor = p.line),
            )
        }
    }
}
