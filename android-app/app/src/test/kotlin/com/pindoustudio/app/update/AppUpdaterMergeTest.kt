package com.pindoustudio.app.update

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AppUpdaterMergeTest {

    @Test
    fun `skipping multiple versions merges A B C changelogs and targets latest APK`() {
        val manifest = UpdateManifest(
            versionCode = 7,
            versionName = "1.2.4",
            changelog = "1.2.4 最新说明",
            sha256 = "deadbeef",
            forceUpdate = false,
            apkMirrors = listOf(
                "https://ghfast.top/https://github.com/LEFTX1/pindou-studio/releases/download/v1.2.4/pindou-studio-v1.2.4-release.apk"
            ),
            fallbackPageUrl = "https://github.com/LEFTX1/pindou-studio/releases",
            releaseHistory = listOf(
                ReleaseHistoryEntry(7L, "1.2.4", "C: 支持长方形自由拉伸裁剪"),
                ReleaseHistoryEntry(6L, "1.2.3", "B: 新增交互式放大框选"),
                ReleaseHistoryEntry(5L, "1.2.2", "A: 修复异形描边脖颈切割"),
                ReleaseHistoryEntry(4L, "1.2.1", "已安装的旧版本")
            )
        )

        val summary = manifest.buildMergedSummary(currentVersionCode = 4L)
        assertEquals(3, summary.skippedCount)
        assertTrue(summary.mergedChangelog.contains("【v1.2.4】"))
        assertTrue(summary.mergedChangelog.contains("【v1.2.3】"))
        assertTrue(summary.mergedChangelog.contains("【v1.2.2】"))
        assertFalse(summary.mergedChangelog.contains("1.2.1"))
    }

    @Test
    fun `single version step reports skippedCount 1 without multi-header noise`() {
        val manifest = UpdateManifest(
            versionCode = 7,
            versionName = "1.2.4",
            changelog = "支持长方形自由拉伸裁剪",
            sha256 = "deadbeef",
            forceUpdate = false,
            apkMirrors = listOf("https://example.com/v1.2.4.apk"),
            fallbackPageUrl = "https://github.com/LEFTX1/pindou-studio/releases",
            releaseHistory = listOf(
                ReleaseHistoryEntry(7L, "1.2.4", "支持长方形自由拉伸裁剪"),
                ReleaseHistoryEntry(6L, "1.2.3", "旧版本")
            )
        )

        val summary = manifest.buildMergedSummary(currentVersionCode = 6L)
        assertEquals(1, summary.skippedCount)
        assertEquals("支持长方形自由拉伸裁剪", summary.mergedChangelog)
    }

    @Test
    fun `legacy manifest without history falls back cleanly`() {
        val manifest = UpdateManifest(
            versionCode = 8,
            versionName = "1.2.5",
            changelog = "一键合并历史更新",
            sha256 = "abc",
            forceUpdate = false,
            apkMirrors = listOf("https://example.com/v1.2.5.apk"),
            fallbackPageUrl = "https://github.com/LEFTX1/pindou-studio/releases"
        )

        val summary = manifest.buildMergedSummary(currentVersionCode = 5L)
        assertEquals(3, summary.skippedCount)
        assertEquals("一键合并历史更新", summary.mergedChangelog)
    }
}
