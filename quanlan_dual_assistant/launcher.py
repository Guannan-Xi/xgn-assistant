from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Sequence

from .modes import MODES, ModeSpec, get_mode


def _python_command(mode: ModeSpec, *, gui: bool, extra_args: Sequence[str]) -> list[str]:
    base = mode.gui_command if gui else mode.cli_command
    return [sys.executable, *base, *extra_args]


def launch_mode(mode: ModeSpec, *, gui: bool, extra_args: Sequence[str] = ()) -> int:
    if not mode.path.exists():
        raise FileNotFoundError(f"Mode folder is missing: {mode.path}")
    cmd = _python_command(mode, gui=gui, extra_args=extra_args)
    completed = subprocess.run(cmd, cwd=str(mode.path))
    return int(completed.returncode or 0)


def open_mode_async(mode: ModeSpec, *, gui: bool = True, extra_args: Sequence[str] = ()) -> subprocess.Popen:
    if not mode.path.exists():
        raise FileNotFoundError(f"Mode folder is missing: {mode.path}")
    cmd = _python_command(mode, gui=gui, extra_args=extra_args)
    return subprocess.Popen(cmd, cwd=str(mode.path))


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="AutoMediaProducer",
        description="QuanLan dual-mode assistant launcher.",
    )
    parser.add_argument("--mode", choices=sorted(MODES), help="research=科研助手, culture=文史小秘")
    parser.add_argument("-m", "--module", choices=sorted({mode.package for mode in MODES.values()}), help="Compatibility: infer mode from a package module name.")
    parser.add_argument("--gui", action="store_true", help="Open the selected mode's GUI.")
    parser.add_argument("--cli", action="store_true", help="Run the selected mode's CLI.")
    parser.add_argument("args", nargs=argparse.REMAINDER, help="Arguments passed to the selected mode.")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None) -> None:
    ns = _parse_args(argv)
    if ns.module and not ns.mode:
        ns.mode = next(mode.key for mode in MODES.values() if mode.package == ns.module)
        ns.cli = True
    if not ns.mode:
        from .selector import main as selector_main

        selector_main()
        return
    mode = get_mode(ns.mode)
    extra = list(ns.args or [])
    if extra and extra[0] == "--":
        extra = extra[1:]
    if ns.gui or not ns.cli:
        from .selector import main as selector_main

        selector_main(initial_mode=mode.key)
        return
    gui = bool(ns.gui or not ns.cli)
    raise SystemExit(launch_mode(mode, gui=gui, extra_args=extra))


if __name__ == "__main__":
    main()
