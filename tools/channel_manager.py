from __future__ import annotations

import argparse
import fnmatch
import json
import os
import shutil
import sys
import tempfile
import time
import zipfile
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RELEASE_ROOT = PROJECT_ROOT.parent / "xgn-assistant-release"
DEFAULT_DEV_ROOT = PROJECT_ROOT
DEFAULT_TEST_ROOT = PROJECT_ROOT.parent / "xgn-assistant-test"
UPDATE_DIR_NAME = ".release_updates"
STATE_FILE_NAME = "release_channel_state.json"
UPDATE_LOCK_NAME = "release_upgrade.lock"

EXCLUDE_DIRS = {
    ".git",
    ".workbench_runtime",
    ".codex_self_learning",
    ".release_updates",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "outputs",
    "output",
    "dist",
    "build",
    "_temp",
}
EXCLUDE_NAMES = {
    ".env",
    "quanlan_dual_assistant_settings.json",
    "gui_settings.json",
    "quanlan_email_settings.json",
    "relay_settings.json",
    "quanlan_model_scheme.json",
    "smtp_password.txt",
}
EXCLUDE_PATTERNS = (
    "*.pyc",
    "*.pyo",
    "*.log",
    "*.tmp",
    "*.bak",
    "*.zip",
    "*.7z",
    "*.rar",
    "*.mp4",
    "*.mov",
    "*.avi",
    "*.wav",
    "*.mp3",
    "*.pdf",
    "*_api_key.txt",
    "*_endpoint_id.txt",
    "*token*",
    "*secret*",
)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _is_excluded(path: Path, root: Path) -> bool:
    try:
        rel = path.relative_to(root)
    except ValueError:
        return True
    parts = set(rel.parts)
    if parts & EXCLUDE_DIRS:
        return True
    name = path.name
    if name in EXCLUDE_NAMES:
        return True
    return any(fnmatch.fnmatch(name.lower(), pattern.lower()) for pattern in EXCLUDE_PATTERNS)


def _copy_tree(src: Path, dst: Path) -> None:
    src = src.resolve()
    dst = dst.resolve()
    for root, dirs, files in os.walk(src):
        root_path = Path(root)
        dirs[:] = [d for d in dirs if not _is_excluded(root_path / d, src)]
        for filename in files:
            source = root_path / filename
            if _is_excluded(source, src):
                continue
            target = dst / source.relative_to(src)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)


def _is_release_busy(release_root: Path) -> bool:
    state = _load_json(release_root / STATE_FILE_NAME)
    active = state.get("active_tasks")
    if isinstance(active, list) and active:
        return True
    return bool(state.get("busy"))


def _set_state(root: Path, **updates: object) -> None:
    path = root / STATE_FILE_NAME
    data = _load_json(path)
    data.update(updates)
    data["updated_at"] = _now()
    _write_json(path, data)


def _update_dir(root: Path) -> Path:
    return root / UPDATE_DIR_NAME


def _target_root(args: argparse.Namespace, *, default_channel: str = "test") -> Path:
    channel = str(getattr(args, "channel", "") or default_channel).strip().lower()
    if getattr(args, "release_root", ""):
        return Path(args.release_root)
    if channel == "dev":
        return DEFAULT_DEV_ROOT
    if channel == "test":
        return DEFAULT_TEST_ROOT
    return DEFAULT_RELEASE_ROOT


def init_release(args: argparse.Namespace) -> int:
    release_root = _target_root(args, default_channel="test")
    if release_root.exists() and any(release_root.iterdir()) and not args.force:
        print(f"发布版已存在：{release_root}")
    else:
        if release_root.exists() and args.force:
            shutil.rmtree(release_root)
        _copy_tree(PROJECT_ROOT, release_root)
        print(f"已初始化发布版：{release_root}")
    _set_state(
        release_root,
        channel=str(args.channel or "test"),
        dev_root=str(PROJECT_ROOT),
        explicit_update_required=True,
        busy=False,
        active_tasks=[],
        last_init_at=_now(),
    )
    (_update_dir(release_root)).mkdir(parents=True, exist_ok=True)
    return 0


def package_update(args: argparse.Namespace) -> int:
    release_root = _target_root(args, default_channel="test")
    update_dir = _update_dir(release_root)
    update_dir.mkdir(parents=True, exist_ok=True)
    channel = str(args.channel or "test").strip().lower()
    package_name = f"xgn-assistant-{channel}-update-{_stamp()}.zip"
    package_path = update_dir / package_name
    manifest = {
        "created_at": _now(),
        "dev_root": str(PROJECT_ROOT),
        "release_root": str(release_root),
        "channel": channel,
        "package": package_name,
        "note": str(args.note or ""),
        "requires_explicit_apply": True,
    }
    with tempfile.TemporaryDirectory(prefix="xgn_update_") as tmp:
        tmp_root = Path(tmp) / "payload"
        _copy_tree(PROJECT_ROOT, tmp_root)
        _write_json(tmp_root / "UPDATE_MANIFEST.json", manifest)
        with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for path in tmp_root.rglob("*"):
                if path.is_file():
                    zf.write(path, path.relative_to(tmp_root))
    pointer = update_dir / "pending_update.json"
    _write_json(pointer, {**manifest, "path": str(package_path)})
    print(f"Generated {channel} pending update package, not applied: {package_path}")
    return 0


def apply_pending_update(args: argparse.Namespace) -> int:
    if not getattr(args, "yes", False):
        print("Refusing to apply update without explicit --yes.")
        return 3
    release_root = _target_root(args, default_channel="test")
    update_dir = _update_dir(release_root)
    pointer = update_dir / "pending_update.json"
    pending = _load_json(pointer)
    package_path = Path(str(pending.get("path") or ""))
    if not pointer.exists() or not package_path.exists():
        print("没有待升级包。")
        return 0
    if _is_release_busy(release_root):
        print("发布版正在执行任务，跳过升级。")
        return 2
    lock_path = update_dir / UPDATE_LOCK_NAME
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
    except FileExistsError:
        print("已有升级进程在运行。")
        return 2
    backup_dir = update_dir / f"backup_{_stamp()}"
    try:
        _set_state(release_root, upgrading=True)
        backup_dir.mkdir(parents=True, exist_ok=True)
        for item in release_root.iterdir():
            if item.name == UPDATE_DIR_NAME:
                continue
            if _is_excluded(item, release_root) and item.name not in {"modes", "quanlan_dual_assistant", "tools", "AutoMediaProducer.py", "README.md", "requirements.txt"}:
                continue
            target = backup_dir / item.name
            if item.is_dir():
                shutil.copytree(item, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            else:
                shutil.copy2(item, target)
        with zipfile.ZipFile(package_path, "r") as zf:
            zf.extractall(release_root)
        applied_dir = update_dir / "applied"
        applied_dir.mkdir(parents=True, exist_ok=True)
        applied_path = applied_dir / package_path.name
        shutil.move(str(package_path), applied_path)
        pointer.unlink(missing_ok=True)
        _set_state(release_root, upgrading=False, last_upgrade_at=_now(), last_upgrade_package=applied_path.name)
        print(f"发布版已升级：{applied_path.name}")
        return 0
    except Exception as exc:
        _set_state(release_root, upgrading=False, last_upgrade_error=f"{type(exc).__name__}: {exc}")
        print(f"升级失败：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        lock_path.unlink(missing_ok=True)


def deploy_update(args: argparse.Namespace) -> int:
    package_code = package_update(args)
    if package_code:
        return package_code
    apply_args = argparse.Namespace(**vars(args))
    apply_args.yes = True
    return apply_pending_update(apply_args)


def mark_busy(args: argparse.Namespace) -> int:
    root = _target_root(args, default_channel="test")
    active = [x for x in str(args.active or "").split(",") if x]
    _set_state(root, busy=bool(active), active_tasks=active)
    return 0


def status(args: argparse.Namespace) -> int:
    root = _target_root(args, default_channel="test")
    data = _load_json(root / STATE_FILE_NAME)
    print(json.dumps(data, ensure_ascii=False, indent=2))
    pending = _load_json(_update_dir(root) / "pending_update.json")
    if pending:
        print("pending_update:")
        print(json.dumps(pending, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="xgn-assistant release/development channel manager")
    parser.add_argument("--release-root", default="")
    parser.add_argument("--channel", choices=["dev", "test", "release"], default="test")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_init = sub.add_parser("init-release")
    p_init.add_argument("--force", action="store_true")
    p_init.set_defaults(func=init_release)
    p_pkg = sub.add_parser("package-update")
    p_pkg.add_argument("--note", default="")
    p_pkg.set_defaults(func=package_update)
    p_apply = sub.add_parser("apply-pending-update")
    p_apply.add_argument("--yes", action="store_true", help="Explicit confirmation required to apply an update.")
    p_apply.set_defaults(func=apply_pending_update)
    p_deploy = sub.add_parser("deploy-update")
    p_deploy.add_argument("--note", default="")
    p_deploy.set_defaults(func=deploy_update)
    p_busy = sub.add_parser("mark-busy")
    p_busy.add_argument("--active", default="")
    p_busy.set_defaults(func=mark_busy)
    p_status = sub.add_parser("status")
    p_status.set_defaults(func=status)
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
