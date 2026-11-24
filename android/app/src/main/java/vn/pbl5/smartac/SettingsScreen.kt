package vn.pbl5.smartac

import androidx.activity.compose.BackHandler
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
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
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp

val ROLE_NAME = mapOf("admin" to "quản trị viên", "member" to "thành viên", "guest" to "khách", "pending" to "chờ duyệt",
    "automation" to "tự động")

@Composable
fun SettingsScreen(vm: AppViewModel, open: (String) -> Unit) {
    val p = LocalPalette.current
    val me = vm.me
    val admin = me?.role == "admin"
    var pwOpen by remember { mutableStateOf(false) }
    var signOutAsk by remember { mutableStateOf(false) }
    Page {
        Text("Cài đặt", style = MaterialTheme.typography.headlineMedium, modifier = Modifier.padding(top = 12.dp))
        Panel(padding = PaddingValues(16.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(14.dp)) {
                Box(Modifier.size(52.dp).clip(CircleShape).background(p.ink), contentAlignment = Alignment.Center) {
                    Text((me?.displayName ?: "?").take(1).uppercase(), color = p.bg, style = MaterialTheme.typography.titleLarge)
                }
                Column(Modifier.weight(1f)) {
                    Text(me?.displayName ?: "", style = MaterialTheme.typography.titleMedium)
                    Hint("${me?.username ?: ""}, ${ROLE_NAME[me?.role] ?: me?.role ?: ""}")
                }
                SecondaryButton("Đổi mật khẩu", { pwOpen = true }, height = 44.dp)
            }
        }

        if (admin) {
            SectionTitle("Nhà")
            Panel(padding = PaddingValues(0.dp)) {
                val pending = vm.members.count { it.role == "pending" }
                SettingRow(Icons.People, p.blueTint, p.blueStroke, "Thành viên", "${vm.members.size} tài khoản",
                    badge = if (pending > 0) pending.toString() else null) { open("members") }
                Divider()
                val ir = vm.ir
                SettingRow(Icons.Ac, p.blueTint, p.blueStroke, "Điều hòa trong phòng",
                    when {
                        ir == null || ir.protocol == null -> "Chưa rõ giao thức"
                        ir.confirmed -> "Giao thức ${ir.protocol}, đã xác nhận"
                        else -> "Giao thức ${ir.protocol}, chưa xác nhận"
                    }) { open("ir") }
                Divider()
                val n = vm.net
                SettingRow(Icons.Wifi, p.mintTint, p.mintIcon, "Mạng của Pi",
                    when {
                        n == null -> "Đang tải"
                        else -> "${NET_NAME[n.mode] ?: n.mode}, ${if (n.onBackup) "đang phát Wi-Fi riêng" else "đang dùng Wi-Fi nhà"}"
                    }) { open("network") }
                Divider()
                SettingRow(Icons.Globe, p.mintTint, p.mintIcon, "Truy cập từ xa",
                    vm.publicUrl?.let { "${AppViewModel.shortUrl(it)}, ${if (vm.link == Link.INTERNET) "đang dùng" else "sẵn sàng"}" }
                        ?: "Chưa bật (Bước 13 trong hướng dẫn)", onClick = null)
            }
        }

        SectionTitle("Ứng dụng")
        Panel(padding = PaddingValues(0.dp)) {
            Row(Modifier.fillMaxWidth().heightIn(min = 64.dp).padding(horizontal = 16.dp, vertical = 10.dp),
                verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("Thông báo", style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.Medium)
                    Hint(if (admin) "Node mất kết nối, tài khoản chờ duyệt, phòng nóng" else "Node mất kết nối, phòng nóng")
                }
                Switch(checked = vm.notifyEnabled, onCheckedChange = { vm.setNotify(it) },
                    colors = SwitchDefaults.colors(checkedTrackColor = p.blue, checkedThumbColor = Color.White,
                        uncheckedTrackColor = p.track, uncheckedBorderColor = p.line))
            }
            Divider()
            SettingRow(Icons.Settings, p.track, p.ink2, "Raspberry Pi", AppViewModel.shortUrl(vm.serverUrl)) { vm.changeServer() }
            Divider()
            Row(Modifier.fillMaxWidth().heightIn(min = 56.dp).padding(horizontal = 16.dp), verticalAlignment = Alignment.CenterVertically) {
                Text("Phiên bản", style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.Medium, modifier = Modifier.weight(1f))
                Hint("app ${BuildConfig.VERSION_NAME}")
            }
        }
        vm.notice?.let { Hint(it) }
        SecondaryButton("Đăng xuất", { signOutAsk = true }, Modifier.fillMaxWidth())
    }

    if (pwOpen) PasswordDialog(vm) { pwOpen = false }
    if (signOutAsk) {
        AlertDialog(
            onDismissRequest = { signOutAsk = false },
            title = { Text("Đăng xuất?") },
            text = { Text("Bạn sẽ cần đăng nhập lại trên điện thoại này.") },
            confirmButton = { TextButton(onClick = { signOutAsk = false; vm.signOut() }) { Text("Đăng xuất") } },
            dismissButton = { TextButton(onClick = { signOutAsk = false }) { Text("Thôi") } },
        )
    }
}

val NET_NAME = mapOf("auto" to "Tự động", "standalone" to "Độc lập", "home" to "Chỉ Wi-Fi nhà")

@Composable
private fun PasswordDialog(vm: AppViewModel, close: () -> Unit) {
    var old by remember { mutableStateOf("") }
    var new by remember { mutableStateOf("") }
    var error by remember { mutableStateOf<String?>(null) }
    var done by remember { mutableStateOf(false) }
    val p = LocalPalette.current
    AlertDialog(
        onDismissRequest = close,
        title = { Text("Đổi mật khẩu") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                if (done) {
                    Text("Đã đổi mật khẩu. Các thiết bị khác của bạn đã bị đăng xuất.")
                } else {
                    OutlinedTextField(old, { old = it }, label = { Text("Mật khẩu hiện tại") }, singleLine = true,
                        visualTransformation = PasswordVisualTransformation(), colors = fieldColors(), modifier = Modifier.fillMaxWidth())
                    OutlinedTextField(new, { new = it }, label = { Text("Mật khẩu mới (ít nhất 8 ký tự)") }, singleLine = true,
                        visualTransformation = PasswordVisualTransformation(), colors = fieldColors(), modifier = Modifier.fillMaxWidth())
                    error?.let { Hint(it, color = p.orangeText) }
                }
            }
        },
        confirmButton = {
            if (done) TextButton(onClick = close) { Text("Xong") }
            else TextButton(onClick = {
                if (new.length < 8) error = "Mật khẩu mới cần ít nhất 8 ký tự."
                else vm.changePassword(old, new) { err -> if (err == null) done = true else error = err }
            }, enabled = !vm.busy) { Text("Đổi mật khẩu") }
        },
        dismissButton = { if (!done) TextButton(onClick = close) { Text("Thôi") } },
    )
}

// ------------------------------------------------------------------ thanh vien
@Composable
fun MembersScreen(vm: AppViewModel, onBack: () -> Unit) {
    BackHandler(onBack = onBack)
    val me = vm.me
    var toDelete by remember { mutableStateOf<Member?>(null) }
    Page {
        TopBar("Thành viên", onBack = onBack)
        Hint("Người khác tự tạo tài khoản trong app, rồi bạn cấp quyền ở đây. Thành viên điều khiển được; khách chỉ xem.")
        vm.members.forEach { m ->
            val mine = m.username == me?.username
            Panel(radius = 20.dp) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text(m.displayName, style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.SemiBold)
                        Hint("${m.username}, ${ROLE_NAME[m.role] ?: m.role}${if (mine) " (bạn)" else ""}",
                            color = if (m.role == "pending") LocalPalette.current.orangeText else LocalPalette.current.ink2)
                    }
                }
                if (!mine) {
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        if (m.role == "pending") {
                            PrimaryButton("Duyệt", { vm.setRole(m, "member") }, height = 44.dp, enabled = !vm.busy)
                            SecondaryButton("Khách", { vm.setRole(m, "guest") }, height = 44.dp, enabled = !vm.busy)
                            QuietButton("Từ chối", { toDelete = m }, color = LocalPalette.current.orangeText)
                        } else {
                            listOf("admin" to "Quản trị", "member" to "Thành viên", "guest" to "Khách")
                                .filter { it.first != m.role }
                                .forEach { (role, label) -> SecondaryButton(label, { vm.setRole(m, role) }, height = 44.dp, enabled = !vm.busy) }
                            QuietButton("Xóa", { toDelete = m }, color = LocalPalette.current.orangeText)
                        }
                    }
                }
            }
        }
        vm.notice?.let { Hint(it) }
    }
    toDelete?.let { m ->
        AlertDialog(
            onDismissRequest = { toDelete = null },
            title = { Text("Xóa tài khoản ${m.username}?") },
            text = { Text("Người này sẽ bị đăng xuất khỏi mọi thiết bị. Phiếu cảm nhận đã ghi vẫn giữ lại.") },
            confirmButton = { TextButton(onClick = { vm.removeMember(m); toDelete = null }) { Text("Xóa") } },
            dismissButton = { TextButton(onClick = { toDelete = null }) { Text("Thôi") } },
        )
    }
}

// ------------------------------------------------------------------ mang cua Pi
@Composable
fun NetworkScreen(vm: AppViewModel, onBack: () -> Unit) {
    BackHandler(onBack = onBack)
    val n = vm.net
    var ask by remember { mutableStateOf<String?>(null) }
    Page {
        TopBar("Mạng của Pi", onBack = onBack)
        if (n == null) {
            Hint("Đang tải…")
        } else {
            Hint(when {
                !n.running -> "Dịch vụ pbl5-netwatch không chạy nên đổi chế độ chưa có tác dụng."
                n.onBackup -> "Pi đang phát Wi-Fi SmartAC-Backup."
                else -> "Pi đang dùng Wi-Fi nhà."
            }, color = if (n.running) LocalPalette.current.ink2 else LocalPalette.current.orangeText)
            listOf(
                Triple("auto", "Tự động", "Dùng Wi-Fi nhà; mất Wi-Fi nhà quá 2 phút thì tự phát mạng riêng."),
                Triple("standalone", "Độc lập", "Luôn phát SmartAC-Backup, không cần router. Không có Internet."),
                Triple("home", "Chỉ Wi-Fi nhà", "Không bao giờ phát mạng riêng."),
            ).forEach { (mode, title, desc) ->
                val sel = n.mode == mode
                val p = LocalPalette.current
                Panel(radius = 20.dp, border = if (sel) p.blueStroke else p.line,
                    onClick = if (sel || !n.running || vm.busy) null else ({ ask = mode })) {
                    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                        Box(Modifier.size(22.dp).clip(CircleShape).border(2.dp, if (sel) p.blueStroke else p.line, CircleShape),
                            contentAlignment = Alignment.Center) { if (sel) Dot(p.blueStroke, 10.dp) }
                        Column(Modifier.weight(1f)) {
                            Text(title, style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.SemiBold)
                            Hint(desc)
                        }
                    }
                }
            }
        }
        vm.notice?.let { Hint(it) }
    }
    ask?.let { mode ->
        AlertDialog(
            onDismissRequest = { ask = null },
            title = { Text("Chuyển sang ${NET_NAME[mode]}?") },
            text = {
                Text(if (mode == "standalone") "Pi rời Wi-Fi nhà và phát SmartAC-Backup. Nếu app đã quét mã Wi-Fi trên tem, app sẽ tự vào mạng đó sau khoảng 20 giây."
                else "Pi sẽ áp dụng trong khoảng 15 giây.")
            },
            confirmButton = { TextButton(onClick = { vm.setNetwork(mode); ask = null }) { Text("Chuyển") } },
            dismissButton = { TextButton(onClick = { ask = null }) { Text("Thôi") } },
        )
    }
}

// ------------------------------------------------------------------ nhan dien dieu hoa (giao thuc IR)
@Composable
fun IrScreen(vm: AppViewModel, onBack: () -> Unit) {
    BackHandler(onBack = onBack)
    val p = LocalPalette.current
    val ir = vm.ir
    var brand by remember { mutableStateOf<String?>(null) }
    Page {
        TopBar("Nhận diện điều hòa", onBack = onBack)
        if (ir == null) {
            Hint("Đang tải…")
        } else {
            Steps(if (vm.irTesting) 1 else if (ir.confirmed && !ir.learnActive) 2 else 0)
            Hint(when {
                ir.protocol == null -> "Node chưa báo giao thức (firmware cũ hơn 0.11.0?)."
                ir.confirmed -> "Đang dùng giao thức ${ir.protocol}, ${ir.confirmedBy ?: ""} đã xác nhận điều hòa nhận lệnh."
                else -> "Đang dùng giao thức ${ir.protocol}, chưa xác nhận điều hòa có nhận lệnh."
            })
            if (vm.irTesting) {
                Panel(border = p.blueStroke) {
                    SectionTitle("Thử lệnh")
                    Hint("Bấm Bật thử hoặc Tắt thử, nghe điều hòa bíp và nhìn đèn dàn lạnh.")
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        SecondaryButton("Bật thử", { vm.testPower(true) }, Modifier.weight(1f), enabled = !vm.busy)
                        SecondaryButton("Tắt thử", { vm.testPower(false) }, Modifier.weight(1f), enabled = !vm.busy)
                    }
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        PrimaryButton("Đã phản ứng", { vm.confirmIr(true) }, Modifier.weight(1f), enabled = !vm.busy)
                        SecondaryButton("Không phản ứng", { vm.confirmIr(false) }, Modifier.weight(1f), enabled = !vm.busy)
                    }
                }
            } else {
                Listening(ir.learnActive)
                PrimaryButton(if (ir.learnActive) "Dừng nghe" else "Bắt đầu nghe remote", { vm.toggleLearn() },
                    Modifier.fillMaxWidth(), enabled = !vm.busy)
                if (!ir.learnActive && ir.learnStarted && ir.candidates.isEmpty()) {
                    Hint("Không nghe thấy tín hiệu nào. Thử lại, đứng gần node hơn.", center = true)
                }
            }
            ir.candidates.forEach { c ->
                if (c.ac) {
                    Panel(border = p.blueStroke) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text(c.protocol, style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
                            Hint("${c.count} lần")
                        }
                        Hint(c.note)
                        val current = ir.protocol == c.protocol
                        PrimaryButton(if (current) "Đang dùng" else "Khớp, dùng giao thức này", { vm.useProtocol(c.protocol, c.model) },
                            Modifier.fillMaxWidth(), enabled = !current && !vm.busy, height = 48.dp)
                    }
                } else {
                    Panel(radius = 18.dp) {
                        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                            Dot(p.muted, 10.dp)
                            Hint(c.note)
                        }
                    }
                }
            }
            vm.notice?.let { Hint(it) }
            SectionTitle("Chọn theo hãng điều hòa")
            val b = brand
            if (b == null) {
                Panel(padding = PaddingValues(0.dp)) {
                    ir.brands.keys.forEachIndexed { i, name ->
                        if (i > 0) Divider()
                        Row(Modifier.fillMaxWidth().heightIn(min = 52.dp).clickable(role = Role.Button) { brand = name }
                            .padding(horizontal = 16.dp), verticalAlignment = Alignment.CenterVertically) {
                            Text(name, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
                            Icon(Icons.Chevron, contentDescription = null, tint = p.muted, modifier = Modifier.size(16.dp))
                        }
                    }
                }
            } else {
                QuietButton("← Hãng khác ($b)", { brand = null })
                ir.brands[b].orEmpty().forEachIndexed { i, proto ->
                    Panel(radius = 18.dp) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Column(Modifier.weight(1f)) {
                                Text(proto, style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.SemiBold)
                                Hint(if (i == 0) "thử cái này trước" else "nếu cái trên không được")
                            }
                            val current = ir.protocol == proto
                            SecondaryButton(if (current) "Đang dùng" else "Dùng", { vm.useProtocol(proto) }, height = 44.dp,
                                enabled = !current && !vm.busy)
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun Steps(current: Int) {
    val p = LocalPalette.current
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        listOf("Nghe remote", "Bật thử", "Xác nhận").forEachIndexed { i, label ->
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Box(Modifier.fillMaxWidth().heightIn(min = 4.dp).clip(RoundedCornerShape(2.dp))
                    .background(if (i <= current) p.blueStroke else p.line))
                Text(label, style = MaterialTheme.typography.labelSmall,
                    color = if (i == current) p.ink else p.ink2, fontWeight = if (i == current) FontWeight.SemiBold else FontWeight.Normal)
            }
        }
    }
}

/** Vong song quanh remote khi dang nghe. */
@Composable
private fun Listening(active: Boolean) {
    val p = LocalPalette.current
    val t = rememberInfiniteTransition(label = "nghe")
    val pulse by t.animateFloat(0.6f, 1.2f, infiniteRepeatable(tween(2200), RepeatMode.Restart), label = "song")
    Box(Modifier.fillMaxWidth().padding(vertical = 8.dp), contentAlignment = Alignment.Center) {
        if (active) {
            Box(Modifier.size(150.dp).scale(pulse).clip(CircleShape).background(p.blueTint.copy(alpha = (1.25f - pulse).coerceIn(0f, 0.8f))))
        }
        Box(Modifier.size(92.dp).clip(CircleShape).background(p.surface).border(1.dp, p.line, CircleShape),
            contentAlignment = Alignment.Center) {
            Icon(Icons.Remote, contentDescription = null, tint = p.blueStroke, modifier = Modifier.size(40.dp))
        }
    }
    Hint(if (active) "Đang nghe: cầm remote của điều hòa, chĩa vào node, bấm nút nguồn hoặc đổi nhiệt độ vài lần."
         else "Node sẽ nghe trong 60 giây. Chuẩn bị sẵn remote của điều hòa.", center = true)
}
