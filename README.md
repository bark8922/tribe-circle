# tribe-circle

Standalone hosting for the **Circle** hiring overview, iframed into `overview.tribe.xyz/circle_1`.

Auto-refresh runs via `.github/workflows/refresh.yml` every 2 hours: pulls live data from tribe-recruiting, runs `build_circle_data.py`, pushes a fresh `circle_data.json`. Cloudflare Workers auto-deploys on push.

URL pattern for the iframe:
```
https://tribe-circle.tribe-bamboohr.workers.dev/
  ?member={Current User's Email}
  &first_name={Current User's First Name}
  &admin=1   (only for blake@tribe.xyz and martin@tribe.xyz)
```

Tribe weeks are Mon-Sun, ISO-aligned. 2026W20 = Mon May 11 - Sun May 17.
