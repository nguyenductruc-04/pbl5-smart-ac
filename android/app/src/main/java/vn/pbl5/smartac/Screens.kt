package vn.pbl5.smartac

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.journeyapps.barcodescanner.ScanContract
import com.journeyapps.barcodescanner.ScanOptions
import org.json.JSONObject
import java.util.Locale

@Composable
private fun Page(content: @Composable () -> Unit) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .verticalScroll(rememberScrollState())
            .padding(20.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) { content() }
}

@Composable
private fun Title(text: String) {
    Text(text, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.SemiBold)
}

@Composable
internal fun Hint(text: String, error: Boolean = false) {
    Text(
        text,
        style = MaterialTheme.typography.bodyMedium,
        color = if (error) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurfaceVariant,
    )
}

/** Mo camera quet QR tren tem (ma thiet lap hoac ma Wi-Fi du phong). */
@Composable
private fun rememberScanner(vm: AppViewModel): () -> Unit {
    val launcher = rememberLauncherForActivityResult(ScanContract()) { result ->
        result.contents?.let { vm.onScan(it) }
    }
    return {
        launcher.launch(
            ScanOptions()
                .setDesiredBarcodeFormats(ScanOptions.QR_CODE)
                .setPrompt("Quét mã QR trên tem dán ở Raspberry Pi")
                .setBeepEnabled(false)
                .setOrientationLocked(false)
        )
    }
}

// ------------------------------------------------------------------ tim Pi
@Composable
fun ConnectScreen(s: Screen.Connect, vm: AppViewModel) {
    var address by rememberSaveable { mutableStateOf("") }
    Page {
        Title("Tìm Raspberry Pi")
        Hint("Điện thoại cần ở cùng mạng Wi-Fi với Pi. Ở chế độ độc lập, vào Wi-Fi SmartAC-Backup rồi bấm Thử lại.")
        s.error?.let { Hint(it, error = true) }
        if (s.found.isEmpty()) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                CircularProgressIndicator(modifier = Modifier.size(20.dp), strokeWidth = 2.dp)
                Hint("Đang tìm trong mạng Wi-Fi…")
            }
        } else {
            Text("Tìm thấy", fontWeight = FontWeight.SemiBold)
            s.found.forEach { url ->
                FilledTonalButton(onClick = { vm.connectTo(url) }, modifier = Modifier.fillMaxWidth()) {
                    Text(AppViewModel.shortUrl(url))
                }
            }
        }
        OutlinedButton(onClick = { vm.retry() }, modifier = Modifier.fillMaxWidth()) { Text("Thử lại") }
        val scan = rememberScanner(vm)
        Button(onClick = scan, modifier = Modifier.fillMaxWidth()) { Text("Quét mã Wi-Fi trên tem") }
        Hint(
            if (vm.wifiJoinSupported) "Mã bên phải tem đưa điện thoại vào thẳng Wi-Fi SmartAC-Backup của Pi, kể cả khi không có Wi-Fi nhà."
            else "Điện thoại này cần vào Wi-Fi SmartAC-Backup bằng tay trong Cài đặt."
        )
        Spacer(Modifier.height(8.dp))
        Text("Hoặc nhập địa chỉ", fontWeight = FontWeight.SemiBold)
        OutlinedTextField(
            value = address,
            onValueChange = { address = it },
            label = { Text("Địa chỉ IP của Pi hoặc tên miền") },
            placeholder = { Text("192.168.1.20") },
            singleLine = true,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri, imeAction = ImeAction.Go),
            modifier = Modifier.fillMaxWidth(),
        )
        Button(
            onClick = { vm.connectTo(address) },
            enabled = address.isNotBlank() && !vm.busy,
            modifier = Modifier.fillMaxWidth(),
        ) { Text("Kết nối") }
    }
}

// ------------------------------------------------------------------ dang nhap / dang ky / thiet lap
@Composable
fun AuthScreen(s: Screen.Auth, vm: AppViewModel) {
    var code by rememberSaveable(vm.setupCode) { mutableStateOf(vm.setupCode ?: "") }
    var username by rememberSaveable { mutableStateOf("") }
    var displayName by rememberSaveable { mutableStateOf("") }
    var password by rememberSaveable { mutableStateOf("") }
    var password2 by rememberSaveable { mutableStateOf("") }
    var localError by rememberSaveable { mutableStateOf<String?>(null) }
    val mode = s.mode

    Page {
        Title(
            when (mode) {
                AuthMode.LOGIN -> "Đăng nhập"
                AuthMode.REGISTER -> "Tạo tài khoản"
                AuthMode.SETUP -> "Thiết lập lần đầu"
            }
        )
        Hint(
            when (mode) {
                AuthMode.LOGIN -> "Đăng nhập bằng tài khoản trên Raspberry Pi này."
                AuthMode.REGISTER -> "Sau khi tạo, quản trị viên cần cấp quyền thì bạn mới đăng nhập được."
                AuthMode.SETUP -> "Pi này chưa có chủ. Nhập mã thiết lập in trên tem dán ở Pi, rồi tạo tài khoản quản trị viên."
            }
        )
        if (mode == AuthMode.SETUP) {
            OutlinedTextField(
                value = code, onValueChange = { code = it.uppercase(Locale.ROOT) },
                label = { Text("Mã thiết lập") }, placeholder = { Text("XXXX-XXXX-XXXX") },
                singleLine = true, modifier = Modifier.fillMaxWidth(),
            )
            val scan = rememberScanner(vm)
            OutlinedButton(onClick = scan, modifier = Modifier.fillMaxWidth()) { Text("Quét mã trên tem") }
        }
        OutlinedTextField(
            value = username, onValueChange = { username = it },
            label = { Text("Tên đăng nhập") }, singleLine = true,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Ascii),
            modifier = Modifier.fillMaxWidth(),
        )
        if (mode != AuthMode.LOGIN) {
            OutlinedTextField(
                value = displayName, onValueChange = { displayName = it },
                label = { Text("Tên hiển thị (không bắt buộc)") }, singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
        }
        OutlinedTextField(
            value = password, onValueChange = { password = it },
            label = { Text("Mật khẩu") }, singleLine = true,
            visualTransformation = PasswordVisualTransformation(),
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
            modifier = Modifier.fillMaxWidth(),
        )
        if (mode != AuthMode.LOGIN) {
            OutlinedTextField(
                value = password2, onValueChange = { password2 = it },
                label = { Text("Nhập lại mật khẩu") }, singleLine = true,
                visualTransformation = PasswordVisualTransformation(),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                modifier = Modifier.fillMaxWidth(),
            )
        }
        val message = localError ?: s.message
        message?.let { Hint(it, error = localError != null || !s.ok) }
        Button(
            onClick = {
                localError = when {
                    username.trim().length < 3 -> "Tên đăng nhập cần ít nhất 3 ký tự."
                    mode != AuthMode.LOGIN && password.length < 8 -> "Mật khẩu cần ít nhất 8 ký tự."
                    mode != AuthMode.LOGIN && password != password2 -> "Hai lần nhập mật khẩu chưa giống nhau."
                    mode == AuthMode.SETUP && code.isBlank() -> "Nhập mã thiết lập trên tem."
                    else -> null
                }
                if (localError == null) {
                    vm.submitAuth(mode, code, username, displayName, password)
                    password2 = ""
                }
            },
            enabled = !vm.busy,
            modifier = Modifier.fillMaxWidth(),
        ) {
            Text(
                when (mode) {
                    AuthMode.LOGIN -> "Đăng nhập"
                    AuthMode.REGISTER -> "Gửi yêu cầu"
                    AuthMode.SETUP -> "Tạo tài khoản quản trị"
                }
            )
        }
        when (mode) {
            AuthMode.LOGIN -> TextButton(onClick = { localError = null; vm.switchAuth(AuthMode.REGISTER) }) {
                Text("Chưa có tài khoản? Tạo tài khoản")
            }
            AuthMode.REGISTER -> TextButton(onClick = { localError = null; vm.switchAuth(AuthMode.LOGIN) }) {
                Text("Đã có tài khoản? Đăng nhập")
            }
            AuthMode.SETUP -> {}
        }
        TextButton(onClick = { vm.changeServer() }) {
            Text("Đổi Raspberry Pi (${AppViewModel.shortUrl(vm.serverUrl)})")
        }
    }
}

// ------------------------------------------------------------------ man hinh chinh
private val MODE_NAME = mapOf("cool" to "Mát", "dry" to "Khô", "fan" to "Quạt", "auto" to "Tự động", "heat" to "Sưởi")
private val ROLE_NAME = mapOf("admin" to "Quản trị viên", "member" to "Thành viên", "guest" to "Khách")

private fun fmt(v: Double?, unit: String): String =
    if (v == null) "–" else String.format(Locale.forLanguageTag("vi"), "%.1f %s", v, unit)

@Composable
fun MainScreen(vm: AppViewModel) {
    val me = vm.me
    val r = vm.room
    Page {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Title("Điều hòa thông minh")
                if (me != null) Hint("${me.displayName}, ${ROLE_NAME[me.role] ?: me.role}")
            }
            TextButton(onClick = { vm.signOut() }) { Text("Đăng xuất") }
        }
        vm.linkError?.let { Hint("Mất kết nối tới Pi: $it", error = true) }
        if (vm.noRooms || r == null) {
            Hint("Chưa có node nào báo về. Cắm điện node trong phòng rồi đợi khoảng một phút.")
        } else {
            RoomContent(vm, me, r)
        }
        if (me?.role == "admin") {
            IrCard(vm)
            NetworkCard(vm)
            MembersCard(vm, me)
        }
        vm.notice?.let { Hint(it) }
        TextButton(onClick = { vm.changeServer() }) {
            Text("Đổi Raspberry Pi (${AppViewModel.shortUrl(vm.serverUrl)})")
        }
    }

    if (vm.pendingConfirm != null) {
        AlertDialog(
            onDismissRequest = { vm.pendingConfirm = null },
            title = { Text("Máy nén vừa tắt") },
            text = { Text("Nên đợi máy nén nghỉ đủ rồi mới bật lại. Vẫn bật ngay?") },
            confirmButton = { TextButton(onClick = { vm.confirmEarlyStart() }) { Text("Vẫn bật") } },
            dismissButton = { TextButton(onClick = { vm.pendingConfirm = null }) { Text("Đợi") } },
        )
    }
}

@Composable
private fun RoomContent(vm: AppViewModel, me: Me?, r: RoomView) {
    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        val canControl = me?.canControl == true && r.online && !vm.busy
        if (me?.canControl == false) Hint("Bạn đang dùng tài khoản khách nên chỉ xem được.")
        if (!r.online) Hint("Node trong phòng đang mất kết nối.", error = true)

        Card(Modifier.fillMaxWidth()) {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text("Trong phòng", fontWeight = FontWeight.SemiBold)
                Row(horizontalArrangement = Arrangement.spacedBy(24.dp)) {
                    Reading("Nhiệt độ", fmt(r.temp, "°C"))
                    Reading("Độ ẩm", fmt(r.hum, "%"))
                    Reading("Có người", when (r.presence) { true -> "Có"; false -> "Không"; null -> "–" })
                }
                r.ageS?.let { Hint("Cập nhật $it giây trước") }
            }
        }

        Card(Modifier.fillMaxWidth()) {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                val on = r.power == "on"
                Text("Điều hòa", fontWeight = FontWeight.SemiBold)
                Hint(
                    if (r.power == null) "Chưa gửi lệnh nào"
                    else if (on) "Đang bật, chế độ ${MODE_NAME[r.mode] ?: r.mode ?: "–"}"
                    else "Đang tắt"
                )
                if (r.uncertain) Hint("Trạng thái có thể đã lệch với thực tế. Gửi một lệnh để đồng bộ lại.", error = true)
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                    val t = r.acTemp ?: 26
                    OutlinedButton(
                        onClick = { vm.command(JSONObject().put("temp", t - 1)) },
                        enabled = canControl && on && t > 16,
                    ) { Text("−", fontSize = 22.sp) }
                    Text("$t°C", fontSize = 40.sp, fontWeight = FontWeight.Medium)
                    OutlinedButton(
                        onClick = { vm.command(JSONObject().put("temp", t + 1)) },
                        enabled = canControl && on && t < 30,
                    ) { Text("+", fontSize = 22.sp) }
                }
                Button(
                    onClick = { vm.command(JSONObject().put("power", if (on) "off" else "on")) },
                    enabled = canControl,
                    modifier = Modifier.fillMaxWidth(),
                ) { Text(if (on) "Tắt điều hòa" else "Bật điều hòa") }
                if (on) {
                    Text("Chế độ", style = MaterialTheme.typography.labelLarge)
                    Choice(
                        listOf("cool" to "Mát", "dry" to "Khô", "fan" to "Quạt", "auto" to "Tự động"),
                        r.mode, canControl,
                    ) { vm.command(JSONObject().put("mode", it)) }
                    Text("Quạt", style = MaterialTheme.typography.labelLarge)
                    Choice(
                        listOf("auto" to "Tự động", "low" to "Thấp", "mid" to "Vừa", "high" to "Cao"),
                        r.fan, canControl,
                    ) { vm.command(JSONObject().put("fan", it)) }
                }
                if (me?.canControl == true) FixRow(vm, r)
            }
        }
        vm.suggestion?.let { SuggestionCard(vm, it, canControl) }
        ChartCard(vm)

        Card(Modifier.fillMaxWidth()) {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text("Bạn thấy thế nào?", fontWeight = FontWeight.SemiBold)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    val canVote = me?.canControl == true && !vm.busy
                    FilledTonalButton(onClick = { vm.vote("cooler") }, enabled = canVote, modifier = Modifier.weight(1f)) {
                        Text("Nóng")
                    }
                    FilledTonalButton(onClick = { vm.vote("comfortable") }, enabled = canVote, modifier = Modifier.weight(1f)) {
                        Text("Dễ chịu")
                    }
                    FilledTonalButton(onClick = { vm.vote("warmer") }, enabled = canVote, modifier = Modifier.weight(1f)) {
                        Text("Lạnh")
                    }
                }
            }
        }
    }
}

@Composable
private fun Reading(label: String, value: String) {
    Column {
        Text(label, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(value, style = MaterialTheme.typography.titleLarge)
    }
}

// ------------------------------------------------------------------ thanh vien (quan tri vien)
@Composable
private fun MembersCard(vm: AppViewModel, me: Me) {
    var toDelete by remember { mutableStateOf<Member?>(null) }
    toDelete?.let { m ->
        AlertDialog(
            onDismissRequest = { toDelete = null },
            title = { Text("Xóa tài khoản ${m.username}?") },
            text = { Text("Người này sẽ bị đăng xuất khỏi mọi thiết bị. Phiếu cảm nhận đã ghi vẫn giữ lại.") },
            confirmButton = { TextButton(onClick = { vm.removeMember(m); toDelete = null }) { Text("Xóa") } },
            dismissButton = { TextButton(onClick = { toDelete = null }) { Text("Thôi") } },
        )
    }
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text("Thành viên", fontWeight = FontWeight.SemiBold)
            Hint("Người khác tự tạo tài khoản trong app hoặc trên dashboard, rồi bạn cấp quyền ở đây. Thành viên điều khiển được; khách chỉ xem.")
            vm.members.forEach { m ->
                val mine = m.username == me.username
                Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text(m.displayName, fontWeight = FontWeight.Medium)
                    Hint(
                        if (m.role == "pending") "${m.username}, đang chờ duyệt"
                        else "${m.username}, ${(ROLE_NAME[m.role] ?: m.role).lowercase()}${if (mine) " (bạn)" else ""}",
                        error = m.role == "pending",
                    )
                    if (!mine) {
                        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                            if (m.role == "pending") {
                                FilledTonalButton(onClick = { vm.setRole(m, "member") }, enabled = !vm.busy) { Text("Duyệt") }
                                OutlinedButton(onClick = { vm.setRole(m, "guest") }, enabled = !vm.busy) { Text("Khách") }
                                TextButton(onClick = { vm.removeMember(m) }, enabled = !vm.busy) { Text("Từ chối") }
                            } else {
                                listOf("admin" to "Quản trị", "member" to "Thành viên", "guest" to "Khách")
                                    .filter { it.first != m.role }
                                    .forEach { (role, label) ->
                                        OutlinedButton(onClick = { vm.setRole(m, role) }, enabled = !vm.busy) { Text(label) }
                                    }
                                TextButton(onClick = { toDelete = m }, enabled = !vm.busy) { Text("Xóa") }
                            }
                        }
                    }
                }
            }
        }
    }
}
