"""Small, advisory layer plans; model work never runs under a project lock."""
import hashlib
import json
import uuid

from . import channels, layers, llm, store
from .edits import EditError
from .schema import Layer, LAYER_ROLES


def fingerprint(project):
    raw = project.to_dict()
    for key in ('updated_at', 'log', 'layer_proposal'):
        raw.pop(key, None)
    return hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest()


def validate(value):
    # JSON-mode models (LM Studio, Ollama) return objects, not bare lists.
    if isinstance(value, dict):
        value = value.get('layers')
    if not isinstance(value, list) or len(value) > 16:
        raise ValueError('Expected a short list of layers.')
    entries = [dict(name=e['name'].strip(), role=e['role'], why=e['why'].strip())
               for e in value if isinstance(e, dict) and e.get('role') in LAYER_ROLES
               and all(isinstance(e.get(k), str) and e[k].strip() for k in ('name', 'why'))
               and len(e['name'].strip()) <= 24 and len(e['why']) <= 240]
    if not 3 <= len(entries) <= 8:
        raise ValueError('Expected 3–8 valid layers.')
    for role in ('pictures', 'voice'):
        if sum(e['role'] == role for e in entries) > 1:
            raise ValueError('Pictures and Voice each use one main track.')
    return entries


def suggest(pid, progress):
    with store.lock_for(pid):
        project = store.load(pid)
        baseline, previous = fingerprint(project), project.layer_proposal
    if not project.slides or project.draft:
        return {}
    try:
        # Bound context, including imported scripts without an outline.
        channel = channels.load_or_none(project.channel_id)
        context = dict(format=project.style.format,
            channel=dict(name=channel.name[:80], tone=channel.tone[:160]) if channel else None,
            outline=dict(thesis=str(project.outline.get('thesis', ''))[:500], sections=[
                {k: str(section.get(k, ''))[:240] for k in ('heading', 'summary', 'kind')}
                for section in project.outline.get('sections', [])[:24]]),
            beats=[dict(beat=s.beat[:80], words=s.narration[:160]) for s in project.slides[:24]])
        progress('Suggesting layers')
        entries = validate(llm.complete_json(
            'Suggest 3–8 timeline layers. Return only JSON: {"layers": [{name, role, why}]}. '
            'Names at most 24 characters; short reasons. Use only these roles: '
            + ', '.join(LAYER_ROLES) + '. One Pictures and one Voice at most.\n'
            + json.dumps(context), model=llm.MODEL_UTILITY, timeout=90, retries=0))
        with store.lock_for(pid):
            fresh = store.load(pid)
            if fingerprint(fresh) != baseline or fresh.layer_proposal != previous:
                progress('Layer suggestion skipped: project changed; suggest again.')
                return {}
            fresh.layer_proposal = dict(id=uuid.uuid4().hex, base=baseline, entries=entries)
            store.save(fresh)
        progress('Layer proposal ready in Edit')
        return {'proposal': fresh.layer_proposal['id']}
    except Exception as exc:  # Advisory failures belong only in the job log.
        progress(f'Layer suggestion skipped ({str(exc)[:100]})')
        return {}


def decide(project, payload):
    proposal = project.layer_proposal
    if not proposal or payload.get('proposal') != proposal.get('id'):
        raise EditError('Layer proposal changed; refresh Edit.', 409)
    if payload['op'] == 'dismiss_proposal':
        project.layer_proposal = {}
        return
    if fingerprint(project) != proposal.get('base'):
        raise EditError('Project changed; suggest layers again before applying.', 409)
    for track in layers.effective(project, items={}):
        if track.locked:
            raise layers.LockedLayerError(layers._locked_message(track))
    try:
        entries = validate(proposal.get('entries'))
    except (ValueError, TypeError) as exc:
        raise EditError(str(exc)) from exc
    tracks = [Layer(name=e['name'], role=e['role'], color=layers._COLORS[e['role']], order=i)
              for i, e in enumerate(entries)]
    # Keep omitted roles, including dormant content and the two main tracks.
    roles = {t.role for t in tracks}
    for row in layers.rows(project):
        if row['role'] not in roles:
            tracks.append(Layer.from_dict(dict(row, order=len(tracks))))
            roles.add(row['role'])
    for role, owner, key in layers._bindings(project):
        track = layers.resolve(tracks, role)
        if track:
            owner[key] = track.id
    project.layers, project.layer_proposal = tracks, {}
