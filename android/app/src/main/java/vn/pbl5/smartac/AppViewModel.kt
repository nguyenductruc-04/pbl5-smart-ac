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

enum class AuthMode { WELCOME, LOGIN, REGISTER, SETUP }

/** Duong dien thoai dang dung de toi Pi. */
enum class Link { HOME, BACKUP, INTERNET }

data class Activity(val ts: Double, val title: String, val detail: String, val kind: String)

sealed interface Screen {
    data object Loading : Screen
    data class Connect(val found: List<String>, val error: String?) : Screen
    data class Auth(val mode: AuthMode, val message: String? = null, val ok: Boolean = false) : Screen
    data object Main : Screen
}

data class Suggestion(
    val text: String,
    val why: String,
    val target: JSONObject?,
    val canApply: Boolean,
    val band: Pair<Double, Double>?,
    val roomTemp: Double?,
    val warm: Boolean,
)

data class NetInfo(val mode: String, val running: Boolean, val onBackup: Boolean)

data class Series(val hours: Int, val ts: List<Double>, val temp: List<Double>, val hum: List<Double>)

data class IrCandidate(val protocol: String, val ac: Boolean, val count: Int, val model: Int, val note: String)

data class IrInfo(
    val protocol: String?,
    val confirmed: Boolean,
    val confirmedBy: String?,
    val learnActive: Boolean,
    val learnStarted: Boolean,
    val candidates: List<IrCandidate>,
    val brands: Map<String, List<String>>,
)

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
    var ir by mutableStateOf<IrInfo?>(null)
        private set
    /** Vua doi giao thuc: hien buoc thu "Bat thu / Tat thu / Dieu hoa da phan ung". */
    var irTesting by mutableStateOf(false)
        private set

    /** Lenh bi tu choi vi may nen vua tat, cho nguoi dung xac nhan "Van bat". */
    var pendingConfirm by mutableStateOf<JSONObject?>(null)

    val serverUrl: String? get() = api?.baseUrl
    /** Dia chi Internet (Cloudflare Tunnel) Pi bao ve, neu da bat truy cap tu xa. */
    val publicUrl: String? get() = prefs.publicUrl
    val link: Link
        get() = when {
            api?.baseUrl == BACKUP_URL -> Link.BACKUP
            api?.baseUrl?.startsWith("https://") == true -> Link.INTERNET
            else -> Link.HOME
        }
    var activity by mutableStateOf<List<Activity>>(emptyList())
        private set
    var notifyEnabled by mutableStateOf(true)
        private set

    init {
        notifyEnabled = prefs.notify
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
        screen = Screen.Auth(if (claimed) AuthMode.WELCOME else AuthMode.SETUP)
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
        loadActivity()
        if (me?.role == "admin") {
            loadMembers()
            loadIr()
        }
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
        screen = Screen.Auth(if (message == null) AuthMode.WELCOME else AuthMode.LOGIN, message)
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
                    if (me?.role == "admin" && (ticks % 10 == 0 || ir?.learnActive == true)) loadIr()
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
        val roomT = if (s.isNull("room_temp")) null else s.optDouble("room_temp")
        val arr = s.optJSONArray("comfort_band")
        val band = if (arr != null && arr.length() == 2) arr.optDouble(0) to arr.optDouble(1) else null
        val reason = s.optString("reason")
        val text = when (reason) {
            "TOO_WARM" -> "Phòng đang nóng với bạn. Bật điều hòa ở $tt°?"
            "WARMER_SETPOINT" -> "Có thể tăng lên $tt° mà vẫn dễ chịu, đỡ tốn điện."
            "COOLER_SETPOINT" -> "Phòng đang ấm hơn mức bạn thường thấy dễ chịu. Giảm xuống $tt°?"
            "ROOM_EMPTY_LONG" -> "Phòng đã trống hơn 15 phút. Tắt điều hòa?"
            "SLIGHTLY_WARM" -> "Ấm hơn vùng dễ chịu của bạn một chút. Nếu thấy nóng, bật ở $tt°."
            "COMFORTABLE" -> "Phòng đang dễ chịu với bạn, chưa cần bật điều hòa."
            "TOO_COOL_AC_OFF" -> "Phòng hơi mát với bạn."
            "SETPOINT_OK" -> "Nhiệt độ đặt hiện tại đang hợp với bạn."
            "ROOM_EMPTY" -> "Phòng đang trống."
            "MODE_NOT_SUPPORTED" -> "Gợi ý chỉ áp dụng cho chế độ mát, khô hoặc tự động."
            else -> "Chưa có số đo mới nên chưa có gợi ý."
        }
        val model = s.optJSONObject("model")
        val votes = model?.optInt("votes") ?: 0
        val why = if (model?.optBoolean("personal") == true) "Học từ $votes phiếu cảm nhận của bạn và dữ liệu khảo sát ASHRAE."
        else "Đang dùng mô hình chung (ASHRAE); sẽ hợp với bạn hơn khi có từ 10 phiếu (hiện có $votes)."
        val offered = s.optString("action") != "none" || reason == "SLIGHTLY_WARM"
        val warm = reason in setOf("TOO_WARM", "COOLER_SETPOINT", "SLIGHTLY_WARM")
        return Suggestion(text, why, t, t != null && offered && !s.optBoolean("auto"), band, roomT, warm)
    }

    /** Nhat ky: lenh qua Safety Layer va nhung lan bam remote goc. */
    fun loadActivity() {
        val a = api ?: return
        val id = room?.id ?: return
        viewModelScope.launch {
            runCatching {
                val dec = a.call("GET", "/rooms/$id/decisions?limit=30").getJSONArray("items")
                val ir = a.call("GET", "/rooms/$id/ir-events?limit=10").getJSONArray("items")
                val out = mutableListOf<Activity>()
                for (i in 0 until dec.length()) {
                    val d = dec.getJSONObject(i)
                    val who = SOURCE_VI[d.optString("source")] ?: d.optString("source")
                    val what = describeState(d.optJSONObject("requested"))
                    val (title, detail, kind) = when (d.optString("verdict")) {
                        "sync" -> Triple("Báo điều hòa thực tế đang ${if (d.optJSONObject("requested")?.optString("power") == "on") "bật" else "tắt"}", who, "info")
                        "allow" -> Triple(what, who, "ac")
                        "skip" -> Triple(what, "$who, điều hòa đã ở trạng thái này", "info")
                        else -> Triple(what, "$who, bị chặn: ${explain(ApiException(0, d.optString("code"), d.optString("code")))}", "warn")
                    }
                    out.add(Activity(d.optDouble("ts"), title, detail, kind))
                }
                for (i in 0 until ir.length()) {
                    val e = ir.getJSONObject(i)
                    out.add(Activity(e.optDouble("ts"), describeState(e), "Bấm remote, node nghe được", "ac"))
                }
                activity = out.sortedByDescending { it.ts }.take(25)
            }
        }
    }

    fun changePassword(old: String, new: String, done: (String?) -> Unit) {
        val a = api ?: return
        viewModelScope.launch {
            busy = true
            val err = try {
                a.call("PUT", "/auth/password", JSONObject().put("old_password", old).put("new_password", new))
                null
            } catch (e: ApiException) {
                if (e.code == "WRONG_PASSWORD") "Mật khẩu hiện tại không đúng." else explain(e)
            } finally {
                busy = false
            }
            done(err)
        }
    }

    fun setNotify(on: Boolean) {
        notifyEnabled = on
        prefs.notify = on
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

    // ------------------------------------------------------------ giao thuc IR (v0.11.0, ADR 0009)
    private suspend fun loadIr() {
        val a = api ?: return
        val id = room?.id ?: return
        runCatching { ir = toIr(a.call("GET", "/rooms/$id/ir")) }
    }

    private fun toIr(j: JSONObject): IrInfo {
        val learn = j.optJSONObject("learn")
        val cands = j.optJSONArray("candidates")
        val list = (0 until (cands?.length() ?: 0)).map { i ->
            val c = cands!!.getJSONObject(i)
            val last = c.optJSONObject("last")
            val ac = c.optBoolean("ac", true)
            val count = c.optInt("count")
            val note = if (ac && last != null) {
                val parts = mutableListOf(if (last.optString("power") == "on") "bật" else "tắt")
                last.optString("mode").takeIf { it.isNotBlank() && it != "null" }?.let { parts.add(MODE_VI[it] ?: it) }
                if (!last.isNull("temp")) parts.add("${last.optInt("temp")} °C")
                "Remote vừa gửi: ${parts.joinToString(", ")} ($count lần). Khớp màn hình remote thì dùng giao thức này."
            } else {
                "${last?.optInt("bits") ?: "?"} bit, $count lần: node nghe thấy nhưng không phải giao thức điều hòa đã biết."
            }
            IrCandidate(c.getString("protocol"), ac, count, if (c.isNull("model")) -1 else c.optInt("model", -1), note)
        }
        val b = j.optJSONObject("brands")
        val brands = linkedMapOf<String, List<String>>()
        b?.keys()?.forEach { k ->
            val arr = b.getJSONArray(k)
            brands[k] = (0 until arr.length()).map { arr.getString(it) }
        }
        return IrInfo(
            protocol = j.optString("protocol").takeIf { !j.isNull("protocol") && it.isNotBlank() },
            confirmed = j.optBoolean("confirmed"),
            confirmedBy = j.optString("confirmed_by").takeIf { !j.isNull("confirmed_by") && it.isNotBlank() },
            learnActive = learn?.optBoolean("active") ?: false,
            learnStarted = learn != null && !learn.isNull("started"),
            candidates = list,
            brands = brands,
        )
    }

    private fun irAction(done: String?, run: suspend (Api, String) -> JSONObject) {
        val a = api ?: return
        val id = room?.id ?: return
        viewModelScope.launch {
            busy = true
            try {
                ir = toIr(run(a, id))
                if (done != null) notice = done
            } catch (e: ApiException) {
                notice = when (e.code) {
                    "PROTOCOL_NOT_SUPPORTED" -> "Node không hỗ trợ giao thức này."
                    "NODE_TIMEOUT" -> "Node không trả lời. Nạp firmware 0.11.0 cho node rồi thử lại."
                    else -> explain(e)
                }
            } finally {
                busy = false
            }
        }
    }

    fun toggleLearn() {
        val active = ir?.learnActive == true
        irAction(if (active) "Đã dừng nhận diện." else null) { a, id ->
            if (active) a.call("DELETE", "/rooms/$id/ir/learn")
            else a.call("POST", "/rooms/$id/ir/learn", JSONObject().put("seconds", 60))
        }
    }

    fun useProtocol(protocol: String, model: Int = -1) {
        irAction("Node đã chuyển sang $protocol. Bấm Bật thử và nghe điều hòa có bíp không.") { a, id ->
            val r = a.call("PUT", "/rooms/$id/ir", JSONObject().put("protocol", protocol).put("model", model))
            irTesting = true
            r
        }
    }

    fun testPower(on: Boolean) {
        val a = api ?: return
        val id = room?.id ?: return
        viewModelScope.launch {
            busy = true
            notice = try {
                a.call("POST", "/rooms/$id/commands", JSONObject().put("power", if (on) "on" else "off").put("confirm", true))
                "Đã phát lệnh ${if (on) "bật" else "tắt"}. Điều hòa có bíp không?"
            } catch (e: ApiException) {
                explain(e)
            } finally {
                busy = false
            }
        }
    }

    fun confirmIr(works: Boolean) {
        irTesting = false
        irAction(if (works) "Đã lưu: điều hòa nhận lệnh với giao thức này."
                 else "Thử giao thức khác: nhận diện lại, hoặc chọn theo hãng.") { a, id ->
            a.call("POST", "/rooms/$id/ir/confirm", JSONObject().put("works", works))
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
        private val SOURCE_VI = mapOf("app" to "Từ ứng dụng", "rule" to "Tự động", "ai" to "Gợi ý tự động", "remote" to "Remote")

        fun describeState(j: JSONObject?): String {
            if (j == null) return "Lệnh"
            val parts = mutableListOf<String>()
            when (j.optString("power")) {
                "on" -> parts.add("Bật")
                "off" -> return "Tắt điều hòa"
            }
            j.optString("mode").takeIf { it.isNotBlank() && it != "null" }?.let { parts.add(MODE_VI[it] ?: it) }
            if (!j.isNull("temp") && j.has("temp")) parts.add("${j.optInt("temp")}°")
            return if (parts.isEmpty()) "Đổi cài đặt" else parts.joinToString(", ").replaceFirstChar { it.uppercase() }
        }

        private val MODE_VI = mapOf("cool" to "mát", "dry" to "khô", "fan" to "quạt", "auto" to "tự động", "heat" to "sưởi")
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
