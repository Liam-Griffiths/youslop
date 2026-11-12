"""Block poster signatures must not need .py source files (packaged builds ship none)."""
from pathlib import Path


def test_signature_without_module_source(monkeypatch):
    from app import block_library, place_blocks, screen_blocks

    real = Path.read_bytes

    def no_source(self):
        if self.suffix == '.py' and self.name in ('place_blocks.py', 'screen_blocks.py'):
            raise FileNotFoundError(self)  # as in dist/Corkbored/_internal/app/
        return real(self)

    with_source = {m.__name__: block_library._module_bytes(m) for m in (place_blocks, screen_blocks)}
    monkeypatch.setattr(Path, 'read_bytes', no_source)
    for module in (place_blocks, screen_blocks):
        compiled = block_library._module_bytes(module)
        assert compiled and compiled != with_source[module.__name__]
        assert compiled == block_library._module_bytes(module)  # stable between calls

    items = block_library.registry()
    for ref in ('route_map', 'chat_thread'):
        assert block_library.signature(items[ref])
