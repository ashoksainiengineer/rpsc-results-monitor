# RPSC Results Monitor

`https://rpsc.rajasthan.gov.in/results` par jab bhi koi **naya result** aata hai,
turant phone par **push notification** (ntfy ke through) bhejta hai.

Ye GitHub Actions par har 15 minute chalta hai — tumhara laptop on ho ya off,
farak nahi padta. Sab kuch cloud me chalta hai.

## Kaise kaam karta hai

1. Page fetch karta hai aur results table parse karta hai (`monitor.py`).
2. Har result ka ek fingerprint `state.json` me save hota hai.
3. Jo row pehle nahi thi, wo "naya" maani jaati hai -> ntfy par notification.
4. Naya state wapas repo me commit ho jaata hai.

## Phone par subscribe karna

1. **ntfy** app install karo: Android (Play Store / F-Droid) ya iOS (App Store)
   ya browser se https://ntfy.sh kholo.
2. App me **+ → Subscribe to topic** karo.
3. Topic naam daalo: **`NTFY_TOPIC` secret wala naam** (repo owner ke paas hai).
4. Bas — ab har naya result tumhe phone par turant milega.

## Settings

- **Frequency**: `.github/workflows/rpsc-monitor.yml` me `cron` badal do.
- **Topic/server**: repo → Settings → Secrets and variables → Actions → `NTFY_TOPIC`
  (aur optional `NTFY_SERVER`).

## Local testing

```bash
# baseline banane ke liye (pehli baar)
python3 monitor.py --verbose

# notification bhej ke test karo
NTFY_TOPIC=your-topic python3 monitor.py --test

# dry run (state change nahi hoga)
python3 monitor.py --dry-run --verbose
```

## Manual run

Actions tab -> "RPSC Results Monitor" -> **Run workflow**.
