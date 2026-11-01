<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/brand/corkbored-dark.svg">
    <img alt="Corkbored" src="docs/brand/corkbored-light.svg" width="280">
  </picture>
</p>

# Corkbored

**Idea in. Episode out.**

Corkbored turns an idea or a script into a researched, narrated, illustrated
video, on your own computer. It makes careful, researched long-form video
cheap enough for one person to produce, review and publish.

Free and open source. [GPL-3.0](LICENSE).

## What it does

- **Research:** searches the subject and keeps sources for review.
- **Write:** Claude drafts an outline and script, or adapts your own words.
- **Narrate:** record each paragraph or use the built-in narrator.
- **Cut:** choose pictures, titles and cues timed to the narration.
- **Review:** check the timeline, run timing and readability checks, and review frames.
- **Publish:** render a finished file and upload it to YouTube.

## How it works

1. **Describe the idea.** A sentence or two, or paste a script.
2. **Claude writes it.** Research and archive searches supply a script and a picture per paragraph.
3. **Add your voice.** Record each paragraph, or let the built-in narrator read it.
4. **Review and render.** Check the cut on the timeline, change what you like, then render the final file.

Styles include Documentary, Video essay, Handwritten board, Flameboat,
Casefile, Loudmouth, Group Chat and Ticker. Channels keep a series' colours,
opening slate, end card and defaults together.

## Get started

You need a Mac, Windows or Linux computer, and either the Claude Code CLI
signed in with a Claude subscription or an Anthropic API key in Settings.
A microphone is optional for your own narration.

Get packaged builds from [Releases](https://github.com/Liam-Griffiths/youslop/releases).
See each release's assets for the available systems and filenames.

To run from source, install Python 3.12+, git and ffmpeg. Install Chromium
for scenes and 3D; cards with Pillow equivalents work without it. No Node is
needed.

```sh
git clone https://github.com/Liam-Griffiths/youslop.git corkbored
cd corkbored
./run.sh
```

The launcher creates a virtual environment and installs Python dependencies
on first use. Open the local URL it prints, then set up Claude in Settings.
For local narration, download the voice files described below.

## The studio

The Timeline shows pictures, narration, titles, captions, chapters and music.
Scrub and preview at quarter size, edit words and timings, or split a paragraph
at the playhead. Earlier recordings remain available when you replace a take.

The instant Check flags pacing, readability and timing issues without a model
call. Frame review uses Claude and proposes fixes for you to approve. Preview
one picture before rendering the finished cut.

## Built for agents

The [producer skill](.claude/skills/corkbored-producer/SKILL.md) describes the
storyboard and review loop. The command line uses the same operations as the app:

```sh
.venv/bin/python -m app.cli --help
.venv/bin/python -m app.cli check <id>
```

## Where it stands

| Area | Status |
|---|---|
| Research, script, archive search, narration and YouTube upload | Available |
| Documentary, essay, board and five drawn cuts | Available |
| Chromium scenes, cards, thumbnails and 3D | Available |
| Timeline layers, timing edits, razor and take history | Available |
| Instant checks, frame review, fixes, CLI and producer skill | Available; frame review needs owner validation with Claude |
| Piece-to-camera, packs and the six-stage studio redesign | Planned |

See the [roadmap](docs/roadmap.md) and [work queue](docs/tickets/PROGRESS.md).

## Building it yourself

If there's no release for your platform, or you'd rather build your own, it
takes about five minutes. You need **Python 3.12 or newer** and **git**. The
build is for the machine you build on: a Mac makes a Mac app, an ARM Linux
machine makes an ARM Linux app, and so on.

### macOS

```sh
git clone https://github.com/Liam-Griffiths/youslop.git corkbored
cd corkbored
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt pyinstaller pywebview
.venv/bin/python scripts/fetch_ffmpeg.py
.venv/bin/pyinstaller --noconfirm corkbored.spec
open dist/Corkbored.app
```

Drag `dist/Corkbored.app` into Applications to keep it. If macOS says it "can't
be opened", right-click it → **Open** once; it isn't signed.

### Linux

First install the system libraries the window needs. The GStreamer plugins
are what the window plays sound and video through: without
`gstreamer1.0-plugins-good` playing a take or a voice preview crashes the
page, and without the **libav** plugin every video in the app — the slate and
end-card previews, the per-picture preview, the finished render — comes up as
a broken play button, because that plugin is where WebKitGTK's H.264 and AAC
decoders live. The videos themselves are fine; nothing on the machine can
decode them.

```sh
# Debian / Ubuntu
sudo apt install python3-venv python3-dev pkg-config libcairo2-dev \
  libgirepository-2.0-dev gir1.2-webkit2-4.1 \
  gstreamer1.0-plugins-good gstreamer1.0-libav
# Fedora (libav lives in RPM Fusion free, which Fedora does not enable itself)
sudo dnf install python3-devel pkg-config cairo-gobject-devel \
  gobject-introspection-devel webkit2gtk4.1 \
  gstreamer1-plugins-good gstreamer1-libav
# Arch
sudo pacman -S python pkgconf cairo gobject-introspection webkit2gtk-4.1 \
  gst-plugins-good gst-libav
```

GStreamer reads its plugin list once at startup, so restart Corkbored after
installing them. To check a machine before guessing — `gst-inspect-1.0
avdec_h264` prints the decoder if it is there and nothing if it is not.

Running a downloaded Linux release instead of building it? You still need
WebKitGTK and both GStreamer packages: the `webkit2gtk-4.1`/`webkit2gtk4.1`,
plugins-good and libav packages from the line for your distro above.

Then:

```sh
git clone https://github.com/Liam-Griffiths/youslop.git corkbored
cd corkbored
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt pyinstaller pywebview pygobject
.venv/bin/python scripts/fetch_ffmpeg.py
.venv/bin/pyinstaller --noconfirm corkbored.spec
./dist/Corkbored/Corkbored
```

The app is the whole `dist/Corkbored/` folder. Move it anywhere you like, but
keep the folder together.

### Windows

In PowerShell:

```powershell
git clone https://github.com/Liam-Griffiths/youslop.git corkbored
cd corkbored
py -m venv .venv
.venv\Scripts\pip install -r requirements.txt pyinstaller pywebview
.venv\Scripts\python scripts\fetch_ffmpeg.py
.venv\Scripts\pyinstaller --noconfirm corkbored.spec
.\dist\Corkbored\Corkbored.exe
```

The app is the whole `dist\Corkbored\` folder; keep it together.

### The built-in narrator's voice files

The narrator is built into the app, but its two voice files (~337MB) are a
separate download. The first time you open the Record tab, it shows the
exact folder they belong in and a command you can copy to fetch them. The
folder is:

| | |
|---|---|
| macOS | `~/Library/Application Support/Corkbored/assets/tts/` |
| Linux | `~/.local/share/corkbored/assets/tts/` |
| Windows | `%LOCALAPPDATA%\Corkbored\assets\tts\` |

Existing installs keep using their legacy data folder when the new folder
does not exist; Settings shows the active location. `CORKBORED_DATA` overrides
it.

Download both files into that folder, then restart Corkbored:

- [kokoro-v1.0.onnx](https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx)
- [voices-v1.0.bin](https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin)

You don't need these if you record your own voice.

## How it's made

Projects are plain files on your disk. Narration drives picture timing.
Code checks what it can measure before Claude reviews selected frames.
Python, ffmpeg and Chromium draw the cut; there is no front-end build step.

## History

Corkbored began as **Youslop**, a joke: a tool to make low-effort AI video so
easy that YouTube would have to deal with it. Building it properly turned it
into the opposite: a studio for careful, researched video that one person
can make well. The name changed to match.

## Licence

[GPL-3.0](LICENSE). ffmpeg and x264 are bundled under their GPL terms;
[THIRD-PARTY.md](THIRD-PARTY.md) lists included components and licences.
Archive search records provenance; check each asset's rights before publishing.
