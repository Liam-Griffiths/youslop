"""Product identifiers and backwards-compatible environment names."""
import os

NAME = "Corkbored"
LONG_NAME = "Corkbored"
SLUG = "corkbored"
ENV_PREFIX = "CORKBORED_"
LEGACY_ENV_PREFIXES = ("YOUSLOP_", "VB_")
LEGACY_SLUGS = ("Youslop", "youslop")
FILE_EXT = ".corkbored"
LEGACY_FILE_EXTS = (".youslop",)


def env_names(key: str) -> list[str]:
    """All environment names for KEY, newest first."""
    return [ENV_PREFIX + key] + [prefix + key for prefix in LEGACY_ENV_PREFIXES]


def env(key: str, default: str = "") -> str:
    """Read the first set name, preserving explicitly empty values."""
    for name in env_names(key):
        value = os.environ.get(name)
        if value is not None:
            return value
    return default


def promote_legacy(env: dict[str, str]) -> None:
    """Copy legacy values to unset current names, in prefix priority order."""
    for prefix in LEGACY_ENV_PREFIXES:
        for name in list(env):
            if name.startswith(prefix):
                env.setdefault(ENV_PREFIX + name[len(prefix):], env[name])
