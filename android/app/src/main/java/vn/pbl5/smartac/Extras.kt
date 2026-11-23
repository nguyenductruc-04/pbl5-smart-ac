package vn.pbl5.smartac

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/** Hang nut chon mot (che do, quat, khoang thoi gian, che do mang). */
@Composable
internal fun Choice(
    options: List<Pair<String, String>>,
    selected: String?,
    enabled: Boolean,
    onPick: (String) -> Unit,
) {
    Row(horizontalArrangement = Arrangement.spacedBy(6.dp), modifier = Modifier.fillMaxWidth()) {
        options.forEach { (value, label) ->
            val pad = PaddingValues(horizontal = 4.dp, vertical = 8.dp)
            val content: @Composable () -> Unit = {
                Text(label, fontSize = 13.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
            if (value == selected) {
                Button(onClick = {}, enabled = enabled, contentPadding = pad, modifier = Modifier.weight(1f)) { content() }
            } else {
                OutlinedButton(onClick = { onPick(value) }, enabled = enabled, contentPadding = pad, modifier = Modifier.weight(1f)) {
                    content()
                }
            }
        }
    }
}

/** "Dieu hoa khong lam theo?" (ADR 0005): gui lai, hoac bao trang thai that ma khong phat IR. */
@Composable
internal fun FixRow(vm: AppViewModel, r: RoomView) {
    var open by remember { mutableStateOf(false) }
    TextButton(onClick = { open = !open }, contentPadding = PaddingValues(0.dp)) {
        Text(if (open) "Điều hòa không làm theo? (thu gọn)" else "Điều hòa không làm theo?")
    }
    if (!open) return
    Hint("Gửi lại: phát lại đúng lệnh hiện tại. Dùng khi tín hiệu bị chắn hoặc điều hòa bỏ lỡ.")
    OutlinedButton(onClick = { vm.resend() }, enabled = !vm.busy && r.online, modifier = Modifier.fillMaxWidth()) {
        Text("Gửi lại lệnh")
    }
    Hint("Nếu ai đó vừa bật/tắt bằng remote mà app chưa biết, báo trạng thái thật (không phát tín hiệu):")
    val actualOn = r.power != "on"
    OutlinedButton(onClick = { vm.syncPower(if (actualOn) "on" else "off") }, enabled = !vm.busy, modifier = Modifier.fillMaxWidth()) {
        Text(if (actualOn) "Thực tế điều hòa đang bật" else "Thực tế điều hòa đang tắt")
    }
}

@Composable
internal fun SuggestionCard(vm: AppViewModel, s: Suggestion, canControl: Boolean) {
    Card(
        Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.secondaryContainer),
    ) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("Gợi ý cho bạn", fontWeight = FontWeight.SemiBold)
            Text(s.text, style = MaterialTheme.typography.bodyLarge)
            if (s.canApply && canControl) {
                Button(onClick = { vm.applySuggestion() }) { Text("Áp dụng") }
            }
            Hint(s.why)
        }
    }
}

@Composable
internal fun ChartCard(vm: AppViewModel) {
    val s = vm.series
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("Diễn biến nhiệt độ", fontWeight = FontWeight.SemiBold)
            Choice(listOf("6" to "6 giờ", "24" to "24 giờ", "168" to "7 ngày"), (s?.hours ?: 24).toString(), true) {
                vm.loadSeries(it.toInt())
            }
            if (s == null || s.temp.size < 2) Hint("Chưa đủ số đo để vẽ.") else TempChart(s)
        }
    }
}

@Composable
private fun TempChart(s: Series) {
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        run {
            val lo = s.temp.min()
            val hi = s.temp.max()
            val line = MaterialTheme.colorScheme.primary
            val grid = MaterialTheme.colorScheme.outlineVariant
            Row {
                Text("%.1f °C".format(hi), style = MaterialTheme.typography.labelSmall)
            }
            Canvas(Modifier.fillMaxWidth().height(140.dp)) {
                val span = (hi - lo).takeIf { it > 0.2 } ?: 0.2
                val t0 = s.ts.first()
                val tSpan = (s.ts.last() - t0).takeIf { it > 0 } ?: 1.0
                drawLine(grid, Offset(0f, 0f), Offset(size.width, 0f))
                drawLine(grid, Offset(0f, size.height), Offset(size.width, size.height))
                val path = Path()
                s.ts.indices.forEach { i ->
                    val x = ((s.ts[i] - t0) / tSpan * size.width).toFloat()
                    val y = ((1 - (s.temp[i] - lo) / span) * size.height).toFloat()
                    if (i == 0) path.moveTo(x, y) else path.lineTo(x, y)
                }
                drawPath(path, line, style = Stroke(width = 2.dp.toPx()))
            }
            Text("%.1f °C".format(lo), style = MaterialTheme.typography.labelSmall)
            val fmt = SimpleDateFormat(if (s.hours > 24) "dd/MM HH:mm" else "HH:mm", Locale.getDefault())
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text(fmt.format(Date((s.ts.first() * 1000).toLong())), style = MaterialTheme.typography.labelSmall)
                Text(fmt.format(Date((s.ts.last() * 1000).toLong())), style = MaterialTheme.typography.labelSmall)
            }
            Hint("Độ ẩm gần nhất: %.0f %%".format(s.hum.last()))
        }
    }
}

/** Che do mang cua Pi (chi quan tri vien). */
@Composable
internal fun NetworkCard(vm: AppViewModel) {
    val n = vm.net ?: return
    var ask by remember { mutableStateOf<String?>(null) }
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("Mạng của Pi", fontWeight = FontWeight.SemiBold)
            Hint(
                when {
                    !n.running -> "Dịch vụ pbl5-netwatch không chạy nên đổi chế độ chưa có tác dụng."
                    n.onBackup -> "Pi đang phát Wi-Fi SmartAC-Backup."
                    else -> "Pi đang dùng Wi-Fi nhà."
                },
                error = !n.running,
            )
            Choice(
                listOf("auto" to "Tự động", "standalone" to "Độc lập", "home" to "Wi-Fi nhà"),
                n.mode, n.running && !vm.busy,
            ) { ask = it }
        }
    }
    ask?.let { mode ->
        AlertDialog(
            onDismissRequest = { ask = null },
            title = { Text("Đổi chế độ mạng?") },
            text = {
                Text(
                    when (mode) {
                        "standalone" -> "Pi rời Wi-Fi nhà và phát SmartAC-Backup (không có Internet). Nếu app đã quét mã Wi-Fi trên tem, app sẽ tự vào mạng đó sau khoảng 20 giây; nếu chưa, vào Wi-Fi SmartAC-Backup bằng tay."
                        "home" -> "Pi chỉ dùng Wi-Fi nhà, không bao giờ phát mạng riêng. Nếu Wi-Fi nhà đổi mật khẩu, phải giữ nút reset để vào lại."
                        else -> "Pi dùng Wi-Fi nhà; mất Wi-Fi nhà quá 2 phút thì tự phát SmartAC-Backup."
                    }
                )
            },
            confirmButton = { TextButton(onClick = { vm.setNetwork(mode); ask = null }) { Text("Chuyển") } },
            dismissButton = { TextButton(onClick = { ask = null }) { Text("Thôi") } },
        )
    }
}

/** Nhan dien va doi giao thuc IR cua dieu hoa (chi quan tri vien, v0.11.0). */
@Composable
internal fun IrCard(vm: AppViewModel) {
    val ir = vm.ir ?: return
    var brand by remember { mutableStateOf<String?>(null) }
    var showBrands by remember { mutableStateOf(false) }
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("Điều hòa trong phòng", fontWeight = FontWeight.SemiBold)
            Text(
                when {
                    ir.protocol == null -> "Node chưa báo giao thức (firmware cũ hơn 0.11.0?)."
                    ir.confirmed -> "Giao thức ${ir.protocol}, ${ir.confirmedBy ?: ""} đã xác nhận điều hòa nhận lệnh."
                    else -> "Giao thức ${ir.protocol}, chưa xác nhận điều hòa có nhận lệnh."
                },
                style = MaterialTheme.typography.bodyMedium,
            )
            Button(onClick = { vm.toggleLearn() }, enabled = !vm.busy, modifier = Modifier.fillMaxWidth()) {
                Text(if (ir.learnActive) "Dừng nhận diện" else "Nhận diện remote")
            }
            if (ir.learnActive) {
                Hint("Đang nghe: cầm remote điều hòa, chĩa vào node, bấm nút nguồn hoặc đổi nhiệt độ 2–3 lần.")
            } else if (ir.learnStarted && ir.candidates.isEmpty()) {
                Hint("Không nghe thấy tín hiệu nào. Thử lại, đứng gần node hơn.")
            }
            ir.candidates.forEach { c ->
                ProtocolRow(vm, ir, c.protocol, c.note, c.model, usable = c.ac)
            }
            if (vm.irTesting) {
                Hint("Thử lệnh: nghe tiếng bíp và nhìn đèn dàn lạnh.")
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(onClick = { vm.testPower(true) }, enabled = !vm.busy, modifier = Modifier.weight(1f)) {
                        Text("Bật thử")
                    }
                    OutlinedButton(onClick = { vm.testPower(false) }, enabled = !vm.busy, modifier = Modifier.weight(1f)) {
                        Text("Tắt thử")
                    }
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(onClick = { vm.confirmIr(true) }, enabled = !vm.busy, modifier = Modifier.weight(1f)) {
                        Text("Đã phản ứng")
                    }
                    OutlinedButton(onClick = { vm.confirmIr(false) }, enabled = !vm.busy, modifier = Modifier.weight(1f)) {
                        Text("Không phản ứng")
                    }
                }
            }
            TextButton(onClick = { showBrands = !showBrands }, contentPadding = PaddingValues(0.dp)) {
                Text(if (showBrands) "Ẩn danh sách hãng" else "Chọn giao thức theo hãng")
            }
            if (showBrands) {
                val b = brand
                if (b == null) {
                    ir.brands.keys.forEach { name ->
                        TextButton(onClick = { brand = name }, contentPadding = PaddingValues(horizontal = 0.dp)) { Text(name) }
                    }
                } else {
                    TextButton(onClick = { brand = null }, contentPadding = PaddingValues(0.dp)) { Text("← Hãng khác ($b)") }
                    ir.brands[b].orEmpty().forEachIndexed { i, p ->
                        ProtocolRow(vm, ir, p, if (i == 0) "thử cái này trước" else "nếu cái trên không được", -1, true)
                    }
                }
            }
        }
    }
}

@Composable
private fun ProtocolRow(vm: AppViewModel, ir: IrInfo, protocol: String, note: String, model: Int, usable: Boolean) {
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Text(protocol, fontWeight = FontWeight.Medium)
        Hint(note)
        if (usable) {
            val current = ir.protocol == protocol
            OutlinedButton(onClick = { vm.useProtocol(protocol, model) }, enabled = !current && !vm.busy) {
                Text(if (current) "Đang dùng" else "Dùng giao thức này")
            }
        }
    }
}
