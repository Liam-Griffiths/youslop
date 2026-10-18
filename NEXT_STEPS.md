# Next steps

Suggestions, roughly in the order I'd do them. Each one says why it is worth
doing and where the work actually lands, because the reason is the part that
rots first.

## 1. Re-measure the render's memory cap

`render.render()` throttles the segment pool on free memory:

```python
workers = max(1, min(workers, int(free_mb // 5000)))
```

The 5000 came from measuring ~3.5–5GB of RSS per ffmpeg, and most of that was
an essay segment re-decoding a 1080p caption PNG for every output frame. That
no longer happens — stills are decoded once and held by the `loop` filter (see
`HOLD_STILL` in `render.py`) — so the divisor is now almost certainly far too
conservative and a 16GB machine is rendering three segments at a time when it
could run six.

Measure one essay segment's peak RSS (`/usr/bin/time -v`, or watch
`status.VmHWM`), then set the divisor from what you see. This is the cheapest
remaining win on total render time.

## 2. Make the drawn formats as cheap to preview as the photographic ones

A quarter-res preview costs 1.7–5.2s for the documentary and essay cuts and
**13.5s** for the board cut, because `board.frames()` and
`custom_slide.frames()` draw every frame in Pillow at 1080p and the preview
only scales the result on the way into the encoder (`render._reframe`).

Two ways out, in increasing order of work:

- **Draw at preview scale.** The layouts are in 1080p pixels, so this means
  threading a scale factor through `board.py`/`diagram.py`/`custom_slide.py`,
  or drawing at 1080p and `.resize()`-ing each frame before the pipe — the
  latter is a two-line change and still halves the compositing cost.
- **Cache settled frames.** `board.frames()` already folds finished beats into
  a base image; a board that is fully drawn for the last 40% of its segment is
  yielding an identical frame hundreds of times. Yield it once and let ffmpeg
  hold it, the same trick the stills now use.

## 3. Chapter cards for the drawn cuts

`render._render_segment` draws a chapter card for any format that composes its
picture in the filtergraph. The board and designed-slide cuts return earlier
than that, so a chapter marked in those formats still opens its own slide and
its own long pause, but no card appears. Either draw the card into the frame
stream in `board.py`, or compose it over the encoded segment in a second pass.
Worth doing — a handwritten-board video is exactly the kind that wants visible
section breaks.

## 4. A few tests, aimed at the render

There is no test suite. The risky changes in this codebase are all in the same
shape: a filtergraph edit that silently moves a pixel or a second. Three cheap
tests would have caught everything I had to check by hand:

- **Graph golden tests.** `_render_segment` builds a filtergraph string; snapshot
  it for a documentary, an essay and a preview-size segment. No ffmpeg needed,
  runs in milliseconds, and catches "I changed the card feed and the fades
  moved."
- **Timing invariants.** `_slide_durations` + `_picture_groups` + `paragraph_gaps`
  against a fixture project: assert the voice offset inside a segment is `T/2`
  (+ `HEAD_PAD` on the first), which is the arithmetic `preview_segment`
  depends on and nothing currently guards.
- **One SSIM test.** Render a 3-second segment and compare against a committed
  reference at SSIM > 0.99. Independent encodes of identical frames land around
  0.998, so the threshold is safe and the test is the only one that would catch
  a real visual regression.

## 5. Finish the standalone-video story

A video with no channel can now open on a type-led slate and close on an end
card, both drawn from its own title and colours. What is still channel-only:

- **A sting for the opening.** `IntroSpec.music` is resolved against
  `channel_dir()`, so a standalone slate is silent. Resolving it against the
  project directory when `channel_id` is empty would be a small change in
  `render._audio_graph`'s sting branch and `intro.sting_chain`.
- **Promotion.** Filing a standalone video into a channel (the picker on the
  Render tab) moves where its opening comes from, but does not offer to adopt
  the channel's look, voice or narrator the way `schema.new_project` does at
  creation. A "take the channel's look too?" prompt would close that gap.
- **The thumbnail** still defaults to `banner` rather than following whatever
  the video's own theme picked.

## 6. Make the video list searchable rather than just reordered

Standalone videos now sit above the channel lists, with a sidebar link and a
count — fine while there are a dozen. The next thing it needs is a filter:
free-text over title and idea, plus status ("needs recording", "rendered"),
either on the home page or as a real `#/videos` route. `store.list_projects()`
already returns everything the filter would need.

## 7. Propose chapter marks instead of waiting to be told

Chapters are marked by hand on the Script tab. The script already carries the
structure to guess from: `slide.section` changes (intro → main → conclusion)
and `slide.beat` changes mark exactly the places a chapter usually starts. A
"suggest chapters" button that pre-fills marks at those boundaries — and that
the creator then edits or deletes — would make the feature usable on a
36-paragraph script without 36 decisions.

## 8. Longer-horizon

- **Caption rendering.** Essay captions are a PNG per phrase through Pillow
  (`titles.render_caption`), re-rendered whenever the narration changes. A
  single sprite sheet, or ffmpeg's own `drawtext`, would cut both the disk
  churn and the input count on the segment graph.
- **`app.js` is 5,800 lines and `main.py` 2,400.** Both are still navigable, but
  the project tab painters (`paintScript`/`paintMedia`/`paintRecord`/
  `paintRender`) are self-contained enough to split into files without
  introducing a build step.
- **Resume a failed render.** Segments are rendered into `segments/` and thrown
  away on the next run (`shutil.rmtree`). Keeping them, keyed by a hash of what
  they were rendered from, would make a failed or cancelled render cheap to
  pick up — the same idea `draft` already applies to script generation.

## 9. Research missed a death (RJ Mitte run, 18 Oct 2026) — fixed, verify on a real run

**What happened:** a script about RJ Mitte praised his charity and campaign work
but never mentioned his death, which is documented widely (Bing News and
Wikipedia both have it, 12–16 Oct 2026). The project's research field was
empty: research found nothing and wrote without grounding, and nothing recorded
why.

**Causes found in the app log (`~/Library/Application Support/Youslop/logs/youslop.log`):**
- DuckDuckGo answered the burst of six queries with HTTP 202 (a bot challenge),
  which the scrape read as "no results". No retry, no fallback.
- In the dev checkout, `SEARXNG_URL` was set but the instance returned 403 to
  JSON requests, and `auto` never tried the next backend, so research silently
  stopped there too.

**Changes:** per-site pacing (DuckDuckGo 5s, Bing 3s, Wikipedia 1s), retry with
backoff on 202/429/503, a fallback chain (SearXNG → Brave → free scrape → Claude
search), DuckDuckGo + Bing News + Wikipedia search together, and the top
Wikipedia article read in full through its API every run.

**Still open:**
- Why the local SearXNG container returns 403 for `format=json` even though
  `searxng/settings.yml` lists `json` (likely the running container's config or
  its limiter; check after a restart).
- Failures are only logged to the app log, not to the project. A project whose
  research came back empty should say so in its own log.
- Verify on a real full run (script + Sources panel) that the death appears.
