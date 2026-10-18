"""Project data model. Everything is plain dict-serialisable for project.json."""
from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

# What `Project.music` holds when the creator has not named a track. Nothing
# selected means no bed at all: a video that was never given music should come
# out silent under the narration, not carrying whatever happened to be in
# assets/music. Asking for one to be picked is a choice of its own, and this is
# what that choice looks like. It cannot collide with a filename.
AUTO_MUSIC = "__auto__"


def _uid(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:8]}"


@dataclass
class MediaCandidate:
    """One searchable asset from a provider, before or after download."""
    id: str
    provider: str                 # wikimedia | openverse | pexels | ...
    kind: str                     # image | video
    title: str = ""
    url: str = ""                 # full-resolution download URL
    thumb: str = ""               # preview URL for the picker grid
    source_page: str = ""         # human-facing attribution page
    author: str = ""
    license: str = ""
    width: int = 0
    height: int = 0
    duration: float = 0.0         # video only
    score: float = 0.0            # ranking score, higher is better
    query: str = ""               # the query that surfaced it
    local_path: str = ""          # set once downloaded, relative to project dir
    ref: str = ""                 # provider-native handle, used to upgrade `url`
    full: bool = False            # True once `url` points at a render-quality file
    # Point of interest as [x, y] in 0..1 of the source image. When set, the
    # crop and the Ken Burns move are constrained to keep it on screen, which
    # is what stops a slow zoom from wandering off a subject's face.
    focal: list[float] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Take:
    """A recorded narration take for one slide."""
    path: str = ""                # processed wav, relative to project dir
    raw_path: str = ""            # original browser upload
    duration: float = 0.0
    peak_db: float = 0.0
    recorded_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Slide:
    """One narration paragraph and the visual that sits under it."""
    id: str = field(default_factory=lambda: _uid("s"))
    section: str = "main"                 # intro | main | conclusion
    beat: str = ""                        # outline beat this paragraph serves
    title: str = ""                       # lower-left typography; "" = no title
    # A full-frame card announcing the section this paragraph opens, held in
    # the silence that precedes it. "" = this paragraph opens nothing. The
    # words are the card's, not the paragraph's: a chapter is usually titled
    # more broadly than the paragraph that happens to start it.
    chapter: str = ""
    narration: str = ""
    visual_note: str = ""                 # plain-English description of the shot
    queries: list[str] = field(default_factory=list)
    prefer_kind: str = "image"            # image | video | map
    # Only meaningful when prefer_kind == "map": the point the widget was
    # left on (0/0/0 = never set), so reopening the picker re-centres on it
    # instead of the whole world. See app/maps.py.
    map_place: str = ""                   # label shown in the picker/credits
    map_lat: float = 0.0
    map_lon: float = 0.0
    map_zoom: int = 0
    map_kind: str = "satellite"           # satellite | street
    map_style: str = "still"              # still | establishing
    candidates: list[dict] = field(default_factory=list)
    chosen_id: str = ""
    # The take the video uses: this paragraph's entry in `takes` for the
    # project's chosen voice (`Project.voice_track`). Everything downstream —
    # the renderer, the timeline, the recorded counts — reads only this.
    take: dict | None = None
    # Every voice this paragraph has been read in, kept side by side so trying
    # another voice never costs the one already there: "mic", "kokoro",
    # "elevenlabs", "openai" -> that read's take. Each lives in its own folder
    # under takes/. Write through `Project.set_take`, not into this directly.
    takes: dict = field(default_factory=dict)
    locked_media: bool = False            # user picked; don't auto-overwrite
    # auto = follow the channel's picture_every rule; hold = keep the picture
    # already on screen; new = always start a fresh picture here.
    picture_mode: str = "auto"            # auto | hold | new
    # What the handwritten board format draws for this paragraph. All of it is
    # optional: a slide with none of it set gets a lead and some points derived
    # from its own narration, and "auto" picks the template that fits whatever
    # it has. Ignored entirely by the other two formats. See app/board.py.
    board_template: str = "auto"          # auto | a key from board.TEMPLATES
    board_lead: str = ""                  # the line the slide is about
    board_points: list[str] = field(default_factory=list)   # the lines under it
    board_note: str = ""                  # footnote, caption or attribution
    # A diagram spec — the thing app/diagram.py draws. Set by the diagram
    # editor, by the writer, or by an agent calling the diagram endpoint.
    # Rendered as a media candidate like any picture, and drawn full-frame by
    # the board format's "diagram" template.
    diagram: dict = field(default_factory=dict)
    # A custom slide spec — positioned text, shapes and archive photos, each
    # on its own reveal beat. What the diagram spec is for a shape, this is
    # for a layout no template anticipated. See app/custom_slide.py.
    custom: dict = field(default_factory=dict)
    # What the drawn cuts put on screen, keyed by cut ("flameboat",
    # "casefile", ...): a list of cues, each landing on the words in its `on`.
    # Keyed so switching a video between cuts keeps what was written for each.
    # A cut with nothing here draws from the narration. See app/cuts/.
    cues: dict = field(default_factory=dict)

    @property
    def word_count(self) -> int:
        return len(self.narration.split())

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["word_count"] = self.word_count
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Slide":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


def group_slides(slides: list["Slide"], every: int) -> list[list["Slide"]]:
    """Split paragraphs into the runs that share one picture.

    `every` is the default run length. A slide can override it: "hold" joins the
    run in front of it whatever the count says, "new" always starts its own.
    A paragraph that opens a chapter also starts its own, whatever it asked
    for: the card announcing it is drawn at the end of the segment before it,
    so a chapter that began mid-picture would have its card land in the middle
    of the previous section instead of on the boundary.
    """
    every = max(1, min(8, int(every or 1)))
    runs: list[list["Slide"]] = []
    n = 0
    for slide in slides:
        mode = getattr(slide, "picture_mode", "auto")
        if (getattr(slide, "chapter", "") or "").strip():
            mode = "new"
        if not runs or mode == "new" or (mode != "hold" and n >= every):
            runs.append([])
            n = 0
        runs[-1].append(slide)
        n += 1
    return runs


@dataclass
class Style:
    # How the pictures are staged. "kenburns" is the documentary cut: the
    # picture fills the frame and drifts. "essay" is the video-essay cut: the
    # whole picture sits inside a bordered slide over a blurred version of
    # itself, and the narration is set on screen as captions. "board" is the
    # handwritten cut: white ink on a grey-blue slide that fills up as you
    # talk, pictures taped onto it rather than filling it. See render.py.
    # The five drawn cuts in app/cuts/ — flameboat, casefile, loudmouth,
    # groupchat, ticker — draw every frame themselves and join on hard cuts.
    format: str = "kenburns"        # kenburns | essay | board | a cut key | custom:<id>
    vignette: float = 0.34          # 0 = off, 1 = heavy
    ken_burns: bool = True
    ken_burns_amount: float = 0.10  # fractional zoom over a slide
    transition: float = 0.55        # crossfade seconds
    music_db: float = -22.0         # dB below the narration (bed is loudness-matched first)
    duck_db: float = -11.0          # how far music drops under narration
    title_font: str = ""            # resolved automatically when empty
    accent: str = "#E8C36A"
    # The second colour. Flat-black-and-one-gold templates ignore it; the
    # colourful ones are built on the pair, and patterns alternate between them.
    accent2: str = "#7FA6B8"
    # Which theme these colours came from. It also decides the ground, the ink
    # and which icons the patterns are tiled from — see themes.palette().
    theme: str = "archive"
    grade: str = "warm"             # warm | neutral | cool | mono
    # How many paragraphs share one picture. 1 is a new picture every paragraph;
    # raise it when the archives are thin, and each picture holds proportionally
    # longer with a correspondingly slower Ken Burns move over the whole hold.
    picture_every: int = 1
    # Whether a paragraph marked as opening a chapter gets its card on screen.
    # Off renders the cut straight through, chapter marks and all, which is
    # what you want for a video that is one continuous argument.
    chapter_cards: bool = True
    # Base silence after each paragraph. The actual pause varies around this with
    # how the paragraph ended — see audio.paragraph_gaps.
    paragraph_gap: float = 0.42
    # The board format's four knobs, ignored by the other two. `board_hand` is
    # which handwriting it is lettered in (see diagram.HANDS), `board_ground`
    # the colour of the board itself, `board_grain` how much tooth the surface
    # has, and `board_settle` how long one element takes to arrive once its
    # turn comes.
    board_hand: str = "marker"      # marker | bradley | chalk | casual
    board_ground: str = "#3A4552"
    board_grain: float = 0.5
    board_settle: float = 0.5
    # Which variant of a drawn cut — "paper" for Loudmouth, "light" for Group
    # Chat, and so on (each cut's LOOKS). Empty is the cut's own default.
    cut_look: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Voice:
    """How a raw take becomes the finished read.

    Set up once against a test recording in the record tab's mic panel, kept on
    the channel so every video in a series is read and cleaned the same way.
    Every field is a plain number, so the whole chain can be swept from the UI
    and re-applied to takes that are already recorded.
    """
    preset: str = "warm"            # warm | neutral | bright | live | custom
    low_cut: float = 85.0           # Hz — desk rumble and room boom, out
    warmth: float = 2.2             # dB at 180Hz — chest, body
    box_cut: float = 3.0            # dB out at 430Hz — the small-room honk
    presence: float = 2.0           # dB at 3.1kHz — consonants, intelligibility
    air: float = 1.0                # dB shelf from 9.5kHz — "expensive mic"
    de_room: float = 0.65           # 0..1 how hard the reflections are pushed down
    denoise: float = 0.5            # 0..1 broadband hiss and hum
    compression: float = 0.55       # 0..1 how level the read is held
    sibilance: float = 0.35         # 0..1 de-esser, paying for the presence lift
    target_lufs: float = -16.0      # every take lands here
    # Chrome's own denoiser is aimed at a call, not a read: it fights the chain
    # below and smears the top end. Worth a try only in a genuinely bad room.
    browser_cleanup: bool = False

    # What each knob is allowed to be. A slider cannot leave these, but a
    # hand-edited project.json can, and a de-esser at 400% is an unpleasant
    # way to find that out halfway through a render.
    LIMITS = {
        "low_cut": (40.0, 160.0), "warmth": (-6.0, 6.0), "box_cut": (0.0, 8.0),
        "presence": (-4.0, 6.0), "air": (-3.0, 6.0), "de_room": (0.0, 1.0),
        "denoise": (0.0, 1.0), "compression": (0.0, 1.0), "sibilance": (0.0, 1.0),
        "target_lufs": (-24.0, -12.0),
    }

    def clamp(self) -> "Voice":
        for key, (lo, hi) in self.LIMITS.items():
            setattr(self, key, max(lo, min(hi, float(getattr(self, key)))))
        return self

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# One entry in the pronunciation guide. Stored as a plain dict on the channel
# and the project, the way credits and candidates are.
#
#   term    what appears in the script, e.g. "Elon"
#   respell a plain-English respelling the creator typed, e.g. "ell-on"
#   ipa     the phonemes actually used; wins over respell when both are set
#   note    why, for whoever reads this in six months
#
# `ipa` is the source of truth rather than `respell` because a respelling is a
# guess at espeak's spelling rules and frequently loses: "Ehlon" comes out
# "AY-lon". The UI resolves a respelling to phonemes so it can be heard and
# corrected, and keeps the result here.
SAY_FIELDS = ("term", "respell", "ipa", "note")


@dataclass
class Narrator:
    """Who reads the script: you at a microphone, or a local model.

    A whole-video decision rather than a per-paragraph one, because a video that
    switches between a real voice and a synthetic one halfway through sounds
    broken rather than varied. `Voice` above still applies either way — it is
    the chain the finished take is levelled through.
    """
    mode: str = "mic"               # mic | ai
    # Which model reads it in "ai" mode: "kokoro" on this machine, or a hosted
    # service — "elevenlabs" or "openai" (see app/voice_cloud.py).
    engine: str = "kokoro"
    voice: str = "bm_george"        # that engine's voice id; tts.VOICES for Kokoro
    model: str = ""                 # a hosted engine's model; "" is its default
    speed: float = 1.0              # 0.5–1.5, 1.0 is the model's own pace

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# The four starting points the mic panel offers. "warm" is the default: a
# close podcast read. "live" is for a room that cannot be fixed, and trades
# some naturalness for getting the walls out of the recording.
VOICE_PRESETS: dict[str, dict[str, float]] = {
    "warm":    {"warmth": 2.2, "box_cut": 3.0, "presence": 2.0, "air": 1.0,
                "de_room": 0.65, "denoise": 0.5, "compression": 0.55,
                "sibilance": 0.35, "low_cut": 85.0},
    "neutral": {"warmth": 0.8, "box_cut": 2.0, "presence": 2.0, "air": 1.4,
                "de_room": 0.40, "denoise": 0.4, "compression": 0.40,
                "sibilance": 0.30, "low_cut": 80.0},
    "bright":  {"warmth": 0.0, "box_cut": 2.5, "presence": 3.2, "air": 2.4,
                "de_room": 0.50, "denoise": 0.5, "compression": 0.55,
                "sibilance": 0.45, "low_cut": 95.0},
    "live":    {"warmth": 2.6, "box_cut": 4.5, "presence": 1.8, "air": 0.6,
                "de_room": 0.85, "denoise": 0.65, "compression": 0.65,
                "sibilance": 0.35, "low_cut": 100.0},
}


@dataclass
class Presenter:
    """An optional piece of camera footage of you, cut into the video.

    Usually a short face-to-face beat straight after the channel slate, before
    the archive material takes over. Its own audio is kept and treated as part
    of the voice bus, so the music ducks under it exactly as it does under the
    narration.
    """
    path: str = ""                  # relative to the project dir
    filename: str = ""              # original name, for the UI
    source_duration: float = 0.0
    trim_start: float = 0.0
    trim_end: float = 0.0           # seconds trimmed off the tail
    position: str = "after_intro"   # start | after_intro | end
    enabled: bool = True
    has_audio: bool = True
    width: int = 0
    height: int = 0
    focal: list[float] = field(default_factory=list)

    @property
    def duration(self) -> float:
        """Playable length after trimming."""
        d = self.source_duration - max(0.0, self.trim_start) - max(0.0, self.trim_end)
        return max(0.0, round(d, 3))

    def usable(self) -> bool:
        return bool(self.path) and self.enabled and self.duration >= 0.8

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["duration"] = self.duration
        return d


@dataclass
class IntroSpec:
    """The animated opening slate every video on a channel shares."""
    template: str = "columns"       # columns (currently the only one)
    duration: float = 5.0
    columns: int = 5
    stagger: float = 0.13           # gap between each column's entrance
    fly_duration: float = 0.62      # how long one column takes to land
    subjects: list[str] = field(default_factory=list)   # who appears in the columns
    images: list[str] = field(default_factory=list)     # resolved, relative to channel dir
    credits: list[dict] = field(default_factory=list)   # provenance for those images
    focals: list[list[float]] = field(default_factory=list)  # per-image [x, y], parallel to images
    show_video_title: bool = True
    hold: float = 1.0               # beat at the end before the first slide
    # A sting of its own for the slate. The main music bed holds off until the
    # slate is over, so the two never fight.
    music: str = ""                 # relative to the channel dir, "" = none
    music_filename: str = ""
    music_db: float = -4.0          # relative to the narration's -16 LUFS
    music_tail: float = 1.1         # how long it rings on over the first slide
    # A sting is usually cut from a longer track, so the slate takes a window of
    # it rather than its opening: `music_start` seconds in, for as long as the
    # slate plus the tail runs. `music_duration` is the whole file's length,
    # kept here so the UI can bound that offset without probing the file again.
    music_start: float = 0.0
    music_fade: float = 1.35        # fade-out at the end of the window, 0 = cut
    music_duration: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class OutroSpec:
    """The end screen: the held card the video finishes on.

    YouTube's own end-screen elements — the video cards, the subscribe badge —
    are overlaid by YouTube on top of the last stretch of the video, and can
    only be placed where the picture leaves room for them. So a template here is
    mostly a question of *where the holes are*: the slots are drawn as empty
    plates for the creator to line the real elements up with in Studio.
    """
    enabled: bool = False
    template: str = "twoup"
    duration: float = 12.0          # YouTube allows an end screen 5-20s long
    slots: int = 2                  # video/playlist plates the layout leaves room for
    subscribe: bool = True          # reserve a round plate for the subscribe badge
    cta: str = ""                   # "" = a line that suits the template
    handle: str = ""                # @handle, set under the channel name
    show_video_title: bool = False
    settle: float = 0.7             # how long the layout takes to arrive
    countdown: bool = True          # hairline showing how long the card is up
    backdrop: float = 0.0           # 0 = the template's own ground; up to 1 = the
    #                                 last picture of the video, knocked back
    # How long the music bed takes to fade out at the end. It exists here rather
    # than in Style because it is the end screen that makes it a question: a bed
    # that dies on the first frame of a 20-second card leaves it sitting silent.
    music_fade: float = 6.0
    # A sting of its own for the card, the closing twin of `IntroSpec.music`:
    # it starts as the card comes up and runs for as long as the card is on
    # screen (shorter if the file is). The bed's own fade-out is unchanged.
    sting: str = ""                 # relative to the owner's folder, "" = none
    sting_filename: str = ""
    sting_db: float = -4.0          # relative to the narration's -16 LUFS
    sting_start: float = 0.0        # seconds into the file the window opens
    sting_fade: float = 2.0         # fade-out at the end of the window, 0 = cut
    sting_duration: float = 0.0     # the whole file's length, for the UI

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AvatarSpec:
    """A still host image pinned in a corner of every essay-format video.

    Deliberately a picture rather than an animation: the look this borrows
    from is a drawn character sitting in the corner reacting, not a rigged
    puppet, and a still costs one overlay instead of a second video track.
    Only the essay format draws it; the documentary cut ignores it entirely.
    """
    enabled: bool = False
    path: str = ""                  # relative to the channel dir
    filename: str = ""              # original name, for the UI
    position: str = "bottom_right"  # bottom_right | bottom_left
    scale: float = 0.24             # fraction of frame height

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Thumb:
    """The YouTube thumbnail: one image, a few words, 1280×720.

    Separate from the video's own typography, because a thumbnail is read at
    120px wide in a sidebar and needs far fewer, far bigger words than a slate.
    """
    template: str = "banner"
    headline: str = ""              # "" = fall back to the video title
    kicker: str = ""                # small line above the headline
    image: str = ""                 # project-relative path, "" = nothing picked
    focal: list[float] = field(default_factory=list)   # [x, y] kept in frame
    credit: dict = field(default_factory=dict)         # provenance of that image
    accent: str = ""                # "" = inherit the project's accent
    uppercase: bool = True
    text_scale: float = 1.0         # 0.7 – 1.3, on top of the fitted size
    dim: float = 0.55               # how far the picture is knocked back for type
    flip: bool = False              # mirror the layout, where the style has sides
    rendered_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Channel:
    """A series. Videos in one inherit its look and open on its slate."""
    id: str
    name: str                       # "Who were they?"
    tagline: str = ""               # small line under the name on the slate
    concept: str = ""               # what the series covers; steers scripts and casting
    default_minutes: int = 12
    tone: str = "warm documentary"
    style: Style = field(default_factory=Style)
    voice: Voice = field(default_factory=Voice)
    narrator: Narrator = field(default_factory=Narrator)
    lexicon: list[dict] = field(default_factory=list)   # pronunciations, the series
    music: str = ""                 # the bed new videos start on; "" = none
    intro: IntroSpec = field(default_factory=IntroSpec)
    outro: OutroSpec = field(default_factory=OutroSpec)
    avatar: AvatarSpec = field(default_factory=AvatarSpec)
    # The thumbnail style new videos in this channel start on. A theme sets it
    # alongside the slate and the end screen; the video can still change it.
    thumb_template: str = "banner"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "name": self.name, "tagline": self.tagline,
            "concept": self.concept, "default_minutes": self.default_minutes,
            "tone": self.tone, "style": self.style.to_dict(),
            "voice": self.voice.to_dict(), "narrator": self.narrator.to_dict(),
            "lexicon": self.lexicon,
            "music": self.music, "intro": self.intro.to_dict(),
            "outro": self.outro.to_dict(), "avatar": self.avatar.to_dict(),
            "thumb_template": self.thumb_template,
            "created_at": self.created_at, "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Channel":
        style = Style(**{k: v for k, v in (d.get("style") or {}).items()
                         if k in Style.__dataclass_fields__})
        intro = IntroSpec(**{k: v for k, v in (d.get("intro") or {}).items()
                             if k in IntroSpec.__dataclass_fields__})
        voice = Voice(**{k: v for k, v in (d.get("voice") or {}).items()
                         if k in Voice.__dataclass_fields__})
        narrator = Narrator(**{k: v for k, v in (d.get("narrator") or {}).items()
                               if k in Narrator.__dataclass_fields__})
        # `outro` used to be a bare flag for a static card. An old channel that
        # had it on keeps an end screen; the template it gets is the default.
        raw_outro = d.get("outro")
        if isinstance(raw_outro, bool):
            outro = OutroSpec(enabled=raw_outro)
        else:
            outro = OutroSpec(**{k: v for k, v in (raw_outro or {}).items()
                                 if k in OutroSpec.__dataclass_fields__})
        avatar = AvatarSpec(**{k: v for k, v in (d.get("avatar") or {}).items()
                               if k in AvatarSpec.__dataclass_fields__})
        known = ({f for f in cls.__dataclass_fields__}
                 - {"style", "intro", "voice", "outro", "narrator", "avatar"})
        return cls(**{k: v for k, v in d.items() if k in known},
                   style=style, intro=intro, voice=voice, outro=outro,
                   narrator=narrator, avatar=avatar)


def new_channel(name: str, concept: str = "") -> Channel:
    return Channel(id=_uid("c"), name=name.strip(), concept=concept.strip())


@dataclass
class Project:
    id: str
    idea: str
    title: str = ""
    subtitle: str = ""
    channel_id: str = ""
    use_intro: bool = True
    use_outro: bool = True
    # A standalone video's own opening and close. A video inside a channel
    # takes both from the channel — that is most of what a channel is for —
    # so these are read only when `channel_id` is empty, and they let a
    # one-off video open and close properly without inventing a series to
    # hang it off. Only the type-led slate templates apply: the cast-led ones
    # need portraits, which belong to a channel. See render._slate_channel.
    #
    # Both are off until asked for — an empty `intro.template` and an
    # `outro.enabled` of False — rather than following `use_intro`, which has
    # always defaulted to True and means "use the channel's, if it has one".
    # Reading that flag as consent for a slate nobody set up would put an
    # opening card on the front of every standalone video already on disk.
    intro: IntroSpec = field(default_factory=lambda: IntroSpec(template=""))
    outro: OutroSpec = field(default_factory=OutroSpec)
    # A pasted article is kept in the project directory as source.txt rather than
    # in this record: it can be thousands of words, and project.json is read and
    # rewritten constantly. Only the flag and the mode live here.
    has_source: bool = False
    fidelity: str = "faithful"      # faithful | adapted
    tone: str = "warm documentary"
    target_minutes: int = 12
    status: str = "new"      # new | scripted | media | recording | rendered
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    outline: dict = field(default_factory=dict)
    # What research.gather() found before the outline was written: sourced
    # facts, open questions, corrections to the creator's own idea, and
    # (added after the script is written) any paragraph script_gen.verify_script
    # flagged as unsupported. {} when SEARXNG_URL isn't set or nothing came
    # back — a video written before this existed, or without research
    # configured, just has an empty one.
    research: dict = field(default_factory=dict)
    # Work in progress from a script run that did not finish: the outline it
    # settled on and the sections already written. A run costs real model time,
    # and a usage limit two sections into six used to throw all of it away.
    # Cleared the moment a run completes.
    draft: dict = field(default_factory=dict)
    slides: list[Slide] = field(default_factory=list)
    style: Style = field(default_factory=Style)
    voice: Voice = field(default_factory=Voice)
    presenter: Presenter = field(default_factory=Presenter)
    thumb: Thumb = field(default_factory=Thumb)
    narrator: Narrator = field(default_factory=Narrator)
    # Which voice the whole video uses — a key of `Slide.takes`. One voice for
    # the whole video, chosen deliberately: a script read half by ElevenLabs
    # and half by the local model sounds like two narrators.
    voice_track: str = ""
    lexicon: list[dict] = field(default_factory=list)   # pronunciations, this video
    music: str = ""          # a filename in assets/music, AUTO_MUSIC, or "" = none
    render: dict = field(default_factory=dict)   # last render result
    log: list[str] = field(default_factory=list)

    # -------------------------------------------------------------- helpers
    def slide(self, sid: str) -> Slide | None:
        return next((s for s in self.slides if s.id == sid), None)

    def picture_runs(self) -> list[list[str]]:
        """Slide ids grouped by the picture they share."""
        return [[s.id for s in run]
                for run in group_slides(self.slides, self.style.picture_every)]

    def est_seconds(self) -> float:
        from .config import PARAGRAPH_GAP, WORDS_PER_MINUTE
        words = sum(s.word_count for s in self.slides)
        return words / WORDS_PER_MINUTE * 60 + PARAGRAPH_GAP * len(self.slides)

    def recorded_seconds(self) -> float:
        return sum((s.take or {}).get("duration", 0.0) for s in self.slides)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "idea": self.idea,
            "title": self.title,
            "subtitle": self.subtitle,
            "channel_id": self.channel_id,
            "use_intro": self.use_intro,
            "use_outro": self.use_outro,
            "intro": self.intro.to_dict(),
            "outro": self.outro.to_dict(),
            "has_source": self.has_source,
            "fidelity": self.fidelity,
            "tone": self.tone,
            "target_minutes": self.target_minutes,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "outline": self.outline,
            "research": self.research,
            "draft": self.draft,
            "slides": [s.to_dict() for s in self.slides],
            "style": self.style.to_dict(),
            "voice": self.voice.to_dict(),
            "presenter": self.presenter.to_dict(),
            "thumb": self.thumb.to_dict(),
            "narrator": self.narrator.to_dict(),
            "lexicon": self.lexicon,
            "music": self.music,
            "render": self.render,
            "log": self.log[-200:],
            "picture_runs": self.picture_runs(),
            "est_seconds": self.est_seconds(),
            "recorded_seconds": self.recorded_seconds(),
            "recorded_count": sum(1 for s in self.slides if s.take),
            "voice_track": self.voice_track,
            "voice_tracks": self.track_counts(),
        }

    # --------------------------------------------------------------- voices
    def set_take(self, slide: "Slide", track: str, take: dict | None) -> None:
        """Store (or clear) one paragraph's read in one voice. It becomes the
        take the video uses only if that voice is the video's voice — or if
        the video has no voice yet, in which case this one becomes it."""
        if take:
            slide.takes[track] = take
        else:
            slide.takes.pop(track, None)
        if not self.voice_track and take:
            self.use_track(track)
        elif track == self.voice_track:
            slide.take = take

    def use_track(self, track: str) -> None:
        """Make `track` the voice of the whole video. Nothing is deleted:
        paragraphs not read in it yet simply have no take until they are."""
        self.voice_track = track
        for s in self.slides:
            s.take = s.takes.get(track)

    def track_counts(self) -> dict[str, int]:
        """How many paragraphs each voice has read."""
        out: dict[str, int] = {}
        for s in self.slides:
            for track in s.takes:
                out[track] = out.get(track, 0) + 1
        return out

    def sync_takes(self) -> None:
        """Keep `take` and `takes` agreeing.

        On load, a project from before voices were kept apart has only `take`;
        each one is filed under the voice it was read in, and the voice most of
        the script was read in becomes the video's. Before a save, the active
        take is written back to its voice, because a good deal of code adjusts
        `slide.take` in place (a corrected duration, a re-cleaned recording)."""
        for s in self.slides:
            if s.take and not s.takes:
                s.takes[take_track(s.take)] = s.take
        if not self.voice_track:
            counts = self.track_counts()
            if counts:
                self.voice_track = max(counts, key=counts.get)
                for s in self.slides:
                    s.take = s.takes.get(self.voice_track)
            return
        for s in self.slides:
            if s.take:
                s.takes[self.voice_track] = s.take
            else:
                s.takes.pop(self.voice_track, None)

    @classmethod
    def from_dict(cls, d: dict) -> "Project":
        style = Style(**{k: v for k, v in (d.get("style") or {}).items()
                         if k in Style.__dataclass_fields__})
        voice = Voice(**{k: v for k, v in (d.get("voice") or {}).items()
                         if k in Voice.__dataclass_fields__})
        presenter = Presenter(**{k: v for k, v in (d.get("presenter") or {}).items()
                                 if k in Presenter.__dataclass_fields__})
        thumb = Thumb(**{k: v for k, v in (d.get("thumb") or {}).items()
                         if k in Thumb.__dataclass_fields__})
        narrator = Narrator(**{k: v for k, v in (d.get("narrator") or {}).items()
                               if k in Narrator.__dataclass_fields__})
        # A project written before a video could carry its own opening has no
        # `intro` at all, and must not acquire one by inheriting IntroSpec's
        # cast-led default — hence the empty template rather than {}.
        raw_intro = d.get("intro")
        intro = (IntroSpec(**{k: v for k, v in raw_intro.items()
                              if k in IntroSpec.__dataclass_fields__})
                 if isinstance(raw_intro, dict) else IntroSpec(template=""))
        outro = OutroSpec(**{k: v for k, v in (d.get("outro") or {}).items()
                             if k in OutroSpec.__dataclass_fields__})
        known = ({f for f in cls.__dataclass_fields__}
                 - {"slides", "style", "voice", "presenter", "thumb", "narrator",
                    "intro", "outro"})
        base = {k: v for k, v in d.items() if k in known}
        p = cls(
            **base,
            slides=[Slide.from_dict(s) for s in d.get("slides", [])],
            style=style,
            voice=voice,
            presenter=presenter,
            thumb=thumb,
            narrator=narrator,
            intro=intro,
            outro=outro,
        )
        p.sync_takes()
        return p


MIC_TRACK = "mic"


def take_track(take: dict) -> str:
    """Which voice a take was read in: the engine for a synthetic read, the
    microphone otherwise."""
    if take.get("synthetic"):
        return str(take.get("engine") or "kokoro")
    return MIC_TRACK


def chapter_title(project: Project, slide: Slide) -> str:
    """What the card announcing `slide`'s section says, or "" for no card.

    A paragraph opens a chapter when it has been marked as one — `slide.chapter`
    carries the words. The essay cut keeps its old behaviour as a fallback:
    with nothing marked anywhere in the video, a paragraph's own title
    announces the section, which is how every essay video rendered before
    chapters could be marked by hand. Marking even one turns that off, so the
    two rules are never both running and the marks alone decide.

    Lives here rather than in the renderer because the narration timing asks
    the same question — the card needs a hole in the voice to be read in (see
    `audio.paragraph_gaps`) — and the two must not be able to disagree about
    where a chapter starts.
    """
    if not getattr(project.style, "chapter_cards", True):
        return ""
    marked = (slide.chapter or "").strip()
    if marked:
        return marked
    if (project.style.format == "essay" and slide.title
            and not any((s.chapter or "").strip() for s in project.slides)):
        return slide.title
    return ""


def new_project(idea: str, target_minutes: int = 12, tone: str = "warm documentary",
                channel: Channel | None = None) -> Project:
    """A new video. Inside a channel it inherits that channel's look and voice."""
    p = Project(id=_uid("p"), idea=idea.strip(), target_minutes=target_minutes, tone=tone)
    if channel:
        p.channel_id = channel.id
        p.tone = channel.tone or tone
        p.style = Style(**channel.style.to_dict())
        p.voice = Voice(**channel.voice.to_dict())
        p.narrator = Narrator(**channel.narrator.to_dict())
        p.music = channel.music
        p.thumb.template = channel.thumb_template or "banner"
    return p
