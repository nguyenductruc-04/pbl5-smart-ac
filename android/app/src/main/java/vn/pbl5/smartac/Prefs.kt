package vn.pbl5.smartac

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

/** Dia chi Pi va phien dang nhap, ma hoa bang khoa trong Android Keystore. */
class Prefs(context: Context) {
    private val sp: SharedPreferences = EncryptedSharedPreferences.create(
        context,
        "pbl5_auth",
        MasterKey.Builder(context).setKeyScheme(MasterKey.KeyScheme.AES256_GCM).build(),
        EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
        EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
    )

    /** Dia chi trong mang nha (http://IP:8000) lan gan nhat ket noi duoc. */
    var baseUrl: String?
        get() = sp.getString("base_url", null)
        set(value) {
            sp.edit().putString("base_url", value).apply()
        }

    /** Dia chi qua Internet (Cloudflare Tunnel), Pi bao trong /setup/status. */
    var publicUrl: String?
        get() = sp.getString("public_url", null)
        set(value) {
            sp.edit().putString("public_url", value).apply()
        }

    /** Wi-Fi du phong doc tu QR tren tem, de app tu vao lai khi Pi chuyen sang che do Doc lap. */
    var backupWifi: Pair<String, String?>?
        get() = sp.getString("backup_ssid", null)?.let { it to sp.getString("backup_pass", null) }
        set(value) {
            sp.edit().putString("backup_ssid", value?.first).putString("backup_pass", value?.second).apply()
        }

    var token: String?
        get() = sp.getString("token", null)
        set(value) {
            sp.edit().putString("token", value).apply()
        }
}
