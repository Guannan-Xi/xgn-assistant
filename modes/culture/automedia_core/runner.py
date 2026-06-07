from __future__ import annotations

import argparse
import base64
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .postprocess_cards import create_cover_and_endcards, guess_author_from_filename, normalize_book_title, clean_prefix
from .split_assets import split_episode_scripts_and_images

try:
    from pypdf import PdfReader, PdfWriter
except Exception:  # pragma: no cover - handled at runtime
    PdfReader = None
    PdfWriter = None

try:
    import pymupdf4llm  # type: ignore
    PYMU_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency
    pymupdf4llm = None
    PYMU_AVAILABLE = False


# =========================
# File and text utilities
# =========================

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROMPTS_DIR = PROJECT_ROOT / "prompts"
CONFIG_DIR = PROJECT_ROOT / "config"


def default_output_dir_for_book(book: Path) -> Path:
    """Default output directory: next to the source PDF, under short video assets."""
    book_path = Path(book).expanduser()
    book_dir_name = book_path.stem.strip().rstrip(".") or "未命名书籍"
    return (book_path.parent / "短视频素材" / book_dir_name).resolve()
OUTLINE_PROMPT_PATH = PROMPTS_DIR / "01_大纲生成提示词.md"
EPISODE_PROMPT_BUILDER_PATH = PROMPTS_DIR / "02_脚本生成提示词.md"
SCRIPT_JSON_REQUIREMENT_PATH = PROMPTS_DIR / "03_脚本生成_JSON规范.md"
VOICEOVER_POLISH_PROMPT_PATH = PROMPTS_DIR / "04_台词润色提示词.md"
AC_MASTER_PROMPT_PATH = PROMPTS_DIR / "10_封面母图提示词.md"
DETERMINISTIC_EPISODE_PROMPT_PATH = PROMPTS_DIR / "14_本地确定性脚本提示词模板.md"
GENERATION_RULES_PATH = CONFIG_DIR / "生成规则配置.json"
COPYWRITING_CONFIG_PATH = CONFIG_DIR / "文案风格配置.json"

DEFAULT_GEMINI_FAST_MODEL = "gemini-3-flash-preview"
DEFAULT_GEMINI_PRO_MODEL = "gemini-3.1-pro-preview"
DEFAULT_GEMINI_IMAGE_MODEL = "gemini-3-pro-image-preview"
GEMINI_IMAGE_MODEL_ALIASES = {
    "gemini-2.0-flash-preview-image-generation": DEFAULT_GEMINI_IMAGE_MODEL,
    "gemini-2.5-flash-image-preview": DEFAULT_GEMINI_IMAGE_MODEL,
    "gemini-3-pro-image": "gemini-3-pro-image-preview",
    "gemini-3.1-flash-image": "gemini-3.1-flash-image-preview",
}
GEMINI_TEXT_MODEL_OPTIONS = [
    "gemini-3.1-pro-preview",
    "gemini-3-pro-preview",
    "gemini-3-flash-preview",
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
]

# Friendly aliases / fallbacks for model names that users may type from public
# model labels. The API sometimes requires the exact preview suffix.
GEMINI_MODEL_FALLBACKS = {
    "gemini-3.1-pro": ["gemini-3.1-pro-preview", "gemini-3-flash-preview"],
    "gemini-3-pro-preview": ["gemini-3-flash-preview", "gemini-2.5-flash"],
    "gemini-3-flash": ["gemini-3-flash-preview", "gemini-2.5-flash"],
}

# Hard alias repair: these public/short labels are convenient in the UI or old settings,
# but some Gemini API versions only accept the preview-suffixed model code.
# We normalize before calling the API, so old gui_settings.json cannot break outline again.
GEMINI_MODEL_ALIASES = {
    "gemini-3.1-pro": "gemini-3.1-pro-preview",
}
# 脚本生成默认使用清单内的 GPT-5.5；分集提示词内部阶段跟随脚本模型。
DEFAULT_OPENAI_TEXT_MODEL = "gpt-5.5"
DEFAULT_OPENAI_PRO_MODEL = "gpt-5.5"
OPENAI_TEXT_MODEL_OPTIONS = [
    "gpt-5.5",
    "gpt-5.5-openai-compact",
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5.4-openai-compact",
    "gpt-5.3-codex",
    "gpt-5.3-codex-spark",
    "gpt-5.2",
    "codex-auto-review",
    "claude-haiku-4-5-20251001",
    "claude-sonnet-4-6",
    "claude-opus-4-6",
    "claude-opus-4-7",
    "claude-opus-4-8",
]

OPENAI_IMAGE_MODEL_OPTIONS = [
    "gpt-image-2",
    "gemini-3-pro-image-preview",
    "gemini-3.1-flash-image-preview",
]
DEFAULT_OPENAI_IMAGE_MODEL = "gpt-image-2"
LOW_COST_OPENAI_IMAGE_MODEL = "gpt-image-2"

DEFAULT_DOUBAO_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
DOUBAO_ENDPOINT_FILE_NAMES = ["ark_endpoint_id.txt", "doubao_endpoint_id.txt", "ark_model.txt", "doubao_model.txt"]
DOUBAO_TEXT_MODEL_OPTIONS = [
    "",  # 留空时读取环境变量或本地接入点文件；也可手动填写 ep-xxx。
    "ep-请填写推理接入点ID",
    "doubao-seed-2-0-lite-260215",
]



DEEPSEEK_DEFAULT_MODEL = "deepseek-v4-pro"
DEEPSEEK_TEXT_MODEL_OPTIONS = [
    "deepseek-v4-pro",
    "deepseek-chat",
    "deepseek-reasoner",
]
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_FOREIGN_MODEL_BASE_URL = "https://greatwalllink.top/v1"


def foreign_model_base_url() -> str:
    base_url = (
        os.getenv("NEWAPI_BASE_URL", "")
        or os.getenv("FOREIGN_MODEL_BASE_URL", "")
        or DEFAULT_FOREIGN_MODEL_BASE_URL
    ).rstrip("/")
    base_url = base_url.replace("greatwallink.top", "greatwalllink.top")
    if not base_url.endswith("/v1"):
        base_url = base_url.rstrip("/") + "/v1"
    return base_url


def deepseek_base_url() -> str:
    return (os.getenv("DEEPSEEK_BASE_URL", "") or DEFAULT_DEEPSEEK_BASE_URL).rstrip("/")


def openai_compatible_client(api_key: str, *, base_url: str, timeout: int | float, max_retries: int | None = None):
    """Create an OpenAI-compatible client without inheriting system proxies."""
    from openai import OpenAI

    kwargs: dict[str, Any] = {"api_key": api_key, "base_url": base_url, "timeout": timeout}
    if max_retries is not None:
        kwargs["max_retries"] = max(0, int(max_retries))
    try:
        import httpx

        kwargs["http_client"] = httpx.Client(trust_env=False, timeout=timeout)
    except Exception:
        pass
    try:
        return OpenAI(**kwargs)
    except TypeError:
        kwargs.pop("http_client", None)
        return OpenAI(**kwargs)


def extract_chat_content(response: Any) -> str:
    if isinstance(response, str):
        return response.strip()
    direct = getattr(response, "output_text", "") or ""
    if str(direct).strip():
        return str(direct).strip()
    try:
        output = getattr(response, "output", []) or []
        parts: list[str] = []
        for item in output:
            for content in getattr(item, "content", []) or []:
                value = getattr(content, "text", None)
                if value:
                    parts.append(str(value))
        if parts:
            return "\n".join(parts).strip()
    except Exception:
        pass
    try:
        return str((response.choices[0].message.content or "")).strip()
    except Exception:
        pass
    if isinstance(response, dict):
        try:
            return str((((response.get("choices") or [{}])[0].get("message") or {}).get("content") or "")).strip()
        except Exception:
            return ""
    return ""


def requests_post_no_proxy(url: str, **kwargs: Any):
    """POST without HTTP_PROXY/HTTPS_PROXY environment fallback."""
    import requests

    session = requests.Session()
    session.trust_env = False
    try:
        return session.post(url, **kwargs)
    finally:
        session.close()


def doubao_model_looks_like_api_key(value: str) -> bool:
    model = str(value or "").strip()
    if not model:
        return False
    if model.startswith(("ep-", "doubao-")):
        return False
    return bool(re.match(r"^(ark-|sk-|AK[A-Za-z0-9_-]{12,})", model))


def doubao_saved_endpoint() -> str:
    """Read a saved Doubao/Ark endpoint ID or directly callable model ID.

    The value is not an API secret, so the GUI may persist it in gui_settings.json
    and also in a small txt file for CLI/automation reuse.
    """
    for name in DOUBAO_ENDPOINT_FILE_NAMES:
        value = read_text(PROJECT_ROOT / name).strip()
        if value:
            return value
    return ""


def doubao_env_model() -> str:
    return (
        os.getenv("ARK_ENDPOINT_ID", "")
        or os.getenv("DOUBAO_ENDPOINT_ID", "")
        or os.getenv("ARK_MODEL", "")
        or os.getenv("DOUBAO_MODEL", "")
        or doubao_saved_endpoint()
    ).strip()


class PipelineCancelled(RuntimeError):
    """Raised when the user requests a safe stop from the GUI."""


def check_cancelled(stop_event=None) -> None:
    if stop_event is not None and getattr(stop_event, "is_set", lambda: False)():
        raise PipelineCancelled("用户已停止任务。")


_LOG_HANDLER = None


def set_log_handler(handler) -> None:
    """Set an optional log handler used by the GUI. Pass None to restore stdout logging."""
    global _LOG_HANDLER
    _LOG_HANDLER = handler


def log(message: str) -> None:
    if _LOG_HANDLER is not None:
        try:
            _LOG_HANDLER(str(message))
            return
        except Exception:
            pass
    try:
        print(message, flush=True)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        safe_message = str(message).encode(encoding, errors="replace").decode(encoding, errors="replace")
        print(safe_message, flush=True)


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name, "")
    if not value:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _approx_token_count(text: str) -> int:
    """CJK-friendly rough estimate for cost visibility only."""
    value = str(text or "")
    if not value:
        return 0
    cjk = len(re.findall(r"[\u4e00-\u9fff]", value))
    other = max(0, len(value) - cjk)
    return int(cjk * 1.15 + other / 4)


def _int_env(name: str, default: int) -> int:
    try:
        value = os.getenv(name, "").strip()
        return int(value) if value else int(default)
    except Exception:
        return int(default)


def _task_context_char_budget(task_name: str = "text") -> int:
    """Max local PDF/Markdown characters sent per text call.

    The raw parser cache may be larger, but prompt construction caps context so a
    single GPT call cannot unexpectedly consume a whole-book sized prompt.
    Override with environment variables when you intentionally want more context.
    """
    task = str(task_name or "text").lower()
    if task == "outline":
        return _int_env("AMP_MAX_OUTLINE_CONTEXT_CHARS", _int_env("AMP_MAX_CONTEXT_CHARS", 90_000))
    if task.startswith("script"):
        return _int_env("AMP_MAX_SCRIPT_CONTEXT_CHARS", _int_env("AMP_MAX_CONTEXT_CHARS", 48_000))
    if task.startswith("polish"):
        return _int_env("AMP_MAX_POLISH_CONTEXT_CHARS", 24_000)
    return _int_env("AMP_MAX_CONTEXT_CHARS", 48_000)


def strip_non_story_markdown(text: str) -> str:
    """Remove non-narrative material before sending chapter text to an LLM.

    Keeps the book's main argument and narrative, but removes token-heavy parts
    that do not help script writing: notes, references, bibliography, omitted
    image markers, markdown images, and inline footnote markers.
    """
    value = str(text or "")
    if not value.strip():
        return ""

    # Drop everything after common notes / bibliography headings. In books like
    # 《万历十五年》, the annotation section can be very long and consumes tokens
    # without helping the episode narration.
    cut_patterns = [
        r"【\s*注释\s*】",
        r"^\s*#{1,6}\s*注释\b",
        r"^\s*注释\s*$",
        r"【\s*参考文献\s*】",
        r"^\s*#{1,6}\s*参考文献\b",
        r"^\s*参考文献\s*$",
        r"^\s*参考资料\s*$",
        r"^\s*References\s*$",
        r"^\s*Bibliography\s*$",
        r"^\s*Notes\s*$",
        r"^\s*【\s*注\s*】",
    ]
    cut_at: int | None = None
    for pat in cut_patterns:
        m = re.search(pat, value, flags=re.I | re.M)
        if m and (cut_at is None or m.start() < cut_at):
            cut_at = m.start()
    if cut_at is not None:
        value = value[:cut_at]

    # Remove parser/image noise.
    value = re.sub(r"\*\*==>\s*picture\s*\[[^\]]+\]\s*intentionally omitted\s*<==\*\*", "", value, flags=re.I)
    value = re.sub(r"==>\s*picture\s*\[[^\]]+\]\s*intentionally omitted\s*<==", "", value, flags=re.I)
    value = re.sub(r"<PARSED TEXT FOR PAGE:\s*[^>]+>", "", value, flags=re.I)
    value = re.sub(r"<IMAGE FOR PAGE:\s*[^>]+>.*?(?=<PARSED TEXT FOR PAGE:|\Z)", "", value, flags=re.I | re.S)
    value = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", value)
    value = re.sub(r"<image[^>]*>", "", value, flags=re.I)

    # Remove inline footnote/citation markers, not the narrative sentence.
    value = re.sub(r"\[\[\s*\d+\s*\]\]", "", value)
    value = re.sub(r"(?<!\w)\[\s*\d+\s*\](?!\w)", "", value)

    # Remove isolated footnote lines if any survived.
    lines: list[str] = []
    for line in value.splitlines():
        stripped = line.strip()
        if re.match(r"^\[\d+\]\s+", stripped):
            continue
        if re.match(r"^\d+\.\s*(参见|见|《|Taxation|History|Samedo|Gouveia|页|卷)", stripped, flags=re.I):
            continue
        # Short figure-only captions are usually not useful to narration.
        if stripped in {"张居正像", "正德皇帝像"}:
            continue
        lines.append(line)

    value = "\n".join(lines)
    value = re.sub(r"[ \t]{2,}", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value).strip()
    return value


def prepare_source_context_for_llm(text: str, *, max_chars: int, label: str = "本集章节正文") -> tuple[str, dict[str, Any]]:
    original = str(text or "")
    cleaned = strip_non_story_markdown(original) if _env_flag("AMP_STRIP_NON_STORY_SOURCE", True) else original
    compact = _compact_llm_context(cleaned, max_chars=max_chars, label=label)
    stats = {
        "original_chars": len(original),
        "cleaned_chars": len(cleaned),
        "sent_chars": len(compact),
        "removed_chars": max(0, len(original) - len(cleaned)),
        "approx_input_tokens_before_clean": _approx_token_count(original),
        "approx_input_tokens_after_clean": _approx_token_count(compact),
        "strip_non_story_source": _env_flag("AMP_STRIP_NON_STORY_SOURCE", True),
    }
    return compact, stats

def _compact_llm_context(text: str, *, max_chars: int = 48_000, label: str = "上下文") -> str:
    """Trim noisy local PDF markdown before sending it to a text model.

    This does not summarize or rewrite the source. It removes obvious markdown
    image noise and caps very long extracts. Keeping the head+tail usually
    preserves chapter start, headings and ending conclusions while cutting cost.
    """
    value = str(text or "")
    if not value.strip():
        return ""
    value = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", value)
    value = re.sub(r"<image[^>]*>", "", value, flags=re.I)
    value = re.sub(r"[ \t]{2,}", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value).strip()
    if max_chars > 0 and len(value) > max_chars:
        head = int(max_chars * 0.72)
        tail = max_chars - head
        value = (
            value[:head].rstrip()
            + f"\n\n【{label}因 token 成本保护被截断；如需更完整内容，请调高 AMP_MAX_CONTEXT_CHARS / AMP_MAX_SCRIPT_CONTEXT_CHARS】\n\n"
            + value[-tail:].lstrip()
        )
    return value


def _openai_output_budget(task_name: str) -> int | None:
    task = str(task_name or "text").lower()
    env_value = os.getenv("AMP_OPENAI_MAX_OUTPUT_TOKENS", "").strip()
    if env_value:
        try:
            return max(256, int(env_value))
        except Exception:
            pass
    if task == "outline":
        return _int_env("AMP_OPENAI_OUTLINE_MAX_OUTPUT_TOKENS", 4096)
    if task.startswith("episode_prompt"):
        return _int_env("AMP_OPENAI_EPISODE_PROMPT_MAX_OUTPUT_TOKENS", 4096)
    if task.startswith("script"):
        return _int_env("AMP_OPENAI_SCRIPT_MAX_OUTPUT_TOKENS", 24576)
    if task.startswith("polish"):
        return _int_env("AMP_OPENAI_POLISH_MAX_OUTPUT_TOKENS", 8192)
    if task.startswith("split_") or task in {"book_final_summary", "split_transition"}:
        return _int_env("AMP_OPENAI_SMALL_TASK_MAX_OUTPUT_TOKENS", 1024)
    return _int_env("AMP_OPENAI_DEFAULT_MAX_OUTPUT_TOKENS", 4096)


def _model_is_expensive_openai(model: str) -> bool:
    value = str(model or "").lower()
    return "gpt-5.5" in value or value.endswith("-pro")


def read_text(path: Path, default: str = "") -> str:
    try:
        if path.exists():
            return path.read_text(encoding="utf-8")
    except Exception:
        return default
    return default


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text or "", encoding="utf-8")


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json_file(path: Path, default: Any = None) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default
    return default


def _merge_config(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge_config(result[key], value)
        else:
            result[key] = value
    return result


def default_generation_rules() -> dict[str, Any]:
    return {
        "version": 1,
        "说明": "大模型生成和自动绘图提示词的可调规则。程序只保留兜底默认值；常用策略请优先改这里，不要改 Python。",
        "script": {
            "compact_json_note": "\n\n【长章节 JSON 稳定性要求】\n1. 本阶段只生成 source_coverage_checklist 与 voiceover；image_prompts 必须输出空数组 []，不要生成每句绘图提示词。\n2. full_script 不要重复粘贴全部 voiceover；可以输出空字符串，程序会自动由 voiceover 合成完整脚本。\n3. 这样做不是压缩内容，而是避免 JSON 过大导致模型截断；原文覆盖必须体现在 voiceover 中。\n",
            "local_context_header": "以下是【本集切分 PDF】经过本地解析并清洗后的章节正文。已去除注释、参考文献、图片占位、脚注编号等非剧情内容。请只基于本集正文写脚本，不要使用整本书全文，不要凭空补充。\n\n【本集正文 Markdown（已去除注释/参考文献/图片占位）】\n{compact_context}",
            "coverage_repair_instruction": "【必须重写：原文覆盖不足】\n上一版脚本未通过覆盖检查：{reason}。\n本集来源页数约 {pages} 页，B系正文不得少于 {min_b} 句，建议达到 {target_b} 句左右；低于 {min_b} 句将被程序拒绝。请充分覆盖原文，不要压缩。后续会由分集拆分流程控制单条视频时长。\n请重新通读本集 Markdown，先按原文顺序列出 14～24 个 source_coverage_checklist 要点，再把这些要点充分展开成 B 系正文。\n重点：按原文逻辑讲清关键事件、人物关系、制度背景、作者判断、重要转折、典型例证、因果链条和后续影响。\n不要只保留结论；必须保留能支撑结论的具体例子、人物行动、制度机制和转折过程。\n台词要更精彩：每个段落群都要有明确冲突、具体场景、追问或后果，但不得编造原文没有的细节。\n仍然只输出同一 JSON 结构，不要解释，不要 Markdown。\n",
            "coverage_retry_note": "【第 {round_no} 轮补救附加要求】\n当前最佳版本只有 {current_b} 条 B 系正文。请输出完整 JSON，不要只输出新增段落；B 系正文建议达到 {target_b} 条左右，并且必须覆盖原文中尚未展开的细节。\n",
        },
        "image_prompts": {
            "no_text_rule": "不要在画面中生成任何可识别文字、标题、书名、作者名、字幕、logo、水印、印章字或大段书法。",
            "a1_postprocess_constraint": " 额外要求：这张图是 A 系封面与 C 结尾页共用的竖版 9:16 母图；只生成背景和主体视觉，不要出现任何可识别文字、中文书法、标题、书名、作者名、logo、slogan、水印或印章文字；顶部 20% 留干净标题区，中部 45% 放核心视觉，底部 15% 预留品牌区；先判断书籍类型和本集主题，再决定场景、色调和视觉隐喻；不要默认昏暗、黑金暗红、史诗化、厚重历史感或纯氛围图；每个元素都要对应文稿中的人物、地点、物件、冲突、证据、选择或概念，适合后处理裁切成 A1/A2/A01/A02/C。",
            "general_postprocess_constraint": " 额外要求：不要在画面中生成任何可识别文字、水印或logo。",
            "a1_base": "竖版 9:16，无文字封面母图，{genre_label}读书解读首页背景，内容驱动的高质量插画。",
            "a1_template": "{base} 必须紧扣 A1 首页台词的中心内容：『{line}』。画面主题：{scene}。{style} 顶部约20%预留干净标题区，中部约45%放核心视觉，底部约15%预留品牌区；先按书籍类型选择视觉系统：历史用人物关系、空间压力和制度器物；社科/经济学用现实场景、家庭预算、市场、学校、诊所、公共服务窗口、田野调查和简洁数据结构；文学/哲学/心理用人物处境、光影、房间、道路和关键物件。{safety_rule}{no_text_rule} 不要写实照片质感、不要3D渲染、不要无关装饰。",
            "history_template": "竖屏 9:16，历史人文/经典读书解读短视频正文配图。必须直接表现本句台词的历史含义：『{line}』。画面主题：{scene}。只画这一句正在讲的内容，不要把上一句、下一句或整章摘要混进来；如果台词讲制度、矛盾、传言或原因，就用人物关系、空间距离、奏疏、宫门、书案、礼制器物等可视化表达，不要只给泛泛空镜。{style} 人物可用背影、侧影或群像，不要求写实还原具体长相；服饰、建筑、器物符合历史语境，禁止现代物品。{safety_rule}{no_text_rule}",
            "general_template": "竖屏 9:16，{genre_label}读书解读正文配图。必须直接表现本句台词正在讲的问题、证据、人物处境、概念或情节含义：『{line}』。画面主题：{scene}。只画这一句，不要混入上一句、下一句或整章摘要；如果台词包含具体案例，优先画案例里的具体人、地点、物件和对比关系，例如非洲家庭、蚊帐、疟疾防治、公益组织免费发放与家庭自费购买的差别，不要泛化成抽象贫困背景或空洞公共卫生场景；根据书籍类型选择现实场景、人物远景、关键物件、简洁图表、抽象隐喻或文学化空间。{style} 人物只用远景、背影、侧影或非特定群像，不描绘可识别真人；画面要尊重主题对象，不卖惨、不凝视、不刻板化；可使用抽象图表元素但不生成可读文字。{safety_rule}{no_text_rule}",
        },
    }


def load_generation_rules(create_if_missing: bool = True) -> dict[str, Any]:
    defaults = default_generation_rules()
    if create_if_missing and not GENERATION_RULES_PATH.exists():
        try:
            write_json(GENERATION_RULES_PATH, defaults)
        except Exception:
            pass
    raw = read_json_file(GENERATION_RULES_PATH, {})
    return _merge_config(defaults, raw if isinstance(raw, dict) else {})


def generation_rule(path: str, fallback: str = "") -> str:
    cur: Any = load_generation_rules(create_if_missing=True)
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return fallback
        cur = cur[part]
    return str(cur if cur is not None else fallback)


def copywriting_brand_texts() -> dict[str, str]:
    data = read_json_file(COPYWRITING_CONFIG_PATH, {})
    brand = data.get("brand") if isinstance(data.get("brand"), dict) else {}
    name = str(brand.get("name") or "知识慢炖").strip() or "知识慢炖"
    slogan = str(brand.get("slogan") or "让经典不再高冷，让智慧人人可用").strip()
    follow_sentence = str(brand.get("follow_sentence") or f"想读完整论证，可以看原书；也欢迎关注【{name}】，下一期继续讲。").strip()
    return {"brand_name": name, "brand_slogan": slogan, "follow_sentence": follow_sentence}


def safe_filename(value: str, fallback: str = "item", max_len: int = 90) -> str:
    text = str(value or "").strip()
    text = re.sub(r"[\\/:*?\"<>|\r\n\t]+", "_", text)
    text = re.sub(r"\s+", "_", text)
    text = text.strip("._ ")
    return (text[:max_len] or fallback).strip("._ ") or fallback


def _episode_no_from_dir_name(name: str) -> int | None:
    """Parse an existing episode folder by serial number only.

    Folder titles are generated from summaries and may vary between runs, so resume
    logic must match ``EP01_*`` by the numeric prefix instead of the subtitle body.
    """
    text = str(name or "").strip()
    m = re.match(r"^EP\s*0*(\d{1,4})(?:[_\-\s].*)?$", text, flags=re.I)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def _episode_no_from_existing_dir(path: Path) -> int | None:
    no = _episode_no_from_dir_name(Path(path).name)
    if no is not None:
        return no
    data = read_json_file(Path(path) / "00_本集大纲.json", default={}) or {}
    try:
        value = int(data.get("episode_no") or 0)
        return value if value > 0 else None
    except Exception:
        return None


def _episode_dir_reuse_priority(path: Path) -> tuple[int, float, str]:
    """Prefer folders that already contain later-stage results when duplicates exist."""
    path = Path(path)
    score = 0
    for rel in ["02_脚本.json", "03_台词.txt", "04_绘图提示词.json", "07_拆分脚本与配图/00_拆分索引.json"]:
        if (path / rel).exists():
            score += 1
    try:
        mtime = path.stat().st_mtime
    except Exception:
        mtime = 0.0
    return (-score, -mtime, path.name)


def find_existing_episode_dir_by_no(episodes_root: Path, episode_no: int) -> Path | None:
    """Find an existing EP folder by number, ignoring the generated subtitle.

    This prevents reruns from creating ``EP01_new-title`` beside
    ``EP01_old-title`` just because the summary/title changed.
    """
    root = Path(episodes_root)
    if not root.exists() or not root.is_dir():
        return None
    candidates: list[Path] = []
    for child in root.iterdir():
        if not child.is_dir():
            continue
        if _episode_no_from_existing_dir(child) == int(episode_no):
            candidates.append(child)
    if not candidates:
        return None
    return sorted(candidates, key=_episode_dir_reuse_priority)[0]


def fill_template(text: str, **kwargs: Any) -> str:
    result = str(text or "")
    for key, value in kwargs.items():
        result = result.replace("{" + str(key) + "}", str(value))
    return result




def default_image_size_for_id(image_id: str, shared_ac_source: str = "A1") -> str:
    """Return the image API request size with a lowest-cost default.

    gpt-image-2 only creates the low-cost 9:16 source images needed by the
    timeline. Final cover/video-homepage sizes, crops, text, logo and crispness
    are handled locally by Pillow, so A/C pages no longer need an oversized API
    render. Override AMP_IMAGE_COST_MODE=balanced or explicit size envs only
    when you intentionally want larger API images.
    """
    image_id = str(image_id or "").strip()
    shared_id = str(shared_ac_source or "A1").strip() or "A1"
    cost_mode = os.getenv("AMP_IMAGE_COST_MODE", "lowest").strip().lower()
    low_cost_size = os.getenv("AMP_LOW_COST_IMAGE_SIZE", "720x1280").strip() or "720x1280"
    if cost_mode in {"lowest", "low", "min", "minimum", "cheap"}:
        if image_id == shared_id:
            return os.getenv("AMP_SHARED_AC_IMAGE_SIZE", low_cost_size).strip() or low_cost_size
        if image_id.startswith("B"):
            return os.getenv("AMP_B_IMAGE_SIZE", low_cost_size).strip() or low_cost_size
        return os.getenv("AMP_IMAGE_SIZE", low_cost_size).strip() or low_cost_size
    if image_id == shared_id:
        return os.getenv("AMP_SHARED_AC_IMAGE_SIZE", "1080x1920").strip() or "1080x1920"
    if image_id.startswith("B"):
        return os.getenv("AMP_B_IMAGE_SIZE", "720x1280").strip() or "720x1280"
    return os.getenv("AMP_IMAGE_SIZE", "720x1280").strip() or "720x1280"


def default_image_quality() -> str:
    """Use the cheapest API quality by default; local postprocess restores crispness."""
    return os.getenv("AMP_IMAGE_QUALITY", "low").strip() or "low"


def normalize_openai_image_size_for_model(model: str, size: str | None) -> str:
    """Map internal video sizes to API-supported sizes for GPT Image models.

    gpt-image-2 supports flexible dimensions; earlier GPT Image models are kept on
    the common portrait/landscape/square sizes used by OpenAI docs.
    """
    model = str(model or "").strip()
    raw = str(size or "720x1280").strip() or "720x1280"
    if model == "gpt-image-2":
        return raw
    if model in {"gpt-image-1.5", "gpt-image-1", "gpt-image-1-mini"}:
        m = re.match(r"^(\d+)x(\d+)$", raw)
        if not m:
            return "1024x1536"
        w, h = int(m.group(1)), int(m.group(2))
        if abs(w - h) <= max(1, int(max(w, h) * 0.08)):
            return "1024x1024"
        return "1024x1536" if h >= w else "1536x1024"
    return raw




# =========================
# Image prompt safety guards
# =========================

_IMAGE_PROMPT_RISK_REPLACEMENTS: list[tuple[str, str]] = [
    (r"试马弄伤了?前额", "试马后以身体不适为由回避朝臣"),
    (r"弄伤了?前额", "身体不适"),
    (r"不慎抓破了?皮肤而行走不便", "因身体不适而行动不便"),
    (r"抓破了?皮肤而行走不便", "因身体不适而行动不便"),
    (r"抓破了?皮肤", "身体不适"),
    (r"抓破", "身体不适"),
    (r"伤口|创口|血迹|流血|出血|鲜血|淌血|血腥", "不适迹象"),
    (r"割腕|自残|自伤|自杀|自尽|自刎|上吊|投河|跳楼|服毒", "悲剧传闻"),
    (r"刀割|割开|刺入|砍下|砍头|处决特写", "危险冲突"),
    (r"疼痛特写|皮肤损伤特写|身体伤害细节", "身体不适的间接暗示"),
]

_IMAGE_PROMPT_RISK_KEYWORDS = (
    "试马弄伤", "弄伤", "抓破", "伤口", "血迹", "流血", "出血", "鲜血", "血腥",
    "割腕", "自残", "自伤", "自杀", "自尽", "自刎", "上吊", "投河", "跳楼", "服毒",
    "刀割", "刺入", "疼痛特写", "皮肤损伤", "身体伤害",
)


def _replace_image_prompt_risky_terms(value: str) -> str:
    text = str(value or "")
    for pattern, repl in _IMAGE_PROMPT_RISK_REPLACEMENTS:
        text = re.sub(pattern, repl, text)
    return text


def sanitize_image_prompt_for_safety(prompt: str, *, aggressive: bool = False) -> str:
    """Remove terms that commonly trigger image safety filters while preserving the line meaning.

    The script/voiceover may legitimately mention historical illness, rumors or injuries.  Image
    generation should visualize those ideas indirectly with palace doors, papers, medicine tables
    and distant figures, not with explicit physical-harm wording or close-ups.
    """
    original = str(prompt or "").strip()
    if not original:
        return original
    text = _replace_image_prompt_risky_terms(original)
    # When a prompt embeds the narration line inside 『...』, sanitize that quoted line too.
    text = re.sub(
        r"(本句台词|首页台词|A1 首页台词|分集 A1 首页台词|中心内容)：『(.*?)』",
        lambda m: f"{m.group(1)}：『{_replace_image_prompt_risky_terms(m.group(2))}』",
        text,
        flags=re.S,
    )
    safety_tail = "画面只用环境、物件、书桌、窗边、公共空间、抽象隐喻、人物远景或侧影来间接表达，不表现血腥、危险行为、医学细节或身体特写。"
    if any(k in original for k in _IMAGE_PROMPT_RISK_KEYWORDS) or any(k in text for k in _IMAGE_PROMPT_RISK_KEYWORDS) or aggressive:
        # Remove any remaining high-risk snippets after broad replacement.
        text = _replace_image_prompt_risky_terms(text)
        text = re.sub(r"不展示[^。；;]*?(伤|血|皮肤|疼痛)[^。；;]*[。；;]", "", text)
        text = re.sub(r"不出现[^。；;]*?(伤|血|皮肤|疼痛)[^。；;]*[。；;]", "", text)
        if safety_tail not in text:
            text = text.rstrip("。；; ") + "。" + safety_tail
    if aggressive:
        # Keep visual guidance but avoid sending the full original sentence if it still contains risk terms.
        text = _replace_image_prompt_risky_terms(text)
        if any(k in text for k in _IMAGE_PROMPT_RISK_KEYWORDS):
            text = (
                "竖屏 9:16，历史人文/经典读书解读短视频正文配图。"
                "以明代宫廷或内阁书房为场景，用半掩宫门、奏疏、药案、帘幕、烛光和人物远景表现朝廷传闻、身体不适与无法临朝造成的政治张力。"
                "色调由内容决定，可以使用自然光、古纸色、青绿、朱红、金色点缀或冷暖对比；画面沉稳克制但不默认昏暗，不生成任何可识别文字、标题、logo、水印。"
                "画面只做间接表达，不表现血腥、危险行为、医学细节或身体特写。"
            )
    return re.sub(r"\s+", " ", text).strip()


def image_prompt_moderation_blocked(exc: Exception) -> bool:
    text = str(exc or "").lower()
    return any(x in text for x in ["moderation_blocked", "safety_violations", "self-harm", "safety system"])


def _parse_image_size(size: str | None) -> tuple[int, int] | None:
    m = re.match(r"^\s*(\d{2,5})\s*x\s*(\d{2,5})\s*$", str(size or ""), flags=re.I)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def _crop_image_to_ratio(img: Any, ratio: tuple[int, int]) -> Any:
    """Center-crop an image to a target ratio without stretching it."""
    target_ratio = ratio[0] / ratio[1]
    w, h = img.size
    source_ratio = w / max(1, h)
    if abs(source_ratio - target_ratio) < 1e-6:
        return img.copy()
    if source_ratio > target_ratio:
        new_w = int(h * target_ratio)
        left = max(0, (w - new_w) // 2)
        return img.crop((left, 0, left + new_w, h))
    new_h = int(w / target_ratio)
    top = max(0, (h - new_h) // 2)
    return img.crop((0, top, w, top + new_h))


def _fit_generated_image_to_size(img: Any, target: tuple[int, int], resample: Any = None) -> Any:
    """Fit generated images to the requested output size by crop+resize, never by distortion."""
    target_w, target_h = target
    fitted = _crop_image_to_ratio(img, (target_w, target_h))
    if fitted.size != target:
        fitted = fitted.resize(target, resample) if resample is not None else fitted.resize(target)
    return fitted


def _enhance_generated_image_file(path: Path, requested_size: str | None = None) -> None:
    """Normalize generated image dimensions and improve crispness locally.

    Dimension normalization is always applied when requested_size is available,
    even when AMP_LOCAL_IMAGE_ENHANCE=0. That prevents reused or provider-returned
    3:4 images from leaking into B/A2/C 9:16 timeline outputs.
    """
    if not path.exists():
        return
    try:
        from PIL import Image, ImageEnhance, ImageFilter
        img = Image.open(path).convert("RGB")
        target = _parse_image_size(requested_size)
        changed = False
        if target and img.size != target:
            img = _fit_generated_image_to_size(img, target, Image.Resampling.LANCZOS)
            changed = True

        if os.getenv("AMP_LOCAL_IMAGE_ENHANCE", "1").strip().lower() in {"0", "false", "off", "no"}:
            if changed:
                path.parent.mkdir(parents=True, exist_ok=True)
                img.save(path, quality=96, optimize=True)
            return

        img = ImageEnhance.Contrast(img).enhance(float(os.getenv("AMP_LOCAL_CONTRAST", "1.04")))
        img = ImageEnhance.Sharpness(img).enhance(float(os.getenv("AMP_LOCAL_SHARPNESS", "1.18")))
        img = img.filter(ImageFilter.UnsharpMask(radius=1.15, percent=115, threshold=3))
        path.parent.mkdir(parents=True, exist_ok=True)
        img.save(path, quality=96, optimize=True)
    except Exception as exc:
        log(f"⚠️ 本地图片尺寸校正/增强失败，已保留原图：{exc}")

def image_cadence_note(interval_text: str = "3-8") -> str:
    cleaned = str(interval_text or "3-8").strip() or "3-8"
    upper = cleaned.split("-")[-1].strip() if "-" in cleaned else cleaned
    return (
        f"配图节奏要求：平均每 {cleaned} 秒至少对应 1 张图。"
        f"请把旁白与画面切得足够细，voiceover 与 image_prompts 的数量要基本对应；"
        f"若某句旁白明显超过 {upper} 秒，请主动拆成更短的旁白单元与画面单元。"
    )


def is_model_not_found_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return ("not_found" in text or "not found" in text or "404" in text) and "models/" in text


def canonical_gemini_model(model: str) -> str:
    model = (model or "").strip()
    return GEMINI_MODEL_ALIASES.get(model, model)


def canonical_gemini_image_model(model: str) -> str:
    model = (model or "").strip()
    return GEMINI_IMAGE_MODEL_ALIASES.get(model, model)


def _extract_gemini_inline_image_b64(data: Any) -> str:
    if isinstance(data, dict):
        inline = data.get("inlineData") or data.get("inline_data")
        if isinstance(inline, dict):
            value = inline.get("data") or inline.get("b64_json") or inline.get("base64")
            if value:
                return str(value).split(",", 1)[-1].strip()
        for key in ("data", "b64_json", "base64", "image_base64"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.split(",", 1)[-1].strip()
        for value in data.values():
            found = _extract_gemini_inline_image_b64(value)
            if found:
                return found
    if isinstance(data, list):
        for value in data:
            found = _extract_gemini_inline_image_b64(value)
            if found:
                return found
    return ""


def model_candidates(model: str, fallbacks: dict[str, list[str]], default_model: str) -> list[str]:
    requested = (model or default_model or "").strip()
    first = canonical_gemini_model(requested) or default_model
    candidates: list[str] = []
    for item in [first, *fallbacks.get(requested, []), *fallbacks.get(first, []), default_model]:
        item = canonical_gemini_model((item or "").strip())
        if item and item not in candidates:
            candidates.append(item)
    return candidates


def strip_code_fence(text: str) -> str:
    s = str(text or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json|JSON|markdown|md|text)?\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    return s.strip()



def looks_like_sdk_response_dump(text: str) -> bool:
    """Detect accidental serialization of SDK Response objects.

    If OpenAI returns an incomplete Responses API object with no text, the SDK
    object's repr can look like ``Response(id='...', incomplete_details=...)``.
    That is never valid narration or JSON and must not be saved as B01.
    """
    value = str(text or "").strip()
    if not value:
        return False
    bad_markers = [
        "Response(id=",
        "ResponseReasoningItem(",
        "IncompleteDetails(",
        "reasoning_tokens=",
        "text=ResponseTextConfig(",
        "object='response'",
    ]
    return any(marker in value for marker in bad_markers)


def assert_not_sdk_response_dump(text: str, task_name: str = "模型调用") -> None:
    if looks_like_sdk_response_dump(text):
        raise RuntimeError(
            f"{task_name} 返回的是 SDK Response 对象/不完整响应，而不是正文文本。"
            "常见原因是 max_output_tokens 被 reasoning_tokens 耗尽，或模型返回 status=incomplete。"
            "已阻止把 Response(id=...) 写入台词；请降低 OpenAI reasoning effort，或增大 AMP_OPENAI_SCRIPT_MAX_OUTPUT_TOKENS 后重试。"
        )


def parse_json_loose(text: str) -> Any:
    """Parse model JSON. Accepts fenced JSON or text containing one JSON object."""
    s = strip_code_fence(text)
    try:
        return json.loads(s)
    except Exception:
        pass

    match = re.search(r"(\{[\s\S]*\})", s)
    if match:
        try:
            return json.loads(match.group(1))
        except Exception:
            pass

    match = re.search(r"(\[[\s\S]*\])", s)
    if match:
        try:
            return json.loads(match.group(1))
        except Exception:
            pass

    raise ValueError("模型返回内容不是可解析 JSON。请查看 raw_*.txt 文件。")


def ascii_safe_pdf_copy(pdf_path: Path) -> tuple[Path, tempfile.TemporaryDirectory | None]:
    """Return an ASCII-only temporary copy for SDKs that cannot upload Chinese paths.

    Some Windows SDK/file-upload stacks still try to encode multipart filenames as ASCII.
    A source path containing Chinese characters can then fail before the request is sent.
    This helper leaves the original PDF untouched and gives the SDK a short ASCII filename.
    """
    original = Path(pdf_path)
    try:
        str(original).encode("ascii")
        original.name.encode("ascii")
        return original, None
    except UnicodeEncodeError:
        tmp = tempfile.TemporaryDirectory(prefix="amp_pdf_upload_")
        safe_path = Path(tmp.name) / "book.pdf"
        shutil.copy2(original, safe_path)
        return safe_path, tmp


class ProgressFileReader(io.IOBase):
    """File-like wrapper that logs upload progress while an SDK reads bytes."""

    def __init__(self, path: Path, *, label: str = "PDF upload") -> None:
        self.path = Path(path)
        self.label = label
        self.total = max(1, self.path.stat().st_size)
        self.sent = 0
        self._fh = open(self.path, "rb")
        self._last_bucket = -1
        self._last_log_at = 0.0

    def read(self, size: int = -1) -> bytes:
        data = self._fh.read(size)
        if data:
            self.sent += len(data)
            self._log_progress()
        return data

    def seek(self, offset: int, whence: int = 0) -> int:
        pos = self._fh.seek(offset, whence)
        if whence == 0:
            self.sent = max(0, pos)
        return pos

    def tell(self) -> int:
        return self._fh.tell()

    @property
    def name(self) -> str:
        return str(self.path)

    def close(self) -> None:
        self._fh.close()

    def __enter__(self) -> "ProgressFileReader":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _log_progress(self) -> None:
        percent = min(100, int(self.sent * 100 / self.total))
        bucket = percent // 10
        now = time.monotonic()
        if bucket != self._last_bucket or now - self._last_log_at >= 5:
            self._last_bucket = bucket
            self._last_log_at = now
            log(f"  {self.label}: {percent}% ({self.sent / 1024 / 1024:.1f}/{self.total / 1024 / 1024:.1f} MB)")


def read_api_key(provider: str, explicit: str = "") -> str:
    if explicit:
        return explicit.strip()
    provider = provider.lower().strip()
    env_names = {
        "openai": ["OPENAI_API_KEY"],
        "image": ["IMAGE_API_KEY", "OPENAI_IMAGE_API_KEY"],
        "gemini": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
        "deepseek": ["DEEPSEEK_API_KEY"],
        "doubao": ["ARK_API_KEY", "DOUBAO_API_KEY", "VOLCENGINE_ARK_API_KEY"],
    }.get(provider, [])
    for name in env_names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    file_names = {
        "openai": ["openai_api_key.txt"],
        "image": ["image_api_key.txt", "openai_image_api_key.txt"],
        "gemini": ["gemini_api_key.txt", "google_api_key.txt"],
        "deepseek": ["deepseek_api_key.txt"],
        "doubao": ["ark_api_key.txt", "doubao_api_key.txt"],
    }.get(provider, [])
    for name in file_names:
        value = read_text(PROJECT_ROOT / name).strip()
        if value:
            return value
    return ""


# =========================
# PDF utilities
# =========================


def ensure_pypdf() -> None:
    if PdfReader is None or PdfWriter is None:
        raise RuntimeError("缺少 pypdf。请先运行：pip install -r requirements.txt")


def count_pdf_pages(pdf_path: Path) -> int:
    ensure_pypdf()
    reader = PdfReader(str(pdf_path))
    return len(reader.pages)


def is_image_only_pdf(pdf_path: Path, *, sample_pages: int = 5) -> bool:
    """Fast probe for scanned/image-only PDFs; avoids slow local OCR/PyMuPDF4LLM."""
    try:
        import fitz  # type: ignore

        doc = fitz.open(str(pdf_path))
        if doc.page_count <= 0:
            return False
        limit = min(max(1, sample_pages), doc.page_count)
        image_pages = 0
        text_chars = 0
        for idx in range(limit):
            page = doc.load_page(idx)
            text_chars += len((page.get_text("text") or "").strip())
            if page.get_images(full=True):
                image_pages += 1
        return text_chars < 50 and image_pages >= max(1, limit - 1)
    except Exception:
        return False


def _decode_process_output(data: bytes | str) -> str:
    if isinstance(data, str):
        return data
    for encoding in ("utf-8", "gbk", "cp936"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _pymupdf4llm_to_markdown_isolated(pdf_path: Path, *, timeout: int = 900) -> str:
    """Run PyMuPDF4LLM outside the GUI worker process so codec noise cannot kill reader threads."""
    with tempfile.TemporaryDirectory(prefix="pymupdf4llm_") as temp_dir:
        out_path = Path(temp_dir) / "parsed.md"
        script = (
            "from pathlib import Path\n"
            "import sys\n"
            "import pymupdf4llm\n"
            "pdf_path = sys.argv[1]\n"
            "out_path = Path(sys.argv[2])\n"
            "text = pymupdf4llm.to_markdown(pdf_path) or ''\n"
            "out_path.write_text(text, encoding='utf-8', errors='ignore')\n"
        )
        env = os.environ.copy()
        env.setdefault("PYTHONIOENCODING", "utf-8")
        env.setdefault("PYTHONUTF8", "1")
        completed = subprocess.run(
            [sys.executable, "-c", script, str(pdf_path), str(out_path)],
            cwd=str(PROJECT_ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
        if completed.returncode != 0:
            stderr = _decode_process_output(completed.stderr).strip()
            stdout = _decode_process_output(completed.stdout).strip()
            detail = stderr or stdout or f"exit code {completed.returncode}"
            raise RuntimeError(detail[:800])
        if not out_path.exists():
            stderr = _decode_process_output(completed.stderr).strip()
            raise RuntimeError((stderr or "PyMuPDF4LLM did not write parsed markdown")[:800])
        return out_path.read_text(encoding="utf-8", errors="replace")


def extract_pdf_text(pdf_path: Path, max_chars: int = 180_000, use_mineru: bool = False) -> str:
    """Simple, stable local PDF parsing.

    Priority:
    1. PyMuPDF4LLM -> high-quality Markdown, no GPU, no subprocess.
    2. pypdf -> final lightweight fallback with [PDF Page N] anchors.

    The `use_mineru` argument is accepted only for backward compatibility and is ignored.
    """
    if PYMU_AVAILABLE and pymupdf4llm is not None:
        try:
            log(f"📄 使用 PyMuPDF4LLM 解析：{pdf_path.name}")
            md_text = _pymupdf4llm_to_markdown_isolated(pdf_path) or ""
            min_chars = int(os.environ.get("AMP_PYMUPDF4LLM_MIN_CHARS", "500") or 500)
            if len(md_text.strip()) >= min_chars:
                result = f"[PyMuPDF4LLM Markdown解析]\n{md_text[:max_chars]}"
                if len(md_text) > max_chars:
                    result += "\n\n[截断提示] PyMuPDF4LLM 解析结果过长，后续内容未放入本次上下文。"
                log(f"✅ PyMuPDF4LLM 解析完成 → {len(md_text):,} 字符")
                return result
            if md_text.strip():
                log(f"⚠️ PyMuPDF4LLM 返回内容过短（{len(md_text.strip())} 字符），回退 pypdf。")
            else:
                log("⚠️ PyMuPDF4LLM 返回为空，回退 pypdf。")
        except Exception as exc:
            log(f"⚠️ PyMuPDF4LLM 异常（回退 pypdf）：{exc}")

    ensure_pypdf()
    reader = PdfReader(str(pdf_path))
    chunks: list[str] = []
    total = 0
    for idx, page in enumerate(reader.pages, start=1):
        try:
            page_text = page.extract_text() or ""
        except Exception:
            page_text = ""
        page_text = page_text.strip()
        if page_text:
            block = f"\n\n[PDF Page {idx}]\n{page_text}"
            chunks.append(block)
            total += len(block)
        if total >= max_chars:
            chunks.append("\n\n[截断提示] PDF 文本过长，后续内容未放入本次文本 fallback。")
            break
    return "".join(chunks).strip()


def _pdf_text_is_usable_for_outline(text: str) -> bool:
    stripped = re.sub(r"\s+", "", str(text or ""))
    min_chars = _int_env("AMP_MIN_USABLE_PDF_TEXT_CHARS", 3000)
    if len(stripped) < min_chars:
        return False
    metadata_markers = ["GeneralInformation", "书名=", "作者", "页数=", "出版社", "出版日期", "SS号", "DX号"]
    marker_hits = sum(1 for marker in metadata_markers if marker in stripped)
    page_count = len(re.findall(r"\[PDF Page \d+\]", str(text or "")))
    if marker_hits >= 4 and page_count <= 2:
        return False
    return True


def _find_existing_outline_near_output(out_dir: Path) -> Path | None:
    names = ["00_分集解读大纲.json"]
    roots = [
        out_dir,
        out_dir / "短视频素材",
        out_dir / "outputs",
        out_dir / "output",
    ]
    for root in roots:
        for name in names:
            path = root / name
            if path.exists():
                data = read_json_file(path, {})
                if isinstance(data, dict) and data.get("episodes"):
                    return path
    try:
        for path in out_dir.glob("*/00_分集解读大纲.json"):
            data = read_json_file(path, {})
            if isinstance(data, dict) and data.get("episodes"):
                return path
    except Exception:
        return None
    return None


def assert_usable_pdf_text(text: str, pdf_path: Path, source: str) -> None:
    if _pdf_text_is_usable_for_outline(text):
        return
    nonspace_chars = len(re.sub(r"\s+", "", str(text or "")))
    raise RuntimeError(
        f"{source} 只提取到 {nonspace_chars} 个非空白字符，不足以生成分集大纲。"
        f"这本 PDF 很可能是扫描/图片版或文字层损坏：{pdf_path}。"
        "请先做 OCR，或换成可复制文字的 PDF / 手动提供已有大纲 JSON。"
    )


def build_pdf_text_fallback_prompt(prompt: str, pdf_path: Path, *, max_chars: int = 180_000) -> str:
    extracted = extract_pdf_text(pdf_path, max_chars=max_chars)
    assert_usable_pdf_text(extracted, pdf_path, "pypdf text extraction")
    prefix = "PyMuPDF4LLM Markdown" if "PyMuPDF4LLM" in extracted else "pypdf text extraction"
    return f"{prompt}\n\nThe following content was extracted with {prefix} and keeps page markers:\n{extracted}"


# =========================
# Local PDF parsing: PyMuPDF4LLM first, upload PDF only if local parsing fails
# =========================

PDF_PARSE_MODE_OPTIONS = ["auto", "pymupdf4llm"]
DEFAULT_LOCAL_PDF_PARSER = "pymupdf4llm"

# Backward-compatible aliases for older GUI/settings code.
MINERU_MODE_OPTIONS = PDF_PARSE_MODE_OPTIONS
DEFAULT_MINERU_BACKEND = DEFAULT_LOCAL_PDF_PARSER
DEFAULT_MINERU_API_URL = ""


def short_hash_text(text: str) -> str:
    import hashlib
    return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()[:16]


def local_parse_cache_key(pdf_path: Path, parser: str, mode: str) -> str:
    try:
        stat = pdf_path.stat()
        raw = f"{pdf_path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}|{parser}|{mode}"
    except Exception:
        raw = f"{pdf_path}|{parser}|{mode}"
    return short_hash_text(raw)


def try_local_pdf_parse(pdf_path: Path, *, mode: str = "auto", parser: str = DEFAULT_LOCAL_PDF_PARSER, cache_dir: Path | None = None, max_chars: int = 120_000) -> str:
    mode = (mode or "auto").strip().lower()
    if mode in {"", "none", "off", "disabled", "false", "0"}:
        raise RuntimeError("本地解析已关闭。")
    parser = (parser or DEFAULT_LOCAL_PDF_PARSER).strip().lower()
    if mode not in {"auto", "pymupdf4llm"}:
        raise RuntimeError(f"未知本地解析模式：{mode}。请使用 auto/pymupdf4llm/off。")
    if parser not in {"pymupdf4llm", "auto"}:
        # Older settings may contain vlm/pipeline/hybrid from MinerU; silently normalize.
        parser = DEFAULT_LOCAL_PDF_PARSER

    cache_root = Path(cache_dir) if cache_dir else (PROJECT_ROOT / ".pymupdf4llm_cache")
    key = local_parse_cache_key(pdf_path, parser, mode)
    output_dir = cache_root / key
    cached = output_dir / "pymupdf4llm_parsed_context.txt"
    if cached.exists():
        text = read_text(cached).strip()
        if text:
            assert_usable_pdf_text(text, pdf_path, "cached PDF text")
            log(f"  ✅ 使用 PyMuPDF4LLM 缓存：{cached}")
            return text

    output_dir.mkdir(parents=True, exist_ok=True)
    parsed = extract_pdf_text(pdf_path, max_chars=max_chars)
    if not parsed.strip():
        raise RuntimeError("本地 PDF 解析未返回可用内容。")
    assert_usable_pdf_text(parsed, pdf_path, "local PDF parsing")
    write_text(output_dir / "pymupdf4llm_parsed_context.txt", parsed)
    return parsed



def paddle_ocr_cache_key(pdf_path: Path, mode: str = "ppstructurev3") -> str:
    try:
        stat = pdf_path.stat()
        raw = f"{pdf_path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}|paddleocr|{mode}"
    except Exception:
        raw = f"{pdf_path}|paddleocr|{mode}"
    return short_hash_text(raw)


def _paddle_markdown_text(result: Any) -> str:
    try:
        md = getattr(result, "markdown", None)
        if isinstance(md, dict):
            value = md.get("markdown_texts") or md.get("text") or ""
            if isinstance(value, list):
                return "\n\n".join(str(x) for x in value if str(x).strip()).strip()
            return str(value or "").strip()
        if isinstance(md, str):
            return md.strip()
    except Exception:
        pass
    try:
        data = result if isinstance(result, dict) else dict(result)
        md = data.get("markdown") or {}
        if isinstance(md, dict):
            value = md.get("markdown_texts") or md.get("text") or ""
            if isinstance(value, list):
                return "\n\n".join(str(x) for x in value if str(x).strip()).strip()
            return str(value or "").strip()
        value = data.get("markdown_texts") or ""
        if value:
            return str(value).strip()
    except Exception:
        pass
    return ""


def try_paddleocr_pdf_parse(pdf_path: Path, *, cache_dir: Path | None = None, max_chars: int = 220_000) -> str:
    """Parse scanned/image-only PDFs locally with PaddleOCR PP-StructureV3."""
    try:
        from paddleocr import PPStructureV3  # type: ignore
    except Exception as exc:
        raise RuntimeError("?? PaddleOCR/PP-StructureV3????? Python ???? paddleocr ? paddlepaddle?") from exc

    cache_root = Path(cache_dir) if cache_dir else (PROJECT_ROOT / ".paddleocr_cache")
    key = paddle_ocr_cache_key(pdf_path)
    output_dir = cache_root / key
    cached = output_dir / "paddleocr_ppstructurev3.md"
    if cached.exists():
        text = read_text(cached).strip()
        if text:
            log(f"  ? ?? PaddleOCR ???????{cached}")
            return _compact_llm_context(text, max_chars=max_chars, label="PaddleOCR ??????")

    output_dir.mkdir(parents=True, exist_ok=True)
    log("  ?? ?? PaddleOCR PP-StructureV3 ?????? PDF????????????????????")
    pipeline = PPStructureV3(
        lang=os.getenv("AMP_PADDLEOCR_LANG", "ch"),
        use_doc_orientation_classify=_env_flag("AMP_PADDLEOCR_ORIENTATION", True),
        use_doc_unwarping=_env_flag("AMP_PADDLEOCR_UNWARP", False),
        use_textline_orientation=_env_flag("AMP_PADDLEOCR_TEXTLINE_ORIENTATION", True),
        use_table_recognition=_env_flag("AMP_PADDLEOCR_TABLE", True),
        use_formula_recognition=_env_flag("AMP_PADDLEOCR_FORMULA", False),
        use_chart_recognition=_env_flag("AMP_PADDLEOCR_CHART", False),
    )
    results = pipeline.predict(str(pdf_path))
    markdown_pages: list[Any] = []
    page_texts: list[str] = []
    total = len(results) if hasattr(results, "__len__") else 0
    for idx, result in enumerate(results, start=1):
        log(f"  PaddleOCR ?????? {idx}/{total or '?'} ?")
        try:
            md = result.markdown
            if isinstance(md, dict):
                markdown_pages.append(md)
        except Exception:
            pass
        page_text = _paddle_markdown_text(result)
        if page_text:
            page_texts.append(f"\n\n[PDF Page {idx}]\n{page_text}")

    combined = ""
    if markdown_pages:
        try:
            merged = pipeline.concatenate_markdown_pages(markdown_pages)
            combined = _paddle_markdown_text(merged)
        except Exception as exc:
            log(f"  ?? PaddleOCR Markdown ????????????{exc}")
    if not combined:
        combined = "\n".join(page_texts).strip()
    if not combined:
        raise RuntimeError("PaddleOCR PP-StructureV3 ????? Markdown?")
    write_text(cached, combined)
    log(f"  ? PaddleOCR ??????????{cached}")
    return _compact_llm_context(combined, max_chars=max_chars, label="PaddleOCR ??????")


def build_local_pdf_context_prompt(prompt: str, pdf_path: Path, local_text: str, *, max_chars: int = 48_000) -> str:
    local_text = _compact_llm_context(local_text, max_chars=max_chars, label="本地解析结果")
    # Add lightweight page anchors from pypdf so outline generation can still
    # produce source_ranges. Keep anchors small; they are only for page定位，不应
    # 把同一章节文本再塞一遍造成 token 翻倍。
    try:
        anchor_budget = _int_env("AMP_MAX_PAGE_ANCHOR_CHARS", 18_000)
        page_anchors = _compact_llm_context(extract_pdf_text(pdf_path, max_chars=anchor_budget), max_chars=anchor_budget, label="页码锚点")
    except Exception as exc:
        page_anchors = f"[页码锚点提取失败：{exc}]"
    return (
        f"{prompt}\n\n"
        "以下内容由本地 PyMuPDF4LLM 优先解析得到；请优先依据 Markdown 解析结果。"
        "后面只附少量 [PDF Page N] 页码锚点，用于定位 source_ranges。\n\n"
        "【PyMuPDF4LLM 本地解析结果】\n"
        f"{local_text}\n\n"
        "【PDF 页码锚点】\n"
        f"{page_anchors}"
    )


# Backward-compatible function names; older code paths/settings may still reference them.
def try_local_mineru_parse(pdf_path: Path, *, mode: str = "auto", backend: str = DEFAULT_LOCAL_PDF_PARSER, api_url: str = "", cache_dir: Path | None = None) -> str:
    return try_local_pdf_parse(pdf_path, mode=mode, parser=backend, cache_dir=cache_dir)


def build_mineru_context_prompt(prompt: str, pdf_path: Path, mineru_text: str, *, max_chars: int = 220_000) -> str:
    return build_local_pdf_context_prompt(prompt, pdf_path, mineru_text, max_chars=max_chars)


def normalize_page_range(start_page: int, end_page: int, total_pages: int, page_offset: int = 0) -> tuple[int, int]:
    """Map outline pages to 1-based PDF pages, then clamp."""
    start_pdf_page = int(start_page) + int(page_offset)
    end_pdf_page = int(end_page) + int(page_offset)
    if start_pdf_page > end_pdf_page:
        start_pdf_page, end_pdf_page = end_pdf_page, start_pdf_page
    start_pdf_page = max(1, min(total_pages, start_pdf_page))
    end_pdf_page = max(1, min(total_pages, end_pdf_page))
    return start_pdf_page, end_pdf_page


def split_pdf_by_ranges(source_pdf: Path, output_pdf: Path, ranges: list[dict[str, Any]], page_offset: int = 0) -> list[dict[str, int]]:
    ensure_pypdf()
    reader = PdfReader(str(source_pdf))
    total_pages = len(reader.pages)
    writer = PdfWriter()
    used: list[dict[str, int]] = []
    seen_pages: set[int] = set()

    for item in ranges or []:
        try:
            start = int(item.get("start_page") or item.get("start") or item.get("from") or 0)
            end = int(item.get("end_page") or item.get("end") or item.get("to") or start)
        except Exception:
            continue
        if start <= 0 or end <= 0:
            continue
        start_pdf, end_pdf = normalize_page_range(start, end, total_pages, page_offset=page_offset)
        for page_no in range(start_pdf, end_pdf + 1):
            if page_no in seen_pages:
                continue
            writer.add_page(reader.pages[page_no - 1])
            seen_pages.add(page_no)
        used.append({"start_page": start_pdf, "end_page": end_pdf})

    if not used:
        # As a safe fallback, give the episode the whole book rather than silently producing an empty PDF.
        for page in reader.pages:
            writer.add_page(page)
        used.append({"start_page": 1, "end_page": total_pages})

    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    with output_pdf.open("wb") as f:
        writer.write(f)
    return used


PAGE_RANGE_RE = re.compile(r"P\s*(\d+)\s*[-—–~至到]\s*P?\s*(\d+)", re.I)
SINGLE_PAGE_RE = re.compile(r"P\s*(\d+)", re.I)


def page_ranges_from_text(text: str) -> list[dict[str, Any]]:
    ranges: list[dict[str, Any]] = []
    for m in PAGE_RANGE_RE.finditer(str(text or "")):
        ranges.append({"label": m.group(0), "start_page": int(m.group(1)), "end_page": int(m.group(2))})
    if not ranges:
        singles = [int(x) for x in SINGLE_PAGE_RE.findall(str(text or ""))]
        for n in singles:
            ranges.append({"label": f"P{n}", "start_page": n, "end_page": n})
    return ranges


CHAPTER_HEADING_RE = re.compile(
    r"^\s*((?:第\s*[一二三四五六七八九十百千万零〇两\d]+\s*[章节回篇部卷])|(?:Chapter\s+\d+)|(?:CHAPTER\s+\d+))"
    r"[\s：:、.．-]*([^\n\r]{0,48})\s*$",
    re.I,
)
LOCAL_OUTLINE_EXCLUDE_RE = re.compile(r"目录|目次|版权|封面|扉页|序言|前言|导读|附录|注释|参考文献|索引|后记|致谢")


def _clean_local_chapter_label(title: str, fallback: str) -> str:
    text = re.sub(r"\s+", " ", str(title or "")).strip(" #\t\r\n-—_")
    text = re.sub(r"^\[?PDF Page \d+\]?\s*", "", text, flags=re.I).strip()
    if not text:
        text = fallback
    return text[:64]


def _chapter_marker(label: str, fallback_no: int) -> str:
    text = str(label or "")
    m = re.search(r"第\s*[一二三四五六七八九十百千万零〇两\d]+\s*[章节回篇部卷]", text)
    if m:
        return re.sub(r"\s+", "", m.group(0))
    m = re.search(r"(?:Chapter|CHAPTER)\s+\d+", text)
    if m:
        return m.group(0).title().replace(" ", "")
    return f"第{fallback_no}章"


def _local_outline_title(book_title: str, chapter_label: str, chapter_no: int, part_no: int, part_count: int) -> str:
    marker = _chapter_marker(chapter_label, chapter_no)
    base = normalize_book_title(book_title) or str(book_title or "").strip() or "本书"
    if part_count <= 1:
        return f"{base}{marker} 01"
    return f"{base}{marker} {part_no:02d}"


def _chapter_ranges_from_pdf_outline(pdf_path: Path) -> list[dict[str, Any]]:
    ensure_pypdf()
    reader = PdfReader(str(pdf_path))
    total_pages = len(reader.pages)
    raw_outline = getattr(reader, "outline", None) or getattr(reader, "outlines", None) or []
    rows: list[dict[str, Any]] = []

    def walk(items: Any, level: int = 0) -> None:
        if not isinstance(items, list):
            items = [items]
        for item in items:
            if isinstance(item, list):
                walk(item, level + 1)
                continue
            title = str(getattr(item, "title", "") or "").strip()
            if not title:
                continue
            try:
                page_no = int(reader.get_destination_page_number(item)) + 1
            except Exception:
                continue
            if 1 <= page_no <= total_pages:
                rows.append({"label": title, "start_page": page_no, "level": level})

    walk(raw_outline, 0)
    if not rows:
        return []
    rows = sorted(rows, key=lambda x: (int(x["start_page"]), int(x.get("level") or 0)))
    chapterish = [
        x for x in rows
        if CHAPTER_HEADING_RE.search(str(x.get("label") or ""))
        and not LOCAL_OUTLINE_EXCLUDE_RE.search(str(x.get("label") or ""))
    ]
    candidates = chapterish if len(chapterish) >= 2 else [
        x for x in rows
        if int(x.get("level") or 0) <= 1
        and not LOCAL_OUTLINE_EXCLUDE_RE.search(str(x.get("label") or ""))
    ]
    if len(candidates) < 2:
        return []

    chapters: list[dict[str, Any]] = []
    for idx, item in enumerate(candidates):
        start = int(item["start_page"])
        next_start = int(candidates[idx + 1]["start_page"]) if idx + 1 < len(candidates) else total_pages + 1
        excluded_starts = [
            int(x["start_page"])
            for x in rows
            if int(x.get("start_page") or 0) > start
            and int(x.get("start_page") or 0) < next_start
            and LOCAL_OUTLINE_EXCLUDE_RE.search(str(x.get("label") or ""))
        ]
        if excluded_starts:
            next_start = min(next_start, min(excluded_starts))
        end = max(start, min(total_pages, next_start - 1))
        if end - start + 1 < 2:
            continue
        chapters.append({
            "label": _clean_local_chapter_label(str(item.get("label") or ""), f"第{idx + 1}章"),
            "start_page": start,
            "end_page": end,
        })
    return chapters


def _chapter_ranges_from_page_headings(pdf_path: Path) -> list[dict[str, Any]]:
    ensure_pypdf()
    reader = PdfReader(str(pdf_path))
    total_pages = len(reader.pages)
    hits: list[dict[str, Any]] = []
    for idx, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        lines = [re.sub(r"\s+", " ", x).strip() for x in text.splitlines() if x.strip()]
        for line in lines[:12]:
            if len(line) > 72 or LOCAL_OUTLINE_EXCLUDE_RE.search(line):
                continue
            m = CHAPTER_HEADING_RE.match(line)
            if m:
                hits.append({"label": _clean_local_chapter_label(line, f"第{len(hits) + 1}章"), "start_page": idx})
                break
    deduped: list[dict[str, Any]] = []
    seen_pages: set[int] = set()
    for hit in hits:
        page_no = int(hit["start_page"])
        if page_no in seen_pages:
            continue
        seen_pages.add(page_no)
        deduped.append(hit)
    if len(deduped) < 2:
        return []
    chapters: list[dict[str, Any]] = []
    for idx, item in enumerate(deduped):
        start = int(item["start_page"])
        next_start = int(deduped[idx + 1]["start_page"]) if idx + 1 < len(deduped) else total_pages + 1
        end = max(start, min(total_pages, next_start - 1))
        if end - start + 1 < 2:
            continue
        chapters.append({"label": item["label"], "start_page": start, "end_page": end})
    return chapters


def _split_page_range_evenly(start_page: int, end_page: int, parts: int) -> list[tuple[int, int]]:
    total = max(1, int(end_page) - int(start_page) + 1)
    parts = max(1, min(int(parts), total))
    ranges: list[tuple[int, int]] = []
    for idx in range(parts):
        start = int(start_page) + (idx * total) // parts
        end = int(start_page) + ((idx + 1) * total) // parts - 1
        ranges.append((start, max(start, end)))
    return ranges


def build_local_chapter_outline(args: "PipelineArgs") -> dict[str, Any] | None:
    if not _env_flag("AMP_LOCAL_CHAPTER_OUTLINE", False):
        return None
    try:
        chapters = _chapter_ranges_from_pdf_outline(args.book)
        source = "PDF目录/书签"
        if not chapters:
            chapters = _chapter_ranges_from_page_headings(args.book)
            source = "页面标题扫描"
    except Exception as exc:
        log(f"  ⚠️ 本地章节识别失败，回退到大纲模型：{exc}")
        return None
    if not chapters:
        return None

    total_pages = sum(max(1, int(ch["end_page"]) - int(ch["start_page"]) + 1) for ch in chapters)
    target_pages = _int_env("AMP_LOCAL_OUTLINE_TARGET_PAGES", 10)
    max_pages = _int_env("AMP_LOCAL_OUTLINE_MAX_PAGES", 12)
    if args.episode_count and args.episode_count > 0:
        target_pages = max(4, int((total_pages + args.episode_count - 1) // args.episode_count))
        max_pages = max(max_pages, target_pages)
    target_pages = max(4, target_pages)
    max_pages = max(target_pages, max_pages)

    book_title = normalize_book_title(args.book.stem) or args.book.stem
    author = guess_author_from_filename(args.book.stem)
    episodes: list[dict[str, Any]] = []
    episode_no = 1
    for chapter_no, chapter in enumerate(chapters, start=1):
        start = int(chapter["start_page"])
        end = int(chapter["end_page"])
        page_count = max(1, end - start + 1)
        part_count = max(1, int((page_count + max_pages - 1) // max_pages))
        if part_count == 1 and page_count > target_pages:
            part_count = 2
        for part_no, (part_start, part_end) in enumerate(_split_page_range_evenly(start, end, part_count), start=1):
            label = str(chapter["label"])
            range_label = f"{label} {part_no:02d}/{part_count:02d} P{part_start}-P{part_end}"
            title = _local_outline_title(book_title, label, chapter_no, part_no, part_count)
            episodes.append({
                "episode_no": episode_no,
                "title": title,
                "duration": "3-4分钟",
                "hook": f"围绕{_chapter_marker(label, chapter_no)}的一个核心矛盾展开。",
                "main_points": [
                    f"本集只讲{label}的第{part_no}段内容",
                    "先给冲突，再补背景，避免长铺垫",
                    "结尾预告下一段或下一章的关键问题",
                ],
                "source_labels": [range_label],
                "source_ranges": [{"label": range_label, "start_page": part_start, "end_page": part_end}],
                "source_chapter_label": label,
                "chapter_part_no": part_no,
                "chapter_part_count": part_count,
            })
            episode_no += 1

    outline = {
        "book_title": book_title,
        "author": author,
        "outline_notes": (
            f"已优先使用本地{source}生成大纲；按章节顺序切分，再把长章节拆成约3-4分钟短集。"
            f"全书集数连续编号，共{len(episodes)}集。"
        ),
        "local_outline_source": source,
        "local_chapters": chapters,
        "episodes": episodes,
    }
    return normalize_outline(outline)


# =========================
# LLM providers
# =========================

@dataclass
class ModelConfig:
    provider: str = "dry-run"
    text_model: str = ""
    image_provider: str = "openai"
    image_model: str = DEFAULT_OPENAI_IMAGE_MODEL
    api_key: str = ""
    image_api_key: str = ""
    temperature: float = 0.4
    max_retries: int = 4
    request_timeout: int = 600
    local_parse_mode: str = "auto"
    mineru_backend: str = DEFAULT_MINERU_BACKEND
    mineru_api_url: str = DEFAULT_MINERU_API_URL
    mineru_cache_dir: str = ""
    auto_resume: bool = True
    skip_existing_text: bool = True
    skip_existing_images: bool = True
    only_missing_images: bool = False
    only_postprocess: bool = False
    start_episode_no: int = 1
    start_stage: str = "outline"
    stop_event: Any = None


class LLMClient:
    def __init__(self, config: ModelConfig):
        self.config = config
        self.provider = (config.provider or "dry-run").lower().strip()
        self.image_provider = (config.image_provider or "none").lower().strip()
        self.api_key = read_api_key(self.provider, config.api_key)
        image_key_provider = "gemini" if self.image_provider == "gemini" else "image"
        self.image_api_key = read_api_key(image_key_provider, config.image_api_key)

    def is_dry_run(self) -> bool:
        return self.provider in {"dry", "dry-run", "mock", "none"}

    def generate_text(self, prompt: str, *, pdf_path: Path | None = None, task_name: str = "text") -> str:
        check_cancelled(self.config.stop_event)
        if self.is_dry_run():
            return self._dry_run_text(prompt, pdf_path=pdf_path, task_name=task_name)

        # Prefer local PDF parsing. If every local parser/text fallback fails,
        # keep pdf_path so providers that support files can upload the original PDF.
        if pdf_path and pdf_path.exists():
            if is_image_only_pdf(pdf_path):
                log("  ⚠️ 检测到纯图片/扫描版 PDF，跳过 PyMuPDF4LLM/pypdf，直接使用 PaddleOCR PP-StructureV3 本地解析。")
                cache_dir = Path(self.config.mineru_cache_dir) if self.config.mineru_cache_dir else None
                paddle_text = try_paddleocr_pdf_parse(
                    pdf_path,
                    cache_dir=(cache_dir / "paddleocr") if cache_dir else None,
                    max_chars=max(_task_context_char_budget(task_name) + 20_000, 80_000),
                )
                prompt = build_mineru_context_prompt(prompt, pdf_path, paddle_text, max_chars=_task_context_char_budget(task_name))
                log("  ✅ 已使用 PaddleOCR 本地解析 Markdown，本次不上传原始 PDF。")
                pdf_path = None
            else:
                parse_mode = (self.config.local_parse_mode or "auto").lower().strip()
                if parse_mode in {"off", "none", "disabled", "false", "0"}:
                    log("  ⚠️ 已禁止 PDF 直传：local_parse_mode=off 被强制改为 auto。")
                    parse_mode = "auto"
                try:
                    cache_dir = Path(self.config.mineru_cache_dir) if self.config.mineru_cache_dir else None
                    context_budget = _task_context_char_budget(task_name)
                    local_text = try_local_pdf_parse(
                        pdf_path,
                        mode=parse_mode,
                        parser=self.config.mineru_backend,
                        cache_dir=cache_dir,
                        max_chars=max(context_budget + 20_000, 80_000),
                    )
                    prompt = build_local_pdf_context_prompt(prompt, pdf_path, local_text, max_chars=context_budget)
                    log("  ✅ 已使用本地解析 Markdown/文本，本次不会上传 PDF。")
                except Exception as local_exc:
                    log(f"  ⚠️ 本地 PDF 解析失败，改用 pypdf 文本提取。原因：{local_exc}")
                    try:
                        prompt = build_pdf_text_fallback_prompt(prompt, pdf_path, max_chars=_task_context_char_budget(task_name))
                    except Exception as fallback_exc:
                        log(f"  ⚠️ pypdf 文本 fallback 也失败，将把原始 PDF 直传给支持文件的大模型：{fallback_exc}")
                    else:
                        pdf_path = None
                else:
                    pdf_path = None

        prompt_tokens = _approx_token_count(prompt)
        model_name = self.config.text_model or "默认模型"
        if task_name == "outline" and prompt_tokens >= 50_000:
            log("  ⏳ 大纲输入很长，模型可能需要 1-10 分钟才返回；期间界面显示“运行中”属于正常等待。")
            log("  ℹ️ 若点击停止，当前 API 请求通常要等服务端返回或超时后才会真正中断。")

        if _env_flag("AMP_LOG_TOKEN_ESTIMATE", True):
            model_name = self.config.text_model or "默认模型"
            log(f"  🧮 {task_name} 输入估算：约 {_approx_token_count(prompt):,} tokens（{self.provider}/{model_name}）")
            if self.provider == "openai" and _model_is_expensive_openai(model_name):
                log("  💰 成本提醒：当前 OpenAI 兼容模型属于较高价档；可按成本需要切换模型。")

        last_error: Exception | None = None
        for attempt in range(1, self.config.max_retries + 2):
            check_cancelled(self.config.stop_event)
            try:
                self._current_task_name = task_name
                started = time.perf_counter()
                log(f"  🚀 正在请求 {task_name} 模型：{self.provider}/{model_name}，超时 {self.config.request_timeout}s。")
                if self.provider == "gemini":
                    result = self._gemini_text(prompt, pdf_path=pdf_path)
                elif self.provider == "openai":
                    result = self._openai_text(prompt, pdf_path=pdf_path)
                elif self.provider == "doubao":
                    result = self._doubao_text(prompt, pdf_path=pdf_path)
                elif self.provider == "deepseek":
                    result = self._deepseek_text(prompt, pdf_path=pdf_path)
                else:
                    raise RuntimeError(f"未知文本模型 provider：{self.provider}")
                elapsed = time.perf_counter() - started
                log(f"  ✅ {task_name} 模型已返回，耗时 {elapsed:.1f}s。")
                if _env_flag("AMP_LOG_TOKEN_ESTIMATE", True):
                    log(f"  🧮 {task_name} 输出估算：约 {_approx_token_count(result):,} tokens")
                return result
            except Exception as exc:
                last_error = exc
                if pdf_path and "PDF file upload through the relay failed" in str(exc):
                    break
                if attempt > self.config.max_retries:
                    break
                wait = min(30, 2 ** attempt)
                log(f"⚠️ {task_name} 第 {attempt} 次调用失败，{wait}s 后重试：{exc}")
                if self.config.stop_event is not None and self.config.stop_event.wait(wait):
                    check_cancelled(self.config.stop_event)
        raise RuntimeError(f"{task_name} 调用失败：{last_error}") from last_error

    def generate_image(self, prompt: str, save_path: Path, *, size: str | None = None, quality: str | None = None) -> bool:
        check_cancelled(self.config.stop_event)
        original_prompt = str(prompt or "")
        current_prompt = sanitize_image_prompt_for_safety(original_prompt)
        if current_prompt != original_prompt:
            log(f"  🛡️ 已预处理生图提示词中的高风险身体伤害/自伤触发词：{save_path.name}")
        if self.image_provider in {"", "none", "dry", "dry-run", "mock"}:
            write_text(save_path.with_suffix(".prompt.txt"), current_prompt)
            return False

        last_error: Exception | None = None
        used_aggressive_safety = False
        for attempt in range(1, self.config.max_retries + 2):
            check_cancelled(self.config.stop_event)
            try:
                if self.image_provider == "openai":
                    return self._openai_image(current_prompt, save_path, size=size, quality=quality)
                if self.image_provider == "gemini":
                    return self._gemini_image(current_prompt, save_path, size=size)
                raise RuntimeError(f"未知图片模型 provider：{self.image_provider}")
            except Exception as exc:
                last_error = exc
                if image_prompt_moderation_blocked(exc) and not used_aggressive_safety:
                    safer_prompt = sanitize_image_prompt_for_safety(current_prompt, aggressive=True)
                    if safer_prompt != current_prompt:
                        current_prompt = safer_prompt
                        used_aggressive_safety = True
                        log(f"⚠️ 生图安全系统拦截，已改写为更克制的间接画面后重试：{save_path.name}")
                        continue
                    used_aggressive_safety = True
                if image_prompt_moderation_blocked(exc) and used_aggressive_safety:
                    log(f"⚠️ 生图仍被安全系统拦截，停止重复提交同一类提示词：{save_path.name}；原因：{exc}")
                    break
                if attempt > self.config.max_retries:
                    break
                wait = min(30, 2 ** attempt)
                log(f"⚠️ 生图失败，第 {attempt} 次重试前等待 {wait}s：{exc}")
                if self.config.stop_event is not None and self.config.stop_event.wait(wait):
                    check_cancelled(self.config.stop_event)
        write_text(save_path.with_suffix(".prompt.txt"), current_prompt)
        log(f"⚠️ 图片未生成，只保存已安全改写的提示词：{save_path.with_suffix('.prompt.txt')}；原因：{last_error}")
        return False

    def _dry_run_text(self, prompt: str, *, pdf_path: Path | None, task_name: str) -> str:
        if task_name == "outline":
            return json.dumps({
                "book_title": "未调用模型的示例书名",
                "episodes": [
                    {
                        "episode_no": 1,
                        "title": "示例第一期：请配置模型后重新生成",
                        "duration": "3-4分钟",
                        "hook": "这是 dry-run 占位结果。",
                        "main_points": ["程序结构验证", "PDF 分割验证", "脚本与配图输出验证"],
                        "source_labels": ["示例 P1-P5"],
                        "source_ranges": [{"label": "示例 P1-P5", "start_page": 1, "end_page": 5}],
                    }
                ],
            }, ensure_ascii=False, indent=2)
        if task_name.startswith("episode_prompt"):
            return "请根据本集大纲和章节原文，写一个观点清晰、节奏紧凑、适合短视频口播的解读脚本，并输出 JSON。"
        if task_name.startswith("script"):
            return json.dumps({
                "episode_no": 1,
                "title": "示例脚本",
                "voiceover": [
                    {"image_id": "A1", "text": "这是 dry-run 生成的封面对应台词。"},
                    {"image_id": "B01", "text": "真正运行时，这里会变成本集第一句逐句口播台词。"},
                    {"image_id": "B02", "text": "每句台词都会对应一张描述其内容的画面。"},
                    {"image_id": "C", "text": "最后用一句话收束观点。"},
                ],
                "image_prompts": [
                    {"image_id": "A1", "name": "A1_A与C共享母图", "prompt": "竖版 9:16，低成本源图，无文字母图。经典读书解读类封面风格，根据书籍类型自动选择历史人文或社会科学纪录片风格。顶部20%预留标题区，中部45%为核心视觉，底部15%预留品牌区；不生成任何文字、标题、logo、水印、书法或印章文字。"},
                    {"image_id": "B01", "name": "B01_内容", "prompt": "竖屏插画，一本书被拆解成大纲、PDF 原文、脚本、台词和配图的流水线。"},
                    {"image_id": "B02", "name": "B02_内容", "prompt": "竖屏插画，短视频台词逐句对应一幕画面，便于剪辑。"},
                ],
                "full_script": "这是 dry-run 脚本。配置 provider 和 API Key 后会调用真实模型。",
            }, ensure_ascii=False, indent=2)
        return "dry-run"

    def _gemini_text(self, prompt: str, *, pdf_path: Path | None) -> str:
        if not self.api_key:
            raise RuntimeError("未找到 Gemini API Key：请设置 GEMINI_API_KEY，或在项目根目录放 gemini_api_key.txt。中转域名会继续使用，但 Key 按模型独立读取。")
        requested_model = self.config.text_model or DEFAULT_GEMINI_FAST_MODEL
        canonical_requested_model = canonical_gemini_model(requested_model)
        if canonical_requested_model != requested_model:
            log(f"⚠️ Gemini 模型名已自动修正：{requested_model} → {canonical_requested_model}")
            requested_model = canonical_requested_model

        client = openai_compatible_client(api_key=self.api_key, base_url=foreign_model_base_url(), timeout=self.config.request_timeout)

        def call_with_model(model: str) -> str:
            full_prompt = prompt
            if pdf_path and pdf_path.exists():
                task_name = str(getattr(self, "_current_task_name", "text") or "text")
                budget = _task_context_char_budget(task_name)
                extracted = extract_pdf_text(pdf_path, max_chars=budget)
                extracted_plain = re.sub(r"\s+", "", extracted or "")
                if len(extracted_plain) < int(os.getenv("AMP_SCANNED_PDF_MIN_TEXT_CHARS", "500")):
                    log("⚠️ Gemini 已改走 NewAPI/OpenAI 兼容中转，扫描版 PDF 也不直传，改用本地文本提示。")
                else:
                    log("⚠️ Gemini 已改走 NewAPI/OpenAI 兼容中转，使用本地文本提取结果。")
                prefix = "PyMuPDF4LLM Markdown" if "PyMuPDF4LLM" in (extracted or "") else "pypdf 文本提取"
                if not extracted:
                    extracted = "[PDF 文本提取为空：该 PDF 可能是扫描版或加密版。若使用 Gemini，请开启 AMP_ALLOW_GEMINI_PDF_DIRECT_FOR_SCANNED=1；或先转换为可复制文字的 PDF/Markdown。]"
                full_prompt = f"{prompt}\n\n以下是使用 {prefix} 的内容（已保留页码标记）：\n{extracted}"
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": full_prompt}],
                temperature=self.config.temperature,
            )
            return extract_chat_content(response)

        last_error: Exception | None = None
        for candidate in model_candidates(requested_model, GEMINI_MODEL_FALLBACKS, DEFAULT_GEMINI_FAST_MODEL):
            try:
                if candidate != requested_model:
                    log(f"⚠️ Gemini 模型 {requested_model} 不可用，自动尝试：{candidate}")
                return call_with_model(candidate)
            except Exception as exc:
                last_error = exc
                if is_model_not_found_error(exc):
                    continue
                raise
        raise last_error or RuntimeError(f"Gemini 模型不可用：{requested_model}")

    def _openai_text(self, prompt: str, *, pdf_path: Path | None) -> str:
        if not self.api_key:
            raise RuntimeError("未找到 OpenAI API Key：请设置 OPENAI_API_KEY，或在项目根目录放 openai_api_key.txt。")
        model = self.config.text_model or DEFAULT_OPENAI_TEXT_MODEL
        client = openai_compatible_client(api_key=self.api_key, base_url=foreign_model_base_url(), timeout=self.config.request_timeout)

        def output_text(response: Any) -> str:
            # Never fall back to str(response). The repr of an incomplete Responses
            # API object looks like Response(id=...) and can poison B01/台词/绘图提示词.
            text = str(getattr(response, "output_text", "") or "").strip()
            if not text:
                pieces: list[str] = []
                for item in getattr(response, "output", []) or []:
                    for content in getattr(item, "content", []) or []:
                        value = getattr(content, "text", None)
                        if value:
                            pieces.append(str(value))
                text = "\n".join(pieces).strip()
            status = str(getattr(response, "status", "") or "").lower()
            incomplete = getattr(response, "incomplete_details", None)
            if not text:
                reason = getattr(incomplete, "reason", None) if incomplete is not None else None
                usage = getattr(response, "usage", None)
                raise RuntimeError(
                    "OpenAI 没有返回正文文本，已拒绝把 SDK Response 对象写入脚本。"
                    f"status={status or 'unknown'}; incomplete_reason={reason or 'none'}; usage={usage}"
                )
            if status == "incomplete" or incomplete is not None:
                reason = getattr(incomplete, "reason", None) if incomplete is not None else None
                # 有文本时仍允许解析，但记录提醒；无文本已在上面直接报错。
                log(f"⚠️ OpenAI 返回 incomplete，但包含文本，继续解析；reason={reason or 'unknown'}")
            assert_not_sdk_response_dump(text, "OpenAI")
            return text

        def create_response_compatible(**payload: Any):
            """Call Responses API with parameters supported by current flagship models.

            Some newer reasoning models reject sampling parameters such as
            temperature. The UI does not expose temperature, so the safest
            default is to omit it. If a user deliberately enables temperature
            through AMP_OPENAI_USE_TEMPERATURE=1 and the model rejects it, we
            remove the parameter and retry once automatically.
            """
            payload = dict(payload)
            if os.getenv("AMP_OPENAI_USE_TEMPERATURE", "0").strip() in {"1", "true", "True", "yes"}:
                payload["temperature"] = self.config.temperature
            try:
                return client.responses.create(**payload)
            except Exception as exc:
                text = str(exc)
                if "Unsupported parameter" in text and "temperature" in text and "temperature" in payload:
                    payload.pop("temperature", None)
                    log("⚠️ OpenAI 当前模型不支持 temperature，已自动移除该参数后重试。")
                    return client.responses.create(**payload)
                if "Unsupported parameter" in text and "max_output_tokens" in text and "max_output_tokens" in payload:
                    payload.pop("max_output_tokens", None)
                    log("⚠️ OpenAI 当前接口不支持 max_output_tokens，已自动移除后重试。")
                    return client.responses.create(**payload)
                if ("Unsupported parameter" in text or "unknown parameter" in text.lower()) and "reasoning" in text and "reasoning" in payload:
                    payload.pop("reasoning", None)
                    log("⚠️ OpenAI 当前模型/接口不支持 reasoning 参数，已自动移除后重试。")
                    return client.responses.create(**payload)
                raise

        if pdf_path and pdf_path.exists():
            if not _env_flag("AMP_ALLOW_OPENAI_PDF_FILES", False):
                raise RuntimeError(
                    "PDF 文件直传到 OpenAI-compatible 中转站已默认禁用；当前 relay 不兼容 Files API。"
                    "请先使用本地解析结果，或显式设置 AMP_ALLOW_OPENAI_PDF_FILES=1 后自行承担兼容性风险。"
                )
            log("  Local parsing failed; uploading PDF by Files API as final fallback.")
            file_ref: dict[str, str]
            try:
                upload_path, tmp_upload = ascii_safe_pdf_copy(pdf_path)
                try:
                    with ProgressFileReader(upload_path, label="OpenAI Files PDF 上传") as fh:
                        uploaded = client.files.create(file=fh, purpose="assistants")
                    file_id = str(getattr(uploaded, "id", "") or "")
                    if not file_id:
                        raise RuntimeError(f"Files API returned no file id: {uploaded!r}")
                    file_ref = {"type": "input_file", "file_id": file_id}
                    log(f"  PDF uploaded through Files API: {file_id}")
                finally:
                    if tmp_upload is not None:
                        tmp_upload.cleanup()
            except Exception as upload_exc:
                raise RuntimeError(
                    "PDF file upload through the relay failed, and this scanned PDF is too large for base64 inline upload. "
                    "Use local OCR first, or a relay/provider that supports Files API. "
                    f"Upload error: {upload_exc}"
                ) from upload_exc
            model_input: Any = [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        file_ref,
                    ],
                }
            ]
        else:
            model_input = prompt

        payload: dict[str, Any] = {"model": model, "input": model_input}
        task_name = str(getattr(self, "_current_task_name", "text") or "text")
        max_output = _openai_output_budget(task_name)
        if max_output:
            payload["max_output_tokens"] = max_output
        # For long JSON/script generation, high reasoning can consume the entire
        # max_output_tokens budget and produce no visible text. Default to low,
        # configurable via AMP_OPENAI_REASONING_EFFORT.
        reasoning_effort = os.getenv("AMP_OPENAI_REASONING_EFFORT", "low").strip().lower()
        if reasoning_effort and reasoning_effort not in {"off", "none", "0", "false"}:
            payload["reasoning"] = {"effort": reasoning_effort}
        response = create_response_compatible(**payload)
        return output_text(response)

    def _doubao_text(self, prompt: str, *, pdf_path: Path | None) -> str:
        """Volcengine Ark / Doubao chat-completions provider.

        火山方舟兼容 OpenAI SDK：base_url 默认使用国内站
        https://ark.cn-beijing.volces.com/api/v3；model 填控制台创建的
        推理接入点 ID（ep-...），也兼容少数可直接调用的 Model ID。
        PDF 不直传给方舟 Chat API；沿用本项目的本地解析 / 文本 fallback，
        这样对接入点兼容性最好，也更省 token 和网络成本。
        """
        if not self.api_key:
            raise RuntimeError(
                "未找到豆包/火山方舟 API Key：请设置 ARK_API_KEY，"
                "或在项目根目录放 ark_api_key.txt / doubao_api_key.txt。"
            )
        model = (self.config.text_model or doubao_env_model()).strip()
        if not model:
            raise RuntimeError(
                "未设置豆包/火山方舟模型。请把模型名填写为控制台的推理接入点 ID（ep-...），"
                "或设置 ARK_ENDPOINT_ID / DOUBAO_ENDPOINT_ID / ARK_MODEL / DOUBAO_MODEL，"
                "也可以在 GUI 的“豆包接入点 ID”中填写并保存。"
            )
        if doubao_model_looks_like_api_key(model):
            raise RuntimeError(
                "豆包/火山方舟模型名填写错误：当前模型名看起来像 API Key。"
                "模型名栏应填推理接入点 ID（ep-...）或 doubao- 开头的 Model ID；"
                "API Key 请填 ARK_API_KEY/DOUBAO_API_KEY 或 GUI 的 Key 输入框。"
            )
        base_url = (
            os.getenv("ARK_BASE_URL", "")
            or os.getenv("DOUBAO_BASE_URL", "")
            or DEFAULT_DOUBAO_BASE_URL
        ).rstrip("/")

        full_prompt = prompt
        if pdf_path and pdf_path.exists():
            full_prompt = build_pdf_text_fallback_prompt(prompt, pdf_path, max_chars=_task_context_char_budget(str(getattr(self, "_current_task_name", "text") or "text")))

        client = openai_compatible_client(api_key=self.api_key, base_url=base_url, timeout=self.config.request_timeout)
        payload: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": full_prompt}],
            "temperature": self.config.temperature,
        }
        max_tokens = os.getenv("ARK_MAX_TOKENS", "") or os.getenv("DOUBAO_MAX_TOKENS", "")
        if max_tokens.strip():
            try:
                payload["max_tokens"] = int(max_tokens)
            except ValueError:
                log(f"⚠️ ARK_MAX_TOKENS/DOUBAO_MAX_TOKENS 不是整数，已忽略：{max_tokens}")

        try:
            response = client.chat.completions.create(**payload)
        except Exception as exc:
            text = str(exc)
            if "temperature" in payload and "temperature" in text and ("Unsupported" in text or "unsupported" in text or "不支持" in text):
                payload.pop("temperature", None)
                log("⚠️ 当前豆包/火山方舟模型不支持 temperature，已自动移除后重试。")
                response = client.chat.completions.create(**payload)
            else:
                raise
        return extract_chat_content(response)

    def _deepseek_text(self, prompt: str, *, pdf_path: Path | None) -> str:
        """DeepSeek text generation through the DeepSeek API."""
        if not self.api_key:
            raise RuntimeError("未找到 DeepSeek API Key：请设置 DEEPSEEK_API_KEY，或在项目根目录放 deepseek_api_key.txt。")
        model = self.config.text_model or os.getenv("DEEPSEEK_MODEL", DEEPSEEK_DEFAULT_MODEL)
        base_url = deepseek_base_url()
        full_prompt = prompt
        if pdf_path and pdf_path.exists():
            full_prompt = build_pdf_text_fallback_prompt(prompt, pdf_path, max_chars=_task_context_char_budget(str(getattr(self, "_current_task_name", "text") or "text")))
        response = requests_post_no_proxy(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={"model": model, "messages": [{"role": "user", "content": full_prompt}], "temperature": self.config.temperature},
            timeout=self.config.request_timeout,
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]

    def _openai_image(self, prompt: str, save_path: Path, *, size: str | None = None, quality: str | None = None) -> bool:
        if not self.image_api_key:
            raise RuntimeError("未找到 GPT-image2 生图 API Key：请设置 IMAGE_API_KEY/OPENAI_IMAGE_API_KEY，或在 GUI 填写 GPT-image2 Key。")
        model = self.config.image_model or DEFAULT_OPENAI_IMAGE_MODEL
        client = openai_compatible_client(api_key=self.image_api_key, base_url=foreign_model_base_url(), timeout=self.config.request_timeout)
        payload = {"model": model, "prompt": prompt, "size": normalize_openai_image_size_for_model(model, size or "720x1280")}
        q = (quality or default_image_quality()).strip()
        if q:
            payload["quality"] = q
        try:
            result = client.images.generate(**payload)
        except Exception as exc:
            text = str(exc)
            if "quality" in payload and ("Unsupported" in text or "unsupported" in text or "quality" in text):
                payload.pop("quality", None)
                log("⚠️ 当前生图接口不支持 quality 参数，已自动移除后重试。")
                result = client.images.generate(**payload)
            else:
                raise
        item = result.data[0]
        b64 = getattr(item, "b64_json", None)
        if not b64:
            raise RuntimeError("图片接口未返回 b64_json。")
        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_path.write_bytes(base64.b64decode(b64))
        _enhance_generated_image_file(save_path, payload.get("size"))
        return True

    def _gemini_image(self, prompt: str, save_path: Path, *, size: str | None = None) -> bool:
        if not self.image_api_key:
            raise RuntimeError("未找到 Gemini 生图 API Key：请设置 GEMINI_API_KEY，或在 GUI 填写 Gemini Key。")
        model = canonical_gemini_image_model(self.config.image_model or DEFAULT_GEMINI_IMAGE_MODEL)
        base = foreign_model_base_url().rsplit("/v1", 1)[0].rstrip("/")
        response = requests_post_no_proxy(
            f"{base}/v1beta/models/{model}:generateContent",
            headers={"Authorization": f"Bearer {self.image_api_key}", "Content-Type": "application/json"},
            json={
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
            },
            timeout=self.config.request_timeout,
        )
        response.raise_for_status()
        data = response.json()
        b64 = _extract_gemini_inline_image_b64(data)
        if not b64:
            raise RuntimeError("Gemini 原生生图接口未返回 inlineData 图片。")
        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_path.write_bytes(base64.b64decode(b64))
        _enhance_generated_image_file(save_path, size or "720x1280")
        return True


# =========================
# Prompt templates
# =========================

OUTLINE_PROMPT = """
你是一名短视频读书解读策划。请阅读我提供的整本书 PDF，生成一份可直接用于系列短视频制作的“分集解读大纲”。

目标风格：把整本书先组织成一个能追下去的系列故事，而不是机械按目录逐章复述。每一集都要有强切入点、明确冲突、主要内容、原文参考页码；可以按人物线、权力线、矛盾升级线、悬念线、现实共鸣线来重组，只要不歪曲原文。

硬性要求：
1. 只输出 JSON，不要输出 Markdown、解释、代码围栏。
2. 分集数量由你根据整本书的故事张力、人物线索、核心冲突和可拍性自然决定，不要机械固定，也不要机械跟随目录；每一集必须能独立成片，同时让下一集有继续追看的理由。
3. 每集必须有 source_ranges，用于后续切分 PDF。页码写书中可定位的 PDF/正文页码。格式必须是数组：
   [{"label":"章节或小节名 P1-P18", "start_page":1, "end_page":18}]
4. source_ranges 可以有多个范围，而且允许是非连续页码、不同章节、不同书籍位置的组合；start_page/end_page 必须是整数；不要写“见前文”“全书”等模糊标签。跨章节/跨位置组合时，source_ranges 按故事线需要列出多个页码范围，并用 source_labels 标明这些材料来自哪里。
5. 主题不要泛泛概括，要能拍成短视频；标题要有冲突感，切入点要足够抓人。对《贫穷的本质》这类社科/发展经济学作品，默认受众是没有受过社会经济学学术训练、但关心贫富差距如何产生并维持、希望理解并打破阶层固化处境的普通人。大纲要从具体例子、人物选择、家庭预算、公共服务、价格激励和现实处境切入，先激发兴趣，再带出机制；不要写成社科论文目录、概念讲义或鸡汤式阶层焦虑。允许把同一人物、同一制度矛盾、同一后果链条、同一个现实共鸣主题分散在全书不同位置的材料组合成一集，但 main_points 要说明为什么这样组合。
6. outline_notes 简要说明你为什么这样分集，尤其说明你采用的是哪条故事线，而不是只说“按章节拆分”。
7. 每集必须建立“关键案例库” key_examples，至少 2～5 条。不要把好例子压缩成抽象结论。凡是原书出现具体人群、实验、田野观察、历史事件、关键物件、制度操作、对比组或反常识场景，都要优先写进 key_examples，并标明它支撑什么问题。
8. 对社科/经济学书尤其要保留可口播的典型例子，例如蚊帐防疟疾、驱虫、疫苗、免费赠送与自费购买、小额激励、家庭预算、学校出勤、信贷和保险等。如果原文确实出现“一个蚊帐就能预防疟疾，但很多人不买，并对比公益组织免费赠送和自己购买的区别”，必须把这个案例写进对应集的 key_examples，不能只写成“低成本健康干预推广困难”。
9. main_points 负责讲“这一集要解决什么问题”，key_examples 负责列“用哪些原书例子来讲清它”。两者不能互相替代。

请按以下 JSON 结构输出：
{
  "book_title": "",
  "author": "",
  "outline_notes": "",
  "episodes": [
    {
      "episode_no": 1,
      "title": "第一期：...",
      "duration": "3-4分钟",
      "hook": "切入点：...",
      "main_points": ["...", "...", "..."],
      "key_examples": [
        {"name": "案例名", "detail": "原书里的具体例子、对比或场景", "supports": "这个例子支撑的观点或问题"}
      ],
      "source_labels": ["第一章 ... P1-P18"],
      "source_ranges": [
        {"label": "第一章 ... P1-P18", "start_page": 1, "end_page": 18}
      ]
    }
  ]
}
""".strip()

EPISODE_PROMPT_BUILDER = """
你是一名短视频脚本导演。下面是一集读书解读大纲，请把它改写成“给脚本生成大模型使用的提示词”。

要求：

【原文覆盖与深度解读要求】
1. 脚本生成阶段的首要任务不是写短摘要，而是充分、认真地解读本集原文；润色阶段才负责把表达改得更通俗。
1A. 对《贫穷的本质》这类社科/发展经济学作品，默认受众是没有受过社会经济学学术训练、但关心贫富差距如何产生并维持、希望理解并打破阶层固化处境的普通人。台词必须从具体例子入手，先讲“谁遇到了什么选择、为什么这个选择不容易、结果怎样”，再解释背后的经济学机制。不要先讲概念、模型、学派或宏大判断。
2. 生成脚本前，必须先通读本集 Markdown/PDF 原文，提炼一份“原文覆盖清单”：关键事件、人物关系、制度背景、作者判断、重要转折、典型例证、因果链条、后续影响。脚本必须覆盖这份清单中的主要内容。
3. 不要只抓最戏剧化的一两件事。原文如果同时讨论皇帝、首辅、文官集团、财政制度、礼仪、党争、道德与现实的冲突，脚本也必须按逻辑展开这些层次。
4. A1 负责开篇钩子，C 负责收束和预告；真正覆盖原文的内容必须主要放在 B 系正文里。禁止把长章节压缩成 A1+B01+B02+C 这种提纲式脚本。
5. 对超过 20 页或 Markdown 很长的章节，B 系正文通常不得少于 45 句；超过 30 页的章节通常不得少于 70 句。除非用户明确要求极短视频，否则不要为了省事压缩正文。
6. 每 6～10 个 B 句应形成一个小段落逻辑：先讲事实，再解释原因，再指出影响；不要连续堆结论，也不要只写情绪化评价。
7. full_script 必须是完整讲述稿，不能只是 voiceover 的几句摘要；voiceover 要从 full_script 拆成可配图的逐句台词。
8. 输出 JSON 中必须包含 source_coverage_checklist 字段，列出本集原文中已被脚本覆盖的 6～15 个要点，方便程序和人工检查覆盖是否充分。
9. 如果原文内容丰富，但你只能输出很短的脚本，应优先增加 B 系正文句数，而不是用“这背后很复杂”“由此可见”等空泛句带过。
10. 开头第一句话必须点睛本章：直接提出本集最值得看的问题、反差或人物处境。开头三句话内必须自然亮出书名和一句精简标签；标签只能来自已知上下文，不得编造奖项、出版史或名人评价。《贫穷的本质》可在上下文允许时称为“2019 年诺贝尔经济学奖相关的反贫困研究代表作”；信息不足时用“社科经典/历史经典/文学经典”等保守标签。
11. 正文不能连续输出抽象摘要。每个判断都要尽量用具体例子、场景、人物选择、制度后果、田野观察、实验/数据证据或原书细节托住；不要让“作者认为/这说明/由此可见”连着出现。

1. 只输出提示词正文，不要解释。
2. 提示词必须要求模型基于本集 PDF 原文，不要凭空编造。
3. 提示词必须要求输出 JSON，包含 full_script、voiceover、image_prompts 三部分。
4. voiceover 必须逐句绑定 image_id，但三类编号职责不能混：
   - A1 只用于封面开场，不承载正文内容；A2/A01/A02 是后处理导出的封面规格文件名，不要出现在 voiceover 或 image_prompts 里。
   - B01、B02、B03... 才是正文内容画面，每一句正文台词都必须绑定一个 B 系编号。
   - C 只用于结尾台词，不承载正文内容，不需要单独生成 image_prompt。
5. image_prompts 只允许输出 A1 和 B 系列：
   - A1 是封面/片尾共用母图。
   - B 系列必须逐句对应正文台词，prompt 要直接描述该句台词的画面内容。
   - 不要输出 C 的 image_prompt；C 末页由后处理生成。
   - 所有图片都只生成纯画面背景，不要生成任何可识别文字、标题、书名、作者名、logo、水印或大段印章文字。
   - 每条 B 系 prompt 必须以“本句台词”为第一依据：先提取这一句里的人物、事件、地点、制度、矛盾、情绪，再转成具体画面；不能只写“历史感背景”“宫殿空镜”“对应内容画面”，也不能把上一句、下一句或整集摘要混进来。
   - prompt 风格必须服从台词风格：台词是克制的知识叙述，画面就应是纪录片式、历史人文、清楚具体但不夸张；色调由内容决定，可以丰富但必须统一耐看，不要默认昏暗、黑金暗红或纯氛围化。台词讲流言/冲突/制度压力，就用朝房议论、奏疏、宫门距离、人物背影等可视化矛盾；台词讲婚姻/国本，就用宫廷礼制、后宫帘幕、东宫/朝堂张力等画面。每个元素都要对应台词里的对象、地点、器物、冲突、证据或概念，不添加无关装饰。
6. A1 的旁白必须先概括本集真正讲什么，再从本集正文或 PDF 原文里提炼一个自然钩子，第一句话要点睛本章并吸引观众注意；禁止为了贴近生活而硬套生活类比。优先顺序是：① 从人物处境、制度约束、证据反差或关键选择里提出一个有趣问题；② 从本集内容里挑一个反常识细节或关键矛盾开场；③ 只有当普通生活、职场、家庭或规则压力与后文确实自然相连时，才使用生活切口。开头三句话内必须自然出现书名《{book_title}》和一句精简标签；标签只能来自已知信息或输入上下文，不得编造奖项、出版史、销量或名人评价。若书名是《贫穷的本质》，可称为“2019 年诺贝尔经济学奖相关的反贫困研究代表作”；若信息不足，则保守写“这本社科经典/历史经典/文学经典”。钩子后必须立刻接住同一个核心词或同一个问题，平滑落到本集章节和第一段正文，不要像单独贴上去的标语。A1 推荐结构是“本集真实问题/人物处境 → 书名与精简标签 → 本集具体从哪里讲起”，整体不超过 2 句。不要把陌生专名堆进第一问里；要先让普通观众听懂，再逐步引出事件或论证。A1 和 B01 必须能连读成一段顺畅旁白；不要写“生活中，我们常常……”“生活里，很多……”这类泛泛套话，不要把生活道理强行套到历史或社科内容上；不要和 B01 正文重复同一句信息。A1 的 prompt 必须按“母板生成提示词”生成一张竖版 9:16 无文字母图：先判断书籍类型和本集主题，再提取人物/群体、关键地点、事件、证据、物件、矛盾和核心视觉意象；顶部 20% 预留干净标题区，中部 45% 放核心视觉，底部 15% 预留品牌区；不要生成任何文字、中文书法、标题、logo、slogan、水印或印章文字；整体风格要动态适配本书，不默认黑金暗红、厚重历史感或暗黑电影感，每个元素都要对应文稿内容。
7. C 不需要单独生成新底图；C 结尾页将复用 A1 母图裁切得到，并在后处理时只添加 logo“{brand_name}”、slogan“{brand_slogan}”、关注引导语“{follow_sentence}”与分享引导语。C 对应台词要凝练收束本集，并在非全书最后一集时提示下集内容；如果系统提供下一集/下一章标题，预告含义必须与该标题一致，摘要只用于解释标题，不能偏离标题；不要复述 A1 或 B 段已经说过的钩子。
8. 配图节奏要足够密：每一句台词都必须对应一幕画面，单幕建议控制在 3~8 秒；平均每 {image_interval_seconds} 秒至少对应 1 张图，voiceover 与 image_prompts 的数量要尽量一一对应；如果一句旁白明显超过这个时长，就主动拆成更短的句子和画面单元。
9. 台词要忠于原文、通顺、地道、易懂，有观点、有冲突、有转折；句子成分要完整，必要的主语、谓语、宾语和指代不能省略，不要写成电报式、过度压缩式中文，也不要为了“口语化”而改成网络聊天腔、夸张解说腔或营销文案。
10. 保留本集标题、切入点、主要内容、原文参考范围。
11. 对原文证据要谨慎：能从本集 PDF 里找到依据才可以写，不能把常识当成书中内容。

本集大纲 JSON：
{episode_json}
""".strip()

SCRIPT_JSON_REQUIREMENT = """
请严格输出合法 JSON，不要 Markdown，不要代码围栏，不要解释。

必须输出字段：
{
  "episode_no": 1,
  "title": "",
  "full_script": "完整口播脚本",
  "source_coverage_checklist": ["覆盖要点1", "覆盖要点2", "覆盖要点3"],
  "voiceover": [
    {"image_id": "A1", "text": "封面开场台词"},
    {"image_id": "B01", "text": "正文台词"},
    {"image_id": "B02", "text": "正文台词"},
    {"image_id": "C", "text": "结尾台词"}
  ],
  "image_prompts": [
    {"image_id": "A1", "name": "A1_A与C共享母图", "prompt": "无文字封面母图提示词"},
    {"image_id": "B01", "name": "B01_内容", "prompt": "直接表现 B01 台词内容的画面提示词"}
  ]
}

硬性要求：
1. 只基于本集正文，不要写注释、参考文献、图片占位、脚注编号。
2. source_coverage_checklist 写 6～15 个原文覆盖要点。
3. A1 只做开篇钩子，B 系正文负责充分解读，C 只做收束和下集预告。
4. 长章节不要压缩成 A1+B01+B02+C；超过 20 页通常不少于 45 条 B，超过 30 页通常不少于 70 条 B。
5. voiceover 每条台词要短、清楚、适合配音；B 系编号连续递增。
6. image_prompts 只输出 A1 和 B 系，不输出 C；每条 prompt 必须紧贴同 image_id 的台词。
7. B 系 prompt 不能泛写“对应内容画面、历史感背景、宫殿背景”，必须包含该句台词里的具体对象和场景。
8. 生图 prompt 涉及伤害、死亡、病因、传闻时，用间接画面表达，不画身体特写、血腥或危险行为。
9. 如果本集大纲或输入中包含 key_examples / 关键案例库，必须把这些案例写进 source_coverage_checklist，并在 B 系正文中逐个展开。不要只写“低成本干预推广困难”“价格影响选择”这种抽象句。
10. 社科/经济学书的典型案例必须保留具体对象和对比。例如原文若出现蚊帐防疟疾，以及公益组织免费赠送和个人自费购买的差别，正文必须讲出“蚊帐是什么干预、为什么有效、为什么有人不买、免费赠送与购买差在哪里”，不能省略为一句“预防措施推广困难”。
"""

VOICEOVER_POLISH_PROMPT = """
请只对以下已标图号的中文旁白进行逐句润色。任务仅限于在原句含义范围内修复语病、错别字、搭配不当、指代不清、标点不顺、明显拗口表达、不够地道的中文说法，以及带有明显 AI 味、过度戏剧化或不符合著作解读旁白的表达，不做其他任何事情。

必须严格遵守逐句锁定规则：不新增任何一句，不删除任何一句，不合并任何一句，不拆分任何一句，不改变任何句子的顺序。每一句润色后都必须与原句一一对应，句子数量、位置关系和前后承接关系必须完全保持不变。不要改变句子序号、图号和原有分句边界；可以让语气更顺，但不能把一个编号里的意思改成新的意思，也不能让前后逻辑跳跃。

必须严格保留所有图号、字母标记、编号、时间码、LRC 锚点、括号标记及其顺序和位置，不得移动、改写、补充或删除。原文中的换行、段落结构和标记结构尽量保持不变。

【润色阶段不得压缩原文覆盖】
1. 最终润色只负责把已经生成的台词改得清楚、通俗、顺口；不能删掉脚本生成阶段对原文的覆盖点。
2. 不要把多层论证压缩成一句空泛结论；如果原句包含人物、制度、原因、后果，润色后这些信息仍要保留。
3. 可以把书面表达改成更容易听懂的现代汉语，但不能把原文里的关键事件、例证、作者判断和因果链条改没。
4. A1 和 C 可以为逻辑顺畅而重写，但 B 系正文必须继续承担充分解读原文的任务。


语言风格要服从著作本身的气质和本集主题，而不是套用固定网感。保持经典著作解读的通俗、克制、准确，并进一步贴近纪录片式知识叙述：像一位可靠的讲述者在平实介绍事实、现象和观点，表达清楚、有画面感、有节奏，但不表演、不煽情、不端着讲课。

可以适度优化节奏、停顿感和顺口程度，让旁白更自然；但要忠于原文，通顺、地道、易懂即可，不要为了“口语化”改成聊天腔、网络段子、营销文案或夸张解说腔。

【终稿语言风格要求】
1. 最后一轮润色的目标是“通俗易懂的标准汉语旁白”：让普通观众一听就明白，但不要写成聊天口吻。
2. 优先使用清楚、平实、顺口的现代汉语；能用短句就不用长句，能说清人物关系就不要堆抽象名词。
3. 遇到书面化表达，要改得更自然：少用“其、乃、由此可见、得以、致使、从而、进而、显现出、基于、在此背景下、某种意义上、不可避免地”等套语；必要的历史制度名词可以保留，但要放在听得懂的句子里。
4. 不能过度口语化：不要写“咱们、你看、说白了、其实吧、怎么说呢、搞事情、离谱、扎心、摆烂、封神、天花板”等聊天腔、网络梗或营销号词。
5. 保持知识类解读的克制和准确：像可靠讲述者在说明事情，不端着讲课，也不嬉笑调侃。
6. 不要为了通俗而删掉关键事实；应把复杂关系拆开说清楚，例如“谁做了什么、为什么这么做、带来了什么后果”。
7. 如果一句话同时有多个抽象概念，优先改成具体关系和动作；但必须保持原有事实、行数、编号和 image_id 不变。


在不改变原意、不增加信息的前提下，尽量去除死板的解读腔、AI 味和模板化表达。避免使用“本文将”“本章将”“接下来我们将”“本书主要讲了”“从科学角度看”等机械开场或总结式套话；如果原句中已有这类表达，只能改得更自然、更像正常旁白，不能借机扩写或改写观点。

不要使用浮夸、宏大、空泛、煽动性或带有 AI 味的大词套话。尽量避免“底层逻辑”“深层机制”“本质上”“直接揭示”“核心密码”“认知跃迁”“颠覆认知”“震撼”“封神”“天花板”“绝不是”“从来不是”“真正的主角”“命运齿轮”“无声地改变一切”等夸张、绝对化、拟人化或泛化表达；除非原句确有明确对应含义且无法删除，否则应改成更具体、平实、准确、符合纪录片知识叙述的中文表达。

遇到类似“但它们绝不是被动的旁观者”这类明显带有戏剧化、拟人化、AI 腔或过度强调的句子，应在不改变原意的前提下改得更克制、更客观，例如保留“并非只是被动存在”“它们也会参与其中”“它们对过程产生影响”这类知识叙述方向，但不要新增解释、例子或结论。具体改法必须根据原句上下文判断，不要套用固定句式。

语言可以更灵动，但不能改变事实边界和原意边界。可以让表达更有故事感、更有观看节奏、更适合短视频旁白，但这种故事感只能来自更自然的语序、更清楚的指代、更顺畅的停顿和更准确的词语选择，不能添加原文没有的情节、悬念、情绪煽动、背景解释、因果关系、总结升华或个人判断。

保持纪录片知识叙述的质感：句子应简洁、清楚、可信，避免过度口号化、过度人格化、过度反问、过度转折和强行制造悬念。可以把生硬的书面句改成自然旁白，但不要变成营销文案、鸡汤文案、爆款标题党、网络口水话或夸张解说腔。

额外注意：不要把中文压缩成缺主语、缺谓语或指代不清的短句。遇到制度、时间、人物关系说明时，要尽量保留完整句子成分，让现代汉语读起来顺畅自然。例如“每旬仅在三、六、九日举行早朝，其余时间让年幼皇帝专心读书”应改成“当时的安排是：每旬只在初三、初六、初九举行早朝，其余时间，则让年幼的皇帝专心读书”；“因万历年纪尚小，当时能真正影响他的人屈指可数”应改成“由于万历年纪还小，当时真正能影响他的人并不多”。

开头如果需要钩子，必须把 A1、B01、B02 当作连续旁白一起检查。先概括本集真正讲什么，再根据本集中心设计钩子；不要先套生活类比，也不要先套固定爆款句。钩子优先从本集原文或正文里寻找真正有趣的问题、人物处境、历史矛盾或反常识细节，例如“你以为皇帝就能自由自在吗？其实并不是。”；也可以关注与本集自然相关的生活现象，但必须和后文共享同一个对象或问题，并且能自然回到本集主旨。不要使用“生活中，我们常常……”这类泛泛套话，不要把生活道理强行套到历史内容上；钩子必须服务后文，不能突兀，也不能为了吸引人而添加原文没有的事实。

A1 的开篇语要做到“本集中心 → 钩子 → 承接 → 正文落点”自然连贯：先确认本集中心，再用第一句提出问题或反差，后一个分句必须接住同一个核心词或同一个历史问题，再落到书名、章节或本集要讲的事件。A1 不能只是抽象标语，也不能先讲一个泛泛生活道理再突然跳到书名。润色时要重点检查 A1 和 B01 的过渡：A1 最后一分句必须为 B01 铺路，B01 第一分句要顺着 A1 的对象或问题继续说；如果 A1 结尾是“制度束缚”，B01 应自然进入礼仪、制度、皇帝处境或具体事件；如果 A1 提到“午朝讹传”，B01 应顺势进入罚俸、礼仪或万历处境。前后不能出现“话题断裂、主语忽然换人、钩子和正文没有共同对象”的情况；一旦不顺，优先重写 A1，而不是硬加生活类比。

开头前三句话还要做“书名与标签”检查：如果原台词或本集大纲里已经提供书名、作者、奖项、出版背景或作品定位，要尽量在前三句话内自然保留书名和一句精简标签；如果没有这些信息，不能凭空编造，只能把已有书名自然放入开头。例：《贫穷的本质》若上下文已有诺奖信息，可写成“这本 2019 年诺贝尔经济学奖相关的反贫困研究代表作”；若上下文没有奖项信息，就不要硬加。A1 第一整句必须点睛本章，不能只是“本期我们继续解读……”。

润色正文时，优先把干巴巴的总结句改成“例子托结论”的表达：如果原句已经包含例子、人物动作、制度后果、田野观察或原书细节，必须保留；如果原句只有抽象判断，不能新增事实，但可以把语序改得更像“这个例子说明了什么”，减少“作者认为/由此可见/本章指出”这类连续摘要腔。

遇到不顺的开头，要在不改变事实、不新增资料的前提下改成内容型钩子。坏例子：“生活中，我们常常身不由己，被各种规则束缚。《万历十五年》就讲述了……”；可改方向：“你以为皇帝站在朝廷最上面，就能按自己的意思行事吗？其实不然；《万历十五年》这一集先从一个看似平淡的年份说起，看礼仪和制度怎样约束万历。”





【短句与长难句兜底】
1. 最后兜底润色必须优先保证通顺、地道、易懂；不要使用长难句、套娃从句或连续多层修饰。
2. 每个编号可以包含一到两个短句，但不要把多个因果、转折和解释塞进一个长句里。能拆成两句，就不要用一串逗号硬连。
3. 单个句子尽量控制在 35～45 个汉字以内；超过 55 个汉字时，必须优先拆短，除非拆开会破坏原意或固定名词。
4. 避免连续使用三个以上逗号。遇到“因为……所以……但……反而……因此……”这类长链条，要拆成“事实一句、原因一句、结果一句”。
5. 每个短句都要有明确主语和动作：先说谁，做了什么；再说为什么；最后说结果。不要用抽象名词堆叠代替说明。
6. 解释古代制度或非现代汉语概念时，也要短。解释只说明“这是什么”，不要顺手扩成百科段落。
7. 润色后的句子读起来应像稳定的知识旁白：清楚、克制、有节奏；不要写成论文长句、翻译腔、聊天腔或营销号句式。

【十一优化补充：开篇指代与浅入规则】
润色 A1/B01/B02 时，不要预设观众已经知道“午朝”“罚俸”“张冯”“考成法”等专有背景。钩子不能一开头就堆陌生名词，例如不要写“你以为午朝大典讹传、官员被罚只是偶然事件吗？”；应先用更容易理解的问题、人物处境或自然生活场景切入，再把本集具体事件带出来。

A1 必须避免“从 A 讲起，讲到 B”这种松散串联句。更好的结构是：先提出本集中心里的问题，再用一个承接句把书名、章节名、本集名和正文首段接上。例如当 B01 是“1587 年本是平淡无奇的一年”时，A1 可以先说“你以为皇帝站在朝廷最上面，就能按自己的意思行事吗？其实不然；《万历十五年》这一集先从一个看似平淡的年份说起，看礼仪和制度怎样约束万历。”这样 B01 才能自然接到“1587年”。

禁止凭空指代。不要输出没有明确前文对象的“这件小事”“这件事”“这背后”“这个问题”。如果前一句没有把对象说清楚，就直接改成明确名词，例如“这个看似平淡的年份”“这场朝会风波”“这个折中办法”。B02 尤其要检查：如果 B01 只说“1587年是平淡的一年”，B02 就不能突然说“从这件小事讲起”。

【十四优化补充：A1 上集回顾与正文首句承接】
如果 A1 含有“上集提到/上集讲到/上集说到”等回顾，必须同时检查 A1 后第一条和第二条 B 段；这些 B 段不一定叫 B01/B02，也可能沿用原长脚本编号，如 B45、B86。不要只看编号，要按实际顺序连读。

A1 回顾上一集后，必须为本集正文首句铺出共同对象或共同问题。不能让 A1 只说上一集的申时行、张居正或制度结果，下一句却突然出现“随后又有流言称”“再到后来”“又有说法”等需要前文承接的表达。若正文首句是这类承接句，必须在不新增事实的前提下，把句子改成自足表达，先交代议论对象，再写具体说法。

还要检查弱转场和弱指代。A1 后第一条正文不能写“我们再来看看他的婚姻”“接着看这件事”“再看这个问题”这类依赖前文对象的句子。只要 A1 里同时出现两个以上人物，B 段里的“他/这个/这件事”就必须改成明确对象。例如“我们再来看看他的婚姻”应改为“要理解国本之争，先要从万历的婚姻说起”。


【绘图提示词联动规则】
终稿台词会直接驱动 A1/B 绘图提示词重建，所以润色时不能让台词变成抽象口号或缺少画面对象的空泛句。每句 B 段应尽量保留可被画面表达的对象、场景、矛盾或动作，例如人物、朝堂、奏疏、制度、礼仪、传言、婚姻、国本等；不要把台词润成只有“这背后很复杂”“问题越来越明显”这类无法配图的空句。
A1/B/C 的逻辑顺畅优先，但 B 段每一句仍要能单独生成一幕画面；如果改写承接句，必须让新句也有明确的可视化核心。

不要添加原文没有的信息、概念、背景、例子、因果关系或结论。模糊或不通顺处，只在原句含义范围内做最小必要修改；如果一句话本身信息不足，不要自行补全，只做语序、措辞、标点和语气层面的自然化处理。

只输出润色后的旁白正文，不要解释修改原因，不要输出修改建议，不要输出对照表，不要添加标题、注释或任何额外内容。

本集大纲 JSON，仅供理解语境，不能据此扩写：
{episode_json}

待润色旁白：
{voiceover_text}
""".strip()


# =========================
# Pipeline data helpers
# =========================

def _format_key_example(item: Any) -> str:
    """Format outline key_examples without losing concrete case details."""
    if isinstance(item, dict):
        name = str(item.get("name") or item.get("title") or item.get("case") or item.get("案例") or "").strip()
        detail = str(item.get("detail") or item.get("description") or item.get("内容") or "").strip()
        supports = str(item.get("supports") or item.get("point") or item.get("支撑") or "").strip()
        parts = [x for x in [name, detail, f"支撑：{supports}" if supports else ""] if x]
        return "｜".join(parts)
    return str(item or "").strip()


@dataclass
class Episode:
    episode_no: int
    title: str
    duration: str = ""
    hook: str = ""
    main_points: list[str] = field(default_factory=list)
    key_examples: list[str] = field(default_factory=list)
    source_labels: list[str] = field(default_factory=list)
    source_ranges: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any], fallback_no: int) -> "Episode":
        no = int(data.get("episode_no") or data.get("no") or fallback_no)
        title = str(data.get("title") or f"第{no}集").strip()
        source_ranges = data.get("source_ranges") or data.get("page_ranges") or []
        source_labels = data.get("source_labels") or []
        if isinstance(source_labels, str):
            source_labels = [source_labels]
        if not source_ranges:
            probe = "\n".join([title, str(data.get("hook") or ""), "\n".join(source_labels), json.dumps(data, ensure_ascii=False)])
            source_ranges = page_ranges_from_text(probe)
        return cls(
            episode_no=no,
            title=title,
            duration=str(data.get("duration") or "").strip(),
            hook=str(data.get("hook") or data.get("cut_in") or "").strip(),
            main_points=[str(x).strip() for x in (data.get("main_points") or data.get("points") or []) if str(x).strip()],
            key_examples=[_format_key_example(x) for x in (data.get("key_examples") or data.get("examples") or data.get("案例库") or []) if _format_key_example(x)],
            source_labels=[str(x).strip() for x in source_labels if str(x).strip()],
            source_ranges=source_ranges,
            raw=data,
        )

    def to_dict(self) -> dict[str, Any]:
        data = dict(self.raw or {})
        data.update({
            "episode_no": self.episode_no,
            "title": self.title,
            "duration": self.duration,
            "hook": self.hook,
            "main_points": self.main_points,
            "key_examples": self.key_examples,
            "source_labels": self.source_labels,
            "source_ranges": self.source_ranges,
        })
        return data


def normalize_outline(raw_outline: Any) -> dict[str, Any]:
    if isinstance(raw_outline, list):
        raw_outline = {"book_title": "", "episodes": raw_outline}
    if not isinstance(raw_outline, dict):
        raise ValueError("大纲 JSON 顶层必须是对象或数组。")
    episodes_raw = raw_outline.get("episodes") or raw_outline.get("items") or raw_outline.get("outline") or []
    if isinstance(episodes_raw, dict):
        episodes_raw = list(episodes_raw.values())
    episodes: list[dict[str, Any]] = []
    for idx, item in enumerate(episodes_raw, start=1):
        if not isinstance(item, dict):
            continue
        episodes.append(Episode.from_dict(item, idx).to_dict())
    if not episodes:
        raise ValueError("没有在模型输出中找到 episodes。")
    raw_outline["episodes"] = episodes
    return raw_outline


def script_from_model_output(raw_text: str, episode: Episode) -> dict[str, Any]:
    assert_not_sdk_response_dump(raw_text, "脚本生成")
    try:
        parsed = parse_json_loose(raw_text)
        if isinstance(parsed, dict):
            return normalize_script_json(parsed, episode)
    except Exception as exc:
        # Long chapter scripts must be valid JSON. Do not silently turn a failed
        # API response or malformed JSON into B01, because that hides the real
        # failure and causes later image generation to proceed with garbage.
        preview = str(raw_text or "").strip()[:600].replace("\n", " ")
        tail = str(raw_text or "").strip()[-300:].replace("\n", " ")
        hint = "如果返回预览以 JSON 开头但不能解析，通常是输出过长被截断；新版已要求不输出 image_prompts 和重复 full_script，请删除旧 raw/script 文件后从 script 阶段重跑。"
        raise RuntimeError(f"脚本生成返回内容不是可解析 JSON，已拒绝降级为 B01。解析错误：{exc}；{hint}；返回预览：{preview}；返回结尾：{tail}") from exc

    raise RuntimeError("脚本生成返回内容不是 JSON object。")


def normalize_script_json(data: dict[str, Any], episode: Episode) -> dict[str, Any]:
    data = dict(data or {})
    data.setdefault("episode_no", episode.episode_no)
    data.setdefault("title", episode.title)
    data.setdefault("full_script", "")

    voiceover = data.get("voiceover") or data.get("lines") or data.get("台词") or []
    if isinstance(voiceover, str):
        voiceover = [{"image_id": "B01", "text": voiceover}]
    fixed_voiceover: list[dict[str, str]] = []
    for idx, item in enumerate(voiceover, start=1):
        if isinstance(item, str):
            text = item.strip()
            assert_not_sdk_response_dump(text, f"voiceover B{idx:02d}")
            fixed_voiceover.append({"image_id": f"B{idx:02d}", "text": text})
        elif isinstance(item, dict):
            image_id = str(item.get("image_id") or item.get("id") or f"B{idx:02d}").strip()
            text = str(item.get("text") or item.get("line") or item.get("台词") or "").strip()
            if text:
                assert_not_sdk_response_dump(text, f"voiceover {image_id}")
                fixed_voiceover.append({"image_id": image_id, "text": text})
    if not fixed_voiceover and data.get("full_script"):
        text = str(data.get("full_script")).strip()
        assert_not_sdk_response_dump(text, "full_script")
        fixed_voiceover.append({"image_id": "B01", "text": text})
    data["voiceover"] = fixed_voiceover
    # 为了避免长章节 JSON 输出过大，脚本生成阶段允许 full_script 为空或极短；
    # 程序会用 voiceover 自动合成完整口播稿。
    if not str(data.get("full_script") or "").strip() and fixed_voiceover:
        data["full_script"] = "\n".join(str(v.get("text") or "").strip() for v in fixed_voiceover if str(v.get("text") or "").strip())

    prompts = data.get("image_prompts") or data.get("prompts") or data.get("绘图提示词") or []
    if isinstance(prompts, str):
        prompts = [{"image_id": "B01", "name": "B01_内容", "prompt": prompts}]
    fixed_prompts: list[dict[str, str]] = []
    for idx, item in enumerate(prompts, start=1):
        if isinstance(item, str):
            image_id = f"B{idx:02d}"
            fixed_prompts.append({"image_id": image_id, "name": f"{image_id}_内容", "prompt": item.strip()})
        elif isinstance(item, dict):
            image_id = str(item.get("image_id") or item.get("id") or f"B{idx:02d}").strip()
            name = str(item.get("name") or f"{image_id}_内容").strip()
            prompt = str(item.get("prompt") or item.get("text") or item.get("提示词") or "").strip()
            if prompt:
                fixed_prompts.append({"image_id": image_id, "name": safe_filename(name, f"{image_id}_image"), "prompt": prompt})
    if not fixed_prompts:
        for v in fixed_voiceover:
            image_id = v["image_id"]
            fixed_prompts.append({
                "image_id": image_id,
                "name": f"{image_id}_内容",
                "prompt": f"竖屏9:16，读书解读短视频插图，主题：{episode.title}；画面对应台词：{v['text'][:120]}；不要出现大段文字。",
            })
    data["image_prompts"] = fixed_prompts
    return data



def voiceover_to_marked_text(script_data: dict[str, Any]) -> str:
    """Format voiceover lines as marked narration text for locked, sentence-by-sentence polishing."""
    lines: list[str] = []
    for item in script_data.get("voiceover") or []:
        image_id = str(item.get("image_id") or "").strip()
        text = str(item.get("text") or "").strip()
        if image_id or text:
            lines.append(f"【{image_id}】{text}" if image_id else text)
    return "\n".join(lines).strip()


def merge_polished_voiceover_text(raw_text: str, original_script: dict[str, Any]) -> dict[str, Any] | None:
    """Merge a non-JSON polished narration body back into script JSON.

    The default polish prompt asks the model to return only marked narration lines such as
    【B01】台词. We accept the result only when line count and image_id order match the
    original voiceover, so picture bindings cannot drift silently.
    """
    original_voiceover = original_script.get("voiceover") or []
    if not original_voiceover:
        return None

    cleaned = strip_code_fence(raw_text)
    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    if len(lines) != len(original_voiceover):
        return None

    parsed: list[dict[str, str]] = []
    for idx, (line, original) in enumerate(zip(lines, original_voiceover), start=1):
        original_id = str(original.get("image_id") or "").strip()
        match = re.match(r"^【([^】]+)】\s*(.*)$", line)
        if match:
            image_id = match.group(1).strip()
            text = match.group(2).strip()
        else:
            # Backward-tolerant fallback: if the model omitted markers but kept line count,
            # only accept by position and preserve original image_id.
            image_id = original_id
            text = line.strip()
        if original_id and image_id != original_id:
            return None
        if not text:
            return None
        parsed.append({"image_id": original_id or image_id or f"B{idx:02d}", "text": text})

    merged = dict(original_script)
    merged["voiceover"] = parsed
    merged["full_script"] = "\n".join(item["text"] for item in parsed).strip()
    # Keep image_prompts unchanged. The polish step is deliberately limited to narration.
    return merged


def infer_book_meta(book_path: Path, outline: dict[str, Any]) -> tuple[str, str]:
    raw_title = str(outline.get("book_title") or book_path.stem or "").strip()
    raw_author = str(outline.get("author") or outline.get("book_author") or "").strip()
    author = raw_author or guess_author_from_filename(book_path.stem)
    title = normalize_book_title(raw_title) or book_path.stem
    # If outline accidentally put author into title like a filename, strip it.
    if author and title.endswith(author):
        title = title[: -len(author)].strip(" -_（）()") or title
    return title, author


def _clean_sentence_text(text: str, max_chars: int = 96) -> str:
    value = re.sub(r"\s+", "", str(text or "")).strip("。！？!?；;，,：: ")
    if len(value) > max_chars:
        parts = [x.strip() for x in re.split(r"[。！？!?；;]", value) if x.strip()]
        value = parts[0] if parts else value[:max_chars]
    if len(value) > max_chars:
        value = value[:max_chars].rstrip("，。；：、")
    return value


def _summary_from_episode_outline(episode: Episode | None, max_chars: int = 72) -> str:
    if episode is None:
        return ""
    parts: list[str] = []
    hook = clean_prefix(episode.hook, ["切入点：", "hook:", "Hook:"]).strip()
    if hook:
        parts.append(hook)
    for point in episode.main_points or []:
        point = str(point or "").strip()
        if point:
            parts.append(point)
        if len("，".join(parts)) >= max_chars:
            break
    if not parts:
        title = re.sub(r"^第\s*[0-9一二三四五六七八九十百]+\s*[期集章回]\s*[：:]\s*", "", episode.title).strip()
        if title:
            parts.append(title)
    return _clean_sentence_text("，".join(parts), max_chars=max_chars)


def build_default_opening_line(book_title: str, episode: Episode) -> str:
    hook = clean_prefix(episode.hook, ["切入点：", "hook:", "Hook:"])
    chapter_name = re.sub(r"^第\s*[0-9一二三四五六七八九十百]+\s*[期集章回]\s*[：:]\s*", "", episode.title).strip() or episode.title
    hook_core = _clean_sentence_text(hook or chapter_name, max_chars=48)
    # 不再强行套生活类比；只保留与本章内容直接相关的切入点。
    first = hook_core if hook_core else chapter_name
    if first and not re.search(r"[。！？!?]$", first):
        first += "。"
    mention = f"这一集读《{book_title}》：{chapter_name}。" if book_title else f"这一集来看：{chapter_name}。"
    return f"{first}{mention}"


def default_ac_master_prompt() -> str:
    return """【母板生成提示词】

你是知识类短视频首席视觉导演，擅长把不同书籍转化成各自独立的 A/C 系列视觉系统。

请根据输入文稿内容，生成一张适合后处理排版的“无文字母图”。

输入内容：
{manuscript}

请先判断这本书的类型：历史、人文、社科、经济学、心理学、商业、哲学、文学、传记或科学。再提取本集的核心问题、人物/群体、关键场景、证据、物件、矛盾和情绪基调，设计一张只属于这本书和这一集的视觉母图。

画面要求：
- 不要生成任何文字、中文书法、标题、logo、slogan、水印、印章文字或可识别题签。
- 只生成背景和主体视觉，适合后期叠加文字。
- 顶部必须预留干净标题区；中部保留稳定主视觉区；中下部留一条适合放主题说明的干净区域；底部预留品牌区。
- 主体不要遮挡标题区、主题说明区和品牌区；构图稳定，适合裁剪成 3:4、9:16、4:3、16:9 多种比例。

风格要求：
- 每本书要有自己的视觉气质，不要套同一种暗色历史模板。
- 历史书可以用礼制空间、书案、奏疏、人物关系和时代器物；社科/经济学书可以用家庭预算、市场、学校、诊所、公共服务窗口、田野调查、简洁数据结构和现实空间；文学/哲学/心理书可以用人物处境、光影、房间、道路、物件和抽象关系。
- 风格要克制、清楚、有质感；可以是钢笔淡彩、水墨、数据新闻式插画、现代社科插图、文学化场景插画或扁平矢量插画。不要写实照片、不要 3D 渲染、不要过度 CG。
- 色调由内容决定：可以使用明亮自然光、暖色、冷暖对比、古纸色、青绿、朱红、金色点缀或更丰富的主题色，但必须服务人物处境、制度关系、经济选择、空间地点或核心概念。
- 可根据文稿主题改变背景元素，不强制固定皇帝、宫殿、龙纹、地图、书桌或抽象图标；画面里的每个元素都要对应文稿中的人物、地点、物件、冲突、证据或概念。
- 背景不要杂乱，不要堆满物件，不添加无关装饰、随机符号、空泛光效或纯氛围物件，优先保证可排版性和表达准确性。

色彩要求：
- 色彩可以丰富，但要统一、清楚、耐看；不用为了“高级感”强行压暗。
- 避免刺眼霓虹和与内容无关的高饱和装饰色；如果使用强色，只作为信息重点或关系对比。

构图要求：
- 竖版 9:16；分辨率按接口低成本档输出，后续由本地后处理放大到发布尺寸。
- 顶部约 18%~22% 留暗色安全区；中部约 28%~72% 放核心视觉；画面 50%~63% 高度附近留主题说明区；底部约 78%~92% 预留品牌区。
- 画面整体要像“无文字母板”，而不是已经完成排字的海报。

输出：一张 9:16 无文字母图；最终发布尺寸由本地后处理输出。
""".strip()


def _prompt_file_or_default(path: Path, default: str) -> str:
    try:
        if path.exists():
            text = path.read_text(encoding="utf-8").strip()
            if text:
                return text
    except Exception:
        pass
    return default


def load_runtime_prompt_files() -> dict[str, str]:
    """Read all runtime prompt files from prompts/.

    The hard-coded strings above are fallback templates only; normal GUI and CLI
    runs should use these editable files so prompt engineering stays independent
    from program code.
    """
    return {
        "outline_prompt": _prompt_file_or_default(OUTLINE_PROMPT_PATH, OUTLINE_PROMPT),
        "episode_prompt_builder": _prompt_file_or_default(EPISODE_PROMPT_BUILDER_PATH, EPISODE_PROMPT_BUILDER),
        "script_json_requirement": _prompt_file_or_default(SCRIPT_JSON_REQUIREMENT_PATH, SCRIPT_JSON_REQUIREMENT),
        "voiceover_polish_prompt": _prompt_file_or_default(VOICEOVER_POLISH_PROMPT_PATH, VOICEOVER_POLISH_PROMPT),
    }


def default_deterministic_episode_prompt_template() -> str:
    return """你是中文知识类短视频脚本导演。请基于【本集切分 PDF/Markdown 原文】生成一集完整脚本。

【基本信息】
- 书名：{book_title}
- 集数：{episode_no}
- 本集标题：{episode_title}
- 预计时长：整章脚本阶段不按单条视频时长压缩；后续分集拆分再控制每条 2.5～4 分钟
- 原文范围：{source_labels}
- 大纲切入点：{hook}
- 大纲要点：
{main_points}
- 关键案例库：
{key_examples}

【生成原则】
1. 先完整理解本集正文，再写脚本；不要只复述大纲，不要只抓一两个戏剧化片段。
1A. 对《贫穷的本质》这类社科/发展经济学作品，默认受众是没有受过社会经济学学术训练、但关心贫富差距如何产生并维持、希望理解并打破阶层固化处境的普通人。脚本必须通俗易懂、形象生动，从原书具体例子入手引人入胜，再解释背后的经济学机制，不要先讲抽象概念。
2. 系统会在输入前去掉注释、参考文献、图片占位、脚注编号等非剧情内容；这些内容不要写进脚本。
3. 必须充分覆盖本集核心事件、人物关系、制度背景、作者判断、重要转折、典型例证、因果链条和后续影响；不能只写大结论。
4. 先把原文切成 8～18 个“叙事/论证段落群”，再按这些段落群展开 B 系正文；每个段落群至少有 4～8 条 B 句，重要段落群可以更多。
5. A1 只负责开篇钩子和本集落点；B 系正文负责充分解读原文，允许完整展开，不在整章脚本阶段压缩。
6. 完播率优化只在后续分集拆分阶段控制单条视频时长；整章脚本可以有很多 B 句，分集时再拆成多个 2.5～4 分钟短集。
7. 对超过 30 页的章节，B 系正文不得少于 100 条，建议 120 条左右；超过 20 页通常不少于 75 条，建议 90 条左右。不要把 30 多页原文压成 40 条左右的摘要。
8. 每 6～8 个 B 句形成一个小段落逻辑：事实 → 原因 → 影响 → 转折/追问。要有具体人物、动作、事件和制度后果。
9. 台词要“精彩”但不能编造：用反常识问题、具体场景、关键冲突和因果推进增强可看性；不要用“疯狂、无情、彻底”等词替代事实。
10. 输出必须是合法 JSON，不要 Markdown，不要代码围栏，不要解释。
11. 为防止长章节 JSON 过大，脚本生成阶段不要输出 image_prompts，image_prompts 请输出空数组 []；绘图提示词会在分集、润色后由系统按最终台词重建。
12. full_script 不要重复粘贴全部 voiceover；可以写空字符串 ""，系统会用 voiceover 自动合成完整口播稿。
13. 每一句 B 系台词都要短、清楚、适合配音，并绑定一个 image_id。
14. 生图 prompt 遇到伤害、病因、死亡、传闻等内容，后续绘图阶段会用间接画面表达；本阶段只负责台词，不负责生图 prompt。
15. A1 第一句话必须点睛本章：直接提出本集最值得看的问题、反差或人物处境，不要先寒暄、铺背景或写“本章主要讲”。
16. 开头三句话内必须自然亮出书名和一句精简标签。标签只能来自已知信息或输入上下文，不得编造奖项、销量、出版史或名人评价。例：《贫穷的本质》可写成“2019 年诺贝尔经济学奖相关的反贫困研究代表作”；《万历十五年》可写成“黄仁宇的历史经典”。信息不足时，用“这本社科经典/历史经典/文学经典”即可。
17. 正文要多用原书里的具体例子支撑结论。不要连续写“作者认为/这说明/由此可见”式摘要；每个抽象判断后，都要尽量接一个具体场景、人物选择、制度后果、田野观察、实验/数据证据或原书细节。
18. 如果“关键案例库”不为空，必须优先展开其中案例，并写进 source_coverage_checklist。每个关键案例至少用 2～4 条 B 系台词讲清：例子是什么、对比在哪里、为什么重要、它支撑什么结论。
19. 对社科/经济学书，不能把蚊帐防疟疾、免费赠送与自费购买、疫苗接种、驱虫、小额激励、家庭预算等典型例子压缩成抽象概括。原文或关键案例库出现这些对象时，必须保留具体对象和对比关系。
""".strip()


def summarize_episode_for_shared_cover(episode: Episode) -> str:
    parts: list[str] = []
    hook = clean_prefix(episode.hook, ["切入点：", "hook:", "Hook:"]).strip()
    if hook:
        parts.append(f"核心冲突：{hook}")
    for point in (episode.main_points or [])[:4]:
        point = str(point).strip()
        if point:
            parts.append(point)
    for example in (episode.key_examples or [])[:3]:
        example = str(example).strip()
        if example:
            parts.append(f"关键案例：{example}")
    if episode.source_labels:
        parts.append("原文参考：" + "；".join([str(x).strip() for x in episode.source_labels[:3] if str(x).strip()]))
    return "；".join(parts)


def build_shared_ac_master_prompt(book_title: str, episode: Episode, chapter_summary: str) -> str:
    manuscript = (
        f"书名：《{book_title}》\n"
        f"本集标题：{episode.title}\n"
        f"切入点：{episode.hook}\n"
        f"主要内容：{'；'.join([str(x).strip() for x in (episode.main_points or []) if str(x).strip()])}\n"
        f"参考范围：{'；'.join([str(x).strip() for x in (episode.source_labels or []) if str(x).strip()])}\n"
        f"本集摘要：{chapter_summary}"
    ).strip()
    template = _prompt_file_or_default(AC_MASTER_PROMPT_PATH, default_ac_master_prompt())
    return fill_template(template, manuscript=manuscript, book_title=book_title, episode_title=episode.title, chapter_summary=chapter_summary)


def generate_cover_title_from_voiceover(script_data: dict[str, Any], episode: Episode, book_title: str = "") -> str:
    """根据整集台词生成一个更凝练的封面标题，并保存供后处理配置文件使用。
    这里采用稳定的本地规则，避免新增一轮模型调用带来的不稳定。
    """
    texts: list[str] = []
    for item in script_data.get("voiceover") or []:
        image_id = str(item.get("image_id") or "").strip()
        text = clean_prefix(str(item.get("text") or "").strip(), ["切入点：", "hook:", "Hook:"]).strip()
        if not text or image_id == "C":
            continue
        texts.append(text)
    whole = "".join(texts)
    chapter_name = re.sub(r"^第\s*[0-9一二三四五六七八九十百]+\s*[期集章回]\s*[：:]\s*", "", episode.title).strip() or episode.title
    episode_label_match = re.match(r"^(第\s*[0-9一二三四五六七八九十百]+\s*[期集章回])", episode.title.strip())
    episode_label = episode_label_match.group(1).replace(" ", "") if episode_label_match else ""

    candidates: list[str] = []
    hook = clean_prefix(episode.hook, ["切入点：", "hook:", "Hook:"]).strip()
    if hook:
        candidates.append(hook)
    if chapter_name:
        candidates.append(chapter_name)

    # 常见历史解读标题压缩规则：尽量变成一个简短疑问句或判断句。
    patterns = [
        (r"不上朝", "皇帝为何不上朝？"),
        (r"太子|国本", "皇帝连太子都定不了？"),
        (r"牌坊|牌位", "皇帝只是个牌位？"),
        (r"首辅|和稀泥", "首辅为什么只能和稀泥？"),
        (r"张居正|抄家", "张居正为何死后被清算？"),
        (r"海瑞", "清官海瑞为何做不好官？"),
        (r"戚继光|送礼", "戚继光为何也得送礼？"),
        (r"李贽|自杀|割喉", "李贽为何把自己逼上绝路？"),
        (r"1587|毫无意义", "1587年，真的是无事之秋吗？"),
    ]
    for pat, title in patterns:
        if re.search(pat, whole) or re.search(pat, hook) or re.search(pat, chapter_name):
            candidates.insert(0, title)
            break

    for cand in candidates:
        cand = re.sub(r'[“”"《》【】]', '', cand)
        cand = re.sub(r"^第\s*[0-9一二三四五六七八九十百]+\s*[期集章回]\s*[：:|｜-]*\s*", "", cand)
        cand = cand.strip("。！？!?；;，,：: ")
        if not cand:
            continue
        if len(cand) > 18:
            # 取更短、更适合封面的核心标题
            cand = re.split(r"[，。；：:？！!?]", cand)[0].strip()
        if len(cand) > 20:
            cand = cand[:20].rstrip("，。；：:？！!?")
        if cand and not re.search(r"[？?]$", cand) and ("为何" in cand or "怎么" in cand or "谁" in cand or "吗" in cand or "能" in cand or "为什么" in cand):
            cand += "？"
        return f"{episode_label}｜{cand}".strip("｜") if episode_label else cand

    fallback = chapter_name or (book_title and f"读懂《{book_title}》") or "这一期我们讲什么？"
    fallback = fallback[:18].rstrip("，。；：:？！!?")
    return f"{episode_label}｜{fallback}".strip("｜") if episode_label else fallback
def build_default_closing_line(book_title: str, episode: Episode, next_episode: Episode | None = None, next_summary: str = "") -> str:
    follow_sentence = copywriting_brand_texts()["follow_sentence"]
    next_title = _clean_sentence_text(getattr(next_episode, "title", "") if next_episode else "", max_chars=64)
    summary = _clean_sentence_text(next_summary or _summary_from_episode_outline(next_episode), max_chars=64)
    # 默认 C 预告以下一集标题为语义锚点；摘要只作兜底，避免预告含义和下一章/下一集标题不一致。
    if next_title:
        teaser = f"下一期看{next_title}。"
    elif summary:
        teaser = f"下一期看{summary}。"
    else:
        teaser = f"这一期先讲到这里，后面继续读《{book_title}》。" if book_title else "这一期先讲到这里，后面继续把这本书读下去。"
    return f"{teaser}{follow_sentence}"



def best_chapter_label_for_cover(episode: Episode) -> str:
    """Prefer a source label that contains a chapter marker for cover chapter fields."""
    candidates = [str(x or "").strip() for x in (episode.source_labels or [])]
    candidates.append(str(episode.title or "").strip())
    for item in candidates:
        if re.search(r"第\s*[0-9一二三四五六七八九十百]+\s*[章节回篇部卷]", item):
            return item
    return str(episode.title or "").strip()


def extract_next_teaser_for_endcard(script_data: dict[str, Any]) -> str:
    """Extract a concise next-episode teaser from the C narration line for the end card."""
    voiceover = script_data.get("voiceover") or []
    closing = ""
    if isinstance(voiceover, list):
        for item in voiceover:
            if str((item or {}).get("image_id") or "").strip() == "C":
                closing = str((item or {}).get("text") or "")
                break
    text = re.sub(r"\s+", "", closing or "")
    if not text:
        return "下一期内容待更新"
    # Remove CTAs and keep just the preview content.
    for marker in ["想继续把经典", "如果你也对经典", "欢迎关注【", "记得关注【", "让我们把经典读给你听", "更细的来龙去脉", "想读完整", "想看完整", "下方链接", "原著", "原书", "支持我们", "支持创作"]:
        idx = text.find(marker)
        if idx > 0:
            text = text[:idx]
            break
        if idx == 0:
            text = ""
            break
    m = re.search(r"(?:下一期|下期)[^：:]{0,80}[：:](.+)$", text)
    if m:
        text = m.group(1)
    text = text.strip("。；;，,：:")
    return text or "下一期内容待更新"

def ensure_standard_cover_end_assets(script_data: dict[str, Any], episode: Episode, book_title: str, next_episode: Episode | None = None, next_summary: str = "") -> dict[str, Any]:
    data = dict(script_data or {})
    voiceover = [dict(x) for x in (data.get("voiceover") or [])]
    raw_prompts = [dict(x) for x in (data.get("image_prompts") or [])]

    if not any(str(x.get("image_id") or "").strip() == "A1" for x in voiceover):
        voiceover.insert(0, {"image_id": "A1", "text": build_default_opening_line(book_title, episode)})
    closing_line = build_default_closing_line(book_title, episode, next_episode, next_summary=next_summary)
    has_c = False
    for item in voiceover:
        if str(item.get("image_id") or "").strip() == "C":
            item["text"] = closing_line
            has_c = True
    if not has_c:
        voiceover.append({"image_id": "C", "text": closing_line})

    chapter_summary = summarize_episode_for_shared_cover(episode)
    prompts: list[dict[str, Any]] = []
    seen_a1 = False
    for item in raw_prompts:
        image_id = str(item.get("image_id") or "").strip()
        if image_id == "C":
            continue  # C 系末页直接复用 A1 共用母图，不单独生图
        if image_id == "A1":
            if seen_a1:
                continue
            seen_a1 = True
            item["name"] = "A1_A与C共享底图"
        prompts.append(item)

    if not seen_a1:
        prompts.insert(0, {
            "image_id": "A1",
            "name": "A1_A与C共享母图",
            "prompt": build_shared_ac_master_prompt(book_title, episode, chapter_summary),
        })

    for item in prompts:
        image_id = str(item.get("image_id") or "").strip()
        prompt = str(item.get("prompt") or "").strip()
        if not prompt:
            continue
        if image_id == "A1":
            extra = generation_rule("image_prompts.a1_postprocess_constraint")
            if extra.strip() not in prompt:
                item["prompt"] = prompt + extra
        else:
            extra = generation_rule("image_prompts.general_postprocess_constraint")
            if extra.strip() not in prompt:
                item["prompt"] = prompt + extra

    data["voiceover"] = voiceover
    data["image_prompts"] = prompts
    data["shared_ac_source"] = "A1"
    auto_cover_title = generate_cover_title_from_voiceover(data, episode, book_title)
    data["cover_title_auto"] = auto_cover_title
    if not str(data.get("cover_title_final") or "").strip():
        data["cover_title_final"] = auto_cover_title
    return data


def seconds_to_lrc_timestamp(total_seconds: int) -> str:
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    return f"{minutes:02d}:{seconds:02d}.00"


def _estimate_lrc_seconds(text: str, default_seconds: int = 6) -> int:
    """Estimate a practical LRC step from Chinese narration length."""
    try:
        chars = len(re.sub(r"\s+", "", str(text or "")))
        return max(3, min(12, round(chars / 5.5) or int(default_seconds)))
    except Exception:
        return max(1, int(default_seconds))


def build_voiceover_lrc(script_data: dict[str, Any], step_seconds: int = 6) -> str:
    blocks: list[str] = []
    current = 0
    for item in script_data.get("voiceover") or []:
        image_id = str(item.get("image_id") or "").strip()
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        ts = seconds_to_lrc_timestamp(current)
        prefix = f"【{image_id}】" if image_id else ""
        blocks.append(f"[{ts}]{prefix}{text}")
        current += _estimate_lrc_seconds(text, default_seconds=step_seconds)
    return "\n".join(blocks).strip() + "\n"


def _norm_for_repeat_check(text: str) -> str:
    return re.sub(r"[\s，,。！？!?；;：:\-—_《》【】\"\'“”‘’]+", "", str(text or ""))


def _too_repetitive_opening(opening: str, first_body: str) -> bool:
    a = _norm_for_repeat_check(opening)
    b = _norm_for_repeat_check(first_body)
    if not a or not b:
        return False
    if len(a) >= 18 and a[:18] in b:
        return True
    if len(b) >= 18 and b[:18] in a:
        return True
    # 若 A1 和 B01 前半段高度重合，说明钩子/开头和正文重复。
    prefix_a = a[:28]
    prefix_b = b[:28]
    if len(prefix_a) >= 12 and len(prefix_b) >= 12:
        overlap = sum(1 for ch in prefix_a if ch in prefix_b) / max(1, min(len(prefix_a), len(prefix_b)))
        return overlap > 0.82
    return False


def _non_repeating_opening(book_title: str, episode: Episode | None, first_body: str) -> str:
    if episode is not None:
        hook = _clean_sentence_text(clean_prefix(episode.hook, ["切入点：", "hook:", "Hook:"]), max_chars=40)
        title = _clean_sentence_text(episode.title, max_chars=32)
        candidate = f"这一集先看一个关键问题：{hook or title}。"
        if not _too_repetitive_opening(candidate, first_body):
            return candidate
        return f"这一集继续读《{book_title or '这本书'}》，先抓住{title or '这一章'}里最关键的一处转折。"
    return "这一集先从最关键的一处转折讲起。"


def enforce_ab_c_numbering(script_data: dict[str, Any], episode: Episode | None = None, book_title: str = "") -> dict[str, Any]:
    """Hard rule: A=cover, B=content, C=end.

    - Only A1 is allowed for cover/opening.
    - All middle narration is renumbered B01, B02...
    - C is only ending narration.
    - image_prompts only keep A1 and B-series. C is generated by postprocess, not by image model.
    """
    data = dict(script_data or {})
    original_voiceover = [dict(x) for x in (data.get("voiceover") or [])]
    original_prompts = [dict(x) for x in (data.get("image_prompts") or [])]
    prompt_map = {str(p.get("image_id") or "").strip(): dict(p) for p in original_prompts if str(p.get("image_id") or "").strip()}

    a_text = ""
    content_items: list[dict[str, str]] = []
    c_text = ""

    for item in original_voiceover:
        old_id = str(item.get("image_id") or "").strip()
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        if old_id == "A1" and not a_text:
            a_text = text
        elif old_id == "C" and not c_text:
            c_text = text
        else:
            # Any A2/A01/A02/other accidental content id is treated as B-series content.
            content_items.append({"old_id": old_id, "text": text})

    if not a_text and episode is not None:
        a_text = build_default_opening_line(book_title, episode)
    elif not a_text:
        a_text = "这一期，我们从这本书的关键问题讲起。"

    if not c_text:
        c_text = f"这一期就到这里。{copywriting_brand_texts()['follow_sentence']}"

    if content_items and _too_repetitive_opening(a_text, content_items[0].get("text", "")):
        a_text = _non_repeating_opening(book_title, episode, content_items[0].get("text", ""))

    new_voiceover = [{"image_id": "A1", "text": a_text}]
    id_map: dict[str, str] = {}
    for idx, item in enumerate(content_items, start=1):
        new_id = f"B{idx:02d}"
        old_id = item.get("old_id") or new_id
        id_map[old_id] = new_id
        new_voiceover.append({"image_id": new_id, "text": item["text"]})
    new_voiceover.append({"image_id": "C", "text": c_text})

    new_prompts: list[dict[str, Any]] = []

    a_prompt = dict(prompt_map.get("A1") or {})
    if a_prompt:
        a_prompt["image_id"] = "A1"
        a_prompt["name"] = "A1_A与C共享底图"
        new_prompts.append(a_prompt)

    for idx, item in enumerate(content_items, start=1):
        new_id = f"B{idx:02d}"
        old_id = item.get("old_id") or new_id
        prompt_item = dict(prompt_map.get(old_id) or prompt_map.get(new_id) or {})
        if prompt_item:
            prompt_item["image_id"] = new_id
            prompt_item["name"] = f"{new_id}_内容"
            new_prompts.append(prompt_item)

    data["voiceover"] = new_voiceover
    data["image_prompts"] = new_prompts
    data["shared_ac_source"] = "A1"
    return data



def _compact_prompt_text(text: str, max_chars: int = 120) -> str:
    """Keep a narration line usable inside an image prompt without making it a wall of text."""
    value = re.sub(r"\s+", "", str(text or "")).strip()
    value = re.sub(r"^[【\[]?[A-Z]\d*[】\]]", "", value).strip()
    if len(value) > max_chars:
        value = value[: max_chars - 1].rstrip("，,；;、 ") + "…"
    return value




def _infer_book_genre(book_title: str = "", episode_title: str = "", text: str = "") -> str:
    """Infer broad book genre for adaptive prompts and visuals.

    This is a lightweight deterministic guardrail. The LLM still decides the
    detailed outline/script, but local prompt rebuilding must not hard-code a
    single visual style such as Ming-history palace imagery for every book.
    """
    source = " ".join([str(book_title or ""), str(episode_title or ""), str(text or "")]).lower()
    checks: list[tuple[str, tuple[str, ...]]] = [
        ("social_science", ("贫穷的本质", "poor economics", "poverty", "发展经济学", "随机对照", "rct", "社会学", "政治学", "公共政策", "贫穷陷阱", "小额信贷", "微贷", "扶贫", "贫困", "穷人")),
        ("business", ("商业", "管理", "创业", "战略", "组织", "增长", "品牌", "营销", "公司", "企业", "产品", "用户", "领导力", "business", "management", "startup")),
        ("psychology", ("心理", "认知", "情绪", "行为", "习惯", "决策", "偏见", "大脑", "mental", "psychology", "behavior")),
        ("science", ("科学", "物理", "化学", "生物", "宇宙", "技术", "算法", "人工智能", "ai", "physics", "biology", "technology", "science")),
        ("finance", ("投资", "金融", "经济", "股票", "债券", "财富", "市场", "交易", "货币", "finance", "investing", "economics")),
        ("philosophy", ("哲学", "伦理", "意义", "存在", "自由", "理性", "思想", "philosophy")),
        ("literature", ("小说", "文学", "诗", "散文", "人物命运", "人物", "命运", "故事", "情节", "叙事", "主人公", "福贵", "余华", "fiction", "novel", "literature")),
        ("biography", ("传记", "自传", "回忆录", "人物传", "biography", "memoir")),
        ("history", ("历史", "王朝", "皇帝", "朝廷", "明代", "清代", "宋代", "唐代", "战争", "帝国", "万历", "张居正", "海瑞")),
        ("health", ("医学", "健康", "疾病", "营养", "睡眠", "运动", "医疗", "medicine", "health")),
        ("education", ("教育", "学习", "学校", "课堂", "老师", "学生", "education", "learning")),
    ]
    for genre, keys in checks:
        if any(k in source for k in keys):
            return genre
    return "general"


def _is_poor_economics_book(book_title: str = "", episode_title: str = "", text: str = "") -> bool:
    return _infer_book_genre(book_title=book_title, episode_title=episode_title, text=text) == "social_science" and any(
        k in " ".join([str(book_title or ""), str(episode_title or ""), str(text or "")]).lower()
        for k in ["贫穷的本质", "poor economics", "poverty", "发展经济学", "随机对照", "rct", "贫穷陷阱", "小额信贷"]
    )


def _genre_label_zh(genre: str) -> str:
    return {
        "history": "历史人文",
        "social_science": "社会科学/发展经济学/公共政策",
        "business": "商业管理/组织战略",
        "psychology": "心理学/行为科学",
        "science": "科学技术/知识科普",
        "finance": "财经投资/经济金融",
        "philosophy": "哲学思想/观念解读",
        "literature": "文学/小说/人物命运",
        "biography": "人物传记/人生叙事",
        "health": "医学健康/生活科学",
        "education": "教育学习/成长",
        "general": "经典读书/知识解读",
    }.get(str(genre or "general"), "经典读书/知识解读")


def _infer_social_science_scene_from_voiceover(text: str, *, episode_title: str = "", book_title: str = "") -> str:
    line_source = str(text or "")
    source = " ".join([line_source, str(episode_title or ""), str(book_title or "")])
    rules: list[tuple[tuple[str, ...], str]] = [
        (("蚊帐", "疟疾", "malaria", "非洲", "免费赠送", "免费发放", "自费购买", "公益组织"), "非洲乡村家庭或社区卫生点的克制插画：床边挂起蚊帐，家人和儿童只用远景或背影；卫生人员在公共卫生点发放蚊帐，旁边用家庭账本、市场摊位或两条分岔路径表现“免费发放”和“自费购买”的选择差异；可用诊所或病房远景提示疟疾风险，但不画病痛特写、脏乱猎奇或可识别真人肖像"),
        (("驱虫", "寄生虫", "校医", "儿童健康", "上课缺席"), "学校和基层卫生场景的组合画面：教室、校医桌、儿童远景、药盒轮廓和出勤表样式的抽象色块，表现低成本健康干预如何影响上学与长期机会，不画病体特写"),
        (("吃饭", "看病", "借钱", "孩子上学", "不努力", "懒", "每天", "艰难选择"), "发展经济学纪录片式综合场景：一张家庭桌面上有账本、零钱、药盒、饭碗、孩子书本和公共服务表格，背景远处虚化连接诊所、学校、市场或公共服务窗口，表现低收入家庭每天在吃饭、看病、借钱和上学之间做取舍；画面尊重、明亮、具体，不把贫穷画成脏乱或抽象标签"),
        (("贫穷陷阱", "陷阱", "收入", "增长", "曲线", "阈值"), "干净的抽象曲线图意象、简化坐标、阶梯和分叉道路，旁边是远景中的普通家庭与小摊，表现收入门槛和选择困境"),
        (("饥饿", "吃得饱", "营养", "粮食", "卡路里", "大米", "食物"), "乡村家庭的简朴餐桌、米袋、市场摊位和朴素厨房，表现食物选择与营养问题，克制、尊重、不卖惨"),
        (("健康", "疫苗", "接种", "诊所", "护士", "医生", "蚊帐", "药", "腹泻", "净水", "医疗"), "基层诊所或公共卫生点，护士背影、排队人群远景、药箱、蚊帐或净水容器，表现低成本健康干预的现实场景"),
        (("教育", "学校", "老师", "学生", "课堂", "上学", "识字", "辅导", "全班"), "简朴教室、黑板、课桌、老师与学生远景，表现教育资源、学习差距和课堂互动"),
        (("小额信贷", "微贷", "贷款", "借贷", "还款", "利息", "债务"), "社区小额信贷小组会议、账本、计算器、手写表格和小店门口的远景，表现金融工具与现实约束"),
        (("储蓄", "存钱", "存款", "账户", "银行", "现金", "收入"), "小商铺柜台、存钱罐、账本、手机或简洁银行窗口远景，表现储蓄难题与日常现金流"),
        (("保险", "风险", "旱灾", "灾害", "失业", "疾病", "冲击"), "干旱田地、阴云、家庭账本和公共服务窗口的组合画面，表现风险冲击与保障不足"),
        (("生育", "孩子", "家庭", "女性", "女孩", "婚姻"), "家庭院落或社区公共空间的远景，女性、儿童与长辈的非特写群像，表现家庭决策与代际选择，避免凝视和刻板贫困"),
        (("创业", "企业", "小店", "生意", "摊贩", "赤脚资本家", "利润"), "街边小店、摊位、简易库存、账本和店主背影，表现微型生意的收益和限制"),
        (("制度", "政策", "腐败", "政府", "援助", "补贴", "执行", "项目"), "基层办公室、公告栏、表格、排队窗口和政策文件轮廓，表现政策执行与制度摩擦"),
        (("实验", "随机", "对照", "研究", "数据", "证据", "调查"), "研究人员背影、问卷夹板、地图、简洁数据点和村庄远景，表现田野实验和证据推理"),
        (("价格", "激励", "补贴", "免费", "成本", "选择"), "市场摊位、价签形状的抽象图标、家庭账本和分岔路径，表现价格激励如何改变选择"),
    ]
    for keys, scene in rules:
        if any(k in line_source for k in keys):
            return scene
    for keys, scene in rules:
        if any(k in source for k in keys):
            return scene
    return "社会科学纪录片式场景：普通家庭、学校、诊所、市场、小店、基层办公室或田野调查现场，画面必须服务本句台词的具体问题、证据或政策含义，避免泛泛摆拍"


def _infer_adaptive_nonhistory_scene_from_voiceover(text: str, *, episode_title: str = "", book_title: str = "", genre: str = "general") -> str:
    line = str(text or "")
    source = " ".join([line, str(episode_title or ""), str(book_title or "")])
    rules_by_genre: dict[str, list[tuple[tuple[str, ...], str]]] = {
        "business": [
            (("增长", "用户", "产品", "市场", "品牌"), "现代办公室或产品白板，增长曲线、用户路径、团队讨论远景，表现商业问题和决策取舍"),
            (("组织", "管理", "领导", "团队", "流程"), "会议室、流程图、团队协作和项目看板的克制场景，表现组织运转与管理张力"),
            (("创业", "公司", "融资", "利润"), "创业团队、小型办公室、电脑、账本和市场数据的组合画面，表现创业现实约束"),
        ],
        "psychology": [
            (("习惯", "行为", "选择", "偏见", "决策"), "人物远景与抽象分岔路径、便签、日常物件和柔和光线，表现心理机制如何影响选择"),
            (("情绪", "焦虑", "压力", "关系"), "安静室内、窗边侧影、交错线条和柔和阴影，表现情绪和关系张力，不画痛苦特写"),
        ],
        "science": [
            (("实验", "数据", "算法", "模型"), "实验室或数据可视化空间，简洁图表、仪器轮廓、研究人员远景，表现科学证据和模型推理"),
            (("宇宙", "物理", "生物", "技术"), "自然现象、显微结构、星空或科技设备的干净画面，表现科学概念，不生成可读文字"),
        ],
        "finance": [
            (("投资", "市场", "股票", "风险", "收益"), "简洁金融图表、账本、电脑屏幕轮廓和城市远景，表现市场波动与风险收益"),
            (("财富", "储蓄", "债务", "现金"), "家庭账本、存钱罐、银行卡和清楚克制的桌面静物，表现财务选择与长期规划"),
        ],
        "philosophy": [
            (("自由", "意义", "伦理", "理性", "存在"), "安静书房、开放门廊、抽象光影和人物背影，表现思想问题和观念冲突"),
        ],
        "literature": [
            (("命运", "人物", "爱情", "家庭", "冲突"), "电影感的生活场景、人物远景、室内外空间关系，表现人物命运和情感张力"),
            (("城市", "乡村", "旅程", "回忆"), "具有文学氛围的街道、房间、道路或旧物，表现叙事空间和时间流动"),
        ],
        "biography": [
            (("童年", "成长", "转折", "事业", "选择"), "人物剪影、时间线式构图、书桌、照片轮廓和关键场景远景，表现人生转折"),
        ],
        "health": [
            (("疾病", "健康", "睡眠", "营养", "运动"), "干净诊室、生活方式场景、餐桌、床边光线或运动远景，表现健康机制，不画病体特写"),
        ],
        "education": [
            (("学习", "课堂", "老师", "学生", "考试", "成长"), "教室、书桌、黑板、学生远景和学习材料，表现教育问题和成长路径"),
        ],
        "general": [
            (("问题", "为什么", "关键", "机制", "证据"), "现代知识解读场景：书桌、便签、简洁图表、人物背影和抽象路径，表现问题拆解和思考过程"),
        ],
    }
    rules = rules_by_genre.get(genre, []) + rules_by_genre.get("general", [])
    for keys, scene in rules:
        if any(k in line for k in keys):
            return scene
    for keys, scene in rules:
        if any(k in source for k in keys):
            return scene
    return f"{_genre_label_zh(genre)}读书解读场景：根据本句台词选择人物、空间、物件、数据或抽象隐喻，画面必须服务这一句的具体含义，不要套用固定模板"


def _adaptive_style_block(text: str, *, genre: str = "general") -> str:
    source = str(text or "")
    if genre == "history":
        if any(k in source for k in ["流言", "传言", "矛盾", "不愿", "躲避", "束缚", "争", "弹劾", "清算"]):
            mood = "克制紧张、有暗线和压迫感"
        elif any(k in source for k in ["大婚", "婚姻", "后宫", "皇后", "嫔妃"]):
            mood = "庄重、华丽但压抑，礼制感强"
        else:
            mood = "沉稳、厚重、可信"
        return f"画面气质要与台词语气一致：{mood}；整体是历史人文/经典解读风格的钢笔淡彩或水墨插画，线条清晰、色块分明、手绘感强。色调由内容决定，不默认昏暗或黑金暗红；可用自然光、古纸色、青绿、朱红、金色点缀或冷暖对比，但每种颜色都要服务人物关系、空间压力或事件含义。画面元素必须来自台词中的人物、地点、物件、制度、冲突或证据，不添加无关装饰、随机符号、空泛光效。不是写实照片也非3D渲染，不夸张、不玄幻、不营销。"
    if genre == "social_science":
        return _social_science_style_block(source)
    if genre in {"business", "finance"}:
        mood = "清晰、克制、有决策感和现实压力"
    elif genre == "psychology":
        mood = "细腻、安静、有心理张力但不过度戏剧化"
    elif genre == "science":
        mood = "理性、清楚、证据感强，有科普纪录片质感"
    elif genre == "literature":
        mood = "电影感、人物感、情绪克制，有文学氛围"
    elif genre == "philosophy":
        mood = "安静、抽象、留白，有思想感"
    elif genre == "biography":
        mood = "人物纪实感、时间感和关键转折感"
    else:
        mood = "沉稳、可信、有知识解读质感"
    return f"画面气质要与台词语气一致：{mood}；整体是{_genre_label_zh(genre)}风格的钢笔淡彩/水墨/扁平矢量插画，构图干净、手绘质感。色彩可以更丰富，但必须由内容决定；可用明亮自然光、克制暖色、冷暖对比或数据新闻式色块，不默认昏暗。每个元素都要对应台词里的对象、关系、证据、选择、冲突或概念；删除无关装饰、空泛氛围、随机图标和泛泛背景。不是写实照片也非3D渲染，不夸张、不玄幻、不营销。"


def _social_science_style_block(text: str) -> str:
    source = str(text or "")
    if any(k in source for k in ["反直觉", "误解", "陷阱", "矛盾", "问题在于", "为什么"]):
        mood = "带有反常识张力，清楚、克制、有思考感"
    elif any(k in source for k in ["实验", "数据", "证据", "研究", "随机"]):
        mood = "理性、清晰、证据感强，像经济学插图和数据新闻的结合"
    elif any(k in source for k in ["健康", "教育", "饥饿", "家庭", "风险"]):
        mood = "温和、尊重、真实，不煽情不卖惨"
    else:
        mood = "沉稳、可信、有公共议题质感"
    return f"画面气质要与台词语气一致：{mood}；整体是社会科学/发展经济学读书解读的钢笔淡彩/扁平矢量插画风格（接近数据新闻和公共议题插图），构图清楚、手绘质感。台词一旦出现具体案例，就优先画案例里的具体人、地点、物件和对比关系，例如非洲家庭、蚊帐、疟疾防治、公益组织免费发放与家庭自费购买的差别；如果台词同时提到吃饭、看病、借钱、孩子上学，应画家庭账本、零钱、药盒、饭碗、书本、诊所/学校/市场远景组成的选择场景，不要只画教室或黑板。不要泛化成空洞的贫困背景、抽象图标或公共卫生宣传画。色彩可以更丰富，但要服务具体机制：家庭预算、健康选择、教育机会、风险、时间成本、公共服务或信息差；可以用明亮现实空间、暖色、冷暖对比和清晰色块，不默认昏暗，也不卖惨。画面中的每个物件都必须对应台词含义，不添加无关人物、建筑、符号、装饰光效或泛泛贫困背景。不是写实照片也非3D渲染，不夸张、不玄幻、不营销。"



def _infer_visual_scene_from_voiceover(text: str, *, episode_title: str = "", book_title: str = "") -> str:
    """Infer a concrete, line-bound visual scene from narration keywords."""
    genre = _infer_book_genre(book_title=book_title, episode_title=episode_title, text=text)
    if genre == "social_science":
        return _infer_social_science_scene_from_voiceover(text, episode_title=episode_title, book_title=book_title)
    if genre != "history":
        return _infer_adaptive_nonhistory_scene_from_voiceover(text, episode_title=episode_title, book_title=book_title, genre=genre)

    line_source = str(text or "")
    source = " ".join([line_source, str(episode_title or ""), str(book_title or "")])
    rules: list[tuple[tuple[str, ...], str]] = [
        (("大婚", "婚姻", "皇后", "嫔妃", "后宫"), "明代宫廷婚礼或后宫帘幕的克制场面，红金礼制元素、宫灯、屏风和人物远景，表现婚姻背后的制度压力"),
        (("国本", "太子", "储君", "立储", "皇长子"), "朝堂与东宫之间的权力拉扯，文官奏疏、宫门深处的皇子剪影、压低的宫廷光线，表现储位争议"),
        (("流言", "传言", "议论", "讹传", "说法"), "宫门长廊或朝房外的低声议论，几名文官侧影、半掩的奏疏与阴影，表现传闻在朝廷中扩散"),
        (("病", "药", "脚", "抓破", "火气", "奇痒", "不便"), "内廷寝殿或药案，药碗、帘幕后模糊人影、太医器具和低光环境，表现皇帝以身体不适为由无法临朝"),
        (("申时行", "首辅", "内阁", "调和", "文官集团", "朝臣"), "内阁书房或朝堂侧殿，首辅与文官群像、奏疏堆叠、烛光书案，表现夹在皇帝与文官之间的调和压力"),
        (("张居正", "抄家", "清算", "弹劾"), "府门封条、散落奏疏、昏暗宅院与官员背影，表现权臣身后遭清算的历史余波"),
        (("礼仪", "礼制", "制度", "规矩", "束缚", "祖制"), "礼制卷轴、朝服队列、宫廷仪仗与压迫感强的殿门，表现制度和礼仪对人的约束"),
        (("奏疏", "奏章", "弹劾", "上疏", "批红"), "书案上层层奏疏、朱批痕迹、官员执笔剪影和烛光，表现文书政治与朝廷压力"),
        (("万历", "皇帝", "天子", "临朝", "早朝", "朝会", "午朝"), "明代宫廷朝堂，御座或龙椅保持距离感，文官队列、空旷殿阶与皇帝背影，表现皇权与礼制的张力"),
        (("军", "戚继光", "边防", "战争", "将领"), "边关城墙、军旗、盔甲和将领远景，以克制但清楚的历史战场气氛表现军事处境"),
        (("海瑞", "清官", "官场", "县衙"), "县衙或简朴书房，清官背影、案牍、暗色木桌和冷静光线，表现官场伦理与现实冲突"),
        (("财政", "赋税", "银", "土地", "民生"), "账册、银锭、田亩图、乡民远景与官府书案，表现财政和民生压力"),
    ]
    for keys, scene in rules:
        if any(k in line_source for k in keys):
            return scene
    for keys, scene in rules:
        if any(k in source for k in keys):
            return scene
    return "历史人文读书解读场景：根据本句台词选择人物远景、历史空间、书案、制度器物或地图等元素，服务这一句的具体含义，避免泛泛宫殿背景"


def _image_prompt_style_block(text: str) -> str:
    genre = _infer_book_genre(text=text)
    return _adaptive_style_block(text, genre=genre)


def _genre_safety_rule(genre: str) -> str:
    if genre == "social_science":
        return "如果台词涉及疾病、医疗、饥饿、儿童、贫困处境，只用诊所、课堂、市场、家庭空间、账本、公共服务窗口和人物远景间接表达；不画痛苦特写、病体特写、脏乱猎奇或可识别真人肖像。"
    if genre in {"health", "psychology"}:
        return "如果台词涉及疾病、身体、心理压力、创伤或治疗，只用干净空间、生活物件、人物远景或抽象隐喻表达；不画病体特写、痛苦特写、危险行为或可识别真人肖像。"
    if genre == "literature":
        return "如果台词涉及死亡、暴力、疾病或强烈情绪，只用环境、物件、背影和光影间接表达；不画血腥、危险行为或身体特写。"
    if genre == "history":
        return "如果台词涉及身体不适、意外、传闻或病因，只能用药案、帘幕、宫门、奏疏和人物远景间接表达，不画身体特写或医学细节。"
    return "如果台词涉及疾病、伤害、灾难、暴力或敏感处境，只用环境、物件、数据、人物远景或抽象隐喻间接表达；不画血腥、危险行为、痛苦特写或可识别真人肖像。"


def _magazine_b_page_prompt_constraint() -> str:
    return (
        "Editorial magazine-page direction: compose this as a premium illustrated magazine inner page, "
        "not a poster, screenshot, slide, or card grid. Use one clear focal scene, disciplined negative space, "
        "layered foreground/midground/background, subtle editorial color accents, and stable 9:16 safe margins. "
        "Do not add readable text, labels, logo, watermark, UI, decorative clutter, or unrelated symbols. "
        "Every visible element must serve the exact narration line."
    )


def build_voiceover_bound_image_prompt(
    image_id: str,
    text: str,
    *,
    book_title: str = "",
    episode_title: str = "",
    is_a1: bool = False,
    previous_prompt: str = "",
) -> str:
    """Build a drawing prompt from the final narration line, then safety-sanitize it."""
    raw_line = _compact_prompt_text(text, 130 if not is_a1 else 100)
    line = _replace_image_prompt_risky_terms(raw_line)
    genre = _infer_book_genre(book_title=book_title, episode_title=episode_title, text=text)
    genre_label = _genre_label_zh(genre)
    scene = _infer_visual_scene_from_voiceover(text, episode_title=episode_title, book_title=book_title)
    style = _adaptive_style_block(" ".join([text, book_title, episode_title]), genre=genre)
    no_text_rule = generation_rule("image_prompts.no_text_rule", "不要在画面中生成任何可识别文字、标题、书名、作者名、字幕、logo、水印、印章字或大段书法。")
    safety_rule = _genre_safety_rule(genre)
    template_vars = {
        "image_id": image_id,
        "line": line,
        "genre": genre,
        "genre_label": genre_label,
        "scene": scene,
        "style": style,
        "safety_rule": safety_rule,
        "no_text_rule": no_text_rule,
        "book_title": book_title,
        "episode_title": episode_title,
    }

    if is_a1:
        base = str(previous_prompt or "").strip()
        if not base:
            base = fill_template(generation_rule("image_prompts.a1_base"), **template_vars)
        prompt = fill_template(generation_rule("image_prompts.a1_template"), base=base, **template_vars).strip()
        return sanitize_image_prompt_for_safety(prompt)

    if genre == "history":
        prompt = fill_template(generation_rule("image_prompts.history_template"), **template_vars).strip()
    else:
        prompt = fill_template(generation_rule("image_prompts.general_template"), **template_vars).strip()
    if re.match(r"^B\d+$", str(image_id or "").strip()):
        prompt = f"{prompt}\n{_magazine_b_page_prompt_constraint()}"
    return sanitize_image_prompt_for_safety(prompt)


def rebuild_image_prompts_from_voiceover(
    script_data: dict[str, Any],
    *,
    book_title: str = "",
    episode: "Episode | None" = None,
    episode_title: str = "",
) -> dict[str, Any]:
    """Regenerate A1/B image prompts after narration polish.

    Voiceover polish may rewrite A1/B lines, so old image prompts can become stale.
    This guard makes `04_绘图提示词` reflect the final saved narration exactly.
    """
    data = dict(script_data or {})
    voiceover = [dict(x) for x in (data.get("voiceover") or []) if isinstance(x, dict)]
    old_prompts = [dict(x) for x in (data.get("image_prompts") or []) if isinstance(x, dict)]
    old_map = {str(x.get("image_id") or "").strip(): x for x in old_prompts if str(x.get("image_id") or "").strip()}
    title = str(episode_title or (episode.title if episode is not None else "") or data.get("title") or "").strip()
    rebuilt: list[dict[str, Any]] = []
    for item in voiceover:
        image_id = str(item.get("image_id") or "").strip()
        text = str(item.get("text") or "").strip()
        if not image_id or not text or image_id == "C":
            continue
        if image_id == "A1":
            prev = str((old_map.get("A1") or {}).get("prompt") or "").strip()
            rebuilt.append({
                "image_id": "A1",
                "name": "A1_A与C共享底图",
                "voiceover_text": text,
                "prompt": build_voiceover_bound_image_prompt("A1", text, book_title=book_title, episode_title=title, is_a1=True, previous_prompt=prev),
                "prompt_source": "rebuilt_from_final_voiceover",
            })
            continue
        if not re.match(r"^B\d+$", image_id):
            continue
        rebuilt.append({
            "image_id": image_id,
            "name": f"{image_id}_内容",
            "voiceover_text": text,
            "prompt": build_voiceover_bound_image_prompt(image_id, text, book_title=book_title, episode_title=title),
            "prompt_source": "rebuilt_from_final_voiceover",
        })
    data["image_prompts"] = rebuilt
    data["image_prompt_policy"] = "all_A1_B_prompts_rebuilt_from_final_voiceover; C_has_no_image_prompt"
    return data

def align_image_prompts_with_voiceover(script_data: dict[str, Any], book_title: str = "") -> dict[str, Any]:
    """Make image_prompts match A/B/C roles.

    A1 = cover/shared base.
    Bxx = content images, each mapped to one narration line.
    C = ending card, no image prompt, generated by postprocess from A1 shared base.
    """
    data = dict(script_data or {})
    voiceover = [dict(x) for x in (data.get("voiceover") or [])]
    prompts = [dict(x) for x in (data.get("image_prompts") or [])]
    prompt_map = {str(item.get("image_id") or "").strip(): dict(item) for item in prompts if str(item.get("image_id") or "").strip()}
    aligned: list[dict[str, Any]] = []

    # A1: cover/shared base only.
    if any(str(v.get("image_id") or "").strip() == "A1" for v in voiceover):
        if "A1" in prompt_map:
            a1 = dict(prompt_map["A1"])
            a1["image_id"] = "A1"
            a1["name"] = "A1_A与C共享底图"
            aligned.append(a1)

    for item in voiceover:
        image_id = str(item.get("image_id") or "").strip()
        text = str(item.get("text") or "").strip()
        if image_id in {"A1", "C"}:
            continue
        if not image_id.startswith("B"):
            continue
        prompt_item = dict(prompt_map.get(image_id) or {})
        if not prompt_item:
            prompt_item = {
                "image_id": image_id,
                "name": f"{image_id}_内容",
                "prompt": f"竖屏 9:16，著作解读短视频正文内容画面。直接表现这句台词所讲的内容：{text}"
            }
        else:
            prompt_item["image_id"] = image_id
            prompt_item["name"] = f"{image_id}_内容"
            existing = str(prompt_item.get("prompt") or "").strip()
            anchor = f"这张图必须直接对应这句台词：{text}。"
            if anchor not in existing:
                prompt_item["prompt"] = (existing + " " + anchor).strip()
        aligned.append(prompt_item)

    # de-duplicate by image_id, preserving A1 then B order. Never include C here.
    dedup: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in aligned:
        image_id = str(item.get("image_id") or "").strip()
        if not image_id or image_id == "C" or image_id in seen:
            continue
        if image_id != "A1" and not image_id.startswith("B"):
            continue
        seen.add(image_id)
        dedup.append(item)
    data["image_prompts"] = dedup
    # After any voiceover polish/renumbering, old prompts may no longer match the final lines.
    # Rebuild from the saved A1/B narration so drawing prompts reflect the exact台词和风格.
    return rebuild_image_prompts_from_voiceover(data, book_title=book_title)


def save_script_outputs(episode_dir: Path, script_data: dict[str, Any]) -> None:
    # Hard stop: never write Response(id=...) SDK dumps into user-facing files.
    assert_not_sdk_response_dump(str((script_data or {}).get("full_script") or ""), "full_script")
    for item in (script_data or {}).get("voiceover") or []:
        if isinstance(item, dict):
            assert_not_sdk_response_dump(str(item.get("text") or ""), f"voiceover {item.get('image_id') or ''}")
    lrc_text = build_voiceover_lrc(script_data, step_seconds=6)
    data_to_save = dict(script_data or {})
    data_to_save["voiceover_lrc"] = lrc_text
    write_json(episode_dir / "02_脚本.json", data_to_save)
    write_text(episode_dir / "02_完整脚本.txt", str(script_data.get("full_script") or ""))

    coverage_items = script_data.get("source_coverage_checklist") or script_data.get("coverage_checklist") or script_data.get("原文覆盖清单") or []
    if isinstance(coverage_items, list) and coverage_items:
        write_text(episode_dir / "02_原文覆盖清单.txt", "\n".join(f"{i+1}. {str(item).strip()}" for i, item in enumerate(coverage_items) if str(item).strip()) + "\n")

    voice_lines = []
    numbered_voice_lines = []
    for idx, item in enumerate(script_data.get("voiceover") or [], start=1):
        line = f"【{item.get('image_id', '')}】{item.get('text', '')}".strip()
        voice_lines.append(line)
        numbered_voice_lines.append(f"{idx:03d}. {line}".strip())
    write_text(episode_dir / "03_台词.txt", "\n".join(voice_lines).strip() + "\n")
    write_text(episode_dir / "03_台词_有序号.txt", "\n".join(numbered_voice_lines).strip() + "\n")
    write_text(episode_dir / "03_台词.lrc", lrc_text)

    prompt_lines = []
    for item in script_data.get("image_prompts") or []:
        prompt_lines.append(f"## {item.get('image_id', '')} {item.get('name', '')}\n{item.get('prompt', '')}".strip())
    write_text(episode_dir / "04_绘图提示词.txt", "\n\n".join(prompt_lines).strip() + "\n")
    write_json(episode_dir / "04_绘图提示词.json", script_data.get("image_prompts") or [])


# =========================
# Main workflow
# =========================

@dataclass
class PipelineArgs:
    book: Path
    out: Path
    episode_count: int = 0
    page_offset: int = 0

    # Backwards-compatible global text settings.
    # If a stage-specific setting is empty, the workflow falls back to these.
    provider: str = "gemini"
    text_model: str = DEFAULT_GEMINI_FAST_MODEL
    api_key: str = ""

    # Stage-specific text model settings.
    outline_provider: str = "gemini"
    outline_model: str = DEFAULT_GEMINI_FAST_MODEL
    outline_api_key: str = ""
    episode_prompt_provider: str = "openai"
    episode_prompt_model: str = DEFAULT_OPENAI_TEXT_MODEL
    episode_prompt_api_key: str = ""
    script_provider: str = "openai"
    script_model: str = DEFAULT_OPENAI_PRO_MODEL
    script_api_key: str = ""
    polish_provider: str = "deepseek"
    polish_model: str = DEEPSEEK_DEFAULT_MODEL
    polish_api_key: str = ""

    # Polish sub-stage settings
    transition_provider: str = "deepseek"
    transition_model: str = DEEPSEEK_DEFAULT_MODEL
    transition_api_key: str = ""
    split_polish_provider: str = "deepseek"
    split_polish_model: str = DEEPSEEK_DEFAULT_MODEL
    split_polish_api_key: str = ""
    final_polish_provider: str = "deepseek"
    final_polish_model: str = DEEPSEEK_DEFAULT_MODEL
    final_polish_api_key: str = ""
    book_summary_provider: str = "deepseek"
    book_summary_model: str = DEEPSEEK_DEFAULT_MODEL
    book_summary_api_key: str = ""

    image_provider: str = "openai"
    image_model: str = DEFAULT_OPENAI_IMAGE_MODEL
    image_api_key: str = ""
    skip_outline: Path | None = None
    skip_images: bool = True
    max_retries: int = 4
    outline_prompt: str = OUTLINE_PROMPT
    episode_prompt_builder: str = EPISODE_PROMPT_BUILDER
    script_json_requirement: str = SCRIPT_JSON_REQUIREMENT
    voiceover_polish_prompt: str = VOICEOVER_POLISH_PROMPT
    image_interval_seconds: str = "3-8"
    local_parse_mode: str = "auto"
    mineru_backend: str = DEFAULT_MINERU_BACKEND
    mineru_api_url: str = DEFAULT_MINERU_API_URL
    mineru_cache_dir: str = ""
    auto_resume: bool = True
    skip_existing_text: bool = True
    skip_existing_images: bool = True
    only_missing_images: bool = False
    only_postprocess: bool = False
    start_episode_no: int = 1
    start_stage: str = "outline"
    continue_from_folder: Path | None = None
    split_assets: bool = True
    test_b_image_limit: int = 0
    stop_event: Any = None

    def stage_settings(self, stage: str) -> tuple[str, str, str]:
        """Return provider/model/key for one text stage with safe fallbacks.

        stage values: outline, episode_prompt, script, polish.
        """
        mapping = {
            "outline": (self.outline_provider, self.outline_model, self.outline_api_key),
            "episode_prompt": (self.episode_prompt_provider, self.episode_prompt_model, self.episode_prompt_api_key),
            "script": (self.script_provider, self.script_model, self.script_api_key),
            "polish": (self.polish_provider, self.polish_model, self.polish_api_key),
            "transition": (self.transition_provider, self.transition_model, self.transition_api_key),
            "split_polish": (self.split_polish_provider, self.split_polish_model, self.split_polish_api_key),
            "final_polish": (self.final_polish_provider, self.final_polish_model, self.final_polish_api_key),
            "book_summary": (self.book_summary_provider, self.book_summary_model, self.book_summary_api_key),
        }
        provider, model, key = mapping.get(stage, ("", "", ""))
        provider = (provider or self.provider or "gemini").strip()
        # Only reuse the legacy/global text_model when it belongs to the same provider.
        # Otherwise a blank Doubao/OpenAI stage could accidentally inherit Gemini's default model name.
        global_provider = (self.provider or "gemini").strip()
        fallback_model = self.text_model if provider == global_provider else ""
        model = (model or fallback_model or "").strip()
        key = (key or self.api_key or "").strip()
        if provider == "gemini":
            if not model:
                model = DEFAULT_GEMINI_FAST_MODEL
            model = canonical_gemini_model(model)
        elif provider == "openai" and not model:
            model = DEFAULT_OPENAI_TEXT_MODEL
        elif provider == "doubao":
            if not model:
                model = doubao_env_model()
            if model and doubao_model_looks_like_api_key(model):
                raise RuntimeError(
                    "豆包/火山方舟的模型名栏应填写推理接入点 ID（通常 ep- 开头）或可直连 Model ID（doubao- 开头），"
                    "不要把 API Key 填到模型名栏。API Key 请填写在下方“豆包/火山方舟 API Key”。"
                )
        return provider, model, key


PIPELINE_STAGE_ORDER = ["outline", "split_pdf", "episode_prompt", "script", "polish", "images", "postprocess", "split_assets"]


def pipeline_stage_rank(stage: str) -> int:
    try:
        return PIPELINE_STAGE_ORDER.index((stage or "outline").strip())
    except ValueError:
        return 0


def should_reuse_existing(args: "PipelineArgs", stage: str, required_paths: list[Path], *, kind: str = "text") -> bool:
    if not required_paths or not all(p.exists() for p in required_paths):
        return False
    stage_rank = pipeline_stage_rank(stage)
    start_rank = pipeline_stage_rank(args.start_stage)
    if args.only_postprocess and stage_rank < pipeline_stage_rank("postprocess"):
        return True
    if args.only_missing_images and stage_rank < pipeline_stage_rank("images"):
        return True
    # 选择“从某步骤开始”时，该步骤及后续步骤应重新执行；只有前置步骤复用。
    # 否则用户把台词润色切到豆包后，旧的 02/03/04 文件会被自动续跑逻辑挡住，导致润色根本不调用。
    if start_rank > 0:
        return stage_rank < start_rank
    if kind == "image":
        return bool(args.skip_existing_images or args.only_missing_images)
    return bool(args.auto_resume or args.skip_existing_text)


def load_or_scan_image_result(episode_dir: Path, script_data: dict[str, Any]) -> dict[str, Any]:
    stored = read_json_file(episode_dir / "05_配图生成结果.json", default=None)
    if isinstance(stored, dict) and stored.get("results"):
        return stored
    images_dir = episode_dir / "images"
    results: list[dict[str, Any]] = []
    shared_ac_source = str(script_data.get("shared_ac_source") or "A1").strip() or "A1"
    for item in script_data.get("image_prompts") or []:
        image_id = str(item.get("image_id") or "image").strip()
        if image_id == "C":
            continue
        name = safe_filename(str(item.get("name") or image_id), fallback=image_id)
        png_path = images_dir / f"{name}.png"
        # 只有真实 PNG 才算已完成配图；.prompt.txt 只是提示词记录，不能当成图片。
        if png_path.exists():
            expected_size = default_image_size_for_id(image_id, shared_ac_source)
            _enhance_generated_image_file(png_path, expected_size)
            results.append({
                "image_id": image_id,
                "name": name,
                "ok": True,
                "path": str(png_path),
                "size": expected_size,
                "quality": default_image_quality(),
                "reused": True,
            })
    return {"images_dir": str(images_dir), "shared_ac_source": shared_ac_source, "results": results}



def _source_page_span_from_context(local_chapter_context: str | None, episode: Episode | None = None) -> int:
    """Estimate source page span so long chapters cannot be accepted as tiny summaries."""
    text = str(local_chapter_context or "")
    pages: list[int] = []
    for key in ("start_page", "end_page"):
        for m in re.finditer(rf'"{key}"\s*:\s*(\d+)', text):
            try:
                pages.append(int(m.group(1)))
            except Exception:
                pass
    if pages:
        return max(pages) - min(pages) + 1
    if episode is not None:
        vals: list[int] = []
        for rng in getattr(episode, "source_ranges", []) or []:
            if isinstance(rng, dict):
                for key in ("start_page", "end_page", "start", "end"):
                    try:
                        value = int(rng.get(key) or 0)
                        if value > 0:
                            vals.append(value)
                    except Exception:
                        pass
        if vals:
            return max(vals) - min(vals) + 1
    return 0


def _clean_source_char_count(local_chapter_context: str | None) -> int:
    text = str(local_chapter_context or "")
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"==>picture.*?omitted<==", "", text, flags=re.I)
    return len(text)


def _min_b_lines_for_source(local_chapter_context: str | None, episode: Episode | None = None) -> int:
    pages = _source_page_span_from_context(local_chapter_context, episode)
    chars = _clean_source_char_count(local_chapter_context)
    # 这是整章脚本的“覆盖下限”，不是压缩目标。
    # 整章脚本允许充分展开；后续再由拆分流程切成多个短视频。
    if pages >= 30 or chars >= 70000:
        return int(os.getenv("AMP_MIN_B_LINES_LONG_CHAPTER", "100"))
    if pages >= 20 or chars >= 45000:
        return int(os.getenv("AMP_MIN_B_LINES_MEDIUM_CHAPTER", "75"))
    if pages >= 10 or chars >= 22000:
        return int(os.getenv("AMP_MIN_B_LINES_SHORT_CHAPTER", "50"))
    if pages >= 5 or chars >= 9000:
        return int(os.getenv("AMP_MIN_B_LINES_SMALL_CHAPTER", "25"))
    return int(os.getenv("AMP_MIN_B_LINES_TINY_CHAPTER", "10"))


def _target_b_lines_for_source(local_chapter_context: str | None, episode: Episode | None = None) -> int:
    """Preferred length for comprehensive chapter scripts. Split stage controls video length later."""
    min_b = _min_b_lines_for_source(local_chapter_context, episode)
    pages = _source_page_span_from_context(local_chapter_context, episode)
    chars = _clean_source_char_count(local_chapter_context)
    if pages >= 30 or chars >= 70000:
        return int(os.getenv("AMP_TARGET_B_LINES_LONG_CHAPTER", str(max(min_b + 20, 120))))
    if pages >= 20 or chars >= 45000:
        return int(os.getenv("AMP_TARGET_B_LINES_MEDIUM_CHAPTER", str(max(min_b + 15, 90))))
    if pages >= 10 or chars >= 22000:
        return int(os.getenv("AMP_TARGET_B_LINES_SHORT_CHAPTER", str(max(min_b + 10, 60))))
    return int(os.getenv("AMP_TARGET_B_LINES_DEFAULT", str(max(min_b, 30))))



def _voiceover_b_line_count(script_data: dict[str, Any]) -> int:
    count = 0
    for item in script_data.get("voiceover") or []:
        image_id = str((item or {}).get("image_id") or "").strip().upper()
        text = str((item or {}).get("text") or "").strip()
        if image_id.startswith("B") and text:
            count += 1
    return count


def script_source_coverage_status(script_data: dict[str, Any], local_chapter_context: str | None = None, episode: Episode | None = None) -> tuple[bool, str]:
    """Return whether script is long/deep enough to be treated as complete.

    This prevents a long source chapter from being cached as A1+B01+B02+C and then
    blocking later image generation. It intentionally checks only coarse signals:
    B-line count, full_script length, and optional source_coverage_checklist.
    """
    data = script_data or {}
    # Any SDK Response dump in full_script/voiceover means the previous model call
    # failed; treat it as incomplete so resume will rebuild instead of reuse.
    if looks_like_sdk_response_dump(str(data.get("full_script") or "")):
        return False, "full_script 含有 SDK Response(id=...) 失败对象，不是有效脚本"
    for item in data.get("voiceover") or []:
        if isinstance(item, dict) and looks_like_sdk_response_dump(str(item.get("text") or "")):
            return False, f"{item.get('image_id') or 'voiceover'} 含有 SDK Response(id=...) 失败对象，不是有效台词"
    b_count = _voiceover_b_line_count(data)
    min_b = _min_b_lines_for_source(local_chapter_context, episode)
    pages = _source_page_span_from_context(local_chapter_context, episode)
    chars = _clean_source_char_count(local_chapter_context)
    full_len = len(str(data.get("full_script") or "").strip())
    checklist = data.get("source_coverage_checklist") or data.get("coverage_checklist") or data.get("原文覆盖清单") or []
    checklist_len = len(checklist) if isinstance(checklist, list) else 0
    if b_count < min_b:
        return False, f"B系正文只有 {b_count} 句，低于本章完整性下限 {min_b} 句（页数约 {pages}，文本约 {chars} 字符）"
    if (pages >= 10 or chars >= 22000) and full_len < 1200:
        return False, f"full_script 过短（{full_len} 字），不像完整解读本章原文"
    required_checklist = 0
    if pages >= 30 or chars >= 70000:
        required_checklist = int(os.getenv("AMP_MIN_COVERAGE_CHECKLIST_LONG", "14"))
    elif pages >= 20 or chars >= 45000:
        required_checklist = int(os.getenv("AMP_MIN_COVERAGE_CHECKLIST_MEDIUM", "12"))
    elif pages >= 10 or chars >= 22000:
        required_checklist = int(os.getenv("AMP_MIN_COVERAGE_CHECKLIST_SHORT", "10"))
    if required_checklist and checklist_len < required_checklist:
        return False, f"source_coverage_checklist 只有 {checklist_len} 项，低于本章覆盖清单下限 {required_checklist} 项"
    return True, f"覆盖检查通过：B系正文 {b_count} 句，下限 {min_b} 句；覆盖清单 {checklist_len} 项；整章脚本不设上限，后续由分集拆分控制单条视频时长"


def build_source_coverage_repair_instruction(script_data: dict[str, Any], local_chapter_context: str | None, episode: Episode | None) -> str:
    ok, reason = script_source_coverage_status(script_data, local_chapter_context, episode)
    min_b = _min_b_lines_for_source(local_chapter_context, episode)
    target_b = _target_b_lines_for_source(local_chapter_context, episode)
    pages = _source_page_span_from_context(local_chapter_context, episode)
    return fill_template(
        generation_rule("script.coverage_repair_instruction"),
        reason=reason,
        min_b=min_b,
        target_b=target_b,
        pages=pages,
    )

def build_outline(client: LLMClient, args: PipelineArgs) -> dict[str, Any]:
    if args.skip_outline:
        raw_text = read_text(args.skip_outline)
        if not raw_text:
            raise RuntimeError(f"无法读取已有大纲：{args.skip_outline}")
        raw_outline = parse_json_loose(raw_text)
        outline = normalize_outline(raw_outline)
        return outline

    local_outline = build_local_chapter_outline(args) if client.is_dry_run() or _env_flag("AMP_LOCAL_CHAPTER_OUTLINE", False) else None
    if local_outline:
        write_text(args.out / "raw_00_模型返回_大纲.txt", "已使用本地章节识别生成大纲；未调用大纲模型。\n")
        write_json(args.out / "raw_00_本地章节大纲.json", local_outline)
        log(f"  ✅ 本地章节大纲生成完成：{len(local_outline.get('episodes') or [])} 集；未调用大纲模型。")
        return local_outline
    if client.is_dry_run():
        log("  ⚠️ dry-run 本地章节识别不足，回退到大纲模型生成。")
    else:
        log("  ▶ 大纲阶段使用模型阅读全文生成故事线大纲；本地章节大纲仅作为显式兜底（AMP_LOCAL_CHAPTER_OUTLINE=1）。")

    prompt = fill_template(args.outline_prompt or OUTLINE_PROMPT, episode_count=str(args.episode_count or ""), image_interval_seconds=args.image_interval_seconds)
    raw = client.generate_text(prompt, pdf_path=args.book, task_name="outline")
    write_text(args.out / "raw_00_模型返回_大纲.txt", raw)
    outline = normalize_outline(parse_json_loose(raw))
    return outline



def build_deterministic_episode_prompt(episode: Episode, *, image_interval_seconds: str = "3-8", book_title: str = "") -> str:
    """Build script prompt locally.

    The old flow used another LLM to write the prompt. If that call returned an
    incomplete SDK Response object, the next script call received Response(id=...)
    as its instruction. A deterministic prompt is safer, cheaper, and easier to
    validate.
    """
    ep = episode.to_dict()
    main_points = ep.get("main_points") or []
    if isinstance(main_points, list):
        main_points_text = "\n".join(f"- {str(x).strip()}" for x in main_points if str(x).strip())
    else:
        main_points_text = str(main_points or "").strip()
    key_examples = ep.get("key_examples") or ep.get("examples") or []
    if isinstance(key_examples, list):
        key_examples_text = "\n".join(f"- {_format_key_example(x)}" for x in key_examples if _format_key_example(x))
    else:
        key_examples_text = str(key_examples or "").strip()
    source_labels = ep.get("source_labels") or []
    if isinstance(source_labels, list):
        source_labels_text = "；".join(str(x).strip() for x in source_labels if str(x).strip())
    else:
        source_labels_text = str(source_labels or "").strip()
    template = _prompt_file_or_default(DETERMINISTIC_EPISODE_PROMPT_PATH, default_deterministic_episode_prompt_template())
    return fill_template(
        template,
        book_title=book_title or "未提供",
        episode_no=f"EP{int(getattr(episode, 'episode_no', 0) or 0):02d}",
        episode_title=getattr(episode, "title", ""),
        source_labels=source_labels_text or "见下方本集 Markdown",
        hook=ep.get("hook") or "",
        main_points=main_points_text or "- 请以本集 Markdown 原文为准提炼要点",
        key_examples=key_examples_text or "- 无；请从本集 Markdown 原文中主动提炼具体案例，不要只写抽象观点",
        image_interval_seconds=image_interval_seconds,
    )


def build_episode_prompt(client: LLMClient, episode: Episode, episode_dir: Path, prompt_builder: str = EPISODE_PROMPT_BUILDER, image_interval_seconds: str = "3-8", book_title: str = "") -> str:
    deterministic = build_deterministic_episode_prompt(
        episode,
        image_interval_seconds=image_interval_seconds,
        book_title=book_title,
    )

    # 分集提示词作为脚本内部阶段，默认跟随脚本模型 gpt-5.5。只有 dry-run 或显式关闭时才使用本地模板。
    if client.is_dry_run() or not _env_flag("AMP_USE_EPISODE_PROMPT_LLM", True):
        write_text(episode_dir / "01_分集脚本生成提示词.txt", deterministic)
        write_text(episode_dir / "raw_01_模型返回_分集提示词.txt", "已使用本地确定性分集提示词；未调用 LLM。")
        return deterministic

    template = prompt_builder or EPISODE_PROMPT_BUILDER
    brand_texts = copywriting_brand_texts()
    prompt = fill_template(
        template,
        episode_json=json.dumps(episode.to_dict(), ensure_ascii=False, indent=2),
        image_interval_seconds=image_interval_seconds,
        image_cadence_note=image_cadence_note(image_interval_seconds),
        book_title=book_title,
        brand_name=brand_texts["brand_name"],
        brand_slogan=brand_texts["brand_slogan"],
        follow_sentence=brand_texts["follow_sentence"],
    )
    try:
        raw = client.generate_text(prompt, task_name=f"episode_prompt_{episode.episode_no:02d}")
        assert_not_sdk_response_dump(raw, "分集提示词生成")
        cleaned = strip_code_fence(raw)
        if looks_like_sdk_response_dump(cleaned) or len(cleaned.strip()) < 200:
            raise RuntimeError("分集提示词生成结果无效。")
    except Exception as exc:
        # 不再让 Response(id=...) 污染后续；但也不中断整章流程。
        write_text(episode_dir / "raw_01_模型返回_分集提示词.txt", f"分集提示词 LLM 生成失败，已回退本地模板：{exc}")
        write_text(episode_dir / "01_分集脚本生成提示词.txt", deterministic)
        return deterministic

    write_text(episode_dir / "01_分集脚本生成提示词.txt", cleaned)
    write_text(episode_dir / "raw_01_模型返回_分集提示词.txt", raw)
    return cleaned


def build_script(
    client: LLMClient,
    episode: Episode,
    episode_prompt: str,
    episode_pdf: Path,
    episode_dir: Path,
    script_json_requirement: str = SCRIPT_JSON_REQUIREMENT,
    image_interval_seconds: str = "3-8",
    book_title: str = "",
    local_chapter_context: str | None = None,
) -> dict[str, Any]:
    requirement = fill_template(
        script_json_requirement or SCRIPT_JSON_REQUIREMENT,
        image_interval_seconds=image_interval_seconds,
        image_cadence_note=image_cadence_note(image_interval_seconds),
        book_title=book_title,
    )
    if looks_like_sdk_response_dump(episode_prompt):
        raise RuntimeError("episode_prompt 含有 Response(id=...) 失败对象，已拒绝进入脚本生成。")
    compact_json_note = generation_rule("script.compact_json_note")
    final_prompt = f"{episode_prompt}\n\n{requirement}{compact_json_note}"
    if local_chapter_context and str(local_chapter_context).strip():
        compact_context, context_stats = prepare_source_context_for_llm(
            str(local_chapter_context).strip(),
            max_chars=_task_context_char_budget(f"script_{episode.episode_no:02d}"),
            label="本集章节正文",
        )
        write_json(episode_dir / "00_输入上下文清洗统计.json", context_stats)
        write_text(episode_dir / "00_章节原文_剧情清洗版.md", compact_context)
        if context_stats.get("removed_chars", 0) > 0:
            log(
                "  🧹 已清洗非剧情上下文："
                f"{context_stats.get('original_chars')} → {context_stats.get('sent_chars')} 字符，"
                f"估算 token：{context_stats.get('approx_input_tokens_before_clean')} → {context_stats.get('approx_input_tokens_after_clean')}"
            )
        local_context_header = fill_template(generation_rule("script.local_context_header"), compact_context=compact_context)
        final_prompt = f"{final_prompt}\n\n{local_context_header}"
        raw = client.generate_text(final_prompt, pdf_path=None, task_name=f"script_{episode.episode_no:02d}")
    else:
        # 没有可复用的章节 Markdown 时，也只允许 client 内部先本地解析/文本提取；
        # PDF 不会直传给任何文本模型。
        raw = client.generate_text(final_prompt, pdf_path=episode_pdf, task_name=f"script_{episode.episode_no:02d}")
    write_text(episode_dir / "raw_02_模型返回_脚本.txt", raw)
    script_data = script_from_model_output(raw, episode)

    # 生成阶段必须充分覆盖原文。若模型只返回摘要，最多补救两轮；仍不达标则停止，避免缓存残缺脚本。
    ok, reason = script_source_coverage_status(script_data, local_chapter_context, episode)
    if not ok and not client.is_dry_run():
        write_text(episode_dir / "raw_02_覆盖检查失败.txt", reason)
        best_data = script_data
        best_reason = reason
        repair_rounds = int(os.getenv("AMP_SCRIPT_COVERAGE_REPAIR_ROUNDS", "2"))
        for round_no in range(1, max(1, repair_rounds) + 1):
            target_b = _target_b_lines_for_source(local_chapter_context, episode)
            current_b = _voiceover_b_line_count(best_data)
            repair_prompt = (
                f"{final_prompt}\n\n"
                f"{build_source_coverage_repair_instruction(best_data, local_chapter_context, episode)}\n"
                f"{fill_template(generation_rule('script.coverage_retry_note'), round_no=round_no, current_b=current_b, target_b=target_b)}"
            )
            raw_retry = client.generate_text(repair_prompt, pdf_path=None if local_chapter_context else episode_pdf, task_name=f"script_{episode.episode_no:02d}_coverage_retry_{round_no}")
            retry_name = "raw_02_模型返回_脚本_覆盖补救.txt" if round_no == 1 else f"raw_02_模型返回_脚本_覆盖补救_{round_no}.txt"
            write_text(episode_dir / retry_name, raw_retry)
            retry_data = script_from_model_output(raw_retry, episode)
            retry_ok, retry_reason = script_source_coverage_status(retry_data, local_chapter_context, episode)
            if _voiceover_b_line_count(retry_data) > _voiceover_b_line_count(best_data):
                best_data = retry_data
                best_reason = retry_reason
            if retry_ok:
                script_data = retry_data
                write_text(episode_dir / "raw_02_覆盖检查结果.txt", retry_reason)
                break
        else:
            script_data = best_data
            final_ok, final_reason = script_source_coverage_status(script_data, local_chapter_context, episode)
            write_text(episode_dir / "raw_02_覆盖检查结果.txt", f"补救后仍未达标：{final_reason}")
            if not final_ok and not _env_flag("AMP_ALLOW_INCOMPLETE_SCRIPT", False):
                raise RuntimeError(f"脚本覆盖原文不足，已停止保存后续产物：{final_reason}")

    return script_data


def polish_voiceover(client: LLMClient, episode: Episode, script_data: dict[str, Any], episode_pdf: Path | None, episode_dir: Path, polish_prompt: str = VOICEOVER_POLISH_PROMPT) -> dict[str, Any]:
    template = (polish_prompt or "").strip()
    if not template:
        write_text(episode_dir / "raw_03_模型返回_台词润色.txt", "已跳过：未配置台词润色提示词。")
        return script_data
    if client.is_dry_run():
        write_text(episode_dir / "raw_03_模型返回_台词润色.txt", "dry-run：不调用模型润色，保留原台词。")
        return script_data

    voiceover_text = voiceover_to_marked_text(script_data)
    prompt = template.replace("{episode_json}", json.dumps(episode.to_dict(), ensure_ascii=False, indent=2))
    prompt = prompt.replace("{script_json}", json.dumps(script_data, ensure_ascii=False, indent=2))
    prompt = prompt.replace("{voiceover_text}", voiceover_text)

    raw = client.generate_text(prompt, pdf_path=episode_pdf, task_name=f"polish_{episode.episode_no:02d}")
    write_text(episode_dir / "raw_03_模型返回_台词润色.txt", raw)

    # Compatibility path: custom/old polish prompts may still ask for a full script JSON.
    try:
        parsed = parse_json_loose(raw)
        if isinstance(parsed, dict):
            return normalize_script_json(parsed, episode)
    except Exception:
        pass

    polished = merge_polished_voiceover_text(raw, script_data)
    if polished is not None:
        return polished

    log("  ⚠️ 台词润色结果无法与原图号逐句对应，已保留原脚本。请查看 raw_03_模型返回_台词润色.txt。")
    return script_data


def _image_provider_can_generate(client: Any) -> bool:
    provider = str(getattr(client, "image_provider", "") or "").lower().strip()
    return provider not in {"", "none", "dry", "dry-run", "mock"}


def _expected_image_prompt_items(script_data: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for item in script_data.get("image_prompts") or []:
        if not isinstance(item, dict):
            continue
        image_id = str(item.get("image_id") or "").strip()
        prompt = str(item.get("prompt") or "").strip()
        if not image_id or image_id == "C" or not prompt:
            continue
        items.append(item)
    return items


def generate_images(client: LLMClient, episode_dir: Path, script_data: dict[str, Any], *, skip_existing: bool = False, only_missing: bool = False, test_b_image_limit: int = 0) -> dict[str, Any]:
    images_dir = episode_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    missing_after: list[dict[str, str]] = []
    shared_ac_source = str(script_data.get("shared_ac_source") or "A1").strip() or "A1"
    can_generate_images = _image_provider_can_generate(client)
    test_b_raw = int(test_b_image_limit or 0)
    test_b_enabled = test_b_raw != 0
    test_b_allowed = max(0, test_b_raw)
    b_seen = 0
    if test_b_enabled:
        log(f"  🧪 快速测试模式：本次允许处理 {test_b_allowed} 张 B 图，A1/后处理/拆分继续执行")
    for item in _expected_image_prompt_items(script_data):
        image_id = str(item.get("image_id") or "image").strip()
        name = safe_filename(str(item.get("name") or image_id), fallback=image_id)
        prompt = str(item.get("prompt") or "").strip()
        save_path = images_dir / f"{name}.png"
        prompt_path = save_path.with_suffix('.prompt.txt')
        size = default_image_size_for_id(image_id, shared_ac_source)
        quality = default_image_quality()

        if test_b_enabled and re.match(r"^B\d+$", image_id):
            b_seen += 1
            if b_seen > test_b_allowed:
                reason = f"快速测试模式：B图只画前 {test_b_allowed} 张"
                missing_after.append({"image_id": image_id, "name": name, "reason": reason})
                results.append({
                    "image_id": image_id,
                    "name": name,
                    "ok": False,
                    "size": size,
                    "quality": quality,
                    "path": "",
                    "missing_image": True,
                    "quick_test_skipped": True,
                })
                log(f"  🧪 跳过测试外 B 图：{image_id} {name}")
                continue

        # 关键修复：.prompt.txt 只是“未生图/失败/干跑”的占位文件，不能算作图片完成。
        # 以前只补缺失图片时看到 .prompt.txt 就跳过，导致每章后续永远补不出真 PNG。
        if (skip_existing or only_missing) and save_path.exists():
            _enhance_generated_image_file(save_path, size)
            results.append({
                "image_id": image_id,
                "name": name,
                "ok": True,
                "size": size,
                "quality": quality,
                "path": str(save_path),
                "reused": True,
            })
            log(f"  ♻️ 复用已有图片并校正尺寸：{image_id} {name} -> {size}")
            continue
        if (skip_existing or only_missing) and (not can_generate_images) and prompt_path.exists():
            # 没有真实生图模型时才把 prompt.txt 视作“提示词已保存”，避免重复写文件。
            results.append({
                "image_id": image_id,
                "name": name,
                "ok": False,
                "size": size,
                "quality": quality,
                "path": str(prompt_path),
                "reused_prompt_only": True,
                "missing_image": True,
            })
            missing_after.append({"image_id": image_id, "name": name, "reason": "只有提示词文件，没有真实图片"})
            log(f"  📝 已有提示词但未生图：{image_id} {name}")
            continue
        if prompt_path.exists() and can_generate_images and not save_path.exists():
            log(f"  🔁 发现旧提示词占位，重新生成图片：{image_id} {name}")

        ok = client.generate_image(prompt, save_path, size=size, quality=quality)
        if ok and prompt_path.exists():
            try:
                prompt_path.unlink()
            except Exception:
                pass
        if not ok:
            missing_after.append({"image_id": image_id, "name": name, "reason": "生图失败，仅保存提示词"})
        results.append({
            "image_id": image_id,
            "name": name,
            "ok": ok,
            "size": size,
            "quality": quality,
            "path": str(save_path if ok else prompt_path),
            "missing_image": not ok,
        })
        log(f"  {'✅' if ok else '📝'} {image_id} {name}")
    expected_count = len(_expected_image_prompt_items(script_data))
    ok_count = len([x for x in results if x.get("ok")])
    payload = {
        "images_dir": str(images_dir),
        "shared_ac_source": shared_ac_source,
        "expected_count": expected_count,
        "ok_count": ok_count,
        "missing_count": max(0, expected_count - ok_count),
        "missing_after": missing_after,
        "test_b_image_limit": test_b_allowed if test_b_enabled else 0,
        "test_b_image_used": min(b_seen, test_b_allowed) if test_b_enabled else 0,
        "results": results,
    }
    if missing_after:
        log(f"  ⚠️ 本章仍缺 {len(missing_after)} 张真图片；已记录到 05_配图生成结果.json，可切到真实生图模型后用‘只补缺失图片’继续。")
    else:
        log(f"  ✅ 本章配图完成：{ok_count}/{expected_count}")
    write_json(episode_dir / "05_配图生成结果.json", payload)
    return payload


def find_image_path(image_result: dict[str, Any], image_id: str) -> Path | None:
    for item in (image_result.get("results") or []):
        if str(item.get("image_id") or "").strip() == image_id:
            p = Path(str(item.get("path") or ""))
            if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"} and p.exists():
                return p
    return None


def build_image_completion_report(index_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize whether every chapter has real generated PNG/JPG/WebP files.

    This report intentionally does not count *.prompt.txt as completed images.
    prompt.txt means a prompt was saved but the image model did not produce a picture.
    """
    chapters: list[dict[str, Any]] = []
    all_complete = True
    for row in index_rows or []:
        image_result = row.get("image_result") if isinstance(row.get("image_result"), dict) else {}
        results = image_result.get("results") if isinstance(image_result.get("results"), list) else []
        expected = int(image_result.get("expected_count") or len(results) or 0)
        ok = int(image_result.get("ok_count") or len([x for x in results if isinstance(x, dict) and x.get("ok")]) or 0)
        missing = image_result.get("missing_after") if isinstance(image_result.get("missing_after"), list) else []
        split_assets = row.get("split_assets") if isinstance(row.get("split_assets"), dict) else {}
        parts = split_assets.get("parts") if isinstance(split_assets.get("parts"), list) else []
        part_rows = []
        for part in parts:
            if not isinstance(part, dict):
                continue
            part_rows.append({
                "part_no": part.get("part_no"),
                "title": part.get("title"),
                "image_count": part.get("image_count"),
                "images_dir": part.get("images_dir"),
            })
        complete = bool(expected > 0 and ok >= expected and not missing)
        # If images were skipped intentionally, mark as incomplete instead of silently passing.
        if image_result.get("skipped") is True:
            complete = False
        if not complete:
            all_complete = False
        chapters.append({
            "episode_no": row.get("episode_no"),
            "title": row.get("title"),
            "folder": row.get("folder"),
            "expected_images": expected,
            "real_images": ok,
            "missing_images": max(0, expected - ok),
            "complete": complete,
            "missing_after": missing,
            "split_parts": part_rows,
        })
    return {"all_chapters_complete": all_complete, "chapters": chapters}


def discover_episode_dirs_from_continue_folder(folder: Path) -> tuple[Path, list[Path]]:
    target = folder.expanduser().resolve()
    if not target.exists():
        raise FileNotFoundError(f"找不到续作文件夹：{target}")
    def _existing_sort_key(p: Path) -> tuple[int, str]:
        no = _episode_no_from_existing_dir(p)
        return (no if no is not None else 999999, p.name)

    if (target / "00_本集大纲.json").exists() and (target / "02_脚本.json").exists():
        return target.parent, [target]
    episodes_root = target / "episodes"
    if episodes_root.exists() and episodes_root.is_dir():
        episode_dirs = sorted([p for p in episodes_root.iterdir() if p.is_dir() and (p / "02_脚本.json").exists()], key=_existing_sort_key)
        if episode_dirs:
            return target, episode_dirs
    # fallback: scan direct children
    episode_dirs = sorted([p for p in target.iterdir() if p.is_dir() and (p / "02_脚本.json").exists()], key=_existing_sort_key)
    if episode_dirs:
        return target, episode_dirs
    raise RuntimeError("指定文件夹中没有找到可续作的分集目录（需要包含 02_脚本.json）。")


def infer_meta_from_existing_project(project_root: Path) -> tuple[str, str]:
    candidates = [project_root]
    if project_root.name.lower() == "episodes" and project_root.parent != project_root:
        candidates.insert(0, project_root.parent)
    elif project_root.parent.name.lower() == "episodes" and project_root.parent.parent != project_root.parent:
        candidates.insert(0, project_root.parent.parent)
    outline = {}
    chosen_root = project_root
    for root in candidates:
        data = read_json_file(root / "00_分集解读大纲.json", default={}) or {}
        if data:
            outline = data
            chosen_root = root
            break
    book_title = normalize_book_title(str(outline.get("book_title") or "").strip())
    if not book_title:
        name_source = chosen_root.name
        if name_source.lower() == "episodes" and chosen_root.parent != chosen_root:
            name_source = chosen_root.parent.name
        book_title = normalize_book_title(name_source)
    author = str(outline.get("author") or "").strip() or guess_author_from_filename(chosen_root.name)
    if not author and chosen_root.parent != chosen_root:
        author = guess_author_from_filename(chosen_root.parent.name)
    return book_title, author


def continue_from_existing_folder(args: PipelineArgs) -> None:
    project_root, episode_dirs = discover_episode_dirs_from_continue_folder(args.continue_from_folder or args.out)
    book_title, book_author = infer_meta_from_existing_project(project_root)
    image_client = LLMClient(ModelConfig(
        provider="dry-run",
        text_model="",
        image_provider=args.image_provider,
        image_model=args.image_model,
        image_api_key=args.image_api_key,
        max_retries=args.max_retries,
        stop_event=args.stop_event,
    ))
    transition_client: LLMClient | None = None
    if getattr(args, "split_assets", True):
        trans_provider, trans_model, trans_key = args.stage_settings("polish")
        transition_client = LLMClient(ModelConfig(
            provider=trans_provider,
            text_model=trans_model,
            api_key=trans_key,
            max_retries=args.max_retries,
            local_parse_mode="auto",
            stop_event=args.stop_event,
        ))
    split_only_mode = str(getattr(args, "start_stage", "") or "").strip() == "split_assets"
    log(f"① 指定文件夹续作模式：{project_root}")
    remaining_test_b_images = max(0, int(args.test_b_image_limit or 0))
    if remaining_test_b_images:
        log(f"   快速测试：整个任务只处理前 {remaining_test_b_images} 张 B 图。")
    if split_only_mode:
        log("   当前起始步骤为 split_assets：只重建每章 3~5 分钟分集、分集 LRC、分集封面/首页与配图；跳过生图和整集封面后处理。")
    else:
        log("   将直接复用其中已有脚本、台词和绘图提示词，继续生图并做封面/片尾后处理。")
    index_rows: list[dict[str, Any]] = []
    deferred_split_tasks: list[dict[str, Any]] = []
    for idx, episode_dir in enumerate(episode_dirs, start=1):
        check_cancelled(args.stop_event)
        episode_json = read_json_file(episode_dir / "00_本集大纲.json", default={}) or {}
        title = str(episode_json.get("title") or episode_dir.name)
        episode_no = int(episode_json.get("episode_no") or idx)
        if episode_no < max(1, int(args.start_episode_no or 1)):
            log(f"  ⏭️ 跳过 EP{episode_no:02d} {title}")
            continue
        log(f"\n=== EP{episode_no:02d} {title}｜从已有脚本继续绘图 ===")
        script_json_path = episode_dir / "02_脚本.json"
        if not script_json_path.exists():
            log("  ⚠️ 缺少 02_脚本.json，无法续作，已跳过。")
            continue
        script_data = read_json_file(script_json_path, default={}) or {}
        if not script_data:
            log("  ⚠️ 脚本 JSON 为空，已跳过。")
            continue
        episode = Episode.from_dict(episode_json or {"title": title}, episode_no)
        local_chapter_context = read_text(episode_dir / "00_章节原文_本地解析.md")
        coverage_ok, coverage_reason = script_source_coverage_status(script_data, local_chapter_context, episode)
        if not coverage_ok:
            log(f"  ⚠️ 已有脚本覆盖原文不足：{coverage_reason}")
            log("     指定文件夹续作默认不重写文本；如需补全本章内容，请从 script 或 polish 阶段重跑，或删除残缺的 02/03/04 文件。")
        # 只做整理，不改写原有台词和脚本内容
        script_data = ensure_standard_cover_end_assets(script_data, episode, book_title, next_episode=None)
        script_data = enforce_ab_c_numbering(script_data, episode=episode, book_title=book_title)
        script_data = align_image_prompts_with_voiceover(script_data, book_title=book_title)
        save_script_outputs(episode_dir, script_data)
        log("  ♻️ 已复用并整理已有脚本 / 台词 / 绘图提示词")

        image_result = {"skipped": True}
        if split_only_mode:
            log("  ▶ split_assets 模式：跳过生图，只扫描已有图片用于分集配图")
            image_result = load_or_scan_image_result(episode_dir, script_data)
        elif args.only_postprocess:
            image_result = load_or_scan_image_result(episode_dir, script_data)
            log("  ▶ 只重做封面/片尾后处理：跳过生图")
        elif args.skip_images and not args.only_missing_images:
            log("  ⏭️ 已跳过生图，仅整理已有脚本与提示词")
            image_result = load_or_scan_image_result(episode_dir, script_data)
        else:
            before_test_b = remaining_test_b_images
            log(f"  ▶ 生图模型：{args.image_provider} / {args.image_model or '默认模型'}")
            image_result = generate_images(
                image_client,
                episode_dir,
                script_data,
                skip_existing=bool(args.skip_existing_images or args.auto_resume),
                only_missing=bool(args.only_missing_images or True),
                test_b_image_limit=(remaining_test_b_images if remaining_test_b_images > 0 else -1) if args.test_b_image_limit else 0,
            )
            if args.test_b_image_limit:
                remaining_test_b_images = max(0, remaining_test_b_images - int(image_result.get("test_b_image_used") or 0))
                if before_test_b and not remaining_test_b_images:
                    log("  🧪 快速测试 B 图额度已用完；后续章节只跑文本/后处理/拆分，不再处理 B 图。")

        card_result = {"skipped": True}
        if split_only_mode:
            card_result = {"skipped": True, "reason": "split_assets 模式跳过整集封面后处理"}
        else:
            try:
                if not image_result.get("results"):
                    image_result = load_or_scan_image_result(episode_dir, script_data)
                base_cover = find_image_path(image_result, "A1")
                base_end = base_cover
                if base_cover is None:
                    raise RuntimeError("未找到 A1 母图，无法生成 A/C 封面与片尾。")
                card_result = create_cover_and_endcards(
                    episode_dir,
                    base_cover,
                    base_end,
                    book_title=book_title,
                    author=book_author,
                    episode_title=title,
                    hook=episode.hook,
                    cover_title=str(script_data.get("cover_title_final") or script_data.get("cover_title_auto") or ""),
                    next_teaser=extract_next_teaser_for_endcard(script_data),
                    chapter_label=best_chapter_label_for_cover(episode),
                )
                log("  ✅ 已完成封面/片尾后处理")
            except Exception as exc:
                card_result = {"error": str(exc)}
                log(f"  ⚠️ 封面/片尾后处理失败：{exc}")

        split_result = {"skipped": True}
        if getattr(args, "split_assets", True) and script_data:
            # 拆分脚本延后到所有章节脚本都生成之后再做。这样某章最后一集做下集预告时，
            # 可以读取下一章第一集的台词，而不是只能退回固定套话或 C 片尾。
            try:
                script_data.setdefault("source_chapter_label", best_chapter_label_for_cover(episode))
                script_data.setdefault("source_labels", episode.source_labels)
                script_data.setdefault("book_title", book_title)
                script_data.setdefault("book_author", book_author)
                script_data.setdefault("outline_episode_title", episode.title)
            except Exception:
                pass
            deferred_split_tasks.append({"episode_no": episode.episode_no, "episode_dir": episode_dir, "script_data": script_data})
            split_result = {"pending": True, "reason": "等待全部章节脚本生成后统一拆分，以便跨章读取下一章第一集内容。"}

        index_rows.append({
            "episode_no": episode_no,
            "title": title,
            "folder": str(episode_dir),
            "script": str(script_json_path),
            "voiceover": str(episode_dir / "03_台词.txt"),
            "voiceover_lrc": str(episode_dir / "03_台词.lrc"),
            "image_prompts": str(episode_dir / "04_绘图提示词.txt"),
            "image_result": image_result,
            "cover_endcards": card_result,
            "split_assets": split_result,
        })
        if args.test_b_image_limit:
            log("  🧪 测试运行：本集完成；继续扫描后续已有集用于统一拆分/打包/邮件，B 图额度用完后不再生成 B 图。")
    if getattr(args, "split_assets", True) and deferred_split_tasks:
        trans_provider, trans_model, _ = args.stage_settings("transition")
        split_polish_provider_log, split_polish_model_log, _ = args.stage_settings("split_polish")
        final_polish_provider_log, final_polish_model_log, _ = args.stage_settings("final_polish")
        book_summary_provider_log, book_summary_model_log, _ = args.stage_settings("book_summary")
        log(f"\n⑦ 统一生成拆分脚本、分集 LRC、分集封面/首页与对应图片。")
        log(f"  承接过渡模型：{trans_provider} / {trans_model or '默认模型'}")
        log(f"  分集润色模型：{split_polish_provider_log} / {split_polish_model_log or '默认模型'}")
        log(f"  终稿润色模型：{final_polish_provider_log} / {final_polish_model_log or '默认模型'}")
        log(f"  全书总结模型：{book_summary_provider_log} / {book_summary_model_log or '默认模型'}")
        transition_client = make_text_client("transition")
        split_polish_client = make_text_client("split_polish")
        final_polish_client = make_text_client("final_polish")
        book_summary_client = make_text_client("book_summary")
        log(f"\n⑦ 统一生成拆分脚本、分集 LRC、分集封面/首页与对应图片：用上一集/下一集台词生成凝练承接与预告，并用台词润色模型做分集一润色；支持跨章读取下一章第一集。承接/润色模型：{trans_provider} / {trans_model or '默认模型'}")
        split_results_by_episode: dict[int, dict[str, Any]] = {}
        ordered_split_tasks = sorted(deferred_split_tasks, key=lambda t: int(t.get("episode_no") or 0))
        for task_index, task in enumerate(ordered_split_tasks):
            check_cancelled(args.stop_event)
            ep_no = int(task.get("episode_no") or 0)
            ep_dir = Path(task.get("episode_dir"))
            prev_ep_dir = Path(ordered_split_tasks[task_index - 1].get("episode_dir")) if task_index > 0 else None
            next_ep_dir = Path(ordered_split_tasks[task_index + 1].get("episode_dir")) if task_index + 1 < len(ordered_split_tasks) else None
            latest_script = read_json_file(ep_dir / "02_脚本.json", default=None) or task.get("script_data") or {}
            try:
                result = split_episode_scripts_and_images(
                    ep_dir,
                    latest_script,
                    transition_client=transition_client,
                    split_polish_client=split_polish_client,
                    final_polish_client=final_polish_client,
                    book_summary_client=book_summary_client,
                    prev_episode_dir=prev_ep_dir,
                    next_episode_dir=next_ep_dir,
                    skip_existing_parts=bool(args.auto_resume or args.skip_existing_text or args.only_missing_images or args.only_postprocess or pipeline_stage_rank(args.start_stage) > 0),
                )
                split_results_by_episode[ep_no] = result
                if not result.get("skipped"):
                    log(f"  ✅ EP{ep_no:02d} 已生成拆分脚本、分集 LRC、分集封面/首页与对应图片文件夹")
            except Exception as split_exc:
                split_results_by_episode[ep_no] = {"error": str(split_exc)}
                log(f"  ⚠️ EP{ep_no:02d} 拆分脚本与图片失败：{split_exc}")
                log("".join(traceback.format_exception(type(split_exc), split_exc, split_exc.__traceback__)).rstrip())
        for row in index_rows:
            ep_no = int(row.get("episode_no") or 0)
            if ep_no in split_results_by_episode:
                row["split_assets"] = split_results_by_episode[ep_no]

    write_json(project_root / "index_continue_draw.json", index_rows)
    write_json(project_root / "00_配图完成检查.json", build_image_completion_report(index_rows))
    write_text(project_root / "README_续作绘图.md", "已按指定文件夹续作模式完成：复用已有脚本继续绘图。\n另见 00_配图完成检查.json，里面会标出每章是否仍缺真实 PNG 图片。\n")
    log(f"\n✅ 指定文件夹续作完成。目录：{project_root}")


def run_pipeline(args: PipelineArgs) -> None:
    if args.continue_from_folder is not None:
        return continue_from_existing_folder(args)
    if not args.book.exists():
        raise FileNotFoundError(f"找不到书籍 PDF：{args.book}")
    args.out.mkdir(parents=True, exist_ok=True)

    def make_text_client(stage: str) -> LLMClient:
        provider, model, key = args.stage_settings(stage)
        return LLMClient(ModelConfig(
            provider=provider,
            text_model=model,
            image_provider="none",
            image_model="",
            api_key=key,
            max_retries=args.max_retries,
            local_parse_mode=args.local_parse_mode,
            mineru_backend=args.mineru_backend,
            mineru_api_url=args.mineru_api_url,
            mineru_cache_dir=args.mineru_cache_dir or str(args.out / "_pymupdf4llm_cache"),
            stop_event=args.stop_event,
        ))

    image_client = LLMClient(ModelConfig(
        provider="dry-run",
        text_model="",
        image_provider=args.image_provider,
        image_model=args.image_model,
        image_api_key=args.image_api_key,
        max_retries=args.max_retries,
        stop_event=args.stop_event,
    ))

    check_cancelled(args.stop_event)
    stage_start = str(args.start_stage or "outline")
    if args.only_postprocess:
        stage_start = "postprocess"
    elif args.only_missing_images and pipeline_stage_rank(stage_start) < pipeline_stage_rank("images"):
        stage_start = "images"
    args.start_stage = stage_start
    split_only_mode = pipeline_stage_rank(stage_start) >= pipeline_stage_rank("split_assets")

    log("本地解析策略：大纲阶段和分集脚本阶段都只把本地解析后的 Markdown/文本传给模型，禁止 PDF 直传。")
    if split_only_mode:
        log("当前起始步骤为 split_assets：只重建每章 3~5 分钟分集、分集 LRC、分集封面/首页与配图；不重跑脚本、生图或整集封面后处理。")
    if args.auto_resume or args.skip_existing_text or args.skip_existing_images or args.only_missing_images or args.only_postprocess or args.start_episode_no > 1 or pipeline_stage_rank(stage_start) > 0:
        log(
            f"续作模式：自动断点续跑={'开' if args.auto_resume else '关'}｜复用文本={'开' if args.skip_existing_text else '关'}｜"
            f"复用图片={'开' if args.skip_existing_images else '关'}｜只补缺图={'开' if args.only_missing_images else '关'}｜"
            f"只重做后处理={'开' if args.only_postprocess else '关'}｜从 EP{max(1, args.start_episode_no):02d} / {stage_start} 开始"
        )

    outline_file = args.out / "00_分集解读大纲.json"
    outline_txt = args.out / "00_分集解读大纲_可读.txt"
    nearby_outline = None if args.skip_outline else _find_existing_outline_near_output(args.out)
    if not args.skip_outline and should_reuse_existing(args, "outline", [outline_file]):
        args.skip_outline = outline_file
        log(f"① 复用已有整本书分集解读大纲：{outline_file.name}")
    elif nearby_outline and should_reuse_existing(args, "outline", [nearby_outline]):
        args.skip_outline = nearby_outline
        log(f"① 自动发现并复用已有分集解读大纲：{nearby_outline}")
    else:
        outline_provider, outline_model, _ = args.stage_settings("outline")
        log(f"① 生成/读取整本书分集解读大纲｜模型：{outline_provider} / {outline_model or '默认模型'}")
    outline = build_outline(make_text_client("outline"), args)
    check_cancelled(args.stop_event)
    write_json(outline_file, outline)
    write_text(outline_txt, outline_to_markdown(outline))

    book_title, book_author = infer_book_meta(args.book, outline)
    episodes = [Episode.from_dict(x, idx) for idx, x in enumerate(outline.get("episodes") or [], start=1)]
    log(f"② 共解析到 {len(episodes)} 集，开始按原文分割标签切 PDF 并生成脚本")
    remaining_test_b_images = max(0, int(args.test_b_image_limit or 0))
    if remaining_test_b_images:
        log(f"🧪 快速测试：先生成/复用全文故事线大纲；整个任务只处理前 {remaining_test_b_images} 张 B 图，后续集仍保留文本与拆分视野。")

    index_rows: list[dict[str, Any]] = []
    deferred_split_tasks: list[dict[str, Any]] = []
    for ep_index, episode in enumerate(episodes):
        next_episode = episodes[ep_index + 1] if ep_index + 1 < len(episodes) else None
        check_cancelled(args.stop_event)
        episodes_root = args.out / "episodes"
        ep_name = f"EP{episode.episode_no:02d}_{safe_filename(episode.title, f'episode_{episode.episode_no:02d}') }"
        desired_episode_dir = episodes_root / ep_name
        existing_episode_dir = find_existing_episode_dir_by_no(episodes_root, episode.episode_no)
        episode_dir = existing_episode_dir or desired_episode_dir
        if existing_episode_dir and existing_episode_dir.resolve() != desired_episode_dir.resolve():
            log(f"  ♻️ 按序号复用已有章节目录：{existing_episode_dir.name}（忽略本次小标题差异，不新建 {desired_episode_dir.name}）")
        episode_dir.mkdir(parents=True, exist_ok=True)
        outline_json_path = episode_dir / "00_本集大纲.json"
        if existing_episode_dir and outline_json_path.exists() and (args.auto_resume or args.skip_existing_text or args.only_missing_images or args.only_postprocess or pipeline_stage_rank(stage_start) > 0):
            log("  ♻️ 保留已有本集大纲文件；续作匹配以 EP 序号为准，不以小标题为准")
        else:
            write_json(outline_json_path, episode.to_dict())

        episode_pdf = episode_dir / "00_章节原文_本地解析用.pdf"
        used_ranges_path = episode_dir / "00_实际切分页码.json"
        local_parse_path = episode_dir / "00_章节原文_本地解析.md"
        episode_prompt_path = episode_dir / "01_分集脚本生成提示词.txt"
        script_json_path = episode_dir / "02_脚本.json"
        voiceover_path = episode_dir / "03_台词.txt"
        image_prompts_path = episode_dir / "04_绘图提示词.json"

        log(f"\n=== EP{episode.episode_no:02d} {episode.title} ===")
        if episode.episode_no < max(1, int(args.start_episode_no or 1)):
            log(f"  ⏭️ 按续作设置跳过本集（起始集数为 EP{max(1, int(args.start_episode_no or 1)):02d}）")
            image_result = load_or_scan_image_result(episode_dir, read_json_file(script_json_path, {})) if script_json_path.exists() else {"skipped": True}
            card_dir = episode_dir / "06_封面与片尾"
            index_rows.append({
                "episode_no": episode.episode_no,
                "title": episode.title,
                "folder": str(episode_dir),
                "pdf": str(episode_pdf),
                "script": str(script_json_path),
                "voiceover": str(voiceover_path),
                "image_prompts": str(image_prompts_path),
                "image_result": image_result,
                "cover_endcards": {"dir": str(card_dir)} if card_dir.exists() else {"skipped": True},
            })
            continue

        # split pdf / local parse
        used_ranges = read_json_file(used_ranges_path, default=[]) if used_ranges_path.exists() else []
        if should_reuse_existing(args, "split_pdf", [episode_pdf, used_ranges_path]):
            log(f"  ♻️ 复用已切分 PDF：{episode_pdf.name}，页码 {used_ranges}")
        elif not args.only_postprocess and not args.only_missing_images:
            used_ranges = split_pdf_by_ranges(args.book, episode_pdf, episode.source_ranges, page_offset=0)
            write_json(used_ranges_path, used_ranges)
            log(f"  ✅ 已切分 PDF：{episode_pdf.name}，页码 {used_ranges}")
        else:
            if not episode_pdf.exists():
                used_ranges = split_pdf_by_ranges(args.book, episode_pdf, episode.source_ranges, page_offset=0)
                write_json(used_ranges_path, used_ranges)
                log(f"  ✅ 已补建切分 PDF：{episode_pdf.name}，页码 {used_ranges}")

        local_chapter_context = None
        if local_parse_path.exists() and should_reuse_existing(args, "split_pdf", [local_parse_path]):
            local_chapter_context = read_text(local_parse_path)
            if local_chapter_context.strip():
                log("  ♻️ 复用本集本地解析 Markdown")
        elif not args.only_postprocess and not args.only_missing_images:
            check_cancelled(args.stop_event)
            parse_mode = (args.local_parse_mode or "auto").lower().strip()
            if parse_mode in {"off", "none", "disabled", "false", "0"}:
                log("  ⚠️ 已禁止 PDF 直传：本集解析模式 off 被强制改为 auto。")
                parse_mode = "auto"
            log("  ▶ 本地解析本集 PDF：PyMuPDF4LLM 优先；失败后只回退 pypdf 文本提取，禁止上传 PDF")
            try:
                parsed = try_local_pdf_parse(
                    episode_pdf,
                    mode=parse_mode,
                    parser=args.mineru_backend,
                    cache_dir=args.out / "_pymupdf4llm_cache" / "episodes",
                    max_chars=_int_env("AMP_LOCAL_PARSE_CACHE_CHARS", 120_000),
                )
            except Exception as parse_exc:
                log(f"  ⚠️ PyMuPDF4LLM 本地解析失败，改用 pypdf 文本提取，禁止上传 PDF：{parse_exc}")
                parsed = extract_pdf_text(episode_pdf, max_chars=_int_env("AMP_LOCAL_PARSE_CACHE_CHARS", 120_000))
            local_chapter_context = (
                "【本集来源页码】\n"
                f"{json.dumps(used_ranges, ensure_ascii=False)}\n\n"
                f"{parsed}"
            )
            write_text(local_parse_path, local_chapter_context)
            log("  ✅ 本集本地解析完成；脚本生成将使用 Markdown/文本，不上传 PDF")

        # episode prompt
        if should_reuse_existing(args, "episode_prompt", [episode_prompt_path]):
            episode_prompt = read_text(episode_prompt_path)
            raw_episode_prompt = read_text(episode_dir / "raw_01_模型返回_分集提示词.txt")
            if looks_like_sdk_response_dump(episode_prompt) or len(episode_prompt.strip()) < 200:
                log("  ⚠️ 已有分集脚本提示词无效或含 Response(id=...)，使用脚本模型重建")
                episode_prompt = build_episode_prompt(make_text_client("episode_prompt"), episode, episode_dir, args.episode_prompt_builder, args.image_interval_seconds, book_title=book_title)
            elif "本地确定性分集提示词" in raw_episode_prompt and not _env_flag("AMP_ALLOW_LOCAL_EPISODE_PROMPT_REUSE", False):
                log("  ⚠️ 已有分集提示词来自本地模板，默认使用脚本模型重建")
                episode_prompt = build_episode_prompt(make_text_client("episode_prompt"), episode, episode_dir, args.episode_prompt_builder, args.image_interval_seconds, book_title=book_title)
            else:
                log("  ♻️ 复用本集脚本提示词")
        elif args.only_postprocess or args.only_missing_images:
            episode_prompt = read_text(episode_prompt_path)
            if looks_like_sdk_response_dump(episode_prompt) or not episode_prompt.strip():
                episode_prompt = build_deterministic_episode_prompt(episode, image_interval_seconds=args.image_interval_seconds, book_title=book_title)
        else:
            check_cancelled(args.stop_event)
            ep_provider, ep_model, _ = args.stage_settings("episode_prompt")
            if _env_flag("AMP_USE_EPISODE_PROMPT_LLM", True):
                log(f"  ▶ 分集提示词模型：{ep_provider} / {ep_model or '默认模型'}")
            else:
                log("  ▶ 分集提示词：使用本地确定性模板，不调用 LLM")
            episode_prompt = build_episode_prompt(make_text_client("episode_prompt"), episode, episode_dir, args.episode_prompt_builder, args.image_interval_seconds, book_title=book_title)
            log("  ✅ 已生成本集脚本提示词")

        # script / polish
        script_data: dict[str, Any]
        reuse_polish = should_reuse_existing(args, "polish", [script_json_path, voiceover_path, image_prompts_path])
        reuse_script = should_reuse_existing(args, "script", [script_json_path])
        force_rebuild_script = False

        if (reuse_polish or reuse_script or script_json_path.exists()) and not args.only_postprocess:
            existing_for_check = read_json_file(script_json_path, default={}) or {}
            coverage_ok, coverage_reason = script_source_coverage_status(existing_for_check, local_chapter_context, episode)
            if not coverage_ok:
                log(f"  ⚠️ 已有脚本覆盖原文不足，取消复用并重建：{coverage_reason}")
                reuse_polish = False
                reuse_script = False
                force_rebuild_script = True

        if reuse_polish:
            script_data = read_json_file(script_json_path, default={}) or {}
            log("  ♻️ 复用已完成脚本 / 台词 / 绘图提示词")
        else:
            if reuse_script and not force_rebuild_script:
                script_data = read_json_file(script_json_path, default={}) or {}
                log("  ♻️ 复用已有脚本 JSON；继续执行台词润色")
            elif args.only_postprocess or args.only_missing_images:
                script_data = read_json_file(script_json_path, default={}) or {}
            elif force_rebuild_script or pipeline_stage_rank(stage_start) <= pipeline_stage_rank("script"):
                check_cancelled(args.stop_event)
                script_provider, script_model, _ = args.stage_settings("script")
                log(f"  ▶ 脚本生成模型：{script_provider} / {script_model or '默认模型'}")
                script_data = build_script(
                    make_text_client("script"),
                    episode,
                    episode_prompt,
                    episode_pdf,
                    episode_dir,
                    args.script_json_requirement,
                    args.image_interval_seconds,
                    book_title=book_title,
                    local_chapter_context=local_chapter_context,
                )
                log("  ✅ 已生成脚本初稿")
            else:
                script_data = read_json_file(script_json_path, default={}) or {}

            if script_data and not (args.only_postprocess or args.only_missing_images) and (force_rebuild_script or pipeline_stage_rank(stage_start) <= pipeline_stage_rank("polish")):
                check_cancelled(args.stop_event)
                polish_provider, polish_model, _ = args.stage_settings("polish")
                log(f"  ▶ 台词润色模型：{polish_provider} / {polish_model or '默认模型'}")
                script_data = ensure_standard_cover_end_assets(script_data, episode, book_title, next_episode=next_episode)
                script_data = enforce_ab_c_numbering(script_data, episode=episode, book_title=book_title)
                script_data = align_image_prompts_with_voiceover(script_data, book_title=book_title)
                script_data = polish_voiceover(make_text_client("polish"), episode, script_data, None, episode_dir, args.voiceover_polish_prompt)
                script_data = enforce_ab_c_numbering(script_data, episode=episode, book_title=book_title)
                script_data = align_image_prompts_with_voiceover(script_data, book_title=book_title)
                save_script_outputs(episode_dir, script_data)
                log(f"  ✅ 已完成台词润色，并输出脚本、台词、LRC 和绘图提示词（当前配图节奏目标：每句台词一幕画面，约每 {args.image_interval_seconds} 秒 1 张）")
            elif script_data:
                script_data = ensure_standard_cover_end_assets(script_data, episode, book_title, next_episode=next_episode)
                script_data = enforce_ab_c_numbering(script_data, episode=episode, book_title=book_title)
                script_data = align_image_prompts_with_voiceover(script_data, book_title=book_title)
                save_script_outputs(episode_dir, script_data)

        if not script_data:
            script_data = read_json_file(script_json_path, default={}) or {}
        if script_data and (args.only_postprocess or args.only_missing_images or should_reuse_existing(args, "polish", [script_json_path])):
            script_data = ensure_standard_cover_end_assets(script_data, episode, book_title, next_episode=next_episode)
            script_data = enforce_ab_c_numbering(script_data, episode=episode, book_title=book_title)
            script_data = align_image_prompts_with_voiceover(script_data, book_title=book_title)
            save_script_outputs(episode_dir, script_data)

        # images / postprocess
        image_result = {"skipped": True}
        card_result: dict[str, Any] = {"skipped": True}
        should_do_cards = (not split_only_mode) and ((not args.skip_images) or args.only_postprocess or args.only_missing_images or pipeline_stage_rank(stage_start) >= pipeline_stage_rank("postprocess"))

        if split_only_mode:
            image_result = load_or_scan_image_result(episode_dir, script_data)
            log("  ▶ split_assets 模式：跳过生图和整集封面后处理，只扫描已有图片用于分集配图")
        elif args.only_postprocess:
            image_result = load_or_scan_image_result(episode_dir, script_data)
            log("  ▶ 只重做封面/片尾后处理：跳过文本模型与生图模型")
        elif args.skip_images and not args.only_missing_images:
            log("  ⏭️ 已跳过生图，仅保留绘图提示词")
        else:
            check_cancelled(args.stop_event)
            before_test_b = remaining_test_b_images
            log(f"  ▶ 生图模型：{args.image_provider} / {args.image_model or '默认模型'}")
            image_result = generate_images(
                image_client,
                episode_dir,
                script_data,
                skip_existing=bool(args.skip_existing_images or args.auto_resume),
                only_missing=bool(args.only_missing_images),
                test_b_image_limit=(remaining_test_b_images if remaining_test_b_images > 0 else -1) if args.test_b_image_limit else 0,
            )
            if args.test_b_image_limit:
                remaining_test_b_images = max(0, remaining_test_b_images - int(image_result.get("test_b_image_used") or 0))
                if before_test_b and not remaining_test_b_images:
                    log("  🧪 快速测试 B 图额度已用完；后续章节只跑文本/后处理/拆分，不再处理 B 图。")

        if should_do_cards:
            try:
                if image_result.get("results"):
                    base_cover = find_image_path(image_result, "A1")
                else:
                    image_result = load_or_scan_image_result(episode_dir, script_data)
                    base_cover = find_image_path(image_result, "A1")
                base_end = base_cover
                if base_cover is None:
                    raise RuntimeError("未找到可作为 A/C 母图的 A1 图片，请先生成或补齐 A1。")
                card_result = create_cover_and_endcards(
                    episode_dir,
                    base_cover,
                    base_end,
                    book_title=book_title,
                    author=book_author,
                    episode_title=episode.title,
                    hook=episode.hook,
                    cover_title=str(script_data.get("cover_title_final") or script_data.get("cover_title_auto") or ""),
                    chapter_label=best_chapter_label_for_cover(episode),
                    next_teaser=extract_next_teaser_for_endcard(script_data),
                )
                log("  ✅ 已完成封面/片尾后处理（A1/A2/A01/A02 + C，均复用同一张 9:16 母图）")
            except Exception as card_exc:
                card_result = {"error": str(card_exc)}
                log(f"  ⚠️ 封面/片尾后处理失败：{card_exc}")

        split_result = {"skipped": True}
        if getattr(args, "split_assets", True) and script_data:
            try:
                script_data.setdefault("source_chapter_label", best_chapter_label_for_cover(episode))
                script_data.setdefault("source_labels", episode.source_labels)
                script_data.setdefault("book_title", book_title)
                script_data.setdefault("book_author", book_author)
                script_data.setdefault("outline_episode_title", episode.title)
            except Exception:
                pass
            deferred_split_tasks.append({"episode_no": episode.episode_no, "episode_dir": episode_dir, "script_data": script_data})
            split_result = {"pending": True, "reason": "等待全部章节脚本生成后统一拆分，以便跨章读取下一章第一集内容。"}

        index_rows.append({
            "episode_no": episode.episode_no,
            "title": episode.title,
            "folder": str(episode_dir),
            "pdf": str(episode_pdf),
            "script": str(script_json_path),
            "voiceover": str(voiceover_path),
            "image_prompts": str(image_prompts_path),
            "image_result": image_result,
            "cover_endcards": card_result,
            "split_assets": split_result,
        })
        if args.test_b_image_limit:
            log("  🧪 测试运行：本集完成；继续处理后续大纲集的文本/拆分视野，B 图额度用完后不再生成 B 图。")

    if getattr(args, "split_assets", True) and deferred_split_tasks:
        trans_provider, trans_model, _ = args.stage_settings("transition")
        split_polish_provider_log, split_polish_model_log, _ = args.stage_settings("split_polish")
        final_polish_provider_log, final_polish_model_log, _ = args.stage_settings("final_polish")
        book_summary_provider_log, book_summary_model_log, _ = args.stage_settings("book_summary")
        log(f"\n⑦ 统一生成拆分脚本、分集 LRC、分集封面/首页与对应图片。")
        log(f"  承接过渡模型：{trans_provider} / {trans_model or '默认模型'}")
        log(f"  分集润色模型：{split_polish_provider_log} / {split_polish_model_log or '默认模型'}")
        log(f"  终稿润色模型：{final_polish_provider_log} / {final_polish_model_log or '默认模型'}")
        log(f"  全书总结模型：{book_summary_provider_log} / {book_summary_model_log or '默认模型'}")
        transition_client = make_text_client("transition")
        split_polish_client = make_text_client("split_polish")
        final_polish_client = make_text_client("final_polish")
        book_summary_client = make_text_client("book_summary")
        split_results_by_episode: dict[int, dict[str, Any]] = {}
        ordered_split_tasks = sorted(deferred_split_tasks, key=lambda t: int(t.get("episode_no") or 0))
        for task_index, task in enumerate(ordered_split_tasks):
            check_cancelled(args.stop_event)
            ep_no = int(task.get("episode_no") or 0)
            ep_dir = Path(task.get("episode_dir"))
            prev_ep_dir = Path(ordered_split_tasks[task_index - 1].get("episode_dir")) if task_index > 0 else None
            next_ep_dir = Path(ordered_split_tasks[task_index + 1].get("episode_dir")) if task_index + 1 < len(ordered_split_tasks) else None
            latest_script = read_json_file(ep_dir / "02_脚本.json", default=None) or task.get("script_data") or {}
            try:
                result = split_episode_scripts_and_images(
                    ep_dir,
                    latest_script,
                    transition_client=transition_client,
                    split_polish_client=split_polish_client,
                    final_polish_client=final_polish_client,
                    book_summary_client=book_summary_client,
                    prev_episode_dir=prev_ep_dir,
                    next_episode_dir=next_ep_dir,
                    skip_existing_parts=bool(args.auto_resume or args.skip_existing_text or args.only_missing_images or args.only_postprocess or pipeline_stage_rank(args.start_stage) > 0),
                )
                split_results_by_episode[ep_no] = result
                if not result.get("skipped"):
                    log(f"  ✅ EP{ep_no:02d} 已生成拆分脚本、分集 LRC、分集封面/首页与对应图片文件夹")
            except Exception as split_exc:
                split_results_by_episode[ep_no] = {"error": str(split_exc)}
                log(f"  ⚠️ EP{ep_no:02d} 拆分脚本与图片失败：{split_exc}")
                log("".join(traceback.format_exception(type(split_exc), split_exc, split_exc.__traceback__)).rstrip())
        for row in index_rows:
            ep_no = int(row.get("episode_no") or 0)
            if ep_no in split_results_by_episode:
                row["split_assets"] = split_results_by_episode[ep_no]

    write_json(args.out / "index.json", index_rows)
    write_json(args.out / "00_配图完成检查.json", build_image_completion_report(index_rows))
    write_text(args.out / "README_本次输出.md", output_readme(outline, index_rows) + "\n\n配图检查：请查看 `00_配图完成检查.json`，确认每章 expected_images 与 real_images 一致；*.prompt.txt 不会被视为已完成图片。\n")
    log(f"\n✅ 完成。输出目录：{args.out}")


def outline_to_markdown(outline: dict[str, Any]) -> str:
    lines = [f"# {outline.get('book_title') or '分集解读大纲'}", ""]
    author = str(outline.get("author") or outline.get("book_author") or "").strip()
    if author:
        lines += [f"- 作者：{author}", ""]
    notes = str(outline.get("outline_notes") or "").strip()
    if notes:
        lines += [f"> {notes}", ""]
    for ep in outline.get("episodes") or []:
        lines.append(f"## {ep.get('title') or ('EP' + str(ep.get('episode_no', '')))}")
        if ep.get("duration"):
            lines.append(f"- 视频时长估算：{ep.get('duration')}")
        if ep.get("hook"):
            lines.append(f"- 切入点：{ep.get('hook')}")
        points = ep.get("main_points") or []
        if points:
            lines.append("- 主要内容：")
            for p in points:
                lines.append(f"  - {p}")
        examples = ep.get("key_examples") or ep.get("examples") or []
        formatted_examples = [_format_key_example(x) for x in examples if _format_key_example(x)]
        if formatted_examples:
            lines.append("- 关键案例：")
            for ex in formatted_examples:
                lines.append(f"  - {ex}")
        ranges = ep.get("source_ranges") or []
        if ranges:
            lines.append("- 原文分割标签：")
            for r in ranges:
                label = r.get("label") or f"P{r.get('start_page')}-P{r.get('end_page')}"
                lines.append(f"  - {label}：P{r.get('start_page')} - P{r.get('end_page')}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def output_readme(outline: dict[str, Any], index_rows: list[dict[str, Any]]) -> str:
    lines = [
        "# 自动生成结果说明",
        "",
        "本目录由精简版 AutoMediaProducer 生成。每集目录包含：",
        "",
        "- `00_本集大纲.json`：本集结构化大纲",
        "- `00_章节原文_本地解析用.pdf`：按大纲 source_ranges 切出的原文 PDF",
        "- `01_分集脚本生成提示词.txt`：由大纲生成的脚本提示词",
        "- `raw_02_模型返回_脚本.txt`：模型生成的脚本初稿",
        "- `raw_03_模型返回_台词润色.txt`：台词润色模型返回内容",
        "- `02_脚本.json` / `02_完整脚本.txt`：润色后的最终脚本",
        "- `03_台词.txt`：最终台词",
        "- `04_绘图提示词.json` / `.txt`：逐图绘图提示词",
        "- `images/`：配图；如果未配置生图模型，会保存同名 `.prompt.txt`",
        "- `06_封面与片尾/`：后处理统一生成 A1=3:4、A2=9:16、A01=4:3、A02=16:9 四种封面，以及 C=9:16 结尾页；文字、logo、slogan 均由程序统一排版",
        "",
        "## 分集索引",
        "",
    ]
    for row in index_rows:
        lines.append(f"- EP{row['episode_no']:02d} {row['title']} - `{row['folder']}`")
    lines.append("")
    return "\n".join(lines)


def parse_args(argv: Iterable[str] | None = None) -> PipelineArgs:
    parser = argparse.ArgumentParser(
        prog="AutoMediaProducer",
        description="精简工作流：整本书 PDF -> 分集解读大纲 -> 分集提示词 -> 切分 PDF -> 脚本 -> 台词/绘图提示词 -> 配图",
    )
    parser.add_argument("book_positional", nargs="?", help=argparse.SUPPRESS)
    parser.add_argument("--book", default="", help="输入书籍 PDF 路径；也可以直接把 PDF 路径作为第一个参数")
    parser.add_argument("--out", default="", help="输出目录；留空则默认输出到 PDF 所在文件夹旁边的短视频素材目录")
    parser.add_argument("--episode-count", type=int, default=0, help="兼容旧参数：当前默认由模型根据书本结构自动决定分集数量")
    parser.add_argument("--page-offset", type=int, default=0, help=argparse.SUPPRESS)
    parser.add_argument("--provider", default=os.getenv("TEXT_PROVIDER", "gemini"), choices=["dry-run", "openai", "gemini", "doubao", "deepseek"], help="兼容旧参数：全局文本 provider；各阶段未单独设置时使用")
    parser.add_argument("--text-model", default=os.getenv("TEXT_MODEL", ""), help="兼容旧参数：全局文本模型名；各阶段未单独设置时使用")
    parser.add_argument("--api-key", default="", help="兼容旧参数：全局文本模型 API Key；也可用环境变量或 *_api_key.txt")
    parser.add_argument("--outline-provider", default=os.getenv("OUTLINE_PROVIDER", ""), choices=["dry-run", "openai", "gemini", "doubao", "deepseek"], help="大纲生成 provider，默认 gemini")
    parser.add_argument("--outline-model", default=os.getenv("OUTLINE_MODEL", ""), help="大纲生成模型，默认 gemini-3-flash-preview")
    parser.add_argument("--outline-api-key", default="", help="大纲生成 API Key；留空则按 provider 读取本地 key 文件或环境变量")
    parser.add_argument("--episode-prompt-provider", default=os.getenv("EPISODE_PROMPT_PROVIDER", "openai"), choices=["dry-run", "openai", "gemini", "doubao", "deepseek"], help="分集脚本提示词生成 provider，默认 openai")
    parser.add_argument("--episode-prompt-model", default=os.getenv("EPISODE_PROMPT_MODEL", DEFAULT_OPENAI_PRO_MODEL), help="分集脚本提示词生成模型，默认跟随脚本模型 gpt-5.5")
    parser.add_argument("--episode-prompt-api-key", default="", help="分集脚本提示词生成 API Key")
    parser.add_argument("--script-provider", default=os.getenv("SCRIPT_PROVIDER", "openai"), choices=["dry-run", "openai", "gemini", "doubao", "deepseek"], help="脚本生成 provider，默认 openai")
    parser.add_argument("--script-model", default=os.getenv("SCRIPT_MODEL", DEFAULT_OPENAI_PRO_MODEL), help="脚本生成模型，默认 gpt-5.5")
    parser.add_argument("--script-api-key", default="", help="脚本生成 API Key")
    parser.add_argument("--polish-provider", default=os.getenv("POLISH_PROVIDER", "deepseek"), choices=["dry-run", "openai", "gemini", "doubao", "deepseek"], help="台词润色 provider，默认 deepseek")
    parser.add_argument("--polish-model", default=os.getenv("POLISH_MODEL", DEEPSEEK_DEFAULT_MODEL), help="台词润色模型，默认 deepseek-v4-pro")
    parser.add_argument("--polish-api-key", default="", help="台词润色 API Key")
    parser.add_argument("--transition-provider", default=os.getenv("TRANSITION_PROVIDER", ""), choices=["dry-run", "openai", "gemini", "doubao", "deepseek"], help="承接过渡 provider，默认继承 polish")
    parser.add_argument("--transition-model", default=os.getenv("TRANSITION_MODEL", ""), help="承接过渡模型")
    parser.add_argument("--transition-api-key", default="", help="承接过渡 API Key")
    parser.add_argument("--split-polish-provider", default=os.getenv("SPLIT_POLISH_PROVIDER", ""), choices=["dry-run", "openai", "gemini", "doubao", "deepseek"], help="分集润色 provider，默认继承 polish")
    parser.add_argument("--split-polish-model", default=os.getenv("SPLIT_POLISH_MODEL", ""), help="分集润色模型")
    parser.add_argument("--split-polish-api-key", default="", help="分集润色 API Key")
    parser.add_argument("--final-polish-provider", default=os.getenv("FINAL_POLISH_PROVIDER", ""), choices=["dry-run", "openai", "gemini", "doubao", "deepseek"], help="终稿润色 provider，默认 deepseek")
    parser.add_argument("--final-polish-model", default=os.getenv("FINAL_POLISH_MODEL", ""), help="终稿润色模型")
    parser.add_argument("--final-polish-api-key", default="", help="终稿润色 API Key")
    parser.add_argument("--book-summary-provider", default=os.getenv("BOOK_SUMMARY_PROVIDER", ""), choices=["dry-run", "openai", "gemini", "doubao", "deepseek"], help="全书总结 provider，默认继承 polish")
    parser.add_argument("--book-summary-model", default=os.getenv("BOOK_SUMMARY_MODEL", ""), help="全书总结模型")
    parser.add_argument("--book-summary-api-key", default="", help="全书总结 API Key")
    parser.add_argument("--image-provider", default=os.getenv("IMAGE_PROVIDER", "openai"), choices=["none", "dry-run", "openai", "gemini"], help="生图 provider，默认 openai")
    parser.add_argument("--image-model", default=os.getenv("IMAGE_MODEL", DEFAULT_OPENAI_IMAGE_MODEL), help="图片模型名；OpenAI 默认 gpt-image-2")
    parser.add_argument("--image-api-key", default="", help="生图 API Key；也可用环境变量或 *_api_key.txt")
    parser.add_argument("--outline-json", dest="skip_outline", default="", help="已有大纲 JSON 路径；传入后跳过整本书大纲生成")
    parser.add_argument("--skip-images", action="store_true", help="跳过生图，只生成脚本、台词和绘图提示词")
    parser.add_argument("--max-retries", type=int, default=4, help="模型调用重试次数")
    parser.add_argument("--local-parse-mode", default=os.getenv("LOCAL_PARSE_MODE", "auto"), choices=PDF_PARSE_MODE_OPTIONS, help="PDF 本地解析模式：auto/pymupdf4llm；禁止 PDF 直传，失败后使用 pypdf 文本提取")
    parser.add_argument("--local-pdf-parser", default=os.getenv("LOCAL_PDF_PARSER", DEFAULT_LOCAL_PDF_PARSER), choices=["pymupdf4llm"], help="本地 PDF 解析器，默认 pymupdf4llm")
    parser.add_argument("--auto-resume", action="store_true", help="自动断点续跑：优先复用输出目录中已完成的步骤")
    parser.add_argument("--skip-existing-text", action="store_true", help="若文本阶段结果已存在，则优先复用，不重复调用模型")
    parser.add_argument("--skip-existing-images", action="store_true", help="若图片已存在，则优先复用，不重复生图")
    parser.add_argument("--only-missing-images", action="store_true", help="只补缺失的图片；文本阶段全部复用已有结果")
    parser.add_argument("--only-postprocess", action="store_true", help="只重做封面/片尾后处理，不重新调用文本模型或生图模型")
    parser.add_argument("--start-episode-no", type=int, default=1, help="从第几集开始继续，默认 1")
    parser.add_argument("--start-stage", default="outline", choices=PIPELINE_STAGE_ORDER, help="从哪个阶段开始继续：outline/split_pdf/episode_prompt/script/polish/images/postprocess/split_assets")
    parser.add_argument("--continue-from-folder", default="", help="选择一个已有输出文件夹或单集文件夹，直接复用其中已有脚本继续绘图与后处理")
    parser.add_argument("--no-split-assets", action="store_true", help="不生成‘拆分脚本与对应图片文件夹’这一步")
    parser.add_argument("--test-b-image-limit", type=int, default=0, help="快速测试：每章只生成/处理前 N 张 B 图；0 表示正常生成全部 B 图")
    # Backward-compatible hidden options from the old MinerU build.
    parser.add_argument("--mineru-backend", default="", help=argparse.SUPPRESS)
    parser.add_argument("--mineru-api-url", default="", help=argparse.SUPPRESS)

    ns = parser.parse_args(list(argv) if argv is not None else None)

    continue_folder_value = (ns.continue_from_folder or "").strip().strip('"')
    book_value = (ns.book or ns.book_positional or "").strip().strip('"')
    if not book_value and not continue_folder_value:
        log("请输入书籍 PDF 路径。也可以把 PDF 文件直接拖到这个窗口后按回车：")
        try:
            book_value = input("> ").strip().strip('"')
        except EOFError:
            book_value = ""
    if not book_value and not continue_folder_value:
        parser.error("缺少书籍 PDF 路径。用法：python AutoMediaProducer.py --book 你的书.pdf")
    if not book_value and continue_folder_value:
        book_value = continue_folder_value
    out_value = (ns.out or "").strip().strip('"')
    if not out_value:
        out_value = str(default_output_dir_for_book(Path(book_value))) if not continue_folder_value else continue_folder_value

    def stage_provider(value: str) -> str:
        return (value or ns.provider or "gemini").strip()

    def stage_model(value: str, provider_value: str) -> str:
        value = (value or ns.text_model or "").strip()
        provider_value = (provider_value or "").strip()
        if not value and provider_value == "gemini":
            return DEFAULT_GEMINI_FAST_MODEL
        if not value and provider_value == "openai":
            return DEFAULT_OPENAI_TEXT_MODEL
        if not value and provider_value == "doubao":
            return doubao_env_model()
        if not value and provider_value == "deepseek":
            return DEEPSEEK_DEFAULT_MODEL
        return value

    outline_provider = stage_provider(ns.outline_provider)
    script_provider = stage_provider(ns.script_provider)
    polish_provider = stage_provider(ns.polish_provider)

    runtime_prompts = load_runtime_prompt_files()

    return PipelineArgs(
        book=Path(book_value).expanduser().resolve(),
        out=Path(out_value).expanduser().resolve(),
        episode_count=ns.episode_count,
        page_offset=0,
        provider=ns.provider,
        text_model=ns.text_model,
        api_key=ns.api_key,
        outline_provider=outline_provider,
        outline_model=stage_model(ns.outline_model, outline_provider),
        outline_api_key=ns.outline_api_key or ns.api_key,
        episode_prompt_provider=script_provider,
        episode_prompt_model=stage_model(ns.script_model, script_provider),
        episode_prompt_api_key=ns.script_api_key or ns.api_key,
        script_provider=script_provider,
        script_model=stage_model(ns.script_model, script_provider),
        script_api_key=ns.script_api_key or ns.api_key,
        polish_provider=polish_provider,
        polish_model=stage_model(ns.polish_model, polish_provider),
        polish_api_key=ns.polish_api_key or ns.api_key,
        transition_provider=polish_provider,
        transition_model=stage_model(ns.polish_model, polish_provider),
        transition_api_key=ns.polish_api_key or ns.api_key,
        split_polish_provider=polish_provider,
        split_polish_model=stage_model(ns.polish_model, polish_provider),
        split_polish_api_key=ns.polish_api_key or ns.api_key,
        final_polish_provider=polish_provider,
        final_polish_model=stage_model(ns.polish_model, polish_provider),
        final_polish_api_key=ns.polish_api_key or ns.api_key,
        book_summary_provider=polish_provider,
        book_summary_model=stage_model(ns.polish_model, polish_provider),
        book_summary_api_key=ns.polish_api_key or ns.api_key,
        image_provider=ns.image_provider,
        image_model=ns.image_model,
        image_api_key=ns.image_api_key,
        skip_outline=Path(ns.skip_outline).expanduser().resolve() if ns.skip_outline else None,
        skip_images=ns.skip_images,
        max_retries=ns.max_retries,
        outline_prompt=runtime_prompts.get("outline_prompt", OUTLINE_PROMPT),
        episode_prompt_builder=runtime_prompts.get("episode_prompt_builder", EPISODE_PROMPT_BUILDER),
        script_json_requirement=runtime_prompts.get("script_json_requirement", SCRIPT_JSON_REQUIREMENT),
        voiceover_polish_prompt=runtime_prompts.get("voiceover_polish_prompt", VOICEOVER_POLISH_PROMPT),
        local_parse_mode=ns.local_parse_mode,
        mineru_backend=(ns.local_pdf_parser or ns.mineru_backend or DEFAULT_LOCAL_PDF_PARSER),
        mineru_api_url="",
        auto_resume=bool(ns.auto_resume),
        skip_existing_text=bool(ns.skip_existing_text),
        skip_existing_images=bool(ns.skip_existing_images),
        only_missing_images=bool(ns.only_missing_images),
        only_postprocess=bool(ns.only_postprocess),
        start_episode_no=max(1, int(ns.start_episode_no or 1)),
        start_stage=str(ns.start_stage or "outline"),
        continue_from_folder=Path(ns.continue_from_folder).expanduser().resolve() if str(ns.continue_from_folder or "").strip() else None,
        split_assets=not bool(ns.no_split_assets),
        test_b_image_limit=max(0, int(ns.test_b_image_limit or 0)),
    )


def main(argv: Iterable[str] | None = None) -> None:
    try:
        args = parse_args(argv)
        run_pipeline(args)
    except (KeyboardInterrupt, PipelineCancelled):
        log("\n已停止。")
        raise SystemExit(130)
    except Exception as exc:
        log(f"\n❌ 运行失败：{exc}")
        if os.getenv("DEBUG", ""):
            traceback.print_exc()
        raise SystemExit(1)


if __name__ == "__main__":
    main()
