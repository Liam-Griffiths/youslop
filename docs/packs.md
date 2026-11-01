# Making a Corkbored pack

A pack is a folder of content. It can add themes (coordinated channel colours
and card choices), blocks (reusable scene templates), music beds, confirmed 3D
models and fonts. No account, store or network connection is needed.

```text
my-pack/
  pack.json
  themes/signal.json
  blocks/title/block.json
  blocks/title/block.html
  music/bed.wav
  music/credits.json
  models/object/model.glb
  models/object/manifest.json
  fonts/Example.ttf
  preview.jpg
```

Only `pack.json` is required. Omit kinds you do not supply. `preview.jpg` is an
optional 1280×720 cover. Model folders use the existing library layout and need
`confirmed: true` in their manifest. Music accepts mp3, wav, m4a, flac, aac and ogg;
fonts accept woff2, ttf and otf.

The manifest is a JSON object:

```json
{"id":"my-pack","name":"My pack","version":"1.0.0","author":"Your name",
 "licence":"GPL-3.0-or-later","licence_url":"","corkbored":">=1.0",
 "description":"A theme and title card for essays."}
```

`id`, `name`, `version`, `author` and `licence` are required nonempty strings.
The id must match the folder name and `^[a-z0-9][a-z0-9-]{1,47}$`.
`licence_url`, `corkbored` and `description` are optional strings; `corkbored` is
informational compatibility metadata, currently not a version gate. Use numeric
release versions such as `1.0.0` (optional prerelease/build suffixes) for builds
and upgrades. Unknown manifest fields are ignored.

Themes have the same fields as `app/themes.py`: four hex colours, label, audience
(`for`), blurb, grade, icons, pattern, light flag, frame overrides and default
intro/thumb/outro choices. References are `my-pack/signal`, `my-pack/bed.wav`,
`my-pack/object` and `pack/my-pack/title` for blocks. Card choices prefix the
block reference with `scene:`. Pack fonts are available in template context as
`fonts["pack:my-pack/Example.ttf"]` with a scoped `/fonts/packs/` URL.

Scenes use `blocks/<id>/block.json` and `block.html`, not a `scenes/` folder.
Follow the [block authoring guide](blocks/format.md) and
[scene builder contract](scene-builder.md): extend `_base.html`, put content in
`head` and `body`, declare `data-layer`, `data-start`, `data-duration` and
`data-motion`. The builder captures layers and compiles motion in ffmpeg.
The [original scene contract](tickets/02-scene-engine/T2.2-scene-runtime.md)
explains composition roots and seeking; packs use its sandboxed block subset.
No scripts, custom Jinja functions or arbitrary includes are allowed. Declare
local resources in block metadata. Prefer one layer per panel or line.

Packs cannot contain Python, JavaScript, shell scripts, executables, symlinks or
special files. Templates cannot access the network or run arbitrary code.
The sandbox validates template syntax, HTML tags, attributes and asset paths;
all assets must stay inside the block folder or use permitted bundled font URLs.
Manifest/security errors disable the pack. Invalid individual items are reported
and hidden while good items remain available; check/build reject either kind of
problem so an archive never silently ships a broken item.

Keep rights and source information with your content. The manifest describes the
pack licence; each block also declares its licence. Include font/model licence
notices beside those assets. `music/credits.json` maps each filename to a JSON
object with `title`, `artist`, `licence` and `url` strings. These track credits
flow into video description credits. You must have permission to distribute
all included content. Templates extending the app's base files are GPL like
the app for now; this may change after an owner licensing decision. The app's
licence headers have not been changed. Other assets retain their own licences.

## Complete small example

From the repository root, set a disposable data directory **before** running
Python. The scaffold creates a complete block with metadata and a builder layer:

```sh
export CORKBORED_DATA="$(mktemp -d)"
mkdir -p "$CORKBORED_DATA/drafts/my-pack/themes" "$CORKBORED_DATA/drafts/my-pack/blocks"
.venv/bin/python -m app.cli block new title
cp -R "$CORKBORED_DATA/blocks/title" "$CORKBORED_DATA/drafts/my-pack/blocks/title"
cat > "$CORKBORED_DATA/drafts/my-pack/pack.json" <<'JSON'
{"id":"my-pack","name":"My pack","version":"1.0.0","author":"Your name","licence":"GPL-3.0-or-later"}
JSON
cat > "$CORKBORED_DATA/drafts/my-pack/themes/signal.json" <<'JSON'
{"key":"signal","label":"Signal","for":"Essays","blurb":"Orange on charcoal",
 "accent":"#FF5A1F","accent2":"#6FB7FF","ground":"#0E0F11","ink":"#F2F2F2",
 "grade":"neutral","icons":[],"pattern":"icons","light":false,"frame":{},
 "intro":"columns","thumb":"banner","outro":"scene:outro_twoup"}
JSON
.venv/bin/python -m app.cli pack check "$CORKBORED_DATA/drafts/my-pack"
.venv/bin/python -m app.cli pack build "$CORKBORED_DATA/drafts/my-pack"
```

Check prints problems and exits 1 on failure. Otherwise it writes one midpoint
PNG per block/aspect to `.check/` (480×270 landscape, 270×480 portrait, 270×270
square) using the scene still-preview path. It does not encode clips. Inspect
those images for typography and layout; static lint cannot judge the design.
Use `--static-only` on check/build for browser-free validation; it explicitly
skips previews. Browser failure fails the default check/build.

Build runs check first, then writes `my-pack-1.0.0.corkboredpack` beside the folder.
It refuses to overwrite an existing archive. The zip has one top-level id folder;
`.check/` and all dotfiles/directories are excluded. Source security validation
still examines hidden files. Install the archive with Settings → Packs → Install
pack, or drop it onto the app window. For local iteration you can instead copy
the folder to `$CORKBORED_DATA/packs/my-pack` and press Rescan in Settings.
Items appear with the pack name appended. Installed packs are read-only content;
edit the draft, bump its version, rebuild, and confirm replacement in Settings.
The old version is retained under `packs/.old/`.

The bundled `packs/starter/` is an initial draft for the owner to refine: one
Signal theme and cold-open, chapter-card and end-card blocks, landscape only.
It ships without music or models. Built-in packs cannot be removed, replaced or
shadowed by installed packs.
