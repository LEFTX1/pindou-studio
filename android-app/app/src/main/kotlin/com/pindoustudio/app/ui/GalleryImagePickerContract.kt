package com.pindoustudio.app.ui

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.provider.MediaStore
import androidx.activity.result.contract.ActivityResultContract

/**
 * 优先直达系统原生相册（而非 DocumentsUI 文件管理器）的图片选择契约：
 * 1) ACTION_PICK + MediaStore.Images.Media.EXTERNAL_CONTENT_URI + image MIME 过滤掉文件管理器包后锁定相册；
 * 2) 若无，尝试纯 ACTION_PICK image MIME 并同样过滤文件管理器；
 * 3) 再兜底 Android 13+ PhotoPicker 或 ACTION_GET_CONTENT。
 */
class GalleryImagePickerContract : ActivityResultContract<Unit, Uri?>() {

    override fun createIntent(context: Context, input: Unit): Intent {
        val pm = context.packageManager

        val mediaStorePick = Intent(Intent.ACTION_PICK).apply {
            setDataAndType(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, "image/*")
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
        choosePreferredGalleryPackage(pm, mediaStorePick)?.let { pkg ->
            mediaStorePick.setPackage(pkg)
            return mediaStorePick
        }
        if (hasNonFileManagerActivity(pm, mediaStorePick)) {
            return mediaStorePick
        }

        val actionPick = Intent(Intent.ACTION_PICK).apply {
            type = "image/*"
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
        choosePreferredGalleryPackage(pm, actionPick)?.let { pkg ->
            actionPick.setPackage(pkg)
            return actionPick
        }
        if (hasNonFileManagerActivity(pm, actionPick)) {
            return actionPick
        }

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            val photoPicker = Intent(MediaStore.ACTION_PICK_IMAGES).apply {
                type = "image/*"
            }
            if (photoPicker.resolveActivity(pm) != null) {
                return photoPicker
            }
        }

        return Intent(Intent.ACTION_GET_CONTENT).apply {
            type = "image/*"
            addCategory(Intent.CATEGORY_OPENABLE)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
    }

    override fun parseResult(resultCode: Int, intent: Intent?): Uri? {
        if (resultCode != Activity.RESULT_OK || intent == null) return null
        return intent.data ?: intent.clipData?.takeIf { it.itemCount > 0 }?.getItemAt(0)?.uri
    }

    companion object {
        private val FILE_MANAGER_TOKENS = listOf(
            "documentsui",
            "filemanager",
            "fileexplorer",
            "myfiles",
            "nbu.files",
            "apps.docs",
            ".files",
            "document"
        )

        private val PREFERRED_GALLERY_PACKAGES = listOf(
            "com.miui.gallery",
            "com.huawei.photos",
            "com.hihonor.photos",
            "com.honor.photos",
            "com.coloros.gallery3d",
            "com.oplus.gallery3d",
            "com.oneplus.gallery",
            "com.vivo.gallery",
            "com.sec.android.gallery3d",
            "com.meizu.media.gallery",
            "com.android.gallery3d",
            "cn.nubia.gallery3d",
            "com.nothing.gallery",
            "com.sonyericsson.album",
            "com.google.android.apps.photos"
        )

        private fun queryCandidates(pm: PackageManager, intent: Intent): List<String> {
            val resolved = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                pm.queryIntentActivities(intent, PackageManager.ResolveInfoFlags.of(PackageManager.MATCH_DEFAULT_ONLY.toLong()))
            } else {
                @Suppress("DEPRECATION")
                pm.queryIntentActivities(intent, PackageManager.MATCH_DEFAULT_ONLY)
            }
            return resolved
                .mapNotNull { it.activityInfo?.packageName }
                .distinct()
                .filter { pkg ->
                    val lower = pkg.lowercase()
                    FILE_MANAGER_TOKENS.none { token -> lower.contains(token) }
                }
        }

        private fun hasNonFileManagerActivity(pm: PackageManager, intent: Intent): Boolean =
            queryCandidates(pm, intent).isNotEmpty()

        private fun choosePreferredGalleryPackage(pm: PackageManager, intent: Intent): String? {
            val candidates = queryCandidates(pm, intent)
            if (candidates.isEmpty()) return null
            if (candidates.size == 1) return candidates.first()
            for (preferred in PREFERRED_GALLERY_PACKAGES) {
                if (preferred in candidates) return preferred
            }
            return candidates.firstOrNull { pkg ->
                val lower = pkg.lowercase()
                lower.contains("gallery") || lower.contains("photos") || lower.contains("album")
            } ?: candidates.first()
        }
    }
}
