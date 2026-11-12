# Corkbored website

The public site: a static Next.js export in `site/` only. This is the one place
in the repository that uses Node, an owner-approved exception (see
`docs/tickets/19-website/README.md`). The app itself keeps its no-Node rule:
nothing outside `site/` imports from here or runs npm.

## Commands

```sh
cd site
npm ci            # install exact versions from package-lock.json
npm run dev       # local dev server
npm run build     # static export to site/out/ (no server output)
```

Media and fonts are built ahead of time with Python, from the repo root:

```sh
.venv/bin/python site/tools/build_images.py
uv run --no-project --with fonttools --with brotli python site/tools/build_fonts.py
```

## How images work

- **Sources.** Screenshots live in `site/media-src/*.png`.
- **Building.** `build_images.py` writes AVIF and WebP copies at 480, 768, 1080, 1440 and 1920 px
  wide (never upscaled) into `site/public/media/`. Each file name carries a short
  content hash, so the files are cached as immutable (`vercel.json`). It also writes
  `site/lib/media-manifest.json`.
- **Serving.** `next/image` uses the custom loader in `lib/image-loader.ts`, which picks the
  nearest pre-built width. `<Shot>` wraps it in `<picture>` with AVIF first. Nothing
  goes through `/_next/image`, so Vercel's image optimizer is never used.

## Environment

| Variable | Default | Use |
|---|---|---|
| `NEXT_PUBLIC_MEDIA_BASE` | `/media` | Where images (and later the trailer) are served from. Set it to a CDN URL and upload `public/media/` there to move media off Vercel; no code changes. |

## Content rules

- **Copy.** Plain and short, with no claims beyond what has shipped (see
  `docs/tickets/PROGRESS.md`).
- **Names.** The product name and URLs come from `lib/brand.ts`, which mirrors
  `app/brand.py`.
- **Screenshots.** They come from the running app with the bundled example project. T19.2 makes
  this one command; until then `media-src/` holds interim 1x captures.
