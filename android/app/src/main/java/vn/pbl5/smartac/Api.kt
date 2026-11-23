package vn.pbl5.smartac

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.TimeUnit

/** Loi tu gateway: `{"error": {"code", "message", ...}}`. status = 0 khi khong toi duoc Pi. */
class ApiException(
    val status: Int,
    val code: String,
    override val message: String,
    val extra: JSONObject? = null,
) : Exception(message)

/** Goi REST API cua gateway (docs/API.md). Token phien dang nhap lay moi lan goi. */
class Api(val baseUrl: String, private val quick: Boolean = false, private val token: () -> String?) {

    suspend fun call(method: String, path: String, body: JSONObject? = null): JSONObject =
        withContext(Dispatchers.IO) {
            val requestBody = when {
                body != null -> body.toString().toRequestBody(JSON)
                method == "POST" || method == "PUT" -> "".toRequestBody(JSON)
                else -> null
            }
            val builder = Request.Builder()
                .url("$baseUrl/api/v1$path")
                .method(method, requestBody)
            token()?.let { builder.header("Authorization", "Bearer $it") }
            try {
                (if (quick) quickHttp else http).newCall(builder.build()).execute().use { resp ->
                    val text = resp.body?.string().orEmpty()
                    val json = if (text.isBlank()) JSONObject()
                    else runCatching { JSONObject(text) }.getOrElse { JSONObject() }
                    if (!resp.isSuccessful) {
                        val err = json.optJSONObject("error")
                        throw ApiException(
                            resp.code,
                            err?.optString("code")?.ifBlank { null } ?: "HTTP_${resp.code}",
                            err?.optString("message")?.ifBlank { null } ?: "Lỗi ${resp.code}",
                            err,
                        )
                    }
                    json
                }
            } catch (e: IOException) {
                throw ApiException(0, "NETWORK", "Không kết nối được tới Raspberry Pi")
            }
        }

    companion object {
        private val JSON = "application/json".toMediaType()
        private val http: OkHttpClient = OkHttpClient.Builder()
            .connectTimeout(4, TimeUnit.SECONDS)
            .readTimeout(12, TimeUnit.SECONDS)   // lenh cho node tra loi toi 5 s
            .build()
        /** Do xem Pi co o dia chi nay khong: bo cuoc nhanh khi dien thoai dang o mang khac. */
        private val quickHttp: OkHttpClient = http.newBuilder()
            .connectTimeout(2, TimeUnit.SECONDS)
            .readTimeout(4, TimeUnit.SECONDS)
            .build()
    }
}

/** Cau thong bao tieng Viet cho ma loi (giong dashboard). */
fun explain(e: ApiException): String = when (e.code) {
    "NETWORK" -> "Không kết nối được tới Raspberry Pi. Kiểm tra mạng của điện thoại."
    "LOGIN_FAILED" -> "Sai tên đăng nhập hoặc mật khẩu."
    "LOGIN_LOCKED" -> "Sai mật khẩu quá nhiều lần. Thử lại sau ít phút."
    "ACCOUNT_PENDING" -> "Tài khoản đang chờ quản trị viên duyệt."
    "SESSION_INVALID", "UNAUTHORIZED" -> "Phiên đăng nhập đã hết. Đăng nhập lại."
    "USERNAME_TAKEN" -> "Tên đăng nhập này đã có người dùng."
    "BAD_USERNAME" -> "Tên đăng nhập 3–32 ký tự: chữ thường không dấu, số, dấu chấm, gạch dưới, gạch ngang."
    "BAD_PASSWORD", "HTTP_422" -> "Mật khẩu cần 8–128 ký tự và không trùng tên đăng nhập."
    "SETUP_CODE_INVALID" -> "Mã thiết lập không đúng. Xem lại tem dán trên Raspberry Pi."
    "SETUP_TOO_MANY" -> "Nhập sai mã quá nhiều lần. Chờ một phút."
    "SETUP_LOCAL_ONLY" -> "Thiết lập lần đầu chỉ làm được khi điện thoại ở cùng mạng Wi-Fi với Pi (hoặc mạng SmartAC-Backup)."
    "ALREADY_CLAIMED" -> "Raspberry Pi này đã có quản trị viên. Hãy đăng nhập."
    "NOT_CLAIMED" -> "Raspberry Pi chưa được thiết lập. Dùng mã trên tem để tạo quản trị viên."
    "FORBIDDEN" -> "Tài khoản của bạn không có quyền làm việc này."
    "NODE_OFFLINE" -> "Node trong phòng đang mất kết nối."
    "NODE_TIMEOUT" -> "Node không trả lời; chưa chắc điều hòa đã nhận lệnh."
    "COMPRESSOR_MIN_OFF" -> "Máy nén vừa tắt, cần nghỉ thêm một lúc."
    "RATE_LIMIT" -> "Bấm hơi nhanh, đợi vài giây."
    "MANUAL_HOLD" -> "Đang tạm dừng chế độ tự động."
    "TELEMETRY_STALE" -> "Chưa có số đo mới từ phòng."
    "VOTE_TOO_FAST" -> "Bạn vừa gửi phiếu rồi."
    else -> e.message
}
