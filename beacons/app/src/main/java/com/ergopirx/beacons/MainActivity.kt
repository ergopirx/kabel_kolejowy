package com.ergopirx.beacons

import android.Manifest
import android.app.Activity
import android.app.AlertDialog
import android.content.Intent
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.location.Location
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import android.provider.Settings
import android.view.View
import android.view.WindowInsets
import android.view.WindowManager
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast

class MainActivity : Activity() {

    private lateinit var store: MarkerStore
    private lateinit var navigator: Navigator
    private lateinit var compass: CompassView
    private lateinit var bottomBar: View
    private lateinit var chipRow: LinearLayout
    private lateinit var dropButton: Button

    private val chips = HashMap<Long, TextView>()
    private var chipOrder: List<Long> = emptyList()
    private var chipLocation: Location? = null
    private var chipsDirty = true

    /** Id of the beacon we last buzzed for, so arrival vibrates once per approach. */
    private var arrivedId = -1L
    private var askedForPermission = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)

        compass = findViewById(R.id.compass)
        bottomBar = findViewById(R.id.bottom_bar)
        chipRow = findViewById(R.id.chip_row)
        dropButton = findViewById(R.id.drop_button)

        store = MarkerStore(this)
        navigator = Navigator(this) { render() }

        compass.onMarkerTapped = { id -> select(id) }
        dropButton.setOnClickListener { onDropPressed() }

        goEdgeToEdge()
        if (!navigator.hasFineLocation()) requestLocationPermission()
        render()
    }

    override fun onResume() {
        super.onResume()
        if (navigator.hasFineLocation()) navigator.start()
        render()
    }

    override fun onPause() {
        super.onPause()
        navigator.stop()
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == REQUEST_LOCATION && navigator.hasFineLocation()) navigator.start()
        render()
    }

    // ---- rendering --------------------------------------------------------------------------

    private fun render() {
        val fix = navigator.location
        val hasPermission = navigator.hasFineLocation()

        compass.update(
            markers = store.markers,
            selectedId = store.selectedId,
            location = fix,
            heading = navigator.heading,
            compassUnreliable = navigator.compassUnreliable,
            hasPermission = hasPermission,
            locationEnabled = navigator.locationEnabled,
        )

        dropButton.setText(if (hasPermission) R.string.drop_here else R.string.grant_location)

        if (chipsDirty || fix !== chipLocation) {
            refreshChips(fix)
            chipLocation = fix
            chipsDirty = false
        }

        val selected = store.selected
        if (selected != null && fix != null) {
            val arrived = Geo.distance(fix, selected) <= Geo.arrivalRadius(fix)
            if (arrived && arrivedId != selected.id) {
                arrivedId = selected.id
                buzz()
            } else if (!arrived && arrivedId == selected.id) {
                arrivedId = -1L
            }
        }
    }

    private fun refreshChips(fix: Location?) {
        val order = store.markers.map { it.id }
        if (order != chipOrder) {
            chipRow.removeAllViews()
            chips.clear()
            for (m in store.markers) chipRow.addView(makeChip(m.id))
            chipOrder = order
        }
        for (m in store.markers) {
            val chip = chips[m.id] ?: continue
            val selected = m.id == store.selectedId
            chip.background = GradientDrawable().apply {
                cornerRadius = dp(22f)
                setColor(withAlpha(m.color, if (selected) 0x66 else 0x1E))
                setStroke(dp(2f).toInt(), if (selected) m.color else withAlpha(m.color, 0x55))
            }
            chip.text = if (fix != null) "${m.name} · ${Geo.formatDistance(Geo.distance(fix, m))}" else m.name
            chip.setTextColor(if (selected) Color.WHITE else 0xCCFFFFFF.toInt())
        }
    }

    private fun makeChip(id: Long): TextView = TextView(this).apply {
        textSize = 14f
        typeface = android.graphics.Typeface.DEFAULT_BOLD
        setSingleLine()
        setPadding(dp(16f).toInt(), dp(10f).toInt(), dp(16f).toInt(), dp(10f).toInt())
        layoutParams = LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT,
        ).apply { marginEnd = dp(8f).toInt() }
        setOnClickListener { select(id) }
        setOnLongClickListener {
            store.markers.firstOrNull { it.id == id }?.let(::promptEdit)
            true
        }
        chips[id] = this
    }

    private fun select(id: Long) {
        store.selectedId = id
        chipsDirty = true
        render()
    }

    // ---- actions ----------------------------------------------------------------------------

    private fun onDropPressed() {
        if (!navigator.hasFineLocation()) {
            requestLocationPermission()
            return
        }
        val fix = navigator.location
        if (fix == null) {
            Toast.makeText(this, R.string.finding_position, Toast.LENGTH_SHORT).show()
            return
        }
        val draft = Marker(
            id = store.nextId(),
            name = getString(R.string.default_name, store.markers.size + 1),
            lat = fix.latitude,
            lon = fix.longitude,
            color = store.nextColor(),
            createdAt = System.currentTimeMillis(),
        )
        val subtitle = if (fix.hasAccuracy()) getString(R.string.pinned_here, fix.accuracy.toInt())
        else getString(R.string.pinned_here_no_accuracy)

        showEditor(draft, R.string.new_beacon, subtitle, R.string.action_drop, isNew = true) { result ->
            store.add(result)
            chipsDirty = true
            render()
        }
    }

    private fun promptEdit(marker: Marker) {
        showEditor(marker, R.string.edit_beacon, null, R.string.action_save, isNew = false) { result ->
            store.update(result)
            chipsDirty = true
            render()
        }
    }

    /**
     * One dialog for both dropping and editing: a name field plus a row of colour swatches.
     * Editing adds "Move here" (re-pin to where you stand) and "Delete".
     */
    private fun showEditor(
        marker: Marker,
        titleRes: Int,
        subtitle: String?,
        positiveRes: Int,
        isNew: Boolean,
        onDone: (Marker) -> Unit,
    ) {
        val view = layoutInflater.inflate(R.layout.dialog_marker, null)
        val subtitleView = view.findViewById<TextView>(R.id.subtitle)
        val nameField = view.findViewById<EditText>(R.id.name)
        val swatchRow = view.findViewById<LinearLayout>(R.id.swatches)

        subtitleView.visibility = if (subtitle == null) View.GONE else View.VISIBLE
        subtitleView.text = subtitle
        nameField.setText(marker.name)
        nameField.setSelection(marker.name.length)

        var color = marker.color
        val swatches = Marker.PALETTE.map { paletteColor ->
            View(this).apply {
                layoutParams = LinearLayout.LayoutParams(dp(34f).toInt(), dp(34f).toInt()).apply {
                    marginStart = dp(3f).toInt()
                    marginEnd = dp(3f).toInt()
                }
                tag = paletteColor
            }
        }
        fun paintSwatches() {
            for (swatch in swatches) {
                val c = swatch.tag as Int
                swatch.background = GradientDrawable().apply {
                    shape = GradientDrawable.OVAL
                    setColor(c)
                    if (c == color) setStroke(dp(3f).toInt(), Color.WHITE)
                }
            }
        }
        for (swatch in swatches) {
            swatch.setOnClickListener {
                color = swatch.tag as Int
                paintSwatches()
            }
            swatchRow.addView(swatch)
        }
        paintSwatches()

        val builder = AlertDialog.Builder(this)
            .setTitle(titleRes)
            .setView(view)
            .setPositiveButton(positiveRes) { _, _ ->
                val name = nameField.text.toString().trim().ifEmpty { marker.name }
                onDone(marker.copy(name = name, color = color))
            }

        if (isNew) {
            builder.setNegativeButton(R.string.action_cancel, null)
        } else {
            builder.setNegativeButton(R.string.action_delete) { _, _ -> confirmDelete(marker) }
            builder.setNeutralButton(R.string.action_move_here) { _, _ -> moveHere(marker) }
        }
        builder.show()
    }

    private fun confirmDelete(marker: Marker) {
        AlertDialog.Builder(this)
            .setMessage(getString(R.string.delete_confirm, marker.name))
            .setPositiveButton(R.string.action_delete) { _, _ ->
                store.remove(marker.id)
                chipsDirty = true
                render()
                Toast.makeText(this, getString(R.string.deleted, marker.name), Toast.LENGTH_SHORT).show()
            }
            .setNegativeButton(R.string.action_cancel, null)
            .show()
    }

    private fun moveHere(marker: Marker) {
        val fix = navigator.location
        if (fix == null) {
            Toast.makeText(this, R.string.finding_position, Toast.LENGTH_SHORT).show()
            return
        }
        store.update(marker.copy(lat = fix.latitude, lon = fix.longitude))
        chipsDirty = true
        render()
        Toast.makeText(this, getString(R.string.moved_here, marker.name), Toast.LENGTH_SHORT).show()
    }

    // ---- permissions ------------------------------------------------------------------------

    private fun requestLocationPermission() {
        val permissions = arrayOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION)
        // After a flat "don't ask again" the system returns instantly, so send the user to settings.
        val canAsk = !askedForPermission || shouldShowRequestPermissionRationale(Manifest.permission.ACCESS_FINE_LOCATION)
        if (canAsk) {
            askedForPermission = true
            requestPermissions(permissions, REQUEST_LOCATION)
        } else {
            Toast.makeText(this, R.string.open_settings, Toast.LENGTH_SHORT).show()
            startActivity(
                Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.fromParts("package", packageName, null)),
            )
        }
    }

    // ---- system ui --------------------------------------------------------------------------

    private fun goEdgeToEdge() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) window.setDecorFitsSystemWindows(false)
        val root = findViewById<View>(R.id.root)
        val pad = dp(16f).toInt()
        root.setOnApplyWindowInsetsListener { _, insets ->
            val top: Int
            val bottom: Int
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                val bars = insets.getInsets(WindowInsets.Type.systemBars())
                top = bars.top
                bottom = bars.bottom
            } else {
                @Suppress("DEPRECATION")
                top = insets.systemWindowInsetTop
                @Suppress("DEPRECATION")
                bottom = insets.systemWindowInsetBottom
            }
            compass.setTopInset(top)
            bottomBar.setPadding(pad, pad, pad, pad + bottom)
            insets
        }
    }

    private fun buzz() {
        val vibrator: Vibrator? = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            getSystemService(VibratorManager::class.java)?.defaultVibrator
        } else {
            getSystemService(Vibrator::class.java)
        }
        if (vibrator?.hasVibrator() != true) return
        vibrator.vibrate(VibrationEffect.createWaveform(longArrayOf(0, 50, 70, 50, 70, 120), -1))
    }

    private fun dp(v: Float) = v * resources.displayMetrics.density

    private fun withAlpha(color: Int, alpha: Int) = (color and 0x00FFFFFF) or (alpha shl 24)

    private companion object {
        const val REQUEST_LOCATION = 1
    }
}
