package vn.pbl5.smartac

import android.app.Application
import android.net.Uri
import android.os.Build
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import org.json.JSONObject

enum class AuthMode { LOGIN, REGISTER, SETUP }

sealed interface Screen {
    data object Loading : Screen
    data class Connect(val found: List<String>, val error: String?) : Screen
    data class Auth(val mode: AuthMode, val message: String? = null, val ok: Boolean = false) : Screen
    data object Main : Screen
}

data class Suggestion(val text: String, val why: String, val target: JSONObject?, val canApply: Boolean)

data class NetInfo(val mode: String, val running: Boolean, val onBackup: Boolean)

data class Series(val hours: Int, val ts: List<Double>, val temp: List<Double>, val hum: List<Double>)

data class Member(val username: String, val displayName: String, val role: String)

data class Me(val username: String, val displayName: String, val role: String) {
    val canControl get() = role == "admin" || role == "member"
}

data class RoomView(
    val id: String,
    val online: Boolean,
    val temp: Double?,
    val hum: Double?,
    val presence: Boolean?,
    val ageS: Int?,
    val power: String?,
    val mode: String?,
    val fan: String?,
    val acTemp: Int?,
    val uncertain: Boolean,
) {
    companion object {
        fun from(j: JSONObject): RoomView {
            val t = j.optJSONObject("telemetry")
            val ac = j.optJSONObject("ac")
            val node = j.optJSONObject("node")
            fun JSONObject?.num(key: String): Double? =
                if (this == null || this.isNull(key)) null else this.optDouble(key)
            val presence = when (val p = t?.opt("presence")) {
                is Boolean -> p
                is Number -> p.toInt() != 0
                else -> null
            }
            return RoomView(
                id = j.getString("room"),
                online = node?.optString("status") == "online",
                temp = t.num("temp"),
                hum = t.num("hum"),
                presence = presence,
                ageS = t.num("age_s")?.toInt(),
                power = ac?.optString("power")?.ifBlank { null },
                mode = ac?.optString("mode")?.ifBlank { null },
                fan = ac?.optString("fan")?.ifBlank { null },
                acTemp = ac.num("temp")?.toInt(),
                uncertain = ac?.optBoolean("uncertain") ?: false,
            )
        }
    }
}

class AppViewModel(app: Application) : AndroidViewModel(app) {
    private val prefs = Prefs(app)
    private val discovery = Discovery(app)
    private val wifi = BackupWifi(app)
    private var api: Api? = null
    private var pollJob: Job? = null
    private val found = mutableListOf<String>()

    var screen by mutableStateOf<Screen>(Screen.Loading)
        private set
    var me by mutableStateOf<Me?>(null)
        private set
    var room by mutableStateOf<RoomView?>(null)
        private set
    var noRooms by mutableStateOf(false)
        private set
    var linkError by mutableStateOf<String?>(null)
        private set
    var busy by mutableStateOf(false)
        private set
    var notice by mutableStateOf<String?>(null)
    /** Ma thiet lap doc tu QR tren tem, dien san vao man hinh thiet lap. */
    var setupCode by mutableStateOf<String?>(null)
        private set
    var members by mutableStateOf<List<Member>>(emptyList())
        private set
    val wifiJoinSupported: Boolean get() = wifi.supported
    var suggestion by mutableStateOf<Suggestion?>(null)
        private set
    var series by mutableStateOf<Series?>(null)
        private set
    var net by mutableStateOf<NetInfo?>(null)
        private set

    /** Lenh bi tu choi vi may nen vua tat, cho nguoi dung xac nhan "Van bat". */
    var pendingConfirm by mutableStateOf<JSONObject?>(null)

    val serverUrl: String? get() = api?.baseUrl

    init {
        viewModelScope.launch { connect() }
    }

    // ------------------------------------------------------------ tim Pi
    private suspend fun probe(url: String): JSONObject? =
        runCatching { Api(url, quick = true) { null }.call("GET", "/setup/status") }.getOrNull()

    /**
     * Dia chi dau tien tra loi, theo thu tu uu tien: mang nha (nhanh, khong can Internet),
     * mang du phong cua Pi, roi Internet qua Cloudflare Tunnel. Do song song nen mat toi da ~2 s.
     */
    private suspend fun findServer(): Pair<String, JSONObject>? = coroutineScope {
        val urls = listOfNotNull(prefs.baseUrl, BACKUP_URL, prefs.publicUrl).distinct()
        val probes = urls.map { url -> async { probe(url) } }
        var hit: Pair<String, JSONObject>? = null
        for ((url, p) in urls.zip(probes)) {
            val status = p.await() ?: continue
            hit = url to status
            break
        }
        probes.forEach { it.cancel() }
        hit
    }

    private suspend fun connect() {
        screen = Screen.Loading
        val hit = findServer()
        if (hit != null) use(hit.first, hit.second) else showConnect(null)
    }

    fun retry() {
        viewModelScope.launch { connect() }
    }

    fun connectTo(input: String) {
        val url = normalizeUrl(input) ?: run {
            showConnect("Địa chỉ chưa đúng. Ví dụ: 192.168.1.20 hoặc 192.168.1.20:8000")
            return
        }
        viewModelScope.launch {
            busy = true
            val status = probe(url)
            busy = false
            if (status == null) showConnect("Không thấy Raspberry Pi ở $url") else use(url, status)
        }
    }

    // ------------------------------------------------------------ QR tren tem, Wi-Fi du phong
    fun onScan(text: String) {
        LabelQr.parseSetup(text)?.let { qr ->
            setupCode = qr.code
            when (val s = screen) {
                is Screen.Auth -> if (s.mode != AuthMode.SETUP) {
                    screen = Screen.Auth(s.mode, "Pi này đã có quản trị viên, mã trên tem chỉ dùng khi thiết lập lần đầu hoặc sau khi reset.")
                }
                is Screen.Connect -> screen = s.copy(error = "Đã đọc mã thiết lập. Giờ cho điện thoại vào cùng mạng với Pi, hoặc quét mã Wi-Fi bên phải tem.")
                else -> {}
            }
            return
        }
        LabelQr.parseWifi(text)?.let { qr ->
            prefs.backupWifi = qr.ssid to qr.password
            joinBackup(qr.ssid, qr.password)
            return
        }
        notice = "Mã QR này không phải mã trên tem của Pi."
        val s = screen
        if (s is Screen.Connect) screen = s.copy(error = "Mã QR này không phải mã trên tem của Pi.")
    }

    fun joinBackup(ssid: String, password: String?) {
        if (!wifi.supported) {
            showConnect("Điện thoại này cần vào Wi-Fi $ssid bằng tay trong Cài đặt, rồi bấm Thử lại.")
            return
        }
        pollJob?.cancel()
        screen = Screen.Loading
        wifi.join(ssid, password) { ok ->
            viewModelScope.launch {
                if (!ok) {
                    showConnect("Không vào được Wi-Fi $ssid. Kiểm tra Pi đang phát mạng này (chế độ Độc lập, hoặc mất Wi-Fi nhà quá 2 phút).")
                    return@launch
                }
                val status = probe(BACKUP_URL)
                if (status == null) showConnect("Đã vào $ssid nhưng chưa thấy Pi trả lời. Đợi vài giây rồi bấm Thử lại.")
                else use(BACKUP_URL, status)
            }
        }
    }

    private fun showConnect(error: String?) {
        screen = Screen.Connect(found.toList(), error)
        discovery.start { url ->
            viewModelScope.launch {
                if (url !in found) {
                    found.add(url)
                    val s = screen
                    if (s is Screen.Connect) screen = s.copy(found = found.toList())
                }
            }
        }
    }

    fun changeServer() {
        pollJob?.cancel()
        prefs.baseUrl = null
        api = null
        showConnect(null)
    }

    private suspend fun use(url: String, status: JSONObject) {
        discovery.stop()
        rememberServer(url, status)
        api = Api(url) { prefs.token }
        if (prefs.token != null) {
            try {
                enterMain()
                return
            } catch (e: ApiException) {
                if (e.status != 401 && e.status != 403) {
                    showConnect(explain(e))
                    return
                }
                prefs.token = null
            }
        }
        val claimed = status.optBoolean("claimed", true)
        screen = Screen.Auth(if (claimed) AuthMode.LOGIN else AuthMode.SETUP)
    }

    private fun rememberServer(url: String, status: JSONObject) {
        val public = status.optString("public_url").takeIf { it.startsWith("https://") }
        if (public != null) prefs.publicUrl = public
        if (url != public && url != prefs.publicUrl) prefs.baseUrl = url   // chi nho dia chi trong mang nha
    }

    // ------------------------------------------------------------ tai khoan
    fun switchAuth(mode: AuthMode) {
        screen = Screen.Auth(mode)
    }

    fun submitAuth(mode: AuthMode, code: String, username: String, displayName: String, password: String) {
        val a = api ?: return
        viewModelScope.launch {
            busy = true
            try {
                val body = JSONObject()
                    .put("username", username.trim().lowercase())
                    .put("password", password)
                if (mode != AuthMode.LOGIN && displayName.isNotBlank()) body.put("display_name", displayName.trim())
                if (mode == AuthMode.REGISTER) {
                    a.call("POST", "/auth/register", body)
                    screen = Screen.Auth(
                        AuthMode.LOGIN,
                        "Đã gửi yêu cầu cho ${username.trim().lowercase()}. Khi quản trị viên duyệt, đăng nhập bằng tên và mật khẩu vừa tạo.",
                        ok = true,
                    )
                    return@launch
                }
                body.put("device", deviceName())
                if (mode == AuthMode.SETUP) body.put("code", code.trim())
                val r = a.call("POST", if (mode == AuthMode.SETUP) "/setup" else "/auth/login", body)
                prefs.token = r.getString("token")
                enterMain()
            } catch (e: ApiException) {
                val next = if (e.code == "ALREADY_CLAIMED") AuthMode.LOGIN else mode
                screen = Screen.Auth(next, explain(e))
            } finally {
                busy = false
            }
        }
    }

    private suspend fun enterMain() {
        val a = api ?: return
        val j = a.call("GET", "/auth/me")
        me = Me(
            username = j.optString("username"),
            displayName = j.optString("display_name").ifBlank { j.optString("username") },
            role = j.optString("role"),
        )
        refresh()
        loadExtras(series = true)
        if (me?.role == "admin") loadMembers()
        screen = Screen.Main
        startPolling()
    }

    fun signOut() {
        val a = api
        viewModelScope.launch {
            if (a != null) runCatching { a.call("POST", "/auth/logout") }
            signedOut(null)
        }
    }

    private fun signedOut(message: String?) {
        pollJob?.cancel()
        prefs.token = null
        me = null
        room = null
        screen = Screen.Auth(AuthMode.LOGIN, message)
    }

    // ------------------------------------------------------------ phong va dieu khien
    private fun startPolling() {
        pollJob?.cancel()
        pollJob = viewModelScope.launch {
            var misses = 0
            var ticks = 0
            while (isActive) {
                delay(POLL_MS)
                try {
                    refresh()
                    misses = 0
                    ticks++
                    if (me?.role == "admin" && ticks % 5 == 0) loadMembers()
                    if (ticks % 5 == 0) loadExtras(series = ticks % 20 == 0)
                } catch (e: ApiException) {
                    if (e.status == 401 || e.code == "ACCOUNT_PENDING") {
                        signedOut(explain(e))
                        return@launch
                    }
                    linkError = explain(e)
                    // Dien thoai doi mang (Wi-Fi nha <-> 4G <-> SmartAC-Backup): tim lai Pi o dia chi khac.
                    // Cung mot Pi nen phien dang nhap van dung, khong phai dang nhap lai.
                    if (e.code == "NETWORK" && ++misses >= 2) {
                        findServer()?.let { (url, status) ->
                            rememberServer(url, status)
                            if (url != api?.baseUrl) api = Api(url) { prefs.token }
                        }
                        misses = 0
                    }
                }
            }
        }
    }

    private suspend fun refresh() {
        val a = api ?: return
        val rooms = a.call("GET", "/rooms").getJSONArray("rooms")
        if (rooms.length() == 0) {
            noRooms = true
            room = null
        } else {
            noRooms = false
            room = RoomView.from(a.call("GET", "/rooms/" + rooms.getJSONObject(0).getString("room")))
        }
        linkError = null
    }

    fun command(body: JSONObject) {
        val a = api ?: return
        val id = room?.id ?: return
        viewModelScope.launch {
            busy = true
            notice = null
            try {
                a.call("POST", "/rooms/$id/commands", body)
                refresh()
            } catch (e: ApiException) {
                if (e.extra?.optBoolean("can_confirm") == true) pendingConfirm = body
                else notice = explain(e)
            } finally {
                busy = false
            }
        }
    }

    fun confirmEarlyStart() {
        val body = pendingConfirm ?: return
        pendingConfirm = null
        command(JSONObject(body.toString()).put("confirm", true))
    }

    fun vote(vote: String) {
        val a = api ?: return
        val id = room?.id ?: return
        viewModelScope.launch {
            busy = true
            notice = try {
                a.call("POST", "/rooms/$id/comfort", JSONObject().put("vote", vote))
                "Đã ghi cảm nhận của bạn. Cảm ơn!"
            } catch (e: ApiException) {
                explain(e)
            } finally {
                busy = false
            }
        }
    }

    // ------------------------------------------------------------ goi y, bieu do, che do mang
    private suspend fun loadExtras(series: Boolean) {
        val a = api ?: return
        val id = room?.id ?: return
        runCatching { suggestion = toSuggestion(a.call("GET", "/rooms/$id/suggestion")) }
        runCatching {
            val n = a.call("GET", "/system/network")
            val st = n.optJSONObject("status")
            net = NetInfo(n.optString("mode"), st?.optBoolean("running") ?: false, st?.optString("state") == "ap")
        }
        if (series) loadSeries(this.series?.hours ?: 24)
    }

    fun loadSeries(hours: Int) {
        val a = api ?: return
        val id = room?.id ?: return
        viewModelScope.launch {
            runCatching {
                val items = a.call("GET", "/rooms/$id/telemetry/series?hours=$hours&points=120").getJSONArray("items")
                val rows = (0 until items.length()).map { items.getJSONObject(it) }
                series = Series(
                    hours,
                    rows.map { it.getDouble("ts") },
                    rows.map { it.getDouble("temp") },
                    rows.map { it.getDouble("hum") },
                )
            }
        }
    }

    private fun toSuggestion(s: JSONObject): Suggestion {
        val t = s.optJSONObject("target")
        val tt = t?.optInt("temp")
        val room = if (s.isNull("room_temp")) "" else "Phòng ${"%.1f".format(s.optDouble("room_temp"))} °C. "
        val band = s.optJSONArray("comfort_band")
        val hi = band?.optDouble(1)
        val reason = s.optString("reason")
        val text = when (reason) {
            "TOO_WARM" -> "${room}Có vẻ hơi nóng với bạn. Nên bật điều hòa ở $tt °C."
            "WARMER_SETPOINT" -> "Có thể tăng lên $tt °C mà vẫn dễ chịu, đỡ tốn điện."
            "COOLER_SETPOINT" -> "${room}Nên giảm nhiệt độ đặt xuống $tt °C."
            "ROOM_EMPTY_LONG" -> "Phòng đã trống hơn 15 phút. Nên tắt điều hòa."
            "SLIGHTLY_WARM" -> "${room}Ấm hơn vùng dễ chịu của bạn (trên ${"%.1f".format(hi ?: 0.0)} °C) nhưng chưa nóng hẳn. Nếu thấy nóng, có thể bật ở $tt °C."
            "COMFORTABLE" -> "${room}Phòng đang dễ chịu với bạn, chưa cần bật điều hòa."
            "TOO_COOL_AC_OFF" -> "${room}Phòng hơi mát với bạn."
            "SETPOINT_OK" -> "Nhiệt độ đặt hiện tại đang hợp với bạn."
            "ROOM_EMPTY" -> "Phòng đang trống, chưa có gợi ý."
            "MODE_NOT_SUPPORTED" -> "Gợi ý chỉ áp dụng cho chế độ mát, khô hoặc tự động."
            else -> "Chưa có số đo mới nên chưa có gợi ý."
        }
        val model = s.optJSONObject("model")
        val votes = model?.optInt("votes") ?: 0
        val why = (if (band != null) "Vùng dễ chịu của bạn: ${"%.1f".format(band.optDouble(0))}–${"%.1f".format(band.optDouble(1))} °C. " else "") +
            if (model?.optBoolean("personal") == true) "Học từ $votes phiếu của bạn và dữ liệu khảo sát ASHRAE."
            else "Đang dùng mô hình chung (ASHRAE); sẽ hợp với bạn hơn khi có từ 10 phiếu (hiện có $votes)."
        val offered = s.optString("action") != "none" || reason == "SLIGHTLY_WARM"
        return Suggestion(text, why, t, t != null && offered && !s.optBoolean("auto"))
    }

    fun applySuggestion() {
        suggestion?.target?.let { command(JSONObject(it.toString())) }
    }

    /** Dieu hoa khong lam theo: phat lai trang thai du kien (ADR 0005). */
    fun resend() {
        val a = api ?: return
        val id = room?.id ?: return
        viewModelScope.launch {
            busy = true
            notice = try {
                a.call("POST", "/rooms/$id/commands/resend")
                "Đã gửi lại lệnh."
            } catch (e: ApiException) {
                if (e.code == "NO_STATE") "Chưa có lệnh nào để gửi lại." else explain(e)
            } finally {
                busy = false
            }
        }
    }

    /** Bao trang thai that cua dieu hoa, khong phat IR. */
    fun syncPower(power: String) {
        val a = api ?: return
        val id = room?.id ?: return
        viewModelScope.launch {
            busy = true
            notice = try {
                a.call("PUT", "/rooms/$id/ac-state", JSONObject().put("power", power))
                refresh()
                "Đã cập nhật: điều hòa thực tế đang ${if (power == "on") "bật" else "tắt"}."
            } catch (e: ApiException) {
                explain(e)
            } finally {
                busy = false
            }
        }
    }

    fun setNetwork(mode: String) {
        val a = api ?: return
        viewModelScope.launch {
            busy = true
            try {
                a.call("PUT", "/system/network", JSONObject().put("mode", mode))
                notice = when (mode) {
                    "standalone" -> "Pi sẽ phát Wi-Fi SmartAC-Backup trong khoảng 15 giây."
                    "home" -> "Pi sẽ chỉ dùng Wi-Fi nhà."
                    else -> "Pi sẽ dùng Wi-Fi nhà, mất Wi-Fi nhà thì tự phát mạng riêng."
                }
                // Pi sap roi Wi-Fi nha: app tu vao mang cua Pi neu da quet ma Wi-Fi tren tem
                val w = prefs.backupWifi
                if (mode == "standalone" && w != null && net?.onBackup != true) {
                    viewModelScope.launch {
                        delay(20_000)
                        joinBackup(w.first, w.second)
                    }
                }
            } catch (e: ApiException) {
                notice = explain(e)
            } finally {
                busy = false
            }
        }
    }

    // ------------------------------------------------------------ thanh vien (quan tri vien)
    private suspend fun loadMembers() {
        val a = api ?: return
        val items = runCatching { a.call("GET", "/users").getJSONArray("items") }.getOrNull() ?: return
        members = (0 until items.length()).map { i ->
            val u = items.getJSONObject(i)
            Member(u.getString("username"), u.optString("display_name").ifBlank { u.getString("username") }, u.getString("role"))
        }
    }

    fun setRole(m: Member, role: String) = memberAction("Đã cập nhật quyền của ${m.username}.") {
        it.call("PUT", "/users/" + Uri.encode(m.username), JSONObject().put("role", role))
    }

    fun removeMember(m: Member) = memberAction("Đã xóa tài khoản ${m.username}.") {
        it.call("DELETE", "/users/" + Uri.encode(m.username))
    }

    private fun memberAction(done: String, run: suspend (Api) -> Unit) {
        val a = api ?: return
        viewModelScope.launch {
            busy = true
            notice = try {
                run(a)
                done
            } catch (e: ApiException) {
                if (e.code == "LAST_ADMIN") "Phải còn ít nhất một quản trị viên." else explain(e)
            } finally {
                busy = false
            }
            loadMembers()
        }
    }

    override fun onCleared() {
        discovery.stop()
        wifi.leave()
    }

    companion object {
        const val BACKUP_URL = "http://10.42.0.1:8000"   // Pi o che do mang du phong (SmartAC-Backup)
        private const val POLL_MS = 3000L

        fun deviceName(): String = "${Build.MANUFACTURER} ${Build.MODEL}, app".take(60)

        /** "192.168.1.20" -> "http://192.168.1.20:8000". Tra ve null neu khong hop le. */
        fun normalizeUrl(input: String): String? {
            val s = input.trim().trimEnd('/')
            if (s.isEmpty() || s.contains(' ')) return null
            if (s.startsWith("http://") || s.startsWith("https://")) return s
            val host = s.substringBefore(':')
            val local = host.endsWith(".local") || host.all { it.isDigit() || it == '.' }
            return when {
                !local -> "https://$s"              // ten mien: qua Cloudflare Tunnel
                s.contains(':') -> "http://$s"
                else -> "http://$s:8000"
            }
        }

        fun shortUrl(url: String?): String = url?.substringAfter("://") ?: ""
    }
}
