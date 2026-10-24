package com.ergopirx.beacons

import android.location.Location
import java.util.Locale
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt

/** Distance and bearing from a fix to a marker, plus the human-friendly formatting around them. */
object Geo {

    private val scratch = FloatArray(2)

    /** Great-circle distance in metres. */
    fun distance(from: Location, to: Marker): Float {
        Location.distanceBetween(from.latitude, from.longitude, to.lat, to.lon, scratch)
        return scratch[0]
    }

    /** Initial true bearing from the fix to the marker, in degrees [0, 360). */
    fun bearing(from: Location, to: Marker): Float {
        Location.distanceBetween(from.latitude, from.longitude, to.lat, to.lon, scratch)
        return (scratch[1] + 360f) % 360f
    }

    /**
     * How close counts as "you're here". GPS jitter of a few metres is normal, so we never go
     * below 8 m, grow with the fix's reported accuracy, and cap it so a bad fix can't claim arrival
     * from the other side of a car park.
     */
    fun arrivalRadius(fix: Location): Float {
        val accuracy = if (fix.hasAccuracy()) fix.accuracy * 0.75f else 8f
        return min(30f, max(8f, accuracy))
    }

    fun formatDistance(metres: Float): String = when {
        metres < 1000f -> "${metres.roundToInt()} m"
        metres < 10_000f -> String.format(Locale.getDefault(), "%.1f km", metres / 1000f)
        else -> "${(metres / 1000f).roundToInt()} km"
    }

    /** Minutes of walking at a relaxed 1.3 m/s, or null when it's too far to be a walk. */
    fun walkMinutes(metres: Float): Int? {
        val minutes = (metres / 1.3f / 60f).roundToInt()
        return if (minutes in 1..(8 * 60)) minutes else null
    }

    private val CARDINALS = arrayOf("N", "NE", "E", "SE", "S", "SW", "W", "NW")

    fun cardinal(degrees: Float): String {
        val normalised = ((degrees % 360f) + 360f) % 360f
        return CARDINALS[((normalised + 22.5f) / 45f).toInt() % 8]
    }
}
