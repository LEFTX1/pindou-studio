package com.pindoustudio.app.data

import kotlin.math.abs
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class Ciede2000Test {

    @Test
    fun `ciede2000 matches Sharma 2005 and scikit-image reference pairs`() {
        val cases = listOf(
            // (l1, a1, b1, l2, a2, b2, expectedDeltaE00)
            doubleArrayOf(50.0, 2.6772, -79.7751, 50.0, 0.0, -82.7485, 2.0425),
            doubleArrayOf(50.0, 3.1571, -77.2803, 50.0, 0.0, -82.7485, 2.8615),
            doubleArrayOf(50.0, 2.8361, -74.0200, 50.0, 0.0, -82.7485, 3.4412),
            doubleArrayOf(50.0, -1.3802, -84.2814, 50.0, 1.0, -84.4250, 1.2175),
            doubleArrayOf(60.2574, -34.0099, 36.2677, 60.4626, -34.1751, 39.4387, 1.2644),
            doubleArrayOf(95.0, -2.5, 4.0, 93.5, 1.2, 2.1, 5.5766)
        )
        for ((idx, c) in cases.withIndex()) {
            val actual = PaletteRepository.ciede2000(c[0], c[1], c[2], c[3], c[4], c[5])
            assertTrue("Case $idx mismatch: actual=$actual expected=${c[6]}", abs(actual - c[6]) < 2e-4)
        }

        // Identical colors -> exact zero
        assertEquals(0.0, PaletteRepository.ciede2000(65.0, 12.0, -18.0, 65.0, 12.0, -18.0), 1e-9)
        // Achromatic whites -> finite L* delta
        val neutral = PaletteRepository.ciede2000(100.0, 0.0, 0.0, 92.0, 0.0, 0.0)
        assertTrue("Neutral diff invalid: $neutral", neutral.isFinite() && neutral > 3.0)
    }
}
