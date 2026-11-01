"""Local pack authoring: reuse loader validation and the sandboxed block preview."""
from pathlib import Path
import tempfile
import zipfile

from . import blocks, brand, packs, scenes, stage


def check(folder, *, static_only=False):
    folder = Path(folder).resolve()
    pack = packs._load(folder)
    errors = pack.problems + [f'{ref}: {p}' for ref, ps in pack.item_problems.items() for p in ps]
    if errors or static_only:
        return errors
    # Register only in this context; never install or modify the user's library.
    token = packs.STAGED.set((folder,))
    try:
        output = folder / '.check'
        if output.is_symlink():
            return ['.check must not be a symlink']
        output.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=f'{brand.SLUG}-pack-check-') as temporary:
            for item in pack.blocks():
                for aspect in item['meta']['aspects']:
                    name = f'{item["path"].name}-{aspect.replace(":", "x")}.png'
                    target = output / name
                    if target.exists() or target.is_symlink():
                        # Refuse links, but permit refreshing our own preview files.
                        if not target.is_file() or target.is_symlink():
                            errors.append(f'{name}: preview target must be a regular file')
                            continue
                    try:
                        template, ctx = blocks.prepare(item['ref'], aspect=aspect)
                        size = (480, 270) if aspect == '16:9' else (270, 480) if aspect == '9:16' else (270, 270)
                        target.write_bytes(scenes.capture(Path(temporary), template, ctx,
                                           t=ctx['duration']/2, size=size))
                    except (OSError, ValueError, stage.StageError) as exc:
                        errors.append(f'{item["ref"]} {aspect}: preview failed: {exc}')
    finally:
        packs.STAGED.reset(token)
    return errors


def build(folder):
    """Package a checked folder; caller runs check first. Never overwrite a bundle."""
    folder = Path(folder).resolve()
    pack = packs._load(folder)
    if pack.problems or pack.item_problems:
        raise packs.PackError('Pack changed or is invalid; run pack check again')
    packs._version(pack.version)  # Also ensures the output filename is safe.
    out = folder.parent / f'{pack.id}-{pack.version}{packs.EXTENSION}'
    with zipfile.ZipFile(out, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(folder.rglob('*')):
            relative = path.relative_to(folder)
            if path.is_file() and not any(p.startswith('.') for p in relative.parts):
                archive.write(path, str(Path(pack.id) / relative))
    return out
