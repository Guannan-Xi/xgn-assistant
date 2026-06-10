from __future__ import annotations

import json
import os
import re
import smtplib
import subprocess
import sys
import threading
import time
import shutil
import uuid
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .launcher import _python_command
from .modes import PROJECT_ROOT, get_mode


SETTINGS_FILE = PROJECT_ROOT / "quanlan_dual_assistant_settings.json"
MODEL_DEFAULTS_FILE = PROJECT_ROOT / "quanlan_model_defaults.json"
MODEL_PROFILES_FILE = PROJECT_ROOT / "quanlan_model_profiles.json"
MODEL_CONNECTION_LIBRARY_FILE = PROJECT_ROOT / "quanlan_model_connection_library.json"
MODEL_PROFILE_SECRET_DIR = PROJECT_ROOT / ".model_profiles"
MODEL_CONNECTION_SECRET_DIR = PROJECT_ROOT / ".model_connection_library"
MODEL_DOC_SOURCE_URL = "https://quanland.feishu.cn/wiki/JhfUw6lChio8JpkursGc6yBrnac"
MODEL_DOC_SOURCE_TOKEN = "JhfUw6lChio8JpkursGc6yBrnac"
FEISHU_DOCS_WORKDIR = Path(os.environ.get("FEISHU_DOCS_WORKDIR", r"C:\Users\XGN\Documents\Codex\2026-06-04\new-chat-3\work\feishu-direct"))
DEFAULT_PROFILE_ID = "dst"
DEFAULT_FOREIGN_BASE_URL = "https://api.dstopology.com/v1"
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_GPT_PRO_BASE_URL = "https://www.fhl.mom/v1"
DEFAULT_MINIMAX_BASE_URL = "https://api.53hk.cn"
BGM_LIBRARY_DIR = PROJECT_ROOT / "bgm_library"
AUDIO_LIBRARY_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac"}
LEGACY_FOREIGN_BASE_URLS: set[str] = set()
PER_MODEL_BASE_URL_FIELDS = {
    "gpt_base_url",
    "gpt_pro_base_url",
    "gpt_image_base_url",
    "culture_text_base_url",
    "culture_polish_base_url",
    "culture_image_base_url",
    "research_text_base_url",
    "research_polish_base_url",
    "research_image_base_url",
}
MINIMAX_KEY_FILE = PROJECT_ROOT / "minimax_api_key.txt"
MINIMAX_OFFICIAL_KEY_FILE = PROJECT_ROOT / "minimax_official_api_key.txt"
MINIMAX_FAST_KEY_FILE = PROJECT_ROOT / "minimax_fast_api_key.txt"
MODEL_KEY_FILES = {
    "openai_api_key": PROJECT_ROOT / "openai_api_key.txt",
    "image_api_key": PROJECT_ROOT / "image_api_key.txt",
    "gpt_pro_api_key": PROJECT_ROOT / "gpt_pro_api_key.txt",
    "deepseek_api_key": PROJECT_ROOT / "deepseek_api_key.txt",
    "minimax_api_key": MINIMAX_KEY_FILE,
}
PROFILE_MODEL_KEY_NAMES = ("openai_api_key", "image_api_key", "gpt_pro_api_key", "deepseek_api_key", "minimax_api_key")
MODEL_KEY_FALLBACK_FILES = {
    "openai_api_key": [PROJECT_ROOT / "modes" / "culture" / "openai_api_key.txt", PROJECT_ROOT / "modes" / "research" / "openai_api_key.txt"],
    "image_api_key": [PROJECT_ROOT / "modes" / "culture" / "image_api_key.txt", PROJECT_ROOT / "modes" / "research" / "image_api_key.txt"],
    "gpt_pro_api_key": [],
    "deepseek_api_key": [PROJECT_ROOT / "deepseek_api_key.txt", PROJECT_ROOT / "modes" / "culture" / "deepseek_api_key.txt", PROJECT_ROOT / "modes" / "research" / "deepseek_api_key.txt"],
    "minimax_api_key": [],
}
SMTP_PASSWORD_FILES = [
    PROJECT_ROOT / "smtp_password.txt",
    PROJECT_ROOT / "modes" / "research" / "smtp_password.txt",
    PROJECT_ROOT / "modes" / "culture" / "smtp_password.txt",
]
SMTP_PASSWORD_ENV_NAMES = ["AMP_SMTP_PASSWORD", "QUANLAN_SMTP_PASSWORD"]
MODEL_KEY_ENV_NAMES = {
    "openai_api_key": ["OPENAI_API_KEY"],
    "image_api_key": ["IMAGE_API_KEY", "OPENAI_IMAGE_API_KEY"],
    "gpt_pro_api_key": ["GPT_PRO_API_KEY"],
    "deepseek_api_key": ["DEEPSEEK_API_KEY"],
    "minimax_api_key": ["MINIMAX_API_KEY"],
}
MODEL_PROFILE_MODEL_FIELDS = {
    "culture_text_provider", "culture_text_model", "culture_polish_provider",
    "culture_polish_model", "culture_image_provider", "culture_image_model",
    "text_engine", "polish_engine", "image_engine", "foreign_base_url", "deepseek_base_url",
    "gpt_base_url", "gpt_pro_base_url", "gpt_image_base_url",
    "culture_text_base_url", "culture_polish_base_url", "culture_image_base_url",
    "research_text_base_url", "research_polish_base_url", "research_image_base_url",
    "minimax_base_url", "minimax_tts_model",
}
MODEL_CONNECTION_ROLES = {
    "text": {"label": "GPT / 文本", "provider": "openai", "key_name": "openai_api_key"},
    "gpt_pro": {"label": "GPT-Pro / 备用文本", "provider": "gpt_pro", "key_name": "gpt_pro_api_key"},
    "polish": {"label": "DeepSeek / 润色", "provider": "deepseek", "key_name": "deepseek_api_key"},
    "image": {"label": "gpt-image-2 / 生图", "provider": "image", "key_name": "image_api_key"},
    "minimax": {"label": "MiniMax / 配音 BGM", "provider": "minimax", "key_name": "minimax_api_key"},
}
MODEL_CONNECTION_ROLE_ORDER = ("text", "gpt_pro", "polish", "image", "minimax")
MODEL_STEP_ROUTES = {
    "script_text": {"label": "脚本/文案生成", "role": "text", "roles": ("text",)},
    "research_text": {"label": "科研速递文本", "role": "text", "roles": ("text",)},
    "polish_text": {"label": "最终文案润色", "role": "polish", "roles": ("polish", "text")},
    "image_generation": {"label": "图片生成", "role": "image", "roles": ("image",)},
    "gpt_pro_backup": {"label": "GPT-Pro 备用文本", "role": "gpt_pro", "roles": ("gpt_pro",)},
    "voice_bgm": {"label": "配音/BGM", "role": "minimax", "roles": ("minimax",)},
}
MODEL_STEP_ORDER = ("script_text", "research_text", "polish_text", "image_generation", "gpt_pro_backup", "voice_bgm")
ROLE_DEFAULT_STEP = {
    "text": "script_text",
    "gpt_pro": "gpt_pro_backup",
    "polish": "polish_text",
    "image": "image_generation",
    "minimax": "voice_bgm",
}
JOBS: dict[str, dict[str, Any]] = {}


def _new_job_id() -> str:
    return uuid.uuid4().hex


XIAOZHULI_ROOT = Path(os.environ.get("XIAOZHULI_ROOT", r"D:\Quanlan\Codes\Python\quanlan-feishu-assistant"))
XIAOZHULI_PORT = int(os.environ.get("XIAOZHULI_DASHBOARD_PORT", "8787"))
XIAOZHULI_TARGET = f"http://127.0.0.1:{XIAOZHULI_PORT}"
XIAOZHULI_PROCESS: subprocess.Popen[str] | None = None
XIAOZHULI_CONFIG_DIRTY = False
SHARED_CONFIG_UPDATED_AT = ""
SHARED_MODEL_CONFIG_GUARD_MESSAGE = "Model config is centralized in xgn-assistant total console."
EEG_ANALYSER_ROOT = Path(os.environ.get("EEG_ANALYSER_ROOT", r"D:\Quanlan\Codes\Python\quanlan-analyser"))
EEG_ANALYSER_PORT = int(os.environ.get("EEG_ANALYSER_PORT", "4173"))
EEG_ANALYSER_TARGET = f"http://127.0.0.1:{EEG_ANALYSER_PORT}"
EEG_ANALYSER_PROCESS: subprocess.Popen[str] | None = None
DAILY_RESEARCH_DEFAULT_ROOT = Path(os.environ.get("DAILY_RESEARCH_DEFAULT_ROOT", r"D:\Quanlan\全澜脑科学视频号\科研速递"))
SCIENCE_TASK_SETTINGS_FILE = PROJECT_ROOT / "modes" / "research" / "quanlan_task_page_settings.json"
SCIENCE_DEFAULT_ROOT = Path(os.environ.get("SCIENCE_CLASSIC_DEFAULT_ROOT", r"D:\Quanlan\全澜脑科学视频号\神经科学经典"))
SCIENCE_DEFAULT_PDF_GLOB = "Principles of Neural Science*.pdf"


def _read_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return fallback


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _strip_windows_long_prefix(value: str) -> str:
    text = str(value or "").strip().strip('"')
    if text.startswith("//?/"):
        return text[4:]
    if text.startswith("\\\\?\\"):
        return text[4:]
    return text


def _science_path_is_corrupt(value: str) -> bool:
    text = _strip_windows_long_prefix(value)
    return bool(text and ("?" in text or "\ufffd" in text))


def _find_default_science_pdf() -> str:
    candidates: list[Path] = []
    preferred = SCIENCE_DEFAULT_ROOT / "神经科学原理" / "原文"
    roots = [preferred, SCIENCE_DEFAULT_ROOT]
    for root in roots:
        try:
            iterator = root.glob(SCIENCE_DEFAULT_PDF_GLOB) if root == preferred else root.rglob(SCIENCE_DEFAULT_PDF_GLOB)
            candidates.extend([p for p in iterator if p.is_file()])
        except Exception:
            continue
    if not candidates:
        return ""
    candidates = sorted(candidates, key=lambda p: (0 if "Principles of Neural Science, Sixth Edition" in p.name else 1, len(str(p))))
    return str(candidates[0])


def _default_science_out_dir_for_pdf(pdf_path: str) -> str:
    path = Path(_strip_windows_long_prefix(pdf_path))
    if not str(path):
        return str(SCIENCE_DEFAULT_ROOT)
    stem = path.stem
    if " -- " in stem:
        stem = stem.split(" -- ", 1)[0]
    return str(path.with_name(f"{stem}_章节PDF直传结果"))


def _repair_science_slot_paths(slot: dict[str, Any]) -> bool:
    pdf_path = _strip_windows_long_prefix(str(slot.get("pdf_path") or slot.get("current_pdf_path") or ""))
    out_dir = _strip_windows_long_prefix(str(slot.get("out_dir") or ""))
    changed = False
    if _science_path_is_corrupt(pdf_path) or (pdf_path and not Path(pdf_path).exists()):
        default_pdf = _find_default_science_pdf()
        if default_pdf:
            pdf_path = default_pdf
            slot["pdf_path"] = default_pdf
            slot["current_pdf_path"] = default_pdf
            changed = True
    if _science_path_is_corrupt(out_dir) or not out_dir:
        repaired_out = _default_science_out_dir_for_pdf(pdf_path) if pdf_path else str(SCIENCE_DEFAULT_ROOT)
        slot["out_dir"] = repaired_out
        changed = True
    return changed


def _science_task_settings() -> dict[str, Any]:
    data = _read_json(SCIENCE_TASK_SETTINGS_FILE, {"version": 1, "slots": []})
    if not isinstance(data, dict):
        data = {"version": 1, "slots": []}
    slots = data.get("slots")
    if not isinstance(slots, list):
        data["slots"] = []
    if not data["slots"]:
        data["slots"].append({"slot_index": 0, "out_dir": str(SCIENCE_DEFAULT_ROOT)})
    if isinstance(data["slots"][0], dict) and _repair_science_slot_paths(data["slots"][0]):
        _write_json(SCIENCE_TASK_SETTINGS_FILE, data)
    return data


def _science_first_slot() -> dict[str, Any]:
    data = _science_task_settings()
    slot = data["slots"][0]
    return slot if isinstance(slot, dict) else {}


def _save_science_first_slot(slot: dict[str, Any]) -> dict[str, Any]:
    data = _science_task_settings()
    slots = data.get("slots") if isinstance(data.get("slots"), list) else []
    while len(slots) < 1:
        slots.append({})
    slot["slot_index"] = int(slot.get("slot_index", 0) or 0)
    data["slots"] = slots
    data["slots"][0] = slot
    data["version"] = 1
    data["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    _write_json(SCIENCE_TASK_SETTINGS_FILE, data)
    return data


def _science_output_dir_from_settings() -> str:
    slot = _science_first_slot()
    return _strip_windows_long_prefix(str(slot.get("out_dir") or "")) or str(SCIENCE_DEFAULT_ROOT)


def _scriptable_science_chapter(title: str) -> bool:
    text = str(title or "").strip()
    if not text:
        return False
    lowered = text.lower()
    blocked = ("front matter", "preface", "contents", "index", "glossary", "references", "appendix", "copyright")
    if any(x in lowered for x in blocked):
        return False
    return bool(re.search(r"\d", text)) or len(text) >= 4


def _parse_science_pdf_toc(pdf_path: str) -> list[dict[str, Any]]:
    clean_path = _strip_windows_long_prefix(pdf_path)
    if not clean_path or not Path(clean_path).exists():
        raise FileNotFoundError(f"PDF 不存在：{clean_path or pdf_path}")
    try:
        from pypdf import PdfReader
    except Exception as exc:
        raise RuntimeError(f"缺少 pypdf，无法读取 PDF 目录：{exc}") from exc

    reader = PdfReader(clean_path)
    outline = getattr(reader, "outline", []) or []
    rows: list[dict[str, Any]] = []

    def walk(items: Any, level: int = 1) -> None:
        if not isinstance(items, (list, tuple)):
            items = [items]
        for item in items:
            if isinstance(item, (list, tuple)):
                walk(item, level + 1)
                continue
            title = str(getattr(item, "title", "") or "")
            if not title and isinstance(item, dict):
                title = str(item.get("/Title") or item.get("title") or "")
            title = re.sub(r"\s+", " ", title).strip()
            if not title:
                continue
            page = 0
            try:
                page = int(reader.get_destination_page_number(item)) + 1
            except Exception:
                page = 0
            rows.append({
                "index": len(rows),
                "title": title,
                "level": max(1, int(level or 1)),
                "page": page,
                "selected": bool(_scriptable_science_chapter(title) and re.match(r"^\s*\d+", title)),
                "scriptable": _scriptable_science_chapter(title),
                "parsed": False,
            })

    walk(outline, 1)
    return rows


def _science_state_payload(*, extract: bool = False) -> dict[str, Any]:
    slot = dict(_science_first_slot())
    pdf_path = _strip_windows_long_prefix(str(slot.get("pdf_path") or slot.get("current_pdf_path") or ""))
    out_dir = _strip_windows_long_prefix(str(slot.get("out_dir") or "")) or str(SCIENCE_DEFAULT_ROOT)
    toc = slot.get("current_toc") if isinstance(slot.get("current_toc"), list) else []
    if extract and pdf_path:
        toc = _parse_science_pdf_toc(pdf_path)
        slot["current_toc"] = toc
        slot["pdf_path"] = pdf_path
        slot["current_pdf_path"] = pdf_path
        slot["out_dir"] = out_dir
        _save_science_first_slot(slot)
    selected = [x for x in toc if isinstance(x, dict) and x.get("selected")]
    scriptable = [x for x in toc if isinstance(x, dict) and x.get("scriptable", _scriptable_science_chapter(str(x.get("title") or "")))]
    return {
        "ok": True,
        "pdf_path": pdf_path,
        "out_dir": out_dir,
        "content_style": slot.get("content_style") or "科学经典解读",
        "test_b_image_limit": int(slot.get("test_b_image_limit", 0) or 0),
        "toc": toc,
        "total": len(toc),
        "scriptable": len(scriptable),
        "selected": len(selected),
        "settings_path": str(SCIENCE_TASK_SETTINGS_FILE),
    }


def _science_model_fields_from_console() -> dict[str, Any]:
    models = _models_with_url_defaults(_model_settings())
    text_model = str(models.get("research_text_model") or models.get("culture_text_model") or models.get("text_engine") or "gpt-5.5")
    polish_model = str(models.get("research_polish_model") or models.get("culture_polish_model") or models.get("polish_engine") or text_model)
    image_model = str(models.get("research_image_model") or models.get("culture_image_model") or models.get("image_engine") or "gpt-image-2")
    return {
        "text_engine": _daily_text_engine_arg(text_model),
        "review_engine": _daily_text_engine_arg(polish_model),
        "image_engine": _daily_image_engine_arg(image_model),
        "call_mode": "API 自动调用",
    }


def _save_science_state_payload(payload: dict[str, Any]) -> dict[str, Any]:
    slot = dict(_science_first_slot())
    incoming_pdf = _strip_windows_long_prefix(str(payload.get("pdf_path") or payload.get("science_pdf_path") or ""))
    incoming_out = _strip_windows_long_prefix(str(payload.get("out_dir") or payload.get("science_out_dir") or ""))
    if _science_path_is_corrupt(incoming_pdf):
        incoming_pdf = ""
    if _science_path_is_corrupt(incoming_out):
        incoming_out = ""
    pdf_path = incoming_pdf or _strip_windows_long_prefix(str(slot.get("pdf_path") or slot.get("current_pdf_path") or ""))
    out_dir = incoming_out or _strip_windows_long_prefix(str(slot.get("out_dir") or "")) or str(SCIENCE_DEFAULT_ROOT)
    slot["pdf_path"] = pdf_path
    slot["current_pdf_path"] = pdf_path
    slot["out_dir"] = out_dir
    _repair_science_slot_paths(slot)
    slot["content_style"] = "科学经典解读"
    slot["flow_parse"] = bool(payload.get("flow_parse", slot.get("flow_parse", True)))
    slot["flow_script"] = bool(payload.get("flow_script", slot.get("flow_script", True)))
    slot["flow_image"] = bool(payload.get("flow_image", slot.get("flow_image", True)))
    slot["test_b_image_limit"] = max(0, int(payload.get("test_b_image_limit") or slot.get("test_b_image_limit") or 0))
    slot.update(_science_model_fields_from_console())
    toc = payload.get("toc")
    if isinstance(toc, list):
        clean_toc = []
        for idx, row in enumerate(toc):
            if not isinstance(row, dict):
                continue
            title = str(row.get("title") or "").strip()
            if not title:
                continue
            clean_toc.append({
                "index": int(row.get("index", idx) or idx),
                "title": title,
                "level": max(1, int(row.get("level", 1) or 1)),
                "page": int(row.get("page", 0) or 0),
                "selected": bool(row.get("selected")),
                "scriptable": bool(row.get("scriptable", _scriptable_science_chapter(title))),
                "parsed": bool(row.get("parsed", False)),
            })
        slot["current_toc"] = clean_toc
    _save_science_first_slot(slot)
    return _science_state_payload(extract=False)


def _clear_folder_contents(value: str) -> tuple[bool, str]:
    raw = _strip_windows_long_prefix(value)
    if not raw:
        return False, "没有可清空的作品文件夹。"
    path = Path(raw).expanduser()
    if not path.exists():
        path.mkdir(parents=True, exist_ok=True)
        return True, str(path)
    if not path.is_dir():
        return False, "目标不是文件夹，已拒绝清空。"
    for child in path.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    return True, str(path)


def _read_secret(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig").replace("\ufeff", "").strip()
    except Exception:
        return ""


def _minimax_provider_from_config() -> str:
    settings = _read_json(SETTINGS_FILE, {})
    models = _read_json(MODEL_DEFAULTS_FILE, {})
    provider = str(settings.get("minimax_provider") or "").strip().lower() if isinstance(settings, dict) else ""
    base_url = str(models.get("minimax_base_url") or "").strip().lower() if isinstance(models, dict) else ""
    if provider == "fast" or "api.53hk.cn" in base_url:
        return "fast"
    if provider == "official" or "api.minimaxi.com" in base_url:
        return "official"
    return ""


def _minimax_key_paths_for_current_provider() -> list[Path]:
    provider = _minimax_provider_from_config()
    if provider == "fast":
        return [MINIMAX_FAST_KEY_FILE, MINIMAX_KEY_FILE, MINIMAX_OFFICIAL_KEY_FILE]
    if provider == "official":
        return [MINIMAX_OFFICIAL_KEY_FILE, MINIMAX_KEY_FILE, MINIMAX_FAST_KEY_FILE]
    return [MINIMAX_KEY_FILE, MINIMAX_FAST_KEY_FILE, MINIMAX_OFFICIAL_KEY_FILE]


def _read_model_secret(key_name: str) -> tuple[str, Path]:
    paths = _minimax_key_paths_for_current_provider() if key_name == "minimax_api_key" else [MODEL_KEY_FILES[key_name], *MODEL_KEY_FALLBACK_FILES.get(key_name, [])]
    for path in paths:
        value = _read_secret(path)
        if value:
            return value, path
    return "", MODEL_KEY_FILES[key_name]


def _profile_exists(data: dict[str, Any], profile_id: str) -> bool:
    return any(
        isinstance(item, dict) and _profile_id(str(item.get("id") or "")) == profile_id
        for item in data.get("profiles", [])
    )


def _read_test_secret(key_name: str, payload: dict[str, Any]) -> tuple[str, Path, bool]:
    inline_value = str(payload.get(key_name) or "").strip()
    if inline_value:
        return inline_value, MODEL_KEY_FILES[key_name], False
    profile_id = _profile_id(str(payload.get("profile_id") or ""))
    if profile_id and key_name in PROFILE_MODEL_KEY_NAMES:
        data = _read_model_profiles()
        if _profile_exists(data, profile_id):
            path = _profile_secret_path(profile_id, key_name)
            return _read_secret(path), path, True
    value, path = _read_model_secret(key_name)
    return value, path, False


def _write_secret(path: Path, value: str) -> None:
    text = str(value or "").strip()
    if text:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")


def _clear_secret(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _profile_id(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", str(value or "").strip()).strip("-").lower()
    return slug[:48] or f"profile-{int(time.time())}"


def _default_profile_models() -> dict[str, str]:
    shared_base_url = DEFAULT_FOREIGN_BASE_URL
    return {
        "foreign_base_url": shared_base_url,
        "deepseek_base_url": DEFAULT_DEEPSEEK_BASE_URL,
        "culture_text_base_url": DEFAULT_FOREIGN_BASE_URL,
        "culture_polish_base_url": DEFAULT_FOREIGN_BASE_URL,
        "culture_image_base_url": DEFAULT_FOREIGN_BASE_URL,
        "research_text_base_url": DEFAULT_FOREIGN_BASE_URL,
        "research_polish_base_url": DEFAULT_FOREIGN_BASE_URL,
        "research_image_base_url": DEFAULT_FOREIGN_BASE_URL,
        "culture_text_provider": "openai",
        "culture_text_model": "gpt-5.5",
        "culture_polish_provider": "openai",
        "culture_polish_model": "gpt-5.5",
        "culture_image_provider": "openai",
        "culture_image_model": "gpt-image-2",
        "gpt_base_url": shared_base_url,
        "gpt_pro_base_url": DEFAULT_GPT_PRO_BASE_URL,
        "gpt_image_base_url": shared_base_url,
        "text_engine": "gpt-5.5",
        "polish_engine": "gpt-5.5",
        "image_engine": "gpt-image-2",
        "minimax_base_url": DEFAULT_MINIMAX_BASE_URL,
        "minimax_tts_model": "speech-2.8-hd",
        "gpt_pro_model": "gpt-5.5",
    }


def _profile_secret_path(profile_id: str, key_name: str) -> Path:
    return MODEL_PROFILE_SECRET_DIR / _profile_id(profile_id) / f"{key_name}.txt"


def _connection_id(value: str) -> str:
    return _profile_id(value)


def _connection_secret_path(connection_id: str, key_name: str) -> Path:
    return MODEL_CONNECTION_SECRET_DIR / _connection_id(connection_id) / f"{key_name}.txt"


def _model_connection_role(value: str) -> str:
    role = str(value or "").strip().lower()
    aliases = {
        "openai": "text",
        "gpt": "text",
        "txt": "text",
        "deepseek": "polish",
        "tts": "minimax",
        "bgm": "minimax",
    }
    role = aliases.get(role, role)
    return role if role in MODEL_CONNECTION_ROLES else "text"


def _provider_for_connection_role(role: str) -> str:
    return str(MODEL_CONNECTION_ROLES.get(role, {}).get("provider") or role)


def _key_for_connection_role(role: str) -> str:
    return str(MODEL_CONNECTION_ROLES.get(role, {}).get("key_name") or "openai_api_key")


def _connection_has_key(connection: dict[str, Any]) -> bool:
    cid = _connection_id(str(connection.get("id") or ""))
    key_name = str(connection.get("key_name") or _key_for_connection_role(str(connection.get("role") or "")))
    return bool(_read_secret(_connection_secret_path(cid, key_name)))


def _connection_public_item(connection: dict[str, Any]) -> dict[str, Any]:
    role = _model_connection_role(str(connection.get("role") or ""))
    cid = _connection_id(str(connection.get("id") or connection.get("name") or f"{role}-connection"))
    key_name = str(connection.get("key_name") or _key_for_connection_role(role))
    item = {
        "id": cid,
        "role": role,
        "role_label": str(MODEL_CONNECTION_ROLES[role]["label"]),
        "name": str(connection.get("name") or cid),
        "provider": str(connection.get("provider") or _provider_for_connection_role(role)),
        "base_url": str(connection.get("base_url") or ""),
        "model": str(connection.get("model") or ""),
        "key_name": key_name,
        "enabled": bool(connection.get("enabled", True)),
        "priority": int(connection.get("priority") or 100),
        "last_test_ok": bool(connection.get("last_test_ok", False)),
        "last_tested_at": str(connection.get("last_tested_at") or ""),
        "last_test_message": str(connection.get("last_test_message") or ""),
        "latency_ms": int(float(connection.get("latency_ms") or 0)),
        "key_configured": bool(_read_secret(_connection_secret_path(cid, key_name))),
    }
    if connection.get("locked"):
        item["locked"] = True
    return item


def _connection_from_models(role: str, name: str, models: dict[str, Any], *, priority: int, locked: bool = False) -> dict[str, Any]:
    role = _model_connection_role(role)
    if role == "text":
        base_url = str(models.get("gpt_base_url") or models.get("culture_text_base_url") or models.get("foreign_base_url") or DEFAULT_FOREIGN_BASE_URL)
        model = str(models.get("culture_text_model") or models.get("text_engine") or "gpt-5.5")
    elif role == "gpt_pro":
        base_url = str(models.get("gpt_pro_base_url") or models.get("culture_text_base_url") or models.get("foreign_base_url") or DEFAULT_FOREIGN_BASE_URL)
        model = str(models.get("gpt_pro_model") or models.get("culture_text_model") or models.get("text_engine") or "gpt-5.5")
    elif role == "polish":
        base_url = str(models.get("deepseek_base_url") or models.get("culture_polish_base_url") or DEFAULT_DEEPSEEK_BASE_URL)
        model = str(models.get("culture_polish_model") or models.get("polish_engine") or "gpt-5.5")
    elif role == "image":
        base_url = str(models.get("gpt_image_base_url") or models.get("culture_image_base_url") or models.get("foreign_base_url") or DEFAULT_FOREIGN_BASE_URL)
        model = str(models.get("culture_image_model") or models.get("image_engine") or "gpt-image-2")
    else:
        base_url = str(models.get("minimax_base_url") or DEFAULT_MINIMAX_BASE_URL)
        model = str(models.get("minimax_tts_model") or "speech-2.8-hd")
    if role == "minimax":
        base_url = _minimax_base_url(base_url)
    elif role == "polish":
        base_url = str(base_url or DEFAULT_DEEPSEEK_BASE_URL).strip().rstrip("/")
    else:
        base_url = _normalized_defaultable_base_url(base_url, DEFAULT_FOREIGN_BASE_URL)
    cid = _connection_id(f"{role}-{name}-{base_url}-{model}")
    return {
        "id": cid,
        "role": role,
        "name": name,
        "provider": _provider_for_connection_role(role),
        "base_url": base_url,
        "model": model,
        "key_name": _key_for_connection_role(role),
        "enabled": True,
        "priority": priority,
        "locked": locked,
    }


def _seed_default_profile_keys() -> None:
    profile_id = DEFAULT_PROFILE_ID
    for key_name in PROFILE_MODEL_KEY_NAMES:
        target = _profile_secret_path(profile_id, key_name)
        if target.exists() and _read_secret(target):
            continue
        for fallback in MODEL_KEY_FALLBACK_FILES.get(key_name, []):
            value = _read_secret(fallback)
            if value:
                _write_secret(target, value)
                break


def _seed_connection_library_from_profiles(data: dict[str, Any]) -> dict[str, Any]:
    existing = data.get("connections")
    if not isinstance(existing, list):
        existing = []
    deleted = {
        _connection_id(str(item or ""))
        for item in (data.get("deleted_connections") if isinstance(data.get("deleted_connections"), list) else [])
    }
    by_id = {
        _connection_id(str(item.get("id") or "")): item
        for item in existing
        if isinstance(item, dict) and _connection_id(str(item.get("id") or "")) not in deleted
    }
    priority = 10
    models = _read_json(MODEL_DEFAULTS_FILE, {})
    if isinstance(models, dict):
        for role in MODEL_CONNECTION_ROLE_ORDER:
            conn = _connection_from_models(role, "当前默认", models, priority=priority, locked=True)
            if conn["id"] not in deleted:
                by_id.setdefault(conn["id"], conn)
            priority += 10
    profiles = _read_json(MODEL_PROFILES_FILE, {})
    profile_items = profiles.get("profiles") if isinstance(profiles, dict) else []
    if isinstance(profile_items, list):
        for profile in profile_items:
            if not isinstance(profile, dict):
                continue
            profile_models = profile.get("models") if isinstance(profile.get("models"), dict) else {}
            name = str(profile.get("name") or profile.get("id") or "方案")
            for role in MODEL_CONNECTION_ROLE_ORDER:
                conn = _connection_from_models(role, name, profile_models, priority=priority, locked=bool(profile.get("locked")))
                if conn["id"] in deleted:
                    priority += 10
                    continue
                by_id.setdefault(conn["id"], conn)
                source_key = _profile_secret_path(str(profile.get("id") or ""), str(conn.get("key_name") or ""))
                target_key = _connection_secret_path(str(conn.get("id") or ""), str(conn.get("key_name") or ""))
                if source_key.exists() and _read_secret(source_key) and not _read_secret(target_key):
                    _write_secret(target_key, _read_secret(source_key))
                priority += 10
    for role in MODEL_CONNECTION_ROLE_ORDER:
        key_name = _key_for_connection_role(role)
        for conn in list(by_id.values()):
            if isinstance(conn, dict) and _model_connection_role(str(conn.get("role") or "")) == role:
                target_key = _connection_secret_path(str(conn.get("id") or ""), key_name)
                if not _read_secret(target_key):
                    value, _ = _read_model_secret(key_name)
                    if value:
                        _write_secret(target_key, value)
                break
    data["connections"] = sorted(by_id.values(), key=lambda item: (int(item.get("priority") or 100), str(item.get("name") or "")))
    for item in data["connections"]:
        if not isinstance(item, dict):
            continue
        role = _model_connection_role(str(item.get("role") or ""))
        base_url = str(item.get("base_url") or "").strip().rstrip("/")
        if role == "polish" and base_url == f"{DEFAULT_DEEPSEEK_BASE_URL}/v1":
            item["base_url"] = DEFAULT_DEEPSEEK_BASE_URL
    return data


def _read_model_connection_library() -> dict[str, Any]:
    data = _read_json(MODEL_CONNECTION_LIBRARY_FILE, {})
    if not isinstance(data, dict):
        data = {}
    data = _seed_connection_library_from_profiles(data)
    data["active_connections"] = data.get("active_connections") if isinstance(data.get("active_connections"), dict) else {}
    data["step_routes"] = data.get("step_routes") if isinstance(data.get("step_routes"), dict) else {}
    for step, meta in MODEL_STEP_ROUTES.items():
        current = data["step_routes"].get(step)
        if not isinstance(current, list):
            role = str(meta.get("role") or "text")
            current = [
                str(item.get("id") or "")
                for item in data.get("connections", [])
                if isinstance(item, dict) and _model_connection_role(str(item.get("role") or "")) == role
            ][:3]
        allowed_roles = {str(x) for x in (meta.get("roles") or (meta.get("role") or "text",))}
        cleaned: list[str] = []
        for raw in current:
            cid = _connection_id(str(raw or ""))
            item = _connection_by_id(data, cid)
            if item and bool(item.get("enabled", True)) and _model_connection_role(str(item.get("role") or "")) in allowed_roles and cid not in cleaned:
                cleaned.append(cid)
        for item in data.get("connections", []):
            if not isinstance(item, dict):
                continue
            cid = _connection_id(str(item.get("id") or ""))
            if bool(item.get("enabled", True)) and _model_connection_role(str(item.get("role") or "")) in allowed_roles and cid and cid not in cleaned:
                cleaned.append(cid)
        data["step_routes"][step] = cleaned
    _repair_active_model_connections(data)
    _write_json(MODEL_CONNECTION_LIBRARY_FILE, data)
    return data


def _public_model_connection_library(data: dict[str, Any] | None = None) -> dict[str, Any]:
    data = data or _read_model_connection_library()
    connections = data.get("connections") if isinstance(data.get("connections"), list) else []
    public = [_connection_public_item(item) for item in connections if isinstance(item, dict)]
    grouped: dict[str, list[dict[str, Any]]] = {role: [] for role in MODEL_CONNECTION_ROLE_ORDER}
    by_provider_model: dict[str, dict[str, Any]] = {}
    for item in public:
        grouped.setdefault(str(item.get("role") or "text"), []).append(item)
        provider = str(item.get("provider") or "unknown")
        model = str(item.get("model") or "未设置")
        key = f"{provider}::{model}"
        group = by_provider_model.setdefault(key, {"provider": provider, "model": model, "connections": []})
        group["connections"].append(item)
    routes = data.get("step_routes") if isinstance(data.get("step_routes"), dict) else {}
    return {
        "roles": {role: dict(MODEL_CONNECTION_ROLES[role]) for role in MODEL_CONNECTION_ROLE_ORDER},
        "steps": {step: {**dict(MODEL_STEP_ROUTES[step]), "roles": list(MODEL_STEP_ROUTES[step].get("roles") or (MODEL_STEP_ROUTES[step].get("role"),))} for step in MODEL_STEP_ORDER},
        "step_routes": {step: [str(x) for x in routes.get(step, []) if str(x or "")] for step in MODEL_STEP_ORDER},
        "active_connections": data.get("active_connections") if isinstance(data.get("active_connections"), dict) else {},
        "connections": public,
        "grouped": grouped,
        "by_provider_model": list(by_provider_model.values()),
    }


def _connection_sort_key(item: dict[str, Any], *, active_id: str = "") -> tuple[int, int, int, int, int, str]:
    tested = 0 if item.get("last_test_ok") else 1
    key_ready = 0 if _connection_has_key(item) else 1
    active_bias = 0 if active_id and _connection_id(str(item.get("id") or "")) == active_id else 1
    latency = int(float(item.get("latency_ms") or 999999))
    return (tested, key_ready, active_bias, latency, int(item.get("priority") or 100), str(item.get("name") or ""))


def _connection_by_id(data: dict[str, Any], connection_id: str) -> dict[str, Any] | None:
    cid = _connection_id(connection_id)
    for item in data.get("connections", []):
        if isinstance(item, dict) and _connection_id(str(item.get("id") or "")) == cid:
            return item
    return None


def _repair_active_model_connections(data: dict[str, Any]) -> bool:
    changed = False
    active = data.get("active_connections") if isinstance(data.get("active_connections"), dict) else {}
    for role in MODEL_CONNECTION_ROLE_ORDER:
        cid = _connection_id(str(active.get(role) or ""))
        if cid and _connection_by_id(data, cid):
            continue
        best = _best_connection_for_role(role, data)
        if best and _connection_id(str(best.get("id") or "")) != cid:
            active[role] = _connection_id(str(best.get("id") or ""))
            changed = True
    data["active_connections"] = active
    return changed


def _best_connection_for_step(step: str, data: dict[str, Any] | None = None) -> dict[str, Any] | None:
    data = data or _read_model_connection_library()
    meta = MODEL_STEP_ROUTES.get(step)
    if not meta:
        return None
    allowed_roles = {str(x) for x in (meta.get("roles") or (meta.get("role") or "text",))}
    routes = data.get("step_routes") if isinstance(data.get("step_routes"), dict) else {}
    candidate_ids = [str(x or "") for x in routes.get(step, []) if str(x or "")]
    candidates: list[dict[str, Any]] = []
    for cid in candidate_ids:
        item = _connection_by_id(data, cid)
        if item and bool(item.get("enabled", True)) and _model_connection_role(str(item.get("role") or "")) in allowed_roles:
            candidates.append(item)
    if candidates:
        active = data.get("active_connections") if isinstance(data.get("active_connections"), dict) else {}
        active_ids = {_connection_id(str(active.get(step) or "")), _connection_id(str(active.get(str(MODEL_STEP_ROUTES[step].get("role") or "")) or ""))}
        active_id = next((cid for cid in candidate_ids if _connection_id(cid) in active_ids), "")
        return sorted(candidates, key=lambda item: _connection_sort_key(item, active_id=active_id))[0]
    for role in allowed_roles:
        conn = _best_connection_for_role(role, data)
        if conn:
            return conn
    return None


def _best_connection_for_role(role: str, data: dict[str, Any] | None = None) -> dict[str, Any] | None:
    role = _model_connection_role(role)
    data = data or _read_model_connection_library()
    connections = [
        item for item in data.get("connections", [])
        if isinstance(item, dict) and _model_connection_role(str(item.get("role") or "")) == role and bool(item.get("enabled", True))
    ]
    if not connections:
        return None
    active = data.get("active_connections") if isinstance(data.get("active_connections"), dict) else {}
    active_id = _connection_id(str(active.get(role) or ""))
    return sorted(connections, key=lambda item: _connection_sort_key(item, active_id=active_id))[0]


def _models_from_connection_library(models: dict[str, Any] | None = None) -> dict[str, Any]:
    result = dict(models or _model_settings())
    data = _read_model_connection_library()
    selected: dict[str, str] = {}
    for step in MODEL_STEP_ORDER:
        meta = MODEL_STEP_ROUTES[step]
        role = str(meta.get("role") or "text")
        conn = _best_connection_for_step(step, data) or _best_connection_for_role(role, data)
        if not conn:
            continue
        cid = _connection_id(str(conn.get("id") or ""))
        selected[step] = cid
        base_url = str(conn.get("base_url") or "")
        model = str(conn.get("model") or "")
        if step == "script_text":
            normalized = _normalized_defaultable_base_url(base_url, DEFAULT_FOREIGN_BASE_URL)
            result["foreign_base_url"] = normalized
            result["gpt_base_url"] = normalized
            result["culture_text_base_url"] = normalized
            result["culture_text_provider"] = str(conn.get("provider") or "openai")
            result["culture_text_model"] = model
            result["text_engine"] = model
            selected["text"] = cid
        elif step == "research_text":
            normalized = _normalized_defaultable_base_url(base_url, str(result.get("foreign_base_url") or DEFAULT_FOREIGN_BASE_URL))
            result["research_text_base_url"] = normalized
            result["text_engine"] = result.get("text_engine") or model
        elif step == "gpt_pro_backup":
            result["gpt_pro_base_url"] = _normalized_defaultable_base_url(base_url, str(result.get("foreign_base_url") or DEFAULT_FOREIGN_BASE_URL))
            result["gpt_pro_model"] = model
            selected["gpt_pro"] = cid
        elif step == "polish_text":
            provider = str(conn.get("provider") or "deepseek").strip() or "deepseek"
            if provider in {"openai", "gpt_pro", "text"}:
                normalized = _normalized_defaultable_base_url(base_url, str(result.get("foreign_base_url") or DEFAULT_FOREIGN_BASE_URL))
                result["gpt_pro_base_url"] = normalized
            else:
                normalized = str(base_url or DEFAULT_DEEPSEEK_BASE_URL).strip().rstrip("/")
                result["deepseek_base_url"] = normalized
            result["culture_polish_base_url"] = normalized
            result["research_polish_base_url"] = normalized
            result["culture_polish_provider"] = provider
            result["culture_polish_model"] = model
            result["polish_engine"] = model
            selected["polish"] = cid
        elif step == "image_generation":
            normalized = _normalized_defaultable_base_url(base_url, str(result.get("foreign_base_url") or DEFAULT_FOREIGN_BASE_URL))
            result["gpt_image_base_url"] = normalized
            result["culture_image_base_url"] = normalized
            result["research_image_base_url"] = normalized
            image_provider = str(conn.get("provider") or "openai").strip() or "openai"
            result["culture_image_provider"] = "openai" if image_provider in {"image", "gpt_image", "gpt-image"} else image_provider
            result["culture_image_model"] = model
            result["image_engine"] = model
            selected["image"] = cid
        elif step == "voice_bgm":
            result["minimax_base_url"] = _minimax_base_url(base_url)
            result["minimax_tts_model"] = model
            selected["minimax"] = cid
        key_name = str(conn.get("key_name") or _key_for_connection_role(role))
        key_value = _read_secret(_connection_secret_path(cid, key_name))
        if key_value and key_name in MODEL_KEY_FILES:
            _write_secret(MODEL_KEY_FILES[key_name], key_value)
    data["active_connections"] = {**(data.get("active_connections") if isinstance(data.get("active_connections"), dict) else {}), **selected}
    _write_json(MODEL_CONNECTION_LIBRARY_FILE, data)
    return result


def _apply_connection_library_to_defaults(*, mark_changed: bool = False) -> dict[str, Any]:
    models = _models_from_connection_library(_model_settings())
    _write_json(MODEL_DEFAULTS_FILE, _strip_private_model_fields(models))
    if mark_changed:
        _mark_shared_config_changed()
        _sync_shared_model_config_to_projects(models)
    return models


def _activate_profile_connections(profile: dict[str, Any]) -> None:
    models = profile.get("models") if isinstance(profile.get("models"), dict) else {}
    if not models:
        return
    data = _read_model_connection_library()
    profile_name = str(profile.get("name") or profile.get("id") or "当前方案")
    existing = [item for item in data.get("connections", []) if isinstance(item, dict)]
    by_id = {_connection_id(str(item.get("id") or "")): item for item in existing}
    active = data.get("active_connections") if isinstance(data.get("active_connections"), dict) else {}
    for priority, role in enumerate(MODEL_CONNECTION_ROLE_ORDER, start=1):
        conn = _connection_from_models(role, profile_name, models, priority=priority * 10, locked=bool(profile.get("locked")))
        cid = _connection_id(str(conn.get("id") or ""))
        preserved = by_id.get(cid, {})
        by_id[cid] = {**preserved, **conn}
        active[role] = cid
        key_name = str(conn.get("key_name") or _key_for_connection_role(role))
        profile_key = _profile_secret_path(str(profile.get("id") or ""), key_name)
        target_key = _connection_secret_path(cid, key_name)
        if _read_secret(profile_key) and not _read_secret(target_key):
            _write_secret(target_key, _read_secret(profile_key))
    data["connections"] = sorted(by_id.values(), key=lambda item: (int(item.get("priority") or 100), str(item.get("name") or "")))
    data["active_connections"] = active
    step_routes = data.get("step_routes") if isinstance(data.get("step_routes"), dict) else {}
    active_routes = {
        "script_text": [active.get("text", "")],
        "research_text": [active.get("text", "")],
        "polish_text": [active.get("polish", ""), active.get("text", "")],
        "image_generation": [active.get("image", "")],
        "gpt_pro_backup": [active.get("gpt_pro", ""), active.get("text", "")],
        "voice_bgm": [active.get("minimax", "")],
    }
    for step, ids in active_routes.items():
        merged: list[str] = []
        for raw in [*ids, *(step_routes.get(step) if isinstance(step_routes.get(step), list) else [])]:
            cid = _connection_id(str(raw or ""))
            if cid and cid not in merged:
                merged.append(cid)
        step_routes[step] = merged
    data["step_routes"] = {k: [x for x in v if x] for k, v in step_routes.items() if isinstance(v, list)}
    _write_json(MODEL_CONNECTION_LIBRARY_FILE, data)


def _save_model_connection(payload: dict[str, Any]) -> dict[str, Any]:
    data = _read_model_connection_library()
    role = _model_connection_role(str(payload.get("role") or "text"))
    name = str(payload.get("name") or payload.get("connection_name") or "").strip() or str(MODEL_CONNECTION_ROLES[role]["label"])
    base_url = str(payload.get("base_url") or "").strip()
    model = str(payload.get("model") or "").strip()
    if not base_url or not model:
        raise ValueError("base_url and model are required")
    if role == "minimax":
        base_url = _minimax_base_url(base_url)
    elif role == "polish":
        base_url = base_url.rstrip("/")
    else:
        base_url = _normalized_defaultable_base_url(base_url, DEFAULT_FOREIGN_BASE_URL)
    cid = _connection_id(str(payload.get("connection_id") or payload.get("id") or f"{role}-{name}-{base_url}-{model}"))
    key_name = _key_for_connection_role(role)
    connections = [
        item for item in data.get("connections", [])
        if isinstance(item, dict) and _connection_id(str(item.get("id") or "")) != cid
    ]
    existing_priority = int(str(payload.get("priority") or "0") or 0)
    if not existing_priority:
        existing_priority = max([int(item.get("priority") or 0) for item in connections if isinstance(item, dict)] or [0]) + 10
    connections.append({
        "id": cid,
        "role": role,
        "name": name,
        "provider": str(payload.get("provider") or _provider_for_connection_role(role)).strip() or _provider_for_connection_role(role),
        "base_url": base_url,
        "model": model,
        "key_name": key_name,
        "enabled": True,
        "priority": existing_priority,
    })
    data["connections"] = connections
    deleted = data.get("deleted_connections") if isinstance(data.get("deleted_connections"), list) else []
    data["deleted_connections"] = [item for item in deleted if _connection_id(str(item or "")) != cid]
    active = data.get("active_connections") if isinstance(data.get("active_connections"), dict) else {}
    active[role] = cid
    data["active_connections"] = active
    key_value = str(payload.get("api_key") or payload.get(key_name) or "").strip()
    if key_value:
        _write_secret(_connection_secret_path(cid, key_name), key_value)
        if key_name in MODEL_KEY_FILES:
            _write_secret(MODEL_KEY_FILES[key_name], key_value)
    _write_json(MODEL_CONNECTION_LIBRARY_FILE, data)
    _apply_connection_library_to_defaults(mark_changed=True)
    return _public_model_connection_library(data)


def _set_active_model_connection(payload: dict[str, Any]) -> dict[str, Any]:
    data = _read_model_connection_library()
    role = _model_connection_role(str(payload.get("role") or "text"))
    cid = _connection_id(str(payload.get("connection_id") or payload.get("id") or ""))
    if not any(isinstance(item, dict) and _connection_id(str(item.get("id") or "")) == cid and _model_connection_role(str(item.get("role") or "")) == role for item in data.get("connections", [])):
        raise ValueError("connection not found")
    active = data.get("active_connections") if isinstance(data.get("active_connections"), dict) else {}
    active[role] = cid
    data["active_connections"] = active
    _write_json(MODEL_CONNECTION_LIBRARY_FILE, data)
    _apply_connection_library_to_defaults(mark_changed=True)
    return _public_model_connection_library(data)


def _save_step_route(payload: dict[str, Any]) -> dict[str, Any]:
    data = _read_model_connection_library()
    step = str(payload.get("step") or "").strip()
    if step not in MODEL_STEP_ROUTES:
        raise ValueError("unknown step")
    allowed_roles = {str(x) for x in (MODEL_STEP_ROUTES[step].get("roles") or (MODEL_STEP_ROUTES[step].get("role") or "text",))}
    raw_ids = payload.get("connection_ids")
    if not isinstance(raw_ids, list):
        raw_ids = []
    ids: list[str] = []
    for raw in raw_ids:
        cid = _connection_id(str(raw or ""))
        item = _connection_by_id(data, cid)
        if item and _model_connection_role(str(item.get("role") or "")) in allowed_roles and cid not in ids:
            ids.append(cid)
    routes = data.get("step_routes") if isinstance(data.get("step_routes"), dict) else {}
    routes[step] = ids
    data["step_routes"] = routes
    _write_json(MODEL_CONNECTION_LIBRARY_FILE, data)
    _apply_connection_library_to_defaults(mark_changed=True)
    return _public_model_connection_library(data)


def _delete_model_connection(payload: dict[str, Any]) -> dict[str, Any]:
    data = _read_model_connection_library()
    cid = _connection_id(str(payload.get("connection_id") or payload.get("id") or ""))
    if not cid:
        raise ValueError("connection not found")
    connections = data.get("connections") if isinstance(data.get("connections"), list) else []
    kept: list[dict[str, Any]] = []
    removed: dict[str, Any] | None = None
    for item in connections:
        if isinstance(item, dict) and _connection_id(str(item.get("id") or "")) == cid:
            removed = item
        elif isinstance(item, dict):
            kept.append(item)
    if not removed:
        raise ValueError("connection not found")
    data["connections"] = kept
    deleted = data.get("deleted_connections") if isinstance(data.get("deleted_connections"), list) else []
    if cid not in deleted:
        deleted.append(cid)
    data["deleted_connections"] = deleted
    active = data.get("active_connections") if isinstance(data.get("active_connections"), dict) else {}
    role = _model_connection_role(str(removed.get("role") or ""))
    if _connection_id(str(active.get(role) or "")) == cid:
        active.pop(role, None)
    data["active_connections"] = active
    for key_name in PROFILE_MODEL_KEY_NAMES:
        _clear_secret(_connection_secret_path(cid, key_name))
    _write_json(MODEL_CONNECTION_LIBRARY_FILE, data)
    _apply_connection_library_to_defaults(mark_changed=True)
    return _public_model_connection_library(data)


def _read_model_profiles() -> dict[str, Any]:
    data = _read_json(MODEL_PROFILES_FILE, {})
    if not isinstance(data, dict):
        data = {}
    profiles = data.get("profiles")
    if not isinstance(profiles, list):
        profiles = []
    default_profile = {
        "id": DEFAULT_PROFILE_ID,
        "name": "DST 系列",
        "locked": True,
        "models": _default_profile_models(),
    }
    by_id = {str(item.get("id") or ""): item for item in profiles if isinstance(item, dict)}
    by_id.pop("foreign-default", None)
    by_id[DEFAULT_PROFILE_ID] = {**default_profile, **by_id.get(DEFAULT_PROFILE_ID, {})}
    by_id[DEFAULT_PROFILE_ID]["id"] = DEFAULT_PROFILE_ID
    by_id[DEFAULT_PROFILE_ID]["name"] = by_id[DEFAULT_PROFILE_ID].get("name") or "DST 系列"
    by_id[DEFAULT_PROFILE_ID]["locked"] = True
    by_id[DEFAULT_PROFILE_ID]["models"] = {**_default_profile_models(), **(by_id[DEFAULT_PROFILE_ID].get("models") or {})}
    data["profiles"] = list(by_id.values())
    active = str(data.get("active_profile") or DEFAULT_PROFILE_ID)
    if active == "foreign-default" or active not in by_id:
        active = DEFAULT_PROFILE_ID
    data["active_profile"] = active
    _seed_default_profile_keys()
    _write_json(MODEL_PROFILES_FILE, data)
    return data


def _profile_public_status(data: dict[str, Any] | None = None) -> dict[str, Any]:
    data = data or _read_model_profiles()
    public_profiles: list[dict[str, Any]] = []
    for item in data.get("profiles", []):
        if not isinstance(item, dict):
            continue
        pid = _profile_id(str(item.get("id") or ""))
        configured = {
            key: bool(_read_secret(_profile_secret_path(pid, key)))
            for key in PROFILE_MODEL_KEY_NAMES
        }
        public_profiles.append({
            "id": pid,
            "name": str(item.get("name") or pid),
            "locked": bool(item.get("locked")),
            "models": _strip_private_model_fields(item.get("models") or {}),
            "keys": configured,
        })
    return {"active_profile": str(data.get("active_profile") or "foreign-default"), "profiles": public_profiles}


def _current_profile_models(payload: dict[str, Any] | None = None) -> dict[str, str]:
    payload = payload or {}
    models = _read_json(MODEL_DEFAULTS_FILE, {})
    if not isinstance(models, dict):
        models = {}
    result: dict[str, str] = {}
    for key in MODEL_PROFILE_MODEL_FIELDS:
        value = payload.get(key, models.get(key, ""))
        if key == "foreign_base_url":
            value = _normalized_defaultable_base_url(str(value or ""), DEFAULT_FOREIGN_BASE_URL)
        elif key == "deepseek_base_url":
            value = (str(value or "") or DEFAULT_DEEPSEEK_BASE_URL).strip().rstrip("/")
        elif key in PER_MODEL_BASE_URL_FIELDS:
            value = _normalized_defaultable_base_url(str(value or ""), str(result.get("foreign_base_url") or models.get("foreign_base_url") or DEFAULT_FOREIGN_BASE_URL))
        else:
            value = str(value or "")
        result[key] = value
    return result


def _save_current_as_profile(payload: dict[str, Any]) -> dict[str, Any]:
    data = _read_model_profiles()
    name = str(payload.get("profile_name") or payload.get("name") or "").strip()
    profile_id = _profile_id(str(payload.get("profile_id") or name or data.get("active_profile") or "profile"))
    if profile_id == DEFAULT_PROFILE_ID:
        name = name or "DST 系列"
    name = name or profile_id
    profiles = [item for item in data.get("profiles", []) if isinstance(item, dict) and _profile_id(str(item.get("id") or "")) != profile_id]
    locked = profile_id == DEFAULT_PROFILE_ID
    saved_profile = {"id": profile_id, "name": name, "locked": locked, "models": _current_profile_models(payload)}
    profiles.append(saved_profile)
    data["profiles"] = profiles
    data["active_profile"] = profile_id
    _write_json(MODEL_PROFILES_FILE, data)
    for key_name in PROFILE_MODEL_KEY_NAMES:
        value = str(payload.get(key_name) or "").strip()
        if not value:
            value, _ = _read_model_secret(key_name)
        if value:
            _write_secret(_profile_secret_path(profile_id, key_name), value)
    _activate_profile_connections(saved_profile)
    _mark_shared_config_changed()
    _sync_shared_model_config_to_projects()
    return _profile_public_status(data)


def _apply_model_profile(profile_id: str) -> dict[str, Any]:
    profile_id = _profile_id(profile_id)
    data = _read_model_profiles()
    match = None
    for item in data.get("profiles", []):
        if isinstance(item, dict) and _profile_id(str(item.get("id") or "")) == profile_id:
            match = item
            break
    if not match:
        raise ValueError("profile not found")
    models = _read_json(MODEL_DEFAULTS_FILE, {})
    if not isinstance(models, dict):
        models = {}
    for key, value in (match.get("models") or {}).items():
        if key in MODEL_PROFILE_MODEL_FIELDS:
            models[key] = value
    _write_json(MODEL_DEFAULTS_FILE, models)
    for key_name in PROFILE_MODEL_KEY_NAMES:
        active_path = MODEL_KEY_FILES[key_name]
        value = _read_secret(_profile_secret_path(profile_id, key_name))
        if value:
            _write_secret(active_path, value)
        else:
            _clear_secret(active_path)
    data["active_profile"] = profile_id
    _write_json(MODEL_PROFILES_FILE, data)
    _activate_profile_connections(match)
    _mark_shared_config_changed()
    result = _public_settings()
    sync_report = _sync_shared_model_config_to_projects()
    test_report: list[dict[str, Any]] = []
    result["sync_report"] = sync_report
    result["connectivity_report"] = test_report
    result["apply_log"] = _build_model_apply_log(result, sync_report, test_report)
    return result


def _apply_profile_key(profile_id: str, key_name: str) -> dict[str, Any]:
    profile_id = _profile_id(profile_id)
    if key_name not in PROFILE_MODEL_KEY_NAMES:
        raise ValueError("unknown key")
    data = _read_model_profiles()
    if not _profile_exists(data, profile_id):
        raise ValueError("profile not found")
    value = _read_secret(_profile_secret_path(profile_id, key_name))
    if not value:
        raise ValueError("profile key not configured")
    _write_secret(MODEL_KEY_FILES[key_name], value)
    _mark_shared_config_changed()
    result = _public_settings()
    result["sync_report"] = _sync_shared_model_config_to_projects()
    return result


def _delete_model_profile(profile_id: str) -> dict[str, Any]:
    profile_id = _profile_id(profile_id)
    if profile_id == DEFAULT_PROFILE_ID:
        raise ValueError("default profile cannot be deleted")
    data = _read_model_profiles()
    data["profiles"] = [item for item in data.get("profiles", []) if not (isinstance(item, dict) and _profile_id(str(item.get("id") or "")) == profile_id)]
    if data.get("active_profile") == profile_id:
        data["active_profile"] = DEFAULT_PROFILE_ID
    _write_json(MODEL_PROFILES_FILE, data)
    return _profile_public_status(data)


def _read_smtp_password() -> tuple[str, str, str]:
    for path in SMTP_PASSWORD_FILES:
        value = _read_secret(path)
        if value:
            return value, str(path), "鏈湴鏂囦欢"
    for name in SMTP_PASSWORD_ENV_NAMES:
        value = os.environ.get(name, "").strip()
        if value:
            return value, str(SMTP_PASSWORD_FILES[0]), f"鐜鍙橀噺 {name}"
    return "", str(SMTP_PASSWORD_FILES[0]), "未配置"


def _write_smtp_password(value: str) -> None:
    text = str(value or "").strip()
    if not text:
        return
    for path in SMTP_PASSWORD_FILES:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")


def _smtp_status(*, include_value: bool = False) -> dict[str, Any]:
    value, path, source = _read_smtp_password()
    data: dict[str, Any] = {
        "smtp_password_configured": bool(value),
        "smtp_password_path": path,
        "smtp_password_source": source,
    }
    if include_value:
        data["smtp_password"] = value
    return data


def _strip_private_model_fields(data: Any) -> Any:
    if isinstance(data, dict):
        cleaned: dict[str, Any] = {}
        for key, value in data.items():
            lower = str(key).lower()
            if lower == "keys" or "mineru" in lower:
                continue
            if any(word in lower for word in ("password", "secret", "token", "api_key", "apikey", "access_key", "private_key", "auth", "cookie")):
                continue
            cleaned[str(key)] = _strip_private_model_fields(value)
        return cleaned
    if isinstance(data, list):
        return [_strip_private_model_fields(item) for item in data]
    return data


def _secret_statuses(*, include_values: bool = False, only: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {}
    items = [(only, MODEL_KEY_FILES[only])] if only in MODEL_KEY_FILES else list(MODEL_KEY_FILES.items())
    for key, path in items:
        file_value, file_path = _read_model_secret(key)
        env_name = ""
        env_value = ""
        for name in MODEL_KEY_ENV_NAMES.get(key, []):
            value = os.environ.get(name, "").strip()
            if value:
                env_name = name
                env_value = value
                break
        value = file_value or env_value
        result[f"{key}_configured"] = bool(value)
        result[f"{key}_path"] = str(file_path)
        result[f"{key}_source"] = "?????" if file_value else (f"???? {env_name}" if env_value else "???")
        if include_values:
            result[key] = value
    return result


def _safe_error(exc: BaseException) -> str:
    text = re.sub(r"sk-[A-Za-z0-9_-]{8,}", "sk-***", str(exc))
    for key in MODEL_KEY_FILES:
        value, _ = _read_model_secret(key)
        if value:
            text = text.replace(value, "***")
    smtp_value, _, _ = _read_smtp_password()
    if smtp_value:
        text = text.replace(smtp_value, "***")
    return text[:300]


def _http_error_hint(provider: str, exc: urllib.error.HTTPError) -> str:
    if exc.code == 401:
        if provider == "openai":
            return "已连接到 GPT 文本接口，但当前 GPT Key 被服务端拒绝；请检查所选方案的 openai_api_key 是否对该中转站和模型有权限。"
        return "已连接到接口，但当前 Key 被服务端拒绝；请检查 Key 是否属于该服务或是否有模型权限。"
    if exc.code == 403:
        return "已连接到接口，但当前 Key 没有访问该模型/接口的权限。"
    return _safe_error(exc)


def _model_settings() -> dict[str, Any]:
    models = _read_json(MODEL_DEFAULTS_FILE, {})
    return models if isinstance(models, dict) else {}


def _normalized_base_url(value: str, fallback: str) -> str:
    base_url = (value or fallback).strip().rstrip("/")
    if not base_url.endswith("/v1"):
        base_url += "/v1"
    return base_url


def _normalized_defaultable_base_url(value: str, fallback: str) -> str:
    raw = str(value or "").strip().rstrip("/")
    if raw in LEGACY_FOREIGN_BASE_URLS:
        raw = ""
    return _normalized_base_url(raw, fallback)


def _model_base_url(models: dict[str, Any], key: str, fallback: str | None = None) -> str:
    fallback = fallback or str(models.get("foreign_base_url") or DEFAULT_FOREIGN_BASE_URL)
    return _normalized_defaultable_base_url(str(models.get(key) or ""), fallback)


def _minimax_base_url(value: str = "") -> str:
    base = str(value or DEFAULT_MINIMAX_BASE_URL).strip().rstrip("/")
    if "api.53hk.cn" in base.lower():
        return base
    return base + ("" if base.endswith("/v1") else "/v1")


def _models_with_url_defaults(models: dict[str, Any]) -> dict[str, Any]:
    result = dict(models)
    foreign_base = _normalized_defaultable_base_url(str(result.get("foreign_base_url") or ""), DEFAULT_FOREIGN_BASE_URL)
    result["foreign_base_url"] = foreign_base
    result["deepseek_base_url"] = str(result.get("deepseek_base_url") or DEFAULT_DEEPSEEK_BASE_URL).strip().rstrip("/")
    result["minimax_base_url"] = _minimax_base_url(str(result.get("minimax_base_url") or ""))
    for key in PER_MODEL_BASE_URL_FIELDS:
        result[key] = _model_base_url(result, key, foreign_base)
    return result


def _http_json(url: str, *, headers: dict[str, str], payload: dict[str, Any], timeout: int = 30) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", errors="replace")
    try:
        return json.loads(body)
    except Exception:
        return {"raw": body[:500]}


def _http_get_json(url: str, *, headers: dict[str, str], timeout: int = 30) -> dict[str, Any]:
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", errors="replace")
    try:
        return json.loads(body)
    except Exception:
        return {"raw": body[:500]}


def _run_feishu_doc_reader(label: str, command: list[str], cwd: Path, *, env_extra: dict[str, str] | None = None) -> tuple[str, str]:
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    try:
        proc = subprocess.run(
            command,
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=45,
        )
    except Exception as exc:
        return "", f"{label} 异常：{_safe_error(exc)}"
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "读取失败")[-800:]
        return "", f"{label} 失败：{detail}"
    return proc.stdout or "", ""


def _feishu_model_doc_env() -> dict[str, str]:
    refs = [
        MODEL_DOC_SOURCE_URL,
        MODEL_DOC_SOURCE_TOKEN,
        *[x.strip() for x in str(os.environ.get("FEISHU_ALLOWED_DOCUMENT_REFS") or "").split(",") if x.strip()],
    ]
    return {
        "FEISHU_ALLOWED_DOCUMENT_REFS": ",".join(dict.fromkeys(refs)),
        "FEISHU_PERMISSION_MODE": os.environ.get("FEISHU_PERMISSION_MODE", "live_accessible"),
        "FEISHU_READONLY": "true",
    }


def _read_feishu_model_doc_text() -> tuple[str, str]:
    errors: list[str] = []
    xiaozhuli_script = XIAOZHULI_ROOT / "feishu-docs.mjs"
    if XIAOZHULI_ROOT.exists():
        direct_reader = r"""
const ref = String(process.argv[1] || '');
const wikiMatch = ref.match(/\/wiki\/([A-Za-z0-9]+)/);
const docMatch = ref.match(/\/docx\/([A-Za-z0-9]+)/);
const { authed } = await import('./feishu-auth.mjs');
let documentId = docMatch ? docMatch[1] : ref;
if (wikiMatch) {
  const query = new URLSearchParams({ token: wikiMatch[1] });
  const body = await authed(`/wiki/v2/spaces/get_node?${query}`, { method: 'GET' }, 'tenant');
  documentId = body.data?.node?.obj_token || '';
}
if (!documentId) throw new Error('未解析到飞书文档 token');
const raw = await authed(`/docx/v1/documents/${documentId}/raw_content`, { method: 'GET' }, 'tenant');
process.stdout.write(raw.data?.content || raw.data?.raw_content || '');
"""
        text, error = _run_feishu_doc_reader(
            "全澜小猪理白名单读取",
            ["node", "-e", direct_reader, MODEL_DOC_SOURCE_URL],
            XIAOZHULI_ROOT,
            env_extra=_feishu_model_doc_env(),
        )
        if text:
            return text, ""
        if error:
            errors.append(error)
        if xiaozhuli_script.exists():
            text, error = _run_feishu_doc_reader(
                "全澜小猪理脚本读取",
                ["node", str(xiaozhuli_script), "--tenant", "raw", MODEL_DOC_SOURCE_URL],
                XIAOZHULI_ROOT,
                env_extra=_feishu_model_doc_env(),
            )
            if text:
                return text, ""
            if error:
                errors.append(error)
    script = FEISHU_DOCS_WORKDIR / "feishu-docs.mjs"
    if not script.exists():
        script = Path(r"C:\Users\XGN\.codex\skills\feishu-docs-ops\scripts\feishu-docs.mjs")
    if script.exists():
        text, error = _run_feishu_doc_reader(
            "备用 Feishu 脚本读取",
            ["node", str(script), "raw", MODEL_DOC_SOURCE_URL],
            FEISHU_DOCS_WORKDIR if FEISHU_DOCS_WORKDIR.exists() else PROJECT_ROOT,
            env_extra=_feishu_model_doc_env(),
        )
        if text:
            return text, ""
        if error:
            errors.append(error)
    if not errors:
        errors.append("未找到 Feishu 文档读取脚本。")
    return "", "\n".join(errors[-3:])


def _role_from_model_doc_text(text: str) -> str:
    lower = text.lower()
    if any(x in lower for x in ("image", "gpt-image", "生图", "绘图", "图片")):
        return "image"
    if any(x in lower for x in ("minimax", "tts", "speech", "配音", "bgm", "音乐")):
        return "minimax"
    if any(x in lower for x in ("deepseek", "润色", "polish")):
        return "polish"
    if any(x in lower for x in ("gpt-pro", "gpt_pro")):
        return "gpt_pro"
    return "text"


def _provider_from_model_doc_text(text: str, base_url: str) -> str:
    lower = f"{text} {base_url}".lower()
    if "deepseek" in lower:
        return "deepseek"
    if "minimax" in lower or "53hk" in lower:
        return "minimax"
    if "image" in lower or "gpt-image" in lower:
        return "image"
    if "gpt-pro" in lower or "gpt_pro" in lower:
        return "gpt_pro"
    return "openai"


def _model_from_model_doc_text(text: str) -> str:
    lower = text.lower()
    if "gpt-image" in lower or "gpt-image2" in lower or "gpt image" in lower:
        return "gpt-image-2"
    if "gpt-pro" in lower or "gpt_pro" in lower:
        return "gpt-5.5"
    if "deepseek" in lower:
        return "deepseek-chat"
    if "minimax" in lower:
        model_match = re.search(r"\bMiniMax[-_A-Za-z0-9.]+\b", text, re.I)
        return model_match.group(0) if model_match else "speech-2.8-hd"
    if re.search(r"\bgpt\b", lower):
        return "gpt-5.5"
    model_match = re.search(r"\b(?:gpt[-_A-Za-z0-9.]+|deepseek[-_A-Za-z0-9.]+|gpt-image[-_A-Za-z0-9.]+|speech[-_A-Za-z0-9.]+|music[-_A-Za-z0-9.]+|MiniMax[-_A-Za-z0-9.]+)\b", text, re.I)
    return model_match.group(0) if model_match else ""


def _append_model_doc_candidate(
    found: list[dict[str, str]],
    seen: set[tuple[str, str, str]],
    *,
    label: str,
    context: str,
    base_url: str,
    api_key: str = "",
) -> None:
    base_url = str(base_url or "").strip().rstrip("/")
    if not base_url or "feishu.cn" in base_url.lower():
        return
    model = _model_from_model_doc_text(label)
    if not model:
        return
    text = f"{context} {label} {model}"
    role = _role_from_model_doc_text(text)
    provider = _provider_from_model_doc_text(text, base_url)
    if provider == "deepseek":
        role = "polish"
    if provider == "image":
        role = "image"
    if provider == "minimax":
        role = "minimax"
    if "gpt-pro" in text.lower() or "gpt_pro" in text.lower():
        role = "gpt_pro"
        provider = "gpt_pro"
    key = (role, base_url, model)
    if key in seen:
        return
    seen.add(key)
    candidate = {
        "role": role,
        "provider": provider,
        "name": f"飞书文档｜{provider}｜{model}",
        "base_url": base_url,
        "model": model,
    }
    if api_key:
        candidate["api_key"] = api_key
    found.append(candidate)


def _extract_model_doc_connections(text: str) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    url_re = re.compile(r"https?://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]+")
    key_re = re.compile(r"(?:\"key\"\s*:\s*\"([^\"]+)\"|key\s*[：:]\s*([^\s,，]+))", re.I)
    lines = [raw.strip() for raw in text.splitlines()]
    context = ""
    pending_label = ""
    pending_base_url = ""
    pending_model_line = ""
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        lower = line.lower()
        model_line_match = re.search(r"^model\s*[：:]\s*(.+)$", line, re.I)
        if model_line_match and pending_label:
            pending_model_line = model_line_match.group(1).strip()
            pending_label = f"{pending_label} {pending_model_line}"
            continue
        if line.startswith("{"):
            try:
                payload = json.loads(line)
            except Exception:
                payload = {}
            base_url = str(payload.get("url") or payload.get("base_url") or "")
            api_key = str(payload.get("key") or "")
            if pending_label and base_url:
                _append_model_doc_candidate(found, seen, label=pending_label, context=context, base_url=base_url, api_key=api_key)
                pending_label = ""
            continue
        if "系列" in line or "link" in lower or "dstopology" in lower or line in {"FHL系列", "DST系列"}:
            context = line
            continue
        base_match = re.search(r"base\s*url\s*[：:]\s*(https?://\S+)", line, re.I)
        if base_match:
            pending_base_url = base_match.group(1).strip()
            continue
        key_match = key_re.search(line)
        if key_match and pending_label and pending_base_url:
            api_key = str(key_match.group(1) or key_match.group(2) or "").strip()
            _append_model_doc_candidate(found, seen, label=pending_label, context=context, base_url=pending_base_url, api_key=api_key)
            pending_label = ""
            pending_base_url = ""
            pending_model_line = ""
            continue
        if any(token in lower for token in ("gpt", "deepseek", "minimax")) and "key" not in lower and "url" not in lower:
            pending_label = line
            pending_base_url = ""
            pending_model_line = ""
            continue
        urls = url_re.findall(line)
        if not urls:
            continue
        for base_url in urls:
            _append_model_doc_candidate(found, seen, label=line, context=context, base_url=base_url)
    return found


def _merge_model_doc_connections() -> dict[str, Any]:
    text, error = _read_feishu_model_doc_text()
    if error:
        if "tenant needs read permission" in error or '"code":131006' in error:
            error = "飞书文档已加入本地白名单，但飞书云端尚未把该 wiki/docx 授权给全澜小猪理企业应用；请在文档权限中给小猪理/应用开放读取。"
        return {"ok": False, "error": error, "added": [], "candidates": [], "count": 0}
    candidates = _extract_model_doc_connections(text)
    data = _read_model_connection_library()
    existing = {
        (_model_connection_role(str(item.get("role") or "")), str(item.get("base_url") or "").rstrip("/"), str(item.get("model") or ""))
        for item in data.get("connections", [])
        if isinstance(item, dict)
    }
    added: list[dict[str, str]] = []
    connections = data.get("connections") if isinstance(data.get("connections"), list) else []
    priority = max([int(item.get("priority") or 0) for item in connections if isinstance(item, dict)] or [0]) + 10
    for candidate in candidates:
        key = (_model_connection_role(candidate["role"]), candidate["base_url"].rstrip("/"), candidate["model"])
        if key in existing:
            for item in connections:
                if not isinstance(item, dict):
                    continue
                item_key = (_model_connection_role(str(item.get("role") or "")), str(item.get("base_url") or "").rstrip("/"), str(item.get("model") or ""))
                if item_key == key and candidate.get("api_key"):
                    cid = _connection_id(str(item.get("id") or ""))
                    key_name = str(item.get("key_name") or _key_for_connection_role(candidate["role"]))
                    if cid and not _read_secret(_connection_secret_path(cid, key_name)):
                        _write_secret(_connection_secret_path(cid, key_name), str(candidate.get("api_key") or ""))
                    break
            continue
        cid = _connection_id(f"{candidate['role']}-{candidate['provider']}-{candidate['base_url']}-{candidate['model']}")
        connections.append({
            "id": cid,
            "role": candidate["role"],
            "name": candidate["name"],
            "provider": candidate["provider"],
            "base_url": candidate["base_url"],
            "model": candidate["model"],
            "key_name": _key_for_connection_role(candidate["role"]),
            "enabled": True,
            "priority": priority,
            "source": MODEL_DOC_SOURCE_URL,
        })
        if candidate.get("api_key"):
            _write_secret(_connection_secret_path(cid, _key_for_connection_role(candidate["role"])), str(candidate.get("api_key") or ""))
        priority += 10
        added.append({k: v for k, v in candidate.items() if k != "api_key"})
        existing.add(key)
    data["connections"] = connections
    _write_json(MODEL_CONNECTION_LIBRARY_FILE, data)
    public_candidates = [{k: v for k, v in item.items() if k != "api_key"} for item in candidates]
    return {"ok": True, "added": added, "candidates": public_candidates, "count": len(added)}


def _failed_step_keys(report: dict[str, Any]) -> list[str]:
    failed: list[str] = []
    for item in report.get("summary", []):
        if isinstance(item, dict) and not item.get("ok"):
            step = str(item.get("step") or "")
            if step in MODEL_STEP_ROUTES:
                failed.append(step)
    return failed


def _attach_doc_connections_to_failed_steps(failed_steps: list[str], candidates: list[dict[str, Any]]) -> dict[str, Any]:
    data = _read_model_connection_library()
    routes = data.get("step_routes") if isinstance(data.get("step_routes"), dict) else {}
    changed_steps: list[str] = []
    added_route_count = 0
    candidate_keys = {
        (_model_connection_role(str(item.get("role") or "")), str(item.get("base_url") or "").rstrip("/"), str(item.get("model") or ""))
        for item in candidates
        if isinstance(item, dict)
    }
    for step in failed_steps:
        meta = MODEL_STEP_ROUTES.get(step)
        if not meta:
            continue
        allowed_roles = {str(x) for x in (meta.get("roles") or (meta.get("role") or "text",))}
        current = [_connection_id(str(x or "")) for x in routes.get(step, []) if str(x or "")]
        before_count = len(current)
        for item in data.get("connections", []):
            if not isinstance(item, dict):
                continue
            role = _model_connection_role(str(item.get("role") or ""))
            key = (role, str(item.get("base_url") or "").rstrip("/"), str(item.get("model") or ""))
            cid = _connection_id(str(item.get("id") or ""))
            if key in candidate_keys and role in allowed_roles and cid and cid not in current:
                current.append(cid)
        if len(current) != before_count:
            routes[step] = current
            changed_steps.append(step)
            added_route_count += len(current) - before_count
    data["step_routes"] = routes
    if changed_steps:
        _write_json(MODEL_CONNECTION_LIBRARY_FILE, data)
        _apply_connection_library_to_defaults(mark_changed=True)
    return {"changed_steps": changed_steps, "route_count": added_route_count}


def _test_step_routes_with_repair() -> dict[str, Any]:
    initial = _test_step_routes()
    failed_steps = _failed_step_keys(initial)
    repair: dict[str, Any] = {
        "attempted": bool(failed_steps),
        "source": MODEL_DOC_SOURCE_URL,
        "failed_steps": failed_steps,
        "ok": not bool(failed_steps),
        "added_count": 0,
        "changed_steps": [],
        "route_count": 0,
        "error": "",
    }
    if not failed_steps:
        return {**initial, "repair": repair}
    merge = _merge_model_doc_connections()
    repair["ok"] = bool(merge.get("ok"))
    repair["added_count"] = int(merge.get("count") or 0)
    repair["error"] = str(merge.get("error") or "")
    if not merge.get("ok"):
        return {**initial, "repair": repair}
    doc_candidates = merge.get("candidates") if isinstance(merge.get("candidates"), list) else []
    attached = _attach_doc_connections_to_failed_steps(failed_steps, doc_candidates)
    repair["changed_steps"] = attached.get("changed_steps", [])
    repair["route_count"] = int(attached.get("route_count") or 0)
    if repair["added_count"] <= 0 and repair["route_count"] <= 0:
        return {**initial, "repair": repair}
    repaired = _test_step_routes()
    repair["retested"] = True
    repair["remaining_failed_steps"] = _failed_step_keys(repaired)
    return {**repaired, "initial_summary": initial.get("summary", []), "repair": repair}


def _test_model(provider: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    started = time.perf_counter()
    provider = provider.strip().lower()
    models = _model_settings()
    payload = payload if isinstance(payload, dict) else {}
    connection_id = _connection_id(str(payload.get("connection_id") or ""))
    if connection_id:
        library = _read_model_connection_library()
        for item in library.get("connections", []):
            if not isinstance(item, dict) or _connection_id(str(item.get("id") or "")) != connection_id:
                continue
            role = _model_connection_role(str(item.get("role") or ""))
            provider = str(item.get("provider") or _provider_for_connection_role(role)).strip().lower()
            payload = {**payload, "profile_id": ""}
            key_name = str(item.get("key_name") or _key_for_connection_role(role))
            key_value = _read_secret(_connection_secret_path(connection_id, key_name))
            if key_value:
                payload[key_name] = key_value
            base_url = str(item.get("base_url") or "")
            model_name = str(item.get("model") or "")
            if role == "text":
                payload.update({"foreign_base_url": base_url, "culture_text_base_url": base_url, "culture_text_model": model_name, "text_engine": model_name})
                provider = "openai"
            elif role == "gpt_pro":
                payload.update({"gpt_pro_base_url": base_url, "culture_text_model": model_name, "text_engine": model_name})
                provider = "gpt_pro"
            elif role == "polish":
                payload.update({"deepseek_base_url": base_url, "culture_polish_base_url": base_url, "culture_polish_model": model_name, "polish_engine": model_name})
                provider = "deepseek"
            elif role == "image":
                payload.update({"culture_image_base_url": base_url, "gpt_image_base_url": base_url, "culture_image_model": model_name, "image_engine": model_name})
                provider = "image"
            elif role == "minimax":
                payload.update({"minimax_base_url": base_url, "minimax_tts_model": model_name})
                provider = "minimax"
            break
    for key in MODEL_PROFILE_MODEL_FIELDS:
        if key in payload:
            models[key] = str(payload.get(key) or models.get(key) or "")
    foreign_base_value = str(payload.get("foreign_base_url") or models.get("foreign_base_url") or "")
    deepseek_base_value = str(payload.get("deepseek_base_url") or models.get("deepseek_base_url") or "")
    foreign_base = _normalized_base_url(foreign_base_value, DEFAULT_FOREIGN_BASE_URL)
    deepseek_base = (deepseek_base_value or DEFAULT_DEEPSEEK_BASE_URL).strip().rstrip("/")
    culture_text_base = _model_base_url(models, "culture_text_base_url", foreign_base)
    research_text_base = _model_base_url(models, "research_text_base_url", foreign_base)
    culture_image_base = _model_base_url(models, "culture_image_base_url", foreign_base)
    gpt_pro_base = _model_base_url(models, "gpt_pro_base_url", foreign_base)
    attempt_model = ""
    attempt_endpoint = ""
    try:
        if provider == "openai":
            key, _, from_profile = _read_test_secret("openai_api_key", payload)
            if not key:
                message = "所选方案 GPT Key 未配置。" if from_profile else "GPT Key 未配置。"
                return {"ok": False, "message": message, "suggestion": "先粘贴并保存 GPT Key。"}
            model = str(models.get("culture_text_model") or models.get("text_engine") or "GPT")
            attempt_model, attempt_endpoint = model, culture_text_base
            data = _http_json(
                f"{culture_text_base}/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                payload={"model": model, "messages": [{"role": "user", "content": "请只回复 ok"}], "max_tokens": 8},
            )
            ok = bool(data.get("choices"))
            return {"ok": ok, "message": f"GPT 测试{'通过' if ok else '未拿到回复'}。", "model": model, "endpoint": culture_text_base}
        if provider == "gpt_pro":
            key, _, from_profile = _read_test_secret("gpt_pro_api_key", payload)
            if not key:
                message = "所选方案 GPT-Pro Key 未配置。" if from_profile else "GPT-Pro Key 未配置。"
                return {"ok": False, "message": message, "suggestion": "先粘贴并保存 GPT-Pro Key。"}
            model = str(models.get("culture_polish_model") or models.get("polish_engine") or "gpt-5.5")
            if "deepseek" in model.lower():
                model = str(models.get("culture_text_model") or models.get("text_engine") or "gpt-5.5")
            attempt_model, attempt_endpoint = model, gpt_pro_base
            data = _http_json(
                f"{gpt_pro_base}/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                payload={"model": model, "messages": [{"role": "user", "content": "请只回复 ok"}], "max_tokens": 8},
            )
            ok = bool(data.get("choices"))
            return {"ok": ok, "message": f"GPT-Pro 测试{'通过' if ok else '未拿到回复'}。", "model": model, "endpoint": gpt_pro_base}
        if provider in {"deepseek", "gpt_pro"}:
            key, _, from_profile = _read_test_secret("deepseek_api_key", payload)
            if not key:
                message = "所选方案 DeepSeek Key 未配置。" if from_profile else "DeepSeek Key 未配置。"
                return {"ok": False, "message": message, "suggestion": "先粘贴并保存 DeepSeek Key。"}
            model = "deepseek-chat" if provider == "deepseek" else str(models.get("culture_polish_model") or "gpt-5.5")
            attempt_model, attempt_endpoint = model, deepseek_base
            data = _http_json(
                f"{deepseek_base}/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                payload={"model": model, "messages": [{"role": "user", "content": "请只回复 ok"}], "max_tokens": 8},
            )
            ok = bool(data.get("choices"))
            return {"ok": ok, "message": f"DeepSeek 测试{'通过' if ok else '未拿到回复'}。", "model": model, "endpoint": deepseek_base}
        if provider == "image":
            key, _, from_profile = _read_test_secret("image_api_key", payload)
            if not key:
                message = "所选方案绘图 Key 未配置。" if from_profile else "绘图 Key 未配置。"
                return {"ok": False, "message": message, "suggestion": "先粘贴并保存绘图 Key。"}
            model = str(models.get("culture_image_model") or models.get("image_engine") or "gpt-image-2")
            attempt_model, attempt_endpoint = model, culture_image_base
            data = _http_get_json(
                f"{culture_image_base}/models",
                headers={"Authorization": f"Bearer {key}"},
                timeout=30,
            )
            model_ids = {str(item.get("id") or "") for item in data.get("data", []) if isinstance(item, dict)}
            ok = model in model_ids if model_ids else False
            message = f"绘图模型 {model} {'已在模型列表中' if ok else '未在模型列表中'}。未实际生图，避免消耗额度。"
            return {"ok": ok, "message": message, "model": model, "endpoint": culture_image_base, "available_models": sorted(model_ids)[:20]}
        if provider == "minimax":
            key = str(payload.get("minimax_api_key") or "").strip()
            if not key:
                key, _ = _read_model_secret("minimax_api_key")
            if not key:
                return {"ok": False, "message": "MiniMax Key 未配置。", "suggestion": "先粘贴并保存 MiniMax Key。"}
            minimax_base = str(models.get("minimax_base_url") or DEFAULT_MINIMAX_BASE_URL)
            model = str(models.get("minimax_tts_model") or "speech-2.8-hd")
            attempt_model, attempt_endpoint = model, minimax_base
            return {"ok": True, "message": "MiniMax Key 已配置。为避免误生成音频，此按钮暂不自动合成。", "model": model, "endpoint": minimax_base}
        return {"ok": False, "message": "未知测试项。", "model": attempt_model, "endpoint": attempt_endpoint}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "message": f"{provider} 测试失败：HTTP {exc.code}", "suggestion": _http_error_hint(provider, exc), "model": attempt_model, "endpoint": attempt_endpoint}
    except Exception as exc:
        return {"ok": False, "message": f"{provider} 测试失败：{type(exc).__name__}", "suggestion": _safe_error(exc), "model": attempt_model, "endpoint": attempt_endpoint}
    finally:
        pass


def _record_connection_test_result(connection_id: str, result: dict[str, Any]) -> dict[str, Any]:
    cid = _connection_id(connection_id)
    if not cid:
        return _public_model_connection_library()
    data = _read_model_connection_library()
    changed = False
    for item in data.get("connections", []):
        if isinstance(item, dict) and _connection_id(str(item.get("id") or "")) == cid:
            item["last_test_ok"] = bool(result.get("ok"))
            item["last_tested_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            item["last_test_message"] = str(result.get("message") or "")[:240]
            elapsed = result.get("elapsed_seconds")
            try:
                item["latency_ms"] = int(float(elapsed) * 1000)
            except Exception:
                pass
            changed = True
            break
    if changed:
        _write_json(MODEL_CONNECTION_LIBRARY_FILE, data)
    return _public_model_connection_library(data)


MODEL_TEST_PROVIDERS = [
    ("openai", "GPT 文本"),
    ("gpt_pro", "GPT-Pro"),
    ("deepseek", "DeepSeek 润色"),
    ("image", "gpt-image-2 生图"),
    ("minimax", "MiniMax 配音/BGM"),
]


def _test_model_detailed(provider: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    started = time.perf_counter()
    result = _test_model(provider, payload)
    result["provider"] = provider
    result["label"] = dict(MODEL_TEST_PROVIDERS).get(provider, provider)
    result["elapsed_seconds"] = round(time.perf_counter() - started, 2)
    result["tested_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    if provider == "image":
        result.setdefault("test_mode", "只验证 Key、模型名和接口地址；未实际生图，避免消耗额度。")
    elif provider == "minimax":
        result.setdefault("test_mode", "只验证 Key、模型名和接口地址；未实际合成音频，避免消耗额度。")
    else:
        result.setdefault("test_mode", "chat/completions 真实短文本请求。")
    return result


def _test_all_model_links_for_payload(payload: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    payload = payload if isinstance(payload, dict) else {}
    return [_test_model_detailed(provider, payload) for provider, _ in MODEL_TEST_PROVIDERS]


def _test_step_routes() -> dict[str, Any]:
    data = _read_model_connection_library()
    results: list[dict[str, Any]] = []
    summary: list[dict[str, Any]] = []
    for step in MODEL_STEP_ORDER:
        meta = MODEL_STEP_ROUTES[step]
        routes = data.get("step_routes") if isinstance(data.get("step_routes"), dict) else {}
        ids = [str(x or "") for x in routes.get(step, []) if str(x or "")]
        step_results: list[dict[str, Any]] = []
        passed: dict[str, Any] | None = None
        for cid in ids:
            item = _connection_by_id(data, cid)
            if not item:
                continue
            result = _test_model_detailed(str(item.get("provider") or ""), {"connection_id": cid})
            _record_connection_test_result(cid, result)
            row = {"step": step, "step_label": meta["label"], "connection_id": cid, **result}
            step_results.append(row)
            results.append(row)
            if result.get("ok"):
                passed = row
                break
        summary.append({
            "step": step,
            "step_label": meta["label"],
            "candidate_count": len(ids),
            "tested_count": len(step_results),
            "passed_count": 1 if passed else 0,
            "ok": bool(passed),
            "passed_model": str(passed.get("model") or "") if passed else "",
            "passed_provider": str(passed.get("provider") or "") if passed else "",
            "passed_connection_id": str(passed.get("connection_id") or "") if passed else "",
            "latency_ms": int(float(passed.get("elapsed_seconds") or 0) * 1000) if passed else 0,
        })
    return {"results": results, "summary": summary}


def _test_email(payload: dict[str, Any]) -> dict[str, Any]:
    host = str(payload.get("smtp_host") or "").strip()
    user = str(payload.get("smtp_user") or "").strip()
    sender = str(payload.get("smtp_sender") or user).strip()
    password, path, source = _read_smtp_password()
    try:
        port = int(str(payload.get("smtp_port") or "465").strip())
    except Exception:
        return {"ok": False, "message": "SMTP 端口必须是数字。", "suggestion": "QQ 邮箱通常是 465。"}
    if not host or not user or not password:
        return {"ok": False, "message": "SMTP 未配置完整。", "suggestion": "请填写服务器、账号，并保存 SMTP 授权码。", "path": path, "source": source}
    try:
        started = time.perf_counter()
        if port == 465:
            server = smtplib.SMTP_SSL(host, port, timeout=30)
        else:
            server = smtplib.SMTP(host, port, timeout=30)
            if port in {25, 587}:
                server.starttls()
        try:
            server.login(user, password)
        finally:
            try:
                server.quit()
            except Exception:
                pass
        return {"ok": True, "message": f"SMTP 测试通过：已成功连接并登录，用时 {time.perf_counter() - started:.1f}s。", "sender": sender, "path": path, "source": source}
    except Exception as exc:
        return {"ok": False, "message": f"SMTP 测试失败：{type(exc).__name__}", "suggestion": _safe_error(exc), "path": path, "source": source}


def _public_settings() -> dict[str, Any]:
    settings = _read_json(SETTINGS_FILE, {})
    models = _apply_connection_library_to_defaults()
    if isinstance(models, dict):
        models = _models_with_url_defaults(_strip_private_model_fields(models))
    if isinstance(settings, dict) and not str(settings.get("auto_clip_bgm_library_dir") or "").strip():
        settings = {**settings, "auto_clip_bgm_library_dir": str(BGM_LIBRARY_DIR)}
    profiles = _profile_public_status()
    return {
        "settings": _strip_private_model_fields(settings) if isinstance(settings, dict) else {},
        "models": models if isinstance(models, dict) else {},
        "model_profiles": profiles,
        "model_connection_library": _public_model_connection_library(),
        "secrets": _secret_statuses(),
        "email_secret": _smtp_status(),
        "project_root": str(PROJECT_ROOT),
        "bgm_library": _bgm_library_summary(str(settings.get("auto_clip_bgm_library_dir") or BGM_LIBRARY_DIR) if isinstance(settings, dict) else ""),
    }


def _bgm_library_dir(value: str = "") -> Path:
    raw = str(value or "").strip().strip('"')
    return Path(raw).expanduser().resolve() if raw else BGM_LIBRARY_DIR.resolve()


def _bgm_library_summary(value: str = "") -> dict[str, Any]:
    root = _bgm_library_dir(value)
    root.mkdir(parents=True, exist_ok=True)
    items: list[dict[str, Any]] = []
    for path in sorted(root.iterdir(), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True):
        if not path.is_file() or path.suffix.lower() not in AUDIO_LIBRARY_EXTS:
            continue
        items.append(
            {
                "name": path.name,
                "path": str(path),
                "size": path.stat().st_size,
                "mtime": int(path.stat().st_mtime),
            }
        )
    return {"path": str(root), "items": items}


def _save_public_settings(payload: dict[str, Any]) -> dict[str, Any]:
    current = _read_json(SETTINGS_FILE, {})
    if not isinstance(current, dict):
        current = {}
    allowed = {
        "research_days", "research_max_articles", "research_issue_count", "research_journals", "research_out_dir", "research_skip_medical_related",
        "research_resume_dir", "research_article_list", "culture_book", "culture_out_dir",
        "culture_continue_folder", "auto_clip_image_dir", "auto_clip_lrc_dir",
        "auto_clip_output_dir", "auto_clip_bgm", "auto_clip_bgm_library_dir", "email_enabled", "email_recipient", "smtp_host",
        "smtp_port", "smtp_user", "smtp_sender", "minimax_voice_id",
        "minimax_provider", "minimax_tts_model", "minimax_bgm_model", "minimax_bgm_prompt",
    }
    for key in allowed:
        if key in payload:
            current[key] = str(payload.get(key) or "")
    _write_json(SETTINGS_FILE, current)
    for key, path in MODEL_KEY_FILES.items():
        value = str(payload.get(key) or "").strip()
        if value:
            if key == "minimax_api_key":
                provider_path = _minimax_key_paths_for_current_provider()[0]
                _write_secret(provider_path, value)
            else:
                _write_secret(path, value)
    if str(payload.get("smtp_password") or "").strip():
        _write_smtp_password(str(payload.get("smtp_password") or ""))

    models = _read_json(MODEL_DEFAULTS_FILE, {})
    if not isinstance(models, dict):
        models = {}
    models = _strip_private_model_fields(models)
    model_allowed = {
        "culture_text_provider", "culture_text_model", "culture_polish_provider",
        "culture_polish_model", "culture_image_provider", "culture_image_model",
        "text_engine", "polish_engine", "image_engine", "foreign_base_url", "deepseek_base_url",
        "gpt_base_url", "gpt_pro_base_url", "gpt_image_base_url", "minimax_base_url",
        "minimax_tts_model", "minimax_bgm_model",
        "culture_text_base_url", "culture_polish_base_url", "culture_image_base_url",
        "research_text_base_url", "research_polish_base_url", "research_image_base_url",
    }
    for key in model_allowed:
        if key in payload:
            value = str(payload.get(key) or "")
            if key == "foreign_base_url":
                value = _normalized_defaultable_base_url(value, DEFAULT_FOREIGN_BASE_URL)
            elif key == "deepseek_base_url":
                value = (value or DEFAULT_DEEPSEEK_BASE_URL).strip().rstrip("/")
            elif key == "minimax_base_url":
                value = _minimax_base_url(value)
            elif key in PER_MODEL_BASE_URL_FIELDS:
                value = _normalized_defaultable_base_url(value, str(models.get("foreign_base_url") or DEFAULT_FOREIGN_BASE_URL))
            models[key] = value
    models = _models_from_connection_library(models)
    _write_json(MODEL_DEFAULTS_FILE, models)
    _mark_shared_config_changed()
    result = _public_settings()
    result["sync_report"] = _sync_shared_model_config_to_projects(models)
    return result


def _active_profile_name() -> str:
    profiles = _profile_public_status()
    active_id = str(profiles.get("active_profile") or "")
    for item in profiles.get("profiles", []):
        if isinstance(item, dict) and str(item.get("id") or "") == active_id:
            return str(item.get("name") or active_id)
    return active_id or "未选择"


def _model_usage_summary(models: dict[str, Any] | None = None) -> dict[str, str]:
    models = _models_with_url_defaults(models or _model_settings())
    polish_provider = str(models.get("culture_polish_provider") or "").strip().lower()
    polish_model = str(models.get("culture_polish_model") or models.get("polish_engine") or "")
    polish_url = str(
        models.get("research_polish_base_url")
        or models.get("culture_polish_base_url")
        or models.get("foreign_base_url")
        or DEFAULT_FOREIGN_BASE_URL
    )
    if polish_provider == "deepseek" or "deepseek" in polish_model.lower():
        polish_url = str(models.get("deepseek_base_url") or DEFAULT_DEEPSEEK_BASE_URL)
    return {
        "profile": "连接库自动组合",
        "text_model": str(models.get("culture_text_model") or models.get("text_engine") or "未设置"),
        "image_model": str(models.get("culture_image_model") or models.get("image_engine") or "未设置"),
        "polish_model": polish_model or "未设置",
        "minimax_model": str(models.get("minimax_tts_model") or "speech-2.8-hd"),
        "text_url": str(models.get("culture_text_base_url") or models.get("foreign_base_url") or DEFAULT_FOREIGN_BASE_URL),
        "research_text_url": str(models.get("research_text_base_url") or models.get("culture_text_base_url") or models.get("foreign_base_url") or DEFAULT_FOREIGN_BASE_URL),
        "image_url": str(models.get("culture_image_base_url") or models.get("foreign_base_url") or DEFAULT_FOREIGN_BASE_URL),
        "research_image_url": str(models.get("research_image_base_url") or models.get("culture_image_base_url") or models.get("foreign_base_url") or DEFAULT_FOREIGN_BASE_URL),
        "polish_url": polish_url,
        "culture_polish_url": str(models.get("culture_polish_base_url") or polish_url),
        "research_polish_url": str(models.get("research_polish_base_url") or polish_url),
        "gpt_pro_url": str(models.get("gpt_pro_base_url") or ""),
        "deepseek_url": str(models.get("deepseek_base_url") or DEFAULT_DEEPSEEK_BASE_URL),
        "minimax_url": str(models.get("minimax_base_url") or DEFAULT_MINIMAX_BASE_URL),
    }


def _shared_model_env_lines(summary: dict[str, str]) -> list[str]:
    key_paths = {key: str(path) for key, path in MODEL_KEY_FILES.items()}
    secret_flags = _secret_statuses()
    return [
        "# Quanlan shared model config. No plaintext keys are written here.",
        f"QUANLAN_MODEL_PROFILE={summary['profile']}",
        f"QUANLAN_TEXT_MODEL={summary['text_model']}",
        f"QUANLAN_IMAGE_MODEL={summary['image_model']}",
        f"QUANLAN_POLISH_MODEL={summary['polish_model']}",
        f"QUANLAN_MINIMAX_MODEL={summary['minimax_model']}",
        f"FEISHU_CODEX_MODEL={summary['text_model']}",
        f"FEISHU_CODEX_CASUAL_MODEL={summary['text_model']}",
        f"IMAGE_MODEL={summary['image_model']}",
        f"POLISH_MODEL={summary['polish_model']}",
        f"GPT_PRO_MODEL={summary['text_model']}",
        f"MINIMAX_MODEL={summary['minimax_model']}",
        f"OPENAI_BASE_URL={summary['text_url']}",
        f"OPENAI_API_BASE={summary['text_url']}",
        f"CULTURE_TEXT_BASE_URL={summary['text_url']}",
        f"RESEARCH_TEXT_BASE_URL={summary['research_text_url']}",
        f"CULTURE_IMAGE_BASE_URL={summary['image_url']}",
        f"RESEARCH_IMAGE_BASE_URL={summary['research_image_url']}",
        f"GPT_IMAGE_BASE_URL={summary['research_image_url']}",
        f"CULTURE_POLISH_BASE_URL={summary['culture_polish_url']}",
        f"RESEARCH_POLISH_BASE_URL={summary['research_polish_url']}",
        f"DEEPSEEK_BASE_URL={summary['deepseek_url']}",
        f"GPT_PRO_BASE_URL={summary['gpt_pro_url'] or summary['research_polish_url']}",
        f"MINIMAX_BASE_URL={summary['minimax_url']}",
        f"OPENAI_API_KEY_CONFIGURED={str(bool(secret_flags.get('openai_api_key_configured'))).lower()}",
        f"IMAGE_API_KEY_CONFIGURED={str(bool(secret_flags.get('image_api_key_configured'))).lower()}",
        f"DEEPSEEK_API_KEY_CONFIGURED={str(bool(secret_flags.get('deepseek_api_key_configured'))).lower()}",
        f"MINIMAX_API_KEY_CONFIGURED={str(bool(secret_flags.get('minimax_api_key_configured'))).lower()}",
        f"OPENAI_API_KEY_FILE={key_paths.get('openai_api_key', '')}",
        f"IMAGE_API_KEY_FILE={key_paths.get('image_api_key', '')}",
        f"GPT_PRO_API_KEY_FILE={key_paths.get('gpt_pro_api_key', '')}",
        f"DEEPSEEK_API_KEY_FILE={key_paths.get('deepseek_api_key', '')}",
        f"MINIMAX_API_KEY_FILE={key_paths.get('minimax_api_key', '')}",
    ]


def _project_model_key_targets(root: Path, key_name: str) -> list[Path]:
    names = {
        "openai_api_key": ["openai_api_key.txt"],
        "image_api_key": ["image_api_key.txt", "openai_image_api_key.txt"],
        "gpt_pro_api_key": ["gpt_pro_api_key.txt"],
        "deepseek_api_key": ["deepseek_api_key.txt"],
        "minimax_api_key": ["minimax_api_key.txt"],
    }.get(key_name, [])
    targets = [root / name for name in names]
    if root == PROJECT_ROOT:
        for mode_dir in (root / "modes" / "culture", root / "modes" / "research"):
            targets.extend(mode_dir / name for name in names)
    return targets


def _sync_project_model_keys(root: Path) -> dict[str, Any]:
    copied: list[str] = []
    missing: list[str] = []
    for key_name in PROFILE_MODEL_KEY_NAMES:
        value, _ = _read_model_secret(key_name)
        if not value:
            missing.append(key_name)
            continue
        for target in _project_model_key_targets(root, key_name):
            _write_secret(target, value)
            copied.append(str(target))
    return {"key_files_synced": len(copied), "missing_keys": missing}


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            text = line.strip()
            if not text or text.startswith("#") or "=" not in text:
                continue
            key, value = text.split("=", 1)
            values[key.strip()] = value.strip()
    except Exception:
        return {}
    return values


def _verify_project_model_config(project_id: str, name: str, root: Path, summary: dict[str, str]) -> dict[str, Any]:
    env_path = root / ".env.quanlan-model.local"
    json_path = root / ".env.quanlan-model.local.json"
    mismatches: list[str] = []
    if not env_path.exists():
        mismatches.append("missing env file")
    if not json_path.exists():
        mismatches.append("missing json file")
    env_values = _parse_env_file(env_path)
    expected_env = {
        "QUANLAN_MODEL_PROFILE": summary["profile"],
        "QUANLAN_TEXT_MODEL": summary["text_model"],
        "QUANLAN_IMAGE_MODEL": summary["image_model"],
        "QUANLAN_POLISH_MODEL": summary["polish_model"],
        "QUANLAN_MINIMAX_MODEL": summary["minimax_model"],
        "OPENAI_BASE_URL": summary["text_url"],
        "CULTURE_TEXT_BASE_URL": summary["text_url"],
        "RESEARCH_TEXT_BASE_URL": summary["research_text_url"],
        "CULTURE_IMAGE_BASE_URL": summary["image_url"],
        "RESEARCH_IMAGE_BASE_URL": summary["research_image_url"],
        "DEEPSEEK_BASE_URL": summary["deepseek_url"],
        "MINIMAX_BASE_URL": summary["minimax_url"],
    }
    for key, expected in expected_env.items():
        actual = env_values.get(key, "")
        if actual != expected:
            mismatches.append(f"{key} mismatch")
    data = _read_json(json_path, {})
    if not isinstance(data, dict):
        mismatches.append("json invalid")
        data = {}
    models = data.get("models") if isinstance(data.get("models"), dict) else {}
    for key in ("profile", "text_model", "image_model", "polish_model", "minimax_model", "text_url", "image_url", "deepseek_url", "minimax_url"):
        if str(models.get(key) or "") != str(summary.get(key) or ""):
            mismatches.append(f"json {key} mismatch")
    key_report = _sync_project_model_keys(root)
    return {
        "id": project_id,
        "name": name,
        "ok": not mismatches,
        "env_path": str(env_path),
        "json_path": str(json_path),
        "checked": True,
        "mismatches": mismatches,
        **key_report,
        **summary,
    }


def _sync_shared_model_config_to_projects(models: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    models = _models_with_url_defaults(models or _apply_connection_library_to_defaults(mark_changed=False))
    summary = _model_usage_summary(models)
    snapshot = {
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "profile": summary["profile"],
        "models": summary,
        "key_status": _secret_statuses(),
        "key_files": {key: str(path) for key, path in MODEL_KEY_FILES.items()},
        "note": "No plaintext keys are stored in this file.",
    }
    projects = [
        ("assistant", "自媒体小猪理", PROJECT_ROOT),
        ("xiaozhuli", "全澜小猪理", XIAOZHULI_ROOT),
        ("eeg", "脑电分析平台", EEG_ANALYSER_ROOT),
    ]
    env_text = "\n".join(_shared_model_env_lines(summary)) + "\n"
    report: list[dict[str, Any]] = []
    for project_id, name, root in projects:
        try:
            root.mkdir(parents=True, exist_ok=True)
            env_path = root / ".env.quanlan-model.local"
            json_path = root / ".env.quanlan-model.local.json"
            env_path.write_text(env_text, encoding="utf-8")
            json_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
            key_report = _sync_project_model_keys(root)
            verify = _verify_project_model_config(project_id, name, root, summary)
            report.append({**verify, **key_report})
        except Exception as exc:
            report.append({"id": project_id, "name": name, "ok": False, "checked": False, "error": _safe_error(exc), **summary})
    return report


def _apply_model_config_to_all_projects() -> dict[str, Any]:
    models = _models_with_url_defaults(_apply_connection_library_to_defaults(mark_changed=False))
    _write_json(MODEL_DEFAULTS_FILE, _strip_private_model_fields(models))
    _mark_shared_config_changed()
    sync_report = _sync_shared_model_config_to_projects(models)
    _restart_xiaozhuli_dashboard(takeover=True)
    sync_report = _sync_shared_model_config_to_projects(models)
    test_report = _test_all_model_links()
    result = _public_settings()
    result["sync_report"] = sync_report
    result["connectivity_report"] = test_report
    result["apply_log"] = _build_model_apply_log(result, sync_report, test_report)
    result["apply_ok"] = all(bool(item.get("ok")) for item in sync_report)
    return result


def _test_all_model_links() -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for provider, label in MODEL_TEST_PROVIDERS:
        result = _test_model_detailed(provider, {})
        results.append({"provider": provider, "label": label, **result})
    return results


def _build_model_apply_log(data: dict[str, Any], sync_report: list[dict[str, Any]], test_report: list[dict[str, Any]]) -> list[str]:
    models = data.get("models") if isinstance(data.get("models"), dict) else {}
    summary = _model_usage_summary(models)
    lines = [
        f"模型方案已切换：{summary['profile']}",
        f"公共模型：文案生成用 {summary['text_model']} ｜ 图片生成用 {summary['image_model']} ｜ 润色用 {summary['polish_model']} ｜ MiniMax 用 {summary['minimax_model']}",
    ]
    for item in sync_report:
        if item.get("ok"):
            lines.append(f"{item.get('name')}已切换{summary['profile']}模型方案；文案生成用{summary['text_model']}；图片生成用{summary['image_model']}；润色用{summary['polish_model']}；本地配置已写入。")
        else:
            lines.append(f"{item.get('name')}同步失败：{item.get('error') or 'unknown'}")
    if test_report:
        lines.append("连通性测试报告：")
        for item in test_report:
            status = "通过" if item.get("ok") else "失败"
            lines.append(f"{item.get('label')}：{status} ｜ 模型：{item.get('model') or '未设置'} ｜ URL：{item.get('endpoint') or '未设置'} ｜ {item.get('message') or ''}")
    else:
        lines.append("本次只检测公共配置写入、运行注入和子项目只读防线；未自动发起模型接口请求。")
    lines.append("Key 明文未写入网页日志；子项目本地配置只保存 Key 状态和本机密钥文件引用。")
    return lines


def _entry_html() -> bytes:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>鍏ㄦ緶搴旂敤鎬绘帶鍙?/title>
  <style>
    :root{font-family:Arial,"Microsoft YaHei",sans-serif;color:#17202a;background:#f3f6f8;--brand:#0f766e;--line:#d8e0e7;--muted:#64748b;--soft:#f7faf9;--card:#fff;--shadow:0 10px 26px rgba(15,23,42,.07)}
    *{box-sizing:border-box}body{margin:0;background:linear-gradient(180deg,#f8fafc 0%,#eef4f3 100%)}.wrap{max-width:1040px;margin:0 auto;padding:30px 18px}
    .boss-home{position:fixed;right:18px;bottom:18px;z-index:50;display:inline-flex;align-items:center;justify-content:center;min-height:42px;padding:0 16px;border-radius:999px;background:#111827;color:#fff;font-weight:700;text-decoration:none;box-shadow:0 10px 28px rgba(15,23,42,.24)}
    .brief{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin:0 0 18px}
    .brief div{background:#fff;border:1px solid var(--line);border-left:3px solid #14b8a6;border-radius:8px;padding:14px;box-shadow:0 6px 18px rgba(15,23,42,.05)}.brief span{display:block;color:var(--brand);font-size:12px;font-weight:800;margin-bottom:8px}.brief strong{display:block;line-height:1.4;margin-bottom:8px}.brief p{margin:0;color:var(--muted);font-size:13px;line-height:1.55}
    h1{font-size:28px;margin:0 0 8px}.hint{color:var(--muted);font-size:14px;line-height:1.6;margin:0 0 22px}
    .section-head{align-items:flex-end;display:flex;gap:12px;justify-content:space-between;margin:20px 0 10px}.section-head h2{font-size:18px;margin:0}.section-head span{color:var(--muted);font-size:12px}.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}
    a.card{display:block;background:var(--card);border:1px solid var(--line);border-radius:8px;padding:16px;text-decoration:none;color:inherit;box-shadow:var(--shadow);min-width:0}
    a.card:hover{border-color:#14b8a6;box-shadow:0 12px 28px rgba(15,118,110,.14);transform:translateY(-1px)}
    .title{font-size:17px;font-weight:800;margin-bottom:6px}.desc{font-size:13px;color:var(--muted);line-height:1.5;margin-top:8px}.meta{color:var(--muted);font-size:12px;line-height:1.5;margin-top:8px;overflow-wrap:anywhere}.pill{display:inline-flex;align-items:center;min-height:24px;padding:0 8px;border-radius:999px;background:#eef2f6;color:#334155;font-size:12px;font-weight:800}.pill.ok{background:#ecfdf3;color:#027a48}.pill.warn{background:#fff7ed;color:#b54708}
    @media(max-width:900px){.grid,.brief{grid-template-columns:1fr}.section-head{align-items:flex-start;flex-direction:column}}
  </style>
</head>
<body>
  <a class="boss-home" href="/assistant/#model">缁熶竴閰嶇疆</a>
  <div class="wrap">
    <h1>鍏ㄦ緶搴旂敤鎬绘帶鍙?/h1>
    <p class="hint">涓€涓叆鍙ｇ鐞嗚嚜濯掍綋灏忕尓鐞嗐€佸叏婢滃皬鐚悊鍜岃剳鐢靛垎鏋愬钩鍙帮紱澶фā鍨?URL銆並ey銆丼MTP 鍜岄€氱敤鍙傛暟鍙湪杩欓噷閰嶇疆锛屽啀鍚屾鍒伴渶瑕佺殑椤圭洰銆?/p>
    <section class="brief">
      <div><span>缁熶竴閰嶇疆</span><strong>妯″瀷銆並ey銆丼MTP 闆嗕腑绠＄悊銆?/strong><p>瀛愰」鐩彧淇濈暀涓氬姟娴佺▼锛屼笉鍐嶉噸澶嶅睍绀洪€氱敤閰嶇疆銆?/p></div>
      <div><span>搴旂敤鎬绘帶</span><strong>鍚姩銆佹墦寮€銆佸悓姝ュ涓」鐩€?/strong><p>鎵€鏈夊簲鐢ㄥ叆鍙ｆ斁鍦ㄥ悓涓€涓帶鍒跺彴锛屼笉闇€瑕佽绔彛銆?/p></div>
      <div><span>鐘舵€佸彲淇?/span><strong>鍙樉绀烘憳瑕侊紝涓嶆硠闇插瘑閽ャ€?/strong><p>鐘舵€佹帴鍙ｇ敤浜庤瘖鏂紝椤甸潰渚ч粯璁や繚鎶ゆ晱鎰熶俊鎭€?/p></div>
    </section>
    <div class="section-head"><h2>搴旂敤鎬绘帶</h2><span id="home_app_summary">姝ｅ湪璇诲彇搴旂敤鐘舵€?/span></div>
    <section class="grid" id="home_app_grid">
      <a class="card" href="/assistant/"><div class="title">鑷獟浣撳皬鐚悊</div><div class="desc">鍐呭鐢熶骇銆佹ā鍨嬩笌 Key銆侀偖浠躲€佸彂甯冨拰鑷紭鍖栫殑鎬绘帶宸ヤ綔鍙般€?/div></a>
      <a class="card" href="/xiaozhuli/"><div class="title">鍏ㄦ緶灏忕尓鐞?/div><div class="desc">閿€鍞煡璇嗗簱銆佸鎴峰缓璁€丷ole-play 璁板綍鍜屾湇鍔＄姸鎬併€?/div></a>
      <a class="card" href="/eeg/"><div class="title">鑴戠數鍒嗘瀽骞冲彴</div><div class="desc">NeuroCloud EEG 鍒嗘瀽娴佺▼鍏ュ彛锛涘唴閮ㄤ笉灞曠ず閫氱敤妯″瀷閰嶇疆銆?/div></a>
    </section>
    <div class="section-head"><h2>閫氱敤閰嶇疆涓庤瘖鏂?/h2><span>閰嶇疆鍙湪鎬绘帶鍙扮淮鎶?/span></div>
    <div class="grid">
      <a class="card" href="/assistant/#model"><div class="title">缁熶竴妯″瀷閰嶇疆</div><div class="desc">閰嶇疆榛樿鍥藉鏂规銆丏ST 鏂规锛屼互鍙婃瘡涓ā鍨嬬殑 URL/Key 涓嬫媺棰勮锛涙墍鏈夊瓙椤圭洰鍏辩敤杩欓噷鐨勫綋鍓嶆柟妗堛€?/div></a>
      <a class="card" href="/assistant/#more"><div class="title">搴旂敤鎬绘帶涓庡伐鍏?/div><div class="desc">鐩磋揪搴旂敤鐘舵€併€侀偖浠躲€佽嚜浼樺寲銆佸彂甯冨拰璇婃柇宸ュ叿銆?/div></a>
    </div>
  </div>
  <script>

let currentJob="";
const defaultForeignBaseUrl="https://api.dstopology.com/v1";
const defaultDeepseekBaseUrl="https://api.deepseek.com";
const modelUrlIds=["foreign_base_url","culture_text_base_url","culture_polish_base_url","culture_image_base_url","research_text_base_url","research_polish_base_url","research_image_base_url"];
const keyNameMap={openai_api_key:"openai",image_api_key:"image",gemini_api_key:"gemini",deepseek_api_key:"deepseek",minimax_api_key:"minimax",smtp_password:"smtp"};
const visibleSecrets={};
let modelProfiles={active_profile:"",profiles:[]};
function byId(id){return document.getElementById(id)}
function cap(s){return s[0].toUpperCase()+s.slice(1)}
function showPanel(name){for(const n of ["culture","research","clip","model","more"]){const p=byId("panel"+cap(n)),t=byId("tab"+cap(n));if(p)p.classList.toggle("active",n===name);if(t)t.classList.toggle("active",n===name)}}
function keyText(ok){return ok?'<span class="ok">已配置</span>':'<span class="missing">未配置</span>'}
function applyKeyStatus(sec){sec=sec||{};const map={openai_key_status:"openai_api_key_configured",image_key_status:"image_api_key_configured",gemini_key_status:"gemini_api_key_configured",deepseek_key_status:"deepseek_api_key_configured",minimax_key_status:"minimax_api_key_configured"};for(const [id,k] of Object.entries(map)){if(byId(id))byId(id).innerHTML=keyText(!!sec[k])}for(const [key,prefix] of Object.entries(keyNameMap)){if(key==="smtp_password")continue;const path=sec[key+"_path"]||"";const source=sec[key+"_source"]||"";if(byId(prefix+"_key_path"))byId(prefix+"_key_path").textContent=path?("保存位置："+path+" ｜ 来源："+source):"保存位置：未找到"}}
function applyEmailStatus(email){email=email||{};if(byId("smtp_key_status"))byId("smtp_key_status").innerHTML=keyText(!!email.smtp_password_configured);if(byId("smtp_key_path"))byId("smtp_key_path").textContent=email.smtp_password_path?("保存位置："+email.smtp_password_path+" ｜ 来源："+(email.smtp_password_source||"")):"保存位置：未找到"}
function renderModelProfileStatus(profile){const el=byId("model_profile_status");if(!el)return;const keys=profile&&profile.keys?profile.keys:{};const names={openai_api_key:"OpenAI",image_api_key:"Image",gemini_api_key:"Gemini",deepseek_api_key:"DeepSeek",minimax_api_key:"MiniMax"};const text=Object.entries(names).map(([k,n])=>n+":"+(keys[k]?"已存":"未存")).join(" ｜ ");el.textContent="方案状态："+((profile&&profile.id)||"未选择")+" ｜ "+text}
function fieldValue(id){const el=byId(id);return el?String(el.value||""):""}
function profileKeyText(profile,key){return profile&&profile.keys&&profile.keys[key]?"已存":"未存"}
function renderRouteSummary(profile){
  const box=byId("model_route_summary");
  if(!box)return;
  if(byId("route_profile_name"))byId("route_profile_name").textContent=profileLabel(profile||{})||"未选择方案";
  const rows=[
    ["文史文本",fieldValue("culture_text_provider"),fieldValue("culture_text_model"),fieldValue("culture_text_base_url"),"OpenAI "+profileKeyText(profile,"openai_api_key")+" / Gemini "+profileKeyText(profile,"gemini_api_key")],
    ["文史润色",fieldValue("culture_polish_provider"),fieldValue("culture_polish_model"),fieldValue("culture_polish_base_url"),"DeepSeek "+profileKeyText(profile,"deepseek_api_key")],
    ["文史生图",fieldValue("culture_image_provider"),fieldValue("culture_image_model"),fieldValue("culture_image_base_url"),"Image "+profileKeyText(profile,"image_api_key")],
    ["科研文本","engine",fieldValue("text_engine"),fieldValue("research_text_base_url"),"OpenAI "+profileKeyText(profile,"openai_api_key")+" / Gemini "+profileKeyText(profile,"gemini_api_key")],
    ["科研润色","engine",fieldValue("polish_engine"),fieldValue("research_polish_base_url"),"DeepSeek "+profileKeyText(profile,"deepseek_api_key")],
    ["科研图片","engine",fieldValue("image_engine"),fieldValue("research_image_base_url"),"Image "+profileKeyText(profile,"image_api_key")]
  ];
  box.innerHTML=rows.map(([role,provider,model,url,key])=>'<div class="route-item"><b>'+escapeHtml(role)+'</b><span>'+escapeHtml(provider||"未设置")+' ｜ '+escapeHtml(model||"未设置")+'</span><span>'+escapeHtml(url||"未设置")+'</span><span>'+escapeHtml(key)+'</span></div>').join("");
}
function renderModelProfiles(profiles){
  modelProfiles=profiles||{active_profile:"",profiles:[]};
  const sel=byId("model_profile_select");
  if(sel){
    sel.innerHTML="";
    for(const item of modelProfiles.profiles||[]){
      const opt=document.createElement("option");
      opt.value=item.id;
      opt.textContent=(item.name||item.id)+(item.locked?" ｜ 默认":"");
      sel.appendChild(opt);
    }
    if(modelProfiles.active_profile)sel.value=modelProfiles.active_profile;
    const active=(modelProfiles.profiles||[]).find(p=>p.id===sel.value)||{};
    if(byId("model_profile_name"))byId("model_profile_name").value=active.name||"";
    renderModelProfileStatus(active);
    renderRouteSummary(active);
    sel.onchange=()=>{const p=(modelProfiles.profiles||[]).find(x=>x.id===sel.value)||{};if(byId("model_profile_name"))byId("model_profile_name").value=p.name||"";renderModelProfileStatus(p);renderRouteSummary(p)};
  }
  renderUrlPresetSelectors();
  renderKeyPresetSelectors();
}
function profileLabel(profile){return (profile&&profile.name)||((profile&&profile.id)||"方案")}
function renderUrlPresetSelectors(){
  for(const field of modelUrlIds){
    const input=byId(field);
    if(!input)continue;
    const host=input.parentElement;
    if(!host)continue;
    let sel=byId(field+"_preset");
    if(!sel){
      sel=document.createElement("select");
      sel.id=field+"_preset";
      sel.className="model-preset-select";
      host.appendChild(sel);
    }
    const options=[];
    const seen=new Set();
    for(const profile of modelProfiles.profiles||[]){
      const url=profile&&profile.models?profile.models[field]:"";
      if(!url||seen.has(url))continue;
      seen.add(url);
      options.push({url,label:profileLabel(profile)+" ｜ "+url});
    }
    sel.innerHTML='<option value="">选择已保存 URL</option>'+options.map(o=>'<option value="'+escapeAttr(o.url)+'">'+escapeHtml(o.label)+'</option>').join("");
    sel.onchange=()=>{if(sel.value)input.value=sel.value};
  }
}
function renderKeyPresetSelectors(){
  for(const [key,prefix] of Object.entries(keyNameMap)){
    if(key==="smtp_password")continue;
    const card=document.querySelector('.key-card[data-key="'+key+'"]');
    if(!card)continue;
    let box=byId(prefix+"_key_profile_box");
    if(!box){
      box=document.createElement("div");
      box.id=prefix+"_key_profile_box";
      box.className="key-actions";
      const select=document.createElement("select");
      select.id=prefix+"_key_profile_select";
      const button=document.createElement("button");
      button.className="secondary";
      button.type="button";
      button.textContent="应用此 Key";
      button.onclick=()=>applyProfileKey(key);
      box.appendChild(select);
      box.appendChild(button);
      card.appendChild(box);
    }
    const sel=byId(prefix+"_key_profile_select");
    const opts=(modelProfiles.profiles||[]).filter(p=>p.keys&&p.keys[key]);
    sel.innerHTML='<option value="">选择已保存 Key</option>'+opts.map(p=>'<option value="'+escapeAttr(p.id)+'">'+escapeHtml(profileLabel(p))+'</option>').join("");
  }
}
function escapeHtml(value){return String(value||"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]))}
function escapeAttr(value){return escapeHtml(value)}
function selectedProfileId(){const sel=byId("model_profile_select");return sel?sel.value:""}
async function loadSettings(){const r=await fetch("/api/settings");const data=await r.json();const s=data.settings||{},m=data.models||{};for(const [k,v] of Object.entries({...s,...m})){if(byId(k))byId(k).value=v||""}renderModelProfiles(data.model_profiles||{});applyKeyStatus(data.secrets||{});applyEmailStatus(data.email_secret||{})}
function restoreDefaultUrls(){for(const id of modelUrlIds){if(byId(id))byId(id).value=defaultForeignBaseUrl}if(byId("deepseek_base_url"))byId("deepseek_base_url").value=defaultDeepseekBaseUrl;const p=(modelProfiles.profiles||[]).find(x=>x.id===selectedProfileId())||{};renderRouteSummary(p);if(byId("status"))status.textContent="模型地址已恢复默认，点击保存后生效"}
function collect(){const ids=["culture_book","culture_out_dir","culture_continue_folder","culture_text_provider","culture_text_model","culture_polish_provider","culture_polish_model","culture_image_provider","culture_image_model","research_out_dir","research_days","research_max_articles","research_journals","research_article_list","text_engine","polish_engine","image_engine","foreign_base_url","deepseek_base_url","culture_text_base_url","culture_polish_base_url","culture_image_base_url","research_text_base_url","research_polish_base_url","research_image_base_url","openai_api_key","image_api_key","gemini_api_key","deepseek_api_key","minimax_api_key","smtp_password","auto_clip_image_dir","auto_clip_lrc_dir","auto_clip_output_dir","auto_clip_bgm","minimax_voice_id","minimax_tts_model","minimax_bgm_model","minimax_bgm_prompt","email_recipient","smtp_host","smtp_port","smtp_user","smtp_sender"];const p={};for(const id of ids){if(byId(id))p[id]=byId(id).value}return p}
function clearSecretInputs(){for(const id of ["openai_api_key","image_api_key","gemini_api_key","deepseek_api_key","minimax_api_key","smtp_password"]){if(byId(id))byId(id).value=""}}
function hideSecret(key){const prefix=keyNameMap[key];visibleSecrets[key]=false;if(prefix&&byId(prefix+"_key_value"))byId(prefix+"_key_value").textContent="已隐藏"}
async function toggleSecret(key){const prefix=keyNameMap[key];if(!prefix)return;if(visibleSecrets[key]){hideSecret(key);return}const box=byId(prefix+"_key_value");if(box)box.textContent="读取中...";const r=await fetch("/api/secret?key="+encodeURIComponent(key));const data=await r.json();if(key==="smtp_password"){const email=data.email_secret||{};if(box)box.textContent=email.smtp_password||"未配置";applyEmailStatus(email)}else{const sec=data.secrets||{};if(box)box.textContent=sec[key]||"未配置";applyKeyStatus(sec)}visibleSecrets[key]=true}
function renderTest(id,result){const el=byId(id);if(!el)return;const ok=result&&result.ok;el.innerHTML=(ok?'<span class="ok">测试通过</span>':'<span class="missing">测试失败</span>')+" ｜ "+((result&&result.message)||"无结果")+((result&&result.suggestion)?(" ｜ 建议："+result.suggestion):"")}
async function testModel(provider){const id=provider+"_test_result";if(byId(id))byId(id).textContent="测试中...";const payload={...collect(),provider};const r=await fetch("/api/test_model",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});const data=await r.json();clearSecretInputs();for(const key of Object.keys(keyNameMap))hideSecret(key);renderTest(id,data.result||{});applyKeyStatus(data.secrets||{});applyEmailStatus(data.email_secret||{})}
async function testEmail(){if(byId("smtp_test_result"))byId("smtp_test_result").textContent="测试中...";const r=await fetch("/api/test_email",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(collect())});const data=await r.json();clearSecretInputs();hideSecret("smtp_password");renderTest("smtp_test_result",data.result||{});applyEmailStatus(data.email_secret||{})}
async function saveSettings(){const r=await fetch("/api/settings",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(collect())});const data=await r.json();status.textContent=data.ok?"设置已保存":"保存失败";clearSecretInputs();for(const key of Object.keys(keyNameMap))hideSecret(key);renderModelProfiles(data.model_profiles||{});applyKeyStatus(data.secrets||{});applyEmailStatus(data.email_secret||{});return data}
async function applyModelProfile(){const id=selectedProfileId();if(!id){status.textContent="请先选择模型方案";return}status.textContent="正在应用模型方案...";const r=await fetch("/api/model_profile",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({action:"apply",profile_id:id})});const data=await r.json();if(!data.ok){status.textContent="应用方案失败："+(data.error||"unknown");return}clearSecretInputs();for(const key of Object.keys(keyNameMap))hideSecret(key);const s=data.settings||{},m=data.models||{};for(const [k,v] of Object.entries({...s,...m})){if(byId(k))byId(k).value=v||""}renderModelProfiles(data.model_profiles||{});applyKeyStatus(data.secrets||{});applyEmailStatus(data.email_secret||{});status.textContent="模型方案已应用"}
async function applyProfileKey(key){const prefix=keyNameMap[key];const sel=prefix?byId(prefix+"_key_profile_select"):null;const profileId=sel?sel.value:"";if(!profileId){status.textContent="请先选择一个已保存 Key";return}status.textContent="正在应用 Key...";const r=await fetch("/api/model_profile",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({action:"apply_key",profile_id:profileId,key_name:key})});const data=await r.json();if(!data.ok){status.textContent="应用 Key 失败："+(data.error||"unknown");return}clearSecretInputs();hideSecret(key);renderModelProfiles(data.model_profiles||{});applyKeyStatus(data.secrets||{});applyEmailStatus(data.email_secret||{});status.textContent="Key 已应用；各子项目启动时会使用总控台当前配置"}
async function saveModelProfile(){const name=(byId("model_profile_name")&&byId("model_profile_name").value)||"";const id=selectedProfileId();status.textContent="正在保存模型方案...";const r=await fetch("/api/model_profile",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({...collect(),action:"save",profile_id:id,profile_name:name})});const data=await r.json();if(!data.ok){status.textContent="保存方案失败："+(data.error||"unknown");return}clearSecretInputs();for(const key of Object.keys(keyNameMap))hideSecret(key);renderModelProfiles(data.model_profiles||{});applyKeyStatus(data.secrets||{});applyEmailStatus(data.email_secret||{});status.textContent="模型方案已保存"}
async function deleteModelProfile(){const id=selectedProfileId();if(!id){status.textContent="请先选择模型方案";return}if(id==="foreign-default"){status.textContent="默认方案不能删除";return}const r=await fetch("/api/model_profile",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({action:"delete",profile_id:id})});const data=await r.json();if(!data.ok){status.textContent="删除方案失败："+(data.error||"unknown");return}renderModelProfiles(data.model_profiles||{});status.textContent="模型方案已删除"}
async function start(payload){await saveSettings();const r=await fetch("/api/start",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});const data=await r.json();currentJob=data.job_id||"";status.textContent=data.message||"已启动";cmd.textContent=(data.cmd||[]).join(" ");poll()}
function startCulture(test){start({...collect(),mode:"culture",stage:byId("culture_stage").value,test_b_image_limit:test?1:Number(byId("culture_test_b").value||0)})}
function startResearch(action){start({...collect(),mode:"research",action})}
function startClip(){start({...collect(),mode:"auto_clip"})}
function startBgm(){start({...collect(),mode:"bgm"})}
function startTool(action){start({...collect(),mode:"tool",action})}
function openXiaozhuli(){window.open("/xiaozhuli/","_blank")}
async function stopJob(){if(!currentJob)return;await fetch("/api/stop?id="+encodeURIComponent(currentJob),{method:"POST"});poll()}
async function poll(){if(!currentJob)return;const r=await fetch("/api/job?id="+encodeURIComponent(currentJob));const data=await r.json();status.textContent=data.status+" / exit="+(data.exit_code??"");log.textContent=(data.lines||[]).join("");log.scrollTop=log.scrollHeight;if(["running","starting","stopping"].includes(data.status))setTimeout(poll,1000)}
for(const id of ["culture_text_provider","culture_text_model","culture_polish_provider","culture_polish_model","culture_image_provider","culture_image_model","text_engine","polish_engine","image_engine",...modelUrlIds]){const el=byId(id);if(el)el.addEventListener("input",()=>{const p=(modelProfiles.profiles||[]).find(x=>x.id===selectedProfileId())||{};renderRouteSummary(p)})}
loadSettings();
if(location.hash==="#more"){showPanel("more")}else if(location.hash==="#culture"){showPanel("culture")}else if(location.hash==="#research"){showPanel("research")}else if(location.hash==="#clip"){showPanel("clip")}else{showPanel("model")}

</script>
</body>
</html>""".encode("utf-8")


def _assistant_html() -> bytes:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>寰堟湁鑴戝瓙鐨勫皬鐚悊 Web</title>
  <style>
    :root{font-family:Arial,"Microsoft YaHei",sans-serif;color:#202124;background:#f4f6f8}
    body{margin:0}.shell{display:grid;grid-template-columns:390px 1fr;min-height:100vh}
    .boss-home{position:fixed;right:18px;bottom:18px;z-index:50;display:inline-flex;align-items:center;justify-content:center;min-height:42px;padding:0 16px;border-radius:999px;background:#111827;color:#fff;font-weight:700;text-decoration:none;box-shadow:0 10px 28px rgba(15,23,42,.24)}
    .brief{display:grid;grid-template-columns:1fr;gap:8px;margin:12px 0}.brief div{background:#f7f9fc;border:1px solid #d7dce2;border-radius:8px;padding:10px}.brief span{display:block;color:#1769aa;font-size:12px;font-weight:800;margin-bottom:5px}.brief strong{display:block;font-size:13px;line-height:1.4;margin-bottom:4px}.brief p{margin:0;color:#607080;font-size:12px;line-height:1.45}
    aside{background:#fff;border-right:1px solid #d7dce2;padding:16px;overflow:auto}
    main{padding:16px;min-width:0}h1{font-size:20px;margin:0 0 6px}h2{font-size:15px;margin:14px 0 8px}
    label{display:block;font-size:12px;margin:8px 0 4px;color:#4f5b67}
    input,select{box-sizing:border-box;width:100%;padding:8px;border:1px solid #c8d0d8;border-radius:6px;background:#fff}
    button{padding:8px 10px;border:0;border-radius:6px;background:#1769aa;color:white;cursor:pointer}
    button.secondary{background:#5f6368}button.danger{background:#b3261e}.row{display:flex;gap:8px;margin-top:12px;flex-wrap:wrap}
    .tabs{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin:14px 0}.tabs button{background:#e8eef5;color:#263238}.tabs button.active{background:#1769aa;color:#fff}
    .panel{display:none}.panel.active{display:block}.grid2{display:grid;grid-template-columns:1fr 1fr;gap:8px}
    pre{white-space:pre-wrap;background:#111;color:#eee;border-radius:8px;padding:14px;min-height:72vh;overflow:auto}
    .hint,.desc{font-size:12px;color:#607080;line-height:1.5}.desc{margin:4px 0 10px}.status{font-size:13px;color:#1769aa;margin:8px 0;word-break:break-all}
    .cmd{font-size:12px;color:#607080;margin-top:8px;word-break:break-all}
    @media(max-width:900px){.shell{grid-template-columns:1fr}aside{border-right:0;border-bottom:1px solid #d7dce2}.grid2{grid-template-columns:1fr}}
  </style>
</head>
<body>
<a class="boss-home" href="http://127.0.0.1:8765/">杩斿洖鎺у埗鍙伴椤?/a>
<div class="shell">
  <aside>
    <h1>寰堟湁鑴戝瓙鐨勫皬鐚悊 Web</h1>
    <p class="hint">缁熶竴鏈湴缃戦〉鏈嶅姟锛氭枃鍙插皬绉樸€佺鐮斿姪鎵嬨€佺瀛︾粡鍏搞€佽嚜鍔ㄥ壀杈戙€佽浼楁祴璇曘€佽嚜浼樺寲銆佸彂甯冨伐鍏烽兘浠庤繖閲屽惎鍔ㄣ€?/p>
    <section class="brief">
      <div><span>褰撳墠鐘舵€?/span><strong>宸︿晶鏄换鍔￠厤缃紝鍙充晶鏄繍琛屾棩蹇椼€?/strong><p>姣忔鍚姩浠诲姟鍚庯紝鏃ュ織浼氬憡璇変綘鐜板湪璺戝埌鍝竴姝ャ€?/p></div>
      <div><span>涓氬姟浠峰€?/span><strong>瀹冩妸鍐呭鐢熶骇鍙樻垚鍙拷韪殑娴佹按绾裤€?/strong><p>浣犲彲浠ュ垽鏂槸绱犳潗缂哄け銆佹ā鍨嬮棶棰橈紝杩樻槸浠诲姟宸茬粡瀹屾垚銆?/p></div>
      <div><span>鐜板湪鍙互鍋?/span><strong>鍏堥€夊唴瀹圭被鍨嬶紝鍐嶅～绱犳潗璺緞锛屾渶鍚庡惎鍔ㄤ换鍔°€?/strong><p>浠诲姟杩愯涓笉瑕侀噸澶嶇偣鍑诲惎鍔紱濡傞渶鍋滄锛岀敤鈥滃仠姝㈠綋鍓嶄换鍔♀€濄€?/p></div>
    </section>
    <div class="tabs">
      <button id="tabCulture" onclick="showPanel('culture')">鏂囧彶</button>
      <button id="tabResearch" onclick="showPanel('research')">绉戠爺</button>
      <button id="tabClip" onclick="showPanel('clip')">鍓緫</button>
      <button id="tabModel" onclick="showPanel('model')">妯″瀷鏂规绠＄悊</button>
      <button id="tabMore" onclick="showPanel('more')">鏇村</button>
    </div>

    <section id="panelCulture" class="panel active">
      <h2>鏂囧彶灏忕</h2>
      <label>涔︾睄 PDF</label><input id="culture_book" placeholder="D:/鐭ヨ瘑/璐┓鐨勬湰璐?pdf">
      <label>杈撳嚭鐩綍</label><input id="culture_out_dir" placeholder="D:/鐭ヨ瘑/璐┓鐨勬湰璐?鐭棰戠礌鏉?>
      <label>缁х画鐩綍</label><input id="culture_continue_folder" placeholder="鍙暀绌?>
      <label>寮€濮嬮樁娈?/label>
      <select id="culture_stage"><option>outline</option><option>split_pdf</option><option>episode_prompt</option><option>script</option><option>polish</option><option>images</option><option>postprocess</option><option>split_assets</option></select>
      <div class="grid2">
        <div><label>鏂囨湰 provider</label><select id="culture_text_provider"><option>openai</option><option>gemini</option><option>deepseek</option><option>doubao</option><option>dry-run</option></select></div>
        <div><label>鏂囨湰妯″瀷</label><input id="culture_text_model" placeholder="gpt-5.5"></div>
        <div><label>娑﹁壊 provider</label><select id="culture_polish_provider"><option>deepseek</option><option>openai</option><option>gemini</option><option>doubao</option><option>dry-run</option></select></div>
        <div><label>娑﹁壊妯″瀷</label><input id="culture_polish_model" placeholder="gpt-5.5"></div>
        <div><label>鐢熷浘 provider</label><select id="culture_image_provider"><option>openai</option><option>gemini</option><option>dry-run</option><option>none</option></select></div>
        <div><label>鐢熷浘妯″瀷</label><input id="culture_image_model" placeholder="gpt-image-2"></div>
      </div>
      <label>娴嬭瘯 B 鍥炬暟</label><input id="culture_test_b" value="0">
      <div class="row"><button onclick="startCulture(false)">寮€濮嬫枃鍙茬敓鎴?/button><button onclick="startCulture(true)">娴嬭瘯 B 鍥?/button></div>
      <p class="desc"><b>寮€濮嬫枃鍙茬敓鎴愶細</b>鎸夊綋鍓?PDF銆佽緭鍑虹洰褰曞拰妯″瀷鍙傛暟璺戝畬鏁存枃鍙茬礌鏉愰摼璺€?br><b>娴嬭瘯 B 鍥撅細</b>鍙鐞嗗皯閲?B 鍥撅紝鐢ㄦ潵蹇€熸鏌ヨ剼鏈€佹彁绀鸿瘝銆佺敓鍥惧拰鍚庡鐞嗐€?/p>
    </section>

    <section id="panelResearch" class="panel">
      <h2>绉戠爺鍔╂墜 / 绉戝缁忓吀</h2>
      <label>杈撳嚭鐩綍</label><input id="research_out_dir" placeholder="鐣欑┖鍒欎娇鐢ㄩ粯璁よ緭鍑虹洰褰?>
      <div class="grid2"><div><label>妫€绱㈠ぉ鏁?/label><input id="research_days" value="14"></div><div><label>鏂囩珷鏁?/label><input id="research_max_articles" value="5"></div></div>
      <label>鏈熷垔鍒楄〃</label><input id="research_journals" placeholder="Nature, Science, Neuron...">
      <label>宸叉湁鏂囩尞娓呭崟 / 缁仛鐩綍</label><input id="research_article_list" placeholder="鍙暀绌?>
      <div class="grid2"><div><label>文本模型</label><input id="text_engine" placeholder="gpt-5.5"></div><div><label>润色模型</label><input id="polish_engine" placeholder="DeepSeek Chat（官方润色）"></div></div>
      <label>鍥剧墖妯″瀷</label><input id="image_engine" placeholder="鐢熷浘涓撶敤锝淕PT Image 2">
      <div class="row"><button onclick="startResearch('digest')">姣忔棩鐮旂┒閫熼€?/button><button onclick="startResearch('article_list')">琛ユ枃鐚竻鍗?/button><button onclick="startResearch('continue_list')">娓呭崟缁仛</button><button onclick="startResearch('resume')">缁仛妗ｆ湡</button></div>
      <p class="desc"><b>姣忔棩鐮旂┒閫熼€掞細</b>妫€绱㈡湡鍒婃枃鐚苟鐢熸垚鐮旂┒閫熼€掔礌鏉愩€?br><b>琛ユ枃鐚竻鍗曪細</b>鍙敓鎴愭垨琛ラ綈鍊欓€夋枃鐚?JSON锛屼笉鐢熸垚绱犳潗銆?br><b>娓呭崟缁仛锛?/b>浠庡凡鏈夋枃鐚竻鍗曠户缁埗浣滃悗缁礌鏉愩€?br><b>缁仛妗ｆ湡锛?/b>浠庡凡鏈夋。鏈熺洰褰曠户缁ˉ榻愭湭瀹屾垚姝ラ銆?/p>
      <div class="row"><button onclick="startTool('science')">绉戝缁忓吀瑙ｈ</button><button onclick="startTool('science_test_b')">绉戝缁忓吀娴嬭瘯 B 鍥?/button></div>
      <p class="desc"><b>绉戝缁忓吀瑙ｈ锛?/b>鍚姩绉戠爺鍔╂墜閲岀殑缁忓吀璁烘枃/绉戝鍐呭瑙ｈ娴佺▼銆?br><b>绉戝缁忓吀娴嬭瘯 B 鍥撅細</b>鐢ㄦ渶灏?B 鍥鹃搴﹀揩閫熸鏌ョ瀛︾粡鍏哥殑鍥炬枃閾捐矾銆?/p>
    </section>

    <section id="panelClip" class="panel">
      <h2>鑷姩鍓緫 / BGM</h2>
      <label>鍥剧墖鐩綍</label><input id="auto_clip_image_dir" placeholder="鍒嗛泦鍥剧墖鐩綍">
      <label>LRC / 闊抽鐩綍</label><input id="auto_clip_lrc_dir" placeholder="瀛楀箷鎴栭煶棰戠洰褰?>
      <label>杈撳嚭鐩綍</label><input id="auto_clip_output_dir" placeholder="鍙暀绌?>
      <label>BGM 鏂囦欢/鐩綍</label><input id="auto_clip_bgm" placeholder="鍙暀绌?>
      <h2>MiniMax Voice / BGM</h2>
      <label>MiniMax API Key</label><input id="minimax_api_key" type="password" placeholder="saved locally; never shown in logs">
      <div class="status" id="minimax_key_status">MiniMax key: checking...</div>
      <div class="grid2">
        <div><label>Voice ID</label><input id="minimax_voice_id" placeholder="male-qn-qingse"></div>
        <div><label>TTS Model</label><input id="minimax_tts_model" placeholder="speech-2.8-hd"></div>
        <div><label>BGM Model</label><input id="minimax_bgm_model" placeholder="music-2.6"></div>
        <div><label>BGM Prompt</label><input id="minimax_bgm_prompt" placeholder="instrumental, documentary, soft piano"></div>
      </div>
      <div class="row"><button onclick="startClip()">鍚姩鑷姩鍓緫</button><button onclick="startBgm()">鐢熸垚 BGM</button></div>
      <p class="desc"><b>鍚姩鑷姩鍓緫锛?/b>鎸?LRC 鐢婚潰缂栧彿鍖归厤鍥剧墖锛岃皟鐢?FFmpeg 鍚堟垚瑙嗛銆?br><b>鐢熸垚 BGM锛?/b>鏍规嵁涔︾睄/绱犳潗鎽樿鐢熸垚涓€鏉¤儗鏅煶涔愮礌鏉愩€?/p>
    </section>

    <section id="panelModel" class="panel">
      <div class="panel-head"><div><h2>妯″瀷鏂规绠＄悊</h2><p class="desc">杩欓噷绠＄悊鏂规鐨勫垱寤恒€佸鍒躲€佷慨鏀广€佸垹闄ゅ拰搴旂敤銆傛瘡涓柟妗堝垎鍒繚瀛?GPT銆丟PT-Pro銆丟PT-image2銆丮iniMax 鐨?URL銆佹ā鍨嬪悕鍜?Key銆?/p></div><span class="panel-tag">鏂规绠＄悊</span></div>
      <div class="section soft">
        <div class="section-title"><h3>鏂规鎺у埗</h3><span id="model_profile_status">鏂规鐘舵€侊細璇诲彇涓?/span></div>
        <div class="grid2">
          <div><label>閫夋嫨鏂规</label><select id="model_profile_select"></select></div>
          <div><label>方案名称</label><input id="model_profile_name" placeholder="例如：GreatWall Link 系列 / DST 系列 / FHL 系列"></div>
        </div>
        <div class="row"><button class="secondary" onclick="newModelProfile()">鏂板缓鏂规</button><button class="secondary" onclick="applyModelProfile()">搴旂敤鎵€閫夋柟妗?/button><button onclick="saveModelProfile()">淇濆瓨/瑕嗙洊</button><button class="danger" onclick="deleteModelProfile()">鍒犻櫎鏂规</button></div>
      </div>
      <div class="section">
        <div class="section-title"><h3>鏂规鎽樿</h3><span id="route_profile_name">璇诲彇涓?/span></div>
        <div class="route-summary" id="model_route_summary"></div>
      </div>
      <div class="section">
        <div class="section-title"><h3>妯″瀷閰嶇疆</h3><span>姣忎釜妯″瀷鍒嗗埆閰嶇疆 URL銆佹ā鍨嬪悕銆並ey</span></div>
        <div class="grid2">
          <div class="scheme-card"><b>GPT / 鏂囧彶鏂囨湰</b><label>URL</label><input id="gpt_base_url" placeholder="https://api.dstopology.com/v1"><label>妯″瀷鍚?/label><input id="culture_text_model" placeholder="gpt-5.5"><label>Key</label><input id="openai_api_key" type="password" autocomplete="off" placeholder="GPT Key"></div>
          <div class="scheme-card"><b>GPT / 鏂囧彶娑﹁壊</b><label>URL</label><input id="deepseek_base_url" placeholder="https://api.dstopology.com/v1"><label>妯″瀷鍚?/label><input id="culture_polish_model" placeholder="gpt-5.5"><label>Key</label><input id="gpt_pro_api_key" type="password" autocomplete="off" placeholder="GPT Key"></div>
          <div class="scheme-card"><b>GPT-image2 / 鏂囧彶鐢熷浘</b><label>URL</label><input id="gpt_image_base_url" placeholder="https://api.dstopology.com/v1"><label>妯″瀷鍚?/label><input id="culture_image_model" placeholder="gpt-image-2"><label>Key</label><input id="image_api_key" type="password" autocomplete="off" placeholder="GPT-image2 Key"></div>
          <div class="scheme-card"><b>MiniMax / 閰嶉煶涓?BGM</b><label>URL</label><input id="minimax_base_url" placeholder="https://api.53hk.cn"><label>妯″瀷鍚?/label><input id="minimax_tts_model" placeholder="speech-2.8-hd"><label>Key</label><input id="minimax_api_key" type="password" autocomplete="off" placeholder="MiniMax Key"></div>
        </div>
      </div>
      <div class="section soft">
        <div class="section-title"><h3>浠诲姟寮曟搸鍒悕</h3><span>鐢ㄤ簬鏂囧彶/绉戠爺浠诲姟锛屼笉鍗曠嫭閲嶅璺敱閰嶇疆</span></div>
        <div class="grid3">
          <div><label>鏂囨湰寮曟搸</label><input id="text_engine" placeholder="gpt-5.5"></div>
          <div><label>娑﹁壊寮曟搸</label><input id="polish_engine" placeholder="gpt-5.5"></div>
          <div><label>鍥剧墖寮曟搸</label><input id="image_engine" placeholder="GPT-image2"></div>
        </div>
      </div>
    </section>

    <section id="panelMore" class="panel">
      <h2>鏇村宸ュ叿</h2>
      <label>鏀朵欢閭</label><input id="email_recipient" placeholder="澶氫釜閭鐢ㄩ€楀彿鍒嗛殧">
      <div class="grid2"><div><label>SMTP 鏈嶅姟鍣?/label><input id="smtp_host" placeholder="smtp.qq.com"></div><div><label>SMTP 绔彛</label><input id="smtp_port" placeholder="465"></div><div><label>SMTP 璐﹀彿</label><input id="smtp_user" placeholder="閭璐﹀彿"></div><div><label>鍙戜欢浜?/label><input id="smtp_sender" placeholder="榛樿鍚岃处鍙?></div></div>
      <div class="row"><button onclick="startTool('audience')">瑙備紬娴嬭瘯</button><button onclick="startTool('audience_apply')">瑙備紬娴嬭瘯骞跺簲鐢?/button><button onclick="startTool('self_optimizer_once')">鑷紭鍖栦竴娆?/button><button onclick="startTool('self_optimizer_daemon')">鍚姩鑷紭鍖栧櫒</button></div>
      <p class="desc"><b>瑙備紬娴嬭瘯锛?/b>鎵弿鍏紑瑙嗛鍙?璇讳功绫诲弽棣堜俊鍙凤紝杈撳嚭瑙備紬椋庨櫓鎶ュ憡銆?br><b>瑙備紬娴嬭瘯骞跺簲鐢細</b>鍦ㄨ浼楁祴璇曞熀纭€涓婂厑璁歌嚜鍔ㄥ啓鍏ュ彲搴旂敤淇銆?br><b>鑷紭鍖栦竴娆★細</b>绔嬪嵆璺戜竴杞嚜浼樺寲瑙傚療銆乺ole-play銆佽鍒掑拰璁板綍銆?br><b>鍚姩鑷紭鍖栧櫒锛?/b>鍚姩闀胯繍琛?daemon锛屽畾鏃惰瀵熼」鐩苟鍐欏叆鏃ュ織/鐘舵€併€?/p>
      <div class="row"><button onclick="startTool('package_update')">鐢熸垚娴嬭瘯鐗堟湰鏇存柊鍖?/button><button onclick="startTool('init_release')">鍒濆鍖栨祴璇曠増鏈洰褰?/button><button onclick="startTool('model_help')">CLI 鑷</button><button onclick="openXiaozhuli()">鎵撳紑灏忕尓鐞嗗唴宓?/button></div>
      <p class="desc"><b>鐢熸垚娴嬭瘯鐗堟湰鏇存柊鍖咃細</b>鍙敓鎴?test 寰呮洿鏂?zip锛屼笉浼氬簲鐢ㄥ埌褰撳墠鏈嶅姟銆?br><b>鍒濆鍖栨祴璇曠増鏈洰褰曪細</b>鍒涘缓鎴栧垵濮嬪寲娴嬭瘯鐗堢洰褰曘€傚紑鍙戠増鏄綋鍓嶆簮鐮佺洰褰曪紱娴嬭瘯鐗堢敤浜庨獙鏀躲€?br><b>CLI 鑷锛?/b>鎵撳紑鏂囧彶 CLI help锛岄獙璇佸叆鍙ｅ弬鏁版槸鍚︽甯搞€?br><b>鎵撳紑灏忕尓鐞嗗唴宓岋細</b>鍦ㄥ綋鍓嶆湇鍔′笅浠ｇ悊鎵撳紑鍙︿竴涓皬鐚悊 dashboard銆?/p>
      <p class="hint">鏁忔劅 Key 涓嶅湪缃戦〉涓睍绀恒€傛ā鍨嬪拰 SMTP 鐨勭湡瀹炶繛閫氭祴璇曚繚鐣欐湰鍦伴厤缃?鐜鍙橀噺鏂瑰紡锛屽悗缁彲缁х画鍋氫笓闂ㄦ祴璇曟帴鍙ｃ€?/p>
    </section>

    <div class="row"><button class="secondary" onclick="saveSettings()">淇濆瓨璁剧疆</button><button class="danger" onclick="stopJob()">鍋滄褰撳墠浠诲姟</button></div>
    <div class="status" id="status">寰呭懡</div><div class="cmd" id="cmd"></div>
  </aside>
  <main><pre id="log"></pre></main>
</div>
<script>
let currentJob="";
function byId(id){return document.getElementById(id)}
function cap(s){return s[0].toUpperCase()+s.slice(1)}
function showPanel(name){for(const n of ["culture","research","clip","model","more"]){byId("panel"+cap(n)).classList.toggle("active",n===name);byId("tab"+cap(n)).classList.toggle("active",n===name)}}
function syncModelMirrorFields(){
  const gptBase=fieldValue("gpt_base_url")||defaultForeignBaseUrl;
  const gptProBase=fieldValue("deepseek_base_url")||defaultDeepseekBaseUrl;
  const gptImageBase=fieldValue("gpt_image_base_url")||gptBase;
  if(byId("text_engine")&&!(byId("text_engine").value||""))byId("text_engine").value=fieldValue("culture_text_model")||"gpt-5.5";
  if(byId("polish_engine")&&!(byId("polish_engine").value||""))byId("polish_engine").value=fieldValue("culture_polish_model")||"gpt-5.5";
  if(byId("image_engine")&&!(byId("image_engine").value||""))byId("image_engine").value=fieldValue("culture_image_model")||"GPT-image2";
  return {
    foreign_base_url:gptBase,
    deepseek_base_url:gptProBase,
    gpt_base_url:gptBase,
    gpt_pro_base_url:gptProBase,
    gpt_image_base_url:gptImageBase,
    culture_text_base_url:gptBase,
    culture_polish_base_url:gptProBase,
    culture_image_base_url:gptImageBase,
    research_text_base_url:gptBase,
    research_polish_base_url:gptProBase,
    research_image_base_url:gptImageBase,
    text_engine:fieldValue("text_engine")||fieldValue("culture_text_model")||"gpt-5.5",
    polish_engine:fieldValue("polish_engine")||fieldValue("culture_polish_model")||"gpt-5.5",
    image_engine:fieldValue("image_engine")||fieldValue("culture_image_model")||"GPT-image2"
  };
}
function loadSettings(){const r=fetch("/api/settings");return r.then(r=>r.json()).then(data=>{const s=data.settings||{},m=data.models||{};const merged={...s,...m};for(const [k,v] of Object.entries(merged)){if(byId(k))byId(k).value=v||""}if(byId("gpt_base_url"))byId("gpt_base_url").value=m.gpt_base_url||m.culture_text_base_url||m.foreign_base_url||defaultForeignBaseUrl;if(byId("deepseek_base_url"))byId("deepseek_base_url").value=m.deepseek_base_url||defaultDeepseekBaseUrl;if(byId("gpt_image_base_url"))byId("gpt_image_base_url").value=m.gpt_image_base_url||m.culture_image_base_url||m.foreign_base_url||defaultForeignBaseUrl;if(byId("minimax_base_url"))byId("minimax_base_url").value=m.minimax_base_url||defaultMiniMaxBaseUrl;syncModelMirrorFields();renderModelProfiles(data.model_profiles||{});applyKeyStatus(data.secrets||{});applyEmailStatus(data.email_secret||{});loadApps();return data})}
function restoreDefaultUrls(){
  if(byId("gpt_base_url"))byId("gpt_base_url").value=defaultForeignBaseUrl;
  if(byId("deepseek_base_url"))byId("deepseek_base_url").value=defaultDeepseekBaseUrl;
  if(byId("gpt_image_base_url"))byId("gpt_image_base_url").value=defaultForeignBaseUrl;
  if(byId("minimax_base_url"))byId("minimax_base_url").value=defaultMiniMaxBaseUrl;
  syncModelMirrorFields();
  const p=(modelProfiles.profiles||[]).find(x=>x.id===selectedProfileId())||{};
  renderRouteSummary(p);
  setStatus("妯″瀷鍦板潃宸叉仮澶嶉粯璁わ紝鐐瑰嚮淇濆瓨鍚庣敓鏁?,"ok");
}
function collect(){const ids=["culture_book","culture_out_dir","culture_continue_folder","culture_text_provider","culture_text_model","culture_polish_provider","culture_polish_model","culture_image_provider","culture_image_model","research_out_dir","research_days","research_max_articles","research_journals","research_article_list","text_engine","polish_engine","image_engine","gpt_base_url","deepseek_base_url","gpt_image_base_url","minimax_base_url","culture_text_base_url","culture_polish_base_url","culture_image_base_url","research_text_base_url","research_polish_base_url","research_image_base_url","openai_api_key","image_api_key","gpt_pro_api_key","minimax_api_key","smtp_password","auto_clip_image_dir","auto_clip_lrc_dir","auto_clip_output_dir","auto_clip_bgm","minimax_voice_id","minimax_tts_model","minimax_bgm_model","minimax_bgm_prompt","email_recipient","smtp_host","smtp_port","smtp_user","smtp_sender"];const p={};for(const id of ids){if(byId(id))p[id]=byId(id).value}return p}
function clearSecretInputs(){for(const id of ["openai_api_key","image_api_key","gpt_pro_api_key","minimax_api_key","smtp_password"]){if(byId(id))byId(id).value=""}}
function hideSecret(key){const prefix=keyNameMap[key];visibleSecrets[key]=false;if(prefix&&byId(prefix+"_key_value"))byId(prefix+"_key_value").textContent="宸查殣钘?}
async function toggleSecret(key){const prefix=keyNameMap[key];if(!prefix)return;if(visibleSecrets[key]){hideSecret(key);notify("宸查殣钘忔晱鎰熶俊鎭?,"ok");return}const b=beginAction("姝ｅ湪璇诲彇鏈満瀵嗛挜鐘舵€?..");try{const box=byId(prefix+"_key_value");if(box)box.textContent="璇诲彇涓?..";const r=await fetch("/api/secret?key="+encodeURIComponent(key));const data=await r.json();if(key==="smtp_password"){const email=data.email_secret||{};if(box)box.textContent=email.smtp_password||"鏈厤缃?;applyEmailStatus(email)}else{const sec=data.secrets||{};if(box)box.textContent=sec[key]||"鏈厤缃?;applyKeyStatus(sec)}visibleSecrets[key]=true;endAction(b,"瀵嗛挜宸茶鍙栵紱娉ㄦ剰涓嶈鍦ㄤ粬浜哄彲瑙佹椂灞曠ず","ok")}catch(err){failAction(b,err,"璇诲彇瀵嗛挜澶辫触")}}
function renderTest(id,result){const el=byId(id);if(!el)return;const ok=result&&result.ok;el.innerHTML=(ok?'<span class="ok">娴嬭瘯閫氳繃</span>':'<span class="missing">娴嬭瘯澶辫触</span>')+" 锝?"+((result&&result.message)||"鏃犵粨鏋?)+((result&&result.suggestion)?(" 锝?寤鸿锛?+result.suggestion):"")}
function appendLogLine(message){const el=byId("log");if(!el)return;const now=new Date().toLocaleTimeString();const current=el.textContent==="鏆傛棤鏃ュ織"?"":el.textContent;const lines=(current+"["+now+"] "+message+"\\n").split("\\n").slice(-1000);el.textContent=lines.join("\\n");el.scrollTop=el.scrollHeight}
function selectedProfileName(){const p=(modelProfiles.profiles||[]).find(x=>x.id===selectedProfileId())||{};return profileLabel(p)}
function newModelProfile(){const sel=byId("model_profile_select");if(sel)sel.value="";if(byId("model_profile_name"))byId("model_profile_name").value="";setStatus("宸插垏鎹㈠埌鏂板缓鏂规锛屽彲鐩存帴缂栬緫鍚庝繚瀛?,"ok")}
function testMeta(provider,payload){const map={openai:{label:"GPT",model:payload.culture_text_model||payload.text_engine||"gpt-5.5",url:payload.culture_text_base_url||payload.foreign_base_url},image:{label:"GPT-image2",model:payload.culture_image_model||payload.image_engine||"gpt-image-2",url:payload.culture_image_base_url||payload.foreign_base_url},gpt_pro:{label:"润色文本",model:payload.culture_polish_model||payload.polish_engine||"gpt-5.5",url:payload.culture_polish_base_url||payload.gpt_base_url||payload.foreign_base_url},minimax:{label:"MiniMax",model:payload.minimax_tts_model||"speech-2.8-hd",url:payload.minimax_base_url||defaultMiniMaxBaseUrl}};return map[provider]||{label:provider,model:"",url:""}}
function logTestResult(meta,result){const ok=result&&result.ok;appendLogLine((ok?"閫氳繃 ":"澶辫触 ")+meta.label+" 锝?model="+(result.model||meta.model||"鏈缃?)+" 锝?url="+(result.endpoint||meta.url||"鏈缃?)+" 锝?"+((result&&result.message)||"鏃犵粨鏋?));if(result&&result.suggestion)appendLogLine("寤鸿 "+meta.label+" 锝?"+result.suggestion)}
async function runModelTest(provider,{batch=false}={}){const id=provider+"_test_result";const payload={...collect(),provider,profile_id:selectedProfileId()};const meta=testMeta(provider,payload);if(byId(id))byId(id).textContent="娴嬭瘯涓?..";appendLogLine("寮€濮嬫祴璇?"+meta.label+" 锝?鏂规="+selectedProfileName()+" 锝?model="+(meta.model||"鏈缃?)+" 锝?url="+(meta.url||"鏈缃?));const r=await fetch("/api/test_model",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});const data=await r.json();clearSecretInputs();for(const key of Object.keys(keyNameMap))hideSecret(key);const result=data.result||{};renderTest(id,result);applyKeyStatus(data.secrets||{});applyEmailStatus(data.email_secret||{});logTestResult(meta,result);if(!batch)setStatus(result.ok?"妯″瀷娴嬭瘯閫氳繃":"妯″瀷娴嬭瘯澶辫触锛?+(result.message||"璇风湅鍙充晶鏃ュ織"),result.ok?"ok":"error");return result}
async function testModel(provider){const b=beginAction("姝ｅ湪娴嬭瘯妯″瀷杩為€氭€?..");try{const result=await runModelTest(provider);endAction(b,result.ok?"妯″瀷娴嬭瘯閫氳繃":"妯″瀷娴嬭瘯澶辫触锛?+(result.message||"璇风湅鍙充晶鏃ュ織"),result.ok?"ok":"error")}catch(err){appendLogLine("寮傚父 妯″瀷娴嬭瘯 锝?"+((err&&err.message)||err||"unknown"));failAction(b,err,"妯″瀷娴嬭瘯澶辫触")}}
async function testAllModels(){const b=beginAction("姝ｅ湪娴嬭瘯鍏ㄩ儴妯″瀷閾炬帴...");appendLogLine("==== 寮€濮嬫祴璇曞叏閮ㄦā鍨嬮摼鎺?锝?鏂规="+selectedProfileName()+" ====");let okCount=0;const plan=["openai","image","gpt_pro","minimax"];try{for(const provider of plan){const result=await runModelTest(provider,{batch:true});if(result&&result.ok)okCount++}const allOk=okCount===plan.length;appendLogLine("==== 鍏ㄩ儴妯″瀷閾炬帴娴嬭瘯瀹屾垚 锝?閫氳繃 "+okCount+"/"+plan.length+" ====");endAction(b,allOk?"鍏ㄩ儴妯″瀷閾炬帴娴嬭瘯閫氳繃":"妯″瀷閾炬帴娴嬭瘯瀹屾垚锛岄儴鍒嗗け璐ワ紝璇风湅鍙充晶鏃ュ織",allOk?"ok":"error")}catch(err){appendLogLine("寮傚父 鍏ㄩ儴妯″瀷閾炬帴娴嬭瘯 锝?"+((err&&err.message)||err||"unknown"));failAction(b,err,"鍏ㄩ儴妯″瀷閾炬帴娴嬭瘯澶辫触")}}
async function testEmail(){const b=beginAction("姝ｅ湪娴嬭瘯 SMTP...");try{if(byId("smtp_test_result"))byId("smtp_test_result").textContent="娴嬭瘯涓?..";appendLogLine("寮€濮嬫祴璇?SMTP 锝?host="+(fieldValue("smtp_host")||"鏈缃?)+" 锝?user="+(fieldValue("smtp_user")||"鏈缃?));const r=await fetch("/api/test_email",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(collect())});const data=await r.json();clearSecretInputs();hideSecret("smtp_password");const result=data.result||{};renderTest("smtp_test_result",result);applyEmailStatus(data.email_secret||{});appendLogLine((result.ok?"閫氳繃 ":"澶辫触 ")+"SMTP 锝?"+(result.message||"鏃犵粨鏋?));if(result.suggestion)appendLogLine("寤鸿 SMTP 锝?"+result.suggestion);endAction(b,result.ok?"SMTP 娴嬭瘯閫氳繃":"SMTP 娴嬭瘯澶辫触锛?+(result.message||"璇风湅鍙充晶鏃ュ織"),result.ok?"ok":"error")}catch(err){appendLogLine("寮傚父 SMTP 娴嬭瘯 锝?"+((err&&err.message)||err||"unknown"));failAction(b,err,"SMTP 娴嬭瘯澶辫触")}}
async function saveSettings(){const b=beginAction("姝ｅ湪淇濆瓨鎬绘帶鍙拌缃?..");try{const payload={...collect(),...syncModelMirrorFields()};const r=await fetch("/api/settings",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});const data=await r.json();clearSecretInputs();for(const key of Object.keys(keyNameMap))hideSecret(key);renderModelProfiles(data.model_profiles||{});applyKeyStatus(data.secrets||{});applyEmailStatus(data.email_secret||{});loadApps();endAction(b,data.ok?"璁剧疆宸蹭繚瀛橈紱瀛愰」鐩細浣跨敤鎬绘帶鍙板綋鍓嶉厤缃?:"淇濆瓨澶辫触",data.ok?"ok":"error");return data}catch(err){failAction(b,err,"淇濆瓨澶辫触");return {ok:false,error:String(err&&err.message||err)}}}}
async function applyModelProfile(){const id=selectedProfileId();if(!id){setStatus("璇峰厛閫夋嫨妯″瀷鏂规","error");return}const b=beginAction("姝ｅ湪搴旂敤妯″瀷鏂规...");try{const r=await fetch("/api/model_profile",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({action:"apply",profile_id:id})});const data=await r.json();if(!data.ok){endAction(b,"搴旂敤鏂规澶辫触锛?+(data.error||"unknown"),"error");return}clearSecretInputs();for(const key of Object.keys(keyNameMap))hideSecret(key);const s=data.settings||{},m=data.models||{};for(const [k,v] of Object.entries({...s,...m})){if(byId(k))byId(k).value=v||""}syncModelMirrorFields();renderModelProfiles(data.model_profiles||{});applyKeyStatus(data.secrets||{});applyEmailStatus(data.email_secret||{});loadApps();endAction(b,"妯″瀷鏂规宸插簲鐢紱瀛愰」鐩惎鍔ㄦ椂浼氬悓姝ヤ娇鐢?,"ok")}catch(err){failAction(b,err,"搴旂敤鏂规澶辫触")}}
async function applyProfileKey(key){const prefix=keyNameMap[key];const sel=prefix?byId(prefix+"_key_profile_select"):null;const profileId=sel?sel.value:"";if(!profileId){setStatus("璇峰厛閫夋嫨涓€涓凡淇濆瓨 Key","error");return}const b=beginAction("姝ｅ湪搴旂敤 Key...");try{const r=await fetch("/api/model_profile",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({action:"apply_key",profile_id:profileId,key_name:key})});const data=await r.json();if(!data.ok){endAction(b,"搴旂敤 Key 澶辫触锛?+(data.error||"unknown"),"error");return}clearSecretInputs();hideSecret(key);renderModelProfiles(data.model_profiles||{});applyKeyStatus(data.secrets||{});applyEmailStatus(data.email_secret||{});loadApps();endAction(b,"Key 宸插簲鐢紱鍚勫瓙椤圭洰鍚姩鏃朵細浣跨敤鎬绘帶鍙板綋鍓嶉厤缃?,"ok")}catch(err){failAction(b,err,"搴旂敤 Key 澶辫触")}}
async function saveModelProfile(){const name=(byId("model_profile_name")&&byId("model_profile_name").value)||"";const id=selectedProfileId();const b=beginAction("姝ｅ湪淇濆瓨妯″瀷鏂规...");try{const payload={...collect(),...syncModelMirrorFields()};const r=await fetch("/api/model_profile",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({...payload,action:"save",profile_id:id,profile_name:name})});const data=await r.json();if(!data.ok){endAction(b,"淇濆瓨鏂规澶辫触锛?+(data.error||"unknown"),"error");return}clearSecretInputs();for(const key of Object.keys(keyNameMap))hideSecret(key);renderModelProfiles(data.model_profiles||{});applyKeyStatus(data.secrets||{});applyEmailStatus(data.email_secret||{});loadApps();endAction(b,"妯″瀷鏂规宸蹭繚瀛?,"ok")}catch(err){failAction(b,err,"淇濆瓨鏂规澶辫触")}}
async function deleteModelProfile(){const id=selectedProfileId();if(!id){setStatus("璇峰厛閫夋嫨妯″瀷鏂规","error");return}if(id==="foreign-default"){setStatus("榛樿鏂规涓嶈兘鍒犻櫎","error");return}const b=beginAction("姝ｅ湪鍒犻櫎妯″瀷鏂规...");try{const r=await fetch("/api/model_profile",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({action:"delete",profile_id:id})});const data=await r.json();if(!data.ok){endAction(b,"鍒犻櫎鏂规澶辫触锛?+(data.error||"unknown"),"error");return}renderModelProfiles(data.model_profiles||{});loadApps();endAction(b,"妯″瀷鏂规宸插垹闄?,"ok")}catch(err){failAction(b,err,"鍒犻櫎鏂规澶辫触")}}
async function start(payload){const b=beginAction("姝ｅ湪淇濆瓨璁剧疆骞跺惎鍔ㄤ换鍔?..");try{const saved=await saveSettings();if(saved&&!saved.ok){endAction(b,"璁剧疆淇濆瓨澶辫触锛屼换鍔℃湭鍚姩","error");return}const r=await fetch("/api/start",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});const data=await r.json();currentJob=data.job_id||"";cmd.textContent=(data.cmd||[]).join(" ");endAction(b,data.message||"浠诲姟宸插惎鍔?,"ok");poll()}catch(err){failAction(b,err,"鍚姩浠诲姟澶辫触")}}
function startCulture(test){start({...collect(),mode:"culture",stage:byId("culture_stage").value,test_b_image_limit:test?1:Number(byId("culture_test_b").value||0)})}
function startResearch(action){start({...collect(),mode:"research",action})}
function startClip(){start({...collect(),mode:"auto_clip"})}
function startBgm(){start({...collect(),mode:"bgm"})}
function startTool(action){start({...collect(),mode:"tool",action})}
function openEegAnalyser(){notify("姝ｅ湪鎵撳紑鑴戠數鍒嗘瀽骞冲彴...","ok");window.open("/eeg/","_blank")}
function openXiaozhuli(){notify("姝ｅ湪鎵撳紑鍏ㄦ緶灏忕尓鐞?..","ok");window.open("/xiaozhuli/","_blank")}
async function stopJob(){if(!currentJob){setStatus("褰撳墠娌℃湁姝ｅ湪杩愯鐨勪换鍔?,"error");return}const b=beginAction("姝ｅ湪鍋滄褰撳墠浠诲姟...");try{await fetch("/api/stop?id="+encodeURIComponent(currentJob),{method:"POST"});endAction(b,"鍋滄璇锋眰宸插彂閫?,"ok");poll()}catch(err){failAction(b,err,"鍋滄浠诲姟澶辫触")}}
async function poll(){if(!currentJob)return;const r=await fetch("/api/job?id="+encodeURIComponent(currentJob));const data=await r.json();const message=data.status+" / exit="+(data.exit_code??"");const el=byId("status");if(el)el.textContent=message;log.textContent=(data.lines||[]).join("");log.scrollTop=log.scrollHeight;if(["running","starting","stopping"].includes(data.status))setTimeout(poll,1000);else notify("浠诲姟鐘舵€侊細"+message,data.exit_code===0?"ok":"info")}
for(const id of ["culture_text_model","culture_polish_model","culture_image_model","text_engine","polish_engine","image_engine","gpt_base_url","deepseek_base_url","gpt_image_base_url","minimax_base_url"]){const el=byId(id);if(el)el.addEventListener("input",()=>{syncModelMirrorFields();const p=(modelProfiles.profiles||[]).find(x=>x.id===selectedProfileId())||{};renderRouteSummary(p)})}
loadSettings();
if(location.hash==="#more"){showPanel("more")}else if(location.hash==="#culture"){showPanel("culture")}else if(location.hash==="#research"){showPanel("research")}else if(location.hash==="#clip"){showPanel("clip")}else{showPanel("model")}
</script>
</body>
</html>""".encode("utf-8")


def _entry_html_v2() -> bytes:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>全澜应用总控台</title>
  <style>
    :root{font-family:Arial,"Microsoft YaHei",sans-serif;color:#17202a;background:#f3f6f8;--brand:#0f766e;--line:#d8e0e7;--muted:#64748b;--card:#fff;--shadow:0 10px 26px rgba(15,23,42,.07)}
    *{box-sizing:border-box}body{margin:0;background:linear-gradient(180deg,#f8fafc 0%,#eef4f3 100%)}.wrap{max-width:1040px;margin:0 auto;padding:30px 18px}
    h1{font-size:28px;margin:0 0 8px}.hint{color:var(--muted);font-size:14px;line-height:1.6;margin:0 0 22px;max-width:920px}
    .section-head{align-items:flex-end;display:flex;gap:12px;justify-content:space-between;margin:20px 0 10px}.section-head h2{font-size:18px;margin:0}.section-head span{color:var(--muted);font-size:12px}
    .grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}.card{display:block;background:var(--card);border:1px solid var(--line);border-radius:8px;padding:16px;text-decoration:none;color:inherit;box-shadow:var(--shadow);min-width:0}.card:hover{border-color:#14b8a6;box-shadow:0 12px 28px rgba(15,118,110,.14);transform:translateY(-1px)}
    .title{font-size:17px;font-weight:800;margin-bottom:6px}.desc{font-size:13px;color:var(--muted);line-height:1.5;margin-top:8px}.meta{color:var(--muted);font-size:12px;line-height:1.5;margin-top:8px;overflow-wrap:anywhere}
    .row{display:flex;gap:8px;margin-top:12px;flex-wrap:wrap}button{padding:8px 10px;border:0;border-radius:6px;background:var(--brand);color:#fff;cursor:pointer}button+button{background:#334155}
    .pill{display:inline-flex;align-items:center;min-height:24px;padding:0 8px;border-radius:999px;background:#eef2f6;color:#334155;font-size:12px;font-weight:800}.pill.ok{background:#ecfdf3;color:#027a48}.pill.warn{background:#fff7ed;color:#b54708}
    @media(max-width:900px){.grid{grid-template-columns:1fr}.section-head{align-items:flex-start;flex-direction:column}}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>全澜应用总控台</h1>
    <p class="hint">这里是三个项目的统一入口和控制面板；项目页只保留业务操作，大模型连接统一在“连接库”维护并同步到各项目本地配置，Key 全程仅显示配置状态。</p>
    <div class="section-head"><h2>项目入口</h2><span id="home_app_summary">正在读取状态</span></div>
    <section class="grid" id="home_app_grid">
      <a class="card" href="/assistant/"><div class="title">自媒体小猪理</div><div class="desc">文史、科研、剪辑与邮箱配置业务入口。</div></a>
      <a class="card" href="/xiaozhuli/"><div class="title">全澜小猪理</div><div class="desc">销售知识库、客户建议、Role-play 记录和服务状态。</div></a>
      <a class="card" href="/eeg/"><div class="title">脑电分析平台</div><div class="desc">NeuroCloud EEG 分析流程入口。</div></a>
    </section>
    <div class="section-head"><h2>公共配置</h2><span>只在总控台维护</span></div>
    <section class="grid">
      <a class="card" href="/model/"><div class="title">大模型连接库</div><div class="desc">添加、查阅、编辑、删除和测试各类模型连接；任务自动组合可用连接。</div></a>
      <a class="card" href="/audience/"><div class="title">虚拟用户测试</div><div class="desc">按项目自动列出虚拟用户评审入口，并在页面内查看运行日志。</div></a>
    </section>
    <div class="section-head"><h2>自优化器统一控制</h2><span>代码保留在各自项目中</span></div>
    <section class="grid">
      <a class="card" href="/optimizer/"><div class="title">进入自优化器控制台</div><div class="desc">统一启动、停止三个项目的自优化器，并集中查看各项目运行日志。</div></a>
    </section>
  </div>
<script>
function pill(app){const online=!!(app&&app.online),sync=(app&&app.sync_state)||"未知";const cls=online&&(sync==="已同步"||sync==="流程平台")?"ok":(online?"warn":"");return '<span class="pill '+cls+'">'+(online?"在线":"离线")+' ｜ '+sync+'</span>'}
function esc(s){return String(s||"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\\\"":"&quot;","'":"&#39;"}[c]))}
fetch("/api/apps").then(r=>r.json()).then(data=>{const apps=data.apps||[];const grid=document.getElementById("home_app_grid");document.getElementById("home_app_summary").textContent="已读取 "+apps.length+" 个项目";if(!grid||!apps.length)return;grid.innerHTML=apps.map(app=>'<a class="card" href="'+esc(app.route||"/")+'"><div class="title">'+esc(app.name||app.id)+'</div><div>'+pill(app)+'</div><div class="desc">'+esc(app.description||app.config_scope||"")+'</div><div class="meta">'+esc(app.config_scope||"")+'</div></a>').join("")}).catch(()=>{document.getElementById("home_app_summary").textContent="状态读取失败"})
</script>
</body>
</html>""".encode("utf-8")


def _project_control_html(kind: str) -> bytes:
    is_optimizer = kind == "optimizer"
    title = "自优化器统一控制" if is_optimizer else "虚拟用户测试"
    desc = "统一启动、停止各项目自己的自优化器，并集中查看运行日志；总控台只负责控制，不搬运项目代码。" if is_optimizer else "自动读取总控台项目列表；每个项目仍运行自己工程内的虚拟用户/角色评审入口，日志集中显示在这里。"
    endpoint = "/api/optimizer" if is_optimizer else "/api/audience"
    result_title = "运行日志" if is_optimizer else "虚拟用户测试结果"
    summary_style = "display:none" if is_optimizer else ""
    raw_log_open = " open" if is_optimizer else ""
    body = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    :root{{font-family:Arial,"Microsoft YaHei",sans-serif;color:#1f2937;background:#f5f7fb;--brand:#1769aa;--line:#d7dce2;--muted:#667085;--bad:#b3261e}}
    *{{box-sizing:border-box}}body{{margin:0;padding:20px}}.wrap{{max-width:1280px;margin:0 auto}}
    .top{{display:flex;align-items:flex-start;justify-content:space-between;gap:14px;margin-bottom:16px}}h1{{font-size:26px;margin:0 0 8px}}.hint{{color:var(--muted);font-size:13px;line-height:1.6;margin:0;max-width:820px}}
    a.home{{display:inline-flex;align-items:center;min-height:38px;padding:0 13px;border-radius:8px;background:#111827;color:#fff;text-decoration:none;font-weight:700}}
    .layout{{display:grid;grid-template-columns:430px 1fr;gap:14px}}.grid{{display:grid;gap:12px}}.card{{background:#fff;border:1px solid var(--line);border-radius:10px;padding:14px;box-shadow:0 8px 22px rgba(15,23,42,.05)}}
    .title{{font-size:17px;font-weight:800;margin-bottom:6px}}.desc{{font-size:12px;color:var(--muted);line-height:1.5;margin:6px 0}}.meta{{font-size:12px;color:var(--muted);word-break:break-all}}
    .row{{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}}button{{border:0;border-radius:7px;background:var(--brand);color:#fff;padding:8px 10px;cursor:pointer}}button.secondary{{background:#475569}}button.danger{{background:var(--bad)}}button.ghost{{background:#eef2f6;color:#263238}}
    .status{{font-size:13px;color:var(--brand);margin:0 0 10px;word-break:break-all}}.summary{{display:grid;grid-template-columns:1fr;gap:10px;margin:12px 0}}.summary-box{{border:1px solid var(--line);border-radius:8px;background:#f8fafc;padding:12px}}.summary-box h3{{font-size:14px;margin:0 0 8px}}.summary-box ul{{margin:0;padding-left:18px;color:#334155;font-size:13px;line-height:1.6}}.summary-box li+li{{margin-top:4px}}details{{margin-top:12px}}summary{{cursor:pointer;color:#475569;font-size:13px;font-weight:700}}pre{{white-space:pre-wrap;background:#111827;color:#e5e7eb;border-radius:10px;padding:14px;max-height:46vh;overflow:auto}}
    .dialog-backdrop{{position:fixed;inset:0;background:rgba(15,23,42,.42);display:none;align-items:center;justify-content:center;padding:20px;z-index:20}}.dialog{{width:min(620px,100%);background:#fff;border-radius:10px;padding:16px;border:1px solid var(--line);box-shadow:0 20px 60px rgba(15,23,42,.24)}}.dialog textarea{{width:100%;min-height:150px;border:1px solid #cbd5e1;border-radius:8px;padding:10px;font:14px/1.5 Arial,"Microsoft YaHei",sans-serif;resize:vertical}}.dialog .row{{justify-content:flex-end}}
    @media(max-width:960px){{.layout{{grid-template-columns:1fr}}}}
  </style>
</head>
<body>
<div class="wrap">
  <div class="top">
    <div><h1>{title}</h1><p class="hint">{desc}</p></div>
    <a class="home" href="/">返回总控台</a>
  </div>
  <div class="layout">
    <section class="grid" id="project_grid"></section>
    <main class="card">
      <div class="title">{result_title}</div>
      <div class="status" id="status">选择项目后可启动或查看日志</div>
      <section class="summary" id="summary_panel" style="{summary_style}">
        <div class="summary-box"><h3>虚拟用户汇总</h3><ul id="summary_overview"><li>等待测试完成后生成汇总。</li></ul></div>
        <div class="summary-box"><h3>优化建议</h3><ul id="summary_suggestions"><li>暂无建议。</li></ul></div>
        <div class="summary-box"><h3>预计优化后的效果</h3><ul id="summary_effects"><li>暂无预计效果。</li></ul></div>
      </section>
      <details{raw_log_open}><summary>原始运行日志</summary><pre id="log">暂无日志</pre></details>
    </main>
  </div>
</div>
<div class="dialog-backdrop" id="feedback_dialog">
  <div class="dialog">
    <div class="title">输入优化建议</div>
    <p class="desc" id="feedback_target">选择项目后可写入虚拟用户测试建议。</p>
    <textarea id="feedback_text" placeholder="例如：普通观众看不懂开头，建议前 8 秒先抛出人物困境，再进入书名和章节。"></textarea>
    <div class="row">
      <button class="ghost" onclick="closeFeedbackDialog()">取消</button>
      <button onclick="submitFeedback()">写入建议</button>
    </div>
  </div>
</div>
<script>
const endpoint="{endpoint}";
const isOptimizer={str(is_optimizer).lower()};
const storageKey="quanlan_{kind}_jobs";
let jobs=JSON.parse(localStorage.getItem(storageKey)||"{{}}");
let selectedProject="";
let selectedJobKey="";
function esc(s){{return String(s||"").replace(/[&<>"']/g,c=>({{"&":"&amp;","<":"&lt;",">":"&gt;","\\\"":"&quot;","'":"&#39;"}}[c]))}}
function saveJobs(){{localStorage.setItem(storageKey,JSON.stringify(jobs))}}
function setStatus(text){{document.getElementById("status").textContent=text}}
function listHtml(items,emptyText){{const arr=Array.isArray(items)?items.filter(Boolean):[];return (arr.length?arr:[emptyText]).slice(0,8).map(x=>"<li>"+esc(x)+"</li>").join("")}}
function renderSummary(summary,data){{if(isOptimizer)return;const s=summary||{{}};const running=["running","starting","stopping"].includes((data&&data.status)||"");document.getElementById("summary_overview").innerHTML=listHtml(s.overview,running?"正在生成虚拟用户汇总...":"暂无汇总");document.getElementById("summary_suggestions").innerHTML=listHtml(s.suggestions,running?"测试完成后生成优化建议。":"暂无建议");document.getElementById("summary_effects").innerHTML=listHtml(s.expected_effects,running?"测试完成后估算优化效果。":"暂无预计效果")}}
function actionLabel(mode){{
  if(mode==="dev_upgrade")return "升级开发版本";
  if(mode==="release_deploy")return "部署发布版本";
  return isOptimizer?"运行一次":"启动虚拟用户测试";
}}
function jobKey(project,mode){{return project+":"+(mode||"once")}}
function actionButtons(app){{
  const id=esc(app.id);
  if(isOptimizer)return '<button onclick="startJob(\\''+id+'\\',\\'once\\')">运行一次</button> <button class="secondary" onclick="startJob(\\''+id+'\\',\\'daemon\\')">启动常驻</button>';
  return '<button onclick="startJob(\\''+id+'\\',\\'once\\')">启动虚拟用户测试</button> <button class="secondary" onclick="startJob(\\''+id+'\\',\\'dev_upgrade\\')">一键升级开发版</button> <button class="ghost" onclick="startJob(\\''+id+'\\',\\'release_deploy\\')">一键部署发布版</button> <button class="ghost" onclick="openFeedbackDialog(\\''+id+'\\')">输入优化建议</button>';
}}
function renderApps(apps){{
  const grid=document.getElementById("project_grid");
  grid.innerHTML=(apps||[]).map(app=>`<div class="card">
    <div class="title">${{esc(app.name||app.id)}}</div>
    <div class="desc">${{esc(app.config_scope||app.description||"")}}</div>
    <div class="meta">项目 ID：${{esc(app.id)}} ｜ 状态：${{app.online?"在线":"离线"}} ｜ ${{esc(app.sync_state||"")}}</div>
    <div class="row">
      ${{actionButtons(app)}}
      <button class="ghost" onclick="viewJob('${{esc(app.id)}}')">查看日志</button>
      <button class="danger" onclick="stopJob('${{esc(app.id)}}')">停止</button>
    </div>
  </div>`).join("");
}}
async function loadApps(){{const r=await fetch("/api/apps");const data=await r.json();renderApps(data.apps||[])}}
async function startJob(project,mode){{
  selectedProject=project;selectedJobKey=jobKey(project,mode);setStatus("正在"+actionLabel(mode)+"："+project+" ...");
  document.getElementById("log").textContent="正在创建任务："+project+" / "+actionLabel(mode)+"\\n等待后台返回任务编号...";
  renderSummary({{overview:["正在创建任务："+project+" / "+actionLabel(mode)],suggestions:["等待虚拟用户测试完成后生成建议。"],expected_effects:["测试完成后估算优化效果。"]}},{{status:"starting"}});
  const r=await fetch(endpoint,{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify({{project,mode}})}});
  const data=await r.json();
  if(!data.ok){{setStatus("启动失败："+(data.error||"unknown"));document.getElementById("log").textContent=data.error||"启动失败";return}}
  jobs[selectedJobKey]=data.job_id;jobs[project]=data.job_id;saveJobs();setStatus("已启动："+(data.name||project)+" / "+actionLabel(data.mode||mode));document.getElementById("log").textContent="任务已创建，正在读取后台日志...";poll();
}}
async function viewJob(project){{selectedProject=project;selectedJobKey=project;if(!jobs[project]){{setStatus(project+" 暂无本页启动的任务");document.getElementById("log").textContent="暂无日志";return}}poll()}}
async function stopJob(project){{const id=jobs[selectedJobKey]||jobs[project||selectedProject];if(!id){{setStatus("没有可停止的任务");return}}await fetch("/api/stop?id="+encodeURIComponent(id),{{method:"POST"}});setStatus("停止请求已发送");poll()}}
function openFeedbackDialog(project){{selectedProject=project;document.getElementById("feedback_target").textContent="写入项目："+project;document.getElementById("feedback_text").value="";document.getElementById("feedback_dialog").style.display="flex";document.getElementById("feedback_text").focus()}}
function closeFeedbackDialog(){{document.getElementById("feedback_dialog").style.display="none"}}
async function submitFeedback(){{const text=document.getElementById("feedback_text").value.trim();if(!text){{setStatus("请先输入优化建议");return}}setStatus("正在写入优化建议...");const r=await fetch("/api/audience_feedback",{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify({{project:selectedProject,text}})}});const data=await r.json();if(!data.ok){{setStatus("写入失败："+(data.error||"unknown"));return}}closeFeedbackDialog();setStatus("优化建议已写入："+(data.name||selectedProject));renderSummary({{overview:["已收到人工优化建议，后续虚拟用户测试会把它纳入问题队列。"],suggestions:[text],expected_effects:["预计下一轮会围绕这条建议生成更具体的修复项和复测结果。"]}},{{status:"finished"}})}}
async function poll(){{
  const id=jobs[selectedJobKey]||jobs[selectedProject];if(!id)return;
  const r=await fetch("/api/job?id="+encodeURIComponent(id));const data=await r.json();
  const readable=(["running","starting"].includes(data.status)?"正在处理":data.status==="stopping"?"正在停止":data.status==="finished"?(data.exit_code===0?"已完成":"未完成，请查看日志"):data.status==="failed"?"任务失败":"等待操作");
  setStatus((selectedProject||"项目")+" ｜ "+readable);
  renderSummary(data.summary,data);
  document.getElementById("log").textContent=(data.lines||[]).join("")||"暂无日志";
  if(["running","starting","stopping"].includes(data.status))setTimeout(poll,1000);
}}
loadApps();
</script>
</body>
</html>"""
    return body.encode("utf-8")


def _automedia_html_v2() -> bytes:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>自媒体小猪理工作台</title>
  <style>
    :root{font-family:Arial,"Microsoft YaHei",sans-serif;color:#1f2937;background:#f5f7fb;--brand:#1769aa;--line:#d7dce2;--muted:#607080;--soft:#f7f9fc;--bad:#b3261e}
    *{box-sizing:border-box}body{margin:0}.shell{display:grid;grid-template-columns:470px 1fr;min-height:100vh}
    aside{background:#fff;border-right:1px solid var(--line);padding:16px;overflow:auto}main{padding:16px;min-width:0;display:grid;grid-template-rows:minmax(320px,1fr) minmax(118px,auto) minmax(220px,.55fr);gap:12px;height:100vh}
    h1{font-size:20px;margin:0 0 6px}h2{font-size:16px;margin:14px 0 8px}.hint,.desc{font-size:12px;color:var(--muted);line-height:1.5}
    .boss-home{position:fixed;right:18px;bottom:18px;z-index:50;display:inline-flex;align-items:center;min-height:42px;padding:0 16px;border-radius:999px;background:#111827;color:#fff;font-weight:700;text-decoration:none;box-shadow:0 10px 28px rgba(15,23,42,.24)}
    .tabs{display:grid;grid-template-columns:repeat(5,1fr);gap:6px;margin:14px 0}.tabs button{background:#e8eef5;color:#263238}.tabs button.active{background:var(--brand);color:#fff}
    .panel{display:none}.panel.active{display:block}.grid2{display:grid;grid-template-columns:1fr 1fr;gap:10px}.grid3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px}
    label{display:block;font-size:12px;margin:8px 0 4px;color:#4f5b67}input,select{width:100%;padding:8px;border:1px solid #c8d0d8;border-radius:6px;background:#fff}
    .toggle-row{display:flex;align-items:center;gap:8px;margin-top:10px;color:#1f2937;font-size:13px}.toggle-row input{width:auto}
    button{padding:8px 10px;border:0;border-radius:6px;background:var(--brand);color:#fff;cursor:pointer}button.secondary{background:#5f6368}button.danger{background:var(--bad)}button.ghost{background:#eef2f6;color:#263238}
    .row{display:flex;gap:8px;margin-top:12px;flex-wrap:wrap}.status{font-size:13px;color:var(--brand);margin:8px 0;word-break:break-all}.cmd{font-size:12px;color:var(--muted);word-break:break-all}
    .tool-grid{display:grid;gap:10px;margin-top:10px}.tool-card{border:1px solid var(--line);border-radius:8px;background:var(--soft);padding:10px}.tool-card b{display:block;font-size:13px;margin-bottom:4px;color:#111827}.tool-card .desc{margin:0 0 8px}
    .science-path{background:#fff;border:1px solid var(--line);border-radius:8px;padding:10px;margin-top:10px}.checkbox-cell{display:flex;align-items:center;gap:6px}.checkbox-cell input{width:auto}.muted{color:var(--muted)}
    .workspace-card{background:#fff;border:1px solid var(--line);border-radius:8px;padding:12px;min-height:0;overflow:hidden}.section-head{display:flex;align-items:flex-start;justify-content:space-between;gap:10px;margin-bottom:8px}.section-head h2{margin:0 0 4px}
    .mini-stats{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:8px}.mini-stat{background:var(--soft);border:1px solid var(--line);border-radius:8px;padding:10px}.mini-stat b{display:block;font-size:18px;color:#111827}.mini-stat span{font-size:12px;color:var(--muted)}
    .article-card{display:flex;flex-direction:column}.list-panel{margin-top:10px;border:1px solid var(--line);border-radius:8px;background:#fff;min-height:0;overflow:auto;flex:1}.list-row{display:grid;grid-template-columns:64px 78px minmax(280px,1fr) 150px;gap:10px;padding:10px 12px;border-top:1px solid #edf0f3;font-size:12px;align-items:start}.list-row:first-child{border-top:0}.list-row.header{position:sticky;top:0;background:#f8fafc;color:#4f5b67;font-weight:700;z-index:1}.tag{display:inline-flex;align-items:center;justify-content:center;min-height:22px;padding:0 7px;border-radius:999px;font-weight:700;background:#eef2f6;color:#334155}.tag.done{background:#ecfdf3;color:#027a48}.tag.todo{background:#fff7ed;color:#b54708}.paper-title{font-weight:700;color:#1f2937}.paper-meta{margin-top:3px;color:var(--muted);overflow-wrap:anywhere}
    .jobs-card{display:flex;flex-direction:column;min-height:118px}.jobs-list{display:grid;gap:8px;overflow:auto;min-height:0}.job-row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px;align-items:center;border:1px solid var(--line);border-radius:8px;background:#fff;padding:8px 10px;cursor:pointer}.job-row.active{border-color:var(--brand);background:#f3f8fd}.job-title{font-weight:700;font-size:13px;color:#111827;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.job-meta{margin-top:3px;font-size:12px;color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.job-actions{display:flex;gap:6px}.job-actions button{padding:6px 8px;font-size:12px}
    .log-card{display:flex;flex-direction:column}.log-card pre{white-space:pre-wrap;background:#111827;color:#e5e7eb;border-radius:8px;padding:12px;min-height:0;flex:1;overflow:auto;margin:0}
    @media(max-width:900px){.shell{grid-template-columns:1fr}main{height:auto;grid-template-rows:auto auto auto}.grid2,.grid3{grid-template-columns:1fr}aside{border-right:0;border-bottom:1px solid var(--line)}.list-row{grid-template-columns:54px 62px minmax(0,1fr) 96px}.job-row{grid-template-columns:1fr}.job-actions{justify-content:flex-start}}
  </style>
</head>
<body>
<a class="boss-home" href="/">返回控制台首页</a>
<div class="shell">
  <aside>
    <h1>自媒体小猪理工作台</h1>
    <p class="hint">文史、每日研究速递、科学经典和剪辑任务集中在这里启动；运行日志在右侧显示。</p>
    <div class="tabs">
      <button id="tabCulture" onclick="showPanel('culture')">文史</button>
      <button id="tabDigest" onclick="showPanel('digest')">每日研究速递</button>
      <button id="tabScience" onclick="showPanel('science')">科学经典</button>
      <button id="tabClip" onclick="showPanel('clip')">剪辑</button>
      <button id="tabMore" onclick="showPanel('more')">更多</button>
    </div>
    <section id="panelCulture" class="panel">
      <h2>文史小秘</h2>
      <label>书籍 PDF</label><input id="culture_book" placeholder="D:/知识/xxx.pdf">
      <label>输出目录</label><input id="culture_out_dir" placeholder="D:/输出/文史素材">
      <label>继续目录</label><input id="culture_continue_folder" placeholder="可留空">
      <label>开始阶段</label><select id="culture_stage"><option>outline</option><option>split_pdf</option><option>episode_prompt</option><option>script</option><option>polish</option><option>images</option><option>postprocess</option><option>split_assets</option></select>
      <label>测试 B 图数</label><input id="culture_test_b" value="0">
      <div class="row"><button onclick="startCulture(false)">开始文史生成</button><button class="secondary" onclick="startCulture(true)">测试 B 图</button><button class="secondary" onclick="openOutputFolder('culture')">打开作品文件夹</button></div>
    </section>
    <section id="panelDigest" class="panel">
      <h2>每日研究速递</h2>
      <label>输出目录</label><input id="research_out_dir" placeholder="可留空">
      <div class="grid3"><div><label>检索天数</label><input id="research_days" value="14"></div><div><label>每期文章数</label><input id="research_max_articles" value="5"></div><div><label>每天期数</label><select id="research_issue_count"><option value="1">1 期</option><option value="2">2 期</option><option value="3">3 期</option></select></div></div>
      <label>期刊列表</label><input id="research_journals" placeholder="Nature, Science, Neuron...">
      <label>已有文献清单 / 续做目录</label><input id="research_article_list" placeholder="可留空">
      <label class="toggle-row"><input id="research_skip_medical_related" type="checkbox"> 微信避险：跳过医学、疾病、临床和生物医学外推相关论文</label>
      <label class="toggle-row"><input id="email_enabled" type="checkbox"> 完成后发送邮件</label>
      <div class="row"><button onclick="startResearch('digest')">开始创作</button><button onclick="startResearch('article_list')">补文献清单</button><button onclick="startResearch('continue_list')">清单续做</button><button onclick="startResearch('resume')">续做档期</button><button class="secondary" onclick="loadArticleList()">查看文献清单</button><button class="secondary" onclick="openOutputFolder('research')">打开作品文件夹</button></div>
    </section>
    <section id="panelScience" class="panel">
      <h2>科学经典</h2>
      <p class="hint">面向经典论文/科学著作解读，使用已选 PDF 的目录和章节选择，不走每日研究速递的最新论文检索。</p>
      <div class="science-path">
        <label>书籍 PDF</label><input id="science_pdf_path" placeholder="D:/Quanlan/全澜脑科学视频号/神经科学经典/...pdf">
        <label>作品文件夹</label><input id="science_out_dir" placeholder="D:/Quanlan/全澜脑科学视频号/神经科学经典/...">
        <div class="row"><button class="secondary" onclick="loadScienceToc(true)">读取 / 刷新目录</button><button class="ghost" onclick="selectScienceAll(true)">全选正文</button><button class="ghost" onclick="selectScienceAll(false)">取消选择</button></div>
      </div>
      <div class="tool-grid">
        <div class="tool-card"><b>开始创作</b><p class="desc">按右侧选中的章节执行解析、脚本、配图和后处理；适合正式生成科学经典素材。</p><button onclick="startScience(false)">开始创作</button></div>
        <div class="tool-card"><b>测试 B 图</b><p class="desc">只限制首张 B 图额度，用来快速验证提示词、生图 Key、后处理和成品素材链路。</p><button class="secondary" onclick="startScience(true)">测试 B 图</button></div>
        <div class="tool-card"><b>作品文件夹</b><p class="desc">打开或清空科学经典自己的输出目录，不影响每日研究速递目录。</p><div class="row"><button class="secondary" onclick="openOutputFolder('science')">打开作品文件夹</button><button class="danger" onclick="clearOutputFolder('science')">清空作品文件夹</button></div></div>
      </div>
    </section>
    <section id="panelClip" class="panel">
      <h2>自动剪辑 / BGM</h2>
      <label>图片目录</label><input id="auto_clip_image_dir" placeholder="分集图片目录">
      <label>LRC / 音频目录</label><input id="auto_clip_lrc_dir" placeholder="字幕或音频目录">
      <label>输出目录</label><input id="auto_clip_output_dir" placeholder="可留空">
      <label>BGM 音乐库</label><input id="auto_clip_bgm_library_dir" placeholder="默认使用项目音乐库">
      <label>选择 BGM</label><select id="auto_clip_bgm_select" onchange="selectBgmFromLibrary()"><option value="">不使用背景音乐</option></select>
      <label>BGM 文件/目录</label><input id="auto_clip_bgm" placeholder="可留空">
      <div class="grid2">
        <div><label>语音/音乐通道</label><select id="minimax_provider" onchange="applyMinimaxProvider()"><option value="official">MiniMax（官方）</option><option value="fast">MiniMax（极速）</option></select></div>
        <div><label>Base URL</label><input id="minimax_base_url" placeholder="https://api.53hk.cn"></div>
        <div><label>TTS 模型</label><input id="minimax_tts_model" placeholder="speech-2.8-hd"></div>
        <div><label>BGM 模型</label><input id="minimax_bgm_model" placeholder="music-2.6"></div>
      </div>
      <label>MiniMax Key</label><input id="minimax_api_key" type="password" autocomplete="off" placeholder="粘贴新 Key；保存后清空">
      <div class="grid2"><div><label>Voice ID</label><input id="minimax_voice_id" placeholder="male-qn-qingse"></div><div><label>BGM Prompt</label><input id="minimax_bgm_prompt" placeholder="instrumental, documentary, soft piano"></div></div>
      <div class="row"><button onclick="startClip()">启动自动剪辑</button><button class="secondary" onclick="startBgm()">生成并入库 BGM</button><button class="secondary" onclick="refreshBgmLibrary()">刷新音乐库</button><button class="secondary" onclick="openOutputFolder('clip')">打开作品文件夹</button></div>
    </section>
    <section id="panelMore" class="panel">
      <h2>更多工具</h2>
      <p class="hint">模型方案、虚拟用户、自优化和版本发布在这里集中入口；不会和文史/每日研究速递任务混在一起。</p>
      <div class="row"><button onclick="location.href='/model/'">大模型连接库</button><button class="secondary" onclick="location.href='/audience/'">虚拟用户测试</button><button class="secondary" onclick="location.href='/optimizer/'">自优化器控制台</button></div>
      <div class="row"><button onclick="startTool('audience_full_review')">当前项目虚拟用户测试</button><button class="secondary" onclick="startTool('self_optimizer_once')">自优化一次</button><button class="secondary" onclick="startTool('self_optimizer_daemon')">启动自优化器</button></div>
      <div class="row"><button class="secondary" onclick="startTool('package_update')">生成测试版更新包</button><button class="secondary" onclick="startTool('init_release')">初始化测试版目录</button><button class="secondary" onclick="startTool('model_help')">CLI 自检</button><button class="secondary" onclick="openXiaozhuli()">打开小猪理内嵌</button></div>
      <h2>邮箱配置</h2>
      <p class="hint">这里只保存发件与收件参数；SMTP 密码只写入本机配置，网页不回显明文。</p>
      <label>收件邮箱</label><input id="email_recipient" placeholder="多个邮箱用逗号分隔">
      <div class="grid2">
        <div><label>SMTP 服务器</label><input id="smtp_host" placeholder="smtp.qq.com"></div>
        <div><label>SMTP 端口</label><input id="smtp_port" placeholder="465"></div>
        <div><label>SMTP 账号</label><input id="smtp_user" placeholder="邮箱账号"></div>
        <div><label>发件人</label><input id="smtp_sender" placeholder="默认同账号"></div>
      </div>
      <label>SMTP 密码 / 授权码</label><input id="smtp_password" type="password" autocomplete="off" placeholder="粘贴新密码或授权码；保存后清空">
    </section>
    <div class="row"><button class="secondary" onclick="saveSettings()">保存当前设置</button><button class="danger" onclick="stopJob()">停止当前任务</button></div>
    <div class="status" id="status">待命</div><div class="cmd" id="cmd"></div>
  </aside>
  <main>
    <section class="workspace-card article-card" id="article_list_box">
      <div class="section-head">
        <div><h2 id="workspace_title">文献清单</h2><p class="hint" id="workspace_hint">查看当前有哪些文献、哪些已做、用在了哪几期。</p></div>
        <button class="secondary" id="workspace_refresh" onclick="loadArticleList()">刷新清单</button>
      </div>
      <div class="mini-stats">
        <div class="mini-stat"><b id="article_total">-</b><span>清单总数</span></div>
        <div class="mini-stat"><b id="article_done">-</b><span id="stat_done_label">已做</span></div>
        <div class="mini-stat"><b id="article_todo">-</b><span id="stat_todo_label">未做</span></div>
      </div>
      <div class="status" id="article_list_status">填写或选择文献清单后，点击查看。</div>
      <div class="list-panel" id="article_list_rows"></div>
    </section>
    <section class="workspace-card jobs-card">
      <div class="section-head"><div><h2>运行任务</h2><div class="hint">每个模式独立启动、独立停止，可同时制作多组素材。</div></div><button class="secondary" onclick="refreshAllJobs()">刷新任务</button></div>
      <div class="jobs-list" id="jobs_list">暂无运行任务</div>
    </section>
    <section class="workspace-card log-card">
      <div class="section-head"><div><h2>运行日志</h2><div class="status" id="job_status">等待操作</div></div></div>
      <pre id="log">暂无日志</pre>
    </section>
  </main>
</div>
<script>
const jobsStorageKey="quanlan_automedia_jobs_v2";
const selectedJobStorageKey="quanlan_automedia_selected_job";
let jobsById=JSON.parse(localStorage.getItem(jobsStorageKey)||"{}");
let selectedJobId=localStorage.getItem(selectedJobStorageKey)||"";
let pollHandles={};
let scienceToc=[];
function byId(id){return document.getElementById(id)}
function cap(s){return s[0].toUpperCase()+s.slice(1)}
function showPanel(name){for(const n of ["culture","digest","science","clip","more"]){const p=byId("panel"+cap(n)),t=byId("tab"+cap(n));if(p)p.classList.toggle("active",n===name);if(t)t.classList.toggle("active",n===name)}if(name==="science")loadScienceToc(false);else if(name==="digest")loadArticleList();else if(name==="culture")renderCultureWorkspace();else renderModeWorkspace(name)}
function fieldValue(id){const el=byId(id);return el?String(el.value||""):""}
function setField(id,value){const el=byId(id);if(el)el.value=value||""}
function setStatus(message){byId("status").textContent=message}
function jobStatusText(data){const s=String((data&&data.status)||"");if(["running","starting"].includes(s))return"正在处理";if(s==="stopping")return"正在停止";if(s==="finished")return data.exit_code===0?"已完成":"未完成，请查看日志";if(s==="failed")return"任务失败，请查看日志";return"等待操作"}
function isLiveStatus(s){return["running","starting","stopping"].includes(String(s||""))}
function saveJobs(){localStorage.setItem(jobsStorageKey,JSON.stringify(jobsById));localStorage.setItem(selectedJobStorageKey,selectedJobId||"")}
function jobBaseLabel(baseKey){const labels={"culture:test_b":"文史 / 测试 B 图","research:digest":"研究速递 / 开始创作","research:article_list":"研究速递 / 补文献清单","research:continue_list":"研究速递 / 清单续做","research:resume":"研究速递 / 续做档期","science:test_b":"科学经典 / 测试 B 图","science:run":"科学经典 / 开始创作","clip":"自动剪辑","bgm":"BGM 入库","tool:audience_full_review":"虚拟用户测试","tool:self_optimizer_once":"自优化一次","tool:self_optimizer_daemon":"自优化器","tool:package_update":"测试版更新包","tool:init_release":"初始化测试版","tool:model_help":"CLI 自检"};if(labels[baseKey])return labels[baseKey];if(baseKey&&baseKey.startsWith("culture:"))return"文史 / "+baseKey.slice(8);if(baseKey&&baseKey.startsWith("tool:"))return"工具 / "+baseKey.slice(5);return baseKey||"任务"}
function jobKindForBase(baseKey){if(!baseKey)return"";if(baseKey.startsWith("culture:"))return"culture";if(baseKey.startsWith("research:"))return"research";if(baseKey.startsWith("science:"))return"science";if(baseKey==="clip"||baseKey==="bgm")return"clip";if(baseKey.startsWith("tool:"))return"tool";return baseKey}
function selectedJob(){return jobsById[selectedJobId]||null}
function latestJobForKind(kind){const items=Object.values(jobsById).filter(j=>!kind||j.kind===kind).sort((a,b)=>(b.started_at||0)-(a.started_at||0));return items[0]||null}
function renderJobs(){
  const box=byId("jobs_list");if(!box)return;
  if(!box.dataset.bound){box.dataset.bound="1";box.addEventListener("click",e=>{const btn=e.target.closest("[data-job-action]");const row=e.target.closest(".job-row");if(!row)return;const id=row.dataset.jobId;if(btn){e.stopPropagation();if(btn.dataset.jobAction==="stop")stopJob(id);else viewJob(id);return}viewJob(id)})}
  const items=Object.values(jobsById).sort((a,b)=>(b.started_at||0)-(a.started_at||0)).slice(0,24);
  if(!items.length){box.textContent="暂无运行任务";return}
  box.innerHTML=items.map(j=>{const active=j.id===selectedJobId;const status=jobStatusText(j);const when=j.started_at?new Date(j.started_at).toLocaleTimeString():"";const cmd=Array.isArray(j.cmd)?j.cmd.join(" "):"";return '<div class="job-row '+(active?'active':'')+'" data-job-id="'+esc(j.id)+'"><div><div class="job-title">'+esc(j.label||j.id)+' ｜ '+esc(status)+'</div><div class="job-meta">'+esc([when,j.id,cmd].filter(Boolean).join(" ｜ "))+'</div></div><div class="job-actions"><button class="secondary" data-job-action="view">查看</button><button class="danger" data-job-action="stop">停止</button></div></div>'}).join("");
}
function rememberJob(id,baseKey,payload,data){jobsById[id]={id,label:jobBaseLabel(baseKey),base_key:baseKey,kind:jobKindForBase(baseKey),mode:payload.mode||"",action:payload.action||payload.stage||"",status:"starting",exit_code:null,cmd:data.cmd||[],started_at:Date.now(),updated_at:Date.now()};selectedJobId=id;saveJobs();renderJobs()}
function schedulePoll(id){if(!id||pollHandles[id])return;pollHandles[id]=setTimeout(()=>{pollHandles[id]=0;poll(id)},1000)}
function refreshAllJobs(){const ids=Object.keys(jobsById);if(!ids.length){setStatus("暂无运行任务");return}for(const id of ids)poll(id)}
function applyMinimaxProvider(){const provider=fieldValue("minimax_provider");if(provider==="official"&&!fieldValue("minimax_base_url"))setField("minimax_provider","fast");if(!fieldValue("minimax_base_url")||fieldValue("minimax_base_url")==="https://api.minimaxi.com/v1")setField("minimax_base_url","https://api.53hk.cn");if(!fieldValue("minimax_tts_model")||fieldValue("minimax_tts_model")==="MiniMax-M2.7")setField("minimax_tts_model","speech-2.8-hd");if(!fieldValue("minimax_bgm_model")||fieldValue("minimax_bgm_model")==="MiniMax-M2.7"||fieldValue("minimax_bgm_model")==="music-2.6-free")setField("minimax_bgm_model","music-2.6")}
function collect(){const ids=["culture_book","culture_out_dir","culture_continue_folder","research_out_dir","research_days","research_max_articles","research_issue_count","research_journals","research_article_list","minimax_provider","minimax_base_url","minimax_api_key","minimax_tts_model","minimax_bgm_model","minimax_voice_id","minimax_bgm_prompt","smtp_password","auto_clip_image_dir","auto_clip_lrc_dir","auto_clip_output_dir","auto_clip_bgm","auto_clip_bgm_library_dir","email_recipient","smtp_host","smtp_port","smtp_user","smtp_sender"];const p={};for(const id of ids){if(byId(id))p[id]=fieldValue(id)}p.email_enabled=!!(byId("email_enabled")&&byId("email_enabled").checked);p.research_skip_medical_related=!!(byId("research_skip_medical_related")&&byId("research_skip_medical_related").checked);return p}
function renderBgmLibrary(library){const sel=byId("auto_clip_bgm_select");if(!sel)return;const current=fieldValue("auto_clip_bgm");const items=(library&&library.items)||[];sel.innerHTML='<option value="">不使用背景音乐</option>'+items.map(x=>'<option value="'+esc(x.path)+'">'+esc(x.name)+'</option>').join("");if(current){sel.value=current}if(library&&library.path&&!fieldValue("auto_clip_bgm_library_dir"))setField("auto_clip_bgm_library_dir",library.path)}
function selectBgmFromLibrary(){setField("auto_clip_bgm",fieldValue("auto_clip_bgm_select"))}
async function refreshBgmLibrary(){const url="/api/bgm_library?path="+encodeURIComponent(fieldValue("auto_clip_bgm_library_dir"));const r=await fetch(url);const data=await r.json();renderBgmLibrary(data.bgm_library||{});setStatus(data.ok?"音乐库已刷新":"音乐库读取失败")}
async function loadSettings(){const r=await fetch("/api/settings");const data=await r.json();const merged={...(data.models||{}),...(data.settings||{})};for(const [k,v] of Object.entries(merged)){if(k==="email_enabled"&&byId("email_enabled"))byId("email_enabled").checked=String(v).toLowerCase()==="true";else if(k==="research_skip_medical_related"&&byId("research_skip_medical_related"))byId("research_skip_medical_related").checked=String(v).toLowerCase()==="true";else setField(k,v)}if(!fieldValue("minimax_provider"))setField("minimax_provider",fieldValue("minimax_base_url")==="https://api.53hk.cn"?"fast":"official");renderBgmLibrary(data.bgm_library||{});renderCultureWorkspace()}
async function saveSettings(){const r=await fetch("/api/settings",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(collect())});const data=await r.json();setField("smtp_password","");setField("minimax_api_key","");setStatus(data.ok?"设置已保存":"保存失败");return data}
async function start(payload,baseKey){const saved=await saveSettings();if(saved&&!saved.ok)return;const r=await fetch("/api/start",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});const data=await r.json();if(!r.ok||data.ok===false||!data.job_id){setStatus(data.error||"任务未启动");if(byId("log"))byId("log").textContent=data.error||"任务未启动";return}rememberJob(data.job_id,baseKey,payload,data);byId("cmd").textContent="";setStatus((data.message||"任务已开始处理")+"："+jobBaseLabel(baseKey));byId("log").textContent="任务已创建，正在读取后台日志...";poll(data.job_id)}
function startCulture(test){const stage=fieldValue("culture_stage")||"outline";start({...collect(),mode:"culture",stage,test_b_image_limit:test?1:Number(fieldValue("culture_test_b")||0)},test?"culture:test_b":"culture:"+stage)}
function startResearch(action){const p=collect();if(p.email_enabled&&!p.email_recipient){setStatus("请先填写收件邮箱，或取消邮件发送");showPanel("more");return}start({...p,mode:"research",action},"research:"+action)}
function startClip(){start({...collect(),mode:"auto_clip"},"clip")}
function startBgm(){start({...collect(),mode:"bgm"},"bgm")}
function startTool(action){start({...collect(),mode:"tool",action},"tool:"+action)}
function outputPathFor(kind){
  if(kind==="culture")return fieldValue("culture_out_dir");
  if(kind==="research")return fieldValue("research_out_dir")||"D:/Quanlan/全澜脑科学视频号/科研速递";
  if(kind==="science")return fieldValue("science_out_dir")||"D:/Quanlan/全澜脑科学视频号/神经科学经典";
  if(kind==="clip")return fieldValue("auto_clip_output_dir")||fieldValue("auto_clip_image_dir");
  const active=["culture","digest","science","clip"].find(n=>{const p=byId("panel"+cap(n));return p&&p.classList.contains("active")});
  if(active==="culture")return outputPathFor("culture");
  if(active==="digest")return outputPathFor("research");
  if(active==="science")return outputPathFor("science");
  if(active==="clip")return outputPathFor("clip");
  return fieldValue("research_out_dir")||fieldValue("culture_out_dir")||fieldValue("auto_clip_output_dir")||"D:/Quanlan/全澜脑科学视频号/科研速递";
}
async function openOutputFolder(kind){
  const job=latestJobForKind(kind==="research"?"research":kind==="science"?"science":kind==="culture"?"culture":kind==="clip"?"clip":"");
  const payload={job_id:job?job.id:"",path:outputPathFor(kind)};
  const r=await fetch("/api/open_output_folder",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
  const data=await r.json();
  setStatus(data.ok?"作品文件夹已打开":(data.message||"没有可打开的作品文件夹"));
}
async function clearOutputFolder(kind){
  const target=outputPathFor(kind);
  if(!target){setStatus("没有可清空的作品文件夹");return}
  if(!confirm("确认清空这个作品文件夹里的内容？\\n"+target))return;
  const r=await fetch("/api/clear_output_folder",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({path:target})});
  const data=await r.json();
  setStatus(data.ok?"作品文件夹已清空":(data.message||"清空失败"));
}
function esc(s){return String(s||"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;")}
function renderArticleList(data){
  byId("article_total").textContent=data.total??0;byId("article_done").textContent=data.done??0;byId("article_todo").textContent=data.todo??0;
  byId("article_list_status").textContent=data.ok?("清单："+(data.article_list_path||"")+" ｜ 进度："+(data.progress_path||"未生成")):(data.error||"读取失败");
  const rows=data.items||[];
  const html=['<div class="list-row header"><div>状态</div><div>PMID</div><div>文献</div><div>用于期数</div></div>'].concat(rows.map(x=>'<div class="list-row"><div><span class="tag '+(x.status==="done"?"done":"todo")+'">'+(x.status==="done"?"已做":"未做")+'</span></div><div>'+esc(x.pmid||"-")+'</div><div><div class="paper-title">'+esc(x.title||"未命名文献")+'</div><div class="paper-meta">'+esc([x.journal,x.pub_date].filter(Boolean).join(" ｜ "))+'</div></div><div>'+esc(x.issue||x.used_date||"-")+'</div></div>')).join("");
  byId("article_list_rows").innerHTML=html;
}
function renderCultureWorkspace(){
  byId("workspace_title").textContent="文史解读工作台";
  byId("workspace_hint").textContent="当前文史素材的书籍、输出、阶段和质检状态集中在这里。";
  byId("workspace_refresh").textContent="刷新文史";
  byId("workspace_refresh").onclick=renderCultureWorkspace;
  const book=fieldValue("culture_book");
  const out=fieldValue("culture_out_dir");
  const cont=fieldValue("culture_continue_folder");
  const stage=fieldValue("culture_stage")||"outline";
  const bLimit=Number(fieldValue("culture_test_b")||0)||1;
  byId("article_total").textContent=stage;
  byId("article_done").textContent=bLimit;
  byId("article_todo").textContent=out?"已设置":"待设置";
  byId("stat_done_label").textContent="B图额度";
  byId("stat_todo_label").textContent="输出目录";
  byId("article_list_status").textContent="书籍："+(book||"未设置")+" ｜ 输出："+(out||"未设置")+" ｜ 继续："+(cont||"新任务");
  const rows=[
    ["书籍来源",book||"未设置","文史 PDF / 章节素材入口",""],
    ["输出目录",out||"未设置","样例、脚本、配图和拆分素材会落到这里",""],
    ["继续目录",cont||"新任务","断点续做时读取已有分集目录",""],
    ["启动阶段",stage,"outline / script / images / postprocess / split_assets",""],
    ["测试 B 图",String(bLimit),"快速验证提示词、生图、后处理和成品链路",""],
  ];
  byId("article_list_rows").innerHTML='<div class="list-row header"><div>项目</div><div>当前值</div><div>用途</div><div>状态</div></div>'+rows.map(x=>'<div class="list-row"><div><span class="tag '+(x[1]==="未设置"?"todo":"done")+'">'+esc(x[0])+'</span></div><div>'+esc(x[1])+'</div><div>'+esc(x[2])+'</div><div>'+esc(x[3])+'</div></div>').join("");
}
function renderModeWorkspace(name){
  if(name==="clip"){
    byId("workspace_title").textContent="剪辑与音乐素材";
    byId("workspace_hint").textContent="当前图片、字幕、音频和 BGM 输出位置。";
    byId("workspace_refresh").textContent="刷新音乐库";
    byId("workspace_refresh").onclick=refreshBgmLibrary;
    byId("article_total").textContent=fieldValue("minimax_tts_model")||"-";
    byId("article_done").textContent=fieldValue("minimax_bgm_model")||"-";
    byId("article_todo").textContent=fieldValue("auto_clip_output_dir")?"已设置":"待设置";
    byId("stat_done_label").textContent="BGM";
    byId("stat_todo_label").textContent="输出";
    byId("article_list_status").textContent="图片："+(fieldValue("auto_clip_image_dir")||"未设置")+" ｜ LRC："+(fieldValue("auto_clip_lrc_dir")||"未设置");
    byId("article_list_rows").innerHTML="";
  }
}
async function loadArticleList(){
  byId("workspace_title").textContent="文献清单";byId("workspace_hint").textContent="查看当前有哪些文献、哪些已做、用在了哪几期。";byId("workspace_refresh").textContent="刷新清单";byId("workspace_refresh").onclick=loadArticleList;byId("stat_done_label").textContent="已做";byId("stat_todo_label").textContent="未做";
  setStatus("正在读取文献清单...");
  const url="/api/research_article_list?path="+encodeURIComponent(fieldValue("research_article_list"));
  const r=await fetch(url);const data=await r.json();renderArticleList(data);setStatus(data.ok?"文献清单已更新":"文献清单读取失败");
}
function renderScienceToc(data){
  if(data.pdf_path)setField("science_pdf_path",data.pdf_path);
  if(data.out_dir)setField("science_out_dir",data.out_dir);
  scienceToc=(data.toc||[]).map((x,i)=>({...x,index:Number(x.index??i),selected:!!x.selected,scriptable:x.scriptable!==false}));
  byId("workspace_title").textContent="科学经典目录";
  byId("workspace_hint").textContent="选择要创作的章节；开始创作和测试 B 图都会使用这里的勾选。";
  byId("workspace_refresh").textContent="刷新目录";
  byId("workspace_refresh").onclick=()=>loadScienceToc(true);
  byId("article_total").textContent=data.total??scienceToc.length;
  byId("article_done").textContent=data.selected??scienceToc.filter(x=>x.selected).length;
  byId("article_todo").textContent=data.scriptable??scienceToc.filter(x=>x.scriptable).length;
  byId("stat_done_label").textContent="已选";
  byId("stat_todo_label").textContent="可处理";
  byId("article_list_status").textContent=data.ok?("PDF："+(data.pdf_path||"未设置")+" ｜ 输出："+(data.out_dir||"未设置")):(data.error||"目录读取失败");
  const rows=scienceToc.map(x=>{
    const pad=Math.max(0,Number(x.level||1)-1)*16;
    const disabled=x.scriptable?"":" disabled";
    const cls=x.selected?"done":"todo";
    const label=x.selected?"已选":(x.scriptable?"可选":"跳过");
    return '<div class="list-row"><div class="checkbox-cell"><input type="checkbox" data-science-index="'+x.index+'" '+(x.selected?'checked ':'')+disabled+' onchange="toggleScienceChapter(this)"><span class="tag '+cls+'">'+label+'</span></div><div>'+esc(x.page||"-")+'</div><div><div class="paper-title" style="padding-left:'+pad+'px">'+esc(x.title||"未命名章节")+'</div><div class="paper-meta">'+esc("层级 "+(x.level||1))+'</div></div><div>'+esc(x.parsed?"已解析":"")+'</div></div>';
  }).join("");
  byId("article_list_rows").innerHTML='<div class="list-row header"><div>选择</div><div>页码</div><div>章节</div><div>状态</div></div>'+rows;
}
async function saveScienceState(){
  const payload={pdf_path:fieldValue("science_pdf_path"),out_dir:fieldValue("science_out_dir"),toc:scienceToc};
  const r=await fetch("/api/science_state",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
  const data=await r.json();
  renderScienceToc(data);
  return data;
}
async function loadScienceToc(extract){
  const path=fieldValue("science_pdf_path"),out=fieldValue("science_out_dir");
  if(path||out)await fetch("/api/science_state",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({pdf_path:path,out_dir:out,toc:scienceToc})});
  const r=await fetch("/api/science_state?extract="+(extract?"1":"0"));
  const data=await r.json();
  renderScienceToc(data);
  setStatus(data.ok?(extract?"目录已刷新":"科学经典设置已读取"):(data.error||"科学经典设置读取失败"));
}
async function toggleScienceChapter(el){
  const idx=Number(el.getAttribute("data-science-index"));
  for(const item of scienceToc){if(Number(item.index)===idx)item.selected=!!el.checked}
  await saveScienceState();
}
async function selectScienceAll(flag){
  scienceToc=scienceToc.map(x=>({...x,selected:!!flag&&x.scriptable}));
  await saveScienceState();
}
async function startScience(test){
  const data=await saveScienceState();
  if(!data.pdf_path){setStatus("请先设置科学经典 PDF");return}
  if(!data.selected){setStatus("请先在右侧选择至少一个章节");return}
  start({...collect(),mode:"tool",action:test?"science_test_b":"science",science_pdf_path:data.pdf_path,science_out_dir:data.out_dir},test?"science:test_b":"science:run");
}
async function viewJob(id){if(!id||!jobsById[id]){setStatus("没有可查看的任务");return}selectedJobId=id;saveJobs();renderJobs();await poll(id)}
async function stopJob(id){const target=id||selectedJobId;if(!target||!jobsById[target]){setStatus("当前没有选中的运行任务");return}await fetch("/api/stop?id="+encodeURIComponent(target),{method:"POST"});jobsById[target].status="stopping";jobsById[target].updated_at=Date.now();saveJobs();renderJobs();setStatus("停止请求已发送："+(jobsById[target].label||target));poll(target)}
async function poll(id){const target=id||selectedJobId;if(!target||!jobsById[target])return;const r=await fetch("/api/job?id="+encodeURIComponent(target));const data=await r.json();const job=jobsById[target];job.status=data.status||"missing";job.exit_code=data.exit_code??null;job.updated_at=Date.now();saveJobs();renderJobs();const msg=(job.label||target)+" ｜ "+jobStatusText(data);if(target===selectedJobId){byId("status").textContent=msg;if(byId("job_status"))byId("job_status").textContent=msg;byId("log").textContent=(data.lines||[]).join("")||"暂无日志"}if(isLiveStatus(data.status))schedulePoll(target);else if(job.base_key==="bgm")refreshBgmLibrary()}
loadSettings().then(()=>{const hash=location.hash.replace("#","");showPanel(["culture","digest","science","clip","more"].includes(hash)?hash:"culture");renderJobs();if(selectedJobId&&jobsById[selectedJobId])poll(selectedJobId);refreshAllJobs()});
</script>
</body>
</html>""".encode("utf-8")


def _assistant_html_v2() -> bytes:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>大模型连接库</title>
  <style>
    :root{font-family:Arial,"Microsoft YaHei",sans-serif;color:#1f2937;background:#f5f7fb;--brand:#1769aa;--line:#d7dce2;--muted:#607080;--soft:#f7f9fc;--ok:#16833a;--bad:#b3261e}
    *{box-sizing:border-box}body{margin:0}.shell{display:grid;grid-template-columns:420px 1fr;min-height:100vh}
    aside{background:#fff;border-right:1px solid var(--line);padding:16px;overflow:auto}main{padding:16px;min-width:0}
    h1{font-size:20px;margin:0 0 6px}h2{font-size:16px;margin:14px 0 8px}h3{font-size:14px;margin:0}
    .boss-home{position:fixed;right:18px;bottom:18px;z-index:50;display:inline-flex;align-items:center;min-height:42px;padding:0 16px;border-radius:999px;background:#111827;color:#fff;font-weight:700;text-decoration:none;box-shadow:0 10px 28px rgba(15,23,42,.24)}
    .hint,.desc{font-size:12px;color:var(--muted);line-height:1.5}.desc{margin:4px 0 10px}
    .tabs{display:grid;grid-template-columns:repeat(5,1fr);gap:6px;margin:14px 0}.tabs button{background:#e8eef5;color:#263238}.tabs button.active{background:var(--brand);color:#fff}
    .panel{display:none}.panel.active{display:block}.section{border-top:1px solid var(--line);padding-top:12px;margin-top:12px}.section.soft{background:var(--soft);border:1px solid var(--line);border-radius:8px;padding:12px}
    .section-title{display:flex;justify-content:space-between;gap:10px;align-items:flex-end;margin-bottom:8px}.section-title span{font-size:12px;color:var(--muted)}
    .grid2{display:grid;grid-template-columns:1fr 1fr;gap:10px}.grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}
    label{display:block;font-size:12px;margin:8px 0 4px;color:#4f5b67}input,select{width:100%;padding:8px;border:1px solid #c8d0d8;border-radius:6px;background:#fff}
    button{padding:8px 10px;border:0;border-radius:6px;background:var(--brand);color:#fff;cursor:pointer}button.secondary{background:#5f6368}button.danger{background:var(--bad)}button.ghost{background:#eef2f6;color:#263238}
    .row{display:flex;gap:8px;margin-top:12px;flex-wrap:wrap}.scheme-card{border:1px solid var(--line);border-radius:8px;background:#fff;padding:12px}.scheme-card b{display:block;margin-bottom:6px}
    .route-summary,.connection-library,.step-flow,.model-library{display:grid;gap:8px}.route-item,.connection-card,.step-card,.model-group{border:1px solid var(--line);border-radius:8px;background:#fff;padding:10px;font-size:12px}.route-item b,.connection-card b,.step-card b,.model-group b{display:block;margin-bottom:4px}.route-item span,.connection-card span,.step-card span,.model-group span{display:block;color:var(--muted);word-break:break-all}
    .connection-card.active{border-color:var(--brand);box-shadow:0 0 0 2px rgba(23,105,170,.12)}.connection-head{display:flex;justify-content:space-between;gap:8px;align-items:flex-start}.badge{display:inline-flex;align-items:center;min-height:20px;padding:0 7px;border-radius:999px;background:#eef2f6;color:#334155;font-weight:700;font-size:11px}.badge.ok{background:#ecfdf3;color:#027a48}.badge.bad{background:#fff1f2;color:#b3261e}
    .model-chip,.candidate-chip{display:block;border:1px solid #cfd7df;border-radius:8px;background:#f8fafc;padding:8px;margin-top:6px;cursor:grab}.model-chip:active,.candidate-chip:active{cursor:grabbing}.candidate-list{min-height:44px;border:1px dashed #b8c3ce;border-radius:8px;background:#fbfdff;padding:6px;margin-top:8px}.candidate-list.drag-over{border-color:var(--brand);background:#eef7ff}.candidate-chip{background:#fff}.candidate-chip .row{margin-top:6px}.empty-drop{color:var(--muted);font-size:12px;padding:7px}
    dialog{border:0;border-radius:8px;padding:0;width:min(560px,calc(100vw - 28px));box-shadow:0 24px 80px rgba(15,23,42,.28)}dialog::backdrop{background:rgba(15,23,42,.36)}.dialog-body{padding:16px}.dialog-head{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;border-bottom:1px solid var(--line);padding:14px 16px}.dialog-head h3{margin:0}.xbtn{background:#eef2f6;color:#263238;border-radius:999px;min-width:34px}
    .status{font-size:13px;color:var(--brand);margin:8px 0;word-break:break-all}.ok{color:var(--ok);font-weight:700}.missing{color:var(--bad);font-weight:700}
    pre{white-space:pre-wrap;background:#111827;color:#e5e7eb;border-radius:8px;padding:14px;min-height:72vh;overflow:auto}.cmd{font-size:12px;color:var(--muted);word-break:break-all}
    @media(max-width:900px){.shell{grid-template-columns:1fr}.grid2,.grid3{grid-template-columns:1fr}aside{border-right:0;border-bottom:1px solid var(--line)}}
  </style>
</head>
<body>
<a class="boss-home" href="/">返回控制台首页</a>
<div class="shell">
  <aside>
    <h1>大模型连接库</h1>
    <p class="hint">不再人工选择整套大模型方案；这里按模型类别维护连接库，任务启动时会自动从每类可用连接中组合执行。网页与日志不回显明文 Key。</p>

    <section id="panelModel" class="panel active">
      <div class="section soft">
        <div class="section-title"><h3>连接库操作</h3><span id="model_library_status">读取中</span></div>
        <div class="row"><button onclick="openConnectionDialog()">添加连接</button><button class="secondary" onclick="applyModelConfigToAllProjects()">一键应用到所有项目并检测</button><button class="secondary" onclick="testAllModels()">一键测试及修复</button><button class="ghost" onclick="loadSettings()">刷新连接库</button></div>
      </div>
      <div class="section">
        <div class="section-title"><h3>自动组合摘要</h3><span id="route_profile_name">未选择</span></div>
        <div class="route-summary" id="model_route_summary"></div>
        <div class="row"><button class="ghost" onclick="testModel('openai')">测 GPT</button><button class="ghost" onclick="testModel('gpt_pro')">测 GPT-Pro</button><button class="ghost" onclick="testModel('deepseek')">测 DeepSeek 润色</button><button class="ghost" onclick="testModel('image')">测 gpt-image-2</button><button class="ghost" onclick="testModel('minimax')">测 MiniMax</button></div>
      </div>
      <div class="section">
        <div class="section-title"><h3>步骤流程</h3><span>把右侧模型拖到步骤里作为候选</span></div>
        <div class="step-flow" id="model_step_flow"></div>
      </div>
    </section>


  </aside>
  <main>
    <div class="status" id="status">等待操作</div>
    <div class="section-title"><h3>模型库</h3><span>按供应商和模型名称分类，可拖动到左侧步骤</span></div>
    <div class="model-library" id="model_connection_library"></div>
    <pre id="log">暂无日志</pre>
  </main>
</div>
<dialog id="connection_dialog">
  <div class="dialog-head"><div><h3>添加大模型连接</h3><p class="desc">填写连接参数和模型名，保存后会加入相应模型类别作为备选方案。</p></div><button class="xbtn" onclick="closeConnectionDialog()">×</button></div>
  <div class="dialog-body">
    <div class="grid2">
      <div><label>模型类别</label><select id="conn_role"><option value="text">GPT / 文本</option><option value="gpt_pro">GPT-Pro / 备用文本</option><option value="polish">DeepSeek / 润色</option><option value="image">gpt-image-2 / 生图</option><option value="minimax">MiniMax / 配音 BGM</option></select></div>
      <div><label>连接名称</label><input id="conn_name" placeholder="例如 DST 文本 / FHL 生图"></div>
      <div><label>Base URL</label><input id="conn_base_url" placeholder="https://example.com/v1"></div>
      <div><label>模型名</label><input id="conn_model" placeholder="gpt-5.5 / deepseek-chat / gpt-image-2"></div>
    </div>
    <label>Key（可选，保存后清空且不回显）</label><input id="conn_api_key" type="password" autocomplete="off" placeholder="粘贴这个连接对应的 Key">
    <div class="row"><button onclick="saveModelConnection()">保存到连接库</button><button class="secondary" onclick="closeConnectionDialog()">取消</button></div>
  </div>
</dialog>
<script>
let currentJob="";
const defaultForeignBaseUrl="https://api.dstopology.com/v1";
const defaultDeepseekBaseUrl="https://api.deepseek.com";
const defaultMiniMaxBaseUrl="https://api.53hk.cn";
let modelProfiles={active_profile:"",profiles:[]};
let modelConnectionLibrary={roles:{},active_connections:{},connections:[],grouped:{}};
let editingConnectionId="";
function byId(id){return document.getElementById(id)}
function cap(s){return s[0].toUpperCase()+s.slice(1)}
function escapeHtml(s){return String(s||"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]))}
function escapeAttr(s){return escapeHtml(s)}
function setStatus(message){const el=byId("status");if(el)el.textContent=message}
function appendLogLine(message){const el=byId("log");if(!el)return;const now=new Date().toLocaleTimeString();const current=el.textContent==="暂无日志"?"":el.textContent;el.textContent=(current+"["+now+"] "+message+"\\n").split("\\n").slice(-1000).join("\\n");el.scrollTop=el.scrollHeight}
function clearLog(){const el=byId("log");if(el)el.textContent=""}
function showPanel(name){for(const n of ["culture","research","clip","model","more"]){const p=byId("panel"+cap(n)),t=byId("tab"+cap(n));if(p)p.classList.toggle("active",n===name);if(t)t.classList.toggle("active",n===name)}}
function fieldValue(id){const el=byId(id);return el?String(el.value||""):""}
function setField(id,value){const el=byId(id);if(el)el.value=value||""}
function selectedProfileId(){return ""}
function clearSecretInputs(){for(const id of ["openai_api_key","image_api_key","gpt_pro_api_key","deepseek_api_key","minimax_api_key","smtp_password"]){setField(id,"")}}
function syncModelMirrorFields(){
  const gpt=fieldValue("gpt_base_url")||defaultForeignBaseUrl;
  const deepseek=fieldValue("deepseek_base_url")||defaultDeepseekBaseUrl;
  const img=fieldValue("gpt_image_base_url")||gpt;
  if(!fieldValue("text_engine"))setField("text_engine",fieldValue("culture_text_model")||"gpt-5.5");
  if(!fieldValue("polish_engine"))setField("polish_engine",fieldValue("culture_polish_model")||"gpt-5.5");
  if(!fieldValue("image_engine"))setField("image_engine",fieldValue("culture_image_model")||"gpt-image-2");
  return {
    foreign_base_url:gpt,deepseek_base_url:deepseek,gpt_base_url:gpt,gpt_pro_base_url:fieldValue("gpt_pro_base_url"),gpt_image_base_url:img,
    culture_text_base_url:gpt,culture_polish_base_url:deepseek,culture_image_base_url:img,
    research_text_base_url:gpt,research_polish_base_url:deepseek,research_image_base_url:img,
    text_engine:fieldValue("text_engine")||fieldValue("culture_text_model")||"gpt-5.5",
    polish_engine:fieldValue("polish_engine")||fieldValue("culture_polish_model")||"gpt-5.5",
    image_engine:fieldValue("image_engine")||fieldValue("culture_image_model")||"gpt-image-2"
  };
}
function collect(){const ids=["culture_book","culture_out_dir","culture_continue_folder","culture_text_provider","culture_text_model","culture_polish_provider","culture_polish_model","culture_image_provider","culture_image_model","research_out_dir","research_days","research_max_articles","research_journals","research_article_list","text_engine","polish_engine","image_engine","gpt_base_url","gpt_pro_base_url","gpt_image_base_url","deepseek_base_url","minimax_base_url","minimax_tts_model","minimax_bgm_model","minimax_voice_id","minimax_bgm_prompt","openai_api_key","gpt_pro_api_key","image_api_key","deepseek_api_key","minimax_api_key","smtp_password","auto_clip_image_dir","auto_clip_lrc_dir","auto_clip_output_dir","auto_clip_bgm","email_recipient","smtp_host","smtp_port","smtp_user","smtp_sender"];const p={};for(const id of ids){if(byId(id))p[id]=fieldValue(id)}return {...p,...syncModelMirrorFields()}}
function profileLabel(p){return (p&&p.name)||((p&&p.id)||"")}
function keyText(profile,key){return profile&&profile.keys&&profile.keys[key]?"已存":"未存"}
function activeConnection(role){const id=(modelConnectionLibrary.active_connections||{})[role]||"";return (modelConnectionLibrary.connections||[]).find(x=>x.id===id)||((modelConnectionLibrary.grouped||{})[role]||[])[0]||{}}
function connectionById(id){return (modelConnectionLibrary.connections||[]).find(x=>x.id===id)||{}}
function latencyText(item){return item&&item.latency_ms?item.latency_ms+" ms":(item&&item.last_tested_at?"未统计":"未测试")}
function bestCandidate(ids){return (ids||[]).map(connectionById).filter(x=>x&&x.id).sort((a,b)=>{const at=a.last_test_ok?0:1,bt=b.last_test_ok?0:1;if(at!==bt)return at-bt;const al=a.latency_ms||999999,bl=b.latency_ms||999999;if(al!==bl)return al-bl;return (a.priority||100)-(b.priority||100)})[0]||{}}
function renderConnectionLibrary(data){
  modelConnectionLibrary=data||{roles:{},active_connections:{},connections:[],grouped:{}};
  const box=byId("model_connection_library");if(!box)return;
  const groups=(modelConnectionLibrary.by_provider_model||[]).sort((a,b)=>(a.provider+a.model).localeCompare(b.provider+b.model));
  box.innerHTML=groups.map(group=>{
    const items=(group.connections||[]);
    const cards=items.map(item=>{
      const status=item.last_tested_at?(item.last_test_ok?"已测通":"测试失败"):"未测试";
      const badge='<span class="badge '+(item.last_tested_at?(item.last_test_ok?"ok":"bad"):'')+'">'+status+'</span>';
      const keyBadge='<span class="badge '+(item.key_configured?"ok":"bad")+'">Key '+(item.key_configured?"已存":"未存")+'</span>';
      return '<div class="model-chip" draggable="true" data-connection-id="'+escapeAttr(item.id)+'"><div class="connection-head"><b>'+escapeHtml(item.name||item.id)+'</b><div>'+badge+' '+keyBadge+'</div></div><span>步骤类别：'+escapeHtml((modelConnectionLibrary.roles[item.role]||{}).label||item.role)+'</span><span>URL：'+escapeHtml(item.base_url||"未设置")+'</span><span>延迟：'+escapeHtml(latencyText(item))+'</span><span>最近结果：'+escapeHtml(item.last_test_message||"")+'</span><div class="row"><button class="ghost" onclick="openConnectionDialog(\\''+escapeAttr(item.role)+'\\',\\''+escapeAttr(item.id)+'\\')">编辑</button><button class="ghost" onclick="testConnection(\\''+escapeAttr(item.id)+'\\')">测试</button><button class="danger" onclick="deleteConnection(\\''+escapeAttr(item.id)+'\\')">删除</button></div></div>';
    }).join("");
    return '<div class="model-group"><div class="section-title"><h3>'+escapeHtml(group.provider||"供应商")+'</h3><span>'+escapeHtml(group.model||"模型")+' ｜ '+items.length+' 个连接</span></div>'+cards+'</div>';
  }).join("");
  const count=(modelConnectionLibrary.connections||[]).length;
  if(byId("model_library_status"))byId("model_library_status").textContent="已读取 "+count+" 个连接";
  renderStepFlow();
  bindDragSources();
  renderRouteSummary({});
}
function renderStepFlow(){
  const box=byId("model_step_flow");if(!box)return;
  const steps=modelConnectionLibrary.steps||{}, routes=modelConnectionLibrary.step_routes||{};
  const order=["script_text","research_text","polish_text","image_generation","gpt_pro_backup","voice_bgm"];
  box.innerHTML=order.map(step=>{
    const meta=steps[step]||{}, ids=(routes[step]||[]);
    const best=bestCandidate(ids);
    const chips=ids.length?ids.map(id=>{
      const item=connectionById(id); if(!item.id)return "";
      return '<div class="candidate-chip" draggable="true" data-connection-id="'+escapeAttr(item.id)+'"><b>'+escapeHtml(item.provider)+' ｜ '+escapeHtml(item.model)+'</b><span>'+escapeHtml(item.name||item.id)+'</span><span>'+escapeHtml(item.base_url||"")+'</span><span>延迟：'+escapeHtml(latencyText(item))+'</span><div class="row"><button class="ghost" onclick="testConnection(\\''+escapeAttr(item.id)+'\\')">测试</button><button class="danger" onclick="removeStepCandidate(\\''+escapeAttr(step)+'\\',\\''+escapeAttr(item.id)+'\\')">移除</button></div></div>';
    }).join(""):'<div class="empty-drop">拖入模型连接作为候选</div>';
    const roleLabel=(meta.roles||[meta.role||"text"]).map(r=>(modelConnectionLibrary.roles[r]||{}).label||r).join(" / ");
    return '<div class="step-card"><div class="connection-head"><b>'+escapeHtml(meta.label||step)+'</b><span class="badge">'+escapeHtml(roleLabel)+'</span></div><span>当前会选：'+escapeHtml(best.id?((best.provider||"")+" ｜ "+(best.model||"")+" ｜ "+latencyText(best)):"暂无候选")+'</span><div class="candidate-list" data-step="'+escapeAttr(step)+'" data-role="'+escapeAttr(meta.role||"text")+'">'+chips+'</div></div>';
  }).join("");
  bindDropTargets();
}
function renderRouteSummary(profile){
  const box=byId("model_route_summary");if(!box)return;
  byId("route_profile_name").textContent="连接库自动组合";
  const models=(profile&&profile.models)||{};
  const textConn=activeConnection("text"), proConn=activeConnection("gpt_pro"), polishConn=activeConnection("polish"), imageConn=activeConnection("image"), minimaxConn=activeConnection("minimax");
  const rows=[
    ["GPT",textConn.base_url||models.gpt_base_url||fieldValue("gpt_base_url"),textConn.model||models.culture_text_model||fieldValue("culture_text_model"),textConn.key_configured?"已存":"未存"],
    ["GPT-Pro",proConn.base_url||models.gpt_pro_base_url||fieldValue("gpt_pro_base_url"),proConn.model||models.culture_text_model||fieldValue("culture_text_model")||"gpt-5.5",proConn.key_configured?"已存":"未存"],
    ["润色文本",polishConn.base_url||models.culture_polish_base_url||models.deepseek_base_url||fieldValue("gpt_base_url"),polishConn.model||models.culture_polish_model||fieldValue("culture_polish_model")||"gpt-5.5",polishConn.key_configured?"已存":"未存"],
    ["gpt-image-2",imageConn.base_url||models.gpt_image_base_url||fieldValue("gpt_image_base_url"),imageConn.model||models.culture_image_model||fieldValue("culture_image_model"),imageConn.key_configured?"已存":"未存"],
    ["MiniMax",minimaxConn.base_url||fieldValue("minimax_base_url")||defaultMiniMaxBaseUrl,minimaxConn.model||fieldValue("minimax_tts_model")||"speech-2.8-hd",minimaxConn.key_configured?"已存":"未存"]
  ];
  box.innerHTML=rows.map(([name,url,model,key])=>'<div class="route-item"><b>'+name+'</b><span>URL：'+(url||"未设置")+'</span><span>模型：'+(model||"未设置")+'</span><span>Key：'+key+'</span></div>').join("");
}
function renderModelProfiles(data){modelProfiles=data||{active_profile:"",profiles:[]}}
async function loadSettings(){
  const r=await fetch("/api/settings");const data=await r.json();const merged={...(data.settings||{}),...(data.models||{})};
  for(const [k,v] of Object.entries(merged)){setField(k,v)}
  setField("gpt_base_url",merged.gpt_base_url||merged.culture_text_base_url||merged.foreign_base_url||defaultForeignBaseUrl);
  setField("gpt_pro_base_url",merged.gpt_pro_base_url||"");
  setField("deepseek_base_url",merged.deepseek_base_url||merged.culture_polish_base_url||defaultDeepseekBaseUrl);
  setField("gpt_image_base_url",merged.gpt_image_base_url||merged.culture_image_base_url||merged.foreign_base_url||defaultForeignBaseUrl);
  setField("minimax_base_url",merged.minimax_base_url||defaultMiniMaxBaseUrl);
  renderConnectionLibrary(data.model_connection_library||{});
  renderModelProfiles(data.model_profiles||{});
}
async function saveSettings(){const r=await fetch("/api/settings",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(collect())});const data=await r.json();clearSecretInputs();if(data.model_connection_library)renderConnectionLibrary(data.model_connection_library);if(data.model_profiles)renderModelProfiles(data.model_profiles);setStatus(data.ok?"设置已保存；会同步到子项目":"保存失败");return data}
function modelTestLines(result){
  const ok=result&&result.ok;
  return [
    "【"+((result&&result.label)||"接口")+"】"+(ok?"通过":"失败"),
    "  provider: "+((result&&result.provider)||""),
    "  model: "+((result&&result.model)||"未设置"),
    "  url: "+((result&&result.endpoint)||"未设置"),
    "  mode: "+((result&&result.test_mode)||""),
    "  elapsed: "+((result&&result.elapsed_seconds)!=null?result.elapsed_seconds+"s":"未统计"),
    "  message: "+((result&&result.message)||""),
    result&&result.suggestion?("  suggestion: "+result.suggestion):""
  ].filter(Boolean);
}
function logModelTestResult(result){for(const line of modelTestLines(result)){appendLogLine(line)}}
async function testModel(provider){
  setStatus("正在测试接口："+provider);
  const payload={...collect(),provider,profile_id:selectedProfileId()};
  const r=await fetch("/api/test_model",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
  const data=await r.json();
  clearSecretInputs();
  if(data.model_profiles)renderModelProfiles(data.model_profiles);
  logModelTestResult(data.result||{provider,message:"无结果",ok:false});
  setStatus((data.result&&data.result.ok)?"接口测试通过":"接口测试失败，详情见右侧日志");
  return data.result||{};
}
function openConnectionDialog(role,id){const dlg=byId("connection_dialog");const item=(modelConnectionLibrary.connections||[]).find(x=>x.id===id)||{};editingConnectionId=item.id||"";setField("conn_role",item.role||role||"text");setField("conn_name",item.name||"");setField("conn_base_url",item.base_url||"");setField("conn_model",item.model||"");setField("conn_api_key","");if(dlg&&dlg.showModal)dlg.showModal();else if(dlg)dlg.setAttribute("open","open")}
function closeConnectionDialog(){const dlg=byId("connection_dialog");if(dlg&&dlg.close)dlg.close();else if(dlg)dlg.removeAttribute("open")}
async function saveModelConnection(){
  const payload={action:"save",connection_id:editingConnectionId,role:fieldValue("conn_role"),name:fieldValue("conn_name"),base_url:fieldValue("conn_base_url"),model:fieldValue("conn_model"),api_key:fieldValue("conn_api_key")};
  if(!payload.base_url||!payload.model){setStatus("请填写 Base URL 和模型名");return}
  const r=await fetch("/api/model_connection",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
  const data=await r.json();setField("conn_api_key","");
  if(data.ok){closeConnectionDialog();renderConnectionLibrary(data.model_connection_library||{});if(data.models){for(const [k,v] of Object.entries(data.models)){setField(k,v)}}setStatus("连接已加入连接库，并设为该类别优先备选")}else setStatus("保存连接失败："+(data.error||"unknown"));
}
async function activateConnection(role,id){
  const r=await fetch("/api/model_connection",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({action:"activate",role,connection_id:id})});
  const data=await r.json();
  if(data.ok){renderConnectionLibrary(data.model_connection_library||{});if(data.models){for(const [k,v] of Object.entries(data.models)){setField(k,v)}}setStatus("已设为该模型类别的优先连接")}else setStatus("切换连接失败："+(data.error||"unknown"));
}
function bindDragSources(){
  document.querySelectorAll(".model-chip,.candidate-chip").forEach(el=>{
    el.addEventListener("dragstart",ev=>{ev.dataTransfer.setData("text/plain",el.getAttribute("data-connection-id")||"")});
  });
}
function bindDropTargets(){
  document.querySelectorAll(".candidate-list").forEach(el=>{
    el.addEventListener("dragover",ev=>{ev.preventDefault();el.classList.add("drag-over")});
    el.addEventListener("dragleave",()=>el.classList.remove("drag-over"));
    el.addEventListener("drop",ev=>{
      ev.preventDefault();el.classList.remove("drag-over");
      const id=ev.dataTransfer.getData("text/plain");
      const step=el.getAttribute("data-step")||"";
      addStepCandidate(step,id);
    });
  });
}
async function saveStepRoute(step,ids){
  const r=await fetch("/api/model_connection",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({action:"route",step,connection_ids:ids})});
  const data=await r.json();
  if(data.ok){renderConnectionLibrary(data.model_connection_library||{});setStatus("步骤候选已保存")}else setStatus("步骤候选保存失败："+(data.error||"unknown"));
}
function addStepCandidate(step,id){
  const item=connectionById(id), meta=(modelConnectionLibrary.steps||{})[step]||{};
  if(!item.id)return;
  const allowed=meta.roles||[meta.role];
  if(!allowed.includes(item.role)){setStatus("这个模型类别不能放入该步骤");return}
  const routes=modelConnectionLibrary.step_routes||{};
  const ids=(routes[step]||[]).filter(x=>x!==id);
  ids.push(id);
  saveStepRoute(step,ids);
}
function removeStepCandidate(step,id){
  const routes=modelConnectionLibrary.step_routes||{};
  const ids=(routes[step]||[]).filter(x=>x!==id);
  saveStepRoute(step,ids);
}
async function testConnection(id){
  const item=(modelConnectionLibrary.connections||[]).find(x=>x.id===id)||{};
  setStatus("正在测试连接："+(item.name||id));
  const r=await fetch("/api/test_model",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({connection_id:id,provider:item.provider||""})});
  const data=await r.json();
  if(data.model_connection_library)renderConnectionLibrary(data.model_connection_library);
  logModelTestResult(data.result||{provider:item.provider,message:"无结果",ok:false});
  setStatus((data.result&&data.result.ok)?"连接测试通过":"连接测试失败，详情见右侧日志");
}
async function deleteConnection(id){
  const item=(modelConnectionLibrary.connections||[]).find(x=>x.id===id)||{};
  if(!confirm("删除连接："+(item.name||id)+"？"))return;
  const r=await fetch("/api/model_connection",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({action:"delete",connection_id:id})});
  const data=await r.json();
  if(data.ok){renderConnectionLibrary(data.model_connection_library||{});setStatus("连接已删除")}else setStatus("删除连接失败："+(data.error||"unknown"));
}
async function testAllModels(){
  clearLog();
  setStatus("正在按步骤测试候选模型，失败时会自动核对飞书文档...");
  appendLogLine("==== 开始按步骤测试及修复候选模型 ====");
  const r=await fetch("/api/test_step_routes_repair",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({})});
  const data=await r.json();
  clearSecretInputs();
  if(data.model_connection_library)renderConnectionLibrary(data.model_connection_library);
  if(data.model_profiles)renderModelProfiles(data.model_profiles);
  const repair=data.repair||{};
  if(repair.attempted){
    appendLogLine("发现失败步骤，正在调用全澜小猪理核对飞书模型文档");
    if(repair.error){
      appendLogLine("自动修复未完成 ｜ "+String(repair.error).replace(/\\s+/g," ").slice(0,240));
    }else{
      appendLogLine("飞书核对完成 ｜ 新增连接 "+(repair.added_count||0)+" ｜ 补入步骤候选 "+(repair.route_count||0));
      if(repair.retested)appendLogLine("已补入候选并完成复测");
    }
  }
  const summary=data.summary||[];
  let okSteps=0;
  for(const item of summary){
    if(item&&item.ok)okSteps++;
    const state=item.ok?"通过":"未通过";
    const model=item.ok?((item.passed_provider||"")+" / "+(item.passed_model||"")+" / "+(item.latency_ms||0)+" ms"):"无可用模型";
    appendLogLine((item.step_label||item.step||"步骤")+" ｜ "+state+" ｜ 通过 "+(item.passed_count||0)+"/"+(item.candidate_count||0)+" ｜ 尝试 "+(item.tested_count||0)+" ｜ "+model);
  }
  appendLogLine("==== 步骤候选测试及修复完成 ｜ 步骤通过 "+okSteps+"/"+summary.length+" ====");
  setStatus(okSteps===summary.length?"每个步骤至少 1 个模型通过":"自动修复后仍有步骤没有通过模型，详情见右侧日志");
  return summary;
}
async function applyModelConfigToAllProjects(){
  clearLog();
  setStatus("正在把当前大模型连接库应用到所有项目，并逐项检测...");
  appendLogLine("==== 开始应用公共大模型配置到所有项目 ====");
  const r=await fetch("/api/model_connection",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({action:"apply_all"})});
  const data=await r.json();
  clearSecretInputs();
  if(data.model_connection_library)renderConnectionLibrary(data.model_connection_library);
  if(data.model_profiles)renderModelProfiles(data.model_profiles);
  if(data.models){for(const [k,v] of Object.entries(data.models)){setField(k,v)}}
  for(const line of data.apply_log||[]){appendLogLine(line)}
  for(const item of data.sync_report||[]){
    const state=item.ok?"通过":"未通过";
    const detail=(item.mismatches&&item.mismatches.length)?(" ｜ "+item.mismatches.join("；")):"";
    appendLogLine((item.name||item.id)+" 配置写入检测："+state+detail);
  }
  appendLogLine("==== 公共大模型配置应用完成 ====");
  setStatus(data.apply_ok?"所有需要项目已更新并通过检测":"有项目未通过配置检测，详情见右侧日志");
  loadSettings();
  return data;
}
async function start(payload){const saved=await saveSettings();if(saved&&!saved.ok)return;const r=await fetch("/api/start",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});const data=await r.json();currentJob=data.job_id||"";byId("cmd").textContent="";setStatus(data.message||"任务已开始处理");poll()}
function startCulture(test){start({...collect(),mode:"culture",stage:fieldValue("culture_stage"),test_b_image_limit:test?1:Number(fieldValue("culture_test_b")||0)})}
function startResearch(action){start({...collect(),mode:"research",action})}
function startClip(){start({...collect(),mode:"auto_clip"})}
function startBgm(){start({...collect(),mode:"bgm"})}
function startTool(action){start({...collect(),mode:"tool",action})}
function openXiaozhuli(){window.open("/xiaozhuli/","_blank")}
async function stopJob(){if(!currentJob){setStatus("当前没有正在运行的任务");return}await fetch("/api/stop?id="+encodeURIComponent(currentJob),{method:"POST"});setStatus("停止请求已发送");poll()}
async function poll(){if(!currentJob)return;const r=await fetch("/api/job?id="+encodeURIComponent(currentJob));const data=await r.json();byId("status").textContent=jobStatusText(data);byId("log").textContent=(data.lines||[]).join("")||"暂无日志";if(["running","starting","stopping"].includes(data.status))setTimeout(poll,1000);else refreshBgmLibrary()}
for(const id of ["gpt_base_url","gpt_image_base_url","deepseek_base_url","minimax_base_url","culture_text_model","culture_polish_model","culture_image_model","text_engine","polish_engine","image_engine"]){document.addEventListener("input",e=>{if(e.target&&e.target.id===id)renderRouteSummary((modelProfiles.profiles||[]).find(x=>x.id===selectedProfileId())||{})})}
loadSettings().then(()=>showPanel("model"));
</script>
</body>
</html>""".encode("utf-8")


def _json(handler: BaseHTTPRequestHandler, data: Any, status: int = 200) -> None:
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _daily_research_progress_path(article_list_path: Path) -> Path:
    return article_list_path.with_name(article_list_path.stem + "_续做进度.json")


def _candidate_article_list_files(root: Path) -> list[Path]:
    names = ("00_文献信息.json", "00_候选文献清单.json", "article_list.json", "articles.json")
    candidates: list[Path] = []
    if root.is_dir():
        for name in names:
            path = root / name
            if path.exists():
                candidates.append(path)
        try:
            candidates.extend(p for p in root.glob("文献清单*.json") if "续做进度" not in p.name)
        except Exception:
            pass
    return sorted(candidates, key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)


def _resolve_research_article_list_path(value: str = "") -> Path | None:
    raw = str(value or "").strip().strip('"')
    candidates: list[Path] = []
    if raw:
        path = Path(raw).expanduser()
        if path.exists():
            if path.is_file():
                candidates.append(path)
            else:
                candidates.extend(_candidate_article_list_files(path))
                parent = path.parent
                if parent.exists():
                    candidates.extend(_candidate_article_list_files(parent))
    settings = _read_json(SETTINGS_FILE, {})
    saved = str(settings.get("research_article_list") or "").strip()
    if saved and saved != raw:
        saved_path = Path(saved).expanduser()
        if saved_path.exists():
            candidates.extend([saved_path] if saved_path.is_file() else _candidate_article_list_files(saved_path))
    if DAILY_RESEARCH_DEFAULT_ROOT.exists():
        candidates.extend(_candidate_article_list_files(DAILY_RESEARCH_DEFAULT_ROOT))
    for path in candidates:
        if path.exists() and path.is_file() and "续做进度" not in path.name:
            return path.resolve()
    return None


def _article_items_from_json(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = data.get("articles") or data.get("items") or data.get("papers") or data.get("article_list") or []
    else:
        items = []
    return [x for x in items if isinstance(x, dict)]


def _research_article_list_summary(value: str = "") -> dict[str, Any]:
    article_path = _resolve_research_article_list_path(value)
    if not article_path:
        return {"ok": False, "error": "未找到文献清单；请填写文献清单 JSON、清单目录或某一期输出目录。", "items": []}
    data = _read_json(article_path, [])
    items = _article_items_from_json(data)
    progress_path = _daily_research_progress_path(article_path)
    progress = _read_json(progress_path, {}) if progress_path.exists() else {}
    used = progress.get("used_pmids", {}) if isinstance(progress, dict) else {}
    used_map: dict[str, Any] = used if isinstance(used, dict) else {str(x): {} for x in used or []}
    rows: list[dict[str, Any]] = []
    used_count = 0
    for idx, item in enumerate(items, start=1):
        pmid = str(item.get("pmid") or item.get("PMID") or "").strip()
        used_info = used_map.get(pmid) if pmid else None
        done = bool(used_info)
        if done:
            used_count += 1
        if isinstance(used_info, dict):
            issue_dir = str(used_info.get("issue_dir") or "")
            used_date = str(used_info.get("date") or "")
        else:
            issue_dir = ""
            used_date = ""
        rows.append({
            "index": idx,
            "pmid": pmid,
            "title": str(item.get("title") or item.get("title_cn") or item.get("article_title") or "")[:260],
            "journal": str(item.get("journal") or "")[:120],
            "pub_date": str(item.get("pub_date") or item.get("date") or "")[:40],
            "status": "done" if done else "todo",
            "issue": Path(issue_dir).name if issue_dir else "",
            "issue_dir": issue_dir,
            "used_date": used_date,
        })
    return {
        "ok": True,
        "article_list_path": str(article_path),
        "progress_path": str(progress_path) if progress_path.exists() else "",
        "total": len(items),
        "done": used_count,
        "todo": max(0, len(items) - used_count),
        "updated_at": str(progress.get("updated_at") or "") if isinstance(progress, dict) else "",
        "items": rows,
    }


def _send_bytes(handler: BaseHTTPRequestHandler, body: bytes, content_type: str, status: int = 200) -> None:
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _mark_shared_config_changed() -> None:
    global XIAOZHULI_CONFIG_DIRTY, SHARED_CONFIG_UPDATED_AT
    XIAOZHULI_CONFIG_DIRTY = True
    SHARED_CONFIG_UPDATED_AT = time.strftime("%Y-%m-%d %H:%M:%S")


def _apply_shared_config_env(env: dict[str, str]) -> None:
    models = _models_with_url_defaults(_apply_connection_library_to_defaults())
    _sync_shared_model_config_to_projects(models)
    foreign_base = str(models.get("foreign_base_url") or DEFAULT_FOREIGN_BASE_URL)
    text_base = str(models.get("culture_text_base_url") or foreign_base)
    research_text_base = str(models.get("research_text_base_url") or text_base)
    image_base = str(models.get("research_image_base_url") or models.get("gpt_image_base_url") or models.get("culture_image_base_url") or foreign_base)
    polish_base = str(models.get("research_polish_base_url") or models.get("culture_polish_base_url") or foreign_base)
    env["FOREIGN_MODEL_BASE_URL"] = foreign_base
    env["NEWAPI_BASE_URL"] = foreign_base
    env["OPENAI_BASE_URL"] = text_base
    env["OPENAI_API_BASE"] = text_base
    env["GEMINI_BASE_URL"] = research_text_base
    env["CULTURE_TEXT_BASE_URL"] = text_base
    env["RESEARCH_TEXT_BASE_URL"] = research_text_base
    env["CULTURE_IMAGE_BASE_URL"] = str(models.get("culture_image_base_url") or image_base)
    env["RESEARCH_IMAGE_BASE_URL"] = image_base
    env["GPT_IMAGE_BASE_URL"] = image_base
    env["CULTURE_POLISH_BASE_URL"] = str(models.get("culture_polish_base_url") or polish_base)
    env["RESEARCH_POLISH_BASE_URL"] = polish_base
    env["DEEPSEEK_BASE_URL"] = str(models.get("deepseek_base_url") or DEFAULT_DEEPSEEK_BASE_URL)
    env["GPT_PRO_BASE_URL"] = str(models.get("gpt_pro_base_url") or polish_base)
    env["MINIMAX_BASE_URL"] = str(models.get("minimax_base_url") or DEFAULT_MINIMAX_BASE_URL)
    env["QUANLAN_MODEL_PROFILE"] = "连接库自动组合"
    env["QUANLAN_TEXT_MODEL"] = str(models.get("culture_text_model") or models.get("text_engine") or "")
    env["QUANLAN_IMAGE_MODEL"] = str(models.get("culture_image_model") or models.get("image_engine") or "")
    env["QUANLAN_POLISH_MODEL"] = str(models.get("culture_polish_model") or models.get("polish_engine") or "")
    env["QUANLAN_MINIMAX_MODEL"] = str(models.get("minimax_tts_model") or "speech-2.8-hd")
    env["FEISHU_CODEX_MODEL"] = str(models.get("culture_text_model") or models.get("text_engine") or env.get("FEISHU_CODEX_MODEL") or "")
    env["FEISHU_CODEX_CASUAL_MODEL"] = str(models.get("culture_text_model") or env.get("FEISHU_CODEX_CASUAL_MODEL") or "")
    env["IMAGE_MODEL"] = str(models.get("culture_image_model") or models.get("image_engine") or "")
    env["POLISH_MODEL"] = str(models.get("culture_polish_model") or models.get("polish_engine") or "")
    env["MINIMAX_MODEL"] = str(models.get("minimax_tts_model") or "speech-2.8-hd")
    for key_name, env_names in MODEL_KEY_ENV_NAMES.items():
        value, _ = _read_model_secret(key_name)
        if value:
            for env_name in env_names:
                env[env_name] = value
    minimax_value, _ = _read_model_secret("minimax_api_key")
    if minimax_value:
        env["MINIMAX_API_KEY"] = minimax_value


def _url_reachable(url: str, timeout: float = 1.2) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return 200 <= resp.status < 500
    except Exception:
        return False


def _process_running(process: subprocess.Popen[str] | None) -> bool:
    return bool(process and process.poll() is None)


def _pids_on_port(port: int) -> list[int]:
    if os.name != "nt":
        return []
    try:
        result = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=3)
    except Exception:
        return []
    pids: set[int] = set()
    marker = f":{port}"
    for line in (result.stdout or "").splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[0].upper() != "TCP" or parts[3].upper() != "LISTENING":
            continue
        if not parts[1].endswith(marker):
            continue
        try:
            pid = int(parts[-1])
        except ValueError:
            continue
        if pid and pid != os.getpid():
            pids.add(pid)
    return sorted(pids)


def _kill_pids(pids: list[int]) -> None:
    for pid in pids:
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, text=True, timeout=5)
        except Exception:
            pass


def _stop_process(process: subprocess.Popen[str] | None) -> None:
    if not _process_running(process):
        return
    process.terminate()
    try:
        process.wait(timeout=3)
    except Exception:
        try:
            process.kill()
        except Exception:
            pass


def _app_statuses() -> dict[str, Any]:
    xiaozhuli_online = _url_reachable(f"{XIAOZHULI_TARGET}/", timeout=0.6)
    eeg_online = _url_reachable(f"{EEG_ANALYSER_TARGET}/", timeout=0.6)
    xiaozhuli_managed = _process_running(XIAOZHULI_PROCESS)
    eeg_managed = _process_running(EEG_ANALYSER_PROCESS)
    xiaozhuli_sync = "待同步" if XIAOZHULI_CONFIG_DIRTY else ("已同步" if xiaozhuli_managed else "外部运行" if xiaozhuli_online else "未启动")
    if XIAOZHULI_CONFIG_DIRTY and xiaozhuli_online and not xiaozhuli_managed:
        xiaozhuli_sync = "需接管重启"
    profiles = _profile_public_status()
    active_profile = profiles.get("active_profile") or ""
    key_count = sum(1 for value in _secret_statuses().values() if isinstance(value, bool) and value)
    return {
        "shared": {
            "active_profile": active_profile,
            "configured_key_count": key_count,
            "smtp_configured": _smtp_status().get("smtp_password_configured", False),
            "updated_at": SHARED_CONFIG_UPDATED_AT,
        },
        "apps": [
            {
                "id": "assistant",
                "name": "自媒体小猪理",
                "route": "/assistant/",
                "target": "总控台内置",
                "online": True,
                "managed": True,
                "sync_state": "已同步",
                "config_scope": "模型、Key、SMTP 在总控台维护；任务页只保留业务参数。",
            },
            {
                "id": "xiaozhuli",
                "name": "全澜小猪理",
                "route": "/xiaozhuli/",
                "target": XIAOZHULI_TARGET,
                "online": xiaozhuli_online,
                "managed": xiaozhuli_managed,
                "sync_state": xiaozhuli_sync,
                "port": XIAOZHULI_PORT,
                "config_scope": "由总控台启动时注入模型 URL、模型名和 Key；内部模型配置入口隐藏。",
            },
            {
                "id": "eeg",
                "name": "脑电分析平台",
                "route": "/eeg/",
                "target": EEG_ANALYSER_TARGET,
                "online": eeg_online,
                "managed": eeg_managed,
                "sync_state": "流程平台",
                "port": EEG_ANALYSER_PORT,
                "config_scope": "入口在总控台；平台内部只展示脑电分析流程，不展示通用模型/工具配置。",
            },
        ],
    }


def _eeg_analyser_web_root() -> Path:
    explicit = os.environ.get("EEG_ANALYSER_WEB_ROOT", "").strip()
    candidates = [
        Path(explicit) if explicit else None,
        EEG_ANALYSER_ROOT / "outputs" / "eeglab-mne-release",
        EEG_ANALYSER_ROOT / "outputs" / "eeglab-mne-mvp",
        EEG_ANALYSER_ROOT / "outputs" / "eeglab-mne-dev",
    ]
    for path in candidates:
        if path and (path / "index.html").exists():
            return path
    raise FileNotFoundError(f"EEG analyser web root not found under: {EEG_ANALYSER_ROOT}")


def _ensure_eeg_analyser() -> None:
    global EEG_ANALYSER_PROCESS
    if _url_reachable(f"{EEG_ANALYSER_TARGET}/"):
        return
    if EEG_ANALYSER_PROCESS and EEG_ANALYSER_PROCESS.poll() is None:
        return
    web_root = _eeg_analyser_web_root()
    EEG_ANALYSER_PROCESS = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(EEG_ANALYSER_PORT), "--bind", "127.0.0.1"],
        cwd=str(web_root),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    time.sleep(0.8)


def _restart_eeg_analyser(*, takeover: bool = False) -> dict[str, Any]:
    global EEG_ANALYSER_PROCESS
    _stop_process(EEG_ANALYSER_PROCESS)
    EEG_ANALYSER_PROCESS = None
    if takeover:
        _kill_pids(_pids_on_port(EEG_ANALYSER_PORT))
    _ensure_eeg_analyser()
    return _app_statuses()


def _proxy_eeg_analyser(handler: BaseHTTPRequestHandler) -> None:
    _ensure_eeg_analyser()
    parsed = urllib.parse.urlparse(handler.path)
    inner_path = parsed.path[len("/eeg"):] or "/"
    if not inner_path.startswith("/"):
        inner_path = "/" + inner_path
    target = f"{EEG_ANALYSER_TARGET}{inner_path}" + (f"?{parsed.query}" if parsed.query else "")
    data = None
    headers = {"Cache-Control": "no-store"}
    if handler.command in {"POST", "PUT", "PATCH"}:
        length = int(handler.headers.get("Content-Length", "0") or 0)
        data = handler.rfile.read(length) if length else b""
        if handler.headers.get("Content-Type"):
            headers["Content-Type"] = handler.headers["Content-Type"]
    req = urllib.request.Request(target, data=data, method=handler.command, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = resp.read()
            content_type = resp.headers.get("Content-Type", "application/octet-stream")
            if content_type.startswith("text/html") or content_type.startswith("text/javascript"):
                text = body.decode("utf-8", errors="replace")
                text = text.replace("http://127.0.0.1:8765/", "/")
                body = text.encode("utf-8")
            _send_bytes(handler, body, content_type, resp.status)
    except urllib.error.HTTPError as exc:
        _send_bytes(handler, exc.read(), exc.headers.get("Content-Type", "text/plain; charset=utf-8"), exc.code)
    except urllib.error.URLError as exc:
        _send_bytes(handler, f"EEG analyser unavailable: {_safe_error(exc)}".encode("utf-8"), "text/plain; charset=utf-8", 502)


def _ensure_xiaozhuli_dashboard() -> None:
    global XIAOZHULI_PROCESS, XIAOZHULI_CONFIG_DIRTY
    if XIAOZHULI_PROCESS and XIAOZHULI_PROCESS.poll() is None and not XIAOZHULI_CONFIG_DIRTY:
        return
    if XIAOZHULI_PROCESS and XIAOZHULI_PROCESS.poll() is None and XIAOZHULI_CONFIG_DIRTY:
        _stop_process(XIAOZHULI_PROCESS)
        XIAOZHULI_PROCESS = None
    if _url_reachable(f"{XIAOZHULI_TARGET}/"):
        return
    entry = XIAOZHULI_ROOT / "xiaozhuli-dashboard.mjs"
    if not entry.exists():
        raise FileNotFoundError(f"Xiaozhuli dashboard not found: {entry}")
    env = os.environ.copy()
    _apply_shared_config_env(env)
    env.setdefault("XIAOZHULI_DASHBOARD_HOST", "127.0.0.1")
    env.setdefault("XIAOZHULI_DASHBOARD_PORT", str(XIAOZHULI_PORT))
    XIAOZHULI_PROCESS = subprocess.Popen(["node", entry.name], cwd=str(XIAOZHULI_ROOT), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)
    XIAOZHULI_CONFIG_DIRTY = False
    time.sleep(0.6)


def _restart_xiaozhuli_dashboard(*, takeover: bool = False) -> dict[str, Any]:
    global XIAOZHULI_PROCESS, XIAOZHULI_CONFIG_DIRTY
    _stop_process(XIAOZHULI_PROCESS)
    XIAOZHULI_PROCESS = None
    if takeover:
        _kill_pids(_pids_on_port(XIAOZHULI_PORT))
    XIAOZHULI_CONFIG_DIRTY = True
    _ensure_xiaozhuli_dashboard()
    return _app_statuses()


def _control_app(payload: dict[str, Any]) -> dict[str, Any]:
    app_id = str(payload.get("app") or "").strip()
    action = str(payload.get("action") or "").strip()
    takeover = bool(payload.get("takeover", True))
    if action == "status":
        return _app_statuses()
    if app_id == "xiaozhuli":
        if action in {"ensure", "start"}:
            _ensure_xiaozhuli_dashboard()
            return _app_statuses()
        if action in {"restart", "sync"}:
            return _restart_xiaozhuli_dashboard(takeover=takeover)
    if app_id == "eeg":
        if action in {"ensure", "start"}:
            _ensure_eeg_analyser()
            return _app_statuses()
        if action == "restart":
            return _restart_eeg_analyser(takeover=takeover)
    if app_id == "assistant" and action in {"ensure", "start"}:
        return _app_statuses()
    raise ValueError("unknown app action")


def _proxy_xiaozhuli(handler: BaseHTTPRequestHandler) -> None:
    _ensure_xiaozhuli_dashboard()
    parsed = urllib.parse.urlparse(handler.path)
    inner_path = parsed.path[len("/xiaozhuli"):] or "/"
    if not inner_path.startswith("/"):
        inner_path = "/" + inner_path
    if handler.command in {"POST", "PUT", "PATCH", "DELETE"} and inner_path.lower().startswith("/api/model"):
        _json(
            handler,
            {
                "ok": False,
                "saved": False,
                "centralized": True,
                "readonly": True,
                "message": SHARED_MODEL_CONFIG_GUARD_MESSAGE,
            },
            409,
        )
        return
    target = f"{XIAOZHULI_TARGET}{inner_path}" + (f"?{parsed.query}" if parsed.query else "")
    data = None
    headers = {"Cache-Control": "no-store"}
    if handler.command in {"POST", "PUT", "PATCH"}:
        length = int(handler.headers.get("Content-Length", "0") or 0)
        data = handler.rfile.read(length) if length else b""
        if handler.headers.get("Content-Type"):
            headers["Content-Type"] = handler.headers["Content-Type"]
    req = urllib.request.Request(target, data=data, method=handler.command, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = resp.read()
            content_type = resp.headers.get("Content-Type", "application/octet-stream")
            if content_type.startswith("text/html") or content_type.startswith("text/javascript"):
                text = body.decode("utf-8", errors="replace")
                text = text.replace('href="/ui/', 'href="/xiaozhuli/ui/').replace('src="/ui/', 'src="/xiaozhuli/ui/')
                text = text.replace('fetch("/api/', 'fetch("/xiaozhuli/api/').replace("fetch('/api/", "fetch('/xiaozhuli/api/")
                body = text.encode("utf-8")
            _send_bytes(handler, body, content_type, resp.status)
    except urllib.error.HTTPError as exc:
        _send_bytes(handler, exc.read(), exc.headers.get("Content-Type", "text/plain; charset=utf-8"), exc.code)


def _add(args: list[str], flag: str, value: Any) -> None:
    text = str(value or "").strip()
    if text:
        args.extend([flag, text])


def _daily_text_engine_arg(value: Any) -> str:
    text = str(value or "").strip()
    aliases = {
        "gpt-5.5": "GPT-5.5",
        "gpt-5.4": "GPT-5.4",
        "gpt-5.4-mini": "GPT-5.4 mini（快速）",
        "gpt-5.4-nano": "GPT-5.4 nano（最低成本）",
        "deepseek-chat": "DeepSeek Chat（官方润色）",
        "deepseek-reasoner": "DeepSeek Reasoner（官方）",
    }
    return aliases.get(text.lower(), text)


def _daily_image_engine_arg(value: Any) -> str:
    text = str(value or "").strip()
    aliases = {
        "gpt-image-2": "生图专用｜GPT Image 2",
        "gpt image 2": "生图专用｜GPT Image 2",
        "gemini-3-pro-image-preview": "生图专用｜Gemini 3 Pro Image Preview",
        "gemini-3.1-flash-image-preview": "生图专用｜Gemini 3.1 Flash Image Preview",
    }
    return aliases.get(text.lower(), text)


def _default_output_dir(payload: dict[str, Any]) -> str:
    mode_key = str(payload.get("mode") or "").strip()
    action = str(payload.get("action") or "").strip()
    if mode_key == "culture":
        return str(payload.get("culture_out_dir") or "").strip()
    if mode_key == "research":
        return str(payload.get("research_out_dir") or "").strip() or str(DAILY_RESEARCH_DEFAULT_ROOT)
    if mode_key == "bgm":
        return str(_bgm_library_dir(str(payload.get("auto_clip_bgm_library_dir") or "")))
    if mode_key == "auto_clip":
        return str(payload.get("auto_clip_output_dir") or payload.get("auto_clip_image_dir") or "").strip()
    if mode_key == "tool" and action in {"science", "science_test_b"}:
        return str(payload.get("science_out_dir") or "").strip() or _science_output_dir_from_settings()
    return ""


def _extract_output_dir_from_line(line: str) -> str:
    text = str(line or "").strip()
    patterns = (
        r"(?:素材已生成|输出目录|作品目录|已生成|已保存)[：:]\s*([A-Za-z]:\\[^\r\n]+)",
        r"(?:素材已生成|输出目录|作品目录|已生成|已保存)[：:]\s*(/[^\r\n]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip().strip('"')
    return ""


def _open_folder_path(value: str) -> tuple[bool, str]:
    raw = str(value or "").strip().strip('"')
    if not raw:
        return False, "还没有可打开的作品文件夹。"
    path = Path(raw).expanduser()
    if path.is_file():
        path = path.parent
    if not path.exists():
        try:
            path.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            return False, f"文件夹不存在，且无法创建：{exc}"
    try:
        if os.name == "nt":
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
        return True, str(path)
    except Exception as exc:
        return False, f"打开文件夹失败：{exc}"


def _build_command(payload: dict[str, Any]) -> tuple[list[str], Path]:
    mode_key = str(payload.get("mode") or "culture")
    if mode_key == "auto_clip":
        cmd = [sys.executable, "-m", "quanlan_dual_assistant.auto_video_editor"]
        _add(cmd, "--images", payload.get("auto_clip_image_dir"))
        _add(cmd, "--lrc", payload.get("auto_clip_lrc_dir"))
        _add(cmd, "--output", payload.get("auto_clip_output_dir"))
        _add(cmd, "--bgm", payload.get("auto_clip_bgm"))
        minimax_key, _ = _read_model_secret("minimax_api_key")
        if minimax_key or os.environ.get("MINIMAX_API_KEY"):
            cmd.append("--synthesize-voice")
            cmd.extend(["--tts-provider", "minimax"])
        if payload.get("minimax_tts_model"):
            _add(cmd, "--tts-model", payload.get("minimax_tts_model"))
        if payload.get("minimax_voice_id"):
            _add(cmd, "--minimax-voice-id", payload.get("minimax_voice_id"))
        return cmd, PROJECT_ROOT
    if mode_key == "bgm":
        cmd = [sys.executable, "-m", "quanlan_dual_assistant.auto_video_editor", "--generate-bgm"]
        _add(cmd, "--bgm-output", str(_bgm_library_dir(str(payload.get("auto_clip_bgm_library_dir") or ""))))
        _add(cmd, "--summary-root", payload.get("culture_out_dir") or payload.get("auto_clip_lrc_dir"))
        _add(cmd, "--bgm-model", payload.get("minimax_bgm_model"))
        _add(cmd, "--bgm-prompt", payload.get("minimax_bgm_prompt"))
        return cmd, PROJECT_ROOT
    if mode_key == "tool":
        action = str(payload.get("action") or "")
        if action in {"audience", "audience_apply", "audience_full_review"}:
            cmd = [sys.executable, "-m", "modes.culture.automedia_core.audience_test_bot"]
            if action == "audience_full_review":
                cmd.append("--online")
            if action == "audience_apply":
                cmd.append("--apply")
            return cmd, PROJECT_ROOT
        if action == "self_optimizer_once":
            return [sys.executable, "self_optimizer.py", "once", "--force"], PROJECT_ROOT
        if action == "self_optimizer_daemon":
            return [sys.executable, "self_optimizer.py", "daemon"], PROJECT_ROOT
        if action == "package_update":
            return [sys.executable, "tools/channel_manager.py", "--channel", "test", "package-update", "--note", "web test update"], PROJECT_ROOT
        if action == "init_release":
            return [sys.executable, "tools/channel_manager.py", "--channel", "test", "init-release"], PROJECT_ROOT
        if action == "model_help":
            return [sys.executable, "AutoMediaProducer.py", "--mode", "culture", "--cli", "--", "--help"], PROJECT_ROOT
        if action in {"science", "science_test_b"}:
            mode = get_mode("research")
            science_payload = {
                "pdf_path": payload.get("science_pdf_path"),
                "out_dir": payload.get("science_out_dir"),
                "test_b_image_limit": 1 if action == "science_test_b" else 0,
            }
            _save_science_state_payload(science_payload)
            args = ["AutoMediaProducer.py", "--science-classic-run"]
            _add(args, "--science-pdf", science_payload.get("pdf_path"))
            _add(args, "--science-out-dir", science_payload.get("out_dir"))
            if science_payload["test_b_image_limit"]:
                args.extend(["--science-test-b-image-limit", str(science_payload["test_b_image_limit"])])
            return [sys.executable, *args], mode.path
        return [sys.executable, "AutoMediaProducer.py", "--help"], PROJECT_ROOT

    mode = get_mode(mode_key)
    args: list[str] = []
    if mode.key == "culture":
        models = _models_with_url_defaults(_model_settings())

        def model_value(field: str, default: str = "") -> str:
            return str(payload.get(field) or models.get(field) or default).strip()

        text_provider = model_value("culture_text_provider", "openai")
        text_model = model_value("culture_text_model", "gpt-5.5")
        polish_provider = model_value("culture_polish_provider", "openai")
        polish_model = model_value("culture_polish_model", "gpt-5.5")
        image_provider = model_value("culture_image_provider", "openai")
        if image_provider == "image":
            image_provider = "openai"
        image_model = model_value("culture_image_model", "gpt-image-2")
        _add(args, "--book", payload.get("culture_book"))
        _add(args, "--out", payload.get("culture_out_dir"))
        _add(args, "--continue-from-folder", payload.get("culture_continue_folder"))
        _add(args, "--start-stage", payload.get("stage"))
        _add(args, "--provider", text_provider)
        _add(args, "--text-model", text_model)
        _add(args, "--outline-provider", text_provider)
        _add(args, "--outline-model", text_model)
        _add(args, "--episode-prompt-provider", text_provider)
        _add(args, "--episode-prompt-model", text_model)
        _add(args, "--script-provider", text_provider)
        _add(args, "--script-model", text_model)
        _add(args, "--polish-provider", polish_provider)
        _add(args, "--polish-model", polish_model)
        _add(args, "--image-provider", image_provider)
        _add(args, "--image-model", image_model)
        limit = int(payload.get("test_b_image_limit") or 0)
        if limit:
            args.extend(["--test-b-image-limit", str(limit)])
        if not any(flag in args for flag in ("--book", "--continue-from-folder")):
            args.append("--help")
    elif mode.key == "research":
        action = str(payload.get("action") or "digest")
        article_list_value = str(payload.get("research_article_list") or "").strip()
        if action in {"continue_list", "resume"} and not article_list_value:
            resolved_article_list = _resolve_research_article_list_path("")
            if not resolved_article_list:
                raise ValueError("未找到可续做的文献清单。请先点击“补文献清单”，或在“已有文献清单 / 续做目录”填写清单 JSON、清单目录或某一期输出目录。")
            article_list_value = str(resolved_article_list)
            payload["research_article_list"] = article_list_value
        if action == "article_list":
            args.append("--daily-build-article-list")
        elif action == "continue_list":
            args.extend(["--daily-research-digest", "--daily-continue-until-exhausted"])
        elif action == "resume":
            args.extend(["--daily-research-digest", "--daily-resume-existing"])
        else:
            args.append("--daily-research-digest")
        _add(args, "--daily-out-dir", payload.get("research_out_dir"))
        _add(args, "--daily-days", payload.get("research_days"))
        _add(args, "--daily-max-articles", payload.get("research_max_articles"))
        _add(args, "--daily-issue-count", payload.get("research_issue_count"))
        _add(args, "--daily-journals", payload.get("research_journals"))
        _add(args, "--daily-article-list", article_list_value)
        _add(args, "--daily-text-engine", _daily_text_engine_arg(payload.get("text_engine")))
        _add(args, "--daily-polish-engine", _daily_text_engine_arg(payload.get("polish_engine")))
        _add(args, "--daily-image-engine", _daily_image_engine_arg(payload.get("image_engine")))
        if str(payload.get("research_skip_medical_related") or "").lower() in {"1", "true", "yes", "on"}:
            args.append("--daily-skip-medical-related")
        if payload.get("email_enabled") and payload.get("email_recipient"):
            args.append("--daily-email")
            _add(args, "--daily-email-recipient", payload.get("email_recipient"))
    return _python_command(mode, gui=False, extra_args=args), mode.path


def _build_optimizer_command(project: str, mode: str) -> tuple[str, list[str], Path]:
    project = str(project or "").strip()
    mode = "daemon" if str(mode or "").strip() == "daemon" else "once"
    if project == "assistant":
        cmd = [sys.executable, "self_optimizer.py", "daemon" if mode == "daemon" else "once"]
        if mode == "once":
            cmd.append("--force")
        return "自媒体小猪理", cmd, PROJECT_ROOT
    if project == "xiaozhuli":
        cmd = ["node", "self-optimizer.mjs", "daemon" if mode == "daemon" else "once"]
        if mode == "once":
            cmd.append("--force")
        return "全澜小猪理", cmd, XIAOZHULI_ROOT
    if project == "eeg":
        cmd = ["node", "work/self_optimizer.js", "daemon" if mode == "daemon" else "once"]
        if mode == "once":
            cmd.append("--force")
        return "脑电分析平台", cmd, EEG_ANALYSER_ROOT
    raise ValueError("unknown optimizer project")


def _build_audience_command(project: str, mode: str = "once") -> tuple[str, list[str], Path, str]:
    project = str(project or "").strip()
    mode = str(mode or "once").strip()
    if mode == "dev_upgrade":
        if project == "assistant":
            return "自媒体小猪理", [sys.executable, "self_optimizer.py", "once", "--force", "--apply"], PROJECT_ROOT, mode
        if project == "xiaozhuli":
            return "全澜小猪理", ["node", "self-optimizer.mjs", "once", "--force"], XIAOZHULI_ROOT, mode
        if project == "eeg":
            return "脑电分析平台", ["node", "work/self_optimizer.js", "once", "--force"], EEG_ANALYSER_ROOT, mode
        raise ValueError("该项目还没有暴露开发版升级命令。")
    if mode == "release_deploy":
        if project == "assistant":
            return "自媒体小猪理", [sys.executable, "tools/channel_manager.py", "--channel", "release", "deploy-update", "--note", "web audience release deploy"], PROJECT_ROOT, mode
        if project == "xiaozhuli":
            return "全澜小猪理", ["node", "self-optimizer.mjs", "once", "--force"], XIAOZHULI_ROOT, mode
        if project == "eeg":
            return "脑电分析平台", ["powershell", "-ExecutionPolicy", "Bypass", "-File", "work/promote_release_if_idle.ps1"], EEG_ANALYSER_ROOT, mode
        raise ValueError("该项目还没有暴露发布版部署命令。")
    if project == "assistant":
        return "自媒体小猪理", [sys.executable, "-m", "modes.culture.automedia_core.audience_test_bot", "--online"], PROJECT_ROOT, "once"
    if project == "xiaozhuli":
        return "全澜小猪理", ["node", "self-optimizer.mjs", "once", "--force"], XIAOZHULI_ROOT, "once"
    if project == "eeg":
        return "脑电分析平台", ["node", "work/self_optimizer.js", "once", "--force"], EEG_ANALYSER_ROOT, "once"
    raise ValueError("该项目还没有暴露虚拟用户测试命令；已自动显示，待项目提供命令后可启动。")


def _audience_mode_label(mode: str) -> str:
    if mode == "dev_upgrade":
        return "一键升级开发版本"
    if mode == "release_deploy":
        return "一键部署发布版本"
    return "虚拟用户测试"


def _initial_job_lines(name: str, mode: str, cmd: list[str], cwd: Path) -> list[str]:
    return [
        f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 已接收任务：{name} / {_audience_mode_label(mode)}\n",
        f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 工作目录：{cwd}\n",
        f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 命令：{' '.join(cmd)}\n",
        f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 正在启动进程，请稍候...\n",
    ]


def _pending_summary(name: str, mode: str) -> dict[str, list[str]]:
    label = _audience_mode_label(mode)
    return {
        "overview": [f"{name} / {label} 已启动，正在等待虚拟用户测试结果。"],
        "suggestions": ["测试完成后，这里只展示可执行的优化建议。"],
        "expected_effects": ["测试完成后，这里展示预计优化后的点击、理解、转发或发布稳定性变化。"],
    }


def _compact_line(value: Any, limit: int = 180) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit].rstrip()


def _parse_last_json(text: str) -> dict[str, Any]:
    decoder = json.JSONDecoder()
    for match in reversed(list(re.finditer(r"\{", text))[-160:]):
        try:
            data, end = decoder.raw_decode(text[match.start():])
        except Exception:
            continue
        if isinstance(data, dict) and any(key in data for key in ("findings", "readable_log", "last_result", "idle_optimization")):
            return data
    return {}


def _effect_for_finding(finding: dict[str, Any]) -> str:
    area = str(finding.get("area") or "")
    severity = str(finding.get("severity") or "")
    if severity == "pass":
        return "预计效果：保持当前版本，不做无效改动，继续积累真实播放和评论数据。"
    if area == "opening":
        return "预计效果：前 3-8 秒更快让普通观众听懂处境，降低划走率。"
    if area == "publish_title":
        return "预计效果：标题更像具体问题或冲突，提升点击意愿和停留判断。"
    if area == "share":
        return "预计效果：转发理由更清楚，朋友圈/社群分享阻力更低。"
    if area == "comments":
        return "预计效果：置顶评论更容易引出回答，提升互动入口。"
    if area == "language":
        return "预计效果：减少空泛爆款词，提升可信度和文史内容质感。"
    if area == "postprocess":
        return "预计效果：发布前观感更稳定，减少封面/字幕/排版造成的劝退。"
    if area == "missing_material":
        return "预计效果：补齐素材后才能形成有效虚拟用户复测结论。"
    return "预计效果：把发现转成下一轮可验证的修复项，降低同类问题复发。"


def _summary_from_report(report: dict[str, Any]) -> dict[str, list[str]]:
    findings = report.get("findings") if isinstance(report.get("findings"), list) else []
    if findings:
        top = [item for item in findings if isinstance(item, dict)][:8]
        overview = [
            f"{str(item.get('severity') or '').upper()} / {item.get('area') or 'overall'}：{_compact_line(item.get('message'))}"
            for item in top
            if item.get("message")
        ]
        suggestions = list(dict.fromkeys(
            _compact_line(item.get("suggestion"), 220)
            for item in top
            if item.get("suggestion")
        ))
        expected = list(dict.fromkeys(_effect_for_finding(item) for item in top))
        return {
            "overview": overview or ["本轮虚拟用户测试未发现明确问题。"],
            "suggestions": suggestions or ["继续积累真实观众反馈后复测。"],
            "expected_effects": expected or ["维持当前版本，避免无依据调整。"],
        }
    if report.get("last_result"):
        return {
            "overview": ["自优化器已完成一轮检查，结果已写入项目状态。"],
            "suggestions": ["如需更细的虚拟用户建议，请使用“输入优化建议”补充你的观察后再复测。"],
            "expected_effects": ["下一轮会把记录的反馈纳入角色评审和修复计划。"],
        }
    return {}


def _summary_from_job(job: dict[str, Any]) -> dict[str, list[str]]:
    text = "".join(str(line) for line in job.get("lines") or [])
    report = _parse_last_json(text)
    summary = _summary_from_report(report) if report else {}
    if summary:
        return summary
    status = str(job.get("status") or "")
    if status in {"running", "starting", "stopping"}:
        return job.get("summary") or {
            "overview": ["任务正在运行，等待虚拟用户测试结果。"],
            "suggestions": ["完成后展示优化建议。"],
            "expected_effects": ["完成后展示预计效果。"],
        }
    lines = [_compact_line(line, 220) for line in text.splitlines() if re.search(r"建议|优化|效果|虚拟用户|发现|summary|recommend", line, re.I)]
    if lines:
        return {
            "overview": lines[:4],
            "suggestions": lines[4:10] or ["请查看原始日志中的详细建议。"],
            "expected_effects": ["已从日志提取关键信息；下一轮建议使用结构化虚拟用户报告复测。"],
        }
    return {
        "overview": ["本轮没有生成可提取的虚拟用户摘要。"],
        "suggestions": ["请补充人工优化建议，或查看原始日志定位测试脚本输出。"],
        "expected_effects": ["补充建议后，下一轮可形成更明确的优化目标。"],
    }


def _build_feedback_command(project: str, text: str) -> tuple[str, list[str], Path]:
    project = str(project or "").strip()
    text = str(text or "").strip()
    if not text:
        raise ValueError("优化建议不能为空。")
    if project == "assistant":
        return "自媒体小猪理", [sys.executable, "self_optimizer.py", "add-feedback", text], PROJECT_ROOT
    if project == "xiaozhuli":
        return "全澜小猪理", ["node", "self-optimizer.mjs", "add-feedback", text], XIAOZHULI_ROOT
    if project == "eeg":
        return "脑电分析平台", ["node", "work/self_optimizer.js", "add-feedback", text], EEG_ANALYSER_ROOT
    raise ValueError("未知项目，无法写入优化建议。")


def _run_job(job_id: str, cmd: list[str], cwd: Path) -> None:
    job = JOBS[job_id]
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("AMP_IMAGE_QUALITY", "low")
    env.setdefault("AMP_IMAGE_COST_MODE", "lowest")
    env.setdefault("AMP_IMAGE_MAX_RETRIES", "1")
    env.setdefault("OPENAI_IMAGE_RETRY_DELAYS", "0,8")
    env.setdefault("OPENAI_IMAGE_TIMEOUT", "240")
    models = _apply_connection_library_to_defaults()
    _sync_shared_model_config_to_projects(models)
    env["QUANLAN_MODEL_DEFAULTS_FILE"] = str(MODEL_DEFAULTS_FILE)
    env["QUANLAN_SHARED_MODEL_CONFIG_FILE"] = str(PROJECT_ROOT / ".env.quanlan-model.local.json")
    for key_name, env_names in MODEL_KEY_ENV_NAMES.items():
        value, _ = _read_model_secret(key_name)
        if value:
            for env_name in env_names:
                env[env_name] = value
    if isinstance(models, dict):
        base_url = _normalized_base_url(str(models.get("foreign_base_url") or ""), DEFAULT_FOREIGN_BASE_URL)
        text_url = _model_base_url(models, "research_text_base_url", base_url)
        image_url = _model_base_url(models, "research_image_base_url", base_url)
        env["FOREIGN_MODEL_BASE_URL"] = text_url
        env["NEWAPI_BASE_URL"] = text_url
        env["OPENAI_BASE_URL"] = text_url
        env["OPENAI_API_BASE"] = text_url
        env["CHATSHARE_API_BASE"] = text_url
        env["GPT_IMAGE_BASE_URL"] = image_url
        for field, env_name in {
            "culture_text_base_url": "CULTURE_TEXT_BASE_URL",
            "culture_polish_base_url": "CULTURE_POLISH_BASE_URL",
            "culture_image_base_url": "CULTURE_IMAGE_BASE_URL",
            "research_text_base_url": "RESEARCH_TEXT_BASE_URL",
            "research_polish_base_url": "RESEARCH_POLISH_BASE_URL",
            "research_image_base_url": "RESEARCH_IMAGE_BASE_URL",
        }.items():
            env[env_name] = _model_base_url(models, field, base_url)
        if models.get("deepseek_base_url"):
            env["DEEPSEEK_BASE_URL"] = str(models.get("deepseek_base_url") or "")
        env["GPT_PRO_BASE_URL"] = str(models.get("gpt_pro_base_url") or models.get("research_polish_base_url") or "")
        if models.get("minimax_base_url"):
            env["MINIMAX_BASE_URL"] = str(models.get("minimax_base_url") or "")
    try:
        proc = subprocess.Popen(cmd, cwd=str(cwd), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", bufsize=1)
        job["process"] = proc
        job["status"] = "running"
        job["lines"].append(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 任务已开始处理，请保持窗口开启。\n")
        assert proc.stdout is not None
        for line in proc.stdout:
            output_dir = _extract_output_dir_from_line(line)
            if output_dir:
                job["output_dir"] = output_dir
            job["lines"].append(line)
            job["lines"] = job["lines"][-1000:]
        job["exit_code"] = proc.wait()
        job["status"] = "finished"
        if job["exit_code"] == 0:
            job["lines"].append(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 任务已完成。\n")
        else:
            job["lines"].append(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 任务未完成，请查看运行日志中的具体提示。\n")
        job["summary"] = _summary_from_job(job)
    except Exception as exc:
        job["status"] = "failed"
        job["exit_code"] = -1
        job["lines"].append(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 任务失败：{type(exc).__name__}: {exc}\n")
        job["summary"] = _summary_from_job(job)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        path = urllib.parse.urlparse(self.path)
        if path.path == "/":
            body = _entry_html_v2()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path.path == "/eeg":
            self.send_response(302)
            self.send_header("Location", "/eeg/")
            self.end_headers()
            return
        if path.path.startswith("/eeg/"):
            _proxy_eeg_analyser(self)
            return
        if path.path == "/xiaozhuli":
            self.send_response(302)
            self.send_header("Location", "/xiaozhuli/")
            self.end_headers()
            return
        if path.path.startswith("/xiaozhuli/"):
            _proxy_xiaozhuli(self)
            return
        if path.path in {"/xgn", "/xgn/"}:
            self.send_response(302)
            self.send_header("Location", "/assistant/")
            self.end_headers()
            return
        if path.path == "/assistant":
            self.send_response(302)
            self.send_header("Location", "/assistant/")
            self.end_headers()
            return
        if path.path == "/assistant/":
            body = _automedia_html_v2()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path.path == "/model":
            self.send_response(302)
            self.send_header("Location", "/model/")
            self.end_headers()
            return
        if path.path == "/model/":
            body = _assistant_html_v2()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path.path == "/optimizer":
            self.send_response(302)
            self.send_header("Location", "/optimizer/")
            self.end_headers()
            return
        if path.path == "/optimizer/":
            body = _project_control_html("optimizer")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path.path == "/audience":
            self.send_response(302)
            self.send_header("Location", "/audience/")
            self.end_headers()
            return
        if path.path == "/audience/":
            body = _project_control_html("audience")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path.path == "/api/settings":
            accept = self.headers.get("Accept", "")
            if "text/html" in accept and "application/json" not in accept:
                self.send_response(302)
                self.send_header("Location", "/")
                self.end_headers()
                return
            _json(self, _public_settings())
            return
        if path.path == "/api/apps":
            _json(self, {"ok": True, **_app_statuses()})
            return
        if path.path == "/api/research_article_list":
            query = urllib.parse.parse_qs(path.query)
            _json(self, _research_article_list_summary(query.get("path", [""])[0]))
            return
        if path.path == "/api/science_state":
            query = urllib.parse.parse_qs(path.query)
            try:
                _json(self, _science_state_payload(extract=query.get("extract", ["0"])[0] in {"1", "true", "yes"}))
            except Exception as exc:
                _json(self, {"ok": False, "error": _safe_error(exc)}, 400)
            return
        if path.path == "/api/bgm_library":
            query = urllib.parse.parse_qs(path.query)
            _json(self, {"ok": True, "bgm_library": _bgm_library_summary(query.get("path", [""])[0])})
            return
        if path.path == "/api/secret":
            key = urllib.parse.parse_qs(path.query).get("key", [""])[0]
            if key == "smtp_password":
                _json(self, {"ok": True, "key": key, "email_secret": _smtp_status(include_value=True)})
                return
            if key not in MODEL_KEY_FILES:
                _json(self, {"error": "unknown key"}, 404)
                return
            _json(self, {"ok": True, "key": key, "secrets": _secret_statuses(include_values=True, only=key)})
            return
        if path.path == "/api/job":
            job_id = urllib.parse.parse_qs(path.query).get("id", [""])[0]
            job = JOBS.get(job_id)
            _json(self, {k: v for k, v in (job or {"status": "missing", "lines": []}).items() if k != "process"})
            return
        _json(self, {"error": "not found"}, 404)

    def do_POST(self) -> None:
        path = urllib.parse.urlparse(self.path)
        if path.path.startswith("/eeg/"):
            _proxy_eeg_analyser(self)
            return
        if path.path.startswith("/xiaozhuli/"):
            _proxy_xiaozhuli(self)
            return
        if path.path == "/api/settings":
            length = int(self.headers.get("Content-Length", "0") or 0)
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            _json(self, {"ok": True, **_save_public_settings(payload)})
            return
        if path.path == "/api/apps":
            length = int(self.headers.get("Content-Length", "0") or 0)
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            try:
                _json(self, {"ok": True, **_control_app(payload)})
            except Exception as exc:
                _json(self, {"ok": False, "error": _safe_error(exc), **_app_statuses()}, 400)
            return
        if path.path == "/api/test_model":
            length = int(self.headers.get("Content-Length", "0") or 0)
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            result = _test_model_detailed(str(payload.get("provider") or ""), payload)
            extra: dict[str, Any] = {}
            if payload.get("connection_id"):
                extra["model_connection_library"] = _record_connection_test_result(str(payload.get("connection_id") or ""), result)
            _json(self, {"ok": True, "result": result, **extra, **_public_settings()})
            return
        if path.path == "/api/test_all_models":
            length = int(self.headers.get("Content-Length", "0") or 0)
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            results = _test_all_model_links_for_payload(payload)
            _json(self, {"ok": True, "results": results, **_public_settings()})
            return
        if path.path == "/api/test_step_routes":
            report = _test_step_routes()
            _json(self, {"ok": True, **report, **_public_settings()})
            return
        if path.path == "/api/test_step_routes_repair":
            report = _test_step_routes_with_repair()
            _json(self, {"ok": True, **report, **_public_settings()})
            return
        if path.path == "/api/test_email":
            length = int(self.headers.get("Content-Length", "0") or 0)
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            _save_public_settings(payload)
            _json(self, {"ok": True, "result": _test_email(payload), **_public_settings()})
            return
        if path.path == "/api/model_profile":
            length = int(self.headers.get("Content-Length", "0") or 0)
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            action = str(payload.get("action") or "").strip()
            try:
                if action == "save":
                    _save_public_settings(payload)
                    _json(self, {"ok": True, "model_profiles": _save_current_as_profile(payload), **_public_settings()})
                elif action == "apply":
                    _json(self, {"ok": True, **_apply_model_profile(str(payload.get("profile_id") or ""))})
                elif action == "apply_key":
                    _json(self, {"ok": True, **_apply_profile_key(str(payload.get("profile_id") or ""), str(payload.get("key_name") or ""))})
                elif action == "delete":
                    _json(self, {"ok": True, "model_profiles": _delete_model_profile(str(payload.get("profile_id") or "")), **_public_settings()})
                else:
                    _json(self, {"ok": False, "error": "unknown action"}, 400)
            except Exception as exc:
                _json(self, {"ok": False, "error": _safe_error(exc)}, 400)
            return
        if path.path == "/api/optimizer":
            length = int(self.headers.get("Content-Length", "0") or 0)
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            try:
                name, cmd, cwd = _build_optimizer_command(str(payload.get("project") or ""), str(payload.get("mode") or "once"))
                job_id = _new_job_id()
                JOBS[job_id] = {"job_id": job_id, "status": "starting", "cmd": cmd, "cwd": str(cwd), "lines": [], "exit_code": None}
                threading.Thread(target=_run_job, args=(job_id, cmd, cwd), daemon=True).start()
                _json(self, {"ok": True, "job_id": job_id, "name": name, "mode": str(payload.get("mode") or "once"), "cmd": cmd})
            except Exception as exc:
                _json(self, {"ok": False, "error": _safe_error(exc)}, 400)
            return
        if path.path == "/api/model_connection":
            length = int(self.headers.get("Content-Length", "0") or 0)
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            action = str(payload.get("action") or "").strip()
            try:
                if action == "save":
                    _json(self, {"ok": True, "model_connection_library": _save_model_connection(payload), **_public_settings()})
                elif action == "activate":
                    _json(self, {"ok": True, "model_connection_library": _set_active_model_connection(payload), **_public_settings()})
                elif action == "route":
                    _json(self, {"ok": True, "model_connection_library": _save_step_route(payload), **_public_settings()})
                elif action == "delete":
                    _json(self, {"ok": True, "model_connection_library": _delete_model_connection(payload), **_public_settings()})
                elif action == "apply_all":
                    _json(self, {"ok": True, **_apply_model_config_to_all_projects()})
                else:
                    _json(self, {"ok": False, "error": "unknown action"}, 400)
            except Exception as exc:
                _json(self, {"ok": False, "error": _safe_error(exc)}, 400)
            return
        if path.path == "/api/audience":
            length = int(self.headers.get("Content-Length", "0") or 0)
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            try:
                name, cmd, cwd, mode = _build_audience_command(str(payload.get("project") or ""), str(payload.get("mode") or "once"))
                job_id = _new_job_id()
                JOBS[job_id] = {"job_id": job_id, "status": "starting", "cmd": cmd, "cwd": str(cwd), "lines": _initial_job_lines(name, mode, cmd, cwd), "summary": _pending_summary(name, mode), "exit_code": None}
                threading.Thread(target=_run_job, args=(job_id, cmd, cwd), daemon=True).start()
                _json(self, {"ok": True, "job_id": job_id, "name": name, "mode": mode, "cmd": cmd})
            except Exception as exc:
                _json(self, {"ok": False, "error": _safe_error(exc)}, 400)
            return
        if path.path == "/api/audience_feedback":
            length = int(self.headers.get("Content-Length", "0") or 0)
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            try:
                name, cmd, cwd = _build_feedback_command(str(payload.get("project") or ""), str(payload.get("text") or ""))
                proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
                if proc.returncode != 0:
                    raise RuntimeError((proc.stderr or proc.stdout or "写入优化建议失败")[-800:])
                _json(self, {"ok": True, "name": name, "message": "优化建议已写入", "stdout": (proc.stdout or "")[-1200:]})
            except Exception as exc:
                _json(self, {"ok": False, "error": _safe_error(exc)}, 400)
            return
        if path.path == "/api/start":
            length = int(self.headers.get("Content-Length", "0") or 0)
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            try:
                _apply_connection_library_to_defaults(mark_changed=True)
                cmd, cwd = _build_command(payload)
            except Exception as exc:
                _json(self, {"ok": False, "error": _safe_error(exc)}, 400)
                return
            job_id = _new_job_id()
            JOBS[job_id] = {"job_id": job_id, "status": "starting", "cmd": cmd, "cwd": str(cwd), "lines": [], "exit_code": None, "output_dir": _default_output_dir(payload)}
            threading.Thread(target=_run_job, args=(job_id, cmd, cwd), daemon=True).start()
            _json(self, {"job_id": job_id, "message": "已启动网页任务", "cmd": cmd})
            return
        if path.path == "/api/science_state":
            length = int(self.headers.get("Content-Length", "0") or 0)
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            try:
                _json(self, _save_science_state_payload(payload))
            except Exception as exc:
                _json(self, {"ok": False, "error": _safe_error(exc)}, 400)
            return
        if path.path == "/api/open_output_folder":
            length = int(self.headers.get("Content-Length", "0") or 0)
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            job_id = str(payload.get("job_id") or "").strip()
            target = str(payload.get("path") or "").strip()
            if job_id and JOBS.get(job_id, {}).get("output_dir"):
                target = str(JOBS[job_id].get("output_dir") or target)
            ok, message = _open_folder_path(target)
            _json(self, {"ok": ok, "path": message if ok else target, "message": "作品文件夹已打开" if ok else message}, 200 if ok else 400)
            return
        if path.path == "/api/clear_output_folder":
            length = int(self.headers.get("Content-Length", "0") or 0)
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            ok, message = _clear_folder_contents(str(payload.get("path") or ""))
            _json(self, {"ok": ok, "path": message if ok else "", "message": "作品文件夹已清空" if ok else message}, 200 if ok else 400)
            return
        if path.path == "/api/stop":
            job_id = urllib.parse.parse_qs(path.query).get("id", [""])[0]
            proc = JOBS.get(job_id, {}).get("process")
            if proc and proc.poll() is None:
                proc.terminate()
                JOBS[job_id]["status"] = "stopping"
            _json(self, {"ok": True})
            return
        _json(self, {"error": "not found"}, 404)

    def log_message(self, format: str, *args: Any) -> None:
        return


def main(argv: list[str] | None = None) -> None:
    port = int((argv or sys.argv[1:] or ["8765"])[0])
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"XGN Assistant Web: {url}", flush=True)
    webbrowser.open(url)
    server.serve_forever()


if __name__ == "__main__":
    main()
































