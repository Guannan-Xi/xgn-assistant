#!/usr/bin/env python3
"""Launcher for AutoMediaProducer.

No arguments: start the friendly desktop GUI.
With arguments: run the CLI workflow for automation.
"""
from __future__ import annotations

import sys


def main() -> None:
    if len(sys.argv) == 1 or "--gui" in sys.argv:
        if "--gui" in sys.argv:
            sys.argv.remove("--gui")
        from automedia_core.gui import main as gui_main
        gui_main()
    else:
        from automedia_core.runner import main as cli_main
        cli_main()


if __name__ == "__main__":
    main()
