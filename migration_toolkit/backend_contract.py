from __future__ import annotations

import ast
from dataclasses import dataclass
import os
from pathlib import Path
import re
from typing import Any

DEFAULT_HISTORICAL_ITEM_TYPE_LABELS: tuple[str, ...] = ("Agreement", "Charter", "Letter")


class BackendContractError(RuntimeError):
    pass


@dataclass(frozen=True)
class BackendContract:
    historical_item_type_labels: tuple[str, ...]
    historical_item_type_values: frozenset[str]
    source: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "historical_item_type_labels": list(self.historical_item_type_labels),
            "historical_item_type_values": sorted(self.historical_item_type_values),
        }


def backend_choice_values(labels: tuple[str, ...]) -> frozenset[str]:
    return frozenset(label.strip().lower() for label in labels if label.strip())


def default_backend_root() -> Path | None:
    env_root = os.environ.get("BACKEND_REPO")
    candidates = [Path(env_root)] if env_root else []
    candidates.extend([Path("/app"), Path("../backend")])
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if (resolved / "config" / "settings.py").is_file():
            return resolved
    return None


def load_backend_contract(backend_root: Path | str | None = None) -> BackendContract:
    labels, source = _historical_item_type_labels(backend_root)
    return BackendContract(
        historical_item_type_labels=labels,
        historical_item_type_values=backend_choice_values(labels),
        source=source,
    )


def _historical_item_type_labels(backend_root: Path | str | None) -> tuple[tuple[str, ...], str]:
    explicit_root = Path(backend_root).expanduser().resolve() if backend_root else None
    if explicit_root and not (explicit_root / "config" / "settings.py").is_file():
        raise BackendContractError(f"Backend settings file not found at {explicit_root / 'config' / 'settings.py'}")

    env_value = os.environ.get("HISTORICAL_ITEM_TYPES")
    if env_value:
        return _split_env_list(env_value), "env:HISTORICAL_ITEM_TYPES"

    resolved_root = explicit_root or default_backend_root()
    if resolved_root is not None:
        env_file = resolved_root / "config" / ".env"
        env_labels = _read_env_list(env_file, "HISTORICAL_ITEM_TYPES")
        if env_labels:
            return env_labels, f"{env_file}:HISTORICAL_ITEM_TYPES"

        settings_file = resolved_root / "config" / "settings.py"
        settings_labels = _read_settings_default_list(settings_file, "HISTORICAL_ITEM_TYPES")
        if settings_labels:
            return settings_labels, f"{settings_file}:HISTORICAL_ITEM_TYPES default"

    return DEFAULT_HISTORICAL_ITEM_TYPE_LABELS, "migration-toolkit fallback:HISTORICAL_ITEM_TYPES"


def _read_env_list(path: Path, key: str) -> tuple[str, ...] | None:
    if not path.is_file():
        return None

    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        line_key, raw_value = stripped.split("=", 1)
        if line_key.strip() == key:
            return _split_env_list(raw_value)
    return None


def _split_env_list(raw_value: str) -> tuple[str, ...]:
    value = raw_value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return tuple(part.strip() for part in value.split(",") if part.strip())


def _read_settings_default_list(path: Path, key: str) -> tuple[str, ...] | None:
    if not path.is_file():
        return None

    pattern = re.compile(rf"{re.escape(key)}=\(list,\s*(\[[^\]]*\])\)")
    match = pattern.search(path.read_text(encoding="utf-8"))
    if not match:
        return None
    value = ast.literal_eval(match.group(1))
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return None
    return tuple(value)
