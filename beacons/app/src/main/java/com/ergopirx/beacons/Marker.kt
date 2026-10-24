package com.ergopirx.beacons

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject

/** A saved GPS position the arrow can point at. */
data class Marker(
    val id: Long,
    val name: String,
    val lat: Double,
    val lon: Double,
    val color: Int,
    val createdAt: Long,
) {
    fun toJson(): JSONObject = JSONObject()
        .put("id", id)
        .put("name", name)
        .put("lat", lat)
        .put("lon", lon)
        .put("color", color)
        .put("createdAt", createdAt)

    companion object {
        /** Fresh, high-contrast colours that read well on the dark ring. */
        val PALETTE = intArrayOf(
            0xFFFF6B2C.toInt(), // tangerine
            0xFF2FE6DE.toInt(), // cyan
            0xFFB6F04A.toInt(), // lime
            0xFFFF4FA3.toInt(), // magenta
            0xFFFFD23F.toInt(), // yellow
            0xFF9B6BFF.toInt(), // violet
            0xFF3DF59A.toInt(), // mint
            0xFFFF5C5C.toInt(), // coral
        )

        fun fromJson(o: JSONObject) = Marker(
            id = o.getLong("id"),
            name = o.getString("name"),
            lat = o.getDouble("lat"),
            lon = o.getDouble("lon"),
            color = o.getInt("color"),
            createdAt = o.optLong("createdAt"),
        )
    }
}

/** Persists markers as a JSON array in SharedPreferences. Small enough that nothing heavier is needed. */
class MarkerStore(context: Context) {

    private val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    val markers: MutableList<Marker> = load()

    /** Id of the marker the big arrow points at, or -1 when none is selected. */
    var selectedId: Long = prefs.getLong(KEY_SELECTED, -1L)
        set(value) {
            if (field == value) return
            field = value
            prefs.edit().putLong(KEY_SELECTED, value).apply()
        }

    val selected: Marker? get() = markers.firstOrNull { it.id == selectedId }

    fun add(marker: Marker) {
        markers += marker
        selectedId = marker.id
        persist()
    }

    fun update(marker: Marker) {
        val i = markers.indexOfFirst { it.id == marker.id }
        if (i < 0) return
        markers[i] = marker
        persist()
    }

    fun remove(id: Long) {
        markers.removeAll { it.id == id }
        if (selectedId == id) selectedId = markers.lastOrNull()?.id ?: -1L
        persist()
    }

    fun nextColor(): Int = Marker.PALETTE[markers.size % Marker.PALETTE.size]

    fun nextId(): Long {
        val now = System.currentTimeMillis()
        return if (markers.any { it.id == now }) now + 1 else now
    }

    private fun load(): MutableList<Marker> {
        val raw = prefs.getString(KEY_MARKERS, null) ?: return mutableListOf()
        return runCatching {
            val arr = JSONArray(raw)
            MutableList(arr.length()) { Marker.fromJson(arr.getJSONObject(it)) }
        }.getOrDefault(mutableListOf())
    }

    private fun persist() {
        val arr = JSONArray()
        markers.forEach { arr.put(it.toJson()) }
        prefs.edit().putString(KEY_MARKERS, arr.toString()).apply()
    }

    private companion object {
        const val PREFS = "beacons"
        const val KEY_MARKERS = "markers"
        const val KEY_SELECTED = "selected"
    }
}
