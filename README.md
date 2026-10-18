# Youslop

Youslop turns an idea or a script into a narrated, illustrated video: Claude
writes it, it searches for images or you supply them, it generates a voice or you supply the voice yourself, ffmpeg cuts the final file. It runs
entirely on your own machine — your Claude subscription or API key, your
microphone, your render. Voila a low effort slop youtube video.

## Why this exists

YouTube is now overrun with low effort slop content. This janky vibe coded tool aims to make it so easy and lazy to produce low effort slop content that YouTube will be foreced to implement solutions to make slop content unprofitable. Real creators that make quality content are being drowned out in a sea of garbage, and users are forced to wade through that sea of garbage to find the creator we like. This must end.

Here is an Example video created with no effort at all:
https://www.youtube.com/watch?v=YAlnSGxnru4

## Using it

**Download:** grab the latest build for your OS from
[Releases](https://github.com/Liam-Griffiths/youslop/releases) and run it —
no Python, no Homebrew, nothing else to install.

**From source:**

```
git clone https://github.com/Liam-Griffiths/youslop.git
cd youslop
./run.sh
```

Either way, you'll need one of:

- the [Claude Code CLI](https://claude.com/claude-code), signed in — free with
  a Claude subscription, and the default
- an [Anthropic API key](https://console.anthropic.com/), set in Settings

From there: **New video** → describe the idea (or paste a script) → pick a
channel, a look, how often the picture changes → write the script. Claude
plans the visuals, the archives get searched, you record your voice over each
paragraph (or let the built-in AI narrator read it), and **Render** cuts the
final file.

A few things worth knowing once you're in:

- **Channels** give a series of videos the same opening slate, colours and
  defaults. A one-off video doesn't need one: on its Render tab it can open on
  a title card and close on an end card of its own, drawn from its own title
  and colours. Standalone videos have their own section at the top of the home
  page and a link in the sidebar.
- **Timeline** at the top of the Render tab lays the whole cut out in time:
  scrub it, step a frame at a time (←/→), jump paragraph to paragraph
  (Shift+←/→), play it (Space) from small quarter-size proxies, and edit the
  words, picture, cues or recording of whatever is under the playhead. Pictures
  are drawn only as you reach them, then kept until the script changes. The
  opening slate, end card and music bed are on it too.
- **Preview this bit** on the Media tab renders just the picture you're looking
  at — the real framing, drift, titles and narration, small and rough — instead
  of rendering the whole video to see one shot.
- **Chapters**: *start a chapter* on any paragraph in the Script tab puts a
  full-frame card in the pause before it, and gives that paragraph its own
  picture. Turn the cards off for the whole video on the Render tab.
- **Video styles** — Documentary, Video essay, Handwritten board, or design
  your own with Claude and reuse it across videos. Styles export and import as
  a single file, so you can share one or move it between installs.
- **Drawn cuts** — five more styles that draw every frame themselves, each
  aimed at a different kind of channel: **Flameboat** (rapid-fire tech
  explainer: B-roll, code, terminals, memes, a cut on every clause),
  **Casefile** (true crime on a lamp-lit corkboard, pinned up as you talk),
  **Loudmouth** (kinetic type for motivation, faith and spoken word), **Group
  Chat** (storytime: a message thread that cuts away to the scene and back)
  and **Ticker** (a markets terminal for finance channels). Claude writes each paragraph's *cues* — what
  appears, landing on which words — and you can edit them on the Pictures
  tab. A paragraph with none is drawn from its narration.
- **Diagrams and custom slides** let Claude draw a shape or a whole slide
  layout for a paragraph that has no real photograph to illustrate it.
- **Project files** move a video between computers: **save project file…**
  on a video's page, **open project file…** on the New video page. The file
  carries the script, pictures, recordings and settings, but not the finished
  render.
- Settings (gear icon, bottom of the sidebar) is where API keys, the model,
  and the data folder live.

## Building it yourself

If there's no release for your platform, or you'd rather build your own, it
takes about five minutes. You need **Python 3.12 or newer** and **git**. The
build is for the machine you build on: a Mac makes a Mac app, an ARM Linux
machine makes an ARM Linux app, and so on.

### macOS

```sh
git clone https://github.com/Liam-Griffiths/youslop.git
cd youslop
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt pyinstaller pywebview
.venv/bin/python scripts/fetch_ffmpeg.py
.venv/bin/pyinstaller --noconfirm youslop.spec
open dist/Youslop.app
```

Drag `dist/Youslop.app` into Applications to keep it. If macOS says it "can't
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

GStreamer reads its plugin list once at startup, so restart Youslop after
installing them. To check a machine before guessing — `gst-inspect-1.0
avdec_h264` prints the decoder if it is there and nothing if it is not.

Running a downloaded Linux release instead of building it? You still need
WebKitGTK and both GStreamer packages: the `webkit2gtk-4.1`/`webkit2gtk4.1`,
plugins-good and libav packages from the line for your distro above.

Then:

```sh
git clone https://github.com/Liam-Griffiths/youslop.git
cd youslop
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt pyinstaller pywebview pygobject
.venv/bin/python scripts/fetch_ffmpeg.py
.venv/bin/pyinstaller --noconfirm youslop.spec
./dist/Youslop/Youslop
```

The app is the whole `dist/Youslop/` folder. Move it anywhere you like, but
keep the folder together.

### Windows

In PowerShell:

```powershell
git clone https://github.com/Liam-Griffiths/youslop.git
cd youslop
py -m venv .venv
.venv\Scripts\pip install -r requirements.txt pyinstaller pywebview
.venv\Scripts\python scripts\fetch_ffmpeg.py
.venv\Scripts\pyinstaller --noconfirm youslop.spec
.\dist\Youslop\Youslop.exe
```

The app is the whole `dist\Youslop\` folder; keep it together.

### The AI narrator's voice files

The narrator is built into the app, but its two voice files (~337MB) are a
separate download. The first time you open the Record tab, it shows the
exact folder they belong in and a command you can copy to fetch them. The
folder is:

| | |
|---|---|
| macOS | `~/Library/Application Support/Youslop/assets/tts/` |
| Linux | `~/.local/share/youslop/assets/tts/` |
| Windows | `%LOCALAPPDATA%\Youslop\assets\tts\` |

Download both files into that folder, then restart Youslop:

- [kokoro-v1.0.onnx](https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx)
- [voices-v1.0.bin](https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin)

You don't need these if you record your own voice.

## Licence

GPLv3 — see [LICENSE](LICENSE). ffmpeg and x264, both GPL, are bundled; see
[THIRD-PARTY.md](THIRD-PARTY.md) for the full list of what's in here and
under what terms.
