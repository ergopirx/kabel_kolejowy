package com.ergopirx.beacons

import android.Manifest
import android.annotation.SuppressLint
import android.app.Activity
import android.content.pm.PackageManager
import android.hardware.GeomagneticField
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.os.Build
import android.os.Bundle
import android.view.Surface
import kotlin.math.atan2
import kotlin.math.cos
import kotlin.math.hypot
import kotlin.math.sin

/**
 * Where you are and which way you face.
 *
 * Location comes straight from [LocationManager] (fused provider where the OS offers it, GPS +
 * network otherwise), so no Play Services dependency. Heading comes from the rotation-vector sensor,
 * is corrected for screen rotation and magnetic declination, and is smoothed on the unit circle so
 * the arrow never spins the long way round when crossing north.
 */
class Navigator(
    private val activity: Activity,
    private val onUpdate: () -> Unit,
) : SensorEventListener, LocationListener {

    var location: Location? = null
        private set

    /** True heading in degrees [0, 360), or null until the first usable reading. */
    var heading: Float? = null
        private set

    /** True when the magnetometer reports low accuracy and a figure-8 calibration would help. */
    var compassUnreliable = false
        private set

    private val sensorManager: SensorManager = activity.getSystemService(SensorManager::class.java)
    private val locationManager: LocationManager = activity.getSystemService(LocationManager::class.java)

    private val rotationSensor: Sensor? = sensorManager.getDefaultSensor(Sensor.TYPE_ROTATION_VECTOR)
    private val accelerometer: Sensor? = sensorManager.getDefaultSensor(Sensor.TYPE_ACCELEROMETER)
    private val magnetometer: Sensor? = sensorManager.getDefaultSensor(Sensor.TYPE_MAGNETIC_FIELD)

    val hasCompass: Boolean = rotationSensor != null || (accelerometer != null && magnetometer != null)

    private val rotationMatrix = FloatArray(9)
    private val remapped = FloatArray(9)
    private val gravity = FloatArray(3)
    private val geomagnetic = FloatArray(3)
    private var hasGravity = false
    private var hasGeomagnetic = false

    // Smoothed heading as a unit vector, so averaging 359° and 1° gives 0° rather than 180°.
    private var smoothX = 0f
    private var smoothY = 0f

    private var declination = 0f
    private var running = false

    fun hasFineLocation(): Boolean =
        activity.checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED

    /** Whether the device's location switch is on. Cached: it is read on every frame. */
    var locationEnabled = true
        private set

    private fun readLocationEnabled(): Boolean =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) locationManager.isLocationEnabled
        else locationManager.isProviderEnabled(LocationManager.GPS_PROVIDER) ||
            locationManager.isProviderEnabled(LocationManager.NETWORK_PROVIDER)

    fun start() {
        if (running) return
        running = true
        locationEnabled = readLocationEnabled()
        when {
            rotationSensor != null ->
                sensorManager.registerListener(this, rotationSensor, SensorManager.SENSOR_DELAY_GAME)
            accelerometer != null && magnetometer != null -> {
                sensorManager.registerListener(this, accelerometer, SensorManager.SENSOR_DELAY_GAME)
                sensorManager.registerListener(this, magnetometer, SensorManager.SENSOR_DELAY_GAME)
            }
        }
        startLocation()
    }

    fun stop() {
        running = false
        sensorManager.unregisterListener(this)
        locationManager.removeUpdates(this)
    }

    @SuppressLint("MissingPermission")
    private fun startLocation() {
        if (!hasFineLocation()) return
        val available = locationManager.allProviders
        val providers = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S && LocationManager.FUSED_PROVIDER in available) {
            listOf(LocationManager.FUSED_PROVIDER)
        } else {
            listOf(LocationManager.GPS_PROVIDER, LocationManager.NETWORK_PROVIDER).filter { it in available }
        }
        for (provider in providers) {
            locationManager.getLastKnownLocation(provider)?.let(::offer)
            locationManager.requestLocationUpdates(provider, 1000L, 0f, this)
        }
    }

    /** Keeps the newest fix unless an older one is clearly more precise. */
    private fun offer(fix: Location) {
        val current = location
        val better = current == null ||
            fix.time - current.time > 10_000L ||
            (fix.hasAccuracy() && (!current.hasAccuracy() || fix.accuracy <= current.accuracy))
        if (!better) return

        location = fix
        declination = GeomagneticField(
            fix.latitude.toFloat(), fix.longitude.toFloat(), fix.altitude.toFloat(), fix.time,
        ).declination

        // Without any compass hardware, fall back to the direction of travel while moving.
        if (!hasCompass && fix.hasBearing() && fix.hasSpeed() && fix.speed > 1f) {
            heading = (fix.bearing + 360f) % 360f
        }
        onUpdate()
    }

    // ---- LocationListener -------------------------------------------------------------------

    override fun onLocationChanged(location: Location) = offer(location)

    // Explicit overrides: on API 26–29 these are abstract and the framework calls them.
    override fun onProviderEnabled(provider: String) = refreshLocationEnabled()
    override fun onProviderDisabled(provider: String) = refreshLocationEnabled()

    private fun refreshLocationEnabled() {
        locationEnabled = readLocationEnabled()
        onUpdate()
    }

    @Deprecated("Deprecated in Java")
    override fun onStatusChanged(provider: String?, status: Int, extras: Bundle?) = Unit

    // ---- SensorEventListener ----------------------------------------------------------------

    override fun onSensorChanged(event: SensorEvent) {
        when (event.sensor.type) {
            Sensor.TYPE_ROTATION_VECTOR -> {
                SensorManager.getRotationMatrixFromVector(rotationMatrix, event.values)
                publishHeading(rotationMatrix)
            }
            Sensor.TYPE_ACCELEROMETER -> {
                lowPass(event.values, gravity)
                hasGravity = true
                fuseAccelAndMag()
            }
            Sensor.TYPE_MAGNETIC_FIELD -> {
                lowPass(event.values, geomagnetic)
                hasGeomagnetic = true
                fuseAccelAndMag()
            }
        }
    }

    override fun onAccuracyChanged(sensor: Sensor, accuracy: Int) {
        if (sensor.type == Sensor.TYPE_ROTATION_VECTOR || sensor.type == Sensor.TYPE_MAGNETIC_FIELD) {
            val unreliable = accuracy == SensorManager.SENSOR_STATUS_UNRELIABLE ||
                accuracy == SensorManager.SENSOR_STATUS_ACCURACY_LOW
            if (unreliable != compassUnreliable) {
                compassUnreliable = unreliable
                onUpdate()
            }
        }
    }

    private fun fuseAccelAndMag() {
        if (hasGravity && hasGeomagnetic &&
            SensorManager.getRotationMatrix(rotationMatrix, null, gravity, geomagnetic)
        ) publishHeading(rotationMatrix)
    }

    /**
     * Derives the heading from a device-to-world rotation matrix in a way that works whether the
     * phone is lying flat, held upright, or anywhere in between.
     *
     * Column 1 of the matrix is the screen's "up" axis expressed in world (east, north, up)
     * coordinates; column 2 is the axis pointing out of the screen. Lying flat, the first points
     * where you're walking; held upright, the *back* of the phone does. Summing their horizontal
     * projections hands over smoothly between the two, with no tilt threshold to flicker across.
     */
    private fun publishHeading(matrix: FloatArray) {
        val (axisX, axisY) = when (displayRotation()) {
            Surface.ROTATION_90 -> SensorManager.AXIS_Y to SensorManager.AXIS_MINUS_X
            Surface.ROTATION_180 -> SensorManager.AXIS_MINUS_X to SensorManager.AXIS_MINUS_Y
            Surface.ROTATION_270 -> SensorManager.AXIS_MINUS_Y to SensorManager.AXIS_X
            else -> SensorManager.AXIS_X to SensorManager.AXIS_Y
        }
        SensorManager.remapCoordinateSystem(matrix, axisX, axisY, remapped)

        val east = remapped[1] - remapped[2]
        val north = remapped[4] - remapped[5]
        if (hypot(east, north) < 0.05f) return // pointing straight up or down: no heading to speak of

        val magnetic = Math.toDegrees(atan2(east, north).toDouble()).toFloat()
        val trueRad = Math.toRadians((magnetic + declination).toDouble())
        val alpha = if (heading == null) 1f else SMOOTHING
        smoothX += (cos(trueRad).toFloat() - smoothX) * alpha
        smoothY += (sin(trueRad).toFloat() - smoothY) * alpha

        heading = ((Math.toDegrees(atan2(smoothY, smoothX).toDouble()) + 360.0) % 360.0).toFloat()
        onUpdate()
    }

    private fun displayRotation(): Int =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            activity.display?.rotation ?: Surface.ROTATION_0
        } else {
            @Suppress("DEPRECATION")
            activity.windowManager.defaultDisplay.rotation
        }

    private fun lowPass(input: FloatArray, output: FloatArray) {
        for (i in 0 until 3) output[i] += (input[i] - output[i]) * 0.25f
    }

    private companion object {
        /** Per-sample blend at ~50 Hz: settles in about a third of a second without feeling laggy. */
        const val SMOOTHING = 0.15f
    }
}
