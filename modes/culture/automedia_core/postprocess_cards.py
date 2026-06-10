from __future__ import annotations

import json
import math
import os
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont

BRAND_NAME = "知识慢炖"
BRAND_SLOGAN = "让经典不再高冷，让智慧人人可用"
DEFAULT_FOLLOW_TEXT = "创作不易，欢迎在下方链接购买原书支持我们"
DEFAULT_CTA_TEXT = "关注【知识慢炖】，下一集继续把问题讲透"
BEST_POSTPROCESS_ENGINE = "playwright_html"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROMPTS_DIR = PROJECT_ROOT / "prompts"
CONFIG_DIR = PROJECT_ROOT / "config"
POSTPROCESS_SPEC_PATH = PROMPTS_DIR / "05_后处理规范.json"
POSTPROCESS_OVERRIDE_PATH = CONFIG_DIR / "后处理风格覆盖.json"
BRAND_CONFIG_PATH = CONFIG_DIR / "文案风格配置.json"
RUNTIME_SWITCH_PATH = Path(os.environ.get("QUANLAN_CULTURE_RUN_SWITCH_FILE") or (CONFIG_DIR / "运行开关.json"))
ASSETS_DIR = Path(__file__).resolve().parent / "assets"
BRAND_LOGO_PATH = ASSETS_DIR / "knowledge_slow_stew_logo.png"


def _brand_display_name(name: str) -> str:
    text = str(name or BRAND_NAME).strip()
    if text.startswith("【") and text.endswith("】"):
        return text
    return f"【{text.strip('【】')}】"

DEFAULT_LAYOUT_CONFIG: dict[str, Any] = {
    "version": 12,
    "note": "自适应安全排版模板：封面、首页、片尾的坐标、字号、颜色、边框、暗角、品牌栏均可配置。坐标均为相对比例 [x1,y1,x2,y2]。v12 优化 AC 系列图安全间距；A02 品牌区独立居中，竖版整体上移，默认避免章节、集名、品牌栏互相干涉，长标题只缩字号、不换行、不省略，防止溢出。",
    "cover": {"A2": {"book_box": [0.075, 0.058, 0.925, 0.155], "author_box": [0.28, 0.168, 0.72, 0.205], "chapter_no_box": [0.33, 0.225, 0.67, 0.268], "chapter_name_box": [0.1, 0.3, 0.9, 0.398], "episode_no_box": [0.33, 0.42, 0.67, 0.463], "episode_name_box": [0.075, 0.493, 0.925, 0.61], "footer_box": [0.07, 0.78, 0.93, 0.902], "episode_box": [0.33, 0.42, 0.67, 0.463], "title_box": [0.1, 0.3, 0.9, 0.398], "description_box": [0.075, 0.493, 0.925, 0.61]}, "A1": {"book_box": [0.075, 0.06, 0.925, 0.155], "author_box": [0.28, 0.168, 0.72, 0.208], "chapter_no_box": [0.32, 0.245, 0.68, 0.292], "chapter_name_box": [0.11, 0.318, 0.89, 0.42], "episode_no_box": [0.32, 0.452, 0.68, 0.498], "episode_name_box": [0.07, 0.528, 0.93, 0.65], "footer_box": [0.08, 0.79, 0.92, 0.91], "episode_box": [0.32, 0.452, 0.68, 0.498], "title_box": [0.11, 0.318, 0.89, 0.42], "description_box": [0.07, 0.528, 0.93, 0.65]}, "A01": {"book_box": [0.1, 0.052, 0.9, 0.165], "author_box": [0.33, 0.178, 0.67, 0.225], "chapter_no_box": [0.36, 0.264, 0.64, 0.31], "chapter_name_box": [0.16, 0.335, 0.84, 0.43], "episode_no_box": [0.36, 0.466, 0.64, 0.51], "episode_name_box": [0.11, 0.538, 0.89, 0.65], "footer_box": [0.22, 0.79, 0.78, 0.905], "episode_box": [0.36, 0.466, 0.64, 0.51], "title_box": [0.16, 0.335, 0.84, 0.43], "description_box": [0.11, 0.538, 0.89, 0.65]}, "A02": {"book_box": [0.22, 0.075, 0.78, 0.205], "author_box": [0.42, 0.22, 0.58, 0.26], "chapter_no_box": [0.42, 0.295, 0.58, 0.34], "chapter_name_box": [0.3, 0.38, 0.7, 0.475], "episode_no_box": [0.42, 0.505, 0.58, 0.55], "episode_name_box": [0.22, 0.585, 0.78, 0.685], "footer_box": [0.32, 0.76, 0.68, 0.89], "episode_box": [0.42, 0.505, 0.58, 0.55], "title_box": [0.3, 0.38, 0.7, 0.475], "description_box": [0.22, 0.585, 0.78, 0.685]}, "vertical": {"book_box": [0.075, 0.058, 0.925, 0.155], "author_box": [0.28, 0.168, 0.72, 0.205], "chapter_no_box": [0.33, 0.225, 0.67, 0.268], "chapter_name_box": [0.1, 0.3, 0.9, 0.398], "episode_no_box": [0.33, 0.42, 0.67, 0.463], "episode_name_box": [0.075, 0.493, 0.925, 0.61], "footer_box": [0.07, 0.78, 0.93, 0.902], "episode_box": [0.33, 0.42, 0.67, 0.463], "title_box": [0.1, 0.3, 0.9, 0.398], "description_box": [0.075, 0.493, 0.925, 0.61]}, "wide": {"book_box": [0.22, 0.075, 0.78, 0.205], "author_box": [0.42, 0.22, 0.58, 0.26], "chapter_no_box": [0.42, 0.295, 0.58, 0.34], "chapter_name_box": [0.3, 0.38, 0.7, 0.475], "episode_no_box": [0.42, 0.505, 0.58, 0.55], "episode_name_box": [0.22, 0.585, 0.78, 0.685], "footer_box": [0.32, 0.76, 0.68, 0.89], "episode_box": [0.42, 0.505, 0.58, 0.55], "title_box": [0.3, 0.38, 0.7, 0.475], "description_box": [0.22, 0.585, 0.78, 0.685]}},
    "endcard": {
        "C": {
            "heading_panel": [0.08, 0.115, 0.92, 0.255],
            "heading_box": [0.08, 0.120, 0.92, 0.245],
            "teaser_panel": [0.08, 0.315, 0.92, 0.505],
            "teaser_box": [0.12, 0.340, 0.88, 0.480],
            "cta_panel": [0.08, 0.610, 0.92, 0.738],
            "cta_box": [0.12, 0.630, 0.88, 0.718],
            "footer_box": [0.08, 0.805, 0.92, 0.930]
        },
        "vertical": {
            "heading_panel": [0.08, 0.115, 0.92, 0.255],
            "heading_box": [0.08, 0.120, 0.92, 0.245],
            "teaser_panel": [0.08, 0.315, 0.92, 0.505],
            "teaser_box": [0.12, 0.340, 0.88, 0.480],
            "cta_panel": [0.08, 0.610, 0.92, 0.738],
            "cta_box": [0.12, 0.630, 0.88, 0.718],
            "footer_box": [0.08, 0.805, 0.92, 0.930]
        }
    }
}

DEFAULT_STYLE_CONFIG: dict[str, Any] = {
    "说明": "排版表现参数。颜色支持 #RRGGBB、[r,g,b] 或 [r,g,b,a]。scale 表示相对 min(width,height) 的比例。",
    "colors": {
        "cover_episode": [255, 242, 194],
        "cover_book": [227, 186, 96],
        "cover_author": [242, 226, 196],
        "cover_description": [250, 240, 220],
        "brand_name": [236, 198, 116],
        "brand_slogan": [242, 226, 196],
        "end_heading": [235, 188, 95],
        "end_teaser": [248, 238, 218],
        "end_cta": [248, 238, 218],
        "end_brand": [212, 166, 74],
        "end_slogan": [242, 226, 196],
        "end_follow": [248, 238, 218],
        "end_share": [238, 220, 184],
        "separator": [154, 122, 47, 170]
    },
    "text_shadow": {
        "enabled": True,
        "shadow_color": [0, 0, 0, 205],
        "stroke_color": [98, 68, 28, 205],
        "stroke_divisor": 36,
        "offsets": [[-2, -2], [2, -2], [-2, 2], [2, 2], [0, 3]],
        "glow_color": [238, 196, 108, 92],
        "glow_px": 3
    },
    "border": {
        "enabled": True,
        "margin_min_px": 24,
        "margin_max_px": 36,
        "margin_scale": 0.024,
        "inner_gap_scale": 0.012,
        "radius_scale": 0.018,
        "outer_width_scale": 0.0026,
        "outer_color": [212, 166, 74, 220],
        "inner_color": [154, 122, 47, 180],
        "corner_scale": 0.034,
        "corner_step_scale": 0.010
    },
    "cover": {
        "editorial_layout": {
            "enabled": True,
            "vertical_note_title": "",
            "vertical_note_subtitle": "",
            "vertical_note_meta": "",
            "wide_tagline": "",
            "wide_note": "",
            "title_rewrites": [
                {"book_contains": "贫穷", "pattern": "给\\s*100\\s*万.*消灭贫穷", "replacement": "给穷人100万，能消灭贫穷吗？"}
            ],
            "vertical_bg_darken": 0.50,
            "wide_bg_darken": 0.44,
            "bg_blur": 1.0
        },
        "tint": {
            "base_overlay": [5, 4, 4, 80],
            "top_overlay": [0, 0, 0, 80],
            "top_height": 0.25,
            "bottom_overlay": [0, 0, 0, 95],
            "bottom_start": 0.78,
            "soft_box": [0.08, 0.08, 0.92, 0.58],
            "soft_radius_scale": 0.05,
            "soft_alpha": 70,
            "soft_blur_scale": 0.045,
            "soft_blur_min_px": 28
        },
        "grain_opacity": 12,
        "crop": {
            "master_focus_x": 0.50,
            "master_focus_y": 0.50,
            "A1_top_ratio_from_2160x3840": 0.09375,
            "wide_bg_focus_x": 0.50,
            "wide_bg_focus_y": 0.48,
            "wide_bg_blur_scale": 0.018,
            "wide_bg_blur_min_px": 10,
            "A01_fg_height_ratio": 0.96,
            "A02_fg_height_ratio": 0.94,
            "A01_fg_center_x": 0.58,
            "A02_fg_center_x": 0.60,
            "wide_fade_ratio": 0.10,
            "wide_fade_min_px": 24
        },
        "text": {
            "vertical": {"book_max_scale": 0.062, "book_min_scale": 0.030, "author_max_scale": 0.034, "author_min_scale": 0.020, "chapter_no_max_scale": 0.038, "chapter_no_min_scale": 0.018, "chapter_name_max_scale": 0.056, "chapter_name_min_scale": 0.028, "episode_no_max_scale": 0.038, "episode_no_min_scale": 0.018, "episode_name_max_scale": 0.052, "episode_name_min_scale": 0.024, "episode_max_scale": 0.038, "episode_min_scale": 0.018, "title_max_scale": 0.056, "title_min_scale": 0.028, "description_max_scale": 0.052, "description_min_scale": 0.024, "book_max_lines": 1, "author_max_lines": 1, "chapter_no_max_lines": 1, "chapter_name_max_lines": 1, "episode_no_max_lines": 1, "episode_name_max_lines": 1, "episode_max_lines": 1, "title_max_lines": 1, "description_max_lines": 1},
            "wide": {"book_max_scale": 0.052, "book_min_scale": 0.024, "author_max_scale": 0.030, "author_min_scale": 0.018, "chapter_no_max_scale": 0.030, "chapter_no_min_scale": 0.016, "chapter_name_max_scale": 0.044, "chapter_name_min_scale": 0.022, "episode_no_max_scale": 0.030, "episode_no_min_scale": 0.016, "episode_name_max_scale": 0.040, "episode_name_min_scale": 0.019, "episode_max_scale": 0.030, "episode_min_scale": 0.016, "title_max_scale": 0.044, "title_min_scale": 0.022, "description_max_scale": 0.040, "description_min_scale": 0.019, "book_max_lines": 1, "author_max_lines": 1, "chapter_no_max_lines": 1, "chapter_name_max_lines": 1, "episode_no_max_lines": 1, "episode_name_max_lines": 1, "episode_max_lines": 1, "title_max_lines": 1, "description_max_lines": 1}
        },
        "separator": {
            "enabled": True,
            "book_offset_y": 0.010,
            "x1": 0.28,
            "x2": 0.72,
            "color": [154, 122, 47, 170]
        },
        "plates": {
            "enabled": True,
            "fill": [7, 6, 6, 138],
            "subtle_fill": [7, 6, 6, 96],
            "outline": [202, 154, 72, 220],
            "separator": [190, 145, 64, 160],
            "description_fill": [8, 7, 7, 188],
            "description_outline": [212, 166, 74, 225],
            "description_width_px": 2,
            "description_radius_scale": 0.12,
            "book_separator_offset": 0.012,
            "width_px": 2
        }
    },
    "ornaments": {
        "enabled": True,
        "corner_fret": {"enabled": True, "color": [218, 172, 84, 225], "width_px": 2, "size_scale": 0.075},
        "clouds": {"enabled": True, "color": [182, 136, 56, 78], "width_px": 2},
        "dragon_hint": {"enabled": True, "color": [150, 108, 42, 58], "width_px": 2}
    },
    "footer_bar": {
        "fill": [8, 7, 7, 178],
        "outline": [176, 134, 72, 220],
        "width_px": 2,
        "radius_ratio": 0.18,
        "icon_size_ratio": 0.54,
        "icon_x_ratio_vertical": 0.055,
        "icon_x_ratio_wide": 0.05,
        "icon_bg_fill": [247, 242, 230, 235],
        "icon_bg_outline": [184, 144, 86, 235],
        "text_gap_ratio": 0.032,
        "vertical_name_y": 0.14,
        "vertical_slogan_y": 0.57,
        "vertical_name_size_ratio": 0.285,
        "vertical_slogan_size_ratio": 0.145,
        "wide_name_box": [0.08, 0.08, 0.96, 0.42],
        "wide_slogan_box": [0.08, 0.40, 0.96, 0.92],
        "wide_name_max_ratio": 0.235,
        "wide_name_min_ratio": 0.140,
        "wide_slogan_max_ratio": 0.132,
        "wide_slogan_min_ratio": 0.078
    },
    "endcard": {
        "editorial_layout": {
            "enabled": True,
            "next_label": "下一期",
            "teaser_rewrites": [
                {"pattern": "宁可买电视也不吃饱", "replacement": "宁可买电视，也不吃饱？"},
                {"pattern": "宁可买电视，也不吃饱$", "replacement": "宁可买电视，也不吃饱？"}
            ],
            "bg_darken": 0.60,
            "bg_blur": 1.8
        },
        "tint": {
            "base_overlay": [5, 4, 4, 170],
            "soft_ellipse": [0.12, 0.05, 0.88, 0.82],
            "soft_alpha": 70,
            "soft_blur_scale": 0.05,
            "soft_blur_min_px": 30
        },
        "grain_opacity": 10,
        "logo_plate_pad_divisor": 14,
        "logo_plate_outline_width_divisor": 30,
        "logo_plate_fill": [247, 242, 230, 235],
        "logo_plate_outline": [184, 144, 86, 235],
        "heading_panel": {
            "fill": [8, 7, 7, 184],
            "outline": [176, 134, 72, 210],
            "width_px": 2,
            "radius_scale": 0.16
        },
        "panel": {
            "fill": [8, 7, 7, 164],
            "outline": [176, 134, 72, 220],
            "width_px": 2,
            "radius_scale": 0.11
        },
        "text": {
            "heading_max_scale": 0.108,
            "heading_min_scale": 0.055,
            "teaser_max_scale": 0.048,
            "teaser_min_scale": 0.026,
            "cta_max_scale": 0.046,
            "cta_min_scale": 0.024,
            "brand_max_scale": 0.082,
            "brand_min_scale": 0.043,
            "slogan_max_scale": 0.038,
            "slogan_min_scale": 0.022,
            "heading_max_lines": 1,
            "teaser_max_lines": 2,
            "cta_max_lines": 2,
            "brand_max_lines": 1,
            "slogan_max_lines": 1
        },
        "separators": {
            "heading_offset_y": 0.012,
            "heading_x1": 0.30,
            "heading_x2": 0.70,
            "brand_offset_y": 0.010,
            "brand_x1": 0.35,
            "brand_x2": 0.65,
            "color": [154, 122, 47, 140]
        }
    }
}

DEFAULT_GLOBAL_POSTPROCESS_SPEC: dict[str, Any] = {
    "version": 2,
    "说明": "这是全局后处理规范。可在 GUI 的“提示词 / 规范”页面编辑，保存后重跑后处理即可生效。所有排版参数都已外置：封面/片尾/分集封面的坐标、字号、颜色、边框、暗角、裁剪和品牌栏等都能直接修改。",
    "brand": {
        "name": BRAND_NAME,
        "slogan": BRAND_SLOGAN,
        "end_heading": "下集预告",
        "follow_text": DEFAULT_FOLLOW_TEXT,
        "cta_text": DEFAULT_CTA_TEXT,
        "share_text": "下一期内容待更新"
    },
    "assets": {
        "cover_specs": [
            {"asset_id": "A1", "key": "wx_3x4", "label": "微信视频号3:4封面", "size": [1080, 1440], "ratio": [3, 4], "platform": "wechat"},
            {"asset_id": "A2", "key": "wx_9x16", "label": "微信视频号9:16竖版封面", "size": [1080, 1920], "ratio": [9, 16], "platform": "wechat"},
            {"asset_id": "A01", "key": "bili_4x3", "label": "哔哩哔哩4:3封面", "size": [1600, 1200], "ratio": [4, 3], "platform": "bilibili"},
            {"asset_id": "A02", "key": "bili_16x9", "label": "哔哩哔哩16:9封面", "size": [1920, 1080], "ratio": [16, 9], "platform": "bilibili"}
        ],
        "endcard_spec": {"asset_id": "C", "key": "end_9x16", "label": "9:16结尾页", "size": [1080, 1920], "ratio": [9, 16], "platform": "vertical"}
    },
    "layout": deepcopy(DEFAULT_LAYOUT_CONFIG),
    "split_cover_rules": {
        "说明": "拆分分集封面文案规则，已尽量解耦到后处理中。先按 derived_fields 生成书名/作者/章节名/期数/本期标题等逻辑字段，再由 slot_mapping 决定这些字段分别放进哪个版位。可用变量：{episode_label} {part_code} {part_number} {part_episode_label} {chapter_name} {book_title} {author} {theme_full} {theme_body} {description}",
        "derived_fields": {
            "book_name": "{book_title}",
            "author_name": "{author}",
            "chapter_title": "{chapter_name}",
            "period": "{part_episode_label}",
            "current_title": "{theme_body}"
        },
        "slot_mapping": {
            "episode": "period",
            "title": "chapter_title",
            "book": "book_name",
            "author": "author_name",
            "description": "current_title"
        },
        "field_order": ["book_name", "author_name", "chapter_title", "period", "current_title"],
        "strip_part_prefix_in_description": True,
        "episode_template": "{part_episode_label}",
        "title_template": "{chapter_name}",
        "book_template": "{book_title}",
        "author_template": "{author}",
        "description_template": "{description}"
    },
    "style": deepcopy(DEFAULT_STYLE_CONFIG),
    "visual_controls": {
        "preset": "magazine_prime",
        "说明": "A/C 系列图片的可视化后处理控制台参数。GUI 会修改这里；Playwright HTML 模板会真实读取这些值。",
        "background": {
            "brightness": 0.92,
            "saturation": 0.98,
            "contrast": 1.10,
            "blur_px": 3,
            "blur_opacity": 0.24,
            "vignette": 0.34,
            "top_darken": 0.18,
            "bottom_darken": 0.30,
            "focus_x": 50,
            "focus_y": 48
        },
        "glass": {
            "opacity": 0.68,
            "blur_px": 14,
            "radius_px": 28,
            "border_opacity": 0.58,
            "glow": 0.22
        },
        "title": {
            "scale": 1.18,
            "glow": 0.18,
            "stroke": 0.26,
            "letter_spacing": 0.0,
            "max_lines_vertical": 3,
            "max_lines_wide": 3
        },
        "ornaments": {
            "frame": True,
            "corner": False,
            "cloud": False,
            "noise": True,
            "scanline": False,
            "progress_bar": False,
            "particle": False,
            "orb": False
        },
        "composition": {
            "visual_priority": True,
            "wide_text_side": "left",
            "wide_panel_width_pct": 52,
            "vertical_panel_y_pct": 10,
            "vertical_panel_h_pct": 76
        }
    },
    "rendering": {
        "engine": BEST_POSTPROCESS_ENGINE,
        "fallback_engine": "",
        "device_scale_factor": 1.0
    }
}


def _read_json_file(path: Path) -> dict[str, Any]:
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}
    return {}


def _runtime_switch(path: str, default: bool = True) -> bool:
    data = _read_json_file(RUNTIME_SWITCH_PATH)
    cur: Any = data
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return bool(cur)


def _runtime_value(path: str, default: Any = None) -> Any:
    data = _read_json_file(RUNTIME_SWITCH_PATH)
    cur: Any = data
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def _postprocess_engine(config_payload: dict[str, Any] | None = None) -> str:
    return BEST_POSTPROCESS_ENGINE


def _render_with_playwright(kind: str, base_path: Path | None, out_path: Path, meta: dict[str, Any], spec: dict[str, Any], config_payload: dict[str, Any]) -> bool:
    try:
        from .postprocess_playwright import render_cover_with_playwright, render_end_card_with_playwright
    except Exception as exc:
        raise RuntimeError("Playwright/HTML renderer is unavailable; other renderers are disabled.") from exc
    try:
        if kind == "cover":
            render_cover_with_playwright(base_path, out_path, meta, spec, config_payload)
        else:
            render_end_card_with_playwright(base_path, out_path, meta, spec, config_payload)
        return True
    except Exception as exc:
        raise RuntimeError(f"Playwright/HTML {kind} renderer failed for {out_path}; other renderers are disabled.") from exc


def _brand_override_from_copywriting_config() -> dict[str, Any]:
    data = _read_json_file(BRAND_CONFIG_PATH)
    brand = data.get("brand") if isinstance(data.get("brand"), dict) else {}
    if not brand:
        return {}
    out: dict[str, Any] = {"brand": {}}
    if brand.get("name"):
        out["brand"]["name"] = brand.get("name")
    if brand.get("slogan"):
        out["brand"]["slogan"] = brand.get("slogan")
    if brand.get("follow_sentence"):
        out["brand"]["follow_text"] = brand.get("follow_sentence")
    return out


def _deep_merge_config(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge_config(result[key], value)
        else:
            result[key] = value
    return result


def default_global_postprocess_spec_text() -> str:
    return json.dumps(DEFAULT_GLOBAL_POSTPROCESS_SPEC, ensure_ascii=False, indent=2)


def load_global_postprocess_spec(create_if_missing: bool = True) -> dict[str, Any]:
    """加载全局后处理规范。

    优先级：
    1. 程序默认值，只作兜底；
    2. prompts/05_后处理规范.json，主配置；
    3. config/后处理风格覆盖.json，局部覆盖；
    4. config/文案风格配置.json 中的品牌字段。

    因此后续调整排版、颜色、装饰、品牌文案，不需要改 Python。
    """
    if create_if_missing:
        try:
            PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            if not POSTPROCESS_SPEC_PATH.exists():
                POSTPROCESS_SPEC_PATH.write_text(default_global_postprocess_spec_text() + "\n", encoding="utf-8")
        except Exception:
            pass
    result = deepcopy(DEFAULT_GLOBAL_POSTPROCESS_SPEC)
    raw = _read_json_file(POSTPROCESS_SPEC_PATH)
    if raw:
        result = _deep_merge_config(result, raw)
    if _runtime_switch("postprocess.enable_config_override", True):
        override = _read_json_file(POSTPROCESS_OVERRIDE_PATH)
        if override:
            result = _deep_merge_config(result, override)
        brand_override = _brand_override_from_copywriting_config()
        if brand_override:
            result = _deep_merge_config(result, brand_override)
    return result


def _brand_value(config: dict[str, Any], key: str, fallback: str) -> str:
    brand = config.get("brand") if isinstance(config.get("brand"), dict) else {}
    value = str(brand.get(key) or "").strip()
    return value or fallback


def _get_nested(config: dict[str, Any] | None, path: str, default: Any = None) -> Any:
    cur: Any = config or {}
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def _style_config(config_payload: dict[str, Any] | None = None) -> dict[str, Any]:
    style = deepcopy(DEFAULT_STYLE_CONFIG)
    if isinstance(config_payload, dict):
        candidate = config_payload.get("style")
        if isinstance(candidate, dict):
            style = _deep_merge_config(style, candidate)
    else:
        global_spec = load_global_postprocess_spec(create_if_missing=True)
        candidate = global_spec.get("style")
        if isinstance(candidate, dict):
            style = _deep_merge_config(style, candidate)
    return style


def _bounded_number(value: Any, fallback: float, floor: float | None = None, cap: float | None = None) -> float:
    try:
        result = float(value)
    except Exception:
        result = fallback
    if floor is not None:
        result = max(floor, result)
    if cap is not None:
        result = min(cap, result)
    return result


def _visual_controls(config_payload: dict[str, Any] | None = None) -> dict[str, Any]:
    if isinstance(config_payload, dict) and isinstance(config_payload.get("visual_controls"), dict):
        return config_payload["visual_controls"]
    try:
        global_spec = load_global_postprocess_spec(create_if_missing=True)
        vc = global_spec.get("visual_controls") if isinstance(global_spec, dict) else {}
        return vc if isinstance(vc, dict) else {}
    except Exception:
        return {}


def _vc_number(config_payload: dict[str, Any] | None, path: str, fallback: float, floor: float | None = None, cap: float | None = None) -> float:
    return _bounded_number(_get_nested(_visual_controls(config_payload), path, fallback), fallback, floor, cap)


def _vc_bool(config_payload: dict[str, Any] | None, path: str, fallback: bool = False) -> bool:
    value = _get_nested(_visual_controls(config_payload), path, fallback)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "开", "是"}
    return bool(value)


def _rewrite_text_by_rules(text: str, rules: Any, *, book_title: str = "") -> str:
    value = _clean_text(text)
    if not isinstance(rules, list):
        return value
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        book_contains = str(rule.get("book_contains") or "").strip()
        if book_contains and book_contains not in str(book_title or ""):
            continue
        pattern = str(rule.get("pattern") or "").strip()
        replacement = str(rule.get("replacement") or "")
        if not pattern:
            continue
        try:
            value = re.sub(pattern, replacement, value)
        except re.error:
            if pattern in value:
                value = value.replace(pattern, replacement)
    return value


def _color(value: Any, fallback: tuple[int, int, int] | tuple[int, int, int, int]) -> tuple[int, ...]:
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("#") and len(text) in {7, 9}:
            try:
                r = int(text[1:3], 16)
                g = int(text[3:5], 16)
                b = int(text[5:7], 16)
                if len(text) == 9:
                    a = int(text[7:9], 16)
                    return (r, g, b, a)
                return (r, g, b)
            except Exception:
                return fallback
    if isinstance(value, (list, tuple)) and len(value) in {3, 4}:
        try:
            return tuple(max(0, min(255, int(x))) for x in value)
        except Exception:
            return fallback
    return fallback


def _style_color(style: dict[str, Any], key: str, fallback: tuple[int, int, int] | tuple[int, int, int, int]) -> tuple[int, ...]:
    return _color(_get_nested(style, f"colors.{key}"), fallback)


def _style_number(style: dict[str, Any], path: str, fallback: float) -> float:
    value = _get_nested(style, path, fallback)
    try:
        return float(value)
    except Exception:
        return fallback


def _style_int(style: dict[str, Any], path: str, fallback: int) -> int:
    value = _get_nested(style, path, fallback)
    try:
        return int(value)
    except Exception:
        return fallback


def _conf_float(conf: dict[str, Any], key: str, fallback: float, *, cap: float | None = None, floor: float | None = None) -> float:
    try:
        value = float(conf.get(key, fallback))
    except Exception:
        value = fallback
    if cap is not None:
        value = min(value, cap)
    if floor is not None:
        value = max(value, floor)
    return value


COVER_SPECS: list[dict[str, Any]] = [
    {"asset_id": "A1", "key": "wx_3x4", "label": "微信视频号3:4封面", "short_label": "A1_微信3x4", "size": (1080, 1440), "ratio": (3, 4), "platform": "wechat"},
    {"asset_id": "A2", "key": "wx_9x16", "label": "微信视频号9:16竖版封面", "short_label": "A2_微信9x16", "size": (1080, 1920), "ratio": (9, 16), "platform": "wechat"},
    {"asset_id": "A01", "key": "bili_4x3", "label": "哔哩哔哩4:3封面", "short_label": "A01_B站4x3", "size": (1600, 1200), "ratio": (4, 3), "platform": "bilibili"},
    {"asset_id": "A02", "key": "bili_16x9", "label": "哔哩哔哩16:9封面", "short_label": "A02_B站16x9", "size": (1920, 1080), "ratio": (16, 9), "platform": "bilibili"},
]

END_CARD_SPEC: dict[str, Any] = {
    "asset_id": "C",
    "key": "end_9x16",
    "label": "9:16结尾页",
    "short_label": "C_9x16",
    "size": (1080, 1920),
    "ratio": (9, 16),
    "platform": "vertical",
}


def ratio_string(ratio: tuple[int, int]) -> str:
    return f"{ratio[0]}:{ratio[1]}"


def validate_cover_specs() -> list[dict[str, Any]]:
    expected = {
        "A1": {"ratio": (3, 4), "size": (1080, 1440)},
        "A2": {"ratio": (9, 16), "size": (1080, 1920)},
        "A01": {"ratio": (4, 3), "size": (1600, 1200)},
        "A02": {"ratio": (16, 9), "size": (1920, 1080)},
        "C": {"ratio": (9, 16), "size": (1080, 1920)},
    }
    rows: list[dict[str, Any]] = []
    for spec in [*COVER_SPECS, END_CARD_SPEC]:
        asset_id = str(spec.get("asset_id") or "")
        ratio = tuple(spec.get("ratio") or ())
        size = tuple(spec.get("size") or ())
        expected_ratio = expected.get(asset_id, {}).get("ratio", ratio)
        expected_size = expected.get(asset_id, {}).get("size", size)
        ok = ratio == expected_ratio and size == expected_size
        rows.append({
            "asset_id": asset_id,
            "label": spec.get("label"),
            "size": list(size),
            "expected_size": list(expected_size),
            "ratio": ratio_string(ratio),
            "expected_ratio": ratio_string(expected_ratio),
            "ok": ok,
        })
        if not ok:
            raise ValueError(f"规格定义错误：{asset_id} 应为 {expected_size} / {expected_ratio}，当前为 {size} / {ratio}")
    return rows


def _font_candidates(role: str = "body") -> list[str]:
    """Role-aware font fallback.

    标题类文本优先宋体/衬线，正文和品牌副标题优先更干净的无衬线，
    这样能同时兼顾古典气质与阅读清晰度。
    """
    serif = [
        "C:/Windows/Fonts/NotoSerifSC-VF.ttf",
        "C:/Windows/Fonts/Source Han Serif SC Heavy (TrueType).ttf",
        "C:/Windows/Fonts/STZHONGS.TTF",
        "C:/Windows/Fonts/STSONG.TTF",
        "C:/Windows/Fonts/simsun.ttc",
        "C:/Windows/Fonts/FZSTK.TTF",
        "C:/Windows/Fonts/STKAITI.TTF",
        "C:/Windows/Fonts/simkai.ttf",
        "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc",
        "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSerifCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/System/Library/Fonts/Supplemental/Songti.ttc",
        "/System/Library/Fonts/STSong.ttc",
    ]
    sans = [
        "C:/Windows/Fonts/Noto Sans SC Bold (TrueType).otf",
        "C:/Windows/Fonts/Noto Sans SC Medium (TrueType).otf",
        "C:/Windows/Fonts/Noto Sans SC (TrueType).otf",
        "C:/Windows/Fonts/NotoSansSC-VF.ttf",
        "C:/Windows/Fonts/msyhbd.ttc",
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/Dengb.ttf",
        "C:/Windows/Fonts/Deng.ttf",
        "C:/Windows/Fonts/simhei.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
    ]
    role = str(role or "body").lower()
    if role in {"episode", "episode_title", "main", "title", "heading"}:
        return sans + serif
    if role in {"book", "chapter", "brand"}:
        return serif + sans
    if role in {"author", "meta", "slogan", "cta", "teaser", "body"}:
        return sans + serif
    return serif + sans


def _find_font_path(role: str = "body") -> str | None:
    for item in _font_candidates(role):
        if Path(item).exists():
            return item
    return None


_FONT_PATH_CACHE: dict[str, str | None] = {}


def get_font(size: int, role: str = "body") -> ImageFont.ImageFont:
    size = max(12, int(size))
    role = str(role or "body").lower()
    if role not in _FONT_PATH_CACHE:
        _FONT_PATH_CACHE[role] = _find_font_path(role)
    path = _FONT_PATH_CACHE.get(role)
    if path:
        try:
            return ImageFont.truetype(path, size=size)
        except Exception:
            pass
    # Fallback: try body path if role-specific path fails.
    if role != "body":
        if "body" not in _FONT_PATH_CACHE:
            _FONT_PATH_CACHE["body"] = _find_font_path("body")
        body_path = _FONT_PATH_CACHE.get("body")
        if body_path:
            try:
                return ImageFont.truetype(body_path, size=size)
            except Exception:
                pass
    return ImageFont.load_default()


def _clean_text(text: Any) -> str:
    value = str(text or "")
    value = value.replace("　", " ")
    value = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F]", "", value)
    return value.strip()


def _safe_file_component(value: str, fallback: str = "untitled") -> str:
    text = _clean_text(value) or fallback
    text = re.sub(r"[\\/:*?\"<>|\r\n\t]+", "_", text)
    text = re.sub(r"\s+", "_", text).strip("._ ")
    return text[:80] or fallback


def clean_prefix(text: str, prefixes: Iterable[str]) -> str:
    value = _clean_text(text)
    for prefix in prefixes:
        if value.startswith(prefix):
            value = value[len(prefix):].strip()
    return value


def extract_chapter_name(episode_title: str) -> str:
    text = str(episode_title or "").strip()
    text = re.sub(r"^第\s*[0-9一二三四五六七八九十百]+\s*[期集]\s*[：:]\s*", "", text)
    return text or str(episode_title or "").strip()


def _compact_zh_index(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "").strip())


def split_chapter_index_name(text: str, fallback_name: str = "") -> tuple[str, str]:
    """Return (章节序号, 章节名) from strings like 第二章《首辅申时行》."""
    raw = _clean_text(text)
    raw_public = _public_chapter_label(raw) if "_public_chapter_label" in globals() else raw
    patterns = [
        r"(第\s*[0-9一二三四五六七八九十百]+\s*[章节回篇部卷])\s*[：:：、|-]?\s*[《〈]?([^》〉：:|｜\-]*)[》〉]?",
        r"(第\s*[0-9一二三四五六七八九十百]+\s*[章节回篇部卷])\s*[：:：、|-]?\s*(.+)",
    ]
    for pat in patterns:
        m = re.search(pat, raw_public)
        if m:
            idx = _compact_zh_index(m.group(1))
            name = _clean_text(m.group(2)).strip("《》〈〉:：、|- ")
            return idx, _public_chapter_label(name or fallback_name)
    return "", _public_chapter_label(fallback_name or raw_public)


def split_episode_index_name(text: str, fallback_name: str = "") -> tuple[str, str]:
    """Return (集序号, 集名称) from strings like 第三集｜张居正清算余波."""
    raw = _public_chapter_label(_clean_text(text))
    m = re.search(r"(第\s*[0-9一二三四五六七八九十百]+\s*[期集])\s*[：:|｜、-]?\s*(.*)", raw)
    if m:
        idx = _compact_zh_index(m.group(1))
        name = _clean_text(m.group(2)).strip("|｜:：、- ")
        return idx, _public_chapter_label(name or fallback_name)
    return "", _public_chapter_label(fallback_name or raw)


def guess_author_from_filename(filename_stem: str) -> str:
    text = str(filename_stem or "")
    candidates = re.findall(r"[（(]([^()（）]{1,20})[)）]", text)
    if candidates:
        return candidates[-1].strip()
    return ""


def normalize_book_title(title: str) -> str:
    """Clean display-only book title text for AC covers.

    File names often contain author names or edition marks such as
    “（经典版）”“修订版”“精装版”.  These are useful for files, but should
    not be printed on the cover.  Keep the real title, remove decoration.
    """
    text = str(title or "").strip()
    if not text:
        return text
    text = re.sub(r"\.(pdf|epub|mobi|azw3|txt|docx?)$", "", text, flags=re.I).strip()
    # Remove bracketed edition/format decorations wherever they appear.
    edition_words = r"(?:经典|修订|珍藏|纪念|增订|新版|再版|典藏|插图|精装|平装|全译|完整版|无删减|扫描|电子|PDF|EPUB|MOBI)"
    text = re.sub(rf"\s*[（(][^()（）]{{0,30}}{edition_words}[^()（）]{{0,30}}[)）]\s*", "", text, flags=re.I)
    # Remove trailing author/metadata parentheses repeatedly, e.g. “(黄仁宇)”.
    for _ in range(4):
        new_text = re.sub(r"\s*[（(][^()（）]{1,30}[)）]\s*$", "", text).strip()
        if new_text == text:
            break
        text = new_text
    # Remove bare edition suffixes such as “经典版” when they were not bracketed.
    text = re.sub(rf"{edition_words}\s*版", "", text, flags=re.I)
    text = re.sub(r"[_\-—｜|]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" _-—｜|")
    return text.strip()


def _create_placeholder(size: tuple[int, int], title: str = "") -> Image.Image:
    w, h = size
    img = Image.new("RGB", size, (42, 24, 16))
    draw = ImageDraw.Draw(img)
    for y in range(h):
        t = y / max(1, h - 1)
        r = int(28 + 70 * (1 - t))
        g = int(14 + 24 * (1 - t))
        b = int(10 + 16 * (1 - t))
        draw.line((0, y, w, y), fill=(r, g, b))
    glow = Image.new("RGBA", size, (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    gdraw.ellipse((int(w * 0.30), int(h * 0.00), int(w * 1.02), int(h * 0.58)), fill=(230, 138, 42, 70))
    glow = glow.filter(ImageFilter.GaussianBlur(radius=max(20, int(min(size) * 0.07))))
    img = Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB")
    d = ImageDraw.Draw(img)
    base_y = int(h * 0.84)
    for i in range(7):
        x = int(w * 0.03) + i * int(w * 0.12)
        width = int(w * (0.08 + 0.02 * (i % 2)))
        height = int(h * (0.10 + 0.03 * (i % 3)))
        d.rectangle((x, base_y - height, x + width, base_y), fill=(16, 10, 8))
        d.polygon([(x - 8, base_y - height), (x + width // 2, base_y - height - 18), (x + width + 8, base_y - height)], fill=(22, 14, 11))
    if title:
        small = get_font(int(min(size) * 0.05), role="meta")
        d.text((int(w * 0.06), int(h * 0.07)), title[:18], font=small, fill=(140, 110, 90))
    return img


def _load_base(path: Path | None, size: tuple[int, int], title: str = "") -> Image.Image:
    if path and path.exists() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
        try:
            return Image.open(path).convert("RGB")
        except Exception:
            pass
    return _create_placeholder(size, title=title)


def _extract_logo_icon(path: Path | None, size: int) -> Image.Image | None:
    if not path or not path.exists():
        return None
    try:
        src = Image.open(path).convert("RGBA")
    except Exception:
        return None
    px = src.load()
    for y in range(src.size[1]):
        for x in range(src.size[0]):
            r, g, b, a = px[x, y]
            if a < 10:
                continue
            if r > 246 and g > 242 and b > 232:
                px[x, y] = (255, 255, 255, 0)
    bbox = src.getbbox()
    if bbox:
        src = src.crop(bbox)
    out = Image.new("RGBA", (size, size), (255, 255, 255, 0))
    logo = src.copy()
    logo.thumbnail((int(size * 0.84), int(size * 0.84)), Image.Resampling.LANCZOS)
    out.alpha_composite(logo, ((size - logo.width) // 2, (size - logo.height) // 2))
    return out


def _paste_rgba(dst: Image.Image, src: Image.Image, xy: tuple[int, int]) -> None:
    dst.paste(src, xy, src)


def _crop_to_ratio(img: Image.Image, ratio: tuple[int, int], *, focus_y: float = 0.50, focus_x: float = 0.50) -> Image.Image:
    target_ratio = ratio[0] / ratio[1]
    w, h = img.size
    source_ratio = w / h
    if abs(source_ratio - target_ratio) < 1e-6:
        return img.copy()
    if source_ratio > target_ratio:
        new_w = int(h * target_ratio)
        left = int(w * focus_x - new_w / 2)
        left = max(0, min(w - new_w, left))
        return img.crop((left, 0, left + new_w, h))
    new_h = int(w / target_ratio)
    top = int(h * focus_y - new_h / 2)
    top = max(0, min(h - new_h, top))
    return img.crop((0, top, w, top + new_h))


def _fit_vertical_master(img: Image.Image, style: dict[str, Any] | None = None) -> Image.Image:
    """Normalize any generated image to the 9:16 semantic master expected by the template."""
    style = style or DEFAULT_STYLE_CONFIG
    return _crop_to_ratio(
        img,
        (9, 16),
        focus_y=_style_number(style, "cover.crop.master_focus_y", 0.50),
        focus_x=_style_number(style, "cover.crop.master_focus_x", 0.50),
    )


def _fit_image(img: Image.Image, size: tuple[int, int], ratio: tuple[int, int]) -> Image.Image:
    return _crop_to_ratio(img, ratio).resize(size, Image.Resampling.LANCZOS)


def _fit_image_for_asset(img: Image.Image, spec: dict[str, Any], style: dict[str, Any] | None = None) -> Image.Image:
    """Apply production crop rules for A1/A2/A01/A02/C.

    All crop/focus parameters are exposed in prompts/05_后处理规范.json under style.cover.crop.
    """
    style = style or DEFAULT_STYLE_CONFIG
    asset_id = str(spec.get("asset_id") or "")
    size = tuple(spec["size"])
    ratio = tuple(spec["ratio"])
    master = _fit_vertical_master(img, style)
    if asset_id == "A1":
        mw, mh = master.size
        crop_h = int(mw * 4 / 3)
        top_ratio = _style_number(style, "cover.crop.A1_top_ratio_from_2160x3840", 360 / 3840)
        top = int(mh * top_ratio)
        if top + crop_h > mh:
            top = max(0, mh - crop_h)
        return master.crop((0, top, mw, top + crop_h)).resize(size, Image.Resampling.LANCZOS)
    if asset_id in {"A2", "C"}:
        return master.resize(size, Image.Resampling.LANCZOS)
    if asset_id in {"A01", "A02"}:
        w, h = size
        bg = _crop_to_ratio(
            master,
            ratio,
            focus_y=_style_number(style, "cover.crop.wide_bg_focus_y", 0.48),
            focus_x=_style_number(style, "cover.crop.wide_bg_focus_x", 0.50),
        ).resize(size, Image.Resampling.LANCZOS)
        blur = max(
            _style_int(style, "cover.crop.wide_bg_blur_min_px", 10),
            int(min(size) * _style_number(style, "cover.crop.wide_bg_blur_scale", 0.018)),
        )
        bg = bg.filter(ImageFilter.GaussianBlur(radius=blur)).convert("RGBA")
        fg_h_ratio = _style_number(style, f"cover.crop.{asset_id}_fg_height_ratio", 0.94 if asset_id == "A02" else 0.96)
        fg_h = int(h * fg_h_ratio)
        fg_w = int(fg_h * 9 / 16)
        fg = master.resize((fg_w, fg_h), Image.Resampling.LANCZOS).convert("RGBA")
        center_x = _style_number(style, f"cover.crop.{asset_id}_fg_center_x", 0.60 if asset_id == "A02" else 0.58)
        x = int(w * center_x - fg_w / 2)
        y = (h - fg_h) // 2
        mask = Image.new("L", (fg_w, fg_h), 255)
        fade_w = max(
            _style_int(style, "cover.crop.wide_fade_min_px", 24),
            int(fg_w * _style_number(style, "cover.crop.wide_fade_ratio", 0.10)),
        )
        md = ImageDraw.Draw(mask)
        for i in range(fade_w):
            alpha = int(255 * i / max(1, fade_w))
            md.line((i, 0, i, fg_h), fill=alpha)
        bg.paste(fg, (x, y), mask)
        return bg.convert("RGB")
    return _fit_image(img, size, ratio)


def _text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, spacing: int | None = None) -> tuple[int, int]:
    if not text:
        return (0, 0)
    spacing = spacing if spacing is not None else max(4, getattr(font, "size", 24) // 5)
    bbox = draw.multiline_textbbox((0, 0), text, font=font, spacing=spacing, align="center")
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


_LINE_START_FORBIDDEN = set("，。！？；：、,.!?;:)]）】》」』…")
_LINE_END_FORBIDDEN = set("([{（【《「『")


def _tidy_line_breaks(lines: list[str]) -> list[str]:
    """Avoid Chinese punctuation or closing marks at the beginning of a wrapped line."""
    lines = [str(x or "") for x in lines if str(x or "")]
    if len(lines) <= 1:
        return lines
    for i in range(1, len(lines)):
        while lines[i] and lines[i][0] in _LINE_START_FORBIDDEN and lines[i - 1]:
            lines[i - 1] += lines[i][0]
            lines[i] = lines[i][1:]
        while lines[i - 1] and lines[i - 1][-1] in _LINE_END_FORBIDDEN and lines[i]:
            lines[i] = lines[i - 1][-1] + lines[i]
            lines[i - 1] = lines[i - 1][:-1]
    return [x for x in lines if x]


def _smart_wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int, max_lines: int = 2) -> str:
    text = _clean_text(text)
    if not text:
        return ""
    text = re.sub(r"\s+", "", text)
    # AC cover titles are now single-line by default.  For max_lines <= 1,
    # never add ellipsis and never insert line breaks; _fit_text will keep
    # shrinking the font until the full title fits the box.
    if max_lines <= 1:
        return text
    if _text_size(draw, text, font)[0] <= max_width:
        return text

    # Prefer semantic separators; keep punctuation at the end of the previous line.
    for sep in ["｜", "|", "，", "、", "：", ":", "；", ";", "。", "？", "?", "！", "!", "—", "-"]:
        if sep in text:
            idx = text.find(sep)
            if 0 < idx < len(text) - 1:
                cut = idx + 1 if sep in _LINE_START_FORBIDDEN or sep in "｜|，、：:；;。？?！!" else idx
                candidate_lines = _tidy_line_breaks([text[:cut], text[cut:]])
                if len(candidate_lines) <= max_lines and all(_text_size(draw, line, font)[0] <= max_width for line in candidate_lines):
                    return "\n".join(candidate_lines)

    # Find the most balanced visual break, avoiding forbidden punctuation starts.
    best: tuple[int, int] | None = None
    start_i = max(2, len(text) // 3)
    end_i = min(len(text) - 1, len(text) * 2 // 3)
    for i in range(start_i, end_i + 1):
        if text[i] in _LINE_START_FORBIDDEN or text[i - 1] in _LINE_END_FORBIDDEN:
            continue
        left, right = text[:i], text[i:]
        w1 = _text_size(draw, left, font)[0]
        w2 = _text_size(draw, right, font)[0]
        if w1 <= max_width and w2 <= max_width:
            score = abs(w1 - w2)
            if best is None or score < best[0]:
                best = (score, i)
    if best:
        i = best[1]
        return "\n".join(_tidy_line_breaks([text[:i], text[i:]]))

    # Greedy fallback with punctuation repair.  Multi-line non-cover texts may
    # still use ellipsis as a last resort; cover title slots are configured to
    # one line and do not enter this branch.
    lines: list[str] = []
    cur = ""
    for ch in text:
        probe = cur + ch
        if cur and _text_size(draw, probe, font)[0] > max_width:
            lines.append(cur)
            cur = ch
            if len(lines) >= max_lines:
                break
        else:
            cur = probe
    if cur and len(lines) < max_lines:
        lines.append(cur)
    lines = _tidy_line_breaks(lines)
    if len("".join(lines)) < len(text) and lines:
        last = lines[-1]
        while len(last) > 1 and _text_size(draw, last + "…", font)[0] > max_width:
            last = last[:-1]
        lines[-1] = last + "…"
    return "\n".join(lines[:max_lines])
def _fit_text(draw: ImageDraw.ImageDraw, text: str, box: tuple[int, int, int, int], max_size: int, min_size: int, max_lines: int = 2, font_role: str = "body") -> tuple[ImageFont.ImageFont, str, int]:
    x1, y1, x2, y2 = box
    max_width = max(20, x2 - x1)
    max_height = max(20, y2 - y1)
    max_size = max(10, int(max_size))
    min_size = max(6, min(int(min_size), max_size))
    clean = _clean_text(text)

    # Single-line AC title mode: full text only, no wrap, no ellipsis.
    # Continue below the configured minimum if needed so long book names remain complete.
    if max_lines <= 1:
        single = re.sub(r"\s+", "", clean)
        absolute_floor = 6
        for size in range(max_size, absolute_floor - 1, -1):
            font = get_font(size, role=font_role)
            spacing = max(1, size // 8)
            w, h = _text_size(draw, single, font, spacing)
            if w <= max_width and h <= max_height:
                return font, single, spacing
        font = get_font(absolute_floor, role=font_role)
        return font, single, max(1, absolute_floor // 8)

    # First pass: normal configured range.
    for size in range(max_size, min_size - 1, -2):
        font = get_font(size, role=font_role)
        wrapped = _smart_wrap(draw, clean, font, max_width, max_lines=max_lines)
        spacing = max(3, size // 6)
        w, h = _text_size(draw, wrapped, font, spacing)
        if w <= max_width and h <= max_height:
            return font, wrapped, spacing
    # Safety pass: if the configured min size is still too large, keep shrinking.
    safety_floor = max(8, min_size // 2)
    for size in range(min_size - 2, safety_floor - 1, -2):
        font = get_font(size, role=font_role)
        wrapped = _smart_wrap(draw, clean, font, max_width, max_lines=max_lines)
        spacing = max(2, size // 7)
        w, h = _text_size(draw, wrapped, font, spacing)
        if w <= max_width and h <= max_height:
            return font, wrapped, spacing
    font = get_font(safety_floor, role=font_role)
    wrapped = _smart_wrap(draw, clean, font, max_width, max_lines=max_lines)
    return font, wrapped, max(2, safety_floor // 7)
def _draw_text_with_shadow(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, font: ImageFont.ImageFont, fill: tuple[int, ...], spacing: int = 8, anchor: str | None = None, align: str = "center", stroke: int | None = None, style: dict[str, Any] | None = None) -> None:
    x, y = xy
    style = style or DEFAULT_STYLE_CONFIG
    shadow_conf = _get_nested(style, "text_shadow", {})
    shadow_enabled = bool(shadow_conf.get("enabled", True)) if isinstance(shadow_conf, dict) else True
    shadow_fill = _color(_get_nested(style, "text_shadow.shadow_color"), (0, 0, 0, 190))
    offsets = _get_nested(style, "text_shadow.offsets", [[-2, -2], [2, -2], [-2, 2], [2, 2], [0, 3]])
    # 金色标题外发光，接近样例中的金属字质感。
    glow_fill = _color(_get_nested(style, "text_shadow.glow_color"), (216, 166, 72, 80))
    glow_radius = max(0, _style_int(style, "text_shadow.glow_px", 2))
    if glow_radius > 0:
        for dx, dy in [(-glow_radius, 0), (glow_radius, 0), (0, -glow_radius), (0, glow_radius)]:
            draw.multiline_text((x + dx, y + dy), text, font=font, fill=glow_fill, spacing=spacing, anchor=anchor, align=align)
    if shadow_enabled and isinstance(offsets, list):
        for item in offsets:
            try:
                dx, dy = int(item[0]), int(item[1])
            except Exception:
                continue
            draw.multiline_text((x + dx, y + dy), text, font=font, fill=shadow_fill, spacing=spacing, anchor=anchor, align=align)
    stroke_divisor = max(1, _style_int(style, "text_shadow.stroke_divisor", 36))
    stroke_width = stroke if stroke is not None else (0 if stroke_divisor >= 9999 else max(1, getattr(font, "size", 24) // stroke_divisor))
    stroke_fill = _color(_get_nested(style, "text_shadow.stroke_color"), (80, 58, 24, 190))
    draw.multiline_text((x, y), text, font=font, fill=fill, spacing=spacing, anchor=anchor, align=align, stroke_width=stroke_width, stroke_fill=stroke_fill)


def _render_single_line_to_box(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    box: tuple[int, int, int, int],
    *,
    fill: tuple[int, ...],
    spacing: int,
    align: str = "center",
    style: dict[str, Any] | None = None,
) -> bool:
    """Draw a one-line title without overflow.

    For unusually long book/chapter/episode names, font shrinking may still not
    fit inside narrow A01/A02 boxes.  In that case we render the full text on a
    transparent layer and horizontally condense that layer to the target box.
    This preserves every character, keeps one line, and avoids ellipsis/overflow.
    """
    if not text or "\n" in text:
        return False
    max_width = max(1, box[2] - box[0])
    max_height = max(1, box[3] - box[1])
    tw, th = _text_size(draw, text, font, spacing)
    if tw <= max_width and th <= max_height:
        return False
    pad = max(8, int(getattr(font, "size", 24) * 0.35))
    layer_w = max(1, tw + pad * 2)
    layer_h = max(1, th + pad * 2)
    layer = Image.new("RGBA", (layer_w, layer_h), (255, 255, 255, 0))
    ldraw = ImageDraw.Draw(layer)
    _draw_text_with_shadow(
        ldraw,
        (pad + tw // 2, pad),
        text,
        font,
        fill,
        spacing=spacing,
        anchor="ma",
        align="center",
        style=style,
    )
    bbox = layer.getbbox()
    if bbox:
        layer = layer.crop(bbox)
    lw, lh = layer.size
    if lw <= 0 or lh <= 0:
        return True
    scale = min(max_width / lw, max_height / lh, 1.0)
    target_w = max(1, int(lw * scale))
    target_h = max(1, int(lh * scale))
    if target_w > max_width:
        target_w = max_width
    if target_h > max_height:
        target_h = max_height
    if (target_w, target_h) != layer.size:
        layer = layer.resize((target_w, target_h), Image.Resampling.LANCZOS)
    if align == "left":
        x = box[0]
    else:
        x = box[0] + (max_width - target_w) // 2
    y = box[1] + (max_height - target_h) // 2
    base_img = getattr(draw, "_image", None) or getattr(draw, "im", None)
    try:
        draw.bitmap((x, y), layer, fill=None)
    except Exception:
        # Fallback for Pillow builds where ImageDraw cannot paste RGBA directly.
        if hasattr(draw, "_image"):
            draw._image.alpha_composite(layer, (x, y))  # type: ignore[attr-defined]
        else:
            draw.bitmap((x, y), layer, fill=None)
    return True


def _draw_centered(draw: ImageDraw.ImageDraw, text: str, box: tuple[int, int, int, int], *, fill: tuple[int, ...], max_size: int, min_size: int, max_lines: int = 2, style: dict[str, Any] | None = None, font_role: str = "body") -> str:
    font, wrapped, spacing = _fit_text(draw, text, box, max_size=max_size, min_size=min_size, max_lines=max_lines, font_role=font_role)
    if max_lines <= 1 and _render_single_line_to_box(draw, wrapped, font, box, fill=fill, spacing=spacing, align="center", style=style):
        return wrapped
    tw, th = _text_size(draw, wrapped, font, spacing)
    x = (box[0] + box[2]) // 2
    y = box[1] + max(0, (box[3] - box[1] - th) // 2)
    _draw_text_with_shadow(draw, (x, y), wrapped, font, fill, spacing=spacing, anchor="ma", align="center", style=style)
    return wrapped


def _draw_left(draw: ImageDraw.ImageDraw, text: str, box: tuple[int, int, int, int], *, fill: tuple[int, ...], max_size: int, min_size: int, max_lines: int = 2, style: dict[str, Any] | None = None, font_role: str = "body") -> str:
    font, wrapped, spacing = _fit_text(draw, text, box, max_size=max_size, min_size=min_size, max_lines=max_lines, font_role=font_role)
    if max_lines <= 1 and _render_single_line_to_box(draw, wrapped, font, box, fill=fill, spacing=spacing, align="left", style=style):
        return wrapped
    tw, th = _text_size(draw, wrapped, font, spacing)
    x = box[0]
    y = box[1] + max(0, (box[3] - box[1] - th) // 2)
    _draw_text_with_shadow(draw, (x, y), wrapped, font, fill, spacing=spacing, anchor="la", align="left", style=style)
    return wrapped


def _draw_border(draw: ImageDraw.ImageDraw, w: int, h: int, style: dict[str, Any] | None = None) -> None:
    style = style or DEFAULT_STYLE_CONFIG
    if not bool(_get_nested(style, "border.enabled", True)):
        return
    # Keep border 24-36px from the edge by default; all values can be changed in 后处理规范.json.
    m1 = max(
        _style_int(style, "border.margin_min_px", 24),
        min(_style_int(style, "border.margin_max_px", 36), int(min(w, h) * _style_number(style, "border.margin_scale", 0.024))),
    )
    m2 = m1 + max(8, int(min(w, h) * _style_number(style, "border.inner_gap_scale", 0.012)))
    gold = _color(_get_nested(style, "border.outer_color"), (212, 166, 74, 220))
    gold2 = _color(_get_nested(style, "border.inner_color"), (154, 122, 47, 180))
    draw.rounded_rectangle(
        (m1, m1, w - m1, h - m1),
        radius=max(12, int(min(w, h) * _style_number(style, "border.radius_scale", 0.018))),
        outline=gold,
        width=max(2, int(min(w, h) * _style_number(style, "border.outer_width_scale", 0.0026))),
    )
    draw.rectangle((m2, m2, w - m2, h - m2), outline=gold2, width=1)
    corner = int(min(w, h) * _style_number(style, "border.corner_scale", 0.034))
    step = max(8, int(min(w, h) * _style_number(style, "border.corner_step_scale", 0.010)))
    for x, y, sx, sy in [(m1, m1, 1, 1), (w - m1, m1, -1, 1), (m1, h - m1, 1, -1), (w - m1, h - m1, -1, -1)]:
        draw.line((x, y + sy * corner, x, y), fill=gold, width=2)
        draw.line((x, y, x + sx * corner, y), fill=gold, width=2)
        draw.line((x + sx * step, y + sy * corner, x + sx * step, y + sy * step), fill=gold2, width=1)
        draw.line((x + sx * step, y + sy * step, x + sx * corner, y + sy * step), fill=gold2, width=1)


def _apply_cover_tint(img: Image.Image, style: dict[str, Any] | None = None) -> Image.Image:
    style = style or DEFAULT_STYLE_CONFIG
    base = img.convert("RGBA")
    w, h = base.size
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    d.rectangle((0, 0, w, h), fill=_color(_get_nested(style, "cover.tint.base_overlay"), (5, 4, 4, 80)))
    d.rectangle((0, 0, w, int(h * _style_number(style, "cover.tint.top_height", 0.25))), fill=_color(_get_nested(style, "cover.tint.top_overlay"), (0, 0, 0, 80)))
    d.rectangle((0, int(h * _style_number(style, "cover.tint.bottom_start", 0.78)), w, h), fill=_color(_get_nested(style, "cover.tint.bottom_overlay"), (0, 0, 0, 95)))
    # Soft central readability field, not a hard black panel.
    soft = Image.new("L", base.size, 0)
    sd = ImageDraw.Draw(soft)
    soft_box = _get_nested(style, "cover.tint.soft_box", [0.08, 0.08, 0.92, 0.58])
    try:
        sx1, sy1, sx2, sy2 = [float(x) for x in soft_box]
    except Exception:
        sx1, sy1, sx2, sy2 = 0.08, 0.08, 0.92, 0.58
    sd.rounded_rectangle((int(w*sx1), int(h*sy1), int(w*sx2), int(h*sy2)), radius=int(min(w,h)*_style_number(style, "cover.tint.soft_radius_scale", 0.05)), fill=_style_int(style, "cover.tint.soft_alpha", 70))
    soft = soft.filter(ImageFilter.GaussianBlur(radius=max(_style_int(style, "cover.tint.soft_blur_min_px", 28), int(min(w, h) * _style_number(style, "cover.tint.soft_blur_scale", 0.045)))))
    tint = Image.new("RGBA", base.size, (0, 0, 0, 0))
    tint.putalpha(soft)
    return Image.alpha_composite(Image.alpha_composite(base, overlay), tint)


def _apply_end_tint(img: Image.Image, style: dict[str, Any] | None = None) -> Image.Image:
    style = style or DEFAULT_STYLE_CONFIG
    base = img.convert("RGBA")
    w, h = base.size
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    d.rectangle((0, 0, w, h), fill=_color(_get_nested(style, "endcard.tint.base_overlay"), (5, 4, 4, 110)))
    soft = Image.new("L", base.size, 0)
    sd = ImageDraw.Draw(soft)
    ellipse = _get_nested(style, "endcard.tint.soft_ellipse", [0.12, 0.05, 0.88, 0.82])
    try:
        ex1, ey1, ex2, ey2 = [float(x) for x in ellipse]
    except Exception:
        ex1, ey1, ex2, ey2 = 0.12, 0.05, 0.88, 0.82
    sd.ellipse((int(w*ex1), int(h*ey1), int(w*ex2), int(h*ey2)), fill=_style_int(style, "endcard.tint.soft_alpha", 70))
    soft = soft.filter(ImageFilter.GaussianBlur(radius=max(_style_int(style, "endcard.tint.soft_blur_min_px", 30), int(min(w, h) * _style_number(style, "endcard.tint.soft_blur_scale", 0.05)))))
    tint = Image.new("RGBA", base.size, (0, 0, 0, 0))
    tint.putalpha(soft)
    return Image.alpha_composite(Image.alpha_composite(base, overlay), tint)


def _add_subtle_grain(img: Image.Image, opacity: int = 16) -> Image.Image:
    base = img.convert("RGBA")
    noise = Image.effect_noise(base.size, 18).convert("L")
    alpha = noise.point(lambda p: opacity if p > 132 else 0)
    grain = Image.new("RGBA", base.size, (255, 242, 194, 0))
    grain.putalpha(alpha)
    return Image.alpha_composite(base, grain)


def _draw_separator(draw: ImageDraw.ImageDraw, y: int, x1: int, x2: int, color=(180, 137, 76, 175)) -> None:
    if x2 <= x1:
        return
    draw.line((x1, y, x2, y), fill=color, width=2)
    cx = (x1 + x2) // 2
    draw.ellipse((cx - 4, y - 4, cx + 4, y + 4), fill=(210, 170, 110, 230))


def _draw_deco_separator(draw: ImageDraw.ImageDraw, y: int, x1: int, x2: int, *, color=(190, 145, 64, 190), width: int = 2) -> None:
    """高保真金色分隔线：两端细线，中间菱形花结。"""
    if x2 <= x1:
        return
    cx = (x1 + x2) // 2
    gap = max(22, (x2 - x1) // 40)
    draw.line((x1, y, cx - gap, y), fill=color, width=width)
    draw.line((cx + gap, y, x2, y), fill=color, width=width)
    r = max(5, width * 3)
    bright = (238, 194, 95, min(255, color[3] + 35 if len(color) > 3 else 235))
    pts = [(cx, y - r), (cx + r, y), (cx, y + r), (cx - r, y)]
    draw.polygon(pts, outline=bright, fill=(20, 14, 8, 120))
    rr = max(2, r // 2)
    for dx in [-gap - rr * 2, gap + rr * 2]:
        draw.ellipse((cx + dx - rr, y - rr, cx + dx + rr, y + rr), outline=color, width=max(1, width - 1))


def _draw_plaque_frame(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], *, color=(196, 150, 70, 220), fill=(8, 7, 7, 120), width: int = 2, radius: int | None = None, ornate: bool = True) -> None:
    """牌匾式文本框，带角花和侧边菱形。"""
    x1, y1, x2, y2 = box
    if x2 <= x1 or y2 <= y1:
        return
    h = y2 - y1
    w = x2 - x1
    radius = radius if radius is not None else max(10, h // 7)
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=color, width=width)
    inner = max(5, h // 12)
    c2 = (132, 98, 42, 150)
    draw.rounded_rectangle((x1 + inner, y1 + inner, x2 - inner, y2 - inner), radius=max(6, radius - inner), outline=c2, width=1)
    if not ornate:
        return
    l = max(12, min(w, h) // 4)
    # 四角折线
    for sx, sy, ax, ay in [(1,1,x1,y1),(-1,1,x2,y1),(1,-1,x1,y2),(-1,-1,x2,y2)]:
        draw.line((ax, ay + sy*l, ax, ay + sy*inner, ax + sx*inner, ay + sy*inner), fill=color, width=width)
        draw.line((ax + sx*l, ay, ax + sx*inner, ay, ax + sx*inner, ay + sy*inner), fill=color, width=width)
    # 左右小耳朵
    cy = (y1 + y2) // 2
    r = max(4, h // 11)
    for x, sgn in [(x1, -1), (x2, 1)]:
        pts = [(x, cy - r), (x + sgn*r, cy), (x, cy + r)]
        draw.line(pts, fill=color, width=width)


def _draw_corner_fret(draw: ImageDraw.ImageDraw, w: int, h: int, style: dict[str, Any] | None = None) -> None:
    """绘制更接近样例的四角回纹角花。"""
    style = style or DEFAULT_STYLE_CONFIG
    if not bool(_get_nested(style, "ornaments.corner_fret.enabled", True)):
        return
    m = max(20, int(min(w, h) * _style_number(style, "border.margin_scale", 0.024)))
    color = _color(_get_nested(style, "ornaments.corner_fret.color"), (212, 166, 74, 205))
    width = max(1, _style_int(style, "ornaments.corner_fret.width_px", 2))
    size = max(42, int(min(w, h) * _style_number(style, "ornaments.corner_fret.size_scale", 0.072)))
    step = max(10, size // 5)
    pattern = [(0,0),(size,0),(size,step),(step,step),(step,size),(0,size),(0,0),(size//2,0),(size//2,step*2),(size-step,step*2),(size-step,size-step),(step*2,size-step),(step*2,size//2),(0,size//2)]
    def transform(pt, corner):
        x,y=pt
        if corner==0: return (m+x, m+y)
        if corner==1: return (w-m-x, m+y)
        if corner==2: return (m+x, h-m-y)
        return (w-m-x, h-m-y)
    for c in range(4):
        pts=[transform(pt,c) for pt in pattern]
        draw.line(pts, fill=color, width=width, joint="curve")
        # 小圆点/云勾
        px, py = transform((size//2, size//2), c)
        r=max(3, step//4)
        draw.ellipse((px-r,py-r,px+r,py+r), outline=color, width=width)


def _draw_cloud_pattern(draw: ImageDraw.ImageDraw, w: int, h: int, *, area: str = "cover", style: dict[str, Any] | None = None) -> None:
    """程序化云纹暗纹。不会覆盖主体，只在边缘与暗部制造装饰层。"""
    style = style or DEFAULT_STYLE_CONFIG
    if not bool(_get_nested(style, "ornaments.clouds.enabled", True)):
        return
    color = _color(_get_nested(style, "ornaments.clouds.color"), (172, 126, 48, 70))
    width = max(1, _style_int(style, "ornaments.clouds.width_px", 2))
    scale = min(w, h)
    bands = [(0.07, 0.15), (0.82, 0.91)] if area == "cover" else [(0.08, 0.20), (0.73, 0.88)]
    for bi, (ys, ye) in enumerate(bands):
        ybase = int(h * ys)
        band_h = int(h * (ye - ys))
        count = 7 if w > h else 5
        for i in range(count):
            x = int(w * (0.05 + i * 0.16)) + ((bi % 2) * int(w * 0.04))
            y = ybase + int((i % 3) * band_h * 0.22)
            r = int(scale * (0.018 + (i % 3) * 0.006))
            # 连续 C 形云勾
            draw.arc((x, y, x + 2*r, y + 2*r), 180, 360, fill=color, width=width)
            draw.arc((x + r, y - r//2, x + 3*r, y + 3*r//2), 180, 360, fill=color, width=width)
            draw.arc((x + 2*r, y, x + 4*r, y + 2*r), 180, 330, fill=color, width=width)
            draw.line((x, y + r, x - r, y + r), fill=color, width=width)
            draw.line((x + 4*r, y + r, x + 5*r, y + r), fill=color, width=width)


def _draw_side_dragon_hint(draw: ImageDraw.ImageDraw, w: int, h: int, style: dict[str, Any] | None = None) -> None:
    """低调龙纹/卷草暗纹，用线条暗示，不生成具象文字。"""
    style = style or DEFAULT_STYLE_CONFIG
    if not bool(_get_nested(style, "ornaments.dragon_hint.enabled", True)):
        return
    color = _color(_get_nested(style, "ornaments.dragon_hint.color"), (150, 108, 42, 65))
    width = max(1, _style_int(style, "ornaments.dragon_hint.width_px", 2))
    for side in [0, 1]:
        x0 = int(w * (0.035 if side == 0 else 0.965))
        sgn = 1 if side == 0 else -1
        y0 = int(h * 0.18)
        for k in range(3):
            y = y0 + int(h * 0.18 * k)
            pts=[]
            for t in range(0, 120, 4):
                a=t/18.0
                x=x0 + sgn*int(math.sin(a)*w*0.018 + t*w*0.00035)
                yy=y + int(math.cos(a*0.8)*h*0.012 + t*h*0.0010)
                pts.append((x,yy))
            if len(pts)>1:
                draw.line(pts, fill=color, width=width)


def _draw_ornaments(draw: ImageDraw.ImageDraw, w: int, h: int, style: dict[str, Any] | None = None, *, area: str = "cover") -> None:
    style = style or DEFAULT_STYLE_CONFIG
    if not _runtime_switch("postprocess.enable_high_fidelity_ornaments", True):
        return
    if not bool(_get_nested(style, "ornaments.enabled", True)):
        return
    _draw_cloud_pattern(draw, w, h, area=area, style=style)
    _draw_side_dragon_hint(draw, w, h, style=style)
    _draw_corner_fret(draw, w, h, style=style)


def _draw_cover_text_plate(draw: ImageDraw.ImageDraw, img: Image.Image, spec: dict[str, Any], boxes: dict[str, tuple[int, int, int, int]], style: dict[str, Any] | None = None) -> None:
    """高保真封面文字承载结构：按书名→作者→章节→集信息→品牌的顺序承托文字。"""
    style = style or DEFAULT_STYLE_CONFIG
    if not bool(_get_nested(style, "cover.plates.enabled", True)):
        return
    w, h = img.size
    gold = _color(_get_nested(style, "cover.plates.outline"), (202, 154, 72, 220))
    subtle = _color(_get_nested(style, "cover.plates.subtle_fill"), (7, 6, 6, 82))
    width = _style_int(style, "cover.plates.width_px", 2)
    book_box = boxes.get("book_box")
    if book_box:
        x1, y1, x2, y2 = book_box
        pad_x = int(w * 0.010)
        pad_y = int(h * 0.008)
        _draw_plaque_frame(draw, (max(0, x1 - pad_x), max(0, y1 - pad_y), min(w, x2 + pad_x), min(h, y2 + pad_y)), color=gold, fill=subtle, width=max(1, width - 1), ornate=True)
        _draw_deco_separator(draw, book_box[3] + int(h * _style_number(style, "cover.plates.book_separator_offset", 0.012)), int(w * 0.28), int(w * 0.72), color=_color(_get_nested(style, "cover.plates.separator"), (190, 145, 64, 160)), width=max(1, width))
    def panel_for(key: str, *, strong: bool = False) -> None:
        box = boxes.get(key)
        if not box:
            return
        x1, y1, x2, y2 = box
        radius = max(12, int(min(x2 - x1, y2 - y1) * _style_number(style, "cover.plates.description_radius_scale", 0.14)))
        fill = _color(_get_nested(style, "cover.plates.description_fill" if strong else "cover.plates.subtle_fill"), (8, 7, 7, 150 if strong else 96))
        outline = _color(_get_nested(style, "cover.plates.description_outline"), (212, 166, 74, 210))
        outline_to_use = outline if strong else _color(_get_nested(style, "cover.plates.outline"), (202, 154, 72, 175))
        width_to_use = max(1, _style_int(style, "cover.plates.description_width_px", 2)) if strong else max(1, _style_int(style, "cover.plates.width_px", 2) - 1)
        draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline_to_use, width=width_to_use)
    # Draw the large title panels first, then the small numbered chips on top.
    panel_for("chapter_name_box", strong=True)
    panel_for("episode_name_box", strong=True)
    panel_for("chapter_no_box", strong=False)
    panel_for("episode_no_box", strong=False)

def _draw_footer_bar(draw: ImageDraw.ImageDraw, img: Image.Image, box: tuple[int, int, int, int], *, wide: bool = False, brand_name: str = BRAND_NAME, brand_slogan: str = BRAND_SLOGAN, style: dict[str, Any] | None = None) -> None:
    style = style or DEFAULT_STYLE_CONFIG
    brand_label = _brand_display_name(brand_name)
    x1, y1, x2, y2 = box
    bar_h = y2 - y1
    bar_w = x2 - x1
    draw.rounded_rectangle(
        box,
        radius=max(12, int(bar_h * _style_number(style, "footer_bar.radius_ratio", 0.18))),
        fill=_color(_get_nested(style, "footer_bar.fill"), (8, 7, 7, 178)),
        outline=_color(_get_nested(style, "footer_bar.outline"), (176, 134, 72, 220)),
        width=_style_int(style, "footer_bar.width_px", 2),
    )
    icon_size = int(bar_h * _style_number(style, "footer_bar.icon_size_ratio", 0.56))
    icon = _extract_logo_icon(BRAND_LOGO_PATH, icon_size)
    icon_x_ratio = _style_number(style, "footer_bar.icon_x_ratio_wide" if wide else "footer_bar.icon_x_ratio_vertical", 0.05 if wide else 0.055)
    icon_x = x1 + int(bar_w * icon_x_ratio)
    icon_y = y1 + (bar_h - icon_size) // 2
    if icon is not None:
        draw.ellipse(
            (icon_x - 4, icon_y - 4, icon_x + icon_size + 4, icon_y + icon_size + 4),
            fill=_color(_get_nested(style, "footer_bar.icon_bg_fill"), (247, 242, 230, 235)),
            outline=_color(_get_nested(style, "footer_bar.icon_bg_outline"), (184, 144, 86, 235)),
            width=2,
        )
        _paste_rgba(img, icon, (icon_x, icon_y))
    text_left = icon_x + icon_size + int(bar_w * _style_number(style, "footer_bar.text_gap_ratio", 0.035))
    name_font = get_font(int(bar_h * _style_number(style, "footer_bar.vertical_name_size_ratio", 0.31)), role="brand")
    slogan_font = get_font(int(bar_h * _style_number(style, "footer_bar.vertical_slogan_size_ratio", 0.155)), role="slogan")
    brand_fill = _style_color(style, "brand_name", (230, 193, 118))
    slogan_fill = _style_color(style, "brand_slogan", (242, 226, 196))
    if wide:
        # B站角标区域较窄，采用上下两行，避免 slogan 被裁断。
        nb = _get_nested(style, "footer_bar.wide_name_box", [0.08, 0.08, 0.96, 0.42])
        sb = _get_nested(style, "footer_bar.wide_slogan_box", [0.08, 0.40, 0.96, 0.92])
        name_box = (text_left, y1 + int(bar_h * float(nb[1])), x2 - int(bar_w * (1 - float(nb[2]))), y1 + int(bar_h * float(nb[3])))
        slogan_box = (text_left, y1 + int(bar_h * float(sb[1])), x2 - int(bar_w * (1 - float(sb[2]))), y1 + int(bar_h * float(sb[3])))
        _draw_centered(draw, brand_label, name_box, fill=brand_fill, max_size=int(bar_h * _style_number(style, "footer_bar.wide_name_max_ratio", 0.26)), min_size=int(bar_h * _style_number(style, "footer_bar.wide_name_min_ratio", 0.15)), max_lines=1, style=style, font_role="meta")
        _draw_centered(draw, brand_slogan, slogan_box, fill=slogan_fill, max_size=int(bar_h * _style_number(style, "footer_bar.wide_slogan_max_ratio", 0.15)), min_size=int(bar_h * _style_number(style, "footer_bar.wide_slogan_min_ratio", 0.08)), max_lines=2, style=style, font_role="slogan")
    else:
        # Vertical footer also uses bounded text boxes; direct drawing could overflow for long slogans.
        right_pad = max(10, int(bar_w * 0.04))
        name_box = (text_left, y1 + int(bar_h * 0.10), x2 - right_pad, y1 + int(bar_h * 0.46))
        slogan_box = (text_left, y1 + int(bar_h * 0.48), x2 - right_pad, y2 - int(bar_h * 0.10))
        _draw_left(draw, brand_label, name_box, fill=brand_fill, max_size=int(bar_h * _style_number(style, "footer_bar.vertical_name_size_ratio", 0.25)), min_size=int(bar_h * 0.13), max_lines=1, style=style, font_role="meta")
        _draw_left(draw, brand_slogan, slogan_box, fill=slogan_fill, max_size=int(bar_h * _style_number(style, "footer_bar.vertical_slogan_size_ratio", 0.13)), min_size=int(bar_h * 0.070), max_lines=2, style=style, font_role="slogan")


def _load_fixed_brand_logo(max_w: int, max_h: int) -> Image.Image:
    """Load the fixed user-provided Knowledge Slow Stew logo; never draw a fake fallback."""
    if not BRAND_LOGO_PATH.exists():
        raise FileNotFoundError(f"固定 logo 文件缺失：{BRAND_LOGO_PATH}")
    src = Image.open(BRAND_LOGO_PATH).convert("RGBA")
    px = src.load()
    for y in range(src.size[1]):
        for x in range(src.size[0]):
            r, g, b, a = px[x, y]
            if a >= 10 and r > 246 and g > 242 and b > 232:
                px[x, y] = (255, 255, 255, 0)
    bbox = src.getbbox()
    if bbox:
        src = src.crop(bbox)
    max_w = max(24, int(max_w))
    max_h = max(24, int(max_h))
    ratio = min(max_w / max(1, src.width), max_h / max(1, src.height))
    new_size = (max(1, int(src.width * ratio)), max(1, int(src.height * ratio)))
    return src.resize(new_size, Image.Resampling.LANCZOS)


def _paste_rounded_logo(dst: Image.Image, logo: Image.Image, xy: tuple[int, int], radius: int = 22) -> None:
    """Paste logo with a circular/rounded mask while preserving the original symbol design."""
    logo = logo.convert("RGBA")
    w, h = logo.size
    mask = Image.new("L", (w, h), 0)
    if abs(w - h) <= max(3, min(w, h) * 0.08):
        ImageDraw.Draw(mask).ellipse((0, 0, w - 1, h - 1), fill=255)
    else:
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=max(1, int(radius)), fill=255)
    out = Image.new("RGBA", (w, h), (255, 255, 255, 0))
    out.paste(logo, (0, 0), mask)
    dst.paste(out, xy, out)


def _draw_fixed_logo_slogan_footer(draw: ImageDraw.ImageDraw, img: Image.Image, box: tuple[int, int, int, int], *, brand_slogan: str = BRAND_SLOGAN, style: dict[str, Any] | None = None) -> None:
    """C end-card brand area: fixed logo image + slogan only, no generated substitute."""
    style = style or DEFAULT_STYLE_CONFIG
    x1, y1, x2, y2 = box
    bar_w = x2 - x1
    bar_h = y2 - y1
    radius = max(14, int(bar_h * 0.20))
    draw.rounded_rectangle(
        box,
        radius=radius,
        fill=_color(_get_nested(style, "footer_bar.fill"), (8, 7, 7, 178)),
        outline=_color(_get_nested(style, "footer_bar.outline"), (176, 134, 72, 220)),
        width=_style_int(style, "footer_bar.width_px", 2),
    )
    # Fixed uploaded logo: use the exact project asset, not a drawn icon or AI-generated mark.
    logo_max_h = int(bar_h * 0.84)
    logo_max_w = int(bar_w * 0.38)
    logo = _load_fixed_brand_logo(logo_max_w, logo_max_h)
    logo_x = x1 + int(bar_w * 0.045)
    logo_y = y1 + (bar_h - logo.height) // 2
    plate_pad = max(6, int(bar_h * 0.030))
    plate = (logo_x - plate_pad, logo_y - plate_pad, logo_x + logo.width + plate_pad, logo_y + logo.height + plate_pad)
    draw.rounded_rectangle(
        plate,
        radius=max(16, int(min(logo.width, logo.height) * 0.12)),
        fill=(255, 249, 235, 232),
        outline=_color(_get_nested(style, "footer_bar.icon_bg_outline"), (216, 176, 108, 220)),
        width=max(2, int(bar_h * 0.012)),
    )
    _paste_rounded_logo(img, logo, (logo_x, logo_y), radius=max(12, int(min(logo.width, logo.height) * 0.10)))

    text_left = plate[2] + int(bar_w * 0.050)
    text_box = (text_left, y1 + int(bar_h * 0.18), x2 - int(bar_w * 0.045), y2 - int(bar_h * 0.18))
    slogan = _clean_text(brand_slogan) or BRAND_SLOGAN
    _draw_left(
        draw,
        slogan,
        text_box,
        fill=_style_color(style, "brand_slogan", (248, 231, 200)),
        max_size=int(bar_h * 0.24),
        min_size=max(12, int(bar_h * 0.11)),
        max_lines=2,
        style=style,
        font_role="slogan",
    )


def _editorial_enabled(style: dict[str, Any], kind: str) -> bool:
    return bool(_get_nested(style, f"{kind}.editorial_layout.enabled", True))


def _editorial_grade(
    img: Image.Image,
    *,
    darken: float = 0.52,
    blur: float = 1.1,
    controls: dict[str, Any] | None = None,
) -> Image.Image:
    controls = _visual_controls(None) if controls is None else controls
    bg = controls.get("background") if isinstance(controls.get("background"), dict) else {}
    brightness = _bounded_number(bg.get("brightness"), 0.96, 0.62, 1.18)
    saturation = _bounded_number(bg.get("saturation"), 0.96, 0.72, 1.38)
    contrast = _bounded_number(bg.get("contrast"), 1.06, 0.82, 1.32)
    blur = max(0.0, blur + _bounded_number(bg.get("blur_px"), 0.0, 0.0, 18.0) * 0.12)
    vignette_strength = _bounded_number(bg.get("vignette"), 0.32, 0.0, 0.90)
    top_darken = _bounded_number(bg.get("top_darken"), 0.16, 0.0, 0.90)
    bottom_darken = _bounded_number(bg.get("bottom_darken"), 0.24, 0.0, 0.95)
    base = img.convert("RGB")
    base = ImageEnhance.Brightness(base).enhance(brightness)
    base = ImageEnhance.Contrast(base).enhance(contrast)
    base = ImageEnhance.Color(base).enhance(saturation)
    if blur > 0:
        base = base.filter(ImageFilter.GaussianBlur(blur))
    warm = Image.new("RGB", base.size, (226, 206, 174))
    base = Image.blend(base, warm, 0.07)
    dark = Image.new("RGB", base.size, (30, 26, 23))
    base = Image.blend(base, dark, max(0.0, min(0.85, darken)))
    w, h = base.size
    grade = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grade, "RGBA")
    top_span = max(1, int(h * 0.42))
    for yy in range(top_span):
        alpha = int(145 * top_darken * (1 - yy / top_span))
        gd.line((0, yy, w, yy), fill=(4, 6, 8, max(0, min(180, alpha))))
    bottom_start = int(h * 0.54)
    for yy in range(bottom_start, h):
        alpha = int(165 * bottom_darken * ((yy - bottom_start) / max(1, h - bottom_start)))
        gd.line((0, yy, w, yy), fill=(4, 5, 7, max(0, min(190, alpha))))
    mask = Image.new("L", (w, h), 0)
    md = ImageDraw.Draw(mask)
    pad = int(min(w, h) * 0.05)
    md.ellipse((-pad, -pad, w + pad, h + pad), fill=255)
    mask = Image.eval(mask.filter(ImageFilter.GaussianBlur(int(min(w, h) * 0.16))), lambda p: 255 - p)
    vignette = Image.new("RGBA", (w, h), (18, 15, 13, int(120 * vignette_strength)))
    out = base.convert("RGBA")
    out.alpha_composite(grade)
    out.alpha_composite(Image.composite(vignette, Image.new("RGBA", (w, h), (0, 0, 0, 0)), mask))
    return out


def _draw_editorial_pill(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], text: str, *, unit: int, fill=(250, 244, 229, 232), outline=(219, 171, 105, 210), color=(236, 112, 45)) -> None:
    text = _clean_text(text)
    if not text:
        return
    x1, y1, x2, y2 = box
    text_box = _inset_box(box, int(unit * 0.025), int(unit * 0.004))
    max_size = max(18, int(unit * 0.026))
    min_size = max(12, int(unit * 0.015))
    _, wrapped, _ = _fit_text(draw, text, text_box, max_size=max_size, min_size=min_size, max_lines=1, font_role="meta")
    if not str(wrapped or "").strip():
        return
    draw.rounded_rectangle(box, radius=max(12, (y2 - y1) // 2), fill=fill, outline=outline, width=max(2, unit // 540))
    _draw_centered(
        draw,
        wrapped,
        text_box,
        fill=color,
        max_size=max_size,
        min_size=min_size,
        max_lines=1,
        style={"text_shadow": {"enabled": False, "glow_px": 0, "stroke_divisor": 9999}},
        font_role="meta",
    )


def _add_soft_shadow(img: Image.Image, box: tuple[int, int, int, int], radius: int, *, alpha: int = 70, blur: int = 26, offset: tuple[int, int] = (0, 10)) -> None:
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer, "RGBA")
    x1, y1, x2, y2 = box
    dx, dy = offset
    d.rounded_rectangle((x1 + dx, y1 + dy, x2 + dx, y2 + dy), radius=radius, fill=(0, 0, 0, alpha))
    layer = layer.filter(ImageFilter.GaussianBlur(blur))
    img.alpha_composite(layer)


def _draw_magazine_outer_frame(
    draw: ImageDraw.ImageDraw,
    img: Image.Image,
    *,
    color: tuple[int, int, int] = (236, 112, 45),
    accent2: tuple[int, int, int] = (80, 132, 150),
    controls: dict[str, Any] | None = None,
) -> None:
    controls = _visual_controls(None) if controls is None else controls
    if not bool(_get_nested(controls, "ornaments.frame", True)):
        return
    w, h = img.size
    unit = min(w, h)
    margin = max(20, int(unit * 0.026))
    width = max(2, int(unit * 0.0026))
    draw.rounded_rectangle(
        (margin, margin, w - margin, h - margin),
        radius=max(16, int(unit * 0.018)),
        outline=(*color, 95),
        width=width,
    )
    rule_w = int((w - margin * 2) * 0.28)
    draw.line((margin, margin, margin + rule_w, margin), fill=(*accent2, 190), width=max(width + 1, int(unit * 0.004)))
    draw.line((w - margin - rule_w, h - margin, w - margin, h - margin), fill=(*accent2, 150), width=max(width, int(unit * 0.003)))


def _draw_magazine_micro_marks(
    draw: ImageDraw.ImageDraw,
    img: Image.Image,
    *,
    color: tuple[int, int, int] = (236, 112, 45),
    controls: dict[str, Any] | None = None,
) -> None:
    controls = _visual_controls(None) if controls is None else controls
    w, h = img.size
    unit = min(w, h)
    if bool(_get_nested(controls, "ornaments.scanline", False)):
        step = max(16, int(unit * 0.030))
        for y in range(0, h, step):
            draw.line((0, y, w, y), fill=(255, 255, 255, 10), width=1)
    if bool(_get_nested(controls, "ornaments.progress_bar", False)):
        y = h - max(18, int(unit * 0.032))
        x1 = int(w * 0.10)
        x2 = int(w * 0.90)
        draw.rounded_rectangle((x1, y, x2, y + max(3, unit // 210)), radius=999, fill=(255, 255, 255, 35))
        draw.rounded_rectangle((x1, y, x1 + int((x2 - x1) * 0.58), y + max(3, unit // 210)), radius=999, fill=(*color, 170))


def _draw_editorial_logo_badge(
    draw: ImageDraw.ImageDraw,
    img: Image.Image,
    center: tuple[int, int],
    size: int,
    *,
    show_label: bool = False,
    brand_name: str = BRAND_NAME,
    brand_slogan: str = BRAND_SLOGAN,
    light_text: bool = True,
) -> None:
    icon = _extract_logo_icon(BRAND_LOGO_PATH, int(size * 0.84))
    badge_size = int(size)
    x = int(center[0] - badge_size / 2)
    y = int(center[1] - badge_size / 2)
    glow_pad = max(3, badge_size // 18)
    draw.ellipse(
        (x - glow_pad, y - glow_pad, x + badge_size + glow_pad, y + badge_size + glow_pad),
        fill=(222, 176, 112, 24),
    )
    draw.ellipse(
        (x, y, x + badge_size, y + badge_size),
        fill=(255, 248, 232, 232),
        outline=(235, 190, 122, 210),
        width=max(2, badge_size // 44),
    )
    if icon is not None:
        img.alpha_composite(icon, (center[0] - icon.width // 2, center[1] - icon.height // 2))
    if show_label:
        brand_label = _brand_display_name(brand_name)
        name_color = (250, 244, 229) if light_text else (54, 36, 28)
        slogan_color = (220, 170, 118) if light_text else (150, 96, 58)
        _draw_centered(
            draw,
            brand_label,
            (center[0] - badge_size, y + badge_size + int(size * 0.10), center[0] + badge_size, y + badge_size + int(size * 0.42)),
            fill=name_color,
            max_size=max(22, int(size * 0.24)),
            min_size=max(14, int(size * 0.12)),
            max_lines=1,
            style={"text_shadow": {"enabled": False, "glow_px": 0, "stroke_divisor": 9999}},
            font_role="meta",
        )
        _draw_centered(
            draw,
            brand_slogan,
            (center[0] - int(size * 1.65), y + badge_size + int(size * 0.43), center[0] + int(size * 1.65), y + badge_size + int(size * 0.70)),
            fill=slogan_color,
            max_size=max(14, int(size * 0.14)),
            min_size=max(10, int(size * 0.08)),
            max_lines=1,
            style={"text_shadow": {"enabled": False, "glow_px": 0, "stroke_divisor": 9999}},
            font_role="slogan",
        )


def _poster_title_from_context(title: str, hook: str = "", chapter_name: str = "") -> str:
    text = _clean_text(title)
    hook_text = _clean_text(hook)
    chapter = _clean_text(chapter_name)
    generic = {"你敢信吗", "你敢信吗？", "这一集", "本集"}
    poverty_text = " ".join([text, hook_text, chapter])
    if re.search(r"(贫穷|贫困|穷人)", poverty_text) and re.search(r"(懒|不努力|评判|误判|性格|贴.*标签|退路|选择)", poverty_text):
        if re.search(r"(选择太少|退路太少|不是懒)", text) and len(text) <= 18:
            return text
        return "贫穷不是懒\n是选择太少"
    if ("生病" in text or "生病" in hook_text) and "\n" not in text:
        return "为什么\n越穷越生病？"
    if text.strip("？！!?。") in {x.strip("？！!?。") for x in generic}:
        if "电视" in hook_text and ("吃不饱" in hook_text or "食物" in hook_text or "饭" in hook_text):
            return "吃不饱，\n为什么还买电视？"
        if "生病" in hook_text:
            return "越穷，为什么\n越容易生病？"
        if chapter:
            return f"{chapter}\n到底讲了什么？"
    if "电视" in text and "吃" in text and "\n" not in text:
        return "吃不饱，\n为什么还买电视？"
    if text and not re.search(r"[？?]$", text) and ("为什么" in text or "为何" in text or "吗" in text):
        text += "？"
    return text


def _poster_message_pack(title: str, hook: str = "", chapter_name: str = "") -> dict[str, str]:
    text = " ".join(_clean_text(x) for x in [title, hook, chapter_name] if _clean_text(x))
    if re.search(r"(贫穷|贫困|穷人)", text) and re.search(r"(懒|不努力|评判|误判|性格|贴.*标签|退路|选择|活下去|奔波)", text):
        return {
            "marketing_tag": "",
            "wide_tagline": "",
            "wide_note": "",
            "note_title": "",
            "note_subtitle": "",
            "note_meta": "",
            "teaser_subtitle": "下一集：为什么吃不饱的人，还会买电视？",
        }
    if "电视" in text and any(word in text for word in ["吃", "饭", "饱", "食物", "饥饿"]):
        return {
            "marketing_tag": "不是穷人不理性",
            "wide_tagline": "不是浪费钱，而是在用最低成本买确定感。",
            "wide_note": "这集把电视、吃饭和现金放在一起，看见贫穷怎样改写选择。",
            "note_title": "不是不想吃饱，是每一笔钱都在做取舍。",
            "note_subtitle": "电视、食物、现金，背后是压力、希望和贫穷陷阱。",
            "note_meta": "看懂这个选择，才会明白贫穷为什么会反复出现。",
            "teaser_subtitle": "下一集：疾病、收入和选择，会怎样互相拖住一个人？",
        }
    if "生病" in text or "健康" in text or "医疗" in text:
        return {
            "marketing_tag": "贫穷会放大疾病",
            "wide_tagline": "不是身体更差，而是生活把风险一步步推高。",
            "wide_note": "这集讲的是：小病、现金流和拖延治疗如何互相缠住。",
            "note_title": "越穷越容易病，不只是卫生问题。",
            "note_subtitle": "病痛会吞掉收入，收入又决定能不能及时治疗。",
            "note_meta": "贫穷最可怕的地方，是它会把一次风险变成长期困境。",
            "teaser_subtitle": "下一集：把疾病、收入和选择连起来看。",
        }
    subject = _clean_text(chapter_name) or "本集"
    if len(subject) > 12:
        subject = subject[:12].rstrip("，,。；;：: ")
    return {
        "marketing_tag": "",
        "wide_tagline": "",
        "wide_note": "",
        "note_title": "",
        "note_subtitle": "",
        "note_meta": "",
        "teaser_subtitle": "",
    }


def _balanced_poster_title_lines(text: str, max_lines: int = 3) -> list[str]:
    """Split a poster title without injecting topic-specific fallback words."""
    value = _clean_text(text).strip("，,。；;：: ")
    if not value:
        return ["本集看点"]
    if value == "午朝谣言背后的制度困局" and max_lines >= 2:
        return ["午朝谣言背后的", "制度困局"]
    explicit = [line.strip() for line in value.splitlines() if line.strip()]
    if len(explicit) >= 2:
        return explicit[:max_lines]
    semantic = re.search(r"(.{3,14}?)(怎样|如何|怎么|为什么|为何|凭什么)(.+)", value)
    if semantic and max_lines >= 2:
        left = semantic.group(1).strip("，,：: ")
        right = (semantic.group(2) + semantic.group(3)).strip("，,：: ")
        if left and right and 3 <= len(left) <= 14:
            return [left, right][:max_lines]
    parts = [part.strip() for part in re.split(r"([，,：:｜|？?])", value) if part.strip()]
    if len(parts) > 2:
        merged: list[str] = []
        cur = ""
        for part in parts:
            cur += part
            if part in {"，", ",", "：", ":", "｜", "|", "？", "?"}:
                merged.append(cur.strip())
                cur = ""
        if cur:
            merged.append(cur.strip())
        merged = [x.strip("，,：:｜| ") for x in merged if x.strip("，,：:｜| ")]
        if len(merged) >= 2:
            return merged[:max_lines]
    chars = list(value)
    target = max(4, math.ceil(len(chars) / 2))
    break_at = target
    for offset in range(0, max(1, len(chars) // 3)):
        for candidate in (target + offset, target - offset):
            if 3 <= candidate <= len(chars) - 3:
                break_at = candidate
                return ["".join(chars[:break_at]), "".join(chars[break_at:])]
    return [value]


def _draw_poster_glow(img: Image.Image, center: tuple[int, int], radius: int, color=(236, 112, 45), alpha: int = 95) -> None:
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer, "RGBA")
    x, y = center
    d.ellipse((x - radius, y - radius, x + radius, y + radius), fill=(*color, alpha))
    layer = layer.filter(ImageFilter.GaussianBlur(max(24, radius // 3)))
    img.alpha_composite(layer)


def _poster_reframe_vertical(img: Image.Image) -> Image.Image:
    """Zoom into the generated scene so the poster is not dominated by empty top/bottom bands."""
    w, h = img.size
    zoom = 1.82
    rw, rh = int(w * zoom), int(h * zoom)
    resized = img.resize((rw, rh), Image.Resampling.LANCZOS)
    left = max(0, min(rw - w, (rw - w) // 2))
    top = max(0, min(rh - h, int(rh * 0.30)))
    return resized.crop((left, top, left + w, top + h))


def _editorial_plain_style() -> dict[str, Any]:
    return {"text_shadow": {"enabled": False, "glow_px": 0, "stroke_divisor": 9999}}


def _editorial_title_lines(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int, max_lines: int = 3) -> list[str]:
    text = re.sub(r"\s+", "", _clean_text(text))
    if not text:
        return []
    if _text_size(draw, text, font)[0] <= max_width:
        return [text]
    protected: dict[str, str] = {}
    def protect(match: re.Match[str]) -> str:
        key = f"§{len(protected)}§"
        protected[key] = match.group(0)
        return key
    work = re.sub(r"\d+(?:\.\d+)?(?:万|亿|元|块|页|年|%|％)?", protect, text)
    tokens = list(re.finditer(r"§\d+§|.", work))
    separators = ["，", "。", "？", "?", "：", ":", "、", "；", ";", "｜", "|", " "]
    for sep in separators:
        if sep in text:
            raw = [x for x in re.split(f"({re.escape(sep)})", text) if x]
            chunks: list[str] = []
            cur = ""
            for item in raw:
                probe = cur + item
                if cur and _text_size(draw, probe, font)[0] > max_width:
                    chunks.append(cur)
                    cur = item
                else:
                    cur = probe
            if cur:
                chunks.append(cur)
            chunks = _tidy_line_breaks(chunks)
            if 1 < len(chunks) <= max_lines and all(_text_size(draw, line, font)[0] <= max_width for line in chunks):
                return chunks
    lines: list[str] = []
    cur = ""
    for match in tokens:
        token = protected.get(match.group(0), match.group(0))
        probe = cur + token
        if cur and _text_size(draw, probe, font)[0] > max_width and len(lines) < max_lines - 1:
            lines.append(cur)
            cur = token
        else:
            cur = probe
    if cur:
        lines.append(cur)
    return _tidy_line_breaks(lines[:max_lines])


def _draw_editorial_big_title(
    draw: ImageDraw.ImageDraw,
    text: str,
    box: tuple[int, int, int, int],
    *,
    unit: int,
    fill=(54, 36, 28),
    align: str = "left",
    max_ratio: float = 0.094,
    min_ratio: float = 0.044,
    max_lines: int = 3,
    controls: dict[str, Any] | None = None,
) -> None:
    controls = _visual_controls(None) if controls is None else controls
    title_scale = _bounded_number(_get_nested(controls, "title.scale"), 1.0, 0.75, 1.45)
    title_glow = _bounded_number(_get_nested(controls, "title.glow"), 0.0, 0.0, 1.0)
    max_ratio *= title_scale
    min_ratio *= max(0.84, min(1.18, title_scale))
    x1, y1, x2, y2 = box
    max_w = max(10, x2 - x1)
    max_h = max(10, y2 - y1)
    plain = _editorial_plain_style()
    for size in range(int(unit * max_ratio), int(unit * min_ratio) - 1, -2):
        fnt = get_font(size, role="episode")
        if "\n" in str(text):
            lines = [line.strip() for line in str(text).splitlines() if line.strip()][:max_lines]
        else:
            lines = _editorial_title_lines(draw, text, fnt, max_w, max_lines=max_lines)
        spacing = max(4, size // 8)
        tw, th = _text_size(draw, "\n".join(lines), fnt, spacing)
        if lines and th <= max_h and tw <= max_w:
            break
    else:
        size = int(unit * min_ratio)
        fnt = get_font(size, role="episode")
        if "\n" in str(text):
            lines = [line.strip() for line in str(text).splitlines() if line.strip()][:max_lines]
        else:
            lines = _editorial_title_lines(draw, text, fnt, max_w, max_lines=max_lines)
        spacing = max(4, size // 8)
    y = y1
    anchor = "la" if align == "left" else "ma"
    x = x1 if align == "left" else (x1 + x2) // 2
    for line in lines:
        if title_glow > 0:
            glow_style = {
                "text_shadow": {
                    "enabled": True,
                    "glow_px": max(1, int(size * 0.055 * title_glow)),
                    "glow_color": [fill[0], fill[1], fill[2], int(85 * title_glow)],
                    "shadow_color": [0, 0, 0, int(80 * title_glow)],
                    "stroke_color": [0, 0, 0, int(120 * title_glow)],
                    "stroke_divisor": max(42, int(70 / max(0.18, title_glow))),
                    "offsets": [[0, max(1, int(size * 0.025))]],
                }
            }
            _draw_text_with_shadow(draw, (x, y), line, fnt, fill, spacing=spacing, anchor=anchor, align=align, style=glow_style)
        else:
            _draw_text_with_shadow(draw, (x, y), line, fnt, fill, spacing=spacing, anchor=anchor, align=align, stroke=0, style=plain)
        y += _text_size(draw, line, fnt, spacing)[1] + spacing


def _add_luxury_scrims(img: Image.Image, *, top_alpha: int = 150, bottom_alpha: int = 150, center_alpha: int = 24) -> None:
    w, h = img.size
    top = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    td = ImageDraw.Draw(top, "RGBA")
    top_span = max(1, int(h * 0.70))
    for yy in range(top_span):
        alpha = int(top_alpha * (1 - yy / top_span))
        td.line((0, yy, w, yy), fill=(8, 7, 6, max(0, alpha)))
    bottom = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    bd = ImageDraw.Draw(bottom, "RGBA")
    start = int(h * 0.42)
    for yy in range(start, h):
        alpha = int(bottom_alpha * ((yy - start) / max(1, h - start)))
        bd.line((0, yy, w, yy), fill=(7, 6, 5, max(0, min(190, alpha))))
    img.alpha_composite(top)
    img.alpha_composite(bottom)
    if center_alpha:
        img.alpha_composite(Image.new("RGBA", (w, h), (10, 8, 6, center_alpha)))


def _public_chapter_label(text: str) -> str:
    """Hide internal split/page marks from cover-facing copy."""
    cleaned = _clean_text(text)
    # Internal split/page suffixes look like "01/05P15", "01/05 P15",
    # "01 05P", "P15". They are useful for source ranges but toxic on covers.
    cleaned = re.sub(r"\s*\d{1,2}\s*/\s*\d{1,2}\s*P?\s*\d*\s*$", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s+\d{1,2}\s+\d{1,2}\s*P\s*\d*\s*$", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s+\d{1,2}\s*P\s*\d*\s*$", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s*P\s*\d+\s*$", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s+\d{1,2}\s*/\s*\d{1,2}\s*$", "", cleaned)
    return cleaned.strip(" ·｜|-_")


def _poster_no_period(text: str) -> str:
    value = _clean_text(text)
    value = value.replace("。", "")
    value = re.sub(r"[\.．]+$", "", value)
    return value.strip(" ，,；;：:")


_LEGACY_POSTER_DEFAULT_TEXTS = {
    "想看更完整的原著细节，可以从下方链接入手原书",
    "想继续看这类经典拆解",
    "欢迎关注【知识慢炖】",
    "下一期内容待更新",
    "继续看关键转折",
    "先把处境看清楚",
    "本集核心问题",
    "复杂原著",
    "复杂历史",
    "真正的麻烦",
    "人物、制度与时代张力",
    "关键因果",
}


def _is_legacy_poster_default(text: str) -> bool:
    value = _poster_no_period(text)
    if not value:
        return False
    if "??" in value or (value.count("?") >= 2 and value.count("?") >= len(value) * 0.25):
        return True
    legacy = [_poster_no_period(x) for x in _LEGACY_POSTER_DEFAULT_TEXTS]
    return any(item and item in value for item in legacy)


def _cover_episode_label(chapter_no: str, chapter_name: str, episode_no: str, episode_title: str = "") -> str:
    episode = _clean_text(episode_no)
    if not episode:
        raw_for_episode = " ".join(x for x in [_clean_text(episode_title), _clean_text(chapter_name)] if x)
        m = re.search(r"(?:^|\s)(\d{1,3})\s+\d{1,3}\s*P\s*\d*\s*$", raw_for_episode, flags=re.I)
        if m:
            episode = m.group(1)
    if not episode:
        title_without_page = _public_chapter_label(episode_title)
        m = re.search(r"(?:第\s*)?([0-9]{1,3}|[一二三四五六七八九十百]{1,4})\s*(?:集|期)?\s*$", title_without_page)
        if m:
            episode = m.group(1)
    if episode and re.fullmatch(r"\d{1,2}", episode):
        episode = episode.zfill(2)
    if episode:
        return _poster_no_period(f"第{episode}集" if re.fullmatch(r"\d{1,3}", episode) else episode)
    return ""


def _cover_core_point(title: str, hook: str = "", chapter_name: str = "") -> str:
    text = " ".join(_clean_text(x) for x in [title, hook, chapter_name] if _clean_text(x))
    if re.search(r"(贫穷|穷人|贫困|扶贫|营养|饥饿|小额信贷|贷款|教育|健康|风险|选择|约束|公共服务|发展经济学)", text):
        return ""
    return ""


def _add_luxury_text_field(
    img: Image.Image,
    box: tuple[int, int, int, int],
    *,
    alpha: int = 90,
    border_alpha: int = 28,
    radius: int | None = None,
    blur: int | None = None,
    controls: dict[str, Any] | None = None,
) -> None:
    controls = _visual_controls(None) if controls is None else controls
    glass = controls.get("glass") if isinstance(controls.get("glass"), dict) else {}
    opacity_mul = _bounded_number(glass.get("opacity"), 0.70, 0.20, 0.96)
    blur_add = _bounded_number(glass.get("blur_px"), 0.0, 0.0, 34.0) * 0.34
    glow = _bounded_number(glass.get("glow"), 0.18, 0.0, 1.0)
    w, h = img.size
    unit = min(w, h)
    radius = int(radius if radius is not None else unit * 0.022)
    blur = int((blur if blur is not None else max(10, unit // 80)) + blur_add)
    x1, y1, x2, y2 = box
    mask = Image.new("L", (w, h), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle((x1, y1, x2, y2), radius=radius, fill=255)
    if blur > 0:
        mask = mask.filter(ImageFilter.GaussianBlur(blur))
    alpha_to_use = max(0, min(210, int(alpha * opacity_mul)))
    field = Image.new("RGBA", (w, h), (8, 7, 6, alpha_to_use))
    field.putalpha(mask.point(lambda p: int(p * alpha_to_use / 255)))
    img.alpha_composite(field)
    draw = ImageDraw.Draw(img, "RGBA")
    if glow > 0:
        glow_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow_layer, "RGBA")
        gd.rounded_rectangle((x1, y1, x2, y2), radius=radius, outline=(226, 174, 100, int(70 * glow)), width=max(2, unit // 420))
        img.alpha_composite(glow_layer.filter(ImageFilter.GaussianBlur(max(8, unit // 70))))
    draw.rounded_rectangle((x1, y1, x2, y2), radius=radius, outline=(226, 174, 100, int(border_alpha * max(0.45, opacity_mul))), width=max(1, unit // 950))


def _draw_warm_logo_zone(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], unit: int, *, radius_scale: float = 0.020) -> None:
    """Draw a logo container that blends into the warm court background."""
    radius = int(unit * radius_scale)
    draw.rounded_rectangle(
        box,
        radius=radius,
        fill=(250, 244, 229, 78),
        outline=(226, 174, 100, 76),
        width=max(1, unit // 760),
    )


def _draw_refined_brand_signature(
    draw: ImageDraw.ImageDraw,
    img: Image.Image,
    box: tuple[int, int, int, int],
    *,
    brand_name: str = BRAND_NAME,
) -> None:
    """Small magazine-style brand signature; avoids a heavy sticker plate."""
    x1, y1, x2, y2 = box
    h = max(1, y2 - y1)
    icon_size = int(h * 0.98)
    icon = _extract_logo_icon(BRAND_LOGO_PATH, icon_size)
    if icon is not None:
        img.alpha_composite(icon, (x1, y1 + (h - icon_size) // 2))
    label = _clean_text(brand_name).strip("【】")
    font = get_font(max(18, int(h * 0.36)), role="meta")
    color = (255, 242, 214, 238)
    text_x = x1 + icon_size + int(h * 0.18)
    text_y = y1 + int(h * 0.25)
    _draw_text_with_shadow(
        draw,
        (text_x, text_y),
        label,
        font,
        color,
        anchor="la",
        stroke=max(1, h // 64),
        style={"text_shadow": {"enabled": True, "glow_px": max(1, h // 24), "stroke_divisor": 64}},
    )
    draw.line((text_x, y1 + int(h * 0.74), min(x2, text_x + int(h * 2.25)), y1 + int(h * 0.74)), fill=(238, 132, 58, 190), width=max(2, h // 34))


def _is_social_science_cover_context(*parts: str) -> bool:
    text = " ".join(_clean_text(part) for part in parts if _clean_text(part))
    return bool(re.search(r"(贫穷|贫困|穷人|发展经济学|小额信贷|扶贫|公共服务|疟疾|蚊帐|饥饿|营养)", text))


def _magazine_profile_for_context(*parts: str) -> dict[str, Any]:
    text = " ".join(_clean_text(part) for part in parts if _clean_text(part))
    profiles = [
        (
            r"(贫穷|贫困|穷人|发展经济学|小额信贷|扶贫|公共服务|疟疾|蚊帐|饥饿|营养|收入|选择)",
            {
                "kind": "social",
                "label": "SOCIAL IDEAS",
                "kicker": "One case, one hard question",
                "accent": (224, 113, 48),
                "accent2": (68, 137, 151),
                "paper": (252, 248, 238),
            },
        ),
        (
            r"(王朝|帝国|皇帝|战争|制度|历史|朝廷|官僚|边疆|改革|革命|时代|文明|古代)",
            {
                "kind": "history",
                "label": "HISTORY REVIEW",
                "kicker": "Power, people, and the turn of events",
                "accent": (199, 148, 72),
                "accent2": (119, 82, 92),
                "paper": (247, 238, 218),
            },
        ),
        (
            r"(小说|文学|人物|命运|爱情|家庭|童年|创伤|欲望|孤独|关系|叙事|神话)",
            {
                "kind": "literary",
                "label": "LITERARY NOTEBOOK",
                "kicker": "A sharp reading of human texture",
                "accent": (132, 105, 158),
                "accent2": (197, 125, 91),
                "paper": (247, 240, 232),
            },
        ),
        (
            r"(脑|神经|细胞|基因|受体|突触|记忆|认知|心理|机制|实验|科学|医学|疾病|疼痛|AI|人工智能)",
            {
                "kind": "science",
                "label": "SCIENCE FEATURE",
                "kicker": "Mechanism, evidence, and mind",
                "accent": (40, 132, 164),
                "accent2": (210, 118, 96),
                "paper": (235, 247, 249),
            },
        ),
    ]
    for pattern, profile in profiles:
        if re.search(pattern, text, flags=re.I):
            return profile
    return {
        "kind": "culture",
        "label": "CULTURE REVIEW",
        "kicker": "Classic ideas, rebuilt for today",
        "accent": (222, 113, 58),
        "accent2": (74, 131, 145),
        "paper": (250, 244, 229),
    }


def _profile_kind(profile: dict[str, Any] | None) -> str:
    kind = str((profile or {}).get("kind") or "").strip().lower()
    if kind in {"science", "history", "social", "literary", "culture"}:
        return kind
    label = str((profile or {}).get("label") or "").lower()
    if "science" in label:
        return "science"
    if "history" in label:
        return "history"
    if "social" in label:
        return "social"
    if "literary" in label:
        return "literary"
    return "culture"


def _draw_magazine_identity(
    draw: ImageDraw.ImageDraw,
    img: Image.Image,
    *,
    profile: dict[str, Any],
    box: tuple[int, int, int, int],
    unit: int,
    light: bool = True,
) -> None:
    x1, y1, x2, y2 = box
    plain = _editorial_plain_style()
    accent = tuple(profile.get("accent") or (236, 112, 45))
    accent2 = tuple(profile.get("accent2") or (80, 132, 150))
    label = str(profile.get("label") or "CULTURE REVIEW")
    short_label = re.sub(r"\s+(FEATURE|IDEAS|REVIEW|NOTEBOOK)\b", "", label, flags=re.I).strip() or label
    text_color = (250, 244, 229) if light else (38, 42, 48)
    bar_h = max(4, int(unit * 0.006))
    bar_w = max(80, int((x2 - x1) * 0.23))
    draw.rectangle((x1, y1, x1 + bar_w, y1 + bar_h), fill=(*accent, 230))
    draw.rectangle((x1 + bar_w, y1, x1 + bar_w + int(bar_w * 0.82), y1 + bar_h), fill=(*accent2, 215))
    _draw_left(
        draw,
        f"KSS  /  {short_label}",
        (x1, y1 + int(unit * 0.018), x2, y1 + int(unit * 0.056)),
        fill=text_color,
        max_size=int(unit * 0.020),
        min_size=int(unit * 0.011),
        max_lines=1,
        style=plain,
        font_role="meta",
    )


def _profile_rgb(profile: dict[str, Any] | None, key: str, fallback: tuple[int, int, int]) -> tuple[int, int, int]:
    if not profile:
        return fallback
    value = profile.get(key)
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        return (int(value[0]), int(value[1]), int(value[2]))
    return fallback


def _cover_title_lines_for_magazine(display_title: str, *, max_lines: int = 3) -> list[str]:
    title = _poster_no_period(display_title)
    lines = [line.strip() for line in str(title).splitlines() if line.strip()]
    if len(lines) < 2:
        lines = [part.strip() for part in re.split(r"[，,：:]", str(title), maxsplit=max_lines - 1) if part.strip()]
    if len(lines) < 2:
        lines = _balanced_poster_title_lines(str(title), max_lines=max_lines)
    return [_poster_no_period(line) for line in lines[:max_lines] if _poster_no_period(line)]


def _draw_science_axis(draw: ImageDraw.ImageDraw, img: Image.Image, *, profile: dict[str, Any], unit: int) -> None:
    w, h = img.size
    accent = _profile_rgb(profile, "accent", (40, 132, 164))
    accent2 = _profile_rgb(profile, "accent2", (210, 118, 96))
    cx = w // 2
    top = int(h * 0.160)
    bottom = int(h * 0.815)
    draw.line((cx, top, cx, bottom), fill=(*accent, 86), width=max(1, unit // 560))
    for idx, y in enumerate([int(top + (bottom - top) * t) for t in (0.0, 0.18, 0.38, 0.62, 0.82, 1.0)]):
        span = int(unit * (0.070 if idx in {0, 5} else 0.038))
        color = accent2 if idx in {2, 3} else accent
        draw.line((cx - span, y, cx + span, y), fill=(*color, 120), width=max(1, unit // 680))
    ring_box = (
        cx - int(unit * 0.245),
        int(h * 0.305),
        cx + int(unit * 0.245),
        int(h * 0.305) + int(unit * 0.490),
    )
    draw.ellipse(ring_box, outline=(*accent, 72), width=max(1, unit // 420))
    inset = int(unit * 0.060)
    draw.ellipse((ring_box[0] + inset, ring_box[1] + inset, ring_box[2] - inset, ring_box[3] - inset), outline=(*accent2, 66), width=max(1, unit // 520))


def _render_science_center_cover(
    img: Image.Image,
    out_path: Path,
    *,
    display_title: str,
    book_author_line: str,
    chapter_episode_line: str,
    brand_name: str,
    brand_slogan: str,
    mag_profile: dict[str, Any] | None = None,
) -> bool:
    draw = ImageDraw.Draw(img, "RGBA")
    w, h = img.size
    unit = min(w, h)
    plain = _editorial_plain_style()
    profile = mag_profile or _magazine_profile_for_context(display_title, book_author_line, chapter_episode_line)
    paper = _profile_rgb(profile, "paper", (235, 247, 249))
    accent = _profile_rgb(profile, "accent", (40, 132, 164))
    accent2 = _profile_rgb(profile, "accent2", (210, 118, 96))

    _add_luxury_scrims(img, top_alpha=78, bottom_alpha=108, center_alpha=12)
    _draw_poster_glow(img, (w // 2, int(h * 0.425)), int(unit * 0.64), color=accent, alpha=16)
    _draw_poster_glow(img, (int(w * 0.66), int(h * 0.610)), int(unit * 0.38), color=accent2, alpha=10)
    _draw_science_axis(draw, img, profile=profile, unit=unit)

    left = int(w * 0.095)
    right = int(w * 0.905)
    _draw_magazine_identity(draw, img, profile=profile, box=(left, int(h * 0.030), right, int(h * 0.085)), unit=unit, light=True)
    draw.line((left, int(h * 0.086), right, int(h * 0.086)), fill=(*accent, 112), width=max(1, unit // 720))
    if book_author_line:
        _draw_centered(draw, _poster_no_period(book_author_line), (left, int(h * 0.106), right, int(h * 0.170)), fill=(238, 248, 250), max_size=int(unit * 0.052), min_size=int(unit * 0.026), max_lines=1, style=plain, font_role="book")
    if chapter_episode_line:
        _draw_centered(draw, _poster_no_period(chapter_episode_line), (left, int(h * 0.178), right, int(h * 0.236)), fill=(205, 231, 236), max_size=int(unit * 0.040), min_size=int(unit * 0.020), max_lines=1, style=plain, font_role="meta")

    lines = _cover_title_lines_for_magazine(display_title, max_lines=3)
    if len(lines) == 1:
        lines.append("")
    title_panel = (left - int(w * 0.010), int(h * 0.300), right + int(w * 0.010), int(h * (0.620 if len(lines) > 2 else 0.575)))
    _add_soft_shadow(img, title_panel, int(unit * 0.035), alpha=26, blur=max(34, unit // 16), offset=(0, int(h * 0.008)))
    _add_luxury_text_field(img, title_panel, alpha=26, border_alpha=0, radius=int(unit * 0.014), blur=max(16, unit // 58))
    draw.line((left + int(w * 0.060), title_panel[1] + int(unit * 0.022), right - int(w * 0.060), title_panel[1] + int(unit * 0.022)), fill=(*accent2, 172), width=max(3, unit // 210))

    if len(lines) > 2:
        _draw_editorial_big_title(draw, lines[0], (left, int(h * 0.332), right, int(h * 0.420)), unit=unit, fill=(211, 237, 241), align="center", max_ratio=0.078, min_ratio=0.036, max_lines=1)
        _draw_editorial_big_title(draw, lines[1], (left, int(h * 0.430), right, int(h * 0.526)), unit=unit, fill=paper, align="center", max_ratio=0.096, min_ratio=0.042, max_lines=1)
        _draw_editorial_big_title(draw, lines[2], (left, int(h * 0.526), right, int(h * 0.612)), unit=unit, fill=paper, align="center", max_ratio=0.090, min_ratio=0.040, max_lines=1)
    else:
        _draw_editorial_big_title(draw, lines[0], (left, int(h * 0.342), right, int(h * 0.462)), unit=unit, fill=(211, 237, 241), align="center", max_ratio=0.092, min_ratio=0.042, max_lines=1)
        _draw_editorial_big_title(draw, lines[1] or lines[0], (left, int(h * 0.470), right, int(h * 0.568)), unit=unit, fill=paper, align="center", max_ratio=0.106, min_ratio=0.048, max_lines=1)

    rule_y = int(h * 0.678)
    gap = int(w * 0.110)
    draw.line((left + int(w * 0.065), rule_y, w // 2 - gap, rule_y), fill=(*accent, 150), width=max(1, unit // 620))
    draw.line((w // 2 + gap, rule_y, right - int(w * 0.065), rule_y), fill=(*accent, 150), width=max(1, unit // 620))
    _draw_refined_brand_signature(draw, img, (int(w * 0.410), int(h * 0.830), int(w * 0.640), int(h * 0.890)), brand_name=brand_name)

    img = _add_subtle_grain(img, opacity=1)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(out_path, quality=95)
    return True


def _render_literary_free_cover(
    img: Image.Image,
    out_path: Path,
    *,
    fitted: Image.Image,
    display_title: str,
    marketing_tag: str,
    book_author_line: str,
    chapter_episode_line: str,
    brand_name: str,
    brand_slogan: str,
    mag_profile: dict[str, Any] | None = None,
) -> bool:
    draw = ImageDraw.Draw(img, "RGBA")
    w, h = img.size
    unit = min(w, h)
    plain = _editorial_plain_style()
    profile = mag_profile or _magazine_profile_for_context(display_title, marketing_tag, book_author_line, chapter_episode_line)
    paper = _profile_rgb(profile, "paper", (247, 240, 232))
    accent = _profile_rgb(profile, "accent", (132, 105, 158))
    accent2 = _profile_rgb(profile, "accent2", (197, 125, 91))

    _add_luxury_scrims(img, top_alpha=56, bottom_alpha=96, center_alpha=4)
    _draw_poster_glow(img, (int(w * 0.28), int(h * 0.36)), int(unit * 0.54), color=accent, alpha=13)
    _draw_poster_glow(img, (int(w * 0.72), int(h * 0.56)), int(unit * 0.46), color=accent2, alpha=10)
    left = int(w * 0.082)
    right = int(w * 0.918)
    _draw_magazine_identity(draw, img, profile=profile, box=(left, int(h * 0.032), right, int(h * 0.088)), unit=unit, light=True)

    if w > h:
        scene_box = (int(w * 0.055), int(h * 0.170), int(w * 0.440), int(h * 0.845))
        text_left = int(w * 0.480)
        text_right = int(w * 0.925)
        book_box = (text_left, int(h * 0.145), text_right, int(h * 0.205))
        epi_box = (text_left, int(h * 0.214), text_right, int(h * 0.270))
        title_top = int(h * 0.330)
    else:
        scene_box = (int(w * 0.105), int(h * 0.170), int(w * 0.555), int(h * 0.440))
        text_left = int(w * 0.155)
        text_right = int(w * 0.885)
        book_box = (int(w * 0.460), int(h * 0.186), right, int(h * 0.250))
        epi_box = (int(w * 0.460), int(h * 0.258), right, int(h * 0.324))
        title_top = int(h * 0.478)

    scene_w, scene_h = scene_box[2] - scene_box[0], scene_box[3] - scene_box[1]
    scene = _crop_to_ratio(fitted.convert("RGB"), (scene_w, scene_h), focus_y=0.52, focus_x=0.48).resize((scene_w, scene_h), Image.Resampling.LANCZOS)
    scene = ImageEnhance.Brightness(scene).enhance(1.06)
    scene = ImageEnhance.Contrast(scene).enhance(1.05).convert("RGBA")
    scene.alpha_composite(Image.new("RGBA", (scene_w, scene_h), (*accent, 20)))
    mask = Image.new("L", (scene_w, scene_h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, scene_w, scene_h), radius=int(unit * 0.018), fill=230)
    img.paste(scene, (scene_box[0], scene_box[1]), mask)
    draw.rounded_rectangle(scene_box, radius=int(unit * 0.018), outline=(*paper, 58), width=max(1, unit // 760))
    draw.line((scene_box[0] - int(unit * 0.020), scene_box[1] + int(unit * 0.035), scene_box[0] - int(unit * 0.020), scene_box[3] - int(unit * 0.035)), fill=(*accent2, 190), width=max(3, unit // 190))

    if book_author_line:
        _draw_left(draw, _poster_no_period(book_author_line), book_box, fill=(248, 239, 226), max_size=int(unit * 0.044), min_size=int(unit * 0.020), max_lines=1, style=plain, font_role="book")
    if chapter_episode_line:
        _draw_left(draw, _poster_no_period(chapter_episode_line), epi_box, fill=(225, 202, 214), max_size=int(unit * 0.036), min_size=int(unit * 0.018), max_lines=1, style=plain, font_role="meta")

    lines = _cover_title_lines_for_magazine(display_title, max_lines=3)
    panel = (text_left - int(unit * 0.030), title_top - int(unit * 0.028), text_right + int(unit * 0.016), int(title_top + unit * (0.360 if len(lines) > 2 else 0.300)))
    _add_luxury_text_field(img, panel, alpha=24, border_alpha=0, radius=int(unit * 0.012), blur=max(16, unit // 56))
    title_left = text_left + int(unit * 0.012)
    if len(lines) > 2:
        _draw_editorial_big_title(draw, lines[0], (title_left, title_top, text_right, title_top + int(unit * 0.095)), unit=unit, fill=(235, 211, 202), align="left", max_ratio=0.080, min_ratio=0.034, max_lines=1)
        _draw_editorial_big_title(draw, lines[1], (title_left, title_top + int(unit * 0.104), text_right, title_top + int(unit * 0.218)), unit=unit, fill=paper, align="left", max_ratio=0.096, min_ratio=0.038, max_lines=1)
        _draw_editorial_big_title(draw, lines[2], (title_left, title_top + int(unit * 0.214), text_right, title_top + int(unit * 0.330)), unit=unit, fill=paper, align="left", max_ratio=0.096, min_ratio=0.038, max_lines=1)
    else:
        _draw_editorial_big_title(draw, lines[0] if lines else display_title, (title_left, title_top, text_right, title_top + int(unit * 0.130)), unit=unit, fill=(235, 211, 202), align="left", max_ratio=0.092, min_ratio=0.038, max_lines=1)
        _draw_editorial_big_title(draw, lines[1] if len(lines) > 1 else (lines[0] if lines else display_title), (title_left, title_top + int(unit * 0.138), text_right, title_top + int(unit * 0.270)), unit=unit, fill=paper, align="left", max_ratio=0.106, min_ratio=0.044, max_lines=1)

    if marketing_tag and w > h:
        _draw_left(draw, _poster_no_period(marketing_tag), (text_left, int(h * 0.735), text_right, int(h * 0.830)), fill=(245, 231, 218), max_size=int(unit * 0.030), min_size=int(unit * 0.016), max_lines=2, style=plain, font_role="slogan")
    _draw_refined_brand_signature(draw, img, (int(w * (0.740 if w > h else 0.405)), int(h * 0.838), int(w * (0.925 if w > h else 0.655)), int(h * 0.898)), brand_name=brand_name)

    img = _add_subtle_grain(img, opacity=1)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(out_path, quality=95)
    return True


def _render_social_science_wide_cover(
    img: Image.Image,
    out_path: Path,
    *,
    display_title: str,
    book_author_line: str,
    chapter_episode_line: str,
    brand_name: str,
    brand_slogan: str,
    mag_profile: dict[str, Any] | None = None,
) -> bool:
    draw = ImageDraw.Draw(img, "RGBA")
    w, h = img.size
    unit = min(w, h)
    plain = _editorial_plain_style()
    profile = mag_profile or _magazine_profile_for_context(display_title, book_author_line, chapter_episode_line)
    paper = _profile_rgb(profile, "paper", (252, 248, 238))
    warm = _profile_rgb(profile, "accent", (232, 118, 48))
    accent2 = _profile_rgb(profile, "accent2", (76, 138, 154))

    display_title = _poster_no_period(display_title)
    book_author_line = _poster_no_period(book_author_line)
    chapter_episode_line = _poster_no_period(chapter_episode_line)
    _add_luxury_scrims(img, top_alpha=46, bottom_alpha=88, center_alpha=5)
    _draw_poster_glow(img, (int(w * 0.18), int(h * 0.42)), int(unit * 0.70), color=warm, alpha=12)
    _draw_poster_glow(img, (int(w * 0.78), int(h * 0.40)), int(unit * 0.62), color=accent2, alpha=10)

    left = int(w * 0.070)
    right = int(w * 0.760)
    _draw_magazine_identity(draw, img, profile=profile, box=(left, int(h * 0.046), right, int(h * 0.118)), unit=unit, light=True)
    top_rule = int(h * 0.108)
    draw.line((left, top_rule, left + int(w * 0.26), top_rule), fill=(250, 230, 185, 108), width=max(1, unit // 760))
    _draw_left(draw, book_author_line, (left, int(h * 0.134), right, int(h * 0.190)), fill=(250, 242, 224), max_size=int(unit * 0.036), min_size=int(unit * 0.018), max_lines=1, style=plain, font_role="book")
    if chapter_episode_line:
        _draw_left(draw, chapter_episode_line, (left, int(h * 0.205), right, int(h * 0.258)), fill=(255, 190, 104), max_size=int(unit * 0.038), min_size=int(unit * 0.019), max_lines=1, style=plain, font_role="meta")

    title_lines = [line.strip() for line in str(display_title).splitlines() if line.strip()]
    if len(title_lines) < 2:
        title_lines = [part.strip() for part in re.split(r"[，,]", str(display_title), maxsplit=1) if part.strip()]
    if len(title_lines) < 2:
        title_lines = _balanced_poster_title_lines(str(display_title), max_lines=3)
    if len(title_lines) == 2 and re.search(r"[，,]", title_lines[1]) and len(title_lines[1]) >= 7:
        second_parts = [part.strip() for part in re.split(r"[，,]", title_lines[1], maxsplit=1) if part.strip()]
        if len(second_parts) == 2:
            title_lines = [title_lines[0], second_parts[0], second_parts[1]]
    title_box = (left, int(h * 0.335), right, int(h * 0.675))
    title_back = (0, title_box[1] - int(h * 0.065), int(w * 0.72), title_box[3] + int(h * 0.045))
    veil = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    vd = ImageDraw.Draw(veil, "RGBA")
    vd.rounded_rectangle(title_back, radius=int(unit * 0.035), fill=(12, 10, 8, 72))
    veil = veil.filter(ImageFilter.GaussianBlur(max(22, unit // 26)))
    img.alpha_composite(veil)
    line1 = title_lines[0] if title_lines else str(display_title)
    line2 = title_lines[1] if len(title_lines) > 1 else ""
    line3 = title_lines[2] if len(title_lines) > 2 else ""
    title_left = left + int(unit * 0.018)
    if line3:
        _draw_editorial_big_title(draw, line1, (title_left, int(h * 0.336), right, int(h * 0.424)), unit=unit, fill=(248, 220, 178), align="left", max_ratio=0.070, min_ratio=0.030, max_lines=1)
        _draw_editorial_big_title(draw, line2, (title_left, int(h * 0.436), right, int(h * 0.540)), unit=unit, fill=paper, align="left", max_ratio=0.092, min_ratio=0.034, max_lines=1)
        _draw_editorial_big_title(draw, line3, (title_left, int(h * 0.542), right, int(h * 0.654)), unit=unit, fill=paper, align="left", max_ratio=0.092, min_ratio=0.034, max_lines=1)
    else:
        _draw_editorial_big_title(draw, line1, (title_left, int(h * 0.354), right, int(h * 0.470)), unit=unit, fill=(248, 220, 178), align="left", max_ratio=0.078, min_ratio=0.032, max_lines=1)
        _draw_editorial_big_title(draw, line2 or line1, (title_left, int(h * 0.478), right, int(h * 0.632)), unit=unit, fill=paper, align="left", max_ratio=0.104, min_ratio=0.038, max_lines=1)
    draw.line((left, int(h * 0.702), left + int(w * 0.31), int(h * 0.702)), fill=(*warm, 218), width=max(5, unit // 145))
    draw.line((left, int(h * 0.718), left + int(w * 0.18), int(h * 0.718)), fill=(250, 230, 185, 84), width=max(1, unit // 520))

    _draw_refined_brand_signature(draw, img, (int(w * 0.705), int(h * 0.775), int(w * 0.935), int(h * 0.865)), brand_name=brand_name)

    img = _add_subtle_grain(img, opacity=1)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(out_path, quality=95)
    return True


def _render_social_science_vertical_cover(
    img: Image.Image,
    out_path: Path,
    *,
    display_title: str,
    book_author_line: str,
    chapter_episode_line: str,
    brand_name: str,
    brand_slogan: str,
    mag_profile: dict[str, Any] | None = None,
) -> bool:
    draw = ImageDraw.Draw(img, "RGBA")
    w, h = img.size
    unit = min(w, h)
    plain = _editorial_plain_style()
    profile = mag_profile or _magazine_profile_for_context(display_title, book_author_line, chapter_episode_line)
    paper = _profile_rgb(profile, "paper", (252, 248, 238))
    warm = _profile_rgb(profile, "accent", (232, 118, 48))
    accent2 = _profile_rgb(profile, "accent2", (70, 136, 154))

    display_title = _poster_no_period(display_title)
    book_author_line = _poster_no_period(book_author_line)
    chapter_episode_line = _poster_no_period(chapter_episode_line)
    _add_luxury_scrims(img, top_alpha=58, bottom_alpha=98, center_alpha=6)
    _draw_poster_glow(img, (int(w * 0.28), int(h * 0.43)), int(unit * 0.54), color=warm, alpha=12)
    _draw_poster_glow(img, (int(w * 0.76), int(h * 0.50)), int(unit * 0.48), color=accent2, alpha=10)

    left = int(w * 0.090)
    right = int(w * 0.910)
    _draw_magazine_identity(draw, img, profile=profile, box=(left, int(h * 0.030), right, int(h * 0.088)), unit=unit, light=True)
    draw.line((left, int(h * 0.074), right, int(h * 0.074)), fill=(250, 230, 185, 120), width=max(1, unit // 720))
    _draw_centered(draw, book_author_line, (left, int(h * 0.096), right, int(h * 0.164)), fill=(250, 242, 224), max_size=int(unit * 0.056), min_size=int(unit * 0.028), max_lines=1, style=plain, font_role="book")
    if chapter_episode_line:
        _draw_centered(draw, chapter_episode_line, (left, int(h * 0.172), right, int(h * 0.232)), fill=(255, 190, 104), max_size=int(unit * 0.046), min_size=int(unit * 0.022), max_lines=1, style=plain, font_role="meta")

    title_lines = [line.strip() for line in str(display_title).splitlines() if line.strip()]
    if len(title_lines) < 2:
        title_lines = [part.strip() for part in re.split(r"[，,]", str(display_title), maxsplit=1) if part.strip()]
    if len(title_lines) < 2:
        title_lines = _balanced_poster_title_lines(str(display_title), max_lines=3)
    if len(title_lines) == 2 and re.search(r"[，,]", title_lines[1]) and len(title_lines[1]) >= 7:
        second_parts = [part.strip() for part in re.split(r"[，,]", title_lines[1], maxsplit=1) if part.strip()]
        if len(second_parts) == 2:
            title_lines = [title_lines[0], second_parts[0], second_parts[1]]
    line1 = title_lines[0] if title_lines else str(display_title)
    line2 = title_lines[1] if len(title_lines) > 1 else ""
    line3 = title_lines[2] if len(title_lines) > 2 else ""
    panel_top = int(h * 0.318)
    panel_bottom = int(h * (0.620 if line3 else 0.575))
    title_panel = (0, panel_top - int(h * 0.065), right + int(w * 0.030), panel_bottom + int(h * 0.038))
    veil = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    vd = ImageDraw.Draw(veil, "RGBA")
    vd.rounded_rectangle(title_panel, radius=int(unit * 0.040), fill=(12, 10, 8, 78))
    veil = veil.filter(ImageFilter.GaussianBlur(max(24, unit // 24)))
    img.alpha_composite(veil)
    title_left = left + int(unit * 0.018)
    if line3:
        _draw_editorial_big_title(draw, line1, (title_left, int(h * 0.318), right, int(h * 0.405)), unit=unit, fill=(248, 220, 178), align="left", max_ratio=0.088, min_ratio=0.042, max_lines=1)
        _draw_editorial_big_title(draw, line2, (title_left, int(h * 0.414), right, int(h * 0.514)), unit=unit, fill=paper, align="left", max_ratio=0.118, min_ratio=0.054, max_lines=1)
        _draw_editorial_big_title(draw, line3, (title_left, int(h * 0.512), right, int(h * 0.612)), unit=unit, fill=paper, align="left", max_ratio=0.118, min_ratio=0.054, max_lines=1)
    else:
        _draw_editorial_big_title(draw, line1, (title_left, int(h * 0.335), right, int(h * 0.455)), unit=unit, fill=(248, 220, 178), align="left", max_ratio=0.100, min_ratio=0.046, max_lines=1)
        _draw_editorial_big_title(draw, line2 or line1, (title_left, int(h * 0.466), right, int(h * 0.584)), unit=unit, fill=paper, align="left", max_ratio=0.128, min_ratio=0.056, max_lines=1)
    draw.line((left, int(h * 0.652), left + int(w * 0.48), int(h * 0.652)), fill=(*warm, 218), width=max(6, unit // 135))

    _draw_refined_brand_signature(draw, img, (int(w * 0.385), int(h * 0.825), int(w * 0.665), int(h * 0.900)), brand_name=brand_name)

    img = _add_subtle_grain(img, opacity=1)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(out_path, quality=95)
    return True


def _render_luxury_wide_cover(
    img: Image.Image,
    out_path: Path,
    *,
    fitted: Image.Image,
    display_title: str,
    marketing_tag: str,
    book_author_line: str,
    chapter_episode_line: str,
    message_pack: dict[str, str],
    brand_name: str,
    brand_slogan: str,
    mag_profile: dict[str, Any] | None = None,
) -> bool:
    draw = ImageDraw.Draw(img, "RGBA")
    w, h = img.size
    unit = min(w, h)
    plain = _editorial_plain_style()
    profile = mag_profile or _magazine_profile_for_context(display_title, marketing_tag, book_author_line, chapter_episode_line)
    paper = _profile_rgb(profile, "paper", (250, 244, 229))
    warm = _profile_rgb(profile, "accent", (232, 118, 48))
    accent2 = _profile_rgb(profile, "accent2", (80, 132, 150))

    display_title = _poster_no_period(display_title)
    marketing_tag = _poster_no_period(marketing_tag)
    book_author_line = _poster_no_period(book_author_line)
    chapter_episode_line = _poster_no_period(chapter_episode_line)
    _add_luxury_scrims(img, top_alpha=42, bottom_alpha=70, center_alpha=0)
    _draw_poster_glow(img, (int(w * 0.68), int(h * 0.42)), int(unit * 0.56), color=accent2, alpha=16)

    left = int(w * 0.058)
    right = int(w * 0.555)
    top = int(h * 0.088)
    _draw_magazine_identity(draw, img, profile=profile, box=(left, int(h * 0.030), right, int(h * 0.086)), unit=unit, light=True)
    draw.line((left, top, right, top), fill=(242, 214, 162, 118), width=max(1, unit // 700))
    _draw_centered(draw, book_author_line, (left, int(h * 0.112), right, int(h * 0.178)), fill=(252, 246, 232), max_size=int(unit * 0.044), min_size=int(unit * 0.020), max_lines=1, style=plain, font_role="book")
    if chapter_episode_line:
        _draw_centered(draw, chapter_episode_line, (left, int(h * 0.188), right, int(h * 0.244)), fill=(232, 168, 92), max_size=int(unit * 0.040), min_size=int(unit * 0.018), max_lines=1, style=plain, font_role="meta")

    panel_box = (left - int(w * 0.014), int(h * 0.282), right + int(w * 0.008), int(h * 0.662))
    _add_soft_shadow(img, panel_box, int(unit * 0.024), alpha=36, blur=max(22, unit // 18), offset=(0, int(h * 0.010)))
    _add_luxury_text_field(img, panel_box, alpha=46, border_alpha=12, radius=int(unit * 0.020), blur=max(18, unit // 54))
    draw.line((left, panel_box[1] + int(unit * 0.024), left, panel_box[3] - int(unit * 0.024)), fill=(*warm, 204), width=max(4, unit // 170))

    title_lines = [line.strip() for line in str(display_title).splitlines() if line.strip()]
    if len(title_lines) < 2:
        title_lines = [part.strip() for part in re.split(r"[，,]", str(display_title), maxsplit=1) if part.strip()]
    if len(title_lines) < 2:
        title_lines = _balanced_poster_title_lines(str(display_title), max_lines=3)
    if len(title_lines) == 2 and re.search(r"[，,]", title_lines[1]) and len(title_lines[1]) >= 7:
        second_parts = [part.strip() for part in re.split(r"[，,]", title_lines[1], maxsplit=1) if part.strip()]
        if len(second_parts) == 2:
            title_lines = [title_lines[0], second_parts[0] + "，", second_parts[1]]
    title_left = left + int(unit * 0.050)
    title_right = right - int(unit * 0.026)
    line1 = title_lines[0] if title_lines else str(display_title)
    line2 = title_lines[1] if len(title_lines) > 1 else ""
    line3 = title_lines[2] if len(title_lines) > 2 else ""
    if line3:
        _draw_editorial_big_title(draw, line1, (title_left, int(h * 0.316), title_right, int(h * 0.398)), unit=unit, fill=(242, 220, 184), align="left", max_ratio=0.064, min_ratio=0.026, max_lines=1)
        _draw_editorial_big_title(draw, line2, (title_left, int(h * 0.410), title_right, int(h * 0.518)), unit=unit, fill=paper, align="left", max_ratio=0.092, min_ratio=0.034, max_lines=1)
        _draw_editorial_big_title(draw, line3, (title_left, int(h * 0.518), title_right, int(h * 0.630)), unit=unit, fill=paper, align="left", max_ratio=0.092, min_ratio=0.034, max_lines=1)
    else:
        _draw_editorial_big_title(draw, line1, (title_left, int(h * 0.326), title_right, int(h * 0.430)), unit=unit, fill=(242, 220, 184), align="left", max_ratio=0.072, min_ratio=0.028, max_lines=1)
        _draw_editorial_big_title(draw, line2 or line1, (title_left, int(h * 0.438), title_right, int(h * 0.610)), unit=unit, fill=paper, align="left", max_ratio=0.106, min_ratio=0.038, max_lines=1)

    rule_y = int(h * 0.704)
    draw.line((left, rule_y, left + int(w * 0.245), rule_y), fill=(*warm, 218), width=max(5, unit // 160))
    if marketing_tag:
        _draw_left(draw, marketing_tag, (left, int(h * 0.730), right + int(w * 0.010), int(h * 0.842)), fill=(252, 246, 232), max_size=int(unit * 0.036), min_size=int(unit * 0.018), max_lines=2, style=plain, font_role="slogan")

    scene_box = (int(w * 0.595), int(h * 0.100), int(w * 0.940), int(h * 0.865))
    scene_w, scene_h = scene_box[2] - scene_box[0], scene_box[3] - scene_box[1]
    scene = _crop_to_ratio(fitted.convert("RGB"), (scene_w, scene_h), focus_y=0.54, focus_x=0.56).resize((scene_w, scene_h), Image.Resampling.LANCZOS)
    scene = ImageEnhance.Brightness(scene).enhance(1.08)
    scene = ImageEnhance.Contrast(scene).enhance(1.08).convert("RGBA")
    scene.alpha_composite(Image.new("RGBA", (scene_w, scene_h), (255, 255, 255, 10)))
    scene_mask = Image.new("L", (scene_w, scene_h), 0)
    ImageDraw.Draw(scene_mask).rounded_rectangle((0, 0, scene_w, scene_h), radius=int(unit * 0.024), fill=255)
    img.paste(scene, (scene_box[0], scene_box[1]), scene_mask)
    draw.rounded_rectangle(scene_box, radius=int(unit * 0.024), outline=(255, 242, 204, 56), width=max(1, unit // 800))

    logo_zone = (
        scene_box[0] + int(scene_w * 0.09),
        int(h * 0.735),
        scene_box[2] - int(scene_w * 0.09),
        int(h * 0.842),
    )
    _draw_warm_logo_zone(draw, logo_zone, unit, radius_scale=0.018)
    brand_cx = int((logo_zone[0] + logo_zone[2]) / 2)
    brand_y = int((logo_zone[1] + logo_zone[3]) / 2)
    _draw_editorial_logo_badge(draw, img, (brand_cx, brand_y), int(unit * 0.090), show_label=False, brand_name=brand_name, brand_slogan=brand_slogan)

    img = _add_subtle_grain(img, opacity=1)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(out_path, quality=95)
    return True


def _render_luxury_vertical_cover(
    img: Image.Image,
    out_path: Path,
    *,
    fitted: Image.Image,
    display_title: str,
    marketing_tag: str,
    book_author_line: str,
    chapter_episode_line: str,
    message_pack: dict[str, str],
    brand_name: str,
    brand_slogan: str,
    mag_profile: dict[str, Any] | None = None,
) -> bool:
    draw = ImageDraw.Draw(img, "RGBA")
    w, h = img.size
    unit = min(w, h)
    plain = _editorial_plain_style()
    profile = mag_profile or _magazine_profile_for_context(display_title, marketing_tag, book_author_line, chapter_episode_line)
    paper = _profile_rgb(profile, "paper", (252, 248, 238))
    warm = _profile_rgb(profile, "accent", (232, 118, 48))
    accent2 = _profile_rgb(profile, "accent2", (80, 132, 150))
    left = int(w * 0.092)
    right = int(w * 0.908)

    display_title = _poster_no_period(display_title)
    marketing_tag = _poster_no_period(marketing_tag)
    book_author_line = _poster_no_period(book_author_line)
    chapter_episode_line = _poster_no_period(chapter_episode_line)
    _add_luxury_scrims(img, top_alpha=72, bottom_alpha=86, center_alpha=0)
    _draw_poster_glow(img, (int(w * 0.64), int(h * 0.38)), int(unit * 0.42), color=accent2, alpha=14)
    _draw_magazine_identity(draw, img, profile=profile, box=(left, int(h * 0.026), right, int(h * 0.074)), unit=unit, light=True)
    draw.line((left, int(h * 0.068), right, int(h * 0.068)), fill=(242, 214, 162, 104), width=max(1, unit // 720))
    _draw_centered(draw, book_author_line, (left, int(h * 0.082), right, int(h * 0.156)), fill=(252, 246, 232), max_size=int(unit * 0.058), min_size=int(unit * 0.030), max_lines=1, style=plain, font_role="book")
    if chapter_episode_line:
        _draw_centered(draw, chapter_episode_line, (left, int(h * 0.162), right, int(h * 0.224)), fill=(232, 168, 92), max_size=int(unit * 0.044), min_size=int(unit * 0.022), max_lines=1, style=plain, font_role="meta")

    title_lines = [line.strip() for line in str(display_title).splitlines() if line.strip()]
    if len(title_lines) < 2:
        title_lines = [part.strip() for part in re.split(r"[，,]", str(display_title), maxsplit=1) if part.strip()]
    if len(title_lines) < 2:
        title_lines = _balanced_poster_title_lines(str(display_title), max_lines=3)
    if len(title_lines) == 2 and re.search(r"[，,]", title_lines[1]) and len(title_lines[1]) >= 7:
        second_parts = [part.strip() for part in re.split(r"[，,]", title_lines[1], maxsplit=1) if part.strip()]
        if len(second_parts) == 2:
            title_lines = [title_lines[0], second_parts[0] + "，", second_parts[1]]
    line1 = title_lines[0] if title_lines else str(display_title)
    line2 = title_lines[1] if len(title_lines) > 1 else ""
    line3 = title_lines[2] if len(title_lines) > 2 else ""

    panel_bottom = int(h * (0.600 if line3 else 0.548))
    title_panel = (left - int(w * 0.028), int(h * 0.238), right + int(w * 0.012), panel_bottom)
    _add_soft_shadow(img, title_panel, int(unit * 0.032), alpha=22, blur=max(36, unit // 14), offset=(0, int(h * 0.008)))
    _add_luxury_text_field(img, title_panel, alpha=44, border_alpha=10, radius=int(unit * 0.024), blur=max(20, unit // 52))
    draw.line((left, title_panel[1] + int(unit * 0.028), left, title_panel[3] - int(unit * 0.028)), fill=(*warm, 210), width=max(5, unit // 155))
    title_left = left + int(unit * 0.046)
    if line3:
        _draw_editorial_big_title(draw, line1, (title_left, int(h * 0.264), right - int(unit * 0.020), int(h * 0.354)), unit=unit, fill=(242, 220, 184), align="left", max_ratio=0.086, min_ratio=0.042, max_lines=1)
        _draw_editorial_big_title(draw, line2, (title_left, int(h * 0.360), right - int(unit * 0.020), int(h * 0.474)), unit=unit, fill=paper, align="left", max_ratio=0.116, min_ratio=0.052, max_lines=1)
        _draw_editorial_big_title(draw, line3, (title_left, int(h * 0.474), right - int(unit * 0.020), int(h * 0.582)), unit=unit, fill=paper, align="left", max_ratio=0.116, min_ratio=0.052, max_lines=1)
    else:
        _draw_editorial_big_title(draw, line1, (title_left, int(h * 0.270), right - int(unit * 0.020), int(h * 0.398)), unit=unit, fill=(242, 220, 184), align="left", max_ratio=0.096, min_ratio=0.046, max_lines=1)
        _draw_editorial_big_title(draw, line2 or line1, (title_left, int(h * 0.404), right - int(unit * 0.020), int(h * 0.528)), unit=unit, fill=paper, align="left", max_ratio=0.124, min_ratio=0.054, max_lines=1)

    point_top = panel_bottom + int(h * 0.032)
    point_box = (left - int(w * 0.018), point_top, right + int(w * 0.008), min(int(h * 0.742), point_top + int(h * 0.138)))
    if marketing_tag:
        _add_luxury_text_field(img, point_box, alpha=34, border_alpha=8, radius=int(unit * 0.020), blur=max(16, unit // 58))
        draw.line((left, point_box[1] + int(unit * 0.020), left, point_box[3] - int(unit * 0.020)), fill=(*warm, 190), width=max(4, unit // 180))
        _draw_left(draw, marketing_tag, (left + int(unit * 0.040), point_box[1] + int(unit * 0.028), right - int(unit * 0.026), point_box[3] - int(unit * 0.022)), fill=(248, 240, 222), max_size=int(unit * 0.044), min_size=int(unit * 0.024), max_lines=2, style=plain, font_role="slogan")

    brand_size = int(unit * 0.118)
    brand_y = int(h * 0.842)
    logo_zone = (
        int(w * 0.39),
        brand_y - brand_size // 2 - int(unit * 0.022),
        int(w * 0.61),
        brand_y + brand_size // 2 + int(unit * 0.022),
    )
    _draw_warm_logo_zone(draw, logo_zone, unit, radius_scale=0.024)
    _draw_editorial_logo_badge(draw, img, (int(w * 0.50), brand_y), brand_size, show_label=False, brand_name=brand_name, brand_slogan=brand_slogan)

    img = _add_subtle_grain(img, opacity=1)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(out_path, quality=95)
    return True


def _render_luxury_end_card(
    img: Image.Image,
    out_path: Path,
    *,
    book_title: str,
    teaser: str,
    cta: str,
    heading: str,
    brand_name: str,
    brand_slogan: str,
    style: dict[str, Any],
    mag_profile: dict[str, Any] | None = None,
) -> bool:
    draw = ImageDraw.Draw(img, "RGBA")
    w, h = img.size
    unit = min(w, h)
    plain = _editorial_plain_style()
    profile = mag_profile or _magazine_profile_for_context(book_title, teaser, heading)
    paper = _profile_rgb(profile, "paper", (250, 244, 229))
    warm = _profile_rgb(profile, "accent", (232, 118, 48))
    accent2 = _profile_rgb(profile, "accent2", (226, 156, 74))
    is_wide = w > h
    left = int(w * 0.105)
    right = int(w * 0.895)

    teaser = _poster_no_period(teaser)
    cta = _poster_no_period(cta)
    heading = _poster_no_period(heading or "下集预告")
    book_title = normalize_book_title(_poster_no_period(book_title))
    _add_luxury_scrims(img, top_alpha=150, bottom_alpha=176, center_alpha=22)
    _draw_poster_glow(img, (int(w * 0.62), int(h * 0.34)), int(unit * 0.40), color=accent2, alpha=20)
    clean_scene_source = img.copy()

    teaser_title = _poster_title_from_context(teaser, teaser, "")
    if _is_legacy_poster_default(teaser_title) or not teaser_title.strip("？? "):
        teaser_title = _poster_no_period(teaser) or _poster_no_period(heading) or "下集预告"
    teaser_pack = _poster_message_pack(teaser_title, teaser, "")
    parts = [line.strip() for line in str(teaser_title).splitlines() if line.strip()]
    if len(parts) < 2:
        parts = [part.strip() for part in re.split(r"[，,]", teaser_title, maxsplit=1) if part.strip()]
    if len(parts) < 2:
        parts = _balanced_poster_title_lines(teaser_title, max_lines=2)
    line1 = _poster_no_period(parts[0] if parts else teaser_title)
    line2 = _poster_no_period(parts[1] if len(parts) > 1 else "")

    cta_display = cta
    if "点赞" in cta and "分享" in cta and "关注" in cta:
        cta_display = "点赞  ·  分享  ·  关注"
    cta_display = _poster_no_period(cta_display)

    if is_wide:
        left = int(w * 0.080)
        mid = int(w * 0.610)
        right = int(w * 0.925)
        top_rule_y = int(h * 0.112)
        _draw_magazine_identity(draw, img, profile=profile, box=(left, int(h * 0.030), mid, int(h * 0.082)), unit=unit, light=True)
        if book_title:
            _draw_left(draw, f"《{book_title}》", (left, int(h * 0.092), mid, int(h * 0.142)), fill=(238, 220, 188), max_size=int(unit * 0.036), min_size=int(unit * 0.018), max_lines=1, style=plain, font_role="book")
            top_rule_y = int(h * 0.154)
        draw.line((left, top_rule_y, mid - int(w * 0.045), top_rule_y), fill=(218, 166, 94, 145), width=max(1, unit // 700))
        _draw_left(draw, heading, (left, int(h * 0.174), mid, int(h * 0.230)), fill=(*warm, 255), max_size=int(unit * 0.040), min_size=int(unit * 0.020), max_lines=1, style=plain, font_role="meta")

        title_panel = (left - int(w * 0.014), int(h * 0.265), mid, int(h * 0.640))
        _add_soft_shadow(img, title_panel, int(unit * 0.030), alpha=38, blur=max(24, unit // 16), offset=(0, int(h * 0.010)))
        _add_luxury_text_field(img, title_panel, alpha=72, border_alpha=25, radius=int(unit * 0.022), blur=max(12, unit // 72))
        draw.line((left, title_panel[1] + int(unit * 0.026), left, title_panel[3] - int(unit * 0.026)), fill=(*warm, 226), width=max(4, unit // 155))
        title_left = left + int(unit * 0.046)
        title_right = mid - int(unit * 0.040)
        _draw_editorial_big_title(draw, line1, (title_left, int(h * 0.302), title_right, int(h * 0.410)), unit=unit, fill=(242, 220, 184), align="left", max_ratio=0.078, min_ratio=0.034, max_lines=1)
        _draw_editorial_big_title(draw, line2 or line1, (title_left, int(h * 0.424), title_right, int(h * 0.560)), unit=unit, fill=paper, align="left", max_ratio=0.088, min_ratio=0.036, max_lines=1)

        cta_box = (left - int(w * 0.006), int(h * 0.708), mid, int(h * 0.800))
        _add_luxury_text_field(img, cta_box, alpha=58, border_alpha=20, radius=int(unit * 0.017), blur=max(8, unit // 88))
        _draw_centered(draw, cta_display, _inset_box(cta_box, int(unit * 0.030), int(unit * 0.006)), fill=(246, 234, 212), max_size=int(unit * 0.030), min_size=int(unit * 0.016), max_lines=1, style=plain, font_role="cta")

        scene_box = (int(w * 0.655), int(h * 0.175), right, int(h * 0.785))
        scene_w, scene_h = scene_box[2] - scene_box[0], scene_box[3] - scene_box[1]
        scene = _crop_to_ratio(clean_scene_source.convert("RGB"), (scene_w, scene_h), focus_y=0.54, focus_x=0.55).resize((scene_w, scene_h), Image.Resampling.LANCZOS)
        scene = ImageEnhance.Brightness(scene).enhance(1.08)
        scene = ImageEnhance.Contrast(scene).enhance(1.08).convert("RGBA")
        scene.alpha_composite(Image.new("RGBA", (scene_w, scene_h), (8, 7, 6, 44)))
        scene_mask = Image.new("L", (scene_w, scene_h), 0)
        ImageDraw.Draw(scene_mask).rounded_rectangle((0, 0, scene_w, scene_h), radius=int(unit * 0.024), fill=255)
        img.paste(scene, (scene_box[0], scene_box[1]), scene_mask)
        draw.rounded_rectangle(scene_box, radius=int(unit * 0.024), outline=(*accent2, 86), width=max(1, unit // 700))

        logo_zone = (scene_box[0] + int(scene_w * 0.08), int(h * 0.655), scene_box[2] - int(scene_w * 0.08), int(h * 0.765))
        _draw_warm_logo_zone(draw, logo_zone, unit, radius_scale=0.018)
        _draw_editorial_logo_badge(draw, img, ((logo_zone[0] + logo_zone[2]) // 2, (logo_zone[1] + logo_zone[3]) // 2), int(unit * 0.090), show_label=False, brand_name=brand_name, brand_slogan=brand_slogan)

        img = _add_subtle_grain(img, opacity=1)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        img.convert("RGB").save(out_path, quality=95)
        return True

    if book_title:
        _draw_magazine_identity(draw, img, profile=profile, box=(left, int(h * 0.022), right, int(h * 0.076)), unit=unit, light=True)
        _draw_centered(draw, f"《{book_title}》", (left, int(h * 0.084), right, int(h * 0.142)), fill=(238, 220, 188), max_size=int(unit * 0.050), min_size=int(unit * 0.026), max_lines=1, style=plain, font_role="book")
    rule_y = int(h * (0.154 if book_title else 0.136))
    if book_title:
        gap = int(w * 0.180)
        cx = w // 2
        draw.line((left, rule_y, cx - gap, rule_y), fill=(218, 166, 94, 150), width=max(1, unit // 720))
        draw.line((cx + gap, rule_y, right, rule_y), fill=(218, 166, 94, 150), width=max(1, unit // 720))
    else:
        draw.line((left, rule_y, right, rule_y), fill=(218, 166, 94, 150), width=max(1, unit // 720))
    heading_box = (left, int(h * (0.176 if book_title else 0.158)), right, int(h * (0.226 if book_title else 0.208)))
    _draw_left(draw, heading, heading_box, fill=(*warm, 255), max_size=int(unit * 0.048), min_size=int(unit * 0.024), max_lines=1, style=plain, font_role="meta")

    title_panel = (left - int(w * 0.026), int(h * 0.238), right + int(w * 0.010), int(h * 0.515))
    _add_soft_shadow(img, title_panel, int(unit * 0.032), alpha=40, blur=max(30, unit // 16), offset=(0, int(h * 0.008)))
    _add_luxury_text_field(img, title_panel, alpha=74, border_alpha=26, radius=int(unit * 0.024), blur=max(14, unit // 72))
    draw.line((left, title_panel[1] + int(unit * 0.028), left, title_panel[3] - int(unit * 0.028)), fill=(*warm, 226), width=max(5, unit // 155))
    title_left = left + int(unit * 0.046)
    title_right = right - int(unit * 0.050)
    _draw_editorial_big_title(draw, line1, (title_left, int(h * 0.266), title_right, int(h * 0.372)), unit=unit, fill=(242, 220, 184), align="left", max_ratio=0.096, min_ratio=0.044, max_lines=1)
    _draw_editorial_big_title(draw, line2 or line1, (title_left, int(h * 0.386), title_right, int(h * 0.486)), unit=unit, fill=paper, align="left", max_ratio=0.104, min_ratio=0.046, max_lines=1)

    cta_box = (left - int(w * 0.010), int(h * 0.612), right + int(w * 0.010), int(h * 0.695))
    _add_luxury_text_field(img, cta_box, alpha=62, border_alpha=22, radius=int(unit * 0.018), blur=max(10, unit // 88))
    _draw_centered(draw, cta_display, _inset_box(cta_box, int(unit * 0.034), int(unit * 0.008)), fill=(246, 234, 212), max_size=int(unit * 0.030), min_size=int(unit * 0.016), max_lines=2, style=plain, font_role="cta")

    brand_size = int(unit * 0.118)
    brand_y = int(h * 0.842)
    logo_zone = (
        int(w * 0.39),
        brand_y - brand_size // 2 - int(unit * 0.022),
        int(w * 0.61),
        brand_y + brand_size // 2 + int(unit * 0.022),
    )
    _draw_warm_logo_zone(draw, logo_zone, unit, radius_scale=0.024)
    _draw_editorial_logo_badge(draw, img, (int(w * 0.50), brand_y), brand_size, show_label=False, brand_name=brand_name, brand_slogan=brand_slogan)

    img = _add_subtle_grain(img, opacity=1)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(out_path, quality=95)
    return True


def _render_science_center_end_card(
    img: Image.Image,
    out_path: Path,
    *,
    book_title: str,
    teaser: str,
    cta: str,
    heading: str,
    brand_name: str,
    brand_slogan: str,
    mag_profile: dict[str, Any] | None = None,
) -> bool:
    draw = ImageDraw.Draw(img, "RGBA")
    w, h = img.size
    unit = min(w, h)
    plain = _editorial_plain_style()
    profile = mag_profile or _magazine_profile_for_context(book_title, teaser, heading)
    paper = _profile_rgb(profile, "paper", (235, 247, 249))
    accent = _profile_rgb(profile, "accent", (40, 132, 164))
    accent2 = _profile_rgb(profile, "accent2", (210, 118, 96))
    left = int(w * 0.095)
    right = int(w * 0.905)

    _add_luxury_scrims(img, top_alpha=132, bottom_alpha=168, center_alpha=16)
    _draw_poster_glow(img, (w // 2, int(h * 0.440)), int(unit * 0.56), color=accent, alpha=14)
    _draw_science_axis(draw, img, profile=profile, unit=unit)
    _draw_magazine_identity(draw, img, profile=profile, box=(left, int(h * 0.030), right, int(h * 0.086)), unit=unit, light=True)
    if book_title:
        _draw_centered(draw, f"《{normalize_book_title(_poster_no_period(book_title))}》", (left, int(h * 0.118), right, int(h * 0.176)), fill=(222, 242, 246), max_size=int(unit * 0.046), min_size=int(unit * 0.024), max_lines=1, style=plain, font_role="book")
    _draw_centered(draw, _poster_no_period(heading or "下集预告"), (left, int(h * 0.244), right, int(h * 0.304)), fill=(*accent2, 255), max_size=int(unit * 0.050), min_size=int(unit * 0.026), max_lines=1, style=plain, font_role="meta")

    teaser_title = _poster_title_from_context(teaser, teaser, "")
    if _is_legacy_poster_default(teaser_title) or not teaser_title.strip("？? "):
        teaser_title = _poster_no_period(teaser) or _poster_no_period(heading) or "下集预告"
    lines = _cover_title_lines_for_magazine(teaser_title, max_lines=3)
    if len(lines) == 1:
        lines.append("")
    panel = (left - int(w * 0.010), int(h * 0.360), right + int(w * 0.010), int(h * 0.660))
    _add_luxury_text_field(img, panel, alpha=40, border_alpha=18, radius=int(unit * 0.016), blur=max(12, unit // 70))
    draw.line((left + int(w * 0.070), panel[1] + int(unit * 0.026), right - int(w * 0.070), panel[1] + int(unit * 0.026)), fill=(*accent2, 170), width=max(3, unit // 210))
    if len(lines) > 2:
        _draw_editorial_big_title(draw, lines[0], (left, int(h * 0.398), right, int(h * 0.488)), unit=unit, fill=(212, 237, 241), align="center", max_ratio=0.088, min_ratio=0.040, max_lines=1)
        _draw_editorial_big_title(draw, lines[1], (left, int(h * 0.492), right, int(h * 0.574)), unit=unit, fill=paper, align="center", max_ratio=0.092, min_ratio=0.042, max_lines=1)
        _draw_editorial_big_title(draw, lines[2], (left, int(h * 0.574), right, int(h * 0.646)), unit=unit, fill=paper, align="center", max_ratio=0.080, min_ratio=0.036, max_lines=1)
    else:
        _draw_editorial_big_title(draw, lines[0], (left, int(h * 0.410), right, int(h * 0.520)), unit=unit, fill=(212, 237, 241), align="center", max_ratio=0.100, min_ratio=0.044, max_lines=1)
        _draw_editorial_big_title(draw, lines[1] or lines[0], (left, int(h * 0.526), right, int(h * 0.628)), unit=unit, fill=paper, align="center", max_ratio=0.104, min_ratio=0.046, max_lines=1)

    cta_display = "点赞  ·  分享  ·  关注" if "点赞" in cta and "分享" in cta and "关注" in cta else _poster_no_period(cta)
    _draw_centered(draw, cta_display, (left, int(h * 0.720), right, int(h * 0.778)), fill=(230, 239, 239), max_size=int(unit * 0.030), min_size=int(unit * 0.016), max_lines=1, style=plain, font_role="cta")
    _draw_refined_brand_signature(draw, img, (int(w * 0.385), int(h * 0.842), int(w * 0.675), int(h * 0.910)), brand_name=brand_name)

    img = _add_subtle_grain(img, opacity=1)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(out_path, quality=95)
    return True


def _render_literary_free_end_card(
    img: Image.Image,
    out_path: Path,
    *,
    book_title: str,
    teaser: str,
    cta: str,
    heading: str,
    brand_name: str,
    brand_slogan: str,
    mag_profile: dict[str, Any] | None = None,
) -> bool:
    draw = ImageDraw.Draw(img, "RGBA")
    w, h = img.size
    unit = min(w, h)
    plain = _editorial_plain_style()
    profile = mag_profile or _magazine_profile_for_context(book_title, teaser, heading)
    paper = _profile_rgb(profile, "paper", (247, 240, 232))
    accent = _profile_rgb(profile, "accent", (132, 105, 158))
    accent2 = _profile_rgb(profile, "accent2", (197, 125, 91))
    left = int(w * 0.090)
    right = int(w * 0.910)

    _add_luxury_scrims(img, top_alpha=126, bottom_alpha=166, center_alpha=10)
    _draw_poster_glow(img, (int(w * 0.30), int(h * 0.350)), int(unit * 0.48), color=accent, alpha=14)
    _draw_poster_glow(img, (int(w * 0.72), int(h * 0.570)), int(unit * 0.42), color=accent2, alpha=9)
    _draw_magazine_identity(draw, img, profile=profile, box=(left, int(h * 0.032), right, int(h * 0.088)), unit=unit, light=True)
    if book_title:
        _draw_left(draw, f"《{normalize_book_title(_poster_no_period(book_title))}》", (left, int(h * 0.130), right, int(h * 0.190)), fill=(239, 221, 214), max_size=int(unit * 0.046), min_size=int(unit * 0.024), max_lines=1, style=plain, font_role="book")
    _draw_left(draw, _poster_no_period(heading or "下集预告"), (left, int(h * 0.245), right, int(h * 0.310)), fill=(*accent2, 255), max_size=int(unit * 0.060), min_size=int(unit * 0.030), max_lines=1, style=plain, font_role="meta")

    teaser_title = _poster_title_from_context(teaser, teaser, "")
    if _is_legacy_poster_default(teaser_title) or not teaser_title.strip("？? "):
        teaser_title = _poster_no_period(teaser) or _poster_no_period(heading) or "下集预告"
    lines = _cover_title_lines_for_magazine(teaser_title, max_lines=3)
    panel = (left + int(w * 0.035), int(h * 0.358), right + int(w * 0.035), int(h * 0.650))
    _add_luxury_text_field(img, panel, alpha=34, border_alpha=10, radius=int(unit * 0.014), blur=max(12, unit // 64))
    draw.line((left - int(unit * 0.010), panel[1] + int(unit * 0.020), left - int(unit * 0.010), panel[3] - int(unit * 0.020)), fill=(*accent2, 190), width=max(4, unit // 180))
    title_left = left + int(w * 0.075)
    title_right = right - int(w * 0.020)
    if len(lines) > 2:
        _draw_editorial_big_title(draw, lines[0], (title_left, int(h * 0.390), title_right, int(h * 0.480)), unit=unit, fill=(235, 211, 202), align="left", max_ratio=0.088, min_ratio=0.038, max_lines=1)
        _draw_editorial_big_title(draw, lines[1], (title_left, int(h * 0.486), title_right, int(h * 0.570)), unit=unit, fill=paper, align="left", max_ratio=0.090, min_ratio=0.040, max_lines=1)
        _draw_editorial_big_title(draw, lines[2], (title_left, int(h * 0.570), title_right, int(h * 0.638)), unit=unit, fill=paper, align="left", max_ratio=0.078, min_ratio=0.034, max_lines=1)
    else:
        _draw_editorial_big_title(draw, lines[0] if lines else teaser_title, (title_left, int(h * 0.400), title_right, int(h * 0.520)), unit=unit, fill=(235, 211, 202), align="left", max_ratio=0.100, min_ratio=0.044, max_lines=1)
        _draw_editorial_big_title(draw, lines[1] if len(lines) > 1 else (lines[0] if lines else teaser_title), (title_left, int(h * 0.526), title_right, int(h * 0.628)), unit=unit, fill=paper, align="left", max_ratio=0.104, min_ratio=0.046, max_lines=1)

    cta_display = "点赞  ·  分享  ·  关注" if "点赞" in cta and "分享" in cta and "关注" in cta else _poster_no_period(cta)
    _draw_centered(draw, cta_display, (left, int(h * 0.720), right, int(h * 0.790)), fill=(240, 228, 218), max_size=int(unit * 0.030), min_size=int(unit * 0.016), max_lines=2, style=plain, font_role="cta")
    _draw_refined_brand_signature(draw, img, (int(w * 0.380), int(h * 0.840), int(w * 0.680), int(h * 0.910)), brand_name=brand_name)

    img = _add_subtle_grain(img, opacity=1)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(out_path, quality=95)
    return True


def _render_editorial_cover(base_path: Path | None, out_path: Path, meta: dict[str, Any], spec: dict[str, Any], config_payload: dict[str, Any]) -> bool:
    style = _style_config(config_payload)
    controls = _visual_controls(config_payload)
    if not _editorial_enabled(style, "cover"):
        return False
    size = spec["size"]
    platform = spec["platform"]
    is_wide = int(size[0]) > int(size[1])
    content = config_payload.get("content") or {}
    base = _load_base(base_path, (2160, 3840), title=meta.get("book_title") or "")
    fitted = _fit_image_for_asset(base, spec, style)
    if not is_wide:
        fitted = _poster_reframe_vertical(fitted)
    darken = _style_number(style, "cover.editorial_layout.wide_bg_darken" if is_wide else "cover.editorial_layout.vertical_bg_darken", 0.44 if is_wide else 0.50)
    darken = min(darken, 0.28 if is_wide else 0.30)
    img = _editorial_grade(fitted, darken=darken, blur=_style_number(style, "cover.editorial_layout.bg_blur", 1.0), controls=controls).convert("RGBA")
    draw = ImageDraw.Draw(img, "RGBA")
    w, h = size
    unit = min(w, h)
    plain = _editorial_plain_style()
    ink = (54, 36, 28)
    ink_soft = (91, 65, 52)
    paper = (250, 244, 229)
    warm = (236, 112, 45)
    gold = (205, 155, 91)

    book_title = normalize_book_title(_clean_text(str(content.get("book_title") or meta.get("book_title") or "未命名书籍")))
    author = _clean_text(str(content.get("author") or meta.get("author") or ""))
    chapter_no = _clean_text(str(content.get("effective_chapter_no") or content.get("chapter_no_auto") or meta.get("chapter_no") or ""))
    chapter_name = _clean_text(str(content.get("effective_chapter_name") or content.get("chapter_name_auto") or meta.get("chapter_name") or ""))
    episode_no = _clean_text(str(content.get("effective_episode_no") or content.get("episode_no_auto") or content.get("effective_title_episode") or meta.get("episode_label") or ""))
    episode_name = _short_title_main(_clean_text(str(content.get("effective_episode_name") or content.get("episode_name_auto") or content.get("effective_description") or content.get("effective_title_main") or meta.get("hook") or "")))
    if not episode_name:
        episode_name = _clean_text(str(content.get("cover_title_override") or content.get("cover_title_auto") or meta.get("cover_title") or ""))
    display_title = episode_name
    if chapter_name and chapter_name != episode_name and re.search(r"[？?吗为何什么]", chapter_name) and not re.search(r"[？?]$", episode_name):
        display_title = chapter_name
    display_title = _rewrite_text_by_rules(display_title, _get_nested(style, "cover.editorial_layout.title_rewrites", []), book_title=book_title)
    display_title = _poster_title_from_context(display_title, str(meta.get("hook") or content.get("hook") or ""), chapter_name)
    brand_name = _clean_text(str(content.get("brand_name") or meta.get("logo") or BRAND_NAME))
    brand_slogan = _clean_text(str(content.get("brand_slogan") or meta.get("slogan") or BRAND_SLOGAN))
    brand_label = _brand_display_name(brand_name)
    hook_text = str(meta.get("hook") or content.get("hook") or episode_name)
    message_pack = _poster_message_pack(display_title, hook_text, chapter_name)
    marketing_tag = _cover_core_point(display_title, hook_text, chapter_name)
    book_author_line = f"《{book_title}》" if book_title else ""
    chapter_episode_line = _cover_episode_label(chapter_no, chapter_name, episode_no, str(meta.get("episode_title") or ""))
    mag_profile = _magazine_profile_for_context(book_title, display_title, hook_text, chapter_name, marketing_tag)
    profile_kind = _profile_kind(mag_profile)
    _draw_magazine_outer_frame(draw, img, color=_profile_rgb(mag_profile, "accent", warm), accent2=_profile_rgb(mag_profile, "accent2", gold), controls=controls)
    _draw_magazine_micro_marks(draw, img, color=_profile_rgb(mag_profile, "accent", warm), controls=controls)

    if profile_kind == "science":
        return _render_science_center_cover(
            img,
            out_path,
            display_title=display_title,
            book_author_line=book_author_line,
            chapter_episode_line=chapter_episode_line,
            brand_name=brand_name,
            brand_slogan=brand_slogan,
            mag_profile=mag_profile,
        )

    if profile_kind == "social" or _is_social_science_cover_context(book_title, display_title, hook_text, chapter_name):
        if is_wide:
            return _render_social_science_wide_cover(
                img,
                out_path,
                display_title=display_title,
                book_author_line=book_author_line,
                chapter_episode_line=chapter_episode_line,
                brand_name=brand_name,
                brand_slogan=brand_slogan,
                mag_profile=mag_profile,
            )
        return _render_social_science_vertical_cover(
            img,
            out_path,
            display_title=display_title,
            book_author_line=book_author_line,
            chapter_episode_line=chapter_episode_line,
            brand_name=brand_name,
            brand_slogan=brand_slogan,
            mag_profile=mag_profile,
        )

    if profile_kind == "literary":
        return _render_literary_free_cover(
            img,
            out_path,
            fitted=fitted,
            display_title=display_title,
            marketing_tag=marketing_tag,
            book_author_line=book_author_line,
            chapter_episode_line=chapter_episode_line,
            brand_name=brand_name,
            brand_slogan=brand_slogan,
            mag_profile=mag_profile,
        )

    if is_wide:
        return _render_luxury_wide_cover(
            img,
            out_path,
            fitted=fitted,
            display_title=display_title,
            marketing_tag=marketing_tag,
            book_author_line=book_author_line,
            chapter_episode_line=chapter_episode_line,
            message_pack=message_pack,
            brand_name=brand_name,
            brand_slogan=brand_slogan,
            mag_profile=mag_profile,
        )

    return _render_luxury_vertical_cover(
        img,
        out_path,
        fitted=fitted,
        display_title=display_title,
        marketing_tag=marketing_tag,
        book_author_line=book_author_line,
        chapter_episode_line=chapter_episode_line,
        message_pack=message_pack,
        brand_name=brand_name,
        brand_slogan=brand_slogan,
        mag_profile=mag_profile,
    )

    if platform == "wide":
        panel_box = (int(w * 0.042), int(h * 0.085), int(w * 0.568), int(h * 0.900))
        panel_w = panel_box[2]
        _add_soft_shadow(img, panel_box, int(unit * 0.020), alpha=52, blur=max(20, unit // 22), offset=(int(w * 0.010), int(h * 0.008)))
        draw.rounded_rectangle(panel_box, radius=int(unit * 0.020), fill=(248, 242, 229, 244), outline=(214, 170, 106, 110), width=max(1, unit // 560))
        scene_box = (panel_w + int(w * 0.036), int(h * 0.100), w - int(w * 0.050), int(h * 0.895))
        scene_w, scene_h = scene_box[2] - scene_box[0], scene_box[3] - scene_box[1]
        side_scene = _crop_to_ratio(fitted.convert("RGB"), (scene_w, scene_h), focus_y=0.58, focus_x=0.56).resize((scene_w, scene_h), Image.Resampling.LANCZOS)
        side_scene = ImageEnhance.Brightness(side_scene).enhance(1.10)
        side_scene = ImageEnhance.Contrast(side_scene).enhance(1.08).convert("RGBA")
        side_scene.alpha_composite(Image.new("RGBA", (scene_w, scene_h), (10, 9, 8, 44)))
        side_mask = Image.new("L", (scene_w, scene_h), 0)
        ImageDraw.Draw(side_mask).rounded_rectangle((0, 0, scene_w, scene_h), radius=int(unit * 0.020), fill=255)
        img.paste(side_scene, (scene_box[0], scene_box[1]), side_mask)
        draw.rounded_rectangle(scene_box, radius=int(unit * 0.020), outline=(214, 170, 106, 82), width=max(1, unit // 700))
        draw.line((int(w * 0.082), int(h * 0.150), int(w * 0.082), int(h * 0.775)), fill=gold, width=max(2, unit // 350))
        left = int(w * 0.112)
        right = int(w * 0.522)
        if marketing_tag:
            _draw_editorial_pill(draw, (left, int(h * 0.100), left + int(w * 0.220), int(h * 0.158)), marketing_tag, unit=unit, fill=(255, 241, 220, 244), outline=(236, 112, 45, 180), color=(236, 112, 45))
        _draw_left(draw, book_author_line or _cover_main_title_text(book_title), (left, int(h * 0.178), right, int(h * 0.226)), fill=ink_soft, max_size=int(unit * 0.025), min_size=int(unit * 0.014), max_lines=1, style=plain, font_role="book")
        _draw_left(draw, chapter_episode_line or "本集", (left, int(h * 0.238), right, int(h * 0.282)), fill=(118, 82, 62), max_size=int(unit * 0.020), min_size=int(unit * 0.012), max_lines=1, style=plain, font_role="meta")
        _draw_editorial_big_title(draw, display_title, (left, int(h * 0.340), right, int(h * 0.655)), unit=unit, fill=ink, align="left", max_ratio=0.086, min_ratio=0.038, max_lines=3)
        draw.line((left, int(h * 0.705), int(w * 0.480), int(h * 0.705)), fill=warm, width=max(6, unit // 145))
        wide_tagline = str(_get_nested(style, "cover.editorial_layout.wide_tagline", message_pack["wide_tagline"]))
        if wide_tagline:
            _draw_left(draw, wide_tagline, (left, int(h * 0.730), right, int(h * 0.800)), fill=(118, 78, 55), max_size=int(unit * 0.024), min_size=int(unit * 0.015), max_lines=2, style=plain, font_role="slogan")
        wide_note = str(_get_nested(style, "cover.editorial_layout.wide_note", message_pack["wide_note"]))
        if wide_note:
            _draw_left(draw, wide_note, (left, int(h * 0.812), right, int(h * 0.878)), fill=(132, 97, 74), max_size=int(unit * 0.019), min_size=int(unit * 0.012), max_lines=2, style=plain, font_role="body")
        brand_cx = int((scene_box[0] + scene_box[2]) / 2)
        _draw_editorial_logo_badge(draw, img, (brand_cx, int(h * 0.745)), int(unit * 0.120), show_label=False, brand_name=brand_name, brand_slogan=brand_slogan)
    else:
        _draw_poster_glow(img, (int(w * 0.70), int(h * 0.34)), int(unit * 0.34), color=(236, 112, 45), alpha=28)
        draw.rectangle((0, 0, w, h), fill=(10, 9, 8, 16))
        left = int(w * 0.095)
        right = int(w * 0.905)
        _draw_left(draw, book_author_line or _cover_main_title_text(book_title), (left, int(h * 0.112), right, int(h * 0.150)), fill=(234, 207, 166), max_size=int(unit * 0.023), min_size=int(unit * 0.014), max_lines=1, style=plain, font_role="book")
        if chapter_episode_line:
            _draw_editorial_pill(
                draw,
                (left, int(h * 0.168), min(right, left + int(w * 0.66)), int(h * 0.216)),
                chapter_episode_line,
                unit=unit,
                fill=(28, 22, 18, 205),
                outline=(236, 112, 45, 210),
                color=(250, 226, 194),
            )
        title_lines = [line.strip() for line in str(display_title).splitlines() if line.strip()]
        if len(title_lines) < 2:
            title_lines = [part.strip() for part in re.split(r"[，,]", str(display_title), maxsplit=1) if part.strip()]
        if len(title_lines) < 2:
            title_lines = _balanced_poster_title_lines(str(display_title), max_lines=3)
        if len(title_lines) == 2 and re.search(r"[，,]", title_lines[1]) and len(title_lines[1]) >= 7:
            second_parts = [part.strip() for part in re.split(r"[，,]", title_lines[1], maxsplit=1) if part.strip()]
            if len(second_parts) == 2:
                title_lines = [title_lines[0], second_parts[0] + "，", second_parts[1]]
        line1 = title_lines[0]
        line2 = title_lines[1] if len(title_lines) > 1 else title_lines[0]
        line3 = title_lines[2] if len(title_lines) > 2 else ""
        if line3:
            _draw_editorial_big_title(draw, line1, (left, int(h * 0.278), right, int(h * 0.360)), unit=unit, fill=(244, 238, 226), align="left", max_ratio=0.082, min_ratio=0.042, max_lines=1)
            _draw_editorial_big_title(draw, line2, (left, int(h * 0.366), right, int(h * 0.472)), unit=unit, fill=(250, 244, 229), align="left", max_ratio=0.118, min_ratio=0.056, max_lines=1)
            _draw_editorial_big_title(draw, line3, (left, int(h * 0.468), right, int(h * 0.574)), unit=unit, fill=(250, 244, 229), align="left", max_ratio=0.118, min_ratio=0.056, max_lines=1)
            rule_y = int(h * 0.590)
        else:
            _draw_editorial_big_title(draw, line1, (left, int(h * 0.288), right, int(h * 0.390)), unit=unit, fill=(244, 238, 226), align="left", max_ratio=0.092, min_ratio=0.044, max_lines=1)
            _draw_editorial_big_title(draw, line2, (left, int(h * 0.388), right, int(h * 0.522)), unit=unit, fill=(250, 244, 229), align="left", max_ratio=0.124, min_ratio=0.056, max_lines=1)
            rule_y = int(h * 0.548)
        draw.line((left, rule_y, left + int(w * 0.54), rule_y), fill=(236, 112, 45, 228), width=max(6, unit // 130))
        note_title = str(_get_nested(style, "cover.editorial_layout.vertical_note_title", message_pack["note_title"]))
        note_subtitle = str(_get_nested(style, "cover.editorial_layout.vertical_note_subtitle", message_pack["note_subtitle"]))
        note_meta = str(_get_nested(style, "cover.editorial_layout.vertical_note_meta", message_pack["note_meta"]))
        has_note_copy = bool(note_title or note_subtitle or note_meta)
        scene_panel = (left, int(h * 0.620), right, int(h * 0.784))
        scene_w, scene_h = scene_panel[2] - scene_panel[0], scene_panel[3] - scene_panel[1]
        scene = _crop_to_ratio(fitted.convert("RGB"), (scene_w, scene_h), focus_y=0.60, focus_x=0.52).resize((scene_w, scene_h), Image.Resampling.LANCZOS)
        scene = ImageEnhance.Brightness(scene).enhance(1.18)
        scene = ImageEnhance.Contrast(scene).enhance(1.06).convert("RGBA")
        scene.alpha_composite(Image.new("RGBA", (scene_w, scene_h), (12, 9, 7, 94)))
        text_shade = Image.new("RGBA", (scene_w, scene_h), (0, 0, 0, 0))
        shade_draw = ImageDraw.Draw(text_shade, "RGBA")
        shade_draw.rounded_rectangle(
            (
                int(scene_w * 0.000),
                int(scene_h * 0.000),
                int(scene_w * 0.900),
                int(scene_h * 0.500),
            ),
            radius=int(unit * 0.024),
            fill=(10, 7, 5, 132),
        )
        shade_draw.rounded_rectangle(
            (
                int(scene_w * 0.000),
                int(scene_h * 0.455),
                int(scene_w * 0.740),
                int(scene_h * 0.860),
            ),
            radius=int(unit * 0.020),
            fill=(10, 7, 5, 92),
        )
        fade = Image.new("L", (scene_w, scene_h), 0)
        fade_px = fade.load()
        for yy in range(scene_h):
            for xx in range(scene_w):
                left_strength = max(0, 255 - int(xx / max(1, scene_w * 0.78) * 255))
                top_strength = max(0, 255 - int(yy / max(1, scene_h * 0.78) * 255))
                fade_px[xx, yy] = min(255, max(left_strength, top_strength))
        text_shade.putalpha(ImageChops.multiply(text_shade.getchannel("A"), fade))
        scene.alpha_composite(text_shade)
        scene_mask = Image.new("L", (scene_w, scene_h), 0)
        ImageDraw.Draw(scene_mask).rounded_rectangle((0, 0, scene_w, scene_h), radius=int(unit * 0.026), fill=255)
        img.paste(scene, (scene_panel[0], scene_panel[1]), scene_mask)
        draw.rounded_rectangle(scene_panel, radius=int(unit * 0.026), outline=(222, 176, 112, 150), width=max(1, unit // 560))
        draw.rounded_rectangle((left + int(unit * 0.028), scene_panel[1] + int(unit * 0.035), left + int(unit * 0.048), scene_panel[3] - int(unit * 0.035)), radius=int(unit * 0.010), fill=(236, 112, 45, 235))
        if has_note_copy:
            if note_title:
                _draw_left(draw, note_title, (left + int(unit * 0.078), scene_panel[1] + int(unit * 0.050), right - int(unit * 0.042), scene_panel[1] + int(unit * 0.124)), fill=(250, 244, 229), max_size=int(unit * 0.038), min_size=int(unit * 0.020), max_lines=2, style=plain, font_role="slogan")
            if note_subtitle:
                _draw_left(draw, note_subtitle, (left + int(unit * 0.078), scene_panel[1] + int(unit * 0.126), right - int(unit * 0.042), scene_panel[1] + int(unit * 0.180)), fill=(237, 201, 150), max_size=int(unit * 0.027), min_size=int(unit * 0.015), max_lines=2, style=plain, font_role="slogan")
            if note_meta:
                meta_box = (
                    left + int(unit * 0.070),
                    scene_panel[1] + int(unit * 0.176),
                    right - int(unit * 0.036),
                    scene_panel[1] + int(unit * 0.244),
                )
                draw.rounded_rectangle(meta_box, radius=int(unit * 0.014), fill=(14, 10, 8, 118), outline=(255, 255, 255, 18), width=max(1, unit // 900))
                _draw_left(draw, note_meta, (meta_box[0] + int(unit * 0.018), meta_box[1] + int(unit * 0.010), meta_box[2] - int(unit * 0.018), meta_box[3] - int(unit * 0.008)), fill=(224, 190, 144), max_size=int(unit * 0.021), min_size=int(unit * 0.013), max_lines=2, style=plain, font_role="body")
        _draw_editorial_logo_badge(draw, img, (int(w * 0.50), int(h * 0.846)), int(unit * 0.116), show_label=False, brand_name=brand_name, brand_slogan=brand_slogan)

    img = _add_subtle_grain(img, opacity=2)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(out_path, quality=95)
    return True

def _render_editorial_end_card(base_path: Path | None, out_path: Path, meta: dict[str, Any], spec: dict[str, Any], config_payload: dict[str, Any]) -> bool:
    style = _style_config(config_payload)
    controls = _visual_controls(config_payload)
    if not _editorial_enabled(style, "endcard"):
        return False
    content = config_payload.get("content") or {}
    size = spec["size"]
    base = _load_base(base_path, (2160, 3840), title=meta.get("book_title") or "")
    fitted = _poster_reframe_vertical(_fit_image_for_asset(base, spec, style))
    img = _editorial_grade(
        fitted,
        darken=min(_style_number(style, "endcard.editorial_layout.bg_darken", 0.60), 0.40),
        blur=_style_number(style, "endcard.editorial_layout.bg_blur", 1.6),
        controls=controls,
    ).convert("RGBA")
    draw = ImageDraw.Draw(img, "RGBA")
    w, h = size
    unit = min(w, h)
    plain = _editorial_plain_style()
    paper = (250, 244, 229)
    brand_name = _clean_text(str(content.get("brand_name") or meta.get("logo") or BRAND_NAME))
    brand_slogan = _clean_text(str(content.get("brand_slogan") or meta.get("slogan") or BRAND_SLOGAN))
    brand_label = _brand_display_name(brand_name)
    heading = _clean_text(str(content.get("end_heading") or "下集预告"))
    teaser = _extract_teaser_text(str(content.get("next_teaser") or content.get("share_text") or ""), book_title=str(meta.get("book_title") or ""), style=style)
    cta = _clean_text(str(content.get("cta_text") or DEFAULT_CTA_TEXT))
    mag_profile = _magazine_profile_for_context(str(meta.get("book_title") or ""), teaser, heading)
    profile_kind = _profile_kind(mag_profile)
    _draw_magazine_outer_frame(draw, img, color=_profile_rgb(mag_profile, "accent", (232, 118, 48)), accent2=_profile_rgb(mag_profile, "accent2", (80, 132, 150)), controls=controls)
    _draw_magazine_micro_marks(draw, img, color=_profile_rgb(mag_profile, "accent", (232, 118, 48)), controls=controls)

    if profile_kind == "science":
        return _render_science_center_end_card(
            img,
            out_path,
            book_title=str(meta.get("book_title") or ""),
            teaser=teaser,
            cta=cta,
            heading=heading,
            brand_name=brand_name,
            brand_slogan=brand_slogan,
            mag_profile=mag_profile,
        )

    if profile_kind == "literary":
        return _render_literary_free_end_card(
            img,
            out_path,
            book_title=str(meta.get("book_title") or ""),
            teaser=teaser,
            cta=cta,
            heading=heading,
            brand_name=brand_name,
            brand_slogan=brand_slogan,
            mag_profile=mag_profile,
        )

    return _render_luxury_end_card(
        img,
        out_path,
        book_title=str(meta.get("book_title") or ""),
        teaser=teaser,
        cta=cta,
        heading=heading,
        brand_name=brand_name,
        brand_slogan=brand_slogan,
        style=style,
        mag_profile=mag_profile,
    )

    _draw_poster_glow(img, (int(w * 0.28), int(h * 0.35)), int(unit * 0.44), color=(236, 112, 45), alpha=34)
    draw.rectangle((0, 0, w, h), fill=(9, 8, 7, 22))
    left = int(w * 0.105)
    right = int(w * 0.895)
    _draw_editorial_pill(
        draw,
        (left, int(h * 0.080), left + int(w * 0.38), int(h * 0.136)),
        heading,
        unit=unit,
        fill=(28, 22, 18, 214),
        outline=(236, 112, 45, 220),
        color=(250, 226, 194),
    )
    teaser_title = _poster_title_from_context(teaser, teaser, "")
    teaser_pack = _poster_message_pack(teaser_title, teaser, "")
    parts = [line.strip() for line in str(teaser_title).splitlines() if line.strip()]
    if len(parts) < 2:
        parts = [part.strip() for part in re.split(r"[，,]", teaser_title, maxsplit=1) if part.strip()]
    if len(parts) < 2:
        parts = _balanced_poster_title_lines(teaser_title, max_lines=2)
    _draw_editorial_big_title(
        draw,
        parts[0] if parts else teaser_title,
        (left, int(h * 0.212), right, int(h * 0.298)),
        unit=unit,
        fill=(244, 238, 226),
        align="left",
        max_ratio=0.092,
        min_ratio=0.044,
        max_lines=1,
    )
    _draw_editorial_big_title(
        draw,
        parts[1] if len(parts) > 1 else "",
        (left, int(h * 0.300), right, int(h * 0.434)),
        unit=unit,
        fill=paper,
        align="left",
        max_ratio=0.124,
        min_ratio=0.056,
        max_lines=1,
    )
    teaser_sub = str(_get_nested(style, "endcard.editorial_layout.teaser_subtitle", "") or "")
    if not teaser_sub:
        teaser_sub = _clean_text(teaser)
        if teaser_sub == teaser_title:
            teaser_sub = teaser_pack["teaser_subtitle"]
        if len(teaser_sub) > 34:
            teaser_sub = teaser_sub[:34].rstrip("，,。；;：: ") + "。"
    _draw_editorial_pill(
        draw,
        (left, int(h * 0.452), left + int(w * 0.20), int(h * 0.486)),
        "下一集看点",
        unit=unit,
        fill=(24, 18, 14, 198),
        outline=(236, 112, 45, 180),
        color=(250, 226, 194),
    )
    _draw_left(draw, teaser_sub, (left, int(h * 0.492), right, int(h * 0.558)), fill=(220, 184, 142), max_size=int(unit * 0.032), min_size=int(unit * 0.018), max_lines=2, style=plain, font_role="body")
    draw.line((left, int(h * 0.548), left + int(w * 0.56), int(h * 0.548)), fill=(236, 112, 45, 230), width=max(6, unit // 130))
    cta_panel = (left, int(h * 0.598), right, int(h * 0.708))
    draw.rounded_rectangle(cta_panel, radius=int(unit * 0.022), fill=(20, 16, 13, 164), outline=(222, 176, 112, 95), width=max(1, unit // 760))
    cta_display = cta
    if "点赞" in cta and "分享" in cta and "关注" in cta:
        cta_display = "点赞  ·  分享  ·  关注"
    _draw_centered(draw, cta_display, _inset_box(cta_panel, int(unit * 0.032), int(unit * 0.010)), fill=paper, max_size=int(unit * 0.040), min_size=int(unit * 0.018), max_lines=2, style=plain, font_role="cta")
    _draw_editorial_logo_badge(draw, img, (w // 2, int(h * 0.810)), int(unit * 0.120), show_label=False, brand_name=brand_name, brand_slogan=brand_slogan)

    img = _add_subtle_grain(img, opacity=2)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(out_path, quality=95)
    return True

def _split_cover_title(title: str, fallback_episode: str = "", fallback_main: str = "") -> tuple[str, str]:
    text = _clean_text(title)
    episode = _clean_text(fallback_episode)
    main = _clean_text(fallback_main)
    m = re.match(r"^(第[0-9一二三四五六七八九十百]+[期集章回])\s*[｜|:：-]?\s*(.*)$", text)
    if m:
        episode = episode or m.group(1)
        main = m.group(2).strip() or main
    elif "｜" in text:
        left, right = text.split("｜", 1)
        episode = episode or left.strip()
        main = right.strip() or main
    elif text:
        main = text
    main = main.strip("。！？!?；;，,：: ")
    if main and not re.search(r"[？?]$", main) and ("为何" in main or "为什么" in main or "谁" in main or "吗" in main or "不了" in main):
        main += "？"
    return episode, main


def _short_title_main(text: str) -> str:
    # 不截断、不加省略号；AC 排版层会自动缩字号保证完整显示。
    return re.sub(r"\s+", "", _clean_text(text))


def _cover_main_title_text(title: str) -> str:
    text = _clean_text(title) or "未命名标题"
    # 分集封面可能传入“第二章《首辅申时行》”这类目录原名，避免再包一层书名号。
    if "《" in text and "》" in text:
        return text
    if text.startswith("《") and text.endswith("》"):
        return text
    return f"《{text}》"


def _default_layout_config() -> dict[str, Any]:
    layout = deepcopy(DEFAULT_LAYOUT_CONFIG)
    global_spec = load_global_postprocess_spec(create_if_missing=True)
    layout_override = global_spec.get("layout") if isinstance(global_spec.get("layout"), dict) else {}
    if layout_override:
        layout = _merge_dict(layout, layout_override)
    return layout

def _merge_dict(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            result[k] = _merge_dict(result[k], v)
        else:
            result[k] = v
    return result


def _load_or_init_layout_config(config_path: Path, meta: dict[str, Any], spec_rows: list[dict[str, Any]], content: dict[str, Any]) -> dict[str, Any]:
    default_layout = _default_layout_config()
    global_spec = load_global_postprocess_spec(create_if_missing=True)
    default_style = _deep_merge_config(DEFAULT_STYLE_CONFIG, global_spec.get("style") if isinstance(global_spec.get("style"), dict) else {})
    default_assets = global_spec.get("assets") if isinstance(global_spec.get("assets"), dict) else DEFAULT_GLOBAL_POSTPROCESS_SPEC.get("assets", {})
    payload = {
        "说明": "本文件是本集封面/片尾的中间配置。可以单独改 content、layout、style 后重跑后处理或一键重做分集封面，不需要改程序。",
        "meta_preview": meta,
        "spec_check": spec_rows,
        "content": content,
        "assets": default_assets,
        "layout": default_layout,
        "style": default_style,
    }
    if config_path.exists():
        try:
            existing = json.loads(config_path.read_text(encoding="utf-8"))
            if isinstance(existing, dict):
                existing_layout = existing.get("layout")
                existing_style = existing.get("style")
                existing_content = existing.get("content")
                compatibility = global_spec.get("compatibility") if isinstance(global_spec.get("compatibility"), dict) else {}
                # 默认让全局后处理规范覆盖旧的单集配置，避免历史坐标继续导致横版标题偏左、溢出。
                # 如确实需要保留某一集的手工坐标，可在 prompts/05_后处理规范.json 中设：
                # {"compatibility": {"preserve_existing_layout": true, "preserve_existing_style": true}}
                preserve_existing_layout = bool(compatibility.get("preserve_existing_layout", False))
                preserve_existing_style = bool(compatibility.get("preserve_existing_style", False))
                if isinstance(existing_layout, dict) and preserve_existing_layout:
                    payload["layout"] = _merge_dict(default_layout, existing_layout)
                if isinstance(existing_style, dict) and preserve_existing_style:
                    payload["style"] = _deep_merge_config(default_style, existing_style)
                if isinstance(existing_content, dict):
                    merged_content = dict(content)
                    # Preserve user text overrides while refreshing auto fields and global layout/style.
                    for key, value in existing_content.items():
                        if key.endswith("_override") or key in {"follow_text", "share_text", "brand_name", "brand_slogan", "end_heading", "next_teaser", "cta_text"}:
                            if key in {"follow_text", "share_text", "next_teaser", "cta_text"} and _is_legacy_poster_default(str(value)):
                                continue
                            merged_content[key] = value
                    payload["content"] = merged_content
        except Exception:
            pass
    episode, main = _split_cover_title(
        str(payload["content"].get("cover_title_override") or payload["content"].get("cover_title_auto") or meta.get("cover_title") or ""),
        str(payload["content"].get("title_episode_auto") or meta.get("episode_label") or ""),
        str(payload["content"].get("title_main_auto") or ""),
    )
    if payload["content"].get("title_episode_override"):
        episode = str(payload["content"].get("title_episode_override") or "").strip()
    if payload["content"].get("title_main_override"):
        main = str(payload["content"].get("title_main_override") or "").strip()
    main = _short_title_main(main)
    payload["content"]["effective_title_episode"] = episode
    payload["content"]["effective_title_main"] = main
    desc = str(payload["content"].get("description_override") or payload["content"].get("description_auto") or payload["content"].get("title_main_override") or payload["content"].get("title_main_auto") or "").strip()
    payload["content"]["effective_description"] = desc
    payload["content"]["effective_cover_title"] = f"{episode}｜{main}".strip("｜")
    payload["content"]["effective_chapter_no"] = str(payload["content"].get("chapter_no_override") or payload["content"].get("chapter_no_auto") or meta.get("chapter_no") or "").strip()
    payload["content"]["effective_chapter_name"] = str(payload["content"].get("chapter_name_override") or payload["content"].get("chapter_name_auto") or meta.get("chapter_name") or "").strip()
    payload["content"]["effective_episode_no"] = str(payload["content"].get("episode_no_override") or payload["content"].get("episode_no_auto") or episode or "").strip()
    payload["content"]["effective_episode_name"] = str(payload["content"].get("episode_name_override") or payload["content"].get("episode_name_auto") or desc or main or "").strip()
    config_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def _box_from_ratio(layout_box: list[float], w: int, h: int) -> tuple[int, int, int, int]:
    return (int(layout_box[0] * w), int(layout_box[1] * h), int(layout_box[2] * w), int(layout_box[3] * h))


def _inset_box(box: tuple[int, int, int, int], px: int = 0, py: int = 0) -> tuple[int, int, int, int]:
    """Return a smaller text-safe box. Never inverts the rectangle."""
    x1, y1, x2, y2 = box
    px = max(0, int(px))
    py = max(0, int(py))
    if x2 - x1 <= px * 2 + 8:
        px = max(0, (x2 - x1 - 8) // 2)
    if y2 - y1 <= py * 2 + 8:
        py = max(0, (y2 - y1 - 8) // 2)
    return (x1 + px, y1 + py, x2 - px, y2 - py)


def _cover_text_box(box: tuple[int, int, int, int], unit: int, *, level: str = "normal") -> tuple[int, int, int, int]:
    """Inset cover text away from panel borders and from text shadow/stroke."""
    ratios = {
        "book": (0.028, 0.006),
        "small": (0.018, 0.004),
        "normal": (0.026, 0.006),
        "main": (0.034, 0.008),
        "footer": (0.018, 0.004),
    }
    rx, ry = ratios.get(level, ratios["normal"])
    return _inset_box(box, int(unit * rx), int(unit * ry))



def _valid_ratio_box(value: Any) -> bool:
    """Check whether a configured [x1,y1,x2,y2] box is inside the canvas."""
    if not isinstance(value, list) or len(value) != 4:
        return False
    try:
        x1, y1, x2, y2 = [float(v) for v in value]
    except Exception:
        return False
    return 0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1 and (x2 - x1) >= 0.08 and (y2 - y1) >= 0.025


def _repair_cover_layout(layout: dict[str, Any], base_layout: dict[str, Any], platform: str) -> dict[str, Any]:
    """Repair unsafe cover boxes before drawing.

    The GUI lets users edit every coordinate. This guard keeps AC covers from
    overflowing or overlapping when an old/hand-edited config is loaded.
    """
    result: dict[str, Any] = {}
    for key, base_value in base_layout.items():
        value = layout.get(key, base_value)
        result[key] = [float(v) for v in value] if _valid_ratio_box(value) else deepcopy(base_value)

    order = ["book_box", "author_box", "chapter_no_box", "chapter_name_box", "episode_no_box", "episode_name_box", "footer_box"]
    gap = 0.010 if platform != "wide" else 0.008
    last_bottom = -1.0
    for key in order:
        if key not in result:
            continue
        y1, y2 = float(result[key][1]), float(result[key][3])
        if y1 < last_bottom + gap:
            result[key] = deepcopy(base_layout.get(key, result[key]))
            y1, y2 = float(result[key][1]), float(result[key][3])
        if y1 < last_bottom + gap:
            # If even the merged value is unsafe, keep the original height but move it down.
            height = max(0.025, y2 - y1)
            new_y1 = min(0.965 - height, last_bottom + gap)
            result[key][1] = round(new_y1, 4)
            result[key][3] = round(new_y1 + height, 4)
            y2 = float(result[key][3])
        last_bottom = max(last_bottom, y2)
    return result

def _layout_for_cover(config_payload: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    layout = config_payload.get("layout") or {}
    cover_layout = layout.get("cover") or {}
    asset_id = str(spec.get("asset_id") or "")
    platform = str(spec.get("platform") or "")
    candidate = cover_layout.get(asset_id) or cover_layout.get(platform) or cover_layout.get("vertical") or {}
    base_layout = deepcopy(DEFAULT_LAYOUT_CONFIG["cover"].get("wide" if platform == "wide" else "vertical") or {})
    if not isinstance(candidate, dict):
        return base_layout
    # v42 之前的覆盖配置只有 episode/title/book/author/description 五个槽位。
    # 新版封面要显示：书名→作者→章节序号→章节名→集序号→集名称→logo/slogan。
    # 如果直接把旧 episode/title 同时当章节和集数槽位，会出现章节名/集数重叠。
    # 因此：旧配置缺少新版槽位时，使用新版默认槽位，只保留 footer 等不会冲突的自定义项。
    new_keys = {"chapter_no_box", "chapter_name_box", "episode_no_box", "episode_name_box"}
    if not any(k in candidate for k in new_keys):
        merged = dict(base_layout)
        if "footer_box" in candidate:
            merged["footer_box"] = candidate["footer_box"]
        return _repair_cover_layout(merged, base_layout, platform)
    merged = dict(base_layout)
    merged.update(candidate)
    return _repair_cover_layout(merged, base_layout, platform)


def _cover_text_conf(style: dict[str, Any], platform: str) -> dict[str, Any]:
    default = _get_nested(DEFAULT_STYLE_CONFIG, f"cover.text.{platform}", {})
    candidate = _get_nested(style, f"cover.text.{platform}", default)
    conf = dict(candidate) if isinstance(candidate, dict) else dict(default)
    # Safety caps: older override files used oversized book/brand scales for a 5-field layout.
    # In the new 6-field layout they can cause visible overflow, so we clamp them here.
    if platform == "wide":
        caps = {
            "book_max_scale": 0.070, "author_max_scale": 0.034,
            "chapter_no_max_scale": 0.034, "chapter_name_max_scale": 0.050,
            "episode_no_max_scale": 0.034, "episode_name_max_scale": 0.048,
            "episode_max_scale": 0.034, "title_max_scale": 0.050, "description_max_scale": 0.048,
        }
    else:
        caps = {
            "book_max_scale": 0.088, "author_max_scale": 0.040,
            "chapter_no_max_scale": 0.042, "chapter_name_max_scale": 0.064,
            "episode_no_max_scale": 0.042, "episode_name_max_scale": 0.070,
            "episode_max_scale": 0.042, "title_max_scale": 0.064, "description_max_scale": 0.070,
        }
    floors = {
        "book_min_scale": 0.030, "author_min_scale": 0.018,
        "chapter_no_min_scale": 0.018, "chapter_name_min_scale": 0.026,
        "episode_no_min_scale": 0.018, "episode_name_min_scale": 0.026,
        "episode_min_scale": 0.018, "title_min_scale": 0.026, "description_min_scale": 0.026,
    }
    for key, cap in caps.items():
        try:
            conf[key] = min(float(conf.get(key, default.get(key, cap))), cap)
        except Exception:
            conf[key] = min(float(default.get(key, cap)), cap)
    for key, floor in floors.items():
        try:
            conf[key] = max(float(conf.get(key, default.get(key, floor))), floor)
        except Exception:
            conf[key] = max(float(default.get(key, floor)), floor)
    # Keep min lower than max if a legacy config inverted the range.
    for prefix in ["book", "author", "chapter_no", "chapter_name", "episode_no", "episode_name", "episode", "title", "description"]:
        max_key = f"{prefix}_max_scale"
        min_key = f"{prefix}_min_scale"
        if max_key in conf and min_key in conf:
            try:
                if float(conf[min_key]) > float(conf[max_key]):
                    conf[min_key] = max(0.010, float(conf[max_key]) * 0.55)
            except Exception:
                pass
    return conf


def render_cover(base_path: Path | None, out_path: Path, meta: dict[str, Any], spec: dict[str, Any], config_payload: dict[str, Any]) -> None:
    _render_with_playwright("cover", base_path, out_path, meta, spec, config_payload)
    return
    if _render_editorial_cover(base_path, out_path, meta, spec, config_payload):
        return
    size = spec["size"]
    platform = spec["platform"]
    asset_id = str(spec.get("asset_id") or "")
    content = config_payload.get("content") or {}
    style = _style_config(config_payload)
    base = _load_base(base_path, (2160, 3840), title=meta.get("book_title") or "")
    fitted = _fit_image_for_asset(base, spec, style)
    img = _apply_cover_tint(fitted, style).convert("RGBA")
    draw = ImageDraw.Draw(img, "RGBA")
    w, h = size
    unit = min(w, h)
    _draw_border(draw, w, h, style)
    _draw_ornaments(draw, w, h, style, area="cover")

    book_title = normalize_book_title(_clean_text(str(content.get("book_title") or meta.get("book_title") or "未命名书籍")))
    author = _clean_text(str(content.get("author") or meta.get("author") or ""))
    chapter_no = _clean_text(str(content.get("effective_chapter_no") or content.get("chapter_no_auto") or meta.get("chapter_no") or ""))
    chapter_name = _clean_text(str(content.get("effective_chapter_name") or content.get("chapter_name_auto") or meta.get("chapter_name") or ""))
    episode_no = _clean_text(str(content.get("effective_episode_no") or content.get("episode_no_auto") or content.get("effective_title_episode") or meta.get("episode_label") or ""))
    episode_name = _short_title_main(_clean_text(str(content.get("effective_episode_name") or content.get("episode_name_auto") or content.get("effective_description") or content.get("effective_title_main") or meta.get("hook") or "")))
    brand_name = _clean_text(str(content.get("brand_name") or meta.get("logo") or BRAND_NAME))
    brand_slogan = _clean_text(str(content.get("brand_slogan") or meta.get("slogan") or BRAND_SLOGAN))
    boxes = _layout_for_cover(config_payload, spec)
    text_conf = _cover_text_conf(style, platform)

    def box(key: str, fallback: str) -> tuple[int, int, int, int]:
        value = boxes.get(key) or boxes.get(fallback)
        if not value:
            base_layout = DEFAULT_LAYOUT_CONFIG["cover"]["wide" if platform == "wide" else "vertical"]
            value = base_layout.get(key) or base_layout.get(fallback)
        return _box_from_ratio(value, w, h)

    book_box = box("book_box", "book_box")
    author_box = box("author_box", "author_box")
    chapter_no_box = box("chapter_no_box", "episode_box")
    chapter_name_box = box("chapter_name_box", "title_box")
    episode_no_box = box("episode_no_box", "episode_box")
    episode_name_box = box("episode_name_box", "description_box")
    footer_box = box("footer_box", "footer_box")
    _draw_cover_text_plate(draw, img, spec, {"book_box": book_box, "author_box": author_box, "chapter_no_box": chapter_no_box, "chapter_name_box": chapter_name_box, "episode_no_box": episode_no_box, "episode_name_box": episode_name_box, "footer_box": footer_box}, style=style)

    cover_book_color = _style_color(style, "cover_book", (212, 166, 74))
    cover_author_color = _style_color(style, "cover_author", (242, 226, 196))
    cover_episode_color = _style_color(style, "cover_episode", (255, 242, 194))
    cover_title_color = _style_color(style, "cover_description", (246, 236, 214))
    cover_description_color = _style_color(style, "cover_description", (246, 236, 214))

    book_max = int(unit * float(text_conf.get("book_max_scale", 0.064 if platform != "wide" else 0.054)))
    book_min = int(unit * float(text_conf.get("book_min_scale", 0.030 if platform != "wide" else 0.024)))
    author_max = int(unit * float(text_conf.get("author_max_scale", 0.036 if platform != "wide" else 0.030)))
    author_min = int(unit * float(text_conf.get("author_min_scale", 0.020 if platform != "wide" else 0.018)))
    chapter_no_max = int(unit * float(text_conf.get("chapter_no_max_scale", text_conf.get("episode_max_scale", 0.040 if platform != "wide" else 0.032))))
    chapter_no_min = int(unit * float(text_conf.get("chapter_no_min_scale", text_conf.get("episode_min_scale", 0.018))))
    chapter_name_max = int(unit * float(text_conf.get("chapter_name_max_scale", text_conf.get("title_max_scale", 0.058 if platform != "wide" else 0.046))))
    chapter_name_min = int(unit * float(text_conf.get("chapter_name_min_scale", text_conf.get("title_min_scale", 0.028 if platform != "wide" else 0.022))))
    episode_no_max = int(unit * float(text_conf.get("episode_no_max_scale", text_conf.get("episode_max_scale", 0.040 if platform != "wide" else 0.032))))
    episode_no_min = int(unit * float(text_conf.get("episode_no_min_scale", text_conf.get("episode_min_scale", 0.018))))
    episode_name_max = int(unit * float(text_conf.get("episode_name_max_scale", text_conf.get("description_max_scale", 0.052 if platform != "wide" else 0.040))))
    episode_name_min = int(unit * float(text_conf.get("episode_name_min_scale", text_conf.get("description_min_scale", 0.024 if platform != "wide" else 0.019))))
    book_lines = int(text_conf.get("book_max_lines", 1))
    author_lines = int(text_conf.get("author_max_lines", 1))
    chapter_no_lines = int(text_conf.get("chapter_no_max_lines", text_conf.get("episode_max_lines", 1)))
    chapter_name_lines = int(text_conf.get("chapter_name_max_lines", text_conf.get("title_max_lines", 2)))
    episode_no_lines = int(text_conf.get("episode_no_max_lines", text_conf.get("episode_max_lines", 1)))
    episode_name_lines = int(text_conf.get("episode_name_max_lines", text_conf.get("description_max_lines", 2)))

    if book_title:
        _draw_centered(draw, _cover_main_title_text(book_title), _cover_text_box(book_box, unit, level="book"), fill=cover_book_color, max_size=book_max, min_size=book_min, max_lines=book_lines, style=style, font_role="book")
    if author:
        _draw_centered(draw, author, _cover_text_box(author_box, unit, level="small"), fill=cover_author_color, max_size=author_max, min_size=author_min, max_lines=author_lines, style=style, font_role="author")
    sep = _get_nested(style, "cover.separator", {})
    if platform != "wide" and (not isinstance(sep, dict) or sep.get("enabled", True)):
        _draw_separator(draw, author_box[3] + int(h * _style_number(style, "cover.separator.book_offset_y", 0.010)), int(w * _style_number(style, "cover.separator.x1", 0.28)), int(w * _style_number(style, "cover.separator.x2", 0.72)), color=_color(_get_nested(style, "cover.separator.color"), (154, 122, 47, 170)))
    if chapter_no:
        _draw_centered(draw, chapter_no, _cover_text_box(chapter_no_box, unit, level="small"), fill=cover_episode_color, max_size=chapter_no_max, min_size=chapter_no_min, max_lines=chapter_no_lines, style=style, font_role="meta")
    if chapter_name:
        _draw_centered(draw, chapter_name, _cover_text_box(chapter_name_box, unit, level="normal"), fill=cover_title_color, max_size=chapter_name_max, min_size=chapter_name_min, max_lines=chapter_name_lines, style=style, font_role="chapter")
    if episode_no:
        _draw_centered(draw, episode_no, _cover_text_box(episode_no_box, unit, level="small"), fill=cover_episode_color, max_size=episode_no_max, min_size=episode_no_min, max_lines=episode_no_lines, style=style, font_role="meta")
    if episode_name:
        _draw_centered(draw, episode_name, _cover_text_box(episode_name_box, unit, level="main"), fill=cover_description_color, max_size=episode_name_max, min_size=episode_name_min, max_lines=episode_name_lines, style=style, font_role="episode")
    _draw_footer_bar(draw, img, footer_box, wide=(platform == "wide"), brand_name=brand_name, brand_slogan=brand_slogan, style=style)

    img = _add_subtle_grain(img, opacity=_style_int(style, "cover.grain_opacity", 12))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(out_path, quality=95)



def _draw_end_panel(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], style: dict[str, Any], *, fill_key: str = "endcard.panel.fill", outline_key: str = "endcard.panel.outline", width_key: str = "endcard.panel.width_px", radius_key: str = "endcard.panel.radius_scale") -> None:
    """Draw a subtle translucent panel for end-card text blocks."""
    x1, y1, x2, y2 = box
    radius = max(12, int(min(x2 - x1, y2 - y1) * _style_number(style, radius_key, 0.11)))
    draw.rounded_rectangle(
        box,
        radius=radius,
        fill=_color(_get_nested(style, fill_key), (8, 7, 7, 150)),
        outline=_color(_get_nested(style, outline_key), (176, 134, 72, 210)),
        width=max(1, _style_int(style, width_key, 2)),
    )


def _extract_teaser_text(text: str, *, book_title: str = "", style: dict[str, Any] | None = None) -> str:
    """Extract the next-episode teaser from a full closing narration line."""
    value = _clean_text(str(text or ""))
    if re.search(r"口播台词对应内容画面|对应内容画面|待补充|占位|placeholder", value, re.I):
        value = ""
    if not value:
        return "下一期，我们继续把这本书读下去。"
    # Strip common CTA sentence tails so the end-card teaser remains clean.
    for marker in ["喜欢本集", "欢迎点赞", "点赞、分享", "想继续看", "想继续把经典", "如果你也对经典", "欢迎关注【", "记得关注【", "让我们把经典读给你听", "更细的来龙去脉", "想读完整", "想看完整", "下方链接", "原著", "原书", "支持我们", "支持创作"]:
        idx = value.find(marker)
        if idx > 0:
            value = value[:idx].strip(" ；;，,。")
            break
    # Prefer the content after a colon in phrases such as “下一期，我们……看看：xxx”。
    m = re.search(r"(?:下一期|下期)[^：:]{0,80}[：:](.+)$", value)
    if m:
        value = m.group(1).strip(" ；;，,。")
    value = re.sub(r"^(?:下一期|下期|下一集|下集)(?:我们)?(?:一起来|继续)?(?:看|看看|聊聊|读|了解)?[：:，,\s]*", "", value).strip(" ；;，,。")
    value = re.sub(r"^我们(?:一起来|继续)?(?:了解|看看|读)?[：:，,\s]*", "", value).strip(" ；;，,。")
    if not value:
        return f"继续读《{book_title}》后面的关键内容" if book_title else "继续读后面的关键内容"
    return _polish_teaser_title(value, style=style)


def _polish_teaser_title(text: str, *, style: dict[str, Any] | None = None) -> str:
    """Make extracted next-episode text read like a compact poster title."""
    value = _clean_text(text).strip(" ；;，,。")
    if not value:
        return value
    # Keep the common book-club teaser phrasing crisp when the source line is
    # extracted from a longer spoken CTA.
    value = re.sub(r"^(?:下一期|下期|下一集|下集)(?:我们)?(?:一起来|继续)?(?:看|看看)?", "", value).strip(" ；;，,。")
    style = style or DEFAULT_STYLE_CONFIG
    value = _rewrite_text_by_rules(value, _get_nested(style, "endcard.editorial_layout.teaser_rewrites", []))
    if re.search(r"(为什么|为何|凭什么|是不是|能不能|会不会|吗)$", value) and not re.search(r"[？?]$", value):
        value += "？"
    if re.search(r"也不吃饱$", value):
        value = value[:-4].rstrip("，,") + "，也不吃饱？"
    return value


def render_end_card(base_path: Path | None, out_path: Path, meta: dict[str, Any], spec: dict[str, Any], config_payload: dict[str, Any]) -> None:
    _render_with_playwright("endcard", base_path, out_path, meta, spec, config_payload)
    return
    if _render_editorial_end_card(base_path, out_path, meta, spec, config_payload):
        return
    size = spec["size"]
    asset_id = str(spec.get("asset_id") or "C")
    layout = config_payload["layout"]
    style = _style_config(config_payload)
    content = config_payload.get("content") or {}
    base = _load_base(base_path, (2160, 3840), title=meta.get("book_title") or "")
    img = _apply_end_tint(_fit_image_for_asset(base, spec, style), style).convert("RGBA")
    draw = ImageDraw.Draw(img, "RGBA")
    w, h = size
    unit = min(w, h)
    _draw_border(draw, w, h, style)
    _draw_ornaments(draw, w, h, style, area="endcard")
    conf = (layout.get("endcard") or {}).get(asset_id) or (layout.get("endcard") or {}).get("vertical") or {}
    text_conf = _get_nested(style, "endcard.text", {}) if isinstance(_get_nested(style, "endcard.text", {}), dict) else {}
    brand_name = _clean_text(str(content.get("brand_name") or meta.get("logo") or BRAND_NAME))
    brand_slogan = _clean_text(str(content.get("brand_slogan") or meta.get("slogan") or BRAND_SLOGAN))

    # New concise ending-card layout: next preview + CTA + logo/slogan.
    if "heading_box" in conf:
        heading = _clean_text(str(content.get("end_heading") or "下集预告"))
        teaser = _extract_teaser_text(str(content.get("next_teaser") or content.get("share_text") or ""), book_title=str(meta.get("book_title") or ""))
        cta = _clean_text(str(content.get("cta_text") or DEFAULT_CTA_TEXT))

        heading_panel = _box_from_ratio(conf.get("heading_panel", [0.08, 0.115, 0.92, 0.255]), w, h)
        heading_box = _box_from_ratio(conf.get("heading_box", [0.08, 0.12, 0.92, 0.24]), w, h)
        teaser_panel = _box_from_ratio(conf.get("teaser_panel", [0.08, 0.315, 0.92, 0.500]), w, h)
        teaser_box = _box_from_ratio(conf.get("teaser_box", [0.12, 0.340, 0.88, 0.475]), w, h)
        cta_panel = _box_from_ratio(conf.get("cta_panel", [0.08, 0.610, 0.92, 0.735]), w, h)
        cta_box = _box_from_ratio(conf.get("cta_box", [0.12, 0.630, 0.88, 0.715]), w, h)
        footer_box = _box_from_ratio(conf.get("footer_box", [0.08, 0.805, 0.92, 0.930]), w, h)

        _draw_end_panel(draw, heading_panel, style, fill_key="endcard.heading_panel.fill", outline_key="endcard.heading_panel.outline", width_key="endcard.heading_panel.width_px", radius_key="endcard.heading_panel.radius_scale")
        _draw_separator(draw, heading_box[3] + int(h * _style_number(style, "endcard.separators.heading_offset_y", 0.012)), int(w * _style_number(style, "endcard.separators.heading_x1", 0.30)), int(w * _style_number(style, "endcard.separators.heading_x2", 0.70)), color=_color(_get_nested(style, "endcard.separators.color"), (154, 122, 47, 150)))
        _draw_centered(
            draw,
            heading,
            _inset_box(heading_box, int(unit * 0.030), int(unit * 0.006)),
            fill=_style_color(style, "end_heading", (235, 188, 95)),
            max_size=int(unit * _conf_float(text_conf, "heading_max_scale", 0.104, cap=0.116, floor=0.056)),
            min_size=int(unit * _conf_float(text_conf, "heading_min_scale", 0.055, cap=0.068, floor=0.032)),
            max_lines=int(text_conf.get("heading_max_lines", 1)),
            style=style,
            font_role="heading",
        )

        _draw_end_panel(draw, teaser_panel, style)
        _draw_centered(
            draw,
            teaser,
            _inset_box(teaser_box, int(unit * 0.040), int(unit * 0.010)),
            fill=_style_color(style, "end_teaser", (248, 238, 218)),
            max_size=int(unit * _conf_float(text_conf, "teaser_max_scale", 0.056, cap=0.062, floor=0.030)),
            min_size=int(unit * _conf_float(text_conf, "teaser_min_scale", 0.030, cap=0.038, floor=0.018)),
            max_lines=int(text_conf.get("teaser_max_lines", 3)),
            style=style,
            font_role="teaser",
        )

        _draw_end_panel(draw, cta_panel, style)
        _draw_centered(
            draw,
            cta,
            _inset_box(cta_box, int(unit * 0.040), int(unit * 0.006)),
            fill=_style_color(style, "end_cta", (248, 238, 218)),
            max_size=int(unit * _conf_float(text_conf, "cta_max_scale", 0.052, cap=0.058, floor=0.028)),
            min_size=int(unit * _conf_float(text_conf, "cta_min_scale", 0.028, cap=0.036, floor=0.016)),
            max_lines=int(text_conf.get("cta_max_lines", 2)),
            style=style,
            font_role="cta",
        )

        # Branded footer: logo + brand + slogan, kept separate from CTA for a cleaner hierarchy.
        _draw_fixed_logo_slogan_footer(draw, img, footer_box, brand_slogan=brand_slogan, style=style)
        img = _add_subtle_grain(img, opacity=_style_int(style, "endcard.grain_opacity", 10))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        img.convert("RGB").save(out_path, quality=95)
        return

    # Backward-compatible legacy layout for old per-episode config files.
    logo_size = int(float(conf.get("logo_size", 0.16)) * unit)
    logo_y = int(float(conf.get("logo_y", 0.1875)) * h)
    icon = _extract_logo_icon(BRAND_LOGO_PATH, logo_size)
    if icon is not None:
        icon_x = (w - logo_size) // 2
        plate_pad = max(6, logo_size // max(1, _style_int(style, "endcard.logo_plate_pad_divisor", 14)))
        draw.ellipse(
            (icon_x - plate_pad, logo_y - plate_pad, icon_x + logo_size + plate_pad, logo_y + logo_size + plate_pad),
            fill=_color(_get_nested(style, "endcard.logo_plate_fill"), (247, 242, 230, 235)),
            outline=_color(_get_nested(style, "endcard.logo_plate_outline"), (184, 144, 86, 235)),
            width=max(2, logo_size // max(1, _style_int(style, "endcard.logo_plate_outline_width_divisor", 30))),
        )
        _paste_rgba(img, icon, (icon_x, logo_y))

    brand_box = _box_from_ratio(conf["brand_box"], w, h)
    slogan_box = _box_from_ratio(conf["slogan_box"], w, h)
    follow_box = _box_from_ratio(conf["follow_box"], w, h)
    share_box = _box_from_ratio(conf["share_box"], w, h)

    _draw_centered(draw, _brand_display_name(brand_name), brand_box, fill=_style_color(style, "end_brand", (212, 166, 74)), max_size=int(unit * _conf_float(text_conf, "brand_max_scale", 0.074, cap=0.080, floor=0.034)), min_size=int(unit * _conf_float(text_conf, "brand_min_scale", 0.034, cap=0.045, floor=0.020)), max_lines=int(text_conf.get("brand_max_lines", 1)), style=style, font_role="meta")

    sep_color = _color(_get_nested(style, "endcard.separators.color"), (154, 122, 47, 130))
    _draw_separator(draw, brand_box[3] + int(h * _style_number(style, "endcard.separators.brand_offset_y", 0.010)), int(w * _style_number(style, "endcard.separators.brand_x1", 0.35)), int(w * _style_number(style, "endcard.separators.brand_x2", 0.65)), color=sep_color)
    _draw_centered(draw, brand_slogan, slogan_box, fill=_style_color(style, "end_slogan", (242, 226, 196)), max_size=int(unit * _conf_float(text_conf, "slogan_max_scale", 0.032, cap=0.036, floor=0.016)), min_size=int(unit * _conf_float(text_conf, "slogan_min_scale", 0.018, cap=0.024, floor=0.010)), max_lines=int(text_conf.get("slogan_max_lines", 1)), style=style)

    follow_text = str(content.get("follow_text") or f"喜欢这锅知识，记得关注{_brand_display_name(brand_name)}呀～")
    share_text = str(content.get("share_text") or "觉得有用的话，也欢迎转给朋友一起慢慢炖")
    _draw_separator(draw, follow_box[1] + int(h * _style_number(style, "endcard.separators.follow_offset_y", -0.010)), int(w * _style_number(style, "endcard.separators.follow_x1", 0.40)), int(w * _style_number(style, "endcard.separators.follow_x2", 0.60)), color=sep_color)
    _draw_centered(draw, follow_text, follow_box, fill=_style_color(style, "end_follow", (248, 238, 218)), max_size=int(unit * _conf_float(text_conf, "follow_max_scale", 0.040, cap=0.044, floor=0.020)), min_size=int(unit * _conf_float(text_conf, "follow_min_scale", 0.020, cap=0.028, floor=0.012)), max_lines=int(text_conf.get("follow_max_lines", 2)), style=style)
    _draw_separator(draw, share_box[1] + int(h * _style_number(style, "endcard.separators.share_offset_y", -0.010)), int(w * _style_number(style, "endcard.separators.share_x1", 0.38)), int(w * _style_number(style, "endcard.separators.share_x2", 0.62)), color=sep_color)
    _draw_centered(draw, share_text, share_box, fill=_style_color(style, "end_share", (238, 220, 184)), max_size=int(unit * _conf_float(text_conf, "share_max_scale", 0.032, cap=0.036, floor=0.016)), min_size=int(unit * _conf_float(text_conf, "share_min_scale", 0.018, cap=0.024, floor=0.010)), max_lines=int(text_conf.get("share_max_lines", 2)), style=style)

    img = _add_subtle_grain(img, opacity=_style_int(style, "endcard.grain_opacity", 10))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(out_path, quality=95)

def create_cover_and_endcards(
    episode_dir: Path,
    base_cover_path: Path | None,
    base_end_path: Path | None,
    *,
    book_title: str,
    author: str,
    episode_title: str,
    hook: str,
    cover_title: str = "",
    next_teaser: str = "",
    chapter_label: str = "",
) -> dict[str, Any]:
    # 分集封面/首页的“章节名”必须来自原书章节标签，不能被“本集标题”覆盖。
    # 旧逻辑在 episode_title 为“第一集：午朝谣言……”时，会把 chapter_name 改成“午朝谣言……”，
    # 导致封面章节名重复/错位。现在：有 chapter_label 时只用它解析章节；没有时才从 episode_title 兜底。
    chapter_source = str(chapter_label or "").strip()
    chapter_name = extract_chapter_name(chapter_source) if chapter_source else extract_chapter_name(str(episode_title or ""))
    episode_match = re.match(r"^(第\s*[0-9一二三四五六七八九十百]+\s*[期集])\s*[：:]?\s*(.*)$", str(episode_title).strip())
    if episode_match:
        episode_label = episode_match.group(1).replace(" ", "")
        if not chapter_source:
            chapter_name = episode_match.group(2).strip() or chapter_name
    else:
        episode_label = ""
    cleaned_hook = clean_prefix(hook, ["切入点：", "hook:", "Hook:"]).strip().rstrip("。！？!?；;，,")
    auto_cover_title = str(cover_title or "").strip()
    if not auto_cover_title:
        auto_cover_title = f"{episode_label}｜{cleaned_hook}".strip("｜") if episode_label and cleaned_hook else (cleaned_hook or episode_label or chapter_name)
    title_episode, title_main = _split_cover_title(auto_cover_title, episode_label, cleaned_hook or chapter_name)
    title_main = _short_title_main(title_main)
    auto_cover_title = f"{title_episode}｜{title_main}".strip("｜")
    chapter_no, chapter_display_name = split_chapter_index_name(chapter_name, fallback_name=chapter_name)
    episode_no, episode_display_name = split_episode_index_name(title_episode, fallback_name=title_main or cleaned_hook or chapter_display_name)
    episode_no = episode_no or title_episode
    episode_display_name = title_main or episode_display_name or cleaned_hook or chapter_display_name
    global_spec = load_global_postprocess_spec(create_if_missing=True)
    brand_name = _brand_value(global_spec, "name", BRAND_NAME)
    brand_slogan = _brand_value(global_spec, "slogan", BRAND_SLOGAN)
    follow_text_default = _brand_value(global_spec, "follow_text", DEFAULT_FOLLOW_TEXT)
    share_text_default = _brand_value(global_spec, "share_text", next_teaser or "下一期内容待更新")
    meta = {
        "book_title": normalize_book_title(book_title),
        "author": author,
        "episode_title": episode_title,
        "chapter_no": chapter_no,
        "chapter_name": chapter_display_name,
        "episode_no": episode_no,
        "episode_name": episode_display_name,
        "episode_label": episode_no,
        "hook": cleaned_hook,
        "cover_title": auto_cover_title,
        "logo": brand_name,
        "slogan": brand_slogan,
    }
    out_dir = episode_dir / "06_封面与片尾"
    out_dir.mkdir(parents=True, exist_ok=True)
    spec_rows = validate_cover_specs()
    shared_base_copy = None
    if base_cover_path and Path(base_cover_path).exists():
        shared_base_copy = out_dir / "A_C共享母图.png"
        try:
            Image.open(base_cover_path).save(shared_base_copy)
        except Exception:
            shared_base_copy = None

    content = {
        "book_title": meta["book_title"],
        "author": author,
        "cover_title_auto": auto_cover_title,
        "cover_title_override": "",
        "title_episode_auto": title_episode,
        "title_main_auto": title_main,
        "title_episode_override": "",
        "title_main_override": "",
        "chapter_no_auto": chapter_no,
        "chapter_name_auto": chapter_display_name,
        "episode_no_auto": episode_no,
        "episode_name_auto": episode_display_name,
        "chapter_no_override": "",
        "chapter_name_override": "",
        "episode_no_override": "",
        "episode_name_override": "",
        "description_auto": episode_display_name or cleaned_hook or chapter_display_name,
        "description_override": "",
        "effective_cover_title": auto_cover_title,
        "effective_title_episode": title_episode,
        "effective_title_main": title_main,
        "effective_description": episode_display_name or cleaned_hook or chapter_display_name,
        "effective_chapter_no": chapter_no,
        "effective_chapter_name": chapter_display_name,
        "effective_episode_no": episode_no,
        "effective_episode_name": episode_display_name,
        "brand_name": brand_name,
        "brand_slogan": brand_slogan,
        "follow_text": follow_text_default,
        "share_text": share_text_default,
        "end_heading": str(_brand_value(global_spec, "end_heading", "下集预告")),
        "next_teaser": _extract_teaser_text(str(next_teaser or share_text_default), book_title=book_title, style=_style_config(global_spec)),
        "cta_text": str(_brand_value(global_spec, "cta_text", DEFAULT_CTA_TEXT)),
    }
    config_path = out_dir / "封面片尾配置.json"
    config_payload = _load_or_init_layout_config(config_path, meta, spec_rows, content)

    cover_files: dict[str, Any] = {}
    end_files: dict[str, Any] = {}
    book_file = _safe_file_component(meta["book_title"] or "未命名书籍")
    for spec in COVER_SPECS:
        asset_id = spec["asset_id"]
        cover_path = out_dir / f"{asset_id}_{book_file}.png"
        render_cover(base_cover_path, cover_path, meta, spec, config_payload)
        cover_files[asset_id] = {
            "key": spec["key"],
            "label": spec["label"],
            "ratio": ratio_string(spec["ratio"]),
            "size": list(spec["size"]),
            "path": str(cover_path),
        }

    end_spec = dict(END_CARD_SPEC)
    end_path = out_dir / f"C_{_safe_file_component(brand_name)}.png"
    render_end_card(base_end_path, end_path, meta, end_spec, config_payload)
    end_files["C"] = {
        "key": end_spec["key"],
        "label": end_spec["label"],
        "ratio": ratio_string(end_spec["ratio"]),
        "size": list(end_spec["size"]),
        "path": str(end_path),
    }

    quality_review = {
        "review_team": {
            "literary_experts": 100,
            "wechat_operators": 100,
            "wechat_viewers": 30,
            "total": 230,
        },
        "one_vote_veto": [
            "100位文学/历史组：不得把经典讲成鸡汤、爽文、权谋八卦、现代职场段子；不得删改原书关键论证或糟蹋原书气质。",
            "100位运营组：封面首屏必须一眼看出核心冲突；标题、封面、A1、C、发布文案必须在同一条传播主线上。",
            "30位观众组：普通观众不读说明也要知道谁遇到什么问题；不得脏乱暗空、文字拥挤、指代不清或看完无法复述。",
        ],
        "visual_checklist": [
            "A1/A2/A01/A02 的标题、书名、章节、本集名没有裁切、溢出、撞框或被 logo 遮挡。",
            "B 系正文图保持 9:16 时间线规格，主体明确、可剪辑、无模型生成文字或水印。",
            "C 片尾预告含义与下一集标题一致，关注/转发引导短、顺、克制。",
            "背景服务本集核心问题，不是随机古风、空泛书桌、纯光效或无关装饰。",
            "缩略图尺寸下仍能读出主标题，底部品牌区不贴边、不喧宾夺主。",
            "画面不靠廉价暗黑、金边堆叠、随机宫殿和空泛光效装高级；每个元素都要能回到本集内容。",
        ],
        "content_checklist": [
            "A1 前 8 秒提出清楚问题，前 45 秒出现具体冲突、人物处境或反常识点。",
            "B 段每 2～3 句至少回到一个人物、事件、制度后果、证据或具体选择。",
            "最后 3 条 B 与 C 连读顺畅，C 先收束本集，再自然引出下一集。",
            "发布包能分别承担：标题抓矛盾、简介讲价值、朋友圈给转发理由、置顶评论引导讨论。",
            "整集至少有一句普通观众能转述给朋友的清楚看点，而不是只剩专业摘要。",
        ],
    }

    spec_path = out_dir / "封面规格检查.json"
    spec_path.write_text(json.dumps(spec_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    quality_path = out_dir / "230人评审质检清单.json"
    quality_path.write_text(json.dumps(quality_review, ensure_ascii=False, indent=2), encoding="utf-8")
    meta_path = out_dir / "封面片尾元数据.json"
    meta_to_save = {
        "meta": meta,
        "spec_check": spec_rows,
        "quality_review": quality_review,
        "shared_ac_base": str(shared_base_copy) if shared_base_copy else "",
        "covers": cover_files,
        "endcards": end_files,
        "config_path": str(config_path),
        "config_payload": config_payload,
    }
    meta_path.write_text(json.dumps(meta_to_save, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "meta": meta,
        "spec_check": spec_rows,
        "shared_ac_base": str(shared_base_copy) if shared_base_copy else "",
        "covers": cover_files,
        "endcards": end_files,
        "meta_path": str(meta_path),
        "spec_path": str(spec_path),
        "quality_path": str(quality_path),
        "config_path": str(config_path),
    }
