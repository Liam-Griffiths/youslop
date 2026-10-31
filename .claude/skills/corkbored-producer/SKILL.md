---
name: corkbored-producer
description: Plan, check, snapshot and review Corkbored videos from this repository's CLI, propose targeted storyboard fixes, preview sections and publish rendered videos.
---

Use for producing or correcting a Corkbored episode. Run commands from the
repository with `.venv/bin/python -m app.cli`. The CLI routes supported operations
through HTTP jobs while the app is open; otherwise it blocks in-process.
Progress goes to stderr. Use the id printed by `new` in subsequent commands.
`--test` selects one minute and quick research; it still calls the configured LLM.

1. `new "A specific video idea" --test` (omit `--test` for production).
   Creation already researches, writes and gathers media. Inspect its output.
2. `plan PID` resumes script generation; use only when generation needs work.
   `research PID` refreshes the dossier when sources need work.
3. `storyboard PID --json` and `check PID --json`. Resolve P0 findings first.
4. `snapshot PID --sheet`, then `review PID --json`. Targeted review is the
   default. Use `review PID --full` only when the user asks for a full review.
5. Describe each shot as a stranger sees it: literal content, readability,
   timing and meaning. Give no score. Fix P0 first, then P1, then P2;
   within a severity start at the earliest time. Name the weakest shot.
6. `fix PID NOTE_ID` proposes a change. Inspect it before `fix PID NOTE_ID --apply`.
   Picture searches require choosing a result; unsupported fixes need manual work.
   Re-check and review affected shots after applying a fix.

Read [motion defaults](references/motion.md) before changing pacing or camera
choices. Read [storyboard patches](references/storyboard.md) before writing an
`apply PID PATCH.json` patch. `apply` and `ask` currently require the app closed.
Regenerate both references with `doctrine --write` when their Python sources change.

7. `render PID --section SID` previews one section at quarter size. A full render
   requires an explicit user request and `render PID --full --yes`; `--force`
   overrides the P0 gate only when explicitly intended.
8. `publish PID --channel CID --privacy private` uploads the existing render.
   Confirm the intended channel and privacy with the user. The channel must match
   the project's channel and already be connected through OAuth in the UI.
   Privacy defaults to private; public and unlisted require an explicit choice.
   Optional metadata: `--title`, `--description`, repeated `--tag`, `--category-id`.
