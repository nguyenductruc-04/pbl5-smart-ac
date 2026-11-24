package vn.pbl5.smartac

import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import com.journeyapps.barcodescanner.ScanContract
import com.journeyapps.barcodescanner.ScanOptions
import java.util.Locale

/** Mo camera quet QR tren tem (ma thiet lap hoac ma Wi-Fi du phong). */
@Composable
fun rememberScanner(vm: AppViewModel): () -> Unit {
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

@Composable
fun Page(modifier: Modifier = Modifier, content: @Composable () -> Unit) {
    Column(
        modifier.fillMaxWidth().verticalScroll(rememberScrollState()).padding(horizontal = 20.dp, vertical = 12.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) { content() }
}

/** Bieu tuong app: cung bac ha (vung de chiu), cung xanh (dieu hoa), cham cam (phong). */
@Composable
fun AppMark(size: Int = 132) {
    val p = LocalPalette.current
    Canvas(Modifier.size(size.dp).semantics { contentDescription = "Biểu tượng Điều hòa thông minh" }) {
        val s = this.size.width / 132f
        drawCircle(p.blueTint)
        val r = 40f * s
        val c = Offset(66f * s, 86f * s)
        val box = Size(r * 2, r * 2)
        val tl = Offset(c.x - r, c.y - r)
        drawArc(p.band, 180f, 180f, false, tl, box, style = Stroke(12f * s, cap = StrokeCap.Round))
        drawArc(p.blueStroke, 180f, 75f, false, tl, box, style = Stroke(5f * s, cap = StrokeCap.Round))
        drawCircle(p.blueTint, 9f * s, Offset(93f * s, 58f * s))
        drawCircle(p.orange, 6f * s, Offset(93f * s, 58f * s))
    }
}

@Composable
fun LoadingScreen() {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(20.dp)) {
            AppMark(96)
            CircularProgressIndicator(color = LocalPalette.current.blueStroke, strokeWidth = 2.dp, modifier = Modifier.size(24.dp))
        }
    }
}

// ------------------------------------------------------------------ tim Pi
@Composable
fun ConnectScreen(s: Screen.Connect, vm: AppViewModel) {
    val p = LocalPalette.current
    var address by rememberSaveable { mutableStateOf("") }
    val scan = rememberScanner(vm)
    Page(Modifier.imePadding()) {
        Spacer(Modifier.height(24.dp))
        Text("Tìm Raspberry Pi", style = MaterialTheme.typography.headlineMedium)
        Hint("Cho điện thoại vào cùng mạng Wi-Fi với Pi. Nếu Pi đang phát mạng riêng, quét mã Wi-Fi trên tem.")
        s.error?.let { Hint(it, color = p.orangeText) }
        Panel {
            if (s.found.isEmpty()) {
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    CircularProgressIndicator(color = p.blueStroke, strokeWidth = 2.dp, modifier = Modifier.size(20.dp))
                    Text("Đang tìm trong mạng Wi-Fi…", style = MaterialTheme.typography.bodyMedium)
                }
            } else {
                SectionTitle("Tìm thấy")
                s.found.forEach { url ->
                    SecondaryButton(AppViewModel.shortUrl(url), { vm.connectTo(url) }, Modifier.fillMaxWidth())
                }
            }
        }
        PrimaryButton("Quét mã Wi-Fi trên tem", scan, Modifier.fillMaxWidth())
        SecondaryButton("Thử lại", { vm.retry() }, Modifier.fillMaxWidth())
        Spacer(Modifier.height(8.dp))
        SectionTitle("Hoặc nhập địa chỉ")
        OutlinedTextField(
            value = address, onValueChange = { address = it },
            label = { Text("IP của Pi hoặc tên miền") }, placeholder = { Text("192.168.1.20") },
            singleLine = true, shape = RoundedCornerShape(16.dp), colors = fieldColors(),
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
            modifier = Modifier.fillMaxWidth(),
        )
        SecondaryButton("Kết nối", { vm.connectTo(address) }, Modifier.fillMaxWidth(), enabled = address.isNotBlank() && !vm.busy)
    }
}

@Composable
fun fieldColors() = LocalPalette.current.let { p ->
    OutlinedTextFieldDefaults.colors(
        focusedBorderColor = p.blueStroke, unfocusedBorderColor = p.line,
        focusedContainerColor = p.surface, unfocusedContainerColor = p.surface,
        focusedLabelColor = p.blueStroke, cursorColor = p.blueStroke,
    )
}

// ------------------------------------------------------------------ chao mung, dang nhap, dang ky, thiet lap
@Composable
fun AuthScreen(s: Screen.Auth, vm: AppViewModel) {
    if (s.mode == AuthMode.WELCOME) WelcomeScreen(s, vm) else AuthForm(s, vm)
}

@Composable
private fun WelcomeScreen(s: Screen.Auth, vm: AppViewModel) {
    val p = LocalPalette.current
    val scan = rememberScanner(vm)
    Column(Modifier.fillMaxSize().padding(horizontal = 24.dp, vertical = 28.dp)) {
        Column(Modifier.weight(1f).fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(28.dp, Alignment.CenterVertically)) {
            AppMark()
            Text("Điều hòa thông minh", style = MaterialTheme.typography.headlineMedium)
            s.message?.let { Hint(it, color = if (s.ok) p.mintIcon else p.orangeText, center = true) }
        }
        Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
            PrimaryButton("Đăng nhập", { vm.switchAuth(AuthMode.LOGIN) }, Modifier.fillMaxWidth(),
                container = p.ink, content = p.bg, height = 56.dp)
            SecondaryButton("Tạo tài khoản", { vm.switchAuth(AuthMode.REGISTER) }, Modifier.fillMaxWidth(), height = 56.dp)
            Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
                QuietButton("Lắp Pi mới? Quét mã trên tem", scan)
            }
        }
    }
}

@Composable
private fun AuthForm(s: Screen.Auth, vm: AppViewModel) {
    val p = LocalPalette.current
    var code by rememberSaveable(vm.setupCode) { mutableStateOf(vm.setupCode ?: "") }
    var username by rememberSaveable { mutableStateOf("") }
    var displayName by rememberSaveable { mutableStateOf("") }
    var password by rememberSaveable { mutableStateOf("") }
    var password2 by rememberSaveable { mutableStateOf("") }
    var localError by rememberSaveable { mutableStateOf<String?>(null) }
    val mode = s.mode
    val scan = rememberScanner(vm)
    if (mode != AuthMode.SETUP) BackHandler { vm.switchAuth(AuthMode.WELCOME) }

    Page(Modifier.imePadding()) {
        TopBar(
            when (mode) {
                AuthMode.REGISTER -> "Tạo tài khoản"
                AuthMode.SETUP -> "Thiết lập lần đầu"
                else -> "Đăng nhập"
            },
            onBack = if (mode == AuthMode.SETUP) null else ({ vm.switchAuth(AuthMode.WELCOME) }),
        )
        when (mode) {
            AuthMode.SETUP -> Hint("Pi này chưa có chủ. Quét hoặc nhập mã trên tem dán ở Pi, rồi tạo tài khoản quản trị.")
            AuthMode.REGISTER -> Hint("Sau khi tạo, quản trị viên cần duyệt thì bạn mới đăng nhập được.")
            else -> {}
        }
        if (mode == AuthMode.SETUP) {
            OutlinedTextField(
                value = code, onValueChange = { code = it.uppercase(Locale.ROOT) },
                label = { Text("Mã thiết lập") }, placeholder = { Text("XXXX-XXXX-XXXX") },
                singleLine = true, shape = RoundedCornerShape(16.dp), colors = fieldColors(),
                modifier = Modifier.fillMaxWidth(),
            )
            SecondaryButton("Quét mã trên tem", scan, Modifier.fillMaxWidth())
        }
        OutlinedTextField(
            value = username, onValueChange = { username = it }, label = { Text("Tên đăng nhập") },
            singleLine = true, shape = RoundedCornerShape(16.dp), colors = fieldColors(),
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Ascii), modifier = Modifier.fillMaxWidth(),
        )
        if (mode != AuthMode.LOGIN) {
            OutlinedTextField(
                value = displayName, onValueChange = { displayName = it }, label = { Text("Tên hiển thị (không bắt buộc)") },
                singleLine = true, shape = RoundedCornerShape(16.dp), colors = fieldColors(), modifier = Modifier.fillMaxWidth(),
            )
        }
        OutlinedTextField(
            value = password, onValueChange = { password = it }, label = { Text("Mật khẩu") },
            singleLine = true, shape = RoundedCornerShape(16.dp), colors = fieldColors(),
            visualTransformation = PasswordVisualTransformation(),
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password), modifier = Modifier.fillMaxWidth(),
        )
        if (mode != AuthMode.LOGIN) {
            OutlinedTextField(
                value = password2, onValueChange = { password2 = it }, label = { Text("Nhập lại mật khẩu") },
                singleLine = true, shape = RoundedCornerShape(16.dp), colors = fieldColors(),
                visualTransformation = PasswordVisualTransformation(),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password), modifier = Modifier.fillMaxWidth(),
            )
        }
        val message = localError ?: s.message
        message?.let { Hint(it, color = if (localError == null && s.ok) p.mintIcon else p.orangeText) }
        PrimaryButton(
            when (mode) {
                AuthMode.REGISTER -> "Gửi yêu cầu"
                AuthMode.SETUP -> "Tạo tài khoản quản trị"
                else -> "Đăng nhập"
            },
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
            modifier = Modifier.fillMaxWidth(), enabled = !vm.busy, height = 56.dp,
        )
        when (mode) {
            AuthMode.LOGIN -> QuietButton("Chưa có tài khoản? Tạo tài khoản", { localError = null; vm.switchAuth(AuthMode.REGISTER) })
            AuthMode.REGISTER -> QuietButton("Đã có tài khoản? Đăng nhập", { localError = null; vm.switchAuth(AuthMode.LOGIN) })
            else -> {}
        }
        QuietButton("Đổi Raspberry Pi (${AppViewModel.shortUrl(vm.serverUrl)})", { vm.changeServer() }, color = p.ink2)
    }
}
