# Phase 21: a workspace that feels like real creative software

Owner, 2026-11-15: "The script page needs work, it should look more like a
program like Scrivener or another writing app. I like how the facts and the
shot description are easily accessible. Plan being first is confusing to me,
I think I'd like a project dashboard first: I can work on the script, drop off
research notes, images and clips (label them too!). Voice is good. Visual I'm
not sure, maybe this should be more of an editing, where I can layer
images/3D/clips/blocks, ask for a custom agent creating HTML-driven stuff,
choose timings etc. Edit I like, but there are lots of layers. I think the
layers should be custom to the project, defined by the agent at first; users
can add more. Also the library section needs to feel more like an explorer,
like Bridge. I want to really improve on the UX experience."

## The new project shape

```
Before:  1 Plan · 2 Script · 3 Voice · 4 Visuals · 5 Edit · 6 Review & publish
After:   Dashboard · Script · Voice · Edit · Publish
```

- **Dashboard** is where a project opens (`#/p/<id>`). It answers "what is
  left?", shows each stage's state as a card, and holds the **project bin**:
  research notes, pictures, clips, audio and links the creator drops in, each
  with labels.
- **Plan folds into Script.** The outline becomes Script's binder (chapters
  and paragraphs as a tree, like Scrivener), with a corkboard view of beat
  cards for the planning moments. "Write the script" lives there.
- **Script** becomes a writing app: binder · one continuous editor · an
  inspector with the paragraph's facts, shot description, title and findings.
- **Visuals folds into Edit.** Edit gains a sources panel (bin, Library,
  archive search, blocks, 3D, "ask the agent") and you drag onto layers.
  Picture candidates move into the inspector. "Fill the rest" moves to Edit.
- **Layers belong to the project.** The agent proposes a set that fits the
  video ("Archive photos", "Maps", "Lower thirds", "Narration", "Music"); the
  creator renames, adds, reorders, hides and locks them. Built-in lanes with
  nothing on them are not drawn.
- **Library becomes an explorer** in the spirit of Adobe Bridge: folder tree,
  thumbnail grid with a size slider, preview and metadata pane, labels, star
  ratings and colour labels, filters, batch edits.

Old routes keep working: `plan` → `script` (corkboard view), `visuals`,
`media`, `cast`, `stage` → `edit`. Old projects open without migration
prompts; anything the new model needs is derived on load ("unknown keys
ignored, missing keys defaulted").

## Inspiration (ideas only; no code copied)
- **Scrivener:** binder, editor, inspector; corkboard of index cards;
  composition mode; per-document targets and word counts.
- **Ulysses / iA Writer:** quiet editor, typewriter scrolling, focus mode.
- **Adobe Bridge / Lightroom Library:** folder tree, grid with size slider,
  ratings 1–5, colour labels, filter bar, metadata panel, batch keywords.
- **Premiere / Resolve / Final Cut:** named tracks, lock and hide per track,
  track colours, media bin with labels, source panel.

## Tickets, in priority order
| | | |
|---|---|---|
| 0 | T21.0 | No "coming soon" copy: unfinished features are just disabled |
| 1 | T21.1 | Project dashboard as the first stage; Plan leaves the stage bar |
| 2 | T21.2 | Project bin: drop notes, pictures, clips; label them |
| 3 | T21.3 | Script as a writing app: binder, editor, inspector |
| 4 | T21.3b | Corkboard view: the outline as cards inside Script |
| 5 | T21.5 | Project layers: model, derivation for old projects, timeline lanes |
| 6 | T21.5b | Layer manager and agent-proposed layers |
| 7 | T21.6 | Edit becomes the composing stage: sources panel, Visuals folds in |
| 8 | T21.4 | Library as an explorer: tree, grid, preview pane |
| 9 | T21.4b | Library: ratings, colour labels, filters, batch labels, collections |
| 10 | T21.2b | Bin notes and media feed research, script writing and picture fill |
| 11 | T21.6b | Pictures, clips and 3D on upper layers (picture-in-picture) |
| 12 | T21.7 | Ask the agent for a custom HTML scene, placed on a layer |

Why this order: the dashboard and bin are the new front door and small; the
Script rework is what the owner spends most time in; layers are a data model
that Edit's composing work needs; the Library explorer is independent and can
slot in anywhere; agent-made scenes come last because they build on layers and
the sources panel.

Existing Phase 20 fix tickets: T20.10 (Plan board fit) and T20.13 (Visuals
list) are superseded by T21.3b and T21.6. T20.4 (Edit at 1280×720) is folded
into T21.6's acceptance. The rest of Phase 20 stays queued after Phase 21.

## Rules for every ticket in this phase
- Follow `docs/design/studio-flow.md` tokens and components; where this
  phase changes the IA (section 6) the phase README wins. T21.1 updates the
  guide's section 6 and stage table.
- No Node, no build step, plain script tags; vendored single files only with
  licences in `THIRD-PARTY.md`.
- Never delete, overwrite or orphan recorded audio or user media. Removing
  something from the bin or Library unlinks it; files stay on disk unless the
  file was copied in and the user explicitly confirms through the app dialog.
- Every new screen gets a fixture in `scripts/ui_snapshots.py` at 1280×720
  and 1920×1080; the reviewer screenshots it.
- Keyboard first: every new list and grid is arrow-key navigable with a
  visible focus ring.
