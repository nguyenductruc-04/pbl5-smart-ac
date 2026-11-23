package vn.pbl5.smartac

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import android.net.Uri
import android.net.wifi.WifiNetworkSpecifier
import android.os.Build

/**
 * Vao Wi-Fi du phong cua Pi (SmartAC-Backup) ngay trong app, nhu app cua dieu hoa / camera that.
 *
 * Android hien hop thoai "Ket noi voi SmartAC-Backup?"; sau khi dong y, ca app di qua mang nay
 * (bindProcessToNetwork), ke ca khi mang khong co Internet: Android khong tu nhay sang 4G nua.
 * Can Android 10 tro len; may cu thi nguoi dung vao Wi-Fi bang tay trong Cai dat.
 */
class BackupWifi(context: Context) {
    private val cm = context.getSystemService(ConnectivityManager::class.java)
    private var callback: ConnectivityManager.NetworkCallback? = null

    val supported: Boolean get() = Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q

    /** onResult chay tren luong he thong; goi lai tren luong chinh neu can cap nhat giao dien. */
    fun join(ssid: String, password: String?, onResult: (Boolean) -> Unit) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) {
            onResult(false)
            return
        }
        leave()
        val spec = WifiNetworkSpecifier.Builder().setSsid(ssid).apply {
            if (!password.isNullOrEmpty()) setWpa2Passphrase(password)
        }.build()
        val request = NetworkRequest.Builder()
            .addTransportType(NetworkCapabilities.TRANSPORT_WIFI)
            .removeCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
            .setNetworkSpecifier(spec)
            .build()
        val cb = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) {
                cm.bindProcessToNetwork(network)
                onResult(true)
            }

            override fun onUnavailable() {
                onResult(false)
            }

            override fun onLost(network: Network) {
                cm.bindProcessToNetwork(null)
            }
        }
        callback = cb
        cm.requestNetwork(request, cb)
    }

    fun leave() {
        callback?.let { runCatching { cm.unregisterNetworkCallback(it) } }
        callback = null
        cm.bindProcessToNetwork(null)
    }
}

/** Ma QR tren tem (gateway/setup_label.py). */
object LabelQr {
    data class Setup(val code: String, val deviceId: String?)
    data class Wifi(val ssid: String, val password: String?)

    /** `pbl5://setup?id=<device_id>&code=<code>` */
    fun parseSetup(text: String): Setup? {
        if (!text.startsWith("pbl5://setup")) return null
        val uri = Uri.parse(text)
        val code = uri.getQueryParameter("code")?.takeIf { it.isNotBlank() } ?: return null
        return Setup(code, uri.getQueryParameter("id"))
    }

    /** Chuan QR Wi-Fi: `WIFI:T:WPA;S:<ssid>;P:<mat khau>;;` (ky tu \ ; , : " duoc thoat bang \). */
    fun parseWifi(text: String): Wifi? {
        if (!text.startsWith("WIFI:")) return null
        val fields = mutableMapOf<String, String>()
        var key = StringBuilder()
        var value = StringBuilder()
        var inValue = false
        var i = 5
        while (i < text.length) {
            val c = text[i]
            when {
                c == '\\' && i + 1 < text.length -> {
                    (if (inValue) value else key).append(text[i + 1])
                    i++
                }
                !inValue && c == ':' -> inValue = true
                inValue && c == ';' -> {
                    fields[key.toString()] = value.toString()
                    key = StringBuilder()
                    value = StringBuilder()
                    inValue = false
                }
                else -> (if (inValue) value else key).append(c)
            }
            i++
        }
        val ssid = fields["S"]?.takeIf { it.isNotEmpty() } ?: return null
        return Wifi(ssid, fields["P"]?.takeIf { it.isNotEmpty() })
    }
}
