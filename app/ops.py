"""Synchronous production operations shared by HTTP jobs and the CLI."""
import threading

from . import render as renderer, youtube as youtube_mod

from . import channels, check as checks, media, models3d, review as reviews, script_gen, store
from . import cast as cast_mod, cuts as cuts_mod, shots as shots_mod
from .schema import new_project
from .store import project_dir

# Shared with timeline proxy jobs; never hold the project lock for snapshots/review.
PROXY_LOCKS = {}

class PayloadError(ValueError):
    """A creation validation error exposed as HTTP 400."""


def prepare_create(payload):
    script = (payload.get("script") or "").strip()
    idea = (payload.get("idea") or "").strip()
    if not script and len(idea) < 8:
        raise PayloadError("Describe the video idea, or paste a script.")
    if script and len(script.split()) < 120:
        raise PayloadError("That script is too short to build a video from.")

    channel = channels.load_or_none(payload.get("channel_id") or "")
    test = bool(payload.get("test")) and not script
    minutes = 1 if test else max(5, min(30, int(payload.get("target_minutes")
                                                or (channel.default_minutes if channel else 12))))
    tone = payload.get("tone") or (channel.tone if channel else "warm documentary")
    try:
        project = new_project(idea or script[:200], minutes, tone, channel=channel,
                              format_name=payload.get("format_name", ""),
                              delivery=payload.get("delivery", "voice_over"))
    except ValueError as exc:
        raise PayloadError(str(exc)) from exc
    if script:
        project.has_source = True
        project.fidelity = "adapted" if payload.get("fidelity") == "adapted" else "faithful"
    # The two look-and-feel choices worth making before a script exists rather
    # than after: how the pictures are staged, and how often they change. Both
    # already have defaults from the channel (or Style()'s own), so this only
    # overrides them when the creator actually touched the control.
    if not payload.get("format_name") and payload.get("format") in ("kenburns", "essay", "board", "stage", *cuts_mod.KEYS):
        project.style.format = payload["format"]
    if not payload.get("format_name") and payload.get("picture_every"):
        project.style.picture_every = max(1, min(8, int(payload["picture_every"])))
    if payload.get("research_mode") in ("quick", "deep"):
        project.research_mode = payload["research_mode"]
    if test:
        project.test, project.research_mode = True, "quick"
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

    return project, script

def initialize(pid, payload, progress):
    with store.lock_for(pid):
        p = store.load(pid)
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


def create(pid, payload, progress):
    project, _script = prepare_create(payload)
    initialize(project.id, payload, progress)
    return {"project": store.load(project.id).to_dict()}

def plan(pid, payload, progress):
    fresh = bool(payload.get("fresh"))
    with store.lock_for(pid):
        p = store.load(pid)
        # A previous run that died partway is picked up rather than repeated;
        # `fresh` throws that away and writes the script from the top.
        script_gen.generate(p, progress, lambda: store.save(p), fresh=fresh)
        store.save(p)
        # A 3D explainer's pictures come from its shots, except for the
        # paragraphs whose visual line is a photo.
        only = shots_mod.photo_leads(p) if p.style.format == "stage" else None
        if only is None or only:
            media.gather(p, progress, only=only)
            store.save(p)
    return {"slides": len(p.slides)}


def research(pid, payload, progress):
    from . import research as researcher
    project = store.load(pid)
    dossier = researcher.gather(project.idea, progress, mode=project.research_mode)
    with store.lock_for(pid):
        fresh = store.load(pid)
        fresh.research = dossier
        # A draft may already contain sections: keep its settled outline and words.
        if fresh.draft:
            fresh.draft["research"] = dossier
        store.save(fresh)
    return {"research": dossier}

def check(pid, payload, progress):
    return checks.run(store.load(pid), measure=True)

def snapshot(pid, payload, progress):
    with PROXY_LOCKS.setdefault(pid, threading.Lock()):
        project = store.load(pid)
        progress("Grabbing review frames from segment proxies")
        rows = reviews.snapshots(project)
        root = project_dir(pid)
        if payload.get("sheet", True):
            reviews.sheet([dict(row, path=root / row['path']) for row in rows],
                          root / 'review/sheet.png')
        progress(f"Review ready: {len(rows)} frames")
        return {"manifest": "review/snaps.json", "sheet": "review/sheet.png"}

def review(pid, payload, progress):
    with PROXY_LOCKS.setdefault(pid, threading.Lock()):
        return reviews.run(store.load(pid), progress, mode=payload.get('mode', 'targeted'))

def fix(pid, payload, progress):
    return reviews.act(pid, payload['note_id'], payload.get('action', 'fix'),
                       finding=payload.get('finding'))


def render_check(project, payload):
    result = checks.run(project, measure=True)
    if not result["ok"] and not payload.get("force"):
        return {"error": "Render blocked by P0 issues.", "check": result}


def render(pid, payload, progress):
    section = payload.get("section")
    p = store.load(pid)
    if section:
        if not any(s.id == section for s in p.slides):
            raise PayloadError("Paragraph not found")
    else:
        blocked = render_check(p, payload)
        if blocked:
            return blocked
    with store.lock_for(pid):
        p = store.load(pid)
        if section:
            result = renderer.preview_segment(p, section, progress)
        else:
            result = renderer.render(p, progress, preview=bool(payload.get("preview")))
            store.log(p, f"Rendered {result['output']}")
        store.save(p)
    return result


def prepare_publish(p, payload):
    if not p.channel_id:
        raise PayloadError("This video isn't on a channel — nowhere to upload it to.")
    if payload.get("channel_id") and payload["channel_id"] != p.channel_id:
        raise PayloadError("Requested channel does not match this video's channel.")
    if not youtube_mod.status(p.channel_id).get("connected"):
        raise PayloadError("This channel isn't connected to YouTube yet.")
    if not (p.render or {}).get("output"):
        raise PayloadError("Nothing rendered yet.")
    return p, dict(
        title=str(payload.get("title") or p.title or p.idea[:100]),
        description=str(payload.get("description") or youtube_mod.default_description(p)),
        tags=[str(t) for t in (payload.get("tags") or []) if str(t).strip()],
        category_id=str(payload.get("category_id") or "22"),
        privacy=payload.get("privacy") or "private")


def publish(pid, payload, progress, *, prepared=None):
    p, options = prepared if prepared is not None else prepare_publish(store.load(pid), payload)
    result = youtube_mod.upload_video(p, p.channel_id, **options, progress=progress)
    with store.lock_for(pid):
        fresh = store.load(pid)
        fresh.render["youtube_url"] = result["url"]
        store.save(fresh)
    return result
