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
import concurrent.futures
import hashlib
import shlex
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
MODEL_DOC_SOURCE_URLS = (
    MODEL_DOC_SOURCE_URL,
    "https://quanland.feishu.cn/wiki/UZXZwH5dJiPo6DkqqNMcmOEGnJ5",
)
FEISHU_DOCS_WORKDIR = Path(os.environ.get("FEISHU_DOCS_WORKDIR", r"C:\Users\XGN\Documents\Codex\2026-06-04\new-chat-3\work\feishu-direct"))
DEFAULT_PROFILE_ID = "dst"
DEFAULT_FOREIGN_BASE_URL = "https://api.dstopology.com/v1"
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_GPT_PRO_BASE_URL = "https://www.fhl.mom/v1"
DEFAULT_MINIMAX_BASE_URL = "https://api.53hk.cn"
BGM_LIBRARY_DIR = PROJECT_ROOT / "bgm_library"
JOB_MODEL_SNAPSHOT_DIR = PROJECT_ROOT / ".workbench_runtime" / "job_model_snapshots"
CLOUD_MONITOR_STATE_FILE = PROJECT_ROOT / ".workbench_runtime" / "cloud_monitor_state.json"
CLOUD_METRICS_FILE = PROJECT_ROOT / ".workbench_runtime" / "cloud_metrics.json"
CLOUD_SSH_KEY_FILE = Path(os.environ.get("QUANLAN_CLOUD_SSH_KEY", str(Path.home() / ".ssh" / "xiaozhuli_aliyun")))
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
    "polish_text": {"label": "最终文案润色", "role": "polish", "roles": ("polish",)},
    "image_generation": {"label": "图片生成", "role": "image", "roles": ("image",)},
    "voice_bgm": {"label": "配音/BGM", "role": "minimax", "roles": ("minimax",)},
}
MODEL_STEP_ORDER = ("script_text", "research_text", "polish_text", "image_generation", "voice_bgm")
ROLE_DEFAULT_STEP = {
    "text": "script_text",
    "gpt_pro": "",
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
XIAOZHULI_NODE_EXE = os.environ.get("XIAOZHULI_NODE_EXE", r"C:\Program Files\nodejs\node.exe")
XIAOZHULI_WORKER_SCRIPTS = (
    "feishu-codex-dispatcher.mjs",
    "feishu-group-listener.mjs",
    "feishu-permission-sync.mjs",
    "feishu-realtime-optimizer.mjs",
    "feishu-watchdog.mjs",
)
XIAOZHULI_STOP_SCRIPT_ORDER = (
    "feishu-watchdog.mjs",
    "feishu-group-listener.mjs",
    "feishu-realtime-optimizer.mjs",
    "feishu-codex-dispatcher.mjs",
    "feishu-permission-sync.mjs",
    "wecom-callback.mjs",
    "xiaozhuli-dashboard.mjs",
)
PRODUCTION_PUBLIC_BASE_URL = os.environ.get("QUANLAN_PRODUCTION_PUBLIC_BASE_URL", os.environ.get("QUANLAN_ALIYUN_PUBLIC_BASE_URL", "http://39.97.248.225")).rstrip("/")
ASSISTANT_RELEASE_ROOT = Path(os.environ.get("ASSISTANT_RELEASE_ROOT", str(PROJECT_ROOT.parent / "xgn-assistant-release")))
ASSISTANT_DEV_ROOT = Path(os.environ.get("ASSISTANT_DEV_ROOT", str(PROJECT_ROOT.parent / "xgn-assistant")))
ASSISTANT_RELEASE_PORT = int(os.environ.get("ASSISTANT_RELEASE_PORT", "8766"))
ASSISTANT_PRODUCTION_URL = os.environ.get("ASSISTANT_PRODUCTION_URL", f"http://127.0.0.1:{ASSISTANT_RELEASE_PORT}/assistant/").rstrip("/") + "/"
ASSISTANT_RELEASE_PROCESS: subprocess.Popen[str] | None = None
XIAOZHULI_PRODUCTION_URL = os.environ.get("XIAOZHULI_PRODUCTION_URL", f"{PRODUCTION_PUBLIC_BASE_URL}/xiaozhuli/").rstrip("/") + "/"
XIAOZHULI_PROCESS: subprocess.Popen[str] | None = None
XIAOZHULI_CONFIG_DIRTY = False
SHARED_CONFIG_UPDATED_AT = ""
SHARED_MODEL_CONFIG_GUARD_MESSAGE = "Model config is centralized in xgn-assistant total console."
EEG_ANALYSER_ROOT = Path(os.environ.get("EEG_ANALYSER_ROOT", r"D:\Quanlan\Codes\Python\quanlan-analyser"))
EEG_ANALYSER_PORT = int(os.environ.get("EEG_ANALYSER_PORT", "4174"))
EEG_ANALYSER_TARGET = os.environ.get("EEG_ANALYSER_TARGET", "http://39.97.248.225").rstrip("/")
EEG_ANALYSER_DEVELOPMENT_URL = os.environ.get("EEG_ANALYSER_DEVELOPMENT_URL", f"http://127.0.0.1:{EEG_ANALYSER_PORT}/?v=neuron-eeg-image2-new-file-2")
EEG_ANALYSER_PROCESS: subprocess.Popen[str] | None = None
PRODUCTION_CONTROL_TIMEOUT = float(os.environ.get("QUANLAN_PRODUCTION_CONTROL_TIMEOUT", "45") or 45)
CLOUD_MONITOR_DEFAULT_SERVERS = (
    {
        "id": "aliyun-eeg-main",
        "name": "阿里云 ECS / 脑电分析正式服务",
        "provider": "阿里云 ECS",
        "host": "39.97.248.225",
        "root_url": "http://39.97.248.225/",
        "health_url": "http://39.97.248.225/health",
        "ssh_user": "root",
        "ssh_key": str(CLOUD_SSH_KEY_FILE),
        "services": ("eeg", "xiaozhuli"),
    },
)
DAILY_RESEARCH_DEFAULT_ROOT = Path(os.environ.get("DAILY_RESEARCH_DEFAULT_ROOT", r"D:\Quanlan\全澜脑科学视频号\科研速递"))
SCIENCE_TASK_SETTINGS_FILE = PROJECT_ROOT / "modes" / "research" / "quanlan_task_page_settings.json"
SCIENCE_DEFAULT_ROOT = Path(os.environ.get("SCIENCE_CLASSIC_DEFAULT_ROOT", r"D:\Quanlan\鍏ㄦ緶鑴戠瀛﹁棰戝彿\绁炵粡绉戝缁忓吀"))
SCIENCE_DEFAULT_PDF_GLOB = "Principles of Neural Science*.pdf"


def _read_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return fallback


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _safe_job_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    blocked = re.compile(r"(?:api_key|password|secret|token)$", re.I)
    return {str(k): v for k, v in payload.items() if not blocked.search(str(k))}


def _public_job(job: dict[str, Any] | None, *, include_lines: bool = True) -> dict[str, Any]:
    if not isinstance(job, dict):
        return {"status": "missing", "lines": []}
    hidden = {"process", "model_snapshot"}
    data = {k: v for k, v in job.items() if k not in hidden}
    if "job_id" in data and "id" not in data:
        data["id"] = data["job_id"]
    if "payload" in data:
        data["payload"] = _safe_job_payload(data.get("payload") if isinstance(data.get("payload"), dict) else {})
    if not include_lines:
        data.pop("lines", None)
    return data


def _public_jobs() -> list[dict[str, Any]]:
    items = [_public_job(job, include_lines=False) for job in JOBS.values()]
    return sorted(items, key=lambda item: str(item.get("started_at") or item.get("created_at") or ""), reverse=True)


def _terminate_job_process(job: dict[str, Any]) -> bool:
    proc = job.get("process") if isinstance(job, dict) else None
    if proc and getattr(proc, "poll", lambda: None)() is None:
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, text=True, timeout=8)
            else:
                proc.terminate()
            job["status"] = "stopping"
            job["updated_at"] = int(time.time() * 1000)
            return True
        except Exception:
            try:
                proc.kill()
                job["status"] = "stopped"
                job["exit_code"] = job.get("exit_code", -9)
                job["updated_at"] = int(time.time() * 1000)
                return True
            except Exception:
                return False
    return False


def _stop_job_record(job_id: str) -> dict[str, Any]:
    job_id = str(job_id or "").strip()
    if not job_id or job_id not in JOBS:
        return {"ok": False, "message": "没有找到要停止的任务"}
    job = JOBS[job_id]
    terminated = _terminate_job_process(job)
    if not terminated and job.get("status") in {"starting", "running", "stopping"}:
        job["status"] = "stopped"
        job["exit_code"] = job.get("exit_code", -15)
    job["updated_at"] = int(time.time() * 1000)
    try:
        job.setdefault("lines", []).append(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 已收到停止请求，正在收住当前任务。\n")
    except Exception:
        pass
    return {"ok": True, "job_id": job_id, "terminated": terminated, "status": job.get("status", "stopped")}


def _delete_job_record(job_id: str) -> dict[str, Any]:
    job_id = str(job_id or "").strip()
    if not job_id or job_id not in JOBS:
        return {"ok": True, "deleted": False, "message": "任务记录不存在或已删除"}
    job = JOBS[job_id]
    terminated = _terminate_job_process(job)
    if job.get("lines") is not None:
        try:
            job["lines"].append(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 任务记录已从总控台删除。\n")
        except Exception:
            pass
    JOBS.pop(job_id, None)
    return {"ok": True, "deleted": True, "terminated": terminated, "job_id": job_id}


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
    preferred = SCIENCE_DEFAULT_ROOT / "绁炵粡绉戝鍘熺悊" / "鍘熸枃"
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
    return str(path.with_name(f"{stem}_绔犺妭PDF鐩翠紶缁撴灉"))


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
        raise FileNotFoundError(f"PDF 涓嶅瓨鍦細{clean_path or pdf_path}")
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
        "content_style": slot.get("content_style") or "绉戝缁忓吀瑙ｈ",
        "test_b_image_limit": int(slot.get("test_b_image_limit", 0) or 0),
        "toc": toc,
        "total": len(toc),
        "scriptable": len(scriptable),
        "selected": len(selected),
        "settings_path": str(SCIENCE_TASK_SETTINGS_FILE),
    }


def _science_model_fields_from_console() -> dict[str, Any]:
    models = _models_with_url_defaults(_apply_business_steps_to_models(_model_settings()))
    text_model = str(models.get("research_text_model") or models.get("culture_text_model") or models.get("text_engine") or "gpt-5.5")
    polish_model = str(models.get("research_polish_model") or models.get("culture_polish_model") or models.get("polish_engine") or text_model)
    image_model = str(models.get("research_image_model") or models.get("culture_image_model") or models.get("image_engine") or "gpt-image-2")
    return {
        "text_engine": _daily_text_engine_arg(text_model),
        "review_engine": _daily_text_engine_arg(polish_model),
        "image_engine": _daily_image_engine_arg(image_model),
        "call_mode": "API 鑷姩璋冪敤",
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
    slot["content_style"] = "绉戝缁忓吀瑙ｈ"
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


def _connection_public_id_value(connection: dict[str, Any]) -> str:
    role = _model_connection_role(str(connection.get("role") or ""))
    return _connection_id(str(connection.get("id") or connection.get("name") or f"{role}-connection"))


def _same_connection_id(connection: dict[str, Any], connection_id: str) -> bool:
    cid = _connection_id(connection_id)
    raw_id = _connection_id(str(connection.get("id") or ""))
    public_id = _connection_public_id_value(connection)
    variants = {raw_id, public_id, raw_id.rstrip("-"), public_id.rstrip("-")}
    return bool(cid and (cid in variants or cid.rstrip("-") in variants))


def _preserve_connection_test_state(target: dict[str, Any], source: dict[str, Any]) -> None:
    for key in ("last_test_ok", "last_tested_at", "last_test_message", "latency_ms"):
        if source.get(key) not in ("", None) and target.get(key) in ("", None):
            target[key] = source.get(key)


def _connection_test_status_for(data: dict[str, Any], connection: dict[str, Any]) -> dict[str, Any]:
    statuses = data.get("connection_test_status") if isinstance(data.get("connection_test_status"), dict) else {}
    for key in (_connection_public_id_value(connection), _connection_id(str(connection.get("id") or ""))):
        status = statuses.get(key)
        if isinstance(status, dict):
            return status
    for key, status in statuses.items():
        if isinstance(status, dict) and _same_connection_id(connection, str(key or "")):
            return status
    return {}


def _apply_connection_test_status(data: dict[str, Any]) -> dict[str, Any]:
    connections = data.get("connections") if isinstance(data.get("connections"), list) else []
    for item in connections:
        if isinstance(item, dict):
            status = _connection_test_status_for(data, item)
            if status:
                item.update({key: status.get(key) for key in ("last_test_ok", "last_tested_at", "last_test_message", "latency_ms") if key in status})
    return data


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


def _connection_key_value(connection: dict[str, Any]) -> str:
    cid = _connection_id(str(connection.get("id") or ""))
    key_name = str(connection.get("key_name") or _key_for_connection_role(str(connection.get("role") or "")))
    return _read_secret(_connection_secret_path(cid, key_name))


def _normalized_connection_base_key(value: Any) -> str:
    text_value = str(value or "").strip().rstrip("/")
    if text_value.lower().endswith("/v1"):
        text_value = text_value[:-3].rstrip("/")
    return text_value.lower()


def _connection_url_key_fingerprint(connection: dict[str, Any], secret_value: str | None = None) -> str:
    base_key = _normalized_connection_base_key(connection.get("base_url"))
    secret = str(secret_value if secret_value is not None else _connection_key_value(connection) or "").strip()
    if not base_key or not secret:
        return ""
    digest = hashlib.sha256(secret.encode("utf-8")).hexdigest()
    return f"{base_key}::{digest}"


def _deleted_connection_fingerprints(data: dict[str, Any]) -> set[str]:
    raw = data.get("deleted_connection_fingerprints")
    if not isinstance(raw, list):
        return set()
    return {str(item or "").strip() for item in raw if str(item or "").strip()}


def _clean_public_text(value: Any) -> str:
    text = str(value or "")
    replacements = {
        "鏂囨湰": "文本",
        "澶囩敤鏂囨湰": "备用文本",
        "娑﹁壊": "润色",
        "鐢熷浘": "生图",
        "閰嶉煶": "配音",
        "褰撳墠榛樿": "当前默认",
        "鏂规": "方案",
        "?顒€????": "本地文件",
        "?顖氼暔???": "环境变量",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def _connection_public_item(connection: dict[str, Any]) -> dict[str, Any]:
    role = _model_connection_role(str(connection.get("role") or ""))
    cid = _connection_public_id_value(connection)
    key_name = str(connection.get("key_name") or _key_for_connection_role(role))
    item = {
        "id": cid,
        "role": role,
        "role_label": str(MODEL_CONNECTION_ROLES[role]["label"]),
        "name": _clean_public_text(connection.get("name") or cid),
        "provider": _clean_public_text(connection.get("provider") or _provider_for_connection_role(role)),
        "base_url": _clean_public_text(connection.get("base_url") or ""),
        "model": _clean_public_text(connection.get("model") or ""),
        "key_name": key_name,
        "enabled": bool(connection.get("enabled", True)),
        "priority": int(connection.get("priority") or 100),
        "last_tested_at": str(connection.get("last_tested_at") or ""),
        "last_test_message": _clean_public_text(connection.get("last_test_message") or ""),
        "latency_ms": int(float(connection.get("latency_ms") or 0)),
        "key_configured": bool(_read_secret(_connection_secret_path(cid, key_name))),
    }
    if "last_test_ok" in connection:
        item["last_test_ok"] = bool(connection.get("last_test_ok"))
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
    deleted_fingerprints = _deleted_connection_fingerprints(data)
    by_id = {
        _connection_id(str(item.get("id") or "")): item
        for item in existing
        if (
            isinstance(item, dict)
            and _connection_id(str(item.get("id") or "")) not in deleted
            and _connection_url_key_fingerprint(item) not in deleted_fingerprints
        )
    }
    priority = 10
    models = _read_json(MODEL_DEFAULTS_FILE, {})
    if isinstance(models, dict):
        for role in MODEL_CONNECTION_ROLE_ORDER:
            conn = _connection_from_models(role, "褰撳墠榛樿", models, priority=priority, locked=True)
            secret = _read_secret(_connection_secret_path(str(conn.get("id") or ""), str(conn.get("key_name") or "")))
            if not secret:
                secret, _ = _read_model_secret(str(conn.get("key_name") or ""))
            if conn["id"] not in deleted and _connection_url_key_fingerprint(conn, secret) not in deleted_fingerprints:
                existing_item = by_id.get(conn["id"])
                if existing_item is not None:
                    _preserve_connection_test_state(conn, existing_item)
                    by_id[conn["id"]] = {**existing_item, **conn}
                else:
                    by_id[conn["id"]] = conn
            priority += 10
    profiles = _read_json(MODEL_PROFILES_FILE, {})
    profile_items = profiles.get("profiles") if isinstance(profiles, dict) else []
    if isinstance(profile_items, list):
        for profile in profile_items:
            if not isinstance(profile, dict):
                continue
            profile_models = profile.get("models") if isinstance(profile.get("models"), dict) else {}
            name = str(profile.get("name") or profile.get("id") or "鏂规")
            for role in MODEL_CONNECTION_ROLE_ORDER:
                conn = _connection_from_models(role, name, profile_models, priority=priority, locked=bool(profile.get("locked")))
                if conn["id"] in deleted:
                    priority += 10
                    continue
                by_id.setdefault(conn["id"], conn)
                source_key = _profile_secret_path(str(profile.get("id") or ""), str(conn.get("key_name") or ""))
                target_key = _connection_secret_path(str(conn.get("id") or ""), str(conn.get("key_name") or ""))
                source_secret = _read_secret(source_key)
                if not source_secret:
                    source_secret = _read_secret(target_key)
                if not source_secret:
                    source_secret, _ = _read_model_secret(str(conn.get("key_name") or ""))
                conn_id = _connection_id(str(conn.get("id") or ""))
                if _connection_url_key_fingerprint(conn, source_secret) in deleted_fingerprints:
                    by_id.pop(conn_id, None)
                    priority += 10
                    continue
                if conn_id in by_id:
                    existing_item = by_id[conn_id]
                    _preserve_connection_test_state(conn, existing_item)
                    for key, value in conn.items():
                        if key not in existing_item or existing_item.get(key) in ("", None):
                            existing_item[key] = value
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
        if role == "polish" and "api.deepseek.com" in _normalized_connection_base_key(item.get("base_url")) and str(item.get("model") or "").strip().lower().startswith("gpt"):
            item["model"] = "deepseek-chat"
    collapsed: list[dict[str, Any]] = []
    seen_url_secret: dict[tuple[str, str], dict[str, Any]] = {}
    replaced_url_secret_ids: set[str] = set()

    def seed_score(item: dict[str, Any]) -> tuple[int, int, int]:
        clean_name = _clean_public_text(item.get("name") or "").strip()
        return (
            1 if item.get("source") or clean_name.startswith("飞书文档") else 0,
            1 if clean_name and clean_name != "当前默认" else 0,
            -int(item.get("priority") or 100),
        )

    for item in data["connections"]:
        if not isinstance(item, dict):
            continue
        secret = _connection_key_value(item)
        key = (_normalized_connection_base_key(item.get("base_url")), secret) if secret else ("", "")
        fingerprint = _connection_url_key_fingerprint(item, secret)
        if fingerprint and fingerprint in deleted_fingerprints:
            item_id = _connection_id(str(item.get("id") or ""))
            if item_id:
                replaced_url_secret_ids.add(item_id)
            continue
        if secret and key[1]:
            current = seen_url_secret.get(key)
            if current is not None:
                if seed_score(item) > seed_score(current):
                    _preserve_connection_test_state(item, current)
                    current_id = _connection_id(str(current.get("id") or ""))
                    if current_id:
                        replaced_url_secret_ids.add(current_id)
                    seen_url_secret[key] = item
                    collapsed = [
                        existing for existing in collapsed
                        if _connection_id(str(existing.get("id") or "")) != current_id
                    ]
                else:
                    _preserve_connection_test_state(current, item)
                    item_id = _connection_id(str(item.get("id") or ""))
                    if item_id:
                        replaced_url_secret_ids.add(item_id)
                    continue
            else:
                seen_url_secret[key] = item
        collapsed.append(item)
    if replaced_url_secret_ids:
        deleted = data.get("deleted_connections") if isinstance(data.get("deleted_connections"), list) else []
        data["deleted_connections"] = sorted(set([*map(str, deleted), *replaced_url_secret_ids]))
        for route_key in ("step_routes", "active_connections"):
            block = data.get(route_key)
            if not isinstance(block, dict):
                continue
            for key, value in list(block.items()):
                if isinstance(value, list):
                    block[key] = [x for x in value if _connection_id(str(x or "")) not in replaced_url_secret_ids]
                elif _connection_id(str(value or "")) in replaced_url_secret_ids:
                    block.pop(key, None)
    data["connections"] = collapsed
    return data


def _read_model_connection_library() -> dict[str, Any]:
    data = _read_json(MODEL_CONNECTION_LIBRARY_FILE, {})
    if not isinstance(data, dict):
        data = {}
    data = _seed_connection_library_from_profiles(data)
    for item in data.get("connections", []):
        if not isinstance(item, dict):
            continue
        role = _model_connection_role(str(item.get("role") or ""))
        base_url = _normalized_connection_base_key(item.get("base_url"))
        model = str(item.get("model") or "").strip().lower()
        if role == "polish" and "api.deepseek.com" in base_url and model.startswith("gpt"):
            item["model"] = "deepseek-chat"
    data["active_connections"] = data.get("active_connections") if isinstance(data.get("active_connections"), dict) else {}
    data["step_routes"] = data.get("step_routes") if isinstance(data.get("step_routes"), dict) else {}
    for obsolete_step in ("gpt_pro_backup",):
        data["step_routes"].pop(obsolete_step, None)
        data["active_connections"].pop(obsolete_step, None)
    user_step_routes = data.get("user_step_routes")
    if not isinstance(user_step_routes, dict):
        user_step_routes = {}
    for obsolete_step in ("gpt_pro_backup",):
        user_step_routes.pop(obsolete_step, None)
    for step, meta in MODEL_STEP_ROUTES.items():
        current = data["step_routes"].get(step)
        user_managed = bool(user_step_routes.get(step))
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
            if item and bool(item.get("enabled", True)) and _model_connection_role(str(item.get("role") or "")) in allowed_roles:
                real_cid = _connection_id(str(item.get("id") or cid))
                if real_cid not in cleaned:
                    cleaned.append(real_cid)
        if not user_managed and not cleaned:
            for item in data.get("connections", []):
                if not isinstance(item, dict):
                    continue
                cid = _connection_id(str(item.get("id") or ""))
                if bool(item.get("enabled", True)) and _model_connection_role(str(item.get("role") or "")) in allowed_roles and cid and cid not in cleaned:
                    cleaned.append(cid)
        data["step_routes"][step] = cleaned
    _repair_active_model_connections(data)
    _force_current_model_routes(data)
    _write_json(MODEL_CONNECTION_LIBRARY_FILE, data)
    return data


def _dedupe_model_connection_library() -> dict[str, Any]:
    data = _read_model_connection_library()
    connections = data.get("connections") if isinstance(data.get("connections"), list) else []
    by_key: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    by_url_secret: dict[tuple[str, str], dict[str, Any]] = {}
    removed_ids: set[str] = set()

    def score(item: dict[str, Any]) -> tuple[int, int, int, int, int, int]:
        clean_name = _clean_public_text(item.get("name") or "").strip()
        source = str(item.get("source") or "")
        return (
            1 if source or clean_name.startswith("飞书文档") else 0,
            1 if clean_name and clean_name != "当前默认" else 0,
            1 if item.get("last_test_ok") else 0,
            1 if _connection_has_key(item) else 0,
            1 if item.get("last_tested_at") else 0,
            -int(item.get("priority") or 100),
        )

    for item in connections:
        if not isinstance(item, dict):
            continue
        secret_value = _connection_key_value(item)
        url_secret_key = (_normalized_connection_base_key(item.get("base_url")), secret_value) if secret_value else ("", "")
        if secret_value and url_secret_key[0]:
            current_by_secret = by_url_secret.get(url_secret_key)
            if current_by_secret is None or score(item) > score(current_by_secret):
                if current_by_secret is not None:
                    removed_ids.add(_connection_id(str(current_by_secret.get("id") or "")))
                by_url_secret[url_secret_key] = item
            else:
                removed_ids.add(_connection_id(str(item.get("id") or "")))
                continue
        key = (
            _model_connection_role(str(item.get("role") or "")),
            str(item.get("provider") or _provider_for_connection_role(_model_connection_role(str(item.get("role") or "")))).strip(),
            str(item.get("base_url") or "").strip().rstrip("/"),
            str(item.get("model") or "").strip(),
            _clean_public_text(item.get("name") or "").strip(),
        )
        current = by_key.get(key)
        if current is None or score(item) > score(current):
            if current is not None:
                removed_ids.add(_connection_id(str(current.get("id") or "")))
            by_key[key] = item
        else:
            removed_ids.add(_connection_id(str(item.get("id") or "")))
    if not removed_ids:
        return _public_model_connection_library(data)
    data["connections"] = [item for item in connections if isinstance(item, dict) and _connection_id(str(item.get("id") or "")) not in removed_ids]
    for route_key in ("step_routes", "active_connections"):
        block = data.get(route_key)
        if not isinstance(block, dict):
            continue
        for key, value in list(block.items()):
            if isinstance(value, list):
                block[key] = [x for x in value if _connection_id(str(x or "")) not in removed_ids]
            elif _connection_id(str(value or "")) in removed_ids:
                block.pop(key, None)
    deleted = data.get("deleted_connections") if isinstance(data.get("deleted_connections"), list) else []
    data["deleted_connections"] = sorted(set([*map(str, deleted), *removed_ids]))
    _repair_active_model_connections(data)
    _force_current_model_routes(data)
    _write_json(MODEL_CONNECTION_LIBRARY_FILE, data)
    return _public_model_connection_library(data)


def _public_model_connection_library(data: dict[str, Any] | None = None) -> dict[str, Any]:
    data = data or _read_model_connection_library()
    data = _apply_connection_test_status(data)
    connections = data.get("connections") if isinstance(data.get("connections"), list) else []
    public = [_connection_public_item(item) for item in connections if isinstance(item, dict)]
    grouped: dict[str, list[dict[str, Any]]] = {role: [] for role in MODEL_CONNECTION_ROLE_ORDER}
    by_provider_model: dict[str, dict[str, Any]] = {}
    by_model: dict[str, dict[str, Any]] = {}
    for item in public:
        grouped.setdefault(str(item.get("role") or "text"), []).append(item)
        provider = str(item.get("provider") or "unknown")
        model = str(item.get("model") or "未设置")
        key = f"{provider}::{model}"
        group = by_provider_model.setdefault(key, {"provider": provider, "model": model, "connections": []})
        group["connections"].append(item)
        model_group = by_model.setdefault(model, {"model": model, "connections": [], "providers": []})
        model_group["connections"].append(item)
        if provider not in model_group["providers"]:
            model_group["providers"].append(provider)
    routes = data.get("step_routes") if isinstance(data.get("step_routes"), dict) else {}
    return {
        "roles": {role: dict(MODEL_CONNECTION_ROLES[role]) for role in MODEL_CONNECTION_ROLE_ORDER},
        "steps": {step: {**dict(MODEL_STEP_ROUTES[step]), "roles": list(MODEL_STEP_ROUTES[step].get("roles") or (MODEL_STEP_ROUTES[step].get("role"),))} for step in MODEL_STEP_ORDER},
        "step_routes": {step: [str(x) for x in routes.get(step, []) if str(x or "")] for step in MODEL_STEP_ORDER},
        "active_connections": data.get("active_connections") if isinstance(data.get("active_connections"), dict) else {},
        "connections": public,
        "grouped": grouped,
        "by_provider_model": list(by_provider_model.values()),
        "by_model": list(by_model.values()),
    }


def _connection_sort_key(item: dict[str, Any], *, active_id: str = "") -> tuple[int, int, int, int, int, str]:
    tested = 0 if item.get("last_test_ok") else 1
    key_ready = 0 if _connection_has_key(item) else 1
    active_bias = 0 if active_id and _connection_id(str(item.get("id") or "")) == active_id else 1
    latency = int(float(item.get("latency_ms") or 999999))
    return (tested, key_ready, active_bias, latency, int(item.get("priority") or 100), str(item.get("name") or ""))


def _route_rank_for_item(item: dict[str, Any], route_rank: dict[str, int]) -> int:
    for key, rank in route_rank.items():
        if _same_connection_id(item, key):
            return rank
    return 9999


def _connection_by_id(data: dict[str, Any], connection_id: str) -> dict[str, Any] | None:
    cid = _connection_id(connection_id)
    for item in data.get("connections", []):
        if isinstance(item, dict) and _same_connection_id(item, cid):
            return item
    if len(cid) >= 40:
        matches = [
            item for item in data.get("connections", [])
            if isinstance(item, dict) and (_connection_id(str(item.get("id") or "")).startswith(cid) or _connection_public_id_value(item).startswith(cid))
        ]
        if len(matches) == 1:
            return matches[0]
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


def _sync_step_routes_from_active(data: dict[str, Any]) -> bool:
    changed = False
    active = data.get("active_connections") if isinstance(data.get("active_connections"), dict) else {}
    routes = data.get("step_routes") if isinstance(data.get("step_routes"), dict) else {}
    for step, meta in MODEL_STEP_ROUTES.items():
        role = str(meta.get("role") or "text")
        ids: list[str] = []
        for raw in (active.get(step), active.get(role)):
            cid = _connection_id(str(raw or ""))
            item = _connection_by_id(data, cid)
            if item and bool(item.get("enabled", True)):
                real = _connection_public_id_value(item)
                if real and real not in ids:
                    ids.append(real)
        if ids and routes.get(step) != ids:
            routes[step] = ids
            changed = True
    data["step_routes"] = routes
    return changed


def _force_current_model_routes(data: dict[str, Any]) -> bool:
    changed = False
    connections = data.get("connections") if isinstance(data.get("connections"), list) else []

    preferred_specs = [
        ("text", DEFAULT_FOREIGN_BASE_URL, "gpt-5.5", "DST tested", 10),
        ("polish", DEFAULT_DEEPSEEK_BASE_URL, "deepseek-chat", "DeepSeek polish", 20),
        ("image", DEFAULT_FOREIGN_BASE_URL, "gpt-image-2", "DST image", 30),
        ("minimax", DEFAULT_MINIMAX_BASE_URL, "speech-2.8-hd", "MiniMax 53hk", 40),
        ("gpt_pro", DEFAULT_GPT_PRO_BASE_URL, "gpt-5.5", "GPT-Pro backup", 90),
    ]
    by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    for item in connections:
        if isinstance(item, dict):
            by_key[(
                _model_connection_role(str(item.get("role") or "")),
                str(item.get("base_url") or "").strip().rstrip("/"),
                str(item.get("model") or "").strip(),
            )] = item
    for role, base_url, model, name, priority in preferred_specs:
        key = (role, base_url.rstrip("/"), model)
        item = by_key.get(key)
        if not item:
            item = {
                "id": _connection_id(f"{role}-{name}-{base_url}-{model}"),
                "role": role,
                "name": name,
                "provider": _provider_for_connection_role(role),
                "base_url": base_url.rstrip("/"),
                "model": model,
                "key_name": _key_for_connection_role(role),
                "enabled": True,
            }
            connections.append(item)
            by_key[key] = item
            changed = True
        updates = {"priority": priority, "locked": True, "enabled": True}
        for k, v in updates.items():
            if item.get(k) != v:
                item[k] = v
                changed = True
    data["connections"] = connections

    def find(role: str, base_url: str, model: str) -> str:
        for item in connections:
            if not isinstance(item, dict):
                continue
            if _model_connection_role(str(item.get("role") or "")) != role:
                continue
            if str(item.get("base_url") or "").strip().rstrip("/") != base_url.rstrip("/"):
                continue
            if str(item.get("model") or "").strip() != model:
                continue
            return _connection_id(str(item.get("id") or ""))
        return ""

    text_id = find("text", DEFAULT_FOREIGN_BASE_URL, "gpt-5.5")
    polish_id = find("polish", DEFAULT_DEEPSEEK_BASE_URL, "deepseek-chat")
    image_id = find("image", DEFAULT_FOREIGN_BASE_URL, "gpt-image-2")
    minimax_id = find("minimax", DEFAULT_MINIMAX_BASE_URL, "speech-2.8-hd")
    gpt_pro_id = find("gpt_pro", DEFAULT_GPT_PRO_BASE_URL, "gpt-5.5")
    active = data.get("active_connections") if isinstance(data.get("active_connections"), dict) else {}
    for key, cid in {
        "text": text_id,
        "script_text": text_id,
        "research_text": text_id,
        "polish": polish_id,
        "polish_text": polish_id,
        "image": image_id,
        "image_generation": image_id,
        "minimax": minimax_id,
        "voice_bgm": minimax_id,
        "gpt_pro": gpt_pro_id,
    }.items():
        if cid and active.get(key) != cid:
            active[key] = cid
            changed = True
    data["active_connections"] = active
    routes = data.get("step_routes") if isinstance(data.get("step_routes"), dict) else {}
    user_step_routes = data.get("user_step_routes") if isinstance(data.get("user_step_routes"), dict) else {}
    for step, ids in {
        "script_text": [text_id, gpt_pro_id],
        "research_text": [text_id, gpt_pro_id],
        "polish_text": [polish_id],
        "image_generation": [image_id],
        "voice_bgm": [minimax_id],
    }.items():
        cleaned = [cid for cid in ids if cid]
        current = routes.get(step) if isinstance(routes.get(step), list) else []
        if cleaned and not current and not user_step_routes.get(step):
            routes[step] = cleaned
            changed = True
    data["step_routes"] = routes
    return changed


def _best_connection_for_step(step: str, data: dict[str, Any] | None = None) -> dict[str, Any] | None:
    data = data or _read_model_connection_library()
    meta = MODEL_STEP_ROUTES.get(step)
    if not meta:
        return None
    allowed_roles = {str(x) for x in (meta.get("roles") or (meta.get("role") or "text",))}
    active = data.get("active_connections") if isinstance(data.get("active_connections"), dict) else {}
    role = str(meta.get("role") or "text")
    for raw in (active.get(step), active.get(role)):
        item = _connection_by_id(data, str(raw or ""))
        if item and bool(item.get("enabled", True)) and _model_connection_role(str(item.get("role") or "")) in allowed_roles:
            return item
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
        if step == "image_generation":
            route_rank = {_connection_id(cid): index for index, cid in enumerate(candidate_ids)}
            return sorted(
                candidates,
                key=lambda item: (
                    0 if _connection_has_key(item) else 1,
                    _route_rank_for_item(item, route_rank),
                    0 if active_id and _connection_id(str(item.get("id") or "")) == active_id else 1,
                    0 if item.get("last_test_ok") else 1,
                    int(float(item.get("latency_ms") or 999999)),
                    int(item.get("priority") or 100),
                    str(item.get("name") or ""),
                ),
            )[0]
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
    if _sync_step_routes_from_active(data):
        _write_json(MODEL_CONNECTION_LIBRARY_FILE, data)
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
    _sync_step_routes_from_active(data)
    _write_json(MODEL_CONNECTION_LIBRARY_FILE, data)
    return result


def _apply_connection_library_to_defaults(*, mark_changed: bool = False) -> dict[str, Any]:
    models = _models_from_connection_library(_model_settings())
    models = _models_with_url_defaults(_apply_business_steps_to_models(models))
    _write_json(MODEL_DEFAULTS_FILE, _strip_private_model_fields(models))
    if mark_changed:
        _mark_shared_config_changed()
        _sync_shared_model_config_to_projects(models)
    return models


def _write_job_model_snapshot(job_id: str, models: dict[str, Any]) -> Path:
    JOB_MODEL_SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = JOB_MODEL_SNAPSHOT_DIR / f"{re.sub(r'[^A-Za-z0-9_.-]+', '_', job_id)}.json"
    _write_json(path, _strip_private_model_fields(models))
    return path


def _activate_profile_connections(profile: dict[str, Any]) -> None:
    models = profile.get("models") if isinstance(profile.get("models"), dict) else {}
    if not models:
        return
    data = _read_model_connection_library()
    profile_name = str(profile.get("name") or profile.get("id") or "褰撳墠鏂规")
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
    key_value = str(payload.get("api_key") or payload.get(key_name) or "").strip()
    fingerprint = _connection_url_key_fingerprint({"base_url": base_url}, key_value) if key_value else ""
    if fingerprint:
        deleted_fps = data.get("deleted_connection_fingerprints") if isinstance(data.get("deleted_connection_fingerprints"), list) else []
        data["deleted_connection_fingerprints"] = [item for item in deleted_fps if str(item or "") != fingerprint]
    active = data.get("active_connections") if isinstance(data.get("active_connections"), dict) else {}
    active[role] = cid
    data["active_connections"] = active
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
            real_cid = _connection_public_id_value(item)
            if real_cid not in ids:
                ids.append(real_cid)
    routes = data.get("step_routes") if isinstance(data.get("step_routes"), dict) else {}
    routes[step] = ids
    data["step_routes"] = routes
    user_routes = data.get("user_step_routes") if isinstance(data.get("user_step_routes"), dict) else {}
    user_routes[step] = True
    data["user_step_routes"] = user_routes
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
    fingerprint = _connection_url_key_fingerprint(removed)
    if fingerprint:
        deleted_fps = data.get("deleted_connection_fingerprints") if isinstance(data.get("deleted_connection_fingerprints"), list) else []
        if fingerprint not in deleted_fps:
            deleted_fps.append(fingerprint)
        data["deleted_connection_fingerprints"] = deleted_fps
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
        "name": "DST 绯诲垪",
        "locked": True,
        "models": _default_profile_models(),
    }
    by_id = {str(item.get("id") or ""): item for item in profiles if isinstance(item, dict)}
    by_id.pop("foreign-default", None)
    by_id[DEFAULT_PROFILE_ID] = {**default_profile, **by_id.get(DEFAULT_PROFILE_ID, {})}
    by_id[DEFAULT_PROFILE_ID]["id"] = DEFAULT_PROFILE_ID
    by_id[DEFAULT_PROFILE_ID]["name"] = by_id[DEFAULT_PROFILE_ID].get("name") or "DST 绯诲垪"
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
        name = name or "DST 绯诲垪"
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
            return value, str(path), "本地文件"
    for name in SMTP_PASSWORD_ENV_NAMES:
        value = os.environ.get(name, "").strip()
        if value:
            return value, str(SMTP_PASSWORD_FILES[0]), f"环境变量 {name}"
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
        result[f"{key}_source"] = "本地文件" if file_value else (f"环境变量 {env_name}" if env_value else "未配置")
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


def _human_feishu_reader_error(text: str) -> str:
    raw = str(text or "")
    if not raw:
        return "飞书文档读取失败，未返回具体原因。"
    lower = raw.lower()
    if "99991400" in raw or "frequency limit" in lower or "rate limit" in lower:
        return "飞书接口触发频率限制，已跳过飞书补 Key；稍后再点会自动重试。"
    if "not in current feishu authorization whitelist" in lower or "白名单" in raw:
        return "飞书文档不在当前授权白名单内，已跳过飞书补 Key；请把该文档加入小猪理飞书白名单。"
    if "tenant needs read permission" in raw or '"code":131006' in raw:
        return "飞书文档已在本地白名单内，但云端还没给小猪理企业应用读取权限。"
    if "timeout" in lower or "timed out" in lower:
        return "飞书文档读取超时，已跳过飞书补 Key；现有模型库测试会继续执行。"
    if "feishu api failed 400" in lower:
        return "飞书接口返回 400，已跳过飞书补 Key；现有模型库测试会继续执行。"
    return re.sub(r"\s+", " ", raw).strip()[:160]


def _http_error_hint(provider: str, exc: urllib.error.HTTPError) -> str:
    if exc.code == 401:
        if provider == "openai":
            return "已连接到 GPT 文本接口，但当前 GPT Key 被服务端拒绝；请检查所选方案的 openai_api_key 是否对该中转站和模型有权限。"
        return "已连接到接口，但当前 Key 被服务端拒绝；请检查 Key 是否属于该服务或是否有模型权限。"
    if exc.code == 403:
        return "已连接到接口，但当前 Key 没有访问该模型或接口的权限。"
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


def _http_json(url: str, *, headers: dict[str, str], payload: dict[str, Any], timeout: int = 8) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", errors="replace")
    try:
        return json.loads(body)
    except Exception:
        return {"raw": body[:500]}


def _http_get_json(url: str, *, headers: dict[str, str], timeout: int = 8) -> dict[str, Any]:
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
        detail = proc.stderr or proc.stdout or "读取失败"
        return "", _human_feishu_reader_error(f"{label} 失败：{detail}")
    return proc.stdout or "", ""


def _feishu_model_doc_env() -> dict[str, str]:
    refs = [
        *MODEL_DOC_SOURCE_URLS,
        *[ref.rsplit("/", 1)[-1] for ref in MODEL_DOC_SOURCE_URLS],
        *[x.strip() for x in str(os.environ.get("FEISHU_ALLOWED_DOCUMENT_REFS") or "").split(",") if x.strip()],
    ]
    return {
        "FEISHU_ALLOWED_DOCUMENT_REFS": ",".join(dict.fromkeys(refs)),
        "FEISHU_PERMISSION_MODE": os.environ.get("FEISHU_PERMISSION_MODE", "live_accessible"),
        "FEISHU_READONLY": "true",
    }


def _read_feishu_model_doc_text() -> tuple[str, str]:
    texts: list[str] = []
    errors: list[str] = []
    for source_url in MODEL_DOC_SOURCE_URLS:
        text, error = _read_single_feishu_model_doc_text(source_url)
        if text:
            texts.append(f"\n\n# source: {source_url}\n{text}")
        elif error:
            errors.append(f"{source_url}: {error}")
    if texts:
        return "\n".join(texts), ""
    if not errors:
        errors.append("未找到 Feishu 文档读取脚本。")
    return "", "\n".join(errors[-3:])


def _read_single_feishu_model_doc_text(source_url: str) -> tuple[str, str]:
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
if (!documentId) throw new Error('鏈В鏋愬埌椋炰功鏂囨。 token');
const raw = await authed(`/docx/v1/documents/${documentId}/raw_content`, { method: 'GET' }, 'tenant');
process.stdout.write(raw.data?.content || raw.data?.raw_content || '');
"""
        text, error = _run_feishu_doc_reader(
            "鍏ㄦ緶灏忕尓鐞嗙櫧鍚嶅崟璇诲彇",
            ["node", "-e", direct_reader, source_url],
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
                ["node", str(xiaozhuli_script), "--tenant", "raw", source_url],
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
            "澶囩敤 Feishu 鑴氭湰璇诲彇",
            ["node", str(script), "raw", source_url],
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
    if any(x in lower for x in ("image", "gpt-image", "鐢熷浘", "缁樺浘", "鍥剧墖")):
        return "image"
    if any(x in lower for x in ("minimax", "tts", "speech", "閰嶉煶", "bgm", "闊充箰")):
        return "minimax"
    if any(x in lower for x in ("deepseek", "娑﹁壊", "polish")):
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
    if "gpt-pro" in label.lower() or "gpt_pro" in label.lower():
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
    key_re = re.compile(r"(?:\"key\"\s*:\s*\"([^\"]+)\"|key\s*[:：]\s*([^\s,，；;]+))", re.I)
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
        model_line_match = re.search(r"^model\s*[:：]\s*(.+)$", line, re.I)
        if model_line_match and pending_label:
            pending_model_line = model_line_match.group(1).strip()
            pending_label = f"{pending_label} {pending_model_line}"
            continue
        if any(token in lower for token in ("gpt", "deepseek", "minimax")) and "key" not in lower and "url" not in lower:
            pending_label = line
            pending_base_url = ""
            pending_model_line = ""
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
        if "绯诲垪" in line or "link" in lower or "dstopology" in lower or line in {"FHL绯诲垪", "DST绯诲垪"}:
            context = line
            continue
        base_match = re.search(r"base\s*url\s*[:：]\s*(https?://\S+)", line, re.I)
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
        urls = url_re.findall(line)
        if not urls:
            continue
        for base_url in urls:
            _append_model_doc_candidate(found, seen, label=line, context=context, base_url=base_url)
    return found


def _merge_model_doc_connections() -> dict[str, Any]:
    text, error = _read_feishu_model_doc_text()
    if error:
        error = _human_feishu_reader_error(error)
        return {"ok": False, "error": error, "added": [], "candidates": [], "count": 0}
    candidates = _extract_model_doc_connections(text)
    raw_data = _read_json(MODEL_CONNECTION_LIBRARY_FILE, {})
    if isinstance(raw_data, dict):
        candidate_ids = {
            _connection_id(f"{item['role']}-{item['provider']}-{item['base_url']}-{item['model']}")
            for item in candidates
            if isinstance(item, dict)
        }
        deleted_ids = raw_data.get("deleted_connections") if isinstance(raw_data.get("deleted_connections"), list) else []
        cleaned_deleted_ids = [item for item in deleted_ids if _connection_id(str(item or "")) not in candidate_ids]
        if cleaned_deleted_ids != deleted_ids:
            raw_data["deleted_connections"] = cleaned_deleted_ids
            _write_json(MODEL_CONNECTION_LIBRARY_FILE, raw_data)
    data = _read_model_connection_library()
    existing = {
        (_model_connection_role(str(item.get("role") or "")), str(item.get("base_url") or "").rstrip("/"), str(item.get("model") or ""))
        for item in data.get("connections", [])
        if isinstance(item, dict)
    }
    existing_url_keys = {
        (_normalized_connection_base_key(item.get("base_url")), _connection_key_value(item))
        for item in data.get("connections", [])
        if isinstance(item, dict) and _connection_key_value(item)
    }
    deleted_fingerprints = _deleted_connection_fingerprints(data)
    added: list[dict[str, str]] = []
    connections = data.get("connections") if isinstance(data.get("connections"), list) else []
    priority = max([int(item.get("priority") or 0) for item in connections if isinstance(item, dict)] or [0]) + 10
    deleted_ids = data.get("deleted_connections") if isinstance(data.get("deleted_connections"), list) else []
    changed = False
    for candidate in candidates:
        key = (_model_connection_role(candidate["role"]), candidate["base_url"].rstrip("/"), candidate["model"])
        candidate_secret = str(candidate.get("api_key") or "").strip()
        if candidate_secret and _connection_url_key_fingerprint({"base_url": candidate.get("base_url")}, candidate_secret) in deleted_fingerprints:
            continue
        matching_url_key = [
            item for item in connections
            if (
                isinstance(item, dict)
                and candidate_secret
                and _normalized_connection_base_key(item.get("base_url")) == _normalized_connection_base_key(candidate.get("base_url"))
                and _connection_key_value(item) == candidate_secret
            )
        ]
        if matching_url_key:
            for item in matching_url_key:
                old_key_name = str(item.get("key_name") or _key_for_connection_role(str(item.get("role") or "")))
                cid = _connection_id(str(item.get("id") or ""))
                item["role"] = candidate["role"]
                item["name"] = candidate["name"]
                item["provider"] = candidate["provider"]
                item["base_url"] = candidate["base_url"]
                item["model"] = candidate["model"]
                item["key_name"] = _key_for_connection_role(candidate["role"])
                item["source"] = str(candidate.get("source") or MODEL_DOC_SOURCE_URL)
                changed = True
                new_key_name = str(item.get("key_name") or old_key_name)
                if cid and old_key_name != new_key_name and not _read_secret(_connection_secret_path(cid, new_key_name)):
                    _write_secret(_connection_secret_path(cid, new_key_name), candidate_secret)
            existing_url_keys.add((_normalized_connection_base_key(candidate.get("base_url")), candidate_secret))
            existing.add(key)
            continue
        if candidate_secret and (_normalized_connection_base_key(candidate.get("base_url")), candidate_secret) in existing_url_keys:
            continue
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
        if cid in deleted_ids:
            deleted_ids = [item for item in deleted_ids if _connection_id(str(item or "")) != cid]
            data["deleted_connections"] = deleted_ids
            changed = True
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
            "source": str(candidate.get("source") or MODEL_DOC_SOURCE_URL),
        })
        if candidate.get("api_key"):
            _write_secret(_connection_secret_path(cid, _key_for_connection_role(candidate["role"])), str(candidate.get("api_key") or ""))
            existing_url_keys.add((_normalized_connection_base_key(candidate.get("base_url")), str(candidate.get("api_key") or "")))
        priority += 10
        added.append({k: v for k, v in candidate.items() if k != "api_key"})
        existing.add(key)
        changed = True
    data["connections"] = connections
    if changed:
        _write_json(MODEL_CONNECTION_LIBRARY_FILE, data)
    _dedupe_model_connection_library()
    public_candidates = [{k: v for k, v in item.items() if k != "api_key"} for item in candidates]
    return {"ok": True, "added": added, "candidates": public_candidates, "count": len(added)}


def _clear_deleted_markers_for_feishu_candidates(candidates: list[dict[str, str]]) -> None:
    data = _read_json(MODEL_CONNECTION_LIBRARY_FILE, {})
    if not isinstance(data, dict):
        return
    candidate_ids = {
        _connection_id(f"{item['role']}-{item['provider']}-{item['base_url']}-{item['model']}")
        for item in candidates
        if isinstance(item, dict)
    }
    candidate_fps = {
        _connection_url_key_fingerprint({"base_url": item.get("base_url")}, str(item.get("api_key") or ""))
        for item in candidates
        if isinstance(item, dict) and item.get("api_key")
    }
    candidate_fps.discard("")
    changed = False
    deleted_ids = data.get("deleted_connections") if isinstance(data.get("deleted_connections"), list) else []
    cleaned_ids = [item for item in deleted_ids if _connection_id(str(item or "")) not in candidate_ids]
    if cleaned_ids != deleted_ids:
        data["deleted_connections"] = cleaned_ids
        changed = True
    deleted_fps = data.get("deleted_connection_fingerprints") if isinstance(data.get("deleted_connection_fingerprints"), list) else []
    cleaned_fps = [item for item in deleted_fps if str(item or "") not in candidate_fps]
    if cleaned_fps != deleted_fps:
        data["deleted_connection_fingerprints"] = cleaned_fps
        changed = True
    if changed:
        _write_json(MODEL_CONNECTION_LIBRARY_FILE, data)


def _prune_connection_library_to_feishu_candidates(candidates: list[dict[str, str]]) -> dict[str, Any]:
    allowed = {
        _connection_url_key_fingerprint({"base_url": item.get("base_url")}, str(item.get("api_key") or ""))
        for item in candidates
        if isinstance(item, dict) and item.get("api_key")
    }
    allowed.discard("")
    if not allowed:
        return {"removed_count": 0, "removed": []}
    data = _read_model_connection_library()
    connections = data.get("connections") if isinstance(data.get("connections"), list) else []
    kept: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    for item in connections:
        if not isinstance(item, dict):
            continue
        fingerprint = _connection_url_key_fingerprint(item)
        if fingerprint and fingerprint not in allowed:
            removed.append(item)
        else:
            kept.append(item)
    if not removed:
        return {"removed_count": 0, "removed": []}
    removed_ids = {_connection_id(str(item.get("id") or "")) for item in removed}
    data["connections"] = kept
    for route_key in ("step_routes", "active_connections"):
        block = data.get(route_key)
        if not isinstance(block, dict):
            continue
        for key, value in list(block.items()):
            if isinstance(value, list):
                block[key] = [x for x in value if _connection_id(str(x or "")) not in removed_ids]
            elif _connection_id(str(value or "")) in removed_ids:
                block.pop(key, None)
    deleted = data.get("deleted_connections") if isinstance(data.get("deleted_connections"), list) else []
    data["deleted_connections"] = sorted(set([*map(str, deleted), *removed_ids]))
    deleted_fps = data.get("deleted_connection_fingerprints") if isinstance(data.get("deleted_connection_fingerprints"), list) else []
    removed_fps = [_connection_url_key_fingerprint(item) for item in removed]
    data["deleted_connection_fingerprints"] = sorted(set([*map(str, deleted_fps), *[fp for fp in removed_fps if fp]]))
    _repair_active_model_connections(data)
    _write_json(MODEL_CONNECTION_LIBRARY_FILE, data)
    return {
        "removed_count": len(removed),
        "removed": [_connection_public_item(item) for item in removed],
    }


def _align_connection_library_to_feishu_candidates(candidates: list[dict[str, str]]) -> dict[str, Any]:
    candidate_by_fp = {
        _connection_url_key_fingerprint({"base_url": item.get("base_url")}, str(item.get("api_key") or "")): item
        for item in candidates
        if isinstance(item, dict) and item.get("api_key")
    }
    candidate_by_fp.pop("", None)
    if not candidate_by_fp:
        return {"aligned_count": 0}
    data = _read_model_connection_library()
    changed = False
    aligned = 0
    for item in data.get("connections", []):
        if not isinstance(item, dict):
            continue
        candidate = candidate_by_fp.get(_connection_url_key_fingerprint(item))
        if not candidate:
            continue
        desired = {
            "role": candidate["role"],
            "name": candidate["name"],
            "provider": candidate["provider"],
            "base_url": candidate["base_url"],
            "model": candidate["model"],
            "key_name": _key_for_connection_role(candidate["role"]),
            "source": str(candidate.get("source") or MODEL_DOC_SOURCE_URL),
        }
        for key, value in desired.items():
            if item.get(key) != value:
                item[key] = value
                changed = True
        cid = _connection_id(str(item.get("id") or ""))
        candidate_secret = str(candidate.get("api_key") or "")
        new_key_name = str(item.get("key_name") or _key_for_connection_role(str(item.get("role") or "")))
        if cid and candidate_secret and not _read_secret(_connection_secret_path(cid, new_key_name)):
            _write_secret(_connection_secret_path(cid, new_key_name), candidate_secret)
        aligned += 1
    if changed:
        _write_json(MODEL_CONNECTION_LIBRARY_FILE, data)
    return {"aligned_count": aligned}


def _repair_missing_connection_keys_from_feishu() -> dict[str, Any]:
    text, error = _read_feishu_model_doc_text()
    if error:
        text = ""
    keyed_candidates = [item for item in _extract_model_doc_connections(text or "") if item.get("api_key")]
    if keyed_candidates:
        _clear_deleted_markers_for_feishu_candidates(keyed_candidates)
    before = _read_model_connection_library()
    before_count = len([item for item in before.get("connections", []) if isinstance(item, dict)])
    _dedupe_model_connection_library()
    after_dedupe = _read_model_connection_library()
    dedupe_count = len([item for item in after_dedupe.get("connections", []) if isinstance(item, dict)])

    before_missing = {
        _connection_id(str(item.get("id") or ""))
        for item in after_dedupe.get("connections", [])
        if isinstance(item, dict) and not _connection_has_key(item)
    }
    merge = _merge_model_doc_connections()
    if not merge.get("ok"):
        return {
            "ok": False,
            "error": str(merge.get("error") or "飞书模型文档读取失败"),
            "duplicates_removed": max(0, before_count - dedupe_count),
            "filled": [],
            "still_missing": [
                _connection_public_item(item)
                for item in after_dedupe.get("connections", [])
                if isinstance(item, dict) and _connection_id(str(item.get("id") or "")) in before_missing
            ],
        }

    data = _read_model_connection_library()
    changed = False
    verified: list[dict[str, Any]] = []
    updated: list[dict[str, Any]] = []
    for item in data.get("connections", []):
        if not isinstance(item, dict):
            continue
        role = _model_connection_role(str(item.get("role") or ""))
        model = str(item.get("model") or "").strip().lower()
        base_url = _normalized_connection_base_key(item.get("base_url"))
        key_name = str(item.get("key_name") or _key_for_connection_role(role))
        current_key = _connection_key_value(item)
        match = None
        for candidate in keyed_candidates:
            candidate_role = _model_connection_role(str(candidate.get("role") or ""))
            candidate_model = str(candidate.get("model") or "").strip().lower()
            if candidate_model != model or _normalized_connection_base_key(candidate.get("base_url")) != base_url:
                continue
            if candidate_role == role:
                match = candidate
                break
            if role in {"text", "gpt_pro", "polish"} and candidate_role in {"text", "gpt_pro"} and model.startswith("gpt"):
                match = candidate
                break
        if match:
            cid = _connection_id(str(item.get("id") or ""))
            candidate_key = str(match.get("api_key") or "")
            if current_key != candidate_key:
                _write_secret(_connection_secret_path(cid, key_name), candidate_key)
                updated.append(_connection_public_item(item))
                changed = True
            else:
                verified.append(_connection_public_item(item))
    if changed:
        _write_json(MODEL_CONNECTION_LIBRARY_FILE, data)
    pruned = _prune_connection_library_to_feishu_candidates(keyed_candidates)
    aligned = _align_connection_library_to_feishu_candidates(keyed_candidates)
    _dedupe_model_connection_library()
    data = _read_model_connection_library()

    filled: list[dict[str, Any]] = []
    still_missing: list[dict[str, Any]] = []
    for item in data.get("connections", []):
        if not isinstance(item, dict):
            continue
        cid = _connection_id(str(item.get("id") or ""))
        public = _connection_public_item(item)
        if cid in before_missing and public.get("key_configured"):
            filled.append(public)
        elif not public.get("key_configured"):
            still_missing.append(public)
    if filled:
        _apply_connection_library_to_defaults(mark_changed=True)
    return {
        "ok": True,
        "duplicates_removed": max(0, before_count - dedupe_count),
        "filled": filled,
        "updated": updated,
        "verified": verified,
        "still_missing": still_missing,
        "added_count": int(merge.get("count") or 0),
        "candidate_count": len(merge.get("candidates") or []),
        "pruned_count": int(pruned.get("removed_count") or 0),
        "pruned": pruned.get("removed") or [],
        "aligned_count": int(aligned.get("aligned_count") or 0),
        "model_connection_library": _public_model_connection_library(data),
    }


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


def _attach_passed_connections_to_failed_steps(failed_steps: list[str]) -> dict[str, Any]:
    data = _read_model_connection_library()
    routes = data.get("step_routes") if isinstance(data.get("step_routes"), dict) else {}
    changed_steps: list[str] = []
    added_route_count = 0
    for step in failed_steps:
        meta = MODEL_STEP_ROUTES.get(step)
        if not meta:
            continue
        allowed_roles = {str(x) for x in (meta.get("roles") or (meta.get("role") or "text",))}
        current = [_connection_id(str(x or "")) for x in routes.get(step, []) if str(x or "")]
        passed = []
        for item in data.get("connections", []):
            if not isinstance(item, dict) or not bool(item.get("enabled", True)):
                continue
            status = _connection_test_status_for(data, item)
            if (item.get("last_test_ok") is True or status.get("last_test_ok") is True) and _model_connection_role(str(item.get("role") or "")) in allowed_roles:
                item = {**item, **status}
                passed.append(item)
        before_count = len(current)
        for item in sorted(passed, key=lambda item: _connection_sort_key(item)):
            cid = _connection_public_id_value(item)
            if cid and cid not in current:
                current.insert(0, cid)
        if len(current) != before_count:
            routes[step] = current
            changed_steps.append(step)
            added_route_count += len(current) - before_count
    data["step_routes"] = routes
    if changed_steps:
        data["user_step_routes"] = {**(data.get("user_step_routes") if isinstance(data.get("user_step_routes"), dict) else {}), **{step: True for step in changed_steps}}
        _write_json(MODEL_CONNECTION_LIBRARY_FILE, data)
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
    attached_passed = _attach_passed_connections_to_failed_steps(failed_steps)
    if int(attached_passed.get("route_count") or 0) > 0:
        repair["changed_steps"] = attached_passed.get("changed_steps", [])
        repair["route_count"] = int(attached_passed.get("route_count") or 0)
        repaired = _test_step_routes()
        repair["retested"] = True
        repair["remaining_failed_steps"] = _failed_step_keys(repaired)
        if not repair["remaining_failed_steps"]:
            repair["ok"] = True
            return {**repaired, "initial_summary": initial.get("summary", []), "repair": repair}
        failed_steps = list(repair["remaining_failed_steps"])
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
    models = _apply_business_steps_to_models(_model_settings())
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
                base_url = _normalized_defaultable_base_url(base_url, DEFAULT_FOREIGN_BASE_URL)
                payload.update({"foreign_base_url": base_url, "culture_text_base_url": base_url, "culture_text_model": model_name, "text_engine": model_name})
                provider = "openai"
            elif role == "gpt_pro":
                base_url = _normalized_defaultable_base_url(base_url, DEFAULT_FOREIGN_BASE_URL)
                payload.update({"gpt_pro_base_url": base_url, "culture_text_model": model_name, "text_engine": model_name})
                provider = "gpt_pro"
            elif role == "polish":
                base_url = (base_url or DEFAULT_DEEPSEEK_BASE_URL).strip().rstrip("/")
                payload.update({"deepseek_base_url": base_url, "culture_polish_base_url": base_url, "culture_polish_model": model_name, "polish_engine": model_name})
                provider = "deepseek"
            elif role == "image":
                base_url = _normalized_defaultable_base_url(base_url, DEFAULT_FOREIGN_BASE_URL)
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
        if provider == "deepseek":
            key, _, from_profile = _read_test_secret("deepseek_api_key", payload)
            if not key:
                message = "所选方案 DeepSeek Key 未配置。" if from_profile else "DeepSeek Key 未配置。"
                return {"ok": False, "message": message, "suggestion": "先粘贴并保存 DeepSeek Key。"}
            model = "deepseek-chat"
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
                timeout=8,
            )
            model_ids = {str(item.get("id") or "") for item in data.get("data", []) if isinstance(item, dict)}
            ok = model in model_ids if model_ids else False
            message = f"绘图模型 {model} {'已在模型列表中' if ok else '未在模型列表中'}。这是模型列表检查，未实际生图；真实生图仍以任务运行结果为准。"
            return {"ok": ok, "message": message, "model": model, "endpoint": culture_image_base, "available_models": sorted(model_ids)[:20], "list_only": True}
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
        _ = started
def _record_connection_test_result(connection_id: str, result: dict[str, Any]) -> dict[str, Any]:
    cid = _connection_id(connection_id)
    if not cid:
        return _public_model_connection_library()
    tested_public = _connection_by_id(_read_model_connection_library(), cid) or {}
    tested_role = _model_connection_role(str(tested_public.get("role") or ""))
    tested_base = _normalized_connection_base_key(tested_public.get("base_url"))
    tested_model = str(tested_public.get("model") or "").strip().lower()
    data = _read_json(MODEL_CONNECTION_LIBRARY_FILE, {})
    if not isinstance(data, dict):
        data = {}
    connections = data.get("connections") if isinstance(data.get("connections"), list) else []
    statuses = data.get("connection_test_status") if isinstance(data.get("connection_test_status"), dict) else {}
    status_payload = {
        "last_test_ok": bool(result.get("ok")),
        "last_tested_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "last_test_message": str(result.get("message") or "")[:240],
    }
    elapsed = result.get("elapsed_seconds")
    try:
        status_payload["latency_ms"] = int(float(elapsed) * 1000)
    except Exception:
        pass
    statuses[cid] = status_payload
    data["connection_test_status"] = statuses
    changed = False
    for item in connections:
        if not isinstance(item, dict):
            continue
        item_role = _model_connection_role(str(item.get("role") or ""))
        item_base = _normalized_connection_base_key(item.get("base_url"))
        item_model = str(item.get("model") or "").strip().lower()
        same_public = _same_connection_id(item, cid)
        same_route = bool(tested_role and item_role == tested_role and item_base == tested_base and item_model == tested_model)
        if same_public or same_route:
            item.update(status_payload)
            changed = True
    data["connections"] = connections
    if status_payload.get("last_test_ok") is True and tested_role:
        active = data.get("active_connections") if isinstance(data.get("active_connections"), dict) else {}
        active[tested_role] = cid
        for step, meta in MODEL_STEP_ROUTES.items():
            allowed = {str(x) for x in (meta.get("roles") or (meta.get("role") or "text",))}
            if tested_role in allowed:
                active[step] = cid
        data["active_connections"] = active
        _sync_step_routes_from_active(data)
    _write_json(MODEL_CONNECTION_LIBRARY_FILE, data)
    if status_payload.get("last_test_ok") is True:
        _apply_connection_library_to_defaults(mark_changed=True)
    return _public_model_connection_library(_read_model_connection_library())


MODEL_TEST_PROVIDERS = [
    ("openai", "GPT 鏂囨湰"),
    ("gpt_pro", "GPT-Pro"),
    ("deepseek", "DeepSeek 娑﹁壊"),
    ("image", "gpt-image-2 鐢熷浘"),
    ("minimax", "MiniMax 閰嶉煶/BGM"),
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
    passed_by_step: dict[str, str] = {}
    for step in MODEL_STEP_ORDER:
        meta = MODEL_STEP_ROUTES[step]
        routes = data.get("step_routes") if isinstance(data.get("step_routes"), dict) else {}
        ids = [str(x or "") for x in routes.get(step, []) if str(x or "")]
        ids_to_test = ids
        step_results: list[dict[str, Any]] = []
        passed: dict[str, Any] | None = None
        for cid in ids_to_test:
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
                passed_by_step[step] = cid
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
    if passed_by_step:
        _promote_passed_step_connections(passed_by_step)
    return {"results": results, "summary": summary}


def _test_model_library_connections() -> dict[str, Any]:
    data = _read_model_connection_library()
    connections = data.get("connections") if isinstance(data.get("connections"), list) else []
    test_items: list[dict[str, Any]] = []
    for item in connections:
        if not isinstance(item, dict) or not bool(item.get("enabled", True)):
            continue
        cid = _connection_id(str(item.get("id") or ""))
        if not cid:
            continue
        test_items.append(item)

    def run_one(item: dict[str, Any]) -> dict[str, Any]:
        cid = _connection_id(str(item.get("id") or ""))
        result = _test_model_detailed(str(item.get("provider") or ""), {"connection_id": cid})
        _record_connection_test_result(cid, result)
        return {"connection_id": cid, "name": _clean_public_text(item.get("name") or cid), **result}

    results: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        future_map = {executor.submit(run_one, item): item for item in test_items}
        for future in concurrent.futures.as_completed(future_map):
            item = future_map[future]
            cid = _connection_id(str(item.get("id") or ""))
            try:
                row = future.result()
            except Exception as exc:
                row = {
                    "connection_id": cid,
                    "name": _clean_public_text(item.get("name") or cid),
                    "provider": str(item.get("provider") or ""),
                    "model": str(item.get("model") or ""),
                    "ok": False,
                    "message": _safe_error(exc),
                    "elapsed_seconds": 0,
                }
                _record_connection_test_result(cid, row)
            results.append(row)

    summary_by_model: dict[str, dict[str, Any]] = {}
    for row in results:
        item = _connection_by_id(data, str(row.get("connection_id") or "")) or {}
        model = str(row.get("model") or item.get("model") or "未设置")
        group = summary_by_model.setdefault(model, {"model": model, "tested_count": 0, "passed_count": 0, "failed_count": 0, "failures": []})
        group["tested_count"] += 1
        if row.get("ok"):
            group["passed_count"] += 1
        else:
            group["failed_count"] += 1
            if len(group["failures"]) < 6:
                group["failures"].append({
                    "name": row["name"],
                    "provider": str(row.get("provider") or item.get("provider") or ""),
                    "message": str(row.get("message") or ""),
                    "model": model,
                })
    summary = sorted(summary_by_model.values(), key=lambda x: str(x.get("model") or ""))
    return {"results": results, "summary": summary, "model_connection_library": _public_model_connection_library()}


def _promote_passed_step_connections(passed_by_step: dict[str, str]) -> None:
    data = _read_model_connection_library()
    routes = data.get("step_routes") if isinstance(data.get("step_routes"), dict) else {}
    active = data.get("active_connections") if isinstance(data.get("active_connections"), dict) else {}
    changed = False
    for step, raw_cid in passed_by_step.items():
        cid = _connection_id(str(raw_cid or ""))
        item = _connection_by_id(data, cid)
        if not cid or not item:
            continue
        current = [_connection_id(str(x or "")) for x in routes.get(step, []) if str(x or "")]
        promoted = [cid, *[x for x in current if x != cid]]
        if promoted != current:
            routes[step] = promoted
            changed = True
        role = _model_connection_role(str(item.get("role") or MODEL_STEP_ROUTES.get(step, {}).get("role") or "text"))
        if active.get(role) != cid:
            active[role] = cid
            changed = True
        if active.get(step) != cid:
            active[step] = cid
            changed = True
    if changed:
        data["step_routes"] = routes
        data["active_connections"] = active
        _write_json(MODEL_CONNECTION_LIBRARY_FILE, data)


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


EMAIL_PROFILE_KEYS = ("culture", "daily_research_digest", "science", "local")


def _normalize_email_profiles(value: Any) -> dict[str, dict[str, Any]]:
    source = value if isinstance(value, dict) else {}
    profiles: dict[str, dict[str, Any]] = {}
    for key in EMAIL_PROFILE_KEYS:
        raw = source.get(key) if isinstance(source.get(key), dict) else {}
        profiles[key] = {
            "email_enabled": bool(raw.get("email_enabled", raw.get("enabled", False))),
            "email_recipient": str(raw.get("email_recipient", raw.get("recipient", "")) or "").strip(),
        }
    return profiles


def _email_profile_for_payload(payload: dict[str, Any], module_key: str) -> dict[str, Any]:
    profiles = _normalize_email_profiles(payload.get("email_profiles"))
    profile = profiles.get(module_key) or profiles["culture"]
    fallback_enabled = bool(payload.get("email_enabled"))
    fallback_recipient = str(payload.get("email_recipient") or "").strip()
    return {
        "email_enabled": bool(profile.get("email_enabled", fallback_enabled)),
        "email_recipient": str(profile.get("email_recipient") or fallback_recipient).strip(),
    }


def _public_settings() -> dict[str, Any]:
    settings = _read_json(SETTINGS_FILE, {})
    models = _apply_connection_library_to_defaults()
    if isinstance(models, dict):
        models = _models_with_url_defaults(_strip_private_model_fields(models))
    if isinstance(settings, dict) and not str(settings.get("auto_clip_bgm_library_dir") or "").strip():
        settings = {**settings, "auto_clip_bgm_library_dir": str(BGM_LIBRARY_DIR)}
    if isinstance(settings, dict):
        settings = {**settings, "email_profiles": _normalize_email_profiles(settings.get("email_profiles"))}
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
        "culture_clip_image_dir", "culture_clip_lrc_dir", "culture_clip_output_dir", "culture_clip_bgm",
        "research_clip_image_dir", "research_clip_lrc_dir", "research_clip_output_dir", "research_clip_bgm",
        "science_clip_image_dir", "science_clip_lrc_dir", "science_clip_output_dir", "science_clip_bgm",
        "local_clip_image_dir", "local_clip_lrc_dir", "local_clip_output_dir", "local_clip_bgm",
        "science_pdf_path", "science_out_dir",
    }
    for key in allowed:
        if key in payload:
            current[key] = str(payload.get(key) or "")
    if "email_profiles" in payload:
        current["email_profiles"] = _normalize_email_profiles(payload.get("email_profiles"))
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
    return active_id or "鏈€夋嫨"


def _model_usage_summary(models: dict[str, Any] | None = None) -> dict[str, str]:
    models = _models_with_url_defaults(_apply_business_steps_to_models(models or _model_settings()))
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


def _connection_public_config(connection: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(connection, dict):
        return {}
    public = _connection_public_item(connection)
    cfg = {
        "id": public.get("id", ""),
        "name": public.get("name", ""),
        "role": public.get("role", ""),
        "role_label": public.get("role_label", ""),
        "provider": public.get("provider", ""),
        "base_url": public.get("base_url", ""),
        "model": public.get("model", ""),
        "key_name": public.get("key_name", ""),
        "key_configured": bool(public.get("key_configured")),
        "last_tested_at": public.get("last_tested_at", ""),
        "latency_ms": int(public.get("latency_ms") or 0),
    }
    if "last_test_ok" in public:
        cfg["last_test_ok"] = bool(public.get("last_test_ok"))
    return cfg


def _business_step_model_snapshot(data: dict[str, Any] | None = None) -> dict[str, Any]:
    data = _apply_connection_test_status(data or _read_model_connection_library())
    routes = data.get("step_routes") if isinstance(data.get("step_routes"), dict) else {}
    snapshot: dict[str, Any] = {}
    for step in MODEL_STEP_ORDER:
        meta = MODEL_STEP_ROUTES.get(step, {})
        route_ids = [_connection_id(str(x or "")) for x in routes.get(step, []) if str(x or "")]
        candidates: list[dict[str, Any]] = []
        for cid in route_ids:
            item = _connection_by_id(data, cid)
            if item:
                cfg = _connection_public_config(item)
                if cfg:
                    candidates.append(cfg)
        selected = _best_connection_for_step(step, data)
        snapshot[step] = {
            "step": step,
            "label": str(meta.get("label") or step),
            "allowed_roles": list(meta.get("roles") or (meta.get("role") or "" ,)),
            "selected": _connection_public_config(selected),
            "candidates": candidates,
        }
    return snapshot


def _apply_business_steps_to_models(models: dict[str, Any] | None = None) -> dict[str, Any]:
    result = dict(models or _model_settings())
    steps = _business_step_model_snapshot()

    def selected(step: str) -> dict[str, Any]:
        item = (steps.get(step) or {}).get("selected")
        return item if isinstance(item, dict) else {}

    text = selected("script_text")
    research = selected("research_text") or text
    polish = selected("polish_text")
    image = selected("image_generation")
    voice = selected("voice_bgm")
    if text:
        base = str(text.get("base_url") or "")
        model = str(text.get("model") or "")
        provider = str(text.get("provider") or "openai")
        result.update({"foreign_base_url": base, "gpt_base_url": base, "culture_text_base_url": base, "culture_text_provider": provider, "culture_text_model": model, "text_engine": model})
    if research:
        result["research_text_base_url"] = str(research.get("base_url") or result.get("culture_text_base_url") or "")
        if research.get("model"):
            result["text_engine"] = str(research.get("model") or result.get("text_engine") or "")
    if polish:
        provider = str(polish.get("provider") or "deepseek")
        base = str(polish.get("base_url") or "")
        model = str(polish.get("model") or "")
        result.update({"culture_polish_base_url": base, "research_polish_base_url": base, "culture_polish_provider": provider, "culture_polish_model": model, "polish_engine": model})
        if provider == "deepseek" or "deepseek" in model.lower():
            result["deepseek_base_url"] = base
        else:
            result["gpt_pro_base_url"] = base
    if image:
        base = str(image.get("base_url") or "")
        model = str(image.get("model") or "")
        provider = str(image.get("provider") or "openai")
        result.update({"gpt_image_base_url": base, "culture_image_base_url": base, "research_image_base_url": base, "culture_image_provider": "openai" if provider == "image" else provider, "culture_image_model": model, "image_engine": model})
    if voice:
        result["minimax_base_url"] = _minimax_base_url(str(voice.get("base_url") or ""))
        result["minimax_tts_model"] = str(voice.get("model") or result.get("minimax_tts_model") or "speech-2.8-hd")
    result["business_steps"] = steps
    return result


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
    target_secret_dir = root / ".model_connection_library"
    if MODEL_CONNECTION_SECRET_DIR.exists():
        for src in MODEL_CONNECTION_SECRET_DIR.glob("*/*.txt"):
            value = src.read_text(encoding="utf-8", errors="replace").strip()
            if not value:
                continue
            try:
                rel = src.relative_to(MODEL_CONNECTION_SECRET_DIR)
            except Exception:
                continue
            target = target_secret_dir / rel
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
    models = _models_with_url_defaults(_apply_business_steps_to_models(models or _apply_connection_library_to_defaults(mark_changed=False)))
    summary = _model_usage_summary(models)
    snapshot = {
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "profile": summary["profile"],
        "models": summary,
        "business_steps": models.get("business_steps") or _business_step_model_snapshot(),
        "key_status": _secret_statuses(),
        "key_files": {key: str(path) for key, path in MODEL_KEY_FILES.items()},
        "note": "No plaintext keys are stored in this file.",
    }
    projects = [
        ("assistant", "自媒体小猪理", PROJECT_ROOT),
        ("assistant_dev", "自媒体小猪理开发版", ASSISTANT_DEV_ROOT),
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


def _smoke_test_project_model_config(project_id: str, name: str, root: Path, summary: dict[str, Any]) -> dict[str, Any]:
    env_path = root / ".env.quanlan-model.local"
    json_path = root / ".env.quanlan-model.local.json"
    script = r'''
import json, os, pathlib, sys
root = pathlib.Path(sys.argv[1])
expected = json.loads(sys.argv[2])
env_path = root / ".env.quanlan-model.local"
json_path = root / ".env.quanlan-model.local.json"
if not env_path.exists():
    raise SystemExit("missing .env.quanlan-model.local")
if not json_path.exists():
    raise SystemExit("missing .env.quanlan-model.local.json")
env = {}
for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
    if "=" in line and not line.lstrip().startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
data = json.loads(json_path.read_text(encoding="utf-8", errors="replace"))
models = data.get("models") or {}
business_steps = data.get("business_steps") or {}
required_steps = ["script_text", "research_text", "polish_text", "image_generation", "voice_bgm"]
missing_steps = [step for step in required_steps if not ((business_steps.get(step) or {}).get("selected") or {}).get("model")]
if missing_steps:
    raise SystemExit("business_steps missing: " + ", ".join(missing_steps))
required = {
    "OPENAI_BASE_URL": expected.get("text_base_url"),
    "GPT_IMAGE_BASE_URL": expected.get("image_base_url"),
    "CULTURE_IMAGE_BASE_URL": expected.get("image_base_url"),
    "MINIMAX_BASE_URL": expected.get("minimax_base_url"),
}
missing = [k for k, v in required.items() if v and env.get(k) != v]
if missing:
    raise SystemExit("env mismatch: " + ", ".join(missing))
model_checks = {
    "text_model": expected.get("text_model"),
    "image_model": expected.get("image_model"),
    "polish_model": expected.get("polish_model"),
    "minimax_model": expected.get("minimax_model"),
}
bad_models = [k for k, v in model_checks.items() if v and models.get(k) != v]
if bad_models:
    raise SystemExit("json model mismatch: " + ", ".join(bad_models))
key_status = data.get("key_status") or {}
if not any(bool(v) for k, v in key_status.items() if k.endswith("_configured")):
    raise SystemExit("no configured model key visible to project")
print("项目可读取总控台模型方案；文本=%s；图片=%s；润色=%s；MiniMax=%s" % (
    expected.get("text_model") or "",
    expected.get("image_model") or "",
    expected.get("polish_model") or "",
    expected.get("minimax_model") or "",
))
'''
    try:
        proc = subprocess.run(
            [sys.executable, "-c", script, str(root), json.dumps(summary, ensure_ascii=False)],
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        raw_message = (proc.stdout or proc.stderr or "").strip()
        success_message = (
            f"项目可读取总控台模型方案；文本={summary.get('text_model') or ''}；"
            f"图片={summary.get('image_model') or ''}；润色={summary.get('polish_model') or ''}；"
            f"MiniMax={summary.get('minimax_model') or ''}"
        )
        return {
            "id": project_id,
            "name": name,
            "ok": proc.returncode == 0,
            "env_path": str(env_path),
            "json_path": str(json_path),
            "message": success_message if proc.returncode == 0 else (raw_message or "项目模型方案 smoke test 未返回信息。"),
            "exit_code": proc.returncode,
        }
    except Exception as exc:
        return {"id": project_id, "name": name, "ok": False, "env_path": str(env_path), "json_path": str(json_path), "message": _safe_error(exc)}


def _smoke_test_all_project_model_configs(models: dict[str, Any]) -> list[dict[str, Any]]:
    summary = _model_usage_summary(_models_with_url_defaults(models))
    projects = [
        ("assistant", "自媒体小猪理", PROJECT_ROOT),
        ("assistant_dev", "自媒体小猪理开发版", ASSISTANT_DEV_ROOT),
        ("xiaozhuli", "全澜小猪理", XIAOZHULI_ROOT),
        ("eeg", "脑电分析平台", EEG_ANALYSER_ROOT),
    ]
    return [_smoke_test_project_model_config(project_id, name, root, summary) for project_id, name, root in projects]


def _apply_model_config_to_all_projects() -> dict[str, Any]:
    key_repair_report = _repair_missing_connection_keys_from_feishu()
    route_report = _test_step_routes_with_repair()
    failed_steps = [
        item for item in route_report.get("summary", [])
        if isinstance(item, dict) and not item.get("ok")
    ]
    if failed_steps:
        result = _public_settings()
        result["route_report"] = route_report
        result["key_repair_report"] = key_repair_report
        result["sync_report"] = []
        result["connectivity_report"] = _connectivity_report_from_route_report(route_report)
        result["project_test_report"] = []
        result["apply_log"] = [
            "应用已中止：步骤流程中仍有业务步骤没有测通的候选模型。",
            *[
                f"{item.get('step_label') or item.get('step')}：候选 {item.get('candidate_count') or 0} 个，测通 0 个。请从右侧模型库拖入至少一个已测通连接。"
                for item in failed_steps
            ],
        ]
        result["apply_ok"] = False
        return result
    models = _models_with_url_defaults(_apply_business_steps_to_models(_apply_connection_library_to_defaults(mark_changed=False)))
    _write_json(MODEL_DEFAULTS_FILE, _strip_private_model_fields(models))
    _mark_shared_config_changed()
    sync_report = _sync_shared_model_config_to_projects(models)
    _restart_xiaozhuli_dashboard(takeover=True)
    sync_report = _sync_shared_model_config_to_projects(models)
    test_report = _connectivity_report_from_route_report(route_report)
    project_test_report = _smoke_test_all_project_model_configs(models)
    result = _public_settings()
    result["route_report"] = route_report
    result["key_repair_report"] = key_repair_report
    result["sync_report"] = sync_report
    result["connectivity_report"] = test_report
    result["project_test_report"] = project_test_report
    result["apply_log"] = _build_model_apply_log(result, sync_report, test_report, project_test_report)
    result["apply_ok"] = all(bool(item.get("ok")) for item in sync_report) and all(bool(item.get("ok")) for item in project_test_report)
    return result


def _connectivity_report_from_route_report(route_report: dict[str, Any]) -> list[dict[str, Any]]:
    results = route_report.get("results") if isinstance(route_report.get("results"), list) else []
    passed_by_step: dict[str, dict[str, Any]] = {}
    for item in results:
        if isinstance(item, dict) and item.get("ok") and str(item.get("step") or "") not in passed_by_step:
            passed_by_step[str(item.get("step") or "")] = item
    report: list[dict[str, Any]] = []
    for step in MODEL_STEP_ORDER:
        meta = MODEL_STEP_ROUTES.get(step, {})
        item = passed_by_step.get(step)
        if item:
            report.append({
                "provider": str(item.get("provider") or ""),
                "label": str(meta.get("label") or item.get("label") or step),
                "ok": True,
                "model": str(item.get("model") or ""),
                "endpoint": str(item.get("endpoint") or ""),
                "message": str(item.get("message") or "步骤路线测试通过。"),
            })
        else:
            report.append({
                "provider": str(meta.get("role") or step),
                "label": str(meta.get("label") or step),
                "ok": False,
                "model": "",
                "endpoint": "",
                "message": "该步骤没有测通的候选连接。",
            })
    return report


def _test_all_model_links() -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for provider, label in MODEL_TEST_PROVIDERS:
        result = _test_model_detailed(provider, {})
        results.append({"provider": provider, "label": label, **result})
    return results


def _build_model_apply_log(
    data: dict[str, Any],
    sync_report: list[dict[str, Any]],
    test_report: list[dict[str, Any]],
    project_test_report: list[dict[str, Any]] | None = None,
) -> list[str]:
    models = data.get("models") if isinstance(data.get("models"), dict) else {}
    summary = _model_usage_summary(models)
    lines = [
        f"模型方案已切换：{summary['profile']}",
        f"公共模型：文案生成用 {summary['text_model']} ｜ 图片生成用 {summary['image_model']} ｜ 润色用 {summary['polish_model']} ｜ MiniMax 用 {summary['minimax_model']}",
    ]
    for item in sync_report:
        if item.get("ok"):
            lines.append(
                f"{item.get('name')}已切换{summary['profile']}模型方案；文案生成用{summary['text_model']}；图片生成用{summary['image_model']}；润色用{summary['polish_model']}；本地配置已写入。"
            )
        else:
            lines.append(f"{item.get('name')}同步失败：{item.get('error') or 'unknown'}")
    if test_report:
        lines.append("连通性测试报告：")
        for item in test_report:
            status = "列表检查通过" if item.get("list_only") and item.get("ok") else ("通过" if item.get("ok") else "失败")
            lines.append(
                f"{item.get('label')}：{status} ｜ 模型：{item.get('model') or '未设置'} ｜ URL：{item.get('endpoint') or '未设置'} ｜ {item.get('message') or ''}"
            )
    else:
        lines.append("本次只检测公共配置写入、运行注入和子项目只读防线；未自动发起模型接口请求。")
    if project_test_report:
        lines.append("项目内应用实测：")
        for item in project_test_report:
            status = "成功" if item.get("ok") else "失败"
            lines.append(f"{item.get('name') or item.get('id')} 应用大模型方案{status} ｜ {item.get('message') or ''}")
    lines.append("Key 明文未写入网页日志；子项目本地配置只保存 Key 状态和本机密钥文件引用。")
    return lines
def _entry_html() -> bytes:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>閸忋劍绶舵惔鏃傛暏閹粯甯堕崣?/title>
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
  <a class="boss-home" href="/assistant/#model">缂佺喍绔撮柊宥囩枂</a>
  <div class="wrap">
    <h1>閸忋劍绶舵惔鏃傛暏閹粯甯堕崣?/h1>
    <p class="hint">娑撯偓娑擃亜鍙嗛崣锝囶吀閻炲棜鍤滄刊鎺嶇秼鐏忓繒灏撻悶鍡愨偓浣稿弿濠㈡粌鐨悮顏嗘倞閸滃矁鍓抽悽闈涘瀻閺嬫劕閽╅崣甯幢婢堆勀侀崹?URL閵嗕甫ey閵嗕讣MTP 閸滃矂鈧氨鏁ら崣鍌涙殶閸欘亜婀潻娆撳櫡闁板秶鐤嗛敍灞藉晙閸氬本顒為崚浼存付鐟曚胶娈戞い鍦窗閵?/p>
    <section class="brief">
      <div><span>缂佺喍绔撮柊宥囩枂</span><strong>濡€崇€烽妴涓y閵嗕讣MTP 闂嗗棔鑵戠粻锛勬倞閵?/strong><p>鐎涙劙銆嶉惄顔煎涧娣囨繄鏆€娑撴艾濮熷ù浣衡柤閿涘奔绗夐崘宥夊櫢婢跺秴鐫嶇粈娲偓姘辨暏闁板秶鐤嗛妴?/p></div>
      <div><span>鎼存梻鏁ら幀缁樺付</span><strong>閸氼垰濮╅妴浣瑰ⅵ瀵偓閵嗕礁鎮撳銉ヮ樋娑擃亪銆嶉惄顔衡偓?/strong><p>閹碘偓閺堝绨查悽銊ュ弳閸欙絾鏂侀崷銊ユ倱娑撯偓娑擃亝甯堕崚璺哄酱閿涘奔绗夐棁鈧憰浣筋唶缁旑垰褰涢妴?/p></div>
      <div><span>閻樿埖鈧礁褰叉穱?/span><strong>閸欘亝妯夌粈鐑樻喅鐟曚緤绱濇稉宥嗙闂囨彃鐦戦柦銉ｂ偓?/strong><p>閻樿埖鈧焦甯撮崣锝囨暏娴滃氦鐦栭弬顓ㄧ礉妞ょ敻娼版笟褔绮拋銈勭箽閹躲倖鏅遍幇鐔朵繆閹垬鈧?/p></div>
    </section>
    <div class="section-head"><h2>鎼存梻鏁ら幀缁樺付</h2><span id="home_app_summary">濮濓絽婀拠璇插絿鎼存梻鏁ら悩鑸碘偓?/span></div>
    <section class="grid" id="home_app_grid">
      <a class="card" href="/assistant/"><div class="title">閼奉亜鐛熸担鎾崇毈閻氼亞鎮?/div><div class="desc">閸愬懎顔愰悽鐔堕獓閵嗕焦膩閸ㄥ绗?Key閵嗕線鍋栨禒韬测偓浣稿絺鐢啫鎷伴懛顏冪喘閸栨牜娈戦幀缁樺付瀹搞儰缍旈崣鑸偓?/div></a>
      <a class="card" href="/xiaozhuli/"><div class="title">閸忋劍绶剁亸蹇曞皳閻?/div><div class="desc">闁库偓閸烆喚鐓＄拠鍡楃氨閵嗕礁顓归幋宄扮紦鐠侇喓鈧阜ole-play 鐠佹澘缍嶉崪灞炬箛閸旓紕濮搁幀浣碘偓?/div></a>
      <a class="card" href="/eeg/"><div class="title">閼存垹鏁搁崚鍡樼€介獮鍐插酱</div><div class="desc">NeuroCloud EEG 閸掑棙鐎藉ù浣衡柤閸忋儱褰涢敍娑樺敶闁劋绗夌仦鏇犮仛闁氨鏁ゅΟ鈥崇€烽柊宥囩枂閵?/div></a>
    </section>
    <div class="section-head"><h2>闁氨鏁ら柊宥囩枂娑撳氦鐦栭弬?/h2><span>闁板秶鐤嗛崣顏勬躬閹粯甯堕崣鎵樊閹?/span></div>
    <div class="grid">
      <a class="card" href="/assistant/#model"><div class="title">缂佺喍绔村Ο鈥崇€烽柊宥囩枂</div><div class="desc">闁板秶鐤嗘妯款吇閸ヨ棄顦婚弬瑙勵攳閵嗕笍ST 閺傝顢嶉敍灞间簰閸欏﹥鐦℃稉顏吥侀崹瀣畱 URL/Key 娑撳濯烘０鍕啎閿涙稒澧嶉張澶婄摍妞ゅ湱娲伴崗杈╂暏鏉╂瑩鍣烽惃鍕秼閸撳秵鏌熷鍫涒偓?/div></a>
      <a class="card" href="/assistant/#more"><div class="title">鎼存梻鏁ら幀缁樺付娑撳骸浼愰崗?/div><div class="desc">閻╃鎻惔鏃傛暏閻樿埖鈧降鈧線鍋栨禒韬测偓浣藉殰娴兼ê瀵查妴浣稿絺鐢啫鎷扮拠濠冩焽瀹搞儱鍙块妴?/div></a>
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
function keyText(ok){return ok?'<span class="ok">宸查厤缃?/span>':'<span class="missing">鏈厤缃?/span>'}
function applyKeyStatus(sec){sec=sec||{};const map={openai_key_status:"openai_api_key_configured",image_key_status:"image_api_key_configured",gemini_key_status:"gemini_api_key_configured",deepseek_key_status:"deepseek_api_key_configured",minimax_key_status:"minimax_api_key_configured"};for(const [id,k] of Object.entries(map)){if(byId(id))byId(id).innerHTML=keyText(!!sec[k])}for(const [key,prefix] of Object.entries(keyNameMap)){if(key==="smtp_password")continue;const path=sec[key+"_path"]||"";const source=sec[key+"_source"]||"";if(byId(prefix+"_key_path"))byId(prefix+"_key_path").textContent=path?("淇濆瓨浣嶇疆锛?+path+" 锝?鏉ユ簮锛?+source):"淇濆瓨浣嶇疆锛氭湭鎵惧埌"}}
function applyEmailStatus(email){email=email||{};if(byId("smtp_key_status"))byId("smtp_key_status").innerHTML=keyText(!!email.smtp_password_configured);if(byId("smtp_key_path"))byId("smtp_key_path").textContent=email.smtp_password_path?("淇濆瓨浣嶇疆锛?+email.smtp_password_path+" 锝?鏉ユ簮锛?+(email.smtp_password_source||"")):"淇濆瓨浣嶇疆锛氭湭鎵惧埌"}
function renderModelProfileStatus(profile){const el=byId("model_profile_status");if(!el)return;const keys=profile&&profile.keys?profile.keys:{};const names={openai_api_key:"OpenAI",image_api_key:"Image",gemini_api_key:"Gemini",deepseek_api_key:"DeepSeek",minimax_api_key:"MiniMax"};const text=Object.entries(names).map(([k,n])=>n+":"+(keys[k]?"宸插瓨":"鏈瓨")).join(" 锝?");el.textContent="鏂规鐘舵€侊細"+((profile&&profile.id)||"鏈€夋嫨")+" 锝?"+text}
function fieldValue(id){const el=byId(id);return el?String(el.value||""):""}
function profileKeyText(profile,key){return profile&&profile.keys&&profile.keys[key]?"宸插瓨":"鏈瓨"}
function renderRouteSummary(profile){
  const box=byId("model_route_summary");
  if(!box)return;
  if(byId("route_profile_name"))byId("route_profile_name").textContent=profileLabel(profile||{})||"鏈€夋嫨鏂规";
  const rows=[
    ["鏂囧彶鏂囨湰",fieldValue("culture_text_provider"),fieldValue("culture_text_model"),fieldValue("culture_text_base_url"),"OpenAI "+profileKeyText(profile,"openai_api_key")+" / Gemini "+profileKeyText(profile,"gemini_api_key")],
    ["鏂囧彶娑﹁壊",fieldValue("culture_polish_provider"),fieldValue("culture_polish_model"),fieldValue("culture_polish_base_url"),"DeepSeek "+profileKeyText(profile,"deepseek_api_key")],
    ["鏂囧彶鐢熷浘",fieldValue("culture_image_provider"),fieldValue("culture_image_model"),fieldValue("culture_image_base_url"),"Image "+profileKeyText(profile,"image_api_key")],
    ["绉戠爺鏂囨湰","engine",fieldValue("text_engine"),fieldValue("research_text_base_url"),"OpenAI "+profileKeyText(profile,"openai_api_key")+" / Gemini "+profileKeyText(profile,"gemini_api_key")],
    ["绉戠爺娑﹁壊","engine",fieldValue("polish_engine"),fieldValue("research_polish_base_url"),"DeepSeek "+profileKeyText(profile,"deepseek_api_key")],
    ["绉戠爺鍥剧墖","engine",fieldValue("image_engine"),fieldValue("research_image_base_url"),"Image "+profileKeyText(profile,"image_api_key")]
  ];
  box.innerHTML=rows.map(([role,provider,model,url,key])=>'<div class="route-item"><b>'+escapeHtml(role)+'</b><span>'+escapeHtml(provider||"鏈缃?)+' 锝?'+escapeHtml(model||"鏈缃?)+'</span><span>'+escapeHtml(url||"鏈缃?)+'</span><span>'+escapeHtml(key)+'</span></div>').join("");
}
function renderModelProfiles(profiles){
  modelProfiles=profiles||{active_profile:"",profiles:[]};
  const sel=byId("model_profile_select");
  if(sel){
    sel.innerHTML="";
    for(const item of modelProfiles.profiles||[]){
      const opt=document.createElement("option");
      opt.value=item.id;
      opt.textContent=(item.name||item.id)+(item.locked?" 锝?榛樿":"");
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
function profileLabel(profile){return (profile&&profile.name)||((profile&&profile.id)||"鏂规")}
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
      options.push({url,label:profileLabel(profile)+" 锝?"+url});
    }
    sel.innerHTML='<option value="">閫夋嫨宸蹭繚瀛?URL</option>'+options.map(o=>'<option value="'+escapeAttr(o.url)+'">'+escapeHtml(o.label)+'</option>').join("");
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
      button.textContent="搴旂敤姝?Key";
      button.onclick=()=>applyProfileKey(key);
      box.appendChild(select);
      box.appendChild(button);
      card.appendChild(box);
    }
    const sel=byId(prefix+"_key_profile_select");
    const opts=(modelProfiles.profiles||[]).filter(p=>p.keys&&p.keys[key]);
    sel.innerHTML='<option value="">閫夋嫨宸蹭繚瀛?Key</option>'+opts.map(p=>'<option value="'+escapeAttr(p.id)+'">'+escapeHtml(profileLabel(p))+'</option>').join("");
  }
}
function escapeHtml(value){return String(value||"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]))}
function escapeAttr(value){return escapeHtml(value)}
function selectedProfileId(){const sel=byId("model_profile_select");return sel?sel.value:""}
async function loadSettings(){const r=await fetch("/api/settings");const data=await r.json();const s=data.settings||{},m=data.models||{};for(const [k,v] of Object.entries({...s,...m})){if(byId(k))byId(k).value=v||""}renderModelProfiles(data.model_profiles||{});applyKeyStatus(data.secrets||{});applyEmailStatus(data.email_secret||{})}
function restoreDefaultUrls(){for(const id of modelUrlIds){if(byId(id))byId(id).value=defaultForeignBaseUrl}if(byId("deepseek_base_url"))byId("deepseek_base_url").value=defaultDeepseekBaseUrl;const p=(modelProfiles.profiles||[]).find(x=>x.id===selectedProfileId())||{};renderRouteSummary(p);if(byId("status"))status.textContent="妯″瀷鍦板潃宸叉仮澶嶉粯璁わ紝鐐瑰嚮淇濆瓨鍚庣敓鏁?}
function collect(){const ids=["culture_book","culture_out_dir","culture_continue_folder","culture_text_provider","culture_text_model","culture_polish_provider","culture_polish_model","culture_image_provider","culture_image_model","research_out_dir","research_days","research_max_articles","research_journals","research_article_list","text_engine","polish_engine","image_engine","foreign_base_url","deepseek_base_url","culture_text_base_url","culture_polish_base_url","culture_image_base_url","research_text_base_url","research_polish_base_url","research_image_base_url","openai_api_key","image_api_key","gemini_api_key","deepseek_api_key","minimax_api_key","smtp_password","auto_clip_image_dir","auto_clip_lrc_dir","auto_clip_output_dir","auto_clip_bgm","minimax_voice_id","minimax_tts_model","minimax_bgm_model","minimax_bgm_prompt","email_recipient","smtp_host","smtp_port","smtp_user","smtp_sender"];const p={};for(const id of ids){if(byId(id))p[id]=byId(id).value}return p}
function clearSecretInputs(){for(const id of ["openai_api_key","image_api_key","gemini_api_key","deepseek_api_key","minimax_api_key","smtp_password"]){if(byId(id))byId(id).value=""}}
function hideSecret(key){const prefix=keyNameMap[key];visibleSecrets[key]=false;if(prefix&&byId(prefix+"_key_value"))byId(prefix+"_key_value").textContent="宸查殣钘?}
async function toggleSecret(key){const prefix=keyNameMap[key];if(!prefix)return;if(visibleSecrets[key]){hideSecret(key);return}const box=byId(prefix+"_key_value");if(box)box.textContent="璇诲彇涓?..";const r=await fetch("/api/secret?key="+encodeURIComponent(key));const data=await r.json();if(key==="smtp_password"){const email=data.email_secret||{};if(box)box.textContent=email.smtp_password||"鏈厤缃?;applyEmailStatus(email)}else{const sec=data.secrets||{};if(box)box.textContent=sec[key]||"鏈厤缃?;applyKeyStatus(sec)}visibleSecrets[key]=true}
function renderTest(id,result){const el=byId(id);if(!el)return;const ok=result&&result.ok;el.innerHTML=(ok?'<span class="ok">娴嬭瘯閫氳繃</span>':'<span class="missing">娴嬭瘯澶辫触</span>')+" 锝?"+((result&&result.message)||"鏃犵粨鏋?)+((result&&result.suggestion)?(" 锝?寤鸿锛?+result.suggestion):"")}
async function testModel(provider){const id=provider+"_test_result";if(byId(id))byId(id).textContent="娴嬭瘯涓?..";const payload={...collect(),provider};const r=await fetch("/api/test_model",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});const data=await r.json();clearSecretInputs();for(const key of Object.keys(keyNameMap))hideSecret(key);renderTest(id,data.result||{});applyKeyStatus(data.secrets||{});applyEmailStatus(data.email_secret||{})}
async function testEmail(){if(byId("smtp_test_result"))byId("smtp_test_result").textContent="娴嬭瘯涓?..";const r=await fetch("/api/test_email",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(collect())});const data=await r.json();clearSecretInputs();hideSecret("smtp_password");renderTest("smtp_test_result",data.result||{});applyEmailStatus(data.email_secret||{})}
async function saveSettings(){const r=await fetch("/api/settings",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(collect())});const data=await r.json();status.textContent=data.ok?"璁剧疆宸蹭繚瀛?:"淇濆瓨澶辫触";clearSecretInputs();for(const key of Object.keys(keyNameMap))hideSecret(key);renderModelProfiles(data.model_profiles||{});applyKeyStatus(data.secrets||{});applyEmailStatus(data.email_secret||{});return data}
async function applyModelProfile(){const id=selectedProfileId();if(!id){status.textContent="璇峰厛閫夋嫨妯″瀷鏂规";return}status.textContent="姝ｅ湪搴旂敤妯″瀷鏂规...";const r=await fetch("/api/model_profile",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({action:"apply",profile_id:id})});const data=await r.json();if(!data.ok){status.textContent="搴旂敤鏂规澶辫触锛?+(data.error||"unknown");return}clearSecretInputs();for(const key of Object.keys(keyNameMap))hideSecret(key);const s=data.settings||{},m=data.models||{};for(const [k,v] of Object.entries({...s,...m})){if(byId(k))byId(k).value=v||""}renderModelProfiles(data.model_profiles||{});applyKeyStatus(data.secrets||{});applyEmailStatus(data.email_secret||{});status.textContent="妯″瀷鏂规宸插簲鐢?}
async function applyProfileKey(key){const prefix=keyNameMap[key];const sel=prefix?byId(prefix+"_key_profile_select"):null;const profileId=sel?sel.value:"";if(!profileId){status.textContent="璇峰厛閫夋嫨涓€涓凡淇濆瓨 Key";return}status.textContent="姝ｅ湪搴旂敤 Key...";const r=await fetch("/api/model_profile",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({action:"apply_key",profile_id:profileId,key_name:key})});const data=await r.json();if(!data.ok){status.textContent="搴旂敤 Key 澶辫触锛?+(data.error||"unknown");return}clearSecretInputs();hideSecret(key);renderModelProfiles(data.model_profiles||{});applyKeyStatus(data.secrets||{});applyEmailStatus(data.email_secret||{});status.textContent="Key 宸插簲鐢紱鍚勫瓙椤圭洰鍚姩鏃朵細浣跨敤鎬绘帶鍙板綋鍓嶉厤缃?}
async function saveModelProfile(){const name=(byId("model_profile_name")&&byId("model_profile_name").value)||"";const id=selectedProfileId();status.textContent="姝ｅ湪淇濆瓨妯″瀷鏂规...";const r=await fetch("/api/model_profile",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({...collect(),action:"save",profile_id:id,profile_name:name})});const data=await r.json();if(!data.ok){status.textContent="淇濆瓨鏂规澶辫触锛?+(data.error||"unknown");return}clearSecretInputs();for(const key of Object.keys(keyNameMap))hideSecret(key);renderModelProfiles(data.model_profiles||{});applyKeyStatus(data.secrets||{});applyEmailStatus(data.email_secret||{});status.textContent="妯″瀷鏂规宸蹭繚瀛?}
async function deleteModelProfile(){const id=selectedProfileId();if(!id){status.textContent="璇峰厛閫夋嫨妯″瀷鏂规";return}if(id==="foreign-default"){status.textContent="榛樿鏂规涓嶈兘鍒犻櫎";return}const r=await fetch("/api/model_profile",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({action:"delete",profile_id:id})});const data=await r.json();if(!data.ok){status.textContent="鍒犻櫎鏂规澶辫触锛?+(data.error||"unknown");return}renderModelProfiles(data.model_profiles||{});status.textContent="妯″瀷鏂规宸插垹闄?}
async function start(payload){await saveSettings();const r=await fetch("/api/start",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});const data=await r.json();currentJob=data.job_id||"";status.textContent=data.message||"宸插惎鍔?;cmd.textContent=(data.cmd||[]).join(" ");poll()}
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
</html>"""
    return _clean_console_html(body.encode("utf-8"))


def _assistant_html() -> bytes:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>瀵板牊婀侀懘鎴濈摍閻ㄥ嫬鐨悮顏嗘倞 Web</title>
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
<a class="boss-home" href="http://127.0.0.1:8765/">鏉╂柨娲栭幒褍鍩楅崣浼搭浕妞?/a>
<div class="shell">
  <aside>
    <h1>瀵板牊婀侀懘鎴濈摍閻ㄥ嫬鐨悮顏嗘倞 Web</h1>
    <p class="hint">缂佺喍绔撮張顒€婀寸純鎴︺€夐張宥呭閿涙碍鏋冮崣鎻掔毈缁夋ǜ鈧胶顫栭惍鏂垮И閹靛鈧胶顫栫€涳妇绮￠崗鎼炩偓浣藉殰閸斻劌澹€鏉堟垯鈧浇顫囨导妤佺ゴ鐠囨洏鈧浇鍤滄导妯哄閵嗕礁褰傜敮鍐ㄤ紣閸忕兘鍏樻禒搴ょ箹闁插苯鎯庨崝銊ｂ偓?/p>
    <section class="brief">
      <div><span>瑜版挸澧犻悩鑸碘偓?/span><strong>瀹革缚鏅堕弰顖欐崲閸旓繝鍘ょ純顕嗙礉閸欏厖鏅堕弰顖濈箥鐞涘本妫╄箛妞尖偓?/strong><p>濮ｅ繑顐奸崥顖氬З娴犺濮熼崥搴礉閺冦儱绻旀导姘啞鐠囧缍橀悳鏉挎躬鐠烘垵鍩岄崫顏冪濮濄儯鈧?/p></div>
      <div><span>娑撴艾濮熸禒宄扳偓?/span><strong>鐎瑰啯濡搁崘鍛啇閻㈢喍楠囬崣妯诲灇閸欘垵鎷烽煪顏嗘畱濞翠焦鎸夌痪瑁も偓?/strong><p>娴ｇ姴褰叉禒銉ュ灲閺傤厽妲哥槐鐘虫綏缂傚搫銇戦妴浣鼓侀崹瀣６妫版﹫绱濇潻妯绘Ц娴犺濮熷鑼病鐎瑰本鍨氶妴?/p></div>
      <div><span>閻滄澘婀崣顖欎簰閸?/span><strong>閸忓牓鈧鍞寸€瑰湱琚崹瀣剁礉閸愬秴锝炵槐鐘虫綏鐠侯垰绶為敍灞炬付閸氬骸鎯庨崝銊ゆ崲閸斅扳偓?/strong><p>娴犺濮熸潻鎰攽娑擃厺绗夌憰渚€鍣告径宥囧仯閸戣鎯庨崝顭掔幢婵″倿娓堕崑婊勵剾閿涘瞼鏁ら垾婊冧粻濮濄垹缍嬮崜宥勬崲閸斺檧鈧縿鈧?/p></div>
    </section>
    <div class="tabs">
      <button id="tabCulture" onclick="showPanel('culture')">閺傚洤褰?/button>
      <button id="tabResearch" onclick="showPanel('research')">缁夋垹鐖?/button>
      <button id="tabClip" onclick="showPanel('clip')">閸擃亣绶?/button>
      <button id="tabModel" onclick="showPanel('model')">濡€崇€烽弬瑙勵攳缁狅紕鎮?/button>
      <button id="tabMore" onclick="showPanel('more')">閺囨潙顦?/button>
    </div>

    <section id="panelCulture" class="panel active">
      <h2>閺傚洤褰剁亸蹇曨潩</h2>
      <label>娑旓妇鐫?PDF</label><input id="culture_book" placeholder="D:/閻儴鐦?鐠愵偆鈹撻惃鍕拱鐠?pdf">
      <label>鏉堟挸鍤惄顔肩秿</label><input id="culture_out_dir" placeholder="D:/閻儴鐦?鐠愵偆鈹撻惃鍕拱鐠?閻叀顫嬫０鎴犵閺?>
      <label>缂佈呯敾閻╊喖缍?/label><input id="culture_continue_folder" placeholder="閸欘垳鏆€缁?>
      <label>瀵偓婵妯佸▓?/label>
      <select id="culture_stage"><option>outline</option><option>split_pdf</option><option>episode_prompt</option><option>script</option><option>polish</option><option>images</option><option>postprocess</option><option>split_assets</option></select>
      <div class="grid2">
        <div><label>閺傚洦婀?provider</label><select id="culture_text_provider"><option>openai</option><option>gemini</option><option>deepseek</option><option>doubao</option><option>dry-run</option></select></div>
        <div><label>閺傚洦婀板Ο鈥崇€?/label><input id="culture_text_model" placeholder="gpt-5.5"></div>
        <div><label>濞戯箒澹?provider</label><select id="culture_polish_provider"><option>deepseek</option><option>openai</option><option>gemini</option><option>doubao</option><option>dry-run</option></select></div>
        <div><label>濞戯箒澹婂Ο鈥崇€?/label><input id="culture_polish_model" placeholder="gpt-5.5"></div>
        <div><label>閻㈢喎娴?provider</label><select id="culture_image_provider"><option>openai</option><option>gemini</option><option>dry-run</option><option>none</option></select></div>
        <div><label>閻㈢喎娴樺Ο鈥崇€?/label><input id="culture_image_model" placeholder="gpt-image-2"></div>
      </div>
      <label>濞村鐦?B 閸ョ偓鏆?/label><input id="culture_test_b" value="0">
      <div class="row"><button onclick="startCulture(false)">瀵偓婵鏋冮崣鑼晸閹?/button><button onclick="startCulture(true)">濞村鐦?B 閸?/button></div>
      <p class="desc"><b>瀵偓婵鏋冮崣鑼晸閹存劧绱?/b>閹稿缍嬮崜?PDF閵嗕浇绶崙铏规窗瑜版洖鎷板Ο鈥崇€烽崣鍌涙殶鐠烘垵鐣弫瀛樻瀮閸欒尙绀岄弶鎰版懠鐠侯垬鈧?br><b>濞村鐦?B 閸ユ拝绱?/b>閸欘亜顦╅悶鍡楃毌闁?B 閸ユ拝绱濋悽銊︽降韫囶偊鈧喐顥呴弻銉ㄥ壖閺堫兙鈧焦褰佺粈楦跨槤閵嗕胶鏁撻崶鎯ф嫲閸氬骸顦╅悶鍡愨偓?/p>
    </section>

    <section id="panelResearch" class="panel">
      <h2>缁夋垹鐖洪崝鈺傚 / 缁夋垵顒熺紒蹇撳悁</h2>
      <label>鏉堟挸鍤惄顔肩秿</label><input id="research_out_dir" placeholder="閻ｆ瑧鈹栭崚娆庡▏閻劑绮拋銈堢翻閸戣櫣娲拌ぐ?>
      <div class="grid2"><div><label>濡偓缁便垹銇夐弫?/label><input id="research_days" value="14"></div><div><label>閺傚洨鐝烽弫?/label><input id="research_max_articles" value="5"></div></div>
      <label>閺堢喎鍨旈崚妤勩€?/label><input id="research_journals" placeholder="Nature, Science, Neuron...">
      <label>瀹稿弶婀侀弬鍥╁盀濞撳懎宕?/ 缂侇厼浠涢惄顔肩秿</label><input id="research_article_list" placeholder="閸欘垳鏆€缁?>
      <div class="grid2"><div><label>鏂囨湰妯″瀷</label><input id="text_engine" placeholder="gpt-5.5"></div><div><label>娑﹁壊妯″瀷</label><input id="polish_engine" placeholder="DeepSeek Chat锛堝畼鏂规鼎鑹诧級"></div></div>
      <label>閸ュ墽澧栧Ο鈥崇€?/label><input id="image_engine" placeholder="閻㈢喎娴樻稉鎾舵暏閿濇窌PT Image 2">
      <div class="row"><button onclick="startResearch('digest')">濮ｅ繑妫╅惍鏃傗敀闁喖鈧?/button><button onclick="startResearch('article_list')">鐞涖儲鏋冮悮顔界閸?/button><button onclick="startResearch('continue_list')">濞撳懎宕熺紒顓炰粵</button><button onclick="startResearch('resume')">缂侇厼浠涘锝嗘埂</button></div>
      <p class="desc"><b>濮ｅ繑妫╅惍鏃傗敀闁喖鈧帪绱?/b>濡偓缁便垺婀￠崚濠冩瀮閻氼喖鑻熼悽鐔稿灇閻梻鈹掗柅鐔尖偓鎺旂閺夋劑鈧?br><b>鐞涖儲鏋冮悮顔界閸楁洩绱?/b>閸欘亞鏁撻幋鎰灗鐞涖儵缍堥崐娆撯偓澶嬫瀮閻?JSON閿涘奔绗夐悽鐔稿灇缁辩姵娼楅妴?br><b>濞撳懎宕熺紒顓炰粵閿?/b>娴犲骸鍑￠張澶嬫瀮閻氼喗绔婚崡鏇犳埛缂侇厼鍩楁担婊冩倵缂侇厾绀岄弶鎰┾偓?br><b>缂侇厼浠涘锝嗘埂閿?/b>娴犲骸鍑￠張澶嬨€傞張鐔烘窗瑜版洜鎴风紒顓∷夋鎰弓鐎瑰本鍨氬銉╊€冮妴?/p>
      <div class="row"><button onclick="startTool('science')">缁夋垵顒熺紒蹇撳悁鐟欙綀顕?/button><button onclick="startTool('science_test_b')">缁夋垵顒熺紒蹇撳悁濞村鐦?B 閸?/button></div>
      <p class="desc"><b>缁夋垵顒熺紒蹇撳悁鐟欙綀顕伴敍?/b>閸氼垰濮╃粔鎴犵埡閸斺晜澧滈柌宀€娈戠紒蹇撳悁鐠佺儤鏋?缁夋垵顒熼崘鍛啇鐟欙綀顕板ù浣衡柤閵?br><b>缁夋垵顒熺紒蹇撳悁濞村鐦?B 閸ユ拝绱?/b>閻劍娓剁亸?B 閸ラ箖顤傛惔锕€鎻╅柅鐔割梾閺屻儳顫栫€涳妇绮￠崗鍝ユ畱閸ョ偓鏋冮柧鎹愮熅閵?/p>
    </section>

    <section id="panelClip" class="panel">
      <h2>閼奉亜濮╅崜顏囩帆 / BGM</h2>
      <label>閸ュ墽澧栭惄顔肩秿</label><input id="auto_clip_image_dir" placeholder="閸掑棝娉﹂崶鍓у閻╊喖缍?>
      <label>LRC / 闂婃娊顣堕惄顔肩秿</label><input id="auto_clip_lrc_dir" placeholder="鐎涙绠烽幋鏍叾妫版垹娲拌ぐ?>
      <label>鏉堟挸鍤惄顔肩秿</label><input id="auto_clip_output_dir" placeholder="閸欘垳鏆€缁?>
      <label>BGM 閺傚洣娆?閻╊喖缍?/label><input id="auto_clip_bgm" placeholder="閸欘垳鏆€缁?>
      <h2>MiniMax Voice / BGM</h2>
      <label>MiniMax API Key</label><input id="minimax_api_key" type="password" placeholder="saved locally; never shown in logs">
      <div class="status" id="minimax_key_status">MiniMax key: checking...</div>
      <div class="grid2">
        <div><label>Voice ID</label><input id="minimax_voice_id" placeholder="male-qn-qingse"></div>
        <div><label>TTS Model</label><input id="minimax_tts_model" placeholder="speech-2.8-hd"></div>
        <div><label>BGM Model</label><input id="minimax_bgm_model" placeholder="music-2.6"></div>
        <div><label>BGM Prompt</label><input id="minimax_bgm_prompt" placeholder="instrumental, documentary, soft piano"></div>
      </div>
      <div class="row"><button onclick="startClip()">閸氼垰濮╅懛顏勫З閸擃亣绶?/button><button onclick="startBgm()">閻㈢喐鍨?BGM</button></div>
      <p class="desc"><b>閸氼垰濮╅懛顏勫З閸擃亣绶敍?/b>閹?LRC 閻㈠娼扮紓鏍у娇閸栧綊鍘ら崶鍓у閿涘矁鐨熼悽?FFmpeg 閸氬牊鍨氱憴鍡涱暥閵?br><b>閻㈢喐鍨?BGM閿?/b>閺嶈宓佹稊锔剧潉/缁辩姵娼楅幗妯款洣閻㈢喐鍨氭稉鈧弶陇鍎楅弲顖炵叾娑旀劗绀岄弶鎰┾偓?/p>
    </section>

    <section id="panelModel" class="panel">
      <div class="panel-head"><div><h2>濡€崇€烽弬瑙勵攳缁狅紕鎮?/h2><p class="desc">鏉╂瑩鍣风粻锛勬倞閺傝顢嶉惃鍕灡瀵ゆ亽鈧礁顦查崚韬测偓浣锋叏閺€骞库偓浣稿灩闂勩倕鎷版惔鏃傛暏閵嗗倹鐦℃稉顏呮煙濡楀牆鍨庨崚顐＄箽鐎?GPT閵嗕笩PT-Pro閵嗕笩PT-image2閵嗕府iniMax 閻?URL閵嗕焦膩閸ㄥ鎮曢崪?Key閵?/p></div><span class="panel-tag">閺傝顢嶇粻锛勬倞</span></div>
      <div class="section soft">
        <div class="section-title"><h3>閺傝顢嶉幒褍鍩?/h3><span id="model_profile_status">閺傝顢嶉悩鑸碘偓渚婄窗鐠囪褰囨稉?/span></div>
        <div class="grid2">
          <div><label>闁瀚ㄩ弬瑙勵攳</label><select id="model_profile_select"></select></div>
          <div><label>鏂规鍚嶇О</label><input id="model_profile_name" placeholder="渚嬪锛欸reatWall Link 绯诲垪 / DST 绯诲垪 / FHL 绯诲垪"></div>
        </div>
        <div class="row"><button class="secondary" onclick="newModelProfile()">閺傛澘缂撻弬瑙勵攳</button><button class="secondary" onclick="applyModelProfile()">鎼存梻鏁ら幍鈧柅澶嬫煙濡?/button><button onclick="saveModelProfile()">娣囨繂鐡?鐟曞棛娲?/button><button class="danger" onclick="deleteModelProfile()">閸掔娀娅庨弬瑙勵攳</button></div>
      </div>
      <div class="section">
        <div class="section-title"><h3>閺傝顢嶉幗妯款洣</h3><span id="route_profile_name">鐠囪褰囨稉?/span></div>
        <div class="route-summary" id="model_route_summary"></div>
      </div>
      <div class="section">
        <div class="section-title"><h3>濡€崇€烽柊宥囩枂</h3><span>濮ｅ繋閲滃Ο鈥崇€烽崚鍡楀焼闁板秶鐤?URL閵嗕焦膩閸ㄥ鎮曢妴涓y</span></div>
        <div class="grid2">
          <div class="scheme-card"><b>GPT / 閺傚洤褰堕弬鍥ㄦ拱</b><label>URL</label><input id="gpt_base_url" placeholder="https://api.dstopology.com/v1"><label>濡€崇€烽崥?/label><input id="culture_text_model" placeholder="gpt-5.5"><label>Key</label><input id="openai_api_key" type="password" autocomplete="off" placeholder="GPT Key"></div>
          <div class="scheme-card"><b>GPT / 閺傚洤褰跺☉锕佸</b><label>URL</label><input id="deepseek_base_url" placeholder="https://api.dstopology.com/v1"><label>濡€崇€烽崥?/label><input id="culture_polish_model" placeholder="gpt-5.5"><label>Key</label><input id="gpt_pro_api_key" type="password" autocomplete="off" placeholder="GPT Key"></div>
          <div class="scheme-card"><b>GPT-image2 / 閺傚洤褰堕悽鐔锋禈</b><label>URL</label><input id="gpt_image_base_url" placeholder="https://api.dstopology.com/v1"><label>濡€崇€烽崥?/label><input id="culture_image_model" placeholder="gpt-image-2"><label>Key</label><input id="image_api_key" type="password" autocomplete="off" placeholder="GPT-image2 Key"></div>
          <div class="scheme-card"><b>MiniMax / 闁板秹鐓舵稉?BGM</b><label>URL</label><input id="minimax_base_url" placeholder="https://api.53hk.cn"><label>濡€崇€烽崥?/label><input id="minimax_tts_model" placeholder="speech-2.8-hd"><label>Key</label><input id="minimax_api_key" type="password" autocomplete="off" placeholder="MiniMax Key"></div>
        </div>
      </div>
      <div class="section soft">
        <div class="section-title"><h3>娴犺濮熷鏇熸惛閸掝偄鎮?/h3><span>閻劋绨弬鍥у蕉/缁夋垹鐖烘禒璇插閿涘奔绗夐崡鏇犲闁插秴顦茬捄顖滄暠闁板秶鐤?/span></div>
        <div class="grid3">
          <div><label>閺傚洦婀板鏇熸惛</label><input id="text_engine" placeholder="gpt-5.5"></div>
          <div><label>濞戯箒澹婂鏇熸惛</label><input id="polish_engine" placeholder="gpt-5.5"></div>
          <div><label>閸ュ墽澧栧鏇熸惛</label><input id="image_engine" placeholder="GPT-image2"></div>
        </div>
      </div>
    </section>

    <section id="panelMore" class="panel">
      <h2>閺囨潙顦垮銉ュ徔</h2>
      <label>閺€鏈垫闁喚顔?/label><input id="email_recipient" placeholder="婢舵矮閲滈柇顔绢唸閻劑鈧褰块崚鍡涙">
      <div class="grid2"><div><label>SMTP 閺堝秴濮熼崳?/label><input id="smtp_host" placeholder="smtp.qq.com"></div><div><label>SMTP 缁旑垰褰?/label><input id="smtp_port" placeholder="465"></div><div><label>SMTP 鐠愶箑褰?/label><input id="smtp_user" placeholder="闁喚顔堢拹锕€褰?></div><div><label>閸欐垳娆㈡禍?/label><input id="smtp_sender" placeholder="姒涙顓婚崥宀冨閸?></div></div>
      <div class="row"><button onclick="startTool('audience')">鐟欏倷绱ù瀣槸</button><button onclick="startTool('audience_apply')">鐟欏倷绱ù瀣槸楠炶泛绨查悽?/button><button onclick="startTool('self_optimizer_once')">閼奉亙绱崠鏍︾濞?/button><button onclick="startTool('self_optimizer_daemon')">閸氼垰濮╅懛顏冪喘閸栨牕娅?/button></div>
      <p class="desc"><b>鐟欏倷绱ù瀣槸閿?/b>閹殿偅寮块崗顒€绱戠憴鍡涱暥閸?鐠囪鍔熺猾璇插冀妫ｅ牅淇婇崣鍑ょ礉鏉堟挸鍤憴鍌欑船妞嬪酣娅撻幎銉ユ啞閵?br><b>鐟欏倷绱ù瀣槸楠炶泛绨查悽顭掔窗</b>閸︺劏顫囨导妤佺ゴ鐠囨洖鐔€绾偓娑撳﹤鍘戠拋姝屽殰閸斻劌鍟撻崗銉ュ讲鎼存梻鏁ゆ穱顔碱槻閵?br><b>閼奉亙绱崠鏍︾濞嗏槄绱?/b>缁斿宓嗙捄鎴滅鏉烆喛鍤滄导妯哄鐟欏倸鐧傞妴涔簅le-play閵嗕浇顓搁崚鎺戞嫲鐠佹澘缍嶉妴?br><b>閸氼垰濮╅懛顏冪喘閸栨牕娅掗敍?/b>閸氼垰濮╅梹鑳箥鐞?daemon閿涘苯鐣鹃弮鎯邦潎鐎电喖銆嶉惄顔艰嫙閸愭瑥鍙嗛弮銉ョ箶/閻樿埖鈧降鈧?/p>
      <div class="row"><button onclick="startTool('package_update')">閻㈢喐鍨氬ù瀣槸閻楀牊婀伴弴瀛樻煀閸?/button><button onclick="startTool('init_release')">閸掓繂顫愰崠鏍ㄧゴ鐠囨洜澧楅張顒傛窗瑜?/button><button onclick="startTool('model_help')">CLI 閼奉亝顥?/button><button onclick="openXiaozhuli()">閹垫挸绱戠亸蹇曞皳閻炲棗鍞村畵?/button></div>
      <p class="desc"><b>閻㈢喐鍨氬ù瀣槸閻楀牊婀伴弴瀛樻煀閸栧拑绱?/b>閸欘亞鏁撻幋?test 瀵板懏娲块弬?zip閿涘奔绗夋导姘安閻劌鍩岃ぐ鎾冲閺堝秴濮熼妴?br><b>閸掓繂顫愰崠鏍ㄧゴ鐠囨洜澧楅張顒傛窗瑜版洩绱?/b>閸掓稑缂撻幋鏍у灥婵瀵插ù瀣槸閻楀牏娲拌ぐ鏇樷偓鍌氱磻閸欐垹澧楅弰顖氱秼閸撳秵绨惍浣烘窗瑜版洩绱卞ù瀣槸閻楀牏鏁ゆ禍搴ㄧ崣閺€韬测偓?br><b>CLI 閼奉亝顥呴敍?/b>閹垫挸绱戦弬鍥у蕉 CLI help閿涘矂鐛欑拠浣稿弳閸欙絽寮弫鐗堟Ц閸氾附顒滅敮鎼炩偓?br><b>閹垫挸绱戠亸蹇曞皳閻炲棗鍞村畵宀嬬窗</b>閸︺劌缍嬮崜宥嗘箛閸斺€茬瑓娴狅絿鎮婇幍鎾崇磻閸欙缚绔存稉顏勭毈閻氼亞鎮?dashboard閵?/p>
      <p class="hint">閺佸繑鍔?Key 娑撳秴婀純鎴︺€夋稉顓炵潔缁€鎭掆偓鍌浤侀崹瀣嫲 SMTP 閻ㄥ嫮婀＄€圭偠绻涢柅姘ゴ鐠囨洑绻氶悾娆愭拱閸︿即鍘ょ純?閻滎垰顣ㄩ崣姗€鍣洪弬鐟扮础閿涘苯鎮楃紒顓炲讲缂佈呯敾閸嬫矮绗撻梻銊︾ゴ鐠囨洘甯撮崣锝冣偓?/p>
    </section>

    <div class="row"><button class="secondary" onclick="saveSettings()">娣囨繂鐡ㄧ拋鍓х枂</button><button class="danger" onclick="stopJob()">閸嬫粍顒涜ぐ鎾冲娴犺濮?/button></div>
    <div class="status" id="status">瀵板懎鎳?/div><div class="cmd" id="cmd"></div>
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
  setStatus("濡€崇€烽崷鏉挎絻瀹稿弶浠径宥夌帛鐠併倧绱濋悙鐟板毊娣囨繂鐡ㄩ崥搴ｆ晸閺?,"ok");
}
function collect(){const ids=["culture_book","culture_out_dir","culture_continue_folder","culture_text_provider","culture_text_model","culture_polish_provider","culture_polish_model","culture_image_provider","culture_image_model","research_out_dir","research_days","research_max_articles","research_journals","research_article_list","text_engine","polish_engine","image_engine","gpt_base_url","deepseek_base_url","gpt_image_base_url","minimax_base_url","culture_text_base_url","culture_polish_base_url","culture_image_base_url","research_text_base_url","research_polish_base_url","research_image_base_url","openai_api_key","image_api_key","gpt_pro_api_key","minimax_api_key","smtp_password","auto_clip_image_dir","auto_clip_lrc_dir","auto_clip_output_dir","auto_clip_bgm","minimax_voice_id","minimax_tts_model","minimax_bgm_model","minimax_bgm_prompt","email_recipient","smtp_host","smtp_port","smtp_user","smtp_sender"];const p={};for(const id of ids){if(byId(id))p[id]=byId(id).value}return p}
function clearSecretInputs(){for(const id of ["openai_api_key","image_api_key","gpt_pro_api_key","minimax_api_key","smtp_password"]){if(byId(id))byId(id).value=""}}
function hideSecret(key){const prefix=keyNameMap[key];visibleSecrets[key]=false;if(prefix&&byId(prefix+"_key_value"))byId(prefix+"_key_value").textContent="瀹告煡娈ｉ挊?}
async function toggleSecret(key){const prefix=keyNameMap[key];if(!prefix)return;if(visibleSecrets[key]){hideSecret(key);notify("瀹告煡娈ｉ挊蹇旀櫛閹扮喍淇婇幁?,"ok");return}const b=beginAction("濮濓絽婀拠璇插絿閺堫剚婧€鐎靛棝鎸滈悩鑸碘偓?..");try{const box=byId(prefix+"_key_value");if(box)box.textContent="鐠囪褰囨稉?..";const r=await fetch("/api/secret?key="+encodeURIComponent(key));const data=await r.json();if(key==="smtp_password"){const email=data.email_secret||{};if(box)box.textContent=email.smtp_password||"閺堫亪鍘ょ純?;applyEmailStatus(email)}else{const sec=data.secrets||{};if(box)box.textContent=sec[key]||"閺堫亪鍘ょ純?;applyKeyStatus(sec)}visibleSecrets[key]=true;endAction(b,"鐎靛棝鎸滃鑼额嚢閸欐牭绱卞▔銊﹀壈娑撳秷顩﹂崷銊ょ铂娴滃搫褰茬憴浣规鐏炴洜銇?,"ok")}catch(err){failAction(b,err,"鐠囪褰囩€靛棝鎸滄径杈Е")}}
function renderTest(id,result){const el=byId(id);if(!el)return;const ok=result&&result.ok;el.innerHTML=(ok?'<span class="ok">濞村鐦柅姘崇箖</span>':'<span class="missing">濞村鐦径杈Е</span>')+" 閿?"+((result&&result.message)||"閺冪姷绮ㄩ弸?)+((result&&result.suggestion)?(" 閿?瀵ら缚顔呴敍?+result.suggestion):"")}
function appendLogLine(message){const el=byId("log");if(!el)return;const now=new Date().toLocaleTimeString();const current=el.textContent==="暂无日志"?"":el.textContent;el.textContent=(current+"["+now+"] "+message+"\\n").split("\\n").slice(-1000).join("\\n");el.scrollTop=el.scrollHeight}
function clearLog(){const el=byId("log");if(el)el.textContent=""}
function releaseModelSearchFocus(){setTimeout(()=>{const search=byId("model_search");if(search&&document.activeElement===search)search.blur()},0)}
function newModelProfile(){const sel=byId("model_profile_select");if(sel)sel.value="";if(byId("model_profile_name"))byId("model_profile_name").value="";setStatus("瀹告彃鍨忛幑銏犲煂閺傛澘缂撻弬瑙勵攳閿涘苯褰查惄瀛樺复缂傛牞绶崥搴濈箽鐎?,"ok")}
function testMeta(provider,payload){const map={openai:{label:"GPT",model:payload.culture_text_model||payload.text_engine||"gpt-5.5",url:payload.culture_text_base_url||payload.foreign_base_url},image:{label:"GPT-image2",model:payload.culture_image_model||payload.image_engine||"gpt-image-2",url:payload.culture_image_base_url||payload.foreign_base_url},gpt_pro:{label:"娑﹁壊鏂囨湰",model:payload.culture_polish_model||payload.polish_engine||"gpt-5.5",url:payload.culture_polish_base_url||payload.gpt_base_url||payload.foreign_base_url},minimax:{label:"MiniMax",model:payload.minimax_tts_model||"speech-2.8-hd",url:payload.minimax_base_url||defaultMiniMaxBaseUrl}};return map[provider]||{label:provider,model:"",url:""}}
function logTestResult(meta,result){const ok=result&&result.ok;appendLogLine((ok?"闁俺绻?":"婢惰精瑙?")+meta.label+" 閿?model="+(result.model||meta.model||"閺堫亣顔曠純?)+" 閿?url="+(result.endpoint||meta.url||"閺堫亣顔曠純?)+" 閿?"+((result&&result.message)||"閺冪姷绮ㄩ弸?));if(result&&result.suggestion)appendLogLine("瀵ら缚顔?"+meta.label+" 閿?"+result.suggestion)}
async function runModelTest(provider,{batch=false}={}){const id=provider+"_test_result";const payload={...collect(),provider,profile_id:selectedProfileId()};const meta=testMeta(provider,payload);if(byId(id))byId(id).textContent="濞村鐦稉?..";appendLogLine("瀵偓婵绁寸拠?"+meta.label+" 閿?閺傝顢?"+selectedProfileName()+" 閿?model="+(meta.model||"閺堫亣顔曠純?)+" 閿?url="+(meta.url||"閺堫亣顔曠純?));const r=await fetch("/api/test_model",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});const data=await r.json();clearSecretInputs();for(const key of Object.keys(keyNameMap))hideSecret(key);const result=data.result||{};renderTest(id,result);applyKeyStatus(data.secrets||{});applyEmailStatus(data.email_secret||{});logTestResult(meta,result);if(!batch)setStatus(result.ok?"濡€崇€峰ù瀣槸闁俺绻?:"濡€崇€峰ù瀣槸婢惰精瑙﹂敍?+(result.message||"鐠囬婀呴崣鍏呮櫠閺冦儱绻?),result.ok?"ok":"error");return result}
async function testModel(provider){const b=beginAction("濮濓絽婀ù瀣槸濡€崇€锋潻鐐衡偓姘偓?..");try{const result=await runModelTest(provider);endAction(b,result.ok?"濡€崇€峰ù瀣槸闁俺绻?:"濡€崇€峰ù瀣槸婢惰精瑙﹂敍?+(result.message||"鐠囬婀呴崣鍏呮櫠閺冦儱绻?),result.ok?"ok":"error")}catch(err){appendLogLine("瀵倸鐖?濡€崇€峰ù瀣槸 閿?"+((err&&err.message)||err||"unknown"));failAction(b,err,"濡€崇€峰ù瀣槸婢惰精瑙?)}}
async function testAllModels(){const b=beginAction("濮濓絽婀ù瀣槸閸忋劑鍎村Ο鈥崇€烽柧鐐复...");appendLogLine("==== 瀵偓婵绁寸拠鏇炲弿闁劍膩閸ㄥ鎽奸幒?閿?閺傝顢?"+selectedProfileName()+" ====");let okCount=0;const plan=["openai","image","gpt_pro","minimax"];try{for(const provider of plan){const result=await runModelTest(provider,{batch:true});if(result&&result.ok)okCount++}const allOk=okCount===plan.length;appendLogLine("==== 閸忋劑鍎村Ο鈥崇€烽柧鐐复濞村鐦€瑰本鍨?閿?闁俺绻?"+okCount+"/"+plan.length+" ====");endAction(b,allOk?"閸忋劑鍎村Ο鈥崇€烽柧鐐复濞村鐦柅姘崇箖":"濡€崇€烽柧鐐复濞村鐦€瑰本鍨氶敍宀勫劥閸掑棗銇戠拹銉礉鐠囬婀呴崣鍏呮櫠閺冦儱绻?,allOk?"ok":"error")}catch(err){appendLogLine("瀵倸鐖?閸忋劑鍎村Ο鈥崇€烽柧鐐复濞村鐦?閿?"+((err&&err.message)||err||"unknown"));failAction(b,err,"閸忋劑鍎村Ο鈥崇€烽柧鐐复濞村鐦径杈Е")}}
async function testEmail(){const b=beginAction("濮濓絽婀ù瀣槸 SMTP...");try{if(byId("smtp_test_result"))byId("smtp_test_result").textContent="濞村鐦稉?..";appendLogLine("瀵偓婵绁寸拠?SMTP 閿?host="+(fieldValue("smtp_host")||"閺堫亣顔曠純?)+" 閿?user="+(fieldValue("smtp_user")||"閺堫亣顔曠純?));const r=await fetch("/api/test_email",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(collect())});const data=await r.json();clearSecretInputs();hideSecret("smtp_password");const result=data.result||{};renderTest("smtp_test_result",result);applyEmailStatus(data.email_secret||{});appendLogLine((result.ok?"闁俺绻?":"婢惰精瑙?")+"SMTP 閿?"+(result.message||"閺冪姷绮ㄩ弸?));if(result.suggestion)appendLogLine("瀵ら缚顔?SMTP 閿?"+result.suggestion);endAction(b,result.ok?"SMTP 濞村鐦柅姘崇箖":"SMTP 濞村鐦径杈Е閿?+(result.message||"鐠囬婀呴崣鍏呮櫠閺冦儱绻?),result.ok?"ok":"error")}catch(err){appendLogLine("瀵倸鐖?SMTP 濞村鐦?閿?"+((err&&err.message)||err||"unknown"));failAction(b,err,"SMTP 濞村鐦径杈Е")}}
async function saveSettings(){const b=beginAction("濮濓絽婀穱婵嗙摠閹粯甯堕崣鎷岊啎缂?..");try{const payload={...collect(),...syncModelMirrorFields()};const r=await fetch("/api/settings",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});const data=await r.json();clearSecretInputs();for(const key of Object.keys(keyNameMap))hideSecret(key);renderModelProfiles(data.model_profiles||{});applyKeyStatus(data.secrets||{});applyEmailStatus(data.email_secret||{});loadApps();endAction(b,data.ok?"鐠佸墽鐤嗗韫箽鐎涙﹫绱辩€涙劙銆嶉惄顔荤窗娴ｈ法鏁ら幀缁樺付閸欐澘缍嬮崜宥夊帳缂?:"娣囨繂鐡ㄦ径杈Е",data.ok?"ok":"error");return data}catch(err){failAction(b,err,"娣囨繂鐡ㄦ径杈Е");return {ok:false,error:String(err&&err.message||err)}}}}
async function applyModelProfile(){const id=selectedProfileId();if(!id){setStatus("鐠囧嘲鍘涢柅澶嬪濡€崇€烽弬瑙勵攳","error");return}const b=beginAction("濮濓絽婀惔鏃傛暏濡€崇€烽弬瑙勵攳...");try{const r=await fetch("/api/model_profile",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({action:"apply",profile_id:id})});const data=await r.json();if(!data.ok){endAction(b,"鎼存梻鏁ら弬瑙勵攳婢惰精瑙﹂敍?+(data.error||"unknown"),"error");return}clearSecretInputs();for(const key of Object.keys(keyNameMap))hideSecret(key);const s=data.settings||{},m=data.models||{};for(const [k,v] of Object.entries({...s,...m})){if(byId(k))byId(k).value=v||""}syncModelMirrorFields();renderModelProfiles(data.model_profiles||{});applyKeyStatus(data.secrets||{});applyEmailStatus(data.email_secret||{});loadApps();endAction(b,"濡€崇€烽弬瑙勵攳瀹告彃绨查悽顭掔幢鐎涙劙銆嶉惄顔兼儙閸斻劍妞傛导姘倱濮濄儰濞囬悽?,"ok")}catch(err){failAction(b,err,"鎼存梻鏁ら弬瑙勵攳婢惰精瑙?)}}
async function applyProfileKey(key){const prefix=keyNameMap[key];const sel=prefix?byId(prefix+"_key_profile_select"):null;const profileId=sel?sel.value:"";if(!profileId){setStatus("鐠囧嘲鍘涢柅澶嬪娑撯偓娑擃亜鍑℃穱婵嗙摠 Key","error");return}const b=beginAction("濮濓絽婀惔鏃傛暏 Key...");try{const r=await fetch("/api/model_profile",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({action:"apply_key",profile_id:profileId,key_name:key})});const data=await r.json();if(!data.ok){endAction(b,"鎼存梻鏁?Key 婢惰精瑙﹂敍?+(data.error||"unknown"),"error");return}clearSecretInputs();hideSecret(key);renderModelProfiles(data.model_profiles||{});applyKeyStatus(data.secrets||{});applyEmailStatus(data.email_secret||{});loadApps();endAction(b,"Key 瀹告彃绨查悽顭掔幢閸氬嫬鐡欐い鍦窗閸氼垰濮╅弮鏈电窗娴ｈ法鏁ら幀缁樺付閸欐澘缍嬮崜宥夊帳缂?,"ok")}catch(err){failAction(b,err,"鎼存梻鏁?Key 婢惰精瑙?)}}
async function saveModelProfile(){const name=(byId("model_profile_name")&&byId("model_profile_name").value)||"";const id=selectedProfileId();const b=beginAction("濮濓絽婀穱婵嗙摠濡€崇€烽弬瑙勵攳...");try{const payload={...collect(),...syncModelMirrorFields()};const r=await fetch("/api/model_profile",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({...payload,action:"save",profile_id:id,profile_name:name})});const data=await r.json();if(!data.ok){endAction(b,"娣囨繂鐡ㄩ弬瑙勵攳婢惰精瑙﹂敍?+(data.error||"unknown"),"error");return}clearSecretInputs();for(const key of Object.keys(keyNameMap))hideSecret(key);renderModelProfiles(data.model_profiles||{});applyKeyStatus(data.secrets||{});applyEmailStatus(data.email_secret||{});loadApps();endAction(b,"濡€崇€烽弬瑙勵攳瀹歌弓绻氱€?,"ok")}catch(err){failAction(b,err,"娣囨繂鐡ㄩ弬瑙勵攳婢惰精瑙?)}}
async function deleteModelProfile(){const id=selectedProfileId();if(!id){setStatus("鐠囧嘲鍘涢柅澶嬪濡€崇€烽弬瑙勵攳","error");return}if(id==="foreign-default"){setStatus("姒涙顓婚弬瑙勵攳娑撳秷鍏橀崚鐘绘珟","error");return}const b=beginAction("濮濓絽婀崚鐘绘珟濡€崇€烽弬瑙勵攳...");try{const r=await fetch("/api/model_profile",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({action:"delete",profile_id:id})});const data=await r.json();if(!data.ok){endAction(b,"閸掔娀娅庨弬瑙勵攳婢惰精瑙﹂敍?+(data.error||"unknown"),"error");return}renderModelProfiles(data.model_profiles||{});loadApps();endAction(b,"濡€崇€烽弬瑙勵攳瀹告彃鍨归梽?,"ok")}catch(err){failAction(b,err,"閸掔娀娅庨弬瑙勵攳婢惰精瑙?)}}
async function start(payload){const b=beginAction("濮濓絽婀穱婵嗙摠鐠佸墽鐤嗛獮璺烘儙閸斻劋鎹㈤崝?..");try{const saved=await saveSettings();if(saved&&!saved.ok){endAction(b,"鐠佸墽鐤嗘穱婵嗙摠婢惰精瑙﹂敍灞兼崲閸斺剝婀崥顖氬З","error");return}const r=await fetch("/api/start",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});const data=await r.json();currentJob=data.job_id||"";cmd.textContent=(data.cmd||[]).join(" ");endAction(b,data.message||"娴犺濮熷鎻掓儙閸?,"ok");poll()}catch(err){failAction(b,err,"閸氼垰濮╂禒璇插婢惰精瑙?)}}
function startCulture(test){start({...collect(),mode:"culture",stage:byId("culture_stage").value,test_b_image_limit:test?1:Number(byId("culture_test_b").value||0)})}
function startResearch(action){start({...collect(),mode:"research",action})}
function startClip(){start({...collect(),mode:"auto_clip"})}
function startBgm(){start({...collect(),mode:"bgm"})}
function startTool(action){start({...collect(),mode:"tool",action})}
function openEegAnalyser(){notify("濮濓絽婀幍鎾崇磻閼存垹鏁搁崚鍡樼€介獮鍐插酱...","ok");window.open("/eeg/","_blank")}
function openXiaozhuli(){notify("濮濓絽婀幍鎾崇磻閸忋劍绶剁亸蹇曞皳閻?..","ok");window.open("/xiaozhuli/","_blank")}
async function stopJob(){if(!currentJob){setStatus("瑜版挸澧犲▽鈩冩箒濮濓絽婀潻鎰攽閻ㄥ嫪鎹㈤崝?,"error");return}const b=beginAction("濮濓絽婀崑婊勵剾瑜版挸澧犳禒璇插...");try{await fetch("/api/stop?id="+encodeURIComponent(currentJob),{method:"POST"});endAction(b,"閸嬫粍顒涚拠閿嬬湴瀹告彃褰傞柅?,"ok");poll()}catch(err){failAction(b,err,"閸嬫粍顒涙禒璇插婢惰精瑙?)}}
async function poll(){if(!currentJob)return;const r=await fetch("/api/job?id="+encodeURIComponent(currentJob));const data=await r.json();const message=data.status+" / exit="+(data.exit_code??"");const el=byId("status");if(el)el.textContent=message;log.textContent=(data.lines||[]).join("");log.scrollTop=log.scrollHeight;if(["running","starting","stopping"].includes(data.status))setTimeout(poll,1000);else notify("娴犺濮熼悩鑸碘偓渚婄窗"+message,data.exit_code===0?"ok":"info")}
for(const id of ["culture_text_model","culture_polish_model","culture_image_model","text_engine","polish_engine","image_engine","gpt_base_url","deepseek_base_url","gpt_image_base_url","minimax_base_url"]){const el=byId(id);if(el)el.addEventListener("input",()=>{syncModelMirrorFields();const p=(modelProfiles.profiles||[]).find(x=>x.id===selectedProfileId())||{};renderRouteSummary(p)})}
loadSettings();
if(location.hash==="#more"){showPanel("more")}else if(location.hash==="#culture"){showPanel("culture")}else if(location.hash==="#research"){showPanel("research")}else if(location.hash==="#clip"){showPanel("clip")}else{showPanel("model")}
</script>
</body>
</html>""".encode("utf-8")


def _model_connection_html() -> bytes:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>大模型连接库</title>
  <style>
    :root{font-family:Arial,"Microsoft YaHei",sans-serif;color:#17202a;background:#f6f8fb;--brand:#0f766e;--line:#d8e0e7;--muted:#64748b;--soft:#eef6f4;--danger:#b3261e;--ok:#067647}
    *{box-sizing:border-box}body{margin:0;background:#f6f8fb}.top{position:sticky;top:0;z-index:10;background:rgba(246,248,251,.94);backdrop-filter:blur(8px);border-bottom:1px solid var(--line)}
    .top-inner{max-width:1380px;margin:0 auto;padding:14px 18px;display:flex;align-items:center;justify-content:space-between;gap:12px}.back{color:#0f766e;text-decoration:none;font-weight:800}.title h1{font-size:22px;margin:0}.title p{margin:4px 0 0;color:var(--muted);font-size:13px}
    .wrap{max-width:1380px;margin:0 auto;padding:16px 18px 28px;display:grid;grid-template-columns:minmax(420px,1fr) minmax(520px,1.15fr);gap:14px}.panel{background:#fff;border:1px solid var(--line);border-radius:8px;padding:14px;box-shadow:0 12px 28px rgba(15,23,42,.06);min-width:0}
    h2{font-size:16px;margin:0 0 10px}h3{font-size:14px;margin:14px 0 8px}.hint{color:var(--muted);font-size:12px;line-height:1.6;margin:0 0 10px}.ops{display:grid;grid-template-columns:1fr 1fr;gap:8px}.ops button,.row button{min-height:38px}
    button{border:0;border-radius:6px;background:var(--brand);color:white;font-weight:800;padding:8px 10px;cursor:pointer}button.secondary{background:#334155}button.ghost{background:#e8eef2;color:#243447}button.danger{background:var(--danger)}button:disabled{opacity:.55;cursor:not-allowed}
    .log{background:#101827;color:#e5edf6;border-radius:8px;min-height:260px;max-height:380px;overflow:auto;padding:12px;font:12px/1.55 Consolas,"Microsoft YaHei",monospace;white-space:pre-wrap}.status{min-height:28px;color:#0f5132;font-weight:800;font-size:13px;margin:8px 0}
    .step{border:1px solid var(--line);border-radius:8px;padding:10px;margin-bottom:10px;background:#fbfdff}.step-head{display:flex;justify-content:space-between;gap:8px;align-items:center}.step h3{margin:0}.badge{display:inline-flex;align-items:center;border-radius:999px;background:#eef2f6;color:#334155;padding:3px 8px;font-size:12px;font-weight:800}.badge.ok{background:#ecfdf3;color:#067647}.badge.bad{background:#fef3f2;color:#b42318}
    .route-list{min-height:54px;border:1px dashed #b8c4ce;border-radius:8px;margin-top:8px;padding:6px;background:#fff}.route-list.drag{border-color:#0f766e;background:#eefaf7}.item{display:grid;grid-template-columns:1fr auto;gap:8px;align-items:center;border:1px solid #dbe3ea;border-radius:8px;background:#fff;padding:8px;margin:6px 0;min-width:0}.item[draggable=true]{cursor:grab}.item b{font-size:13px;overflow-wrap:anywhere}.meta{font-size:12px;color:#64748b;line-height:1.45;overflow-wrap:anywhere}.item-actions{display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end}
    .trash{border:1px dashed #f1a6a0;background:#fff7f6;color:#9f1d16;border-radius:8px;padding:10px;text-align:center;font-size:13px;font-weight:800;margin:10px 0}.trash.drag{background:#fee4e2;border-color:#d92d20}
    .toolbar{display:grid;grid-template-columns:1fr auto auto;gap:8px;margin-bottom:10px}input,select{width:100%;border:1px solid #c8d2dc;border-radius:6px;padding:8px;background:white}.library-group{border:1px solid var(--line);border-radius:8px;margin-bottom:10px;background:#fff}.library-group h3{display:flex;justify-content:space-between;gap:8px;margin:0;padding:9px 10px;background:#f3f7fa;border-bottom:1px solid var(--line);border-radius:8px 8px 0 0}.library-body{padding:6px 8px}
    .form-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}.form-grid .wide{grid-column:1/-1}.row{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}.small{font-size:12px;color:var(--muted)}.hidden{display:none!important}
    @media(max-width:980px){.wrap{grid-template-columns:1fr}.ops{grid-template-columns:1fr}.toolbar{grid-template-columns:1fr}.form-grid{grid-template-columns:1fr}.form-grid .wide{grid-column:auto}}
  </style>
</head>
<body>
  <div class="top"><div class="top-inner"><a class="back" href="/">返回控制台首页</a><div class="title"><h1>大模型连接库</h1><p>右侧储备和测试模型，左侧给每个业务步骤拖入多个候选；应用前确保每个步骤至少有一个测通连接。</p></div></div></div>
  <main class="wrap">
    <section class="panel">
      <h2>链接库操作</h2>
      <div class="ops">
        <button id="btnTestSteps" onclick="testBusinessChain()">一键测试和修复业务链中的模型</button>
        <button id="btnTestLibrary" onclick="testLibraryModels()">一键测试和修复模型库中的模型</button>
        <button class="secondary" onclick="refreshLibrary()">刷新连接库</button>
        <button class="secondary" onclick="applyAllProjects()">应用到所有项目</button>
      </div>
      <div id="status" class="status">正在读取连接库...</div>
      <pre id="log" class="log">暂无日志</pre>
      <div class="row"><button class="ghost" onclick="clearLog()">清空日志</button></div>
      <h2 style="margin-top:16px">业务步骤流程</h2>
      <p class="hint">把右侧已测试的模型条目拖进步骤；同一步骤可以保留多个候选。运行任务时会优先使用测通连接。</p>
      <div id="steps"></div>
      <div id="trash" class="trash">拖到这里移出当前步骤候选</div>
    </section>
    <section class="panel">
      <h2>模型库</h2>
      <div class="toolbar">
        <input id="modelSearch" placeholder="搜索模型、URL、名称" autocomplete="off">
        <button class="ghost" onclick="newConnection()">新建</button>
        <button class="ghost" onclick="refreshLibrary()">刷新</button>
      </div>
      <div id="editForm" class="form-grid hidden">
        <input type="hidden" id="connId">
        <label>名称<input id="connName"></label>
        <label>类别<select id="connRole"><option value="text">文本</option><option value="polish">润色</option><option value="image">生图</option><option value="minimax">配音/BGM</option></select></label>
        <label>供应商<input id="connProvider" placeholder="openai / deepseek / image / minimax"></label>
        <label>模型名<input id="connModel" placeholder="gpt-5.5 / deepseek-chat / gpt-image-2"></label>
        <label class="wide">URL<input id="connBaseUrl" placeholder="https://..."></label>
        <label class="wide">Key（可留空；留空不会覆盖已有 Key）<input id="connKey" type="password" autocomplete="new-password"></label>
        <div class="row wide"><button onclick="saveConnection()">保存到连接库</button><button class="ghost" onclick="cancelEdit()">取消</button></div>
      </div>
      <div id="library"></div>
    </section>
  </main>
<script>
const roleOrder=["text","polish","image","minimax"];
let lib={connections:[],roles:{},steps:{},step_routes:{},active_connections:{}};
let dragged={id:"",fromStep:""};
function byId(id){return document.getElementById(id)}
function esc(s){return String(s||"").replace(/[&<>"']/g,c=>c==="&"?"&amp;":c==="<"?"&lt;":c===">"?"&gt;":c.charCodeAt(0)===34?"&quot;":"&#39;")}
function log(msg){const el=byId("log");const line="["+new Date().toLocaleTimeString()+"] "+msg;el.textContent=(el.textContent==="暂无日志"?"":el.textContent)+"\\n"+line;el.textContent=el.textContent.trim();el.scrollTop=el.scrollHeight}
function setStatus(msg,kind=""){byId("status").textContent=msg;byId("status").style.color=kind==="error"?"#b42318":"#0f5132"}
function clearLog(){byId("log").textContent="暂无日志";setStatus("日志已清空")}
function friendlyError(x){const s=String((x&&x.error)||(x&&x.message)||x||"未知错误");if(s.includes("frequency limit"))return "飞书接口触发频率限制，已跳过飞书补 Key；稍后再试即可。";if(s.includes("whitelist"))return "飞书文档不在当前授权白名单内，已跳过飞书补 Key。";if(s.includes("HTTP 403"))return "接口拒绝访问，通常是 Key、URL 或模型权限不匹配。";if(s.includes("model_not_found"))return "模型通道不可用，请换同类可用连接。";return s.split("\\n")[0].slice(0,220)}
function connections(){return Array.isArray(lib.connections)?lib.connections:[]}
function conn(id){return connections().find(c=>c.id===id)||null}
function allowed(step,c){const meta=(lib.steps||{})[step]||{};const roles=meta.roles||[meta.role];return roles.includes(c.role)}
async function post(action,payload={}){const r=await fetch("/api/model_connection",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({action,...payload})});const data=await r.json().catch(()=>({ok:false,error:"接口没有返回 JSON"}));if(!r.ok||data.ok===false)throw data;if(data.model_connection_library)lib=data.model_connection_library;else if(data.models&&data.model_connection_library)lib=data.model_connection_library;return data}
async function refreshLibrary(){setStatus("正在刷新连接库...");const r=await fetch("/api/settings");const data=await r.json();lib=data.model_connection_library||{};renderAll();setStatus("连接库已刷新");log("连接库已刷新：共 "+connections().length+" 个连接。")}
function stepKeys(){return Object.keys(lib.steps||{})}
function routeIds(step){return Array.isArray((lib.step_routes||{})[step])?[...(lib.step_routes||{})[step]]:[]}
function connectionLabel(c){return (c.name||c.model||c.id)+" ｜ "+(c.provider||"")+" / "+(c.model||"未填模型")}
function statusText(c){if(c.last_test_ok===true)return "已通";if(c.last_test_ok===false&&c.last_tested_at)return "未通";return "未测"}
function statusBadge(c){if(c.last_test_ok===true)return '<span class="badge ok">已通</span>';if(c.last_test_ok===false&&c.last_tested_at)return '<span class="badge bad">未通</span>';return '<span class="badge">未测</span>'}
function itemMeta(c){return 'URL '+esc(c.base_url||"未填")+' ｜ Key '+(c.key_configured?"已存":"未存")+' ｜ 联通 '+statusText(c)+' ｜ 延迟 '+(Number(c.latency_ms||0)?Number(c.latency_ms||0)+" ms":"-")}
function itemHtml(c,opts={}){const inStep=!!opts.step,remove=inStep?'<button class="danger" onclick="removeFromStep(\\''+esc(opts.step)+'\\',\\''+esc(c.id)+'\\')">移除</button>':'',manage=inStep?'':'<button class="ghost" onclick="editConnection(\\''+esc(c.id)+'\\')">编辑</button><button class="danger" onclick="deleteConnection(\\''+esc(c.id)+'\\')">删除</button>';return '<div class="item" draggable="true" data-id="'+esc(c.id)+'" data-step="'+esc(opts.step||'')+'" ondragstart="dragStart(event)"><div><b>'+esc(connectionLabel(c))+'</b><div class="meta">'+itemMeta(c)+'</div></div><div class="item-actions">'+statusBadge(c)+'<button class="ghost" onclick="testConnection(\\''+esc(c.id)+'\\')">测试</button>'+manage+remove+'</div></div>'}
function renderSteps(){const box=byId("steps");box.innerHTML=stepKeys().map(step=>{const meta=lib.steps[step]||{},ids=routeIds(step),items=ids.map(id=>conn(id)).filter(Boolean),ok=items.some(c=>c.last_test_ok===true),allowedText=(meta.roles||[meta.role]).map(r=>(lib.roles&&lib.roles[r]&&lib.roles[r].label)||r).join(" / ");return '<div class="step"><div class="step-head"><h3>'+esc(meta.label||step)+'</h3>'+(ok?'<span class="badge ok">至少一个通</span>':'<span class="badge bad">需要通路</span>')+'</div><div class="small">可接收：'+esc(allowedText)+'</div><div class="route-list" data-step="'+esc(step)+'" ondragover="dragOver(event)" ondragleave="dragLeave(event)" ondrop="dropOnStep(event)">'+(items.length?items.map(c=>itemHtml(c,{step})).join(""):'<div class="small">把右侧模型拖到这里</div>')+'</div></div>'}).join("")}
function renderLibrary(){const q=byId("modelSearch").value.trim().toLowerCase();const groups={};for(const c of connections()){const hay=[c.name,c.provider,c.model,c.base_url,c.role_label].join(" ").toLowerCase();if(q&&!hay.includes(q))continue;const key=c.model||"未填模型";(groups[key]||(groups[key]=[])).push(c)}const keys=Object.keys(groups).sort((a,b)=>a.localeCompare(b));byId("library").innerHTML=keys.length?keys.map(model=>'<div class="library-group"><h3><span>'+esc(model)+'</span><span class="badge">'+groups[model].length+' 条</span></h3><div class="library-body">'+groups[model].sort((a,b)=>(b.last_test_ok===true)-(a.last_test_ok===true)||(a.priority||0)-(b.priority||0)).map(c=>itemHtml(c)).join("")+'</div></div>').join(""):'<p class="hint">没有匹配的模型连接。</p>'}
function renderAll(){renderSteps();renderLibrary()}
function dragStart(e){dragged={id:e.currentTarget.dataset.id||"",fromStep:e.currentTarget.dataset.step||""};e.dataTransfer.setData("text/plain",dragged.id)}
function dragOver(e){e.preventDefault();e.currentTarget.classList.add("drag")}
function dragLeave(e){e.currentTarget.classList.remove("drag")}
async function saveRoute(step,ids){await post("route",{step,connection_ids:ids});renderAll()}
async function dropOnStep(e){e.preventDefault();e.currentTarget.classList.remove("drag");const step=e.currentTarget.dataset.step,id=dragged.id||e.dataTransfer.getData("text/plain"),c=conn(id);if(!step||!c)return;if(!allowed(step,c)){setStatus("这个模型类别不能用于该步骤","error");log("未加入："+connectionLabel(c)+" 不适合 "+((lib.steps[step]||{}).label||step));return}const ids=routeIds(step).filter(x=>x!==id);ids.push(id);await saveRoute(step,ids);setStatus("已加入步骤候选");log("已加入 "+((lib.steps[step]||{}).label||step)+"： "+connectionLabel(c))}
async function removeFromStep(step,id){const ids=routeIds(step).filter(x=>x!==id);await saveRoute(step,ids);setStatus("已移出步骤候选");log("已从 "+((lib.steps[step]||{}).label||step)+" 移出： "+(conn(id)?connectionLabel(conn(id)):id))}
function setupTrash(){const t=byId("trash");t.ondragover=e=>{e.preventDefault();t.classList.add("drag")};t.ondragleave=()=>t.classList.remove("drag");t.ondrop=async e=>{e.preventDefault();t.classList.remove("drag");if(dragged.fromStep&&dragged.id)await removeFromStep(dragged.fromStep,dragged.id)}}
function newConnection(){byId("editForm").classList.remove("hidden");for(const id of ["connId","connName","connProvider","connModel","connBaseUrl","connKey"])byId(id).value="";byId("connRole").value="text";setStatus("正在新建连接");log("打开新建连接表单。")}
function editConnection(id){const c=conn(id);if(!c)return;byId("editForm").classList.remove("hidden");byId("connId").value=c.id;byId("connName").value=c.name||"";byId("connRole").value=c.role||"text";byId("connProvider").value=c.provider||"";byId("connModel").value=c.model||"";byId("connBaseUrl").value=c.base_url||"";byId("connKey").value="";setStatus("正在编辑："+connectionLabel(c));log("打开编辑："+connectionLabel(c))}
function cancelEdit(){byId("editForm").classList.add("hidden");setStatus("已取消编辑");log("已取消编辑。")}
async function saveConnection(){const payload={connection_id:byId("connId").value,name:byId("connName").value,role:byId("connRole").value,provider:byId("connProvider").value,model:byId("connModel").value,base_url:byId("connBaseUrl").value,api_key:byId("connKey").value};try{await post("save",payload);byId("connKey").value="";cancelEdit();renderAll();setStatus("连接已保存");log("连接已保存："+(payload.name||payload.model))}catch(e){setStatus("保存失败："+friendlyError(e),"error");log("保存失败："+friendlyError(e))}}
async function deleteConnection(id){const c=conn(id);if(!c)return;if(!confirm("确认删除这个连接？删除后会同时从步骤候选里移除。"))return;try{await post("delete",{connection_id:id});renderAll();setStatus("连接已删除");log("连接已删除："+connectionLabel(c))}catch(e){setStatus("删除失败："+friendlyError(e),"error");log("删除失败："+friendlyError(e))}}
function applyLocalTestResult(id,result){for(const c of connections()){if(c.id===id){c.last_test_ok=!!(result&&result.ok);c.last_tested_at=(result&&result.tested_at)||new Date().toLocaleString();const elapsed=Number(result&&result.elapsed_seconds||0);if(elapsed)c.latency_ms=Math.round(elapsed*1000);return c}}return null}
async function testConnection(id){const c=conn(id);if(!c)return;setStatus("正在测试："+connectionLabel(c));log("测试："+connectionLabel(c));try{const r=await fetch("/api/test_model",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({provider:c.provider,connection_id:c.id})});const data=await r.json();if(data.model_connection_library)lib=data.model_connection_library;else applyLocalTestResult(id,data.result||{});if(!r.ok||data.ok===false)throw data;renderAll();const next=conn(id)||c;setStatus("测试完成："+connectionLabel(next)+" / "+statusText(next),next.last_test_ok===true?"":"error");log("结果："+connectionLabel(next)+" ｜ 联通 "+statusText(next)+" ｜ 延迟 "+(Number(next.latency_ms||0)?Number(next.latency_ms||0)+" ms":"-"))}catch(e){applyLocalTestResult(id,{ok:false,tested_at:new Date().toLocaleString()});renderAll();setStatus("测试失败："+friendlyError(e),"error");log("测试失败："+friendlyError(e))}finally{document.activeElement&&document.activeElement.blur&&document.activeElement.blur()}}
async function testBusinessChain(){const btn=byId("btnTestSteps");btn.disabled=true;setStatus("正在测试并修复业务链...");log("开始测试和修复业务链中的模型。");try{const r=await fetch("/api/test_step_routes_repair",{method:"POST"});const data=await r.json();if(data.model_connection_library)lib=data.model_connection_library;const rows=data.summary||[];for(const row of rows)log((row.ok?"通过：":"未通过：")+(row.step_label||row.step)+"，候选 "+(row.candidate_count||0)+" 个，测通 "+(row.passed_count||0)+" 个。"+(row.passed_model?" 使用 "+row.passed_model:""));if(data.repair&&data.repair.attempted)log("修复动作：已尝试从飞书/连接库补齐失败步骤，仍失败 "+((data.repair.remaining_failed_steps||[]).length)+" 个。");renderAll();setStatus(rows.every(x=>x.ok)?"业务链测试通过":"业务链仍有步骤未通",rows.every(x=>x.ok)?"":"error")}catch(e){setStatus("业务链测试失败："+friendlyError(e),"error");log("业务链测试失败："+friendlyError(e))}finally{btn.disabled=false;document.activeElement&&document.activeElement.blur&&document.activeElement.blur()}}
async function testLibraryModels(){const btn=byId("btnTestLibrary");btn.disabled=true;setStatus("正在测试并修复模型库...");log("开始测试和修复模型库中的模型。");try{await post("dedupe");log("已按 URL + Key 去重。");try{const repaired=await post("repair_keys");const rep=repaired.key_repair_report||{};log(rep.ok?"已尝试从飞书补齐 Key，并同步飞书中能安全匹配的连接。":"飞书补 Key 未完成："+friendlyError(rep.error||rep.message||rep));}catch(e){log("飞书补 Key 跳过："+friendlyError(e))}const data=await post("test_library");const summary=data.summary||[];for(const s of summary)log("模型 "+(s.model||"未设置")+"：测试 "+(s.tested_count||0)+" 条，通过 "+(s.passed_count||0)+" 条，失败 "+(s.failed_count||0)+" 条。"+((s.failures&&s.failures[0])?" 主要原因："+friendlyError(s.failures[0].message):""));renderAll();setStatus("模型库测试完成")}catch(e){setStatus("模型库测试失败："+friendlyError(e),"error");log("模型库测试失败："+friendlyError(e))}finally{btn.disabled=false;document.activeElement&&document.activeElement.blur&&document.activeElement.blur()}}
async function applyAllProjects(){setStatus("正在应用到所有项目...");log("开始应用当前连接库方案到所有项目。");try{const data=await post("apply_all");if(Array.isArray(data.log_lines))for(const line of data.log_lines)log(String(line));else log("应用完成。");await refreshLibrary();setStatus("已应用到所有项目")}catch(e){setStatus("应用失败："+friendlyError(e),"error");log("应用失败："+friendlyError(e))}}
byId("modelSearch").addEventListener("input",renderLibrary);
setupTrash();
refreshLibrary();
</script>
</body>
</html>""".encode("utf-8")



def _entry_html_v2() -> bytes:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>郤冠楠的赛博办公室</title>
  <style>
    :root{font-family:Arial,"Microsoft YaHei",sans-serif;color:#17202a;background:#eef5f2;--brand:#0f766e;--brand2:#2563eb;--ink:#102033;--line:#d8e0e7;--muted:#64748b;--card:#fff;--shadow:0 16px 36px rgba(15,23,42,.10);--beam:rgba(250,204,21,.28);--glow:rgba(20,184,166,.24)}
    *{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 18% 0%,#d9f99d 0,#f8fafc 28%,transparent 48%),linear-gradient(145deg,#eef7f4 0%,#f7f2ea 52%,#eef4ff 100%);min-height:100vh;transition:background .5s ease,color .35s ease;cursor:none}a,button,.card,[data-light],[data-toy]{cursor:none}body:before{content:"";position:fixed;inset:0;pointer-events:none;background:linear-gradient(115deg,transparent 0 42%,var(--beam) 48%,transparent 56%);transform:translateX(-80%);animation:sweep 9s linear infinite;mix-blend-mode:multiply}body.lights-off{color:#dbeafe;background:radial-gradient(circle at 70% 8%,rgba(56,189,248,.16),transparent 28%),linear-gradient(145deg,#07111f 0%,#101827 60%,#20123a 100%);--card:rgba(15,23,42,.82);--line:rgba(148,163,184,.28);--muted:#a7b4c8;--shadow:0 18px 42px rgba(0,0,0,.32);--beam:rgba(59,130,246,.18);--glow:rgba(96,165,250,.30)}body.party{background:linear-gradient(125deg,#ecfeff,#fef3c7,#fce7f3,#e0e7ff);background-size:300% 300%;animation:partyBg 7s ease infinite;--beam:rgba(236,72,153,.24);--glow:rgba(245,158,11,.28)}body.focus{background:linear-gradient(145deg,#f8fafc,#eef7f4);--beam:rgba(20,184,166,.12);--glow:rgba(15,118,110,.16)}.wrap{max-width:1120px;margin:0 auto;padding:30px 18px 44px;position:relative}
    .lamp-rig{position:fixed;left:0;right:0;top:0;height:130px;pointer-events:none;z-index:0}.lamp-rig:before,.lamp-rig:after{content:"";position:absolute;top:-18px;width:180px;height:180px;border-radius:50%;background:radial-gradient(circle,var(--glow),transparent 68%);filter:blur(2px);animation:lampFloat 5.5s ease-in-out infinite}.lamp-rig:before{left:8%}.lamp-rig:after{right:9%;animation-delay:1.2s}.control-strip{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:14px;border:1px solid rgba(15,118,110,.16);border-radius:8px;background:rgba(255,255,255,.70);box-shadow:0 10px 22px rgba(15,23,42,.06);padding:10px}.control-strip b{font-size:13px}.switches{display:flex;gap:8px;flex-wrap:wrap}.light-btn{background:#102033;color:#fff;border:0;border-radius:999px;padding:8px 12px;font-weight:900}.light-btn.active{background:#f59e0b;color:#102033;box-shadow:0 0 0 4px rgba(245,158,11,.18)}
    .hero{border:1px solid rgba(15,118,110,.18);border-radius:8px;background:rgba(255,255,255,.78);box-shadow:var(--shadow);padding:22px;position:relative;overflow:hidden;animation:panelIn .55s ease both}.lights-off .hero,.lights-off .control-strip{background:rgba(15,23,42,.72);border-color:rgba(96,165,250,.25)}.hero:before{content:"";position:absolute;inset:0;background:linear-gradient(90deg,rgba(20,184,166,.10),rgba(37,99,235,.08),rgba(245,158,11,.10));pointer-events:none}.hero:after{content:"";position:absolute;left:-30%;top:0;width:24%;height:100%;background:linear-gradient(90deg,transparent,rgba(255,255,255,.42),transparent);transform:skewX(-18deg);animation:shine 6s ease-in-out infinite}.hero>*{position:relative}.eyebrow{display:inline-flex;align-items:center;gap:8px;min-height:26px;padding:0 10px;border-radius:999px;background:#102033;color:#fff;font-size:12px;font-weight:800}.eyebrow:before{content:"";width:8px;height:8px;border-radius:50%;background:#22c55e;box-shadow:0 0 0 0 rgba(34,197,94,.6);animation:pulseDot 1.8s infinite}.hero-top{align-items:flex-start;display:flex;justify-content:space-between;gap:16px}.office-status{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;min-width:330px}.desk-chip{border:1px solid #dbe4ea;border-radius:8px;background:#fff;padding:9px 10px;transition:transform .22s ease,box-shadow .22s ease}.desk-chip:hover{transform:translateY(-2px) rotate(-.4deg);box-shadow:0 12px 24px rgba(15,23,42,.10)}.lights-off .desk-chip{background:rgba(15,23,42,.78);border-color:rgba(148,163,184,.28)}.desk-chip b{display:block;font-size:13px}.desk-chip span{color:var(--muted);font-size:11px}
    h1{font-size:34px;line-height:1.14;margin:13px 0 8px;letter-spacing:0}.hint{color:#415267;font-size:14px;line-height:1.75;margin:0;max-width:780px}.toy-shelf{display:flex;gap:9px;flex-wrap:wrap;margin-top:16px}.toy-btn{border:1px solid #bfd2d6;border-radius:999px;background:#f8fafc;color:#334155;font-size:12px;font-weight:900;padding:7px 10px}.toy-btn:hover{background:#e0f2fe}
    .section-head{align-items:flex-end;display:flex;gap:12px;justify-content:space-between;margin:24px 0 10px}.section-head h2{font-size:19px;margin:0;color:#102033}.section-head span{color:var(--muted);font-size:12px}.version-label{display:inline-flex;align-items:center;gap:8px;color:#334155;font-size:14px;font-weight:900;margin:18px 0 9px}.version-label:before{content:"";width:9px;height:9px;border-radius:50%;background:#14b8a6;box-shadow:0 0 0 4px rgba(20,184,166,.13)}.version-label.dev:before{background:#2563eb;box-shadow:0 0 0 4px rgba(37,99,235,.12)}
    .grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}.card{display:block;background:var(--card);border:1px solid var(--line);border-radius:8px;padding:16px;text-decoration:none;color:inherit;box-shadow:var(--shadow);min-width:0;position:relative;overflow:hidden;transition:transform .22s ease,box-shadow .22s ease,border-color .22s ease;animation:cardRise .42s ease both}.card:nth-child(2){animation-delay:.05s}.card:nth-child(3){animation-delay:.1s}.card:before{content:"";display:block;height:4px;background:linear-gradient(90deg,#14b8a6,#2563eb,#f59e0b);position:absolute;left:0;right:0;top:0}.card:after{content:"";position:absolute;inset:0;background:radial-gradient(circle at var(--mx,50%) var(--my,0%),rgba(20,184,166,.12),transparent 34%);opacity:0;transition:opacity .2s ease;pointer-events:none}.card[data-route]{cursor:pointer}.card:hover{border-color:#14b8a6;box-shadow:0 18px 34px rgba(15,118,110,.18);transform:translateY(-5px) rotate(.2deg)}.card:hover:after{opacity:1}.card:focus-visible{outline:2px solid #14b8a6;outline-offset:3px}.card.focus-card{border-color:#14b8a6;box-shadow:0 0 0 4px rgba(20,184,166,.16),0 18px 34px rgba(15,118,110,.18)}
    .title{font-size:17px;font-weight:900;margin-bottom:6px}.desc{font-size:13px;color:#4f6072;line-height:1.55;margin-top:8px}.meta{color:var(--muted);font-size:12px;line-height:1.5;margin-top:8px;overflow-wrap:anywhere}
    .row{display:flex;gap:8px;margin-top:12px;flex-wrap:wrap}.card-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px;position:relative;z-index:2}button{padding:8px 10px;border:0;border-radius:6px;background:var(--brand);color:#fff;cursor:pointer;font-weight:800;position:relative;overflow:hidden;transition:transform .18s ease,filter .18s ease,box-shadow .18s ease,opacity .18s ease}button:hover{transform:translateY(-1px);filter:brightness(1.06)}button+button{background:#334155}button.danger{background:#b3261e}button.control-start.control-active{background:linear-gradient(135deg,#16a34a,#22c55e);box-shadow:0 10px 20px rgba(34,197,94,.28),0 0 0 3px rgba(34,197,94,.14)}button.control-stop.control-active{background:linear-gradient(135deg,#dc2626,#f97316);box-shadow:0 10px 20px rgba(249,115,22,.30),0 0 0 3px rgba(248,113,113,.16)}button.control-muted,button[aria-disabled="true"]{background:#cbd5e1!important;color:#64748b;box-shadow:none;filter:saturate(.75);opacity:.72}button.control-muted:hover,button[aria-disabled="true"]:hover{transform:none;filter:saturate(.75)}button[data-busy="true"]{opacity:.72;cursor:wait}.open-hint{display:inline-flex;align-items:center;color:#0f766e;font-size:12px;font-weight:900;margin-top:10px}.spark{position:fixed;width:8px;height:8px;border-radius:50%;background:#facc15;pointer-events:none;animation:spark .75s ease-out forwards;z-index:20}
    .pill{display:inline-flex;align-items:center;min-height:24px;padding:0 8px;border-radius:999px;background:#eef2f6;color:#334155;font-size:12px;font-weight:800}.pill.ok{background:#ecfdf3;color:#027a48}.pill.warn{background:#fff7ed;color:#b54708}.utility-grid{grid-template-columns:repeat(3,minmax(0,1fr))}.utility-grid .card{min-height:120px}
    .cursor-dot,.cursor-ring{position:fixed;left:0;top:0;pointer-events:none;z-index:1000;transform:translate(-50%,-50%)}.cursor-dot{width:8px;height:8px;border-radius:50%;background:#0f766e;box-shadow:0 0 18px rgba(20,184,166,.75)}.cursor-ring{width:34px;height:34px;border:1px solid rgba(15,118,110,.72);border-radius:50%;transition:width .16s ease,height .16s ease,border-color .16s ease,background .16s ease}.cursor-ring.hot{width:46px;height:46px;border-color:#f59e0b;background:rgba(245,158,11,.10)}.cursor-trail{position:fixed;width:10px;height:10px;border-radius:50%;background:rgba(37,99,235,.22);pointer-events:none;z-index:999;animation:trailFade .55s ease-out forwards}.scanline{position:fixed;left:0;right:0;height:4px;top:0;background:linear-gradient(90deg,transparent,#22d3ee,#facc15,transparent);box-shadow:0 0 24px rgba(34,211,238,.8);pointer-events:none;z-index:60;animation:scanDrop 1.1s ease-out forwards}.ripple{position:fixed;width:14px;height:14px;border-radius:50%;border:2px solid #14b8a6;pointer-events:none;z-index:998;transform:translate(-50%,-50%);animation:ripple .7s ease-out forwards}
    @keyframes sweep{0%{transform:translateX(-80%)}45%,100%{transform:translateX(130%)}}@keyframes shine{0%,55%{left:-30%}75%,100%{left:120%}}@keyframes pulseDot{0%{box-shadow:0 0 0 0 rgba(34,197,94,.55)}70%{box-shadow:0 0 0 8px rgba(34,197,94,0)}100%{box-shadow:0 0 0 0 rgba(34,197,94,0)}}@keyframes panelIn{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}@keyframes cardRise{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:none}}@keyframes lampFloat{0%,100%{transform:translateY(0)}50%{transform:translateY(12px)}}@keyframes partyBg{0%{background-position:0% 50%}50%{background-position:100% 50%}100%{background-position:0% 50%}}@keyframes spark{to{opacity:0;transform:translate(var(--dx),var(--dy)) scale(.2)}}@keyframes trailFade{to{opacity:0;transform:scale(.25)}}@keyframes scanDrop{from{top:-10px}to{top:100vh;opacity:.1}}@keyframes ripple{to{width:80px;height:80px;opacity:0}}@media(prefers-reduced-motion:reduce){*,*:before,*:after{animation:none!important;transition:none!important}body{cursor:auto}a,button,.card,[data-light],[data-toy]{cursor:pointer}.cursor-dot,.cursor-ring,.cursor-trail,.scanline,.ripple{display:none!important}}
    @media(max-width:900px){.hero-top{display:block}.office-status{grid-template-columns:1fr;margin-top:14px;min-width:0}.control-strip{align-items:flex-start;flex-direction:column}.grid,.utility-grid{grid-template-columns:1fr}.section-head{align-items:flex-start;flex-direction:column}}
  </style>
</head>
<body>
  <div class="lamp-rig"></div>
  <div class="cursor-dot" id="cursor_dot"></div>
  <div class="cursor-ring" id="cursor_ring"></div>
  <div class="wrap">
    <div class="control-strip">
      <b id="light_status">办公室灯光：明亮营业</b>
      <div class="switches">
        <button type="button" class="light-btn active" data-light="on">开灯</button>
        <button type="button" class="light-btn" data-light="off">关灯</button>
        <button type="button" class="light-btn" data-light="party">派对灯</button>
        <button type="button" class="light-btn" data-light="focus">专注灯</button>
      </div>
    </div>
    <section class="hero">
      <div class="hero-top">
        <div>
          <div class="eyebrow">OFFICE ONLINE</div>
          <h1>郤冠楠的赛博办公室</h1>
          <p class="hint">早上好，郤总。这里是三条业务线的驾驶舱、两套版本的分岔口，也是所有按钮开始认真工作的地方。上线区稳稳营业，开发区大胆折腾；模型、Key 和公共配置都收进抽屉，项目页只专心干活。</p>
          <div class="toy-shelf"><button type="button" class="toy-btn" data-toy="scan">扫描全屋</button><button type="button" class="toy-btn" data-toy="confetti">发射火花</button><button type="button" class="toy-btn" data-toy="tidy">整理桌面</button></div>
        </div>
        <div class="office-status">
          <div class="desk-chip"><b>3 条业务线</b><span>内容、销售、脑电各在工位</span></div>
          <div class="desk-chip"><b>2 套版本</b><span>正式稳住，开发撒欢</span></div>
          <div class="desk-chip"><b>1 个抽屉</b><span>模型连接统一收纳</span></div>
        </div>
      </div>
    </section>
    <div class="section-head"><h2>办公桌上的传送门</h2><span id="home_app_summary"></span></div>
    <div class="version-label">上线区</div>
    <section class="grid" id="home_production_grid">
      <a id="production-assistant" class="card" href="http://127.0.0.1:8766/assistant/" target="_blank"><div class="title">自媒体小猪理（发布版）</div><div class="desc">本机发布版入口；运行在独立目录和端口，不受开发版代码修改影响。</div></a>
      <a class="card" href="/xiaozhuli/"><div class="title">全澜小猪理</div><div class="desc">线上正式服务入口。</div></a>
      <a class="card" href="/eeg/"><div class="title">脑电分析平台</div><div class="desc">线上正式服务入口。</div></a>
    </section>
    <div class="version-label dev">开发区</div>
    <section class="grid" id="home_development_grid">
      <a class="card" href="/assistant/"><div class="title">自媒体小猪理</div><div class="desc">文史、每日研究速递、科学经典、剪辑与邮件配置业务入口。</div></a>
      <a class="card" href="/xiaozhuli/"><div class="title">全澜小猪理</div><div class="desc">销售知识库、客户建议、Role-play 记录和服务状态。</div></a>
      <a class="card" href="/eeg/"><div class="title">脑电分析平台</div><div class="desc">NeuroCloud EEG 分析流程入口。</div></a>
    </section>
    <div class="section-head"><h2>公共配置</h2><span></span></div>
    <section class="grid utility-grid">
      <a class="card" href="/model/"><div class="title">大模型连接库</div><div class="desc">添加、查看、编辑、删除和测试各类模型连接；任务自动组合可用连接。</div></a>
      <a class="card" href="/audience/"><div class="title">虚拟用户测试</div><div class="desc">按项目列出虚拟用户评审入口，并在页面内查看运行日志。</div></a>
      <a class="card" href="/cloud/"><div class="title">云服务器健康舱</div><div class="desc">监控正式服务器在线、健康接口、延迟和服务控制状态；CPU/内存/硬盘预留真实采集入口。</div></a>
    </section>
    <div class="section-head"><h2>自由化器</h2><span>代码保留在各自项目中</span></div>
    <section class="grid utility-grid">
      <a class="card" href="/optimizer/"><div class="title">进入自优化器控制台</div><div class="desc">统一启动、停止各项目的自优化器，并集中查看运行日志。</div></a>
    </section>
  </div>
<script>
function pill(app){const online=!!(app&&app.online),sync=(app&&app.sync_state)||"未知";const cls=online&&(sync==="已同步"||sync==="流程平台")?"ok":(online?"warn":"");return '<span class="pill '+cls+'">'+(online?"在线":"离线")+' ｜ '+sync+'</span>'}
function esc(s){return String(s||"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\\\"":"&quot;","'":"&#39;"}[c]))}
function attr(s){return esc(s)}
function jsq(s){return JSON.stringify(String(s||""))}
function setLight(mode){document.body.classList.toggle("lights-off",mode==="off");document.body.classList.toggle("party",mode==="party");document.body.classList.toggle("focus",mode==="focus");document.querySelectorAll("[data-light]").forEach(b=>b.classList.toggle("active",b.dataset.light===mode));const text={on:"办公室灯光：明亮营业",off:"办公室灯光：夜航模式",party:"办公室灯光：正在庆功",focus:"办公室灯光：专注降噪"}[mode]||"办公室灯光：明亮营业";const el=document.getElementById("light_status");if(el)el.textContent=text;try{localStorage.setItem("office_light_mode",mode)}catch(e){}}
function bindLightControls(){document.querySelectorAll("[data-light]").forEach(btn=>btn.addEventListener("click",e=>{setLight(btn.dataset.light||"on");sparkAt(e)}));let saved="on";try{saved=localStorage.getItem("office_light_mode")||"on"}catch(e){}setLight(saved)}
function sparkAt(event){const x=event.clientX||0,y=event.clientY||0;for(let i=0;i<12;i++){const s=document.createElement("span");s.className="spark";s.style.left=x+"px";s.style.top=y+"px";const a=(Math.PI*2*i/12),d=22+Math.random()*24;s.style.setProperty("--dx",Math.cos(a)*d+"px");s.style.setProperty("--dy",Math.sin(a)*d+"px");document.body.appendChild(s);setTimeout(()=>s.remove(),780)}}
function bindCardGlow(){document.addEventListener("pointermove",e=>{const card=e.target.closest&&e.target.closest(".card");if(!card)return;const r=card.getBoundingClientRect();card.style.setProperty("--mx",(e.clientX-r.left)+"px");card.style.setProperty("--my",(e.clientY-r.top)+"px")})}
function bindCursor(){const dot=document.getElementById("cursor_dot"),ring=document.getElementById("cursor_ring");if(!dot||!ring)return;let last=0;document.addEventListener("pointermove",e=>{dot.style.transform="translate("+e.clientX+"px,"+e.clientY+"px) translate(-50%,-50%)";ring.style.transform="translate("+e.clientX+"px,"+e.clientY+"px) translate(-50%,-50%)";const hot=!!(e.target.closest&&e.target.closest("a,button,.card"));ring.classList.toggle("hot",hot);const now=Date.now();if(now-last>42){last=now;const t=document.createElement("span");t.className="cursor-trail";t.style.left=e.clientX-5+"px";t.style.top=e.clientY-5+"px";document.body.appendChild(t);setTimeout(()=>t.remove(),560)}});document.addEventListener("pointerdown",e=>{const r=document.createElement("span");r.className="ripple";r.style.left=e.clientX+"px";r.style.top=e.clientY+"px";document.body.appendChild(r);setTimeout(()=>r.remove(),720)})}
function scanRoom(){const s=document.createElement("span");s.className="scanline";document.body.appendChild(s);setTimeout(()=>s.remove(),1200)}
function tidyDesk(){document.querySelectorAll(".card").forEach((card,i)=>{card.style.transform="translateY(-6px)";setTimeout(()=>card.style.transform="",120+i*35)})}
function bindToys(){document.querySelectorAll("[data-toy]").forEach(btn=>btn.addEventListener("click",e=>{e.preventDefault();sparkAt(e);const toy=btn.dataset.toy;if(toy==="scan")scanRoom();if(toy==="confetti")for(let i=0;i<5;i++)setTimeout(()=>sparkAt(e),i*90);if(toy==="tidy")tidyDesk()}))}
function openCard(card,event){if(event&&event.target&&event.target.closest&&event.target.closest(".card-actions,.open-hint"))return;window.open(card.dataset.route||"/",card.dataset.target||"_self")}
function cardOpenKey(event,card){if(event.key!=="Enter"&&event.key!==" ")return;if(event.target&&event.target.closest&&event.target.closest(".card-actions,.open-hint"))return;event.preventDefault();openCard(card,event)}
function servicePill(app,mode){const online=mode==="production"?!!app.production_online:!!app.development_online;const state=mode==="production"?(app.production_state||app.sync_state||"未知"):(app.development_state||app.sync_state||"未知");const label=mode==="production"?(online?"正式版在线":"正式版离线"):(online?"开发版在线":"开发版离线");return '<span class="pill '+(online?"ok":"")+'">'+label+' ｜ '+esc(state)+'</span>'}
function appLabel(app){return (app&&app.name)||app.id||"服务"}
function serviceControlButtons(app,mode){const online=mode==="production"?!!app.production_online:!!app.development_online;const configured=mode==="development"||!!app.production_control_configured;const note=mode==="production"?(app.production_control_note||"正式服务控制"):"本地开发服务控制";const prefix=mode==="production"?"上线服务":"开发服务";const isProduction=mode==="production";const startDisabled=!isProduction&&online,stopDisabled=!isProduction&&!online;const restartDisabled=false;const startClass='control-start '+(!startDisabled&&configured?'control-active':'control-muted');const stopClass='control-stop danger '+(!stopDisabled&&configured?'control-active':'control-muted');const restartClass=configured?'control-active':'control-muted';return '<div class="card-actions" onclick="event.stopPropagation()" onpointerdown="event.stopPropagation()" onkeydown="event.stopPropagation()"><button type="button" data-service-control="'+attr(app.id)+'" data-scope="'+attr(mode)+'" data-app-name="'+attr(appLabel(app))+'" data-action="start" class="'+startClass+'" aria-disabled="'+(startDisabled?'true':'false')+'" title="'+attr(configured?'启动'+prefix:note)+'">启动</button><button type="button" data-service-control="'+attr(app.id)+'" data-scope="'+attr(mode)+'" data-app-name="'+attr(appLabel(app))+'" data-action="restart" class="'+restartClass+'" aria-disabled="'+(restartDisabled?'true':'false')+'" title="'+attr(configured?'重启'+prefix:note)+'">重启</button><button type="button" data-service-control="'+attr(app.id)+'" data-scope="'+attr(mode)+'" data-app-name="'+attr(appLabel(app))+'" data-action="stop" class="'+stopClass+'" aria-disabled="'+(stopDisabled?'true':'false')+'" title="'+attr(configured?'停止'+prefix:note)+'">停止</button></div>'}
function appCard(app,mode){const route=mode==="production"?(app.production_url||app.route||"/"):(app.development_url||app.route||"/");const target=mode==="production"?"_blank":(app.isolated?"_blank":"_self");const desc=mode==="production"?(app.production_note||"正式服务入口"):(app.description||app.config_scope||"本地开发工程入口");const meta=mode==="production"?(app.production_target||route):(app.development_target||route);const state=servicePill(app,mode);const controls=serviceControlButtons(app,mode);const openText=mode==="production"?"打开上线入口":"进入开发工位";const suffix=mode==="production"?"（发布版）":"（开发版）";const anchor=(mode==="production"&&app.id==="assistant")?"production-assistant":(mode+"-"+(app.id||"app"));return '<article id="'+attr(anchor)+'" class="card" role="link" tabindex="0" data-route="'+attr(route)+'" data-target="'+target+'" onclick="openCard(this,event)" onkeydown="cardOpenKey(event,this)"><div class="title">'+esc((app.name||app.id)+suffix)+'</div><div>'+state+'</div><div class="desc">'+esc(desc)+'</div><div class="meta">'+esc(meta)+'</div><a class="open-hint" href="'+attr(route)+'" target="'+attr(target)+'" onclick="event.stopPropagation()">'+openText+'</a>'+controls+'</article>'}
function focusHashCard(){const id=decodeURIComponent((location.hash||"").replace(/^#/,""));if(!id)return;const el=document.getElementById(id);if(!el)return;el.scrollIntoView({behavior:"smooth",block:"center"});el.classList.add("focus-card");setTimeout(()=>el.classList.remove("focus-card"),2600)}
function renderApps(apps){const prod=document.getElementById("home_production_grid"),dev=document.getElementById("home_development_grid");if(prod)prod.innerHTML=apps.map(app=>appCard(app,"production")).join("");if(dev)dev.innerHTML=apps.map(app=>appCard(app,"development")).join("");setTimeout(focusHashCard,60)}
function loadHomeApps(){return fetch("/api/apps").then(r=>r.json()).then(data=>{const apps=data.apps||[];if(apps.length)renderApps(apps);return data}).catch(()=>{document.getElementById("home_app_summary").textContent="状态读取失败"})}
async function controlService(event,app,scope,action,sourceBtn){event.stopPropagation();event.preventDefault();const btn=sourceBtn||event.currentTarget;const name=(btn&&btn.dataset.appName)||app;if(btn&&(btn.getAttribute("aria-disabled")==="true"||btn.dataset.busy==="true"))return;sparkAt(event);document.querySelectorAll('[data-service-control="'+app+'"]').forEach(b=>b.dataset.busy="true");const summary=document.getElementById("home_app_summary");const scopeName=scope==="production"?"上线服务":"开发服务";const actionName={start:"启动",restart:"重启",stop:"停止"}[action]||"控制";if(summary)summary.textContent="正在"+actionName+scopeName+"："+name;try{const r=await fetch("/api/apps",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({app,action,scope,takeover:true})});const data=await r.json();if(data.apps)renderApps(data.apps);if(!data.ok){if(summary)summary.textContent="操作失败："+(data.error||"unknown");return}if(summary)summary.textContent=scopeName+"已"+actionName+"："+name}catch(err){if(summary)summary.textContent="操作失败："+(err&&err.message?err.message:"network error");loadHomeApps()}finally{document.querySelectorAll('[data-service-control="'+app+'"]').forEach(b=>delete b.dataset.busy)}}
function bindServiceControls(){document.addEventListener("click",event=>{const btn=event.target&&event.target.closest&&event.target.closest("[data-service-control][data-action]");if(!btn)return;event.stopPropagation();event.preventDefault();controlService(event,btn.dataset.serviceControl,btn.dataset.scope||"development",btn.dataset.action,btn)},true)}
bindLightControls();bindCardGlow();bindCursor();bindToys();bindServiceControls();loadHomeApps()
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
    initial_apps = _app_statuses().get("apps", [])
    def _project_action_buttons(app_id: str) -> str:
        safe_id = escape(str(app_id), quote=True)
        if is_optimizer:
            return (
                f"<button onclick=\"startJob('{safe_id}','once')\">运行一次</button> "
                f"<button class=\"secondary\" onclick=\"startJob('{safe_id}','daemon')\">启动持续自我学习</button>"
            )
        return (
            f"<button onclick=\"startJob('{safe_id}','once')\">启动虚拟用户测试</button> "
            f"<button class=\"secondary\" onclick=\"startJob('{safe_id}','dev_upgrade')\">一键升级开发版</button> "
            f"<button class=\"ghost\" onclick=\"startJob('{safe_id}','release_deploy')\">一键部署发布版</button> "
            f"<button class=\"ghost\" onclick=\"openFeedbackDialog('{safe_id}')\">输入优化建议</button>"
        )
    initial_cards = "".join(
        (
            '<div class="card">'
            f'<div class="title">{escape(str(app.get("name") or app.get("id") or ""))}</div>'
            f'<div class="desc">{escape(str(app.get("config_scope") or app.get("description") or ""))}</div>'
            f'<div class="meta">项目 ID：{escape(str(app.get("id") or ""))} ｜ 状态：{"在线" if app.get("online") else "离线"} ｜ {escape(str(app.get("sync_state") or ""))}</div>'
            f'<div class="row">{_project_action_buttons(str(app.get("id") or ""))}'
            f'<button class="ghost" onclick="viewJob(\'{escape(str(app.get("id") or ""), quote=True)}\')">查看日志</button>'
            f'<button class="danger" onclick="stopJob(\'{escape(str(app.get("id") or ""), quote=True)}\')">停止</button>'
            '</div></div>'
        )
        for app in initial_apps
    ) or '<div class="card"><div class="title">暂无项目</div><div class="desc">未读取到总控台项目列表。</div></div>'
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
    <a class="home" href="/">杩斿洖鎬绘帶鍙?/a>
  </div>
  <div class="layout">
    <section class="grid" id="project_grid">{initial_cards}</section>
    <main class="card">
      <div class="title">{result_title}</div>
      <div class="status" id="status">閫夋嫨椤圭洰鍚庡彲鍚姩鎴栨煡鐪嬫棩蹇?/div>
      <section class="summary" id="summary_panel" style="{summary_style}">
        <div class="summary-box"><h3>铏氭嫙鐢ㄦ埛姹囨€?/h3><ul id="summary_overview"><li>绛夊緟娴嬭瘯瀹屾垚鍚庣敓鎴愭眹鎬汇€?/li></ul></div>
        <div class="summary-box"><h3>浼樺寲寤鸿</h3><ul id="summary_suggestions"><li>鏆傛棤寤鸿銆?/li></ul></div>
        <div class="summary-box"><h3>棰勮浼樺寲鍚庣殑鏁堟灉</h3><ul id="summary_effects"><li>鏆傛棤棰勮鏁堟灉銆?/li></ul></div>
      </section>
      <details{raw_log_open}><summary>鍘熷杩愯鏃ュ織</summary><pre id="log">鏆傛棤鏃ュ織</pre></details>
    </main>
  </div>
</div>
<div class="dialog-backdrop" id="feedback_dialog">
  <div class="dialog">
    <div class="title">杈撳叆浼樺寲寤鸿</div>
    <p class="desc" id="feedback_target">閫夋嫨椤圭洰鍚庡彲鍐欏叆铏氭嫙鐢ㄦ埛娴嬭瘯寤鸿銆?/p>
    <textarea id="feedback_text" placeholder="渚嬪锛氭櫘閫氳浼楃湅涓嶆噦寮€澶达紝寤鸿鍓?8 绉掑厛鎶涘嚭浜虹墿鍥板锛屽啀杩涘叆涔﹀悕鍜岀珷鑺傘€?></textarea>
    <div class="row">
      <button class="ghost" onclick="closeFeedbackDialog()">鍙栨秷</button>
      <button onclick="submitFeedback()">鍐欏叆寤鸿</button>
    </div>
  </div>
</div>
<script>
const endpoint="{endpoint}";
const isOptimizer={str(is_optimizer).lower()};
const storageKey="quanlan_{kind}_jobs";
let jobs={{}};
try{{jobs=JSON.parse(localStorage.getItem(storageKey)||"{{}}")||{{}}}}catch(e){{jobs={{}}}}
let selectedProject="";
let selectedJobKey="";
function esc(s){{return String(s||"").replace(/[&<>"']/g,c=>({{"&":"&amp;","<":"&lt;",">":"&gt;","\\\"":"&quot;","'":"&#39;"}}[c]))}}
function saveJobs(){{localStorage.setItem(storageKey,JSON.stringify(jobs))}}
function setStatus(text){{document.getElementById("status").textContent=text}}
function listHtml(items,emptyText){{const arr=Array.isArray(items)?items.filter(Boolean):[];return (arr.length?arr:[emptyText]).slice(0,8).map(x=>"<li>"+esc(x)+"</li>").join("")}}
function renderSummary(summary,data){{if(isOptimizer)return;const s=summary||{{}};const running=["running","starting","stopping"].includes((data&&data.status)||"");document.getElementById("summary_overview").innerHTML=listHtml(s.overview,running?"正在生成虚拟用户汇总...":"暂无汇总");document.getElementById("summary_suggestions").innerHTML=listHtml(s.suggestions,running?"测试完成后生成优化建议。":"暂无建议");document.getElementById("summary_effects").innerHTML=listHtml(s.expected_effects,running?"测试完成后估算优化效果。":"暂无预计效果")}}
function actionLabel(mode){{
  if(mode==="dev_upgrade")return "升级开发区";
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
async function loadApps(){{try{{const r=await fetch("/api/apps");const data=await r.json();renderApps(data.apps||[]);if(!(data.apps||[]).length)setStatus("未读取到项目列表")}}catch(err){{setStatus("项目列表读取失败："+(err&&err.message?err.message:"network error"));const grid=document.getElementById("project_grid");if(grid)grid.innerHTML='<div class="card"><div class="title">项目列表读取失败</div><div class="desc">请刷新页面或检查 /api/apps。</div></div>'}}}}
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
window.loadApps=loadApps;window.renderApps=renderApps;window.startJob=startJob;window.stopJob=stopJob;window.viewJob=viewJob;
loadApps();
</script>
</body>
</html>"""
    return _clean_console_html(body.encode("utf-8"))


def _audience_lab_html() -> bytes:
    initial_apps = _app_statuses().get("apps", [])
    project_buttons = "".join(
        (
            f'<button class="project-btn" data-project="{escape(str(app.get("id") or ""), quote=True)}">'
            f'<b>{escape(str(app.get("name") or app.get("id") or ""))}</b>'
            f'<span>{"在线" if app.get("online") else "离线"} ｜ {escape(str(app.get("sync_state") or ""))}</span>'
            "</button>"
        )
        for app in initial_apps
    ) or '<button class="project-btn" data-project="assistant"><b>自媒体小猪理</b><span>等待项目列表</span></button>'
    body = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>虚拟用户测试</title>
  <style>
    :root{{font-family:Arial,"Microsoft YaHei",sans-serif;color:#17202a;background:#f6f8fb;--brand:#0f766e;--brand2:#2563eb;--ink:#102033;--line:#d8e0e7;--muted:#64748b;--card:#fff;--shadow:0 16px 36px rgba(15,23,42,.10);--good:#027a48;--warn:#b54708;--bad:#b3261e}}
    *{{box-sizing:border-box}}body{{margin:0;min-height:100vh;background:radial-gradient(circle at 12% 0%,#d9f99d 0,#f8fafc 27%,transparent 48%),linear-gradient(145deg,#eef7f4 0%,#f7f2ea 52%,#eef4ff 100%)}}.wrap{{max-width:1320px;margin:0 auto;padding:24px 18px 36px}}
    .top{{display:flex;align-items:flex-start;justify-content:space-between;gap:14px;margin-bottom:14px}}.eyebrow{{display:inline-flex;align-items:center;gap:8px;min-height:26px;padding:0 10px;border-radius:999px;background:#102033;color:#fff;font-size:12px;font-weight:900}}.eyebrow:before{{content:"";width:8px;height:8px;border-radius:50%;background:#22c55e;box-shadow:0 0 0 0 rgba(34,197,94,.55);animation:pulse 1.8s infinite}}h1{{font-size:28px;margin:10px 0 7px;letter-spacing:0}}.hint{{color:#415267;font-size:13px;line-height:1.65;margin:0;max-width:820px}}.home{{display:inline-flex;align-items:center;min-height:38px;padding:0 13px;border-radius:8px;background:#111827;color:#fff;text-decoration:none;font-weight:800;white-space:nowrap}}
    .layout{{display:grid;grid-template-columns:360px minmax(0,1fr);gap:14px}}.panel,.card{{background:rgba(255,255,255,.88);border:1px solid var(--line);border-radius:8px;box-shadow:var(--shadow)}}.panel{{padding:14px}}.panel h2{{font-size:16px;margin:0 0 10px}}.stack{{display:grid;gap:10px}}.project-btn,.mode-btn,.persona{{width:100%;text-align:left;border:1px solid #dbe4ea;background:#fff;color:#17202a;border-radius:8px;padding:10px;cursor:pointer;transition:transform .15s ease,border-color .15s ease,box-shadow .15s ease}}.project-btn:hover,.mode-btn:hover,.persona:hover{{transform:translateY(-1px);border-color:#14b8a6}}.project-btn.active,.mode-btn.active,.persona.active{{border-color:#0f766e;box-shadow:0 0 0 3px rgba(20,184,166,.16)}}.project-btn b,.mode-btn b{{display:block;font-size:14px}}.project-btn span,.mode-btn span,.persona span{{display:block;margin-top:4px;font-size:12px;color:var(--muted);line-height:1.45}}
    .modes{{display:grid;grid-template-columns:1fr 1fr;gap:8px}}.personas{{display:grid;grid-template-columns:1fr;gap:7px;max-height:260px;overflow:auto;padding-right:2px}}.persona{{font-size:12px;font-weight:800;padding:8px}}.persona span{{font-weight:400}}.row{{display:flex;gap:8px;flex-wrap:wrap}}button{{border:0;border-radius:7px;background:var(--brand);color:#fff;padding:9px 11px;cursor:pointer;font-weight:800}}button.secondary{{background:#475569}}button.ghost{{background:#eef2f6;color:#263238}}button.danger{{background:var(--bad)}}button:disabled{{opacity:.55;cursor:not-allowed}}button[data-busy="true"]{{opacity:.70;cursor:wait}}
    .work{{display:grid;gap:14px}}.toolbar{{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:10px;align-items:start;padding:14px}}.status{{font-size:13px;color:#0f766e;font-weight:900;line-height:1.55;overflow-wrap:anywhere}}.mini{{font-size:12px;color:var(--muted);line-height:1.5}}.score-grid{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}}.score{{padding:12px;border:1px solid #dbe4ea;border-radius:8px;background:#fff}}.score b{{font-size:22px;display:block}}.score span{{font-size:12px;color:var(--muted)}}.result-grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}}.result-box{{border:1px solid #dbe4ea;border-radius:8px;background:#fff;padding:12px;min-width:0}}.result-box h3{{font-size:14px;margin:0 0 8px}}.result-box ul{{margin:0;padding-left:18px;color:#334155;font-size:13px;line-height:1.62}}.result-box li+li{{margin-top:4px}}.wide{{grid-column:1/-1}}textarea{{width:100%;min-height:98px;border:1px solid #cbd5e1;border-radius:8px;padding:10px;font:13px/1.5 Arial,"Microsoft YaHei",sans-serif;resize:vertical}}pre{{white-space:pre-wrap;background:#111827;color:#e5e7eb;border-radius:8px;padding:12px;height:300px;overflow:auto;margin:0;box-shadow:inset 0 0 0 1px rgba(255,255,255,.06)}}.log-head{{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:8px}}.log-head h3{{margin:0;font-size:14px}}.pill{{display:inline-flex;align-items:center;min-height:24px;padding:0 8px;border-radius:999px;background:#eef2f6;color:#334155;font-size:12px;font-weight:800}}.pill.ok{{background:#ecfdf3;color:#027a48}}.pill.warn{{background:#fff7ed;color:#b54708}}.pill.bad{{background:#fee4e2;color:#b3261e}}
    @keyframes pulse{{0%{{box-shadow:0 0 0 0 rgba(34,197,94,.55)}}70%{{box-shadow:0 0 0 8px rgba(34,197,94,0)}}100%{{box-shadow:0 0 0 0 rgba(34,197,94,0)}}}}@media(max-width:980px){{.layout{{grid-template-columns:1fr}}.toolbar{{grid-template-columns:1fr}}.score-grid,.result-grid{{grid-template-columns:1fr}}}}
  </style>
</head>
<body>
<div class="wrap">
  <div class="top">
    <div><div class="eyebrow">VIRTUAL PANEL ONLINE</div><h1>虚拟用户测试</h1><p class="hint">把作品和产品丢给一组挑剔的虚拟评委：普通用户、专家、竞品销售、疲惫的一线操作者、预算敏感客户和审美评委。这里是模型模拟，不替代真实用户调研，但专门用来提前抓误解、劝退点和上线风险。</p></div>
    <a class="home" href="/">返回首页</a>
  </div>
  <div class="layout">
    <aside class="stack">
      <section class="panel"><h2>项目</h2><div class="stack" id="project_list">{project_buttons}</div></section>
      <section class="panel"><h2>评审强度</h2><div class="modes" id="mode_list">
        <button class="mode-btn active" data-mode="quick"><b>快速体检</b><span>少量素材，先抓明显问题</span></button>
        <button class="mode-btn" data-mode="standard"><b>标准评审</b><span>公开信号 + 本地素材</span></button>
        <button class="mode-btn" data-mode="deep"><b>深度压力测试</b><span>更像“拿出去溜溜”</span></button>
        <button class="mode-btn" data-mode="preflight"><b>上线前复核</b><span>重点看风险和发布稳定性</span></button>
      </div></section>
      <section class="panel"><h2>虚拟评委</h2><div class="personas" id="persona_list">
        <button class="persona active" data-persona="normal">普通用户<span>第一眼能不能看懂、愿不愿意继续</span></button>
        <button class="persona active" data-persona="expert">挑剔专家<span>事实、逻辑、证据链和专业感</span></button>
        <button class="persona active" data-persona="competitor">竞品销售<span>会怎样攻击你的卖点</span></button>
        <button class="persona active" data-persona="operator">疲惫的一线操作者<span>流程麻烦、按钮不清、信息太挤</span></button>
        <button class="persona active" data-persona="budget">预算敏感客户<span>值不值、风险大不大、替代品是什么</span></button>
        <button class="persona active" data-persona="taste">品牌/审美评委<span>画面、文字、质感和可信度</span></button>
        <button class="persona active" data-persona="safety">安全/合规检查<span>夸大、误导、隐私和高风险表达</span></button>
      </div></section>
    </aside>
    <main class="work">
      <section class="card toolbar">
        <div><div class="status" id="status">选择项目和强度后启动评审。</div><div class="mini" id="context_line">当前：自媒体小猪理 / 快速体检</div></div>
        <div class="row">
          <button id="start_btn" onclick="startReview()">启动评审</button>
          <button class="danger" onclick="stopReview()">停止</button>
          <button class="ghost" onclick="loadReport(true)">读取最新报告</button>
          <button class="secondary" onclick="submitFeedback()">写入优化建议</button>
          <button class="ghost" onclick="clearPageLog()">清空本页日志</button>
        </div>
      </section>
      <section class="score-grid">
        <div class="score"><b id="score_overall">--</b><span>综合判断</span></div>
        <div class="score"><b id="score_positive">--</b><span>正向评价</span></div>
        <div class="score"><b id="score_negative">--</b><span>反对意见</span></div>
        <div class="score"><b id="score_status">待测</b><span>联动状态</span></div>
      </section>
      <section class="result-grid">
        <div class="result-box"><h3>正向评价</h3><ul id="overview"><li>等待评审。</li></ul></div>
        <div class="result-box"><h3>主要反对意见</h3><ul id="objections"><li>等待评审。</li></ul></div>
        <div class="result-box"><h3>建议改动</h3><ul id="suggestions"><li>等待评审。</li></ul></div>
        <div class="result-box"><h3>仍需真人确认</h3><ul id="human"><li>真实观众数据、业务风险和专业事实仍需人工确认。</li></ul></div>
        <div class="result-box wide"><h3>人工观察写入</h3><textarea id="feedback_text" placeholder="例如：开头不要问虚的问题，要直接切中全文科学问题；目录页信息太挤；客户看不懂按钮含义。"></textarea></div>
        <div class="result-box wide"><div class="log-head"><h3>运行日志</h3><span class="pill" id="job_pill">未运行</span></div><pre id="log">暂无日志</pre></div>
      </section>
    </main>
  </div>
</div>
<script>
const projectNames={{assistant:"自媒体小猪理",xiaozhuli:"全澜小猪理",eeg:"脑电分析平台"}};
let selectedProject=localStorage.getItem("audience_lab_project")||"assistant";
let selectedMode=localStorage.getItem("audience_lab_mode")||"quick";
let currentJob=localStorage.getItem("audience_lab_job")||"";
const logKey="audience_lab_page_log";
function esc(s){{return String(s||"").replace(/[&<>"']/g,c=>({{"&":"&amp;","<":"&lt;",">":"&gt;","\\\"":"&quot;","'":"&#39;"}}[c]))}}
function setStatus(text){{document.getElementById("status").textContent=text;appendPageLog(text)}}
function appendPageLog(text){{const line="["+new Date().toLocaleTimeString()+"] "+text+"\\n";let old="";try{{old=localStorage.getItem(logKey)||""}}catch(e){{}}const next=(old+line).slice(-16000);try{{localStorage.setItem(logKey,next)}}catch(e){{}}const el=document.getElementById("log");if(el&&(!currentJob||el.textContent==="暂无日志"))el.textContent=next||"暂无日志"}}
function clearPageLog(){{try{{localStorage.removeItem(logKey)}}catch(e){{}}document.getElementById("log").textContent="本页日志已清空。";setStatus("本页日志已清空")}}
function activeSync(){{document.querySelectorAll("[data-project]").forEach(b=>b.classList.toggle("active",b.dataset.project===selectedProject));document.querySelectorAll("[data-mode]").forEach(b=>b.classList.toggle("active",b.dataset.mode===selectedMode));document.getElementById("context_line").textContent="当前："+(projectNames[selectedProject]||selectedProject)+" / "+modeName(selectedMode)}}
function modeName(mode){{return {{quick:"快速体检",standard:"标准评审",deep:"深度压力测试",preflight:"上线前复核"}}[mode]||"标准评审"}}
function bindControls(){{document.querySelectorAll("[data-project]").forEach(b=>b.addEventListener("click",()=>{{selectedProject=b.dataset.project;localStorage.setItem("audience_lab_project",selectedProject);activeSync();loadReport(false);setStatus("已切换项目："+(projectNames[selectedProject]||selectedProject))}}));document.querySelectorAll("[data-mode]").forEach(b=>b.addEventListener("click",()=>{{selectedMode=b.dataset.mode;localStorage.setItem("audience_lab_mode",selectedMode);activeSync();setStatus("已选择强度："+modeName(selectedMode))}}));document.querySelectorAll("[data-persona]").forEach(b=>b.addEventListener("click",()=>{{b.classList.toggle("active");setStatus("已调整虚拟评委："+b.textContent.trim().replace(/\\s+/g," "))}}))}}
function personas(){{return Array.from(document.querySelectorAll("[data-persona].active")).map(x=>x.dataset.persona)}}
function listHtml(items,emptyText){{const arr=Array.isArray(items)?items.filter(Boolean):[];return (arr.length?arr:[emptyText]).slice(0,10).map(x=>"<li>"+esc(x)+"</li>").join("")}}
function renderSummary(summary,meta){{summary=summary||{{}};document.getElementById("overview").innerHTML=listHtml(summary.overview,"暂无正向评价。");document.getElementById("objections").innerHTML=listHtml(summary.objections||summary.risks,"暂无主要反对意见。");document.getElementById("suggestions").innerHTML=listHtml(summary.suggestions,"暂无建议。");document.getElementById("human").innerHTML=listHtml(summary.needs_human_confirmation||summary.expected_effects,"真实观众数据、业务风险和专业事实仍需人工确认。");const counts=summary.counts||{{}};document.getElementById("score_overall").textContent=counts.overall||"--";document.getElementById("score_positive").textContent=counts.positive||"--";document.getElementById("score_negative").textContent=counts.negative||"--";document.getElementById("score_status").textContent=(meta&&meta.status)||"待测"}}
async function startReview(){{const btn=document.getElementById("start_btn");btn.dataset.busy="true";btn.disabled=true;try{{setStatus("正在创建评审任务："+(projectNames[selectedProject]||selectedProject)+" / "+modeName(selectedMode));document.getElementById("job_pill").textContent="启动中";document.getElementById("log").textContent="正在创建任务...";const r=await fetch("/api/audience",{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify({{project:selectedProject,mode:selectedMode,personas:personas()}})}});const data=await r.json();if(!data.ok){{setStatus("启动失败："+(data.error||"unknown"));document.getElementById("log").textContent=data.error||"启动失败";return}}currentJob=data.job_id;localStorage.setItem("audience_lab_job",currentJob);setStatus("评审已启动："+(data.name||selectedProject)+" / "+modeName(data.mode||selectedMode));pollJob()}}catch(err){{setStatus("启动失败："+(err&&err.message?err.message:"network error"))}}finally{{btn.dataset.busy="";btn.disabled=false}}}}
async function stopReview(){{if(!currentJob){{setStatus("没有正在运行的评审任务");return}}setStatus("正在发送停止请求...");const r=await fetch("/api/stop?id="+encodeURIComponent(currentJob),{{method:"POST"}});const data=await r.json().catch(()=>({{ok:false,message:"停止接口没有返回 JSON"}}));setStatus(data.ok?"停止请求已发送":"停止失败："+(data.message||data.error||"unknown"));pollJob()}}
async function pollJob(){{if(!currentJob)return;const r=await fetch("/api/job?id="+encodeURIComponent(currentJob));const data=await r.json();const status=data.status||"missing";document.getElementById("job_pill").textContent=status;document.getElementById("job_pill").className="pill "+(status==="finished"?(data.exit_code===0?"ok":"warn"):(["running","starting","stopping"].includes(status)?"warn":""));document.getElementById("log").textContent=(data.lines||[]).join("")||localStorage.getItem(logKey)||"暂无日志";renderSummary(data.summary,{{status:status==="finished"?(data.exit_code===0?"完成":"未完成"):status}});if(["running","starting","stopping"].includes(status))setTimeout(pollJob,1200);else loadReport(false)}}
async function loadReport(showStatus){{try{{const r=await fetch("/api/audience_report?project="+encodeURIComponent(selectedProject));const data=await r.json();if(data.ok&&data.summary){{renderSummary(data.summary,{{status:data.report_found?"已读取":"待测"}});if(data.readable_log&&data.readable_log.length&&!currentJob)document.getElementById("log").textContent=data.readable_log.join("\\n");if(showStatus)setStatus(data.report_found?"已读取最新报告："+(data.report_path||""):"还没有找到该项目的评审报告")}}}}catch(err){{if(showStatus)setStatus("读取报告失败："+(err&&err.message?err.message:"network error"))}}}}
async function submitFeedback(){{const text=document.getElementById("feedback_text").value.trim();if(!text){{setStatus("请先写入人工观察");return}}setStatus("正在写入人工观察...");const r=await fetch("/api/audience_feedback",{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify({{project:selectedProject,text}})}});const data=await r.json();if(!data.ok){{setStatus("写入失败："+(data.error||"unknown"));return}}document.getElementById("feedback_text").value="";setStatus("人工观察已写入："+(data.name||selectedProject));renderSummary({{overview:["已收到人工观察，下一轮评审会把它当作必须复测的问题。"],objections:[text],suggestions:["把这条观察转成下一轮可验证的修复项。"],needs_human_confirmation:["请在真实产物和真实用户反馈中复核这条观察。"],counts:{{overall:"记录",positive:"1",negative:"1"}}}},{{status:"已写入"}})}}
bindControls();activeSync();document.getElementById("log").textContent=localStorage.getItem(logKey)||"暂无日志";if(currentJob)pollJob();loadReport(false);
</script>
</body>
</html>"""
    return _clean_console_html(body.encode("utf-8"))


def _cloud_monitor_html() -> bytes:
    body = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>云服务器健康舱</title>
  <style>
    :root{font-family:Arial,"Microsoft YaHei",sans-serif;color:#17202a;background:#eef5f2;--brand:#0f766e;--brand2:#2563eb;--ink:#102033;--line:#d8e0e7;--muted:#64748b;--card:#fff;--bad:#b3261e;--ok:#027a48;--warn:#b54708;--shadow:0 16px 36px rgba(15,23,42,.10);--beam:rgba(250,204,21,.22)}
    *{box-sizing:border-box}body{margin:0;min-height:100vh;padding:20px;background:linear-gradient(145deg,#eef7f4 0%,#f7f2ea 52%,#eef4ff 100%);color:var(--ink)}body:before{content:"";position:fixed;inset:0;pointer-events:none;background:linear-gradient(115deg,transparent 0 42%,var(--beam) 48%,transparent 56%);transform:translateX(-80%);animation:sweep 10s linear infinite;mix-blend-mode:multiply}.wrap{max-width:1280px;margin:0 auto;position:relative}
    .top{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;margin-bottom:14px;border:1px solid rgba(15,118,110,.18);border-radius:8px;background:rgba(255,255,255,.80);box-shadow:var(--shadow);padding:18px;position:relative;overflow:hidden}.top:before{content:"";position:absolute;left:0;right:0;top:0;height:4px;background:linear-gradient(90deg,#14b8a6,#2563eb,#f59e0b)}.top:after{content:"";position:absolute;left:-30%;top:0;width:24%;height:100%;background:linear-gradient(90deg,transparent,rgba(255,255,255,.48),transparent);transform:skewX(-18deg);animation:shine 7s ease-in-out infinite}.top>*{position:relative}.eyebrow{display:inline-flex;align-items:center;gap:8px;min-height:24px;padding:0 10px;border-radius:999px;background:#102033;color:#fff;font-size:12px;font-weight:900}.eyebrow:before{content:"";width:8px;height:8px;border-radius:50%;background:#22c55e;box-shadow:0 0 0 0 rgba(34,197,94,.6);animation:pulseDot 1.8s infinite}
    h1{font-size:30px;line-height:1.12;margin:10px 0 7px;letter-spacing:0}.hint{color:#415267;font-size:13px;line-height:1.7;margin:0;max-width:850px}a.home{display:inline-flex;align-items:center;min-height:38px;padding:0 13px;border-radius:999px;background:#111827;color:#fff;text-decoration:none;font-weight:900;box-shadow:0 10px 18px rgba(17,24,39,.14);white-space:nowrap}.layout{display:grid;grid-template-columns:1fr 420px;gap:14px}.card{background:rgba(255,255,255,.88);border:1px solid var(--line);border-radius:8px;padding:14px;box-shadow:var(--shadow);position:relative;overflow:hidden}.card:before{content:"";display:block;height:4px;background:linear-gradient(90deg,#14b8a6,#2563eb,#f59e0b);position:absolute;left:0;right:0;top:0}.title{font-size:17px;font-weight:900;margin-bottom:8px;color:#102033}
    .toolbar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:12px;border:1px solid rgba(15,118,110,.16);border-radius:8px;background:rgba(255,255,255,.76);box-shadow:0 10px 22px rgba(15,23,42,.06);padding:10px}.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}button{border:0;border-radius:7px;background:linear-gradient(135deg,var(--brand),#14b8a6);color:#fff;padding:8px 10px;cursor:pointer;font-weight:900;transition:transform .18s ease,filter .18s ease,box-shadow .18s ease}button:hover{transform:translateY(-1px);filter:brightness(1.05);box-shadow:0 10px 18px rgba(15,118,110,.18)}button.secondary{background:linear-gradient(135deg,#334155,#64748b)}button.danger{background:linear-gradient(135deg,#b3261e,#f97316)}button.ghost{background:#eef2f6;color:#263238}button:disabled{opacity:.65;cursor:wait;transform:none}.pill{display:inline-flex;align-items:center;min-height:24px;padding:0 8px;border-radius:999px;background:#eef2f6;color:#334155;font-size:12px;font-weight:900}.pill.ok{background:#ecfdf3;color:var(--ok)}.pill.warn{background:#fff7ed;color:var(--warn)}
    .server{display:grid;gap:12px}.server-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-top:2px}.meta{color:var(--muted);font-size:12px;line-height:1.5;overflow-wrap:anywhere}.metrics{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:8px;margin-top:10px}.metric{border:1px solid var(--line);border-radius:8px;background:#f8fafc;padding:10px;min-height:76px;position:relative;overflow:hidden}.metric:after{content:"";position:absolute;left:0;right:0;bottom:0;height:3px;background:#cbd5e1}.metric.status-ok:after{background:#22c55e}.metric.status-warn:after{background:#f59e0b}.metric.status-bad:after{background:#ef4444}.metric b{display:block;font-size:12px;color:#334155}.metric span{display:block;margin-top:8px;font-size:17px;font-weight:900}.metric small{display:block;color:var(--muted);margin-top:4px;line-height:1.35}
    .services{display:grid;gap:8px;margin-top:10px}.service{border:1px solid var(--line);border-radius:8px;padding:10px;background:#fff}.service-top{display:flex;justify-content:space-between;gap:8px;align-items:center}.resource-line{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:6px;margin-top:8px}.resource-line span,.process-row{border:1px solid #e5e7eb;border-radius:7px;background:#f8fafc;padding:6px;font-size:12px;color:#334155;overflow-wrap:anywhere}.processes{display:grid;gap:6px;margin-top:12px}.process-row{display:grid;grid-template-columns:70px 70px 80px minmax(0,1fr);gap:8px;align-items:start}.process-main b{display:inline-block;margin-right:6px}.process-main small{display:block;color:var(--muted);line-height:1.45;margin-top:3px}.status{font-size:13px;color:var(--brand);margin:0 0 10px;word-break:break-all;font-weight:800}pre{white-space:pre-wrap;background:#111827;color:#e5e7eb;border-radius:8px;padding:12px;max-height:52vh;overflow:auto;margin:0;box-shadow:inset 0 0 0 1px rgba(255,255,255,.06)}.note{font-size:12px;color:var(--muted);line-height:1.55;margin-top:10px}
    @keyframes sweep{0%{transform:translateX(-80%)}45%,100%{transform:translateX(130%)}}@keyframes shine{0%,55%{left:-30%}75%,100%{left:120%}}@keyframes pulseDot{0%{box-shadow:0 0 0 0 rgba(34,197,94,.55)}70%{box-shadow:0 0 0 8px rgba(34,197,94,0)}100%{box-shadow:0 0 0 0 rgba(34,197,94,0)}}@media(prefers-reduced-motion:reduce){*,*:before,*:after{animation:none!important;transition:none!important}}
    @media(max-width:980px){.layout{grid-template-columns:1fr}.metrics{grid-template-columns:repeat(2,minmax(0,1fr))}.top{flex-direction:column}.resource-line,.process-row{grid-template-columns:1fr 1fr}.process-row span:last-child{grid-column:1/-1}}@media(max-width:560px){body{padding:12px}.metrics,.resource-line,.process-row{grid-template-columns:1fr}h1{font-size:24px}}
  </style>
</head>
<body>
<div class="wrap">
  <div class="top">
    <div><div class="eyebrow">CLOUD WATCH ONLINE</div><h1>云服务器健康舱</h1><p class="hint">正式服务的值班台：看在线、健康接口、延迟、CPU、内存、硬盘、负载、网络和每个服务的资源占用。按钮负责发指令，日志负责交代清楚。</p></div>
    <a class="home" href="/">返回总控台</a>
  </div>
  <div class="toolbar">
    <button onclick="refreshCloud(this)">手动刷新</button>
    <button class="secondary" id="toggle_monitor" onclick="toggleMonitor(this)">暂停监控</button>
    <button class="ghost" onclick="openCloud()">打开正式服务</button>
    <button class="danger" onclick="clearCloudLogs(this)">清空日志</button>
  </div>
  <div class="layout">
    <main id="server_list" class="server"></main>
    <aside class="card">
      <div class="title">健康舱日志</div>
      <div class="status" id="cloud_status">等待刷新</div>
      <pre id="cloud_log">暂无日志</pre>
      <div class="note" id="metrics_note"></div>
    </aside>
  </div>
</div>
<script>
let cloudState={enabled:true,servers:[],logs:[]};
function esc(s){return String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\\\"":"&quot;","'":"&#39;"}[c]))}
function pill(ok,text){return '<span class="pill '+(ok?'ok':'warn')+'">'+esc(text)+'</span>'}
function metric(label,m){m=m||{};const text=m.label||"待接入";const cls="status-"+(m.status||"unknown");return '<div class="metric '+esc(cls)+'"><b>'+esc(label)+'</b><span>'+esc(text)+'</span><small>'+esc(m.status==="unknown"?"等待采集器写入":(m.unit||""))+'</small></div>'}
function renderCloud(data){cloudState=data||cloudState;document.getElementById("toggle_monitor").textContent=cloudState.enabled?"暂停监控":"恢复监控";document.getElementById("cloud_status").textContent=(cloudState.enabled?"监控中":"已暂停")+" ｜ "+(cloudState.updated_at||"");document.getElementById("cloud_log").textContent=(cloudState.logs||[]).slice(-40).join("\\n")||"暂无日志";document.getElementById("metrics_note").textContent=(cloudState.servers||[]).some(s=>s.remote_metrics&&s.remote_metrics.ok)?"已接入 SSH 只读采集：整体资源和服务进程占用来自云服务器。":((cloudState.metrics_connected?"已接入指标文件：":"尚未接入 CPU/内存/硬盘采集器；预留文件：")+(cloudState.metrics_source||""));
  document.getElementById("server_list").innerHTML=(cloudState.servers||[]).map(s=>'<article class="card"><div class="server-head"><div><div class="title">'+esc(s.name)+'</div><div class="meta">'+esc(s.provider)+' ｜ '+esc(s.host)+' ｜ '+esc(s.root_url)+'</div><div class="meta">采集主机：'+esc((s.remote_metrics&&s.remote_metrics.host)||"待接入")+' ｜ '+esc((s.remote_metrics&&s.remote_metrics.collected_at)||"")+'</div></div><div>'+pill(!!s.online,s.online?"在线":"不可达")+'</div></div><div class="row"><span class="pill">延迟 '+esc(s.latency_ms==null?"待测":s.latency_ms+"ms")+'</span><span class="pill">健康接口 '+esc((s.health_probe&&s.health_probe.message)||"待测")+'</span><span class="pill">首页 '+esc((s.root_probe&&s.root_probe.message)||"待测")+'</span><span class="pill">'+esc((s.remote_metrics&&s.remote_metrics.ok)?"资源已采集":((s.remote_metrics&&s.remote_metrics.error)||"资源待接入"))+'</span></div><div class="metrics">'+metric("CPU",s.metrics&&s.metrics.cpu)+metric("内存",s.metrics&&s.metrics.memory)+metric("硬盘",s.metrics&&s.metrics.disk)+metric("负载",s.metrics&&s.metrics.load)+metric("网络",s.metrics&&s.metrics.network)+'</div><div class="services">'+(s.services||[]).map(serviceHtml).join("")+'</div>'+processHtml(s.top_processes||[])+'</article>').join("")}
function serviceHtml(app){const r=app.resource||{};const actions=app.protected?'<div class="row"><span class="pill warn">保护链路：不在这里停用</span><span class="pill">可优化模型/缓存/启动策略</span></div>':'<div class="row"><button onclick="controlService(event,\\''+esc(app.id)+'\\',\\'start\\')">启动</button><button class="secondary" onclick="controlService(event,\\''+esc(app.id)+'\\',\\'restart\\')">重启</button><button class="danger" onclick="controlService(event,\\''+esc(app.id)+'\\',\\'stop\\')">停止</button><button class="ghost" onclick="window.open(\\''+esc(app.production_url||app.route||"/")+'\\',\\'_blank\\')">打开</button></div>';return '<div class="service"><div class="service-top"><div><b>'+esc(app.name||app.id)+'</b><div class="meta">'+esc(app.production_target||app.production_url||"")+'</div><div class="meta">'+esc(app.description||"")+'</div></div>'+pill(!!app.production_online,app.production_online?"在线":"离线")+'</div><div class="resource-line"><span>systemd '+esc(r.systemd||"未知")+'</span><span>进程 '+esc(r.process_count??"0")+'</span><span>CPU '+esc((r.cpu_percent??0)+"%")+'</span><span>内存 '+esc(r.rss_label||"0B")+'</span></div>'+actions+'</div>'}
function processHtml(rows){rows=(rows||[]).slice(0,8);if(!rows.length)return "";return '<div class="processes"><div class="title">占用最高进程</div>'+rows.map(p=>'<div class="process-row"><b>PID '+esc(p.pid)+'</b><span>CPU '+esc(p.cpu_percent)+'%</span><span>内存 '+esc(p.mem_percent)+'%</span><span class="process-main"><b>'+esc(p.owner||"系统")+'</b>'+esc(p.command)+'<small>'+esc(p.purpose||"用途未识别")+'</small><small>建议：'+esc(p.advice||"观察即可")+'</small><small>'+esc(p.args||"")+'</small></span></div>').join("")+'</div>'}
async function refreshCloud(btn){if(btn)btn.disabled=true;try{const r=await fetch("/api/cloud_servers");renderCloud(await r.json())}catch(err){document.getElementById("cloud_status").textContent="刷新失败："+(err&&err.message?err.message:"network error")}finally{if(btn)btn.disabled=false}}
async function postCloud(action,btn){if(btn)btn.disabled=true;try{const r=await fetch("/api/cloud_servers",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({action})});renderCloud(await r.json())}finally{if(btn)btn.disabled=false}}
function toggleMonitor(btn){postCloud(cloudState.enabled?"pause":"resume",btn)}
function clearCloudLogs(btn){postCloud("clear_logs",btn)}
function openCloud(){const s=(cloudState.servers||[])[0];window.open((s&&s.root_url)||"http://39.97.248.225/","_blank")}
async function controlService(event,app,action){const btn=event.currentTarget;btn.disabled=true;document.getElementById("cloud_status").textContent="正在"+({start:"启动",restart:"重启",stop:"停止"}[action]||"控制")+"："+app;try{const r=await fetch("/api/apps",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({app,action,scope:"production",takeover:true})});const data=await r.json();if(!data.ok){document.getElementById("cloud_status").textContent="操作失败："+(data.error||"unknown")}else{document.getElementById("cloud_status").textContent="操作已发送："+app}await postCloud("refresh")}catch(err){document.getElementById("cloud_status").textContent="操作失败："+(err&&err.message?err.message:"network error")}finally{btn.disabled=false}}
refreshCloud();
setInterval(()=>{if(cloudState.enabled)refreshCloud()},15000);
</script>
</body>
</html>"""
    return body.encode("utf-8")


def _clean_console_html(body: bytes) -> bytes:
    text = body.decode("utf-8", errors="replace")
    replacements = {
        "澶фā鍨嬭繛鎺ュ簱": "大模型连接库",
        "杩斿洖鎺у埗鍙伴椤?": "返回控制台首页",
        "杩斿洖鎬绘帶鍙?": "返回总控台",
        "閫夋嫨椤圭洰鍚庡彲鍚姩鎴栨煡鐪嬫棩蹇?/div>": "选择项目后可启动或查看日志</div>",
        "閫夋嫨椤圭洰鍚庡彲鍚姩鎴栨煡鐪嬫棩蹇?": "选择项目后可启动或查看日志",
        "鏆傛棤鏃ュ織": "暂无日志",
        "鍘熷杩愯鏃ュ織": "原始运行日志",
        "绛夊緟鎿嶄綔": "等待操作",
        "铏氭嫙鐢ㄦ埛姹囨€?": "虚拟用户汇总",
        "浼樺寲寤鸿": "优化建议",
        "棰勮浼樺寲鍚庣殑鏁堟灉": "预计优化后的效果",
        "绛夊緟娴嬭瘯瀹屾垚鍚庣敓鎴愭眹鎬汇€?": "等待测试完成后生成汇总。",
        "鏆傛棤寤鸿銆?": "暂无建议。",
        "鏆傛棤棰勮鏁堟灉銆?": "暂无预计效果。",
        "杈撳叆浼樺寲寤鸿": "输入优化建议",
        "鍐欏叆寤鸿": "写入建议",
        "鍙栨秷": "取消",
        "杩愯涓€娆?": "运行一次",
        "鍚姩甯搁┗": "启动常驻",
        "启动常驻": "启动持续自我学习",
        "鍚姩铏氭嫙鐢ㄦ埛娴嬭瘯": "启动虚拟用户测试",
        "涓€閿崌绾у紑鍙戠増": "一键升级开发版",
        "涓€閿儴缃插彂甯冪増": "一键部署发布版",
        "鏌ョ湅鏃ュ織": "查看日志",
        "鍋滄": "停止",
        "鍦ㄧ嚎": "在线",
        "绂荤嚎": "离线",
        "椤圭洰 ID锛?": "项目 ID：",
        "鐘舵€侊細": "状态：",
        "姝ｅ湪澶勭悊": "正在处理",
        "姝ｅ湪鍋滄": "正在停止",
        "宸插畬鎴?": "已完成",
        "鏈畬鎴愶紝璇锋煡鐪嬫棩蹇?": "未完成，请查看日志",
        "浠诲姟澶辫触": "任务失败",
        "绛夊緟鎿嶄綔": "等待操作",
        "鍋滄璇锋眰宸插彂閫?": "停止请求已发送",
        "娌℃湁鍙仠姝㈢殑浠诲姟": "没有可停止的任务",
        "澶фā鍨嬭繛鎺?": "大模型连接",
        "杩炴帴搴撴搷浣?": "连接库操作",
        "璇诲彇涓?": "读取中",
        "娣诲姞杩炴帴": "添加连接",
        "涓€閿簲鐢ㄥ埌鎵€鏈夐」鐩苟妫€娴?": "一键应用到所有项目并检测",
        "涓€閿祴璇曞強淇": "一键测试及修复",
        "鍒锋柊杩炴帴搴?": "刷新连接库",
        "鑷姩缁勫悎鎽樿": "自动组合摘要",
        "鏈€夋嫨": "未选择",
        "姝ラ娴佺▼": "步骤流程",
        "妯″瀷搴?": "模型库",
        "娣诲姞澶фā鍨嬭繛鎺?": "添加大模型连接",
        "妯″瀷绫诲埆": "模型类别",
        "鏂囨湰": "文本",
        "澶囩敤鏂囨湰": "备用文本",
        "娑﹁壊": "润色",
        "鐢熷浘": "生图",
        "閰嶉煶 BGM": "配音 BGM",
        "杩炴帴鍚嶇О": "连接名称",
        "妯″瀷鍚?": "模型名",
        "淇濆瓨鍒拌繛鎺ュ簱": "保存到连接库",
        "宸插瓨": "已存",
        "鏈瓨": "未存",
        "鏈祴璇?": "未测试",
        "娴嬭瘯": "测试",
        "缂栬緫": "编辑",
        "鍒犻櫎": "删除",
        "渚涘簲鍟?": "供应商",
        "妯″瀷": "模型",
        "涓繛鎺?": "个连接",
        "鏈缃?": "未设置",
        "寤惰繜": "延迟",
        "鏈€杩戠粨鏋滐細": "最近结果：",
        "鎷栧叆妯″瀷杩炴帴浣滀负鍊欓€?": "拖入模型连接作为候选",
        "褰撳墠浼氶€夛細": "当前会选：",
        "杩炴帴搴撹嚜鍔ㄧ粍鍚?": "连接库自动组合",
        "鏃犵粨鏋?": "无结果",
        "閫氳繃": "通过",
        "澶辫触": "失败",
        "姝ｅ湪": "正在",
        "浠诲姟": "任务",
        "宸插惎鍔?": "已启动",
        "宸插垱寤?": "已创建",
        "璇诲彇": "读取",
        "鍚庡彴": "后台",
        "缂栧彿": "编号",
        "椤圭洰": "项目",
        "浼氬": "会",
        "妯″瀷": "模型",
        "杩炴帴": "连接",
        "鍊欓€?": "候选",
        "閰嶇疆": "配置",
        "妫€娴?": "检测",
        "鍐欏叆": "写入",
        "宸叉敹鍒?": "已收到",
        "鍚庣画": "后续",
        "寤鸿": "建议",
        "棰勮": "预计",
        "鐢熸垚": "生成",
        "姹囨€?": "汇总",
        "鏁堟灉": "效果",
        "娴嬭瘯": "测试",
        "鍚姩": "启动",
        "闁埧": "问题",
        "閫夋嫨项目鍚庡彲写入铏氭嫙鐢ㄦ埛测试建议銆?": "选择项目后可写入虚拟用户测试建议。",
        "渚嬪锛氭櫘閫氒浼楃湅涓嶆噦寮€澶达紝建议鍓?8 绉掑厛鎶涘嚭浜虹墿鍥板锛屽啀杩涘叆涔﹀悕鍜岀珷鑺傘€?": "例如：普通观众看不懂开头，建议前 8 秒先抛出人物困境，再进入书名和章节。",
        "鏆傛棤汇总": "暂无汇总",
        "鏆傛棤建议": "暂无建议",
        "绛夊緟后台杩斿洖任务编号": "等待后台返回任务编号",
        "绛夊緟虚拟用户测试瀹屾垚鍚庣敓鎴愬缓璁€?": "等待虚拟用户测试完成后生成建议。",
        "测试瀹屾垚鍚庣敓鎴愪紭鍖栧缓璁€?": "测试完成后生成优化建议。",
        "测试瀹屾垚鍚庝及绠椾紭鍖栨晥鏋溿€?": "测试完成后估算优化效果。",
        "测试瀹屾垚鍚": "测试完成后",
        "瀹屾垚": "完成",
        "宸插惎鍔細": "已启动：",
        "任务宸插垱寤猴紝正在读取后台鏃ュ織": "任务已创建，正在读取后台日志",
        "鏆傛棤鏈〉启动鐨勪换鍔?": "暂无本页启动的任务",
        "停止璇锋眰宸插彂閫?": "停止请求已发送",
        "优化建议宸插啓鍏ワ細": "优化建议已写入：",
        "宸叉敹鍒颁汉宸ヤ紭鍖栧缓璁紝后续虚拟用户测试浼氭妸瀹冪撼鍏ラ棶棰橀槦鍒椼€?": "已收到人工优化建议，后续虚拟用户测试会把它纳入问题队列。",
        "预计涓嬩竴杞細鍥寸粫杩欐潯建议生成鏇村叿浣撶殑淇椤瑰拰澶嶆祴缁撴灉銆?": "预计下一轮会围绕这条建议生成更具体的修复项和复测结果。",
        "锝?": " ｜ ",
        "涓嬩竴": "下一",
        "杞細": "轮会",
        "鏇村叿浣撶殑": "更具体的",
        "淇": "修复",
        "澶嶆祴": "复测",
        "缁撴灉": "结果",
        "鐨勪换鍔?": "的任务",
        "鍚庡彲": "后可",
        "鍚庣敓鎴?": "后生成",
        "杩斿洖": "返回",
        "姣忕被": "每类",
        "瀹屾垚": "完成",
        "鏈〉": "本页",
        "鍏堝閫?": "优先备选",
        "淇濆瓨": "保存",
        "鍒囨崲": "切换",
        "涓嶈兘鏀惧叆璇ユ楠?": "不能放入该步骤",
        "姝ラ": "步骤",
        "鏃犲彲鐢ㄦā鍨?": "无可用模型",
        "鏈€氳繃": "未通过",
        "灏濊瘯": "尝试",
        "鍏叡澶фā鍨嬮厤缃簲鐢ㄥ畬鎴?": "公共大模型配置应用完成",
        "鎵€鏈夐渶瑕侀」鐩凡鏇存柊骞堕€氳繃妫€娴?": "所有需要的项目已更新并通过检测",
        "鏈夐」鐩湭閫氳繃閰嶇疆妫€娴嬶紝璇︽儏瑙佸彸渚ф棩蹇?": "有项目未通过配置检测，详情见右侧日志",
        "褰撳墠娌℃湁正在杩愯鐨勪换鍔?": "当前没有正在运行的任务",
        "返回控制台首页/a>": "返回控制台首页",
        "返回总控台/a>": "返回总控台",
        "连接库操作/h3>": "连接库操作",
        "读取中/span>": "读取中",
        "一键应用到所有项目并检测/button>": "一键应用到所有项目并检测",
        "刷新连接库/button>": "刷新连接库",
        "模型库/h3>": "模型库",
        "选择项目后可启动或查看日志/div>": "选择项目后可启动或查看日志",
        "虚拟用户汇总/h3>": "虚拟用户汇总",
        "等待测试完成后生成汇总。/li>": "等待测试完成后生成汇总。",
        "暂无建议。/li>": "暂无建议。",
        "暂无预计效果。/li>": "暂无预计效果。",
        "涓嶅啀浜哄伐閫夋嫨鏁村澶фā鍨嬫柟妗堬紱杩欓噷鎸夋ā鍨嬬被鍒淮鎶よ繛鎺ュ簱锛屼换鍔″惎鍔ㄦ椂浼氳嚜鍔ㄤ粠每类鍙敤连接涓粍鍚堟墽琛屻€傜綉椤典笌鏃ュ織涓嶅洖鏄炬槑鏂?Key銆?/p>": "这里按模型类别维护连接库；任务启动时会自动从每类可用连接中组合执行。网页与日志不回显明文 Key。",
        "鎶婂彸渚фā鍨嬫嫋鍒版楠ら噷浣滀负候选/span>": "把右侧模型拖到步骤里作为候选",
        "鎸変緵搴斿晢鍜屾ā鍨嬪悕绉板垎绫伙紝鍙嫋鍔ㄥ埌宸︿晶步骤": "按供应商和模型名称分类，可拖动到左侧步骤",
        "娴?GPT": "测 GPT",
        "娴?GPT-Pro": "测 GPT-Pro",
        "娴?DeepSeek 润色": "测 DeepSeek 润色",
        "娴?gpt-image-2": "测 gpt-image-2",
        "娴?MiniMax": "测 MiniMax",
        "娣诲姞大模型连接/h3>": "添加大模型连接",
        "濉啓连接鍙傛暟鍜屾ā鍨嬪悕锛屼繚瀛樺悗会姞鍏ョ浉搴旀ā鍨嬬被鍒綔涓哄閫夋柟妗堛€?/p>": "填写连接参数和模型名，保存后会加入对应模型类别作为备选方案。",
        "澶囩敤文本": "备用文本",
        "模型名/label>": "模型名",
        "Key锛堝彲閫夛紝保存鍚庢竻绌轰笖涓嶅洖鏄撅級": "Key（可选，保存后清空且不回显）",
        "脳": "×",
        "杈撳叆优化建议": "输入优化建议",
        "选择项目后可写入虚拟用户测试建议。/p>": "选择项目后可写入虚拟用户测试建议。",
        "鎺ュ彛娴嬭瘯閫氳繃": "接口测试通过",
        "鎺ュ彛娴嬭瘯澶辫触锛岃鎯呰鍙充晶鏃ュ織": "接口测试失败，详情见右侧日志",
        "杩炴帴娴嬭瘯閫氳繃": "连接测试通过",
        "杩炴帴娴嬭瘯澶辫触锛岃鎯呰鍙充晶鏃ュ織": "连接测试失败，详情见右侧日志",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text.encode("utf-8")


def _automedia_html_v2() -> bytes:
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _assistant_workbench_html() -> bytes:
    return r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
  <title>自媒体小猪理工作台</title>
  <style>
    :root{font-family:Arial,"Microsoft YaHei",sans-serif;color:#17202a;background:#f6f8fb;--brand:#1769aa;--muted:#667085;--line:#d9e0e7;--soft:#eef4f8;--bad:#b3261e;--ok:#0f7b55;--warn:#a15c00}*{box-sizing:border-box}body{margin:0}.shell{display:grid;grid-template-columns:410px 1fr;min-height:100vh}.side{background:#fff;padding:14px;display:grid;grid-template-rows:minmax(0,1fr) auto;gap:10px;height:100vh;overflow:hidden}.mode-scroll{min-height:0;overflow:auto;padding-right:4px}.main{padding:14px;display:grid;grid-template-rows:270px minmax(0,1fr);gap:10px;height:100vh}h1{font-size:20px;margin:0 0 6px}h2{font-size:16px;margin:0 0 8px}h3{font-size:13px;margin:10px 0 7px}.hint{font-size:12px;color:var(--muted);line-height:1.42}.tabs{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin:12px 0}.tabs button{background:#e8eef5;color:#263238}.tabs button.active{background:var(--brand);color:#fff}.page{display:none}.page.active{display:block}.block{background:#fff;border:1px solid var(--line);border-radius:8px;padding:11px;margin-bottom:9px}.block.lead{border-color:#b8d0e7;background:#fbfdff}.grid2{display:grid;grid-template-columns:1fr 1fr;gap:8px}.grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}label{display:block;font-size:12px;margin:7px 0 4px;color:#435160}input,select{width:100%;padding:7px;border:1px solid #c8d0d8;border-radius:6px;background:#fff}.toggle{display:flex;gap:8px;align-items:center}.toggle input{width:auto}button{padding:8px 10px;border:0;border-radius:6px;background:var(--brand);color:#fff;cursor:pointer}button.secondary{background:#5f6368}button.danger{background:var(--bad)}button.ghost{background:#eef2f6;color:#263238}.row{display:flex;gap:7px;margin-top:10px;flex-wrap:wrap}.status{font-size:13px;color:var(--brand);margin:8px 0;word-break:break-all}.card{background:#fff;border:1px solid var(--line);border-radius:8px;padding:12px;min-height:0}details.block summary{cursor:pointer;font-weight:800;color:#334155}.task-card{display:flex;flex-direction:column;min-height:0;padding:0;overflow:hidden;background:#fbfcfe;border-color:#d6dee7;max-height:44vh}.task-card.compact{max-height:190px}.task-head{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:9px 11px;background:#f1f5f9;border-bottom:1px solid #dbe3ec}.task-head h2{margin:0;font-size:15px}.mode-pill{display:inline-flex;align-items:center;max-width:52%;min-height:24px;padding:3px 9px;border-radius:999px;background:#fff;color:#31546f;font-size:12px;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.task-body{padding:10px 11px;display:grid;grid-template-rows:auto auto minmax(0,1fr);min-height:0;gap:9px;flex:1}.task-body .hint{margin:0}.task-actions{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:7px;margin:0}.task-actions button{padding:7px 8px;white-space:nowrap}.jobs{display:grid;align-content:start;gap:8px;overflow:auto;min-height:0;padding-right:2px}.job{border:1px solid var(--line);border-radius:8px;padding:8px;background:#fff;display:grid;grid-template-columns:20px minmax(0,1fr);gap:8px;align-items:start}.job b{display:block;font-size:12px;line-height:1.35}.job span{display:block;font-size:11px;color:var(--muted);word-break:break-all}.job-actions{grid-column:2;display:flex;gap:6px;flex-wrap:wrap}.job-actions button{padding:5px 7px;font-size:12px}.workspace-card{display:flex;flex-direction:column;overflow:hidden}.workspace-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:8px}.workspace-head p{margin:0}.workspace-grid{display:grid;grid-template-columns:1.05fr .95fr;gap:10px;min-height:0}.panel{border:1px solid var(--line);border-radius:8px;padding:9px;background:#fff;min-height:0;overflow:auto}.panel.soft{background:#f8fafc}.kv{display:grid;grid-template-columns:90px 1fr;gap:6px;font-size:13px}.kv b{color:#334155}.flow,.readiness{display:grid;gap:6px}.flow div,.readiness div{background:#f8fafc;border-radius:6px;padding:7px;font-size:12px;line-height:1.35}.flow.compact div{display:none}.flow.compact div.bad,.flow.compact div.warn{display:block}.flow.compact.ok:before{content:"模型连接未发现阻塞项";display:block;background:#eef8f3;color:var(--ok);border-radius:6px;padding:7px;font-size:12px}.badge{display:inline-flex;align-items:center;border-radius:999px;padding:4px 9px;font-size:12px;font-weight:700;background:#eef2f6;color:#334155;white-space:nowrap}.badge.ok{background:#e7f6ef;color:var(--ok)}.badge.warn{background:#fff4df;color:var(--warn)}.badge.bad{background:#fdecec;color:var(--bad)}.back{display:inline-flex;text-decoration:none;background:#eef2f6;color:#334155;border-radius:6px;padding:7px 10px;font-weight:700;font-size:12px;margin-bottom:8px}pre{white-space:pre-wrap;background:#111827;color:#e5e7eb;border-radius:8px;padding:12px;margin:0;height:100%;min-height:240px;overflow:auto;font-size:12px;line-height:1.55}.log-card{display:flex;flex-direction:column}.log-tools{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:8px}.log-tools select{max-width:360px}@media(max-width:980px){.shell{grid-template-columns:1fr}.side,.main{height:auto;display:block}.grid2,.grid3,.workspace-grid{grid-template-columns:1fr}.task-card,.task-card.compact{margin-top:12px;min-height:280px;max-height:none}.task-body{display:flex;flex-direction:column}}
  </style>
</head>
<body><div class="shell"><aside class="side"><div class="mode-scroll"><a class="back" href="/">返回控制台首页</a><h1>自媒体小猪理工作台</h1><p class="hint">每个模式是一张独立控制台：只放本模式要配置的东西、剪辑交付、模型步骤、任务和日志。</p><div class="tabs"><button id="tabCulture" onclick="showMode('culture')">文史解读</button><button id="tabResearch" onclick="showMode('research')">每日速递</button><button id="tabScience" onclick="showMode('science')">科学经典</button><button id="tabLocal" onclick="showMode('local')">自优化</button></div>
<section id="pageCulture" class="page active"><div class="block lead"><h2>文史解读</h2><p class="hint">把书、史料或章节变成可讲清楚的短视频素材。先确认 PDF、输出目录和起跑阶段，再启动。</p><label>书籍 PDF</label><input id="culture_book" placeholder="D:/知识/xxx.pdf"><label>输出目录</label><input id="culture_out_dir" placeholder="D:/输出/文史素材"><label>继续目录</label><input id="culture_continue_folder" placeholder="可留空"><label>开始阶段</label><select id="culture_stage"><option>outline</option><option>split_pdf</option><option>episode_prompt</option><option>script</option><option>polish</option><option>images</option><option>postprocess</option><option>split_assets</option></select><label>测试 B 图数</label><input id="culture_test_b" value="0"><div class="row"><button onclick="startCulture(false)">开始文史生成</button><button class="secondary" onclick="startCulture(true)">快速测试：1 张 B 图</button><button class="secondary" onclick="openOutputFolder('culture')">打开作品文件夹</button></div></div><div class="block"><h3>本模式剪辑交付</h3><label>图片目录</label><input id="culture_clip_image_dir"><label>LRC / 音频目录</label><input id="culture_clip_lrc_dir"><label>输出目录</label><input id="culture_clip_output_dir"><label>BGM 文件/目录</label><input id="culture_clip_bgm"><div class="row"><button class="secondary" onclick="startModeClip('culture')">启动文史剪辑</button><button class="secondary" onclick="startBgm('culture')">生成文史 BGM</button></div></div></section>
<section id="pageResearch" class="page"><div class="block lead"><h2>每日研究速递</h2><p class="hint">面向中国读者的论文快报。默认从 PubMed/清单取原文信息，文案失败就停下排障，不用本地模板假装完成。</p><label>输出目录</label><input id="research_out_dir" placeholder="可留空，默认科研速递栏目下新建分集文件夹"><div class="grid3"><div><label>检索天数</label><input id="research_days" value="14"></div><div><label>每期文章数</label><input id="research_max_articles" value="5"></div><div><label>每天期数</label><select id="research_issue_count"><option value="1">1 期</option><option value="2">2 期</option><option value="3">3 期</option></select></div></div><label>期刊列表</label><input id="research_journals" placeholder="Nature, Science, Neuron..."><label>已有文献清单 / 续做目录</label><input id="research_article_list"><label class="toggle"><input id="research_skip_medical_related" type="checkbox"> 微信避险：跳过医学、疾病、临床和生物医学外推相关论文</label><p class="hint" id="digest_email_hint"></p><div class="row"><button onclick="startResearch('digest')">开始创作</button><button class="secondary" onclick="startResearchQuickTest()">快速测试：1 张 B 图</button><button onclick="startResearch('article_list')">补文献清单</button><button onclick="startResearch('continue_list')">清单续做</button><button onclick="startResearch('resume')">续做档期</button><button class="secondary" onclick="openOutputFolder('research')">打开作品文件夹</button></div></div><div class="block"><h3>本模式剪辑交付</h3><label>图片目录</label><input id="research_clip_image_dir" placeholder="本期 cards 目录"><label>LRC / 音频目录</label><input id="research_clip_lrc_dir"><label>输出目录</label><input id="research_clip_output_dir"><label>BGM 文件/目录</label><input id="research_clip_bgm"><div class="row"><button class="secondary" onclick="startModeClip('research')">启动速递剪辑</button><button class="secondary" onclick="startBgm('research')">生成速递 BGM</button></div></div></section>
<section id="pageScience" class="page"><div class="block lead"><h2>科学经典</h2><p class="hint">把经典神经科学章节拆成口播、字幕和科学插图。B 图只做机制/行为链示意，不做 PPT 式结论卡。</p><label>书籍 PDF</label><input id="science_pdf_path"><label>作品文件夹</label><input id="science_out_dir"><div class="row"><button onclick="startScience(false)">开始创作</button><button class="secondary" onclick="startScience(true)">快速测试：1 张 B 图</button><button class="secondary" onclick="openOutputFolder('science')">打开作品文件夹</button></div></div><div class="block"><h3>本模式剪辑交付</h3><label>图片目录</label><input id="science_clip_image_dir"><label>LRC / 音频目录</label><input id="science_clip_lrc_dir"><label>输出目录</label><input id="science_clip_output_dir"><label>BGM 文件/目录</label><input id="science_clip_bgm"><div class="row"><button class="secondary" onclick="startModeClip('science')">启动科学经典剪辑</button><button class="secondary" onclick="startBgm('science')">生成科学经典 BGM</button></div></div></section>
<section id="pageLocal" class="page"><div class="block lead"><h2>自优化</h2><p class="hint">用于本机工作流维护、调试和持续改进。它独立记录任务和日志，不抢文史、速递、科学经典的生产现场。</p><div class="row"><button onclick="startLocalTool('self_optimizer_once')">跑一次自优化</button><button class="secondary" onclick="startLocalTool('self_optimizer_daemon')">启动持续自优化</button><button class="secondary" onclick="location.href='/model/'">大模型连接库</button><button class="secondary" onclick="location.href='/optimizer/'">自优化器控制台</button><button class="secondary" onclick="location.href='/audience/'">虚拟用户测试</button></div></div><div class="block"><h3>自优化剪辑试验</h3><label>图片目录</label><input id="local_clip_image_dir"><label>LRC / 音频目录</label><input id="local_clip_lrc_dir"><label>输出目录</label><input id="local_clip_output_dir"><label>BGM 文件/目录</label><input id="local_clip_bgm"><div class="row"><button class="secondary" onclick="startModeClip('local')">启动自优化剪辑</button><button class="secondary" onclick="startBgm('local')">生成自优化 BGM</button></div></div></section>
<details class="block"><summary>当前模式邮箱</summary><label class="toggle"><input id="email_enabled" type="checkbox" onchange="saveCurrentEmailProfile()"> 完成后发送邮件</label><label>收件邮箱</label><input id="email_recipient" oninput="saveCurrentEmailProfile()" placeholder="多个邮箱用逗号分隔"><p class="hint" id="email_profile_status"></p><div class="grid2"><div><label>SMTP 服务器</label><input id="smtp_host"></div><div><label>SMTP 端口</label><input id="smtp_port"></div><div><label>SMTP 账号</label><input id="smtp_user"></div><div><label>发件人</label><input id="smtp_sender"></div></div><label>SMTP 密码 / 授权码</label><input id="smtp_password" type="password" autocomplete="off" placeholder="粘贴新密码或授权码；保存后清空"><div class="row"><button class="secondary" onclick="testEmail()">测试 SMTP</button><button onclick="saveSettings()">保存</button></div></details><details class="block"><summary>模型与声音</summary><p class="hint">模型只从总控台读取，不显示 key。</p><div class="row"><button class="secondary" onclick="refreshModelConfig()">刷新模型</button><button class="ghost" onclick="location.href='/model/'">打开总控台</button></div><div class="flow compact" id="left_model_flow"></div><div class="grid2"><div><label>Voice ID</label><input id="minimax_voice_id"></div><div><label>BGM Prompt</label><input id="minimax_bgm_prompt"></div></div><input id="minimax_base_url" type="hidden"><input id="minimax_tts_model" type="hidden"><input id="minimax_bgm_model" type="hidden"><input id="minimax_api_key" type="password" autocomplete="off" style="display:none"></details><div class="row"><button class="secondary" onclick="saveSettings()">保存当前设置</button><button class="danger" onclick="stopJob()">停止当前任务</button></div><div class="status" id="status">待命</div><div class="hint" id="cmd"></div></div><section class="card task-card compact" id="task_card"><div class="task-head"><h2>运行任务</h2><span class="mode-pill" id="task_mode_label"></span></div><div class="task-body"><p class="hint" id="task_hint"></p><div class="task-actions"><button class="secondary" onclick="refreshAllJobs()">刷新</button><button class="danger" onclick="stopJob()">停止</button><button class="ghost" onclick="selectAllJobs(true)">全选</button><button class="danger" onclick="deleteSelectedJobs()">删除</button><button onclick="deployReleaseWhenIdle()">发版</button><button class="ghost" onclick="openProductionCard()">上线区</button></div><div class="jobs" id="jobs_list">暂无运行任务</div></div></section></aside>
<main class="main"><section class="card workspace-card"><div class="workspace-head"><div><h2 id="workspace_title">文史解读</h2><p class="hint" id="workspace_goal">当前模式状态</p></div><span class="badge" id="workspace_badge">待检查</span></div><div class="workspace-grid"><div class="panel"><h3>开工检查</h3><div class="readiness" id="readiness_box"></div><h3>下一步</h3><div class="readiness" id="next_action_box"></div></div><div class="panel soft"><h3>模型检查</h3><div class="flow compact" id="model_flow"></div><div class="row"><button class="secondary" onclick="refreshModelConfig()">刷新模型</button><button class="ghost" onclick="location.href='/model/'">模型库</button></div><h3>当前配置</h3><div class="kv" id="workspace_kv"></div></div></div></section><section class="card log-card"><div class="log-tools"><select id="log_job_select" onchange="selectLogJob(this.value)"><option value="">当前模式日志</option></select><button class="secondary" onclick="scrollLogBottom()">跳到底部</button><button class="secondary" onclick="copyLog()">复制日志</button><button class="secondary" onclick="clearLog()">清空当前日志</button></div><pre id="log">暂无日志</pre></section></main></div>
<script>
const modes=["culture","research","science","local"],modeLabels={culture:"文史解读",research:"每日研究速递",science:"科学经典",local:"自优化"},emailKeyByMode={culture:"culture",research:"daily_research_digest",science:"science",local:"local"},emailProfileLabels={culture:"文史解读",daily_research_digest:"每日研究速递",science:"科学经典",local:"自优化"};
const jobsStorageKey="quanlan_automedia_jobs_v4";let jobsById=JSON.parse(localStorage.getItem(jobsStorageKey)||"{}"),selectedJobId="",currentMode="culture",uiLogs={culture:[],research:[],science:[],local:[]},pollHandles={},modelSnapshot={},connectionLibrary={},activeEmailProfileKey="culture",emailProfiles={culture:{email_enabled:false,email_recipient:""},daily_research_digest:{email_enabled:false,email_recipient:""},science:{email_enabled:false,email_recipient:""},local:{email_enabled:false,email_recipient:""}};
function byId(id){return document.getElementById(id)}function fieldValue(id){const el=byId(id);return el?String(el.value||""):""}function setField(id,v){const el=byId(id);if(el)el.value=v||""}function setStatus(s){byId("status").textContent=s}function cap(s){return s[0].toUpperCase()+s.slice(1)}function htmlEsc(s){return String(s||"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]))}function jsStr(s){return String(s||"").replace(/\\/g,"\\\\").replace(/'/g,"\\'")}
function appendLog(msg,kind){const k=kind||currentMode;if(!uiLogs[k])uiLogs[k]=[];uiLogs[k].push("["+new Date().toLocaleTimeString()+"] "+msg);uiLogs[k]=uiLogs[k].slice(-300);renderLog()}function renderLog(lines){byId("log").textContent=[(uiLogs[currentMode]||[]).join("\n"),(lines||[]).join("")].filter(Boolean).join("\n")||"暂无日志";byId("log").scrollTop=byId("log").scrollHeight}function scrollLogBottom(){byId("log").scrollTop=byId("log").scrollHeight}async function copyLog(){await navigator.clipboard.writeText(byId("log").textContent||"")}function clearLog(){uiLogs[currentMode]=[];renderLog()}
function normalizeEmailProfiles(raw){const out={};for(const key of Object.keys(emailProfileLabels)){const src=raw&&raw[key]||{};out[key]={email_enabled:!!(src.email_enabled||src.enabled),email_recipient:String(src.email_recipient||src.recipient||"").trim()}}return out}function saveCurrentEmailProfile(){const key=activeEmailProfileKey;emailProfiles[key]={email_enabled:!!byId("email_enabled").checked,email_recipient:fieldValue("email_recipient").trim()};updateEmailStatus()}function loadModeEmail(){activeEmailProfileKey=emailKeyByMode[currentMode]||"culture";const p=emailProfiles[activeEmailProfileKey]||{};byId("email_enabled").checked=!!p.email_enabled;setField("email_recipient",p.email_recipient||"");updateEmailStatus()}function updateEmailStatus(){const p=emailProfiles[activeEmailProfileKey]||{};byId("email_profile_status").textContent=modeLabels[currentMode]+"：邮件"+(p.email_enabled?"开启":"关闭")+"；收件人"+(p.email_recipient?"已填写":"未填写")+"。";const d=emailProfiles.daily_research_digest||{};byId("digest_email_hint").textContent="每日研究速递邮件："+(d.email_enabled?(d.email_recipient?"已开启，收件人 "+d.email_recipient:"已开启但未填收件人"):"未开启")+"。";renderWorkspace()}
function collect(){saveCurrentEmailProfile();const ids=["culture_book","culture_out_dir","culture_continue_folder","research_out_dir","research_days","research_max_articles","research_issue_count","research_journals","research_article_list","smtp_password","smtp_host","smtp_port","smtp_user","smtp_sender","science_pdf_path","science_out_dir","minimax_base_url","minimax_api_key","minimax_tts_model","minimax_bgm_model","minimax_voice_id","minimax_bgm_prompt"];for(const m of modes){ids.push(m+"_clip_image_dir",m+"_clip_lrc_dir",m+"_clip_output_dir",m+"_clip_bgm")}const p={};for(const id of ids){if(byId(id))p[id]=fieldValue(id)}p.email_profiles=emailProfiles;const d=emailProfiles.daily_research_digest||{};p.email_enabled=!!d.email_enabled;p.email_recipient=d.email_recipient||"";p.research_skip_medical_related=!!byId("research_skip_medical_related").checked;return p}
async function loadSettings(){appendLog("正在读取当前设置");const r=await fetch("/api/settings"),data=await r.json();modelSnapshot=data.models||{};connectionLibrary=data.model_connection_library||{};const merged={...(data.models||{}),...(data.settings||{})};emailProfiles=normalizeEmailProfiles(merged.email_profiles||{});if(!emailProfiles.daily_research_digest.email_recipient&&merged.email_recipient)emailProfiles.daily_research_digest={email_enabled:String(merged.email_enabled).toLowerCase()==="true",email_recipient:String(merged.email_recipient||"").trim()};for(const [k,v] of Object.entries(merged)){if(k==="email_profiles"||k==="email_enabled"||k==="email_recipient")continue;if(k==="research_skip_medical_related")byId(k).checked=String(v).toLowerCase()==="true";else setField(k,v)}loadModeEmail();appendLog("当前设置已读取")}async function saveSettings(){appendLog("正在保存当前设置");const r=await fetch("/api/settings",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(collect())}),data=await r.json();setField("smtp_password","");setField("minimax_api_key","");setStatus(data.ok?"设置已保存":"保存失败");appendLog(data.ok?"设置已保存":"保存失败");return data}
function baseLabel(base){const map={"culture:test_b":"文史解读 / 快速测试 1 张 B 图","research:test_b":"每日研究速递 / 快速测试 1 张 B 图","research:digest":"每日研究速递 / 开始创作","research:article_list":"每日研究速递 / 补文献清单","research:continue_list":"每日研究速递 / 清单续做","research:resume":"每日研究速递 / 续做档期","science:run":"科学经典 / 开始创作","science:test_b":"科学经典 / 快速测试 1 张 B 图","local:self_optimizer_once":"自优化 / 跑一次自优化","local:self_optimizer_daemon":"自优化 / 持续自优化","local:release_deploy":"自优化 / 升级发布版"};if((base||"").endsWith(":clip"))return modeLabels[(base||"").split(":")[0]]+" / 剪辑";if((base||"").endsWith(":bgm"))return modeLabels[(base||"").split(":")[0]]+" / BGM";return map[base]||base||"任务"}function kindForBase(base){const k=String(base||"").split(":")[0];return modes.includes(k)?k:"culture"}
async function start(payload,base){const kind=kindForBase(base);showMode(kind,false);appendLog("准备启动："+baseLabel(base),kind);const saved=await saveSettings();if(saved&&!saved.ok)return;const r=await fetch("/api/start",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)}),data=await r.json();if(!r.ok||data.ok===false){appendLog("启动失败："+(data.error||"unknown"),kind);return}rememberJob(data.job_id,base,payload,data);setStatus("任务已创建："+baseLabel(base));poll(data.job_id)}
function clipPayload(mode){const p=collect();return {...p,mode:"auto_clip",auto_clip_image_dir:p[mode+"_clip_image_dir"]||"",auto_clip_lrc_dir:p[mode+"_clip_lrc_dir"]||"",auto_clip_output_dir:p[mode+"_clip_output_dir"]||"",auto_clip_bgm:p[mode+"_clip_bgm"]||""}}function startModeClip(mode){start(clipPayload(mode),mode+":clip")}function startBgm(mode){const p=clipPayload(mode);p.mode="bgm";start(p,mode+":bgm")}function startCulture(test){const stage=fieldValue("culture_stage")||"outline";start({...collect(),mode:"culture",stage,test_b_image_limit:test?1:Number(fieldValue("culture_test_b")||0)},test?"culture:test_b":"culture:"+stage)}function startResearch(action){const p=collect(),d=emailProfiles.daily_research_digest||{};if(d.email_enabled&&!d.email_recipient){setStatus("请先填写每日研究速递收件邮箱，或关闭该模块邮件发送");showMode("research");return}start({...p,mode:"research",action},"research:"+action)}function startResearchQuickTest(){const p=collect(),d=emailProfiles.daily_research_digest||{};if(d.email_enabled&&!d.email_recipient){setStatus("请先填写每日研究速递收件邮箱，或关闭该模块邮件发送");showMode("research");return}appendLog("快速测试：每日研究速递只取 1 篇、1 期，并只调用图片模型生成 1 张机制/B图。","research");start({...p,mode:"research",action:"digest",research_max_articles:"1",research_issue_count:"1",research_test_b_image_limit:"1"},"research:test_b")}function startScience(test){start({...collect(),mode:"tool",action:test?"science_test_b":"science"},"science:"+(test?"test_b":"run"))}function startLocalTool(action){start({...collect(),mode:"tool",action},"local:"+action)}
function rememberJob(id,base,payload,data){jobsById[id]={id,label:baseLabel(base),base,kind:kindForBase(base),payload,status:"starting",started_at:Date.now(),cmd:data.cmd||[]};selectedJobId=id;saveJobs();renderJobs()}function saveJobs(){localStorage.setItem(jobsStorageKey,JSON.stringify(jobsById))}function isLive(s){return["running","starting","stopping"].includes(String(s||""))}async function poll(id){const r=await fetch("/api/job?id="+encodeURIComponent(id)),data=await r.json(),job=jobsById[id]||{};job.status=data.status;job.exit_code=data.exit_code;jobsById[id]=job;saveJobs();renderJobs();if(job.kind)currentMode=job.kind;renderLog(data.lines||[]);if(isLive(data.status))pollHandles[id]=setTimeout(()=>poll(id),1200)}async function viewJob(id){selectedJobId=id;const job=jobsById[id];if(job)showMode(job.kind||"culture",false);poll(id)}function visibleJobs(){return Object.values(jobsById).filter(j=>(j.kind||"culture")===currentMode).sort((a,b)=>(b.started_at||0)-(a.started_at||0))}function currentStopJobId(){if(selectedJobId&&jobsById[selectedJobId]&&(jobsById[selectedJobId].kind||"culture")===currentMode&&isLive(jobsById[selectedJobId].status))return selectedJobId;const live=visibleJobs().filter(j=>isLive(j.status));return live.length?live[0].id:""}async function stopJob(id){const target=id||currentStopJobId();if(!target){appendLog("当前模式没有正在运行的任务可停止",currentMode);setStatus("没有正在运行的任务");return}selectedJobId=target;const job=jobsById[target]||{};appendLog("正在停止任务："+(job.label||target),job.kind||currentMode);const r=await fetch("/api/stop?id="+encodeURIComponent(target),{method:"POST"}),data=await r.json().catch(()=>({ok:false,message:"停止接口没有返回 JSON"}));if(!data.ok){appendLog("停止失败："+(data.message||data.error||"unknown"),job.kind||currentMode);setStatus("停止失败");return}if(jobsById[target]){jobsById[target].status=data.status||"stopping";jobsById[target].updated_at=Date.now()}saveJobs();renderJobs();setStatus("停止请求已发送："+(job.label||target));poll(target)}async function deleteJob(id,skipConfirm){if(!skipConfirm&&!confirm("确认删除这条任务记录？"))return;await fetch("/api/job_delete?id="+encodeURIComponent(id),{method:"POST"});delete jobsById[id];if(selectedJobId===id)selectedJobId="";saveJobs();renderJobs()}function selectedJobIds(){return Array.from(document.querySelectorAll("[data-job-check]:checked")).map(x=>x.getAttribute("data-job-check"))}function selectAllJobs(flag){document.querySelectorAll("[data-job-check]").forEach(x=>x.checked=!!flag)}async function deleteSelectedJobs(){const ids=selectedJobIds();if(!ids.length)return;if(!confirm("确认批量删除 "+ids.length+" 条任务记录？"))return;for(const id of ids)await deleteJob(id,true)}async function refreshAllJobs(){const r=await fetch("/api/jobs"),data=await r.json();for(const j of data.jobs||[]){const id=j.id||j.job_id;jobsById[id]={...(jobsById[id]||{}),...j,id,label:j.label||baseLabel(j.base_key||j.mode),kind:kindForBase(j.base_key||j.mode)}}saveJobs();renderJobs();return data.jobs||[]}
function renderJobs(){const items=visibleJobs(),box=byId("jobs_list"),card=byId("task_card");byId("task_mode_label").textContent=modeLabels[currentMode];if(card)card.classList.toggle("compact",!items.length);const stopId=currentStopJobId();byId("task_hint").textContent=stopId?("可停止："+((jobsById[stopId]&&jobsById[stopId].label)||stopId)):"无运行任务";if(!items.length){box.textContent="";refreshLogSelect();return}box.innerHTML=items.map(j=>{const live=isLive(j.status),id=htmlEsc(j.id),safeId=jsStr(j.id);return '<div class="job"><input type="checkbox" data-job-check="'+id+'"><div onclick="viewJob(\''+safeId+'\')"><b>'+htmlEsc(j.label)+' | '+htmlEsc(j.status||"")+'</b><span>'+id+'</span></div><div class="job-actions"><button class="secondary" onclick="viewJob(\''+safeId+'\')">查看</button>'+(live?'<button class="danger" onclick="stopJob(\''+safeId+'\')">停止</button>':'')+'<button class="danger" onclick="deleteJob(\''+safeId+'\')">删除</button></div></div>'}).join("");refreshLogSelect()}function refreshLogSelect(){byId("log_job_select").innerHTML='<option value="">当前模式日志</option>'+visibleJobs().map(j=>'<option value="'+htmlEsc(j.id)+'">'+htmlEsc(j.label)+' ｜ '+htmlEsc(j.status||"")+'</option>').join("")}async function selectLogJob(id){if(id)await viewJob(id)}async function testEmail(){await saveSettings();const r=await fetch("/api/test_email",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(collect())}),data=await r.json();appendLog((data.result&&data.result.ok?"SMTP 测试通过：":"SMTP 测试失败：")+((data.result&&data.result.message)||""),currentMode)}async function openOutputFolder(kind){const p={culture:fieldValue("culture_out_dir"),research:fieldValue("research_out_dir")||"D:/Quanlan/全澜脑科学视频号/科研速递",science:fieldValue("science_out_dir"),local:fieldValue("local_clip_output_dir")||fieldValue("local_clip_image_dir")}[kind]||"";await fetch("/api/open_output_folder",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({path:p})})}
function modelText(keys){for(const k of keys){if(modelSnapshot[k])return modelSnapshot[k]}return "未从总控台读到"}
function connStateText(c){if(!c||!c.model)return "未配置";if(c.last_test_ok===true)return "检测通过";if(c.last_test_ok===false&&c.last_tested_at)return "检测失败";return c.key_configured?"已配置":"缺 key"}
function connTextForStep(step){const lib=connectionLibrary||{},steps=lib.steps||{},business=(modelSnapshot.business_steps||{}),selected=(business[step]&&business[step].selected)||{};if(selected.model){return ((business[step]&&business[step].label)||(steps[step]&&steps[step].label)||step)+"："+(selected.provider||"")+" / "+selected.model+" @ "+(selected.base_url||"未填 URL")+" ｜ "+connStateText(selected)}const active=lib.active_connections||{},connections=lib.connections||[],routeId=active[step]||active[(steps[step]||{}).role]||"",c=connections.find(x=>x.id===routeId)||{};if(c.model){return (steps[step]&&steps[step].label?steps[step].label:step)+"："+(c.provider||"")+" / "+c.model+" @ "+(c.base_url||"未填 URL")+" ｜ "+connStateText(c)}const fallback={script_text:modelText(["text_engine","culture_text_model"]),research_text:modelText(["text_engine","research_text_model"]),polish_text:modelText(["polish_engine","culture_polish_model","research_polish_model"]),image_generation:modelText(["image_engine","culture_image_model","research_image_model"]),voice_bgm:modelText(["minimax_tts_model"])}[step]||"未从总控台读到";return ((steps[step]||{}).label||step)+"："+fallback}
function modeSteps(){return {culture:[["script_text","拆书/脚本"],["polish_text","中文润色"],["image_generation","封面/B 图"],["voice_bgm","配音/BGM/剪辑"]],research:[["research_text","文献解读/脚本"],["polish_text","中文润色"],["image_generation","卡片/图片"],["voice_bgm","配音/BGM/剪辑"]],science:[["script_text","经典内容生成"],["polish_text","中文润色"],["image_generation","B 图/公共元素"],["voice_bgm","配音/BGM/剪辑"]],local:[["script_text","自优化文本任务"],["polish_text","自优化润色任务"],["image_generation","试验图片任务"],["voice_bgm","试验配音/BGM"]]}[currentMode]||[]}
function modelFlow(){return modeSteps().map(x=>x[1]+"｜"+connTextForStep(x[0]))}
function renderModelFlows(){const rows=modelFlow().map(x=>{const cls=x.includes("检测失败")||x.includes("缺 key")||x.includes("未填")||x.includes("未从总控台读到")?"bad":"ok";return '<div class="'+cls+'">'+htmlEsc(x)+'</div>'}).join("");for(const id of ["model_flow","left_model_flow"]){const el=byId(id);if(el){el.innerHTML=rows;el.classList.toggle("ok",!rows.includes('bad'))}}}
async function refreshModelConfig(){appendLog("正在从总控台刷新模型配置");const r=await fetch("/api/settings"),data=await r.json();modelSnapshot=data.models||{};connectionLibrary=data.model_connection_library||{};renderModelFlows();appendLog("模型配置已刷新：按总控台最新连接展示")}
function openProductionCard(){window.location.assign("/#production-assistant")}
async function deployReleaseWhenIdle(){const jobs=await refreshAllJobs();const running=jobs.filter(j=>isLive(j.status));if(running.length){appendLog("还有 "+running.length+" 个任务没结束，先停止或等待结束后再升级发布版","local");setStatus("仍有任务运行，不能升级发布版");showMode("local");return}if(!confirm("确认把当前开发版打包并升级发布版？升级完成后，总控台上线区的自媒体小猪理（发布版）卡片会打开发布版入口。"))return;showMode("local");appendLog("正在升级发布版：先打包，再应用到发布目录。","local");const r=await fetch("/api/audience",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({project:"assistant",mode:"release_deploy"})});const data=await r.json();if(!data.ok){appendLog("升级发布版启动失败："+(data.error||"unknown"),"local");setStatus("升级发布版启动失败");return}const id=data.job_id;jobsById[id]={id,label:baseLabel("local:release_deploy"),base:"local:release_deploy",kind:"local",status:"starting",started_at:Date.now(),cmd:data.cmd||[]};selectedJobId=id;saveJobs();renderJobs();setStatus("升级发布版任务已启动");poll(id)}
function kvRows(rows){return rows.map(x=>'<b>'+htmlEsc(x[0])+'</b><div>'+htmlEsc(String(x[1]||"未设置"))+'</div>').join("")}
function mark(ok,text,badText){return {ok:!!ok,text:ok?text:(badText||text)}}
function modeGoal(){return {culture:"配置素材和起跑阶段",research:"配置论文来源和出片数量",science:"配置经典 PDF 和输出目录",local:"自优化与发布维护"}[currentMode]||""}
function modeNextAction(checks){const missing=checks.filter(x=>!x.ok).map(x=>x.text);if(missing.length)return ["先补："+missing.slice(0,2).join("、")];const live=visibleJobs().filter(j=>isLive(j.status));if(live.length)return ["任务运行中，看日志；卡住就停止。"];return {culture:["可先快速测试 1 张 B 图。"],research:["可先快速测试 1 张 B 图。"],science:["可先快速测试 1 张 B 图。"],local:["可跑一次自优化；无任务时可发版。"]}[currentMode]||["可以启动。"]}
function readinessChecks(ep){const clipReady=!!(fieldValue(currentMode+"_clip_image_dir")&&fieldValue(currentMode+"_clip_lrc_dir")&&fieldValue(currentMode+"_clip_output_dir"));return {culture:[mark(fieldValue("culture_book"),"书籍 PDF 已填写","书籍 PDF 未填写"),mark(fieldValue("culture_out_dir"),"输出目录已填写","输出目录未填写"),mark(fieldValue("culture_stage"),"起跑阶段已选择","起跑阶段未选择"),mark(!ep.email_enabled||ep.email_recipient,"邮件配置可用","邮件开启但收件人未填")],research:[mark(fieldValue("research_out_dir")||true,"输出目录会按默认栏目建分集文件夹"),mark(fieldValue("research_article_list")||Number(fieldValue("research_days")||0)>0,"文献来源可用","请填写文献清单或检索天数"),mark(Number(fieldValue("research_max_articles")||0)>0,"每期文章数已设置","每期文章数需要大于 0"),mark(!ep.email_enabled||ep.email_recipient,"邮件配置可用","邮件开启但收件人未填")],science:[mark(fieldValue("science_pdf_path"),"书籍 PDF 已填写","书籍 PDF 未填写"),mark(fieldValue("science_out_dir"),"作品文件夹已填写","作品文件夹未填写"),mark(!ep.email_enabled||ep.email_recipient,"邮件配置可用","邮件开启但收件人未填")],local:[mark(true,"自优化入口可用"),mark(!ep.email_enabled||ep.email_recipient,"邮件配置可用","邮件开启但收件人未填"),mark(clipReady||true,"剪辑试验可按需填写")]}[currentMode]||[]}
function renderBox(id,items){const el=byId(id);if(el)el.innerHTML=(items||[]).map(x=>'<div>'+htmlEsc(typeof x==="string"?x:x.text)+'</div>').join("")}
function renderReadiness(checks){byId("readiness_box").innerHTML=checks.map(x=>'<div><span class="badge '+(x.ok?"ok":"bad")+'">'+(x.ok?"就绪":"待补")+'</span> '+htmlEsc(x.text)+'</div>').join("")}
function renderWorkspace(){const ep=emailProfiles[emailKeyByMode[currentMode]]||{},clip=[fieldValue(currentMode+"_clip_image_dir"),fieldValue(currentMode+"_clip_output_dir")].filter(Boolean).join(" -> ")||"未设置",rows={culture:[["书籍",fieldValue("culture_book")],["输出",fieldValue("culture_out_dir")],["阶段",fieldValue("culture_stage")],["剪辑",clip],["邮箱",ep.email_enabled?(ep.email_recipient||"开启但未填"):"关闭"]],research:[["输出",fieldValue("research_out_dir")||"默认"],["清单",fieldValue("research_article_list")],["期数",fieldValue("research_issue_count")],["文章",fieldValue("research_max_articles")],["剪辑",clip],["邮箱",ep.email_enabled?(ep.email_recipient||"开启但未填"):"关闭"]],science:[["PDF",fieldValue("science_pdf_path")],["输出",fieldValue("science_out_dir")],["剪辑",clip],["邮箱",ep.email_enabled?(ep.email_recipient||"开启但未填"):"关闭"]],local:[["用途","自优化 / 发版 / 试验"],["剪辑",clip],["邮箱",ep.email_enabled?(ep.email_recipient||"开启但未填"):"关闭"]]}[currentMode];const checks=readinessChecks(ep),ok=checks.every(x=>x.ok);byId("workspace_title").textContent=modeLabels[currentMode];byId("workspace_goal").textContent=modeGoal();byId("workspace_badge").className="badge "+(ok?"ok":"warn");byId("workspace_badge").textContent=ok?"可启动":"待补";byId("workspace_kv").innerHTML=kvRows(rows);renderReadiness(checks);renderBox("next_action_box",modeNextAction(checks));renderModelFlows()}
function showMode(mode,loadEmail=true){currentMode=modes.includes(mode)?mode:"culture";for(const m of modes){byId("page"+cap(m)).classList.toggle("active",m===currentMode);byId("tab"+cap(m)).classList.toggle("active",m===currentMode)}if(loadEmail)loadModeEmail();renderWorkspace();renderJobs();renderLog()}document.addEventListener("input",()=>renderWorkspace());loadSettings().then(()=>{showMode("culture");refreshAllJobs()});
</script></body></html>""".encode("utf-8")

def _json(handler: BaseHTTPRequestHandler, data: Any, status: int = 200) -> None:
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _daily_research_progress_path(article_list_path: Path) -> Path:
    return article_list_path.with_name(article_list_path.stem + "_缁仛杩涘害.json")


def _candidate_article_list_files(root: Path) -> list[Path]:
    names = ("00_鏂囩尞淇℃伅.json", "00_鍊欓€夋枃鐚竻鍗?json", "article_list.json", "articles.json")
    candidates: list[Path] = []
    if root.is_dir():
        for name in names:
            path = root / name
            if path.exists():
                candidates.append(path)
        try:
            candidates.extend(p for p in root.glob("鏂囩尞娓呭崟*.json") if "缁仛杩涘害" not in p.name)
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
        if path.exists() and path.is_file() and "缁仛杩涘害" not in path.name:
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


def _http_probe(url: str, timeout: float = 2.0) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        req = urllib.request.Request(url, method="GET", headers={"Cache-Control": "no-store"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(2048)
            latency_ms = round((time.perf_counter() - started) * 1000)
            return {
                "ok": 200 <= resp.status < 500,
                "status_code": resp.status,
                "latency_ms": latency_ms,
                "message": "可达",
                "sample": body.decode("utf-8", errors="replace")[:160],
            }
    except urllib.error.HTTPError as exc:
        latency_ms = round((time.perf_counter() - started) * 1000)
        return {"ok": False, "status_code": exc.code, "latency_ms": latency_ms, "message": f"HTTP {exc.code}"}
    except Exception as exc:
        latency_ms = round((time.perf_counter() - started) * 1000)
        return {"ok": False, "status_code": 0, "latency_ms": latency_ms, "message": _safe_error(exc)}


def _is_local_url(url: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return False
    host = (parsed.hostname or "").lower()
    return host in {"127.0.0.1", "localhost", "::1", ""}


def _remote_control_env_key(app_id: str, action: str) -> str:
    cleaned_app = re.sub(r"[^A-Za-z0-9]+", "_", app_id or "").upper().strip("_")
    cleaned_action = re.sub(r"[^A-Za-z0-9]+", "_", action or "").upper().strip("_")
    return f"QUANLAN_PROD_{cleaned_app}_{cleaned_action}_CMD"


def _production_control_status(app_id: str, production_url: str) -> dict[str, Any]:
    if app_id == "xiaozhuli":
        return {
            "production_control_kind": "http-api",
            "production_control_configured": True,
            "production_control_note": "线上小猪理服务可由总控台直接启停。",
        }
    if _is_local_url(production_url):
        return {
            "production_control_kind": "local",
            "production_control_configured": True,
            "production_control_note": "本机正式服务，可由总控台直接启停。",
        }
    configured = any(os.environ.get(_remote_control_env_key(app_id, action), "").strip() for action in ("START", "STOP", "RESTART"))
    return {
        "production_control_kind": "remote",
        "production_control_configured": configured,
        "production_control_note": "远程正式服务启停已配置。" if configured else "远程正式服务还没有配置启停命令；只能检测状态和打开入口。",
    }


def _run_xiaozhuli_production_control(action: str) -> None:
    mapped_action = "restart" if action in {"restart", "sync"} else action
    if mapped_action not in {"start", "stop", "restart"}:
        raise ValueError(f"不支持的线上小猪理操作：{action}")
    api_url = XIAOZHULI_PRODUCTION_URL.rstrip("/") + "/api/service"
    data = json.dumps({"name": "all", "action": mapped_action}).encode("utf-8")
    req = urllib.request.Request(
        api_url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=PRODUCTION_CONTROL_TIMEOUT) as resp:
            if resp.status >= 400:
                body = resp.read().decode("utf-8", errors="replace")
                raise RuntimeError(f"线上小猪理控制失败 {resp.status}: {body[:300]}")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"线上小猪理控制失败 {exc.code}: {body[:300]}") from exc



def _assistant_release_pids() -> list[int]:
    pids = set(_pids_on_port(ASSISTANT_RELEASE_PORT))
    if os.name == "nt":
        try:
            result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "Get-CimInstance Win32_Process -Filter \"name='python.exe'\" | "
                    "Where-Object { $_.CommandLine -match 'quanlan_dual_assistant.web_app' -and $_.CommandLine -match ' 8766 ' } | "
                    "ForEach-Object { $_.ProcessId }",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=8,
            )
            for line in result.stdout.splitlines():
                line = line.strip()
                if line.isdigit():
                    pids.add(int(line))
        except Exception:
            pass
    current = os.getpid()
    return [pid for pid in pids if pid != current]


def _assistant_release_online() -> bool:
    return _url_reachable(ASSISTANT_PRODUCTION_URL, timeout=1.2)


def _stop_assistant_release(takeover: bool = True) -> dict[str, Any]:
    global ASSISTANT_RELEASE_PROCESS
    _stop_process(ASSISTANT_RELEASE_PROCESS)
    ASSISTANT_RELEASE_PROCESS = None
    if takeover:
        for pid in _assistant_release_pids():
            try:
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, text=True, timeout=5)
            except Exception:
                pass
    time.sleep(0.4)
    return _app_statuses()


def _ensure_assistant_release(takeover: bool = True) -> dict[str, Any]:
    global ASSISTANT_RELEASE_PROCESS
    if _assistant_release_online():
        return _app_statuses()
    if takeover:
        for pid in _assistant_release_pids():
            try:
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, text=True, timeout=5)
            except Exception:
                pass
    if not ASSISTANT_RELEASE_ROOT.exists():
        raise ValueError(f"本机发布版目录不存在：{ASSISTANT_RELEASE_ROOT}。请先在开发版执行升级发布版。")
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    ASSISTANT_RELEASE_PROCESS = subprocess.Popen(
        [sys.executable, "-X", "utf8", "-m", "quanlan_dual_assistant.web_app", str(ASSISTANT_RELEASE_PORT), "assistant-release"],
        cwd=str(ASSISTANT_RELEASE_ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    time.sleep(1.2)
    return _app_statuses()


def _restart_assistant_release(takeover: bool = True) -> dict[str, Any]:
    _stop_assistant_release(takeover=takeover)
    return _ensure_assistant_release(takeover=takeover)

def _run_remote_production_control(app_id: str, action: str) -> None:
    if app_id == "xiaozhuli":
        _run_xiaozhuli_production_control(action)
        return
    env_key = _remote_control_env_key(app_id, action)
    command = os.environ.get(env_key, "").strip()
    if not command and action == "restart":
        stop_command = os.environ.get(_remote_control_env_key(app_id, "stop"), "").strip()
        start_command = os.environ.get(_remote_control_env_key(app_id, "start"), "").strip()
        if stop_command and start_command:
            for cmd in (stop_command, start_command):
                subprocess.run(shlex.split(cmd), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=PRODUCTION_CONTROL_TIMEOUT, check=True)
            return
    if not command:
        raise ValueError(f"远程正式服务未配置启停控制：请设置环境变量 {env_key}，或把该服务配置为本机地址后再由总控台接管。")
    subprocess.run(shlex.split(command), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=PRODUCTION_CONTROL_TIMEOUT, check=True)


def _cloud_monitor_state() -> dict[str, Any]:
    data = _read_json(CLOUD_MONITOR_STATE_FILE, {})
    if not isinstance(data, dict):
        data = {}
    data.setdefault("enabled", True)
    data.setdefault("logs", [])
    return data


def _write_cloud_monitor_state(data: dict[str, Any]) -> None:
    CLOUD_MONITOR_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    logs = data.get("logs")
    if isinstance(logs, list):
        data["logs"] = logs[-80:]
    _write_json(CLOUD_MONITOR_STATE_FILE, data)


def _cloud_log(message: str) -> None:
    state = _cloud_monitor_state()
    logs = state.setdefault("logs", [])
    if isinstance(logs, list):
        logs.append(f"[{time.strftime('%H:%M:%S')}] {message}")
    _write_cloud_monitor_state(state)


def _external_cloud_metrics() -> dict[str, Any]:
    data = _read_json(CLOUD_METRICS_FILE, {})
    return data if isinstance(data, dict) else {}


def _format_bytes(value: Any) -> str:
    try:
        num = float(value)
    except Exception:
        return "未知"
    units = ["B", "KB", "MB", "GB", "TB"]
    idx = 0
    while num >= 1024 and idx < len(units) - 1:
        num /= 1024
        idx += 1
    return f"{num:.1f}{units[idx]}" if idx else f"{int(num)}B"


def _percent_label(value: Any) -> str:
    try:
        return f"{float(value):.1f}%"
    except Exception:
        return "未知"


def _remote_metric_status(percent: Any, warn: float, bad: float) -> str:
    try:
        value = float(percent)
    except Exception:
        return "unknown"
    if value >= bad:
        return "bad"
    if value >= warn:
        return "warn"
    return "ok"


def _cloud_ssh_command(cfg: dict[str, Any], remote_script: str) -> list[str] | None:
    key_path = Path(str(cfg.get("ssh_key") or CLOUD_SSH_KEY_FILE)).expanduser()
    user = str(cfg.get("ssh_user") or "root").strip() or "root"
    host = str(cfg.get("host") or "").strip()
    if not host or not key_path.exists():
        return None
    return [
        "ssh",
        "-i",
        str(key_path),
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "ConnectTimeout=6",
        f"{user}@{host}",
        remote_script,
    ]


REMOTE_CLOUD_METRICS_SCRIPT = r"""python3 - <<'PY'
import json, os, re, shutil, subprocess, time

def read(path, default=''):
    try:
        return open(path, encoding='utf-8', errors='replace').read().strip()
    except Exception:
        return default

def cpu_percent():
    def snap():
        vals = [int(x) for x in read('/proc/stat').splitlines()[0].split()[1:]]
        idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
        return sum(vals), idle
    total1, idle1 = snap()
    time.sleep(0.15)
    total2, idle2 = snap()
    total = max(1, total2 - total1)
    idle = max(0, idle2 - idle1)
    return round((total - idle) * 100 / total, 1)

def mem_info():
    data = {}
    for line in read('/proc/meminfo').splitlines():
        if ':' in line:
            key, val = line.split(':', 1)
            nums = re.findall(r'\d+', val)
            if nums:
                data[key] = int(nums[0]) * 1024
    total = data.get('MemTotal', 0)
    avail = data.get('MemAvailable', 0)
    used = max(0, total - avail)
    pct = round(used * 100 / total, 1) if total else None
    return {'total': total, 'used': used, 'available': avail, 'percent': pct}

def disk_info(path='/'):
    usage = shutil.disk_usage(path)
    pct = round(usage.used * 100 / usage.total, 1) if usage.total else None
    return {'path': path, 'total': usage.total, 'used': usage.used, 'free': usage.free, 'percent': pct}

def net_bytes():
    rows = []
    for line in read('/proc/net/dev').splitlines()[2:]:
        if ':' not in line:
            continue
        iface, rest = line.split(':', 1)
        iface = iface.strip()
        if iface == 'lo':
            continue
        nums = [int(x) for x in rest.split()]
        if len(nums) >= 16:
            rows.append({'iface': iface, 'rx_bytes': nums[0], 'tx_bytes': nums[8]})
    return rows

def systemctl(name):
    try:
        r = subprocess.run(['systemctl', 'is-active', name], capture_output=True, text=True, timeout=2)
        return (r.stdout or r.stderr or '').strip() or 'unknown'
    except Exception as exc:
        return 'unknown'

def ps_rows():
    r = subprocess.run(['ps', '-eo', 'pid,comm,pcpu,pmem,rss,args', '--sort=-pcpu'], capture_output=True, text=True, timeout=4)
    lines = (r.stdout or '').splitlines()[1:80]
    rows = []
    targets = [
        ('qlanalyser', ['qlanalyser', 'uvicorn service.qlanalyser']),
        ('classifier', ['ollama', 'llama-server']),
        ('xiaozhuli', ['feishu-', 'xiaozhuli']),
        ('nginx', ['nginx']),
    ]
    for line in lines:
        parts = line.split(None, 5)
        if len(parts) < 6:
            continue
        pid, comm, pcpu, pmem, rss, args = parts
        item = {'pid': int(pid), 'command': comm, 'cpu_percent': float(pcpu), 'mem_percent': float(pmem), 'rss_kb': int(rss), 'args': args[:180]}
        lower = (comm + ' ' + args).lower()
        if 'python3 -' in lower or 'ps -eo pid,comm,pcpu,pmem,rss,args' in lower:
            continue
        item['service_id'] = ''
        for sid, needles in targets:
            if any(n in lower for n in needles):
                item['service_id'] = sid
                break
        purpose = '系统/其他进程'
        owner = '系统'
        advice = '通常不需要处理，持续异常时再排查。'
        if 'llama-server' in lower:
            purpose = '本地 DeepSeek 分类模型服务，负责飞书消息进入业务前的本地分类。'
            owner = '小猪理分类器'
            advice = '内存大户；可评估更小模型或缓存参数，但不能绕过分类链路。'
        elif 'ollama serve' in lower or comm == 'ollama':
            purpose = '本地模型管理服务，托管 DeepSeek 模型文件和本地推理接口。'
            owner = '小猪理分类器'
            advice = '常驻占用较小；通常保留。'
        elif 'feishu-group-listener' in lower:
            purpose = '飞书群消息监听入口，负责接收群聊事件。'
            owner = '全澜小猪理'
            advice = '关键入口，不建议停。'
        elif 'feishu-codex-dispatcher' in lower:
            purpose = '任务分发器，把分类后的消息交给知识库、工具或 Codex 队列处理。'
            owner = '全澜小猪理'
            advice = 'CPU 长期高才需要排查队列。'
        elif 'feishu-permission-sync' in lower:
            purpose = '飞书权限同步服务，维护文档/知识库访问白名单。'
            owner = '全澜小猪理'
            advice = '之前告警提到过它，建议常驻。'
        elif 'feishu-watchdog' in lower:
            purpose = '小猪理巡检守护进程，发现监听器或队列异常后告警。'
            owner = '全澜小猪理'
            advice = '常驻合理，占用异常才看日志。'
        elif 'xiaozhuli-self-learning' in lower:
            purpose = '全澜小猪理自学习循环，把用户反馈和运行问题沉淀到后续优化。'
            owner = '全澜小猪理'
            advice = '建议常驻；如果 CPU 长期高，先看学习队列和日志。'
        elif 'xiaozhuli-dashboard' in lower:
            purpose = '全澜小猪理网页控制台和宿主进程。'
            owner = '全澜小猪理'
            advice = '业务入口，常驻合理。'
        elif 'uvicorn' in lower and 'qlanalyser' in lower:
            purpose = '脑电分析平台 FastAPI 服务，负责网页和分析接口。'
            owner = '脑电分析平台'
            advice = '常驻合理，分析任务期间 CPU 上升正常。'
        elif 'aliyundunmonitor' in lower or 'aliyundun' in lower:
            purpose = '阿里云安全/监控组件，用于主机防护和云监控。'
            owner = '阿里云'
            advice = '不建议随便关闭。'
        elif 'aliyun-service' in lower:
            purpose = '阿里云助手服务，用于云端运维命令和实例管理。'
            owner = '阿里云'
            advice = '不建议随便关闭。'
        elif 'dockerd' in lower:
            purpose = 'Docker 守护进程，管理容器运行环境。'
            owner = '系统/Docker'
            advice = '若当前不用容器，可评估是否停用。'
        elif 'containerd' in lower:
            purpose = '容器运行时，通常由 Docker 调用。'
            owner = '系统/Docker'
            advice = '跟 Docker 一起评估。'
        elif 'systemd-journal' in lower or 'rsyslogd' in lower:
            purpose = '系统日志服务，保存系统和服务日志。'
            owner = '系统'
            advice = '不建议关闭，可做日志轮转。'
        elif lower.startswith('sshd') or 'sshd:' in lower:
            purpose = 'SSH 远程登录/运维连接，当前总控台采集云服务器指标也会短暂使用。'
            owner = '系统'
            advice = '采集时短时出现很正常；异常多连接时再排查安全日志。'
        elif 'systemd' in lower:
            purpose = 'Linux 服务管理/用户会话管理。'
            owner = '系统'
            advice = '系统核心进程，不处理。'
        elif 'networkmanager' in lower or 'systemd-resolved' in lower:
            purpose = '系统网络和 DNS 解析服务。'
            owner = '系统'
            advice = '不建议关闭。'
        item['purpose'] = purpose
        item['owner'] = owner
        item['advice'] = advice
        rows.append(item)
    return rows

payload = {
    'ok': True,
    'host': os.uname().nodename,
    'uptime': read('/proc/uptime').split()[0] if read('/proc/uptime') else '',
    'load': os.getloadavg(),
    'cpu_percent': cpu_percent(),
    'memory': mem_info(),
    'disk': disk_info('/'),
    'network': net_bytes(),
    'services': {name: systemctl(name) for name in ['qlanalyser', 'nginx', 'xiaozhuli', 'ollama', 'xiaozhuli-classifier']},
    'processes': ps_rows(),
    'collected_at': time.strftime('%Y-%m-%d %H:%M:%S'),
}
print(json.dumps(payload, ensure_ascii=False))
PY"""


def _collect_remote_cloud_metrics(cfg: dict[str, Any]) -> dict[str, Any]:
    cmd = _cloud_ssh_command(cfg, REMOTE_CLOUD_METRICS_SCRIPT)
    if not cmd:
        return {"ok": False, "error": "未配置 SSH 只读采集；请设置 QUANLAN_CLOUD_SSH_KEY 或放置 ~/.ssh/xiaozhuli_aliyun。"}
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=14)
    except Exception as exc:
        return {"ok": False, "error": _safe_error(exc)}
    if proc.returncode != 0:
        return {"ok": False, "error": _safe_error(RuntimeError((proc.stderr or proc.stdout or "SSH 采集失败")[-500:]))}
    try:
        data = json.loads((proc.stdout or "").strip().splitlines()[-1])
        data["ssh_enabled"] = True
        return data if isinstance(data, dict) else {"ok": False, "error": "SSH 采集返回格式异常"}
    except Exception as exc:
        return {"ok": False, "error": _safe_error(exc)}


def _remote_metrics_to_cards(remote: dict[str, Any], file_metrics: dict[str, Any], server_id: str) -> dict[str, Any]:
    if not remote.get("ok"):
        return {
            "cpu": _metric_value(file_metrics, server_id, "cpu"),
            "memory": _metric_value(file_metrics, server_id, "memory"),
            "disk": _metric_value(file_metrics, server_id, "disk"),
            "load": _metric_value(file_metrics, server_id, "load"),
            "network": _metric_value(file_metrics, server_id, "network"),
        }
    memory = remote.get("memory") if isinstance(remote.get("memory"), dict) else {}
    disk = remote.get("disk") if isinstance(remote.get("disk"), dict) else {}
    load = remote.get("load") if isinstance(remote.get("load"), list) else []
    network = remote.get("network") if isinstance(remote.get("network"), list) else []
    rx = sum(int(x.get("rx_bytes") or 0) for x in network if isinstance(x, dict))
    tx = sum(int(x.get("tx_bytes") or 0) for x in network if isinstance(x, dict))
    cpu_pct = remote.get("cpu_percent")
    mem_pct = memory.get("percent")
    disk_pct = disk.get("percent")
    return {
        "cpu": {"label": _percent_label(cpu_pct), "value": cpu_pct, "unit": "CPU 使用率", "status": _remote_metric_status(cpu_pct, 75, 90)},
        "memory": {"label": _percent_label(mem_pct), "value": mem_pct, "unit": f"{_format_bytes(memory.get('used'))} / {_format_bytes(memory.get('total'))}", "status": _remote_metric_status(mem_pct, 80, 92)},
        "disk": {"label": _percent_label(disk_pct), "value": disk_pct, "unit": f"{_format_bytes(disk.get('used'))} / {_format_bytes(disk.get('total'))}", "status": _remote_metric_status(disk_pct, 75, 90)},
        "load": {"label": ", ".join(f"{float(x):.2f}" for x in load[:3]) if load else "未知", "value": load[0] if load else None, "unit": "1 / 5 / 15 分钟", "status": "ok"},
        "network": {"label": f"入 {_format_bytes(rx)} / 出 {_format_bytes(tx)}", "value": {"rx_bytes": rx, "tx_bytes": tx}, "unit": "累计流量", "status": "ok"},
    }


def _service_resource_summary(remote: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    service_names = {"eeg": "qlanalyser", "xiaozhuli": "xiaozhuli", "classifier": "classifier"}
    processes = remote.get("processes") if isinstance(remote.get("processes"), list) else []
    systemd = remote.get("services") if isinstance(remote.get("services"), dict) else {}
    for app_id, service_name in service_names.items():
        rows = [x for x in processes if isinstance(x, dict) and x.get("service_id") == service_name]
        cpu = sum(float(x.get("cpu_percent") or 0) for x in rows)
        mem = sum(float(x.get("mem_percent") or 0) for x in rows)
        rss = sum(int(x.get("rss_kb") or 0) for x in rows) * 1024
        result[app_id] = {
            "systemd": (systemd.get("xiaozhuli-classifier") if app_id == "classifier" else systemd.get(service_name)) or "unknown",
            "process_count": len(rows),
            "cpu_percent": round(cpu, 1),
            "mem_percent": round(mem, 1),
            "rss": rss,
            "rss_label": _format_bytes(rss),
            "top_processes": sorted(rows, key=lambda x: float(x.get("cpu_percent") or 0), reverse=True)[:6],
        }
    return result


def _metric_value(metrics: dict[str, Any], server_id: str, key: str) -> dict[str, Any]:
    server_metrics = metrics.get(server_id) if isinstance(metrics, dict) else {}
    value = server_metrics.get(key) if isinstance(server_metrics, dict) else None
    if isinstance(value, dict):
        return {"label": str(value.get("label") or "待接入"), "value": value.get("value"), "unit": str(value.get("unit") or ""), "status": str(value.get("status") or "unknown")}
    if value is None or value == "":
        return {"label": "待接入", "value": None, "unit": "", "status": "unknown"}
    return {"label": str(value), "value": value, "unit": "", "status": "ok"}


def _cloud_server_statuses(*, force: bool = False) -> dict[str, Any]:
    state = _cloud_monitor_state()
    metrics = _external_cloud_metrics()
    enabled = bool(state.get("enabled", True))
    servers: list[dict[str, Any]] = []
    for cfg in CLOUD_MONITOR_DEFAULT_SERVERS:
        root_probe = _http_probe(str(cfg.get("root_url") or ""), timeout=2.2) if enabled else {"ok": False, "latency_ms": None, "message": "监控已暂停"}
        health_probe = _http_probe(str(cfg.get("health_url") or ""), timeout=2.2) if enabled else {"ok": False, "latency_ms": None, "message": "监控已暂停"}
        remote_metrics = _collect_remote_cloud_metrics(cfg) if enabled else {"ok": False, "error": "监控已暂停"}
        resource_by_app = _service_resource_summary(remote_metrics)
        ok = bool(root_probe.get("ok") or health_probe.get("ok"))
        latency_values = [x.get("latency_ms") for x in (root_probe, health_probe) if isinstance(x.get("latency_ms"), (int, float))]
        apps = []
        for app in _app_statuses().get("apps", []):
            if app.get("id") in set(cfg.get("services") or ()):
                app = dict(app)
                app["resource"] = resource_by_app.get(str(app.get("id") or ""), {})
                apps.append(app)
        classifier_resource = resource_by_app.get("classifier", {})
        if classifier_resource:
            apps.append({
                "id": "classifier",
                "name": "本地 DeepSeek 分类器",
                "production_url": "http://127.0.0.1:11435/v1",
                "production_target": "127.0.0.1:11435 / xiaozhuli-classifier.service",
                "production_online": classifier_resource.get("systemd") == "active",
                "resource": classifier_resource,
                "protected": True,
                "description": "飞书消息先本地分类的保护链路，优化时不能绕过。",
            })
        servers.append({
            "id": cfg["id"],
            "name": cfg["name"],
            "provider": cfg["provider"],
            "host": cfg["host"],
            "root_url": cfg["root_url"],
            "health_url": cfg["health_url"],
            "enabled": enabled,
            "online": ok,
            "latency_ms": min(latency_values) if latency_values else None,
            "root_probe": root_probe,
            "health_probe": health_probe,
            "remote_metrics": {
                "ok": bool(remote_metrics.get("ok")),
                "error": str(remote_metrics.get("error") or ""),
                "host": str(remote_metrics.get("host") or ""),
                "collected_at": str(remote_metrics.get("collected_at") or ""),
                "ssh_enabled": bool(remote_metrics.get("ssh_enabled")),
            },
            "metrics": _remote_metrics_to_cards(remote_metrics, metrics, str(cfg["id"])),
            "services": apps,
            "top_processes": (remote_metrics.get("processes") or [])[:10] if isinstance(remote_metrics.get("processes"), list) else [],
        })
    if force:
        _cloud_log("已手动刷新云服务器健康状态。")
    return {
        "enabled": enabled,
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "servers": servers,
        "logs": state.get("logs", []),
        "metrics_source": str(CLOUD_METRICS_FILE),
        "metrics_connected": CLOUD_METRICS_FILE.exists(),
    }


def _control_cloud_monitor(payload: dict[str, Any]) -> dict[str, Any]:
    action = str(payload.get("action") or "refresh").strip().lower()
    state = _cloud_monitor_state()
    if action == "pause":
        state["enabled"] = False
        _write_cloud_monitor_state(state)
        _cloud_log("监控已暂停；页面不再主动探测云服务。")
    elif action == "resume":
        state["enabled"] = True
        _write_cloud_monitor_state(state)
        _cloud_log("监控已恢复；开始探测云服务。")
    elif action == "clear_logs":
        state["logs"] = []
        _write_cloud_monitor_state(state)
    elif action == "refresh":
        pass
    else:
        raise ValueError("未知云服务器操作")
    return _cloud_server_statuses(force=action == "refresh")


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


def _windows_node_pids_by_scripts(scripts: tuple[str, ...]) -> dict[str, list[int]]:
    if os.name != "nt":
        return {script: [] for script in scripts}
    patterns = {script: re.compile(re.escape(script), re.IGNORECASE) for script in scripts}
    ps = (
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.Name -eq 'node.exe' } | "
        "Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress"
    )
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", ps],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
        raw = (result.stdout or "").strip()
        items = json.loads(raw) if raw else []
    except Exception:
        items = []
    if isinstance(items, dict):
        items = [items]
    found = {script: [] for script in scripts}
    for item in items if isinstance(items, list) else []:
        cmd = str(item.get("CommandLine") or "")
        try:
            pid = int(item.get("ProcessId") or 0)
        except Exception:
            pid = 0
        if not pid:
            continue
        for script, pattern in patterns.items():
            if pattern.search(cmd):
                found[script].append(pid)
    return found


def _xiaozhuli_worker_pids() -> dict[str, list[int]]:
    return _windows_node_pids_by_scripts((*XIAOZHULI_WORKER_SCRIPTS, "wecom-callback.mjs", "xiaozhuli-dashboard.mjs"))


def _xiaozhuli_workers_running() -> bool:
    pids = _xiaozhuli_worker_pids()
    return any(pids.get(script) for script in XIAOZHULI_WORKER_SCRIPTS)


def _stop_xiaozhuli_workers() -> None:
    pids = _xiaozhuli_worker_pids()
    for script in XIAOZHULI_STOP_SCRIPT_ORDER:
        _kill_pids(pids.get(script, []))


def _start_xiaozhuli_worker(script: str, env: dict[str, str]) -> None:
    node_exe = XIAOZHULI_NODE_EXE if Path(XIAOZHULI_NODE_EXE).exists() else "node"
    entry = XIAOZHULI_ROOT / script
    if not entry.exists():
        return
    subprocess.Popen(
        [node_exe, entry.name],
        cwd=str(XIAOZHULI_ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )


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
    assistant_production_online = _assistant_release_online()
    xiaozhuli_production_online = _url_reachable(XIAOZHULI_PRODUCTION_URL, timeout=0.6)
    eeg_production_url = EEG_ANALYSER_TARGET + "/"
    eeg_online = _url_reachable(eeg_production_url, timeout=0.6)
    eeg_development_online = _url_reachable(EEG_ANALYSER_DEVELOPMENT_URL, timeout=0.6)
    xiaozhuli_managed = _process_running(XIAOZHULI_PROCESS)
    xiaozhuli_workers_running = _xiaozhuli_workers_running()
    eeg_managed = _process_running(EEG_ANALYSER_PROCESS)
    xiaozhuli_sync = "待同步" if XIAOZHULI_CONFIG_DIRTY else ("已同步" if xiaozhuli_managed else "后台运行" if xiaozhuli_workers_running else "外部运行" if xiaozhuli_online else "未启动")
    if XIAOZHULI_CONFIG_DIRTY and xiaozhuli_online and not xiaozhuli_managed:
        xiaozhuli_sync = "需接管重启"
    xiaozhuli_development_online = bool(xiaozhuli_online or xiaozhuli_workers_running)
    xiaozhuli_development_state = "已同步" if xiaozhuli_managed else ("后台运行" if xiaozhuli_workers_running else "外部运行" if xiaozhuli_online else "未启动")
    eeg_development_state = "已启动" if eeg_managed else ("外部运行" if eeg_development_online else "未启动")
    assistant_production_control = _production_control_status("assistant", ASSISTANT_PRODUCTION_URL)
    xiaozhuli_production_control = _production_control_status("xiaozhuli", XIAOZHULI_PRODUCTION_URL)
    eeg_production_control = _production_control_status("eeg", eeg_production_url)
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
                "production_url": ASSISTANT_PRODUCTION_URL,
                "production_target": ASSISTANT_PRODUCTION_URL,
                "production_note": "本机发布版入口；运行在独立目录和端口，不受开发版代码修改影响。",
                "production_online": assistant_production_online,
                "production_state": "本机发布版在线" if assistant_production_online else "本机发布版未启动",
                **assistant_production_control,
                "development_url": "/assistant/",
                "development_target": "http://127.0.0.1:8765/assistant/",
                "online": assistant_production_online,
                "managed": True,
                "sync_state": "本机发布版在线" if assistant_production_online else "本机发布版未启动",
                "development_online": True,
                "development_state": "总控台运行中",
                "config_scope": "模型、Key、SMTP 在总控台维护；任务页只保留业务参数。",
            },
            {
                "id": "xiaozhuli",
                "name": "全澜小猪理",
                "route": "/xiaozhuli/",
                "target": XIAOZHULI_TARGET,
                "production_url": XIAOZHULI_PRODUCTION_URL,
                "production_target": XIAOZHULI_PRODUCTION_URL,
                "production_note": "正式服务入口。",
                "production_online": xiaozhuli_production_online,
                "production_state": "远程在线" if xiaozhuli_production_online else "未启动或不可达",
                **xiaozhuli_production_control,
                "development_url": "/xiaozhuli/",
                "development_target": XIAOZHULI_TARGET,
                "online": xiaozhuli_production_online,
                "managed": xiaozhuli_managed,
                "sync_state": "远程在线" if xiaozhuli_production_online else "未启动或不可达",
                "development_online": xiaozhuli_development_online,
                "development_state": xiaozhuli_development_state,
                "port": XIAOZHULI_PORT,
                "config_scope": "由总控台启动时注入模型 URL、模型名和 Key；内部模型配置入口隐藏。",
            },
            {
                "id": "eeg",
                "name": "脑电分析平台",
                "route": "/eeg/",
                "target": EEG_ANALYSER_TARGET,
                "production_url": eeg_production_url,
                "production_target": eeg_production_url,
                "production_note": "正式服务入口。",
                "production_online": eeg_online,
                "production_state": "远程在线" if eeg_online else "未启动或不可达",
                **eeg_production_control,
                "development_url": EEG_ANALYSER_DEVELOPMENT_URL,
                "development_target": EEG_ANALYSER_DEVELOPMENT_URL,
                "online": eeg_online,
                "managed": eeg_managed,
                "sync_state": "流程平台",
                "development_online": eeg_development_online,
                "development_state": eeg_development_state,
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
    if _url_reachable(EEG_ANALYSER_DEVELOPMENT_URL):
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


def _stop_eeg_analyser(*, takeover: bool = False) -> dict[str, Any]:
    global EEG_ANALYSER_PROCESS
    _stop_process(EEG_ANALYSER_PROCESS)
    EEG_ANALYSER_PROCESS = None
    if takeover:
        _kill_pids(_pids_on_port(EEG_ANALYSER_PORT))
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
                try:
                    import ftfy  # type: ignore
                    text = ftfy.fix_text(text)
                except Exception:
                    pass
                text = text.replace("http://127.0.0.1:8765/", "/")
                body = text.encode("utf-8")
                if "charset=" not in content_type.lower():
                    content_type = content_type.split(";", 1)[0] + "; charset=utf-8"
            _send_bytes(handler, body, content_type, resp.status)
    except urllib.error.HTTPError as exc:
        _send_bytes(handler, exc.read(), exc.headers.get("Content-Type", "text/plain; charset=utf-8"), exc.code)
    except urllib.error.URLError as exc:
        _send_bytes(handler, f"EEG analyser unavailable: {_safe_error(exc)}".encode("utf-8"), "text/plain; charset=utf-8", 502)


def _ensure_xiaozhuli_dashboard() -> None:
    global XIAOZHULI_PROCESS, XIAOZHULI_CONFIG_DIRTY
    if XIAOZHULI_PROCESS and XIAOZHULI_PROCESS.poll() is None and XIAOZHULI_CONFIG_DIRTY:
        _stop_process(XIAOZHULI_PROCESS)
        XIAOZHULI_PROCESS = None
    env = os.environ.copy()
    _apply_shared_config_env(env)
    env.setdefault("XIAOZHULI_DASHBOARD_HOST", "127.0.0.1")
    env.setdefault("XIAOZHULI_DASHBOARD_PORT", str(XIAOZHULI_PORT))
    pids = _xiaozhuli_worker_pids()
    for script in XIAOZHULI_WORKER_SCRIPTS:
        if not pids.get(script):
            _start_xiaozhuli_worker(script, env)
    if not _url_reachable(f"{XIAOZHULI_TARGET}/"):
        entry = XIAOZHULI_ROOT / "xiaozhuli-dashboard.mjs"
        if not entry.exists():
            raise FileNotFoundError(f"Xiaozhuli dashboard not found: {entry}")
        node_exe = XIAOZHULI_NODE_EXE if Path(XIAOZHULI_NODE_EXE).exists() else "node"
        XIAOZHULI_PROCESS = subprocess.Popen([node_exe, entry.name], cwd=str(XIAOZHULI_ROOT), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)
    XIAOZHULI_CONFIG_DIRTY = False
    time.sleep(0.8)


def _restart_xiaozhuli_dashboard(*, takeover: bool = False) -> dict[str, Any]:
    global XIAOZHULI_PROCESS, XIAOZHULI_CONFIG_DIRTY
    _stop_process(XIAOZHULI_PROCESS)
    XIAOZHULI_PROCESS = None
    _stop_xiaozhuli_workers()
    if takeover:
        _kill_pids(_pids_on_port(XIAOZHULI_PORT))
    XIAOZHULI_CONFIG_DIRTY = True
    _ensure_xiaozhuli_dashboard()
    return _app_statuses()


def _stop_xiaozhuli_dashboard(*, takeover: bool = False) -> dict[str, Any]:
    global XIAOZHULI_PROCESS, XIAOZHULI_CONFIG_DIRTY
    _stop_process(XIAOZHULI_PROCESS)
    XIAOZHULI_PROCESS = None
    _stop_xiaozhuli_workers()
    if takeover:
        _kill_pids(_pids_on_port(XIAOZHULI_PORT))
    XIAOZHULI_CONFIG_DIRTY = False
    return _app_statuses()


def _control_app(payload: dict[str, Any]) -> dict[str, Any]:
    app_id = str(payload.get("app") or "").strip()
    action = str(payload.get("action") or "").strip()
    scope = str(payload.get("scope") or "development").strip().lower()
    takeover = bool(payload.get("takeover", True))
    if action == "status":
        return _app_statuses()
    if scope == "production":
        production_urls = {
            "assistant": ASSISTANT_PRODUCTION_URL,
            "xiaozhuli": XIAOZHULI_PRODUCTION_URL,
            "eeg": EEG_ANALYSER_TARGET + "/",
        }
        production_url = production_urls.get(app_id, "")
        if not production_url:
            raise ValueError("unknown production app")
        if app_id == "assistant":
            if action in {"ensure", "start"}:
                return _ensure_assistant_release(takeover=takeover)
            if action == "restart":
                return _restart_assistant_release(takeover=takeover)
            if action == "stop":
                return _stop_assistant_release(takeover=takeover)
        if not _is_local_url(production_url):
            _run_remote_production_control(app_id, action)
            time.sleep(0.6)
            return _app_statuses()
        scope = "development"
    if app_id == "xiaozhuli":
        if action in {"ensure", "start"}:
            _ensure_xiaozhuli_dashboard()
            return _app_statuses()
        if action in {"restart", "sync"}:
            return _restart_xiaozhuli_dashboard(takeover=takeover)
        if action == "stop":
            return _stop_xiaozhuli_dashboard(takeover=takeover)
    if app_id == "eeg":
        if action in {"ensure", "start"}:
            _ensure_eeg_analyser()
            return _app_statuses()
        if action == "restart":
            return _restart_eeg_analyser(takeover=takeover)
        if action == "stop":
            return _stop_eeg_analyser(takeover=takeover)
    if app_id == "assistant":
        if action in {"ensure", "start"}:
            return _app_statuses()
        if action == "stop":
            raise ValueError("总控台自身不能从页面里停止")
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
    lowered = text.lower()
    if "deepseek chat" in lowered:
        return "DeepSeek Chat（官方润色）"
    if "deepseek reasoner" in lowered:
        return "DeepSeek Reasoner（官方）"
    aliases = {
        "gpt-5.5": "GPT-5.5",
        "gpt-5.4": "GPT-5.4",
        "gpt-5.4-mini": "GPT-5.4 mini（快速）",
        "gpt-5.4 mini": "GPT-5.4 mini（快速）",
        "gpt-5.4-nano": "GPT-5.4 nano（最低成本）",
        "gpt-5.4 nano": "GPT-5.4 nano（最低成本）",
        "deepseek-chat": "DeepSeek Chat（官方润色）",
        "deepseek chat": "DeepSeek Chat（官方润色）",
        "deepseek-chat（官方润色）": "DeepSeek Chat（官方润色）",
        "deepseek chat（官方润色）": "DeepSeek Chat（官方润色）",
        "deepseek chat锛堝畼鏂规鼎鑹诧級": "DeepSeek Chat（官方润色）",
        "deepseek-reasoner": "DeepSeek Reasoner（官方）",
        "deepseek reasoner": "DeepSeek Reasoner（官方）",
        "deepseek reasoner锛堝畼鏂癸級": "DeepSeek Reasoner（官方）",
    }
    return aliases.get(lowered, text)


def _daily_image_engine_arg(value: Any) -> str:
    text = str(value or "").strip()
    lowered = text.lower()
    if "gpt image 2" in lowered or "gpt-image-2" in lowered:
        return "生图专用｜GPT Image 2"
    if "gemini 3 pro image" in lowered or "gemini-3-pro-image" in lowered:
        return "生图专用｜Gemini 3 Pro Image Preview"
    if "gemini 3.1 flash image" in lowered or "gemini-3.1-flash-image" in lowered:
        return "生图专用｜Gemini 3.1 Flash Image Preview"
    aliases = {
        "gpt-image-2": "生图专用｜GPT Image 2",
        "gpt image 2": "生图专用｜GPT Image 2",
        "生图专用｜gpt image 2": "生图专用｜GPT Image 2",
        "鐢熷浘涓撶敤锝淕pt image 2": "生图专用｜GPT Image 2",
        "gemini-3-pro-image-preview": "生图专用｜Gemini 3 Pro Image Preview",
        "gemini 3 pro image preview": "生图专用｜Gemini 3 Pro Image Preview",
        "gemini-3.1-flash-image-preview": "生图专用｜Gemini 3.1 Flash Image Preview",
        "gemini 3.1 flash image preview": "生图专用｜Gemini 3.1 Flash Image Preview",
    }
    return aliases.get(lowered, text)


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
    if not text:
        return ""
    markers = ("素材已生成", "输出目录", "作品目录", "已生成", "已保存")
    if not any(marker in text for marker in markers):
        return ""
    tail = text
    for sep in ("：", ":"):
        if sep in tail:
            tail = tail.split(sep, 1)[1]
            break
    tail = tail.strip().strip('"')
    match = re.search(r"([A-Za-z]:\\[^\r\n]+|/[^\r\n]+)", tail)
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
    payload = {**payload, **_apply_business_steps_to_models(_model_settings())}
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
        if action == "release_package_update":
            return [sys.executable, "tools/channel_manager.py", "--channel", "release", "package-update", "--note", "web release package"], PROJECT_ROOT
        if action == "release_init":
            return [sys.executable, "tools/channel_manager.py", "--channel", "release", "init-release"], PROJECT_ROOT
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
        models = _models_with_url_defaults(_apply_business_steps_to_models(_model_settings()))

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
        _add(args, "--daily-test-b-image-limit", payload.get("research_test_b_image_limit"))
        # The current daily digest CLI does not always expose this option.
        # Keep the UI setting for future use, but do not pass an unsupported flag.
        _add(args, "--daily-journals", payload.get("research_journals"))
        _add(args, "--daily-article-list", article_list_value)
        daily_polish_engine = _daily_text_engine_arg(payload.get("polish_engine"))
        daily_text_engine = _daily_text_engine_arg(payload.get("text_engine"))
        if str(daily_polish_engine or "").lower().startswith("deepseek"):
            daily_text_engine = daily_polish_engine
        _add(args, "--daily-text-engine", daily_text_engine)
        _add(args, "--daily-polish-engine", daily_polish_engine)
        _add(args, "--daily-image-engine", _daily_image_engine_arg(payload.get("image_engine")))
        if str(payload.get("research_skip_medical_related") or "").lower() in {"1", "true", "yes", "on"}:
            args.append("--daily-skip-medical-related")
        email_profile = _email_profile_for_payload(payload, "daily_research_digest")
        if email_profile.get("email_enabled") and email_profile.get("email_recipient"):
            args.append("--daily-email")
            _add(args, "--daily-email-recipient", email_profile.get("email_recipient"))
    return _python_command(mode, extra_args=args), mode.path


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


def _audience_material_root() -> str:
    candidates: list[str] = []
    for settings_path in (
        SETTINGS_FILE,
        ASSISTANT_DEV_ROOT / "quanlan_dual_assistant_settings.json",
        ASSISTANT_RELEASE_ROOT / "quanlan_dual_assistant_settings.json",
    ):
        data = _read_json(settings_path, {})
        if isinstance(data, dict):
            value = str(data.get("culture_out_dir") or "").strip().strip('"')
            if value and value not in candidates:
                candidates.append(value)
    for value in candidates:
        path = Path(value)
        if path.exists():
            return str(path)
    fallback = PROJECT_ROOT / "modes" / "culture" / "outputs"
    return str(fallback)


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
    audience_modes = {"once", "quick", "standard", "deep", "preflight"}
    if project == "assistant":
        cmd = [sys.executable, "-m", "modes.culture.automedia_core.audience_test_bot"]
        material_root = _audience_material_root()
        if material_root:
            cmd.extend(["--material-root", material_root])
        if mode in {"standard", "deep", "preflight", "once"}:
            cmd.append("--online")
        if mode == "quick":
            cmd.extend(["--query-limit", "2", "--max-materials", "8"])
        elif mode == "standard" or mode == "once":
            cmd.extend(["--query-limit", "5", "--max-materials", "30"])
        elif mode == "deep":
            cmd.extend(["--query-limit", "8", "--max-materials", "80"])
        elif mode == "preflight":
            cmd.extend(["--query-limit", "5", "--max-materials", "45"])
        return "自媒体小猪理", cmd, PROJECT_ROOT, mode if mode in audience_modes else "standard"
    if project == "xiaozhuli":
        return "全澜小猪理", ["node", "self-optimizer.mjs", "once", "--force"], XIAOZHULI_ROOT, mode if mode in audience_modes else "standard"
    if project == "eeg":
        return "脑电分析平台", ["node", "work/self_optimizer.js", "once", "--force"], EEG_ANALYSER_ROOT, mode if mode in audience_modes else "standard"
    raise ValueError("该项目还没有暴露虚拟用户测试命令；已自动显示，待项目提供命令后可启动。")


def _audience_mode_label(mode: str) -> str:
    if mode == "quick":
        return "快速体检"
    if mode == "standard" or mode == "once":
        return "标准评审"
    if mode == "deep":
        return "深度压力测试"
    if mode == "preflight":
        return "上线前复核"
    if mode == "dev_upgrade":
        return "一键升级开发区"
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
            "objections": [
                f"{item.get('area') or 'overall'}：{_compact_line(item.get('message'))}"
                for item in top
                if str(item.get("severity") or "").lower() not in {"pass", "ok"} and item.get("message")
            ] or ["本轮没有形成强烈反对意见。"],
            "suggestions": suggestions or ["继续积累真实观众反馈后复测。"],
            "expected_effects": expected or ["维持当前版本，避免无依据调整。"],
            "needs_human_confirmation": [
                "虚拟用户测试只能提前暴露可能问题，真实转化、评论和专家事实仍需真人确认。"
            ],
            "counts": {
                "overall": str(len(findings)),
                "positive": str(sum(1 for item in findings if isinstance(item, dict) and str(item.get("severity") or "").lower() in {"pass", "ok"})),
                "negative": str(sum(1 for item in findings if isinstance(item, dict) and str(item.get("severity") or "").lower() not in {"pass", "ok"})),
            },
        }
    if report.get("last_result"):
        return {
            "overview": ["自优化器已完成一轮检查，结果已写入项目状态。"],
            "objections": ["请展开原始日志查看角色评审指出的问题。"],
            "suggestions": ["如需更细的虚拟用户建议，请使用“输入优化建议”补充你的观察后再复测。"],
            "expected_effects": ["下一轮会把记录的反馈纳入角色评审和修复计划。"],
            "needs_human_confirmation": ["项目级自优化结果需要结合真实运行页面复核。"],
            "counts": {"overall": "完成", "positive": "已跑", "negative": "待读"},
        }
    return {}


def _tail_jsonl(path: Path, limit: int = 80) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()[-limit:]
    except Exception:
        return []
    rows: list[dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except Exception:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def _read_json_file(path: Path) -> dict[str, Any]:
    data = _read_json(path, {})
    return data if isinstance(data, dict) else {}


def _audience_report_paths(project: str) -> list[Path]:
    project = str(project or "").strip()
    if project == "assistant":
        return [
            PROJECT_ROOT / "modes" / "culture" / "outputs" / "audience_test_bot" / "latest_audience_test_report.json",
            PROJECT_ROOT / "modes" / "culture" / "outputs" / "self_optimizer" / "self_optimizer_state.json",
            PROJECT_ROOT / "modes" / "culture" / "outputs" / "self_optimizer" / "self_optimizer_patch_plan.json",
        ]
    if project == "xiaozhuli":
        return [
            XIAOZHULI_ROOT / "self-optimizer-state.json",
            XIAOZHULI_ROOT / "self-optimizer-patch-plan.json",
            XIAOZHULI_ROOT / "feishu-realtime-optimizer-state.json",
        ]
    if project == "eeg":
        base = EEG_ANALYSER_ROOT / "outputs" / "eeglab-mne-dev" / "assets" / "realtime_optimizer"
        return [
            base / "self_optimizer_state.json",
            base / "optimizer_state.json",
            base / "self_optimizer_patch_plan.json",
        ]
    return []


def _latest_existing_path(paths: list[Path]) -> Path | None:
    existing = [path for path in paths if path.exists()]
    if not existing:
        return None
    return max(existing, key=lambda path: path.stat().st_mtime)


def _summary_from_optimizer_files(project: str) -> tuple[dict[str, list[str]], list[str], str]:
    if project == "assistant":
        base = PROJECT_ROOT / "modes" / "culture" / "outputs" / "self_optimizer"
        roleplay = base / "self_optimizer_roleplay_detail.jsonl"
        issues = base / "self_optimizer_issues.jsonl"
        patch = base / "self_optimizer_patch_plan.json"
    elif project == "xiaozhuli":
        base = XIAOZHULI_ROOT
        roleplay = base / "self-optimizer-roleplay-detail.jsonl"
        issues = base / "self-optimizer-issues.jsonl"
        patch = base / "self-optimizer-patch-plan.json"
    elif project == "eeg":
        base = EEG_ANALYSER_ROOT / "outputs" / "eeglab-mne-dev" / "assets" / "realtime_optimizer"
        roleplay = base / "self_optimizer_roleplay_detail.jsonl"
        issues = base / "self_optimizer_issues.jsonl"
        patch = base / "self_optimizer_patch_plan.json"
    else:
        return {}, [], ""
    role_rows = _tail_jsonl(roleplay, 60)
    issue_rows = _tail_jsonl(issues, 60)
    patch_data = _read_json_file(patch)
    readable: list[str] = []
    overview: list[str] = []
    objections: list[str] = []
    suggestions: list[str] = []
    for row in reversed(role_rows[-12:]):
        speaker = _compact_line(row.get("speaker") or row.get("persona") or row.get("role") or "虚拟评委", 40)
        text = _compact_line(row.get("message") or row.get("content") or row.get("question") or row.get("finding") or row.get("summary"), 220)
        if text:
            objections.append(f"{speaker}：{text}")
            readable.append(f"虚拟评委：{speaker}；质疑：{text}")
    for row in reversed(issue_rows[-12:]):
        text = _compact_line(row.get("message") or row.get("issue") or row.get("evidence") or row.get("next_action"), 220)
        action = _compact_line(row.get("next_action") or row.get("suggestion") or row.get("fix"), 220)
        if text:
            overview.append(text)
        if action:
            suggestions.append(action)
            readable.append(f"建议：{action}")
    plan_items = patch_data.get("items") or patch_data.get("patches") or patch_data.get("plans") or []
    if isinstance(plan_items, list):
        for item in plan_items[:8]:
            if isinstance(item, dict):
                text = _compact_line(item.get("summary") or item.get("title") or item.get("change") or item.get("next_action"), 220)
            else:
                text = _compact_line(item, 220)
            if text:
                suggestions.append(text)
    summary = {
        "overview": list(dict.fromkeys(overview or ["已读取项目自优化器/角色评审记录。"]))[:8],
        "objections": list(dict.fromkeys(objections or ["未读取到新的角色反对意见；可先运行一轮评审。"]))[:8],
        "suggestions": list(dict.fromkeys(suggestions or ["运行评审或写入人工观察后生成更具体的修复项。"]))[:8],
        "expected_effects": ["把角色反对意见转成下一轮修复和复测项目，降低真实用户首次使用时的误解。"],
        "needs_human_confirmation": ["真实客户/观众反应、专业事实、上线风险仍需人工复核。"],
        "counts": {
            "overall": str(len(role_rows) + len(issue_rows)),
            "positive": "已读",
            "negative": str(len(objections) + len(overview)),
        },
    }
    return summary, readable[-30:], str(base)


def _audience_report_payload(project: str) -> dict[str, Any]:
    project = str(project or "").strip() or "assistant"
    path = _latest_existing_path(_audience_report_paths(project))
    if path:
        report = _read_json_file(path)
        summary = _summary_from_report(report)
        readable = report.get("readable_log") if isinstance(report.get("readable_log"), list) else []
        if summary:
            return {
                "ok": True,
                "project": project,
                "report_found": True,
                "report_path": str(path),
                "summary": summary,
                "readable_log": [str(x) for x in readable[-80:]],
            }
    summary, readable, base = _summary_from_optimizer_files(project)
    return {
        "ok": True,
        "project": project,
        "report_found": bool(summary),
        "report_path": str(path or base or ""),
        "summary": summary or {
            "overview": ["还没有找到该项目的虚拟用户测试报告。"],
            "objections": ["请先启动一轮评审。"],
            "suggestions": ["运行后这里会展示建议改动。"],
            "expected_effects": ["等待评审结果。"],
            "needs_human_confirmation": ["真实用户反馈仍需人工确认。"],
            "counts": {"overall": "--", "positive": "--", "negative": "--"},
        },
        "readable_log": readable,
    }


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
    models = job.get("model_snapshot")
    if not isinstance(models, dict):
        models = _apply_business_steps_to_models(_apply_connection_library_to_defaults())
    else:
        models = _apply_business_steps_to_models(models)
    snapshot_path = job.get("model_snapshot_path")
    if not snapshot_path:
        snapshot_path = str(_write_job_model_snapshot(job_id, models))
        job["model_snapshot_path"] = snapshot_path
    _sync_shared_model_config_to_projects(models)
    env["QUANLAN_MODEL_DEFAULTS_FILE"] = str(snapshot_path)
    env["QUANLAN_SHARED_MODEL_CONFIG_FILE"] = str(snapshot_path)
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
        image_model = str(models.get("culture_image_model") or models.get("image_engine") or "")
        if image_model:
            env["OPENAI_IMAGE_MODEL"] = image_model
            env["CHATSHARE_IMAGE_MODEL"] = image_model
            env["IMAGE_MODEL"] = image_model
            env["QUANLAN_IMAGE_MODEL"] = image_model
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
        polish_model = str(models.get("culture_polish_model") or models.get("polish_engine") or "")
        if polish_model:
            env["DEEPSEEK_MODEL"] = polish_model
            env["DEEPSEEK_CHAT_MODEL"] = polish_model
            env["DEEPSEEK_TEXT_MODEL"] = polish_model
            env["POLISH_MODEL"] = polish_model
        env["GPT_PRO_BASE_URL"] = str(models.get("gpt_pro_base_url") or models.get("research_polish_base_url") or "")
        if models.get("minimax_base_url"):
            env["MINIMAX_BASE_URL"] = str(models.get("minimax_base_url") or "")
        minimax_model = str(models.get("minimax_tts_model") or "")
        if minimax_model:
            env["MINIMAX_MODEL"] = minimax_model
            env["MINIMAX_TTS_MODEL"] = minimax_model
    snapshot_summary = _model_usage_summary(models if isinstance(models, dict) else None)
    try:
        proc = subprocess.Popen(cmd, cwd=str(cwd), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", bufsize=1)
        job["process"] = proc
        job["status"] = "running"
        job["updated_at"] = int(time.time() * 1000)
        job["lines"].append(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 任务已开始处理，请保持窗口开启。\n")
        job["lines"].append(
            f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 本任务使用启动时模型快照：文案 {snapshot_summary.get('text_model')} ｜ 润色 {snapshot_summary.get('polish_model')} ｜ 图片 {snapshot_summary.get('image_model')}；任务启动后再改总控台配置，不会影响本次已启动子进程。\n"
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            output_dir = _extract_output_dir_from_line(line)
            if output_dir:
                job["output_dir"] = output_dir
            job["lines"].append(line)
            job["lines"] = job["lines"][-5000:]
            job["updated_at"] = int(time.time() * 1000)
        job["exit_code"] = proc.wait()
        job["status"] = "finished"
        job["updated_at"] = int(time.time() * 1000)
        if job["exit_code"] == 0:
            job["lines"].append(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 任务已完成。\n")
        else:
            job["lines"].append(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 任务未完成，请查看运行日志中的具体提示。\n")
        job["summary"] = _summary_from_job(job)
    except Exception as exc:
        job["status"] = "failed"
        job["exit_code"] = -1
        job["updated_at"] = int(time.time() * 1000)
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
            body = _assistant_workbench_html()
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
            body = _model_connection_html()
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
            body = _audience_lab_html()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path.path == "/cloud":
            self.send_response(302)
            self.send_header("Location", "/cloud/")
            self.end_headers()
            return
        if path.path == "/cloud/":
            body = _cloud_monitor_html()
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
        if path.path == "/api/audience_report":
            query = urllib.parse.parse_qs(path.query)
            _json(self, _audience_report_payload(query.get("project", ["assistant"])[0]))
            return
        if path.path == "/api/cloud_servers":
            _json(self, {"ok": True, **_cloud_server_statuses()})
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
            _json(self, _public_job(JOBS.get(job_id)))
            return
        if path.path == "/api/jobs":
            _json(self, {"ok": True, "jobs": _public_jobs()})
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
            try:
                _json(self, {"ok": True, **_save_public_settings(payload)})
            except Exception as exc:
                _json(self, {"ok": False, "error": _safe_error(exc)}, 400)
            return
        if path.path == "/api/apps":
            length = int(self.headers.get("Content-Length", "0") or 0)
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            try:
                _json(self, {"ok": True, **_control_app(payload)})
            except Exception as exc:
                _json(self, {"ok": False, "error": _safe_error(exc), **_app_statuses()}, 400)
            return
        if path.path == "/api/cloud_servers":
            length = int(self.headers.get("Content-Length", "0") or 0)
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            try:
                _json(self, {"ok": True, **_control_cloud_monitor(payload)})
            except Exception as exc:
                _json(self, {"ok": False, "error": _safe_error(exc), **_cloud_server_statuses()}, 400)
            return
        if path.path == "/api/test_model":
            length = int(self.headers.get("Content-Length", "0") or 0)
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            result = _test_model_detailed(str(payload.get("provider") or ""), payload)
            extra: dict[str, Any] = {}
            if payload.get("connection_id"):
                extra["model_connection_library"] = _record_connection_test_result(str(payload.get("connection_id") or ""), result)
            _json(self, {"ok": True, **_public_settings(), "result": result, **extra})
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
                elif action == "test_library":
                    _json(self, {"ok": True, **_test_model_library_connections(), **_public_settings()})
                elif action == "dedupe":
                    _json(self, {"ok": True, "model_connection_library": _dedupe_model_connection_library(), **_public_settings()})
                elif action == "repair_keys":
                    report = _repair_missing_connection_keys_from_feishu()
                    _json(self, {"ok": bool(report.get("ok")), "key_repair_report": report, **_public_settings()})
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
                models = _models_with_url_defaults(_apply_business_steps_to_models(_apply_connection_library_to_defaults(mark_changed=True)))
                cmd, cwd = _build_command(payload)
            except Exception as exc:
                _json(self, {"ok": False, "error": _safe_error(exc)}, 400)
                return
            job_id = _new_job_id()
            snapshot_path = _write_job_model_snapshot(job_id, models)
            mode_key = str(payload.get("mode") or "")
            action_key = str(payload.get("action") or payload.get("stage") or "")
            base_key = f"{mode_key}:{action_key}" if mode_key in {"research", "culture"} and action_key else mode_key
            if mode_key == "auto_clip":
                base_key = "clip"
            elif mode_key == "bgm":
                base_key = "bgm"
            elif mode_key == "tool":
                base_key = f"tool:{action_key}" if action_key else "tool"
            now_ms = int(time.time() * 1000)
            JOBS[job_id] = {"job_id": job_id, "id": job_id, "label": base_key or "任务", "base_key": base_key, "kind": mode_key, "mode": mode_key, "action": action_key, "payload": _safe_job_payload(payload), "status": "starting", "cmd": cmd, "cwd": str(cwd), "lines": [], "exit_code": None, "output_dir": _default_output_dir(payload), "started_at": now_ms, "updated_at": now_ms, "model_snapshot": models, "model_snapshot_path": str(snapshot_path)}
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
            result = _stop_job_record(job_id)
            _json(self, result, 200 if result.get("ok") else 404)
            return
        if path.path == "/api/job_delete":
            job_id = urllib.parse.parse_qs(path.query).get("id", [""])[0]
            _json(self, _delete_job_record(job_id))
            return
        _json(self, {"error": "not found"}, 404)

    def log_message(self, format: str, *args: Any) -> None:
        return


def main(argv: list[str] | None = None) -> None:
    args = argv or sys.argv[1:] or ["8765"]
    port = int(args[0])
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"XGN Assistant Web: {url}", flush=True)
    if len(args) <= 1:
        webbrowser.open(url)
    server.serve_forever()


if __name__ == "__main__":
    main()

