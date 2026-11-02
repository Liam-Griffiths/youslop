"""Plan metadata lives in the existing outline; section writers stay unchanged."""
from copy import deepcopy
import time

from . import script_gen, store
from .schema import Slide


def outline_for(project):
    outline = deepcopy(project.outline or project.draft.get('outline') or {})
    for i, section in enumerate(outline.get('sections', [])):
        section.setdefault('id', f'b{i}')
        section.setdefault('heading', f'Beat {i + 1}')
        section.setdefault('summary', '')
        section.setdefault('words', 220)
        section.setdefault('kind', 'main')
        section.setdefault('chapter', section.get('heading', 'Chapter'))
    return outline


def content(section, outline):
    value = {key: section.get(key) for key in ('heading', 'summary', 'words', 'kind', 'sources')}
    value['thesis'] = outline.get('thesis')
    if section.get('kind') == 'intro':
        value['hook'] = outline.get('hook')
    return value


def save(project, outline):
    if not isinstance(outline, dict) or not isinstance(outline.get('sections'), list):
        raise ValueError('Outline needs a sections list.')
    for key in ('chapters',):
        if not isinstance(outline.get(key, []), list) or any(not isinstance(c, str) for c in outline.get(key, [])):
            raise ValueError('Chapter labels must be text.')
    if not isinstance(outline.get('hook', {}), dict):
        raise ValueError('Hook must be an object.')
    if not isinstance(outline.get('sources', []), list) or any(
            not isinstance(s, dict) or any(not isinstance(v, str) for v in s.values())
            for s in outline.get('sources', [])):
        raise ValueError('Sources must contain text fields.')
    sections = outline['sections']
    ids = [s.get('id') for s in sections if isinstance(s, dict)]
    if (len(ids) != len(sections) or any(not isinstance(i, str) or not i for i in ids)
            or len(set(ids)) != len(ids) or len(ids) > 100):
        raise ValueError('Beats need unique text IDs (at most 100).')
    for section in sections:
        if (section.get('kind') not in ('intro', 'main', 'conclusion')
                or not isinstance(section.get('words'), int) or not 1 <= section['words'] <= 10000
                or any(not isinstance(section.get(k, ''), str) for k in ('heading', 'summary', 'chapter'))
                or not isinstance(section.get('sources', []), list)
                or any(not isinstance(s, str) for s in section.get('sources', []))):
            raise ValueError('Invalid beat fields.')
    old_outline = outline_for(project)
    old = {s['id']: s for s in old_outline.get('sections', [])}
    if old.keys() - set(ids):
        raise ValueError('Keep existing beats; removing them could orphan recordings.')
    clean = deepcopy(outline)
    for section in clean['sections']:
        previous = old.get(section['id'], {})
        section.pop('_script', None)
        if '_script' in previous:
            section['_script'] = previous['_script']
        elif previous:
            slides = [s.id for s in project.slides if s.beat == previous.get('heading')]
            section['_script'] = {'content': content(previous, old_outline), 'ids': slides}
        else:
            section['_script'] = {'content': None, 'ids': []}
    project.outline = clean
    if project.draft:
        project.draft['outline'] = deepcopy(clean)
        # Index-keyed draft paragraphs must follow their beat when reordered.
        bank = project.draft.get('sections', {})
        old_positions = {sid: i for i, sid in enumerate(old)}
        project.draft['sections'] = {str(i): bank[str(old_positions[s['id']])]
            for i, s in enumerate(clean['sections']) if s['id'] in old_positions
            and str(old_positions[s['id']]) in bank and content(s, clean) == content(old[s['id']], old_outline)}


def write(pid, progress):
    """Generate changed beats outside the lock; refuse a concurrent edit on apply."""
    with store.lock_for(pid):
        project = store.load(pid)
        original = project.to_dict()
    outline = outline_for(project)
    if not outline.get('sections'):
        raise ValueError('Add a beat before writing the script.')
    by_id = {s.id: s for s in project.slides}
    result = []
    for i, section in enumerate(outline['sections']):
        baseline = section.get('_script')
        existing = ([by_id[sid] for sid in baseline['ids'] if sid in by_id] if baseline
                    else [s for s in project.slides if s.beat == section.get('heading')])
        unchanged = baseline is None or baseline['content'] == content(section, outline)
        if existing and unchanged:
            slides = existing
        else:
            banked = project.draft.get('sections', {}).get(str(i))
            paragraphs = banked or script_gen._write_section(project, outline, i)
            slides = [Slide(section=p['kind'], beat=p['beat'], narration=p['text'],
                            visual_note=p['visual'], on_camera=project.delivery == 'on_camera')
                      for p in paragraphs]
            if not slides:
                raise ValueError('Beat produced no paragraphs.')
            # Keep all retired voices, camera takes and history attached to the new beat.
            for old in existing:
                slides[0].history.extend(deepcopy(old.history))
                takes = old.takes or ({'legacy': old.take} if old.take else {})
                slides[0].history.extend({**deepcopy(take), 'track': track,
                    'narration': take.get('narration', old.narration),
                    'retired_at': time.time(), 'reason': 'plan rewrite'} for track, take in takes.items())
        section['_script'] = {'content': content(section, outline), 'ids': [s.id for s in slides]}
        result.extend(slides)
        progress(f'Beat {i + 1}/{len(outline["sections"])} ready')
    used = {sid for s in outline['sections'] for sid in s['_script']['ids']}
    replaced = {sid for s in project.outline.get('sections', [])
                for sid in s.get('_script', {}).get('ids', [])}
    # Imported/unmatched paragraphs remain reachable, including all their recordings.
    result.extend(s for s in project.slides if s.id not in used and s.id not in replaced)
    with store.lock_for(pid):
        fresh = store.load(pid)
        if fresh.to_dict() != original:
            raise ValueError('Project changed while writing. Retry from the current board.')
        fresh.outline, fresh.slides, fresh.draft = outline, result, {}
        fresh.status = 'scripted'
        store.save(fresh)
    return {'slides': len(result)}
