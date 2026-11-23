# Android app (v0.11.0)

Native Kotlin + Jetpack Compose app for the PBL5 gateway. No IP address to type:

1. Probes in parallel the last home address, the backup network `10.42.0.1:8000` and the Internet address the Pi reports (`PUBLIC_URL`, Cloudflare Tunnel, ADR 0008); switches between them when the phone changes network, without a new sign-in.
2. Otherwise finds the Pi on the Wi-Fi network by mDNS (`_pbl5._tcp`, advertised by `gateway/pbl5.avahi.service`), or takes an address typed by hand.
3. First setup with the code on the Pi's label, sign-in, or sign-up (waits for an admin), as in [ADR 0007](../docs/adr/0007-user-accounts.md).
4. Scans the label on the Pi: the setup code fills the first-setup form; the Wi-Fi code joins `SmartAC-Backup` from inside the app (Android 10+).
5. Room readings and chart, power, temperature, mode and fan, resend / report the real state, comfort votes and suggestion; guests are read only. Admins approve and manage members and switch the Pi network mode. The session token is kept in `EncryptedSharedPreferences`.

6. Background check every 15 minutes (WorkManager): notifies when a node goes offline, when accounts wait for approval, and when the room is hot.

7. Admins detect and switch the AC's IR protocol ("Điều hòa trong phòng"), test it and confirm it works.

## Build

CI builds `app-debug.apk` on every push (job `android`, artifact `pbl5-app`) and attaches it to the GitHub release when a `v*` tag is pushed. Locally, with Android Studio or the Android SDK and Gradle 8.11:

```bash
gradle -p android assembleDebug
adb install -r android/app/build/outputs/apk/debug/app-debug.apk
```

`app/debug.keystore` is a shared debug key, not a secret: APKs from CI and from any laptop install over each other without losing the sign-in.

## Planned

- Instant notifications would need a push service (Firebase); the current check runs every 15 minutes.
- Home-screen widget.
