package vn.pbl5.smartac

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import java.util.concurrent.TimeUnit

/**
 * Kiem tra nen moi 15 phut (khoang toi thieu Android cho phep) va bao khi:
 * - node trong phong mat ket noi (mot lan cho moi lan mat);
 * - co tai khoan moi cho duyet (chi quan tri vien);
 * - phong nong va mo hinh tien nghi goi y bat dieu hoa (toi da 2 gio mot lan).
 *
 * Khong dung Firebase: app tu hoi Pi, nen chay ca khi Pi chi co trong mang nha,
 * nhung tre toi 15 phut va chi khi dien thoai toi duoc Pi (mang nha hoac qua Cloudflare Tunnel).
 */
class WatchWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {

    override suspend fun doWork(): Result {
        val ctx = applicationContext
        val prefs = Prefs(ctx)
        val token = prefs.token ?: return Result.success()
        if (!prefs.notify) return Result.success()
        var api: Api? = null
        for (url in listOfNotNull(prefs.baseUrl, prefs.publicUrl).distinct()) {
            if (runCatching { Api(url, quick = true) { null }.call("GET", "/setup/status") }.isSuccess) {
                api = Api(url) { token }
                break
            }
        }
        val a = api ?: return Result.success()
        val state = ctx.getSharedPreferences("pbl5_watch", Context.MODE_PRIVATE)
        try {
            val me = a.call("GET", "/auth/me")
            val role = me.optString("role")
            val rooms = a.call("GET", "/rooms").getJSONArray("rooms")
            for (i in 0 until rooms.length()) {
                val r = rooms.getJSONObject(i)
                val id = r.getString("room")
                val key = "offline_$id"
                val offline = r.optString("status") != "online"
                if (offline && !state.getBoolean(key, false)) {
                    notify(ctx, 100 + i, "Node $id mất kết nối",
                        "Chưa điều khiển được điều hòa phòng này cho tới khi node kết nối lại.")
                }
                state.edit().putBoolean(key, offline).apply()
            }
            if (role == "admin") {
                val users = a.call("GET", "/users").getJSONArray("items")
                val pending = (0 until users.length()).count { users.getJSONObject(it).optString("role") == "pending" }
                if (pending > state.getInt("pending", 0)) {
                    notify(ctx, 2, "Có $pending tài khoản chờ duyệt", "Mở app, mục Thành viên, để cấp quyền.")
                }
                state.edit().putInt("pending", pending).apply()
            }
            if ((role == "admin" || role == "member") && rooms.length() > 0) {
                val id = rooms.getJSONObject(0).getString("room")
                val s = a.call("GET", "/rooms/$id/suggestion")
                val now = System.currentTimeMillis()
                if (s.optString("reason") == "TOO_WARM" && now - state.getLong("warm_ts", 0) > WARM_EVERY_MS) {
                    val temp = s.optDouble("room_temp")
                    val target = s.optJSONObject("target")?.optInt("temp")
                    notify(ctx, 3, "Phòng %.1f °C, có vẻ nóng".format(temp),
                        "Gợi ý bật điều hòa ở $target °C. Mở app để áp dụng.")
                    state.edit().putLong("warm_ts", now).apply()
                }
            }
        } catch (e: ApiException) {
            // het phien, mat mang...: thu lai o lan sau
        }
        return Result.success()
    }

    companion object {
        private const val CHANNEL = "pbl5_alerts"
        private const val WARM_EVERY_MS = 2 * 3600 * 1000L

        fun schedule(context: Context) {
            val request = PeriodicWorkRequestBuilder<WatchWorker>(15, TimeUnit.MINUTES)
                .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
                .build()
            WorkManager.getInstance(context)
                .enqueueUniquePeriodicWork("pbl5_watch", ExistingPeriodicWorkPolicy.KEEP, request)
        }

        fun notify(context: Context, id: Int, title: String, text: String) {
            if (Build.VERSION.SDK_INT >= 33 &&
                ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) !=
                PackageManager.PERMISSION_GRANTED
            ) return
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                val nm = context.getSystemService(NotificationManager::class.java)
                nm.createNotificationChannel(
                    NotificationChannel(CHANNEL, "Cảnh báo điều hòa", NotificationManager.IMPORTANCE_DEFAULT)
                )
            }
            val open = PendingIntent.getActivity(
                context, 0,
                Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
            )
            val n = NotificationCompat.Builder(context, CHANNEL)
                .setSmallIcon(android.R.drawable.stat_sys_warning)
                .setContentTitle(title)
                .setContentText(text)
                .setStyle(NotificationCompat.BigTextStyle().bigText(text))
                .setContentIntent(open)
                .setAutoCancel(true)
                .build()
            try {
                NotificationManagerCompat.from(context).notify(id, n)
            } catch (e: SecurityException) {
                // nguoi dung tat quyen thong bao
            }
        }
    }
}
