from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = Path(__file__).resolve().parent
SOURCE_MODULES_DIR = PACKAGE_DIR / "source_modules"
COMPAT_FILE = PROJECT_ROOT / "AutoMediaProducer.py"


def _natural_key(path: Path) -> tuple:
    return tuple(int(part) if part.isdigit() else part for part in re.split(r"(\d+)", path.name))


def _runtime_namespace(source_label: str) -> dict:
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    return {
        "__name__": "quanlan_automedia.runtime",
        "__file__": str(COMPAT_FILE),
        "__package__": None,
        "__runtime_source__": source_label,
    }


def _source_module_files() -> list[Path]:
    if not SOURCE_MODULES_DIR.exists():
        return []
    return sorted(
        (p for p in SOURCE_MODULES_DIR.glob("*.py") if p.name != "__init__.py"),
        key=_natural_key,
    )


def _exec_ordered_modules(files: Iterable[Path]) -> dict:
    namespace = _runtime_namespace("source_modules")
    executed: list[str] = []
    for path in files:
        source = path.read_text(encoding="utf-8-sig")
        exec(compile(source, str(path), "exec"), namespace)
        executed.append(path.name)
    namespace["__runtime_modules__"] = executed
    if not callable(namespace.get("run_cli_or_ui")):
        raise RuntimeError("source_modules loaded, but run_cli_or_ui() was not found.")
    return namespace


def load_runtime() -> dict:
    """Load the single authoritative modular runtime."""
    module_files = _source_module_files()
    if not module_files:
        raise RuntimeError("Runtime source_modules directory is missing or empty.")
    return _exec_ordered_modules(module_files)
