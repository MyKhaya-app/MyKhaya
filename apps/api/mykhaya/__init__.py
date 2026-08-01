"""MyKhaya API."""

from pathlib import Path


def _read_version() -> str:
    # Runtime images copy VERSION into /app; tests and local tools read from nearby parents.
    here = Path(__file__).resolve()
    candidates = [Path("/app/VERSION"), Path.cwd() / "VERSION"]
    candidates.extend(parent / "VERSION" for parent in here.parents[:4])
    for path in candidates:
        if path.exists():
            value = path.read_text(encoding="utf-8").strip()
            if value:
                return value
    return "unknown"


__version__ = _read_version()
