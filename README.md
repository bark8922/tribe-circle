# tribe-circle

Standalone hosting for the **Circle** hiring overview page, iframed into `overview.tribe.xyz/circle`.

Lives on Cloudflare Pages, NOT behind Cloudflare Access (intentionally, so the iframe loads cleanly inside overview without an auth challenge). Per-user data isolation is handled in the page itself via the `?member=` URL parameter passed by Bubble.

## Files

- `index.html` / `circle.html` — same content, both serve the page (index.html is the default Cloudflare Pages entry)
- `circle_data.json` — per-pilot snapshot (5 recruiters × this/last week × 3 metrics) regenerated from the main recruiting dashboard pipeline
- `build_circle_data.py` (in [tribe-recruiting/recruiting-dashboard/refresh_staging](https://github.com/bark8922/tribe-recruiting/tree/main/recruiting-dashboard/refresh_staging)) — the generator script

## URL pattern (iframe src on overview)

```
https://tribe-circle.pages.dev/?member={email}&first_name={first name}&admin=1
```

`admin=1` only for blake@tribe.xyz and martin@tribe.xyz.
