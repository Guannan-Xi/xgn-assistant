from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, font as tkfont, messagebox, scrolledtext, ttk

from .postprocess_cards import POSTPROCESS_SPEC_PATH, default_global_postprocess_spec_text
from .email_delivery import test_email_connection

from .runner import (
    DEFAULT_GEMINI_FAST_MODEL,
    DEFAULT_GEMINI_PRO_MODEL,
    DEFAULT_FOREIGN_MODEL_BASE_URL,
    DEFAULT_DEEPSEEK_BASE_URL,
    DEFAULT_OPENAI_TEXT_MODEL,
    OPENAI_IMAGE_MODEL_OPTIONS,
    OPENAI_TEXT_MODEL_OPTIONS,
    DOUBAO_TEXT_MODEL_OPTIONS,
    DEEPSEEK_TEXT_MODEL_OPTIONS,
    GEMINI_TEXT_MODEL_OPTIONS,
    PDF_PARSE_MODE_OPTIONS,
    DEFAULT_LOCAL_PDF_PARSER,
    canonical_gemini_model,
    deepseek_base_url,
    doubao_env_model,
    doubao_model_looks_like_api_key,
    EPISODE_PROMPT_BUILDER,
    OUTLINE_PROMPT,
    SCRIPT_JSON_REQUIREMENT,
    VOICEOVER_POLISH_PROMPT,
    default_ac_master_prompt,
    default_deterministic_episode_prompt_template,
    default_generation_rules,
    default_image_quality,
    PipelineArgs,
    PipelineCancelled,
    default_output_dir_for_book,
    normalize_openai_image_size_for_model,
    read_api_key,
    requests_post_no_proxy,
    run_pipeline,
    set_log_handler,
    write_text,
    openai_compatible_client,
)
from .split_assets import (
    default_split_title_prompt,
    default_split_polish_prompt,
    default_final_polish_prompt,
    default_book_final_summary_prompt,
    _default_transition_prompt,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SETTINGS_PATH = PROJECT_ROOT / "gui_settings.json"
PROMPTS_DIR = PROJECT_ROOT / "prompts"
CONFIG_DIR = PROJECT_ROOT / "config"
RUNTIME_SWITCHES_CONFIG_PATH = CONFIG_DIR / "运行开关.json"


def _is_project_outputs_path(path_text: str) -> bool:
    if not str(path_text or "").strip():
        return False
    try:
        path = Path(path_text).expanduser().resolve()
        project_outputs = (PROJECT_ROOT / "outputs").resolve()
        return path == project_outputs or project_outputs in path.parents
    except Exception:
        return str(path_text).strip().startswith(str(PROJECT_ROOT / "outputs"))


TEXT_MODEL_OPTIONS = {
    "dry-run": [""],  # 仅用于“一键测试 dry-run”，正常流程只显示 Gemini / OpenAI。
    "gemini": GEMINI_TEXT_MODEL_OPTIONS,
    "openai": OPENAI_TEXT_MODEL_OPTIONS,
    "doubao": DOUBAO_TEXT_MODEL_OPTIONS,
    "deepseek": DEEPSEEK_TEXT_MODEL_OPTIONS,
}

IMAGE_MODEL_OPTIONS = {
    "none": [""],
    "dry-run": [""],
    "openai": OPENAI_IMAGE_MODEL_OPTIONS,
    # Gemini 低成本优先：Nano Banana / Gemini 2.5 Flash Image。
    "gemini": [
        "gemini-3-pro-image-preview",
        "gemini-3.1-flash-image-preview",
    ],
}

KEY_FILE_NAMES = {
    "gemini": "gemini_api_key.txt",
    "openai": "openai_api_key.txt",
    "image": "image_api_key.txt",
    "doubao": "ark_api_key.txt",
    "deepseek": "deepseek_api_key.txt",
}
DOUBAO_ENDPOINT_FILE_NAME = "ark_endpoint_id.txt"


def _extract_chat_content(response) -> str:
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

TEXT_STAGES = [
    ("outline", "大纲生成", "优先本地识别章节并切成3-4分钟短集；识别失败才调用模型。"),
    ("script", "脚本生成", "生成分集提示词、分镜、台词和绘图提示词；默认 GPT-5.5。"),
    ("polish", "台词润色", "按图号逐句润色台词，并供承接、拆分润色、终稿和总结复用。"),
]

STAGE_SETTINGS_KEYS = {
    "outline": ("outline_provider", "outline_model"),
    "episode_prompt": ("episode_prompt_provider", "episode_prompt_model"),
    "script": ("script_provider", "script_model"),
    "polish": ("polish_provider", "polish_model"),
    "transition": ("transition_provider", "transition_model"),
    "split_polish": ("split_polish_provider", "split_polish_model"),
    "final_polish": ("final_polish_provider", "final_polish_model"),
    "book_summary": ("book_summary_provider", "book_summary_model"),
}


class ToolTip:
    def __init__(self, widget: tk.Widget, text: str):
        self.widget = widget
        self.text = text
        self.tip: tk.Toplevel | None = None
        widget.bind("<Enter>", self.show)
        widget.bind("<Leave>", self.hide)

    def show(self, _event=None) -> None:
        if self.tip or not self.text:
            return
        x = self.widget.winfo_rootx() + 18
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x}+{y}")
        label = tk.Label(
            self.tip,
            text=self.text,
            justify="left",
            background="#fff8dc",
            relief="solid",
            borderwidth=1,
            padx=8,
            pady=5,
            wraplength=460,
        )
        label.pack()

    def hide(self, _event=None) -> None:
        if self.tip:
            self.tip.destroy()
            self.tip = None


class AutoMediaGUI(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("AutoMediaProducer｜书籍解读短视频自动生成")
        self.geometry("1280x840")
        self.minsize(1180, 760)
        self.log_queue: queue.Queue[tuple] = queue.Queue()
        self.running = False
        self.cancel_event: threading.Event | None = None
        self.last_output_dir: Path | None = None

        self.prompt_texts = {
            "outline": OUTLINE_PROMPT,
            "episode_builder": EPISODE_PROMPT_BUILDER,
            "script_requirement": SCRIPT_JSON_REQUIREMENT,
            "voiceover_polish": VOICEOVER_POLISH_PROMPT,
            "transition_summary_prompt": _default_transition_prompt(),
            "split_title_prompt": default_split_title_prompt(),
            "split_voiceover_polish_prompt": default_split_polish_prompt(),
            "book_final_summary_prompt": default_book_final_summary_prompt(),
            "ac_master_prompt": default_ac_master_prompt(),
        }
        self.postprocess_spec_text = default_global_postprocess_spec_text()
        self.prompt_editors: dict[str, scrolledtext.ScrolledText] = {}
        self.prompt_tabs: list[str] = []
        self.prompt_notebook: ttk.Notebook | None = None
        self.notebook: ttk.Notebook | None = None
        self.prompt_tab: ttk.Frame | None = None
        self.visual_tab: ttk.Frame | None = None
        self.status_var = tk.StringVar(value="准备就绪")
        self._init_prompt_files()

        self._init_style()
        self._init_vars()
        self._auto_out_enabled = True
        self._last_book_for_auto_out = ""
        self._last_auto_out = ""
        self._last_stage_providers = {stage: var.get() for stage, var in self.stage_provider_vars.items()}
        self._last_image_provider = self.image_provider_var.get()
        self._build_ui()
        self._load_settings()
        self._load_email_config_vars()
        self.book_var.trace_add("write", self._on_book_var_changed)
        self._install_settings_autosave_traces()
        self._load_keys_for_current_provider(overwrite=False)
        self._poll_queue()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _font_tuple(self, size: int, weight: str | None = None):
        family = getattr(self, "_ui_font_family", "TkDefaultFont")
        return (family, size, weight) if weight else (family, size)

    def _init_style(self) -> None:
        self.configure(bg="#f6f3ec")

        # Tk 的字体字符串里如果字体名包含空格，必须用大括号包起来。
        # 之前直接写成 "Microsoft YaHei UI 10"，在部分 Windows/Tcl 环境中会被解析成：
        # family=Microsoft, size=YaHei，从而报错：expected integer but got "YaHei"。
        available_fonts = set(tkfont.families(self))
        font_family = next(
            (name for name in ("Microsoft YaHei UI", "Microsoft YaHei", "微软雅黑", "SimSun", "Arial") if name in available_fonts),
            "TkDefaultFont",
        )

        def font_tuple(size: int, weight: str | None = None):
            return (font_family, size, weight) if weight else (font_family, size)

        def font_string(size: int, weight: str | None = None) -> str:
            family = "{" + font_family + "}" if " " in font_family else font_family
            return f"{family} {size}" + (f" {weight}" if weight else "")

        self._ui_font_family = font_family
        self.option_add("*Font", font_string(10))
        self.option_add("*TCombobox*Listbox.font", font_string(10))
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        bg = "#f6f3ec"
        card = "#fffdf8"
        ink = "#2d241a"
        muted = "#6f6458"
        gold = "#b8842f"
        accent = "#7a2e21"
        style.configure("TFrame", background=bg)
        style.configure("Card.TFrame", background=card, relief="flat")
        style.configure("Hero.TFrame", background="#2b2118")
        style.configure("TLabel", background=bg, foreground=ink)
        style.configure("HeroTitle.TLabel", background="#2b2118", foreground="#f7e8c5", font=font_tuple(19, "bold"))
        style.configure("HeroSub.TLabel", background="#2b2118", foreground="#d9c59b", font=font_tuple(10))
        style.configure("Title.TLabel", font=font_tuple(17, "bold"), foreground=ink, background=bg)
        style.configure("Muted.TLabel", foreground=muted, background=bg)
        style.configure("Section.TLabelframe", background=bg, bordercolor="#e5d8bf", relief="solid")
        style.configure("Section.TLabelframe.Label", font=self._font_tuple(10, "bold"), foreground=accent, background=bg)
        style.configure("TButton", padding=(10, 6))
        style.configure("Run.TButton", font=font_tuple(11, "bold"), foreground="white", background=accent, bordercolor=accent)
        style.map("Run.TButton", background=[("active", "#913929"), ("disabled", "#bda99c")])
        style.configure("Stop.TButton", font=font_tuple(11, "bold"), foreground="white", background="#5d5a55", bordercolor="#5d5a55")
        style.configure("TNotebook", background=bg, borderwidth=0)
        style.configure("TNotebook.Tab", padding=(16, 8), font=self._font_tuple(10, "bold"))
        style.map("TNotebook.Tab", background=[("selected", card)], foreground=[("selected", accent)])
        style.configure("Horizontal.TProgressbar", troughcolor="#e6dcc9", background=gold)

    def _init_vars(self) -> None:
        self.book_var = tk.StringVar()
        self.out_var = tk.StringVar()
        # Kept for old settings/CLI compatibility; the UI now uses stage-specific vars below.
        self.provider_var = tk.StringVar(value="gemini")
        self.text_model_var = tk.StringVar(value=DEFAULT_GEMINI_FAST_MODEL)
        self.api_key_var = tk.StringVar(value="")
        self.stage_provider_vars = {
            "outline": tk.StringVar(value="gemini"),
            "episode_prompt": tk.StringVar(value="openai"),
            "script": tk.StringVar(value="openai"),
            "polish": tk.StringVar(value="deepseek"),
            "transition": tk.StringVar(value="deepseek"),
            "split_polish": tk.StringVar(value="deepseek"),
            "final_polish": tk.StringVar(value="deepseek"),
            "book_summary": tk.StringVar(value="deepseek"),
        }
        self.stage_model_vars = {
            "outline": tk.StringVar(value=DEFAULT_GEMINI_FAST_MODEL),
            "episode_prompt": tk.StringVar(value=DEFAULT_OPENAI_TEXT_MODEL),
            "script": tk.StringVar(value=DEFAULT_OPENAI_TEXT_MODEL),
            "polish": tk.StringVar(value="deepseek-v4-pro"),
            "transition": tk.StringVar(value="deepseek-v4-pro"),
            "split_polish": tk.StringVar(value="deepseek-v4-pro"),
            "final_polish": tk.StringVar(value="deepseek-v4-pro"),
            "book_summary": tk.StringVar(value="deepseek-v4-pro"),
        }
        self.stage_model_combos: dict[str, ttk.Combobox] = {}
        self.foreign_base_url_var = tk.StringVar(value=DEFAULT_FOREIGN_MODEL_BASE_URL)
        self.gemini_key_var = tk.StringVar(value="")
        self.openai_key_var = tk.StringVar(value="")
        self.doubao_key_var = tk.StringVar(value="")
        self.deepseek_key_var = tk.StringVar(value="")
        self.doubao_endpoint_var = tk.StringVar(value="")
        self.save_keys_var = tk.BooleanVar(value=True)
        self.outline_json_var = tk.StringVar(value="")
        self.skip_images_var = tk.BooleanVar(value=False)
        self.image_provider_var = tk.StringVar(value="openai")
        self.image_model_var = tk.StringVar(value="gpt-image-2")
        self.image_api_key_var = tk.StringVar(value="")
        self.max_retries_var = tk.StringVar(value="4")
        self.image_interval_var = tk.StringVar(value="3-8")
        self.local_parse_mode_var = tk.StringVar(value="auto")
        self.local_pdf_parser_var = tk.StringVar(value=DEFAULT_LOCAL_PDF_PARSER)
        self.local_pdf_parser_note_var = tk.StringVar(value="PyMuPDF4LLM")
        self.auto_resume_var = tk.BooleanVar(value=True)
        self.skip_existing_text_var = tk.BooleanVar(value=True)
        self.skip_existing_images_var = tk.BooleanVar(value=True)
        self.only_missing_images_var = tk.BooleanVar(value=False)
        self.only_postprocess_var = tk.BooleanVar(value=False)
        self.start_episode_var = tk.StringVar(value="1")
        self.start_stage_var = tk.StringVar(value="outline")
        self.continue_from_existing_folder_var = tk.BooleanVar(value=False)
        self.continue_folder_var = tk.StringVar(value="")
        self.visual_preset_var = tk.StringVar(value="magazine_prime")
        self.vc_bg_brightness_var = tk.DoubleVar(value=0.92)
        self.vc_bg_saturation_var = tk.DoubleVar(value=0.98)
        self.vc_bg_blur_var = tk.DoubleVar(value=3.0)
        self.vc_vignette_var = tk.DoubleVar(value=0.34)
        self.vc_top_darken_var = tk.DoubleVar(value=0.18)
        self.vc_bottom_darken_var = tk.DoubleVar(value=0.30)
        self.vc_glass_opacity_var = tk.DoubleVar(value=0.68)
        self.vc_glass_blur_var = tk.DoubleVar(value=14.0)
        self.vc_glass_glow_var = tk.DoubleVar(value=0.22)
        self.vc_title_scale_var = tk.DoubleVar(value=1.18)
        self.vc_title_glow_var = tk.DoubleVar(value=0.18)
        self.vc_frame_var = tk.BooleanVar(value=True)
        self.vc_scanline_var = tk.BooleanVar(value=False)
        self.email_enabled_var = tk.BooleanVar(value=False)
        self.email_smtp_host_var = tk.StringVar(value="smtp.qq.com")
        self.email_smtp_port_var = tk.StringVar(value="465")
        self.email_use_ssl_var = tk.BooleanVar(value=True)
        self.email_username_var = tk.StringVar(value="399467826@qq.com")
        self.email_from_var = tk.StringVar(value="399467826@qq.com")
        self.email_to_var = tk.StringVar(value="399467826@qq.com")
        self.email_password_env_var = tk.StringVar(value="AMP_SMTP_PASSWORD")
        self.email_password_file_var = tk.StringVar(value="smtp_password.txt")
        self.email_max_mb_var = tk.StringVar(value="20")
        self.email_subject_template_var = tk.StringVar(value="著作解读分集完成：{part_name}")
        self.vc_progress_var = tk.BooleanVar(value=True)
        self.vc_particle_var = tk.BooleanVar(value=True)
        self.vc_orb_var = tk.BooleanVar(value=True)

    def _prompt_file_specs(self) -> list[dict[str, str]]:
        return [
            {
                "key": "outline",
                "filename": "01_大纲生成提示词.md",
                "title": "大纲生成",
                "desc": "控制整本书如何拆成分集大纲。可用变量：{episode_count}、{image_interval_seconds}。",
                "default": OUTLINE_PROMPT,
            },
            {
                "key": "episode_builder",
                "filename": "02_脚本生成提示词.md",
                "title": "脚本生成提示词",
                "desc": "控制每一集脚本生成的叙事要求、画面节奏、A1/C 规则。可用变量：{episode_json}、{image_interval_seconds}、{book_title}。",
                "default": EPISODE_PROMPT_BUILDER,
            },
            {
                "key": "script_requirement",
                "filename": "03_脚本生成_JSON规范.md",
                "title": "脚本 JSON / 分镜规范",
                "desc": "控制脚本输出结构、voiceover 与 image_prompts 的字段规范。可用变量：{image_interval_seconds}。",
                "default": SCRIPT_JSON_REQUIREMENT,
            },
            {
                "key": "voiceover_polish",
                "filename": "04_台词润色提示词.md",
                "title": "台词润色提示词",
                "desc": "控制台词如何变得更通俗、地道，同时保留图号、结构和原意。可用变量：{episode_json}、{script_json}、{voiceover_text}。",
                "default": VOICEOVER_POLISH_PROMPT,
            },
            {
                "key": "postprocess_spec",
                "filename": "05_后处理规范.json",
                "title": "后处理规范",
                "desc": "控制封面/片尾/分集封面的完整后处理参数：品牌文案、尺寸规格、坐标、字号、颜色、阴影、边框、暗角、裁剪、品牌栏、片尾 CTA。保存后重跑后处理即可生效。",
                "default": default_global_postprocess_spec_text(),
            },
            {
                "key": "transition_summary_prompt",
                "filename": "06_承接预告总结提示词.md",
                "title": "承接预告提示词",
                "desc": "控制拆分后 A1 开头承接、C 结尾预告如何由大模型总结。",
                "default": _default_transition_prompt(),
            },
            {
                "key": "split_title_prompt",
                "filename": "07_分集本集名提示词.md",
                "title": "分集本集名提示词",
                "desc": "控制每个 3~5 分钟分集如何根据本集 LRC/台词生成封面与首页显示的本集名。可用变量：{book_title}、{chapter_label}、{part_no}、{current_summary}、{lrc_payload}。",
                "default": default_split_title_prompt(),
            },
            {
                "key": "split_voiceover_polish_prompt",
                "filename": "08_分集台词润色提示词.md",
                "title": "分集台词润色提示词",
                "desc": "控制拆分后每个分集的一次润色、A1/C 简化、33%/67% 留存钩子。可用变量：{title}、{part_no}、{prev_summary}、{current_summary}、{next_title}、{next_summary}、{previous_context}、{next_context}、{hook_target_payload}、{payload}。",
                "default": default_split_polish_prompt(),
            },
            {
                "key": "split_final_polish_prompt",
                "filename": "12_DeepSeek终稿润色提示词.md",
                "title": "DeepSeek 终稿润色提示词",
                "desc": "最终检查每集钩子、开篇、主题、结尾预告的整体过渡；保留 no、image_id 与图片文件名对应。可用变量：{book_title}、{chapter_label}、{title}、{part_no}、{prev_summary}、{current_summary}、{next_title}、{next_summary}、{previous_context}、{next_context}、{opening_context}、{closing_context}、{payload}。",
                "default": default_final_polish_prompt(),
            },
            {
                "key": "book_final_summary_prompt",
                "filename": "09_全书结尾总结提示词.md",
                "title": "全书结尾总结提示词",
                "desc": "控制全书最后一集 C 结尾如何生成全书总结。可用变量：{book_title}、{current_summary}、{payload}。",
                "default": default_book_final_summary_prompt(),
            },
            {
                "key": "ac_master_prompt",
                "filename": "10_封面母图提示词.md",
                "title": "封面母图提示词",
                "desc": "控制 A/C 共用母图的生图提示词。可用变量：{manuscript}、{book_title}、{episode_title}、{chapter_summary}。",
                "default": default_ac_master_prompt(),
            },
            {
                "key": "deterministic_episode_prompt",
                "filename": "14_本地确定性脚本提示词模板.md",
                "title": "本地确定性脚本模板",
                "desc": "当分集提示词模型关闭、dry-run 或模型失败回退时使用。可用变量：{book_title}、{episode_no}、{episode_title}、{source_labels}、{hook}、{main_points}、{image_interval_seconds}。",
                "default": default_deterministic_episode_prompt_template(),
            },
            {
                "key": "generation_rules",
                "filename": "生成规则配置.json",
                "folder": "config",
                "title": "生成规则配置",
                "desc": "控制程序自动追加给脚本生成、覆盖补救、绘图提示词的规则。优先级高于程序兜底默认值。",
                "default": json.dumps(default_generation_rules(), ensure_ascii=False, indent=2),
            },
            {
                "key": "copywriting_config",
                "filename": "文案风格配置.json",
                "folder": "config",
                "title": "文案风格配置",
                "desc": "控制品牌名、关注语、分集开头/结尾模板、是否显示前缀等。保存后重新拆分脚本即可生效。",
                "default": "{}",
            },
            {
                "key": "postprocess_override",
                "filename": "后处理风格覆盖.json",
                "folder": "config",
                "title": "后处理风格覆盖",
                "desc": "后处理局部覆盖配置。优先级高于 05_后处理规范.json，适合临时微调字体、颜色、边框、装饰开关。",
                "default": "{}",
            },
            {
                "key": "runtime_switches",
                "filename": "运行开关.json",
                "folder": "config",
                "title": "运行开关",
                "desc": "控制是否启用配置覆盖、高保真装饰等运行开关。",
                "default": "{}",
            },
        ]

    def _prompt_file_path(self, key: str) -> Path:
        for spec in self._prompt_file_specs():
            if spec["key"] == key:
                if key == "postprocess_spec":
                    return POSTPROCESS_SPEC_PATH
                base_dir = CONFIG_DIR if spec.get("folder") == "config" else PROMPTS_DIR
                return base_dir / spec["filename"]
        raise KeyError(key)

    def _init_prompt_files(self) -> None:
        PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        for spec in self._prompt_file_specs():
            path = self._prompt_file_path(spec["key"])
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(spec["default"].strip() + "\n", encoding="utf-8")
        self._reload_prompt_files(update_editors=False)

    def _reload_prompt_files(self, update_editors: bool = True) -> None:
        for spec in self._prompt_file_specs():
            key = spec["key"]
            path = self._prompt_file_path(key)
            try:
                text = path.read_text(encoding="utf-8") if path.exists() else spec["default"]
            except Exception:
                text = spec["default"]
            if key == "postprocess_spec":
                self.postprocess_spec_text = text.strip()
            else:
                self.prompt_texts[key] = text.strip()
            if update_editors and key in self.prompt_editors:
                widget = self.prompt_editors[key]
                if not widget.winfo_exists():
                    self.prompt_editors.pop(key, None)
                    continue
                widget.delete("1.0", "end")
                widget.insert("1.0", text.strip())

    def _sync_prompt_editors_to_memory(self, *, save_files: bool = False, show_log: bool = False) -> bool:
        specs_by_key = {spec["key"]: spec for spec in self._prompt_file_specs()}
        for key, widget in list(self.prompt_editors.items()):
            if not widget.winfo_exists():
                self.prompt_editors.pop(key, None)
                continue
            text = widget.get("1.0", "end").strip()
            spec = specs_by_key.get(key, {})
            if str(spec.get("filename") or "").lower().endswith(".json"):
                try:
                    json.loads(text or "{}")
                except Exception as exc:
                    title = str(spec.get("title") or key)
                    messagebox.showerror("JSON 格式有误", f"请先修正“{title}”的 JSON 格式。\n\n{exc}")
                    return False
            if key == "postprocess_spec":
                self.postprocess_spec_text = text
            else:
                self.prompt_texts[key] = text
        if save_files:
            self._save_prompt_files(show_log=show_log)
        return True

    def _save_prompt_files(self, *, show_log: bool = True) -> None:
        PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
        for spec in self._prompt_file_specs():
            key = spec["key"]
            path = self._prompt_file_path(key)
            text = self.postprocess_spec_text if key == "postprocess_spec" else self.prompt_texts.get(key, spec["default"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(text or "").strip() + "\n", encoding="utf-8")
        if show_log:
            self._append_log(f"提示词与配置已保存：{PROMPTS_DIR}；{CONFIG_DIR}")

    def _save_prompt_editor_files(self) -> None:
        if self._sync_prompt_editors_to_memory(save_files=True, show_log=True):
            self._save_settings()
            messagebox.showinfo("已保存", f"提示词和配置已保存到：\n{PROMPTS_DIR}\n{CONFIG_DIR}")

    def _restore_current_prompt_default(self) -> None:
        if not self.prompt_notebook or not self.prompt_tabs:
            return
        key = self.prompt_tabs[self.prompt_notebook.index("current")]
        default = ""
        for spec in self._prompt_file_specs():
            if spec["key"] == key:
                default = spec["default"]
                break
        widget = self.prompt_editors.get(key)
        if widget is not None:
            widget.delete("1.0", "end")
            widget.insert("1.0", default.strip())

    def _open_prompts_dir(self) -> None:
        PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
        try:
            if os.name == "nt":
                os.startfile(str(PROMPTS_DIR))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(PROMPTS_DIR)])
            else:
                subprocess.Popen(["xdg-open", str(PROMPTS_DIR)])
        except Exception as exc:
            messagebox.showerror("无法打开提示词目录", str(exc))

    def _build_ui(self) -> None:
        self.geometry("1320x900")
        self.minsize(1100, 720)

        root = ttk.Frame(self, padding=12)
        root.pack(fill="both", expand=True)
        root.rowconfigure(2, weight=1)
        root.columnconfigure(0, weight=1)

        header = ttk.Frame(root)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)
        ttk.Label(header, text="书籍解读短视频自动生成", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            header,
            text="PDF → 大纲 → 脚本 → 润色 → 绘图 → 后处理",
            foreground="#555",
        ).grid(row=0, column=1, sticky="w", padx=(18, 0))

        action_bar = ttk.LabelFrame(root, text="运行", style="Section.TLabelframe")
        action_bar.grid(row=1, column=0, sticky="ew", pady=(10, 10))
        action_bar.columnconfigure(9, weight=1)

        self.run_button_top = ttk.Button(action_bar, text="开始运行", command=self._run, style="Run.TButton", width=14)
        self.run_button_top.grid(row=0, column=0, padx=(12, 8), pady=9)
        self.test_button_top = ttk.Button(action_bar, text="测试运行", command=self._run_quick_test, width=12)
        self.test_button_top.grid(row=0, column=1, padx=(0, 8), pady=9)
        self.stop_button_top = ttk.Button(action_bar, text="停止", command=self._stop, style="Stop.TButton", state="disabled", width=10)
        self.stop_button_top.grid(row=0, column=2, padx=(0, 8), pady=9)
        self.open_button = ttk.Button(action_bar, text="打开输出", command=self._open_output_dir, width=12)
        self.open_button.grid(row=0, column=3, padx=(0, 8), pady=9)
        self.clear_button = ttk.Button(action_bar, text="清空输出", command=self._clear_output_dir, width=12)
        self.clear_button.grid(row=0, column=4, padx=(0, 8), pady=9)

        ttk.Separator(action_bar, orient="vertical").grid(row=0, column=5, sticky="ns", padx=(4, 12), pady=7)
        ttk.Button(action_bar, text="提示词", command=self._show_prompts, width=10).grid(row=0, column=6, padx=(0, 8), pady=9)
        ttk.Button(action_bar, text="视觉", command=self._show_visual, width=10).grid(row=0, column=7, padx=(0, 8), pady=9)
        ttk.Button(action_bar, text="Key", command=self._show_key_manager, width=8).grid(row=0, column=8, padx=(0, 12), pady=9)
        ttk.Label(action_bar, text="测试运行：先生成全文故事线大纲，B图只画一张，仍执行拆分/打包/邮件。", foreground="#555").grid(row=0, column=9, sticky="w", padx=(0, 10))

        # Keep old attribute names used by _set_running_state.
        self.run_button = self.run_button_top
        self.stop_button = self.stop_button_top
        self.notebook = None
        self.prompt_tab = None
        self.visual_tab = None
        self.dry_button = ttk.Button(action_bar, text="dry-run", command=self._run_dry)

        main = ttk.PanedWindow(root, orient="horizontal")
        main.grid(row=2, column=0, sticky="nsew")

        left = ttk.Frame(main, width=760)
        right = ttk.Frame(main, width=560)
        main.add(left, weight=3)
        main.add(right, weight=2)
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)

        left_scroll = ttk.Frame(left)
        left_scroll.grid(row=0, column=0, sticky="nsew")
        left_scroll.rowconfigure(0, weight=1)
        left_scroll.columnconfigure(0, weight=1)
        control_canvas = tk.Canvas(left_scroll, highlightthickness=0, borderwidth=0)
        control_scrollbar = ttk.Scrollbar(left_scroll, orient="vertical", command=control_canvas.yview)
        control_canvas.configure(yscrollcommand=control_scrollbar.set)
        control_canvas.grid(row=0, column=0, sticky="nsew")
        control_scrollbar.grid(row=0, column=1, sticky="ns")

        control_panel = ttk.Frame(control_canvas)
        control_window = control_canvas.create_window((0, 0), window=control_panel, anchor="nw")
        control_panel.bind(
            "<Configure>",
            lambda _event: control_canvas.configure(scrollregion=control_canvas.bbox("all")),
        )
        control_canvas.bind(
            "<Configure>",
            lambda event: control_canvas.itemconfigure(control_window, width=event.width),
        )

        def _on_left_mousewheel(event) -> None:
            delta = -1 if getattr(event, "delta", 0) > 0 else 1
            control_canvas.yview_scroll(delta * 3, "units")

        control_canvas.bind("<Enter>", lambda _event: control_canvas.bind_all("<MouseWheel>", _on_left_mousewheel))
        control_canvas.bind("<Leave>", lambda _event: control_canvas.unbind_all("<MouseWheel>"))
        control_panel.columnconfigure(0, weight=1)
        control_panel.rowconfigure(1, weight=1)

        input_box = ttk.LabelFrame(control_panel, text="输入", style="Section.TLabelframe")
        input_box.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        input_box.columnconfigure(1, weight=1)
        self._path_row(input_box, 0, "书籍 PDF", self.book_var, self._browse_book, "选择一本 PDF 书籍。大纲和脚本都会基于这本书生成。")
        self._path_row(input_box, 1, "输出目录", self.out_var, self._browse_out, "所有结果都会保存到这个目录，不会覆盖原 PDF。", folder=True)

        config_stack = ttk.Frame(control_panel)
        config_stack.grid(row=1, column=0, sticky="nsew")
        config_stack.columnconfigure(0, weight=1)
        config_stack.rowconfigure(0, weight=0)
        config_stack.rowconfigure(1, weight=0)
        config_stack.rowconfigure(2, weight=1)

        model_box = ttk.LabelFrame(config_stack, text="模型", style="Section.TLabelframe")
        model_box.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        self._build_models(model_box)

        email_box = ttk.LabelFrame(config_stack, text="邮箱发送", style="Section.TLabelframe")
        email_box.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        self._build_email_config(email_box)

        param_box = ttk.LabelFrame(config_stack, text="运行选项", style="Section.TLabelframe")
        param_box.grid(row=2, column=0, sticky="nsew")
        self._build_params(param_box)

        log_box = ttk.LabelFrame(right, text="日志", style="Section.TLabelframe")
        log_box.grid(row=0, column=0, sticky="nsew")
        log_box.rowconfigure(1, weight=1)
        log_box.columnconfigure(0, weight=1)

        log_toolbar = ttk.Frame(log_box)
        log_toolbar.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))
        log_toolbar.columnconfigure(1, weight=1)
        ttk.Button(log_toolbar, text="清空日志", command=self._clear_log).grid(row=0, column=0, padx=(0, 8))
        ttk.Label(log_toolbar, text="运行状态和错误会显示在这里", foreground="#666").grid(row=0, column=1, sticky="e")

        self.log_text = scrolledtext.ScrolledText(log_box, wrap="word", font=("Consolas", 10), height=22)
        self.log_text.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        self.log_text.insert("end", "准备就绪。默认模型：大纲 Gemini，脚本 GPT-5.5，绘图 GPT-image2，台词润色 DeepSeek V4 Pro。\n")
        self.log_text.insert("end", "高级设置可通过顶部“提示词”和“视觉”打开。\n")
        self.log_text.configure(state="disabled")

        status_bar = ttk.Frame(root)
        status_bar.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        status_bar.columnconfigure(0, weight=1)
        self.progress = ttk.Progressbar(status_bar, mode="indeterminate")
        self.progress.grid(row=0, column=0, sticky="ew", padx=(0, 12))
        ttk.Label(status_bar, textvariable=self.status_var, style="Muted.TLabel").grid(row=0, column=1, sticky="e")

    def _build_prompt_tab(self, parent: ttk.Frame) -> None:
        toolbar = ttk.Frame(parent)
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        toolbar.columnconfigure(4, weight=1)
        ttk.Button(toolbar, text="保存到提示词文件", command=self._save_prompt_editor_files, style="Run.TButton").grid(row=0, column=0, padx=(0, 8))
        ttk.Button(toolbar, text="从文件重新加载", command=lambda: self._reload_prompt_files(update_editors=True)).grid(row=0, column=1, padx=(0, 8))
        ttk.Button(toolbar, text="恢复当前页默认", command=self._restore_current_prompt_default).grid(row=0, column=2, padx=(0, 8))
        ttk.Button(toolbar, text="打开提示词文件夹", command=self._open_prompts_dir).grid(row=0, column=3, padx=(0, 8))
        ttk.Label(toolbar, text="保存后不需要改程序；重跑对应步骤即可生效。", style="Muted.TLabel").grid(row=0, column=4, sticky="e")

        self.prompt_notebook = ttk.Notebook(parent)
        self.prompt_notebook.grid(row=1, column=0, sticky="nsew")
        self.prompt_editors = {}
        self.prompt_tabs = []
        for spec in self._prompt_file_specs():
            key = spec["key"]
            frame = ttk.Frame(self.prompt_notebook, padding=8)
            frame.rowconfigure(1, weight=1)
            frame.columnconfigure(0, weight=1)
            desc = f"{spec['desc']}\n文件：{self._prompt_file_path(key)}"
            ttk.Label(frame, text=desc, justify="left", wraplength=710, style="Muted.TLabel").grid(row=0, column=0, sticky="ew", pady=(0, 6))
            editor = scrolledtext.ScrolledText(frame, wrap="word", font=("Consolas", 10), undo=True, height=18)
            editor.grid(row=1, column=0, sticky="nsew")
            editor.insert("1.0", self.postprocess_spec_text if key == "postprocess_spec" else self.prompt_texts.get(key, spec["default"]))
            self.prompt_editors[key] = editor
            self.prompt_tabs.append(key)
            self.prompt_notebook.add(frame, text=spec["title"])


    def _visual_presets(self) -> dict[str, dict]:
        return {
            "magazine_prime": {
                "label": "顶刊杂志",
                "background": {"brightness": 0.92, "saturation": 0.98, "blur_px": 3, "vignette": 0.34, "top_darken": 0.18, "bottom_darken": 0.30},
                "glass": {"opacity": 0.68, "blur_px": 14, "glow": 0.22},
                "title": {"scale": 1.18, "glow": 0.18},
                "ornaments": {"frame": True, "corner": False, "scanline": False, "progress_bar": False, "particle": False, "orb": False},
            },
            "warm_paper": {
                "label": "暖纸书房",
                "background": {"brightness": 1.04, "saturation": 0.94, "blur_px": 2, "vignette": 0.15, "top_darken": 0.02, "bottom_darken": 0.07},
                "glass": {"opacity": 0.90, "blur_px": 10, "glow": 0.16},
                "title": {"scale": 1.08, "glow": 0.10},
                "ornaments": {"frame": True, "corner": False, "scanline": False, "progress_bar": False, "particle": False, "orb": False},
            },
            "rational_social": {
                "label": "理性社会",
                "background": {"brightness": 0.86, "saturation": 0.90, "blur_px": 3, "vignette": 0.34, "top_darken": 0.14, "bottom_darken": 0.22},
                "glass": {"opacity": 0.86, "blur_px": 12, "glow": 0.22},
                "title": {"scale": 1.10, "glow": 0.12},
                "ornaments": {"frame": True, "corner": False, "scanline": False, "progress_bar": False, "particle": False, "orb": False},
            },
            "olive_reading": {
                "label": "草木书香",
                "background": {"brightness": 1.02, "saturation": 0.88, "blur_px": 2, "vignette": 0.16, "top_darken": 0.02, "bottom_darken": 0.06},
                "glass": {"opacity": 0.88, "blur_px": 10, "glow": 0.14},
                "title": {"scale": 1.06, "glow": 0.10},
                "ornaments": {"frame": True, "corner": False, "scanline": False, "progress_bar": False, "particle": False, "orb": False},
            },
            "humanities_paper": {
                "label": "人文旧书",
                "background": {"brightness": 0.98, "saturation": 0.86, "blur_px": 2, "vignette": 0.22, "top_darken": 0.06, "bottom_darken": 0.10},
                "glass": {"opacity": 0.88, "blur_px": 10, "glow": 0.18},
                "title": {"scale": 1.06, "glow": 0.10},
                "ornaments": {"frame": True, "corner": False, "scanline": False, "progress_bar": False, "particle": False, "orb": False},
            },
        }

    def _read_postprocess_spec_json(self) -> dict:
        try:
            return json.loads(POSTPROCESS_SPEC_PATH.read_text(encoding="utf-8"))
        except Exception:
            try:
                return json.loads(default_global_postprocess_spec_text())
            except Exception:
                return {}

    def _nested_value(self, data: dict, path: str, default=None):
        cur = data
        for part in path.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur

    def _set_nested_value(self, data: dict, path: str, value) -> None:
        cur = data
        parts = path.split(".")
        for part in parts[:-1]:
            nxt = cur.get(part)
            if not isinstance(nxt, dict):
                nxt = {}
                cur[part] = nxt
            cur = nxt
        cur[parts[-1]] = value

    def _load_visual_controls_to_vars(self) -> None:
        data = self._read_postprocess_spec_json()
        vc = data.get("visual_controls") if isinstance(data.get("visual_controls"), dict) else {}
        self.visual_preset_var.set(str(vc.get("preset") or "magazine_prime"))
        mapping = [
            ("background.brightness", self.vc_bg_brightness_var, 0.92),
            ("background.saturation", self.vc_bg_saturation_var, 0.98),
            ("background.blur_px", self.vc_bg_blur_var, 3.0),
            ("background.vignette", self.vc_vignette_var, 0.34),
            ("background.top_darken", self.vc_top_darken_var, 0.18),
            ("background.bottom_darken", self.vc_bottom_darken_var, 0.30),
            ("glass.opacity", self.vc_glass_opacity_var, 0.68),
            ("glass.blur_px", self.vc_glass_blur_var, 14.0),
            ("glass.glow", self.vc_glass_glow_var, 0.22),
            ("title.scale", self.vc_title_scale_var, 1.18),
            ("title.glow", self.vc_title_glow_var, 0.18),
        ]
        for path, var, default in mapping:
            try:
                var.set(float(self._nested_value(vc, path, default)))
            except Exception:
                var.set(float(default))
        bools = [
            ("ornaments.frame", self.vc_frame_var, True),
            ("ornaments.scanline", self.vc_scanline_var, False),
            ("ornaments.progress_bar", self.vc_progress_var, False),
            ("ornaments.particle", self.vc_particle_var, False),
            ("ornaments.orb", self.vc_orb_var, False),
        ]
        for path, var, default in bools:
            var.set(bool(self._nested_value(vc, path, default)))

    def _save_visual_controls_from_vars(self, *, show_message: bool = True) -> None:
        data = self._read_postprocess_spec_json()
        vc = data.setdefault("visual_controls", {})
        vc["preset"] = self.visual_preset_var.get().strip() or "magazine_prime"
        values = {
            "background.brightness": round(float(self.vc_bg_brightness_var.get()), 3),
            "background.saturation": round(float(self.vc_bg_saturation_var.get()), 3),
            "background.contrast": 1.10,
            "background.blur_px": round(float(self.vc_bg_blur_var.get()), 1),
            "background.vignette": round(float(self.vc_vignette_var.get()), 3),
            "background.top_darken": round(float(self.vc_top_darken_var.get()), 3),
            "background.bottom_darken": round(float(self.vc_bottom_darken_var.get()), 3),
            "glass.opacity": round(float(self.vc_glass_opacity_var.get()), 3),
            "glass.blur_px": round(float(self.vc_glass_blur_var.get()), 1),
            "glass.glow": round(float(self.vc_glass_glow_var.get()), 3),
            "title.scale": round(float(self.vc_title_scale_var.get()), 3),
            "title.glow": round(float(self.vc_title_glow_var.get()), 3),
            "title.max_lines_vertical": 3,
            "title.max_lines_wide": 3,
            "ornaments.frame": bool(self.vc_frame_var.get()),
            "ornaments.corner": False,
            "ornaments.scanline": False,
            "ornaments.progress_bar": False,
            "ornaments.particle": False,
            "ornaments.orb": False,
            "ornaments.noise": True,
            "composition.visual_priority": True,
            "composition.wide_text_side": "left",
            "composition.wide_panel_width_pct": 52,
            "composition.vertical_card_y_pct": 16,
            "composition.vertical_card_h_pct": 52,
        }
        for path, value in values.items():
            self._set_nested_value(vc, path, value)
        data["visual_controls"] = vc
        POSTPROCESS_SPEC_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.postprocess_spec_text = json.dumps(data, ensure_ascii=False, indent=2)
        editor = self.prompt_editors.get("postprocess_spec")
        if editor is not None:
            editor.delete("1.0", "end")
            editor.insert("1.0", self.postprocess_spec_text)
        self._append_log("已保存视觉后处理参数；勾选‘只重做封面/片尾后处理’后运行即可批量重渲染 A/C。")
        if show_message:
            messagebox.showinfo("视觉后处理已保存", "已写入 prompts/05_后处理规范.json。\n重跑后处理即可生成新 A/C 图片。")

    def _apply_visual_preset(self, _event=None) -> None:
        preset = self._visual_presets().get(self.visual_preset_var.get(), self._visual_presets()["magazine_prime"])
        bg = preset.get("background", {})
        glass = preset.get("glass", {})
        title = preset.get("title", {})
        ornaments = preset.get("ornaments", {})
        self.vc_bg_brightness_var.set(float(bg.get("brightness", 0.92)))
        self.vc_bg_saturation_var.set(float(bg.get("saturation", 0.98)))
        self.vc_bg_blur_var.set(float(bg.get("blur_px", 3.0)))
        self.vc_vignette_var.set(float(bg.get("vignette", 0.34)))
        self.vc_top_darken_var.set(float(bg.get("top_darken", 0.18)))
        self.vc_bottom_darken_var.set(float(bg.get("bottom_darken", 0.30)))
        self.vc_glass_opacity_var.set(float(glass.get("opacity", 0.68)))
        self.vc_glass_blur_var.set(float(glass.get("blur_px", 14.0)))
        self.vc_glass_glow_var.set(float(glass.get("glow", 0.22)))
        self.vc_title_scale_var.set(float(title.get("scale", 1.18)))
        self.vc_title_glow_var.set(float(title.get("glow", 0.18)))
        self.vc_frame_var.set(bool(ornaments.get("frame", True)))
        self.vc_scanline_var.set(bool(ornaments.get("scanline", True)))
        self.vc_progress_var.set(bool(ornaments.get("progress_bar", True)))
        self.vc_particle_var.set(bool(ornaments.get("particle", True)))
        self.vc_orb_var.set(bool(ornaments.get("orb", True)))

    def _scale_row(self, parent: ttk.Frame, row: int, label: str, var: tk.DoubleVar, from_: float, to: float, tip: str) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=8, pady=5)
        scale = tk.Scale(parent, variable=var, from_=from_, to=to, orient="horizontal", resolution=0.01, showvalue=True, length=260, bg="#fffdf8", highlightthickness=0)
        scale.grid(row=row, column=1, sticky="ew", padx=8, pady=5)
        ToolTip(scale, tip)

    def _build_visual_tab(self, parent: ttk.Frame) -> None:
        toolbar = ttk.Frame(parent)
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        toolbar.columnconfigure(4, weight=1)
        ttk.Label(toolbar, text="风格预设").grid(row=0, column=0, sticky="w", padx=(0, 8))
        preset_combo = ttk.Combobox(toolbar, textvariable=self.visual_preset_var, values=list(self._visual_presets().keys()), state="readonly", width=18)
        preset_combo.grid(row=0, column=1, sticky="w", padx=(0, 8))
        preset_combo.bind("<<ComboboxSelected>>", self._apply_visual_preset)
        ttk.Button(toolbar, text="应用预设", command=self._apply_visual_preset).grid(row=0, column=2, padx=(0, 8))
        ttk.Button(toolbar, text="保存视觉参数", command=self._save_visual_controls_from_vars, style="Run.TButton").grid(row=0, column=3, padx=(0, 8))
        ttk.Button(toolbar, text="从规范重新加载", command=self._load_visual_controls_to_vars).grid(row=0, column=4, sticky="e")

        grid = ttk.Frame(parent)
        grid.grid(row=1, column=0, sticky="nsew")
        for col in range(3):
            grid.columnconfigure(col, weight=1)
        grid.rowconfigure(0, weight=1)

        bg_box = ttk.LabelFrame(grid, text="背景 / 母图", style="Section.TLabelframe")
        bg_box.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        bg_box.columnconfigure(1, weight=1)
        self._scale_row(bg_box, 0, "亮度", self.vc_bg_brightness_var, 0.30, 1.00, "提高后母图更清楚；太高会压低文字对比。")
        self._scale_row(bg_box, 1, "饱和度", self.vc_bg_saturation_var, 0.70, 1.45, "控制母图色彩浓度。")
        self._scale_row(bg_box, 2, "背景模糊", self.vc_bg_blur_var, 0.0, 24.0, "只影响辅助模糊层，让画面更有电影纵深。")
        self._scale_row(bg_box, 3, "暗角", self.vc_vignette_var, 0.0, 0.90, "提高后边缘更暗，中心更聚焦。")
        self._scale_row(bg_box, 4, "顶部压暗", self.vc_top_darken_var, 0.0, 0.90, "保护顶部书名和标签可读性。")
        self._scale_row(bg_box, 5, "底部压暗", self.vc_bottom_darken_var, 0.0, 0.95, "保护底部品牌栏和 C 图 CTA。")

        glass_box = ttk.LabelFrame(grid, text="玻璃控件 / 面板", style="Section.TLabelframe")
        glass_box.grid(row=0, column=1, sticky="nsew", padx=8)
        glass_box.columnconfigure(1, weight=1)
        self._scale_row(glass_box, 0, "透明度", self.vc_glass_opacity_var, 0.25, 0.85, "越低越能露出母图；越高文字更稳。")
        self._scale_row(glass_box, 1, "玻璃模糊", self.vc_glass_blur_var, 0.0, 32.0, "控制毛玻璃质感。")
        self._scale_row(glass_box, 2, "发光强度", self.vc_glass_glow_var, 0.0, 1.00, "控制面板边缘的金色光晕。")
        self._scale_row(glass_box, 3, "标题字号", self.vc_title_scale_var, 0.80, 1.45, "A2/C 主标题冲击力；长标题会自动缩字。")
        self._scale_row(glass_box, 4, "标题辉光", self.vc_title_glow_var, 0.0, 1.00, "控制主标题描边和外发光。")

        fx_box = ttk.LabelFrame(grid, text="炫酷控件", style="Section.TLabelframe")
        fx_box.grid(row=0, column=2, sticky="nsew", padx=(8, 0))
        checks = [
            ("极简外框", self.vc_frame_var, "只保留一层金色外框；角标默认关闭，避免重复装饰。"),
            ("扫描线", self.vc_scanline_var, "增加高级控件感，但不影响文字。"),
            ("C 图进度条", self.vc_progress_var, "C 片尾 NEXT EPISODE 进度条。"),
            ("粒子", self.vc_particle_var, "细小金色粒子，增加画面精致度。"),
            ("光斑", self.vc_orb_var, "背景金色光斑，提升氛围。"),
        ]
        for i, (text, var, tip) in enumerate(checks):
            cb = ttk.Checkbutton(fx_box, text=text, variable=var)
            cb.grid(row=i, column=0, sticky="w", padx=10, pady=7)
            ToolTip(cb, tip)
        note = (
            "推荐流程：选择预设 → 微调亮度/透明度/标题字号 → 保存视觉参数 → 勾选‘只重做封面/片尾后处理’运行。\n"
            "本页参数会直接写入 prompts/05_后处理规范.json 的 visual_controls。"
        )
        ttk.Label(fx_box, text=note, justify="left", wraplength=300, style="Muted.TLabel").grid(row=len(checks), column=0, sticky="ew", padx=10, pady=(18, 8))
        self._load_visual_controls_to_vars()

    def _path_row(self, parent: ttk.Frame, row: int, label: str, var: tk.StringVar, command, tip: str, folder: bool = False) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=10, pady=7)
        entry = ttk.Entry(parent, textvariable=var)
        entry.grid(row=row, column=1, sticky="ew", padx=8, pady=7)
        ToolTip(entry, tip)
        ttk.Button(parent, text="选择文件夹" if folder else "选择文件", command=command).grid(row=row, column=2, padx=10, pady=7)

    def _default_out_for_book_text(self, book_text: str) -> str:
        book_text = str(book_text or "").strip().strip('"')
        if not book_text:
            return ""
        try:
            return str(default_output_dir_for_book(Path(book_text).expanduser()))
        except Exception:
            return ""

    def _sync_output_dir_for_book(self, *, force: bool = False) -> None:
        if getattr(self, "_syncing_output_dir", False):
            return
        if bool(self.continue_from_existing_folder_var.get()):
            return
        book_text = self.book_var.get().strip().strip('"')
        if not book_text:
            return
        desired = self._default_out_for_book_text(book_text)
        if not desired:
            return
        current_out = self.out_var.get().strip().strip('"')
        should_update = (
            force
            or not current_out
            or _is_project_outputs_path(current_out)
            or current_out == getattr(self, "_last_auto_out", "")
            or book_text != getattr(self, "_last_book_for_auto_out", "")
        )
        if not should_update:
            return
        try:
            self._syncing_output_dir = True
            self.out_var.set(desired)
        finally:
            self._syncing_output_dir = False
        self._last_book_for_auto_out = book_text
        self._last_auto_out = desired

    def _on_book_var_changed(self, *_args) -> None:
        self._sync_output_dir_for_book()

    def _build_params(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(1, weight=1)
        ttk.Label(parent, text="重试次数").grid(row=0, column=0, sticky="w", padx=10, pady=7)
        retry_spin = ttk.Spinbox(parent, from_=0, to=10, textvariable=self.max_retries_var, width=10)
        retry_spin.grid(row=0, column=1, sticky="w", padx=8, pady=7)
        ToolTip(retry_spin, "模型接口偶发断开时自动重试的次数。")

        ttk.Label(parent, text="配图节奏").grid(row=1, column=0, sticky="w", padx=10, pady=7)
        cadence_entry = ttk.Entry(parent, textvariable=self.image_interval_var, width=12)
        cadence_entry.grid(row=1, column=1, sticky="w", padx=8, pady=7)
        ToolTip(cadence_entry, "默认 3-8，表示每句台词尽量对应 1 幕画面。")

        check = ttk.Checkbutton(parent, text="跳过生图，只输出绘图提示词", variable=self.skip_images_var)
        check.grid(row=2, column=0, columnspan=2, sticky="w", padx=10, pady=7)
        ToolTip(check, "只生成文本和绘图提示词，不调用绘图接口。")

        ttk.Checkbutton(parent, text="自动断点续跑", variable=self.auto_resume_var).grid(row=3, column=0, sticky="w", padx=10, pady=7)
        ttk.Checkbutton(parent, text="跳过已生成内容", variable=self.skip_existing_text_var).grid(row=3, column=1, sticky="w", padx=8, pady=7)
        ttk.Checkbutton(parent, text="只补缺失图片", variable=self.only_missing_images_var).grid(row=4, column=0, sticky="w", padx=10, pady=7)
        ttk.Checkbutton(parent, text="只重做后处理", variable=self.only_postprocess_var).grid(row=4, column=1, sticky="w", padx=8, pady=7)

        advanced = ttk.LabelFrame(parent, text="高级续作", style="Section.TLabelframe")
        advanced.grid(row=5, column=0, columnspan=2, sticky="ew", padx=10, pady=(10, 6))
        advanced.columnconfigure(1, weight=1)
        ttk.Checkbutton(advanced, text="从已有文件夹继续", variable=self.continue_from_existing_folder_var).grid(row=0, column=0, sticky="w", padx=8, pady=5)
        self._path_row(advanced, 1, "续作文件夹", self.continue_folder_var, self._browse_continue_folder, "可选择整个输出目录或某一集目录。", folder=True)
        self._path_row(advanced, 2, "已有大纲 JSON", self.outline_json_var, self._browse_outline, "已有结构化大纲时使用；留空则先生成大纲。")
        ttk.Label(advanced, text="起始集").grid(row=3, column=0, sticky="w", padx=8, pady=5)
        ttk.Spinbox(advanced, from_=1, to=999, textvariable=self.start_episode_var, width=10).grid(row=3, column=1, sticky="w", padx=8, pady=5)
        ttk.Label(advanced, text="起始步骤").grid(row=4, column=0, sticky="w", padx=8, pady=5)
        stage_combo = ttk.Combobox(advanced, textvariable=self.start_stage_var, values=["outline", "split_pdf", "episode_prompt", "script", "polish", "images", "postprocess", "split_assets"], state="readonly", width=18)
        stage_combo.grid(row=4, column=1, sticky="w", padx=8, pady=5)

    def _build_email_config(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(1, weight=1)
        parent.columnconfigure(3, weight=1)

        enable = ttk.Checkbutton(parent, text="每集完成后打包发送邮件", variable=self.email_enabled_var)
        enable.grid(row=0, column=0, columnspan=4, sticky="w", padx=10, pady=(8, 5))
        ToolTip(enable, "开启后，分集素材生成完成时会打包为 zip 并发送到指定邮箱。")

        ttk.Label(parent, text="收件邮箱").grid(row=1, column=0, sticky="w", padx=10, pady=5)
        to_entry = ttk.Entry(parent, textvariable=self.email_to_var)
        to_entry.grid(row=1, column=1, columnspan=3, sticky="ew", padx=8, pady=5)
        ToolTip(to_entry, "多个收件人用英文逗号分隔。默认测试邮箱：399467826@qq.com。")

        ttk.Label(parent, text="SMTP").grid(row=2, column=0, sticky="w", padx=10, pady=5)
        host_entry = ttk.Entry(parent, textvariable=self.email_smtp_host_var, width=18)
        host_entry.grid(row=2, column=1, sticky="ew", padx=8, pady=5)
        ttk.Label(parent, text="端口").grid(row=2, column=2, sticky="w", padx=(6, 0), pady=5)
        port_entry = ttk.Entry(parent, textvariable=self.email_smtp_port_var, width=8)
        port_entry.grid(row=2, column=3, sticky="w", padx=8, pady=5)
        ToolTip(host_entry, "QQ 邮箱一般使用 smtp.qq.com。")
        ToolTip(port_entry, "QQ 邮箱 SSL 端口通常为 465。")

        ssl_check = ttk.Checkbutton(parent, text="使用 SSL", variable=self.email_use_ssl_var)
        ssl_check.grid(row=3, column=0, sticky="w", padx=10, pady=5)
        ttk.Label(parent, text="登录账号").grid(row=3, column=1, sticky="w", padx=8, pady=5)
        user_entry = ttk.Entry(parent, textvariable=self.email_username_var)
        user_entry.grid(row=3, column=2, columnspan=2, sticky="ew", padx=8, pady=5)
        ToolTip(user_entry, "通常填写发件邮箱完整地址，例如 你的QQ号@qq.com。")

        ttk.Label(parent, text="发件人").grid(row=4, column=0, sticky="w", padx=10, pady=5)
        from_entry = ttk.Entry(parent, textvariable=self.email_from_var)
        from_entry.grid(row=4, column=1, sticky="ew", padx=8, pady=5)
        ttk.Label(parent, text="附件上限MB").grid(row=4, column=2, sticky="w", padx=(6, 0), pady=5)
        max_entry = ttk.Entry(parent, textvariable=self.email_max_mb_var, width=8)
        max_entry.grid(row=4, column=3, sticky="w", padx=8, pady=5)
        ToolTip(from_entry, "可留空；留空时默认使用登录账号。")
        ToolTip(max_entry, "超过此大小会跳过发送，避免邮箱拒收。")

        ttk.Label(parent, text="密码变量").grid(row=5, column=0, sticky="w", padx=10, pady=5)
        env_entry = ttk.Entry(parent, textvariable=self.email_password_env_var)
        env_entry.grid(row=5, column=1, sticky="ew", padx=8, pady=5)
        ttk.Label(parent, text="密码文件").grid(row=5, column=2, sticky="w", padx=(6, 0), pady=5)
        file_entry = ttk.Entry(parent, textvariable=self.email_password_file_var)
        file_entry.grid(row=5, column=3, sticky="ew", padx=8, pady=5)
        ToolTip(env_entry, "只保存环境变量名，不保存邮箱授权码本身。")
        ToolTip(file_entry, "只保存文件路径。默认读取项目根目录 smtp_password.txt。")

        ttk.Label(parent, text="邮件标题").grid(row=6, column=0, sticky="w", padx=10, pady=5)
        subject_entry = ttk.Entry(parent, textvariable=self.email_subject_template_var)
        subject_entry.grid(row=6, column=1, columnspan=3, sticky="ew", padx=8, pady=5)
        ToolTip(subject_entry, "可用变量：{part_name}、{title}、{part_no}。")

        buttons = ttk.Frame(parent)
        buttons.grid(row=7, column=0, columnspan=4, sticky="e", padx=10, pady=(4, 8))
        ttk.Button(buttons, text="重新读取", command=self._load_email_config_vars).pack(side="right", padx=(8, 0))
        ttk.Button(buttons, text="保存邮箱配置", command=lambda: self._save_email_config_from_vars(show_message=True)).pack(side="right")
        ttk.Button(buttons, text="测试邮件", command=self._test_email_connection).pack(side="right", padx=(0, 8))
        ttk.Button(buttons, text="设置说明", command=self._show_email_help).pack(side="right", padx=(0, 8))

    def _show_email_help(self) -> None:
        win = tk.Toplevel(self)
        win.title("邮箱设置说明")
        win.geometry("760x560")
        win.transient(self)

        frame = ttk.Frame(win, padding=12)
        frame.pack(fill="both", expand=True)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)

        text = scrolledtext.ScrolledText(frame, wrap="word", font=self._font_tuple(10), height=26)
        text.grid(row=0, column=0, sticky="nsew")
        help_text = """邮箱发送设置说明

一、先设置发件箱（以 QQ 邮箱为例）
1. 打开 QQ 邮箱网页版，进入“设置”。
2. 找到“账户”或“POP3/IMAP/SMTP/Exchange/CardDAV/CalDAV 服务”。
3. 开启 SMTP 服务。QQ 邮箱通常会要求短信验证。
4. 开启后会生成“授权码”。这里要用授权码登录 SMTP，不要填写 QQ 密码。

二、主界面参数怎么填
收件邮箱：
  接收素材包的邮箱。多个邮箱用英文逗号分隔。
  当前默认测试邮箱：399467826@qq.com

SMTP：
  QQ 邮箱一般填 smtp.qq.com。

端口：
  勾选“使用 SSL”时，QQ 邮箱一般填 465。
  如果不用 SSL，常见端口是 587，但本工具默认推荐 SSL + 465。

登录账号：
  发件邮箱完整地址，例如 你的QQ号@qq.com。

发件人：
  通常和登录账号相同；留空时程序会自动使用登录账号。

密码变量 / 密码文件：
  为了安全，主界面不保存授权码本身，只保存读取位置。
  方式 A：设置环境变量 AMP_SMTP_PASSWORD，值填 QQ 邮箱授权码。
  方式 B：在项目根目录创建 smtp_password.txt，文件里只放授权码。

附件上限 MB：
  每集素材包超过这个大小时会跳过发送，避免邮箱拒收。默认 20MB。

邮件标题：
  可以使用变量 {part_name}、{title}、{part_no}。
  例如：著作解读分集完成：{part_name}

三、开启发送
1. 填好参数后，点击“保存邮箱配置”。
2. 勾选“每集完成后打包发送邮件”。
3. 开始运行。每个分集完成后，程序会自动打包 zip 并发送邮件。

四、排查
如果发送失败，先检查：
1. 是否开启了 SMTP 服务。
2. 是否使用“授权码”，而不是 QQ 密码。
3. smtp_password.txt 是否放在项目根目录。
4. 收件邮箱是否填写正确。
5. 附件是否超过邮箱限制。
"""
        text.insert("1.0", help_text)
        text.configure(state="disabled")

        footer = ttk.Frame(frame)
        footer.grid(row=1, column=0, sticky="e", pady=(10, 0))
        ttk.Button(footer, text="关闭", command=win.destroy).pack(side="right")

    def _build_models(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(2, weight=1)
        parent.columnconfigure(3, weight=0)
        ttk.Label(parent, text="四个大模型设置", font=self._font_tuple(10, "bold")).grid(
            row=0, column=0, columnspan=4, sticky="w", padx=10, pady=(8, 4)
        )
        ttk.Label(parent, text="阶段", foreground="#555").grid(row=1, column=0, sticky="w", padx=10, pady=(0, 4))
        ttk.Label(parent, text="来源", foreground="#555").grid(row=1, column=1, sticky="w", padx=8, pady=(0, 4))
        ttk.Label(parent, text="模型名", foreground="#555").grid(row=1, column=2, sticky="w", padx=8, pady=(0, 4))
        ttk.Label(parent, text="连接", foreground="#555").grid(row=1, column=3, sticky="w", padx=8, pady=(0, 4))

        for idx, (stage, title, tip) in enumerate(TEXT_STAGES, start=2):
            label = ttk.Label(parent, text=title)
            label.grid(row=idx, column=0, sticky="w", padx=10, pady=5)
            ToolTip(label, tip)

            provider = ttk.Combobox(
                parent,
                textvariable=self.stage_provider_vars[stage],
                values=["gemini", "openai", "deepseek"],
                state="readonly",
                width=12,
            )
            provider.grid(row=idx, column=1, sticky="ew", padx=8, pady=5)
            provider.bind("<<ComboboxSelected>>", lambda _event, st=stage: self._on_stage_provider_change(st))
            ToolTip(provider, "只保留大纲、脚本、台词润色三个文本模型；绘图模型在下方设置。")

            combo = ttk.Combobox(
                parent,
                textvariable=self.stage_model_vars[stage],
                values=TEXT_MODEL_OPTIONS["gemini"],
                state="normal",
            )
            combo.grid(row=idx, column=2, sticky="ew", padx=8, pady=5)
            self.stage_model_combos[stage] = combo
            ToolTip(combo, "默认：大纲 Gemini，脚本 GPT-5.5，台词润色 DeepSeek V4 Pro。")
            ttk.Button(parent, text="测试", command=lambda st=stage: self._test_text_stage_connection(st), width=8).grid(
                row=idx, column=3, sticky="ew", padx=(0, 10), pady=5
            )

        ttk.Label(parent, text="默认：大纲 Gemini；脚本 GPT-5.5；绘图 GPT-image2；台词润色 DeepSeek V4 Pro。", foreground="#555").grid(
            row=5, column=0, columnspan=4, sticky="w", padx=10, pady=(4, 8)
        )

        save_frame = ttk.Frame(parent)
        save_frame.grid(row=6, column=0, columnspan=4, sticky="ew", padx=8, pady=(0, 7))
        ttk.Checkbutton(save_frame, text="运行时保存 Key", variable=self.save_keys_var).pack(side="left", padx=(2, 10))
        ttk.Button(save_frame, text="保存 Key", command=self._save_key_files).pack(side="left", padx=(0, 8))

        base_frame = ttk.LabelFrame(parent, text="OpenAI 兼容中转")
        base_frame.grid(row=7, column=0, columnspan=4, sticky="ew", padx=10, pady=(8, 8))
        base_frame.columnconfigure(1, weight=1)
        ttk.Label(base_frame, text="官网").grid(row=0, column=0, sticky="w", padx=8, pady=4)
        ttk.Label(base_frame, text="https://greatwalllink.top", foreground="#555").grid(row=0, column=1, sticky="w", padx=8, pady=4)
        ttk.Label(base_frame, text="BaseURL").grid(row=1, column=0, sticky="w", padx=8, pady=4)
        base_entry = ttk.Entry(base_frame, textvariable=self.foreign_base_url_var)
        base_entry.grid(row=1, column=1, sticky="ew", padx=8, pady=4)
        ToolTip(base_entry, "Gemini、OpenAI 兼容文本模型和生图模型默认使用这个 /v1 端点。")
        ttk.Label(base_frame, text="推荐 Gemini 模型").grid(row=2, column=0, sticky="w", padx=8, pady=4)
        ttk.Label(base_frame, text="gemini-3.1-pro-preview", foreground="#555").grid(row=2, column=1, sticky="w", padx=8, pady=4)
        ttk.Label(base_frame, text="DeepSeek").grid(row=3, column=0, sticky="w", padx=8, pady=4)
        ttk.Label(base_frame, text=f"不中转，默认 {DEFAULT_DEEPSEEK_BASE_URL}", foreground="#555").grid(row=3, column=1, sticky="w", padx=8, pady=4)

        vault = ttk.LabelFrame(parent, text="API Key（可保存）")
        vault.grid(row=8, column=0, columnspan=4, sticky="ew", padx=10, pady=(8, 8))
        vault.columnconfigure(1, weight=1)
        ttk.Label(vault, text="Gemini").grid(row=0, column=0, sticky="w", padx=8, pady=4)
        ttk.Entry(vault, textvariable=self.gemini_key_var).grid(row=0, column=1, sticky="ew", padx=8, pady=4)
        ttk.Label(vault, text="OpenAI").grid(row=1, column=0, sticky="w", padx=8, pady=4)
        ttk.Entry(vault, textvariable=self.openai_key_var).grid(row=1, column=1, sticky="ew", padx=8, pady=4)
        ttk.Label(vault, text="DeepSeek").grid(row=2, column=0, sticky="w", padx=8, pady=4)
        ttk.Entry(vault, textvariable=self.deepseek_key_var).grid(row=2, column=1, sticky="ew", padx=8, pady=4)
        ttk.Label(vault, text="GPT-image2").grid(row=3, column=0, sticky="w", padx=8, pady=4)
        ttk.Entry(vault, textvariable=self.image_api_key_var).grid(row=3, column=1, sticky="ew", padx=8, pady=4)
        ttk.Button(vault, text="保存全部 Key", command=self._save_all_key_files).grid(row=4, column=1, sticky="e", padx=8, pady=(2, 6))
        ToolTip(vault, "当前简洁模式只显示四模型需要的 Key；更多兼容 Key 可点顶部 Key。")

        sep = ttk.Separator(parent)
        sep.grid(row=9, column=0, columnspan=4, sticky="ew", padx=10, pady=10)

        ttk.Label(parent, text="绘图模型来源").grid(row=10, column=0, sticky="w", padx=10, pady=7)
        image_provider = ttk.Combobox(parent, textvariable=self.image_provider_var, values=["openai", "none", "dry-run"], state="readonly")
        image_provider.grid(row=10, column=1, columnspan=2, sticky="ew", padx=8, pady=7)
        image_provider.bind("<<ComboboxSelected>>", self._on_image_provider_change)
        ToolTip(image_provider, "none 表示不调用生图接口；dry-run 只保存图片提示词。")

        ttk.Label(parent, text="绘图模型").grid(row=11, column=0, sticky="w", padx=10, pady=7)
        self.image_model_combo = ttk.Combobox(parent, textvariable=self.image_model_var, values=IMAGE_MODEL_OPTIONS["none"], state="normal")
        self.image_model_combo.grid(row=11, column=1, columnspan=2, sticky="ew", padx=8, pady=7)
        ToolTip(self.image_model_combo, "默认 gpt-image-2，经 NewAPI/OpenAI 兼容中转请求。")
        ttk.Button(parent, text="测试绘图", command=self._test_image_connection, width=8).grid(row=11, column=3, sticky="ew", padx=(0, 10), pady=7)

    def _browse_book(self) -> None:
        path = filedialog.askopenfilename(title="选择书籍 PDF", filetypes=[("PDF 文件", "*.pdf"), ("所有文件", "*.*")])
        if not path:
            return
        self.book_var.set(path)
        self._sync_output_dir_for_book(force=True)

    def _browse_out(self) -> None:
        path = filedialog.askdirectory(title="选择输出目录")
        if path:
            self.out_var.set(path)
            self._last_auto_out = ""
            self._last_book_for_auto_out = self.book_var.get().strip().strip('"')

    def _browse_continue_folder(self) -> None:
        path = filedialog.askdirectory(title="选择要续作的已有输出目录 / 分集目录")
        if path:
            self.continue_folder_var.set(path)
            if not self.out_var.get().strip():
                self.out_var.set(path)

    def _browse_outline(self) -> None:
        path = filedialog.askopenfilename(title="选择已有大纲 JSON", filetypes=[("JSON 文件", "*.json"), ("文本文件", "*.txt"), ("所有文件", "*.*")])
        if path:
            self.outline_json_var.set(path)

    def _on_stage_provider_change(self, stage: str) -> None:
        provider = self.stage_provider_vars[stage].get().strip() or "gemini"
        if provider not in TEXT_MODEL_OPTIONS:
            provider = "openai" if stage == "script" else "deepseek" if stage == "polish" else "gemini"
            self.stage_provider_vars[stage].set(provider)
        options = TEXT_MODEL_OPTIONS.get(provider, [""])
        combo = self.stage_model_combos.get(stage)
        if combo is not None:
            combo.configure(values=options)
        current = self.stage_model_vars[stage].get().strip()
        all_known = {m for models in TEXT_MODEL_OPTIONS.values() for m in models}
        if stage == "script" and provider == "openai":
            if not current or current not in all_known:
                self.stage_model_vars[stage].set(DEFAULT_OPENAI_TEXT_MODEL)
        elif stage == "polish" and provider == "deepseek":
            if not current or current not in all_known:
                self.stage_model_vars[stage].set("deepseek-v4-pro")
        elif not current or current not in all_known:
            if provider == "doubao":
                endpoint = self.doubao_endpoint_var.get().strip() or doubao_env_model()
                if endpoint and not doubao_model_looks_like_api_key(endpoint):
                    self.stage_model_vars[stage].set(endpoint)
                else:
                    self.stage_model_vars[stage].set(options[0] if options else "")
            else:
                self.stage_model_vars[stage].set(options[0] if options else "")
        self._last_stage_providers[stage] = provider
        self._load_all_key_vars(overwrite=False)
        self._schedule_settings_save()

    def _on_image_provider_change(self, _event=None) -> None:
        provider = self.image_provider_var.get()
        if provider not in {"none", "dry-run"}:
            self.skip_images_var.set(False)
        options = IMAGE_MODEL_OPTIONS.get(provider, [""])
        self.image_model_combo.configure(values=options)
        current = self.image_model_var.get().strip()
        all_known = {m for models in IMAGE_MODEL_OPTIONS.values() for m in models}
        if not current or current not in all_known:
            self.image_model_var.set(options[0] if options else "")
        self._load_all_key_vars(overwrite=False)
        self._last_image_provider = provider
        self._schedule_settings_save()

    def _key_var_for_provider(self, provider: str) -> tk.StringVar | None:
        return {
            "gemini": self.gemini_key_var,
            "openai": self.openai_key_var,
            "doubao": self.doubao_key_var,
            "deepseek": self.deepseek_key_var,
        }.get(provider)

    def _normalized_foreign_base_url(self) -> str:
        base_url = self.foreign_base_url_var.get().strip() or DEFAULT_FOREIGN_MODEL_BASE_URL
        base_url = base_url.replace("greatwallink.top", "greatwalllink.top")
        if not base_url.endswith("/v1"):
            base_url = base_url.rstrip("/") + "/v1"
        self.foreign_base_url_var.set(base_url)
        return base_url

    def _test_text_stage_connection(self, stage: str) -> None:
        provider = self.stage_provider_vars.get(stage, tk.StringVar(value="")).get().strip() or "gemini"
        model = self.stage_model_vars.get(stage, tk.StringVar(value="")).get().strip()
        if provider == "gemini":
            model = canonical_gemini_model(model)
            if model:
                self.stage_model_vars[stage].set(model)
        if provider in {"dry-run", "none"}:
            messagebox.showinfo("测试连接", "dry-run/none 不需要测试连接。")
            return
        key_var = self._key_var_for_provider(provider)
        api_key = key_var.get().strip() if key_var is not None else ""
        api_key = api_key or read_api_key(provider, "")
        if not api_key:
            messagebox.showerror("测试连接", f"{provider} API Key 为空，请先填写或保存 Key。")
            return
        if not model:
            messagebox.showerror("测试连接", "模型名为空，请先选择或填写模型名。")
            return
        base_url = deepseek_base_url() if provider == "deepseek" else self._normalized_foreign_base_url()
        self._append_log(f"🔌 测试连接：{stage} / {provider} / {model} / {base_url}")
        thread = threading.Thread(target=self._test_model_worker, args=(provider, model, api_key, base_url, stage), daemon=True)
        thread.start()

    def _test_image_connection(self) -> None:
        provider = self.image_provider_var.get().strip() or "openai"
        model = self.image_model_var.get().strip()
        if provider in {"dry-run", "none"}:
            messagebox.showinfo("测试连接", "none/dry-run 不需要测试绘图连接。")
            return
        api_key = self.image_api_key_var.get().strip() or read_api_key("image", "")
        if not api_key:
            messagebox.showerror("测试连接", "绘图 API Key 为空，请先填写 GPT-image2 Key。")
            return
        if not model:
            messagebox.showerror("测试连接", "绘图模型名为空，请先选择或填写模型名。")
            return
        base_url = self._normalized_foreign_base_url()
        self._append_log(f"🔌 测试绘图模型：{provider} / {model} / {base_url}")
        thread = threading.Thread(target=self._test_model_worker, args=("image", model, api_key, base_url, "image"), daemon=True)
        thread.start()

    def _test_model_worker(self, provider: str, model: str, api_key: str, base_url: str, label: str) -> None:
        started = time.perf_counter()
        try:
            is_image_test = label == "image"
            client = openai_compatible_client(
                api_key=api_key,
                base_url=base_url,
                timeout=240 if is_image_test else 30,
                max_retries=0 if is_image_test else None,
            )
            if label == "image":
                if provider == "gemini" or model.startswith("gemini-"):
                    gemini_base = base_url.rsplit("/v1", 1)[0].rstrip("/")
                    resp = requests_post_no_proxy(
                        f"{gemini_base}/v1beta/models/{model}:generateContent",
                        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                        json={
                            "contents": [{"role": "user", "parts": [{"text": "A simple neutral educational book-cover background, no text, no logo."}]}],
                            "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
                        },
                        timeout=240,
                    )
                    resp.raise_for_status()
                    elapsed = time.perf_counter() - started
                    self.log_queue.put(("log", f"✅ 测试绘图连接成功：provider=gemini，model={model}，base={base_url}，耗时 {elapsed:.1f}s，接口：generateContent"))
                    return
                payload = {
                    "model": model,
                    "prompt": "A simple neutral educational book-cover background, no text, no logo.",
                    "size": normalize_openai_image_size_for_model(model, "720x1280"),
                }
                if model.startswith("gpt-image"):
                    payload["quality"] = default_image_quality()
                try:
                    response = client.images.generate(**payload)
                except Exception as first_exc:
                    text = str(first_exc)
                    if "quality" in payload and ("Unsupported" in text or "unsupported" in text or "quality" in text):
                        payload.pop("quality", None)
                        response = client.images.generate(**payload)
                    else:
                        raise
                data = getattr(response, "data", None) or []
                if not data:
                    raise RuntimeError("图片接口未返回 data。")
                first = data[0]
                if not (getattr(first, "b64_json", None) or getattr(first, "url", None)):
                    raise RuntimeError("图片接口未返回 b64_json 或 url。")
                elapsed = time.perf_counter() - started
                self.log_queue.put(("log", f"✅ 测试绘图连接成功：provider={provider}，model={model}，base={base_url}，耗时 {elapsed:.1f}s，接口：images.generate，尺寸：{payload.get('size')}"))
                return
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "Connection test. Reply with exactly: OK"}],
                max_tokens=8,
                temperature=0,
            )
            content = _extract_chat_content(response)
            if not content:
                raise RuntimeError(f"模型返回为空或格式不可识别：{type(response).__name__}")
            elapsed = time.perf_counter() - started
            self.log_queue.put(("log", f"✅ 测试连接成功：stage={label}，provider={provider}，model={model}，base={base_url}，耗时 {elapsed:.1f}s，返回：{content[:80] or '空'}"))
        except Exception as exc:
            elapsed = time.perf_counter() - started
            self.log_queue.put(("log", f"❌ 测试连接失败：stage={label}，provider={provider}，model={model}，base={base_url}，耗时 {elapsed:.1f}s，错误：{type(exc).__name__}: {exc}"))

    def _read_ui_key_file(self, provider: str) -> str:
        """Read only the provider's own key file for display in the GUI.

        The relay domain can be shared, but each model/provider keeps its own
        API key file and visible key box.
        """
        filename = KEY_FILE_NAMES.get(provider)
        if not filename:
            return ""
        try:
            return (PROJECT_ROOT / filename).read_text(encoding="utf-8-sig").strip()
        except Exception:
            return ""

    def _sync_current_key_fields_to_provider_vars(self, text_provider: str | None = None, image_provider: str | None = None) -> None:
        # The current UI exposes all key fields directly, so there is no separate
        # per-stage key textbox to sync. Keep this method for compatibility with
        # older saved settings and older button callbacks.
        return

    def _load_all_key_vars(self, overwrite: bool = False) -> None:
        for provider, var in [
            ("gemini", self.gemini_key_var),
            ("openai", self.openai_key_var),
            ("image", self.image_api_key_var),
            ("doubao", self.doubao_key_var),
            ("deepseek", self.deepseek_key_var),
        ]:
            if overwrite or not var.get().strip():
                key = self._read_ui_key_file(provider)
                if key:
                    var.set(key)
        if overwrite or not self.doubao_endpoint_var.get().strip():
            endpoint = doubao_env_model()
            if endpoint and not doubao_model_looks_like_api_key(endpoint):
                self.doubao_endpoint_var.set(endpoint)

    def _load_keys_for_current_provider(self, overwrite: bool = False) -> None:
        self._load_all_key_vars(overwrite=overwrite)

    def _save_all_key_files(self, show_message: bool = True) -> bool:
        self._sync_current_key_fields_to_provider_vars()
        saved = []
        cleared = []
        pairs = [
            ("gemini", self.gemini_key_var.get().strip()),
            ("openai", self.openai_key_var.get().strip()),
            ("image", self.image_api_key_var.get().strip()),
            ("doubao", self.doubao_key_var.get().strip()),
            ("deepseek", self.deepseek_key_var.get().strip()),
        ]
        for provider, key in pairs:
            if provider not in KEY_FILE_NAMES:
                continue
            filename = KEY_FILE_NAMES[provider]
            path = PROJECT_ROOT / filename
            if key:
                write_text(path, key + "\n")
                saved.append(filename)
            elif path.exists():
                try:
                    path.unlink()
                    cleared.append(f"{filename} (cleared)")
                except Exception:
                    pass
        endpoint = self.doubao_endpoint_var.get().strip()
        if endpoint:
            if doubao_model_looks_like_api_key(endpoint):
                if show_message:
                    messagebox.showerror("豆包接入点填写错误", "豆包接入点看起来像 API Key。请填写 ep-... 接入点 ID，API Key 填到豆包 Key 输入框。")
                return False
            write_text(PROJECT_ROOT / DOUBAO_ENDPOINT_FILE_NAME, endpoint + "\n")
            saved.append(DOUBAO_ENDPOINT_FILE_NAME)
        saved.extend(cleared)
        if saved:
            self._append_log("已保存 Key/接入点文件：" + "、".join(saved))
            if show_message:
                messagebox.showinfo("Key/接入点已保存", "已保存到项目根目录：\n" + "\n".join(saved))
            return True
        if show_message:
            messagebox.showinfo("没有可保存的内容", "当前没有填写可保存的 API Key 或豆包接入点。")
        return False

    def _save_key_files(self) -> bool:
        return self._save_all_key_files(show_message=True)

    def _show_key_manager(self) -> None:
        self._load_all_key_vars(overwrite=False)
        win = tk.Toplevel(self)
        win.title("API Key 管理")
        win.geometry("760x360")
        win.transient(self)
        frame = ttk.Frame(win, padding=14)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)
        fields = [
            ("Gemini API Key", self.gemini_key_var, "gemini_api_key.txt", True),
            ("OpenAI API Key", self.openai_key_var, "openai_api_key.txt", True),
            ("GPT-image2 API Key", self.image_api_key_var, "image_api_key.txt", True),
            ("豆包/火山方舟 API Key", self.doubao_key_var, "ark_api_key.txt", True),
            ("DeepSeek API Key", self.deepseek_key_var, "deepseek_api_key.txt", True),
            ("豆包接入点 ID", self.doubao_endpoint_var, DOUBAO_ENDPOINT_FILE_NAME, False),
        ]
        for row, (label, var, filename, is_secret) in enumerate(fields):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", padx=8, pady=8)
            entry = ttk.Entry(frame, textvariable=var)
            entry.grid(row=row, column=1, sticky="ew", padx=8, pady=8)
            ttk.Label(frame, text=filename, foreground="#666").grid(row=row, column=2, sticky="w", padx=8, pady=8)
        tip = ttk.Label(frame, text="Key 与豆包接入点会保存为项目根目录下的 txt 文件；程序运行时会自动读取。", foreground="#555")
        tip.grid(row=5, column=0, columnspan=3, sticky="w", padx=8, pady=(8, 4))
        buttons = ttk.Frame(frame)
        buttons.grid(row=6, column=0, columnspan=3, sticky="e", padx=8, pady=(12, 0))
        ttk.Button(buttons, text="保存全部 Key/接入点", command=lambda: (self._save_all_key_files(show_message=True), win.destroy())).pack(side="right", padx=(8, 0))
        ttk.Button(buttons, text="取消", command=win.destroy).pack(side="right")

    def _read_runtime_switches_config(self) -> dict:
        try:
            data = json.loads(RUNTIME_SWITCHES_CONFIG_PATH.read_text(encoding="utf-8-sig"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _write_runtime_switches_config(self, data: dict) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        RUNTIME_SWITCHES_CONFIG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_email_config_vars(self) -> None:
        root = self._read_runtime_switches_config()
        config = root.get("email_delivery") if isinstance(root.get("email_delivery"), dict) else {}
        recipients = config.get("to", ["399467826@qq.com"])
        if isinstance(recipients, list):
            recipient_text = ", ".join(str(x).strip() for x in recipients if str(x).strip())
        else:
            recipient_text = str(recipients or "").strip()

        self.email_enabled_var.set(bool(config.get("enabled", False)))
        self.email_smtp_host_var.set(str(config.get("smtp_host") or "smtp.qq.com"))
        self.email_smtp_port_var.set(str(config.get("smtp_port") or 465))
        self.email_use_ssl_var.set(bool(config.get("use_ssl", True)))
        self.email_username_var.set(str(config.get("username") or ""))
        self.email_from_var.set(str(config.get("from") or ""))
        self.email_to_var.set(recipient_text or "399467826@qq.com")
        self.email_password_env_var.set(str(config.get("password_env") or "AMP_SMTP_PASSWORD"))
        self.email_password_file_var.set(str(config.get("password_file") or "smtp_password.txt"))
        self.email_max_mb_var.set(str(config.get("max_attachment_mb") or 20))
        self.email_subject_template_var.set(str(config.get("subject_template") or "著作解读分集完成：{part_name}"))

    def _email_config_from_vars(self) -> dict | None:
        try:
            port = int(self.email_smtp_port_var.get().strip() or "465")
            if port <= 0:
                raise ValueError
        except Exception:
            messagebox.showerror("邮箱配置错误", "SMTP 端口必须是正整数。")
            return None
        try:
            max_mb = int(self.email_max_mb_var.get().strip() or "20")
            if max_mb <= 0:
                raise ValueError
        except Exception:
            messagebox.showerror("邮箱配置错误", "附件上限 MB 必须是正整数。")
            return None

        recipients = [x.strip() for x in self.email_to_var.get().replace("；", ",").replace("，", ",").split(",") if x.strip()]
        enabled = bool(self.email_enabled_var.get())
        host = self.email_smtp_host_var.get().strip() or "smtp.qq.com"
        username = self.email_username_var.get().strip()
        sender = self.email_from_var.get().strip() or username
        password_env = self.email_password_env_var.get().strip() or "AMP_SMTP_PASSWORD"
        password_file = self.email_password_file_var.get().strip() or "smtp_password.txt"
        subject_template = self.email_subject_template_var.get().strip() or "著作解读分集完成：{part_name}"

        if enabled:
            missing = []
            if not recipients:
                missing.append("收件邮箱")
            if not host:
                missing.append("SMTP")
            if not username:
                missing.append("登录账号")
            if not sender:
                missing.append("发件人")
            if missing:
                messagebox.showerror("邮箱配置错误", "开启邮箱发送前请补全：" + "、".join(missing))
                return None

        return {
            "enabled": enabled,
            "smtp_host": host,
            "smtp_port": port,
            "use_ssl": bool(self.email_use_ssl_var.get()),
            "username": username,
            "from": sender,
            "to": recipients or ["399467826@qq.com"],
            "password_env": password_env,
            "password_file": password_file,
            "max_attachment_mb": max_mb,
            "subject_template": subject_template,
        }

    def _save_email_config_from_vars(self, *, show_message: bool = False) -> bool:
        config = self._email_config_from_vars()
        if config is None:
            return False
        root = self._read_runtime_switches_config()
        root["email_delivery"] = config
        try:
            self._write_runtime_switches_config(root)
        except Exception as exc:
            messagebox.showerror("保存邮箱配置失败", str(exc))
            return False
        if show_message:
            messagebox.showinfo("已保存", f"邮箱配置已写入：\n{RUNTIME_SWITCHES_CONFIG_PATH}")
        return True

    def _test_email_connection(self) -> None:
        if not self._save_email_config_from_vars(show_message=False):
            return
        self._append_log("📧 开始测试邮箱连接：会尝试登录 SMTP，并发送一封小测试邮件。")
        thread = threading.Thread(target=self._test_email_worker, daemon=True)
        thread.start()

    def _test_email_worker(self) -> None:
        started = time.perf_counter()

        def emit(message: str) -> None:
            self.log_queue.put(("log", "📧 " + str(message)))

        try:
            result = test_email_connection(send_test=True, logger=emit)
            elapsed = time.perf_counter() - started
            if result.get("ok"):
                sent_text = "已发送测试邮件" if result.get("sent") else "仅测试连接"
                self.log_queue.put(("log", f"✅ 邮箱测试成功：{sent_text}，耗时 {elapsed:.1f}s"))
            else:
                self.log_queue.put(("log", f"❌ 邮箱测试失败，耗时 {elapsed:.1f}s：{result.get('reason') or result.get('error') or '未知原因'}"))
                smtp_info = result.get("smtp") if isinstance(result.get("smtp"), dict) else {}
                if smtp_info:
                    self.log_queue.put((
                        "log",
                        "📧 SMTP 配置："
                        f"{smtp_info.get('host') or ''}:{smtp_info.get('port') or ''}，"
                        f"SSL={smtp_info.get('use_ssl')}，"
                        f"登录账号={smtp_info.get('username') or ''}，"
                        f"发件人={smtp_info.get('sender') or ''}，"
                        f"收件人={', '.join(smtp_info.get('recipients') or [])}",
                    ))
                warnings = result.get("warnings") if isinstance(result.get("warnings"), list) else []
                for warning in warnings:
                    self.log_queue.put(("log", f"📧 配置提醒：{warning}"))
                if result.get("hint"):
                    self.log_queue.put(("log", f"📧 排查建议：{result.get('hint')}"))
                if result.get("stage") or result.get("error_type"):
                    self.log_queue.put(("log", f"📧 失败阶段：{result.get('stage') or '未知'}；异常类型：{result.get('error_type') or '未知'}"))
                if result.get("traceback"):
                    self.log_queue.put(("log", "📧 邮箱测试 traceback：\n" + str(result.get("traceback"))))
        except Exception as exc:
            elapsed = time.perf_counter() - started
            self.log_queue.put(("log", f"❌ 邮箱测试异常，耗时 {elapsed:.1f}s：{type(exc).__name__} - {exc}"))
            self.log_queue.put(("log", "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).rstrip()))

    def _validate(self) -> PipelineArgs | None:
        if not self._sync_prompt_editors_to_memory(save_files=True, show_log=False):
            return None
        if not self._save_email_config_from_vars(show_message=False):
            return None
        os.environ["NEWAPI_BASE_URL"] = self._normalized_foreign_base_url()
        continue_mode = bool(self.continue_from_existing_folder_var.get())
        continue_folder: Path | None = None

        if continue_mode:
            continue_text = self.continue_folder_var.get().strip().strip('"')
            if not continue_text:
                messagebox.showerror("缺少续作文件夹", "请先选择一个已有输出目录或分集目录。")
                return None
            continue_folder = Path(continue_text).expanduser()
            if not continue_folder.exists() or not continue_folder.is_dir():
                messagebox.showerror("找不到续作文件夹", f"目录不存在：\n{continue_folder}")
                return None
            # 指定文件夹续作模式不再强制要求 PDF；book 字段用续作目录占位，runner 会直接读取 continue_from_folder。
            book = continue_folder
        else:
            book_text = self.book_var.get().strip().strip('"')
            if not book_text:
                messagebox.showerror("缺少 PDF", "请先选择一本书籍 PDF。")
                return None
            book = Path(book_text).expanduser()
            if not book.exists():
                messagebox.showerror("找不到 PDF", f"文件不存在：\n{book}")
                return None
            if book.suffix.lower() != ".pdf":
                messagebox.showerror("文件类型不正确", "当前程序只支持 PDF。")
                return None

        out_text = self.out_var.get().strip().strip('"')
        if not out_text and continue_mode and continue_folder is not None:
            out_text = str(continue_folder)
            self.out_var.set(out_text)
        auto_out = self._default_out_for_book_text(str(book)) if not continue_mode else ""
        if (
            (not out_text or _is_project_outputs_path(out_text) or out_text == getattr(self, "_last_auto_out", ""))
            and not continue_mode
            and auto_out
        ):
            out_text = auto_out
            self.out_var.set(out_text)
            self._last_book_for_auto_out = str(book)
            self._last_auto_out = out_text
        if (not out_text or _is_project_outputs_path(out_text)) and not continue_mode:
            out_text = str(default_output_dir_for_book(book))
            self.out_var.set(out_text)
        if not out_text:
            messagebox.showerror("缺少输出目录", "请选择输出目录。")
            return None
        out = Path(out_text).expanduser()

        try:
            max_retries = int(self.max_retries_var.get())
            if max_retries < 0:
                raise ValueError
        except Exception:
            messagebox.showerror("参数错误", "重试次数必须是 0 或正整数。")
            return None

        outline_path = None
        outline_text = self.outline_json_var.get().strip().strip('"')
        if outline_text:
            outline_path = Path(outline_text).expanduser()
            if not outline_path.exists():
                messagebox.showerror("找不到大纲", f"已有大纲 JSON 不存在：\n{outline_path}")
                return None

        if self.save_keys_var.get():
            self._save_key_files_quiet()
        else:
            self._load_all_key_vars(overwrite=False)

        def provider_key(provider: str) -> str:
            key_var = self._key_var_for_provider(provider)
            return key_var.get().strip() if key_var is not None else ""

        stage_values = {}
        for stage, title, _tip in TEXT_STAGES:
            provider = self.stage_provider_vars[stage].get().strip() or "gemini"
            model = self.stage_model_vars[stage].get().strip()
            if provider == "gemini":
                fixed_model = canonical_gemini_model(model)
                if fixed_model != model:
                    self._append_log(f"提示：{title} 模型名已自动修正：{model} → {fixed_model}")
                    self.stage_model_vars[stage].set(fixed_model)
                    model = fixed_model
            if provider == "doubao":
                saved_endpoint = self.doubao_endpoint_var.get().strip()
                if not model or model == "ep-请填写推理接入点ID":
                    model = saved_endpoint
                    if model:
                        self.stage_model_vars[stage].set(model)
                if doubao_model_looks_like_api_key(model):
                    messagebox.showerror(
                        "豆包模型名填写错误",
                        f"{title} 的模型名看起来像 API Key。\n\n"
                        "模型名栏请填写火山方舟推理接入点 ID（通常 ep- 开头），"
                        "或 doubao- 开头的可直连 Model ID；API Key 请填写在下方“豆包/火山方舟 API Key”。"
                    )
                    return None
                if saved_endpoint and doubao_model_looks_like_api_key(saved_endpoint):
                    messagebox.showerror(
                        "豆包接入点填写错误",
                        "豆包接入点看起来像 API Key。请填写 ep-... 接入点 ID，API Key 填到豆包 Key 输入框。"
                    )
                    return None
            key = provider_key(provider)
            if provider not in {"dry-run", "none"} and not key and not read_api_key(provider, ""):
                self._append_log(f"提示：{title} 的 {provider} API Key 为空，程序会尝试读取环境变量或本地 key 文件；如果仍为空会报错。")
            stage_values[stage] = (provider, model, key)

        image_provider = self.image_provider_var.get().strip() or "openai"
        image_key = self.image_api_key_var.get().strip() or read_api_key("image", "")
        image_interval = self.image_interval_var.get().strip() or "3-8"

        try:
            start_episode_no = int(self.start_episode_var.get())
            if start_episode_no < 1:
                raise ValueError
        except Exception:
            messagebox.showerror("参数错误", "起始集数必须是大于等于 1 的整数。")
            return None

        start_stage = (self.start_stage_var.get().strip() or "outline")
        if continue_mode and start_stage == "outline":
            start_stage = "images"

        return PipelineArgs(
            book=book.resolve(),
            out=out.resolve(),
            episode_count=0,
            page_offset=0,
            provider=stage_values["outline"][0],
            text_model=stage_values["outline"][1],
            api_key=stage_values["outline"][2],
            outline_provider=stage_values["outline"][0],
            outline_model=stage_values["outline"][1],
            outline_api_key=stage_values["outline"][2],
            episode_prompt_provider=stage_values["script"][0],
            episode_prompt_model=stage_values["script"][1],
            episode_prompt_api_key=stage_values["script"][2],
            script_provider=stage_values["script"][0],
            script_model=stage_values["script"][1],
            script_api_key=stage_values["script"][2],
            polish_provider=stage_values["polish"][0],
            polish_model=stage_values["polish"][1],
            polish_api_key=stage_values["polish"][2],
            transition_provider=stage_values["polish"][0],
            transition_model=stage_values["polish"][1],
            transition_api_key=stage_values["polish"][2],
            split_polish_provider=stage_values["polish"][0],
            split_polish_model=stage_values["polish"][1],
            split_polish_api_key=stage_values["polish"][2],
            final_polish_provider=stage_values["polish"][0],
            final_polish_model=stage_values["polish"][1],
            final_polish_api_key=stage_values["polish"][2],
            book_summary_provider=stage_values["polish"][0],
            book_summary_model=stage_values["polish"][1],
            book_summary_api_key=stage_values["polish"][2],
            image_provider=image_provider,
            image_model=self.image_model_var.get().strip(),
            image_api_key=image_key,
            skip_outline=outline_path.resolve() if outline_path else None,
            skip_images=bool(self.skip_images_var.get()),
            max_retries=max_retries,
            outline_prompt=self.prompt_texts["outline"],
            episode_prompt_builder=self.prompt_texts["episode_builder"],
            script_json_requirement=self.prompt_texts["script_requirement"],
            voiceover_polish_prompt=self.prompt_texts["voiceover_polish"],
            image_interval_seconds=image_interval,
            local_parse_mode=self.local_parse_mode_var.get().strip() or "auto",
            mineru_backend=self.local_pdf_parser_var.get().strip() or DEFAULT_LOCAL_PDF_PARSER,
            mineru_api_url="",
            mineru_cache_dir=str(out.resolve() / "_pymupdf4llm_cache"),
            auto_resume=bool(self.auto_resume_var.get()),
            skip_existing_text=bool(self.skip_existing_text_var.get()),
            skip_existing_images=bool(self.skip_existing_images_var.get()),
            only_missing_images=bool(self.only_missing_images_var.get()),
            only_postprocess=bool(self.only_postprocess_var.get()),
            start_episode_no=start_episode_no,
            start_stage=start_stage,
            continue_from_folder=continue_folder.resolve() if continue_folder is not None else None,
            test_b_image_limit=0,
            stop_event=self.cancel_event,
        )

    def _save_key_files_quiet(self) -> None:
        self._save_all_key_files(show_message=False)

    def _run_dry(self) -> None:
        for stage, _title, _tip in TEXT_STAGES:
            self.stage_provider_vars[stage].set("dry-run")
            self.stage_model_vars[stage].set("")
            self._on_stage_provider_change(stage)
        self.image_provider_var.set("none")
        self.image_model_var.set("")
        self.skip_images_var.set(True)
        self._run()

    def _run_quick_test(self) -> None:
        self._run(test_b_image_limit=1)

    def _run(self, test_b_image_limit: int = 0) -> None:
        if self.running:
            messagebox.showinfo("正在运行", "当前任务还在运行。可以点击“停止”安全停止。")
            return
        self.cancel_event = threading.Event()
        args = self._validate()
        if args is None:
            self.cancel_event = None
            return
        args.test_b_image_limit = max(0, int(test_b_image_limit or 0))
        self._save_settings()
        self.last_output_dir = args.out
        self.running = True
        self.status_var.set("运行中…")
        self._set_running_state(True)
        self.progress.start(10)
        self._clear_log()
        self._append_log("开始运行。当前流程：生成大纲 → 分集提示词 → 切分 PDF → 生成脚本 → 台词润色 → 配图/后处理 → 拆分脚本与图片。")
        self._append_log("PDF 策略：禁止 PDF 直传；只把本地 PyMuPDF4LLM/pypdf 解析后的 Markdown/文本传给模型。")
        self._append_log(f"本地解析：{args.local_parse_mode} / 解析器={args.mineru_backend}")
        for label, provider, model in [
            ("大纲生成", args.outline_provider, args.outline_model),
            ("脚本生成", args.script_provider, args.script_model),
            ("台词润色", args.polish_provider, args.polish_model),
        ]:
            self._append_log(f"{label}模型：{provider} / {model or '默认模型'}")
        self._append_log(f"生图模型：{args.image_provider} / {args.image_model or '默认模型'}")
        if args.test_b_image_limit:
            self._append_log(f"测试运行：先生成/复用全文故事线大纲；B 图只生成/处理前 {args.test_b_image_limit} 张，后续仍执行拆分、打包并尝试发送邮件。")
        self._append_log(f"配图节奏：每句台词对应一幕画面，单幕约 {args.image_interval_seconds} 秒。")
        self._append_log("分集数量：优先由大纲模型阅读全文后按故事线决定；可组合全书不同位置的材料，章节页码只作为原文定位依据。")
        self._append_log(f"输入 PDF：{args.book}")
        self._append_log(f"输出目录：{args.out}")
        thread = threading.Thread(target=self._worker, args=(args,), daemon=True)
        thread.start()

    def _stop(self) -> None:
        if not self.running or self.cancel_event is None:
            return
        self.cancel_event.set()
        self.stop_button.configure(state="disabled")
        self.stop_button_top.configure(state="disabled")
        self._append_log("已请求停止：当前 API 请求返回后，程序会在下一步前安全停止。")

    def _worker(self, args: PipelineArgs) -> None:
        def handler(message: str) -> None:
            self.log_queue.put(("log", message))

        set_log_handler(handler)
        try:
            run_pipeline(args)
            self.log_queue.put(("done", True, False, str(args.out), ""))
        except PipelineCancelled as exc:
            self.log_queue.put(("done", False, True, str(args.out), str(exc)))
        except Exception as exc:
            detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            self.log_queue.put(("log", detail))
            self.log_queue.put(("done", False, False, str(args.out), str(exc)))
        finally:
            set_log_handler(None)

    def _poll_queue(self) -> None:
        try:
            while True:
                item = self.log_queue.get_nowait()
                if item[0] == "log":
                    self._append_log(item[1])
                elif item[0] == "done":
                    self._on_done(success=item[1], cancelled=item[2], out_dir=item[3], error=item[4])
        except queue.Empty:
            pass
        self.after(120, self._poll_queue)

    def _on_done(self, success: bool, cancelled: bool, out_dir: str, error: str) -> None:
        self.running = False
        self.cancel_event = None
        self.progress.stop()
        self._set_running_state(False)
        if success:
            self.status_var.set("已完成")
            self._append_log("✅ 全部完成。")
            messagebox.showinfo("完成", f"生成完成。\n\n输出目录：\n{out_dir}")
        elif cancelled:
            self.status_var.set("已停止")
            self._append_log("⏹️ 已停止。已生成的文件会保留在输出目录。")
            messagebox.showinfo("已停止", f"任务已停止。\n\n已生成的文件保留在：\n{out_dir}")
        else:
            self.status_var.set("运行失败")
            self._append_log(f"❌ 运行失败：{error}")
            messagebox.showerror("运行失败", f"运行失败：\n{error}\n\n详情请查看日志。")

    def _set_running_state(self, is_running: bool) -> None:
        start_state = "disabled" if is_running else "normal"
        stop_state = "normal" if is_running else "disabled"
        self.run_button.configure(state=start_state)
        self.run_button_top.configure(state=start_state)
        self.test_button_top.configure(state=start_state)
        self.dry_button.configure(state=start_state)
        self.stop_button.configure(state=stop_state)
        self.stop_button_top.configure(state=stop_state)
        self.open_button.configure(state="normal")
        self.clear_button.configure(state=start_state)

    def _clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _append_log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", str(message).rstrip() + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _open_output_dir(self) -> None:
        out_text = self.out_var.get().strip().strip('"')
        target = Path(out_text).expanduser() if out_text else self.last_output_dir
        if not target:
            messagebox.showinfo("没有输出目录", "还没有设置输出目录。")
            return
        target.mkdir(parents=True, exist_ok=True)
        try:
            if os.name == "nt":
                os.startfile(str(target))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(target)])
            else:
                subprocess.Popen(["xdg-open", str(target)])
        except Exception as exc:
            messagebox.showerror("无法打开目录", str(exc))

    def _clear_output_dir(self) -> None:
        out_text = self.out_var.get().strip().strip('"')
        target = Path(out_text).expanduser() if out_text else self.last_output_dir
        if not target:
            messagebox.showinfo("没有输出目录", "还没有设置输出目录。")
            return
        try:
            target = target.resolve()
        except Exception:
            target = target
        if str(target).strip() in {"", str(target.anchor), str(PROJECT_ROOT.resolve())}:
            messagebox.showerror("不能清空", "这个目录过于危险，程序拒绝清空。请换一个明确的输出目录。")
            return
        target.mkdir(parents=True, exist_ok=True)
        items = list(target.iterdir())
        if not items:
            messagebox.showinfo("目录已是空的", f"输出目录当前为空：\n{target}")
            return
        if not messagebox.askyesno("确认清空输出目录", f"确定要清空下面目录中的全部内容吗？\n\n{target}\n\n这个操作不可撤销。"):
            return
        failed = []
        for item in items:
            try:
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()
            except Exception as exc:
                failed.append(f"{item.name}: {exc}")
        if failed:
            self._append_log("⚠️ 输出目录已部分清空，但以下项目删除失败：")
            for line in failed:
                self._append_log("  - " + line)
            messagebox.showwarning("部分删除失败", "输出目录已部分清空，详情请查看日志。")
        else:
            self._append_log(f"🧹 已清空输出目录：{target}")
            messagebox.showinfo("已清空", f"已清空输出目录：\n{target}")

    def _show_prompts(self) -> None:
        win = tk.Toplevel(self)
        win.title("提示词 / 规范")
        win.geometry("980x720")
        win.transient(self)
        frame = ttk.Frame(win, padding=10)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)
        self._build_prompt_tab(frame)
        self.status_var.set("正在编辑提示词 / 后处理规范")

    def _show_visual(self) -> None:
        win = tk.Toplevel(self)
        win.title("视觉后处理")
        win.geometry("1040x620")
        win.transient(self)
        frame = ttk.Frame(win, padding=10)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)
        self._build_visual_tab(frame)
        self.status_var.set("正在编辑视觉后处理参数")

    def _settings_data(self) -> dict:
        previous = {}
        try:
            if SETTINGS_PATH.exists():
                previous = json.loads(SETTINGS_PATH.read_text(encoding="utf-8-sig"))
        except Exception:
            previous = {}
        stage_settings = {}
        for stage, _title, _tip in TEXT_STAGES:
            provider = self.stage_provider_vars[stage].get()
            model = self.stage_model_vars[stage].get()
            if provider == "gemini":
                model = canonical_gemini_model(model)
            stage_settings[stage] = {"provider": provider, "model": model}
        book_value = self.book_var.get().strip() or str(previous.get("book") or "")
        out_value = self.out_var.get().strip() or str(previous.get("out") or "")
        if book_value:
            auto_out = self._default_out_for_book_text(book_value)
            if auto_out and (not out_value or _is_project_outputs_path(out_value) or out_value == getattr(self, "_last_auto_out", "")):
                out_value = auto_out
        return {
            "book": book_value,
            "out": out_value,
            "stage_settings": stage_settings,
            "foreign_base_url": self.foreign_base_url_var.get().strip() or DEFAULT_FOREIGN_MODEL_BASE_URL,
            "doubao_endpoint": self.doubao_endpoint_var.get(),
            # Compatibility keys for v9 and earlier.
            "provider": self.stage_provider_vars["outline"].get(),
            "text_model": self.stage_model_vars["outline"].get(),
            "outline_json": self.outline_json_var.get(),
            "skip_images": self.skip_images_var.get(),
            "image_provider": self.image_provider_var.get(),
            "image_model": self.image_model_var.get(),
            "max_retries": self.max_retries_var.get(),
            "image_interval": self.image_interval_var.get(),
            "local_parse_mode": self.local_parse_mode_var.get(),
            "local_pdf_parser": self.local_pdf_parser_var.get(),
            "save_keys": self.save_keys_var.get(),
            "auto_resume": self.auto_resume_var.get(),
            "skip_existing_text": self.skip_existing_text_var.get(),
            "skip_existing_images": self.skip_existing_images_var.get(),
            "only_missing_images": self.only_missing_images_var.get(),
            "only_postprocess": self.only_postprocess_var.get(),
            "start_episode_no": self.start_episode_var.get(),
            "start_stage": self.start_stage_var.get(),
            "continue_from_existing_folder": self.continue_from_existing_folder_var.get(),
            "continue_folder": self.continue_folder_var.get(),
            "prompt_dir": str(PROMPTS_DIR),
            "prompts_externalized": True,
        }

    def _save_settings(self) -> None:
        try:
            SETTINGS_PATH.write_text(json.dumps(self._settings_data(), ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _schedule_settings_save(self, *_args) -> None:
        if not getattr(self, "_settings_autosave_ready", False):
            return
        pending = getattr(self, "_settings_autosave_after_id", None)
        if pending:
            try:
                self.after_cancel(pending)
            except Exception:
                pass
        self._settings_autosave_after_id = self.after(500, self._save_settings)

    def _install_settings_autosave_traces(self) -> None:
        self._settings_autosave_ready = False
        for stage, _title, _tip in TEXT_STAGES:
            self.stage_provider_vars[stage].trace_add("write", self._schedule_settings_save)
            self.stage_model_vars[stage].trace_add("write", self._schedule_settings_save)
        for var in [self.image_provider_var, self.image_model_var, self.foreign_base_url_var]:
            var.trace_add("write", self._schedule_settings_save)
        self._settings_autosave_ready = True

    def _load_settings(self) -> None:
        if not SETTINGS_PATH.exists():
            # Ensure combobox options are initialized even without saved settings.
            for stage, _title, _tip in TEXT_STAGES:
                self._on_stage_provider_change(stage)
            self._on_image_provider_change()
            return
        try:
            data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8-sig"))
        except Exception:
            return
        mapping = {
            "book": self.book_var,
            "out": self.out_var,
            "outline_json": self.outline_json_var,
            "image_provider": self.image_provider_var,
            "image_model": self.image_model_var,
            "max_retries": self.max_retries_var,
            "image_interval": self.image_interval_var,
            "local_parse_mode": self.local_parse_mode_var,
            "local_pdf_parser": self.local_pdf_parser_var,
            "foreign_base_url": self.foreign_base_url_var,
            "doubao_endpoint": self.doubao_endpoint_var,
            "start_episode_no": self.start_episode_var,
            "start_stage": self.start_stage_var,
            "continue_folder": self.continue_folder_var,
        }
        for key, var in mapping.items():
            if key in data and data[key] is not None:
                var.set(str(data[key]))
        self._normalized_foreign_base_url()
        current_book = self.book_var.get().strip().strip('"')
        if current_book:
            self._sync_output_dir_for_book(force=True)
        if "skip_images" in data:
            self.skip_images_var.set(bool(data["skip_images"]))
        if "save_keys" in data:
            self.save_keys_var.set(bool(data["save_keys"]))
        if "auto_resume" in data:
            self.auto_resume_var.set(bool(data["auto_resume"]))
        if "skip_existing_text" in data:
            self.skip_existing_text_var.set(bool(data["skip_existing_text"]))
        if "skip_existing_images" in data:
            self.skip_existing_images_var.set(bool(data["skip_existing_images"]))
        if "only_missing_images" in data:
            self.only_missing_images_var.set(bool(data["only_missing_images"]))
        if "only_postprocess" in data:
            self.only_postprocess_var.set(bool(data["only_postprocess"]))
        if "continue_from_existing_folder" in data:
            self.continue_from_existing_folder_var.set(bool(data["continue_from_existing_folder"]))

        # New v10 format: each text stage can have its own provider/model.
        stage_settings = data.get("stage_settings") if isinstance(data.get("stage_settings"), dict) else None
        if stage_settings:
            for stage, _title, _tip in TEXT_STAGES:
                item = stage_settings.get(stage) or {}
                if isinstance(item, dict):
                    if item.get("provider"):
                        provider_value = str(item["provider"])
                        self.stage_provider_vars[stage].set(provider_value)
                    if item.get("model") is not None:
                        self.stage_model_vars[stage].set(str(item["model"]))
        else:
            # Upgrade v9 and earlier single text-model settings to all stages.
            old_provider = str(data.get("provider") or "gemini")
            old_model = str(data.get("text_model") or DEFAULT_GEMINI_FAST_MODEL)
            for stage, _title, _tip in TEXT_STAGES:
                self.stage_provider_vars[stage].set(old_provider)
                self.stage_model_vars[stage].set(old_model)

        # Always keep outline generation defaulted to Gemini if old/missing settings are empty.
        if not self.stage_provider_vars["outline"].get().strip():
            self.stage_provider_vars["outline"].set("gemini")
        if self.stage_provider_vars["outline"].get().strip() == "gemini" and not self.stage_model_vars["outline"].get().strip():
            self.stage_model_vars["outline"].set(DEFAULT_GEMINI_FAST_MODEL)

        # Upgrade old/invalid saved model names to the four-model setup.
        repaired_settings = False
        if self.stage_provider_vars["script"].get().strip() in {"", "gemini", "doubao"}:
            self.stage_provider_vars["script"].set("openai")
            self.stage_model_vars["script"].set(DEFAULT_OPENAI_TEXT_MODEL)
            repaired_settings = True
        elif self.stage_provider_vars["script"].get().strip() == "openai" and self.stage_model_vars["script"].get().strip() in {"", "gpt-5.5-pro", "gpt-5.4-nano"}:
            self.stage_model_vars["script"].set(DEFAULT_OPENAI_TEXT_MODEL)
            repaired_settings = True
        if self.stage_provider_vars["polish"].get().strip() in {"", "gemini", "doubao", "openai"}:
            self.stage_provider_vars["polish"].set("deepseek")
            self.stage_model_vars["polish"].set("deepseek-v4-pro")
            repaired_settings = True
        elif self.stage_provider_vars["polish"].get().strip() == "deepseek" and not self.stage_model_vars["polish"].get().strip():
            self.stage_model_vars["polish"].set("deepseek-v4-pro")
            repaired_settings = True
        self.stage_provider_vars["episode_prompt"].set(self.stage_provider_vars["script"].get())
        self.stage_model_vars["episode_prompt"].set(self.stage_model_vars["script"].get())
        for hidden_stage in ("transition", "split_polish", "final_polish", "book_summary"):
            self.stage_provider_vars[hidden_stage].set(self.stage_provider_vars["polish"].get())
            self.stage_model_vars[hidden_stage].set(self.stage_model_vars["polish"].get())
        for stage, _title, _tip in TEXT_STAGES:
            provider = self.stage_provider_vars[stage].get().strip()
            model = self.stage_model_vars[stage].get().strip()
            if provider == "gemini":
                new_model = model
                if model == "gemini-2.5-flash":
                    new_model = DEFAULT_GEMINI_FAST_MODEL
                elif model == "gemini-2.5-pro":
                    new_model = DEFAULT_GEMINI_PRO_MODEL
                else:
                    new_model = canonical_gemini_model(model)
                if new_model != model:
                    self.stage_model_vars[stage].set(new_model)
                    repaired_settings = True
            if provider == "openai" and model in {"", "gpt-4.1-mini", "gpt-4o-mini"}:
                self.stage_model_vars[stage].set(DEFAULT_OPENAI_TEXT_MODEL)
                repaired_settings = True
            if provider == "doubao" and model == "ep-请填写推理接入点ID":
                self.stage_model_vars[stage].set("")
                repaired_settings = True
        if self.image_provider_var.get().strip() in {"", "none", "gemini"}:
            self.image_provider_var.set("openai")
            self.image_model_var.set("gpt-image-2")
            repaired_settings = True
        elif self.image_provider_var.get().strip() == "openai" and self.image_model_var.get().strip() in {"", "gpt-image-1.5", "gpt-image-1", "gpt-image-1-mini", "dall-e-2", "dall-e-3"}:
            self.image_model_var.set("gpt-image-2")
            repaired_settings = True

        # 提示词已外置到 prompts/ 目录；旧版 gui_settings.json 中的 prompts 不再覆盖文件。
        self._reload_prompt_files(update_editors=True)
        for stage, _title, _tip in TEXT_STAGES:
            self._on_stage_provider_change(stage)
        self._on_image_provider_change()
        if repaired_settings:
            self._save_settings()
            self._append_log("已自动修复旧模型配置，并保存到 gui_settings.json。")

    def _on_close(self) -> None:
        if self.running:
            if not messagebox.askyesno("任务正在运行", "任务正在运行中。要先请求停止并退出吗？当前 API 请求可能仍需返回后才会停下。"):
                return
            if self.cancel_event is not None:
                self.cancel_event.set()
        self._save_settings()
        self.destroy()


def main() -> None:
    app = AutoMediaGUI()
    app.mainloop()
