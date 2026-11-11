# Phase 19: the public website

Owner, 2026-11-11: "rebuild the landing page. I want it light and friendly.
Simple with minimal claims, just features and download link (a page with all
the releases). I want screenshots of the running app and a cool video
demo/trailer for the website, keep it webm for bandwidth costs. Use next.js as
we'll be targeting Vercel too. I might use BunnyCDN for low cost bandwidth, so
optimize next image for either option. I don't want Vercel to get expensive if
people like this product. I want Claude Opus 5.5 to work on this. Use
https://hyperframes.studio/ as inspiration but stay true to our design style.
We can schedule this work last as it'll use up lots of our Claude usage."

## Who works it
**Claude Opus 5.5, not Codex.** This phase is scheduled last, after every
other open ticket. Each ticket is a separate session. Say before starting
one, because they spend a lot of Claude usage.

## Where it lives, and the Node exception
The site is a separate project in `site/` at the repo root. The owner chose
Next.js, which needs Node. That is an **owner-approved exception that applies
only inside `site/`**:
- The app (`app/`, `static/`, `resources/`, `tests/`) keeps the no-Node,
  no-build-step rule unchanged.
- Nothing outside `site/` may import from it, call `npm`, or depend on
  `site/node_modules`.
- The app's test suite and packaging (`corkbored.spec`) must not see `site/`.
- Tools that capture app media (screenshots, trailer footage) are Python
  scripts under `site/tools/`. They drive the real app through the existing
  headless Chromium path (`app/stage.py`), not Puppeteer or Playwright-for-Node.

`static/landing.html` stays as it is. It's the in-app holding page and is
retired only once the new site is deployed and the owner says so.

## Cost model: nothing heavy goes through Vercel
The owner wants the site to stay cheap if it gets popular. Every decision
below follows from that.
1. **Static export.** `output: 'export'`. No serverless functions,
   middleware or ISR. Vercel serves only the small HTML, JS and fonts. The
   same `out/` folder could move to any static host later.
2. **No Vercel Image Optimization.** `next/image` uses a custom `loaderFile`.
   Image widths (AVIF and WebP) are generated ahead of time by a Python tool
   using Pillow. The loader picks the nearest pre-built width. No setting
   ever routes through `/_next/image`.
3. **Media comes from GitHub** (owner, 2026-11-11: "let's actually have the
   images come from github"). This covers screenshots, the trailer WebM and
   its poster.
   - **Storage:** an orphan branch `site-media` in this repo, so binary media
     never enters `dev`'s history. `site/tools/publish_media.py` commits the
     built files there and records the commit SHA in
     `site/lib/media-manifest.json`.
   - **Delivery:** through jsDelivr's GitHub endpoint, pinned to that commit:
     `https://cdn.jsdelivr.net/gh/Liam-Griffiths/youslop@<sha>/media/<file>`.
     - jsDelivr serves correct MIME types, a real CDN and immutable caching
       for pinned URLs, at no cost.
     - Don't use `raw.githubusercontent.com`. It isn't a CDN, is rate
       limited, sends `nosniff` headers with generic types (which can block
       images and video in browsers), and GitHub discourages hotlinking it.
   - **Limits:** jsDelivr's GitHub endpoint caps each file at 20 MB, so
     keep the trailer under 8 MB. Both routes need the repo to be
     **public**. Until it is, `npm run dev` serves the same files from the
     local `site/public/media/`.
   - **One switch:** `NEXT_PUBLIC_MEDIA_BASE` holds the base URL. It
     defaults to the pinned jsDelivr URL in production and `/media` in dev.
     Moving to Bunny or anywhere else later only changes this value.
4. **Downloads come from GitHub Releases** (owner, 2026-11-11). Binaries are
   release assets; the site only links to them.
5. **Lazy media.** The trailer uses `preload="none"` with a small poster
   until it scrolls into view. Below-the-fold screenshots load lazily.

## Design: true to the brand, in its light register
- Use the light palette the 2026-10-25 landing page already tested
  (`docs/roadmap.md`, "Landing page"):
  - paper `#F4F2EE`, near-black ink `#0B0B0B`, dim `#6B6862`, rules
    `#D6D2CA`;
  - signal orange `#E84A12` for accents and the one primary button.
- Type:
  - the Archivo condensed wordmark (62 % width, 800);
  - Inter for prose;
  - JetBrains Mono for small labels.
  - Self-host from `resources/fonts` (copied into `site/public/fonts`; all
    OFL). No Google Fonts request.
- "Friendly" means generous spacing, rounded 10–14 px cards, real app
  screenshots in soft-shadowed frames, and plain warm copy. It does not mean
  cartoon illustrations, gradients, emoji or exclamation marks.
- Take only **structure** from hyperframes.studio:
  - a short hero with one OS-detected download button plus "Other platforms";
  - a "Get started" panel that lists every platform build;
  - a lean nav (Features, Download, Releases, GitHub);
  - very little copy.

  Don't take its colours, type or layout, and avoid the warm parchment and
  serif display it uses (see `docs/roadmap.md` on looking derivative).
- **Minimal claims.**
  - No stats, testimonials, "best", "AI-powered" or speed promises.
  - Features are stated as what you can do, in one line each, and each one is
    shown by a real screenshot.
  - Copy voice follows Phase 18: plain, natural sentences, no teasers or
    hype.
- Read the product name and site URL from one `site/lib/brand.ts` that
  mirrors `app/brand.py` (`NAME`, `SITE_URL`). Don't hard-code the name in
  components.

## Tickets
| | |
|---|---|
| T19.1 | Site scaffold: Next.js static export, design, features and image pipeline |
| T19.2 | Screenshots and a WebM trailer from the running app |
| T19.3 | Download and releases pages from GitHub Releases, and deploy to Vercel |
