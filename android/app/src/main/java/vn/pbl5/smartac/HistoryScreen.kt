package vn.pbl5.smartac

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

@Composable
fun HistoryScreen(vm: AppViewModel) {
    val p = LocalPalette.current
    LaunchedEffect(Unit) { vm.loadActivity() }
    val s = vm.series
    Page {
        Row(Modifier.fillMaxWidth().padding(top = 12.dp), verticalAlignment = Alignment.CenterVertically) {
            Text("Lịch sử", style = MaterialTheme.typography.headlineMedium, modifier = Modifier.weight(1f))
            vm.room?.let { Hint("Phòng ${it.id.removePrefix("room").trimStart('0').ifBlank { it.id }}") }
        }
        Segmented(listOf("6" to "6 giờ", "24" to "24 giờ", "168" to "7 ngày"), (s?.hours ?: 24).toString()) {
            vm.loadSeries(it.toInt())
        }
        Panel {
            Row(verticalAlignment = Alignment.Bottom) {
                SectionTitle("Nhiệt độ phòng")
                Box(Modifier.weight(1f))
                if (s != null && s.temp.isNotEmpty()) Hint("${vnNumber(s.temp.min())}–${vnNumber(s.temp.max())}°")
            }
            if (s == null || s.temp.size < 2) Hint("Chưa đủ số đo để vẽ.") else TempChart(s, vm.suggestion?.band)
            Row(horizontalArrangement = Arrangement.spacedBy(16.dp), verticalAlignment = Alignment.CenterVertically) {
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    Box(Modifier.size(14.dp, 8.dp).background(p.mintTint))
                    Hint("Vùng dễ chịu của bạn")
                }
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    Dot(p.orange)
                    Hint("Bây giờ")
                }
            }
        }
        if (s != null && s.hum.isNotEmpty()) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Stat("Độ ẩm trung bình", "${vnNumber(s.hum.average(), 0)}%", Modifier.weight(1f))
                Stat("Cao nhất", "${vnNumber(s.temp.max())}°", Modifier.weight(1f))
            }
        }
        SectionTitle("Hoạt động")
        if (vm.activity.isEmpty()) Hint("Chưa có hoạt động nào.")
        val fmt = SimpleDateFormat("HH:mm", Locale.getDefault())
        val day = SimpleDateFormat("dd/MM", Locale.getDefault())
        val today = day.format(Date())
        vm.activity.forEach { a ->
            val d = Date((a.ts * 1000).toLong())
            val (dot, tint) = when (a.kind) {
                "warn" -> p.orange to p.orangeTint
                "info" -> p.ink2 to p.track
                else -> p.blueStroke to p.blueTint
            }
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp), verticalAlignment = Alignment.Top) {
                Column(Modifier.width(48.dp)) {
                    Hint(fmt.format(d))
                    if (day.format(d) != today) Hint(day.format(d))
                }
                Box(Modifier.size(28.dp).clip(CircleShape).background(tint), contentAlignment = Alignment.Center) { Dot(dot) }
                Column(Modifier.weight(1f)) {
                    Text(a.title, style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.Medium)
                    Hint(a.detail)
                }
            }
        }
    }
}

@Composable
private fun Stat(label: String, value: String, modifier: Modifier) {
    Panel(modifier, radius = 18.dp) {
        Hint(label)
        Text(value, style = MaterialTheme.typography.titleLarge)
    }
}

@Composable
private fun TempChart(s: Series, band: Pair<Double, Double>?) {
    val p = LocalPalette.current
    val lo = minOf(s.temp.min(), band?.first ?: 99.0) - 0.5
    val hi = maxOf(s.temp.max(), band?.second ?: -99.0) + 0.5
    val fmt = SimpleDateFormat(if (s.hours > 24) "dd/MM" else "HH:mm", Locale.getDefault())
    Canvas(Modifier.fillMaxWidth().height(170.dp).semantics {
        contentDescription = "Biểu đồ nhiệt độ phòng ${s.hours} giờ qua, từ ${vnNumber(s.temp.min())} đến ${vnNumber(s.temp.max())} độ"
    }) {
        val w = size.width
        val h = size.height
        val t0 = s.ts.first()
        val span = (s.ts.last() - t0).takeIf { it > 0 } ?: 1.0
        fun x(t: Double) = ((t - t0) / span * (w - 12f) + 6f).toFloat()
        fun y(v: Double) = ((hi - v) / (hi - lo) * h).toFloat()
        if (band != null) {
            drawRect(p.mintTint, Offset(0f, y(band.second)), Size(w, y(band.first) - y(band.second)))
        }
        listOf(0f, h / 2, h).forEach { yy -> drawLine(p.line2, Offset(0f, yy), Offset(w, yy), 1f) }
        val path = Path()
        s.ts.indices.forEach { i ->
            if (i == 0) path.moveTo(x(s.ts[i]), y(s.temp[i])) else path.lineTo(x(s.ts[i]), y(s.temp[i]))
        }
        drawPath(path, p.ink, style = Stroke(2.2.dp.toPx(), cap = StrokeCap.Round, join = StrokeJoin.Round))
        val last = Offset(x(s.ts.last()), y(s.temp.last()))
        drawCircle(p.surface, 7.dp.toPx(), last)
        drawCircle(p.orange, 5.dp.toPx(), last)
    }
    Row(Modifier.fillMaxWidth()) {
        Hint(fmt.format(Date((s.ts.first() * 1000).toLong())))
        Box(Modifier.weight(1f))
        Hint("Bây giờ")
    }
}
