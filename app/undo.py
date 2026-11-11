"""Bounded project snapshots. Call under store.lock_for; never touch media."""
from contextvars import ContextVar
from copy import deepcopy
import gzip
import json
import time

edit_source = ContextVar('project_edit', default=None)
MAX_ENTRIES = 100
MAX_BYTES = 50 * 1024 * 1024


def encode(value):
    return json.dumps(value, indent=2, ensure_ascii=False)


def read(root):
    path = root / 'history' / 'index.json'
    history = json.loads(path.read_text()) if path.exists() else {'states': [], 'cursor': 0}
    if any('payload' in state for state in history['states']):
        # The unshipped, monolithic format is safe to discard. Project/media
        # files are unaffected, including all retained recording references.
        history = {'states': [], 'cursor': 0}
        write(root, history)
    return history


def snapshot_path(root, state):
    return root / 'history' / f"{int(state['seq'])}.json.gz"


def snapshot(root, state):
    return json.loads(gzip.decompress(snapshot_path(root, state).read_bytes()))


def save_snapshot(root, state, payload, before=None):
    from .store import atomic_write
    document = {'payload': payload}
    if before is not None:
        document['before'] = before
    compressed = gzip.compress(json.dumps(document, ensure_ascii=False).encode(), compresslevel=1, mtime=0)
    (root / 'history').mkdir(exist_ok=True)
    atomic_write(snapshot_path(root, state), compressed)
    state['bytes'] = len(compressed)


def write(root, history, discarded=()):
    from .store import atomic_write
    removed = list(discarded)
    states = history['states']
    size = sum(state['bytes'] for state in states)
    while states and (len(states) > MAX_ENTRIES + 1 or size > MAX_BYTES):
        if history['cursor']:
            removed.append(states.pop(0))
            history['cursor'] -= 1
        else:
            removed.append(states.pop())
        size -= removed[-1]['bytes']
    folder = root / 'history'
    folder.mkdir(exist_ok=True)
    atomic_write(folder / 'index.json', encode(history))
    for state in removed:
        snapshot_path(root, state).unlink(missing_ok=True)


def rebase(target, before, after):
    """Carry only a non-user write's changed fields into the destination."""
    if before == after:
        return target
    if all(isinstance(v, dict) for v in (target, before, after)):
        out = deepcopy(target)
        for key in before.keys() | after.keys():
            if key in before and key in after and before[key] == after[key]:
                continue
            if key not in after:
                out.pop(key, None)
            elif key not in before or key not in out:
                out[key] = deepcopy(after[key])
            else:
                out[key] = rebase(out[key], before[key], after[key])
        return out
    if all(isinstance(v, list) for v in (target, before, after)) and all(
            isinstance(item, dict) and item.get('id') for seq in (target, before, after) for item in seq):
        old, new = ({i['id']: i for i in seq} for seq in (before, after))
        out = [rebase(i, old[i['id']], new[i['id']]) if i['id'] in old and i['id'] in new else i
               for i in target if i['id'] not in old or i['id'] in new]
        out.extend(deepcopy(i) for i in after if i['id'] not in old and i['id'] not in {x['id'] for x in out})
        if list(old) != list(new):
            order = {sid: n for n, sid in enumerate(new)}
            out.sort(key=lambda item: order.get(item['id'], len(order)))
        return out
    return deepcopy(after)


def remember(root, before, after, source):
    if not before or before == after:
        return
    history = read(root)
    states, cursor = history['states'], history['cursor']
    if source:
        label, gesture = source
        now = time.time()
        coalesce = (cursor == len(states) - 1 and cursor > 0 and gesture
                    and states[cursor]['gesture'] == gesture
                    and states[cursor]['label'] == label and now - states[cursor]['time'] < 1)
        seq = max((state['seq'] for state in states), default=-1) + 1
        if not states:
            states.append(dict(seq=seq, label='', gesture='', time=0))
            save_snapshot(root, states[0], before)
            seq += 1
        baseline = snapshot(root, states[cursor])
        discarded = states[cursor + 1:]
        del states[cursor + 1:]
        entry = dict(seq=seq, label=label, gesture=gesture, time=now)
        if coalesce:
            entry['seq'] = states[cursor]['seq']
            checkpoint = baseline.get('before')
            states[cursor] = entry
        else:
            # Usually the previous snapshot is exactly the pre-edit file.
            # After jobs or restore it may differ: keep that edge's baseline
            # locally, rather than rewriting the rest of the history.
            checkpoint = before if baseline['payload'] != before else None
            states.append(entry)
            history['cursor'] = len(states) - 1
        save_snapshot(root, entry, after, checkpoint)
        write(root, history, discarded)
    elif states:
        # Worker saves never read or rewrite compressed snapshots.
        if states[cursor]['gesture']:
            states[cursor]['gesture'] = ''
            write(root, history)


def recordings(data):
    """Yield owner type/id and complete take metadata, including retired takes."""
    from .schema import take_track
    for kind in ('slides', 'sponsors'):
        for owner in data.get(kind, []):
            takes = dict(owner.get('takes') or {})
            if owner.get('take'):
                takes.setdefault(take_track(owner['take']), owner['take'])
            for track, take in takes.items():
                yield kind, owner['id'], dict(take, track=track, narration=take.get('narration', owner.get('narration', '')))
            for take in owner.get('history', []):
                yield kind, owner['id'], take
    for take in data.get('retired_takes', []):
        yield take['owner_kind'], take['owner_id'], take
    if data.get('mic_test', {}).get('path'):
        yield 'mic_test', '', dict(data['mic_test'], track='mic')


def retain_recordings(target, current):
    def identity(kind, sid, take):
        return kind, sid, take.get('path'), take.get('raw_path'), take.get('video_path')
    known = {identity(k, sid, t) for k, sid, t in recordings(target)}
    changed = False
    for kind, sid, take in recordings(current):
        key = identity(kind, sid, take)
        if key in known or not take.get('path'):
            continue
        retired = dict(deepcopy(take), reason='undo', retired_at=take.get('retired_at') or time.time())
        owner = next((s for s in target.get(kind, []) if s['id'] == sid), None) if kind != 'mic_test' else None
        if owner is not None:
            owner.setdefault('history', []).append(retired)
        else:
            target.setdefault('retired_takes', []).append(dict(retired, owner_kind=kind, owner_id=sid))
        known.add(key)
        changed = True
    return changed


def restore(root, direction):
    from .store import atomic_write
    history = read(root)
    states, cursor = history['states'], history['cursor']
    dest = cursor + (-1 if direction == 'undo' else 1)
    if not states or not 0 <= dest < len(states):
        raise ValueError(f'Nothing to {direction}')
    label = states[cursor if direction == 'undo' else dest]['label']
    origin = snapshot(root, states[cursor])
    destination = snapshot(root, states[dest])
    if direction == 'undo':
        payload = origin.get('before', destination['payload'])
        baseline = origin['payload']
    else:
        payload = destination['payload']
        baseline = destination.get('before', origin['payload'])
    target = json.loads(payload)
    current = json.loads((root / 'project.json').read_text())
    rebased = rebase(target, json.loads(baseline), current)
    retained = retain_recordings(rebased, current)
    if retained or rebased != target:
        target = rebased
        payload = encode(target)
    atomic_write(root / 'project.json', payload)
    states[dest]['gesture'] = ''
    history['cursor'] = dest
    write(root, history)
    return label
