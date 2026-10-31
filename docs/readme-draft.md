<!--
  Draft of the public README for the Corkbored launch (written 2026-10-26).
  It replaces README.md in T6.3, after the rename (T0.4). Before then:
  - every image path under docs/images/ is a placeholder to be captured
    (the mockup canvas shows what each screen should look like);
  - the repo URL assumes the GitHub repo is renamed to Liam-Griffiths/corkbored;
  - the Status table must be checked against docs/tickets/PROGRESS.md on
    launch day, so nothing is listed as available that is not.
  Structure borrowed from two strong READMEs: HyperFrames (one-line promise,
  agent quick start, "how it works" artefact, honest comparison table) and
  EffectCraft (section nav, a screenshot per section, an honest "where it
  stands", "how it's made" principles, a downloads table).
-->

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/brand/corkbored-dark.svg">
    <img alt="Corkbored" src="docs/brand/corkbored-light.svg" width="280">
  </picture>
</p>

<h3 align="center">Idea in. Episode out.</h3>

<p align="center">
  A studio on your own computer that researches, writes, narrates, illustrates,
  edits, reviews and publishes long-form video. You bring the ideas and the
  taste. It does the labour.
</p>

<p align="center">
  <a href="https://github.com/Liam-Griffiths/corkbored/releases/latest"><img alt="Latest release" src="https://img.shields.io/github/v/release/Liam-Griffiths/corkbored?style=flat-square&color=FF5A1F"></a>
  <img alt="Status: early and moving fast" src="https://img.shields.io/badge/status-early%20and%20moving%20fast-FF5A1F?style=flat-square">
  <img alt="Runs locally" src="https://img.shields.io/badge/runs-on%20your%20machine-0E0F11?style=flat-square">
  <a href="LICENSE"><img alt="License: GPLv3" src="https://img.shields.io/badge/license-GPLv3-555?style=flat-square"></a>
</p>

<p align="center">
  <a href="#what-it-makes">What it makes</a> ·
  <a href="#how-it-works">How it works</a> ·
  <a href="#the-studio">The studio</a> ·
  <a href="#built-for-agents">Agents</a> ·
  <a href="#get-started">Get started</a> ·
  <a href="#where-it-stands">Status</a> ·
  <a href="#how-its-made">How it's made</a> ·
  <a href="#downloads">Downloads</a> ·
  <a href="#license">License</a>
</p>

<p align="center">
  <!-- TODO: 20-second GIF: an idea typed in, the Timeline filling up, a review note fixed, the render. -->
  <img src="docs/images/corkbored-hero.gif" alt="Corkbored's Timeline: the player, layer rows for pictures, voice, titles, captions, chapters and music, and the check panel listing two findings" width="100%">
</p>

Corkbored turns an idea, or something you have already written, into a
finished, sourced video. It researches the subject, writes a script you can
edit, records your voice or reads it with a local AI voice, finds and places
the pictures, cuts the video, checks it, and uploads it to YouTube. It runs on
your machine, with your Claude subscription or API key.

> [!NOTE]
> **Made with Corkbored.** Every video on [the channel](https://youtube.com/@CHANNEL)
> was made with it: essays on what happens to society once AI and humanoid
> robots arrive. Watch one before you install anything.
> <!-- TODO: channel link and one featured video thumbnail -->

## What it makes

- **Documentaries and video essays** from archive pictures and footage, with
  titles, captions and chapter cards.
- **Explainers** drawn as handwritten boards, diagrams and designed slides.
- **3D explainers** with a real camera moving around real models: a
  solver plans each shot and checks it before a frame is drawn.
- **Fast-cut formats** for different kinds of channel: kinetic type, a
  rapid-fire tech explainer, a true-crime corkboard, a message-thread
  storytime, a markets terminal.
- **Piece-to-camera**, as sections of a video or whole talking-head videos,
  with jump cuts and cutaways. *(In progress; see [Status](#where-it-stands).)*

<!-- TODO: a 2x3 grid of stills, one per format, each linking to a video. -->

## How it works

One idea goes in. Each step leaves something you can read and change.

1. **Research.** Searches the web and keeps the sources, so every claim can
   be traced.
2. **Script.** Claude writes an outline with a hook and a script in your
   tone, then checks the script against the research. Or paste your own
   essay: faithful mode keeps your words.
3. **Voice.** Record each paragraph yourself, or let a local voice read it.
   Takes are cleaned automatically, and every take you record is kept.
4. **Pictures.** It plans what each paragraph should show and searches open
   archives and stock libraries, or you pick your own.
5. **Edit.** The voice is the clock: every picture, title and cue is timed
   to the words.
6. **Check.** Pacing, readability and timing rules run in under a second,
   with no AI call. Then a review looks at a handful of frames the way a
   stranger would, sound off, and suggests fixes you approve.
7. **Render and publish.** One file, loudness-normalised, verified, and
   uploaded to your channel.

The whole cut is one readable document, the storyboard, which the app, the
command line and an AI agent all read and edit:

```json
{
  "id": "p14", "start": 41.4, "end": 52.9,
  "narration": "The feed learned what we would watch at two in the morning.",
  "title": "The 2 a.m. feed", "title_at": 2.9,
  "picture": {"provider": "wikimedia", "title": "Server hall, 2019"},
  "take": {"duration": 11.1, "words": [{"w": "The", "start": 0.0, "end": 0.12}]}
}
```

## The studio

### Timeline

Every paragraph, picture, title, caption, chapter and music cue on one
ruler. Scrub, drag timings onto the words, split a paragraph at the playhead,
and preview any moment at quarter size without rendering the whole video.

<!-- TODO: screenshot of the Timeline editor -->
<img src="docs/images/timeline.png" alt="The Timeline editor with the title inspector open and a title being moved to land on a word" width="100%">

### Review

Problems are found before you render. The check runs instantly and costs
nothing. The review describes what it sees, picks the weakest shot, and
proposes a change you can apply, dismiss, keep as a warning, or turn into a
rule for the whole channel. There are no scores.

<!-- TODO: screenshot of the Review screen -->
<img src="docs/images/review.png" alt="The Review screen: frames that were looked at, the weakest shot, and a proposed timing change shown as a before-and-after" width="100%">

### Channels that learn

A channel keeps its look, its pacing as numbers, and the rules you have taught
it ("never put a title and a caption on screen in the same second"). Every
new episode starts from them.

<!-- TODO: screenshot of the Channel screen -->
<img src="docs/images/channel.png" alt="A channel's variables, pacing numbers, house rules and saved formats" width="100%">

### 3D explainers

Add a model from the library and name its parts. The planner says what each
shot should show ("push in on the left wing"); the solver works out the
camera and checks framing, motion, occlusion and clearance. A shot that
cannot pass is flagged for you, never quietly dropped.

<!-- TODO: screenshot of the Stage -->
<img src="docs/images/stage.png" alt="The Stage: the cast, a 3D viewport framing the Wright Flyer's left wing, the shot's intent and its checks, and the shot list" width="100%">

## Built for agents

Corkbored is an app first, and everything in it is also reachable from the
command line and from AI coding agents.

```sh
corkbored new "why every thumbnail looks the same" --minutes 12
corkbored check <id>            # instant, free: pacing, readability, timing
corkbored review <id>           # looks at a dozen frames, writes REVIEW.md
corkbored render <id> --section p14
```

Claude Code users can install the `corkbored-producer` skill, then ask for an
episode in plain words. *(Command line and skill: in progress; see
[Status](#where-it-stands).)*

## Get started

**Download** the app for your system from
[Releases](https://github.com/Liam-Griffiths/corkbored/releases/latest). Nothing
else to install.

**Or run from source** (Python 3.12+, ffmpeg, git):

```sh
git clone https://github.com/Liam-Griffiths/corkbored.git
cd corkbored
./run.sh
```

You need one way to reach a model:

- the [Claude Code CLI](https://claude.com/claude-code), signed in (uses
  your Claude subscription; the default), or
- an Anthropic API key, set in Settings, or
- a local model through [Ollama](https://ollama.com), or another
  OpenAI-compatible provider.

Optional: the local voice (two model files, see
[assets/tts/README.md](assets/tts/README.md)), and Chromium for 3D and scene
rendering.

## Where it stands

Corkbored is young and moving fast. It has made finished videos, and it is a
good time to try it and tell us what breaks. Not everything below is done.

<!-- Check every row against docs/tickets/PROGRESS.md before publishing. -->

| Area | Status |
|---|---|
| Research, outline, script, fact-check | Available |
| Your voice, the local AI voice, ElevenLabs and OpenAI voices | Available |
| Picture search across archives and stock libraries | Available |
| Documentary, essay, board, diagram and custom-slide styles | Available |
| Five fast-cut formats | Available |
| 3D explainers | Available, evolving |
| Timeline with proxies, channels, project files | Available |
| YouTube upload | Available |
| Pacing as numbers and the instant check | In progress |
| HTML scene engine (sharper type, motion and layout) | In progress |
| Review with fixes, command line, Claude Code skill | In progress |
| Timeline editing: drag timing, razor, layers | Planned |
| Piece-to-camera and talking-head videos | Planned |

The full plan is in [docs/roadmap.md](docs/roadmap.md) and the work queue in
[docs/tickets/PROGRESS.md](docs/tickets/PROGRESS.md).
[Bug reports](https://github.com/Liam-Griffiths/corkbored/issues) are the most
useful thing you can send.

## How it's made

- **Your machine, your files.** Projects are folders of plain files on your
  disk. No account, no telemetry, no cloud render.
- **The voice is the clock.** Every cut is timed from the narration, so the
  pictures can never drift from the words.
- **Numbers, not adjectives.** "Fast" is a cut every 0.13 to 0.8 seconds;
  "readable" is 0.5 seconds plus 0.3 per word. The planner, the renderer
  and the check all use the same numbers.
- **Free checks before paid ones.** Everything that can be measured is
  measured in code. The AI looks only at what code cannot judge, and only at
  the frames that matter.
- **Nothing you recorded is ever deleted.** A retake is kept beside the take
  it replaced.
- **Python and ffmpeg.** HTML scenes and 3D render in the Chromium already
  on your system. There is no Node and no build step.

## Downloads

Every build is on the [latest release](https://github.com/Liam-Griffiths/corkbored/releases/latest).

| System | File | Notes |
|---|---|---|
| macOS (Apple silicon) | `Corkbored-<ver>-macos-arm64.zip` | Not signed yet: right-click, Open, the first time |
| Linux x86_64 | `Corkbored-<ver>-linux-x86_64.tar.gz` | Needs GStreamer's good and libav plugins for playback |
| Windows x64 | `Corkbored-<ver>-windows-x64.zip` | |

<!-- TODO: confirm the real file names from the release workflow before launch. -->

## Where it came from

Corkbored began as **Youslop**, a joke: a tool to make low-effort AI video so
easy that YouTube would have to deal with it. Building it properly turned it
into the opposite: a studio for careful, researched video that one person
can make well. The name changed to match.

## License

[GPLv3](LICENSE). ffmpeg and x264 are bundled under their own GPL terms;
[THIRD-PARTY.md](THIRD-PARTY.md) lists everything included and its license.
The Corkbored name and mark are not covered by the license.

<p align="center"><sub>Made by Liam Griffiths. Made with Corkbored.</sub></p>
