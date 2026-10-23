# The 3D explainer

A video format built on 3D models: narration over three.js scenes, with
cards, chapter screens and photos where a model cannot do the job. Picked in
the format picker as **3D explainer** (style key `stage`).

This document is the strategy. It was written after a spike (October 2026)
that shot six test models:

- an Airbus A380 and a 1903 Wright Flyer
- the King's Hall at Skokloster Castle
- an aerial scan of Westminster Abbey
- a modelled Paris
- a cutaway loft set

Every rule below was learned from something that went wrong in that spike.
The spike's code lives outside the repo; what it proved is written down here
so it can be rebuilt properly (see **Status** and **Next steps** at the end).

## The one idea

**The models come first, and the camera is only as good as what the system
knows about them.**

Every other format writes the script and then finds pictures for it. Here
that order is reversed. A 3D explainer can only show what is in its models,
and the camera can only frame what it understands: which way is the front,
how big the thing really is, and where its parts are. So the models are
found and *understood* before a word of the script is written, and the
writer is told what can be shown.

## Creating a video: the order of operations

**Story, then cast, then words.**

- **The story (outline) is cheap and changeable.** Claude writes it in a
  minute.
- **The cast is slow and human.** Finding and confirming models can take
  days.
- **The script depends on the cast.** It can only describe what the models
  can show.

So the cast is chosen from the story, and the script waits for the cast.

**What the creator sees:**

1. **New video:** the idea, **3D explainer**, the length. Optionally pick
   models already in the library ("make it about these"), or paste a
   script.
2. **The brief** (*Plan the story and cast*, about 30 s): research, an
   outline, and a proposed **cast**. The video opens on the **Cast** tab.
   - The story is at the top: title, thesis, numbered chapters.
   - The subjects are below, each with its role (hero, comparison,
     supporting, cameo), its chapters and why it is there.
   - Each subject is *ready* (a confirmed model), *needs a model*, or
     *photos instead*.
   - Library models are matched to subjects automatically.
   - Subjects can be added, renamed, removed, or proposed again (subjects
     that already have a model are kept).
3. **Gather the cast, in the creator's own time.**
   - Pick a library model for a subject, or upload a GLB onto it. Intake
     and *Ask Claude* then run on it and it is confirmed.
   - The tab shows "2 of 3 ready".
4. **Write the script.** It can always be pressed; with gaps it warns
   first.
   - The writer continues from the saved draft (no new research or
     outline) and is told each model's real size, parts, regions and
     limits.
   - Each paragraph's visual becomes a stage direction:
     - `3D: <subject> — <whole or a listed part> — <shot>`
     - or `PHOTO: …` for anything no model carries
5. **Record**, then **Stage** (shots), **Media** (pictures for the photo
   beats), **Render**.

The three ways in all end at step 3:

- **Idea first.**
- **Models first:** the chosen models arrive as heroes, and the brief is
  built around them.
- **Script first:** the cast is pulled from the pasted script, and the script
  is not rewritten.

**Changing the cast later:** a removed or swapped model should flag the
paragraphs that use it, with a one-click rewrite of just those paragraphs.
This is not built yet.

**Tested end to end** with *"How did we get from the Wright Flyer to the
A380?"*, with the Flyer chosen first:

- **The brief (34 s):** six chapters, from "Twelve Seconds, 1903" to "Where
  Size Stopped". The cast:
  - the Flyer: the creator's pick
  - the A380: matched from the library
  - the DC-3 and the 747: proposed
- **The script (46 s):** 16 paragraphs.
  - The 3D beats use only real parts and regions: the Flyer's hand-drawn
    "engine and propellers" region, the A380's "left wing", and the Flyer
    under the A380's wing at true scale.
  - The DC-3 (set to photos), the 747 (no model yet) and subjects never in
    the cast (the Comet, the Junkers J 1) became `PHOTO:` beats.

## The pipeline

Worked example: the idea *"From the Wright Flyer to the A380"*.

### 1. Research and cast

Claude reads the idea (plus the usual research pass) and proposes a
**cast**: every subject that needs a model, and why. For this idea, a
history: Wright Flyer (1903), Spirit of St. Louis, DC-3, Comet, 707, 747,
Concorde, A380 (2007). Two models make a comparison video; six to eight make
a history.

**Human:** choose the cast.

### 2. Find the models

For each subject the app searches, in order:

- the model library
- Smithsonian Open Access (CC0)
- NASA 3D Resources
- Sketchfab (downloadable models only, licence-filtered; needs the creator's API key)
- Poly Pizza
- a file the creator uploads

Each candidate shows a thumbnail, licence, triangle count and whether it is
textured.

**Human:** pick one, or mark the subject *no model*. A subject with no model
falls back to photos and cards, and the writer is told so.

### 3. Understand each model (once, in the library)

This happens once per model and is kept in the shared library, so the second
video that uses the A380 skips it.

**First, classify it.** The spike's biggest finding is that understanding
depends on what *kind* of model it is. Each kind needs different questions,
different pictures for Claude, and different shots. The kind is worked out
from the file and a depth probe before anything else:

| kind | example | how it is recognised | lit? | what it limits |
|---|---|---|---|---|
| **object** | A380, Wright Flyer | the probe from the centre sees back faces (inside a shell) | ours, unless an unlit scan | parts may be unnamed; detail budget on close-ups |
| **interior** | King's Hall | almost all front faces from the centre, no void | scans bring their own light | camera spots, eye height, holes, the lens |
| **aerial site** | Westminster Abbey | about half the directions are open sky; one big texture; scan | baked: never relight | tile edges, a tight detail budget, no low angles |
| **modelled site** | Paris | sky above; lit materials; tiled walls; named landmarks | ours: sun, sky, haze | the map edge, per-material detail, roof clearance |
| **set** | the loft | front faces on some sides, void on others; flat backdrop planes | ours | missing walls, cardboard flats, one direction only |

Then:

1. **Normalise:** stand it upright, centre it, put it on the ground.
2. **Identity, front and true size.**
   - Claude looks at six rendered views plus the file's own metadata and
     says, for example, "1903 Wright Flyer, front is +z, real wingspan
     12.3 m".
   - The model is rescaled to its real size, because files arrive at any
     scale. The Smithsonian scan of the Flyer came in at 0.74×.
3. **Parts.**
   - When the file has named nodes (the A380: `wing_L`, `engine0–3`,
     `tail`), each part is shown highlighted and Claude names it.
   - When the file is an unsplit scan (the Flyer: `Object_2…16`, cut into
     chunks of about 65k vertices with no regard for what is what), a part
     is a **region**: a box drawn around the thing. Claude proposes the
     regions from pictures; the creator corrects them by dragging the box.
4. **Look:**
   - Bare scans get a material tint (muslin cream for the Flyer).
   - Missing textures are reported.
   - Huge meshes are simplified.
5. **Credit:**
   - The licence, author and source are read from the file.
   - CC-BY credits are required and go in the description automatically.
   - Non-commercial (NC) licences are flagged, because a monetised channel
     cannot use them.

**Human:** confirm the front, the size and the parts. One click when Claude
got it right; once per model, ever.

The result is the model's **manifest**:

- identity, front, true size, parts and regions, look and credit
- and, from the classification:
  - `kind`
  - `light` (`ours` or `baked`)
  - `detail`: texels per metre for each material
  - `scale_evidence`: the known features used, and how far they agreed
  - **`limits`**: what this model cannot do, for example:
    - `no_low_angles`
    - `aerial_only`
    - `one_direction` (with the valid camera zone)
    - `flats` (with the face-on cone)
    - `edge` (the extent of the tile or map)
    - `soft_ground`

The planner reads `limits` as **what this asset can do**. A shot it asks for
is one the model can deliver. Shots it cannot do are never planned and
then failed.

### 3b. Interiors and other models you stand inside

Some models are not things you look *at* but places you stand *in*: a room,
a cockpit, a cave. The King's Hall (Skokloster Castle, a 1-million-triangle
photogrammetry scan) taught these rules.

- **Classify first, with a depth probe, not raycasts.** From a point, render
  six 64×64 views of signed distance to everything:
  - positive for a surface's front face, negative for a back face, zero for
    nothing
  - six small renders on the GPU instead of millions of ray-triangle tests
    in JavaScript

  From the model's centre:
  - an interior is almost all front faces (walls seen from inside), with no
    void
  - a solid object is back faces (its shell seen from inside it)
- **Identify interiors from inside.** From outside, an interior scan is a
  closed box with holes, so the "what is this?" pictures for Claude are
  taken from eye height within the room.
- **The floor is a median, never one ray.** One ray down from the centre hit
  the table under the chandelier, which made eye height 0.77 m too high.
  Probe a grid and take the median floor height.
- **Choose camera spots by probing a grid at eye height (1.6 m).** Reject
  spots where:
  - back faces are seen (inside a wall or pillar, or outside the room)
  - there is void (holes)
  - something is within about 2 m in the horizontal view (a chandelier, a
    chair back)

  Then prefer spots near the middle of the room. Thin scanned things
  (crystal, rope, foliage) become ragged blobs up close, so they are kept at
  a distance.
- **Interior lens rules (architectural photography):**
  - Keep the camera level. Tilting it makes verticals converge and the walls
    lean.
  - To show a painted ceiling, shift the lens instead (an off-centre frame,
    `setViewOffset`), not the camera.
  - Use about a 78° horizontal field of view. At about 90°, furniture at the
    frame edges stretches.
- **A 360 turns at a steady ~10°/s** with smooth ramps (36 s for a full turn,
  peaking near 12°/s), and starts looking down the room's long axis.
- **Check every heading for holes.** Draw the background in a key colour no
  surface has and count it. Holes in interior scans sit where daylight
  blinded the scanner, in the windows, so the background is set to near-white
  window light. A hole then reads as glare, not a black blot.
- **Scans bring their own light.** Photogrammetry with an *unlit* material
  has the real lighting baked into its photos. The stage's lights, floor and
  shadows do not apply to it, and must not be added.

### 3c. Sites: aerial photogrammetry tiles

The third kind of model, after objects and interiors: a *site*, a scanned
patch of the world like the Westminster Abbey tile (1.5 million triangles, a
~700 m city block, one 4096² texture). The probe classifies it: about half the
directions from the centre see open sky.

**Understanding a site**

- **The subject is a part of the model.** The Abbey is one building among
  dozens. Claude finds it on an orthographic top view with a labelled world
  grid and reads off its extent. Orientation comes from the same picture: the
  cloister on the Abbey's south side fixes north.
- **True size from a known feature, cross-checked against a second.** The
  Abbey's length (~156 m) set the scale, and the western towers (69 m) checked
  it. They disagreed by 13%. When two features disagree by more than 5%, the
  confirm screen shows both and asks.
- **The detail budget.** Texel density is the texture area the surfaces use,
  divided by their world area. Here that is about 28 cm per texel. The budget
  is screen pixels per texel *at the delivered resolution*. A budget computed
  at preview resolution framed previews differently from the final render,
  which must never happen.

**Shooting a site**

- **The tile's edge is the edge of the world.** A frame that shows past it
  shows void. Every sampled frame is checked with a key-colour background.
- **Edge-aware search.** Free parameters: bearing, height, framing, *lens*,
  and (for top-downs) sliding the aim within the slack around the subject.
  - A long lens sees the same subject from further away and far less ground
    beyond it. Here a 16° lens solved what 35° could not.
  - Candidates are tried nearest-first; a quick check on the start and end
    frames rejects most, and the first full pass wins.
- **Priorities, in order:** the subject is whole (never traded), then the edge
  is hidden, then the detail budget. The budget is priced, not absolute: 2 px
  per texel preferred, up to 3.5 allowed at a cost. The shot reports which it
  needed, so the creator knows when a shot is softer than ideal and why.
- **Briefs adapt to the asset.** A wide establishing shot needs context the
  tile may not contain. Here it had to start much tighter than planned, the
  call an editor makes with limited aerial footage.
- **Aerial scans melt near the ground,** so the camera always looks down by
  at least 20°.
- **Last resort, after the checks:** a ground skirt in the tile's median
  colour, and a gentle vignette. Any sliver past the edge reads as ground in
  shade. It is added only after measuring, because the check must see the
  void to measure it.

**Renderer engineering learned here**

- **The render page reports its own errors,** and the server gives up when the
  page goes quiet for 90 s. A syntax error once made a dead page look like a
  slow search for three rounds.
- **Every render gets its own throwaway browser profile.** A crashed run left
  a profile lock that silently blocked the next one.
- **Framing measures about 3,000 sampled points,** not tens of thousands.

### 3d. Modelled cities and scenes

The fourth kind: a *modelled* site, like TerraMesh's Paris (2.2 million
triangles, about 15 × 8.4 km). It has a ground map with one satellite-style
texture, generic extruded buildings with tiled wall textures, and one named
landmark (a 260-triangle Eiffel Tower whose lattice is an alpha texture).

**Understanding**

- **Read the file before rendering anything.**
  - Named nodes say what is in the model (`Eiffel_Tower`), so the subject is
    found by name; a picture confirms it.
  - Lit PBR materials mean the model was built, not scanned, so our sun, sky
    and shadows apply.
- **Detail budget per material, not per model.** Here the budgets differ by
  orders of magnitude:
  - the map: 3.9 m per texel
  - the tower: about 0.4 m per texel
  - the tiled walls: sharp at any distance

  Shots are budgeted on the *subject's* material. The soft ground is managed
  by camera choices: keep it far away, hazed, or out of the bottom of the
  frame.
- **Scale disagreements can be the model's own.** The tower is 401 units tall
  (330 m real) but 245 wide (125 m real): a stylised landmark, not a
  mis-scaled city. The confirm screen shows both and asks.
- **Orientation from a known relationship.** The Trocadéro lies north-west of
  the tower in reality, which fixes north in the model.

**Shooting a modelled city**

- **Hide the map edge with atmosphere, not angles.**
  - The haze is set once per shot, so it is opaque before the map edge in
    every direction the shot looks. It is never changed during a shot, or it
    visibly pumps.
  - The sky is a dome that follows the real horizon, rendered through the
    same tone mapping and colour conversion as everything else. When it
    skipped them, the "same" horizon colour came out two shades and drew a
    pale band with a jagged edge above the city.
- **Haze on the subject is measured, and the shot's purpose sets the limit.**
  - A distant landmark emerging from haze is a good establishing beat
    (allowed up to 60% at the start).
  - Hero shots stay crisp (10%).
- **Clearance is a gate, not a statistic.**
  - A low "heroic" orbit passed 7 m from an office block, which sat cropped
    in the corner like a lens obstruction.
  - The orbit now takes the lowest angle at which the whole path stays at
    least 40 m clear of every roof, measured with the depth probe.
- **City-scale rendering:**
  - Use a logarithmic depth buffer, so distant rooftops do not flicker.
  - Fit shadows to the subject's neighbourhood (about 1.4 km), never the
    whole map.
  - Alpha-tested materials (the lattice) cast lattice shadows.

### 3e. Sets: models built to be seen from one side

The fifth kind: a *set*, like the free "Loft (5)" interior. It is a cutaway
room built for one camera:

- a floor, a beamed ceiling, a brick back wall and a window wall
- **no right wall and no front wall**
- the city outside the windows is three **cardboard flats**

It has a Sketchfab Standard licence, which is not Creative Commons, so the
intake marks it "check the terms" rather than treating it as free.

**Understanding a set**

- **Look from outside on a key colour.** Missing walls and flats are obvious
  in seconds.
- **Not all void is a fault.** Each void pixel's ray is traced: if it leaves
  the room through a window opening it is sky (allowed); anywhere else it is
  a hole in the set (rejected).
- **Scale from everyday objects** when there is no landmark:
  - an armchair is about 0.9 m; a sofa back is about 0.85 m
  - here that gives about 0.5 m per unit
  - eye height comes from that scale, not from guessing

  The first views were taken at what turned out to be seated height.
- **Use what the set gives you.** It had a `Point` node where its author put
  the lamp; that is where our lamp goes. Daylight comes in through its
  windows.

**Shooting a set (the soundstage rules)**

- **Stand where the missing wall would be.** Every shot from the open front
  saw the missing right wall (at best 10.6% of the frame). The solver now
  searches camera spots across the room's own floor, so the missing walls are
  behind the lens.
- **Flats only through glass and near face-on.** Here the limit was within
  about 50°. Seen obliquely, a flat reads as cardboard.
- **No 360s, and nothing that turns toward the open sides.**
- **The motion check tracks the shot's subject, not the whole model.** Points
  leaving the frame made a clean push-in look like a 9-reversal bounce.

### 4. Scenes

A video holds **several scenes**, each with its own models, layout, lighting,
floor and background. A history video needs a workshop for 1903 and a
hangar for 2007, not one world.

Claude proposes scenes from the cast and the story. For this idea:

- **"Hangar lineup":** all eight aircraft at true scale in date order. It
  serves the opening and the finale.
- **One scene per era** for close-ups.

Scenes are built from layout presets (single hero, side by side, lineup,
nose to nose) and looks (lighting preset, lighting map, floor). A scene can
copy another's look so a series stays consistent.

**Human:** approve or edit, in the scene editor.

### 5. Script, written with the manifest

The writer is given every manifest and writes only about what can be shown:

- "The 12-horsepower engine sat beside the pilot": the Flyer has an engine
  region, so this can be shot.
- A sentence that needs a model not in the cast either goes, or becomes a
  photo or card.

Each paragraph carries a rough visual intent ("compare the engines",
"reveal the scale") for the shot planner.

### 6. Voice

The existing takes system, unchanged. Shots are planned against the
confirmed narration, because their lengths come from it.

### 7. Shot planning

For every paragraph Claude writes:

- the shots: scene, subject (a model, part or region), shot type, framing
  and move
- the **join** into each shot
- the inserts the models cannot do: title cards, chapter screens, photos
  (Kitty Hawk, 17 December 1903), and labels that track a part on screen

The AI writes **intent**, never coordinates: "slow orbit of the engine from
behind, tight", not a camera position.

Shot types:

| shot | what it does |
|---|---|
| `static` | a fixed framing |
| `orbit` | a slow circle around the target |
| `closeup` | the frame filled with a part or region |
| `push` / `pull` | dolly in toward, or out from, a target |
| `pan` | a glide from one part to another |
| `crane` | rise or fall while looking at the target |
| `reveal` | from hidden to clear |

Joins:

| join | when |
|---|---|
| hard cut | the default between shots: a new subject or a new point |
| match cut | comparisons: the same framing and move on a different subject |
| continuous move | when the spatial relationship is the point (the Flyer-to-A380 reveal) |
| dissolve | the passing of time within a chapter |
| dip to black / chapter card | a change of chapter or scene |

### 8. Solve and check (code, not AI)

The solver turns intent into a camera path, and the checker refuses a bad
one.

**The search engine** (the same for every kind of model):

- A shot's free parameters are bearing, height, framing, lens, aim slide,
  camera spot and detail level.
- Candidates are sorted nearest-first from the planner's intent.
- Each candidate gets a quick check on its first and last frames, then a full
  check (start, quarters and end) only if it survives.
- **The first candidate that passes wins.** When none passes, the best one
  that keeps the subject whole is used and flagged.
- **Priorities, in order:**
  1. the subject is whole
  2. no holes, edges or missing walls
  3. clearance
  4. the detail budget (priced, not absolute)
  5. closeness to the preferred framing
- Every shot reports what it had to give up ("3 px per texel, softer than
  ideal").

**The checks:**

| check | how | learned from |
|---|---|---|
| framing | about 3,000 sampled vertices, never boxes | the Flyer's off-centre three-quarter view |
| motion | walk the path: at most 1 reversal per axis; the *subject* never reverses on screen; turning ≤ 20°/s | the bouncing reveal; the loft push-in |
| occlusion | flat-colour GPU passes, clipped to a region | the Flyer's rudder |
| holes and edges | key-colour background; void rays traced through windows count as sky | the Abbey tile; the loft's missing walls |
| clearance | depth probe along the path; a gate, not a statistic | the office block in the Paris orbit |
| detail | pixels per texel of the *subject's* material at the delivered resolution | the Abbey; Paris' 3.9 m ground |
| haze | amount on the subject; the limit is set by the shot's purpose | Paris' establishing shot |
| jump cuts | the same subject needs ≥ 30° or a change of size | the engine comparison |

**The rules, each learned the hard way:**

- **Frame the geometry, not the bounding box.** Framing measures a few
  thousand sampled vertices. A box's empty corners pushed a three-quarter
  view of the Flyer off centre.
- **Solve once, then move on one curve.** A shot's start and end framings
  are solved once. Every parameter (angle, height, log-distance, aim point)
  then travels one way on a single ease curve. Re-solving the camera on
  every frame made it bounce: up, down and up again.
- **The aim point follows the distance, not the clock.** On a pull-back the
  aim barely moves while the camera is close, so the subject stays in frame
  by design rather than by correction.
- **Motion check before any frame is drawn.** Walk the path and reject:
  - more than one velocity reversal per axis
  - any reversal of the subject's on-screen motion
  - turning faster than 20°/s
- **Occlusion on the GPU.** Draw the target flat red and everything else
  black, then the target alone, and compare pixel counts. For a region, the
  red pass is clipped to its box. The check runs on a path's start, middle
  and end, not just its first frame.
- **Angle search.** Try bearings around the preferred one and keep the
  nearest that sees enough of the target and stays clear of the geometry.
- **Flag, don't fail.** When no angle passes (an open-frame machine of
  struts and wires is never 85% visible), take the best one and flag it
  amber for a human. Never refuse silently, and never render a bad shot
  silently.
- **Clipping planes are part of the shot.** The far plane must reach past
  the floor's fade, or the floor is cut into a false horizon.
- **No jump cuts.** Two shots of the same subject from nearly the same angle
  are never hard-cut together. The planner moves the angle by about 30° or
  picks another join.

A shot that fails goes back to Claude once, with the reason. If it still
fails, it is flagged amber or red.

### 9. Review

- Claude looks at a contact sheet (start, middle and end of each shot).
- The scene editor shows each shot with its check badge.
- **Human:** fix the flagged shots with *set from view* or a nudge. Edited
  shots are locked, so re-planning never overwrites them.
- Preview plays one section live in the editor, which costs nothing.

### 10. Render and publish

- **Render:** headless Chromium runs the same scene code as the editor and
  sets time directly, so every frame is reproducible.
  - The page posts raw frames to the app's own server, which pipes them into
    ffmpeg. There is no Playwright and no browser remote control.
  - The spike measured about 40 fps at 1080p on a Radeon 780M through
    Vulkan.
  - Chunks never span two scenes.
  - Output joins the existing pipeline: GPU encode, stings, music bed and
    chapter screens.
- **Publish:** the description generator adds the model credits.

## Where a human is needed

Four checkpoints, each meant to take seconds:

1. Choose the cast.
2. Pick the models.
3. Confirm each *new* model's front, size and parts.
4. Fix the flagged shots.

## In the app

- Choosing **3D explainer** adds two tabs, which no other format shows:
  - **Cast:** the video's models, chosen from the library.
  - **Stage:** the scene editor and shot list (to be built).
- **Media stays.** A 3D explainer still has pictures and slides between its
  3D shots (the Kitty Hawk photo, a period newspaper). Once the shot list
  exists, it decides which paragraphs are 3D and which are pictures, and
  Media holds the pictures.
- **3D models** are a section of the shared Library (`assets/models/`), like
  the stock library and the music folder. Each model is one folder holding
  `model.glb`, `manifest.json` and `thumb.jpg`.
- Only GLB is accepted: one file, textures inside, loaded natively by
  three.js.
- three.js 0.170.0 is vendored in `static/vendor/three/` with the four
  add-ons it needs. The scene code lives in `static/stage/` and is shared by
  the editor, the library viewer and (later) the renderer.

## Status (21 October 2026)

**In the app** (uncommitted):

- the 3D model library: `app/models3d.py`, the `/api/models` routes and
  `assets/models/`
  - reads GLB credits, licence terms, counts and named parts
  - refuses a model that is in use from being deleted
- the confirm-model screen:
  - a three.js viewer with a front arrow and a 1.8 m figure
  - turn, true size from one real dimension, flat tint for bare scans
  - auto measurement and thumbnail
- the **3D explainer** format tile, and a **Cast** tab only for that format
  (Media stays)
- model credits in the generated description (CC-BY required, CC0 omitted)
- rendering a 3D explainer stops with a plain "not built yet" message
- `static/stage/core.js`: the first port of the spike (loading,
  set, framing, motion, occlusion, angle search)
- **Intake v2** (`static/stage/probe.js`, `static/stage/intake.js`):
  - **Classification:** each model is classified on first open with the GPU
    depth probe and its materials. All six test models classify correctly,
    in under 0.4 s each.
  - **Measurements:** scan or built, baked or ours, texel density per
    material, top coverage, and floor, ceiling and the room's own centre for
    interiors and sets.
  - **Limit codes:** saved in the manifest's `analysis`, with `kind` as
    the creator's override.
  - **The confirm screen** has a "What it is" section: the kind
    (changeable), the facts, the limits as sentences, and a room-height
    sanity check with a one-click fix (it caught the loft's 0.5 m units).
  - **Rooms and sets open from inside,** at eye height: an interior down its
    long axis, a set from its open side. Thumbnails are taken the same way.
  - **Re-analysis:** bumping `VERSION` in `intake.js` re-analyses every model
    on its next open.

- **Identification by Claude** (`static/stage/identify.js`, `app/identify.py`,
  `POST /api/models/{id}/identify`):
  - **Pictures chosen for the kind:**
    - objects: six labelled views
    - interiors: four views from inside
    - sets: the same, plus one from outside
    - sites: a 1280-pixel top view with a labelled grid, plus an oblique view
  - **Suggestions:** name, front, up to two published or typical sizes, and
    for sites the subject's box and north. Each is applied only by the
    creator's click; two sizes that disagree by more than 5% get a warning.
  - **Images on every backend:** `llm.py` can now send images through all
    three. The CLI gets them as stream-json input, so it never reads a file.
  - **Results on the six test models:**
    - every name is right
    - both fronts are right
    - published sizes for the A380 and the Flyer
    - typical room heights for the hall and the loft
    - the Abbey and the Eiffel Tower are both placed by their boxes
    - the disagreements are flagged: the Abbey's length against its tower
      (9%), and the stylised Eiffel Tower's height against its base (71%)

  - **Part names from pictures.** Each named part is highlighted in a
    numbered tile, six to a sheet. Where it sits is measured relative to the
    model's own front (side, fore and aft, height). Claude names parts from
    both, and takes left and right from the measurement, never from the
    picture. All eleven A380 parts are right, including the four engines
    (left and right, inboard and outboard).
- **Regions by hand.** The confirm screen has a Regions section: add,
  select, move or size with handles (three.js `TransformControls`, now
  vendored), rename, delete.
  - Boxes live in the model's own file units, so they follow its scale and
    heading.
  - A site's subject from Claude becomes the same kind of box.
  - For an unsplit scan, regions are how its parts exist; the Flyer's engine
    and propellers is one.

  Identification lessons:
  - **Tell Claude what intake already measured** (the kind, scan or built,
    the named parts). Without it, Claude called the modelled Paris a scan and
    picked the Tuileries over the file's own `Eiffel_Tower`.
  - **Locate coarse-to-fine.** The first answer from the whole tile is only
    roughly right. A second, zoomed, finer-gridded view draws the box tight.
  - **The measure must match the feature.** "Tower height 69 m" first came
    back as an x-extent. Heights are now `subject_height`, measured from the
    model's points inside the subject's box.

  Classification lessons:
  - **Judge sides at eye level only.** A biplane between its wings has a
    "floor" and a "ceiling" too, but no wall.
  - **Probe a room from halfway up,** above the furniture.
  - **Find a room's middle from where its floor is,** not from its bounding
    box, which backdrops can stretch onto a wall.

**Proven in the spike only** (scratchpad pages, to be rebuilt in the app):

- the depth probe
- holes and edge checks with window tracing
- the edge-aware search with lens and detail levels
- haze, sky dome and ground skirt
- clearance gates
- interior lens shift and 360s
- per-material detail budgets
- the headless render loop: about 30–40 fps at 1080p on a Radeon 780M

**Not tested anywhere yet:**

- the app's own window (WebKitGTK) running the viewer
- rendering on a Mac
- models with animation
- vehicle interiors (cockpits)
- tiny objects

## Next steps

In order. Each step ends with something you can use or watch.

1. **Commit what exists.** The library, the Cast tab, the doc and the
   vendored three.js.
2. **Intake v2: classify and measure.** *Mostly done* (see Status). Still
   to do from this step: the second known feature for sites and objects, the
   site's extent and ground height, and a holes measure for interiors.
   The original scope was:
   - the depth probe
   - the kind (the table in step 3)
   - texel density per material
   - eye height and floor for interiors
   - the extent for sites
   - scale evidence from two features, with a disagreement warning
   - licence handling for non-CC licences ("check the terms")

   The confirm screen shows what was found and the limits it implies.
3. **Identification by Claude, per kind.** *Done* (see Status), including
   part names from highlighted pictures and region boxes by hand. Still
   open: Claude *proposing* regions for an unsplit scan, rather than only a
   site's subject. The original scope was:
   - objects: six views and highlighted parts
   - interiors: views from inside
   - sites: a gridded top view, for the subject's region and north
   - sets: outside views on a key colour

   Regions become boxes you can drag. This replaces "parts and regions" in
   the earlier order.
4. **The solver library.** Port the spike's checks and search engine into
   `static/stage/`. Run the pure parts (framing, motion, paths) under
   Node tests.
5. **The six test models become a regression suite.** One command renders
   each model's reference shots at preview size and records:
   - the check numbers
   - a contact sheet

   A change that moves a number, or makes a sheet worse, is visible before
   it ships. This is the 3D equivalent of the SSIM check the 2D renderer
   already uses.
6. **Renderer integration.**
   - A render page served by the app, which posts frames to a FastAPI
     endpoint and on into `ffutil`'s GPU encode.
   - The watchdog, page error reporting and a fresh browser profile per run.
   - Chunks per scene.
   - Joins through the existing xfade chain.
   - The looks: our light, or baked; haze and sky; skirt.
7. **The Stage tab:** scenes and a shot list with hand-made plans.
   - check badges
   - set-from-view
   - one-section live preview
   - locked edits
8. **The shot planner.** Claude writes intent per paragraph, constrained by
   each manifest's `limits`. The solver fills in the shot, and it goes back
   to Claude once on failure.
9. **The manifest-aware script writer.** It only writes what the cast can
   show.
10. **Model search** (step 2): Smithsonian and Sketchfab first.

**Open risks:**

- **Search time.** The Abbey took about a minute per shot. It can run in
  parallel, and most of it is the candidates' quick checks.
- **GPU memory for big scans.** 180 MB loaded fine here, but a 16k
  texture would not.
- **Platforms.** Headless Chrome on macOS and Windows is untested.
