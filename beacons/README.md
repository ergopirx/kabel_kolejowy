# Beacons

A tiny Android app that remembers where you were and always points you back.

Stand somewhere, tap **Drop a beacon here**, give it a name and a colour. From then on, wherever
you wander, a big glowing arrow points at it and tells you how far away it is. Drop as many as
you like: every beacon sits on the compass ring as a coloured dot in its true direction, growing as
you get closer, and tapping a dot or a chip makes it the one the arrow follows. Walk up to a beacon
and the arrow dissolves into a pulsing target, the phone buzzes once, and the display says **Here**.

## What it does

- **Drop a beacon** at your current GPS position, with a name and one of eight colours. The dialog
  shows the fix accuracy so you know how precise the pin is.
- **Compass ring** that turns with your heading. North is marked in orange, your facing direction
  is the fixed white index at the top, and the readout above shows `237° SW`.
- **One dot per beacon** on the ring in its real direction, sized by distance (log scale: 50 km is a
  pinprick, a few metres fills the dot).
- **Arrow + distance** for the selected beacon: a gradient arrow with a breathing glow, the
  distance in big type (`240 m`, `2.4 km`), a rough walking time and the GPS accuracy.
- **Arrival**: within the fix's accuracy (8 to 30 m) the arrow becomes expanding rings, the phone
  vibrates once, and the readout says *Here*.
- **Chips** along the bottom, one per beacon, showing live distance. Tap to select, long-press to
  rename, recolour, *Move here* (re-pin to where you stand) or delete.
- Beacons persist across restarts. Screen stays on while the app is open.
- Works with the phone flat, upright or anywhere in between: the heading is derived from both the
  screen's up-axis and the phone's back-axis, so there is no tilt threshold to flicker across.

## How it is built

No third-party libraries at all. Framework-only Kotlin:

| Piece | How |
| --- | --- |
| Position | `LocationManager` (fused provider on Android 12+, GPS + network before that) |
| Heading | `TYPE_ROTATION_VECTOR`, remapped for screen rotation, corrected with `GeomagneticField` declination, smoothed on the unit circle so the arrow never swings the long way round across north. Falls back to accelerometer + magnetometer, then to GPS course. |
| Drawing | One custom `View` (`CompassView`) painting the ring, dots, arrow and text on a `Canvas` |
| Storage | A JSON array in `SharedPreferences` |

The result is a single small APK with three permissions: fine location, coarse location, vibrate.

```
app/src/main/java/com/ergopirx/beacons/
  MainActivity.kt   screen, chips, dialogs, permissions, haptics
  CompassView.kt    all the drawing
  Navigator.kt      location + heading
  Marker.kt         model and persistence
  Geo.kt            distance/bearing maths and formatting
```

## Building

Open the `beacons/` folder in a current Android Studio (any release that supports AGP 8.13, i.e. Narwhal 3
Feature Drop 2025.1.3 or newer) and run, or from a terminal with
the Android SDK installed:

```bash
cd beacons
./gradlew assembleDebug
# APK: app/build/outputs/apk/debug/app-debug.apk
adb install app/build/outputs/apk/debug/app-debug.apk
```

Requires Android 8.0 (API 26) or newer. The release build type is configured with R8 shrinking
but has no signing config; add your keystore before publishing.

## Notes on accuracy

- A phone compass is good to roughly 5 to 10 degrees. If the readout at the top turns amber and
  asks you to calibrate, wave the phone in a figure of eight away from metal.
- The first GPS fix can take a minute outdoors. Indoors the app may show the last network-based
  position, which can be off by tens of metres; the `±` figure under the distance tells you.
- Arrival is declared inside the fix's accuracy radius, never tighter than 8 m, so jitter does not
  make the target flicker on and off.
