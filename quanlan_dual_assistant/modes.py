from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODES_ROOT = PROJECT_ROOT / "modes"


@dataclass(frozen=True)
class ModeSpec:
    key: str
    title: str
    subtitle: str
    path: Path
    package: str
    gui_command: tuple[str, ...]
    cli_command: tuple[str, ...]


MODES: dict[str, ModeSpec] = {
    "research": ModeSpec(
        key="research",
        title="科研助手",
        subtitle="科研进展、文献速递、视频号素材生产",
        path=MODES_ROOT / "research",
        package="quanlan_automedia",
        gui_command=("AutoMediaProducer.py",),
        cli_command=("-m", "quanlan_automedia"),
    ),
    "culture": ModeSpec(
        key="culture",
        title="文史小秘",
        subtitle="书籍解读、文史短视频脚本与分集素材",
        path=MODES_ROOT / "culture",
        package="automedia_core",
        gui_command=("AutoMediaProducer.py", "--gui"),
        cli_command=("-m", "automedia_core"),
    ),
}


def get_mode(key: str) -> ModeSpec:
    normalized = (key or "").strip().lower()
    aliases = {
        "research-assistant": "research",
        "science": "research",
        "daily": "research",
        "keyan": "research",
        "科研助手": "research",
        "culture-assistant": "culture",
        "history": "culture",
        "book": "culture",
        "wenshi": "culture",
        "文史小秘": "culture",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in MODES:
        valid = ", ".join(MODES)
        raise ValueError(f"Unknown mode: {key!r}. Valid modes: {valid}")
    return MODES[normalized]

