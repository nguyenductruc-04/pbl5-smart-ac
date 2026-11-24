package vn.pbl5.smartac

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.layout.only
import androidx.compose.foundation.layout.WindowInsetsSides
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.lifecycle.viewmodel.compose.viewModel

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge(
            statusBarStyle = SystemBarStyle.auto(Color.Transparent.toArgb(), Color.Transparent.toArgb()),
            navigationBarStyle = SystemBarStyle.auto(Color.Transparent.toArgb(), Color.Transparent.toArgb()),
        )
        super.onCreate(savedInstanceState)
        WatchWorker.schedule(this)
        setContent {
            AppTheme {
                Box(Modifier.fillMaxSize().background(LocalPalette.current.bg)) {
                    App(viewModel())
                }
            }
        }
    }
}

@Composable
fun App(vm: AppViewModel) {
    when (val s = vm.screen) {
        Screen.Loading -> Box(Modifier.safeDrawingPadding()) { LoadingScreen() }
        is Screen.Connect -> Box(Modifier.safeDrawingPadding()) { ConnectScreen(s, vm) }
        is Screen.Auth -> Box(Modifier.safeDrawingPadding()) { AuthScreen(s, vm) }
        Screen.Main -> {
            AskNotificationPermission()
            MainShell(vm)
        }
    }
}

private enum class Tab(val label: String) { HOME("Nhà"), HISTORY("Lịch sử"), SETTINGS("Cài đặt") }

/** Ba tab o day man hinh; trang chi tiet (dieu khien phong, thanh vien...) che tab va co nut quay lai. */
@Composable
private fun MainShell(vm: AppViewModel) {
    val p = LocalPalette.current
    var tab by rememberSaveable { mutableStateOf(Tab.HOME) }
    var detail by rememberSaveable { mutableStateOf<String?>(null) }
    val back = { detail = null }

    Column(Modifier.fillMaxSize()) {
        Box(Modifier.weight(1f).fillMaxWidth()
            .windowInsetsPadding(WindowInsets.safeDrawing.only(WindowInsetsSides.Top + WindowInsetsSides.Horizontal))) {
            when (detail) {
                "room" -> ControlScreen(vm, back) { detail = "ir" }
                "members" -> MembersScreen(vm) { detail = null }
                "ir" -> IrScreen(vm) { detail = null }
                "network" -> NetworkScreen(vm) { detail = null }
                else -> when (tab) {
                    Tab.HOME -> HomeScreen(vm, openRoom = { detail = "room" }, openSettings = { tab = Tab.SETTINGS })
                    Tab.HISTORY -> HistoryScreen(vm)
                    Tab.SETTINGS -> SettingsScreen(vm) { detail = it }
                }
            }
        }
        if (detail == null) {
            NavigationBar(containerColor = p.surface, tonalElevation = 0.dp) {
                Tab.entries.forEach { t ->
                    NavigationBarItem(
                        selected = tab == t,
                        onClick = { tab = t },
                        icon = {
                            Icon(when (t) { Tab.HOME -> Icons.Home; Tab.HISTORY -> Icons.History; Tab.SETTINGS -> Icons.Settings },
                                contentDescription = null, modifier = Modifier.size(24.dp))
                        },
                        label = { Text(t.label, style = MaterialTheme.typography.labelMedium) },
                        colors = NavigationBarItemDefaults.colors(
                            selectedIconColor = p.blueStroke, selectedTextColor = p.ink, indicatorColor = p.blueTint,
                            unselectedIconColor = p.ink2, unselectedTextColor = p.ink2,
                        ),
                    )
                }
            }
        } else {
            Box(Modifier.windowInsetsPadding(WindowInsets.safeDrawing.only(WindowInsetsSides.Bottom)))
        }
    }

    vm.pendingConfirm?.let {
        AlertDialog(
            onDismissRequest = { vm.pendingConfirm = null },
            title = { Text("Máy nén vừa tắt") },
            text = { Text("Nên đợi máy nén nghỉ đủ (thường 3 phút) rồi mới bật lại. Vẫn bật ngay?") },
            confirmButton = { TextButton(onClick = { vm.confirmEarlyStart() }) { Text("Vẫn bật") } },
            dismissButton = { TextButton(onClick = { vm.pendingConfirm = null }) { Text("Đợi") } },
        )
    }
}

/** Android 13+: xin quyen thong bao mot lan, sau khi da dang nhap (luc nguoi dung hieu app de lam gi). */
@Composable
private fun AskNotificationPermission() {
    if (Build.VERSION.SDK_INT < 33) return
    val context = LocalContext.current
    val launcher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) {}
    LaunchedEffect(Unit) {
        val granted = ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) ==
            PackageManager.PERMISSION_GRANTED
        if (!granted) launcher.launch(Manifest.permission.POST_NOTIFICATIONS)
    }
}
