"""The cast of a 3D explainer: the subjects its story needs, and the models
that play them.

The order a 3D explainer is made in (docs/3d-explainer.md, "Creating a
video"): story, then cast, then words. The outline is cheap and can change;
gathering and confirming models is slow and human; the script can only
describe what the models can show. So the creation job stops after the brief
— research, outline, and `propose()` here — and the script is written later,
from the same saved draft, with `digest()` telling the writer what each
model can do.

A cast entry is a *subject*, which a model may or may not play yet:

    {"id": "s1", "subject": "1903 Wright Flyer", "role": "hero",
     "why": "...", "chapters": [0, 2], "model": "m351ffe23" | "",
     "mode": "model" | "photos"}

`mode: photos` is the creator's word that this subject will be shown with
pictures and cards instead — no model was found, or none is wanted.
"""
from __future__ import annotations

import re
import uuid
from typing import Any, Callable

from . import models3d
from .llm import MODEL_UTILITY, complete_json
from .schema import Project

ROLES = ("hero", "comparison", "supporting", "cameo")

Progress = Callable[[str], None]


def _sid() -> str:
    return "s" + uuid.uuid4().hex[:6]


def model_name(m: dict) -> str:
    """What a library model is called: Claude's name if it has one."""
    return ((m.get("identity") or {}).get("name")) or m.get("title") or m.get("id", "")


def subjects(project: Project) -> list[dict]:
    """The cast as subjects. Entries from before subjects existed ({"model": id})
    become a subject named after their model."""
    out = []
    for c in project.cast or []:
        if not isinstance(c, dict):
            continue
        s = dict(c)
        if "subject" not in s:
            try:
                s["subject"] = model_name(models3d.get(s.get("model", "")))
            except models3d.ModelError:
                s["subject"] = "missing model"
        s.setdefault("id", _sid())
        s.setdefault("role", "supporting")
        s.setdefault("why", "")
        s.setdefault("chapters", [])
        s.setdefault("model", "")
        s.setdefault("mode", "model")
        out.append(s)
    return out


def clean_subject(s: dict, sections: int) -> dict | None:
    name = str(s.get("subject") or "").strip()[:80]
    if not name:
        return None
    chapters = [int(c) for c in (s.get("chapters") or []) if str(c).lstrip("-").isdigit()]
    return {
        "id": str(s.get("id") or _sid())[:12],
        "subject": name,
        "role": s.get("role") if s.get("role") in ROLES else "supporting",
        "why": str(s.get("why") or "")[:240],
        "chapters": sorted({c for c in chapters if 0 <= c < max(1, sections)})[:12],
        "model": str(s.get("model") or "")[:12],
        "mode": "photos" if s.get("mode") == "photos" else "model",
    }


PROPOSE = """\
A 3D explainer video is being planned: narration over 3D models of its
subjects, with photos and cards only where no model exists. Before the
script is written, list its CAST — every subject that deserves a 3D model.

IDEA: \"\"\"{idea}\"\"\"
TITLE: {title}
THESIS: {thesis}
CHAPTERS:
{chapters}
{given}
MODELS ALREADY IN THE CREATOR'S LIBRARY (id: name):
{library}

Rules:
- A subject is a physical thing that can be modelled and shot: a machine, a
  building, a vehicle, a place, a creature, an object. Not people, ideas or
  events (those are photos and cards).
- {size} subjects is right for this length; two make a comparison video, six
  to eight a history. Fewer, stronger subjects beat many cameos.
- role: "hero" (the video is about it), "comparison" (set against the hero),
  "supporting" (appears in a chapter or two), "cameo" (a moment).
- chapters: the numbers of the chapters it appears in.
- library: the id of a library model that IS this subject (the same machine
  or place, not merely similar), else null.
- Include the creator's chosen models in your list too, with their library id,
  so their chapters and role in the story are known.

Return {{"cast": [{{"subject": "...", "role": "...", "why": "one sentence",
"chapters": [0, 2], "library": "m1234abcd" | null}}, ...]}}"""


def propose(project: Project, progress: Progress = lambda m: None,
            source_text: str = "") -> list[dict]:
    """Ask Claude for the cast, matched against the model library. Subjects
    the creator already chose (models first) are kept, at the top."""
    outline = project.outline or (project.draft or {}).get("outline") or {}
    sections = outline.get("sections") or []
    library = models3d.all_models()
    lib_ids = {m["id"] for m in library}
    given = [s for s in subjects(project) if s.get("model")]
    chapter_lines = "\n".join(f"  {i}. {s.get('heading', '')}: {s.get('summary', '')}"[:220]
                              for i, s in enumerate(sections)) or "  (none yet)"
    if source_text and not sections:
        chapter_lines = "  (the creator wrote the script; here it is)\n" + source_text[:9000]
    progress("Proposing the cast")
    reply = complete_json(
        PROPOSE.format(
            idea=project.idea[:1500], title=outline.get("title") or project.title or project.idea[:80],
            thesis=outline.get("thesis") or "", chapters=chapter_lines,
            given=("THE CREATOR HAS ALREADY CHOSEN THESE MODELS — they are in the cast:\n"
                   + "\n".join(f"  {s['model']}: {s['subject']}" for s in given) + "\n") if given else "",
            library="\n".join(f"  {m['id']}: {model_name(m)}" for m in library[:60]) or "  (empty)",
            size=("One or two" if project.target_minutes < 3
                  else "Two to four" if project.target_minutes <= 8 else "Three to six")),
        model=MODEL_UTILITY, timeout=300,
        require=lambda v: isinstance(v, dict) and isinstance(v.get("cast"), list))
    out = list(given)
    taken = {s["model"] for s in given}
    for raw in reply["cast"][:10]:
        if not isinstance(raw, dict):
            continue
        lib = raw.get("library")
        mine = next((g for g in given if g["model"] == lib or _same(g["subject"], str(raw.get("subject") or ""))), None)
        if mine:
            # The creator's own pick: keep it, but take where it appears in the
            # story and why from Claude's answer.
            c = clean_subject({**raw, "model": mine["model"]}, len(sections))
            if c:
                mine["chapters"] = c["chapters"] or mine.get("chapters", [])
                if c["why"]:
                    mine["why"] = c["why"]
            continue
        if lib in taken:
            continue
        s = clean_subject({**raw, "model": lib if lib in lib_ids else ""}, len(sections))
        if s and not any(_same(s["subject"], g["subject"]) for g in out):
            out.append(s)
            if s["model"]:
                taken.add(s["model"])
    progress(f"Cast: {len(out)} subject(s), {sum(1 for s in out if s['model'])} already in the library")
    return out


def _same(a: str, b: str) -> bool:
    norm = lambda t: re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()
    return norm(a) == norm(b)


# --------------------------------------------------------------- for the writer
_LIMIT_WORDS = {
    "stand_inside": "shots stand inside it", "one_direction": "seen from one side only",
    "no_low_angles": "aerial views only", "edge": "keep its edges out of frame",
    "subject_is_a_part": "the subject is one part of a larger scene",
}


def digest(project: Project) -> str:
    """What each cast member can show, for the script writer: who plays it,
    its real size, the parts and regions a shot can aim at, its limits — and
    which subjects are photos only. Empty for any other format."""
    if project.style.format != "stage":
        return ""
    lines = []
    for s in subjects(project):
        head = f"- {s['subject']} ({s['role']})"
        if s["mode"] == "photos" or not s["model"]:
            lines.append(head + ": NO MODEL — show it with photos or cards only.")
            continue
        try:
            m = models3d.get(s["model"])
        except models3d.ModelError:
            lines.append(head + ": NO MODEL — show it with photos or cards only.")
            continue
        a = m.get("analysis") or {}
        kind = models3d.kind_of(m)
        bits = [f"a 3D {kind.replace('_', ' ')}"]
        if m.get("measured") and m.get("scale"):
            w, h, d = (v * m["scale"] for v in m["measured"])
            bits.append(f"about {max(w, d):.3g} m long, {h:.3g} m tall")
        shootable = _shootable(m)[:16]
        if shootable:
            bits.append("parts a shot can aim at: " + ", ".join(shootable))
        limits = [_LIMIT_WORDS[c] for c in (a.get("limits") or []) if c in _LIMIT_WORDS]
        if limits:
            bits.append("limits: " + "; ".join(limits))
        lines.append(head + ": " + "; ".join(bits) + ".")
    if not lines:
        return ""
    return ("CAST (the 3D models this video can show — write only what they can show):\n"
            + "\n".join(lines))


def _shootable(m: dict) -> list[str]:
    """The parts and regions of a model a shot can be aimed at, by name."""
    named = (m.get("identity") or {}).get("parts") or {}
    parts = list(named.values())
    # A part Claude has named goes by that name only, not its node's label too.
    parts += [p.get("label") for p in m.get("parts") or [] if p.get("label") and p.get("node") not in named]
    regions = [r.get("label") for r in m.get("regions") or [] if r.get("label")]
    return [x for x in dict.fromkeys(parts + regions) if x]


VISUAL_RULE = (
    'This is a 3D explainer. The "visual" says what the 3D stage shows, in one '
    'line: "3D: <cast subject> — <whole, or one of its listed parts> — <shot: '
    'slow orbit, close-up, reveal, push in, pull back, comparison>". Use only '
    'subjects and parts from the CAST list. For a beat no model can carry (a '
    'person, a document, a subject with NO MODEL), write "PHOTO: <the picture>".'
)


def visual_rule(project: Project) -> str:
    return VISUAL_RULE if project.style.format == "stage" else ""


def summary(project: Project) -> dict[str, Any]:
    """Counts for the Cast tab's progress line."""
    subs = subjects(project)
    ready = 0
    for s in subs:
        if s["mode"] == "photos":
            continue
        try:
            if s["model"] and models3d.get(s["model"]).get("confirmed"):
                ready += 1
        except models3d.ModelError:
            pass
    needing = [s["subject"] for s in subs if s["mode"] == "model" and not s["model"]]
    return {"subjects": len(subs), "ready": ready, "photos": sum(1 for s in subs if s["mode"] == "photos"),
            "needing": needing}


# ----------------------------------------------------- when the cast changes
# The script is written against the cast as it was. Swap a model, switch a
# subject to photos, rename a region, and some visual lines no longer describe
# anything the stage can show. This finds them without asking Claude: the
# lines follow VISUAL_RULE, so they can be read back.
_WHOLE = {"whole", "the whole", "whole aircraft", "whole model", "all", "full", "overall", "exterior"}


def _norm(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()


def _match(name: str, subs: list[dict]) -> dict | None:
    n = _norm(name)
    if not n:
        return None
    for s in subs:
        if _norm(s["subject"]) == n:
            return s
    for s in subs:                      # "Wright Flyer" for "1903 Wright Flyer"
        m = _norm(s["subject"])
        if re.search(rf"\b{re.escape(n)}\b", m) or re.search(rf"\b{re.escape(m)}\b", n):
            return s
    return None


def _split_visual(v: str) -> tuple[str, list[str]]:
    """("3d" | "photo" | "", fields) for one visual line."""
    m = re.match(r"\s*(3D|PHOTO)\s*:\s*(.*)", v or "", re.I | re.S)
    if not m:
        return "", []
    return m.group(1).lower(), [f.strip(" .") for f in re.split(r"\s+[—–]\s+|\s+-{1,2}\s+", m.group(2))]


def check_visuals(project: Project) -> dict[str, dict]:
    """{slide id: {"level": "warn" | "hint", "text": ...}} for every visual
    line the current cast cannot carry, or could now carry better."""
    if project.style.format != "stage" or not project.slides:
        return {}
    subs = subjects(project)
    models: dict[str, dict | None] = {}
    for s in subs:
        if s["model"] and s["mode"] == "model":
            try:
                models[s["id"]] = models3d.get(s["model"])
            except models3d.ModelError:
                models[s["id"]] = None
    out: dict[str, dict] = {}
    for sl in project.slides:
        kind, fields = _split_visual(sl.visual_note)
        if kind == "3d" and fields:
            names = [n for n in re.split(r"\s+(?:and|&|with|beside|vs\.?|versus)\s+|,\s*", fields[0]) if n.strip()]
            problems = []
            for n in names:
                s = _match(n, subs)
                if not s:
                    problems.append(f"{n.strip()} is not in the cast")
                elif s["id"] not in models:
                    problems.append(f"{s['subject']} has no model now")
                elif models[s["id"]] is None:
                    problems.append(f"{s['subject']}'s model is missing from the library")
            part = fields[1] if len(fields) > 1 else ""
            if not problems and len(names) == 1 and part and _norm(part) not in _WHOLE:
                s = _match(names[0], subs)
                have = [_norm(x) for x in _shootable(models[s["id"]] or {})]
                if have and not any(_norm(part) == h or _norm(part) in h or h in _norm(part) for h in have):
                    problems.append(f"{s['subject']} has no part called \"{part}\"")
            if problems:
                out[sl.id] = {"level": "warn", "text": "; ".join(problems)}
        elif kind == "photo" and fields:
            text = _norm(" ".join(fields))
            for s in subs:
                if s["id"] in models and models[s["id"]] and re.search(rf"\b{re.escape(_norm(s['subject']))}\b", text):
                    out[sl.id] = {"level": "hint", "text": f"{s['subject']} has a model now: this could be a 3D shot"}
                    break
    return out


REVISE = """\
The cast of this 3D explainer changed after its script was written, and some
paragraphs' visual lines no longer fit. Rewrite only those visual lines; the
narration stays exactly as it is.

{digest}

{rule}

PARAGRAPHS:
{rows}

Return {{"visuals": {{"<number>": "the new visual line", ...}}}} for every
numbered paragraph."""


def revise_visuals(project: Project, progress: Progress = lambda m: None,
                   only: list[str] | None = None) -> int:
    """Rewrite the visual lines `check_visuals` flags (or the slides in
    `only`) against the cast as it is now. Returns how many changed."""
    flags = check_visuals(project)
    ids = set(only) if only else set(flags)
    slides = [s for s in project.slides if s.id in ids]
    if not slides:
        return 0
    progress(f"Rewriting {len(slides)} visual line(s) for the new cast")
    rows = "\n".join(
        f'{n}. "{s.narration[:700]}"\n   was: {s.visual_note}\n   problem: {flags.get(s.id, {}).get("text", "the creator asked")}'
        for n, s in enumerate(slides, 1))
    reply = complete_json(REVISE.format(digest=digest(project), rule=VISUAL_RULE, rows=rows),
                          model=MODEL_UTILITY, timeout=300,
                          require=lambda v: isinstance(v, dict) and isinstance(v.get("visuals"), dict))
    changed = 0
    for n, s in enumerate(slides, 1):
        new = str(reply["visuals"].get(str(n)) or "").strip()
        if not new or new == s.visual_note:
            continue
        s.visual_note = new[:400]
        kind, fields = _split_visual(new)
        if kind == "photo" and fields:
            s.queries = [" ".join(fields)[:80]]     # something to search for until media is gathered
        changed += 1
    progress(f"{changed} visual line(s) rewritten")
    return changed
