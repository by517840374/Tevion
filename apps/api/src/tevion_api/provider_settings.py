"""Server-side storage for the user-configured image provider."""

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def _path() -> Path:
    return Path(os.environ.get("TEVION_PROVIDER_CONFIG_PATH", "/tmp/tevion-image-provider.json"))


def load() -> dict[str, str]:
    try:
        value: Any = json.loads(_path().read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def save(*, base_url: str, api_key: str, model: str) -> None:
    target = _path()
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="tevion-provider-", suffix=".json", dir=target.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"base_url": base_url, "api_key": api_key, "model": model}, handle)
        os.replace(temporary, target)
        os.chmod(target, 0o600)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def clear() -> None:
    try:
        _path().unlink()
    except FileNotFoundError:
        pass
