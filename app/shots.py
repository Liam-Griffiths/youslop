"""The shot list of a 3D explainer: what the camera does under each paragraph
whose visual line is a 3D beat, and the clips the renderer cuts in.

A shot lives on its paragraph (the lead of its picture group), as
`Slide.shot`:

    {"intent": {"subjects": ["s1"], "part": "left wing", "move": "push",
                "framing": "tight", "side": "auto", "join": "cut", "why": ""},
     "by": "line" | "claude" | "hand",
     "solved": {"shot": {...}, "pick": {...}, "checks": {...}, "failed": [],
                "flagged": False, "flag": "", "look": "set", "scene": "m1+m2",
                "subject": "left wing", "secs": 8.4, "key": "…", "at": 0,
                "notes": [], "retried": False} | None,
     "locked": False}

The planner writes intent, never coordinates (docs/3d-explainer.md, step 7).
The solver in the browser (static/stage/plan.js, app/stage.py) turns intent
into a camera path and checks it; a shot that fails goes back to Claude once
with the reason, and if it still fails it is used and flagged for a human —
never dropped, never rendered silently bad. A shot set by hand on the Stage
tab is locked, so planning again never overwrites it.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
from pathlib import Path
from typing import Callable

from . import cast as cast_mod
from . import models3d
from . import stage as stage_mod
from .llm import MODEL_UTILITY, complete_json
from .schema import Project, Slide
from .store import project_dir

Progress = Callable[[str], None]

MOVES = ("static", "orbit", "push", "pull", "crane", "reveal", "pan", "turn")
FRAMINGS = ("wide", "medium", "tight")
SIDES = ("auto", "front", "three_quarter", "left", "right", "rear", "above", "low")
JOINS = ("cut", "match", "continuous", "dip")
SOLVE_VERSION = 1           # bump when plan.js changes what a solved shot means
RENDER_VERSION = 1          # bump when a clip drawn from the same shot would differ

# The moves each kind of model can make (plan.js shoots each its own way).
MOVES_FOR = {
    "object": MOVES,
    "interior": ("static", "turn", "orbit", "pan", "push", "pull", "crane"),
    "set": ("static", "push", "pull", "pan"),
    "aerial_site": ("static", "orbit", "push", "pull"),
    "modelled_site": ("static", "orbit", "push", "pull"),
}


# ------------------------------------------------------------- the paragraphs
def is_3d(slide: Slide) -> bool:
    kind, fields = cast_mod._split_visual(slide.visual_note)
    return kind == "3d" and bool(fields)


def groups(project: Project) -> list[list[tuple[Slide, float]]]:
    """The video's picture groups with their screen time (estimated where
    nothing is recorded), exactly as the preview cut times them."""
    from .render import _groups_for_preview
    return _groups_for_preview(project)


def leads(project: Project) -> list[tuple[int, Slide, float]]:
    """(group index, lead paragraph, seconds) for every group whose picture
    is a 3D shot, in the video's order."""
    out = []
    for i, g in enumerate(groups(project)):
        if g and is_3d(g[0][0]):
            out.append((i, g[0][0], round(sum(d for _s, d in g), 2)))
    return out


def photo_leads(project: Project) -> list[str]:
    """The paragraphs whose picture comes from Media: every lead that is not
    a 3D shot."""
    from .render import is_lead
    return [s.id for s in project.slides if is_lead(project, s) and not is_3d(s)]


# ---------------------------------------------------------------- the intent
_MOVE_WORDS = [
    ("turn", r"\b360\b|turn(s|ing)? (on the spot|around)|look(s|ing)? around"),
    ("reveal", r"reveal"),
    ("pull", r"pull(s|ing)? (back|out|away)|dolly out|zoom(s|ing)? out|widen"),
    ("push", r"push(es|ing)? in|dolly in|move(s)? in|zoom(s|ing)? in|close[- ]?up|closer|toward"),
    ("crane", r"crane|rise|rising|lift|boom"),
    ("pan", r"\bpan|glide|sweep|track(s|ing)? along|along the"),
    ("orbit", r"orbit|circle|circling|around|rotate|turntable"),
    ("static", r"static|still|hold|locked|fixed|establish|side[- ]by[- ]side|comparison|compare|lineup|line-up"),
]


def _parse_move(text: str) -> tuple[str, str, str]:
    """(move, framing, side) from a visual line's shot words."""
    t = text.lower()
    move = next((m for m, rx in _MOVE_WORDS if re.search(rx, t)), "orbit")
    framing = ("tight" if re.search(r"close|tight|detail|macro", t)
               else "wide" if re.search(r"wide|establish|whole|full|lineup|line-up|side[- ]by[- ]side|comparison|scale", t)
               else "medium")
    side = ("above" if re.search(r"above|overhead|aerial|top[- ]down|bird", t)
            else "low" if re.search(r"\blow\b|from below|ground level", t)
            else "rear" if re.search(r"behind|rear|from the back", t)
            else "front" if re.search(r"head[- ]on|from the front|front view", t)
            else "left" if re.search(r"left side|from the left|port side", t)
            else "right" if re.search(r"right side|from the right|starboard", t)
            else "auto")
    return move, framing, side


def _cast_models(project: Project) -> dict[str, dict]:
    """Cast subject id -> its library manifest, for subjects played by a model."""
    out = {}
    for s in cast_mod.subjects(project):
        if s["mode"] == "model" and s["model"]:
            try:
                out[s["id"]] = models3d.get(s["model"])
            except models3d.ModelError:
                continue
    return out


def intent_from_line(project: Project, slide: Slide) -> dict | None:
    """What the visual line asks for, read without Claude:
    "3D: <subject> — <part> — <shot>"."""
    kind, fields = cast_mod._split_visual(slide.visual_note)
    if kind != "3d" or not fields:
        return None
    subs = cast_mod.subjects(project)
    have = _cast_models(project)
    names = [n for n in re.split(r"\s+(?:and|&|with|beside|vs\.?|versus|next to|under|over)\s+|,\s*", fields[0]) if n.strip()]
    sids = []
    for n in names:
        s = cast_mod._match(n, subs)
        if s and s["id"] in have and s["id"] not in sids:
            sids.append(s["id"])
    if not sids:
        return None
    part = fields[1] if len(fields) > 1 else ""
    if cast_mod._norm(part) in cast_mod._WHOLE:
        part = ""
    move, framing, side = _parse_move(" ".join(fields[2:]) if len(fields) > 2 else " ".join(fields[1:]))
    return clean_intent({"subjects": sids, "part": part, "move": move, "framing": framing,
                         "side": side, "join": "cut"}, project)


def clean_intent(raw: dict, project: Project) -> dict | None:
    """An intent the solver can take: known subjects with models, a move the
    kind can make, several subjects only when every one is an object."""
    have = _cast_models(project)
    sids = [str(s) for s in (raw.get("subjects") or []) if str(s) in have]
    sids = list(dict.fromkeys(sids))[:4]
    if not sids:
        return None
    kinds = [models3d.kind_of(have[s]) for s in sids]
    if len(sids) > 1 and any(k != "object" for k in kinds):
        sids, kinds = sids[:1], kinds[:1]          # a room or a site is a scene alone
    kind = kinds[0] if len(sids) == 1 else "object"
    move = raw.get("move") if raw.get("move") in MOVES else "orbit"
    if move not in MOVES_FOR.get(kind, MOVES):
        move = {"turn": "pan", "orbit": "pan", "crane": "push", "reveal": "pull", "pan": "orbit"}.get(move, "static")
        if move not in MOVES_FOR.get(kind, MOVES):
            move = "static"
    return {
        "subjects": sids,
        "part": str(raw.get("part") or "").strip()[:60],
        "move": move,
        "framing": raw.get("framing") if raw.get("framing") in FRAMINGS else "medium",
        "side": raw.get("side") if raw.get("side") in SIDES else "auto",
        "join": raw.get("join") if raw.get("join") in JOINS else "cut",
        "why": str(raw.get("why") or "").strip()[:200],
    }


def avoid_jump_cuts(project: Project) -> int:
    """Two hard-cut shots in a row of the same subjects, asked from the same
    side at the same size, would jump in place. Move the second round by
    about a third of a turn before the solver sees it. Returns how many moved."""
    moved, last = 0, None
    turn = {"auto": "rear", "three_quarter": "left", "front": "three_quarter", "left": "three_quarter",
            "right": "three_quarter", "rear": "three_quarter", "above": "three_quarter", "low": "three_quarter"}
    for _i, s, _secs in leads(project):
        it = (s.shot or {}).get("intent")
        if not it:
            last = None
            continue
        if (last and it["join"] == "cut" and it["subjects"] == last["subjects"]
                and it["side"] == last["side"] and it["framing"] == last["framing"]
                and cast_mod._norm(it["part"]) == cast_mod._norm(last["part"])
                and not (s.shot or {}).get("locked")):
            it["side"] = turn.get(it["side"], "three_quarter") if it["side"] != "auto" else "left"
            moved += 1
        last = it
    return moved


PLAN = """\
You are the director of photography for a 3D explainer video: narration over
3D models. For each numbered paragraph below whose visual line is a 3D beat,
write the shot's INTENT. The camera system works out every position itself
and checks each shot; you never give coordinates.

{digest}

THE MODELS, by subject id (only these can be shot):
{models}

For each shot return:
- subjects: subject ids from the list above. Several only for a comparison
  of objects at true scale (they are lined up side by side). A room or a
  site is always alone.
- part: one of that subject's listed parts or regions, or "" for the whole.
- move: one of {moves}. Interiors: static, turn (a slow 360 from the middle),
  orbit (a quarter turn on the spot), pan, push, pull, crane. Sets: static,
  push, pull, pan. Sites: static, orbit, push, pull.
- framing: wide | medium | tight.
- side: auto | front | three_quarter | left | right | rear | above | low.
  "left" and "right" are the subject's own sides.
- join (into this shot from the one before): cut (the default), match (the
  same framing and move on a different subject, for comparisons),
  continuous (the camera carries on from where the last shot ended: same
  subjects only), dip (through black: a change of chapter or a jump in time).
- why: a few words on what the shot is for.

Rules:
- Simple and deliberate: one move per shot, no busy camera.
- Never two hard cuts in a row on the same subject from nearly the same
  side and size: change the side, the framing or the part.
- Vary the moves across the video; an orbit under every paragraph is dull.
- Respect each model's limits.

PARAGRAPHS:
{rows}

Return {{"shots": {{"<number>": {{"subjects": [...], "part": "", "move": "",
"framing": "", "side": "", "join": "", "why": ""}}, ...}}}}"""

RETRY = """\
Some shots in this 3D explainer failed the camera checks. For each, write a
new INTENT that avoids the reason it failed — another side, another
framing, a simpler move, or the whole subject instead of a part. Same
fields and rules as before:

subjects (ids) · part ("" for whole) · move ({moves}) · framing (wide |
medium | tight) · side (auto | front | three_quarter | left | right | rear |
above | low) · join (cut | match | continuous | dip) · why

What the checks mean: whole = the subject runs out of frame; visible = it is
hidden behind something; motion = the move bounces or turns too fast; edge
= the edge of a scanned tile shows; voids = holes in a set or room; level =
the camera tilts in a room; look_down = an aerial scan seen from too low;
detail = the texture is too soft that close; haze = the haze would swallow
the subject; clearance = the camera passes too near something; jump = a
jump cut from the shot before.

THE MODELS:
{models}

FAILED SHOTS:
{rows}

Return {{"shots": {{"<number>": {{...}}, ...}}}}"""


def _models_text(project: Project) -> str:
    lines = []
    for s in cast_mod.subjects(project):
        if s["mode"] != "model" or not s["model"]:
            continue
        try:
            m = models3d.get(s["model"])
        except models3d.ModelError:
            continue
        parts = cast_mod._shootable(m)[:20]
        lines.append(f"  {s['id']}: {s['subject']} — a {models3d.kind_of(m).replace('_', ' ')}"
                     + (f"; parts: {', '.join(parts)}" if parts else ""))
    return "\n".join(lines) or "  (none)"


def plan_intents(project: Project, progress: Progress = lambda m: None,
                 use_claude: bool = True) -> int:
    """Write the intent of every unlocked 3D shot. Claude directs; the
    visual line read back is the fallback, and the start. Returns how many
    shots have an intent."""
    rows, todo = [], []
    for n, (_i, s, secs) in enumerate(leads(project), 1):
        line = intent_from_line(project, s)
        sh = dict(s.shot or {})
        if sh.get("locked"):
            continue
        if line:
            sh["intent"], sh["by"] = line, "line"
        s.shot = sh
        todo.append((n, s))
        chapter = f" [opens chapter: {s.chapter}]" if s.chapter else ""
        rows.append(f'{n}. ({secs:.0f} s){chapter} "{s.narration[:500]}"\n   visual: {s.visual_note}')
    if use_claude and todo:
        progress(f"Directing {len(todo)} 3D shot(s)")
        try:
            reply = complete_json(
                PLAN.format(digest=cast_mod.digest(project), models=_models_text(project),
                            moves=", ".join(MOVES), rows="\n".join(rows)),
                model=MODEL_UTILITY, timeout=400,
                require=lambda v: isinstance(v, dict) and isinstance(v.get("shots"), dict))
            for n, s in todo:
                raw = reply["shots"].get(str(n))
                it = clean_intent(raw, project) if isinstance(raw, dict) else None
                if it:
                    s.shot = {**s.shot, "intent": it, "by": "claude"}
        except Exception as exc:          # noqa: BLE001 - the line's own reading still stands
            progress(f"Claude could not direct the shots ({exc}); using the visual lines as written")
    moved = avoid_jump_cuts(project)
    if moved:
        progress(f"{moved} shot(s) moved round to avoid a jump cut")
    return sum(1 for _i, s, _ in leads(project) if (s.shot or {}).get("intent"))


# ------------------------------------------------------------------ solving
def entries(project: Project, intent: dict) -> list[dict]:
    subs = {s["id"]: s for s in cast_mod.subjects(project)}
    return [{"sid": sid, "model": subs[sid]["model"]} for sid in intent["subjects"] if sid in subs]


def _model_sig(m: dict) -> dict:
    """What about a model changes a solved shot."""
    ident = m.get("identity") or {}
    return {"id": m["id"], "scale": m.get("scale"), "heading": m.get("heading"), "kind": models3d.kind_of(m),
            "regions": m.get("regions"), "parts": ident.get("parts"), "subject": ident.get("subject"),
            "analysed": (m.get("analysis") or {}).get("version")}


def solve_key(project: Project, intent: dict, secs: float) -> str:
    have = {s["id"]: s for s in cast_mod.subjects(project)}
    sigs = []
    for sid in intent.get("subjects") or []:
        try:
            sigs.append(_model_sig(models3d.get(have[sid]["model"])))
        except (KeyError, models3d.ModelError):
            sigs.append(None)
    # Length in steps of about 15%: a slightly longer take does not unsolve
    # a shot, a much longer one does (a move's turning speed depends on it).
    blob = json.dumps([SOLVE_VERSION, intent, sigs, round(math.log(max(1.0, secs)) / math.log(1.15))],
                      sort_keys=True, default=str)
    return hashlib.sha1(blob.encode()).hexdigest()[:16]


def thumbs_dir(project: Project) -> Path:
    return project_dir(project.id) / "stage" / "thumbs"


def status(project: Project) -> dict:
    """Per 3D paragraph: ok | flagged | stale | unsolved | no_model, with
    counts, for the Stage tab and the render's refusal."""
    rows, counts = {}, {"ok": 0, "flagged": 0, "stale": 0, "unsolved": 0, "no_model": 0}
    for _i, s, secs in leads(project):
        sh = s.shot or {}
        it, sol = sh.get("intent"), sh.get("solved")
        if not it:
            st = "no_model" if not intent_from_line(project, s) else "unsolved"
        elif not sol or not sol.get("shot"):
            st = "unsolved"
        elif not sh.get("locked") and sol.get("key") != solve_key(project, it, secs):
            st = "stale"
        else:
            st = "flagged" if sol.get("flagged") else "ok"
        rows[s.id] = {"state": st, "secs": secs}
        counts[st] += 1
    return {"shots": rows, "counts": counts, "total": len(rows)}


def solve(project: Project, progress: Progress = lambda m: None,
          only: list[str] | None = None, force: bool = False) -> dict[str, dict]:
    """Solve the 3D shots that need it — those with no solution, or one that
    no longer matches its intent, models or length; `only` limits it to
    those paragraphs, `force` solves them again regardless. Locked shots are
    never re-solved. Returns the page's results by paragraph."""
    seq = leads(project)
    want = set(only) if only is not None else None
    items, prev_of = [], {}
    models: dict[str, dict] = {}
    previous = None                  # (group index, slide) of the 3D lead before
    for i, s, secs in seq:
        sh = s.shot or {}
        it = sh.get("intent") or intent_from_line(project, s)
        if not it:
            previous = None
            continue
        adjacent = previous is not None and previous[0] == i - 1
        stale = not sh.get("solved") or sh["solved"].get("key") != solve_key(project, it, secs)
        pick = (want is None or s.id in want) and not sh.get("locked") and (force or stale or want is not None)
        if pick:
            ents = entries(project, it)
            for e in ents:
                models.setdefault(e["model"], models3d.get(e["model"]))
            item = {"id": s.id, "entries": ents, "intent": it, "secs": secs, "prev_id": None, "prev": None}
            if adjacent:
                p = previous[1]
                if any(x["id"] == p.id for x in items):
                    item["prev_id"] = p.id
                elif (p.shot or {}).get("solved", {}).get("shot"):
                    ps = p.shot["solved"]
                    item["prev"] = {"shot": ps["shot"], "k": ps.get("pick"), "scene": ps.get("scene")}
            items.append(item)
            prev_of[s.id] = item
            s.shot = {**sh, "intent": it, "by": sh.get("by") or "line"}
        previous = (i, s)
    if not items:
        progress("Every 3D shot is already solved")
        return {}
    ok, why = stage_mod.available()
    if not ok:
        raise stage_mod.StageError(why)
    progress(f"Solving {len(items)} 3D shot(s)")
    results = stage_mod.solve(items, models, progress, thumbs_dir=thumbs_dir(project))
    by_id = {s.id: (s, secs) for _i, s, secs in seq}
    now = time.time()
    for sid, r in results.items():
        s, secs = by_id[sid]
        it = s.shot["intent"]
        if r.get("error"):
            s.shot = {**s.shot, "solved": {"error": r["error"], "key": solve_key(project, it, secs), "at": now,
                                           "notes": r.get("notes") or []}}
            continue
        s.shot = {**s.shot, "solved": {
            "shot": r["shot"], "pick": r.get("pick"), "checks": r.get("checks"), "failed": r.get("failed") or [],
            "flagged": bool(r.get("flagged")), "flag": r.get("flag") or "", "look": r.get("look") or "set",
            "scene": r.get("scene"), "kind": r.get("kind"), "subject": r.get("subject"), "notes": r.get("notes") or [],
            "tried": r.get("tried"), "of": r.get("of"), "ms": r.get("ms"), "score": r.get("score"), "secs": secs,
            "key": solve_key(project, it, secs), "at": now, "thumbs_at": now,
        }}
    return results


def plan(project: Project, progress: Progress = lambda m: None, save: Callable[[], None] = lambda: None,
         use_claude: bool = True) -> dict:
    """The shot planner: intent for every 3D paragraph, solved and checked;
    shots that fail go back to Claude once with the reason, then are solved
    again, and whatever still fails is flagged for a human."""
    n = plan_intents(project, progress, use_claude)
    save()
    if not n:
        return {"shots": 0}
    solve(project, progress, force=True)
    save()
    failed = [(k, s) for k, (_i, s, _secs) in enumerate(leads(project), 1)
              if ((s.shot or {}).get("solved") or {}).get("flagged") and not s.shot.get("locked")
              and not s.shot["solved"].get("retried")]
    if failed and use_claude:
        progress(f"{len(failed)} shot(s) failed their checks; asking Claude for another way to shoot them")
        rows = []
        for k, s in failed:
            sol = s.shot["solved"]
            rows.append(f'{k}. "{s.narration[:300]}"\n   visual: {s.visual_note}\n'
                        f'   tried: {json.dumps(s.shot["intent"])}\n   failed: {", ".join(sol.get("failed") or [])} '
                        f'{json.dumps({c: sol["checks"].get(c) for c in sol.get("failed") or [] if sol.get("checks")})}')
        try:
            reply = complete_json(RETRY.format(models=_models_text(project), moves=", ".join(MOVES), rows="\n".join(rows)),
                                  model=MODEL_UTILITY, timeout=300,
                                  require=lambda v: isinstance(v, dict) and isinstance(v.get("shots"), dict))
            again = []
            for k, s in failed:
                raw = reply["shots"].get(str(k))
                it = clean_intent(raw, project) if isinstance(raw, dict) else None
                if it and it != s.shot["intent"]:
                    first = {"intent": s.shot["intent"], "solved": s.shot["solved"], "by": s.shot.get("by")}
                    s.shot = {**s.shot, "intent": it, "by": "claude", "first_try": first}
                    again.append(s.id)
            if again:
                solve(project, progress, only=again, force=True)
                for _k, s in failed:
                    if s.id in again and s.shot.get("solved"):
                        s.shot["solved"]["retried"] = True
                        # Keep the better of the two tries, with the intent it came from.
                        first = s.shot.get("first_try") or {}
                        was = first.get("solved") or {}
                        if (was.get("shot") and s.shot["solved"].get("flagged")
                                and was.get("score", 1e9) < s.shot["solved"].get("score", 1e9)):
                            s.shot = {**s.shot, "intent": first["intent"], "by": first.get("by"),
                                      "solved": {**was, "retried": True}}
                    s.shot.pop("first_try", None)
                save()
        except Exception as exc:          # noqa: BLE001 - the flagged shots stand, flagged
            progress(f"Claude could not re-plan the failed shots ({exc}); they stay flagged")
    st = status(project)
    progress(f"Shots: {st['counts']['ok']} ok, {st['counts']['flagged']} flagged for a look")
    return {"shots": st["total"], **st["counts"]}


def set_by_hand(project: Project, slide: Slide, shot: dict, checks: dict | None, secs: float) -> None:
    """A shot set from the view on the Stage tab: kept exactly, and locked."""
    sh = dict(slide.shot or {})
    it = sh.get("intent") or intent_from_line(project, slide) or {}
    failed = [k for k, v in (checks or {}).items() if isinstance(v, dict) and v.get("ok") is False]
    prior = sh.get("solved") or {}
    sh["solved"] = {**prior, "shot": shot, "checks": checks or {}, "failed": failed, "flagged": bool(failed),
                    "flag": ("set by hand; fails " + ", ".join(failed)) if failed else "",
                    "secs": secs, "key": solve_key(project, it, secs) if it else "", "at": time.time(), "by_hand": True}
    sh["intent"], sh["locked"], sh["by"] = it, True, "hand"
    slide.shot = sh


# ------------------------------------------------------------------ clips
def clips_dir(project: Project) -> Path:
    return project_dir(project.id) / "stage" / "clips"


def _render_item(project: Project, slide: Slide, seg_len: float, size: tuple[int, int], fps: int) -> dict | None:
    sol = (slide.shot or {}).get("solved") or {}
    it = (slide.shot or {}).get("intent")
    if not sol.get("shot") or not it:
        return None
    ents = entries(project, it)
    sigs = []
    for e in ents:
        m = models3d.get(e["model"])
        sigs.append([m["id"], m.get("scale"), m.get("heading"), m.get("tint"), m.get("bytes")])
    frames = max(2, int(round(seg_len * fps)))
    haze = (sol.get("checks") or {}).get("haze")
    spec = {"entries": ents, "shot": sol["shot"], "intent": it, "look": sol.get("look") or "set",
            "haze": haze if isinstance(haze, dict) and haze.get("far") else None,
            "W": size[0], "H": size[1], "fps": fps, "frames": frames}
    key = hashlib.sha1(json.dumps([RENDER_VERSION, spec, sigs], sort_keys=True, default=str).encode()).hexdigest()[:16]
    return {**spec, "clip": f"{slide.id}_{key}"}


def clip_path(project: Project, slide: Slide, seg_len: float, size: tuple[int, int], fps: int) -> Path | None:
    item = _render_item(project, slide, seg_len, size, fps)
    return clips_dir(project) / f"{item['clip']}.mp4" if item else None


def missing_shots(project: Project, grps: list[list[tuple[Slide, float]]]) -> list[Slide]:
    """3D paragraphs in these groups with no solved shot to draw."""
    out = []
    for g in grps:
        s = g[0][0]
        if is_3d(s) and not ((s.shot or {}).get("solved") or {}).get("shot"):
            out.append(s)
    return out


def ensure_clips(project: Project, wanted: list[tuple[Slide, float]], size: tuple[int, int], fps: int,
                 progress: Progress = lambda m: None) -> dict[str, Path]:
    """The clip for each (lead paragraph, segment length), drawing the ones
    not already on disk in one browser run. Returns them by paragraph id;
    a paragraph with no solved shot is left out."""
    items, out = [], {}
    models: dict[str, dict] = {}
    for s, seg_len in wanted:
        item = _render_item(project, s, seg_len, size, fps)
        if not item:
            continue
        path = clips_dir(project) / f"{item['clip']}.mp4"
        out[s.id] = path
        if path.exists() and path.stat().st_size > 0:
            continue
        for e in item["entries"]:
            models.setdefault(e["model"], models3d.get(e["model"]))
        items.append(item)
    if items:
        made = stage_mod.render(items, models, clips_dir(project), progress)
        if len(made) < len(items):
            raise stage_mod.StageError("Some 3D shots did not render.")
    _sweep(project, {p.name for p in out.values()})
    return out


def _sweep(project: Project, keep: set[str], max_files: int = 400) -> None:
    """Old clips go once there are many: every change of shot or length
    leaves one behind."""
    d = clips_dir(project)
    files = sorted(d.glob("*.mp4"), key=lambda p: p.stat().st_mtime) if d.is_dir() else []
    for p in files[:max(0, len(files) - max_files)]:
        if p.name not in keep:
            p.unlink(missing_ok=True)
