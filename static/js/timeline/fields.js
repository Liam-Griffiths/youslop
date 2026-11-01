// Slide PATCH fields used by the inspector; mirrored in test_inspector_fields.py.
// Cue subfields travel inside `cues`; focal coordinates travel inside `focal`.
const TL_FIELDS = {
  paragraph: ['gap_override'],
  title: ['title', 'title_at', 'title_hold'],
  cue: ['cues'],
  chapter: ['chapter', 'chapter_hold'],
  picture: ['title', 'focal'],
};
