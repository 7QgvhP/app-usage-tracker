package com.appusagetracker.mobile.sync

import android.util.Log
import com.appusagetracker.mobile.data.PendingSession
import org.json.JSONArray
import org.json.JSONObject
import java.io.BufferedReader
import java.net.HttpURLConnection
import java.net.URL

/**
 * PCへ使用区間を送る。
 *
 * 送り先は同一LAN内の自分のPCだけなので、通信ライブラリは足さず
 * 標準の HttpURLConnection と org.json で済ませている。
 */
class SyncClient(
    private val baseUrl: String,
    private val token: String,
    private val deviceName: String,
) {

    companion object {
        private const val TAG = "SyncClient"
        private const val CONNECT_TIMEOUT_MS = 5000
        private const val READ_TIMEOUT_MS = 15000
    }

    /** 送信結果 */
    sealed interface Result {
        /** 受理された（accepted は新規、skipped は取り込み済みで無視された件数） */
        data class Success(val accepted: Int, val skipped: Int) : Result

        /** PCへ届かなかった。次回に持ち越す */
        data class Unreachable(val message: String) : Result

        /** 設定の誤りなど、送り直しても解決しない問題 */
        data class Rejected(val statusCode: Int, val message: String) : Result
    }

    /** 接続確認 */
    fun ping(): Result = request("GET", "/api/sync/info", null)

    /** 使用区間を送る */
    fun send(sessions: List<PendingSession>): Result {
        val body = JSONObject().apply {
            put("device", deviceName)
            put("sessions", JSONArray().apply {
                sessions.forEach { session ->
                    put(JSONObject().apply {
                        put("external_id", session.externalId)
                        put("app_name", session.appName)
                        put("started_at", session.startedAt)
                        put("ended_at", session.endedAt)
                        put("seconds", session.seconds)
                    })
                }
            })
        }
        return request("POST", "/api/sync/usage", body.toString())
    }

    private fun request(method: String, path: String, body: String?): Result {
        val connection = try {
            (URL(baseUrl + path).openConnection() as HttpURLConnection)
        } catch (e: Exception) {
            return Result.Unreachable("接続先の指定が不正です: ${e.message}")
        }

        return try {
            connection.requestMethod = method
            connection.connectTimeout = CONNECT_TIMEOUT_MS
            connection.readTimeout = READ_TIMEOUT_MS
            connection.setRequestProperty("X-Sync-Token", token)

            if (body != null) {
                connection.doOutput = true
                connection.setRequestProperty("Content-Type", "application/json; charset=utf-8")
                connection.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
            }

            val status = connection.responseCode
            val text = readBody(connection, status)

            when {
                status in 200..299 -> parseSuccess(text)
                // 認証や内容の誤りは、同じ内容を送り直しても直らない
                status in 400..499 -> Result.Rejected(status, describe(status, text))
                else -> Result.Unreachable("PC側でエラーが発生しました (HTTP $status)")
            }
        } catch (e: Exception) {
            Log.i(TAG, "PCへ接続できませんでした: ${e.message}")
            Result.Unreachable(e.message ?: "接続できませんでした")
        } finally {
            connection.disconnect()
        }
    }

    private fun readBody(connection: HttpURLConnection, status: Int): String = try {
        val stream = if (status in 200..299) connection.inputStream else connection.errorStream
        stream?.bufferedReader()?.use(BufferedReader::readText).orEmpty()
    } catch (e: Exception) {
        ""
    }

    private fun parseSuccess(text: String): Result = try {
        val json = JSONObject(text)
        Result.Success(json.optInt("accepted", 0), json.optInt("skipped", 0))
    } catch (e: Exception) {
        // 接続確認のように件数を返さない応答もあるため、成功として扱う
        Result.Success(0, 0)
    }

    private fun describe(status: Int, text: String): String {
        val detail = try {
            JSONObject(text).optString("error")
        } catch (e: Exception) {
            ""
        }
        return when (status) {
            401 -> "トークンが一致しません。PCの sync_token.txt を確認してください"
            403 -> "PC側で接続が拒否されました"
            503 -> "PC側で同期が無効になっています（config.json の sync.enabled）"
            else -> detail.ifBlank { "送信内容が受け付けられませんでした (HTTP $status)" }
        }
    }
}
