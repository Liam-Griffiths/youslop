"""Publishing a rendered video straight to YouTube.

Google's OAuth2 and the YouTube Data API v3 are both plain REST/JSON, so this
is `httpx` calls by hand — the same choice `media/providers.py` already makes
for Storyblocks and `research.py` just made for search, rather than pulling
in `google-api-python-client` for what a dozen requests already cover.

A refresh token is a credential, not a setting: it lives in its own file,
`channels/{cid}/youtube.json`, never inside `channel.json` or anything that
gets handed back from an API response. `status()` is the only thing the UI
ever sees, and it carries no secret.
"""
from __future__ import annotations

import json
import os
import secrets
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable

import httpx

from . import channels, models3d
from .config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
from .render import credits_text
from .schema import Project
from .store import project_dir

Progress = Callable[[str], None]

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/youtube/v3"
UPLOAD_API = "https://www.googleapis.com/upload/youtube/v3"
SCOPE = "https://www.googleapis.com/auth/youtube.upload"

CHUNK = 8 * 1024 * 1024   # one resumable-upload PUT per 8MB, so progress can move

# Well-known category IDs, stable across regions, so the UI doesn't need a
# videoCategories.list round trip for a handful of values that don't change.
CATEGORIES = [
    {"id": "22", "label": "People & Blogs"},
    {"id": "27", "label": "Education"},
    {"id": "24", "label": "Entertainment"},
    {"id": "25", "label": "News & Politics"},
    {"id": "28", "label": "Science & Technology"},
    {"id": "26", "label": "Howto & Style"},
    {"id": "20", "label": "Gaming"},
]


def available() -> bool:
    return bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)


# ---------------------------------------------------------------- oauth flow
# A five-minute window between "start" and "callback", not something that
# needs to survive a restart — an in-memory dict is exactly as durable as this
# needs to be, the same reasoning app/jobs.py already applies to job state.
_PENDING: dict[str, tuple[str, float]] = {}   # state -> (channel_id, issued_at)
_PENDING_LOCK = threading.Lock()
_PENDING_TTL = 600


def _sweep_pending() -> None:
    cutoff = time.time() - _PENDING_TTL
    for k in [k for k, (_, t) in _PENDING.items() if t < cutoff]:
        _PENDING.pop(k, None)


def auth_url(channel_id: str, redirect_uri: str) -> str:
    """The URL to send the browser to. Stashes `state` -> channel_id first."""
    state = secrets.token_urlsafe(24)
    with _PENDING_LOCK:
        _sweep_pending()
        _PENDING[state] = (channel_id, time.time())
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",     # only way to get a refresh_token back
        "prompt": "consent",          # force one even on a re-connect
        "state": state,
    }
    return f"{AUTH_URL}?{httpx.QueryParams(params)}"


def resolve_state(state: str) -> str | None:
    """The channel_id a callback's `state` was issued for. Consumes it —
    a state is good for one callback, same as any OAuth state should be."""
    with _PENDING_LOCK:
        _sweep_pending()
        entry = _PENDING.pop(state, None)
    return entry[0] if entry else None


def exchange_code(code: str, redirect_uri: str) -> dict:
    r = httpx.post(TOKEN_URL, data={
        "code": code, "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET, "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }, timeout=20.0)
    r.raise_for_status()
    return r.json()


def _refresh(refresh_token: str) -> dict:
    r = httpx.post(TOKEN_URL, data={
        "refresh_token": refresh_token, "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET, "grant_type": "refresh_token",
    }, timeout=20.0)
    r.raise_for_status()
    return r.json()


# ------------------------------------------------------------------- storage
def _token_path(cid: str) -> Path:
    return channels.channel_dir(cid) / "youtube.json"


def _read(cid: str) -> dict | None:
    p = _token_path(cid)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _write(cid: str, data: dict) -> None:
    d = channels.channel_dir(cid)
    payload = json.dumps(data, indent=2, ensure_ascii=False)
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
        os.replace(tmp, _token_path(cid))
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _fetch_identity(access_token: str) -> dict:
    """The connected channel's own title/thumbnail, for display only."""
    r = httpx.get(f"{API}/channels", params={"part": "snippet", "mine": "true"},
                  headers={"Authorization": f"Bearer {access_token}"}, timeout=20.0)
    r.raise_for_status()
    items = (r.json() or {}).get("items") or []
    if not items:
        return {}
    snippet = items[0].get("snippet") or {}
    thumbs = snippet.get("thumbnails") or {}
    return {
        "channel_title": snippet.get("title", ""),
        "channel_thumb": (thumbs.get("default") or {}).get("url", ""),
    }


def complete_connection(cid: str, code: str, redirect_uri: str) -> None:
    """The callback's whole job: trade the code, look up who this is, save it."""
    tokens = exchange_code(code, redirect_uri)
    identity = {}
    if tokens.get("access_token"):
        try:
            identity = _fetch_identity(tokens["access_token"])
        except Exception:
            pass       # display info only; a connected account with no name shown is fine
    _write(cid, {
        "refresh_token": tokens.get("refresh_token", ""),
        "access_token": tokens.get("access_token", ""),
        "expires_at": time.time() + float(tokens.get("expires_in") or 0),
        "connected_at": time.time(),
        **identity,
    })


def status(cid: str) -> dict:
    """What the UI is allowed to know: connected or not, and who. No secrets."""
    data = _read(cid)
    if not data or not data.get("refresh_token"):
        return {"connected": False}
    return {
        "connected": True,
        "channel_title": data.get("channel_title", ""),
        "channel_thumb": data.get("channel_thumb", ""),
        "connected_at": data.get("connected_at", 0),
    }


def disconnect(cid: str) -> None:
    _token_path(cid).unlink(missing_ok=True)


def _access_token(cid: str) -> str:
    data = _read(cid)
    if not data or not data.get("refresh_token"):
        raise RuntimeError("This channel is not connected to YouTube.")
    if data.get("access_token") and time.time() < float(data.get("expires_at", 0)) - 60:
        return data["access_token"]
    fresh = _refresh(data["refresh_token"])
    data["access_token"] = fresh.get("access_token", "")
    data["expires_at"] = time.time() + float(fresh.get("expires_in") or 0)
    _write(cid, data)
    return data["access_token"]


# -------------------------------------------------------------------- upload
def upload_video(
    project: Project, channel_id: str, *,
    title: str, description: str, tags: list[str], category_id: str,
    privacy: str, progress: Progress = lambda m: None,
) -> dict:
    """Resumable-upload the project's rendered video, then its thumbnail.

    Returns {"video_id", "url"}.
    """
    out = (project.render or {}).get("output")
    if not out:
        raise RuntimeError("Nothing rendered yet.")
    video_path = project_dir(project.id) / out
    if not video_path.is_file():
        raise RuntimeError(f"Rendered file is missing: {out}")
    size = video_path.stat().st_size

    token = _access_token(channel_id)
    headers = {"Authorization": f"Bearer {token}"}

    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "tags": [t.strip() for t in tags if t.strip()][:500],
            "categoryId": str(category_id or "22"),
        },
        "status": {
            "privacyStatus": privacy if privacy in ("private", "unlisted", "public")
                             else "private",
            "selfDeclaredMadeForKids": False,
        },
    }
    progress("Starting the upload session")
    init = httpx.post(
        f"{UPLOAD_API}/videos", params={"uploadType": "resumable", "part": "snippet,status"},
        headers={**headers, "Content-Type": "application/json; charset=UTF-8",
                "X-Upload-Content-Type": "video/mp4",
                "X-Upload-Content-Length": str(size)},
        json=body, timeout=30.0,
    )
    init.raise_for_status()
    upload_url = init.headers["Location"]

    sent = 0
    video_id = ""
    with open(video_path, "rb") as fh, httpx.Client(timeout=120.0) as client:
        while True:
            chunk = fh.read(CHUNK)
            if not chunk:
                break
            end = sent + len(chunk) - 1
            r = client.put(
                upload_url,
                headers={"Content-Length": str(len(chunk)),
                        "Content-Range": f"bytes {sent}-{end}/{size}"},
                content=chunk,
            )
            sent += len(chunk)
            if r.status_code in (200, 201):
                video_id = (r.json() or {}).get("id", "")
                break
            if r.status_code != 308:      # 308 = keep going, anything else is real
                r.raise_for_status()
            progress(f"  uploading… {sent / size * 100:.0f}% "
                     f"({sent / 1e6:.0f}/{size / 1e6:.0f} MB)")

    if not video_id:
        raise RuntimeError("Upload finished but YouTube did not return a video id.")
    progress(f"Uploaded — https://youtu.be/{video_id}")

    thumb = project_dir(project.id) / "thumb" / "thumb.jpg"
    if thumb.is_file():
        progress("Setting the thumbnail")
        try:
            r = httpx.post(
                f"{UPLOAD_API}/thumbnails/set", params={"videoId": video_id},
                headers={**headers, "Content-Type": "image/jpeg"},
                content=thumb.read_bytes(), timeout=60.0,
            )
            r.raise_for_status()
        except Exception as exc:
            # The video is already up; a thumbnail failure is not worth losing that.
            progress(f"  thumbnail failed ({str(exc)[:120]}) — set it manually in Studio")

    return {"video_id": video_id, "url": f"https://youtu.be/{video_id}"}


def default_description(project: Project) -> str:
    return project.description or credits_text(project)


# ---------------------------------------------------------------- description
CHAPTER_MIN_GAP = 10.0      # YouTube ignores a chapter list with one shorter


def _stamp(seconds: float) -> str:
    s = int(max(0, seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def chapter_points(project: Project) -> tuple[list[dict], bool]:
    """Where the video's chapters start, from the same timeline the render
    uses — so the timestamps land where the sections actually begin.

    Marked chapters are used when there are at least two; otherwise the
    outline's beats stand in, named by the description writer. Returns the
    points and whether every paragraph is recorded (if not, the times are
    estimates and will move).

    YouTube only shows chapters when the first is at 0:00, there are at least
    three, and each runs ten seconds or more, so the list is shaped to that:
    the opening is pinned to 0:00 and anything closer than ten seconds to the
    previous point is folded into it.
    """
    from . import render
    tl = render.timeline(project)
    paras = [p for seg in tl["segments"] if seg["type"] == "picture" for p in seg["paragraphs"]]
    by_id = {s.id: s for s in project.slides}
    marked = [p for p in paras if (p.get("chapter") or "").strip()]
    points: list[dict] = []
    if len(marked) >= 2:
        for p in marked:
            points.append({"t": p["start"], "title": p["chapter"].strip(), "text": p["text"]})
    else:
        last_beat = None
        for p in paras:
            beat = (by_id[p["id"]].beat or "").strip() if p["id"] in by_id else ""
            if beat and beat != last_beat:
                points.append({"t": p["start"], "title": "", "text": p["text"]})
            last_beat = beat or last_beat
    if not points or points[0]["t"] > 0.01:
        first = paras[0]["text"] if paras else ""
        points.insert(0, {"t": 0.0, "title": "", "text": first})
    points[0]["t"] = 0.0
    shaped: list[dict] = []
    for p in points:
        if shaped and p["t"] - shaped[-1]["t"] < CHAPTER_MIN_GAP:
            continue
        shaped.append(p)
    for p in shaped:
        p["start"] = _stamp(p["t"])
    return shaped, all(s.take for s in project.slides)


def build_description(project: Project, progress: Callable[[str], None] = lambda m: None) -> dict:
    """Write the whole description: Claude's hook and summary, chapters timed
    off the timeline, hashtags, and the picture credits."""
    from . import script_gen
    points, exact = chapter_points(project)
    progress(f"Writing the description ({len(points)} chapter point(s))")
    words = script_gen.write_description(project, points)
    titles = words["chapter_titles"]
    lines = [words["hook"], ""]
    if words["summary"]:
        lines += [words["summary"], ""]
    if len(points) >= 3:
        lines.append("Chapters")
        for n, p in enumerate(points):
            title = (titles[n] if n < len(titles) and titles[n] else p["title"]) or (
                "Intro" if n == 0 else f"Part {n + 1}")
            lines.append(f"{p['start']} {title}")
        lines.append("")
    credits = credits_text(project).split("\n")
    # credits_text opens with the title, which the description doesn't repeat.
    while credits and not credits[0].lower().startswith(("image", "opening", "music")):
        credits.pop(0)
    # The licence reminder at the end is for the creator, not the viewer.
    credits = [c for c in credits if not c.startswith("Verify every licence")]
    if [c for c in credits if c.startswith("- ")] == [] and not any(
            c.startswith("Music:") for c in credits):
        credits = []          # a heading with nothing under it
    while credits and not credits[-1].strip():
        credits.pop()
    # A 3D explainer's models: a CC-BY model must be credited, so these are
    # never left to the creator to remember. CC0 models owe nothing.
    model_lines = []
    for c in project.cast:
        try:
            line = models3d.credit_line(models3d.get(c.get("model", "")))
        except models3d.ModelError:
            continue
        if line:
            model_lines.append(f"- {line}")
    if model_lines:
        credits = credits + ([""] if credits else []) + ["3D models:"] + model_lines
    if credits:
        lines += credits + [""]
    if words["hashtags"]:
        lines.append(" ".join(f"#{h}" for h in words["hashtags"]))
    text = "\n".join(lines).strip()[:5000]
    return {"description": text, "tags": words["tags"], "chapters": len(points),
            "exact": exact}
