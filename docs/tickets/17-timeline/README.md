# Phase 17: an edit timeline you can actually edit on

Owner, 2026-11-09: "make the timeline more usable. Moving clips around,
extending and shrinking clips, moving everything to insert more stuff (imagine
moving the whole timeline to add a short clip after the intro). Adding blocks."

## Where it stands
Phase 4 gave the Edit stage layer rows, one selection with an inspector, drag
and resize for titles, cues, gaps and chapter holds (T4.5), and a razor that
keeps audio (T4.6). Sponsor slots (Phase 10) are inserted between paragraphs
and everything after them moves later.

What's missing is editing the main track itself. The order and length of
pictures come only from the script and the takes. You cannot drop a clip, a
block or a picture between two paragraphs, drag paragraphs into a new order,
or stretch a picture past its line. There is no undo. A short project also
opens zoomed so far out that items are a few pixels wide.

## Model: a magnetic main track
The paragraph sequence is the main track, the same idea as Final Cut Pro's
primary storyline or CapCut's main track. Anything placed on it pushes
everything after it later (ripple). Titles, overlay blocks, cues and chapters
stay attached to their paragraph, in paragraph-relative seconds as they already
are, so they move with it. That keeps the existing data model and the existing
anchors working: an insert is one more item in the sequence, not a new
free-form track.

## Inspiration
- **Final Cut Pro, the magnetic timeline:** the closest match. Connected clips
  ride on the primary storyline; insert, append and overwrite edits.
- **CapCut:** main-track auto-close, drag from a media panel straight onto the
  track, and a split/duplicate/delete toolbar over the selection.
- **Descript:** edit by text, and "scenes" as the unit you reorder. Our script
  is already the source of truth.
- **Kdenlive and Shotcut:** ripple, roll and slip trims, and the keyboard
  model (J/K/L, I/O, trim-to-playhead).
- **DaVinci Resolve's cut page:** "smart insert" at the nearest edit point to
  the playhead.
- **OpenCut** (open source, a web CapCut alternative): for UI patterns. It's
  React, so ideas only, no code.

## Libraries
The no-build, no-Node rule holds: plain script tags, vendored single files with
licences in `THIRD-PARTY.md`.
- **interact.js** (MIT, one UMD file): drag, resize, snap and restrict
  modifiers for DOM elements. Optional. T4.5's pointer code already works, and
  the hard part here is the data model, not the pointer events. Adopt it only
  if a ticket's drag code would otherwise grow past about 150 lines.
- **wavesurfer.js v7** (BSD-3, UMD build): a voice waveform lane, if T17.7 wants one.
- Not suitable: vis-timeline (built for calendars, heavy styling); React
  timeline editors (they need a build step).

## Tickets
| | |
|---|---|
| T17.1 | Undo and redo for project edits |
| T17.2 | Inserts on the main track: model, timing and render |
| T17.3 | Insert from the timeline: the + at every edit point, drop from panels |
| T17.4 | Select sections and move everything in them (move, cut, copy, paste, duplicate, delete) |
| T17.5 | Extend and shrink: picture tails, insert lengths, clip trims |
| T17.6 | Blocks and graphics on the timeline: drop, duplicate, copy, nudge |
| T17.7 | Timeline ergonomics: fit zoom, wheel zoom, lanes, multi-select |

Order: T17.1 first (undo makes the rest safe to try), then T17.7, T17.2,
T17.4 (the owner's priority: "selecting sections, everything, and moving
them"), T17.3, T17.5, T17.6.
