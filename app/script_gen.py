"""Idea -> outline -> narrated script -> per-slide visual plan."""
from __future__ import annotations

import copy
import concurrent.futures as cf
import hashlib
import re
import threading
from typing import Any, Callable

from . import research as script_research
from .config import WORDS_PER_MINUTE
from .llm import LLMError, MODEL_SCRIPT, MODEL_UTILITY, complete_json
from .schema import Project, Slide

Progress = Callable[[str], None]


NARRATOR_SYSTEM = """You write narration for long-form informational YouTube videos \
of the kind a single host reads over archival photographs: measured, specific, and \
genuinely curious. You are a researcher first and a stylist second.

Hard rules for every line you write:
- Write for the ear. Short declarative sentences. One idea per sentence.
- Concrete over abstract: names, dates, places, numbers, physical detail.
- No YouTube filler. Never write "buckle up", "little did they know", "what \
happened next will", "in this video", "let's dive in", "stay tuned", "like and \
subscribe", or rhetorical questions used as transitions.
- No em-dashes. Use full stops.
- Never invent facts, quotes, dates or statistics. Where a RESEARCHED FACTS \
block is given, every specific claim must trace back to something in it — \
treat it as what you are allowed to say, not a suggestion. A specific detail \
with nothing there to support it gets hedged or cut, not invented. Where no \
RESEARCHED FACTS block is given, apply the same discipline to what you \
already know: if you are not confident a detail is true, write around it or \
characterise the uncertainty honestly ("accounts differ", "the record is \
thin here").
- Do not address the audience as "guys" or "folks". Address them as adults.

You reply with one raw JSON value and nothing else."""


def _facts_block(research: dict) -> str:
    """The research dossier, formatted for a prompt. "" if there is none.

    Every writing prompt gets the whole dossier rather than a slice per
    section: an 8-22 minute video's worth of facts is a page or two, cheap to
    hand over in full, and a section written in isolation from the others
    should still be able to lean on a fact a different beat found.
    """
    facts = (research or {}).get("facts") or []
    if not facts:
        return ""
    lines = [
        f'- {f.get("claim", "")}'
        + (f' ({f.get("date")})' if f.get("date") else "")
        + f' — {f.get("source", "unknown source")}'
        + f' [{f.get("confidence", "medium")} confidence]'
        for f in facts if f.get("claim")
    ]
    block = "RESEARCHED FACTS (ground every specific claim in these):\n" + "\n".join(lines)
    corrections = research.get("corrections") or []
    if corrections:
        block += ("\n\nThe research also found the creator's own idea states "
                 "something that does not hold up — do not repeat it:\n"
                 + "\n".join(f"- {c}" for c in corrections))
    open_qs = research.get("open_questions") or []
    if open_qs:
        block += ("\n\nLeft unclear by research (fine to acknowledge as "
                 "uncertain; do not resolve it with a guess):\n"
                 + "\n".join(f"- {q}" for q in open_qs))
    return block


# --------------------------------------------------------------------- outline
def build_outline(project: Project, progress: Progress = lambda m: None) -> dict:
    total_words = int(project.target_minutes * WORDS_PER_MINUTE)
    intro_words = int(total_words * 0.11)
    concl_words = int(total_words * 0.09)
    main_words = total_words - intro_words - concl_words
    n_beats = max(4, min(11, round(main_words / 235)))

    progress(f"Outlining ~{total_words} words across {n_beats} main beats")

    facts = _facts_block(project.research)
    facts_section = f"{facts}\n\n" if facts else ""
    prompt = f"""Plan an informational YouTube video.

IDEA FROM THE CREATOR:
\"\"\"{project.idea}\"\"\"

{facts_section}Target runtime: {project.target_minutes} minutes, which is about {total_words} \
spoken words at {WORDS_PER_MINUTE} wpm.
Tone: {project.tone}.

First work out what this story actually is: who or what it is about, the span of \
time it covers, and the single tension or question that makes it worth {project.target_minutes} \
minutes of someone's attention. Then structure it.

Return JSON with exactly this shape:
{{
  "title": "the video title, 4-9 words, specific, no clickbait, no colon-subtitle",
  "subtitle": "one clause of context, max 8 words",
  "subject": "the person, event or thing at the centre, named plainly",
  "era": "the time span covered, e.g. '1887-1961'",
  "thesis": "one sentence: the argument or question the video answers",
  "visual_world": "one sentence describing what archival material exists for this \
subject and what the video will therefore look like on screen",
  "sections": [
    {{"kind": "intro", "heading": "short beat name", "summary": "2-3 sentences on \
what this beat covers and why it opens the video", "words": {intro_words}}},
    {{"kind": "main", "heading": "...", "summary": "...", "words": <int>}},
    {{"kind": "conclusion", "heading": "...", "summary": "...", "words": {concl_words}}}
  ]
}}

Rules:
- Exactly one intro section, exactly {n_beats} main sections, exactly one conclusion, in that order.
- The main sections must move chronologically or causally, never repeat each other, \
and together spend about {main_words} words. Give each a "words" budget summing to \
roughly that.
- Headings are for the creator's outline AND may be reused as on-screen chapter \
titles, so keep them 2-5 words, evocative but honest.
- The intro must open on a concrete scene or fact, not a definition or a greeting.
{"- Structure the sections around what RESEARCHED FACTS actually established, not the shape a generic version of this story would take. Where it flags an open question or a correction, the outline should reflect that rather than smooth over it." if facts else ""}"""

    outline = complete_json(
        prompt, system=NARRATOR_SYSTEM, model=MODEL_SCRIPT, timeout=900,
        require=lambda v: bool(_find_sections(v)),
        require_hint="The object must have a top-level \"sections\" array.",
    )
    return _normalise_outline(outline, project, n_beats, intro_words, concl_words)


def find_records(value: Any, key: str, depth: int = 0) -> list[dict]:
    """Find the list of dicts carrying `key`, wherever the model buried it.

    Every structured call in this module wants a list of records. Models mostly
    return it bare, but sometimes wrap it ({"paragraphs": [...]}) or nest it a
    level deeper. Digging costs nothing; a failed call costs a minute.
    """
    if depth > 4:
        return []
    if isinstance(value, list):
        got = [r for r in value if isinstance(r, dict) and r.get(key) not in (None, "")]
        if got:
            return got
        # A list of wrappers: gather across all of them, not just the first,
        # or a whole section comes back one paragraph long.
        gathered: list[dict] = []
        for item in value:
            gathered.extend(find_records(item, key, depth + 1))
        return gathered
    if isinstance(value, dict):
        if value.get(key) not in (None, ""):     # a single bare record
            return [value]
        for inner in value.values():
            found = find_records(inner, key, depth + 1)
            if found:
                return found
    return []


# Keys a model reaches for when it does not use "sections".
_SECTION_KEYS = ("sections", "beats", "structure", "segments", "chapters",
                 "parts", "outline", "plan")


def _find_sections(value: Any) -> list[dict]:
    """Dig the section list out of whatever shape came back.

    Models occasionally wrap the payload ({"outline": {...}}) or rename the array.
    Failing the whole job over that wasted a two-minute call, so we look.
    """
    if isinstance(value, list):
        return [s for s in value if isinstance(s, dict) and s.get("heading")]
    if not isinstance(value, dict):
        return []
    for key in _SECTION_KEYS:
        got = value.get(key)
        if isinstance(got, list):
            found = [s for s in got if isinstance(s, dict) and s.get("heading")]
            if found:
                return found
    # A single wrapper key around the real object.
    for got in value.values():
        if isinstance(got, (dict, list)):
            found = _find_sections(got)
            if found:
                return found
    return []


def _normalise_outline(raw: Any, project: Project, n_beats: int,
                       intro_words: int, concl_words: int) -> dict:
    """Coerce a plausible reply into the outline shape the writer expects."""
    sections = _find_sections(raw)
    if not sections:
        raise ValueError("The outline came back with no sections in it")

    # Metadata may sit beside the sections, one level up, or not at all.
    meta: dict = {}
    def harvest(v: Any) -> None:
        if isinstance(v, dict):
            for k in ("title", "subtitle", "subject", "era", "thesis", "visual_world"):
                if isinstance(v.get(k), str) and k not in meta:
                    meta[k] = v[k]
            for inner in v.values():
                if isinstance(inner, dict):
                    harvest(inner)
    harvest(raw)

    clean: list[dict] = []
    for i, s in enumerate(sections):
        kind = str(s.get("kind") or "").lower()
        if kind not in ("intro", "main", "conclusion"):
            kind = ("intro" if i == 0 else
                    "conclusion" if i == len(sections) - 1 else "main")
        try:
            words = int(s.get("words") or 0)
        except (TypeError, ValueError):
            words = 0
        if words <= 0:
            words = (intro_words if kind == "intro" else
                     concl_words if kind == "conclusion" else
                     max(120, int(project.target_minutes * WORDS_PER_MINUTE * 0.8
                                  / max(1, n_beats))))
        clean.append({
            "kind": kind,
            "heading": str(s.get("heading") or f"Part {i + 1}")[:60],
            "summary": str(s.get("summary") or s.get("description") or "")[:900],
            "words": words,
        })

    return {
        "title": meta.get("title") or project.idea[:60],
        "subtitle": meta.get("subtitle", ""),
        "subject": meta.get("subject") or project.idea[:80],
        "era": meta.get("era", ""),
        "thesis": meta.get("thesis", ""),
        "visual_world": meta.get("visual_world", ""),
        "sections": clean,
    }


# ---------------------------------------------------------------------- script
def _write_section(project: Project, outline: dict, idx: int) -> list[dict]:
    sections = outline["sections"]
    sec = sections[idx]
    words = int(sec.get("words") or 220)
    # ~55 words per paragraph keeps each recorded take to a comfortable breath.
    n_paras = max(2, round(words / 55))

    before = " | ".join(s.get("heading", "") for s in sections[:idx]) or "(this opens the video)"
    after = " | ".join(s.get("heading", "") for s in sections[idx + 1 :]) or "(this ends the video)"

    kind_note = {
        "intro": "This is the opening. Land the viewer inside a specific moment in the "
                 "first two sentences, then widen out to what the video will explore. "
                 "Do not summarise the whole story.",
        "main": "This is a middle beat. Assume the viewer has the earlier beats. Do not "
                "re-introduce the subject or recap.",
        "conclusion": "This is the close. Resolve the thesis, state what the subject left "
                      "behind, and end on a concrete image or fact rather than a moral.",
    }[sec.get("kind", "main")]

    facts = _facts_block(project.research)
    facts_section = f"\n{facts}\n" if facts else ""
    prompt = f"""Write the narration for one section of a video.

VIDEO: {outline.get('title')}
SUBJECT: {outline.get('subject')} ({outline.get('era')})
THESIS: {outline.get('thesis')}
CREATOR'S ORIGINAL IDEA: \"\"\"{project.idea}\"\"\"
{facts_section}
SECTIONS BEFORE THIS ONE: {before}
>>> WRITING NOW: "{sec.get('heading')}" - {sec.get('summary')}
SECTIONS AFTER THIS ONE: {after}

{kind_note}

Budget: about {words} words, split into {n_paras} paragraphs.

Return JSON: a list of {n_paras} objects, each:
{{"text": "the paragraph, 40-75 words, spoken aloud verbatim",
  "visual": "one plain-English sentence describing the single image or clip that \
should be on screen while this paragraph is read"}}

Rules:
- Each paragraph is one continuous spoken thought the narrator reads in one take.
- Paragraphs must flow into each other as continuous prose. Do not start every \
paragraph with the subject's name.
- The "visual" must be something that plausibly exists as a photograph, painting, \
map, document or stock clip. Prefer specific archival material ("Chandrasekhar as a \
student at Trinity College, 1930s") over abstractions ("a symbol of ambition").
- Write only spoken words in "text". No stage directions, no headings, no markdown."""

    reply = complete_json(
        prompt, system=NARRATOR_SYSTEM, model=MODEL_SCRIPT, timeout=900,
        require=lambda v: bool(find_records(v, "text")),
        require_hint='Each item needs a "text" field holding the spoken words.',
    )
    out = []
    for p in find_records(reply, "text"):
        text = str(p.get("text") or "").strip()
        if text:
            out.append({"text": text, "visual": str(p.get("visual") or "").strip(),
                        "kind": sec.get("kind", "main"), "beat": sec.get("heading", "")})
    return out


def draft_key(project: Project) -> str:
    """What a saved draft was written against. Changing any of it invalidates it."""
    seed = f"{project.idea}|{project.target_minutes}|{project.tone}"
    return hashlib.md5(seed.encode("utf-8")).hexdigest()[:12]


def write_script(project: Project, outline: dict, progress: Progress = lambda m: None,
                 checkpoint: Callable[[], None] = lambda: None) -> list[Slide]:
    """Write every section. Sections are independent, so they run in parallel.

    Each finished section is banked on the project before the next one is waited
    on, and a section that fails does not discard the ones that succeeded
    alongside it. A run that dies halfway can then be re-run for the half it is
    missing rather than from the top.
    """
    sections = outline["sections"]
    banked: dict[int, list[dict]] = {
        int(k): v for k, v in (project.draft.get("sections") or {}).items()
        if str(k).isdigit() and int(k) < len(sections)
    }
    todo = [i for i in range(len(sections)) if i not in banked]
    if banked:
        progress(f"Resuming: {len(banked)} of {len(sections)} sections already written")
    if not todo:
        progress("Every section was already written")
    else:
        progress(f"Writing {len(todo)} section{'s' if len(todo) != 1 else ''}"
                 + (f" of {len(sections)}" if banked else ""))

    results = dict(banked)
    guard = threading.Lock()
    failure: BaseException | None = None
    with cf.ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(_write_section, project, outline, i): i for i in todo}
        done = len(banked)
        for fut in cf.as_completed(futures):
            i = futures[fut]
            try:
                paragraphs = fut.result()
            except BaseException as exc:      # noqa: BLE001 - re-raised below
                # Keep going: the other sections in flight are still worth
                # banking, and one of them failing does not spoil them.
                failure = failure or exc
                progress(f"Section “{sections[i].get('heading')}” failed: {str(exc)[:120]}")
                continue
            results[i] = paragraphs
            done += 1
            with guard:
                project.draft.setdefault("sections", {})[str(i)] = paragraphs
                checkpoint()
            progress(f"Section {done}/{len(sections)} written "
                     f"({sections[i].get('heading')})")
    if failure is not None:
        raise failure

    slides: list[Slide] = []
    for i in range(len(sections)):
        for para in results.get(i, []):
            slides.append(
                Slide(
                    section=para["kind"],
                    beat=para["beat"],
                    narration=para["text"],
                    visual_note=para["visual"],
                    queries=[],
                    prefer_kind="image",
                    title="",
                )
            )
    return slides


# ------------------------------------------------------------- visual planning
# The writer reasons in scope words, not raw tile-zoom integers — it has no
# real feel for what "14" means, but "a specific building" vs "a whole
# country" is something it can judge from the narration. These map straight
# onto Slide.map_zoom, same convention the click-to-locate picker's zoom
# slider (the widget itself, there) already writes into that field.
_MAP_SCOPE_ZOOM = {"close": 16, "regional": 11, "wide": 6}


def plan_visuals(project: Project, slides: list[Slide], progress: Progress = lambda m: None) -> None:
    """Fill in search queries, media kind and on-screen titles, in place."""
    if not slides:
        return
    outline = project.outline
    chunks = [slides[i : i + 12] for i in range(0, len(slides), 12)]
    progress(f"Planning visuals for {len(slides)} slides")

    def run(args: tuple[int, list[Slide]]) -> tuple[int, list[dict]]:
        ci, chunk = args
        listing = "\n".join(
            f'{n}. [{s.section}/{s.beat}] "{s.narration}"'
            + (f"\n   creator note: {s.visual_note}" if s.visual_note else "")
            for n, s in enumerate(chunk, 1)
        )
        prompt = f"""For each narration paragraph below, plan the visual.

VIDEO: {outline.get('title')} - {outline.get('thesis', '')}
SUBJECT: {outline.get('subject')} ({outline.get('era', '')})
AVAILABLE VISUAL WORLD: {outline.get('visual_world', '')}

PARAGRAPHS:
{listing}

Return a JSON list of {len(chunk)} objects in the same order:
{{"n": <the number>,
  "queries": ["2 to 3 stock/archive search queries, most specific first"],
  "kind": "image", "video" or "map",
  "place": "" unless kind is \"map\", then the place name to show, as you would type it into a map search",
  "map_style": "" unless kind is \"map\", then one of "still", "establishing", "reveal", "pan",
  "map_type": "" unless kind is \"map\", then one of "satellite", "hybrid", "terrain", "street",
  "map_scope": "" unless kind is \"map\", then one of "close", "regional", "wide",
  "title": "" or a 1-4 word on-screen chapter title}}

Query rules:
- These queries hit Wikimedia Commons, open museum archives and stock libraries. \
Write them the way a picture researcher would: proper nouns, places, years, object \
names. "Ernest Shackleton Endurance 1915" not "polar exploration hardship".
- The first query should be the most specific thing that could plausibly have a \
photograph. Later queries should widen out as fallbacks (a place, an era, an object).
- No quotes, no boolean operators, 2-6 words each.
- Fill "queries" even when "kind" is "map" — a real photo is still allowed to win \
the slot if one turns out to exist.

Kind rules:
- "image" for anything historical, archival or specific to a named person or event.
- "video" only where generic modern motion genuinely helps: landscapes, weather, \
cityscapes, machinery, nature, abstract textures.
- "map" only when the paragraph is fundamentally about geography rather than a \
documentable subject — a route between places, a border, a distance, how isolated \
somewhere is, where one place sits relative to another. Use it sparingly and only \
where a photograph genuinely could not show what the sentence is about; most \
paragraphs, even ones that name a place, still want "image".

Map rules (only when kind is "map"):
- place: always disambiguate. The geocoder that resolves this is a single \
best-guess text match with no other context — "Alexandria" alone resolves to a \
small town in Italy, not Egypt; "Santiago" alone resolves to Costa Rica, not \
Chile. Always write it as "specific place, country" (or ", region, country" for \
anywhere less famous than a capital) using the SUBJECT/era above to supply the \
country — never a bare town, site or landmark name on its own.
- map_style: "still" for a plain establishing beat that just needs orientation; \
"establishing" for a location the narration is building toward or dwelling on — a \
smooth push in toward the site; "reveal" when the point is that somewhere small sits \
inside something much bigger (a pull back from the site to its wider context — good \
for "isolated", "remote", "a single X in all of Y"); "pan" for a lighter beat that \
doesn't carry that much weight.
- map_type: "satellite" as the default for real imagery; "hybrid" (satellite with \
place names/borders) when the paragraph itself is naming the surrounding places or a \
border; "terrain" when the narration is about physical geography — mountains, \
isolation, terrain difficulty, a natural barrier; "street" only for dense city detail \
at a very close scope.
- map_scope: "close" for a specific site, building or short stretch of coastline; \
"regional" for a city, small country or named area (the usual choice); "wide" for a \
whole country, a sea crossing, or a "how isolated is this" beat.

Title rules:
- Titles appear in the lower left as a chapter marker. Use them sparingly: only on \
the FIRST paragraph of a new beat, or at a hard turn in the story. At most {max(1, len(chunk) // 4)} \
of these {len(chunk)} paragraphs should get one. Everything else gets "".
- A title is a label, not a sentence. No end punctuation."""
        return ci, complete_json(
            prompt, model=MODEL_UTILITY, timeout=600,
            require=lambda v: bool(find_records(v, "queries")),
            require_hint='Each item needs "n" and a "queries" array.')

    with cf.ThreadPoolExecutor(max_workers=4) as pool:
        for ci, plan in pool.map(run, list(enumerate(chunks))):
            chunk = chunks[ci]
            records = find_records(plan, "queries")
            by_n = {}
            for pos, item in enumerate(records, 1):
                try:
                    n = int(item.get("n", pos))
                except (TypeError, ValueError):
                    n = pos
                by_n[n] = item
            for n, slide in enumerate(chunk, 1):
                item = by_n.get(n, {})
                queries = [q for q in (item.get("queries") or []) if isinstance(q, str) and q.strip()]
                slide.queries = queries[:3] or [outline.get("subject", project.idea)[:60]]
                kind = item.get("kind")
                place = (item.get("place") or "").strip()[:80]
                if kind == "map" and place:
                    slide.prefer_kind = "map"
                    slide.map_place = place
                    style = item.get("map_style")
                    slide.map_style = style if style in ("still", "establishing", "reveal", "pan") else "still"
                    map_type = item.get("map_type")
                    slide.map_kind = map_type if map_type in ("satellite", "hybrid", "terrain", "street") else "satellite"
                    scope = item.get("map_scope")
                    slide.map_zoom = _MAP_SCOPE_ZOOM.get(scope, _MAP_SCOPE_ZOOM["regional"])
                else:
                    slide.prefer_kind = "video" if kind == "video" else "image"
                title = (item.get("title") or "").strip().strip(".")
                slide.title = title if 0 < len(title) <= 40 else ""
            progress(f"Visuals planned for chunk {ci + 1}/{len(chunks)}")


# --------------------------------------------------------------- the board
def plan_boards(project: Project, slides: list[Slide],
                progress: Progress = lambda m: None) -> None:
    """Write what the handwritten format puts on screen, in place.

    Only run for a video in board format, and only ever *additive*: a slide
    whose board somebody has already written by hand is left alone, and a
    slide this pass skips still gets a board, because `board.content` derives
    one from the narration. See app/board.py and app/diagram.py.
    """
    if not slides:
        return
    from . import board as board_mod
    from . import diagram as diagram_mod

    targets = [s for s in slides
               if not (s.board_lead or s.board_points or s.diagram)]
    if not targets:
        return
    outline = project.outline
    chunks = [targets[i : i + 10] for i in range(0, len(targets), 10)]
    progress(f"Writing boards for {len(targets)} slides")
    menu = "\n".join(f'- "{t["key"]}": {t["blurb"]}' for t in board_mod.TEMPLATES)

    def run(args: tuple[int, list[Slide]]) -> tuple[int, Any]:
        ci, chunk = args
        listing = "\n".join(f'{n}. [{s.section}/{s.beat}] "{s.narration}"'
                             for n, s in enumerate(chunk, 1))
        prompt = f"""Write what goes on screen for each paragraph below.

VIDEO: {outline.get('title')} - {outline.get('thesis', '')}
SUBJECT: {outline.get('subject')}

The format is a handwritten board: white marker on a grey-blue slide that
fills up as the narrator talks. The writing on it is the STRUCTURE of the
point, never a transcript of the voice. Short, blunt, lettered by hand.

TEMPLATES:
{menu}

PARAGRAPHS:
{listing}

Return a JSON list of {len(chunk)} objects in the same order:
{{"n": <the number>,
  "template": "auto" or one of the template keys above,
  "lead": "the line the slide is about — 2-7 words, no end punctuation",
  "points": ["0 to 5 lines under it, 2-6 words each"],
  "note": "" or one short footnote, source or attribution,
  "diagram": null, or a diagram spec when the paragraph is about a shape}}

Rules:
- Short. A point longer than six words cannot be lettered by hand and read at
  a glance. Cut articles and verbs before you cut the noun.
- Never restate the narration. If the voice says it in a sentence, the board
  says it in three words, or says the thing the sentence is evidence for.
- Prefix a point with * to pick it out in the accent colour. At most one per
  slide, and not on every slide.
- "auto" is the right answer most of the time: it picks from what you wrote.
  Name a template only when the content genuinely is a quote, a number, a
  comparison, a sequence or code.
- Vary it. Five bulleted boards in a row is a slide deck, not a video.
- Each paragraph also has a picture. "auto" tapes it up on about one board in
  three; name "taped" or "split" yourself for a paragraph about a concrete
  person, place, object or event, where seeing it beats reading about it.
  Never on two paragraphs running, and never for an abstract point.
- A paragraph with nothing worth writing down gets {{"lead": "", "points": []}}
  and will be given a line from its own narration.

{diagram_mod.SPEC_DOC}

Only give a paragraph a diagram when it is genuinely about a shape — an order,
a hierarchy, an overlap, a loop. At most {max(1, len(chunk) // 4)} of these
{len(chunk)} paragraphs should have one. Everything else gets null."""
        return ci, complete_json(
            prompt, model=MODEL_UTILITY, timeout=600,
            require=lambda v: bool(find_records(v, "lead")),
            require_hint='Each item needs "n" and a "lead".')

    with cf.ThreadPoolExecutor(max_workers=4) as pool:
        for ci, plan in pool.map(run, list(enumerate(chunks))):
            chunk = chunks[ci]
            by_n = {}
            for pos, item in enumerate(find_records(plan, "lead"), 1):
                try:
                    n = int(item.get("n", pos))
                except (TypeError, ValueError):
                    n = pos
                by_n[n] = item
            for n, slide in enumerate(chunk, 1):
                item = by_n.get(n, {})
                slide.board_lead = str(item.get("lead") or "").strip()[:160]
                points = item.get("points") or []
                slide.board_points = [str(p).strip()[:120] for p in points
                                      if str(p).strip()][:6]
                slide.board_note = str(item.get("note") or "").strip()[:160]
                key = str(item.get("template") or "auto")
                slide.board_template = key if key in board_mod.TEMPLATE_KEYS else "auto"
                spec = item.get("diagram")
                if spec:
                    try:
                        slide.diagram = diagram_mod.normalise(spec)
                        slide.prefer_kind = "diagram"
                    except (ValueError, TypeError):
                        slide.diagram = {}
            progress(f"Boards written for chunk {ci + 1}/{len(chunks)}")


def plan_cues(project: Project, slides: list[Slide],
              progress: Progress = lambda m: None) -> None:
    """Write what the video's drawn cut puts on screen, cue by cue, in place.

    The drawn cuts' equivalent of `plan_boards`, and additive the same way:
    a slide that already has cues for this cut is left alone, and a slide
    this pass misses is drawn from its own narration (`cuts.cues_for`).
    Each cue names the words it lands `on`, which is how a fast cut stays on
    the voice without word timings. See app/cuts/.
    """
    from . import cuts

    fmt = project.style.format
    if not slides or not cuts.is_cut(fmt):
        return
    module = cuts.BY_KEY[fmt]
    targets = [s for s in slides if not (s.cues or {}).get(fmt)]
    if not targets:
        return
    outline = project.outline
    facts = _facts_block(project.research or {}) if fmt == "ticker" else ""
    chunks = [targets[i : i + 8] for i in range(0, len(targets), 8)]
    progress(f"Writing {module.LABEL} cues for {len(targets)} paragraphs")

    def run(args: tuple[int, list[Slide]]) -> tuple[int, Any]:
        ci, chunk = args
        listing = "\n".join(f'{n}. [{s.section}/{s.beat}] "{s.narration}"'
                             for n, s in enumerate(chunk, 1))
        prompt = f"""Write what goes on screen for each paragraph below.

VIDEO: {outline.get('title')} - {outline.get('thesis', '')}
SUBJECT: {outline.get('subject', project.idea)}
{facts}
{module.PLAN}

Every cue also has "on": the first 3-6 words of the narration, copied
EXACTLY, at which that cue should appear. The first cue of a paragraph is on
its opening words. Cues are in the order they are spoken.

PARAGRAPHS:
{listing}

Return a JSON list of {len(chunk)} objects in the same order:
{{"n": <the number>, "cues": [ ...cue objects as described above... ]}}"""
        return ci, complete_json(
            prompt, model=MODEL_UTILITY, timeout=600,
            require=lambda v: bool(find_records(v, "cues")),
            require_hint='Each item needs "n" and a "cues" list.')

    with cf.ThreadPoolExecutor(max_workers=4) as pool:
        for ci, plan in pool.map(run, list(enumerate(chunks))):
            chunk = chunks[ci]
            by_n = {}
            for pos, item in enumerate(find_records(plan, "cues"), 1):
                try:
                    n = int(item.get("n", pos))
                except (TypeError, ValueError):
                    n = pos
                by_n[n] = item
            for n, slide in enumerate(chunk, 1):
                cues = cuts.normalise(module, by_n.get(n, {}).get("cues"))
                if cues:
                    slide.cues = {**(slide.cues or {}), fmt: cues}
            progress(f"{module.LABEL} cues written for chunk {ci + 1}/{len(chunks)}")


# --------------------------------------------------------------- fact-check
def verify_script(project: Project, progress: Progress = lambda m: None) -> list[dict]:
    """Flag any paragraph asserting something the research dossier doesn't
    support. Grounding the writer doesn't guarantee it stayed grounded — this
    is the check on the output, not the input, and it's cheap because it is
    checking against a dossier already gathered rather than researching again.

    [] (not skipped) when there is no dossier to check against — nothing to
    flag against nothing, which is different from "everything's fine".
    """
    facts = _facts_block(project.research)
    slides = project.slides
    if not facts or not slides:
        return []

    chunks = [slides[i : i + 12] for i in range(0, len(slides), 12)]
    progress(f"Checking {len(slides)} paragraph(s) against the research")

    def run(args: tuple[int, list[Slide]]) -> list[dict]:
        _ci, chunk = args
        listing = "\n".join(f"{n}. {s.narration}" for n, s in enumerate(chunk, 1))
        prompt = f"""{facts}

NARRATION PARAGRAPHS TO CHECK:
{listing}

For each paragraph, does it assert anything specific (a date, a name, a
number, a quote, a claim of cause or outcome) that the RESEARCHED FACTS above
does not support or actively contradicts? Ignore scene-setting, transitions
and anything already covered by a fact above. Most paragraphs will have
nothing wrong with them — only report the ones that do.

Return JSON: a list of objects, one per paragraph that has a problem:
{{"n": <the paragraph number above>, "claim": "the unsupported or
  contradicted part, quoted or closely paraphrased", "issue": "one sentence
  on what's wrong", "severity": "high" or "low"}}"""
        out = complete_json(prompt, model=MODEL_UTILITY, timeout=400,
                            require=lambda v: isinstance(v, list))
        flags = []
        for item in out if isinstance(out, list) else []:
            if not isinstance(item, dict):
                continue
            try:
                n = int(item.get("n", 0))
            except (TypeError, ValueError):
                continue
            if not 1 <= n <= len(chunk):
                continue
            flags.append({
                "slide_id": chunk[n - 1].id,
                "claim": str(item.get("claim") or "")[:300],
                "issue": str(item.get("issue") or "")[:300],
                "severity": "high" if item.get("severity") == "high" else "low",
            })
        return flags

    all_flags: list[dict] = []
    with cf.ThreadPoolExecutor(max_workers=4) as pool:
        for flags in pool.map(run, list(enumerate(chunks))):
            all_flags.extend(flags)
    progress(f"Fact check: {len(all_flags)} paragraph(s) flagged")
    return all_flags


# ------------------------------------------------------------------ full build
def generate(project: Project, progress: Progress = lambda m: None,
             checkpoint: Callable[[], None] = lambda: None,
             fresh: bool = False) -> Project:
    """Write the script. Picks up an unfinished run unless `fresh` is asked for.

    `checkpoint` persists the project mid-run; without one this still works, it
    just has nothing to come back to.
    """
    key = draft_key(project)
    if fresh or project.draft.get("key") != key:
        # No draft, or one written against a different idea, length or tone.
        project.draft = {"key": key}

    research = project.draft.get("research")
    if research is not None:
        if research:
            progress(f"Picking up research already gathered "
                     f"({len(research.get('facts', []))} fact(s))")
    else:
        research = script_research.gather(project.idea, progress)
        project.draft["research"] = research      # {} is a valid, banked result
        checkpoint()
    project.research = research

    outline = project.draft.get("outline")
    if outline:
        # The saved sections were written to *these* headings. Re-outlining here
        # would produce different ones and strand every one of them.
        progress(f"Picking up the outline this run already settled on "
                 f"({len(outline.get('sections', []))} sections)")
    else:
        outline = build_outline(project, progress)
        project.draft["outline"] = outline
        project.draft["sections"] = {}
        checkpoint()
    project.outline = outline
    project.title = outline.get("title", project.idea[:60])
    project.subtitle = outline.get("subtitle", "")

    slides = write_script(project, outline, progress, checkpoint)
    if not slides:
        raise ValueError("Script generation produced no paragraphs")

    plan_visuals(project, slides, progress)
    if project.style.format == "board":
        plan_boards(project, slides, progress)
    plan_cues(project, slides, progress)
    _plan_style_slides(project, slides, progress)
    project.slides = slides
    project.status = "scripted"
    project.draft = {}          # the run finished; nothing left to come back to

    if project.research.get("facts"):
        project.research["flags"] = verify_script(project, progress)

    words = sum(s.word_count for s in slides)
    progress(f"Script done: {len(slides)} paragraphs, {words} words, "
             f"~{project.est_seconds() / 60:.1f} min")
    return project


# ------------------------------------------------------------- script import
# Furniture that appears in pasted newsletter posts and cannot be read aloud.
_BOILERPLATE = re.compile(
    r"^\s*(subscribe|subscribed|share this post|share|leave a comment|comments?|"
    r"thanks for reading.*|if you enjoyed.*|please share.*|read more|"
    r"discussion about this post|previous|next|\d+ likes?|\d+ comments?|"
    r"upgrade to paid|pledge your support|listen now|watch now|"
    r"type your email.*|sign up|log in|continue reading)\s*$",
    re.I,
)


def clean_pasted(raw: str) -> str:
    """Strip a pasted article down to text a narrator could actually read."""
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)          # images
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)      # links -> label
    text = re.sub(r"<[^>]+>", "", text)                       # stray html
    text = re.sub(r"https?://\S+", "", text)                  # bare urls
    text = re.sub(r"[*_`]{1,3}(.+?)[*_`]{1,3}", r"\1", text)  # emphasis marks

    lines = []
    for line in text.split("\n"):
        stripped = line.strip()
        if _BOILERPLATE.match(stripped):
            continue
        # Keep headings as text; they become beat names downstream.
        lines.append(re.sub(r"^#{1,6}\s*", "", line).rstrip())
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _chunk_paragraphs(text: str, target_words: int = 650) -> list[str]:
    """Group the article's own paragraphs into chunks the model can hold at once."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks, current, count = [], [], 0
    for para in paras:
        words = len(para.split())
        if current and count + words > target_words:
            chunks.append("\n\n".join(current))
            current, count = [], 0
        current.append(para)
        count += words
    if current:
        chunks.append("\n\n".join(current))
    return chunks


FAITHFUL_RULES = """You are preparing the creator's OWN article to be read aloud. \
Their words are the point. You may:
- split a long sentence at a natural breath point,
- merge two very short sentences,
- drop text that cannot be spoken: image captions, link labels, subscribe \
prompts, "click here", stray navigation,
- fix outright spelling and typing errors ("Atleast" -> "At least", "tip's" -> \
"tips", a missing full stop).
You may NOT rewrite their phrasing, swap their vocabulary for your own, add \
transitions they did not write, add or remove facts, or change their opinions. \
If a sentence is awkward but readable, leave it alone."""

ADAPTED_RULES = """You are adapting the creator's article for the ear. Keep every \
fact, every opinion and the running order exactly as they are, but you may \
smooth written-only constructions into speakable ones: unpack parentheses, \
break up long clauses, replace "as I wrote above" style cross-references, and \
fix errors. Stay recognisably in the author's voice and never add new claims."""


def import_script(project: Project, raw_text: str, fidelity: str = "faithful",
                  progress: Progress = lambda m: None) -> Project:
    """Turn a pasted article into a narrated, illustrated video."""
    text = clean_pasted(raw_text)
    words = len(text.split())
    if words < 120:
        raise ValueError("That script is too short to build a video from.")
    progress(f"Cleaned script: {words} words (~{words / WORDS_PER_MINUTE:.1f} min read)")

    rules = ADAPTED_RULES if fidelity == "adapted" else FAITHFUL_RULES

    # 1. Metadata, from the head of the article.
    head = text[:6000]
    meta = complete_json(
        f"""Read the opening of an article that is about to become a narrated video.

\"\"\"{head}\"\"\"

Return JSON:
{{"title": "the video title, 4-9 words; reuse the author's own title if it works \
spoken, otherwise tighten it. No clickbait, no colon-subtitle",
  "subtitle": "one clause of context, max 8 words",
  "subject": "what this is about, named plainly in 2-6 words",
  "era": "the time period, or 'present day'",
  "thesis": "one sentence: the argument the article makes",
  "visual_world": "one sentence on what should be on screen through this video, \
given what photographs and footage plausibly exist for this subject"}}""",
        model=MODEL_UTILITY, timeout=400,
        require=lambda v: isinstance(v, dict) and bool(v.get("title")),
        require_hint='The object needs a top-level "title".')

    project.outline = meta | {"sections": [], "imported": True}
    project.title = meta.get("title") or project.title or "Untitled"
    project.subtitle = meta.get("subtitle", "")
    project.target_minutes = max(3, min(40, round(words / WORDS_PER_MINUTE)))

    # 2. Segment, chunk by chunk, preserving order.
    chunks = _chunk_paragraphs(text)
    progress(f"Segmenting {len(chunks)} chunk(s) into narration paragraphs")

    def segment(args: tuple[int, str]) -> tuple[int, list[dict]]:
        ci, chunk = args
        where = ("the opening of the article" if ci == 0 else
                 "the end of the article" if ci == len(chunks) - 1 else
                 f"the middle of the article (part {ci + 1} of {len(chunks)})")
        out = complete_json(
            f"""Split part of an article into narration paragraphs for a video.

ARTICLE TITLE: {project.title}
THIS IS {where.upper()}.

{rules}

TEXT:
\"\"\"{chunk}\"\"\"

Return a JSON list. One object per narration paragraph, in the original order:
{{"text": "the words to be spoken, 40-75 words",
  "beat": "2-5 word name for the section this paragraph belongs to; reuse the \
same beat name for consecutive paragraphs on the same point",
  "visual": "one plain sentence describing the single image or clip that should \
be on screen while this is read"}}

Cover the whole text. Do not summarise it and do not skip paragraphs.
If the text opens with the article's own headline and standfirst, skip both: they \
are already the video's title and are shown on screen, so reading them aloud is a \
duplicate. Begin at the first real body sentence.
Expand anything that does not read aloud: "&" becomes "and", "e.g." becomes "for \
example", a numeral stays a numeral only if you would say it that way.""",
            system=NARRATOR_SYSTEM, model=MODEL_SCRIPT, timeout=900,
            require=lambda v: bool(find_records(v, "text")),
            require_hint='Each item needs a "text" field holding the spoken words.')
        return ci, find_records(out, "text")

    results: dict[int, list[dict]] = {}
    with cf.ThreadPoolExecutor(max_workers=3) as pool:
        done = 0
        for ci, paras in pool.map(segment, list(enumerate(chunks))):
            results[ci] = paras
            done += 1
            progress(f"Chunk {done}/{len(chunks)} segmented ({len(paras)} paragraphs)")

    slides: list[Slide] = []
    for ci in range(len(chunks)):
        for para in results.get(ci, []):
            slides.append(Slide(
                section="main",
                beat=(para.get("beat") or "").strip()[:40],
                narration=para["text"].strip(),
                visual_note=(para.get("visual") or "").strip(),
            ))
    if not slides:
        raise ValueError("Segmentation produced no paragraphs")

    # Mark the ends so the visual planner treats them as an opening and a close.
    slides[0].section = "intro"
    slides[-1].section = "conclusion"

    plan_visuals(project, slides, progress)
    if project.style.format == "board":
        plan_boards(project, slides, progress)
    plan_cues(project, slides, progress)
    _plan_style_slides(project, slides, progress)
    project.slides = slides
    project.status = "scripted"
    kept = sum(s.word_count for s in slides)
    progress(f"Imported {len(slides)} paragraphs, {kept} words "
             f"({kept / max(1, words) * 100:.0f}% of the source), "
             f"~{project.est_seconds() / 60:.1f} min")
    return project


def generate_diagram(project: Project, slide: Slide, instruction: str = "") -> dict:
    """Ask Claude for a diagram spec for one slide — the "ask Claude" button
    on the diagram editor. Same authoring rules `plan_boards` already writes
    against (`diagram.SPEC_DOC`), aimed at one paragraph instead of a batch,
    and steerable: a blank instruction lets the model pick the shape itself
    from the narration; a creator's own words narrow it down ("as a cycle",
    "put the regulator in the middle").

    Returns a normalised spec — never raises on a malformed reply, since
    `diagram.normalise` already tolerates a model that used "from"/"to" as
    labels instead of ids, left `kind` off, and so on; what this adds on top
    is the JSON-shape retry `complete_json` already does for every other
    writer call.
    """
    from . import diagram as diagram_mod

    outline = project.outline
    idx = project.slides.index(slide)
    prev = project.slides[idx - 1].narration if idx > 0 else ""
    prompt = f"""Draw a diagram for this paragraph of a video's narration.

VIDEO: {outline.get('title')} - {outline.get('thesis', '')}
SUBJECT: {outline.get('subject', project.idea)}

{f'PREVIOUS PARAGRAPH (for context only): "{prev}"' if prev else ''}
THIS PARAGRAPH: "{slide.narration}"

{f'THE CREATOR ASKED FOR: {instruction}' if instruction.strip() else
  'The creator has not specified a layout — pick whichever of the shapes '
  'below actually matches what this paragraph describes.'}

{diagram_mod.SPEC_DOC}

Return exactly one spec, matching the paragraph's own content — never a
generic illustration of the video's subject as a whole."""

    out = complete_json(
        prompt, model=MODEL_UTILITY, timeout=180,
        require=lambda v: isinstance(v, dict) and bool(v.get("nodes")),
        require_hint='Return one JSON object with a "kind" and a "nodes" array.')
    try:
        return diagram_mod.normalise(out)
    except (ValueError, TypeError):
        raise LLMError("Claude's diagram didn't come back in a shape I could draw.")


def design_slide_style(description: str, accent: str = "#E8C36A") -> dict:
    """Design a reusable slide style from a description, with no video yet.

    The sibling of `generate_custom_slide` for someone standing on the home
    page who wants a look before they have a script: there is no paragraph to
    read, so the brief is the whole input. What comes back is a *template* —
    its text is placeholder standing in for the slot, chosen to show the
    length that layout can carry, because `plan_custom_slides` will replace
    every slot per paragraph later.
    """
    from . import custom_slide as custom_mod

    brief = (description or "").strip()
    prompt = f"""Design a reusable slide style for a narrated documentary video.

THE CREATOR ASKED FOR: {brief or
  'a clean, striking slide style — pick something with a strong idea to it.'}
ACCENT COLOUR: {accent}

This design will be reused for EVERY paragraph of a video, with its words and
pictures swapped out each time. So you are designing a *template*:

- Every text element's text is a PLACEHOLDER showing what belongs there and
  roughly how long it can be — "1,910", "the night the dam held", not lorem
  ipsum and not anything specific to one subject.
- Every image element's query is a placeholder search in the same spirit.
- The layout, colours, fonts, opacities and entrances ARE the style. Those are
  what get reused, so they are what you are really deciding.
- Keep it to 2-5 elements. A template with eight slots is a form to fill in,
  and it will be filled in thirty times.

{custom_mod.SPEC_DOC}

Return exactly one spec. Use the accent colour above for whatever carries the
emphasis, so the style suits the channel it will be used in."""

    out = complete_json(
        prompt, model=MODEL_UTILITY, timeout=180,
        require=lambda v: isinstance(v, dict) and bool(v.get("elements")),
        require_hint='Return one JSON object with an "elements" array.')
    try:
        return custom_mod.normalise(out)
    except (ValueError, TypeError):
        raise LLMError("Claude's style didn't come back in a shape I could draw.")


def _plan_style_slides(project: Project, slides: list[Slide],
                       progress: Progress = lambda m: None) -> None:
    """Fill the video's saved slide style, if it is staged in one."""
    from . import slide_styles

    style_id = slide_styles.id_from_format(project.style.format)
    if not style_id:
        return
    style = slide_styles.get(style_id)
    if style:
        plan_custom_slides(project, slides, style.spec, progress)


def plan_custom_slides(project: Project, slides: list[Slide], style_spec: dict,
                       progress: Progress = lambda m: None) -> None:
    """Fill a saved slide style with each paragraph's own words, in place.

    The style supplies the layout, the palette and the entrances; this supplies
    only what goes *in* the slots — the text of each text element, the query of
    each image element. Keeping the design fixed is the whole point of a style:
    thirty paragraphs staged the same way read as one video, where thirty
    separately designed slides read as thirty.

    Additive, the same as `plan_boards`: a paragraph someone has already
    designed by hand is left alone.
    """
    if not slides:
        return
    from . import custom_slide as custom_mod

    try:
        style_spec = custom_mod.normalise(style_spec)
    except (ValueError, TypeError):
        return
    slots = [(i, el) for i, el in enumerate(style_spec["elements"])
             if el["type"] in ("text", "image")]
    if not slots:
        return
    targets = [s for s in slides if not (s.custom or {}).get("elements")]
    if not targets:
        return

    outline = project.outline
    slot_doc = "\n".join(
        f'  {n}. {el["type"]} — '
        + (f'currently "{el.get("text", "")}"' if el["type"] == "text"
           else f'an archive photo, currently searched as "{el.get("query", "")}"')
        for n, (_, el) in enumerate(slots, 1))
    chunks = [targets[i : i + 10] for i in range(0, len(targets), 10)]
    progress(f"Fitting {len(targets)} paragraphs to the slide style")

    def run(args: tuple[int, list[Slide]]) -> tuple[int, Any]:
        ci, chunk = args
        listing = "\n".join(f'{n}. [{s.section}/{s.beat}] "{s.narration}"'
                            for n, s in enumerate(chunk, 1))
        prompt = f"""Fill one fixed slide design with each paragraph's own content.

VIDEO: {outline.get('title')} - {outline.get('thesis', '')}
SUBJECT: {outline.get('subject')}

Every paragraph in this video is staged in the SAME design. You are not
redesigning it — you are only writing what goes in its {len(slots)} slots:

{slot_doc}

PARAGRAPHS:
{listing}

Return a JSON list of {len(chunk)} objects in the same order:
{{"n": <the number>,
  "slots": ["the content for slot 1", "slot 2", …]}}

Rules:
- One entry per slot, in order, always {len(slots)} of them.
- A text slot takes words that fit where they sit — the example text above
  shows the length that works. Shorter is better; it is set large.
- An image slot takes an archive SEARCH, written like a photo caption and
  specific enough to find the right thing ("Apollo 11 launch pad 1969", not
  "rocket"). Never a sentence about the paragraph.
- Never restate the narration. The slide carries the label, the number, the
  name; the voice carries the argument.
- A paragraph with nothing worth putting in a slot gets "" for it."""
        return ci, complete_json(
            prompt, model=MODEL_UTILITY, timeout=600,
            require=lambda v: bool(find_records(v, "slots")),
            require_hint='Each item needs "n" and a "slots" array.')

    with cf.ThreadPoolExecutor(max_workers=4) as pool:
        for ci, plan in pool.map(run, list(enumerate(chunks))):
            chunk = chunks[ci]
            by_n = {}
            for pos, item in enumerate(find_records(plan, "slots"), 1):
                try:
                    n = int(item.get("n", pos))
                except (TypeError, ValueError):
                    n = pos
                by_n[n] = item
            for n, slide in enumerate(chunk, 1):
                filled = by_n.get(n, {}).get("slots") or []
                spec = copy.deepcopy(style_spec)
                for pos, (idx, _) in enumerate(slots):
                    value = str(filled[pos]).strip() if pos < len(filled) else ""
                    if not value:
                        continue
                    el = spec["elements"][idx]
                    if el["type"] == "text":
                        el["text"] = value[:200]
                    else:
                        el["query"] = value[:140]
                        el["local_path"] = ""   # a new query needs a new fetch
                slide.custom = spec


def generate_custom_slide(project: Project, slide: Slide,
                          instruction: str = "") -> dict:
    """Ask Claude to design a slide from scratch for one paragraph.

    The open-ended sibling of `generate_diagram`: where that one picks from
    nine shapes, this one places elements wherever it likes, so a paragraph
    that wants a pull-quote over a photo or one enormous number gets a
    layout rather than the nearest template. A blank instruction lets the
    model read the paragraph and decide; the creator's own words steer it.
    """
    from . import custom_slide as custom_mod

    outline = project.outline
    idx = project.slides.index(slide)
    prev = project.slides[idx - 1].narration if idx > 0 else ""
    prompt = f"""Design a slide for this paragraph of a video's narration.

VIDEO: {outline.get('title')} - {outline.get('thesis', '')}
SUBJECT: {outline.get('subject', project.idea)}
ACCENT COLOUR: {project.style.accent}

{f'PREVIOUS PARAGRAPH (for context only): "{prev}"' if prev else ''}
THIS PARAGRAPH: "{slide.narration}"

{f'THE CREATOR ASKED FOR: {instruction}' if instruction.strip() else
  'The creator has not described a layout — read the paragraph and design '
  'whatever actually serves it.'}

{custom_mod.SPEC_DOC}

Return exactly one spec, designed around this paragraph's own content. Use
the accent colour above for anything meant to stand out, so the slide looks
like it belongs to this channel."""

    out = complete_json(
        prompt, model=MODEL_UTILITY, timeout=180,
        require=lambda v: isinstance(v, dict) and bool(v.get("elements")),
        require_hint='Return one JSON object with an "elements" array.')
    try:
        return custom_mod.normalise(out)
    except (ValueError, TypeError):
        raise LLMError("Claude's slide didn't come back in a shape I could draw.")


def rewrite_slide(project: Project, slide: Slide, instruction: str) -> str:
    """Rewrite one paragraph against a creator instruction, keeping the flow."""
    idx = project.slides.index(slide)
    prev = project.slides[idx - 1].narration if idx > 0 else "(start of video)"
    nxt = project.slides[idx + 1].narration if idx + 1 < len(project.slides) else "(end of video)"
    prompt = f"""Rewrite one paragraph of narration.

VIDEO: {project.outline.get('title')} - {project.outline.get('thesis', '')}

PARAGRAPH BEFORE: "{prev}"
PARAGRAPH TO REWRITE: "{slide.narration}"
PARAGRAPH AFTER: "{nxt}"

CREATOR'S INSTRUCTION: {instruction or "tighten it and make it more concrete"}

It must still read continuously between the paragraphs either side, stay within
40-75 words, and follow every narration rule you have been given.

Return JSON: {{"text": "the rewritten paragraph"}}"""
    out = complete_json(prompt, system=NARRATOR_SYSTEM, model=MODEL_SCRIPT, timeout=600)
    text = (out.get("text") if isinstance(out, dict) else str(out)) or ""
    return text.strip()
