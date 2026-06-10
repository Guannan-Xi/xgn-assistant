from __future__ import annotations

import base64
import html
from copy import deepcopy
from pathlib import Path
from typing import Any

BRAND_NAME = "知识慢炖"
BRAND_SLOGAN = "把一本好书，慢慢讲透"
BRAND_LOGO_PATH = Path(__file__).resolve().parent / "assets" / "knowledge_slow_stew_logo.png"


def _brand_display_name(name: str) -> str:
    text = str(name or BRAND_NAME).strip()
    if text.startswith("【") and text.endswith("】"):
        return text
    return f"【{text.strip('【】')}】"


def _episode_display_label(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if "集" in text or "期" in text:
        return text
    return f"第{text}集"


def _is_social_context(*parts: str) -> bool:
    text = " ".join(str(part or "") for part in parts)
    return any(
        word in text
        for word in ("贫穷", "贫困", "穷人", "发展经济学", "小额信贷", "疟疾", "蚊帐", "公共服务", "饥饿", "营养")
    )

DEFAULT_VISUAL_CONTROLS: dict[str, Any] = {
    "preset": "warm_paper",
    "background": {
        "brightness": 1.03,
        "saturation": 0.94,
        "contrast": 0.98,
        "blur_px": 1.2,
        "title_blur_px": 8,
        "vignette": 0.12,
        "top_darken": 0.02,
        "bottom_darken": 0.06,
        "focus_x": 56,
        "focus_y": 48,
    },
    "paper": {"card_opacity": 0.92, "shadow": 0.14, "texture": 0.08},
    "title": {"scale": 1.0, "max_lines_vertical": 2, "max_lines_wide": 2},
    "brand": {
        "show_logo_on_a": False,
        "show_slogan_on_a": False,
        "logo_width_vertical": 200,
        "logo_width_wide": 122,
        "logo_width_end": 210,
    },
    "ornaments": {"frame": True, "paper_texture": True, "leaf": True},
    "composition": {
        "wide_text_side": "left",
        "wide_panel_width_pct": 52,
        "vertical_card_y_pct": 20,
        "vertical_card_h_pct": 36,
    },
}

VISUAL_PRESETS: dict[str, dict[str, Any]] = {
    "warm_paper": {
        "palette": {
            "paper": "#F7EEDC",
            "cream": "#FFF8E8",
            "orange": "#D96B32",
            "brown": "#5A2E22",
            "light_brown": "#9B6A45",
            "olive": "#7E8A5A",
            "bluegray": "#263A4A",
            "line": "#D6B98C",
        }
    },
    "rational_social": {
        "palette": {
            "paper": "#F7EEDC",
            "cream": "#FFF8E8",
            "orange": "#D96B32",
            "brown": "#5A2E22",
            "light_brown": "#9B6A45",
            "olive": "#C9B08A",
            "bluegray": "#263A4A",
            "line": "#D6B98C",
        },
        "background": {"brightness": 0.95, "saturation": 0.88, "contrast": 0.96},
    },
    "olive_reading": {
        "palette": {
            "paper": "#F8F1E6",
            "cream": "#FFF8E8",
            "orange": "#D96B32",
            "brown": "#4F3B2F",
            "light_brown": "#8B6A45",
            "olive": "#6D7D8B",
            "bluegray": "#263A4A",
            "line": "#BFAE8F",
        }
    },
    "humanities_paper": {
        "palette": {
            "paper": "#EFE1C6",
            "cream": "#FFF8E8",
            "orange": "#B88A55",
            "brown": "#5B3A29",
            "light_brown": "#8B5E3C",
            "olive": "#7D6F54",
            "bluegray": "#263A4A",
            "line": "#B88A55",
        }
    },
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any] | None) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _safe_text(value: Any) -> str:
    return html.escape(str(value or "").strip())


def _number(value: Any, default: float, lo: float | None = None, hi: float | None = None) -> float:
    try:
        out = float(value)
    except Exception:
        out = default
    if lo is not None:
        out = max(lo, out)
    if hi is not None:
        out = min(hi, out)
    return out


def _bool(value: Any, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"1", "true", "yes", "on", "是", "开"}:
            return True
        if text in {"0", "false", "no", "off", "否", "关"}:
            return False
    return default


def _hex_to_rgb(value: Any, fallback: str) -> tuple[int, int, int]:
    text = str(value or fallback).strip()
    if text.startswith("#") and len(text) == 7:
        try:
            return (int(text[1:3], 16), int(text[3:5], 16), int(text[5:7], 16))
        except Exception:
            pass
    return (int(fallback[1:3], 16), int(fallback[3:5], 16), int(fallback[5:7], 16))


def _rgba(hex_color: Any, alpha: float, fallback: str = "#000000") -> str:
    r, g, b = _hex_to_rgb(hex_color, fallback)
    return f"rgba({r},{g},{b},{max(0.0, min(1.0, alpha)):.3f})"


def _data_uri(path: Path | None, mime: str = "image/png") -> str:
    if not path or not Path(path).exists():
        return ""
    raw = Path(path).read_bytes()
    return f"data:{mime};base64," + base64.b64encode(raw).decode("ascii")


def _get_nested(config: dict[str, Any] | None, path: str, default: Any = None) -> Any:
    cur: Any = config or {}
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def _content(config_payload: dict[str, Any]) -> dict[str, Any]:
    c = config_payload.get("content")
    return c if isinstance(c, dict) else {}


def _visual(config_payload: dict[str, Any]) -> dict[str, Any]:
    raw = config_payload.get("visual_controls") if isinstance(config_payload, dict) else {}
    raw = raw if isinstance(raw, dict) else {}
    preset = str(raw.get("preset") or DEFAULT_VISUAL_CONTROLS["preset"])
    merged = _deep_merge(DEFAULT_VISUAL_CONTROLS, VISUAL_PRESETS.get(preset, {}))
    return _deep_merge(merged, raw)


def _palette(visual: dict[str, Any]) -> dict[str, str]:
    p = visual.get("palette") if isinstance(visual.get("palette"), dict) else {}
    defaults = VISUAL_PRESETS["warm_paper"]["palette"]
    return {k: str(p.get(k) or defaults[k]) for k in defaults}


def _headline_font() -> str:
    return '"Noto Serif CJK SC","Source Han Serif SC","Songti SC","STSong","SimSun",serif'


def _ui_font() -> str:
    return '"Noto Sans CJK SC","Source Han Sans SC","PingFang SC","Microsoft YaHei",sans-serif'


def _cover_fields(meta: dict[str, Any], config_payload: dict[str, Any]) -> dict[str, str]:
    content = _content(config_payload)
    return {
        "book": str(content.get("book_title") or meta.get("book_title") or ""),
        "author": str(content.get("author") or meta.get("author") or ""),
        "chapter_no": str(content.get("effective_chapter_no") or meta.get("chapter_no") or ""),
        "chapter_name": str(content.get("effective_chapter_name") or meta.get("chapter_name") or ""),
        "episode_no": str(content.get("effective_episode_no") or meta.get("episode_no") or meta.get("episode_label") or ""),
        "episode_name": str(content.get("effective_episode_name") or meta.get("episode_name") or meta.get("hook") or ""),
        "slogan": str(content.get("brand_slogan") or meta.get("slogan") or BRAND_SLOGAN),
        "brand": _brand_display_name(str(content.get("brand_name") or meta.get("logo") or BRAND_NAME)),
    }


def _end_fields(meta: dict[str, Any], config_payload: dict[str, Any]) -> dict[str, str]:
    content = _content(config_payload)
    teaser = str(content.get("next_teaser") or meta.get("next_title") or meta.get("next_teaser") or "下一期内容待更新")
    return {
        "book": str(content.get("book_title") or meta.get("book_title") or ""),
        "heading": str(content.get("end_heading") or "下集预告"),
        "teaser": teaser,
        "cta": str(content.get("cta_text") or "点赞、分享、关注"),
        "slogan": str(content.get("brand_slogan") or meta.get("slogan") or BRAND_SLOGAN),
        "brand": _brand_display_name(str(content.get("brand_name") or meta.get("logo") or BRAND_NAME)),
    }


def _render_html(html_text: str, out_path: Path, size: tuple[int, int], *, device_scale_factor: float = 1.0) -> None:
    from playwright.sync_api import sync_playwright

    w, h = size
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = None
        launch_errors: list[str] = []
        for launch_kwargs in (
            {},
            {"executable_path": "/usr/bin/chromium", "args": ["--no-sandbox", "--disable-dev-shm-usage"]},
            {"channel": "chromium", "args": ["--no-sandbox", "--disable-dev-shm-usage"]},
        ):
            try:
                browser = p.chromium.launch(**launch_kwargs)
                break
            except Exception as exc:
                launch_errors.append(str(exc))
        if browser is None:
            raise RuntimeError("Playwright Chromium 启动失败：" + " | ".join(launch_errors[-3:]))
        page = browser.new_page(
            viewport={"width": int(w), "height": int(h)},
            device_scale_factor=float(device_scale_factor),
            color_scheme="light",
        )
        page.set_content(html_text, wait_until="load")
        page.wait_for_timeout(500)
        page.screenshot(path=str(out_path), type="png")
        browser.close()


def _css_vars(p: dict[str, str], visual: dict[str, Any], *, focus_x: float | None = None, focus_y: float | None = None) -> str:
    bg = visual.get("background") if isinstance(visual.get("background"), dict) else {}
    paper = visual.get("paper") if isinstance(visual.get("paper"), dict) else {}
    fx = _number(focus_x if focus_x is not None else bg.get("focus_x"), 56, 0, 100)
    fy = _number(focus_y if focus_y is not None else bg.get("focus_y"), 48, 0, 100)
    card_alpha = _number(paper.get("card_opacity"), 0.92, 0.55, 0.98)
    shadow = _number(paper.get("shadow"), 0.14, 0, 0.45)
    texture = _number(paper.get("texture"), 0.08, 0, 0.22)
    vars_map = {
        "--paper": p["paper"],
        "--cream": p["cream"],
        "--orange": p["orange"],
        "--brown": p["brown"],
        "--light-brown": p["light_brown"],
        "--olive": p["olive"],
        "--bluegray": p["bluegray"],
        "--line": p["line"],
        "--paper-card": _rgba(p["cream"], card_alpha, "#FFF8E8"),
        "--paper-shadow": _rgba(p["brown"], shadow, "#5A2E22"),
        "--paper-card-soft": _rgba(p["paper"], max(0.78, card_alpha - 0.08), "#F7EEDC"),
        "--line-soft": _rgba(p["line"], 0.78, "#D6B98C"),
        "--texture-alpha": f"{texture:.3f}",
        "--bg-brightness": f"{_number(bg.get('brightness'), 1.03, 0.35, 1.55):.3f}",
        "--bg-saturation": f"{_number(bg.get('saturation'), 0.94, 0, 2.0):.3f}",
        "--bg-contrast": f"{_number(bg.get('contrast'), 0.98, 0.3, 1.8):.3f}",
        "--bg-blur": f"{_number(bg.get('blur_px'), 1.2, 0, 26):.1f}px",
        "--title-blur": f"{_number(bg.get('title_blur_px'), 8, 0, 24):.1f}px",
        "--bg-focus-x": f"{fx:.1f}%",
        "--bg-focus-y": f"{fy:.1f}%",
        "--top-dark": _rgba("#000000", _number(bg.get("top_darken"), 0.02, 0, 0.7), "#000000"),
        "--bottom-dark": _rgba("#000000", _number(bg.get("bottom_darken"), 0.06, 0, 0.7), "#000000"),
        "--vignette": f"{_number(bg.get('vignette'), 0.12, 0, 0.85):.3f}",
    }
    return "; ".join(f"{k}:{v}" for k, v in vars_map.items())


def _bg_image(base_path: Path | None) -> str:
    bg_uri = _data_uri(base_path) if base_path else ""
    if bg_uri:
        return "url(" + bg_uri + ")"
    return "radial-gradient(circle at 62% 36%, #FFF8E8 0%, #F7EEDC 44%, #EAD8B8 100%)"


def _logo_uri() -> str:
    if not BRAND_LOGO_PATH.exists():
        raise FileNotFoundError(f"固定 logo 文件缺失：{BRAND_LOGO_PATH}")
    return _data_uri(BRAND_LOGO_PATH)


def _common_html_head(w: int, h: int) -> str:
    return f'''<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
html, body {{ margin:0; padding:0; width:{w}px; height:{h}px; overflow:hidden; background:var(--paper); }}
body {{ font-family:{_ui_font()}; }}
* {{ box-sizing:border-box; }}
.canvas {{ position:relative; width:{w}px; height:{h}px; overflow:hidden; background:var(--paper); color:var(--brown); }}
.bg, .bg-soft, .paper-wash, .vignette, .texture, .frame {{ position:absolute; inset:0; pointer-events:none; }}
.bg {{ background-size:cover; background-position:var(--bg-focus-x) var(--bg-focus-y); filter:brightness(var(--bg-brightness)) saturate(var(--bg-saturation)) contrast(var(--bg-contrast)) blur(var(--bg-blur)); transform:scale(1.02); opacity:.92; }}
.bg-soft {{ background-size:cover; background-position:var(--bg-focus-x) var(--bg-focus-y); filter:blur(16px) saturate(.9) brightness(1.02); transform:scale(1.08); opacity:.18; }}
.paper-wash {{ background:linear-gradient(180deg, rgba(247,238,220,.72), rgba(247,238,220,.52)), radial-gradient(circle at 22% 16%, rgba(255,248,232,.90), transparent 28%), radial-gradient(circle at 78% 26%, rgba(217,107,50,.10), transparent 22%); }}
.vignette {{ background:radial-gradient(circle at 50% 40%, rgba(255,255,255,0) 0%, rgba(0,0,0,calc(var(--vignette) * .16)) 64%, rgba(0,0,0,calc(var(--vignette) * .38)) 100%), linear-gradient(to bottom, var(--top-dark), rgba(0,0,0,0) 18%, rgba(0,0,0,0) 78%, var(--bottom-dark)); }}
.texture {{ opacity:var(--texture-alpha); mix-blend-mode:multiply; background-image:radial-gradient(circle at 16% 22%, rgba(90,46,34,.22) 0 1px, transparent 1.6px), radial-gradient(circle at 82% 34%, rgba(90,46,34,.18) 0 1px, transparent 1.3px), linear-gradient(0deg, rgba(90,46,34,.05) 0 1px, transparent 1px); background-size:26px 26px, 40px 40px, 100% 7px; }}
.frame {{ inset:2.5%; border:1.5px solid rgba(214,185,140,.82); border-radius:34px; }}
.frame::after {{ content:""; position:absolute; inset:10px; border:1px solid rgba(126,138,90,.18); border-radius:26px; }}
.serif {{ font-family:{_headline_font()}; font-weight:800; }}
.sans {{ font-family:{_ui_font()}; }}
.fit {{ display:flex; align-items:center; justify-content:center; text-align:center; overflow:hidden; -webkit-font-smoothing:antialiased; text-rendering:optimizeLegibility; }}
.fit.left {{ justify-content:flex-start; text-align:left; }}
.paper-card {{ position:relative; background:linear-gradient(180deg, var(--paper-card), var(--paper-card-soft)); border:1.5px solid var(--line-soft); border-radius:40px; box-shadow:0 18px 40px var(--paper-shadow), inset 0 0 0 1px rgba(255,255,255,.46); overflow:hidden; }}
.paper-card::before {{ content:""; position:absolute; inset:0; background:linear-gradient(135deg, rgba(255,255,255,.25), transparent 28%, rgba(217,107,50,.03)); pointer-events:none; }}
.meta-frame {{ position:relative; display:flex; align-items:center; justify-content:center; text-align:center; border:2px solid rgba(214,185,140,.90); border-radius:28px; color:var(--orange); background:rgba(255,248,232,.74); box-shadow:inset 0 0 0 4px rgba(255,248,232,.35); }}
.meta-frame::before, .meta-frame::after {{ content:""; position:absolute; top:50%; width:12px; height:12px; margin-top:-6px; border:2px solid rgba(214,185,140,.85); border-radius:50%; background:var(--paper); }}
.meta-frame::before {{ left:-24px; }}
.meta-frame::after {{ right:-24px; }}
.main-title {{ color:var(--brown); line-height:1.12; text-shadow:0 2px 0 rgba(255,248,232,.55), 0 8px 18px rgba(90,46,34,.10); }}
.underline {{ height:6px; border-radius:999px; background:linear-gradient(90deg, transparent, rgba(217,107,50,.92), rgba(217,107,50,.92), transparent); }}
.logo-circle {{ position:relative; display:flex; align-items:center; justify-content:center; width:var(--size); height:var(--size); border-radius:50%; background:rgba(255,248,232,.92); border:1.5px solid rgba(214,185,140,.85); box-shadow:0 12px 30px rgba(90,46,34,.12), inset 0 0 0 10px rgba(255,255,255,.32); overflow:hidden; }}
.logo-circle::after {{ content:""; position:absolute; inset:14px; border-radius:50%; border:1px solid rgba(214,185,140,.35); }}
.logo-circle img {{ width:142%; max-width:none; height:auto; object-fit:contain; object-position:center top; transform:translateY(-12%); filter:drop-shadow(0 10px 16px rgba(90,46,34,.12)); }}
.brand-name {{ color:var(--brown); font-family:{_headline_font()}; font-weight:800; letter-spacing:.02em; }}
.brand-slogan {{ color:var(--light-brown); font-weight:650; letter-spacing:.04em; }}
.book-line {{ color:var(--brown); font-weight:700; letter-spacing:.04em; }}
.scribble {{ border-radius:999px; background:linear-gradient(90deg, rgba(217,107,50,.92), rgba(217,107,50,.92)); opacity:.95; }}
.social-mask {{ position:absolute; inset:0; pointer-events:none; background:
  linear-gradient(90deg, rgba(12,18,18,.78) 0%, rgba(12,18,18,.58) 34%, rgba(12,18,18,.18) 62%, rgba(12,18,18,.32) 100%),
  radial-gradient(circle at 24% 44%, rgba(255,248,232,.18), transparent 28%),
  radial-gradient(circle at 76% 30%, rgba(217,107,50,.18), transparent 24%);
}}
.social-kicker {{ color:rgba(255,222,164,.92); font-weight:850; letter-spacing:.08em; text-shadow:0 8px 22px rgba(0,0,0,.24); }}
.social-title {{ color:#FFF5DF; line-height:1.05; text-shadow:0 8px 24px rgba(0,0,0,.46), 0 2px 0 rgba(90,46,34,.22); }}
.social-title .warm {{ color:#FFC06A; }}
.social-rule {{ height:7px; border-radius:999px; background:linear-gradient(90deg, #F07A3A, rgba(240,122,58,.72), rgba(240,122,58,0)); box-shadow:0 8px 24px rgba(240,122,58,.24); }}
.social-chip {{ display:inline-flex; align-items:center; justify-content:center; min-width:120px; height:46px; padding:0 22px; border-radius:999px; background:rgba(255,248,232,.16); border:1px solid rgba(255,231,187,.34); color:#FFE3B1; font-weight:800; backdrop-filter:blur(16px); }}
.social-logo {{ position:absolute; display:flex; align-items:center; justify-content:center; border-radius:28px; background:rgba(255,248,232,.82); border:1px solid rgba(255,231,187,.72); box-shadow:0 18px 50px rgba(0,0,0,.20), inset 0 0 0 1px rgba(255,255,255,.48); }}
.social-logo .logo-circle {{ background:transparent; border:0; box-shadow:none; overflow:visible; }}
.social-logo .logo-circle::after {{ display:none; }}
.social-logo .logo-circle img {{ width:100%; height:100%; object-fit:contain; object-position:center; transform:none; filter:drop-shadow(0 8px 14px rgba(90,46,34,.14)); }}
</style>
</head>
'''


def _fit_script() -> str:
    return '''
<script>
function fits(el) { return el.scrollHeight <= el.clientHeight + 2 && el.scrollWidth <= el.clientWidth + 2; }
function fitBox(el) {
  const max = parseInt(el.dataset.max || '48', 10);
  const min = parseInt(el.dataset.min || '14', 10);
  const lines = Math.max(1, parseInt(el.dataset.lines || '1', 10));
  const lh = parseFloat(el.dataset.lh || '1.10');
  el.style.display = '-webkit-box';
  el.style.webkitBoxOrient = 'vertical';
  el.style.webkitLineClamp = String(lines);
  el.style.lineHeight = String(lh);
  el.style.transformOrigin = el.classList.contains('left') ? 'left center' : 'center center';
  for (let size = max; size >= min; size--) {
    el.style.fontSize = size + 'px';
    if (fits(el)) return;
  }
  el.style.fontSize = min + 'px';
  for (let scale = 0.98; scale >= 0.80; scale -= 0.02) {
    el.style.transform = `scaleX(${scale.toFixed(2)})`;
    if (fits(el)) return;
  }
}
(async function() {
  if (document.fonts && document.fonts.ready) { try { await document.fonts.ready; } catch (e) {} }
  document.querySelectorAll('.fit[data-max]').forEach(fitBox);
})();
</script>
</html>
'''


def _ornaments(visual: dict[str, Any]) -> str:
    ornaments = visual.get("ornaments") if isinstance(visual.get("ornaments"), dict) else {}
    parts: list[str] = []
    if _bool(ornaments.get("paper_texture"), True):
        parts.append('<div class="texture"></div>')
    if _bool(ornaments.get("frame"), True):
        parts.append('<div class="frame"></div>')
    return "\n  ".join(parts)


def _split_social_title(title: str) -> tuple[str, str]:
    text = " ".join(str(title or "").strip().split())
    if not text:
        return "", ""
    for sep in ("，", ",", "：", ":", "；", ";"):
        if sep in text:
            left, right = text.split(sep, 1)
            if left.strip() and right.strip():
                return left.strip(), right.strip()
    if len(text) >= 16:
        mid = len(text) // 2
        return text[:mid].strip(), text[mid:].strip()
    return text, ""


def _social_cover_html(
    base_path: Path | None,
    size: tuple[int, int],
    meta: dict[str, Any],
    spec: dict[str, Any],
    config_payload: dict[str, Any],
    fields: dict[str, str],
    visual: dict[str, Any],
    p: dict[str, str],
    css_vars: str,
    bg: str,
    logo_uri: str,
    show_logo: bool,
) -> str:
    w, h = size
    asset_id = str(spec.get("asset_id") or "").upper()
    vertical = h > w
    brand = visual.get("brand") if isinstance(visual.get("brand"), dict) else {}
    title_scale = _number(_get_nested(visual, "title.scale"), 1.0, 0.7, 1.4)
    title_a, title_b = _split_social_title(fields["episode_name"])
    meta_text = _episode_display_label(fields["episode_no"])
    meta_chip = f'''<div class="social-chip social-period">{_safe_text(meta_text)}</div>''' if meta_text else ""
    logo_w = int(_number(brand.get("logo_width_vertical" if vertical else "logo_width_wide"), 128 if vertical else 98, 72, 180))
    logo_block = f'''
  <div class="social-logo {'social-logo-v' if vertical else 'social-logo-w'}">
    <div class="logo-circle" style="--size:{logo_w}px"><img src="{logo_uri}" /></div>
  </div>''' if show_logo else ""
    if vertical:
        title_max_a = max(78, int(min(w, h) * 0.092 * title_scale))
        title_max_b = max(92, int(min(w, h) * 0.118 * title_scale))
        return _common_html_head(w, h) + f'''
<body>
<div class="canvas social-cover social-v {asset_id.lower()}" style="{css_vars}">
  <div class="bg-soft" style="background-image:{bg};"></div>
  <div class="bg" style="background-image:{bg};"></div>
  <div class="social-mask"></div>
  <div class="texture"></div>
  <div class="social-topline"></div>
  <div class="social-book fit book-line" data-max="54" data-min="28" data-lines="1">《{_safe_text(fields['book'])}》</div>
  {meta_chip}
  <div class="social-title-wrap">
    <div class="fit left serif social-title" data-max="{title_max_a}" data-min="44" data-lines="1">{_safe_text(title_a)}</div>
    <div class="fit left serif social-title" data-max="{title_max_b}" data-min="50" data-lines="2" data-lh="1.04">{_safe_text(title_b)}</div>
  </div>
  <div class="social-rule social-rule-v"></div>
  {logo_block}
</div>
<style>
.social-v .bg {{ background-position:50% 56%; filter:brightness(.88) saturate(1.08) contrast(1.06) blur(.4px); transform:scale(1.018); opacity:1; }}
.social-v .bg-soft {{ opacity:.30; filter:blur(24px) saturate(1.08); }}
.social-topline {{ position:absolute; left:9%; right:9%; top:7%; height:1px; background:linear-gradient(90deg, transparent, rgba(255,231,187,.66), transparent); }}
.social-book {{ position:absolute; left:9%; top:9.2%; width:82%; height:78px; color:#FFF4DF; text-shadow:0 8px 22px rgba(0,0,0,.30); }}
.social-period {{ position:absolute; left:9%; top:18%; }}
.social-title-wrap {{ position:absolute; left:9%; right:7%; top:30.0%; height:330px; display:grid; grid-template-rows:.82fr 1.55fr; gap:6px; }}
.social-title-wrap .fit {{ justify-content:flex-start; text-align:left; }}
.social-rule-v {{ position:absolute; left:9%; top:58.2%; width:58%; }}
.social-logo-v {{ left:39%; right:39%; bottom:6.0%; min-height:116px; }}
</style>
</body>
''' + _fit_script()

    title_max_a = max(58, int(min(w, h) * 0.074 * title_scale))
    title_max_b = max(72, int(min(w, h) * 0.090 * title_scale))
    return _common_html_head(w, h) + f'''
<body>
<div class="canvas social-cover social-w {asset_id.lower()}" style="{css_vars}">
  <div class="bg-soft" style="background-image:{bg};"></div>
  <div class="bg" style="background-image:{bg};"></div>
  <div class="social-mask"></div>
  <div class="texture"></div>
  <div class="social-panel">
    <div class="social-book-w fit left book-line" data-max="42" data-min="24" data-lines="1">《{_safe_text(fields['book'])}》</div>
    {f'''<div class="social-chip">{_safe_text(meta_text)}</div>''' if meta_text else ""}
    <div class="social-title-w">
      <div class="fit left serif social-title" data-max="{title_max_a}" data-min="30" data-lines="1">{_safe_text(title_a)}</div>
      <div class="fit left serif social-title" data-max="{title_max_b}" data-min="36" data-lines="1">{_safe_text(title_b)}</div>
    </div>
    <div class="social-rule"></div>
  </div>
  <div class="social-visual-window"></div>
  {logo_block}
</div>
<style>
.social-w .bg {{ background-position:62% 50%; filter:brightness(.90) saturate(1.08) contrast(1.05) blur(.3px); transform:scale(1.018); opacity:1; }}
.social-w .bg-soft {{ opacity:.28; filter:blur(24px) saturate(1.1); }}
.social-panel {{ position:absolute; left:5.8%; top:8%; width:54%; height:80%; display:grid; grid-template-rows:58px 52px 1fr 7px; gap:18px; padding:34px 42px 30px; border-radius:38px; background:linear-gradient(90deg, rgba(11,16,16,.54), rgba(11,16,16,.26)); border:1px solid rgba(255,231,187,.18); box-shadow:0 30px 80px rgba(0,0,0,.18); backdrop-filter:blur(14px); }}
.social-book-w {{ color:#FFF4DF; text-shadow:0 8px 22px rgba(0,0,0,.28); }}
.social-title-w {{ align-self:center; height:210px; display:grid; grid-template-rows:1fr 1.2fr; gap:12px; }}
.social-visual-window {{ position:absolute; right:5.8%; top:8%; width:35%; height:80%; border-radius:38px; border:1px solid rgba(255,231,187,.20); background:linear-gradient(180deg, rgba(255,248,232,.12), rgba(255,248,232,.03)); box-shadow:inset 0 0 0 1px rgba(255,255,255,.06); }}
.social-logo-w {{ right:8%; bottom:10%; width:158px; height:102px; }}
</style>
</body>
''' + _fit_script()


def _cover_html(base_path: Path | None, size: tuple[int, int], meta: dict[str, Any], spec: dict[str, Any], config_payload: dict[str, Any]) -> str:
    w, h = size
    fields = _cover_fields(meta, config_payload)
    visual = _visual(config_payload)
    p = _palette(visual)
    asset_id = str(spec.get("asset_id") or "").upper()
    vertical = h > w
    title_scale = _number(_get_nested(visual, "title.scale"), 1.0, 0.7, 1.4)
    brand = visual.get("brand") if isinstance(visual.get("brand"), dict) else {}
    logo_uri = _logo_uri()
    bg = _bg_image(base_path)
    css_vars = _css_vars(p, visual)
    show_logo = False
    show_slogan = False
    if _is_social_context(fields["book"], fields["episode_name"], fields["chapter_name"]):
        return _social_cover_html(base_path, size, meta, spec, config_payload, fields, visual, p, css_vars, bg, logo_uri, show_logo)
    if vertical:
        title_max = max(86, int(min(w, h) * 0.106 * title_scale))
        title_min = max(42, int(min(w, h) * 0.046))
        meta_text = _episode_display_label(fields["episode_no"])
        brand_block = f'''
  <div class="brand-v">
    <div class="logo-circle" style="--size:{int(_number(brand.get('logo_width_vertical'), 200, 160, 280))}px"><img src="{logo_uri}" /></div>
  </div>''' if show_logo else ""
        return _common_html_head(w, h) + f'''
<body>
<div class="canvas cover-v {asset_id.lower()}" style="{css_vars}">
  <div class="bg-soft" style="background-image:{bg};"></div>
  <div class="bg" style="background-image:{bg};"></div>
  <div class="paper-wash"></div>
  <div class="vignette"></div>
  {_ornaments(visual)}
  <div class="series-v fit book-line" data-max="48" data-min="28" data-lines="1">《{_safe_text(fields['book'])}》 · {_safe_text(fields['author'])}</div>
  <div class="meta-v meta-frame fit" data-max="54" data-min="30" data-lines="1">{_safe_text(meta_text)}</div>
  <div class="title-v fit serif main-title" data-max="{title_max}" data-min="{title_min}" data-lines="2" data-lh="1.16">{_safe_text(fields['episode_name'])}</div>
  <div class="underline-v scribble"></div>
  <div class="visual-v"></div>
  {brand_block}
</div>
<style>
.cover-v .bg {{ background-position:50% 56%; }}
.series-v {{ position:absolute; left:9%; top:6.2%; width:82%; height:70px; }}
.meta-v {{ position:absolute; left:16%; top:15.8%; width:68%; height:104px; padding:0 36px; }}
.title-v {{ position:absolute; left:10%; top:28.2%; width:80%; height:22%; }}
.underline-v {{ position:absolute; left:18%; top:51.2%; width:64%; height:6px; }}
.visual-v {{ position:absolute; left:8%; right:8%; top:55%; bottom:25%; background:linear-gradient(180deg, rgba(255,248,232,.10), rgba(255,248,232,.02)); border-radius:30px; }}
.brand-v {{ position:absolute; left:39%; right:39%; bottom:6.2%; min-height:142px; display:flex; align-items:center; justify-content:center; border-radius:24px; background:rgba(7,6,5,.52); box-shadow:inset 0 0 0 1px rgba(214,185,140,.28); }}
</style>
</body>
''' + _fit_script()

    title_max = max(60, int(min(w, h) * 0.078 * title_scale))
    title_min = max(28, int(min(w, h) * 0.034))
    panel_pct = _number(_get_nested(visual, "composition.wide_panel_width_pct"), 52, 46, 60)
    left_side = str(_get_nested(visual, "composition.wide_text_side", "left")).lower() != "right"
    panel_left = 4.8 if left_side else 100 - 4.8 - panel_pct
    visual_left = panel_left + panel_pct + 1.2 if left_side else 4.8
    visual_w = max(34.0, 100 - visual_left - 4.8)
    meta_text = _episode_display_label(fields["episode_no"])
    brand_block = f'''
      <div class="brand-w">
        <div class="logo-circle" style="--size:{int(_number(brand.get('logo_width_wide'), 122, 92, 180))}px"><img src="{logo_uri}" /></div>
      </div>''' if show_logo else ""
    return _common_html_head(w, h) + f'''
<body>
<div class="canvas cover-w {asset_id.lower()}" style="{css_vars}">
  <div class="bg-soft" style="background-image:{bg};"></div>
  <div class="bg" style="background-image:{bg};"></div>
  <div class="paper-wash"></div>
  <div class="vignette"></div>
  {_ornaments(visual)}
  <div class="visual-w" style="left:{visual_left}%; width:{visual_w}%;"></div>
  <div class="text-panel paper-card" style="left:{panel_left}%; width:{panel_pct}%;">
    <div class="series-w fit book-line" data-max="40" data-min="24" data-lines="1">《{_safe_text(fields['book'])}》 · {_safe_text(fields['author'])}</div>
    <div class="meta-w meta-frame fit" data-max="42" data-min="24" data-lines="1">{_safe_text(meta_text)}</div>
    <div class="title-w fit left serif main-title" data-max="{title_max}" data-min="{title_min}" data-lines="2" data-lh="1.16">{_safe_text(fields['episode_name'])}</div>
    <div class="underline-w scribble"></div>
    {brand_block}
  </div>
</div>
<style>
.cover-w .bg {{ background-position:72% 50%; }}
.visual-w {{ position:absolute; top:4.8%; height:90.4%; border-radius:30px; background:linear-gradient(180deg, rgba(255,248,232,.08), rgba(255,248,232,.02)); box-shadow:inset 0 0 0 1px rgba(214,185,140,.14); }}
.text-panel {{ position:absolute; top:6.8%; height:86.4%; padding:48px 52px 38px; display:grid; grid-template-rows:54px 92px 1fr 6px 126px; gap:20px; }}
.series-w {{ width:100%; height:54px; }}
.meta-w {{ width:86%; justify-self:center; height:76px; padding:0 30px; }}
.title-w {{ width:100%; align-self:center; }}
.underline-w {{ width:72%; height:6px; justify-self:flex-start; align-self:start; }}
.brand-w {{ display:flex; align-items:center; justify-content:center; justify-self:center; align-self:end; min-width:150px; min-height:126px; padding:12px 20px; border-radius:20px; background:rgba(7,6,5,.50); box-shadow:inset 0 0 0 1px rgba(214,185,140,.26); }}
</style>
</body>
''' + _fit_script()


def _end_html(base_path: Path | None, size: tuple[int, int], meta: dict[str, Any], config_payload: dict[str, Any]) -> str:
    w, h = size
    fields = _end_fields(meta, config_payload)
    visual = _visual(config_payload)
    p = _palette(visual)
    brand = visual.get("brand") if isinstance(visual.get("brand"), dict) else {}
    title_scale = _number(_get_nested(visual, "title.scale"), 1.0, 0.7, 1.4)
    logo_uri = _logo_uri()
    bg = _bg_image(base_path)
    css_vars = _css_vars(p, visual, focus_x=50, focus_y=46)
    title_max = max(88, int(min(w, h) * 0.090 * title_scale))
    title_min = max(42, int(min(w, h) * 0.044))
    return _common_html_head(w, h) + f'''
<body>
<div class="canvas endcard" style="{css_vars}">
  <div class="bg-soft" style="background-image:{bg};"></div>
  <div class="bg" style="background-image:{bg};"></div>
  <div class="paper-wash"></div>
  <div class="vignette"></div>
  {_ornaments(visual)}
  <div class="book-e fit book-line" data-max="76" data-min="34" data-lines="1">《{_safe_text(fields['book'])}》</div>
  <div class="book-rule book-rule-l"></div>
  <div class="book-rule book-rule-r"></div>
  <div class="heading-e meta-frame fit" data-max="44" data-min="26" data-lines="1">{_safe_text(fields['heading'])}</div>
  <div class="title-card paper-card">
    <div class="title-e serif main-title">{_safe_text(fields['teaser'])}</div>
    <div class="underline-e scribble"></div>
  </div>
  <div class="cta-e paper-card">
    <div class="fit sans" data-max="40" data-min="22" data-lines="2" data-lh="1.22">{_safe_text(fields['cta'])}</div>
  </div>
  <div class="brand-e">
    <div class="logo-circle" style="--size:{int(_number(brand.get('logo_width_end'), 210, 160, 280))}px"><img src="{logo_uri}" /></div>
  </div>
</div>
<style>
.endcard .bg {{ background-position:50% 52%; }}
.book-e {{ position:absolute; left:9%; top:3.4%; width:82%; height:92px; color:var(--brown); }}
.book-rule {{ position:absolute; top:13.6%; height:1px; background:rgba(198,139,68,.58); }}
.book-rule-l {{ left:8%; right:60%; }}
.book-rule-r {{ left:60%; right:8%; }}
.heading-e {{ position:absolute; left:31%; top:15.8%; width:38%; height:58px; padding:0 28px; }}
.title-card {{ position:absolute; left:8.5%; top:25.0%; width:83%; height:31%; padding:52px 56px 34px; display:grid; grid-template-rows:1fr 6px; gap:16px; }}
.title-e {{ width:100%; height:100%; display:flex; align-items:center; justify-content:center; text-align:center; white-space:nowrap; overflow:visible; font-size:88px; line-height:1.06; transform:scaleX(.94); transform-origin:center center; }}
.underline-e {{ width:72%; justify-self:center; height:6px; }}
.cta-e {{ position:absolute; left:12%; top:59.2%; width:76%; height:118px; display:flex; align-items:center; justify-content:center; padding:18px 34px; color:var(--brown); }}
.cta-e .fit {{ width:100%; height:100%; }}
.brand-e {{ position:absolute; left:32%; right:32%; bottom:9.0%; min-height:118px; display:flex; align-items:center; justify-content:center; border-radius:28px; background:linear-gradient(180deg, rgba(255,248,232,.12), rgba(255,248,232,.04)); border:1px solid rgba(255,231,187,.20); box-shadow:0 18px 48px rgba(0,0,0,.12), inset 0 0 0 1px rgba(255,255,255,.06); backdrop-filter:blur(10px); }}
.brand-e .logo-circle {{ background:rgba(255,248,232,.22); border:0; box-shadow:none; overflow:hidden; }}
.brand-e .logo-circle::after {{ display:none; }}
.brand-e .logo-circle img {{ width:100%; height:100%; object-fit:contain; object-position:center; transform:none; mix-blend-mode:multiply; opacity:.94; filter:contrast(1.04) saturate(1.05) drop-shadow(0 8px 16px rgba(90,46,34,.12)); }}
</style>
</body>
''' + _fit_script()


def render_cover_with_playwright(base_path: Path | None, out_path: Path, meta: dict[str, Any], spec: dict[str, Any], config_payload: dict[str, Any]) -> None:
    size = tuple(spec.get("size") or (1080, 1920))
    device_scale_factor = _number(_get_nested(config_payload, "rendering.device_scale_factor"), 1.0, 0.5, 3.0)
    _render_html(_cover_html(base_path, size, meta, spec, config_payload), out_path, size, device_scale_factor=device_scale_factor)


def render_end_card_with_playwright(base_path: Path | None, out_path: Path, meta: dict[str, Any], spec: dict[str, Any], config_payload: dict[str, Any]) -> None:
    size = tuple(spec.get("size") or (1080, 1920))
    device_scale_factor = _number(_get_nested(config_payload, "rendering.device_scale_factor"), 1.0, 0.5, 3.0)
    _render_html(_end_html(base_path, size, meta, config_payload), out_path, size, device_scale_factor=device_scale_factor)
