# Youslop

Youslop turns an idea or a script into a narrated, illustrated video: Claude
writes it, the archives (Wikimedia, the Library of Congress, the Met, and more)
supply the pictures, you supply the voice, ffmpeg cuts the final file. It runs
entirely on your own machine — your Claude subscription or API key, your
microphone, your render.

## Why this exists

The name is honest about what it makes. Youslop turns an idea into a narrated,
illustrated video with almost no effort — that's slop, by most people's
definition, and pretending otherwise would be the actual dishonesty.

YouTube is already filling up with this kind of thing: faceless channels
pumping out cheap, repetitive AI video, because making a video the old way
took real effort, and a little effort used to be enough to keep the worst of
it out. That filter is gone. Anyone can prompt their way to a video now,
whether this tool exists or not.

So rather than pretend to be above it, Youslop leans in: a free, genuinely
capable local tool that makes slop *easier*, not harder, to produce. The bet
is that flooding the problem rather than politely ignoring it is what
actually forces a response — a platform can tolerate a slow trickle of AI
video indefinitely, but not an ocean of it. At some point the only way to
protect real creators from being buried is to clamp down on low-effort AI
content properly, and that point arrives faster the easier slop is to make.
Youslop is built to help drag that day forward, not to be the exception that
proves the rule.

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
  defaults.
- **Video styles** — Documentary, Video essay, Handwritten board, or design
  your own with Claude and reuse it across videos. Styles export and import as
  a single file, so you can share one or move it between installs.
- **Diagrams and custom slides** let Claude draw a shape or a whole slide
  layout for a paragraph that has no real photograph to illustrate it.
- Settings (gear icon, bottom of the sidebar) is where API keys, the model,
  and the data folder live.

## Licence

GPLv3 — see [LICENSE](LICENSE). ffmpeg and x264, both GPL, are bundled; see
[THIRD-PARTY.md](THIRD-PARTY.md) for the full list of what's in here and
under what terms.
