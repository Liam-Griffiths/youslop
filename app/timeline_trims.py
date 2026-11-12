"""Bounded ripple/roll edits of metadata; never open or write take files."""
from copy import deepcopy
import math

from . import audio, footage, inserts, render
from .edits import EditError


def limits(project, row, edge):
    if not row.insert:
        gap = audio.gap_map(project)[row.id]
        return -gap, 10-gap
    item = row.insert
    length = item['seconds']
    if item['kind'] != 'clip':
        return .05-length, math.inf
    shoot = footage.load(item['shoot_id'])
    source = next(f for f in shoot.files if f.id == item['source_id'])
    return (.05-length, item['in_s'] if edge == 'start'
            else source.duration-item['out_s'])


def change(project, row, edge, delta):
    if not row.insert:
        row.gap_override = round(audio.gap_map(project)[row.id]+delta, 6)
        return
    item = row.insert
    patch = ({'in_s': item['in_s']-delta} if edge == 'start'
             else {'out_s': item['out_s']+delta}) if item['kind'] == 'clip' else {
                 'seconds': item['seconds']+delta}
    clean, _ = inserts.prepare(project, patch, row)
    inserts.place(project, clean, None)


def apply(project, payload):
    """Return a detached validated project and actual length change."""
    if project.kind == 'clip':
        raise EditError('Use the Clip screen for word trims.')
    if payload.keys() - {'sid', 'edge', 'delta', 'roll', 'version'}:
        raise EditError('Unknown trim field.')
    if payload.get('version') != project.updated_at:
        raise EditError('The cut changed. Retry the trim.', 409)
    edge, delta, roll = payload.get('edge'), payload.get('delta'), payload.get('roll', False)
    if edge not in {'start', 'end', 'slip'} or type(delta) not in (int, float) or not math.isfinite(delta) or type(roll) is not bool:
        raise EditError('Use an edge and a finite delta.')
    row = project.slide(payload.get('sid'))
    if row is None:
        raise EditError('Unknown main-track item.')
    if edge == 'start' and not row.insert:
        raise EditError('Speech cannot be trimmed. Use the razor to split it.')
    candidate = deepcopy(project)
    target = candidate.slide(row.id)
    if edge == 'slip':
        if row.insert.get('kind') != 'clip':
            raise EditError('Only clip inserts can slip.')
        source = next(f for f in footage.load(row.insert['shoot_id']).files if f.id == row.insert['source_id'])
        delta = max(-row.insert['in_s'], min(source.duration-row.insert['out_s'], delta))
        clean, _ = inserts.prepare(candidate, {k: row.insert[k]+delta for k in ('in_s', 'out_s')}, target)
        inserts.place(candidate, clean, None)
        return candidate, delta
    lo, hi = limits(project, row, edge)
    neighbour = None
    if roll:
        index = project.slides.index(row)+(1 if edge == 'end' else -1)
        if not 0 <= index < len(project.slides):
            raise EditError('No neighbour for a roll edit.')
        neighbour = project.slides[index]
        boundary = row.id if edge == 'end' else neighbour.id
        if render._sponsor_placements(project, render._slide_durations(project, True)).get(boundary):
            raise EditError('Cannot roll across a sponsor read.')
        nlo, nhi = limits(project, neighbour, 'start' if edge == 'end' else 'end')
        lo, hi = max(lo, -nhi), min(hi, -nlo)
    delta = max(lo, min(hi, delta))
    if abs(delta) < .000001:
        return project, 0
    change(candidate, target, edge, delta)
    if neighbour:
        change(candidate, candidate.slide(neighbour.id), 'start' if edge == 'end' else 'end', -delta)
    return candidate, delta
