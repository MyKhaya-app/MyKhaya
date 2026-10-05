"""MyKhaya API."""

import os

_version = os.environ.get("MYKHAYA_VERSION", "").strip()
__version__ = _version if _version and _version != "unknown" else "dev"
