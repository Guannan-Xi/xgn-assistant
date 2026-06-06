from __future__ import annotations

from .runtime_loader import load_runtime


def main() -> None:
    namespace = load_runtime()
    entry = namespace.get("run_cli_or_ui")
    if not callable(entry):
        raise RuntimeError("Entry function run_cli_or_ui() was not found after loading runtime source.")
    entry()


if __name__ == "__main__":
    main()
