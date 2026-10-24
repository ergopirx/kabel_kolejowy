package com.ergopirx.beacons

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.LinearGradient
import android.graphics.Paint
import android.graphics.Path
import android.graphics.RadialGradient
import android.graphics.RectF
import android.graphics.Shader
import android.graphics.Typeface
import android.location.Location
import android.util.AttributeSet
import android.util.TypedValue
import android.view.MotionEvent
import android.view.View
import android.view.ViewConfiguration
import kotlin.math.cos
import kotlin.math.hypot
import kotlin.math.ln
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt
import kotlin.math.sin

/**
 * The whole UI in one canvas: a compass ring that rotates with your heading, one glowing dot per
 * beacon sitting on the ring in its real direction (bigger when closer), and a big arrow for the
 * selected beacon with the distance underneath. When you reach it the arrow dissolves into a
 * pulsing target.
 */
class CompassView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
) : View(context, attrs) {

    /** Called with the marker id when the user taps one of the dots on the ring. */
    var onMarkerTapped: ((Long) -> Unit)? = null

    private var markers: List<Marker> = emptyList()
    private var selectedId = -1L
    private var location: Location? = null
    private var heading: Float? = null
    private var compassUnreliable = false
    private var hasPermission = true
    private var locationEnabled = true
    private var topInset = 0

    fun update(
        markers: List<Marker>,
        selectedId: Long,
        location: Location?,
        heading: Float?,
        compassUnreliable: Boolean,
        hasPermission: Boolean,
        locationEnabled: Boolean,
    ) {
        this.markers = markers
        this.selectedId = selectedId
        this.location = location
        this.heading = heading
        this.compassUnreliable = compassUnreliable
        this.hasPermission = hasPermission
        this.locationEnabled = locationEnabled
        invalidate()
    }

    fun setTopInset(px: Int) {
        if (topInset == px) return
        topInset = px
        invalidate()
    }

    // ---- drawing state ----------------------------------------------------------------------

    private val density = resources.displayMetrics.density
    private fun dp(v: Float) = v * density
    private fun sp(v: Float) = TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_SP, v, resources.displayMetrics)

    private val paint = Paint(Paint.ANTI_ALIAS_FLAG)
    private val textPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { textAlign = Paint.Align.CENTER }
    private val path = Path()
    private val arcRect = RectF()
    private var background: Shader? = null

    private val displayTypeface: Typeface = Typeface.create("sans-serif-black", Typeface.NORMAL)
    private val labelTypeface: Typeface = Typeface.DEFAULT_BOLD

    private class Dot(val id: Long, val x: Float, val y: Float)
    private val dots = ArrayList<Dot>()
    private var animating = false

    private val touchSlop = ViewConfiguration.get(context).scaledTouchSlop
    private var downX = 0f
    private var downY = 0f

    override fun onSizeChanged(w: Int, h: Int, oldw: Int, oldh: Int) {
        background = RadialGradient(
            w / 2f, h * 0.38f, max(w, h) * 0.85f,
            intArrayOf(0xFF161C31.toInt(), 0xFF070912.toInt()), null, Shader.TileMode.CLAMP,
        )
    }

    override fun onDraw(canvas: Canvas) {
        val w = width.toFloat()
        val h = height.toFloat()
        val now = System.nanoTime()
        animating = false
        dots.clear()

        paint.shader = background
        paint.style = Paint.Style.FILL
        canvas.drawRect(0f, 0f, w, h, paint)
        paint.shader = null

        // Portrait stacks ring then text; landscape puts them side by side.
        val landscape = w > h * 1.15f
        val cx = if (landscape) w * 0.32f else w / 2f
        val cy = if (landscape) h * 0.5f else topInset + (h - topInset) * 0.36f
        val r = if (landscape) h * 0.34f else min(w * 0.40f, h * 0.25f)
        val textX = if (landscape) w * 0.72f else cx
        val textY = if (landscape) cy - dp(16f) else cy + r + dp(64f)

        val hdg = heading ?: 0f
        drawRing(canvas, cx, cy, r, hdg)
        drawHeadingReadout(canvas, cx, cy - r - dp(34f), hdg)

        val fix = location
        val selected = markers.firstOrNull { it.id == selectedId }
        var selectedDistance = 0f
        var arrived = false

        if (fix != null) {
            for (m in markers) if (m.id != selectedId) drawDot(canvas, cx, cy, r, m, fix, hdg, selected = false)
            if (selected != null) {
                selectedDistance = Geo.distance(fix, selected)
                arrived = selectedDistance <= Geo.arrivalRadius(fix)
                if (arrived) {
                    drawArrival(canvas, cx, cy, r, selected.color, now)
                } else {
                    drawDot(canvas, cx, cy, r, selected, fix, hdg, selected = true)
                    drawArrow(canvas, cx, cy, r, selected.color, Geo.bearing(fix, selected) - hdg, now)
                }
            }
        }

        when {
            !hasPermission -> drawStatus(canvas, textX, textY, R.string.status_no_permission_title, R.string.status_no_permission_hint)
            fix == null && !locationEnabled -> drawStatus(canvas, textX, textY, R.string.status_location_off_title, R.string.status_location_off_hint)
            fix == null -> {
                drawSpinner(canvas, cx, cy, r * 0.18f, now)
                drawStatus(canvas, textX, textY, R.string.status_finding_title, R.string.status_finding_hint)
            }
            markers.isEmpty() -> drawStatus(canvas, textX, textY, R.string.status_empty_title, R.string.status_empty_hint)
            selected == null -> drawStatus(canvas, textX, textY, R.string.status_pick_title, R.string.status_pick_hint)
            else -> drawDistanceBlock(canvas, textX, textY, selected, selectedDistance, arrived, fix)
        }

        if (animating) postInvalidateOnAnimation()
    }

    // ---- ring -------------------------------------------------------------------------------

    private fun drawRing(c: Canvas, cx: Float, cy: Float, r: Float, hdg: Float) {
        paint.style = Paint.Style.STROKE
        paint.strokeCap = Paint.Cap.ROUND
        paint.strokeWidth = dp(1f)
        paint.color = 0x16FFFFFF
        c.drawCircle(cx, cy, r, paint)

        c.save()
        c.rotate(-hdg, cx, cy)
        for (i in 0 until 72) {
            val deg = i * 5
            val major = deg % 90 == 0
            val mid = deg % 30 == 0
            val len = when {
                major -> dp(14f)
                mid -> dp(9f)
                else -> dp(4f)
            }
            paint.strokeWidth = if (major) dp(2.5f) else dp(1.2f)
            paint.color = when {
                deg == 0 -> ACCENT
                major -> 0xB0FFFFFF.toInt()
                mid -> 0x70FFFFFF
                else -> 0x38FFFFFF
            }
            val a = Math.toRadians(deg.toDouble())
            val sx = sin(a).toFloat()
            val sy = -cos(a).toFloat()
            c.drawLine(cx + sx * (r - len), cy + sy * (r - len), cx + sx * r, cy + sy * r, paint)
        }

        textPaint.typeface = labelTypeface
        textPaint.textSize = sp(13f)
        val labelRadius = r - dp(30f)
        for ((i, label) in CARDINALS.withIndex()) {
            val a = Math.toRadians(i * 90.0)
            val x = cx + sin(a).toFloat() * labelRadius
            val y = cy - cos(a).toFloat() * labelRadius
            textPaint.color = if (i == 0) ACCENT else 0x80FFFFFF.toInt()
            c.save()
            c.rotate(hdg, x, y) // keep the letters upright while the ring turns
            c.drawText(label, x, y + textPaint.textSize * 0.36f, textPaint)
            c.restore()
        }
        c.restore()

        // Fixed index at 12 o'clock: this is where you're facing.
        paint.style = Paint.Style.FILL
        paint.color = Color.WHITE
        path.reset()
        path.moveTo(cx, cy - r - dp(5f))
        path.lineTo(cx - dp(6f), cy - r - dp(15f))
        path.lineTo(cx + dp(6f), cy - r - dp(15f))
        path.close()
        c.drawPath(path, paint)
    }

    private fun drawHeadingReadout(c: Canvas, x: Float, y: Float, hdg: Float) {
        textPaint.typeface = Typeface.DEFAULT
        textPaint.textSize = sp(14f)
        val text = when {
            compassUnreliable -> context.getString(R.string.calibrate_compass)
            heading == null -> context.getString(R.string.no_compass)
            else -> context.getString(R.string.heading_readout, hdg.roundToInt() % 360, Geo.cardinal(hdg))
        }
        textPaint.color = if (compassUnreliable) AMBER else 0xA0FFFFFF.toInt()
        c.drawText(text, x, y, textPaint)
    }

    // ---- markers ----------------------------------------------------------------------------

    private fun drawDot(c: Canvas, cx: Float, cy: Float, r: Float, m: Marker, fix: Location, hdg: Float, selected: Boolean) {
        val distance = Geo.distance(fix, m)
        val rel = Math.toRadians((Geo.bearing(fix, m) - hdg).toDouble())
        val x = cx + sin(rel).toFloat() * r
        val y = cy - cos(rel).toFloat() * r

        // Logarithmic size: 50 km is a pinprick, a few metres fills the dot.
        val closeness = (1f - ln(distance + 1f) / ln(50_001f)).coerceIn(0f, 1f)
        val radius = dp(5f) + dp(7f) * closeness

        paint.style = Paint.Style.FILL
        paint.color = withAlpha(m.color, 0x40)
        c.drawCircle(x, y, radius * 2.1f, paint)
        paint.color = m.color
        c.drawCircle(x, y, radius, paint)
        if (selected) {
            paint.style = Paint.Style.STROKE
            paint.strokeWidth = dp(2f)
            paint.color = Color.WHITE
            c.drawCircle(x, y, radius + dp(3.5f), paint)
        }
        dots += Dot(m.id, x, y)
    }

    private fun drawArrow(c: Canvas, cx: Float, cy: Float, r: Float, color: Int, relDeg: Float, now: Long) {
        val len = r * 0.70f
        val breath = 0.5f + 0.5f * sin(now / 1.4e9 * TWO_PI).toFloat() // slow glow pulse

        c.save()
        c.rotate(relDeg, cx, cy)
        path.reset()
        path.moveTo(cx, cy - len)
        path.lineTo(cx + len * 0.36f, cy + len * 0.24f)
        path.lineTo(cx, cy + len * 0.04f)
        path.lineTo(cx - len * 0.36f, cy + len * 0.24f)
        path.close()

        paint.style = Paint.Style.STROKE
        paint.strokeJoin = Paint.Join.ROUND
        for ((widthDp, alpha) in GLOW) {
            paint.strokeWidth = dp(widthDp)
            paint.color = withAlpha(color, (alpha * (0.65f + 0.35f * breath)).toInt())
            c.drawPath(path, paint)
        }

        paint.style = Paint.Style.FILL
        paint.shader = LinearGradient(
            cx, cy - len, cx, cy + len * 0.24f,
            lighten(color, 0.30f), darken(color, 0.25f), Shader.TileMode.CLAMP,
        )
        c.drawPath(path, paint)
        paint.shader = null

        // A thin dashed-looking beam from arrow tip to the ring, so eye travels to the dot.
        paint.style = Paint.Style.STROKE
        paint.strokeWidth = dp(1.5f)
        paint.color = withAlpha(color, 0x60)
        var d = len + dp(10f)
        while (d < r - dp(14f)) {
            c.drawLine(cx, cy - d, cx, cy - min(d + dp(6f), r - dp(14f)), paint)
            d += dp(12f)
        }
        c.restore()
    }

    private fun drawArrival(c: Canvas, cx: Float, cy: Float, r: Float, color: Int, now: Long) {
        val phase = ((now / 1_000_000L) % PULSE_MS) / PULSE_MS.toFloat()
        paint.style = Paint.Style.STROKE
        for (k in 0 until 3) {
            val p = (phase + k / 3f) % 1f
            paint.strokeWidth = dp(1f) + dp(3f) * (1f - p)
            paint.color = withAlpha(color, (210 * (1f - p)).toInt())
            c.drawCircle(cx, cy, r * (0.12f + 0.62f * p), paint)
        }
        paint.style = Paint.Style.FILL
        paint.color = withAlpha(color, 0x50)
        c.drawCircle(cx, cy, dp(22f), paint)
        paint.color = color
        c.drawCircle(cx, cy, dp(11f), paint)
        animating = true
    }

    private fun drawSpinner(c: Canvas, cx: Float, cy: Float, radius: Float, now: Long) {
        val sweepStart = ((now / 1_000_000L) % 1400L) / 1400f * 360f
        arcRect.set(cx - radius, cy - radius, cx + radius, cy + radius)
        paint.style = Paint.Style.STROKE
        paint.strokeWidth = dp(3f)
        paint.strokeCap = Paint.Cap.ROUND
        paint.color = ACCENT
        c.drawArc(arcRect, sweepStart, 100f, false, paint)
        paint.color = 0x30FFFFFF
        c.drawArc(arcRect, sweepStart + 180f, 100f, false, paint)
        animating = true
    }

    // ---- text block -------------------------------------------------------------------------

    private fun drawStatus(c: Canvas, x: Float, y: Float, titleRes: Int, hintRes: Int) {
        textPaint.typeface = labelTypeface
        textPaint.textSize = sp(22f)
        textPaint.color = Color.WHITE
        c.drawText(context.getString(titleRes), x, y, textPaint)
        textPaint.typeface = Typeface.DEFAULT
        textPaint.textSize = sp(14f)
        textPaint.color = 0x90FFFFFF.toInt()
        c.drawText(context.getString(hintRes), x, y + dp(26f), textPaint)
    }

    private fun drawDistanceBlock(c: Canvas, x: Float, y: Float, m: Marker, distance: Float, arrived: Boolean, fix: Location) {
        textPaint.typeface = displayTypeface
        textPaint.textSize = sp(56f)
        textPaint.color = Color.WHITE
        c.drawText(if (arrived) context.getString(R.string.status_here) else Geo.formatDistance(distance), x, y, textPaint)

        textPaint.typeface = labelTypeface
        textPaint.textSize = sp(18f)
        textPaint.color = m.color
        c.drawText(m.name, x, y + dp(32f), textPaint)

        val accuracy = if (fix.hasAccuracy()) fix.accuracy.roundToInt() else null
        val subline = when {
            arrived -> context.getString(R.string.status_within, Geo.arrivalRadius(fix).roundToInt())
            else -> {
                val parts = ArrayList<String>(2)
                Geo.walkMinutes(distance)?.let { minutes ->
                    parts += if (minutes < 60) context.getString(R.string.walk_minutes, minutes)
                    else context.getString(R.string.walk_hours, minutes / 60, minutes % 60)
                }
                accuracy?.let { parts += context.getString(R.string.status_accuracy, it) }
                parts.joinToString(" · ")
            }
        }
        textPaint.typeface = Typeface.DEFAULT
        textPaint.textSize = sp(14f)
        textPaint.color = 0x90FFFFFF.toInt()
        c.drawText(subline, x, y + dp(56f), textPaint)
    }

    // ---- touch ------------------------------------------------------------------------------

    override fun onTouchEvent(event: MotionEvent): Boolean {
        when (event.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                downX = event.x
                downY = event.y
                return true
            }
            MotionEvent.ACTION_UP -> {
                if (hypot(event.x - downX, event.y - downY) <= touchSlop) {
                    val hit = dots.minByOrNull { hypot(it.x - event.x, it.y - event.y) }
                    if (hit != null && hypot(hit.x - event.x, hit.y - event.y) <= dp(28f)) {
                        onMarkerTapped?.invoke(hit.id)
                        performClick()
                    }
                }
                return true
            }
        }
        return super.onTouchEvent(event)
    }

    override fun performClick(): Boolean = super.performClick()

    // ---- colour helpers ---------------------------------------------------------------------

    private fun withAlpha(color: Int, alpha: Int) = (color and 0x00FFFFFF) or (alpha.coerceIn(0, 255) shl 24)

    private fun lighten(color: Int, amount: Float) = blend(color, Color.WHITE, amount)
    private fun darken(color: Int, amount: Float) = blend(color, Color.BLACK, amount)

    private fun blend(from: Int, to: Int, t: Float): Int = Color.argb(
        255,
        (Color.red(from) + (Color.red(to) - Color.red(from)) * t).roundToInt(),
        (Color.green(from) + (Color.green(to) - Color.green(from)) * t).roundToInt(),
        (Color.blue(from) + (Color.blue(to) - Color.blue(from)) * t).roundToInt(),
    )

    private companion object {
        val ACCENT = 0xFFFF6B2C.toInt()
        val AMBER = 0xFFFFC53D.toInt()
        val CARDINALS = arrayOf("N", "E", "S", "W")
        /** Stroke width (dp) and alpha for the arrow's layered glow, widest first. */
        val GLOW = listOf(26f to 28f, 16f to 50f, 8f to 90f)
        const val PULSE_MS = 1800L
        const val TWO_PI = 2.0 * Math.PI
    }
}
