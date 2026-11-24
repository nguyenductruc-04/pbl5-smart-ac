package vn.pbl5.smartac

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
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
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import org.json.JSONObject
import kotlin.math.cos
import kotlin.math.sin

private const val T_MIN = 16
private const val T_MAX = 30

@Composable
fun ControlScreen(vm: AppViewModel, onBack: () -> Unit, openIr: () -> Unit) {
    BackHandler(onBack = onBack)
    val r = vm.room
    var fixOpen by remember { mutableStateOf(false) }
    Page {
        TopBar(
            if (r == null) "Phòng" else "Phòng ${r.id.removePrefix("room").trimStart('0').ifBlank { r.id }}",
            subtitle = when {
                r == null -> null
                !r.online -> "Node mất kết nối"
                r.ageS != null -> "Node trực tuyến, ${r.ageS} giây trước"
                else -> "Node trực tuyến"
            },
            onBack = onBack,
        )
        if (r == null) Hint("Chưa có dữ liệu phòng.") else ControlBody(vm, r) { fixOpen = true }
    }
    if (fixOpen && r != null) {
        val actualOn = r.power != "on"
        AlertDialog(
            onDismissRequest = { fixOpen = false },
            title = { Text("Điều hòa không làm theo?") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    Text("Gửi lại: phát lại đúng lệnh hiện tại, khi tín hiệu bị chắn hoặc điều hòa bỏ lỡ.")
                    Text("Nếu ai đó vừa bấm remote mà app chưa biết, báo trạng thái thật (không phát tín hiệu).")
                    if (vm.me?.role == "admin") {
                        TextButton(onClick = { fixOpen = false; openIr() }) { Text("Nhận diện lại điều hòa") }
                    }
                }
            },
            confirmButton = { TextButton(onClick = { fixOpen = false; vm.resend() }) { Text("Gửi lại lệnh") } },
            dismissButton = {
                TextButton(onClick = { fixOpen = false; vm.syncPower(if (actualOn) "on" else "off") }) {
                    Text(if (actualOn) "Thực tế đang bật" else "Thực tế đang tắt")
                }
            },
        )
    }
}

@Composable
private fun Legend(color: Color, text: String, round: Boolean = false) {
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        Box(Modifier.size(if (round) 8.dp else 14.dp, if (round) 8.dp else 6.dp).clip(RoundedCornerShape(4.dp)).background(color))
        Hint(text)
    }
}

/** Vong chinh nhiet do: cung bac ha = vung de chiu, cung xanh = nhiet do dat, cham cam = phong. */
@Composable
private fun Dial(set: Int, on: Boolean, room: Double?, band: Pair<Double, Double>?) {
    val p = LocalPalette.current
    val label = if (on) "Nhiệt độ đặt $set độ, phòng ${vnNumber(room)} độ" else "Điều hòa đang tắt, phòng ${vnNumber(room)} độ"
    Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
        Box(Modifier.size(280.dp).semantics { contentDescription = label }, contentAlignment = Alignment.Center) {
            Canvas(Modifier.size(280.dp)) {
                val stroke = 18.dp.toPx()
                val pad = 14.dp.toPx()
                val tl = Offset(pad, pad)
                val sz = Size(size.width - 2 * pad, size.height - 2 * pad)
                val radius = sz.width / 2
                val c = Offset(size.width / 2, size.height / 2)
                fun ang(v: Double) = 135f + ((v - T_MIN) / (T_MAX - T_MIN)).coerceIn(0.0, 1.0).toFloat() * 270f
                fun pt(v: Double): Offset {
                    val a = Math.toRadians(ang(v).toDouble())
                    return Offset(c.x + radius * cos(a).toFloat(), c.y + radius * sin(a).toFloat())
                }
                drawArc(p.track, 135f, 270f, false, tl, sz, style = Stroke(stroke, cap = StrokeCap.Round))
                if (band != null) {
                    drawArc(p.band, ang(band.first), ang(band.second) - ang(band.first), false, tl, sz, style = Stroke(stroke))
                }
                if (on) {
                    drawArc(p.blueStroke, 135f, ang(set.toDouble()) - 135f, false, tl, sz,
                        style = Stroke(6.dp.toPx(), cap = StrokeCap.Round))
                    val k = pt(set.toDouble())
                    drawCircle(p.surface, 14.dp.toPx(), k)
                    drawCircle(p.blueStroke, 14.dp.toPx(), k, style = Stroke(5.dp.toPx()))
                }
                if (room != null) {
                    val rp = pt(room)
                    drawCircle(p.bg, 9.dp.toPx(), rp)
                    drawCircle(p.orange, 6.dp.toPx(), rp)
                }
            }
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Hint(if (on) "Nhiệt độ đặt" else "Điều hòa")
                Text(if (on) "$set°" else "Tắt", style = MaterialTheme.typography.displayLarge,
                    color = if (on) p.ink else p.muted)
                Hint("Phòng ${vnNumber(room)}°", color = p.orangeText)
            }
        }
    }
}

@Composable
private fun ModeTile(label: String, icon: ImageVector, selected: Boolean, enabled: Boolean, modifier: Modifier,
                     onClick: () -> Unit) {
    val p = LocalPalette.current
    val shape = RoundedCornerShape(18.dp)
    val fg = if (selected) Color.White else if (enabled) p.ink else p.muted
    Column(
        modifier.height(76.dp).clip(shape).background(if (selected) p.blue else p.surface)
            .border(1.dp, if (selected) p.blue else p.line, shape)
            .clickable(enabled = enabled && !selected, role = Role.RadioButton, onClick = onClick),
        horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center,
    ) {
        Icon(icon, contentDescription = null, tint = fg, modifier = Modifier.size(24.dp))
        Text(label, style = MaterialTheme.typography.labelMedium, color = fg, modifier = Modifier.padding(top = 4.dp))
    }
}

@Composable
private fun Reading(label: String, value: String, modifier: Modifier) {
    val p = LocalPalette.current
    val shape = RoundedCornerShape(16.dp)
    Column(modifier.clip(shape).background(p.surface).border(1.dp, p.line, shape).padding(12.dp)) {
        Hint(label)
        Text(value, style = MaterialTheme.typography.titleLarge, maxLines = 1)
    }
}

@Composable
private fun VoteCard(vm: AppViewModel) {
    val p = LocalPalette.current
    val can = vm.me?.canControl == true && !vm.busy
    Panel(radius = 22.dp) {
        SectionTitle("Bạn thấy thế nào?")
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            VoteButton("Nóng", p.orangeText, p.orangeTint, can, Modifier.weight(1f)) { vm.vote("cooler") }
            VoteButton("Dễ chịu", p.mintIcon, p.mintTint, can, Modifier.weight(1f)) { vm.vote("comfortable") }
            VoteButton("Lạnh", p.blueStroke, p.blueTint, can, Modifier.weight(1f)) { vm.vote("warmer") }
        }
        Hint("Mỗi phiếu giúp gợi ý hợp với bạn hơn.")
    }
}

@Composable
private fun VoteButton(label: String, color: Color, tint: Color, enabled: Boolean, modifier: Modifier, onClick: () -> Unit) {
    val shape = RoundedCornerShape(16.dp)
    Column(
        modifier.height(72.dp).clip(shape).background(tint).clickable(enabled = enabled, role = Role.Button, onClick = onClick),
        horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center,
    ) {
        Icon(Icons.Face, contentDescription = null, tint = color, modifier = Modifier.size(26.dp))
        Text(label, style = MaterialTheme.typography.labelMedium, color = color, modifier = Modifier.padding(top = 4.dp))
    }
}

@Composable
private fun ControlBody(vm: AppViewModel, r: RoomView, openFix: () -> Unit) {
    val p = LocalPalette.current
    val me = vm.me
    Column(verticalArrangement = Arrangement.spacedBy(16.dp)) {
        val on = r.power == "on"
        val canControl = me?.canControl == true && r.online && !vm.busy
        val set = r.acTemp ?: 26
        val band = vm.suggestion?.band

        Dial(set = set, on = on, room = r.temp, band = band)
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.Center, verticalAlignment = Alignment.CenterVertically) {
            Legend(p.band, "Vùng dễ chịu" + (band?.let { " ${vnNumber(it.first)}–${vnNumber(it.second)}°" } ?: ""))
            Box(Modifier.size(16.dp))
            Legend(p.orange, "Phòng", round = true)
        }

        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(16.dp)) {
            RoundIconButton(Icons.Minus, "Giảm 1 độ", { vm.command(JSONObject().put("temp", set - 1)) }, 64.dp,
                enabled = canControl && on && set > T_MIN)
            Button(
                onClick = { vm.command(JSONObject().put("power", if (on) "off" else "on")) },
                enabled = canControl, modifier = Modifier.weight(1f).height(64.dp), shape = RoundedCornerShape(32.dp),
                colors = ButtonDefaults.buttonColors(
                    containerColor = if (on) p.ink else p.blue, contentColor = if (on) p.bg else Color.White),
            ) {
                Icon(Icons.Power, contentDescription = null, modifier = Modifier.size(22.dp))
                Box(Modifier.size(10.dp))
                Text(if (on) "Tắt điều hòa" else "Bật điều hòa", style = MaterialTheme.typography.labelLarge, fontWeight = FontWeight.SemiBold)
            }
            RoundIconButton(Icons.Plus, "Tăng 1 độ", { vm.command(JSONObject().put("temp", set + 1)) }, 64.dp,
                enabled = canControl && on && set < T_MAX)
        }

        if (me?.canControl == false) Hint("Bạn đang dùng tài khoản khách nên chỉ xem được.")
        if (r.uncertain) Hint("Trạng thái điều hòa có thể đã lệch với thực tế. Gửi một lệnh, hoặc mở \"Điều hòa không làm theo?\".", color = p.orangeText)

        SectionTitle("Chế độ")
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            listOf(Triple("cool", "Mát", Icons.Cool), Triple("dry", "Khô", Icons.Dry), Triple("fan", "Quạt", Icons.Fan),
                Triple("auto", "Tự động", Icons.Auto)).forEach { (id, label, icon) ->
                ModeTile(label, icon, selected = on && r.mode == id, enabled = canControl && on, modifier = Modifier.weight(1f)) {
                    vm.command(JSONObject().put("mode", id))
                }
            }
        }
        SectionTitle("Quạt")
        Segmented(listOf("auto" to "Tự động", "low" to "Thấp", "mid" to "Vừa", "high" to "Cao"),
            if (on) r.fan else null, enabled = canControl && on) { vm.command(JSONObject().put("fan", it)) }

        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Reading("Nhiệt độ phòng", "${vnNumber(r.temp)}°", Modifier.weight(1f))
            Reading("Độ ẩm", "${vnNumber(r.hum, 0)}%", Modifier.weight(1f))
            Reading("Trong phòng", when (r.presence) { true -> "Có người"; false -> "Trống"; null -> "–" }, Modifier.weight(1f))
        }

        vm.suggestion?.let { s ->
            Panel(color = p.mintTint, border = null, radius = 22.dp) {
                Text(s.text, style = MaterialTheme.typography.bodyMedium, color = p.mintText)
                Text(s.why, style = MaterialTheme.typography.bodySmall, color = p.mintText.copy(alpha = 0.8f))
                if (s.canApply && canControl) {
                    PrimaryButton(applyLabel(s), { vm.applySuggestion() }, container = p.mintButton, height = 44.dp)
                }
            }
        }

        VoteCard(vm)
        vm.notice?.let { Hint(it) }

        Panel(radius = 18.dp, onClick = openFix) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("Điều hòa không làm theo?", style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
                Icon(Icons.Chevron, contentDescription = null, tint = p.muted, modifier = Modifier.size(18.dp))
            }
        }
    }
}
