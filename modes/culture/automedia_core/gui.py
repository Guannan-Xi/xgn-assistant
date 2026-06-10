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
from .outline_preserve import backup_outline_files_before_clear

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
RUNTIME_SWITCHES_CONFIG_PATH = CONFIG_DIR / "杩愯寮€鍏?json"


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
    "dry-run": [""],  # 浠呯敤浜庘€滀竴閿祴璇?dry-run鈥濓紝姝ｅ父娴佺▼鍙樉绀?Gemini / OpenAI銆?
    "gemini": GEMINI_TEXT_MODEL_OPTIONS,
    "openai": OPENAI_TEXT_MODEL_OPTIONS,
    "doubao": DOUBAO_TEXT_MODEL_OPTIONS,
    "deepseek": DEEPSEEK_TEXT_MODEL_OPTIONS,
}

IMAGE_MODEL_OPTIONS = {
    "none": [""],
    "dry-run": [""],
    "openai": OPENAI_IMAGE_MODEL_OPTIONS,
    # Gemini 浣庢垚鏈紭鍏堬細Nano Banana / Gemini 2.5 Flash Image銆?    "gemini": [
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
    ("outline", "澶х翰鐢熸垚", "浼樺厛鏈湴璇嗗埆绔犺妭骞跺垏鎴?-4鍒嗛挓鐭泦锛涜瘑鍒け璐ユ墠璋冪敤妯″瀷銆?),
    ("script", "鑴氭湰鐢熸垚", "鐢熸垚鍒嗛泦鎻愮ず璇嶃€佸垎闀溿€佸彴璇嶅拰缁樺浘鎻愮ず璇嶏紱榛樿 GPT-5.5銆?),
    ("polish", "鍙拌瘝娑﹁壊", "鎸夊浘鍙烽€愬彞娑﹁壊鍙拌瘝锛屽苟渚涙壙鎺ャ€佹媶鍒嗘鼎鑹层€佺粓绋垮拰鎬荤粨澶嶇敤銆?),
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
        self.title("AutoMediaProducer锝滀功绫嶈В璇荤煭瑙嗛鑷姩鐢熸垚")
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
        self.status_var = tk.StringVar(value="鍑嗗灏辩华")
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

        # Tk 鐨勫瓧浣撳瓧绗︿覆閲屽鏋滃瓧浣撳悕鍖呭惈绌烘牸锛屽繀椤荤敤澶ф嫭鍙峰寘璧锋潵銆?
        # 涔嬪墠鐩存帴鍐欐垚 "Microsoft YaHei UI 10"锛屽湪閮ㄥ垎 Windows/Tcl 鐜涓細琚В鏋愭垚锛?
        # family=Microsoft, size=YaHei锛屼粠鑰屾姤閿欙細expected integer but got "YaHei"銆?
        available_fonts = set(tkfont.families(self))
        font_family = next(
            (name for name in ("Microsoft YaHei UI", "Microsoft YaHei", "寰蒋闆呴粦", "SimSun", "Arial") if name in available_fonts),
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
            "polish": tk.StringVar(value="deepseek-chat"),
            "transition": tk.StringVar(value="deepseek-chat"),
            "split_polish": tk.StringVar(value="deepseek-chat"),
            "final_polish": tk.StringVar(value="deepseek-chat"),
            "book_summary": tk.StringVar(value="deepseek-chat"),
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
        self.email_subject_template_var = tk.StringVar(value="钁椾綔瑙ｈ鍒嗛泦瀹屾垚锛歿part_name}")
        self.vc_progress_var = tk.BooleanVar(value=True)
        self.vc_particle_var = tk.BooleanVar(value=True)
        self.vc_orb_var = tk.BooleanVar(value=True)

    def _prompt_file_specs(self) -> list[dict[str, str]]:
        return [
            {
                "key": "outline",
                "filename": "01_澶х翰鐢熸垚鎻愮ず璇?md",
                "title": "澶х翰鐢熸垚",
                "desc": "鎺у埗鏁存湰涔﹀浣曟媶鎴愬垎闆嗗ぇ绾层€傚彲鐢ㄥ彉閲忥細{episode_count}銆亄image_interval_seconds}銆?,
                "default": OUTLINE_PROMPT,
            },
            {
                "key": "episode_builder",
                "filename": "02_鑴氭湰鐢熸垚鎻愮ず璇?md",
                "title": "鑴氭湰鐢熸垚鎻愮ず璇?,
                "desc": "鎺у埗姣忎竴闆嗚剼鏈敓鎴愮殑鍙欎簨瑕佹眰銆佺敾闈㈣妭濂忋€丄1/C 瑙勫垯銆傚彲鐢ㄥ彉閲忥細{episode_json}銆亄image_interval_seconds}銆亄book_title}銆?,
                "default": EPISODE_PROMPT_BUILDER,
            },
            {
                "key": "script_requirement",
                "filename": "03_鑴氭湰鐢熸垚_JSON瑙勮寖.md",
                "title": "鑴氭湰 JSON / 鍒嗛暅瑙勮寖",
                "desc": "鎺у埗鑴氭湰杈撳嚭缁撴瀯銆乿oiceover 涓?image_prompts 鐨勫瓧娈佃鑼冦€傚彲鐢ㄥ彉閲忥細{image_interval_seconds}銆?,
                "default": SCRIPT_JSON_REQUIREMENT,
            },
            {
                "key": "voiceover_polish",
                "filename": "04_鍙拌瘝娑﹁壊鎻愮ず璇?md",
                "title": "鍙拌瘝娑﹁壊鎻愮ず璇?,
                "desc": "鎺у埗鍙拌瘝濡備綍鍙樺緱鏇撮€氫織銆佸湴閬擄紝鍚屾椂淇濈暀鍥惧彿銆佺粨鏋勫拰鍘熸剰銆傚彲鐢ㄥ彉閲忥細{episode_json}銆亄script_json}銆亄voiceover_text}銆?,
                "default": VOICEOVER_POLISH_PROMPT,
            },
            {
                "key": "postprocess_spec",
                "filename": "05_鍚庡鐞嗚鑼?json",
                "title": "鍚庡鐞嗚鑼?,
                "desc": "鎺у埗灏侀潰/鐗囧熬/鍒嗛泦灏侀潰鐨勫畬鏁村悗澶勭悊鍙傛暟锛氬搧鐗屾枃妗堛€佸昂瀵歌鏍笺€佸潗鏍囥€佸瓧鍙枫€侀鑹层€侀槾褰便€佽竟妗嗐€佹殫瑙掋€佽鍓€佸搧鐗屾爮銆佺墖灏?CTA銆備繚瀛樺悗閲嶈窇鍚庡鐞嗗嵆鍙敓鏁堛€?,
                "default": default_global_postprocess_spec_text(),
            },
            {
                "key": "transition_summary_prompt",
                "filename": "06_鎵挎帴棰勫憡鎬荤粨鎻愮ず璇?md",
                "title": "鎵挎帴棰勫憡鎻愮ず璇?,
                "desc": "鎺у埗鎷嗗垎鍚?A1 寮€澶存壙鎺ャ€丆 缁撳熬棰勫憡濡備綍鐢卞ぇ妯″瀷鎬荤粨銆?,
                "default": _default_transition_prompt(),
            },
            {
                "key": "split_title_prompt",
                "filename": "07_鍒嗛泦鏈泦鍚嶆彁绀鸿瘝.md",
                "title": "鍒嗛泦鏈泦鍚嶆彁绀鸿瘝",
                "desc": "鎺у埗姣忎釜 3~5 鍒嗛挓鍒嗛泦濡備綍鏍规嵁鏈泦 LRC/鍙拌瘝鐢熸垚灏侀潰涓庨椤垫樉绀虹殑鏈泦鍚嶃€傚彲鐢ㄥ彉閲忥細{book_title}銆亄chapter_label}銆亄part_no}銆亄current_summary}銆亄lrc_payload}銆?,
                "default": default_split_title_prompt(),
            },
            {
                "key": "split_voiceover_polish_prompt",
                "filename": "08_鍒嗛泦鍙拌瘝娑﹁壊鎻愮ず璇?md",
                "title": "鍒嗛泦鍙拌瘝娑﹁壊鎻愮ず璇?,
                "desc": "鎺у埗鎷嗗垎鍚庢瘡涓垎闆嗙殑涓€娆℃鼎鑹层€丄1/C 绠€鍖栥€?3%/67% 鐣欏瓨閽╁瓙銆傚彲鐢ㄥ彉閲忥細{title}銆亄part_no}銆亄prev_summary}銆亄current_summary}銆亄next_title}銆亄next_summary}銆亄previous_context}銆亄next_context}銆亄hook_target_payload}銆亄payload}銆?,
                "default": default_split_polish_prompt(),
            },
            {
                "key": "split_final_polish_prompt",
                "filename": "12_DeepSeek缁堢娑﹁壊鎻愮ず璇?md",
                "title": "DeepSeek 缁堢娑﹁壊鎻愮ず璇?,
                "desc": "鏈€缁堟鏌ユ瘡闆嗛挬瀛愩€佸紑绡囥€佷富棰樸€佺粨灏鹃鍛婄殑鏁翠綋杩囨浮锛涗繚鐣?no銆乮mage_id 涓庡浘鐗囨枃浠跺悕瀵瑰簲銆傚彲鐢ㄥ彉閲忥細{book_title}銆亄chapter_label}銆亄title}銆亄part_no}銆亄prev_summary}銆亄current_summary}銆亄next_title}銆亄next_summary}銆亄previous_context}銆亄next_context}銆亄opening_context}銆亄closing_context}銆亄payload}銆?,
                "default": default_final_polish_prompt(),
            },
            {
                "key": "book_final_summary_prompt",
                "filename": "09_鍏ㄤ功缁撳熬鎬荤粨鎻愮ず璇?md",
                "title": "鍏ㄤ功缁撳熬鎬荤粨鎻愮ず璇?,
                "desc": "鎺у埗鍏ㄤ功鏈€鍚庝竴闆?C 缁撳熬濡備綍鐢熸垚鍏ㄤ功鎬荤粨銆傚彲鐢ㄥ彉閲忥細{book_title}銆亄current_summary}銆亄payload}銆?,
                "default": default_book_final_summary_prompt(),
            },
            {
                "key": "ac_master_prompt",
                "filename": "10_灏侀潰姣嶅浘鎻愮ず璇?md",
                "title": "灏侀潰姣嶅浘鎻愮ず璇?,
                "desc": "鎺у埗 A/C 鍏辩敤姣嶅浘鐨勭敓鍥炬彁绀鸿瘝銆傚彲鐢ㄥ彉閲忥細{manuscript}銆亄book_title}銆亄episode_title}銆亄chapter_summary}銆?,
                "default": default_ac_master_prompt(),
            },
            {
                "key": "deterministic_episode_prompt",
                "filename": "14_鏈湴纭畾鎬ц剼鏈彁绀鸿瘝妯℃澘.md",
                "title": "鏈湴纭畾鎬ц剼鏈ā鏉?,
                "desc": "褰撳垎闆嗘彁绀鸿瘝妯″瀷鍏抽棴銆乨ry-run 鎴栨ā鍨嬪け璐ュ洖閫€鏃朵娇鐢ㄣ€傚彲鐢ㄥ彉閲忥細{book_title}銆亄episode_no}銆亄episode_title}銆亄source_labels}銆亄hook}銆亄main_points}銆亄image_interval_seconds}銆?,
                "default": default_deterministic_episode_prompt_template(),
            },
            {
                "key": "generation_rules",
                "filename": "鐢熸垚瑙勫垯閰嶇疆.json",
                "folder": "config",
                "title": "鐢熸垚瑙勫垯閰嶇疆",
                "desc": "鎺у埗绋嬪簭鑷姩杩藉姞缁欒剼鏈敓鎴愩€佽鐩栬ˉ鏁戙€佺粯鍥炬彁绀鸿瘝鐨勮鍒欍€備紭鍏堢骇楂樹簬绋嬪簭鍏滃簳榛樿鍊笺€?,
                "default": json.dumps(default_generation_rules(), ensure_ascii=False, indent=2),
            },
            {
                "key": "copywriting_config",
                "filename": "鏂囨椋庢牸閰嶇疆.json",
                "folder": "config",
                "title": "鏂囨椋庢牸閰嶇疆",
                "desc": "鎺у埗鍝佺墝鍚嶃€佸叧娉ㄨ銆佸垎闆嗗紑澶?缁撳熬妯℃澘銆佹槸鍚︽樉绀哄墠缂€绛夈€備繚瀛樺悗閲嶆柊鎷嗗垎鑴氭湰鍗冲彲鐢熸晥銆?,
                "default": "{}",
            },
            {
                "key": "postprocess_override",
                "filename": "鍚庡鐞嗛鏍艰鐩?json",
                "folder": "config",
                "title": "鍚庡鐞嗛鏍艰鐩?,
                "desc": "鍚庡鐞嗗眬閮ㄨ鐩栭厤缃€備紭鍏堢骇楂樹簬 05_鍚庡鐞嗚鑼?json锛岄€傚悎涓存椂寰皟瀛椾綋銆侀鑹层€佽竟妗嗐€佽楗板紑鍏炽€?,
                "default": "{}",
            },
            {
                "key": "runtime_switches",
                "filename": "杩愯寮€鍏?json",
                "folder": "config",
                "title": "杩愯寮€鍏?,
                "desc": "鎺у埗鏄惁鍚敤閰嶇疆瑕嗙洊銆侀珮淇濈湡瑁呴グ绛夎繍琛屽紑鍏炽€?,
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
                    messagebox.showerror("JSON 鏍煎紡鏈夎", f"璇峰厛淇鈥渰title}鈥濈殑 JSON 鏍煎紡銆俓n\n{exc}")
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
            self._append_log(f"鎻愮ず璇嶄笌閰嶇疆宸蹭繚瀛橈細{PROMPTS_DIR}锛泏CONFIG_DIR}")

    def _save_prompt_editor_files(self) -> None:
        if self._sync_prompt_editors_to_memory(save_files=True, show_log=True):
            self._save_settings()
            messagebox.showinfo("宸蹭繚瀛?, f"鎻愮ず璇嶅拰閰嶇疆宸蹭繚瀛樺埌锛歕n{PROMPTS_DIR}\n{CONFIG_DIR}")

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
            messagebox.showerror("鏃犳硶鎵撳紑鎻愮ず璇嶇洰褰?, str(exc))

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
        ttk.Label(header, text="涔︾睄瑙ｈ鐭棰戣嚜鍔ㄧ敓鎴?, style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            header,
            text="PDF 鈫?澶х翰 鈫?鑴氭湰 鈫?娑﹁壊 鈫?缁樺浘 鈫?鍚庡鐞?,
            foreground="#555",
        ).grid(row=0, column=1, sticky="w", padx=(18, 0))

        action_bar = ttk.LabelFrame(root, text="杩愯", style="Section.TLabelframe")
        action_bar.grid(row=1, column=0, sticky="ew", pady=(10, 10))
        action_bar.columnconfigure(9, weight=1)

        self.run_button_top = ttk.Button(action_bar, text="寮€濮嬭繍琛?, command=self._run, style="Run.TButton", width=14)
        self.run_button_top.grid(row=0, column=0, padx=(12, 8), pady=9)
        self.test_button_top = ttk.Button(action_bar, text="娴嬭瘯杩愯", command=self._run_quick_test, width=12)
        self.test_button_top.grid(row=0, column=1, padx=(0, 8), pady=9)
        self.stop_button_top = ttk.Button(action_bar, text="鍋滄", command=self._stop, style="Stop.TButton", state="disabled", width=10)
        self.stop_button_top.grid(row=0, column=2, padx=(0, 8), pady=9)
        self.open_button = ttk.Button(action_bar, text="鎵撳紑杈撳嚭", command=self._open_output_dir, width=12)
        self.open_button.grid(row=0, column=3, padx=(0, 8), pady=9)
        self.clear_button = ttk.Button(action_bar, text="娓呯┖杈撳嚭", command=self._clear_output_dir, width=12)
        self.clear_button.grid(row=0, column=4, padx=(0, 8), pady=9)

        ttk.Separator(action_bar, orient="vertical").grid(row=0, column=5, sticky="ns", padx=(4, 12), pady=7)
        ttk.Button(action_bar, text="鎻愮ず璇?, command=self._show_prompts, width=10).grid(row=0, column=6, padx=(0, 8), pady=9)
        ttk.Button(action_bar, text="瑙嗚", command=self._show_visual, width=10).grid(row=0, column=7, padx=(0, 8), pady=9)
        ttk.Button(action_bar, text="Key", command=self._show_key_manager, width=8).grid(row=0, column=8, padx=(0, 12), pady=9)
        ttk.Label(action_bar, text="娴嬭瘯杩愯锛氬厛鐢熸垚鍏ㄦ枃鏁呬簨绾垮ぇ绾诧紝B鍥惧彧鐢讳竴寮狅紝浠嶆墽琛屾媶鍒?鎵撳寘/閭欢銆?, foreground="#555").grid(row=0, column=9, sticky="w", padx=(0, 10))

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

        input_box = ttk.LabelFrame(control_panel, text="杈撳叆", style="Section.TLabelframe")
        input_box.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        input_box.columnconfigure(1, weight=1)
        self._path_row(input_box, 0, "涔︾睄 PDF", self.book_var, self._browse_book, "閫夋嫨涓€鏈?PDF 涔︾睄銆傚ぇ绾插拰鑴氭湰閮戒細鍩轰簬杩欐湰涔︾敓鎴愩€?)
        self._path_row(input_box, 1, "杈撳嚭鐩綍", self.out_var, self._browse_out, "鎵€鏈夌粨鏋滈兘浼氫繚瀛樺埌杩欎釜鐩綍锛屼笉浼氳鐩栧師 PDF銆?, folder=True)

        config_stack = ttk.Frame(control_panel)
        config_stack.grid(row=1, column=0, sticky="nsew")
        config_stack.columnconfigure(0, weight=1)
        config_stack.rowconfigure(0, weight=0)
        config_stack.rowconfigure(1, weight=0)
        config_stack.rowconfigure(2, weight=1)

        model_box = ttk.LabelFrame(config_stack, text="妯″瀷", style="Section.TLabelframe")
        model_box.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        self._build_models(model_box)

        email_box = ttk.LabelFrame(config_stack, text="閭鍙戦€?, style="Section.TLabelframe")
        email_box.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        self._build_email_config(email_box)

        param_box = ttk.LabelFrame(config_stack, text="杩愯閫夐」", style="Section.TLabelframe")
        param_box.grid(row=2, column=0, sticky="nsew")
        self._build_params(param_box)

        log_box = ttk.LabelFrame(right, text="鏃ュ織", style="Section.TLabelframe")
        log_box.grid(row=0, column=0, sticky="nsew")
        log_box.rowconfigure(1, weight=1)
        log_box.columnconfigure(0, weight=1)

        log_toolbar = ttk.Frame(log_box)
        log_toolbar.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))
        log_toolbar.columnconfigure(1, weight=1)
        ttk.Button(log_toolbar, text="娓呯┖鏃ュ織", command=self._clear_log).grid(row=0, column=0, padx=(0, 8))
        ttk.Label(log_toolbar, text="杩愯鐘舵€佸拰閿欒浼氭樉绀哄湪杩欓噷", foreground="#666").grid(row=0, column=1, sticky="e")

        self.log_text = scrolledtext.ScrolledText(log_box, wrap="word", font=("Consolas", 10), height=22)
        self.log_text.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        self.log_text.insert("end", "鍑嗗灏辩华銆傞粯璁ゆā鍨嬶細澶х翰 Gemini锛岃剼鏈?GPT-5.5锛岀粯鍥?GPT-image2锛屽彴璇嶆鼎鑹?DeepSeek V4 Pro銆俓n")
        self.log_text.insert("end", "楂樼骇璁剧疆鍙€氳繃椤堕儴鈥滄彁绀鸿瘝鈥濆拰鈥滆瑙夆€濇墦寮€銆俓n")
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
        ttk.Button(toolbar, text="淇濆瓨鍒版彁绀鸿瘝鏂囦欢", command=self._save_prompt_editor_files, style="Run.TButton").grid(row=0, column=0, padx=(0, 8))
        ttk.Button(toolbar, text="浠庢枃浠堕噸鏂板姞杞?, command=lambda: self._reload_prompt_files(update_editors=True)).grid(row=0, column=1, padx=(0, 8))
        ttk.Button(toolbar, text="鎭㈠褰撳墠椤甸粯璁?, command=self._restore_current_prompt_default).grid(row=0, column=2, padx=(0, 8))
        ttk.Button(toolbar, text="鎵撳紑鎻愮ず璇嶆枃浠跺す", command=self._open_prompts_dir).grid(row=0, column=3, padx=(0, 8))
        ttk.Label(toolbar, text="淇濆瓨鍚庝笉闇€瑕佹敼绋嬪簭锛涢噸璺戝搴旀楠ゅ嵆鍙敓鏁堛€?, style="Muted.TLabel").grid(row=0, column=4, sticky="e")

        self.prompt_notebook = ttk.Notebook(parent)
        self.prompt_notebook.grid(row=1, column=0, sticky="nsew")
        self.prompt_editors = {}
        self.prompt_tabs = []
        for spec in self._prompt_file_specs():
            key = spec["key"]
            frame = ttk.Frame(self.prompt_notebook, padding=8)
            frame.rowconfigure(1, weight=1)
            frame.columnconfigure(0, weight=1)
            desc = f"{spec['desc']}\n鏂囦欢锛歿self._prompt_file_path(key)}"
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
                "label": "椤跺垔鏉傚織",
                "background": {"brightness": 0.92, "saturation": 0.98, "blur_px": 3, "vignette": 0.34, "top_darken": 0.18, "bottom_darken": 0.30},
                "glass": {"opacity": 0.68, "blur_px": 14, "glow": 0.22},
                "title": {"scale": 1.18, "glow": 0.18},
                "ornaments": {"frame": True, "corner": False, "scanline": False, "progress_bar": False, "particle": False, "orb": False},
            },
            "warm_paper": {
                "label": "鏆栫焊涔︽埧",
                "background": {"brightness": 1.04, "saturation": 0.94, "blur_px": 2, "vignette": 0.15, "top_darken": 0.02, "bottom_darken": 0.07},
                "glass": {"opacity": 0.90, "blur_px": 10, "glow": 0.16},
                "title": {"scale": 1.08, "glow": 0.10},
                "ornaments": {"frame": True, "corner": False, "scanline": False, "progress_bar": False, "particle": False, "orb": False},
            },
            "rational_social": {
                "label": "鐞嗘€хぞ浼?,
                "background": {"brightness": 0.86, "saturation": 0.90, "blur_px": 3, "vignette": 0.34, "top_darken": 0.14, "bottom_darken": 0.22},
                "glass": {"opacity": 0.86, "blur_px": 12, "glow": 0.22},
                "title": {"scale": 1.10, "glow": 0.12},
                "ornaments": {"frame": True, "corner": False, "scanline": False, "progress_bar": False, "particle": False, "orb": False},
            },
            "olive_reading": {
                "label": "鑽夋湪涔﹂",
                "background": {"brightness": 1.02, "saturation": 0.88, "blur_px": 2, "vignette": 0.16, "top_darken": 0.02, "bottom_darken": 0.06},
                "glass": {"opacity": 0.88, "blur_px": 10, "glow": 0.14},
                "title": {"scale": 1.06, "glow": 0.10},
                "ornaments": {"frame": True, "corner": False, "scanline": False, "progress_bar": False, "particle": False, "orb": False},
            },
            "humanities_paper": {
                "label": "浜烘枃鏃т功",
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
        self._append_log("宸蹭繚瀛樿瑙夊悗澶勭悊鍙傛暟锛涘嬀閫夆€樺彧閲嶅仛灏侀潰/鐗囧熬鍚庡鐞嗏€欏悗杩愯鍗冲彲鎵归噺閲嶆覆鏌?A/C銆?)
        if show_message:
            messagebox.showinfo("瑙嗚鍚庡鐞嗗凡淇濆瓨", "宸插啓鍏?prompts/05_鍚庡鐞嗚鑼?json銆俓n閲嶈窇鍚庡鐞嗗嵆鍙敓鎴愭柊 A/C 鍥剧墖銆?)

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
        ttk.Label(toolbar, text="椋庢牸棰勮").grid(row=0, column=0, sticky="w", padx=(0, 8))
        preset_combo = ttk.Combobox(toolbar, textvariable=self.visual_preset_var, values=list(self._visual_presets().keys()), state="readonly", width=18)
        preset_combo.grid(row=0, column=1, sticky="w", padx=(0, 8))
        preset_combo.bind("<<ComboboxSelected>>", self._apply_visual_preset)
        ttk.Button(toolbar, text="搴旂敤棰勮", command=self._apply_visual_preset).grid(row=0, column=2, padx=(0, 8))
        ttk.Button(toolbar, text="淇濆瓨瑙嗚鍙傛暟", command=self._save_visual_controls_from_vars, style="Run.TButton").grid(row=0, column=3, padx=(0, 8))
        ttk.Button(toolbar, text="浠庤鑼冮噸鏂板姞杞?, command=self._load_visual_controls_to_vars).grid(row=0, column=4, sticky="e")

        grid = ttk.Frame(parent)
        grid.grid(row=1, column=0, sticky="nsew")
        for col in range(3):
            grid.columnconfigure(col, weight=1)
        grid.rowconfigure(0, weight=1)

        bg_box = ttk.LabelFrame(grid, text="鑳屾櫙 / 姣嶅浘", style="Section.TLabelframe")
        bg_box.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        bg_box.columnconfigure(1, weight=1)
        self._scale_row(bg_box, 0, "浜害", self.vc_bg_brightness_var, 0.30, 1.00, "鎻愰珮鍚庢瘝鍥炬洿娓呮锛涘お楂樹細鍘嬩綆鏂囧瓧瀵规瘮銆?)
        self._scale_row(bg_box, 1, "楗卞拰搴?, self.vc_bg_saturation_var, 0.70, 1.45, "鎺у埗姣嶅浘鑹插僵娴撳害銆?)
        self._scale_row(bg_box, 2, "鑳屾櫙妯＄硦", self.vc_bg_blur_var, 0.0, 24.0, "鍙奖鍝嶈緟鍔╂ā绯婂眰锛岃鐢婚潰鏇存湁鐢靛奖绾垫繁銆?)
        self._scale_row(bg_box, 3, "鏆楄", self.vc_vignette_var, 0.0, 0.90, "鎻愰珮鍚庤竟缂樻洿鏆楋紝涓績鏇磋仛鐒︺€?)
        self._scale_row(bg_box, 4, "椤堕儴鍘嬫殫", self.vc_top_darken_var, 0.0, 0.90, "淇濇姢椤堕儴涔﹀悕鍜屾爣绛惧彲璇绘€с€?)
        self._scale_row(bg_box, 5, "搴曢儴鍘嬫殫", self.vc_bottom_darken_var, 0.0, 0.95, "淇濇姢搴曢儴鍝佺墝鏍忓拰 C 鍥?CTA銆?)

        glass_box = ttk.LabelFrame(grid, text="鐜荤拑鎺т欢 / 闈㈡澘", style="Section.TLabelframe")
        glass_box.grid(row=0, column=1, sticky="nsew", padx=8)
        glass_box.columnconfigure(1, weight=1)
        self._scale_row(glass_box, 0, "閫忔槑搴?, self.vc_glass_opacity_var, 0.25, 0.85, "瓒婁綆瓒婅兘闇插嚭姣嶅浘锛涜秺楂樻枃瀛楁洿绋炽€?)
        self._scale_row(glass_box, 1, "鐜荤拑妯＄硦", self.vc_glass_blur_var, 0.0, 32.0, "鎺у埗姣涚幓鐠冭川鎰熴€?)
        self._scale_row(glass_box, 2, "鍙戝厜寮哄害", self.vc_glass_glow_var, 0.0, 1.00, "鎺у埗闈㈡澘杈圭紭鐨勯噾鑹插厜鏅曘€?)
        self._scale_row(glass_box, 3, "鏍囬瀛楀彿", self.vc_title_scale_var, 0.80, 1.45, "A2/C 涓绘爣棰樺啿鍑诲姏锛涢暱鏍囬浼氳嚜鍔ㄧ缉瀛椼€?)
        self._scale_row(glass_box, 4, "鏍囬杈夊厜", self.vc_title_glow_var, 0.0, 1.00, "鎺у埗涓绘爣棰樻弿杈瑰拰澶栧彂鍏夈€?)

        fx_box = ttk.LabelFrame(grid, text="鐐叿鎺т欢", style="Section.TLabelframe")
        fx_box.grid(row=0, column=2, sticky="nsew", padx=(8, 0))
        checks = [
            ("鏋佺畝澶栨", self.vc_frame_var, "鍙繚鐣欎竴灞傞噾鑹插妗嗭紱瑙掓爣榛樿鍏抽棴锛岄伩鍏嶉噸澶嶈楗般€?),
            ("鎵弿绾?, self.vc_scanline_var, "澧炲姞楂樼骇鎺т欢鎰燂紝浣嗕笉褰卞搷鏂囧瓧銆?),
            ("C 鍥捐繘搴︽潯", self.vc_progress_var, "C 鐗囧熬 NEXT EPISODE 杩涘害鏉°€?),
            ("绮掑瓙", self.vc_particle_var, "缁嗗皬閲戣壊绮掑瓙锛屽鍔犵敾闈㈢簿鑷村害銆?),
            ("鍏夋枒", self.vc_orb_var, "鑳屾櫙閲戣壊鍏夋枒锛屾彁鍗囨皼鍥淬€?),
        ]
        for i, (text, var, tip) in enumerate(checks):
            cb = ttk.Checkbutton(fx_box, text=text, variable=var)
            cb.grid(row=i, column=0, sticky="w", padx=10, pady=7)
            ToolTip(cb, tip)
        note = (
            "鎺ㄨ崘娴佺▼锛氶€夋嫨棰勮 鈫?寰皟浜害/閫忔槑搴?鏍囬瀛楀彿 鈫?淇濆瓨瑙嗚鍙傛暟 鈫?鍕鹃€夆€樺彧閲嶅仛灏侀潰/鐗囧熬鍚庡鐞嗏€欒繍琛屻€俓n"
            "鏈〉鍙傛暟浼氱洿鎺ュ啓鍏?prompts/05_鍚庡鐞嗚鑼?json 鐨?visual_controls銆?
        )
        ttk.Label(fx_box, text=note, justify="left", wraplength=300, style="Muted.TLabel").grid(row=len(checks), column=0, sticky="ew", padx=10, pady=(18, 8))
        self._load_visual_controls_to_vars()

    def _path_row(self, parent: ttk.Frame, row: int, label: str, var: tk.StringVar, command, tip: str, folder: bool = False) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=10, pady=7)
        entry = ttk.Entry(parent, textvariable=var)
        entry.grid(row=row, column=1, sticky="ew", padx=8, pady=7)
        ToolTip(entry, tip)
        ttk.Button(parent, text="閫夋嫨鏂囦欢澶? if folder else "閫夋嫨鏂囦欢", command=command).grid(row=row, column=2, padx=10, pady=7)

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
        ttk.Label(parent, text="閲嶈瘯娆℃暟").grid(row=0, column=0, sticky="w", padx=10, pady=7)
        retry_spin = ttk.Spinbox(parent, from_=0, to=10, textvariable=self.max_retries_var, width=10)
        retry_spin.grid(row=0, column=1, sticky="w", padx=8, pady=7)
        ToolTip(retry_spin, "妯″瀷鎺ュ彛鍋跺彂鏂紑鏃惰嚜鍔ㄩ噸璇曠殑娆℃暟銆?)

        ttk.Label(parent, text="閰嶅浘鑺傚").grid(row=1, column=0, sticky="w", padx=10, pady=7)
        cadence_entry = ttk.Entry(parent, textvariable=self.image_interval_var, width=12)
        cadence_entry.grid(row=1, column=1, sticky="w", padx=8, pady=7)
        ToolTip(cadence_entry, "榛樿 3-8锛岃〃绀烘瘡鍙ュ彴璇嶅敖閲忓搴?1 骞曠敾闈€?)

        check = ttk.Checkbutton(parent, text="璺宠繃鐢熷浘锛屽彧杈撳嚭缁樺浘鎻愮ず璇?, variable=self.skip_images_var)
        check.grid(row=2, column=0, columnspan=2, sticky="w", padx=10, pady=7)
        ToolTip(check, "鍙敓鎴愭枃鏈拰缁樺浘鎻愮ず璇嶏紝涓嶈皟鐢ㄧ粯鍥炬帴鍙ｃ€?)

        ttk.Checkbutton(parent, text="鑷姩鏂偣缁窇", variable=self.auto_resume_var).grid(row=3, column=0, sticky="w", padx=10, pady=7)
        ttk.Checkbutton(parent, text="璺宠繃宸茬敓鎴愬唴瀹?, variable=self.skip_existing_text_var).grid(row=3, column=1, sticky="w", padx=8, pady=7)
        ttk.Checkbutton(parent, text="鍙ˉ缂哄け鍥剧墖", variable=self.only_missing_images_var).grid(row=4, column=0, sticky="w", padx=10, pady=7)
        ttk.Checkbutton(parent, text="鍙噸鍋氬悗澶勭悊", variable=self.only_postprocess_var).grid(row=4, column=1, sticky="w", padx=8, pady=7)

        advanced = ttk.LabelFrame(parent, text="楂樼骇缁綔", style="Section.TLabelframe")
        advanced.grid(row=5, column=0, columnspan=2, sticky="ew", padx=10, pady=(10, 6))
        advanced.columnconfigure(1, weight=1)
        ttk.Checkbutton(advanced, text="浠庡凡鏈夋枃浠跺す缁х画", variable=self.continue_from_existing_folder_var).grid(row=0, column=0, sticky="w", padx=8, pady=5)
        self._path_row(advanced, 1, "缁綔鏂囦欢澶?, self.continue_folder_var, self._browse_continue_folder, "鍙€夋嫨鏁翠釜杈撳嚭鐩綍鎴栨煇涓€闆嗙洰褰曘€?, folder=True)
        self._path_row(advanced, 2, "宸叉湁澶х翰 JSON", self.outline_json_var, self._browse_outline, "宸叉湁缁撴瀯鍖栧ぇ绾叉椂浣跨敤锛涚暀绌哄垯鍏堢敓鎴愬ぇ绾层€?)
        ttk.Label(advanced, text="璧峰闆?).grid(row=3, column=0, sticky="w", padx=8, pady=5)
        ttk.Spinbox(advanced, from_=1, to=999, textvariable=self.start_episode_var, width=10).grid(row=3, column=1, sticky="w", padx=8, pady=5)
        ttk.Label(advanced, text="璧峰姝ラ").grid(row=4, column=0, sticky="w", padx=8, pady=5)
        stage_combo = ttk.Combobox(advanced, textvariable=self.start_stage_var, values=["outline", "split_pdf", "episode_prompt", "script", "polish", "images", "postprocess", "split_assets"], state="readonly", width=18)
        stage_combo.grid(row=4, column=1, sticky="w", padx=8, pady=5)

    def _build_email_config(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(1, weight=1)
        parent.columnconfigure(3, weight=1)

        enable = ttk.Checkbutton(parent, text="姣忛泦瀹屾垚鍚庢墦鍖呭彂閫侀偖浠?, variable=self.email_enabled_var)
        enable.grid(row=0, column=0, columnspan=4, sticky="w", padx=10, pady=(8, 5))
        ToolTip(enable, "寮€鍚悗锛屽垎闆嗙礌鏉愮敓鎴愬畬鎴愭椂浼氭墦鍖呬负 zip 骞跺彂閫佸埌鎸囧畾閭銆?)

        ttk.Label(parent, text="鏀朵欢閭").grid(row=1, column=0, sticky="w", padx=10, pady=5)
        to_entry = ttk.Entry(parent, textvariable=self.email_to_var)
        to_entry.grid(row=1, column=1, columnspan=3, sticky="ew", padx=8, pady=5)
        ToolTip(to_entry, "澶氫釜鏀朵欢浜虹敤鑻辨枃閫楀彿鍒嗛殧銆傞粯璁ゆ祴璇曢偖绠憋細399467826@qq.com銆?)

        ttk.Label(parent, text="SMTP").grid(row=2, column=0, sticky="w", padx=10, pady=5)
        host_entry = ttk.Entry(parent, textvariable=self.email_smtp_host_var, width=18)
        host_entry.grid(row=2, column=1, sticky="ew", padx=8, pady=5)
        ttk.Label(parent, text="绔彛").grid(row=2, column=2, sticky="w", padx=(6, 0), pady=5)
        port_entry = ttk.Entry(parent, textvariable=self.email_smtp_port_var, width=8)
        port_entry.grid(row=2, column=3, sticky="w", padx=8, pady=5)
        ToolTip(host_entry, "QQ 閭涓€鑸娇鐢?smtp.qq.com銆?)
        ToolTip(port_entry, "QQ 閭 SSL 绔彛閫氬父涓?465銆?)

        ssl_check = ttk.Checkbutton(parent, text="浣跨敤 SSL", variable=self.email_use_ssl_var)
        ssl_check.grid(row=3, column=0, sticky="w", padx=10, pady=5)
        ttk.Label(parent, text="鐧诲綍璐﹀彿").grid(row=3, column=1, sticky="w", padx=8, pady=5)
        user_entry = ttk.Entry(parent, textvariable=self.email_username_var)
        user_entry.grid(row=3, column=2, columnspan=2, sticky="ew", padx=8, pady=5)
        ToolTip(user_entry, "閫氬父濉啓鍙戜欢閭瀹屾暣鍦板潃锛屼緥濡?浣犵殑QQ鍙稝qq.com銆?)

        ttk.Label(parent, text="鍙戜欢浜?).grid(row=4, column=0, sticky="w", padx=10, pady=5)
        from_entry = ttk.Entry(parent, textvariable=self.email_from_var)
        from_entry.grid(row=4, column=1, sticky="ew", padx=8, pady=5)
        ttk.Label(parent, text="闄勪欢涓婇檺MB").grid(row=4, column=2, sticky="w", padx=(6, 0), pady=5)
        max_entry = ttk.Entry(parent, textvariable=self.email_max_mb_var, width=8)
        max_entry.grid(row=4, column=3, sticky="w", padx=8, pady=5)
        ToolTip(from_entry, "鍙暀绌猴紱鐣欑┖鏃堕粯璁や娇鐢ㄧ櫥褰曡处鍙枫€?)
        ToolTip(max_entry, "瓒呰繃姝ゅぇ灏忎細璺宠繃鍙戦€侊紝閬垮厤閭鎷掓敹銆?)

        ttk.Label(parent, text="瀵嗙爜鍙橀噺").grid(row=5, column=0, sticky="w", padx=10, pady=5)
        env_entry = ttk.Entry(parent, textvariable=self.email_password_env_var)
        env_entry.grid(row=5, column=1, sticky="ew", padx=8, pady=5)
        ttk.Label(parent, text="瀵嗙爜鏂囦欢").grid(row=5, column=2, sticky="w", padx=(6, 0), pady=5)
        file_entry = ttk.Entry(parent, textvariable=self.email_password_file_var)
        file_entry.grid(row=5, column=3, sticky="ew", padx=8, pady=5)
        ToolTip(env_entry, "鍙繚瀛樼幆澧冨彉閲忓悕锛屼笉淇濆瓨閭鎺堟潈鐮佹湰韬€?)
        ToolTip(file_entry, "鍙繚瀛樻枃浠惰矾寰勩€傞粯璁よ鍙栭」鐩牴鐩綍 smtp_password.txt銆?)

        ttk.Label(parent, text="閭欢鏍囬").grid(row=6, column=0, sticky="w", padx=10, pady=5)
        subject_entry = ttk.Entry(parent, textvariable=self.email_subject_template_var)
        subject_entry.grid(row=6, column=1, columnspan=3, sticky="ew", padx=8, pady=5)
        ToolTip(subject_entry, "鍙敤鍙橀噺锛歿part_name}銆亄title}銆亄part_no}銆?)

        buttons = ttk.Frame(parent)
        buttons.grid(row=7, column=0, columnspan=4, sticky="e", padx=10, pady=(4, 8))
        ttk.Button(buttons, text="閲嶆柊璇诲彇", command=self._load_email_config_vars).pack(side="right", padx=(8, 0))
        ttk.Button(buttons, text="淇濆瓨閭閰嶇疆", command=lambda: self._save_email_config_from_vars(show_message=True)).pack(side="right")
        ttk.Button(buttons, text="娴嬭瘯閭欢", command=self._test_email_connection).pack(side="right", padx=(0, 8))
        ttk.Button(buttons, text="璁剧疆璇存槑", command=self._show_email_help).pack(side="right", padx=(0, 8))

    def _show_email_help(self) -> None:
        win = tk.Toplevel(self)
        win.title("閭璁剧疆璇存槑")
        win.geometry("760x560")
        win.transient(self)

        frame = ttk.Frame(win, padding=12)
        frame.pack(fill="both", expand=True)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)

        text = scrolledtext.ScrolledText(frame, wrap="word", font=self._font_tuple(10), height=26)
        text.grid(row=0, column=0, sticky="nsew")
        help_text = """閭鍙戦€佽缃鏄?
涓€銆佸厛璁剧疆鍙戜欢绠憋紙浠?QQ 閭涓轰緥锛?1. 鎵撳紑 QQ 閭缃戦〉鐗堬紝杩涘叆鈥滆缃€濄€?2. 鎵惧埌鈥滆处鎴封€濇垨鈥淧OP3/IMAP/SMTP/Exchange/CardDAV/CalDAV 鏈嶅姟鈥濄€?3. 寮€鍚?SMTP 鏈嶅姟銆俀Q 閭閫氬父浼氳姹傜煭淇￠獙璇併€?4. 寮€鍚悗浼氱敓鎴愨€滄巿鏉冪爜鈥濄€傝繖閲岃鐢ㄦ巿鏉冪爜鐧诲綍 SMTP锛屼笉瑕佸～鍐?QQ 瀵嗙爜銆?
浜屻€佷富鐣岄潰鍙傛暟鎬庝箞濉?鏀朵欢閭锛?  鎺ユ敹绱犳潗鍖呯殑閭銆傚涓偖绠辩敤鑻辨枃閫楀彿鍒嗛殧銆?  褰撳墠榛樿娴嬭瘯閭锛?99467826@qq.com

SMTP锛?  QQ 閭涓€鑸～ smtp.qq.com銆?
绔彛锛?  鍕鹃€夆€滀娇鐢?SSL鈥濇椂锛孮Q 閭涓€鑸～ 465銆?  濡傛灉涓嶇敤 SSL锛屽父瑙佺鍙ｆ槸 587锛屼絾鏈伐鍏烽粯璁ゆ帹鑽?SSL + 465銆?
鐧诲綍璐﹀彿锛?  鍙戜欢閭瀹屾暣鍦板潃锛屼緥濡?浣犵殑QQ鍙稝qq.com銆?
鍙戜欢浜猴細
  閫氬父鍜岀櫥褰曡处鍙风浉鍚岋紱鐣欑┖鏃剁▼搴忎細鑷姩浣跨敤鐧诲綍璐﹀彿銆?
瀵嗙爜鍙橀噺 / 瀵嗙爜鏂囦欢锛?  涓轰簡瀹夊叏锛屼富鐣岄潰涓嶄繚瀛樻巿鏉冪爜鏈韩锛屽彧淇濆瓨璇诲彇浣嶇疆銆?  鏂瑰紡 A锛氳缃幆澧冨彉閲?AMP_SMTP_PASSWORD锛屽€煎～ QQ 閭鎺堟潈鐮併€?  鏂瑰紡 B锛氬湪椤圭洰鏍圭洰褰曞垱寤?smtp_password.txt锛屾枃浠堕噷鍙斁鎺堟潈鐮併€?
闄勪欢涓婇檺 MB锛?  姣忛泦绱犳潗鍖呰秴杩囪繖涓ぇ灏忔椂浼氳烦杩囧彂閫侊紝閬垮厤閭鎷掓敹銆傞粯璁?20MB銆?
閭欢鏍囬锛?  鍙互浣跨敤鍙橀噺 {part_name}銆亄title}銆亄part_no}銆?  渚嬪锛氳憲浣滆В璇诲垎闆嗗畬鎴愶細{part_name}

涓夈€佸紑鍚彂閫?1. 濉ソ鍙傛暟鍚庯紝鐐瑰嚮鈥滀繚瀛橀偖绠遍厤缃€濄€?2. 鍕鹃€夆€滄瘡闆嗗畬鎴愬悗鎵撳寘鍙戦€侀偖浠垛€濄€?3. 寮€濮嬭繍琛屻€傛瘡涓垎闆嗗畬鎴愬悗锛岀▼搴忎細鑷姩鎵撳寘 zip 骞跺彂閫侀偖浠躲€?
鍥涖€佹帓鏌?濡傛灉鍙戦€佸け璐ワ紝鍏堟鏌ワ細
1. 鏄惁寮€鍚簡 SMTP 鏈嶅姟銆?2. 鏄惁浣跨敤鈥滄巿鏉冪爜鈥濓紝鑰屼笉鏄?QQ 瀵嗙爜銆?3. smtp_password.txt 鏄惁鏀惧湪椤圭洰鏍圭洰褰曘€?4. 鏀朵欢閭鏄惁濉啓姝ｇ‘銆?5. 闄勪欢鏄惁瓒呰繃閭闄愬埗銆?"""
        text.insert("1.0", help_text)
        text.configure(state="disabled")

        footer = ttk.Frame(frame)
        footer.grid(row=1, column=0, sticky="e", pady=(10, 0))
        ttk.Button(footer, text="鍏抽棴", command=win.destroy).pack(side="right")

    def _build_models(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(2, weight=1)
        parent.columnconfigure(3, weight=0)
        ttk.Label(parent, text="鍥涗釜澶фā鍨嬭缃?, font=self._font_tuple(10, "bold")).grid(
            row=0, column=0, columnspan=4, sticky="w", padx=10, pady=(8, 4)
        )
        ttk.Label(parent, text="闃舵", foreground="#555").grid(row=1, column=0, sticky="w", padx=10, pady=(0, 4))
        ttk.Label(parent, text="鏉ユ簮", foreground="#555").grid(row=1, column=1, sticky="w", padx=8, pady=(0, 4))
        ttk.Label(parent, text="妯″瀷鍚?, foreground="#555").grid(row=1, column=2, sticky="w", padx=8, pady=(0, 4))
        ttk.Label(parent, text="杩炴帴", foreground="#555").grid(row=1, column=3, sticky="w", padx=8, pady=(0, 4))

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
            ToolTip(provider, "鍙繚鐣欏ぇ绾层€佽剼鏈€佸彴璇嶆鼎鑹蹭笁涓枃鏈ā鍨嬶紱缁樺浘妯″瀷鍦ㄤ笅鏂硅缃€?)

            combo = ttk.Combobox(
                parent,
                textvariable=self.stage_model_vars[stage],
                values=TEXT_MODEL_OPTIONS["gemini"],
                state="normal",
            )
            combo.grid(row=idx, column=2, sticky="ew", padx=8, pady=5)
            self.stage_model_combos[stage] = combo
            ToolTip(combo, "榛樿锛氬ぇ绾?Gemini锛岃剼鏈?GPT-5.5锛屽彴璇嶆鼎鑹?DeepSeek V4 Pro銆?)
            ttk.Button(parent, text="娴嬭瘯", command=lambda st=stage: self._test_text_stage_connection(st), width=8).grid(
                row=idx, column=3, sticky="ew", padx=(0, 10), pady=5
            )

        ttk.Label(parent, text="榛樿锛氬ぇ绾?Gemini锛涜剼鏈?GPT-5.5锛涚粯鍥?GPT-image2锛涘彴璇嶆鼎鑹?DeepSeek V4 Pro銆?, foreground="#555").grid(
            row=5, column=0, columnspan=4, sticky="w", padx=10, pady=(4, 8)
        )

        save_frame = ttk.Frame(parent)
        save_frame.grid(row=6, column=0, columnspan=4, sticky="ew", padx=8, pady=(0, 7))
        ttk.Checkbutton(save_frame, text="杩愯鏃朵繚瀛?Key", variable=self.save_keys_var).pack(side="left", padx=(2, 10))
        ttk.Button(save_frame, text="淇濆瓨 Key", command=self._save_key_files).pack(side="left", padx=(0, 8))

        base_frame = ttk.LabelFrame(parent, text="OpenAI 鍏煎涓浆")
        base_frame.grid(row=7, column=0, columnspan=4, sticky="ew", padx=10, pady=(8, 8))
        base_frame.columnconfigure(1, weight=1)
        ttk.Label(base_frame, text="瀹樼綉").grid(row=0, column=0, sticky="w", padx=8, pady=4)
        ttk.Label(base_frame, text="https://www.fhl.mom/v1", foreground="#555").grid(row=0, column=1, sticky="w", padx=8, pady=4)
        ttk.Label(base_frame, text="BaseURL").grid(row=1, column=0, sticky="w", padx=8, pady=4)
        base_entry = ttk.Entry(base_frame, textvariable=self.foreign_base_url_var)
        base_entry.grid(row=1, column=1, sticky="ew", padx=8, pady=4)
        ToolTip(base_entry, "Gemini銆丱penAI 鍏煎鏂囨湰妯″瀷鍜岀敓鍥炬ā鍨嬮粯璁や娇鐢ㄨ繖涓?/v1 绔偣銆?)
        ttk.Label(base_frame, text="鎺ㄨ崘 Gemini 妯″瀷").grid(row=2, column=0, sticky="w", padx=8, pady=4)
        ttk.Label(base_frame, text="gemini-3.1-pro-preview", foreground="#555").grid(row=2, column=1, sticky="w", padx=8, pady=4)
        ttk.Label(base_frame, text="DeepSeek").grid(row=3, column=0, sticky="w", padx=8, pady=4)
        ttk.Label(base_frame, text=f"涓嶄腑杞紝榛樿 {DEFAULT_DEEPSEEK_BASE_URL}", foreground="#555").grid(row=3, column=1, sticky="w", padx=8, pady=4)

        vault = ttk.LabelFrame(parent, text="API Key锛堝彲淇濆瓨锛?)
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
        ttk.Button(vault, text="淇濆瓨鍏ㄩ儴 Key", command=self._save_all_key_files).grid(row=4, column=1, sticky="e", padx=8, pady=(2, 6))
        ToolTip(vault, "褰撳墠绠€娲佹ā寮忓彧鏄剧ず鍥涙ā鍨嬮渶瑕佺殑 Key锛涙洿澶氬吋瀹?Key 鍙偣椤堕儴 Key銆?)

        sep = ttk.Separator(parent)
        sep.grid(row=9, column=0, columnspan=4, sticky="ew", padx=10, pady=10)

        ttk.Label(parent, text="缁樺浘妯″瀷鏉ユ簮").grid(row=10, column=0, sticky="w", padx=10, pady=7)
        image_provider = ttk.Combobox(parent, textvariable=self.image_provider_var, values=["openai", "none", "dry-run"], state="readonly")
        image_provider.grid(row=10, column=1, columnspan=2, sticky="ew", padx=8, pady=7)
        image_provider.bind("<<ComboboxSelected>>", self._on_image_provider_change)
        ToolTip(image_provider, "none 琛ㄧず涓嶈皟鐢ㄧ敓鍥炬帴鍙ｏ紱dry-run 鍙繚瀛樺浘鐗囨彁绀鸿瘝銆?)

        ttk.Label(parent, text="缁樺浘妯″瀷").grid(row=11, column=0, sticky="w", padx=10, pady=7)
        self.image_model_combo = ttk.Combobox(parent, textvariable=self.image_model_var, values=IMAGE_MODEL_OPTIONS["none"], state="normal")
        self.image_model_combo.grid(row=11, column=1, columnspan=2, sticky="ew", padx=8, pady=7)
        ToolTip(self.image_model_combo, "榛樿 gpt-image-2锛岀粡 NewAPI/OpenAI 鍏煎涓浆璇锋眰銆?)
        ttk.Button(parent, text="娴嬭瘯缁樺浘", command=self._test_image_connection, width=8).grid(row=11, column=3, sticky="ew", padx=(0, 10), pady=7)

    def _browse_book(self) -> None:
        path = filedialog.askopenfilename(title="閫夋嫨涔︾睄 PDF", filetypes=[("PDF 鏂囦欢", "*.pdf"), ("鎵€鏈夋枃浠?, "*.*")])
        if not path:
            return
        self.book_var.set(path)
        self._sync_output_dir_for_book(force=True)

    def _browse_out(self) -> None:
        path = filedialog.askdirectory(title="閫夋嫨杈撳嚭鐩綍")
        if path:
            self.out_var.set(path)
            self._last_auto_out = ""
            self._last_book_for_auto_out = self.book_var.get().strip().strip('"')

    def _browse_continue_folder(self) -> None:
        path = filedialog.askdirectory(title="閫夋嫨瑕佺画浣滅殑宸叉湁杈撳嚭鐩綍 / 鍒嗛泦鐩綍")
        if path:
            self.continue_folder_var.set(path)
            if not self.out_var.get().strip():
                self.out_var.set(path)

    def _browse_outline(self) -> None:
        path = filedialog.askopenfilename(title="閫夋嫨宸叉湁澶х翰 JSON", filetypes=[("JSON 鏂囦欢", "*.json"), ("鏂囨湰鏂囦欢", "*.txt"), ("鎵€鏈夋枃浠?, "*.*")])
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
                self.stage_model_vars[stage].set("deepseek-chat")
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
        base_url = base_url
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
            messagebox.showinfo("娴嬭瘯杩炴帴", "dry-run/none 涓嶉渶瑕佹祴璇曡繛鎺ャ€?)
            return
        key_var = self._key_var_for_provider(provider)
        api_key = key_var.get().strip() if key_var is not None else ""
        api_key = api_key or read_api_key(provider, "")
        if not api_key:
            messagebox.showerror("娴嬭瘯杩炴帴", f"{provider} API Key 涓虹┖锛岃鍏堝～鍐欐垨淇濆瓨 Key銆?)
            return
        if not model:
            messagebox.showerror("娴嬭瘯杩炴帴", "妯″瀷鍚嶄负绌猴紝璇峰厛閫夋嫨鎴栧～鍐欐ā鍨嬪悕銆?)
            return
        base_url = deepseek_base_url() if provider == "deepseek" else self._normalized_foreign_base_url()
        self._append_log(f"馃攲 娴嬭瘯杩炴帴锛歿stage} / {provider} / {model} / {base_url}")
        thread = threading.Thread(target=self._test_model_worker, args=(provider, model, api_key, base_url, stage), daemon=True)
        thread.start()

    def _test_image_connection(self) -> None:
        provider = self.image_provider_var.get().strip() or "openai"
        model = self.image_model_var.get().strip()
        if provider in {"dry-run", "none"}:
            messagebox.showinfo("娴嬭瘯杩炴帴", "none/dry-run 涓嶉渶瑕佹祴璇曠粯鍥捐繛鎺ャ€?)
            return
        api_key = self.image_api_key_var.get().strip() or read_api_key("image", "")
        if not api_key:
            messagebox.showerror("娴嬭瘯杩炴帴", "缁樺浘 API Key 涓虹┖锛岃鍏堝～鍐?GPT-image2 Key銆?)
            return
        if not model:
            messagebox.showerror("娴嬭瘯杩炴帴", "缁樺浘妯″瀷鍚嶄负绌猴紝璇峰厛閫夋嫨鎴栧～鍐欐ā鍨嬪悕銆?)
            return
        base_url = self._normalized_foreign_base_url()
        self._append_log(f"馃攲 娴嬭瘯缁樺浘妯″瀷锛歿provider} / {model} / {base_url}")
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
                    self.log_queue.put(("log", f"鉁?娴嬭瘯缁樺浘杩炴帴鎴愬姛锛歱rovider=gemini锛宮odel={model}锛宐ase={base_url}锛岃€楁椂 {elapsed:.1f}s锛屾帴鍙ｏ細generateContent"))
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
                    raise RuntimeError("鍥剧墖鎺ュ彛鏈繑鍥?data銆?)
                first = data[0]
                if not (getattr(first, "b64_json", None) or getattr(first, "url", None)):
                    raise RuntimeError("鍥剧墖鎺ュ彛鏈繑鍥?b64_json 鎴?url銆?)
                elapsed = time.perf_counter() - started
                self.log_queue.put(("log", f"鉁?娴嬭瘯缁樺浘杩炴帴鎴愬姛锛歱rovider={provider}锛宮odel={model}锛宐ase={base_url}锛岃€楁椂 {elapsed:.1f}s锛屾帴鍙ｏ細images.generate锛屽昂瀵革細{payload.get('size')}"))
                return
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "Connection test. Reply with exactly: OK"}],
                max_tokens=8,
                temperature=0,
            )
            content = _extract_chat_content(response)
            if not content:
                raise RuntimeError(f"妯″瀷杩斿洖涓虹┖鎴栨牸寮忎笉鍙瘑鍒細{type(response).__name__}")
            elapsed = time.perf_counter() - started
            self.log_queue.put(("log", f"鉁?娴嬭瘯杩炴帴鎴愬姛锛歴tage={label}锛宲rovider={provider}锛宮odel={model}锛宐ase={base_url}锛岃€楁椂 {elapsed:.1f}s锛岃繑鍥烇細{content[:80] or '绌?}"))
        except Exception as exc:
            elapsed = time.perf_counter() - started
            self.log_queue.put(("log", f"鉂?娴嬭瘯杩炴帴澶辫触锛歴tage={label}锛宲rovider={provider}锛宮odel={model}锛宐ase={base_url}锛岃€楁椂 {elapsed:.1f}s锛岄敊璇細{type(exc).__name__}: {exc}"))

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
                    messagebox.showerror("璞嗗寘鎺ュ叆鐐瑰～鍐欓敊璇?, "璞嗗寘鎺ュ叆鐐圭湅璧锋潵鍍?API Key銆傝濉啓 ep-... 鎺ュ叆鐐?ID锛孉PI Key 濉埌璞嗗寘 Key 杈撳叆妗嗐€?)
                return False
            write_text(PROJECT_ROOT / DOUBAO_ENDPOINT_FILE_NAME, endpoint + "\n")
            saved.append(DOUBAO_ENDPOINT_FILE_NAME)
        saved.extend(cleared)
        if saved:
            self._append_log("宸蹭繚瀛?Key/鎺ュ叆鐐规枃浠讹細" + "銆?.join(saved))
            if show_message:
                messagebox.showinfo("Key/鎺ュ叆鐐瑰凡淇濆瓨", "宸蹭繚瀛樺埌椤圭洰鏍圭洰褰曪細\n" + "\n".join(saved))
            return True
        if show_message:
            messagebox.showinfo("娌℃湁鍙繚瀛樼殑鍐呭", "褰撳墠娌℃湁濉啓鍙繚瀛樼殑 API Key 鎴栬眴鍖呮帴鍏ョ偣銆?)
        return False

    def _save_key_files(self) -> bool:
        return self._save_all_key_files(show_message=True)

    def _show_key_manager(self) -> None:
        self._load_all_key_vars(overwrite=False)
        win = tk.Toplevel(self)
        win.title("API Key 绠＄悊")
        win.geometry("760x360")
        win.transient(self)
        frame = ttk.Frame(win, padding=14)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)
        fields = [
            ("Gemini API Key", self.gemini_key_var, "gemini_api_key.txt", True),
            ("OpenAI API Key", self.openai_key_var, "openai_api_key.txt", True),
            ("GPT-image2 API Key", self.image_api_key_var, "image_api_key.txt", True),
            ("璞嗗寘/鐏北鏂硅垷 API Key", self.doubao_key_var, "ark_api_key.txt", True),
            ("DeepSeek API Key", self.deepseek_key_var, "deepseek_api_key.txt", True),
            ("璞嗗寘鎺ュ叆鐐?ID", self.doubao_endpoint_var, DOUBAO_ENDPOINT_FILE_NAME, False),
        ]
        for row, (label, var, filename, is_secret) in enumerate(fields):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", padx=8, pady=8)
            entry = ttk.Entry(frame, textvariable=var)
            entry.grid(row=row, column=1, sticky="ew", padx=8, pady=8)
            ttk.Label(frame, text=filename, foreground="#666").grid(row=row, column=2, sticky="w", padx=8, pady=8)
        tip = ttk.Label(frame, text="Key 涓庤眴鍖呮帴鍏ョ偣浼氫繚瀛樹负椤圭洰鏍圭洰褰曚笅鐨?txt 鏂囦欢锛涚▼搴忚繍琛屾椂浼氳嚜鍔ㄨ鍙栥€?, foreground="#555")
        tip.grid(row=5, column=0, columnspan=3, sticky="w", padx=8, pady=(8, 4))
        buttons = ttk.Frame(frame)
        buttons.grid(row=6, column=0, columnspan=3, sticky="e", padx=8, pady=(12, 0))
        ttk.Button(buttons, text="淇濆瓨鍏ㄩ儴 Key/鎺ュ叆鐐?, command=lambda: (self._save_all_key_files(show_message=True), win.destroy())).pack(side="right", padx=(8, 0))
        ttk.Button(buttons, text="鍙栨秷", command=win.destroy).pack(side="right")

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
        self.email_subject_template_var.set(str(config.get("subject_template") or "钁椾綔瑙ｈ鍒嗛泦瀹屾垚锛歿part_name}"))

    def _email_config_from_vars(self) -> dict | None:
        try:
            port = int(self.email_smtp_port_var.get().strip() or "465")
            if port <= 0:
                raise ValueError
        except Exception:
            messagebox.showerror("閭閰嶇疆閿欒", "SMTP 绔彛蹇呴』鏄鏁存暟銆?)
            return None
        try:
            max_mb = int(self.email_max_mb_var.get().strip() or "20")
            if max_mb <= 0:
                raise ValueError
        except Exception:
            messagebox.showerror("閭閰嶇疆閿欒", "闄勪欢涓婇檺 MB 蹇呴』鏄鏁存暟銆?)
            return None

        recipients = [x.strip() for x in self.email_to_var.get().replace("锛?, ",").replace("锛?, ",").split(",") if x.strip()]
        enabled = bool(self.email_enabled_var.get())
        host = self.email_smtp_host_var.get().strip() or "smtp.qq.com"
        username = self.email_username_var.get().strip()
        sender = self.email_from_var.get().strip() or username
        password_env = self.email_password_env_var.get().strip() or "AMP_SMTP_PASSWORD"
        password_file = self.email_password_file_var.get().strip() or "smtp_password.txt"
        subject_template = self.email_subject_template_var.get().strip() or "钁椾綔瑙ｈ鍒嗛泦瀹屾垚锛歿part_name}"

        if enabled:
            missing = []
            if not recipients:
                missing.append("鏀朵欢閭")
            if not host:
                missing.append("SMTP")
            if not username:
                missing.append("鐧诲綍璐﹀彿")
            if not sender:
                missing.append("鍙戜欢浜?)
            if missing:
                messagebox.showerror("閭閰嶇疆閿欒", "寮€鍚偖绠卞彂閫佸墠璇疯ˉ鍏細" + "銆?.join(missing))
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
            messagebox.showerror("淇濆瓨閭閰嶇疆澶辫触", str(exc))
            return False
        if show_message:
            messagebox.showinfo("宸蹭繚瀛?, f"閭閰嶇疆宸插啓鍏ワ細\n{RUNTIME_SWITCHES_CONFIG_PATH}")
        return True

    def _test_email_connection(self) -> None:
        if not self._save_email_config_from_vars(show_message=False):
            return
        self._append_log("馃摟 寮€濮嬫祴璇曢偖绠辫繛鎺ワ細浼氬皾璇曠櫥褰?SMTP锛屽苟鍙戦€佷竴灏佸皬娴嬭瘯閭欢銆?)
        thread = threading.Thread(target=self._test_email_worker, daemon=True)
        thread.start()

    def _test_email_worker(self) -> None:
        started = time.perf_counter()

        def emit(message: str) -> None:
            self.log_queue.put(("log", "馃摟 " + str(message)))

        try:
            result = test_email_connection(send_test=True, logger=emit)
            elapsed = time.perf_counter() - started
            if result.get("ok"):
                sent_text = "宸插彂閫佹祴璇曢偖浠? if result.get("sent") else "浠呮祴璇曡繛鎺?
                self.log_queue.put(("log", f"鉁?閭娴嬭瘯鎴愬姛锛歿sent_text}锛岃€楁椂 {elapsed:.1f}s"))
            else:
                self.log_queue.put(("log", f"鉂?閭娴嬭瘯澶辫触锛岃€楁椂 {elapsed:.1f}s锛歿result.get('reason') or result.get('error') or '鏈煡鍘熷洜'}"))
                smtp_info = result.get("smtp") if isinstance(result.get("smtp"), dict) else {}
                if smtp_info:
                    self.log_queue.put((
                        "log",
                        "馃摟 SMTP 閰嶇疆锛?
                        f"{smtp_info.get('host') or ''}:{smtp_info.get('port') or ''}锛?
                        f"SSL={smtp_info.get('use_ssl')}锛?
                        f"鐧诲綍璐﹀彿={smtp_info.get('username') or ''}锛?
                        f"鍙戜欢浜?{smtp_info.get('sender') or ''}锛?
                        f"鏀朵欢浜?{', '.join(smtp_info.get('recipients') or [])}",
                    ))
                warnings = result.get("warnings") if isinstance(result.get("warnings"), list) else []
                for warning in warnings:
                    self.log_queue.put(("log", f"馃摟 閰嶇疆鎻愰啋锛歿warning}"))
                if result.get("hint"):
                    self.log_queue.put(("log", f"馃摟 鎺掓煡寤鸿锛歿result.get('hint')}"))
                if result.get("stage") or result.get("error_type"):
                    self.log_queue.put(("log", f"馃摟 澶辫触闃舵锛歿result.get('stage') or '鏈煡'}锛涘紓甯哥被鍨嬶細{result.get('error_type') or '鏈煡'}"))
                if result.get("traceback"):
                    self.log_queue.put(("log", "馃摟 閭娴嬭瘯 traceback锛歕n" + str(result.get("traceback"))))
        except Exception as exc:
            elapsed = time.perf_counter() - started
            self.log_queue.put(("log", f"鉂?閭娴嬭瘯寮傚父锛岃€楁椂 {elapsed:.1f}s锛歿type(exc).__name__} - {exc}"))
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
                messagebox.showerror("缂哄皯缁綔鏂囦欢澶?, "璇峰厛閫夋嫨涓€涓凡鏈夎緭鍑虹洰褰曟垨鍒嗛泦鐩綍銆?)
                return None
            continue_folder = Path(continue_text).expanduser()
            if not continue_folder.exists() or not continue_folder.is_dir():
                messagebox.showerror("鎵句笉鍒扮画浣滄枃浠跺す", f"鐩綍涓嶅瓨鍦細\n{continue_folder}")
                return None
            # 鎸囧畾鏂囦欢澶圭画浣滄ā寮忎笉鍐嶅己鍒惰姹?PDF锛沚ook 瀛楁鐢ㄧ画浣滅洰褰曞崰浣嶏紝runner 浼氱洿鎺ヨ鍙?continue_from_folder銆?
            book = continue_folder
        else:
            book_text = self.book_var.get().strip().strip('"')
            if not book_text:
                messagebox.showerror("缂哄皯 PDF", "璇峰厛閫夋嫨涓€鏈功绫?PDF銆?)
                return None
            book = Path(book_text).expanduser()
            if not book.exists():
                messagebox.showerror("鎵句笉鍒?PDF", f"鏂囦欢涓嶅瓨鍦細\n{book}")
                return None
            if book.suffix.lower() != ".pdf":
                messagebox.showerror("鏂囦欢绫诲瀷涓嶆纭?, "褰撳墠绋嬪簭鍙敮鎸?PDF銆?)
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
            messagebox.showerror("缂哄皯杈撳嚭鐩綍", "璇烽€夋嫨杈撳嚭鐩綍銆?)
            return None
        out = Path(out_text).expanduser()

        try:
            max_retries = int(self.max_retries_var.get())
            if max_retries < 0:
                raise ValueError
        except Exception:
            messagebox.showerror("鍙傛暟閿欒", "閲嶈瘯娆℃暟蹇呴』鏄?0 鎴栨鏁存暟銆?)
            return None

        outline_path = None
        outline_text = self.outline_json_var.get().strip().strip('"')
        if outline_text:
            outline_path = Path(outline_text).expanduser()
            if not outline_path.exists():
                messagebox.showerror("鎵句笉鍒板ぇ绾?, f"宸叉湁澶х翰 JSON 涓嶅瓨鍦細\n{outline_path}")
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
                    self._append_log(f"鎻愮ず锛歿title} 妯″瀷鍚嶅凡鑷姩淇锛歿model} 鈫?{fixed_model}")
                    self.stage_model_vars[stage].set(fixed_model)
                    model = fixed_model
            if provider == "doubao":
                saved_endpoint = self.doubao_endpoint_var.get().strip()
                if not model or model == "ep-璇峰～鍐欐帹鐞嗘帴鍏ョ偣ID":
                    model = saved_endpoint
                    if model:
                        self.stage_model_vars[stage].set(model)
                if doubao_model_looks_like_api_key(model):
                    messagebox.showerror(
                        "璞嗗寘妯″瀷鍚嶅～鍐欓敊璇?,
                        f"{title} 鐨勬ā鍨嬪悕鐪嬭捣鏉ュ儚 API Key銆俓n\n"
                        "妯″瀷鍚嶆爮璇峰～鍐欑伀灞辨柟鑸熸帹鐞嗘帴鍏ョ偣 ID锛堥€氬父 ep- 寮€澶达級锛?
                        "鎴?doubao- 寮€澶寸殑鍙洿杩?Model ID锛汚PI Key 璇峰～鍐欏湪涓嬫柟鈥滆眴鍖?鐏北鏂硅垷 API Key鈥濄€?
                    )
                    return None
                if saved_endpoint and doubao_model_looks_like_api_key(saved_endpoint):
                    messagebox.showerror(
                        "璞嗗寘鎺ュ叆鐐瑰～鍐欓敊璇?,
                        "璞嗗寘鎺ュ叆鐐圭湅璧锋潵鍍?API Key銆傝濉啓 ep-... 鎺ュ叆鐐?ID锛孉PI Key 濉埌璞嗗寘 Key 杈撳叆妗嗐€?
                    )
                    return None
            key = provider_key(provider)
            if provider not in {"dry-run", "none"} and not key and not read_api_key(provider, ""):
                self._append_log(f"鎻愮ず锛歿title} 鐨?{provider} API Key 涓虹┖锛岀▼搴忎細灏濊瘯璇诲彇鐜鍙橀噺鎴栨湰鍦?key 鏂囦欢锛涘鏋滀粛涓虹┖浼氭姤閿欍€?)
            stage_values[stage] = (provider, model, key)

        image_provider = self.image_provider_var.get().strip() or "openai"
        image_key = self.image_api_key_var.get().strip() or read_api_key("image", "")
        image_interval = self.image_interval_var.get().strip() or "3-8"

        try:
            start_episode_no = int(self.start_episode_var.get())
            if start_episode_no < 1:
                raise ValueError
        except Exception:
            messagebox.showerror("鍙傛暟閿欒", "璧峰闆嗘暟蹇呴』鏄ぇ浜庣瓑浜?1 鐨勬暣鏁般€?)
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
            messagebox.showinfo("姝ｅ湪杩愯", "褰撳墠浠诲姟杩樺湪杩愯銆傚彲浠ョ偣鍑烩€滃仠姝⑩€濆畨鍏ㄥ仠姝€?)
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
        self.status_var.set("杩愯涓€?)
        self._set_running_state(True)
        self.progress.start(10)
        self._clear_log()
        self._append_log("寮€濮嬭繍琛屻€傚綋鍓嶆祦绋嬶細鐢熸垚澶х翰 鈫?鍒嗛泦鎻愮ず璇?鈫?鍒囧垎 PDF 鈫?鐢熸垚鑴氭湰 鈫?鍙拌瘝娑﹁壊 鈫?閰嶅浘/鍚庡鐞?鈫?鎷嗗垎鑴氭湰涓庡浘鐗囥€?)
        self._append_log("PDF 绛栫暐锛氱姝?PDF 鐩翠紶锛涘彧鎶婃湰鍦?PyMuPDF4LLM/pypdf 瑙ｆ瀽鍚庣殑 Markdown/鏂囨湰浼犵粰妯″瀷銆?)
        self._append_log(f"鏈湴瑙ｆ瀽锛歿args.local_parse_mode} / 瑙ｆ瀽鍣?{args.mineru_backend}")
        for label, provider, model in [
            ("澶х翰鐢熸垚", args.outline_provider, args.outline_model),
            ("鑴氭湰鐢熸垚", args.script_provider, args.script_model),
            ("鍙拌瘝娑﹁壊", args.polish_provider, args.polish_model),
        ]:
            self._append_log(f"{label}妯″瀷锛歿provider} / {model or '榛樿妯″瀷'}")
        self._append_log(f"鐢熷浘妯″瀷锛歿args.image_provider} / {args.image_model or '榛樿妯″瀷'}")
        if args.test_b_image_limit:
            self._append_log(f"娴嬭瘯杩愯锛氬厛鐢熸垚/澶嶇敤鍏ㄦ枃鏁呬簨绾垮ぇ绾诧紱B 鍥惧彧鐢熸垚/澶勭悊鍓?{args.test_b_image_limit} 寮狅紝鍚庣画浠嶆墽琛屾媶鍒嗐€佹墦鍖呭苟灏濊瘯鍙戦€侀偖浠躲€?)
        self._append_log(f"閰嶅浘鑺傚锛氭瘡鍙ュ彴璇嶅搴斾竴骞曠敾闈紝鍗曞箷绾?{args.image_interval_seconds} 绉掋€?)
        self._append_log("鍒嗛泦鏁伴噺锛氫紭鍏堢敱澶х翰妯″瀷闃呰鍏ㄦ枃鍚庢寜鏁呬簨绾垮喅瀹氾紱鍙粍鍚堝叏涔︿笉鍚屼綅缃殑鏉愭枡锛岀珷鑺傞〉鐮佸彧浣滀负鍘熸枃瀹氫綅渚濇嵁銆?)
        self._append_log(f"杈撳叆 PDF锛歿args.book}")
        self._append_log(f"杈撳嚭鐩綍锛歿args.out}")
        thread = threading.Thread(target=self._worker, args=(args,), daemon=True)
        thread.start()

    def _stop(self) -> None:
        if not self.running or self.cancel_event is None:
            return
        self.cancel_event.set()
        self.stop_button.configure(state="disabled")
        self.stop_button_top.configure(state="disabled")
        self._append_log("宸茶姹傚仠姝細褰撳墠 API 璇锋眰杩斿洖鍚庯紝绋嬪簭浼氬湪涓嬩竴姝ュ墠瀹夊叏鍋滄銆?)

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
            self.status_var.set("宸插畬鎴?)
            self._append_log("鉁?鍏ㄩ儴瀹屾垚銆?)
            messagebox.showinfo("瀹屾垚", f"鐢熸垚瀹屾垚銆俓n\n杈撳嚭鐩綍锛歕n{out_dir}")
        elif cancelled:
            self.status_var.set("宸插仠姝?)
            self._append_log("鈴癸笍 宸插仠姝€傚凡鐢熸垚鐨勬枃浠朵細淇濈暀鍦ㄨ緭鍑虹洰褰曘€?)
            messagebox.showinfo("宸插仠姝?, f"浠诲姟宸插仠姝€俓n\n宸茬敓鎴愮殑鏂囦欢淇濈暀鍦細\n{out_dir}")
        else:
            self.status_var.set("杩愯澶辫触")
            self._append_log(f"鉂?杩愯澶辫触锛歿error}")
            messagebox.showerror("杩愯澶辫触", f"杩愯澶辫触锛歕n{error}\n\n璇︽儏璇锋煡鐪嬫棩蹇椼€?)

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
            messagebox.showinfo("娌℃湁杈撳嚭鐩綍", "杩樻病鏈夎缃緭鍑虹洰褰曘€?)
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
            messagebox.showerror("鏃犳硶鎵撳紑鐩綍", str(exc))

    def _clear_output_dir(self) -> None:
        out_text = self.out_var.get().strip().strip('"')
        target = Path(out_text).expanduser() if out_text else self.last_output_dir
        if not target:
            messagebox.showinfo("娌℃湁杈撳嚭鐩綍", "杩樻病鏈夎缃緭鍑虹洰褰曘€?)
            return
        try:
            target = target.resolve()
        except Exception:
            target = target
        if str(target).strip() in {"", str(target.anchor), str(PROJECT_ROOT.resolve())}:
            messagebox.showerror("涓嶈兘娓呯┖", "杩欎釜鐩綍杩囦簬鍗遍櫓锛岀▼搴忔嫆缁濇竻绌恒€傝鎹竴涓槑纭殑杈撳嚭鐩綍銆?)
            return
        target.mkdir(parents=True, exist_ok=True)
        items = list(target.iterdir())
        if not items:
            messagebox.showinfo("鐩綍宸叉槸绌虹殑", f"杈撳嚭鐩綍褰撳墠涓虹┖锛歕n{target}")
            return
        if not messagebox.askyesno("纭娓呯┖杈撳嚭鐩綍", f"纭畾瑕佹竻绌轰笅闈㈢洰褰曚腑鐨勫叏閮ㄥ唴瀹瑰悧锛焅n\n{target}\n\n杩欎釜鎿嶄綔涓嶅彲鎾ら攢銆?):
            return
        book_text = self.book_var.get().strip().strip('"')
        preserved = backup_outline_files_before_clear(target, Path(book_text).expanduser() if book_text else None)
        if preserved:
            self._append_log(f"馃О 宸插浠藉垎闆嗗ぇ绾插埌锛歿preserved[0].parent}")
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
            self._append_log("鈿狅笍 杈撳嚭鐩綍宸查儴鍒嗘竻绌猴紝浣嗕互涓嬮」鐩垹闄ゅけ璐ワ細")
            for line in failed:
                self._append_log("  - " + line)
            messagebox.showwarning("閮ㄥ垎鍒犻櫎澶辫触", "杈撳嚭鐩綍宸查儴鍒嗘竻绌猴紝璇︽儏璇锋煡鐪嬫棩蹇椼€?)
        else:
            self._append_log(f"馃Ч 宸叉竻绌鸿緭鍑虹洰褰曪細{target}")
            messagebox.showinfo("宸叉竻绌?, f"宸叉竻绌鸿緭鍑虹洰褰曪細\n{target}")

    def _show_prompts(self) -> None:
        win = tk.Toplevel(self)
        win.title("鎻愮ず璇?/ 瑙勮寖")
        win.geometry("980x720")
        win.transient(self)
        frame = ttk.Frame(win, padding=10)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)
        self._build_prompt_tab(frame)
        self.status_var.set("姝ｅ湪缂栬緫鎻愮ず璇?/ 鍚庡鐞嗚鑼?)

    def _show_visual(self) -> None:
        win = tk.Toplevel(self)
        win.title("瑙嗚鍚庡鐞?)
        win.geometry("1040x620")
        win.transient(self)
        frame = ttk.Frame(win, padding=10)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)
        self._build_visual_tab(frame)
        self.status_var.set("姝ｅ湪缂栬緫瑙嗚鍚庡鐞嗗弬鏁?)

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
        elif self.stage_provider_vars["script"].get().strip() == "openai" and self.stage_model_vars["script"].get().strip() in {"", "gpt-5.5-pro", "gpt-5.5"}:
            self.stage_model_vars["script"].set(DEFAULT_OPENAI_TEXT_MODEL)
            repaired_settings = True
        if self.stage_provider_vars["polish"].get().strip() in {"", "gemini", "doubao", "openai"}:
            self.stage_provider_vars["polish"].set("deepseek")
            self.stage_model_vars["polish"].set("deepseek-chat")
            repaired_settings = True
        elif self.stage_provider_vars["polish"].get().strip() == "deepseek" and not self.stage_model_vars["polish"].get().strip():
            self.stage_model_vars["polish"].set("deepseek-chat")
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
            if provider == "doubao" and model == "ep-璇峰～鍐欐帹鐞嗘帴鍏ョ偣ID":
                self.stage_model_vars[stage].set("")
                repaired_settings = True
        if self.image_provider_var.get().strip() in {"", "none", "gemini"}:
            self.image_provider_var.set("openai")
            self.image_model_var.set("gpt-image-2")
            repaired_settings = True
        elif self.image_provider_var.get().strip() == "openai" and self.image_model_var.get().strip() in {"", "gpt-image-1.5", "gpt-image-1", "gpt-image-1-mini", "dall-e-2", "dall-e-3"}:
            self.image_model_var.set("gpt-image-2")
            repaired_settings = True

        # 鎻愮ず璇嶅凡澶栫疆鍒?prompts/ 鐩綍锛涙棫鐗?gui_settings.json 涓殑 prompts 涓嶅啀瑕嗙洊鏂囦欢銆?
        self._reload_prompt_files(update_editors=True)
        for stage, _title, _tip in TEXT_STAGES:
            self._on_stage_provider_change(stage)
        self._on_image_provider_change()
        if repaired_settings:
            self._save_settings()
            self._append_log("宸茶嚜鍔ㄤ慨澶嶆棫妯″瀷閰嶇疆锛屽苟淇濆瓨鍒?gui_settings.json銆?)

    def _on_close(self) -> None:
        if self.running:
            if not messagebox.askyesno("浠诲姟姝ｅ湪杩愯", "浠诲姟姝ｅ湪杩愯涓€傝鍏堣姹傚仠姝㈠苟閫€鍑哄悧锛熷綋鍓?API 璇锋眰鍙兘浠嶉渶杩斿洖鍚庢墠浼氬仠涓嬨€?):
                return
            if self.cancel_event is not None:
                self.cancel_event.set()
        self._save_settings()
        self.destroy()


def main() -> None:
    app = AutoMediaGUI()
    app.mainloop()



