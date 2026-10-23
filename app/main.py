"""FastAPI app: the local web UI's backend."""
from __future__ import annotations

import hashlib
import hmac
import io
import json
import mimetypes
import os
import re
import shutil
import tempfile
import time
from pathlib import Path

from fastapi import Body, FastAPI, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image

from . import audio as audio_mod
from . import reactions
from . import llm as llm_mod
from . import settings as settings_mod
from . import cast as cast_mod
from . import channels, ffutil, jobs, library, media, models3d, render, script_gen, store, thumbs
from . import tts as tts_mod
from . import voice_cloud
from . import intro as intro_mod
from . import outro as outro_mod
from . import playback as playback_mod
from . import themes as themes_mod
from . import maps as maps_mod
from . import board as board_mod
from . import cuts as cuts_mod
from . import custom_slide as custom_mod
from . import diagram as diagram_mod
from . import slide_styles
from . import youtube as youtube_mod
from . import transfer
from .config import CACHE_DIR, DATA, MUSIC_DIR, STATIC_DIR, ensure_dirs
from .schema import MIC_TRACK, VOICE_PRESETS, Presenter, Slide, Voice, new_channel, new_project
from .store import project_dir

# The data folders, before anything can want one. `app/__main__.py` does this
# too; it is here as well so that importing this module directly — which is
# what `run.sh` and any uvicorn invocation do — is enough on its own.
ensure_dirs()

app = FastAPI(title="Youslop")

# Set by run.sh whenever the server is bound past loopback. Everything here can
# read, edit and delete projects, so a second machine has to bring the token;
# requests from this machine are never challenged, so local use is unchanged.
ACCESS_TOKEN = (os.environ.get("VB_TOKEN") or "").strip()
if ACCESS_TOKEN.lower() in ("off", "none", "no"):
    ACCESS_TOKEN = ""
LOOPBACK = {"127.0.0.1", "::1", "localhost"}


@app.middleware("http")
async def _require_token(request: Request, call_next):
    if not ACCESS_TOKEN:
        return await call_next(request)
    if (request.client.host if request.client else "") in LOOPBACK:
        return await call_next(request)
    # Any one of these may carry it. Check them all rather than taking the
    # first that is set: "t" doubles as a cache-buster on media URLs, so a
    # first-wins read would reject an otherwise cookie-authorised request.
    supplied = [request.query_params.get("t") or "",
                request.cookies.get("vb_token") or "",
                request.headers.get("x-vb-token") or ""]
    if not any(hmac.compare_digest(v, ACCESS_TOKEN) for v in supplied):
        return Response(
            "Not authorised. Open the address run.sh printed, including its "
            "?t=… token.", status_code=401, media_type="text/plain")
    response = await call_next(request)
    if hmac.compare_digest(request.query_params.get("t") or "", ACCESS_TOKEN):
        # Carry it on a cookie so every later request — images, takes, the API —
        # works without the token being pinned to the address bar.
        response.set_cookie("vb_token", ACCESS_TOKEN, max_age=30 * 24 * 3600,
                            samesite="lax", httponly=True)
    return response


# --------------------------------------------------------------------- helpers
def _load(pid: str):
    try:
        return store.load(pid)
    except FileNotFoundError:
        raise HTTPException(404, f"No project {pid}")


def _slide(project, sid: str) -> Slide:
    s = project.slide(sid)
    if not s:
        raise HTTPException(404, f"No slide {sid}")
    return s


def _focal(value) -> list[float]:
    """Normalise a focal point to [x, y] in 0..1. Anything else clears it."""
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return []
    try:
        return [min(1.0, max(0.0, float(value[0]))), min(1.0, max(0.0, float(value[1])))]
    except (TypeError, ValueError):
        return []


def _apply_voice(voice: Voice, payload: dict) -> Voice:
    """Update a Voice from a patch, resolving presets as it goes.

    Naming a preset loads the whole set. Touching a knob afterwards moves the
    preset to "custom", because a row of numbers that no longer matches the
    name above it is how a panel starts lying about what it is doing.
    """
    payload = dict(payload or {})
    preset = str(payload.pop("preset", "") or "")
    if preset in VOICE_PRESETS:
        voice.preset = preset
        for key, value in VOICE_PRESETS[preset].items():
            setattr(voice, key, float(value))
    elif preset:
        voice.preset = "custom"
    tuned = False
    for key, value in payload.items():
        if not hasattr(voice, key) or key == "preset":
            continue
        current = getattr(voice, key)
        setattr(voice, key,
                bool(value) if isinstance(current, bool) else type(current)(value))
        # The input device and whether the browser pre-cleans are about this
        # machine, not about the sound of the chain: neither breaks a preset.
        tuned = tuned or key != "browser_cleanup"
    if tuned and not preset:
        voice.preset = "custom"
    return voice.clamp()


def _safe_join(root: Path, rel: str) -> Path:
    p = (root / rel).resolve()
    if not str(p).startswith(str(root.resolve())):
        raise HTTPException(400, "Path escapes the project directory")
    if not p.exists():
        raise HTTPException(404, f"No such file: {rel}")
    return p


def _ranged(path: Path, request: Request) -> Response:
    """Serve a file with Range support so <video> and <audio> can seek."""
    size = path.stat().st_size
    ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    rng = request.headers.get("range")
    if not rng:
        return FileResponse(path, media_type=ctype,
                            headers={"Accept-Ranges": "bytes"})
    m = re.match(r"bytes=(\d*)-(\d*)", rng)
    if not m:
        raise HTTPException(416, "Bad range")
    start = int(m.group(1) or 0)
    end = int(m.group(2)) if m.group(2) else size - 1
    end = min(end, size - 1)
    if start > end:
        raise HTTPException(416, "Bad range")
    with open(path, "rb") as fh:
        fh.seek(start)
        data = fh.read(end - start + 1)
    return Response(
        data, status_code=206, media_type=ctype,
        headers={
            "Content-Range": f"bytes {start}-{end}/{size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(len(data)),
        },
    )


# ---------------------------------------------------------------------- pages
@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    """The shell page, with its own assets stamped by their mtime.

    Without the stamp a browser that already has `app.js` in memory will keep
    serving it after an update — which in a desktop app means a new version
    running last version's front end, with no reload button to rescue it.
    """
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    for asset in ("app.js", "styles.css"):
        path = STATIC_DIR / asset
        if path.exists():
            html = html.replace(f"/static/{asset}",
                                f"/static/{asset}?v={int(path.stat().st_mtime)}")
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


# ------------------------------------------------------------------- channels
def _channel(cid: str):
    ch = channels.load_or_none(cid)
    if ch is None:
        raise HTTPException(404, f"No channel {cid}")
    _backfill_sting_duration(ch)
    return ch


def _backfill_sting_duration(ch) -> None:
    """A sting uploaded before the window existed has no recorded length, and
    without one the UI cannot offer a start offset. Probe it once."""
    if not ch.intro.music or ch.intro.music_duration > 0:
        return
    path = channels.channel_dir(ch.id) / ch.intro.music
    if not path.exists():
        return
    try:
        ch.intro.music_duration = round(ffutil.duration(path), 2)
    except Exception:
        return
    with channels.lock_for(ch.id):
        fresh = channels.load_or_none(ch.id)
        if fresh and fresh.intro.music == ch.intro.music:
            fresh.intro.music_duration = ch.intro.music_duration
            channels.save(fresh)


@app.get("/api/channels")
def list_channels() -> list[dict]:
    return channels.list_channels()


@app.post("/api/channels")
def create_channel(payload: dict = Body(...)) -> dict:
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "A channel needs a name.")
    ch = new_channel(name, payload.get("concept") or "")
    ch.tagline = (payload.get("tagline") or "").strip()
    channels.save(ch)
    return ch.to_dict()


def _mtime(path: Path) -> int:
    """A file's modification time, or 0 if it is not there yet."""
    try:
        return int(path.stat().st_mtime)
    except OSError:
        return 0


@app.get("/api/channels/{cid}")
def get_channel(cid: str) -> dict:
    ch = _channel(cid)
    d = ch.to_dict()
    d["videos"] = [p for p in store.list_projects() if p.get("channel_id") == cid]
    d["jobs"] = [{"id": j["id"], "kind": j["kind"]} for j in jobs.active_for(cid)]
    # The previews are cache-busted on their own mtime rather than on the
    # channel's updated_at: rendering one does not touch the channel record, so
    # a second preview would otherwise come back out of the browser cache
    # looking identical to the first.
    d["preview_at"] = _mtime(intro_mod.preview_path(ch))
    d["outro_preview_at"] = _mtime(outro_mod.preview_path(ch))
    d["has_preview"] = d["preview_at"] > 0
    d["has_outro_preview"] = d["outro_preview_at"] > 0
    d["youtube"] = youtube_mod.status(cid)
    d["youtube_available"] = youtube_mod.available()
    return d


@app.patch("/api/channels/{cid}")
def patch_channel(cid: str, payload: dict = Body(...)) -> dict:
    with channels.lock_for(cid):
        ch = _channel(cid)
        for key in ("name", "tagline", "concept", "tone", "music"):
            if key in payload:
                setattr(ch, key, str(payload[key]))
        if "default_minutes" in payload:
            ch.default_minutes = max(5, min(30, int(payload["default_minutes"])))
        # `outro` used to be a bare flag; a client still sending one turns the
        # end screen on or off and leaves its template alone.
        if isinstance(payload.get("outro"), bool):
            ch.outro.enabled = bool(payload["outro"])
        for key, value in (payload.get("style") or {}).items():
            if key == "theme":
                if value not in themes_mod.THEME_KEYS:
                    raise HTTPException(400, f"No such theme: {value}")
                ch.style.theme = str(value)
            elif hasattr(ch.style, key):
                current = getattr(ch.style, key)
                setattr(ch.style, key,
                        bool(value) if isinstance(current, bool) else type(current)(value))
        if "thumb_template" in payload:
            if payload["thumb_template"] not in thumbs.TEMPLATE_KEYS:
                raise HTTPException(400, "No such thumbnail style.")
            ch.thumb_template = str(payload["thumb_template"])
        if "voice" in payload:
            _apply_voice(ch.voice, payload["voice"])
        _apply_narrator(ch.narrator, payload.get("narrator"))
        if "lexicon" in payload:
            ch.lexicon = _clean_lexicon(payload["lexicon"])
        outro_patch = payload.get("outro")
        for key, value in (outro_patch if isinstance(outro_patch, dict) else {}).items():
            if not hasattr(ch.outro, key):
                continue
            current = getattr(ch.outro, key)
            if key == "template":
                if value not in outro_mod.TEMPLATE_KEYS:
                    raise HTTPException(400, f"No such end screen: {value}")
                ch.outro.template = str(value)
            elif key == "slots":
                ch.outro.slots = max(0, min(outro_mod.max_slots(ch.outro.template),
                                            int(value)))
            elif key == "duration":
                ch.outro.duration = max(5.0, min(20.0, float(value)))
            elif key == "backdrop":
                ch.outro.backdrop = max(0.0, min(1.0, float(value)))
            elif key == "music_fade":
                ch.outro.music_fade = max(0.0, min(18.0, float(value)))
            elif isinstance(current, bool):
                setattr(ch.outro, key, bool(value))
            else:
                setattr(ch.outro, key, type(current)(value))
        # Fewer plates than the new template allows is fine; more is not.
        ch.outro.slots = min(ch.outro.slots, outro_mod.max_slots(ch.outro.template))
        for key, value in (payload.get("avatar") or {}).items():
            if key in ("path", "filename") or not hasattr(ch.avatar, key):
                continue        # those two are set by the upload, not the form
            if key == "position":
                if value not in ("bottom_right", "bottom_left"):
                    raise HTTPException(400, "An avatar sits bottom left or right.")
                ch.avatar.position = str(value)
            elif key == "scale":
                ch.avatar.scale = max(0.1, min(0.4, float(value)))
            elif key == "enabled":
                ch.avatar.enabled = bool(value)
        for key, value in (payload.get("intro") or {}).items():
            if not hasattr(ch.intro, key) or key in ("images", "credits"):
                continue
            current = getattr(ch.intro, key)
            if key == "template":
                if value not in intro_mod.TEMPLATE_KEYS:
                    raise HTTPException(400, f"No such slate template: {value}")
                ch.intro.template = str(value)
            elif key == "subjects":
                setattr(ch.intro, key,
                        [str(s).strip() for s in value if str(s).strip()][:8])
            elif key == "focals":
                ch.intro.focals = [_focal(f) for f in (value or [])][:8]
            elif key == "music_start":
                # The window has to leave the slate something to play: the last
                # second of the file is never a legal place to start.
                ch.intro.music_start = max(
                    0.0, min(max(0.0, ch.intro.music_duration - 1.0), float(value)))
            elif key == "music_fade":
                ch.intro.music_fade = max(0.0, min(8.0, float(value)))
            elif key == "music_duration":
                continue        # the file's own length; not the creator's to set
            elif isinstance(current, bool):
                setattr(ch.intro, key, bool(value))
            else:
                setattr(ch.intro, key, type(current)(value))
        channels.save(ch)
    return ch.to_dict()


@app.delete("/api/channels/{cid}")
def delete_channel(cid: str) -> dict:
    """Delete the channel. Its videos survive, unlinked."""
    freed = 0
    for row in store.list_projects():
        if row.get("channel_id") != cid:
            continue
        with store.lock_for(row["id"]):
            p = store.load(row["id"])
            p.channel_id = ""
            store.save(p)
            freed += 1
    channels.delete(cid)
    return {"deleted": cid, "videos_unlinked": freed}


@app.get("/api/intro/templates")
def intro_templates() -> list[dict]:
    """The slates a channel can open on, with the knobs each one answers to."""
    return intro_mod.TEMPLATES


@app.get("/api/themes")
def list_themes() -> list[dict]:
    """The themes a channel can be cast in, with their palettes and picks."""
    return themes_mod.THEMES


@app.post("/api/channels/{cid}/theme")
def apply_theme(cid: str, payload: dict = Body(...)) -> dict:
    """Cast a channel in a theme: its two colours, its grade, and its templates.

    The templates are a suggestion the caller can decline, because a channel
    that has settled on a slate should be able to take a theme's colours
    without losing it.
    """
    key = str(payload.get("key") or "")
    if key not in themes_mod.THEME_KEYS:
        raise HTTPException(400, f"No such theme: {key}")
    take = payload.get("templates", True)
    with channels.lock_for(cid):
        ch = _channel(cid)
        picks = themes_mod.apply_to_style(ch.style, key, bool(take))
        if picks:
            ch.intro.template = picks["intro"]
            ch.thumb_template = picks["thumb"]
            ch.outro.template = picks["outro"]
            ch.outro.slots = min(ch.outro.slots, outro_mod.max_slots(ch.outro.template))
        channels.save(ch)
    return ch.to_dict()


@app.get("/api/outro/templates")
def outro_templates() -> list[dict]:
    """The end screens a channel can close on, and how many plates each holds."""
    return outro_mod.TEMPLATES


@app.post("/api/channels/{cid}/cast")
def suggest_cast(cid: str, payload: dict = Body(default={})) -> dict:
    """Have Claude propose the faces for this channel's opening slate."""
    ch = _channel(cid)
    count = max(3, min(8, int(payload.get("count") or ch.intro.columns or 5) + 1))

    def work(progress):
        progress(f"Casting {count} faces for “{ch.name}”")
        names = intro_mod.suggest_subjects(ch, count)
        with channels.lock_for(cid):
            fresh = _channel(cid)
            fresh.intro.subjects = names
            channels.save(fresh)
        progress("Cast: " + ", ".join(names))
        return {"subjects": names}

    return {"job": jobs.start("cast", cid, work)}


@app.post("/api/channels/{cid}/portraits")
def fetch_portraits(cid: str) -> dict:
    """Search and cache one portrait per cast member."""
    _channel(cid)

    def work(progress):
        with channels.lock_for(cid):
            ch = _channel(cid)
            intro_mod.resolve_images(ch, progress)
            channels.save(ch)
        return {"images": len(ch.intro.images)}

    return {"job": jobs.start("portraits", cid, work)}


@app.delete("/api/channels/{cid}/cast/{index}")
def remove_cast_member(cid: str, index: int) -> dict:
    """Drop one face from the slate: the name, the portrait, focus and credit."""
    with channels.lock_for(cid):
        ch = _channel(cid)
        try:
            gone = intro_mod.remove_cast(ch, index)
        except IndexError as exc:
            raise HTTPException(404, str(exc))
        channels.save(ch)
    return {"channel": ch.to_dict(), "removed": gone}


@app.get("/api/channels/{cid}/cast/{index}/options")
def cast_portrait_options(cid: str, index: int, q: str = "") -> dict:
    """Other portraits this cast member could be shown by."""
    ch = _channel(cid)
    intro_mod.align_cast(ch.intro)
    if not 0 <= index < len(ch.intro.subjects):
        raise HTTPException(404, "No cast member at that position.")
    subject = (q or "").strip() or ch.intro.subjects[index]
    return {"subject": subject, "results": intro_mod.portrait_options(subject)}


@app.post("/api/channels/{cid}/cast/{index}/portrait")
def choose_cast_portrait(cid: str, index: int, payload: dict = Body(...)) -> dict:
    """Put one of those portraits into the slot."""
    cand = payload.get("candidate")
    if not isinstance(cand, dict) or not cand.get("url"):
        raise HTTPException(400, "Pick a portrait to use.")
    with channels.lock_for(cid):
        ch = _channel(cid)
        try:
            intro_mod.set_portrait(ch, index, cand)
        except IndexError as exc:
            raise HTTPException(404, str(exc))
        except Exception as exc:
            raise HTTPException(400, f"Could not fetch that portrait: {exc}")
        channels.save(ch)
    return ch.to_dict()


@app.post("/api/channels/{cid}/cast/{index}/upload")
async def upload_cast_portrait(cid: str, index: int, file: UploadFile) -> dict:
    """Use your own image for one cast member."""
    suffix = Path(file.filename or "portrait.jpg").suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff"}:
        raise HTTPException(400, "That is not an image I can read.")
    data = await file.read()
    with channels.lock_for(cid):
        ch = _channel(cid)
        try:
            intro_mod.adopt_portrait(ch, index, data, suffix, file.filename or "")
        except IndexError as exc:
            raise HTTPException(404, str(exc))
        channels.save(ch)
    return ch.to_dict()


@app.post("/api/channels/{cid}/preview")
def preview_intro(cid: str, payload: dict = Body(default={})) -> dict:
    """Render the slate on its own, with a sample video title."""
    _channel(cid)
    sample = (payload.get("title") or "").strip() or "Your video title here"

    def work(progress):
        ch = _channel(cid)
        out = intro_mod.preview_path(ch)
        length = intro_mod.render_intro(ch, sample, out, progress)
        # The preview plays with the slate's own sting, so the level, the window
        # and the fade can be heard rather than guessed at.
        intro_mod.mux_sting(ch, out, length, progress)
        return {"path": "cache/intro_preview.webm"}

    return {"job": jobs.start("intro preview", cid, work)}


@app.post("/api/channels/{cid}/outro-preview")
def preview_outro(cid: str, payload: dict = Body(default={})) -> dict:
    """Render the end screen on its own, with a sample video title."""
    _channel(cid)
    sample = (payload.get("title") or "").strip() or "Your video title here"

    def work(progress):
        ch = _channel(cid)
        out = outro_mod.preview_path(ch)
        # Templates that hold the last picture of a video have no video here, so
        # the preview falls back to whatever the channel was cast with.
        backdrop = None
        for rel in ch.intro.images:
            candidate = channels.channel_dir(cid) / rel
            if candidate.exists():
                backdrop = candidate
        outro_mod.render_outro(ch, sample, out, backdrop, progress)
        return {"path": "cache/outro_preview.webm"}

    return {"job": jobs.start("end screen preview", cid, work)}


@app.post("/api/channels/{cid}/music")
async def upload_intro_music(cid: str, file: UploadFile) -> dict:
    """A sting for this channel's slate, separate from the main music bed."""
    with channels.lock_for(cid):
        ch = _channel(cid)
        suffix = Path(file.filename or "sting.mp3").suffix.lower()
        if suffix not in {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}:
            raise HTTPException(400, "That is not an audio file I can read.")
        d = channels.channel_dir(cid) / "music"
        d.mkdir(exist_ok=True)
        for old in d.glob("sting.*"):
            old.unlink()
        dest = d / f"sting{suffix}"
        dest.write_bytes(await file.read())
        try:
            length = ffutil.duration(dest)
        except Exception as exc:
            dest.unlink()
            raise HTTPException(400, f"Could not read that audio: {exc}")
        if length < 0.5:
            dest.unlink()
            raise HTTPException(400, "That sting is too short.")
        ch.intro.music = f"music/{dest.name}"
        ch.intro.music_filename = file.filename or dest.name
        ch.intro.music_duration = round(length, 2)
        # A new file means the old window points into nothing.
        ch.intro.music_start = 0.0
        channels.save(ch)
    return {"intro": ch.intro.to_dict(), "duration": round(length, 2)}


@app.delete("/api/channels/{cid}/music")
def delete_intro_music(cid: str) -> dict:
    with channels.lock_for(cid):
        ch = _channel(cid)
        for old in (channels.channel_dir(cid) / "music").glob("sting.*"):
            old.unlink()
        ch.intro.music = ""
        ch.intro.music_filename = ""
        ch.intro.music_duration = 0.0
        ch.intro.music_start = 0.0
        channels.save(ch)
    return {"intro": ch.intro.to_dict()}


@app.post("/api/channels/{cid}/avatar")
async def upload_avatar(cid: str, file: UploadFile) -> dict:
    """The host image the essay format pins in a corner of every video."""
    with channels.lock_for(cid):
        ch = _channel(cid)
        suffix = Path(file.filename or "avatar.png").suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
            raise HTTPException(400, "That is not an image I can read.")
        d = channels.channel_dir(cid) / "avatar"
        d.mkdir(exist_ok=True)
        for old in d.glob("avatar.*"):
            old.unlink()
        dest = d / f"avatar{suffix}"
        dest.write_bytes(await file.read())
        try:
            w, h = ffutil.dimensions(dest)
        except Exception as exc:
            dest.unlink()
            raise HTTPException(400, f"Could not read that image: {exc}")
        ch.avatar.path = f"avatar/{dest.name}"
        ch.avatar.filename = file.filename or dest.name
        # Uploading one is the act of wanting it: nobody adds a host image and
        # then goes looking for the switch that turns it on.
        ch.avatar.enabled = True
        channels.save(ch)
    return {"avatar": ch.avatar.to_dict(), "width": w, "height": h}


@app.delete("/api/channels/{cid}/avatar")
def delete_avatar(cid: str) -> dict:
    with channels.lock_for(cid):
        ch = _channel(cid)
        for old in (channels.channel_dir(cid) / "avatar").glob("avatar.*"):
            old.unlink()
        ch.avatar.path = ""
        ch.avatar.filename = ""
        ch.avatar.enabled = False
        channels.save(ch)
    return {"avatar": ch.avatar.to_dict()}


@app.get("/api/channels/{cid}/file/{rel:path}")
def channel_file(cid: str, rel: str, request: Request) -> Response:
    return _ranged(_safe_join(channels.channel_dir(cid), rel), request)


# -------------------------------------------------------------------- youtube
@app.get("/api/youtube/status")
def youtube_configured() -> dict:
    """Whether GOOGLE_CLIENT_ID/SECRET are set at all — gates the panel
    itself, before any per-channel connection exists."""
    return {"available": youtube_mod.available(), "categories": youtube_mod.CATEGORIES}


@app.get("/api/channels/{cid}/youtube")
def youtube_channel_status(cid: str) -> dict:
    _channel(cid)
    return youtube_mod.status(cid)


@app.get("/api/youtube/oauth/start")
def youtube_oauth_start(channel_id: str, request: Request):
    """A real navigation, not a fetch — this ends on Google's own pages."""
    if not youtube_mod.available():
        raise HTTPException(400, "GOOGLE_CLIENT_ID/SECRET are not set.")
    _channel(channel_id)
    redirect_uri = str(request.base_url) + "api/youtube/oauth/callback"
    url = youtube_mod.auth_url(channel_id, redirect_uri)
    return RedirectResponse(url)


@app.get("/api/youtube/oauth/callback")
def youtube_oauth_callback(request: Request, code: str = "", state: str = "",
                           error: str = ""):
    cid = youtube_mod.resolve_state(state) if state else None
    if not cid:
        return HTMLResponse("This connection link has expired or was already used. "
                            "Go back and click “Connect YouTube” again.", status_code=400)
    if error:
        return RedirectResponse(f"/#/c/{cid}?youtube_error={error}")
    redirect_uri = str(request.base_url) + "api/youtube/oauth/callback"
    try:
        youtube_mod.complete_connection(cid, code, redirect_uri)
    except Exception as exc:
        import html
        return HTMLResponse(f"Could not complete the YouTube connection: "
                            f"{html.escape(str(exc)[:300])}", status_code=400)
    return RedirectResponse(f"/#/c/{cid}")


@app.post("/api/channels/{cid}/youtube/disconnect")
def youtube_disconnect(cid: str) -> dict:
    _channel(cid)
    youtube_mod.disconnect(cid)
    return {"connected": False}


@app.post("/api/projects/{pid}/youtube/upload")
def youtube_upload(pid: str, payload: dict = Body(default={})) -> dict:
    p = _load(pid)
    if not p.channel_id:
        raise HTTPException(400, "This video isn't on a channel — nowhere to upload it to.")
    if not youtube_mod.status(p.channel_id).get("connected"):
        raise HTTPException(400, "This channel isn't connected to YouTube yet.")
    if not (p.render or {}).get("output"):
        raise HTTPException(400, "Nothing rendered yet.")

    title = str(payload.get("title") or p.title or p.idea[:100])
    description = str(payload.get("description") or youtube_mod.default_description(p))
    tags = [str(t) for t in (payload.get("tags") or []) if str(t).strip()]
    category_id = str(payload.get("category_id") or "22")
    privacy = payload.get("privacy") or "private"   # server-side default too

    def work(progress):
        result = youtube_mod.upload_video(
            p, p.channel_id, title=title, description=description, tags=tags,
            category_id=category_id, privacy=privacy, progress=progress)
        with store.lock_for(pid):
            fresh = store.load(pid)
            fresh.render["youtube_url"] = result["url"]
            store.save(fresh)
        return result

    return {"job": jobs.start("youtube upload", pid, work)}


# ------------------------------------------------------------------- projects
@app.get("/api/projects")
def list_projects() -> list[dict]:
    return store.list_projects()


@app.post("/api/projects")
def create_project(payload: dict = Body(...)) -> dict:
    script = (payload.get("script") or "").strip()
    idea = (payload.get("idea") or "").strip()
    if not script and len(idea) < 8:
        raise HTTPException(400, "Describe the video idea, or paste a script.")
    if script and len(script.split()) < 120:
        raise HTTPException(400, "That script is too short to build a video from.")

    channel = channels.load_or_none(payload.get("channel_id") or "")
    minutes = max(5, min(30, int(payload.get("target_minutes")
                                 or (channel.default_minutes if channel else 12))))
    tone = payload.get("tone") or (channel.tone if channel else "warm documentary")
    project = new_project(idea or script[:200], minutes, tone, channel=channel)
    if script:
        project.has_source = True
        project.fidelity = "adapted" if payload.get("fidelity") == "adapted" else "faithful"
    # The two look-and-feel choices worth making before a script exists rather
    # than after: how the pictures are staged, and how often they change. Both
    # already have defaults from the channel (or Style()'s own), so this only
    # overrides them when the creator actually touched the control.
    if payload.get("format") in ("kenburns", "essay", "board", "stage", *cuts_mod.KEYS):
        project.style.format = payload["format"]
    if payload.get("picture_every"):
        project.style.picture_every = max(1, min(8, int(payload["picture_every"])))
    # Models first: models the creator picked on the form are in the cast
    # before the story is planned, and the brief is built around them.
    if project.style.format == "stage":
        for mid in (payload.get("models") or [])[:8]:
            try:
                m = models3d.get(str(mid))
            except models3d.ModelError:
                continue
            project.cast.append({"id": "s" + m["id"][1:7], "subject": cast_mod.model_name(m),
                                 "role": "hero", "why": "chosen by the creator", "chapters": [],
                                 "model": m["id"], "mode": "model"})
    store.save(project)
    if script:
        (project_dir(project.id) / "source.txt").write_text(script, encoding="utf-8")

    def work(progress):
        with store.lock_for(project.id):
            p = store.load(project.id)
            src = project_dir(p.id) / "source.txt"
            if p.style.format == "stage":
                # A 3D explainer is made story, then cast, then words: stop
                # after the brief. The script is written from the same draft
                # once the cast is gathered (docs/3d-explainer.md).
                text = src.read_text(encoding="utf-8") if p.has_source and src.exists() else ""
                if text:
                    script_gen.import_script(p, text, p.fidelity, progress)
                    store.log(p, f"Script imported: {len(p.slides)} paragraphs")
                else:
                    script_gen.brief(p, progress, lambda: store.save(p))
                    store.log(p, f"Brief written: {len((p.outline or {}).get('sections', []))} chapters")
                store.save(p)
                p.cast = cast_mod.propose(p, progress, source_text=text)
                p.status = "casting" if not text else p.status
                store.save(p)
                return {"slides": len(p.slides), "cast": len(p.cast)}
            if p.has_source and src.exists():
                script_gen.import_script(p, src.read_text(encoding="utf-8"),
                                         p.fidelity, progress)
                store.log(p, f"Script imported: {len(p.slides)} paragraphs")
            else:
                script_gen.generate(p, progress, lambda: store.save(p))
                store.log(p, f"Script generated: {len(p.slides)} paragraphs")
            store.save(p)
            media.gather(p, progress)
            store.save(p)
        return {"slides": len(p.slides)}

    jid = jobs.start("import" if script else ("brief" if project.style.format == "stage" else "script"),
                     project.id, work)
    return {"project": project.to_dict(), "job": jid}


@app.get("/api/projects/{pid}")
def get_project(pid: str) -> dict:
    p = _load(pid)
    d = p.to_dict()
    d["jobs"] = [{"id": j["id"], "kind": j["kind"]} for j in jobs.active_for(pid)]
    d["youtube"] = youtube_mod.status(p.channel_id) if p.channel_id else {"connected": False}
    if p.style.format == "stage":
        d["cast"] = cast_mod.subjects(p)
        d["cast_summary"] = cast_mod.summary(p)
    return d


def _apply_narrator(narrator, patch) -> None:
    """Validate a narrator patch. An unknown voice is a typo, not a new voice."""
    if not isinstance(patch, dict):
        return
    if "mode" in patch:
        narrator.mode = "ai" if str(patch["mode"]) == "ai" else "mic"
    if "engine" in patch:
        engine = str(patch["engine"])
        if engine not in (tts_mod.ENGINE, *voice_cloud.KEYS):
            raise HTTPException(400, f"No such voice engine: {engine}")
        if engine != getattr(narrator, "engine", tts_mod.ENGINE):
            # Voice ids mean nothing across engines: start the new one on its
            # own default rather than on a name it has never heard of.
            narrator.engine = engine
            narrator.voice = (tts_mod.DEFAULT_VOICE if engine == tts_mod.ENGINE
                              else voice_cloud.BY_KEY[engine]["default_voice"])
            narrator.model = ""
    engine = getattr(narrator, "engine", tts_mod.ENGINE)
    if "voice" in patch:
        voice = str(patch["voice"])
        ok = (voice in tts_mod.VOICE_IDS if engine == tts_mod.ENGINE
              else voice_cloud.valid_voice_id(voice))
        if not ok:
            raise HTTPException(400, f"No such voice: {voice}")
        narrator.voice = voice
    if "model" in patch:
        model = str(patch["model"] or "")
        if model and (engine == tts_mod.ENGINE or model not in
                      {m["id"] for m in voice_cloud.BY_KEY[engine]["models"]}):
            raise HTTPException(400, f"No such model: {model}")
        narrator.model = model
    if "speed" in patch:
        narrator.speed = round(max(0.5, min(1.5, float(patch["speed"]))), 2)


def _apply_solo_intro(spec, patch: dict) -> None:
    """A standalone video's own opening card.

    Only the type-led templates, and only the knobs that mean anything without
    a channel behind them: no cast, no portraits, no sting. An empty template
    is how the card is turned off.
    """
    for key, value in patch.items():
        if key == "template":
            template = str(value or "")
            if template and template not in intro_mod.SOLO_TEMPLATE_KEYS:
                raise HTTPException(400, f"No such opening card: {template}")
            spec.template = template
        elif key == "duration":
            spec.duration = max(2.0, min(12.0, float(value)))
        elif key == "hold":
            spec.hold = max(0.0, min(4.0, float(value)))
        elif key == "show_video_title":
            spec.show_video_title = bool(value)
        elif key == "music_start":
            spec.music_start = max(0.0, min(max(0.0, spec.music_duration - 1.0), float(value)))
        elif key == "music_fade":
            spec.music_fade = max(0.0, min(8.0, float(value)))
        elif key == "music_db":
            spec.music_db = max(-30.0, min(6.0, float(value)))
        elif key == "music_tail":
            spec.music_tail = max(0.0, min(4.0, float(value)))


def _apply_solo_outro(spec, patch: dict) -> None:
    """A standalone video's own end screen — the channel card, minus the channel."""
    for key, value in patch.items():
        if key == "template":
            if value not in outro_mod.TEMPLATE_KEYS:
                raise HTTPException(400, f"No such end screen: {value}")
            spec.template = str(value)
        elif key == "slots":
            spec.slots = max(0, min(outro_mod.max_slots(spec.template), int(value)))
        elif key == "duration":
            spec.duration = max(5.0, min(20.0, float(value)))
        elif key == "backdrop":
            spec.backdrop = max(0.0, min(1.0, float(value)))
        elif key == "music_fade":
            spec.music_fade = max(0.0, min(18.0, float(value)))
        elif key == "sting_start":
            spec.sting_start = max(0.0, min(max(0.0, spec.sting_duration - 1.0), float(value)))
        elif key == "sting_fade":
            spec.sting_fade = max(0.0, min(8.0, float(value)))
        elif key == "sting_db":
            spec.sting_db = max(-30.0, min(6.0, float(value)))
        elif key in ("cta", "handle"):
            setattr(spec, key, str(value).strip()[:80])
        elif key in ("enabled", "subscribe", "countdown", "show_video_title"):
            setattr(spec, key, bool(value))
    # Fewer plates than the template allows is fine; more is not.
    spec.slots = min(spec.slots, outro_mod.max_slots(spec.template))


@app.patch("/api/projects/{pid}")
def patch_project(pid: str, payload: dict = Body(...)) -> dict:
    with store.lock_for(pid):
        p = _load(pid)
        for key in ("title", "subtitle", "tone", "music", "idea", "channel_id"):
            if key in payload:
                setattr(p, key, payload[key])
        if "description" in payload:
            p.description = str(payload["description"])[:5000]
        if isinstance(payload.get("yt_tags"), list):
            p.yt_tags = [str(t).strip()[:60] for t in payload["yt_tags"] if str(t).strip()][:30]
        if "use_intro" in payload:
            p.use_intro = bool(payload["use_intro"])
        if "use_outro" in payload:
            p.use_outro = bool(payload["use_outro"])
        # A video's own opening and close, read only when it has no channel.
        if isinstance(payload.get("intro"), dict):
            _apply_solo_intro(p.intro, payload["intro"])
        if isinstance(payload.get("outro"), dict):
            _apply_solo_outro(p.outro, payload["outro"])
        _apply_narrator(p.narrator, payload.get("narrator"))
        if "lexicon" in payload:
            p.lexicon = _clean_lexicon(payload["lexicon"])
        for key, value in (payload.get("presenter") or {}).items():
            if key in ("path", "filename", "source_duration", "has_audio",
                       "width", "height", "duration"):
                continue                     # set by the upload, not the client
            if key == "focal":
                p.presenter.focal = _focal(value)
            elif key == "position":
                p.presenter.position = (str(value) if str(value) in
                                        ("start", "after_intro", "end") else "after_intro")
            elif key == "enabled":
                p.presenter.enabled = bool(value)
            elif key in ("trim_start", "trim_end"):
                limit = max(0.0, p.presenter.source_duration - 0.5)
                setattr(p.presenter, key, min(max(0.0, float(value)), limit))
        for key, value in (payload.get("thumb") or {}).items():
            if key in ("image", "credit", "rendered_at"):
                continue                     # set by picking a picture, not the client
            if key == "template":
                if value not in thumbs.TEMPLATE_KEYS:
                    raise HTTPException(400, f"No such thumbnail style: {value}")
                p.thumb.template = str(value)
            elif key == "focal":
                p.thumb.focal = _focal(value)
            elif key in ("headline", "kicker", "accent"):
                setattr(p.thumb, key, str(value)[:200])
            elif key in ("uppercase", "flip"):
                setattr(p.thumb, key, bool(value))
            elif key == "text_scale":
                p.thumb.text_scale = min(1.35, max(0.7, float(value)))
            elif key == "dim":
                p.thumb.dim = min(0.95, max(0.0, float(value)))
        if "target_minutes" in payload:
            p.target_minutes = max(5, min(30, int(payload["target_minutes"])))
        for key, value in (payload.get("style") or {}).items():
            if key == "theme":
                if value not in themes_mod.THEME_KEYS:
                    raise HTTPException(400, f"No such theme: {value}")
                p.style.theme = str(value)
            elif hasattr(p.style, key):
                current = getattr(p.style, key)
                setattr(p.style, key, type(current)(value) if not isinstance(current, bool)
                        else bool(value))
        if "voice" in payload:
            _apply_voice(p.voice, payload["voice"])
        store.save(p)
    return p.to_dict()


@app.delete("/api/projects/{pid}")
def delete_project(pid: str) -> dict:
    store.delete(pid)
    return {"deleted": pid}


# --------------------------------------------------------------------- script
@app.post("/api/projects/{pid}/script")
def regenerate_script(pid: str, payload: dict = Body(default={})) -> dict:
    _load(pid)
    fresh = bool(payload.get("fresh"))

    def work(progress):
        with store.lock_for(pid):
            p = store.load(pid)
            # A previous run that died partway is picked up rather than repeated;
            # `fresh` throws that away and writes the script from the top.
            script_gen.generate(p, progress, lambda: store.save(p), fresh=fresh)
            store.save(p)
            if p.style.format != "stage":      # a 3D explainer's pictures come from its shots
                media.gather(p, progress)
                store.save(p)
        return {"slides": len(p.slides)}

    return {"job": jobs.start("script", pid, work)}


@app.post("/api/projects/{pid}/factcheck")
def factcheck(pid: str) -> dict:
    """Re-check the paragraphs as they stand now against the research already
    gathered — for after a hand edit, without re-running research or the
    write itself."""
    p = _load(pid)
    if not p.research.get("facts"):
        raise HTTPException(400, "No research on this project to check against.")

    def work(progress):
        with store.lock_for(pid):
            fresh = store.load(pid)
            flags = script_gen.verify_script(fresh, progress)
            fresh.research["flags"] = flags
            store.save(fresh)
        return {"flags": len(flags)}

    return {"job": jobs.start("fact check", pid, work)}


@app.post("/api/projects/{pid}/reimport")
def reimport_script(pid: str, payload: dict = Body(default={})) -> dict:
    """Re-segment the pasted source, optionally switching fidelity.

    Kept separate from /script so switching between faithful and adapted does not
    mean pasting the article again.
    """
    p = _load(pid)
    src = project_dir(pid) / "source.txt"
    if not (p.has_source and src.exists()):
        raise HTTPException(400, "This video was not built from a pasted script.")
    fidelity = ("adapted" if payload.get("fidelity") == "adapted"
                else "faithful" if payload.get("fidelity") == "faithful"
                else p.fidelity)

    def work(progress):
        with store.lock_for(pid):
            proj = store.load(pid)
            proj.fidelity = fidelity
            script_gen.import_script(proj, src.read_text(encoding="utf-8"),
                                     fidelity, progress)
            store.save(proj)
            media.gather(proj, progress)
            store.save(proj)
        return {"slides": len(proj.slides), "fidelity": fidelity}

    return {"job": jobs.start("re-import", pid, work)}


@app.patch("/api/projects/{pid}/slides/{sid}")
def patch_slide(pid: str, sid: str, payload: dict = Body(...)) -> dict:
    with store.lock_for(pid):
        p = _load(pid)
        s = _slide(p, sid)
        if "narration" in payload:
            s.narration = str(payload["narration"]).strip()
        if "title" in payload:
            s.title = str(payload["title"]).strip()[:40]
        if "chapter" in payload:
            # "" clears the mark; a chapter also forces its own picture, which
            # `schema.group_slides` applies on the way back out.
            s.chapter = str(payload["chapter"]).strip()[:60]
        if "queries" in payload:
            s.queries = [q for q in payload["queries"] if str(q).strip()][:4]
        if "prefer_kind" in payload:
            kind = str(payload["prefer_kind"])
            s.prefer_kind = (kind if kind in ("video", "map", "diagram", "custom")
                             else "image")
        if "board_template" in payload:
            key = str(payload["board_template"] or "auto")
            if key != "auto" and key not in board_mod.TEMPLATE_KEYS:
                raise HTTPException(400, f"No such board template: {key}")
            s.board_template = key
        for key in ("board_lead", "board_note"):
            if key in payload:
                setattr(s, key, str(payload[key]).strip()[:160])
        if "board_points" in payload:
            raw = payload["board_points"]
            if isinstance(raw, str):
                raw = raw.split("\n")
            s.board_points = [str(p).strip()[:120] for p in raw if str(p).strip()][:6]
        if "diagram" in payload:
            spec = payload["diagram"]
            if not spec:
                s.diagram = {}
            else:
                try:
                    s.diagram = diagram_mod.normalise(spec)
                except (ValueError, TypeError, json.JSONDecodeError) as exc:
                    raise HTTPException(400, f"That diagram spec won't draw: {exc}")
        if "picture_mode" in payload:
            mode = str(payload["picture_mode"])
            if mode not in ("auto", "hold", "new"):
                raise HTTPException(400, "picture_mode is auto, hold or new")
            s.picture_mode = mode
        if isinstance(payload.get("cues"), dict):
            # {"<cut key>": [cues]} — a list replaces that cut's cues, an
            # empty one clears them back to drawing from the narration.
            cues = dict(s.cues or {})
            for key, value in payload["cues"].items():
                if key not in cuts_mod.BY_KEY:
                    raise HTTPException(400, f"No such cut: {key}")
                if value and not isinstance(value, list):
                    raise HTTPException(400, "Cues are a list of objects.")
                clean = cuts_mod.normalise(cuts_mod.BY_KEY[key], value or [])
                if value and not clean:
                    raise HTTPException(400, "None of those cues are a kind this cut draws.")
                if clean:
                    cues[key] = clean
                else:
                    cues.pop(key, None)
            s.cues = cues
        if "chosen_id" in payload:
            s.chosen_id = str(payload["chosen_id"])
            s.locked_media = True
        if "focal" in payload:
            # Lives on the candidate, not the slide, so each image keeps its own
            # point even after you switch pictures and switch back.
            cid = str(payload.get("focal_id") or s.chosen_id)
            cand = next((c for c in s.candidates if c["id"] == cid), None)
            if cand is None:
                raise HTTPException(404, "No such image on this slide")
            cand["focal"] = _focal(payload["focal"])
        store.save(p)
    return s.to_dict()


@app.delete("/api/projects/{pid}/slides/{sid}")
def delete_slide(pid: str, sid: str) -> dict:
    with store.lock_for(pid):
        p = _load(pid)
        _slide(p, sid)
        p.slides = [s for s in p.slides if s.id != sid]
        store.save(p)
    return {"deleted": sid, "slides": len(p.slides)}


@app.post("/api/projects/{pid}/slides/{sid}/split")
def split_slide(pid: str, sid: str) -> dict:
    """Split one paragraph in half, so a long take becomes two shorter ones."""
    with store.lock_for(pid):
        p = _load(pid)
        s = _slide(p, sid)
        sentences = re.split(r"(?<=[.!?])\s+", s.narration)
        if len(sentences) < 2:
            raise HTTPException(400, "Not enough sentences to split.")
        half = len(sentences) // 2
        tail = Slide(section=s.section, beat=s.beat,
                     narration=" ".join(sentences[half:]),
                     visual_note=s.visual_note, queries=list(s.queries),
                     prefer_kind=s.prefer_kind, candidates=list(s.candidates))
        s.narration = " ".join(sentences[:half])
        s.take = None
        s.takes = {}
        p.slides.insert(p.slides.index(s) + 1, tail)
        store.save(p)
    return p.to_dict()


@app.post("/api/projects/{pid}/slides/{sid}/rewrite")
def rewrite(pid: str, sid: str, payload: dict = Body(...)) -> dict:
    p = _load(pid)
    _slide(p, sid)

    def work(progress):
        with store.lock_for(pid):
            proj = store.load(pid)
            slide = proj.slide(sid)
            progress("Rewriting paragraph")
            text = script_gen.rewrite_slide(proj, slide, payload.get("instruction", ""))
            if text:
                slide.narration = text
                slide.take = None      # the old take no longer matches the words
                slide.takes = {}       # ...in any voice
                store.save(proj)
            progress("Rewritten")
            return {"narration": text}

    return {"job": jobs.start("rewrite", pid, work)}


@app.post("/api/projects/{pid}/slides/{sid}/diagram/generate")
def generate_slide_diagram(pid: str, sid: str, payload: dict = Body(default={})) -> dict:
    """Ask Claude to draw a diagram for this slide — the editor's "ask Claude"
    button. Returns the spec for the editor to preview; it is not written to
    the slide until the creator actually picks "use it" there, same as a
    hand-written spec gets the same review before it commits to anything.
    """
    p = _load(pid)
    s = _slide(p, sid)

    def work(progress):
        progress("Asking Claude to draw this")
        spec = script_gen.generate_diagram(p, s, payload.get("instruction", ""))
        progress("Drawn")
        return {"spec": spec}

    return {"job": jobs.start("diagram", pid, work)}


# ------------------------------------------------------------------- settings
@app.get("/api/settings")
def get_settings() -> dict:
    """Everything the Settings page needs: every field, its current value
    (redacted if secret), and whether a real environment variable has already
    locked it — see app/settings.py:status()."""
    return {"fields": settings_mod.status(), "data_dir": str(DATA)}


@app.post("/api/settings")
def save_settings(payload: dict = Body(...)) -> dict:
    """Write a batch of settings. Takes effect on next launch — everything in
    `config.py` is read once at import, same as `.env` always was."""
    try:
        settings_mod.save_file(payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"fields": settings_mod.status(), "restart_required": True}


# ------------------------------------------------------------------------ llm
@app.get("/api/llm/status")
def llm_status() -> dict:
    """Which backend script-writing will use, and why.

    Read by the first-run flow and Settings — "what would run" rather than
    "does it work", so it needs no network call or subprocess to answer.
    """
    return llm_mod.backend_status()


# ---------------------------------------------------------------------- media
@app.get("/api/providers")
def providers() -> list[dict]:
    return media.provider_status()


@app.post("/api/projects/{pid}/media")
def gather_media(pid: str, payload: dict = Body(default={})) -> dict:
    _load(pid)
    only = payload.get("slide_ids")

    def work(progress):
        with store.lock_for(pid):
            p = store.load(pid)
            media.gather(p, progress, only=only)
            store.save(p)
        return {"ok": True}

    return {"job": jobs.start("media", pid, work)}


@app.post("/api/projects/{pid}/slides/{sid}/search")
def slide_search(pid: str, sid: str, payload: dict = Body(...)) -> dict:
    """Run one ad-hoc query and merge the hits into this slide's options."""
    query = (payload.get("query") or "").strip()
    if not query:
        raise HTTPException(400, "Give me something to search for.")
    kind = payload.get("kind") if payload.get("kind") in ("video", "reaction") else "image"
    if kind == "reaction" and not reactions.available():
        raise HTTPException(400, "No Giphy key configured — add one in Settings "
                            "to search reaction GIFs.")
    found = reactions.search(query) if kind == "reaction" else media.search([query], kind)
    with store.lock_for(pid):
        p = _load(pid)
        s = _slide(p, sid)
        have = {c["id"] for c in s.candidates}
        fresh = [c.to_dict() for c in found if c.id not in have]
        s.candidates = fresh + s.candidates
        s.candidates = s.candidates[:60]
        store.save(p)
    # "results" is this query's hits in rank order, so a picker can show the
    # search on its own instead of hunting for it inside the merged strip.
    by_id = {c["id"]: c for c in s.candidates}
    results = [by_id[c.id] for c in found if c.id in by_id]
    return {"added": len(fresh), "results": results, "slide": s.to_dict()}


@app.post("/api/projects/{pid}/slides/{sid}/upload")
async def upload_media(pid: str, sid: str, file: UploadFile) -> dict:
    """Drop in your own image or clip for a slide."""
    with store.lock_for(pid):
        p = _load(pid)
        s = _slide(p, sid)
        suffix = Path(file.filename or "upload.jpg").suffix.lower() or ".jpg"
        kind = "video" if suffix in {".mp4", ".mov", ".webm", ".m4v"} else "image"
        name = f"local_{sid}_{int(time.time())}{suffix}"
        dest = project_dir(pid) / "media" / name
        dest.write_bytes(await file.read())
        try:
            w, h = ffutil.dimensions(dest)
        except Exception:
            w = h = 0
        cand = {
            "id": f"local{int(time.time() * 1000) % 10**10}", "provider": "local",
            "kind": kind, "title": file.filename or name, "url": "", "thumb": "",
            "source_page": "", "author": "you", "license": "your own file",
            "width": w, "height": h, "duration": 0.0, "score": 3.0, "query": "",
            "local_path": f"media/{name}",
        }
        s.candidates.insert(0, cand)
        s.chosen_id = cand["id"]
        s.locked_media = True
        store.save(p)
    return {"slide": s.to_dict()}


MAP_SHOTS = {
    "still": maps_mod.still,
    "establishing": maps_mod.establishing_shot,
    "reveal": maps_mod.reveal_shot,
    "pan": maps_mod.pan_shot,
}


@app.get("/api/maps/geocode")
def maps_geocode(q: str) -> dict:
    """A place name resolved to coordinates — the map widget's "jump to a
    place" box, not something the generators call themselves anymore."""
    coords = maps_mod.geocode(q)
    if not coords:
        raise HTTPException(404, f"Couldn't find “{q}”.")
    return {"lat": coords[0], "lon": coords[1]}


@app.post("/api/projects/{pid}/slides/{sid}/map")
def slide_map(pid: str, sid: str, payload: dict = Body(...)) -> dict:
    """A map, satellite still, or establishing-shot zoom for a point on the
    picker's map widget — the manual half of the map feature: works
    regardless of what the writer decided this slide's kind should be, any
    time a location tells the story better than a photo would. The zoom the
    widget was sitting at when the point was picked is the zoom rendered at.
    See app/maps.py."""
    try:
        lat = float(payload.get("lat"))
        lon = float(payload.get("lon"))
        zoom = int(payload.get("zoom"))
    except (TypeError, ValueError):
        raise HTTPException(400, "Click a point on the map first.")
    label = str(payload.get("label") or "").strip()[:80]
    kind = payload.get("kind") if payload.get("kind") in ("satellite", "street", "hybrid", "terrain") else "satellite"
    style = payload.get("style") if payload.get("style") in MAP_SHOTS else "still"

    with store.lock_for(pid):
        p = _load(pid)
        s = _slide(p, sid)
        dest = project_dir(pid) / "media"
        cand = MAP_SHOTS[style](lat, lon, zoom, kind, p.style.accent, dest, label=label)
        if not cand:
            raise HTTPException(400, "Couldn't reach the map servers.")
        s.candidates.insert(0, cand)
        s.chosen_id = cand["id"]
        s.map_place = label or cand.get("title", "")
        s.map_lat, s.map_lon, s.map_zoom = lat, lon, zoom
        s.map_kind, s.map_style = kind, style
        s.locked_media = True
        store.save(p)
    return {"slide": s.to_dict()}


# -------------------------------------------------------------------- board
@app.get("/api/board/templates")
def board_templates() -> dict:
    """The handwritten format's ten slide templates, and the hands it writes in."""
    return {"templates": board_mod.TEMPLATES, "hands": diagram_mod.HANDS}


@app.post("/api/projects/{pid}/board/plan")
def plan_boards(pid: str, payload: dict = Body(default={})) -> dict:
    """Write the on-screen content for every slide that has none.

    Additive: a board you wrote by hand is never overwritten. Pass
    {"redo": true} to clear what is there first and have the lot rewritten.
    """
    _load(pid)
    redo = bool(payload.get("redo"))
    only = payload.get("slide_ids")

    def work(progress):
        with store.lock_for(pid):
            p = store.load(pid)
            slides = [s for s in p.slides if only is None or s.id in only]
            if redo:
                for s in slides:
                    s.board_lead, s.board_note = "", ""
                    s.board_points, s.diagram = [], {}
                    s.board_template = "auto"
            script_gen.plan_boards(p, slides, progress)
            store.save(p)
            return {"slides": len(slides)}

    return {"job": jobs.start("boards", pid, work)}


# --------------------------------------------------------------------- cuts
@app.get("/api/cuts")
def list_cuts() -> list[dict]:
    """The drawn cuts: what each is for, its looks and its cue kinds."""
    return cuts_mod.info()


@app.post("/api/projects/{pid}/cues/plan")
def plan_cues(pid: str, payload: dict = Body(default={})) -> dict:
    """Write the current cut's cues for every slide that has none.

    Additive, like the boards. {"redo": true} clears this cut's cues first,
    including any edited by hand; other cuts' cues are never touched.
    """
    p = _load(pid)
    if not cuts_mod.is_cut(p.style.format):
        raise HTTPException(400, "This video isn't in one of the drawn cuts.")
    redo = bool(payload.get("redo"))
    only = payload.get("slide_ids")

    def work(progress):
        with store.lock_for(pid):
            p = store.load(pid)
            slides = [s for s in p.slides if only is None or s.id in only]
            if redo:
                for s in slides:
                    s.cues = {k: v for k, v in (s.cues or {}).items()
                              if k != p.style.format}
            script_gen.plan_cues(p, slides, progress)
            store.save(p)
            return {"slides": len(slides)}

    return {"job": jobs.start("cues", pid, work)}


@app.get("/api/projects/{pid}/slides/{sid}/cut.png")
def cut_preview(pid: str, sid: str, t: float = 0.5) -> Response:
    """One frame of this paragraph in the video's cut, `t` of the way in."""
    p = _load(pid)
    s = _slide(p, sid)
    if not cuts_mod.is_cut(p.style.format):
        raise HTTPException(400, "This video isn't in one of the drawn cuts.")
    out = project_dir(pid) / "cuts" / f"{sid}.png"
    try:
        cuts_mod.still(p, s, out, channel=channels.load_or_none(p.channel_id),
                       image_for=lambda sl: render._chosen(p, sl)[0],
                       at=max(0.0, min(1.0, float(t))),
                       cache_dir=project_dir(pid) / "cuts")
    except Exception as exc:
        raise HTTPException(500, f"Could not draw that frame: {str(exc)[:160]}")
    return FileResponse(out, media_type="image/png",
                        headers={"Cache-Control": "no-store"})


@app.get("/api/projects/{pid}/slides/{sid}/board.png")
def board_preview(pid: str, sid: str, t: float = 1.0) -> Response:
    """The board this slide would draw, finished — what the editor shows.

    `t` under 1 renders it part-drawn, which is how the editor previews the
    reveal without encoding a clip for it.
    """
    p = _load(pid)
    s = _slide(p, sid)
    ch = channels.load_or_none(p.channel_id)
    src, _, _ = render._chosen(p, s)
    out = project_dir(pid) / "board" / f"{sid}.png"
    try:
        board_mod.still(p, s, out, channel=ch, image=src,
                        at=max(0.05, min(1.0, float(t))))
    except Exception as exc:
        raise HTTPException(500, f"Could not draw that board: {str(exc)[:160]}")
    return FileResponse(out, media_type="image/png",
                        headers={"Cache-Control": "no-store"})


# ------------------------------------------------------------------ diagrams
@app.get("/api/diagram/kinds")
def diagram_kinds() -> dict:
    """The diagram layouts and how to write a spec for one.

    Served rather than only documented because this is the half of the tool an
    agent drives: read this, write a spec, POST it at a slide.
    """
    return {"kinds": diagram_mod.KINDS, "hands": diagram_mod.HANDS,
            "spec": diagram_mod.SPEC_DOC, "default": diagram_mod.DEFAULT_KIND}


@app.post("/api/diagram/preview")
def diagram_preview(payload: dict = Body(...)) -> Response:
    """Draw a spec and hand back the PNG, without touching any project.

    The editor redraws on every keystroke that parses, so this writes nothing
    to disk — the image comes back in the response body.
    """
    try:
        spec = diagram_mod.normalise(payload.get("spec") or payload)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(400, f"That spec won't draw: {exc}")
    accent = str(payload.get("accent") or "#E8C36A")
    hand = str(payload.get("hand") or diagram_mod.DEFAULT_HAND)
    buf = io.BytesIO()
    diagram_mod.render_still(spec, accent, hand=hand).save(buf, "PNG")
    return Response(buf.getvalue(), media_type="image/png",
                    headers={"Cache-Control": "no-store"})


@app.post("/api/projects/{pid}/slides/{sid}/diagram")
def slide_diagram(pid: str, sid: str, payload: dict = Body(...)) -> dict:
    """Draw a diagram for one slide and put it on the front of its candidates.

    The manual — and agent-facing — half of the diagram tool, the same deal
    the map picker gets: it works whatever the writer decided this slide's
    kind should be, and the spec is kept on the slide so it can be edited
    later rather than redrawn from scratch. `motion` is "reveal" for the
    drawn-in clip (the default) or "still" for one flat frame.
    """
    try:
        spec = diagram_mod.normalise(payload.get("spec") or payload.get("diagram") or {})
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(400, f"That spec won't draw: {exc}")
    motion = "still" if payload.get("motion") == "still" else "reveal"
    seconds = float(payload.get("seconds") or diagram_mod.DEFAULT_SECONDS)

    with store.lock_for(pid):
        p = _load(pid)
        s = _slide(p, sid)
        cand = diagram_mod.candidate(
            spec, project_dir(pid) / "media", p.style.accent, motion=motion,
            seconds=seconds, hand=getattr(p.style, "board_hand", "marker"))
        if not cand:
            raise HTTPException(500, "Could not draw that diagram.")
        s.candidates.insert(0, cand)
        s.chosen_id = cand["id"]
        s.diagram = spec
        s.prefer_kind = "diagram"
        s.locked_media = True
        store.save(p)
    return {"slide": s.to_dict()}


# -------------------------------------------------------------- custom slides
@app.get("/api/custom/spec")
def custom_spec() -> dict:
    """How to write a custom slide spec, and the entrances available.

    Served for the same reason the diagram kinds are: this is the half of the
    tool an agent drives — read this, write a spec, POST it at a slide.
    """
    return {"spec": custom_mod.SPEC_DOC, "anims": custom_mod.ANIMS,
            "sizes": list(custom_mod.SIZE_PX), "fonts": sorted(custom_mod.FONT_KEYS),
            "types": sorted(custom_mod.TYPE_KEYS)}


@app.post("/api/custom/preview")
def custom_preview(payload: dict = Body(...)) -> Response:
    """Draw a spec and hand back the PNG, without touching any project.

    Image elements are only drawn if they already carry a `local_path` — a
    preview must not fire archive searches on every keystroke.
    """
    try:
        spec = custom_mod.normalise(payload.get("spec") or payload)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(400, f"That spec won't draw: {exc}")
    hand = str(payload.get("hand") or custom_mod.DEFAULT_HAND)
    root = None
    pid = str(payload.get("project_id") or "").strip()
    if pid:
        root = project_dir(pid) / "media"
    buf = io.BytesIO()
    custom_mod.render_still(spec, hand=hand, media_root=root).save(buf, "PNG")
    return Response(buf.getvalue(), media_type="image/png",
                    headers={"Cache-Control": "no-store"})


@app.post("/api/projects/{pid}/slides/{sid}/custom/generate")
def generate_slide_custom(pid: str, sid: str, payload: dict = Body(default={})) -> dict:
    """Ask Claude to design a slide for this paragraph — the editor's
    "ask Claude" button, and the open-ended sibling of the diagram one."""
    p = _load(pid)
    s = _slide(p, sid)

    def work(progress):
        progress("Asking Claude to design this slide")
        spec = script_gen.generate_custom_slide(p, s, payload.get("instruction", ""))
        progress("Designed")
        return {"spec": spec}

    return {"job": jobs.start("custom", pid, work)}


@app.post("/api/projects/{pid}/slides/{sid}/custom")
def slide_custom(pid: str, sid: str, payload: dict = Body(...)) -> dict:
    """Render a custom slide for one slide and put it in front of its
    candidates — the same deal the diagram and map pickers get.

    Any image elements are searched for and downloaded here, and the
    resolved spec is what gets saved, so editing it later never re-fetches.
    Runs as a job because those fetches hit the archives.
    """
    try:
        spec = custom_mod.normalise(payload.get("spec") or payload.get("custom") or {})
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(400, f"That spec won't draw: {exc}")
    motion = "still" if payload.get("motion") == "still" else "reveal"
    seconds = float(payload.get("seconds") or custom_mod.DEFAULT_SECONDS)

    def work(progress):
        with store.lock_for(pid):
            p = _load(pid)
            s = _slide(p, sid)
            progress("Finding any pictures this slide asked for")
            cand = custom_mod.candidate(
                spec, project_dir(pid) / "media", motion=motion, seconds=seconds,
                hand=getattr(p.style, "board_hand", "marker"))
            if not cand:
                raise RuntimeError("Could not draw that slide.")
            progress("Drawn")
            s.candidates.insert(0, cand)
            s.chosen_id = cand["id"]
            s.custom = cand["custom"]
            s.prefer_kind = "custom"
            s.locked_media = True
            store.save(p)
            return {"slide": s.to_dict()}

    return {"job": jobs.start("custom", pid, work)}


# ------------------------------------------------------------- slide styles
@app.get("/api/slide-styles")
def list_slide_styles() -> list[dict]:
    """The saved slide designs, as they appear in the Video style picker."""
    return slide_styles.list_styles()


@app.post("/api/slide-styles/design")
def design_slide_style(payload: dict = Body(default={})) -> dict:
    """Ask Claude for a slide style from a description, before any video exists.

    The home page's way in: there is no project and no paragraph here, so the
    brief is the whole input. Runs as a job because it is a model call, and
    is not tied to a project, so it is parked under the styles collection.
    """
    def work(progress):
        progress("Asking Claude to design a style")
        spec = script_gen.design_slide_style(
            str(payload.get("description") or ""),
            str(payload.get("accent") or "#E8C36A"))
        progress("Designed")
        return {"spec": spec}

    return {"job": jobs.start("style", "", work)}


@app.post("/api/slide-styles")
def create_slide_style(payload: dict = Body(...)) -> dict:
    """Keep a design from the slide editor as a reusable named style."""
    try:
        spec = custom_mod.normalise(payload.get("spec") or {})
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(400, f"That spec won't draw: {exc}")
    return slide_styles.save(payload.get("name", ""), spec,
                             hand=str(payload.get("hand") or custom_mod.DEFAULT_HAND))


@app.get("/api/slide-styles/{style_id}/export")
def export_slide_style(style_id: str) -> Response:
    """A style as one portable JSON file — name and spec, nothing local."""
    bundle = slide_styles.export_bundle(style_id)
    if not bundle:
        raise HTTPException(404, "No such style.")
    slug = re.sub(r"[^a-z0-9]+", "-", bundle["name"].lower()).strip("-") or "style"
    body = json.dumps(bundle, indent=2, ensure_ascii=False)
    return Response(body, media_type="application/json", headers={
        "Content-Disposition": f'attachment; filename="{slug}.youslop-style.json"'})


@app.post("/api/slide-styles/import")
def import_slide_style(payload: dict = Body(...)) -> dict:
    """Read a style bundle someone exported and add it to this library."""
    try:
        return slide_styles.import_bundle(payload)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(400, f"That doesn't look like a slide style: {exc}")


@app.get("/api/slide-styles/{style_id}/thumb.jpg")
def slide_style_thumb(style_id: str) -> FileResponse:
    path = slide_styles.thumb_path(style_id)
    if not path.is_file():
        raise HTTPException(404, "No thumbnail for that style.")
    return FileResponse(path, media_type="image/jpeg")


@app.patch("/api/slide-styles/{style_id}")
def rename_slide_style(style_id: str, payload: dict = Body(...)) -> dict:
    if not slide_styles.rename(style_id, payload.get("name", "")):
        raise HTTPException(404, "No such style.")
    return {"ok": True}


@app.delete("/api/slide-styles/{style_id}")
def delete_slide_style(style_id: str) -> dict:
    if not slide_styles.remove(style_id):
        raise HTTPException(404, "No such style.")
    return {"deleted": style_id}


# ------------------------------------------------------------------ thumbnail
@app.get("/api/thumbs/templates")
def thumb_templates() -> list[dict]:
    """The thumbnail styles, with which knobs each one answers to."""
    return thumbs.TEMPLATES


def _thumb_render(p) -> dict:
    """Draw the thumbnail and stamp it, so the client can bust its own cache."""
    out = thumbs.render_thumb(p, project_dir(p.id), project_dir(p.id) / "thumb" / "thumb.jpg")
    p.thumb.rendered_at = time.time()
    return {"path": "thumb/thumb.jpg", "bytes": out.stat().st_size,
            "rendered_at": p.thumb.rendered_at}


@app.post("/api/projects/{pid}/thumb/render")
def render_thumbnail(pid: str) -> dict:
    """Redraw the thumbnail. Pure Pillow, so it runs inline rather than as a job."""
    with store.lock_for(pid):
        p = _load(pid)
        result = _thumb_render(p)
        store.save(p)
    return {**result, "thumb": p.thumb.to_dict()}


@app.post("/api/projects/{pid}/thumb/pick")
def thumb_pick(pid: str, payload: dict = Body(...)) -> dict:
    """Use a picture on the thumbnail — a slide's own, or a search hit."""
    cand = dict(payload.get("candidate") or {})
    with store.lock_for(pid):
        p = _load(pid)
        if cand.get("local_path"):
            rel = cand["local_path"]          # already inside the project
            if not (project_dir(pid) / rel).exists():
                raise HTTPException(404, "That file is no longer in this project.")
        elif cand.get("url"):
            # Only the picture actually chosen earns the full-size rendition.
            try:
                name = media.download_to(media.upgrade(cand),
                                         project_dir(pid) / "thumb",
                                         f"src_{int(time.time())}")
            except Exception as exc:
                raise HTTPException(502, f"Could not fetch that picture: {str(exc)[:120]}")
            rel = f"thumb/{name}"
        else:
            raise HTTPException(400, "That option has no image to fetch.")
        p.thumb.image = rel
        p.thumb.focal = []                     # a new picture invalidates the old point
        p.thumb.credit = {k: cand.get(k, "") for k in
                          ("provider", "title", "author", "license", "source_page")}
        result = _thumb_render(p)
        store.save(p)
    return {**result, "thumb": p.thumb.to_dict()}


@app.post("/api/projects/{pid}/thumb/upload")
async def thumb_upload(pid: str, file: UploadFile) -> dict:
    """Bring your own picture for the thumbnail."""
    suffix = Path(file.filename or "upload.jpg").suffix.lower() or ".jpg"
    if suffix not in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff"}:
        raise HTTPException(400, "That is not an image I can read.")
    with store.lock_for(pid):
        p = _load(pid)
        name = f"upload_{int(time.time())}{suffix}"
        dest = project_dir(pid) / "thumb" / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(await file.read())
        try:
            Image.open(dest).verify()
        except Exception:
            dest.unlink(missing_ok=True)
            raise HTTPException(400, "That image could not be opened.")
        p.thumb.image = f"thumb/{name}"
        p.thumb.focal = []
        p.thumb.credit = {"provider": "local", "title": file.filename or name,
                          "author": "you", "license": "your own file", "source_page": ""}
        result = _thumb_render(p)
        store.save(p)
    return {**result, "thumb": p.thumb.to_dict()}


@app.post("/api/projects/{pid}/thumb/search")
def thumb_search(pid: str, payload: dict = Body(...)) -> dict:
    """Search the archives for a thumbnail picture, unattached to any slide."""
    query = (payload.get("query") or "").strip()
    if not query:
        raise HTTPException(400, "Give me something to search for.")
    p = _load(pid)
    found = media.search([query], "image", fallback=media.subject_query(p))
    return {"results": [c.to_dict() for c in found]}


@app.post("/api/projects/{pid}/thumb/headlines")
def thumb_headlines(pid: str) -> dict:
    """Have Claude propose thumbnail text for this video."""
    _load(pid)

    def work(progress):
        p = _load(pid)
        progress("Writing thumbnail text")
        picks = thumbs.suggest_headlines(p)
        for pick in picks:
            progress(f"  {pick['headline']}" + (f"  ({pick['kicker']})" if pick["kicker"] else ""))
        return {"options": picks}

    return {"job": jobs.start("headlines", pid, work)}


@app.get("/api/thumb")
def thumb(url: str = Query(...)) -> Response:
    """Proxy remote previews so the browser never hits hotlink or CORS walls."""
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "Bad url")
    cache = media.thumb_cache_path(url)
    if cache.exists() and cache.stat().st_size > 0:
        ctype = (cache.with_suffix(".type").read_text()
                 if cache.with_suffix(".type").exists() else "image/jpeg")
        return Response(cache.read_bytes(), media_type=ctype,
                        headers={"Cache-Control": "max-age=86400"})
    try:
        with media.throttle(_provider_of(url)):
            r = media.client().get(url, timeout=25.0)
        r.raise_for_status()
    except Exception as exc:
        raise HTTPException(502, f"Thumbnail fetch failed: {exc}")

    # Downscale here rather than asking the archive for a smaller rendition.
    # Wikimedia only serves widths its own API generated, and a picker grid of
    # full 1920px images would be tens of megabytes per slide.
    body, ctype = r.content, r.headers.get("content-type", "image/jpeg").split(";")[0]
    try:
        img = Image.open(io.BytesIO(body))
        if img.width > 480:
            img.thumbnail((480, 480), Image.LANCZOS)
            buf = io.BytesIO()
            img.convert("RGB").save(buf, "JPEG", quality=82)
            body, ctype = buf.getvalue(), "image/jpeg"
    except Exception:
        pass       # not a still image, or an odd format: serve it untouched

    cache.write_bytes(body)
    cache.with_suffix(".type").write_text(ctype)
    return Response(body, media_type=ctype,
                    headers={"Cache-Control": "max-age=86400"})


def _provider_of(url: str) -> str:
    host = url.split("/")[2] if "://" in url else ""
    if "wikimedia" in host or "wikipedia" in host:
        return "wikimedia"
    if "loc.gov" in host:
        return "loc"
    if "metmuseum" in host:
        return "met"
    return "thumbs"


# ------------------------------------------------------------------ recording
@app.post("/api/projects/{pid}/slides/{sid}/take")
async def upload_take(pid: str, sid: str, file: UploadFile) -> dict:
    with store.lock_for(pid):
        p = _load(pid)
        s = _slide(p, sid)
        root = project_dir(pid)
        raw = root / "raw" / f"{sid}.webm"
        raw.write_bytes(await file.read())
        if raw.stat().st_size < 1024:
            raise HTTPException(400, "That recording is empty.")
        # Each voice keeps its own folder, so recording never overwrites a
        # read in another voice.
        out = root / "takes" / MIC_TRACK / f"{sid}.wav"
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            meta = audio_mod.process_take(raw, out, p.voice)
        except Exception as exc:
            raise HTTPException(400, f"Could not process that take: {exc}")
        p.set_take(s, MIC_TRACK, {"path": f"takes/{MIC_TRACK}/{sid}.wav",
                                  "raw_path": f"raw/{raw.name}", **meta})
        if p.status in ("scripted", "media"):
            p.status = "recording"
        store.save(p)
    return {"slide": s.to_dict(), "recorded_seconds": p.recorded_seconds()}


# --------------------------------------------------------------- ai narration
@app.get("/api/tts")
def tts_status() -> dict:
    """Whether a local read is possible here, in which voices — and which
    hosted voice services are set up beside it."""
    local = tts_mod.status()
    return {**local, "engines": [
        {"key": tts_mod.ENGINE, "label": "On this computer", "ready": local["ready"],
         "metered": False, "detail": local.get("detail", ""),
         "blurb": "Kokoro, running locally. Free, private, unmetered."},
        *[voice_cloud.status(k) for k in voice_cloud.KEYS]]}


def _engine_ready(engine: str) -> None:
    """Refuse up front, with the fix, rather than failing paragraph one."""
    if engine == tts_mod.ENGINE:
        st = tts_mod.status()
    elif engine in voice_cloud.BY_KEY:
        st = voice_cloud.status(engine)
    else:
        raise HTTPException(400, f"No such voice engine: {engine}")
    if not st["ready"]:
        raise HTTPException(400, st["detail"])


@app.get("/api/tts/library")
def tts_library(q: str = "", gender: str = "", use_case: str = "", accent: str = "",
                page: int = 0) -> dict:
    """Search ElevenLabs' shared Voice Library — the voices on their website."""
    try:
        res = voice_cloud.library_search(q, gender, use_case, accent, page)
    except voice_cloud.CloudVoiceError as exc:
        raise HTTPException(400, str(exc))
    res["use_cases"] = [{"id": k, "label": v} for k, v in voice_cloud.LIBRARY_USE_CASES]
    return res


@app.post("/api/tts/library/add")
def tts_library_add(payload: dict = Body(...)) -> dict:
    """Add a library voice to the ElevenLabs account so it can read a script.
    It takes one of the account's custom-voice slots, as it does on the site."""
    try:
        vid = voice_cloud.library_add(str(payload.get("owner") or ""),
                                      str(payload.get("id") or ""),
                                      str(payload.get("name") or ""))
    except voice_cloud.CloudVoiceError as exc:
        raise HTTPException(400, str(exc))
    return {"voice_id": vid}


@app.get("/api/tts/voices/{engine}")
def tts_voices(engine: str, refresh: bool = False) -> list[dict]:
    """The voices a hosted service offers this account."""
    if engine not in voice_cloud.BY_KEY:
        raise HTTPException(404, "No such voice service.")
    try:
        return voice_cloud.voices(engine, refresh)
    except voice_cloud.CloudVoiceError as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/tts/preview/{voice}")
def tts_preview(voice: str, request: Request, engine: str = tts_mod.ENGINE,
                model: str = "") -> Response:
    """One sample line in a voice, so the picker can be listened through.

    ElevenLabs publishes a free sample of every voice, so that is used when
    there is one; otherwise a hosted voice reads the sample line once (a
    small billed request) and it is served from the cache after that.
    """
    if engine == tts_mod.ENGINE:
        if voice not in tts_mod.VOICE_IDS:
            raise HTTPException(404, "No such voice.")
    else:
        _engine_ready(engine)
        if not voice_cloud.valid_voice_id(voice):
            raise HTTPException(404, "No such voice.")
        if engine == "elevenlabs":
            try:
                known = {v["id"]: v for v in voice_cloud.voices(engine)}
            except voice_cloud.CloudVoiceError:
                known = {}
            url = (known.get(voice) or {}).get("preview_url")
            if url:
                return RedirectResponse(url)
    try:
        path = tts_mod.preview(voice, CACHE_DIR, engine=engine, model=model)
    except tts_mod.TTSError as exc:
        raise HTTPException(400, str(exc))
    return _ranged(path, request)


def _lexicon(p) -> dict:
    """The pronunciation guide for one video: the channel's, then its own.

    The channel's entries come first because the names that recur are the
    series' names; a video that disagrees about one of them wins, which is the
    only reason a per-video list exists at all.

    Phonemes for the local model; for a hosted voice, which takes words, the
    respellings as text substitutions instead.
    """
    entries = []
    channel = channels.load_or_none(p.channel_id) if p.channel_id else None
    if channel:
        entries += list(channel.lexicon or [])
    entries += list(p.lexicon or [])
    if _engine(p) != tts_mod.ENGINE:
        return voice_cloud.aliases(entries)
    lang = tts_mod._lang_for(p.narrator.voice)
    return tts_mod.build_lexicon(entries, lang)


def _engine(p) -> str:
    return getattr(p.narrator, "engine", "") or tts_mod.ENGINE


def _wanted_read(p) -> tuple:
    """What a take must have been read with to count as current."""
    engine = _engine(p)
    model = ("" if engine == tts_mod.ENGINE
             else p.narrator.model or voice_cloud.default_model(engine))
    speed = (round(float(p.narrator.speed), 2) if engine == tts_mod.ENGINE
             else voice_cloud.clamp_speed(engine, p.narrator.speed))
    return (engine, p.narrator.voice, speed, model)


def _take_read(take: dict) -> tuple:
    return (take.get("engine") or tts_mod.ENGINE, take.get("voice"),
            take.get("speed"), take.get("model") or "")


def _voice_one(p, s, root: Path, lexicon: dict | None = None) -> dict:
    """Synthesise one paragraph in the project's chosen engine, into that
    engine's own folder — never over a read in another voice."""
    engine = _engine(p)
    out = root / "takes" / engine / f"{s.id}.wav"
    out.parent.mkdir(parents=True, exist_ok=True)
    at = next((i for i, x in enumerate(p.slides) if x.id == s.id), 0)
    context = (p.slides[at - 1].narration if at > 0 else "",
               p.slides[at + 1].narration if at + 1 < len(p.slides) else "")
    meta = tts_mod.speak_to_file(s.narration, out, p.narrator.voice,
                                 p.narrator.speed, p.voice,
                                 _lexicon(p) if lexicon is None else lexicon,
                                 engine=_engine(p), model=p.narrator.model,
                                 context=context, style=p.tone or "")
    # No raw_path: there is no recording behind this one, and "reprocess every
    # take from its raw upload" must skip it rather than fail on it.
    return {"path": f"takes/{engine}/{s.id}.wav", "raw_path": "", **meta}


def _clean_lexicon(raw) -> list[dict]:
    """Normalise a pronunciation guide off the wire.

    Entries are resolved on the way in, so what is stored is what will be said:
    a respelling that produces nothing is a typo the creator should see now,
    not a name that quietly reads wrong in the finished video.
    """
    if not isinstance(raw, list):
        raise HTTPException(400, "The pronunciation guide must be a list.")
    out: list[dict] = []
    seen: set[str] = set()
    for item in raw[:400]:
        if not isinstance(item, dict):
            continue
        term = str(item.get("term") or "").strip()
        if not term or term.lower() in seen:
            continue
        entry = {"term": term,
                 "respell": str(item.get("respell") or "").strip(),
                 "ipa": "",
                 "note": str(item.get("note") or "").strip()[:200]}
        # Resolve now, so the stored entry is the one that will be spoken, and
        # anything that says nothing — "???" is a bare "?" once espeak and the
        # vocabulary filter are done with it — is caught here rather than in a
        # finished video.
        try:
            entry["ipa"] = tts_mod.phonemes_for(
                {"ipa": item.get("ipa"), "respell": entry["respell"]})
        except Exception:
            entry["ipa"] = ""
        # Without the local model there are no phonemes to check against; a
        # respelling is still exactly what a hosted voice uses (as text).
        unchecked = bool(entry["respell"]) and not tts_mod.status()["ready"]
        if not unchecked and not tts_mod.has_phones(entry["ipa"]):
            raise HTTPException(
                400, f"“{term}” has nothing to say it with. Give it a respelling "
                     "like “ELL-on” (capitals mark the stressed syllable).")
        seen.add(term.lower())
        out.append(entry)
    return out


@app.get("/api/tts/say")
def tts_say(text: str, respell: str = "", ipa: str = "",
            voice: str = tts_mod.DEFAULT_VOICE) -> dict:
    """What a term sounds like now, and what an entry would make of it.

    The whole point of the guide is the loop between the two: you cannot correct
    a pronunciation you cannot compare against the one you are getting.
    """
    if not tts_mod.status()["ready"]:
        raise HTTPException(400, tts_mod.status()["detail"])
    lang = tts_mod._lang_for(voice if voice in tts_mod.VOICE_IDS
                             else tts_mod.DEFAULT_VOICE)
    try:
        current = tts_mod.phonemise(text, lang)
        proposed = tts_mod.phonemes_for(
            {"respell": respell, "ipa": ipa}, lang) if (respell or ipa) else ""
    except Exception as exc:
        raise HTTPException(400, f"Could not read that: {exc}")
    return {"text": text, "current": current, "proposed": proposed,
            "changes": bool(proposed) and proposed != current}


@app.post("/api/tts/say-preview")
def tts_say_preview(payload: dict = Body(...)) -> Response:
    """Hear one term, either as it reads now or as an entry would have it.

    In a hosted voice this is a small billed request each time it is not
    already in the cache.
    """
    engine = str(payload.get("engine") or tts_mod.ENGINE)
    _engine_ready(engine)
    text = str(payload.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "Give me a word to say.")
    voice = str(payload.get("voice") or tts_mod.DEFAULT_VOICE)
    if engine == tts_mod.ENGINE and voice not in tts_mod.VOICE_IDS:
        voice = tts_mod.DEFAULT_VOICE
    elif engine != tts_mod.ENGINE and not voice_cloud.valid_voice_id(voice):
        voice = voice_cloud.BY_KEY[engine]["default_voice"]
    entry = {"term": text, "respell": str(payload.get("respell") or ""),
             "ipa": str(payload.get("ipa") or "")}
    if engine != tts_mod.ENGINE:
        lexicon = voice_cloud.aliases([entry])
    else:
        lexicon = tts_mod.build_lexicon([entry]) if (entry["respell"] or entry["ipa"]) else {}
    # Said inside a carrier sentence: a name on its own is read as a fragment,
    # with a falling tone that makes every pronunciation sound slightly wrong.
    sentence = str(payload.get("carrier") or "").strip() or f"This is {text}."
    # Named for what it contains: two "hear" clicks in quick succession would
    # otherwise be writing the same file while the first one is being read.
    stamp = hashlib.md5(
        f"{sentence}|{entry['respell']}|{entry['ipa']}|{voice}|{engine}".encode()
    ).hexdigest()[:12]
    out = CACHE_DIR / f"say_{stamp}.wav"
    try:
        if not (out.is_file() and out.stat().st_size > 4096):
            tts_mod.speak_to_file(sentence, out, voice,
                                  float(payload.get("speed") or 1.0), None, lexicon,
                                  engine=engine, model=str(payload.get("model") or ""))
    except tts_mod.TTSError as exc:
        raise HTTPException(400, str(exc))
    return Response(out.read_bytes(), media_type="audio/wav",
                    headers={"Cache-Control": "no-store"})


@app.post("/api/projects/{pid}/voice-over")
def voice_over(pid: str, payload: dict = Body(default={})) -> dict:
    """Read the whole script in the project's chosen voice.

    Paragraphs already voiced in the current voice are left alone unless
    `redo` is asked for, so changing one line does not re-read the video.
    """
    p0 = _load(pid)
    if not p0.slides:
        raise HTTPException(400, "There is no script to read yet.")
    _engine_ready(_engine(p0))
    redo = bool(payload.get("redo"))

    def pending(p) -> list:
        root = project_dir(pid)
        want = _wanted_read(p)
        todo = []
        for s in p.slides:
            take = s.takes.get(_engine(p)) or {}
            if (not redo and take.get("synthetic") and _take_read(take) == want
                    and (root / take.get("path", "")).is_file()):
                continue
            if (s.narration or "").strip():
                todo.append(s)
        return todo

    if payload.get("dry_run"):
        # What a hosted voice would be sent, so the creator can see the bill
        # coming before it is run up.
        todo = pending(p0)
        return {"paragraphs": len(todo),
                "characters": sum(len(s.narration.strip()) for s in todo),
                "engine": _engine(p0), "metered": _engine(p0) != tts_mod.ENGINE}

    def work(progress):
        with store.lock_for(pid):
            p = store.load(pid)
            root = project_dir(pid)
            todo = pending(p)
            kept = len(p.slides) - len(todo)
            if kept:
                progress(f"{kept} paragraph(s) already read in this voice")
            engine = _engine(p)
            progress(f"Reading {len(todo)} paragraph(s) as {p.narrator.voice} at "
                     f"{p.narrator.speed:.2f}x"
                     + ("" if engine == tts_mod.ENGINE else
                        f" with {voice_cloud.BY_KEY[engine]['label']} "
                        f"({sum(len(s.narration) for s in todo):,} characters)"))
            lexicon = _lexicon(p)
            if lexicon:
                progress(f"Pronunciation guide: {len(lexicon)} entries")
            for n, s in enumerate(todo, 1):
                try:
                    p.set_take(s, engine, _voice_one(p, s, root, lexicon))
                except tts_mod.TTSError:
                    # Out of credits halfway through a hosted read: what was
                    # already read was paid for, so it is kept, not dropped.
                    store.save(p)
                    raise
                if n % 5 == 0 or n == len(todo):
                    # Banked as it goes: a long script is a lot of work to lose.
                    store.save(p)
                    progress(f"{n}/{len(todo)} read "
                             f"({p.recorded_seconds() / 60:.1f} min so far)")
            if p.status in ("scripted", "media"):
                p.status = "recording"
            store.save(p)
        return {"read": len(todo), "kept": kept, "track": engine,
                "in_use": p.voice_track == engine}

    return {"job": jobs.start("voice-over", pid, work)}


@app.post("/api/projects/{pid}/slides/{sid}/voice-over")
def voice_over_one(pid: str, sid: str) -> dict:
    """Re-read one paragraph, after an edit or a change of mind."""
    with store.lock_for(pid):
        p = _load(pid)
        _engine_ready(_engine(p))
        s = _slide(p, sid)
        if not (s.narration or "").strip():
            raise HTTPException(400, "That paragraph has no words in it.")
        try:
            p.set_take(s, _engine(p), _voice_one(p, s, project_dir(pid)))
        except tts_mod.TTSError as exc:
            raise HTTPException(400, str(exc))
        if p.status in ("scripted", "media"):
            p.status = "recording"
        store.save(p)
    return {"slide": s.to_dict(), "recorded_seconds": p.recorded_seconds()}


@app.post("/api/projects/{pid}/takes/reprocess")
def reprocess_takes(pid: str) -> dict:
    """Clean every take again from the raw recording it came from.

    The raw upload is kept for exactly this. A take on disk is the output of
    whatever voice chain was current the day it was recorded, and re-reading a
    whole script to pick up a better one is not a reasonable thing to ask.
    """
    with store.lock_for(pid):
        p = _load(pid)
        root = project_dir(pid)
        done, failed = 0, []
        for n, s in enumerate(p.slides, 1):
            take = s.takes.get(MIC_TRACK) or {}
            if not take.get("raw_path") or not take.get("path"):
                continue
            try:
                raw = _safe_join(root, take["raw_path"])
                meta = audio_mod.process_take(raw, root / take["path"], p.voice)
            except Exception as exc:
                failed.append(f"paragraph {n}: {exc}")
                continue
            p.set_take(s, MIC_TRACK, {**take, **meta})
            done += 1
        store.save(p)
    return {"reprocessed": done, "skipped": len(failed), "failed": failed,
            "project": p.to_dict()}


@app.delete("/api/projects/{pid}/slides/{sid}/take")
def delete_take(pid: str, sid: str, track: str = "") -> dict:
    """Drop one paragraph's read in one voice — the video's, unless named.
    The file stays on disk; only the reference goes."""
    with store.lock_for(pid):
        p = _load(pid)
        s = _slide(p, sid)
        p.set_take(s, track or p.voice_track, None)
        store.save(p)
    return {"slide": s.to_dict()}


@app.get("/api/projects/{pid}/slides/{sid}/take.wav")
def get_take(pid: str, sid: str, request: Request, track: str = "") -> Response:
    """One paragraph's read — in the video's voice, or in `track` to compare."""
    p = _load(pid)
    s = _slide(p, sid)
    take = s.takes.get(track) if track else s.take
    if not take:
        raise HTTPException(404, "No take recorded")
    return _ranged(_safe_join(project_dir(pid), take["path"]), request)


@app.post("/api/projects/{pid}/voice-track")
def set_voice_track(pid: str, payload: dict = Body(...)) -> dict:
    """Choose the voice for the whole video. Every other voice's reads stay
    exactly where they are, so switching back costs nothing."""
    track = str(payload.get("track") or "")
    if track not in (MIC_TRACK, tts_mod.ENGINE, *voice_cloud.KEYS):
        raise HTTPException(400, f"Not a voice: {track}")
    with store.lock_for(pid):
        p = _load(pid)
        p.use_track(track)
        store.save(p)
    return p.to_dict()


# ----------------------------------------------------------------- mic setup
# Everything the record tab's mic panel runs on. One short test recording is
# kept per project (raw/_mictest.webm); it is measured once and then re-cleaned
# on every change to the chain, so a slider can be judged by ear against the
# same eight seconds rather than by reading its own label.
MICTEST_RAW = "raw/_mictest.webm"
MICTEST_OUT = "takes/_mictest.wav"


@app.get("/api/voice/presets")
def voice_presets() -> dict:
    return {"presets": VOICE_PRESETS, "default": Voice().to_dict()}


def _voice_report(p) -> dict:
    """Measure the test recording and re-clean it with this project's chain."""
    root = project_dir(p.id)
    raw = root / MICTEST_RAW
    if not raw.exists():
        raise HTTPException(404, "No test recording yet — record one first.")
    out = root / MICTEST_OUT
    error, meta = "", {}
    try:
        meta = audio_mod.process_take(raw, out, p.voice)
    except Exception as exc:                  # a silent or truncated test clip
        error = str(exc)
        out.unlink(missing_ok=True)
    return {"analysis": audio_mod.analyse(raw), "voice": p.voice.to_dict(),
            # `trimmed` is what lets the panel line the before and after up:
            # the cleaned file starts where the speech does, the raw one does not.
            "take": meta, "error": error, "processed": not error,
            "stamp": time.time()}


@app.post("/api/projects/{pid}/voice/test")
async def voice_test(pid: str, file: UploadFile) -> dict:
    """Take the mic panel's test recording and report on the room it was made in."""
    with store.lock_for(pid):
        p = _load(pid)
        raw = project_dir(pid) / MICTEST_RAW
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_bytes(await file.read())
        if raw.stat().st_size < 1024:
            raw.unlink(missing_ok=True)
            raise HTTPException(400, "That recording is empty.")
    return _voice_report(p)


@app.post("/api/projects/{pid}/voice/preview")
def voice_preview(pid: str, payload: dict = Body(default={})) -> dict:
    """Save a change to the chain and hear it on the test recording."""
    with store.lock_for(pid):
        p = _load(pid)
        if payload.get("voice"):
            _apply_voice(p.voice, payload["voice"])
            store.save(p)
    return _voice_report(p)


@app.get("/api/projects/{pid}/voice/test.wav")
def voice_test_wav(pid: str, request: Request) -> Response:
    """The test recording after the chain — the "after" side of the A/B."""
    path = project_dir(pid) / MICTEST_OUT
    if not path.exists():
        raise HTTPException(404, "Nothing cleaned yet")
    return _ranged(path, request)


@app.get("/api/projects/{pid}/voice/test.src")
def voice_test_src(pid: str, request: Request) -> Response:
    """The test recording exactly as the browser handed it over — the "before"."""
    path = project_dir(pid) / MICTEST_RAW
    if not path.exists():
        raise HTTPException(404, "No test recording yet")
    return _ranged(path, request)


# ------------------------------------------------------------------ presenter
@app.post("/api/projects/{pid}/presenter")
async def upload_presenter(pid: str, file: UploadFile) -> dict:
    """Attach a piece of camera footage of you to this video."""
    with store.lock_for(pid):
        p = _load(pid)
        suffix = Path(file.filename or "clip.mp4").suffix.lower()
        if suffix not in {".mp4", ".mov", ".m4v", ".webm", ".mkv"}:
            raise HTTPException(400, "That is not a video file I can read.")
        d = project_dir(pid) / "presenter"
        d.mkdir(exist_ok=True)
        for old in d.glob("clip.*"):
            old.unlink()
        dest = d / f"clip{suffix}"
        dest.write_bytes(await file.read())
        if dest.stat().st_size < 4096:
            dest.unlink()
            raise HTTPException(400, "That file is empty.")
        try:
            duration = ffutil.duration(dest)
            width, height = ffutil.dimensions(dest)
            has_audio = ffutil.has_audio(dest)
        except Exception as exc:
            dest.unlink()
            raise HTTPException(400, f"Could not read that clip: {exc}")
        if duration < 0.8:
            dest.unlink()
            raise HTTPException(400, "That clip is too short to cut in.")

        p.presenter = Presenter(
            path=f"presenter/{dest.name}", filename=file.filename or dest.name,
            source_duration=round(duration, 3), width=width, height=height,
            has_audio=has_audio,
            position=p.presenter.position or "after_intro",
        )
        store.save(p)
    return {"presenter": p.presenter.to_dict()}


@app.delete("/api/projects/{pid}/presenter")
def delete_presenter(pid: str) -> dict:
    with store.lock_for(pid):
        p = _load(pid)
        d = project_dir(pid) / "presenter"
        for old in d.glob("clip.*"):
            old.unlink()
        p.presenter = Presenter()
        store.save(p)
    return {"presenter": p.presenter.to_dict()}


# --------------------------------------------------------------------- render
@app.post("/api/projects/{pid}/render")
def start_render(pid: str, payload: dict = Body(default={})) -> dict:
    _load(pid)
    preview = bool(payload.get("preview"))

    def work(progress):
        with store.lock_for(pid):
            p = store.load(pid)
            result = render.render(p, progress, preview=preview)
            store.log(p, f"Rendered {result['output']}")
            store.save(p)
        return result

    return {"job": jobs.start("render", pid, work)}


@app.post("/api/projects/{pid}/preview-opening")
def preview_opening(pid: str, payload: dict = Body(default={})) -> dict:
    """Render a standalone video's own opening or end card, to play in app.

    A video in a channel previews those on the channel page, where they are
    set — previewing them here would suggest they belong to this video.
    """
    kind = "outro" if str(payload.get("kind") or "") == "outro" else "intro"
    p = _load(pid)
    if p.channel_id:
        raise HTTPException(400, "This video opens on its channel's slate — "
                                 "preview it on the channel page.")

    def work(progress):
        with store.lock_for(pid):
            return render.preview_opening(store.load(pid), kind, progress)

    return {"job": jobs.start(f"{kind} preview", pid, work)}


@app.post("/api/projects/{pid}/slides/{sid}/preview")
def preview_segment(pid: str, sid: str) -> dict:
    """Render just the picture this paragraph sits under, small, to play in app.

    A job rather than a response body: it is seconds rather than milliseconds,
    and it may have to fetch the picture first. The project is saved after
    because downloading that picture is what fills in its local copy.
    """
    _slide(_load(pid), sid)

    def work(progress):
        with store.lock_for(pid):
            p = store.load(pid)
            result = render.preview_segment(p, sid, progress)
            store.save(p)
        return result

    return {"job": jobs.start("segment preview", pid, work)}


# ---------------------------------------------------------------- timeline
_PROXY_LOCKS: dict[str, "threading.Lock"] = {}


@app.get("/api/projects/{pid}/timeline")
def get_timeline(pid: str) -> dict:
    """The cut laid out in time, and which pictures already have a proxy to
    play. Renders nothing."""
    return render.timeline(_load(pid))


@app.post("/api/projects/{pid}/timeline/proxy")
def timeline_proxy(pid: str, payload: dict = Body(...)) -> dict:
    """Make the small playable proxy for some of the timeline's entries.

    `refs` are what the timeline lists: "intro", "outro" or a picture's number.
    Only the ones asked for, one after another, and only those whose cached
    proxy no longer matches the script: the player asks for the entry under
    the playhead and the next, never the whole cut.
    """
    _load(pid)
    refs = [str(r) for r in (payload.get("refs") or [])][:16]
    if not refs or any(r not in ("intro", "outro") and not r.isdigit() for r in refs):
        raise HTTPException(400, "refs must be intro, outro or picture numbers")

    def work(progress):
        import threading
        # Fetching a picture changes the project, so that part holds the lock
        # and saves; the drawing itself does not, and edits stay possible.
        with store.lock_for(pid):
            p = store.load(pid)
            groups = render._groups_for_preview(p)
            leads = [groups[int(r)][0][0] for r in refs if r.isdigit() and int(r) < len(groups)]
            if leads and render.media.download_chosen(p, progress, only=leads):
                progress("Some pictures could not be downloaded; those play as graded slates")
            store.save(p)
        lock = _PROXY_LOCKS.setdefault(pid, threading.Lock())
        done = []
        with lock:
            p = store.load(pid)
            for r in refs:
                done.append(render.proxy_ref(p, r, progress, download=False))
        return {"segments": done}

    return {"job": jobs.start("timeline proxy", pid, work)}


@app.post("/api/projects/{pid}/timeline/mix")
def timeline_mix(pid: str) -> dict:
    """Mix the whole cut's sound (narration, slate sting, ducked music bed) into
    one file for the timeline to play. Audio only, so it is quick."""
    _load(pid)

    def work(progress):
        import threading
        lock = _PROXY_LOCKS.setdefault(pid + ":mix", threading.Lock())
        with lock:
            return render.build_mix(store.load(pid), progress)

    return {"job": jobs.start("timeline sound", pid, work)}


@app.post("/api/projects/{pid}/description")
def write_description(pid: str) -> dict:
    """Write the YouTube description and tags, and keep them on the project."""
    _load(pid)

    def work(progress):
        p = store.load(pid)
        out = youtube_mod.build_description(p, progress)
        with store.lock_for(pid):
            fresh = store.load(pid)
            fresh.description = out["description"]
            fresh.yt_tags = out["tags"]
            store.save(fresh)
        progress("Description written" + ("" if out["exact"] else
                 " — some paragraphs aren't recorded yet, so the chapter times are estimates"))
        return out

    return {"job": jobs.start("description", pid, work)}


@app.get("/api/projects/{pid}/credits")
def credits(pid: str) -> dict:
    return {"text": render.credits_text(_load(pid))}


@app.get("/api/music")
def music_list() -> list[dict]:
    return [
        {"name": p.name, "size_mb": round(p.stat().st_size / 1e6, 1)}
        for p in sorted(MUSIC_DIR.iterdir())
        if p.suffix.lower() in {".mp3", ".wav", ".m4a", ".flac", ".aac", ".ogg"}
    ]


# ------------------------------------------------------------- 3D models
# The shared model library (app/models3d.py) and each 3D explainer's cast.
def _model_or_404(mid: str) -> dict:
    try:
        return models3d.get(mid)
    except models3d.ModelError as exc:
        raise HTTPException(404, str(exc))


@app.get("/api/models")
def list_models() -> list[dict]:
    return models3d.all_models()


@app.post("/api/models")
async def add_model(file: UploadFile) -> dict:
    """A GLB into the library. Streamed to a temp file, never held in memory."""
    if not (file.filename or "").lower().endswith(".glb"):
        raise HTTPException(400, "Only .glb files are accepted. Most sites offer a "
                                 "GLB download; Blender exports one as glTF Binary.")
    fd, tmp_name = tempfile.mkstemp(suffix=".glb", dir=str(CACHE_DIR))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as out:
            shutil.copyfileobj(file.file, out, 1024 * 1024)
        return models3d.add(tmp, file.filename or "model.glb")
    except models3d.ModelError as exc:
        raise HTTPException(400, str(exc))
    finally:
        tmp.unlink(missing_ok=True)


@app.get("/api/models/{mid}")
def get_model(mid: str) -> dict:
    return _model_or_404(mid)


@app.patch("/api/models/{mid}")
def edit_model(mid: str, payload: dict = Body(default={})) -> dict:
    _model_or_404(mid)
    try:
        return models3d.update(mid, payload)
    except (models3d.ModelError, TypeError, ValueError) as exc:
        raise HTTPException(400, str(exc))


@app.delete("/api/models/{mid}")
def delete_model(mid: str) -> dict:
    _model_or_404(mid)
    using = [p["title"] for p in store.list_projects() if mid in p["cast"]]
    if using:
        raise HTTPException(409, "Still in the cast of: " + "; ".join(using[:5])
                            + ". Remove it from those videos first.")
    models3d.delete(mid)
    return {"deleted": mid}


@app.post("/api/models/{mid}/identify")
async def identify_model(mid: str, views: list[UploadFile], captions: str = Form("[]"),
                         meta: str = Form("{}"), kind: str = Form("object"),
                         mode: str = Form("identify")) -> dict:
    """Ask Claude what this model is, from the pictures the browser rendered
    for its kind (static/stage/identify.js). Stores the suggestions; changes
    nothing else — the confirm screen applies them on a click."""
    m = _model_or_404(mid)
    if kind not in models3d.KINDS:
        raise HTTPException(400, f"Unknown kind {kind!r}")
    images = [await v.read() for v in views[:8]]
    if not images or any(len(b) > 4 * 1024 * 1024 for b in images):
        raise HTTPException(400, "Send one to eight pictures, each under 4 MB.")
    try:
        caps = [str(c)[:200] for c in json.loads(captions)][:len(images)]
        info = json.loads(meta) if meta else {}
    except (json.JSONDecodeError, TypeError) as exc:
        raise HTTPException(400, f"Bad captions or meta: {exc}")
    caps += [""] * (len(images) - len(caps))
    from . import identify as identify_mod
    from starlette.concurrency import run_in_threadpool
    if mode == "parts":
        # Highlighted pictures of the named parts, plus where each sits.
        table = (info or {}).get("table") or []
        try:
            named = await run_in_threadpool(identify_mod.name_parts, m, images, caps, table)
        except llm_mod.LLMUnavailable as exc:
            raise HTTPException(503, str(exc))
        except llm_mod.LLMError as exc:
            raise HTTPException(502, f"Claude could not name the parts: {exc}")
        ident = dict(m.get("identity") or {})
        ident["parts"] = {**(ident.get("parts") or {}), **named}
        ident["parts_from_pictures"] = True
        ident["parts_table"] = [t for t in table if isinstance(t, dict)][:24]   # the measured positions, for checking
        return models3d.update(mid, {"identity": ident})
    if mode == "refine":
        # The closer look at a site's subject: tighten its box, nothing else.
        try:
            box = await run_in_threadpool(identify_mod.refine, m, images[0], caps[0],
                                          (info or {}).get("grid") or {})
        except llm_mod.LLMUnavailable as exc:
            raise HTTPException(503, str(exc))
        except llm_mod.LLMError as exc:
            raise HTTPException(502, f"Claude could not place it: {exc}")
        ident = dict(m.get("identity") or {})
        if box and ident.get("subject"):
            ident["subject"] = {**ident["subject"], "box": box, "refined": True}
        return models3d.update(mid, {"identity": ident})
    try:
        # Off the event loop: the Claude call blocks for up to a few minutes.
        found = await run_in_threadpool(identify_mod.identify, m, kind, images, caps,
                                        info if isinstance(info, dict) else {})
    except llm_mod.LLMUnavailable as exc:
        raise HTTPException(503, str(exc))
    except llm_mod.LLMError as exc:
        raise HTTPException(502, f"Claude could not identify it: {exc}")
    return models3d.update(mid, {"identity": found})


@app.get("/api/models/{mid}/model.glb")
def model_file(mid: str, request: Request) -> Response:
    try:
        path = models3d.glb_path(mid)
    except models3d.ModelError as exc:
        raise HTTPException(404, str(exc))
    return _ranged(path, request)


@app.get("/api/models/{mid}/thumb.jpg")
def model_thumb(mid: str) -> Response:
    _model_or_404(mid)
    path = models3d.thumb_path(mid)
    if not path.is_file():
        raise HTTPException(404, "No thumbnail yet")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "no-cache"})


@app.post("/api/models/{mid}/thumb")
async def set_model_thumb(mid: str, request: Request) -> dict:
    """The browser renders the thumbnail, since it is the one with WebGL."""
    _model_or_404(mid)
    try:
        models3d.set_thumb(mid, await request.body())
    except models3d.ModelError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True}


@app.post("/api/projects/{pid}/cast")
def add_to_cast(pid: str, payload: dict = Body(...)) -> dict:
    """Add a subject: {"subject": name}, or {"model": id} for a library model
    playing itself."""
    with store.lock_for(pid):
        p = _load(pid)
        subs = cast_mod.subjects(p)
        mid = str(payload.get("model") or "")
        if mid:
            m = _model_or_404(mid)
            if not any(x["model"] == mid for x in subs):
                subs.append(cast_mod.clean_subject({"subject": cast_mod.model_name(m), "model": mid,
                                                    "role": "supporting"}, 99))
        else:
            new = cast_mod.clean_subject({"subject": payload.get("subject"), "role": payload.get("role")}, 99)
            if not new:
                raise HTTPException(400, "Name the subject.")
            subs.append(new)
        p.cast = subs
        store.save(p)
    return get_project(pid)


@app.patch("/api/projects/{pid}/cast/{sid}")
def edit_cast(pid: str, sid: str, payload: dict = Body(...)) -> dict:
    """Rename a subject, change its role, give it a model, or say "photos instead"."""
    with store.lock_for(pid):
        p = _load(pid)
        subs = cast_mod.subjects(p)
        s = next((x for x in subs if x["id"] == sid), None)
        if not s:
            raise HTTPException(404, "No such subject")
        if "model" in payload:
            mid = str(payload.get("model") or "")
            if mid:
                _model_or_404(mid)
            s["model"] = mid
            if mid:
                s["mode"] = "model"
        for k in ("subject", "role", "why", "mode"):
            if k in payload:
                s[k] = payload[k]
        sections = len((p.outline or {}).get("sections") or [])
        p.cast = [cast_mod.clean_subject(x, sections or 99) or x for x in subs]
        store.save(p)
    return get_project(pid)


@app.delete("/api/projects/{pid}/cast/{sid}")
def remove_from_cast(pid: str, sid: str) -> dict:
    """Drop a subject (by its id, or by the model playing it)."""
    with store.lock_for(pid):
        p = _load(pid)
        p.cast = [x for x in cast_mod.subjects(p) if x["id"] != sid and x["model"] != sid]
        store.save(p)
    return get_project(pid)


@app.post("/api/projects/{pid}/cast/propose")
def repropose_cast(pid: str) -> dict:
    """Ask again for the cast; subjects with a model already chosen are kept."""
    _load(pid)

    def work(progress):
        with store.lock_for(pid):
            p = store.load(pid)
            p.cast = cast_mod.propose(p, progress)
            store.save(p)
        return {"cast": len(p.cast)}

    return {"job": jobs.start("cast", pid, work)}


# ------------------------------------------------------------------- library
@app.get("/api/library")
def list_library(q: str = "", kind: str = "", tag: str = "") -> list[dict]:
    return library.list_all(q=q, kind=kind, tag=tag)


@app.post("/api/library")
async def add_library_asset(
    file: UploadFile,
    title: str = Form(""),
    tags: str = Form(""),
    author: str = Form(""),
    license: str = Form(""),
    source_page: str = Form(""),
) -> dict:
    """Manually downloaded stock — from Storyblocks or anywhere else — filed
    into the shared library instead of one throwaway slide."""
    data = await file.read()
    if not data:
        raise HTTPException(400, "Empty file")
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    return library.add(data, file.filename or "asset", title=title, tags=tag_list,
                       author=author, license=license, source_page=source_page)


@app.patch("/api/library/{asset_id}")
def edit_library_asset(asset_id: str, payload: dict = Body(default={})) -> dict:
    try:
        return library.update(asset_id, **payload)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))


@app.delete("/api/library/{asset_id}")
def delete_library_asset(asset_id: str) -> dict:
    if not library.remove(asset_id):
        raise HTTPException(404, "No such asset")
    return {"deleted": asset_id}


# --------------------------------------------------------------- folders
@app.get("/api/library/folders")
def list_library_folders() -> list[dict]:
    return library.list_folders()


@app.post("/api/library/folders")
def add_library_folder(payload: dict = Body(...)) -> dict:
    """Start tracking a folder. Scanning it is a separate step — see below —
    so a slow walk of a large folder shows progress instead of this call
    hanging until it's done."""
    path = (payload.get("path") or "").strip()
    if not path:
        raise HTTPException(400, "Give me a folder path.")
    try:
        return library.add_folder(path, label=(payload.get("label") or "").strip())
    except NotADirectoryError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/library/folders/{folder_id}/scan")
def scan_library_folder(folder_id: str) -> dict:
    def work(progress):
        return library.scan_folder(folder_id, progress)

    return {"job": jobs.start("library-scan", "", work)}


@app.delete("/api/library/folders/{folder_id}")
def remove_library_folder(folder_id: str) -> dict:
    dropped = library.remove_folder(folder_id)
    return {"deleted": folder_id, "assets_dropped": dropped}


# Set by app/desktop.py, in the same process, when a native folder dialog is
# actually available — pywebview's, not this server's. A plain browser tab
# (dev mode, or the Record-tab fallback over a LAN) cannot hand a real
# filesystem path back from any file input for security reasons, and has no
# business doing so for a server it may not even be running on the same
# machine as; this stays None there, and the UI falls back to a text field.
FOLDER_DIALOG: "Callable[[], str] | None" = None


@app.post("/api/pick-folder")
def pick_folder_dialog() -> dict:
    """Ask the native folder picker for a path, when one is available."""
    if FOLDER_DIALOG is None:
        raise HTTPException(501, "No native folder picker in this context — "
                             "type or paste the path instead.")
    path = FOLDER_DIALOG()
    if not path:
        raise HTTPException(409, "No folder chosen.")
    return {"path": path}


# ------------------------------------------------------ project files
# The native "save as" dialog, set by app.desktop exactly like FOLDER_DIALOG
# above: given a suggested file name, returns the path chosen, or "".
SAVE_DIALOG: "Callable[[str], str] | None" = None


@app.post("/api/projects/{pid}/export")
def export_project_to(pid: str) -> dict:
    """Save a project file wherever the native dialog says. 501 outside the
    desktop app, where the page downloads it from the GET below instead."""
    p = _load(pid)
    if SAVE_DIALOG is None:
        raise HTTPException(501, "No native save dialog in this context.")
    chosen = SAVE_DIALOG(transfer.filename_for(p) + transfer.EXTENSION)
    if not chosen:
        raise HTTPException(409, "Not saved.")
    dest = Path(chosen)
    if dest.suffix != transfer.EXTENSION:
        dest = dest.with_name(dest.name + transfer.EXTENSION)
    return transfer.export(pid, dest)


@app.get("/api/projects/{pid}/export")
def export_project_download(pid: str) -> Response:
    """The same file as a download, for a browser tab."""
    from starlette.background import BackgroundTask
    p = _load(pid)
    name = transfer.filename_for(p) + transfer.EXTENSION
    tmp = Path(tempfile.mkdtemp(prefix="export-", dir=CACHE_DIR)) / name
    transfer.export(pid, tmp)
    return FileResponse(tmp, filename=name, media_type="application/zip",
                        background=BackgroundTask(shutil.rmtree, tmp.parent, True))


@app.post("/api/projects/import")
def import_project(file: UploadFile, on_conflict: str = Form("")) -> dict:
    """Open a project file. A 409 means the project is already here; the page
    asks, then sends it again with on_conflict "replace" or "copy"."""
    if on_conflict not in ("", "replace", "copy"):
        raise HTTPException(400, "on_conflict must be replace or copy")
    with tempfile.NamedTemporaryFile(dir=CACHE_DIR, suffix=transfer.EXTENSION,
                                     delete=False) as fh:
        shutil.copyfileobj(file.file, fh)
        tmp = Path(fh.name)
    try:
        return transfer.import_(tmp, on_conflict)
    except transfer.AlreadyHere as exc:
        raise HTTPException(409, {"message": str(exc), "already_here": True,
                                  "id": exc.pid, "title": exc.title})
    except transfer.TransferError as exc:
        raise HTTPException(400, str(exc))
    finally:
        tmp.unlink(missing_ok=True)


@app.get("/api/library/file/{asset_id}")
def library_file(asset_id: str, request: Request) -> Response:
    path = library.file_path(asset_id)
    if not path or not path.is_file():
        raise HTTPException(404, "No such asset")
    return _ranged(path, request)


@app.get("/api/library/thumb/{asset_id}")
def library_thumb(asset_id: str) -> Response:
    path = library.thumb_path(asset_id)
    if not path or not path.is_file():
        raise HTTPException(404, "No thumbnail")
    return FileResponse(path, media_type="image/jpeg",
                        headers={"Cache-Control": "max-age=86400"})


@app.get("/api/projects/{pid}/file/{rel:path}")
def project_file(pid: str, rel: str, request: Request) -> Response:
    return _ranged(_safe_join(project_dir(pid), rel), request)


# ------------------------------------------------------------- playback help
@app.get("/api/playback")
def playback_status() -> dict:
    """Whether this machine's own window can play an H.264 render, and the fix."""
    return playback_mod.status()


@app.post("/api/reveal")
def reveal_file(payload: dict = Body(...)) -> dict:
    """Show one of this video's (or channel's) files in the file manager.

    The escape hatch behind every player in the app: the file is on disk and
    is fine, so when the window cannot decode it the creator can still watch
    it in their own player. Only ever a path inside a project or channel
    folder — the same join the file routes use, for the same reason.
    """
    scope = str(payload.get("scope") or "project")
    ident = str(payload.get("id") or "")
    rel = str(payload.get("rel") or "")
    if scope not in ("project", "channel", "music"):
        raise HTTPException(400, "scope must be project, channel or music")
    if scope == "music":
        # The shared bed folder, so a creator can drop tracks into it.
        root = MUSIC_DIR
    else:
        root = project_dir(ident) if scope == "project" else channels.channel_dir(ident)
    path = _safe_join(root, rel)
    try:
        opened, folder = playback_mod.reveal(path)
    except playback_mod.RevealError as exc:
        raise HTTPException(400, str(exc))
    return {"opened": opened, "folder": folder, "path": str(path)}


_STING_TYPES = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}


def _sting_spec(p, role: str):
    if role not in ("intro", "outro"):
        raise HTTPException(404, "A sting goes on the intro or the outro")
    return p.intro if role == "intro" else p.outro


@app.post("/api/projects/{pid}/sting/{role}")
async def upload_project_sting(pid: str, role: str, file: UploadFile) -> dict:
    """A standalone video's own sting for its title card or its end card."""
    data = await file.read()
    with store.lock_for(pid):
        p = _load(pid)
        spec = _sting_spec(p, role)
        suffix = Path(file.filename or "sting.mp3").suffix.lower()
        if suffix not in _STING_TYPES:
            raise HTTPException(400, "That is not an audio file I can read.")
        d = project_dir(pid) / "music"
        d.mkdir(parents=True, exist_ok=True)
        for old in d.glob(f"sting_{role}.*"):
            old.unlink()
        dest = d / f"sting_{role}{suffix}"
        dest.write_bytes(data)
        try:
            length = ffutil.duration(dest)
        except Exception as exc:
            dest.unlink()
            raise HTTPException(400, f"Could not read that audio: {exc}")
        if length < 0.5:
            dest.unlink()
            raise HTTPException(400, "That sting is too short.")
        if role == "intro":
            spec.music, spec.music_filename = f"music/{dest.name}", file.filename or dest.name
            spec.music_duration, spec.music_start = round(length, 2), 0.0
        else:
            spec.sting, spec.sting_filename = f"music/{dest.name}", file.filename or dest.name
            spec.sting_duration, spec.sting_start = round(length, 2), 0.0
        store.save(p)
    return p.to_dict()


@app.delete("/api/projects/{pid}/sting/{role}")
def delete_project_sting(pid: str, role: str) -> dict:
    with store.lock_for(pid):
        p = _load(pid)
        spec = _sting_spec(p, role)
        for old in (project_dir(pid) / "music").glob(f"sting_{role}.*"):
            old.unlink()
        if role == "intro":
            spec.music = spec.music_filename = ""
            spec.music_duration = spec.music_start = 0.0
        else:
            spec.sting = spec.sting_filename = ""
            spec.sting_duration = spec.sting_start = 0.0
        store.save(p)
    return p.to_dict()


@app.get("/api/projects/{pid}/download")
def download_output(pid: str) -> Response:
    p = _load(pid)
    out = (p.render or {}).get("output")
    if not out:
        raise HTTPException(404, "Nothing rendered yet")
    path = _safe_join(project_dir(pid), out)
    return FileResponse(path, media_type="video/mp4", filename=path.name)


# ----------------------------------------------------------------------- jobs
@app.get("/api/jobs/{jid}")
def job_status(jid: str, since: int = 0) -> dict:
    job = jobs.get(jid)
    if not job:
        raise HTTPException(404, "No such job")
    return {
        "id": job["id"], "kind": job["kind"], "state": job["state"],
        "error": job["error"], "result": job["result"],
        "log": job["log"][since:], "log_total": len(job["log"]),
        "elapsed": round((job["finished_at"] or time.time()) - job["started_at"], 1),
    }


@app.exception_handler(Exception)
def unhandled(_request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse({"detail": f"{type(exc).__name__}: {exc}"}, status_code=500)


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
