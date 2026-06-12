from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Sequence

from .modes import MODES, ModeSpec, get_mode

WEB_WORKBENCH_URL = "http://127.0.0.1:8765/assistant/"


def _python_command(mode: ModeSpec, extra_args: Sequence[str]) -> list[str]:
    return [sys.executable, *mode.cli_command, *extra_args]


def launch_mode(mode: ModeSpec, *, extra_args: Sequence[str] = ()) -> int:
    if not mode.path.exists():
        raise FileNotFoundError(f"Mode folder is missing: {mode.path}")
    completed = subprocess.run(_python_command(mode, extra_args), cwd=str(mode.path))
    return int(completed.returncode or 0)


def open_mode_async(mode: ModeSpec, *, extra_args: Sequence[str] = ()) -> subprocess.Popen:
    if not mode.path.exists():
        raise FileNotFoundError(f"Mode folder is missing: {mode.path}")
    return subprocess.Popen(_python_command(mode, extra_args), cwd=str(mode.path))


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="AutoMediaProducer",
        description="QuanLan Web-only assistant launcher.",
    )
    parser.add_argument("--mode", choices=sorted(MODES), help="research or culture")
    parser.add_argument("-m", "--module", choices=sorted({mode.package for mode in MODES.values()}), help="Infer mode from a package module name.")
    parser.add_argument("--cli", action="store_true", help="Run the selected mode's CLI.")
    parser.add_argument("args", nargs=argparse.REMAINDER, help="Arguments passed to the selected mode.")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None) -> None:
    ns = _parse_args(argv)
    if ns.module and not ns.mode:
        ns.mode = next(mode.key for mode in MODES.values() if mode.package == ns.module)
        ns.cli = True
    if not ns.mode or not ns.cli:
        print(f"Desktop GUI has been removed. Use the Web workbench: {WEB_WORKBENCH_URL}")
        print("Start it with: python -m quanlan_dual_assistant.web_app 8765")
        return
    extra = list(ns.args or [])
    if extra and extra[0] == "--":
        extra = extra[1:]
    raise SystemExit(launch_mode(get_mode(ns.mode), extra_args=extra))


if __name__ == "__main__":
    main()
