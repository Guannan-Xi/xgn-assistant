from __future__ import annotations

import sys

WEB_WORKBENCH_URL = "http://127.0.0.1:8765/assistant/"


def main() -> None:
    if len(sys.argv) == 1:
        print(f"Desktop GUI has been removed. Use the Web workbench: {WEB_WORKBENCH_URL}")
        return
    from .runner import main as cli_main
    cli_main()


if __name__ == "__main__":
    main()
