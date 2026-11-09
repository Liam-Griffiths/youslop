# Phase 18: scripts that sound like a person

Owner, 2026-11-09: "I want a more natural script. AI likes overly dramatic
sentence structures: rule of three with short impact sentences. It's really
off-putting when you hear it over and over. Real people have longer sentences,
and not every sentence has to be a dramatic impact sentence. Also talking about
things in an overly stylised way is off-putting: 'here's the inside scoop!',
'he didn't know it was only the start!'. These read like a 12-year-old's
creative writing project, not witty, slick script writing."

## Root cause, in our own prompt
`NARRATOR_SYSTEM` in `app/script_gen.py` says "Write for the ear. Short
declarative sentences. One idea per sentence." That rule asks for the staccato
the owner hears. The banned-phrase list is a handful of literal strings, so the
model writes the same moves in new words.

## The target voice
A well-read person explaining something they find interesting to a smart
friend:
- Sentences vary. Most are medium, some are long with a clause that carries a
  detail, and a short one lands only where it earns it.
- Lists come in whatever number the facts have.
- Transitions come from the logic of the story, not from teasers.
- Wit comes from precise detail and understatement, not from exclamation or
  foreshadowing.
- References for register: good radio documentary and long-form podcast
  narration, or a confident magazine feature read aloud.

## Tickets
| | |
|---|---|
| T18.1 | Narration voice: rewrite the rules, and add a style lint |
| T18.2 | Revise flagged lines: an optional targeted rewrite pass |
