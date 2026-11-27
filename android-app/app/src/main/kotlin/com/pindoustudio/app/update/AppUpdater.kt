package com.pindoustudio.app.update

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings
import androidx.core.content.FileProvider
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest

data class UpdateManifest(
    val versionCode: Long,
    val versionName: String,
    val changelog: String,
    val sha256: String,
    val forceUpdate: Boolean,
    val apkMirrors: List<String>,
    val fallbackPageUrl: String
)

data class AppVersionInfo(
    val versionCode: Long,
    val versionName: String
)

/**
 * 免服务器、国内可直连的零成本多镜像自更新引擎：
 * 1) 清单检测（约 1KB JSON）：按「Gitee Raw -> GitCode Raw -> jsDelivr CDN」顺序容灾拉取；
 * 2) 安装包下载：优先走国内免费直链 / GitHub 加速镜像，逐个校验 ZIP 魔数(PK)与 SHA-256，防 HTML 登录拦截与劫持；
 * 3) 若全部直链被网络拦截，引导通过系统浏览器直开免登录分享页（如 123云盘 / 蒲公英 / GitCode Release）一键下载。
 */
object AppUpdater {

    const val GITHUB_OWNER = "LEFTX1"
    const val GITHUB_REPO = "pindou-studio"

    // 只需推送一次到 GitHub 仓库，国内用户自动依次走多路加速代理 / CDN / 直连拉取更新清单
    val DEFAULT_MANIFEST_URLS = listOf(
        "https://ghfast.top/https://raw.githubusercontent.com/$GITHUB_OWNER/$GITHUB_REPO/main/update/version.json",
        "https://gh-proxy.com/https://raw.githubusercontent.com/$GITHUB_OWNER/$GITHUB_REPO/main/update/version.json",
        "https://fastly.jsdelivr.net/gh/$GITHUB_OWNER/$GITHUB_REPO@main/update/version.json",
        "https://cdn.jsdelivr.net/gh/$GITHUB_OWNER/$GITHUB_REPO@main/update/version.json",
        "https://raw.githubusercontent.com/$GITHUB_OWNER/$GITHUB_REPO/main/update/version.json"
    )

    fun isManifestConfigured(manifestUrls: List<String> = DEFAULT_MANIFEST_URLS): Boolean =
        manifestUrls.any { it.isNotBlank() && !it.contains("YOUR_REPO_OWNER") }

    fun getCurrentVersion(context: Context): AppVersionInfo {
        return runCatching {
            val info = context.packageManager.getPackageInfo(context.packageName, 0)
            val code = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                info.longVersionCode
            } else {
                @Suppress("DEPRECATION")
                info.versionCode.toLong()
            }
            AppVersionInfo(code, info.versionName ?: "1.0")
        }.getOrElse { AppVersionInfo(1L, "1.0") }
    }

    fun fetchManifest(manifestUrls: List<String> = DEFAULT_MANIFEST_URLS): Result<UpdateManifest> {
        var lastError: Throwable? = null
        for (rawUrl in manifestUrls) {
            if (rawUrl.isBlank() || rawUrl.contains("YOUR_REPO_OWNER")) continue
            val attempt = runCatching {
                val conn = openConnectionWithRedirects(rawUrl, connectTimeoutMs = 6000, readTimeoutMs = 8000)
                try {
                    val code = conn.responseCode
                    if (code !in 200..299) error("HTTP $code")
                    val text = conn.inputStream.bufferedReader(Charsets.UTF_8).use { it.readText() }
                    val obj = JSONObject(text)
                    val mirrorsArr = obj.optJSONArray("apkMirrors")
                    val mirrors = buildList {
                        if (mirrorsArr != null) {
                            for (i in 0 until mirrorsArr.length()) {
                                val u = mirrorsArr.optString(i).trim()
                                if (u.isNotEmpty() && !u.contains("YOUR_REPO_OWNER")) add(u)
                            }
                        }
                        val single = obj.optString("downloadUrl").trim()
                        if (single.isNotEmpty() && single !in this && !single.contains("YOUR_REPO_OWNER")) add(single)
                    }
                    UpdateManifest(
                        versionCode = obj.getLong("versionCode"),
                        versionName = obj.optString("versionName", "新版本"),
                        changelog = obj.optString("changelog", "优化功能体验并修复已知问题。"),
                        sha256 = obj.optString("sha256", "").trim().lowercase(),
                        forceUpdate = obj.optBoolean("forceUpdate", false),
                        apkMirrors = mirrors,
                        fallbackPageUrl = obj.optString("fallbackPageUrl", "").trim()
                    )
                } finally {
                    conn.disconnect()
                }
            }
            if (attempt.isSuccess) return attempt
            lastError = attempt.exceptionOrNull()
        }
        return Result.failure(lastError ?: IllegalStateException("未配置或无法访问云端更新清单"))
    }

    fun downloadAndVerifyApk(
        context: Context,
        manifest: UpdateManifest,
        onProgress: (Float) -> Unit
    ): Result<File> {
        if (manifest.apkMirrors.isEmpty()) {
            return Result.failure(IllegalStateException("未提供可用 APK 直链，请使用备用下载页"))
        }
        val updateDir = File(context.cacheDir, "updates").apply { mkdirs() }
        val targetFile = File(updateDir, "pindou_v${manifest.versionName}.apk")
        val tmpFile = File(updateDir, "pindou_download.tmp")
        var lastError: Throwable? = null

        for (mirrorUrl in manifest.apkMirrors) {
            val attempt = runCatching {
                if (tmpFile.exists()) tmpFile.delete()
                val conn = openConnectionWithRedirects(mirrorUrl, connectTimeoutMs = 9000, readTimeoutMs = 30000)
                try {
                    val code = conn.responseCode
                    if (code !in 200..299) error("HTTP $code")
                    val contentType = (conn.contentType ?: "").lowercase()
                    if ("text/html" in contentType) {
                        error("镜像返回网页拦截($contentType)，已切换下一镜像")
                    }
                    val totalBytes = conn.contentLengthLong
                    val digest = MessageDigest.getInstance("SHA-256")
                    val buf = ByteArray(16 * 1024)
                    var readTotal = 0L
                    var verifiedHeader = false

                    conn.inputStream.use { input ->
                        FileOutputStream(tmpFile).use { output ->
                            while (true) {
                                val n = input.read(buf)
                                if (n <= 0) break
                                if (!verifiedHeader) {
                                    if (n < 4 || buf[0] != 0x50.toByte() || buf[1] != 0x4B.toByte() || buf[2] != 0x03.toByte() || buf[3] != 0x04.toByte()) {
                                        error("非有效 APK 安装包文件头（可能触发防盗链跳转）")
                                    }
                                    verifiedHeader = true
                                }
                                output.write(buf, 0, n)
                                digest.update(buf, 0, n)
                                readTotal += n
                                if (totalBytes > 0) {
                                    onProgress((readTotal.toFloat() / totalBytes).coerceIn(0f, 0.99f))
                                }
                            }
                            output.flush()
                        }
                    }

                    if (!verifiedHeader || readTotal < 1024) error("安装包体积异常")
                    val actualSha = digest.digest().joinToString("") { "%02x".format(it) }
                    if (manifest.sha256.isNotEmpty() && actualSha != manifest.sha256) {
                        error("SHA-256 校验失败，已丢弃文件")
                    }
                    if (targetFile.exists()) targetFile.delete()
                    if (!tmpFile.renameTo(targetFile)) {
                        tmpFile.copyTo(targetFile, overwrite = true)
                        tmpFile.delete()
                    }
                    onProgress(1f)
                    targetFile
                } finally {
                    conn.disconnect()
                }
            }
            if (attempt.isSuccess) return attempt
            if (tmpFile.exists()) tmpFile.delete()
            lastError = attempt.exceptionOrNull()
        }
        return Result.failure(lastError ?: IllegalStateException("所有国内镜像下载均失败，请点下方备用下载页"))
    }

    fun installApk(context: Context, apkFile: File): Boolean {
        if (!context.packageManager.canRequestPackageInstalls()) {
            val permIntent = Intent(
                Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                Uri.parse("package:${context.packageName}")
            ).apply {
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            context.startActivity(permIntent)
            return false
        }
        val uri = FileProvider.getUriForFile(context, "${context.packageName}.fileprovider", apkFile)
        val intent = Intent(Intent.ACTION_VIEW).apply {
            setDataAndType(uri, "application/vnd.android.package-archive")
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
        context.startActivity(intent)
        return true
    }

    fun openFallbackDownloadPage(context: Context, url: String) {
        if (url.isBlank()) return
        val intent = Intent(Intent.ACTION_VIEW, Uri.parse(url)).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        context.startActivity(intent)
    }

    private fun openConnectionWithRedirects(
        rawUrl: String,
        connectTimeoutMs: Int,
        readTimeoutMs: Int,
        maxRedirects: Int = 5
    ): HttpURLConnection {
        var current = rawUrl
        repeat(maxRedirects + 1) {
            val conn = (URL(current).openConnection() as HttpURLConnection).apply {
                connectTimeout = connectTimeoutMs
                readTimeout = readTimeoutMs
                instanceFollowRedirects = false
                setRequestProperty("User-Agent", "PindouStudio-Updater/1.0 (Android)")
            }
            val code = conn.responseCode
            if (code in 300..399) {
                val loc = conn.getHeaderField("Location")
                conn.disconnect()
                if (loc.isNullOrBlank()) return conn
                current = URL(URL(current), loc).toString()
            } else {
                return conn
            }
        }
        error("重定向次数过多")
    }
}
