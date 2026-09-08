# Youslop

A local tool for making narrated informational videos — the kind where you talk
over archival photographs for 7 to 22 minutes about a person's life or an event
worth understanding.

You type an idea. Claude researches the shape of the story and writes a script in
paragraphs. The tool searches Wikimedia Commons and the open archives for a
picture to sit under each paragraph. You review both, record your voiceover one
paragraph at a time in the browser, and it cuts the whole thing together with a
slow Ken Burns move, a subtle vignette, lower-left chapter typography and a
ducked music bed.

Everything runs on your machine. Nothing is uploaded anywhere.

---

## Getting started

```bash
./run.sh              # first run creates .venv and installs dependencies
```

Then open <http://127.0.0.1:8420>.

### Recording from another machine

The Mac running this does the work; the machine with the good microphone only
needs a browser. Start the server so the network can reach it:

```bash
HOST=0.0.0.0 HTTPS=1 ./run.sh
```

It prints an address to open on the other machine, with an access token:

```
→ https://192.168.4.26:8420?t=205e7550873008f6f8a5a5ad   ← open this on the other machine
```

**HTTPS is not optional here.** Browsers only hand a microphone to a page served
over https or from localhost; over plain http to a LAN address there is no
microphone at all, and the Record tab says so rather than failing cryptically.
`HTTPS=1` writes a self-signed certificate into `.certs/` naming this machine's
current address — accept the browser's warning once on the other machine. If the
Mac's IP changes, the certificate is reissued on the next start.

**The token** is generated on first use, kept in `.token`, and required for
anything not coming from this machine, because everything the interface can do —
render, delete a project — is reachable by anyone else on the network. Opening
the printed link once sets a cookie and the address bar can go back to normal.
`VB_TOKEN=off` turns it off, `VB_TOKEN=something-of-your-own` fixes it.

macOS may ask whether to allow incoming connections the first time; that prompt
is about this server, and it has to be allowed for the other machine to connect.

**Or tunnel it instead.** With Remote Login on, the other machine can borrow the
port over ssh and see it as localhost, which browsers already trust — no
certificate, no token, nothing bound to the network:

```bash
ssh -N -L 8420:localhost:8420 you@the-mac      # run on the other machine
```

Then open <http://localhost:8420> there.

**Setting the microphone up.** **mic & voice…** on the Record tab opens the panel
where that is done: a picker listing every input on the machine (remembered per
browser, so the good mic stays selected), a meter on a real dBFS scale with the
reading zone marked, and an eight-second test read that is measured and reported
on in words — how far your voice gets clear of the room, how fast the room stops
answering, whether the gain is too hot. The other half of the panel is the voice
chain itself, previewed on that same test read so a change can be judged by ear
against a before and after rather than by reading a slider. Takes are uploaded to
the Mac and cleaned there — the recording machine needs nothing installed.

**Requirements**

| | |
|---|---|
| `ffmpeg` | `brew install ffmpeg` |
| Python | 3.11+ |
| `claude` | Claude Code CLI, signed in — **optional**, see below. Model calls go through your subscription, no API key needed. |
| Docker | **optional** — only for research grounding, see "Research and accuracy" below. |

### Running without Claude Code

Everything downstream of a script — searching the archives, recording, the
local AI voice, rendering, channels, themes, thumbnails — is plain Python and
`ffmpeg`, and none of it touches Claude. The one thing that does is turning an
idea into paragraphs, and right now that is the *only* way a script gets into
the tool — there is no manual "type your own paragraphs" flow in the UI. So
without `claude` on the machine:

- **Cannot**: create a project from an idea, import a pasted script (it still
  has to be segmented into paragraphs, and that step is a model call too),
  ask for a paragraph to be rewritten, get suggested thumbnail text, or get
  suggested cast for a channel's opening slate.
- **Can**: everything else, on a project that already has a script — search
  and pick pictures (`app/media/`, all the archives plus your own uploads and
  Library), record narration, use the local Kokoro AI voice (`app/tts.py`,
  a separate 82M-parameter model that runs on your CPU, nothing to do with
  Claude), render in either style, build channels with their slates, end
  screens and thumbnails, edit any paragraph's text or title by hand, and
  everything the credits/licensing tooling does.

`run.sh` starts either way and prints a note if `claude` is missing; the
script-writing calls themselves (`app/llm.py`) raise a clear error naming the
problem — not installed, not signed in, or a spent usage limit — rather than
failing silently. `CLAUDE_BIN` in `.env` points at a specific binary if
`claude` is not on your `PATH`.

Optional, in a `.env` (copy `.env.example`):

```
PEXELS_API_KEY=…        # free — adds stock photos and video clips
PIXABAY_API_KEY=…       # free — same
NYPL_TOKEN=…            # free — NYPL Digital Collections
STORYBLOCKS_PUBLIC_KEY=…  STORYBLOCKS_SECRET_KEY=…    # paid
VB_USER_AGENT=youslop/1.0 (you@example.com)
```

Wikimedia Commons, the Library of Congress and the Met need no keys and are on
by default. **Set `VB_USER_AGENT` to something with your real contact address** —
Wikimedia asks automated clients to identify themselves.

Drop a few `.mp3`s into `assets/music/` for the background bed, then choose one in
the Render tab. A video starts on **none** and stays there until you say
otherwise: a bed is the one element you cannot miss on the way past, so nothing
selected means narration alone rather than whatever happened to be in the folder.
*Pick one for me* is there when you want the tool to choose — deterministically,
so re-renders keep the same track. Naming a track that has since been deleted
also renders silent, and says so in the log, rather than quietly substituting
another.

A bed shorter than the video **loops** to cover it and is trimmed to length, so a
five minute track carries a twenty-five minute video. The loop is a butt-join, so
a track that does not already loop cleanly will tick at each repeat.

---

## Channels

A channel is a series. Videos in one share a look and open on the same animated
slate, so the tenth video in a channel looks like it belongs with the first.

A channel holds:

- **A theme** — what kind of channel this is, below.
- **Identity** — name, tagline, and a description of what it covers. That
  description steers the scripts and the casting of the opening titles.
- **House look** — two colours, grade, vignette, crossfade, music level. New
  videos start from these rather than from the defaults, and can still diverge.
- **An opening slate** — the animated title sequence below.
- **An end screen** — the card every video finishes on, below.

### The theme

The house look began as one accent colour on black, which suits a history channel
and nothing else. A gaming channel is two loud colours over a third; a beauty
channel is printed on cream; a sports channel is a flag. So a channel is cast in
a **theme**, and a theme carries more than a colour:

- **Two colours** rather than one. The second is not decoration — the colourful
  templates are built on the pair, and patterns alternate between them.
- **A ground and an ink** — what those templates paint on and in. This is the
  part with no interface, because there is no good reason for a channel to
  diverge from it.
- **A set of icons**, which is what the patterns are tiled from. Controllers and
  pixel hearts, or lipsticks and droplets, or columns and hourglasses.
- **A slate, a thumbnail and an end screen** that were designed together.

Eight of them:

| Theme | For | Looks like |
|---|---|---|
| **Archive** | History, biography, essays | Warm gold on black. The default — and what every channel made before themes existed already looks like |
| **Arcade** | Gaming, streaming, tech culture | Hot pink and cyan over deep violet, controllers tiled behind everything |
| **Gloss** | Beauty, makeup, skincare | Blush and rose on a soft gradient, scattered with sparkles. Runs light |
| **Kickoff** | Sports, fitness | Electric green cut across navy on the diagonal, condensed italics |
| **Amp** | Music, podcasts, interviews | Orange into magenta, the channel name repeated as its own wallpaper |
| **Terminal** | Technology, science | Signal green on near-black, mono type, a circuit field |
| **Kitchen** | Food, craft, making things | Tomato and olive on warm paper, pots and leaves tiled behind. Runs light |
| **Broadcast** | News, analysis | Alert red on graphite with a halftone screen |

Applying a theme asks one question, because it is the only one that matters: take
its templates as well, or **just the colours**. A channel that has settled on a
slate can take a new palette without losing it. Either way the two colours are
written into the channel's own style from that moment, and can be edited under
House look afterwards — a theme is a starting point, not a cage.

**The patterns.** Two kinds, and both are drawn rather than pulled from anywhere.
An **icon field** tiles the theme's glyphs in brick-offset rows, rotated
off-square and printed faintly, which gives a flat colour something to be without
competing with type. A **word field** does the same with the channel's own name
repeated in rows, every other row set as an outline rather than a fill — the
older trick and the louder one, and the one that still reads as branding at the
120 pixels a thumbnail is actually looked at. There are forty-odd icons, drawn
with the same Pillow primitives as everything else, so a 26px one in a thumbnail
pattern and a 300px one on a slate come from the same code.

### The opening slate

Thirteen templates, picked from a strip of sketches on the channel page. Three are
cast-led and need portraits; the rest are type-led and work on a channel that has
never been cast. Each one answers to its own knobs, and the labels on the sliders
change with the template.

**Columns** — for lives and history. Columns of portraits fly in from the left,
staggered, on an ease-out. Once they land, a hairline accent rule separates them, a
scrim fades over the top, and the channel name resolves in the centre with the
video's own title beneath it.

The cast is a channel-level list. **Cast it for me** asks Claude for faces that
suit the series — briefed to spread across eras, fields and parts of the world, and
to favour people whose portraits are actually free to use. **Fetch portraits**
finds one image each and caches them on the channel, so every video reuses the same
faces and the sequence stays recognisable. Edit any name, add your own, re-fetch,
and give each portrait a focus point so the narrow columns don't crop a face.

Each face carries its own controls, so one bad portrait does not mean re-casting
the slate. **Change** searches for other pictures of that person and swaps in
whichever you pick — the search box starts on their name, because "Paderewski
portrait photograph" and "Ignacy Jan Paderewski 1900" find different pictures.
**Upload** takes your own image instead. **Remove** drops them entirely.

The four cast arrays — `subjects`, `images`, `focals` and `credits` — are one
table read by index, and every one of those operations moves all four together.
That is the whole reason removal is a server-side endpoint rather than a splice
in the browser: taking a name out of `subjects` alone slides every portrait after
it onto the wrong person. A subject nothing was found for holds an empty slot for
the same reason, rather than shortening the list.

**Dial** — for watches, and anything mechanical. A watch dial shot close and
pushed in on, with the title over it. The dial is bigger than the frame and
cropped by it, set off to the right so the type has somewhere of its own to be:
a sunburst face brushed radially in spokes rather than across, a chapter ring
with every fifth minute cut longer and heavier, applied batons doubled at twelve
and left out at three where the date aperture sits. It sits on a machined bench
— concentric turning marks struck from two centres, a pool of light, a vignette
— because a dial on flat black reads as a cut-out rather than a photograph.

The hands settle at **ten past ten**, where every watch in every advertisement
has stood for a century: it is the one position whose hands frame the maker's
name instead of striking through it. At any other hour the minute hand sweeps up
through the left of the frame and straight across the wordmark. The push-in runs
the whole slate rather than just the entrance, because a shot that arrives and
then holds still dies on the last second, and the seconds hand laps exactly once
— twice reads as a stopwatch, not at all reads as a photograph.

**Signal** — for technology. No portraits at all. The channel name is set as large
as the frame allows in SF Compact Black, left-aligned and stacked, and each line is
wiped in by a travelling accent bar that leaves the letters behind it. The frame
takes a two-frame RGB channel split as each line lands, a shine sweeps across once
the wordmark is complete, and an accent bloom breathes behind it so the hold never
goes dead. A rule down the left margin anchors the alignment, the tagline snaps in
above, and the video's own title fades in below. Line gap and wipe speed are
adjustable.

**Dossier** — for investigations. A file card rules itself in side by side,
clockwise; the metadata (a file number derived from the channel id, the subject,
"DECLASSIFIED") types itself out in mono under a blinking caret; and the channel
name, set in condensed caps, is uncovered by redaction bars that *slide off* the
type rather than wiping it in. A rubber stamp lands last, rotated off-square and
punched on with an overshoot, its ink eaten into by a noise mask. The bars are
lighter than the card, not darker — a true black bar is invisible on a black slate.

**Filmstrip** — for archive documentary. The cast is cut into one long piece of
film with punched perforations, and the whole strip runs past and decelerates to a
stop: grain, gate flicker and a couple of pixels of weave the whole way. Every frame
is a crop of a single pre-built strip image, which is what keeps it fast. When it
parks, a scrim fades up and two accent rules open outward from the centre to bracket
the name. How much film runs past, and how long it takes to stop, are the two knobs.

**Mosaic** — for ensembles. A grid of faces lands tile by tile in a shuffled order,
each tile dropping in slightly oversized and shrinking into place so the wall is
never seen through a gap. Cells are shuffled until no two neighbours hold the same
portrait; a second pass over a short cast is cropped lower and printed black and
white so a repeat reads as another plate; and at most a fifth of the wall goes to
numbered graphic blocks. Then the wall dims and a band opens across the middle
carrying the tagline, the name and the video title.

**Pulse** — for talk and music. The only motion on the type is letter-spacing:
the name opens wide and collapses to a set line, over a mirrored bar spectrum that
rises, spikes on the landing and settles to an idle. Two rules chase the type
outward and stop where it settles.

**Atlas** — for places. Drifting contour country under a graticule, crossed by a
reticle that scrambles its coordinates until it locks on. Then the reticle fades and
its corner brackets unfold sideways into two rules that hand the frame to the
wordmark, centred on its capitals rather than its em box.

**Folio** — for books and reading. The only slate that runs on cream rather than
black, which is most of why it reads as a book channel before a word of it is
legible. A sheet of stock turns in over the page beneath it — soft cast shadow, a
catch of light along the leading edge, no flash of black — and then the title page
sets itself in reading order: rules, small-caps kicker, the name in Baskerville
centred on a title-page measure, a lozenge ornament, the video's own title in
italic, and a roman folio at the foot. The channel accent is printed at half
strength, because a colour mixed for a black slate vanishes into paper.

Those eight are the archive-era slates: one accent colour on black. The five
below are **theme-led** — they read the theme for a second colour, a ground and a
set of icons, so the same template opens a gaming channel and a food channel
quite differently. They are also the colourful ones.

**Arcade** — for gaming. A cabinet attract screen. A field of the theme's icons
scrolls under everything and never stops, because an arcade screen that holds
still looks broken; the wordmark drops in line by line on an ease that lands past
the mark and settles back, carrying a hard shadow in the *second* theme colour
rather than a black blur — which is what makes it read as a decal instead of a
title. Scanlines over the whole frame, two frames of RGB split as the last line
lands, and the tagline blinks on a duty cycle that reads as neon rather than a
fault.

**Gloss** — for beauty and fashion. Nothing here slams. Soft radial light with
the theme's sparkles and droplets tiled over it, the name set in small caps and
widely tracked, and one sweep of gloss that travels across *the letters* rather
than across the frame — the highlight is masked to the wordmark's own alpha.
Sparkles keep twinkling long after everything else has settled, and they are
always white: the theme ink on a blush ground reads as a speck of dirt.

**Kickoff** — for sport. Diagonal bands slam in from both edges, then a slanted
panel slides over them carrying the type. Bands alone are unreadable — condensed
white caps on a field of stripes is a test card, not a title — so the stripes are
the border treatment and the panel does the work, which is how a broadcast lower
third has always solved the same problem. Everything shares one slant, including
the letters and the video title's bar, and a number pulled off the channel id
sits ghosted inside the panel.

**Stack** — for music and talk. No pictures and no icons: the channel name
repeated across the whole frame in stepped rows, half of them outlined, travelling
slowly sideways. A band opens across the middle and sets the name once, properly,
in the clear. The most literal answer to "make the type the artwork".

**Tiles** — for food, craft and making. A wall of icon tiles, alternating between
the two theme colours, flips over one by one in a shuffled order — the flip is a
vertical squash through zero and back out — to uncover a plate carrying the name.
Works on the paper themes as well as the ink ones.

The display size is fitted to the frame rather than fixed, so a short channel name
is set enormous and a long one steps down — "Humanoid Future" lands at 300px across
two lines in Signal.

**Previewing one** puts a placeholder where the video will be, at the video's
own aspect so the panel does not jump, with the renderer's own last line under
it — "Arcade slate rendered: 9.0s, wordmark at 226px" — and a running count
while there is nothing else to say. It appears whether you clicked preview or
arrived on the page while a render was already in flight, only on the panel that
asked for it, and it is replaced by the finished video the moment the job ends.
The end screen's preview works the same way.

All thirteen are five seconds by default and take one to four seconds to render:
frames are composed in Pillow and piped straight into ffmpeg as raw video. The
pattern-led ones cost the most, and the pattern is built once and scrolled rather
than redrawn per frame.

### The slate's own music

A channel can carry a **sting** — its own few seconds of music for the slate,
separate from the video's music bed. Upload it on the channel page and set how loud
it sits against the narration and how long it rings on over the first slide.

Stings usually arrive as a whole track, so the slate takes a **window** of one
rather than its opening: **start it** slides the window anywhere in the file, and
the slate uses the seconds from there — its own length plus the tail. Dragging that
slider scrubs the player next to it, and *hear the window* plays exactly what will
be used, so the portion is found by ear. **Fade out** sets how long the window
takes to die at the end, or is dropped to zero for a straight cut. The slate
preview renders **with the sting on it**, levelled where it will sit once the
finished mix is mastered, and holds its last frame for the tail so the ring-out is
audible; one function, `intro.sting_chain`, builds that window for both the
preview and the finished video, so the two cannot drift apart.

The main bed then holds off until the slate is over, so the two never fight. That
is done with a delayed `afade` rather than an `adelay`, because `afade` with a
start time silences everything before it — and delaying an audio branch is where
the traps are (see below). Measured on a five-second slate: sting fades up from
0.0s, rings out by 5.75s, bed fades in from 6.0s.

If a channel has no cast yet and its template is a cast-led one, or a slate fails
for any reason, the render logs it and continues without an opening rather than
failing the video.

### The end screen

The last five to twenty seconds, held so the video has somewhere to end. YouTube
draws its own clickable elements over that stretch — the video cards, the
subscribe badge — and it draws them wherever you drag them, over a face as
happily as over a gap. So a template here is mostly a decision about **where the
holes are**: each one puts down empty plates at element-sized positions, and you
line the real elements up with them in Studio. A plate nobody covers still reads
as deliberate; a card with nowhere to put them is the usual reason an end screen
ends up over somebody's eyes.

Ten of them, picked from the same kind of strip as the slates.

**Two up** — the channel name, tagline and handle on the left with a round plate
for the subscribe badge under them; two square video plates on the right, headed
by the closing line. The layout most end screens want to be.

**Marquee** — the name set as large as the frame allows across the top, one or
two 16:9 plates beneath it, the badge at the foot. For pointing at one particular
video rather than offering a choice.

**Afterglow** — the video's own last picture holds under a blur and a scrim, and
the plates float over it. The gentlest way to end, and the only template that
knows what the video was about. A clip is skipped in favour of the last still; if
there is no picture at all it falls back to the gradient and says so in the log.

**Console** — a technical grid, the name in SF Compact Black, a mono command
line, and up to three plates drawn in corner by corner with brackets rather than
frames. Pairs with the Signal and Atlas slates.

**Ledger** — cream stock, Baskerville, and plates plated inside a hairline the
way a picture is plated on a printed page. The end screen for a Folio channel.
The accent prints at 62% here for the same reason the Folio slate does: a colour
mixed for a black frame vanishes into paper.

**Quiet** — near black, one rule, the name small, the plates low. Says the least
of any of them.

The four below are **theme-led**, like the slates. The plates sit in the same
element-sized places — a YouTube card does not care what is behind it — but the
ground, the second colour and the icons come from the theme.

**Arcade** — cartridge plates on a scrolling field of icons, the wordmark
carrying the same hard colour shadow the Arcade slate uses, and a prompt that
blinks for the whole hold so a long card never looks frozen.

**Gloss** — soft light and drifting sparkles, the name in Baskerville, plates
centred beneath it. The light one.

**Sideline** — a slanted band across a striped field. The band is on the diagonal
because that is the sports graphic; **the plates are not**, because a YouTube
element dropped onto a rotated plate sits crooked against it, and the entire
point of a plate is that something covers it exactly.

**Wordmark** — the channel name as wallpaper with a band cut out of it and up to
three plates below. The end screen for a channel whose slate is Stack.

Every template answers to the same knobs: how long the card holds, how many
plates it leaves room for (fewer than the template allows is fine — dropping from
two to one leaves the remaining plate where the eye already expects it), how long
the layout takes to settle, the closing line, an `@handle`, and how far the
video's last picture comes through behind it. The plates read left to right, so
the first one a viewer looks at is the next video.

Two things keep moving once the layout has landed: a hairline along the foot that
empties over the length of the card, which is the only honest way to show how
long it is up for, and a ring that breathes out of the subscribe plate every few
seconds. Both are optional and both are cheap — the frame the layout settles into
is composed once and cached, and only those few hundred pixels are redrawn, which
is why a twenty-second card costs about as much to render as a five-second slate.

**The music bed fades out over the end screen**, and how long that fade takes is
set on the card rather than in the house look, because it is the end screen that
makes it a question: a bed that dies on the first frame of a twenty-second card
leaves it sitting in silence. Six seconds by default.

An end screen is a channel-level thing like the slate, and any individual video
can opt out of it on the Render tab. Like the slate, a failure is logged and the
video renders without it rather than not at all.

---

## Bringing your own script

The home page has two modes. **Paste a script** takes an article you already
wrote — a newsletter post, a draft, anything — and turns it into the same kind of
video, skipping the writing step entirely.

Newsletter furniture is stripped first: subscribe prompts, share buttons, image
captions, link labels, bare URLs, markdown emphasis. Headings are kept, because
they become the beat names behind the on-screen chapter titles. What's left is
split into paragraph-sized takes, and each paragraph gets its own picture research
exactly as a generated script would.

Two fidelities:

- **Faithful** (default) keeps your words. It may split a long sentence at a
  breath point, merge two very short ones, drop anything unspeakable, and fix
  outright typos — "Atleast that's the theory, a week into the launch" becomes
  "At least that's the theory. A week into the launch", and "&" becomes "and". It
  may not reword you, add transitions, or touch your facts or opinions.
- **Adapted** additionally smooths written-only constructions into speech —
  unpacking parentheses, breaking long clauses — while staying in your voice.

Your article's own headline and standfirst are skipped rather than read aloud,
since they already appear as the video title and on the slate. Runtime comes from
your word count instead of a target you set. The source text is kept in the
project, so **re-split** switches fidelity or just tries the segmentation again
without pasting anything twice.

A 990-word post imported as 19 paragraphs, 100% of the source, ~6.4 minutes, in
under two minutes.

---

## Research and accuracy

**Start from an idea** used to write purely from what the model already
remembers, with a system prompt telling it not to invent anything — a hedge
against a model that had no way to check anything. It's why an early test
video about Valve and Half-Life 2 quietly narrated its own uncertainty
("this story comes from Newell's own retellings...") rather than actually
finding out.

Claude Code's own web search doesn't work for this: its `WebSearch`/`WebFetch`
tools need an interactive permission prompt that headless (`--print`) mode has
no way to answer, and — across every permission flag there is — a denied or
skipped call doesn't fail loudly. It silently answers from memory instead,
sometimes with a fabricated citation attached. Confirming that took an
afternoon; the detail is worth knowing if you ever wonder why this doesn't
just use `claude`'s built-in search.

So research here goes around the CLI entirely. **`app/research.py`** searches
a local [SearXNG][searxng] instance over plain HTTP, fetches the most
promising pages itself, and only then hands Claude real fetched text to
extract facts from — every claim in the resulting dossier has to trace back
to a page that was actually retrieved. That dossier (dated facts, each with a
source and a confidence; open questions the sources disagree on; corrections
to anything the idea itself got wrong) is what the outline and every
section's narration are then written from — see the **Sources** panel on the
script tab, and `app/script_gen.py`'s `RESEARCHED FACTS` block. A second pass,
**`verify_script`**, checks the finished narration against that same dossier
afterward and flags anything a paragraph asserts that the research doesn't
support — a `check facts` button re-runs it after a hand edit. Both are
visible in the UI, not just in the log: flagged paragraphs get a warning pill
with the issue as its tooltip.

**Setup**, entirely optional — without it, generation falls back to writing
without grounding, same as before this existed:

```bash
docker compose -f docker-compose.searxng.yml up -d
```

Then set `SEARXNG_URL=http://127.0.0.1:8888` in `.env`. The instance is bound
to loopback only and its JSON API is what the default settings.yml enables
(`searxng/settings.yml`) — public instances leave that off, since handing out
JSON is an easy scraping target, but this one only ever answers this machine.

[searxng]: https://docs.searxng.org/

---

## Publishing to YouTube

Once something is rendered, the render tab can upload it straight to
YouTube — title, description (pre-filled with the same credits block the
"credits for the description" button already generates, image and cast
attribution included), tags, a category, and privacy. **Privacy defaults to
Private everywhere a default exists, including server-side** — choosing
Unlisted or Public is a deliberate switch, not something a re-render or a
stray click can turn on.

A YouTube channel is connected once per channel here (not per video) from
the channel page's YouTube panel, which hands off to Google's own
sign-in/consent screen — nothing about your Google account touches this
tool except the OAuth token it hands back, which is kept in
`channels/{id}/youtube.json`, entirely separate from `channel.json`, and
never appears in anything the API returns (`GET /api/channels/{id}` only
ever reports whether it's connected and to which channel's name).

**Setup** (optional — without it, the panel explains why it's not there and
you just upload the render through Studio by hand instead):

1. In [Google Cloud Console](https://console.cloud.google.com/), create a
   project (or use one you have), enable the **YouTube Data API v3**
   (APIs & Services → Library), then create an OAuth client under
   Credentials → **Create Credentials → OAuth client ID → Desktop app**.
2. Put its client ID and secret in `.env`:
   ```
   GOOGLE_CLIENT_ID=...
   GOOGLE_CLIENT_SECRET=...
   ```
3. If your Cloud project's OAuth consent screen is still in "Testing"
   (the default until you publish it), add the Google account you'll
   connect as a **test user** under OAuth consent screen → Audience — Google
   otherwise refuses the sign-in with "access blocked."

The redirect target is derived from whatever address you actually open the
app on (`http://127.0.0.1:PORT/api/youtube/oauth/callback`), so it works
however `run.sh` was started — a "Desktop app" OAuth client doesn't require
that exact loopback port to be pre-registered.

---

## The workflow

**1. Script.** Type the idea and a target length. Claude builds an outline
(intro, main beats, conclusion) budgeted to your runtime, then writes each
section as 40–75 word paragraphs — one paragraph is one recorded take. Edit any
paragraph inline, ask for a rewrite with an instruction, split a long one in two,
or delete it.

**An unfinished run is picked up, not repeated.** Sections are written four at a
time, and each one is banked on the project as it lands, so a run that dies
halfway — a usage limit, a dropped connection — leaves its outline and everything
already written behind. The script tab then offers **carry on**, which writes only
the sections still missing, or **start again**, which throws the draft away. One
section failing no longer discards the ones that succeeded beside it, and the
saved outline is reused rather than rebuilt: re-outlining would produce different
headings and strand every section written against the old ones. Changing the
idea, the length or the tone invalidates a draft on its own.

Failures that retrying cannot fix — a spent usage limit, a signed-out CLI, no
credit — are raised as `LLMUnavailable` and are **not** retried, where a
malformed reply still gets its three attempts. The CLI writes those messages to
stdout as often as to stderr, and only stderr was being reported, which is how a
usage limit came back as `claude exited 1:` and nothing else.

**Or let a model read it.** The record tab switches between **read it yourself**
and **AI voice**. The AI read uses [Kokoro][kok], an 82M-parameter model that
runs locally on the CPU — no key, no request, nothing leaves the machine, and a
re-write at midnight costs nothing but the time. Sixteen English voices, British
and American, each with a *hear* button; pace is adjustable from 0.7× to 1.3×.
Measured on an M1 Pro it synthesises at **3.2× real time**, so a 12-minute video
takes about four minutes to voice.

It is a whole-video decision rather than a per-paragraph one, because a video
that switches between a real voice and a synthetic one halfway through sounds
broken rather than varied. What comes out is a take in exactly the shape the
recorder produces — 48kHz mono, levelled to the same target — so the gaps, the
picture timing, the narration bed and the render cannot tell the two apart and
do not need to. Reading the script again skips paragraphs already read in the
current voice, so changing one line does not re-read the video.

The cleanup chain that a recorded take goes through — de-noise, de-room,
de-ess — is deliberately **not** applied to a synthetic one. There is no room
and no hiss to remove, and running it anyway would only smear the top end. A
synthetic take gets a high-pass, its own ends trimmed, and the loudness every
take lands on.

### How to say things

espeak, which is how Kokoro reaches its phonemes, is good at English and
unreliable at names — and a documentary channel is mostly names. "Elon" comes
out `ɪlˈɒn`, *ih-LON*, stressed on the wrong syllable. The **pronunciation
guide** on the record tab fixes those one at a time.

Write the respelling in syllables with the stressed one in **CAPITALS**:
`ELL-on`, `rod-REE-gess`, `nih-KOH-lah`. That notation is not decoration, it is
load-bearing — handing espeak a respelling directly does not work, because
hyphens make it stress every part (`ell-on` → `ˈɛlˈɒn`, two primary stresses in
one word) and capitals make it spell letters out (`rod-REE-gess` → *rod-ar-ee-ee-gess*).
Each syllable is therefore phonemised on its own in lower case, stripped of
whatever stress espeak guessed, and the one primary stress is placed where the
capitals said. `ELL-on` then resolves to `ˈɛlɒn`, which is the target exactly.

Entries store the **phonemes**, not the respelling, because a respelling is a
guess at espeak's spelling rules and frequently loses. The panel shows what a
word reads as now beside what an entry would make of it, and a *hear* button for
each — you cannot correct a pronunciation you cannot compare with the one you
are getting. The IPA is editable directly for anything a respelling cannot
reach. Anything that resolves to no actual sound is refused on the way in:
`???` survives espeak and the vocabulary filter as a bare `?`, and would
otherwise become a silent wrong name in a finished video.

A guide lives on the **channel**, because the names that recur are the series'
names, and a video can override any of them for itself. At synthesis the text
either side of a match is phonemised in runs rather than word by word, so espeak
still sees enough context to place stress and liaison normally; only the matched
terms are substituted. Paragraphs with no matches take the ordinary text path
through the model rather than the phoneme one.

**Licence.** Kokoro's weights are Apache-2.0, which is why it is the one wired
up. Several better-known local models are research-only or explicitly
non-commercial — XTTS-v2 is under Coqui's CPML, which forbids commercial use —
and are a bad foundation for a tool whose whole point is publishing. The model
files are a one-off 337MB download; see `assets/tts/README.md`.

[kok]: https://huggingface.co/hexgrad/Kokoro-82M

**2. Media.** Every paragraph gets search queries written by a model told to
think like a picture researcher. The tool queries the archives, ranks the hits
and picks a lead image, avoiding repeats across the video. You can click any
alternative, run your own search, or upload your own file.

**How often the picture changes.** One picture per paragraph is the default, and
on a 20-minute video that is a lot of pictures to find. **Picture every N
paragraphs** on the Media tab holds each one across a run of paragraphs instead:
set it to 3 and a 24-paragraph video needs eight pictures, not twenty-four. Only
the paragraphs that start a picture are searched for, the held ones collapse to a
single line in the tab, and the Ken Burns move stretches across the whole hold —
so a picture held for a minute drifts slowly rather than sitting still. Any
paragraph can override the rule: **give this one its own picture**, or **hold the
last picture**. Chapter titles still appear at their own paragraph's moment,
part-way through a held picture.

**Clips that are shorter than the paragraph.** Archive footage is routinely
shorter than the narration over it. A clip is first slowed by up to a third to
cover the gap, and if it still comes up short it is laid end to end with a half
second dissolve at each seam rather than a hard loop, which reads as a considered
cut instead of a mistake. Past about eight repeats it simply runs round.

**Focus points.** Any image can carry a point that must stay on screen — click
**set focus point** and click the subject's face. That point drives two things:
the crop that fits the picture to 16:9, and the Ken Burns move, which is clamped
so the zoom can never drift off it. It matters most for tall studio portraits: a
1000×2000 plate with the face at 12% height loses the face completely to a centre
crop, and keeps it in every single frame with a focus point set. The same picker
is on each channel's cast, where column crops are narrow and unforgiving.

**3. Record.** A teleprompter shows one paragraph at a time. <kbd>space</kbd>
records and stops, <kbd>→</kbd> moves on, <kbd>p</kbd> plays back, <kbd>r</kbd>
discards. Re-record any paragraph any time without touching the rest — the new
take is written to a scratch file and only moved into place once it is known
good, so a silent mic cannot take the previous take down with it.

**What happens to a take on arrival.** It is measured before it is touched: a
20ms RMS envelope of the whole recording, from which the room tone and the real
speech are read off. A fixed "this is silence" threshold cannot work across
takes — one paragraph peaks at −21dBFS and the next, read softer, never gets
above −35 — so the thresholds are set from that take's own room tone. The edges
are found by anchoring on a sustained run of speech, which a mouse click cannot
fake, then walking outwards while the audio is still above the room, so quiet
trailing syllables and the natural decay survive. The walk stops at any isolated
bang, which is how the click that started or stopped the recording is left
outside the trim rather than fading it in. Then: high-pass, de-click, broadband
denoise told the room's actual level (guessing it is what makes denoised speech
sound underwater), the de-room pair below, body at 180Hz with the boxy 430Hz
taken out and a lift at 3kHz where consonants live, a de-esser to pay for that
lift, gentle compression so the ends of sentences stay audible, and two-pass
loudness to −16 LUFS — measured first, then applied as one static gain, so every
take matches every other rather than each being pushed around by its own moving
gain.

**Getting the room out.** A roomy take is not a noisy one, so no denoiser can
touch it: it is your own voice arriving a few milliseconds late off the walls
behind you. Two things move it. The expander is the one that matters —
reflections only ever exist *under* the direct sound, in the gaps between words
and for the 100–200ms after each one, where they sit some 10–15dB below the voice
with nothing else in the way. Setting its threshold from *this take's* speech
level leaves every spoken frame alone (measured on a real take: 0.0dB of gain
change on speech, quiet syllables included) and pulls down only what is left over
in between. The other is tone: a small room piles its reflections into a 300–500Hz
honk that reads as "recorded across a desk" long before anyone would call it an
echo. On a genuinely live take the pair takes the separation between voice and
room from 27dB to 38dB at the default setting, and to 44dB on the **live** preset.

None of which beats moving the microphone. The mic panel measures the room and
says so, because distance, a soft surface behind you and getting off the desk are
worth more than anything the chain can do afterwards.

**The four presets** — warm, neutral, bright, live — are starting points, not
limits; move any slider and the panel says *custom*. **make this the channel
default** puts the settings on the channel so every new video in the series
starts from them.

The raw recording is kept beside the cleaned take. **re-clean all takes** on the
Record tab (and in the mic panel) runs the current chain over all of them again,
so an improvement to the processing reaches a script that is already read.

**The pauses between paragraphs.** Every take butted together with the same gap
is what makes a cut sound assembled rather than spoken. The pause varies with how
the paragraph ended: about half the base gap when it runs on mid-sentence, the
base within a beat, a third more where the outline moves on, and double where a
new chapter title comes up. **Pause between paragraphs** on the Render tab sets
the base (0.42s by default). The same numbers pad the narration bed and time the
pictures, from one list, so the two can never drift apart.

**3b. Talking head (optional).** Attach a piece of camera footage of yourself and
it is cut in as its own segment — by default straight after the channel slate,
which is where a face does the most work. You can also put it at the very start
or use it as a sign-off at the end. Trim either end with a slider (the preview
scrubs as you drag), and give it a focus point if the framing is off-centre or
the clip is vertical.

Its own audio is kept and joins the *voice* bus rather than sitting beside it: it
is levelled to the same −16 LUFS as your recorded takes, so cutting to camera is
not a jump in loudness, and the music ducks under it exactly as it does under the
narration. The clip dissolves in and out using its own footage rather than a
frozen frame, so it simply fades up and away. A clip with no audio track is fine
and renders silent.

**4. Thumbnail.** Six styles, one picture, a few words. The picture comes from
whatever this video already found — every slide's chosen image is in the picker —
or from a fresh archive search that belongs to no slide, or your own upload; the
one you choose is promoted to its full-size rendition and cached in the project.
Text is fitted rather than set: a three-word headline is drawn enormous and a
twelve-word one steps down, wrapping to at most three lines, so nothing ever
overruns its panel. **Write me some** asks Claude for headlines that are the hook
the title cannot carry rather than the title again, and the same focus-point
picker keeps the subject in frame at whatever aspect the style crops to.

Every edit redraws server-side and swaps the preview — there is no second
implementation of the layout in the browser to fall out of step with the
renderer. Output is a 1280×720 progressive JPEG at quality 90, around 250KB
against YouTube's 2MB ceiling, downloadable from the tab and shown on the video
list.

Seven styles run on one accent over a photograph: **Banner** (full-bleed, scrim,
headline across the foot), **Split** (picture one side, type on a solid panel the
other), **Spotlight** (the frame goes grey but for a pool of light on the subject,
headline with a hard accent shadow), **Medallion** (a ringed circle over a blurred
bed of the same photograph), **Diagonal** (cut on a slant with an accent slash)
and **Poster** (a cream card, the picture plated inside a rule, serif headline
beneath).

**Loupe** is the seventh, and the one built for Watch Tales: the picture seen
through a watchmaker's eyeglass, magnified about the focal point and left sharp
and full-colour inside the glass, with the bench outside it greyed, dimmed and
thrown out of focus. It earns its place mechanically as well as thematically —
the lens crops any photograph to a circle and enlarges it, so a picture that
would be unreadable at sidebar width still has one sharp, bright, obvious
subject. The barrel is knurled with deliberately coarse teeth: at the 120px a
thumbnail is actually read at, fine knurling aliases into a grey band and stops
reading as metal at all.

Five more are **theme-led**, and these are the loud ones:

- **Sticker** — outlined type slapped over a field of the theme's icons, the
  subject blended in beside it. The outline is grown off the type layer's own
  alpha rather than stroked per letter, which would thicken every counter and
  close up the small ones. The picture's inner edge is a ramp, not a straight
  cut: a hard edge is exactly what reads as a pasted-in rectangle at sidebar
  size.
- **Duotone** — the picture flattened into the two theme colours with a band of
  type across the foot. The cheapest way to make any photograph — an archive
  scan, a press shot, a frame grab — look like it belongs to one channel, because
  every one of them comes out in the same two colours.
- **Gloss** — soft light, the subject in a ring, sparkles, a serif headline. For
  beauty and fashion.
- **Scoreline** — a slanted band cut across the picture carrying condensed caps,
  built and rotated as one piece so the band edges and the type share a slant.
- **Tiles** — a panel of icon tiles beside the picture with the headline plated
  over them. For food, craft and making.

A theme sets the style new videos in the channel start on; any video can change
it. The theme's colours come through automatically, because a project inherits
its channel's style at creation.

**5. Render.** Adjust vignette, drift, crossfade, grade and music level, then
render. **Preview cut** renders the picture edit with estimated timings before
you have recorded anything, which is the cheap way to check the visuals.

Output lands in `projects/<id>/out/` as an H.264 MP4 mastered to −14 LUFS, which
is what YouTube normalises to. The Render tab also generates an attribution block
for your description.

---

## How it fits together

```
app/
  main.py        FastAPI routes, thumbnail proxy, range-serving for media
  jobs.py        background jobs with a polled progress log
  script_gen.py  idea -> outline -> paragraphs -> per-slide visual plan
  llm.py         shells out to `claude --print`, parses JSON out of replies
  media/
    base.py      rate limiting, relevance gating, query relaxation, scoring
    providers.py Wikimedia, LoC, Met, NYPL, Openverse, Pexels, Pixabay, Storyblocks
    __init__.py  tiered search, auto-pick, downloads
  audio.py       take cleanup, the pause rules and the narration bed
  titles.py      lower-left typography, rendered with Pillow
  channels.py    channel persistence
  themes.py      the eight themes: palettes, icon sets and template picks
  motifs.py      icons, icon/word patterns, gradients — what the themes draw with
  intro.py       casting, portrait caching, the thirteen animated slate templates
  outro.py       the ten end screens and where each leaves room for YouTube
  thumbs.py      the twelve YouTube thumbnail styles, drawn with Pillow
  render.py      segments, Ken Burns, vignette, crossfades, music duck, final mux
static/          the single-page UI
channels/<id>/   channel.json plus the cached cast portraits
channels/<id>/   channel.json, cast portraits, the slate sting
projects/<id>/   project.json, source.txt (a pasted script), media, takes, out
```

### Things worth knowing

**The voice and the pictures are timed from one list.** Screen time per paragraph
is the take's real length plus the pause that follows it, and that pause comes
from the same `audio.paragraph_gaps` the narration bed is padded with. Two
implementations of "how long is this paragraph" would drift apart within a
minute. For the same reason a take whose file no longer matches its stored
duration stops the render with the paragraph number rather than sliding every
picture off the voice: it is how one project ended up with metadata claiming
twenty seconds over an empty wav, after a failed re-record clobbered a good take.

**The icons are drawn, not licensed.** Forty-odd glyphs in `motifs.py`, each a
handful of Pillow primitives inside a unit box, which is why the same controller
comes out at 26px in a thumbnail pattern and 300px on a slate with nothing
scaled or fetched. Several of them are cut out of themselves rather than built
up — the cross is knocked out of the d-pad, the sticks out of the controller —
because a plus and a d-pad drawn additively are the same shape, and at pattern
size that is all the eye gets.

**A pattern is built once and moved, not redrawn.** The scrolling fields on the
Arcade and Stack slates are single images twice the width of the frame, cropped
at a moving offset — thirty frames a second of re-tiling five hundred glyphs
would cost more than the rest of the slate put together. The same rule runs
through the end screens: the frame the layout settles into is composed once and
cached, and only the countdown hairline and the sparkles are redrawn.

**Lifting a colour off itself is not the same as lightening it.** The first cut
of the themed plates used a "shade toward white" helper at 1.75, which on a
near-black violet ground lands three quarters of the way to white — the plates
came out as pale holes punched in the artwork. Panels now mix about a tenth of
the way to white and stay in the theme's own colour. The contrast test that
picks black or white type sits high for the same reason: a bright green measures
as a mid-tone and takes white by a hair, which is exactly where white fails.

**Typography is drawn with Pillow, not ffmpeg.** Homebrew's ffmpeg is built
without libfreetype, so `drawtext` does not exist. Titles are rendered to
transparent PNGs and overlaid — which also buys real letter-spacing, a blurred
drop shadow and a soft gradient scrim so white type survives a bright photograph.

**A preview is cache-busted on its own mtime, not the channel's.** Rendering a
preview writes a file into the channel's cache directory and touches nothing
else, so a `?v=updated_at` on the video URL does not change between two
previews — and the browser hands back the file it already has. The second
preview then looks identical to the first however different the settings were,
which reads as "the template ignored my slider" rather than "your browser
cached it". The API reports each preview file's own modification time and the
URL is busted on that.

**The archives rate limit hard, and quietly.** Wikimedia answers an unthrottled
fan-out with "too many requests", which looks exactly like "no results" unless
you check. Every provider therefore has a concurrency cap and a minimum gap
between requests, searches are memoised across slides, and the search widens in
stages so a 24-slide project spends a few dozen requests rather than several
hundred. Empty results are never cached, because a throttled request and a
genuinely empty one are indistinguishable at that layer.

**Only Wikimedia's own thumbnail URLs are fetchable.** Hand-built widths come
back `400 Use thumbnail sizes listed on …`, and the original files behind
`Special:FilePath` are throttled aggressively. So the provider only ever uses a
URL the API itself generated.

**Previews first, full files only when chosen.** Search asks the API for 480px
previews, and an image is promoted to its 1920px rendition only when it is
actually picked for a slide or cast in an intro. Browsing a dozen options for a
35-slide project would otherwise pull hundreds of megabytes of full-resolution
files off Wikimedia for pictures nobody uses — measured at roughly 9× less
traffic for the same browsing. Previews are additionally downscaled and cached on
disk by our own proxy, so re-opening the picker costs the archives nothing.

**Picture-research queries are usually too specific.** "Endurance Grytviken
whaling station 1914" matches nothing because Commons ANDs every term. Queries
are progressively relaxed — drop the year, drop the last qualifier, drop the
leading subject — and a per-project subject pool is fetched once so a slide whose
exact shot does not exist still gets something on topic instead of a blank frame.

**The music bed is loudness-matched before it is attenuated.** Otherwise "−22 dB"
means "22 dB below whatever this particular track happened to be mastered at", so
a quiet track disappears and a loud one buries the voice. The bed is normalised
to −16 LUFS first, so the setting genuinely means *this far under the narration*.
It is then side-chain ducked against the voice.

**Timing.** Each slide's screen time is its take plus a fixed pause. Crossfades
are centred on paragraph boundaries by padding the narration by half a transition,
and the head and tail padding live on the first and last segments so nothing
drifts. A slide with no recorded take is skipped in a full render.

**The slate and the camera clip are just segments.** Both are inserted into the
same crossfade chain as the slides, and the narration's lead-in grows by whatever
sits in front of it, so adding or removing an opening cannot pull the voice out of
sync with the pictures. Verified with a 5s slate plus a 4s camera clip: the camera
audio runs 5.00–8.75s exactly under its own picture, and the first narrated word
lands at 9.25s against a predicted 9.325s.

**Never fail a job over the shape of a reply.** Every structured model call goes
through `complete_json(..., require=...)`, where `require` is the caller's own
test for a usable answer. A reply that parses but is shaped wrong — the payload
nested under a wrapper key, the array renamed to `beats`, a short aside object
emitted before the real one — is retried with a corrective message rather than
thrown away, and `find_records` then digs the records out of whatever came back.
This was found the hard way: an outline call that had already spent two minutes
died on `outline.get("sections")` returning nothing, and the creator saw only
"Outline came back without sections". Nine wrapper shapes are covered by tests,
and a genuinely empty reply still fails loudly rather than producing a silently
empty section.

**Big blobs stay out of `project.json`.** A pasted article lives in
`projects/<id>/source.txt`, not in the record, which is read and rewritten on
every edit. This was learned the hard way: a `script_source` field was added to
the dataclass but not to `to_dict`, so it silently vanished on save and the
importer quietly wrote a brand-new script instead of using the pasted one. There
is now a round-trip assertion — every `Project` field must survive `to_dict` →
`from_dict` unchanged.

**Never `apad` before `adelay` — and never `apad` without a bound.** Two traps
here, both found the hard way. Seeking a clip with an input `-ss` leaves its first
packet with a non-zero PTS, and an `apad`/`atrim` pair placed after `adelay` moves
the inserted silence to the *end* of the branch: the camera audio then plays at
0:00 over the title slate instead of under its own picture. The camera branch
therefore trims inside the filter graph, resets timestamps with `asetpts`, and has
nothing after `adelay`; `amix=duration=longest` sets the length. Separately,
`apad` with no `atrim` after it produces output forever — it will fill a disk in
seconds. Every `apad` in this codebase is bounded by an explicit `pad_dur` or a
following `atrim`.

---

## Licensing

The tool records where every image came from and generates a credits block, but
**it does not clear rights for you**. Wikimedia results carry a mix of licences,
Library of Congress items say "rights vary", and museum collections have their
own terms. Read the credits output before you publish, particularly if the video
is monetised.
