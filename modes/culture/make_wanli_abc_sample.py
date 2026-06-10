"""Generate a local Wanli Shiwunian A/B/C drawing sample.

This is a cheap visual regression/sample entry point for the postprocess stack:
- A: opening/cover card rendered by automedia_core.postprocess_cards
- B: typical body illustration card generated locally with Pillow
- C: ending teaser card rendered by automedia_core.postprocess_cards

It does not call image models and does not read API keys.
"""

from __future__ import annotations

import json
import math
import shutil
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from automedia_core.postprocess_cards import BRAND_LOGO_PATH, COVER_SPECS, END_CARD_SPEC, create_cover_and_endcards, render_cover, render_end_card


ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "outputs" / "wanli_abc_sample"
SIZE_9X16 = (1080, 1920)


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "C:/Windows/Fonts/simsun.ttc",
    ]
    for path in candidates:
        try:
            if Path(path).exists():
                return ImageFont.truetype(path, size=size)
        except Exception:
            pass
    return ImageFont.load_default()


def _gradient_bg(size: tuple[int, int]) -> Image.Image:
    w, h = size
    img = Image.new("RGB", size, "#1B1412")
    px = img.load()
    for y in range(h):
        t = y / max(1, h - 1)
        for x in range(w):
            r = int(30 + 68 * (1 - t) + 28 * math.sin((x / w) * math.pi))
            g = int(22 + 36 * (1 - t))
            b = int(20 + 20 * (1 - t))
            px[x, y] = (r, g, b)
    return img.convert("RGBA")


def _draw_palace_scene(path: Path) -> None:
    """A/C shared source image: Ming court, no readable text."""
    w, h = SIZE_9X16
    img = _gradient_bg(SIZE_9X16)
    draw = ImageDraw.Draw(img, "RGBA")

    # Warm paper light.
    glow = Image.new("RGBA", SIZE_9X16, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow, "RGBA")
    gd.ellipse((w * 0.10, h * 0.08, w * 0.90, h * 0.62), fill=(226, 155, 78, 52))
    img = Image.alpha_composite(img, glow.filter(ImageFilter.GaussianBlur(60)))
    draw = ImageDraw.Draw(img, "RGBA")

    # Palace beams and screens.
    for i in range(7):
        x = int(w * (0.10 + i * 0.135))
        draw.rectangle((x, int(h * 0.13), x + int(w * 0.028), int(h * 0.68)), fill=(75, 35, 28, 210))
        draw.rectangle((x - 8, int(h * 0.13), x + int(w * 0.028) + 8, int(h * 0.145)), fill=(165, 104, 44, 180))
    for y in [0.18, 0.25, 0.33]:
        draw.rectangle((int(w * 0.08), int(h * y), int(w * 0.92), int(h * y) + 8), fill=(186, 128, 56, 145))

    # Distant throne/symbol of power.
    cx = w // 2
    draw.polygon(
        [(cx, int(h * 0.20)), (int(w * 0.40), int(h * 0.36)), (int(w * 0.60), int(h * 0.36))],
        fill=(191, 134, 61, 175),
    )
    draw.rounded_rectangle(
        (int(w * 0.36), int(h * 0.35), int(w * 0.64), int(h * 0.52)),
        radius=22,
        fill=(104, 43, 34, 210),
        outline=(219, 169, 82, 180),
        width=5,
    )

    # Officials as silhouettes, leaving top/bottom space for postprocess text.
    floor_y = int(h * 0.70)
    for side in [-1, 1]:
        for i in range(6):
            x = int(cx + side * (w * (0.16 + i * 0.055)))
            y = floor_y + i * 14
            color = (29, 25, 25, 205 - i * 10)
            draw.ellipse((x - 18, y - 80, x + 18, y - 44), fill=color)
            draw.polygon([(x - 38, y - 38), (x + 38, y - 38), (x + 52, y + 58), (x - 52, y + 58)], fill=color)
            draw.rectangle((x - 42, y - 52, x + 42, y - 42), fill=(24, 21, 21, 190))

    # Memorial papers and court tension.
    for i in range(18):
        x = int(w * (0.20 + (i % 6) * 0.105))
        y = int(h * (0.72 + (i // 6) * 0.055))
        draw.rounded_rectangle((x, y, x + 85, y + 18), radius=4, fill=(224, 198, 146, 92))
    draw.rectangle((0, int(h * 0.77), w, h), fill=(0, 0, 0, 70))
    draw.rectangle((0, 0, w, h), outline=(218, 170, 92, 110), width=10)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(path, quality=95)


def _draw_body_card(path: Path) -> None:
    """B card: typical body illustration, deliberately without model-generated text."""
    w, h = SIZE_9X16
    img = _gradient_bg(SIZE_9X16)
    draw = ImageDraw.Draw(img, "RGBA")

    glow = Image.new("RGBA", SIZE_9X16, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow, "RGBA")
    gd.ellipse((int(w * 0.12), int(h * 0.16), int(w * 0.88), int(h * 0.72)), fill=(226, 142, 70, 38))
    img = Image.alpha_composite(img, glow.filter(ImageFilter.GaussianBlur(68)))
    draw = ImageDraw.Draw(img, "RGBA")

    # Side corridor.
    draw.polygon([(0, int(h * 0.18)), (w, int(h * 0.10)), (w, int(h * 0.31)), (0, int(h * 0.43))], fill=(90, 48, 36, 150))
    draw.polygon([(0, int(h * 0.62)), (w, int(h * 0.50)), (w, h), (0, h)], fill=(18, 16, 16, 172))
    for i in range(8):
        x = int(w * (0.08 + i * 0.12))
        draw.line((x, int(h * 0.15), x - int(w * 0.10), int(h * 0.74)), fill=(190, 126, 54, 110), width=7)

    # Desk with memorials, officials, hidden emperor silhouette.
    desk = (int(w * 0.15), int(h * 0.545), int(w * 0.85), int(h * 0.705))
    draw.rounded_rectangle((desk[0] - 18, desk[1] + 18, desk[2] + 18, desk[3] + 38), radius=34, fill=(7, 6, 5, 90))
    draw.rounded_rectangle(desk, radius=30, fill=(70, 35, 28, 232), outline=(218, 158, 82, 162), width=5)
    for i in range(7):
        x = int(w * (0.22 + i * 0.085))
        y = int(h * (0.575 + (i % 2) * 0.035))
        draw.rounded_rectangle((x, y, x + 100, y + 32), radius=5, fill=(232, 203, 150, 170))
        draw.line((x + 10, y + 12, x + 86, y + 12), fill=(112, 71, 42, 70), width=2)

    # Emperor represented indirectly behind screen.
    screen = (int(w * 0.33), int(h * 0.205), int(w * 0.67), int(h * 0.500))
    draw.rounded_rectangle(screen, radius=20, fill=(147, 82, 50, 108), outline=(222, 167, 78, 150), width=5)
    for x in range(screen[0] + 28, screen[2], 44):
        draw.line((x, screen[1] + 12, x, screen[3] - 12), fill=(230, 184, 100, 55), width=3)
    draw.ellipse((int(w * 0.47), int(h * 0.30), int(w * 0.53), int(h * 0.36)), fill=(22, 18, 17, 150))
    draw.polygon([(int(w * 0.45), int(h * 0.43)), (int(w * 0.55), int(h * 0.43)), (int(w * 0.58), int(h * 0.50)), (int(w * 0.42), int(h * 0.50))], fill=(22, 18, 17, 145))

    # Foreground officials.
    for i, x in enumerate([0.20, 0.31, 0.69, 0.80]):
        cx = int(w * x)
        base = int(h * (0.82 + (i % 2) * 0.025))
        draw.ellipse((cx - 28, base - 130, cx + 28, base - 74), fill=(20, 18, 18, 230))
        draw.polygon([(cx - 58, base - 66), (cx + 58, base - 66), (cx + 84, base + 118), (cx - 84, base + 118)], fill=(20, 18, 18, 224))
        draw.rectangle((cx - 56, base - 92, cx + 56, base - 78), fill=(18, 16, 16, 220))

    draw.rectangle((0, 0, w, int(h * 0.09)), fill=(0, 0, 0, 44))
    draw.rectangle((0, int(h * 0.83), w, h), fill=(0, 0, 0, 62))
    draw.rounded_rectangle((int(w * 0.035), int(h * 0.035), int(w * 0.965), int(h * 0.965)), radius=28, outline=(218, 170, 92, 118), width=7)
    if BRAND_LOGO_PATH.exists():
        logo_size = int(w * 0.095)
        logo = Image.open(BRAND_LOGO_PATH).convert("RGBA")
        logo.thumbnail((logo_size, logo_size), Image.Resampling.LANCZOS)
        plate_pad = int(w * 0.020)
        plate_x = int(w * 0.065)
        plate_y = int(h * 0.055)
        plate = (
            plate_x,
            plate_y,
            plate_x + logo_size + plate_pad * 2,
            plate_y + logo_size + plate_pad * 2,
        )
        draw.rounded_rectangle(plate, radius=int(w * 0.030), fill=(104, 57, 35, 150), outline=(226, 174, 100, 145), width=3)
        logo_x = plate_x + plate_pad + (logo_size - logo.width) // 2
        logo_y = plate_y + plate_pad + (logo_size - logo.height) // 2
        img.alpha_composite(logo, (logo_x, logo_y))
    img = img.filter(ImageFilter.UnsharpMask(radius=1.2, percent=110, threshold=3))
    path.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(path, quality=95)


def _make_contact_sheet(paths: list[Path], out_path: Path) -> None:
    thumbs: list[Image.Image] = []
    labels = ["A 首页封面", "B 正文配图", "C 片尾预告"]
    for path in paths:
        img = Image.open(path).convert("RGB")
        img.thumbnail((360, 640), Image.Resampling.LANCZOS)
        thumbs.append(img)
    sheet = Image.new("RGB", (1220, 820), "#F4E8D2")
    draw = ImageDraw.Draw(sheet)
    label_font = _font(34, bold=True)
    for i, img in enumerate(thumbs):
        x = 40 + i * 395
        y = 64
        sheet.paste(img, (x, y))
        draw.rounded_rectangle((x - 8, y - 8, x + img.width + 8, y + img.height + 8), radius=10, outline="#B8894C", width=4)
        draw.text((x + img.width // 2, 765), labels[i], font=label_font, fill="#5A2E22", anchor="mm")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path, quality=95)


def _fit_with_blur_bg(src: Image.Image, size: tuple[int, int], *, fill_width_ratio: float = 0.46) -> Image.Image:
    """Place a vertical sample into a wide platform canvas with a matching blurred background."""
    src = src.convert("RGB")
    w, h = size
    bg = src.resize(size, Image.Resampling.LANCZOS).filter(ImageFilter.GaussianBlur(38)).convert("RGBA")
    shade = Image.new("RGBA", size, (10, 8, 7, 132))
    bg.alpha_composite(shade)
    target_w = int(w * fill_width_ratio)
    target_h = h
    if target_w / target_h > src.width / src.height:
        target_w = int(target_h * src.width / src.height)
    else:
        target_h = int(target_w * src.height / src.width)
    fg = src.resize((target_w, target_h), Image.Resampling.LANCZOS).convert("RGBA")
    x = (w - target_w) // 2
    y = (h - target_h) // 2
    mask = Image.new("L", (target_w, target_h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, target_w, target_h), radius=max(18, min(w, h) // 38), fill=255)
    shadow = Image.new("RGBA", size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow, "RGBA")
    shadow_box = (x - 18, y + 14, x + target_w + 18, y + target_h + 32)
    sd.rounded_rectangle(shadow_box, radius=max(18, min(w, h) // 34), fill=(0, 0, 0, 120))
    bg.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(max(18, min(w, h) // 34))))
    bg.paste(fg, (x, y), mask)
    draw = ImageDraw.Draw(bg, "RGBA")
    draw.rounded_rectangle((x, y, x + target_w, y + target_h), radius=max(18, min(w, h) // 38), outline=(222, 176, 112, 130), width=max(3, min(w, h) // 260))
    draw.rectangle((0, 0, w, int(h * 0.08)), fill=(0, 0, 0, 34))
    draw.rectangle((0, int(h * 0.88), w, h), fill=(0, 0, 0, 42))
    return bg.convert("RGB")


def _make_platform_contact_sheet(items: list[tuple[str, Path]], out_path: Path) -> None:
    cell_w, cell_h = 360, 300
    margin = 32
    label_h = 42
    cols = 4
    rows = math.ceil(len(items) / cols)
    sheet = Image.new("RGB", (margin * 2 + cols * cell_w, margin * 2 + rows * (cell_h + label_h)), "#F4E8D2")
    draw = ImageDraw.Draw(sheet)
    label_font = _font(24, bold=True)
    for i, (label, path) in enumerate(items):
        col = i % cols
        row = i // cols
        x = margin + col * cell_w
        y = margin + row * (cell_h + label_h)
        img = Image.open(path).convert("RGB")
        img.thumbnail((cell_w - 20, cell_h - 20), Image.Resampling.LANCZOS)
        px = x + (cell_w - img.width) // 2
        py = y + (cell_h - img.height) // 2
        sheet.paste(img, (px, py))
        draw.rounded_rectangle((px - 6, py - 6, px + img.width + 6, py + img.height + 6), radius=8, outline="#B8894C", width=3)
        draw.text((x + cell_w // 2, y + cell_h + label_h // 2), label, font=label_font, fill="#5A2E22", anchor="mm")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path, quality=95)


def _make_platform_samples(sample_dir: Path, b_path: Path, c_path: Path, base: Path, payload: dict[str, Any], meta: dict[str, str]) -> dict[str, str]:
    platform_dir = OUT_DIR / "平台样张"
    platform_dir.mkdir(parents=True, exist_ok=True)

    files: dict[str, str] = {}
    a_map = {
        "A1_微信视频号_3x4.png": sample_dir / "A1_万历十五年.png",
        "A2_微信视频号_9x16.png": sample_dir / "A2_万历十五年.png",
        "A01_B站_4x3.png": sample_dir / "A01_万历十五年.png",
        "A02_B站_16x9.png": sample_dir / "A02_万历十五年.png",
    }
    for name, src in a_map.items():
        dst = platform_dir / name
        shutil.copy2(src, dst)
        files[dst.stem] = str(dst)

    b_wx = platform_dir / "B01_微信视频号_9x16.png"
    shutil.copy2(b_path, b_wx)
    files[b_wx.stem] = str(b_wx)
    b_bili = platform_dir / "B01_B站_9x16.png"
    shutil.copy2(b_path, b_bili)
    files[b_bili.stem] = str(b_bili)

    c_wx = platform_dir / "C_微信视频号_9x16.png"
    shutil.copy2(c_path, c_wx)
    files[c_wx.stem] = str(c_wx)
    c_bili = platform_dir / "C_B站_16x9.png"
    c_spec = {"asset_id": "C", "key": "end_bili_16x9", "label": "B站16:9片尾页", "short_label": "C_B站16x9", "size": (1920, 1080), "ratio": (16, 9), "platform": "bilibili"}
    render_end_card(base, c_bili, meta, c_spec, payload)
    files[c_bili.stem] = str(c_bili)

    ordered = [
        ("A1 微信3:4", platform_dir / "A1_微信视频号_3x4.png"),
        ("A2 微信9:16", platform_dir / "A2_微信视频号_9x16.png"),
        ("A01 B站4:3", platform_dir / "A01_B站_4x3.png"),
        ("A02 B站16:9", platform_dir / "A02_B站_16x9.png"),
        ("B 微信9:16", b_wx),
        ("B B站9:16", b_bili),
        ("C 微信9:16", c_wx),
        ("C B站16:9", c_bili),
    ]
    contact = platform_dir / "万历十五年_平台规格样张总览.png"
    _make_platform_contact_sheet(ordered, contact)
    files["contact_sheet"] = str(contact)
    return files


def _write_prompts(path: Path) -> list[dict[str, Any]]:
    prompts = [
        {
            "image_id": "A1",
            "name": "A1_A与C共享底图",
            "voiceover_text": "万历皇帝为什么连一次午朝都能牵动整个官场？这一集，我们从一场看似普通的传言，读懂皇权和制度之间的拉扯。",
            "prompt": "竖屏9:16，明代宫廷朝堂，远处御座与屏风，文官队列和奏疏形成压迫感，皇帝只以背影或屏风后的剪影出现；顶部预留标题区，底部预留品牌区；黑金、暗红、宣纸质感，历史人文经典解读风格；不要出现可识别文字、书名、logo、水印。",
        },
        {
            "image_id": "B01",
            "name": "B01_正文内容",
            "voiceover_text": "午朝没有按时举行，表面像是一场礼仪风波，实际上暴露的是皇帝、内阁和文官集团之间长期积累的紧张。",
            "prompt": "竖屏9:16，明代宫廷侧殿或内阁书房，书案上堆放奏疏，几名文官在昏暗烛光中低声议论，屏风后隐约有皇帝剪影；用空间距离表现皇权与文官集团的张力；克制、厚重、电影感，禁止现代物品和文字。",
        },
        {
            "image_id": "C",
            "name": "C_片尾预告",
            "voiceover_text": "下一期，我们继续看申时行如何在皇帝和文官之间夹缝调和。喜欢本集，欢迎点赞、转发并关注【知识慢炖】",
            "prompt": "C片尾与A1共用同一张9:16明代宫廷母图，后处理叠加“下集预告”、预告标题、CTA和固定品牌区；画面保持沉稳、留白充足、标题安全区清晰。",
        },
    ]
    path.write_text(json.dumps(prompts, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    txt_path = path.with_suffix(".txt")
    txt_path.write_text("\n\n".join(f"[{p['image_id']}] {p['name']}\n{p['prompt']}" for p in prompts) + "\n", encoding="utf-8")
    return prompts


def _set_nested(data: dict[str, Any], path: str, value: Any) -> None:
    cur = data
    parts = path.split(".")
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = value


def _clean_sample_config(config_path: Path, base: Path) -> tuple[Path, Path, dict[str, Any], dict[str, str]]:
    """Override topic-specific defaults for this sample and rerender A/C."""
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    content = payload.setdefault("content", {})
    content.update(
        {
            "book_title": "万历十五年",
            "author": "黄仁宇",
            "effective_chapter_no": "第一章",
            "effective_chapter_name": "万历皇帝",
            "effective_episode_no": "第一集",
            "effective_episode_name": "午朝谣言背后的制度困局",
            "brand_name": "【知识慢炖】",
            "brand_slogan": "让经典不再高冷，让普通人也能读懂",
            "next_teaser": "看申时行如何在皇帝和文官之间夹缝调和",
            "cta_text": "创作不易，欢迎购买下方链接中的原著支持我们~",
        }
    )
    _set_nested(payload, "style.cover.editorial_layout.marketing_tag", "经典里的关键问题")
    _set_nested(payload, "style.cover.editorial_layout.vertical_note_title", "这一集看的是：皇帝、文官与制度困局")
    _set_nested(payload, "style.cover.editorial_layout.vertical_note_subtitle", "午朝谣言不是小事，而是权力关系的外露")
    _set_nested(payload, "style.cover.editorial_layout.vertical_note_meta", "看懂这个细节，才能看见万历朝真正的张力。")
    _set_nested(payload, "style.cover.editorial_layout.wide_tagline", "把晚明政治，讲成看得懂的因果线索")
    _set_nested(payload, "style.cover.editorial_layout.wide_note", "从一次午朝传言，看见皇帝和文官集团的长期拉扯。")
    _set_nested(payload, "style.endcard.editorial_layout.teaser_subtitle", "下一集，我们看申时行如何在皇帝和文官之间寻找平衡。")
    payload["rendering"] = {"engine": "playwright_html", "fallback_engine": ""}
    config_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    meta = {
        "book_title": "万历十五年",
        "author": "黄仁宇",
        "chapter_no": "第一章",
        "chapter_name": "万历皇帝",
        "episode_no": "第一集",
        "episode_name": "午朝谣言背后的制度困局",
        "episode_label": "第一集",
        "hook": "万历皇帝为什么连一次午朝都能牵动整个官场？",
        "cover_title": "第一集｜午朝谣言背后的制度困局",
        "logo": "【知识慢炖】",
        "slogan": "让经典不再高冷，让普通人也能读懂",
    }
    formal_dir = config_path.parent
    for spec in COVER_SPECS:
        render_cover(base, formal_dir / f"{spec['asset_id']}_万历十五年.png", meta, spec, payload)
    render_end_card(base, formal_dir / "C_知识慢炖.png", meta, dict(END_CARD_SPEC), payload)

    a_path = OUT_DIR / "A_首页封面示例.png"
    c_path = OUT_DIR / "C_片尾预告示例.png"
    render_cover(base, a_path, meta, COVER_SPECS[0], payload)
    render_end_card(base, c_path, meta, dict(END_CARD_SPEC), payload)
    return a_path, c_path, payload, meta


def main() -> None:
    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    base = OUT_DIR / "base_A_C_shared.png"
    b_path = OUT_DIR / "B01_正文配图示例.png"
    _draw_palace_scene(base)
    _draw_body_card(b_path)

    result = create_cover_and_endcards(
        OUT_DIR,
        base,
        base,
        book_title="万历十五年",
        author="黄仁宇",
        episode_title="第一集：午朝谣言背后的制度困局",
        hook="万历皇帝为什么连一次午朝都能牵动整个官场？",
        cover_title="第一集｜午朝谣言背后的制度困局",
        next_teaser="下一期，我们继续看申时行如何在皇帝和文官之间夹缝调和。",
        chapter_label="第一章 万历皇帝",
    )

    _ = result
    a_named, c_named, payload, meta = _clean_sample_config(OUT_DIR / "06_封面与片尾" / "封面片尾配置.json", base)
    platform_files = _make_platform_samples(OUT_DIR / "06_封面与片尾", b_path, c_named, base, payload, meta)

    prompt_path = OUT_DIR / "万历十五年_ABC绘图提示词.json"
    _write_prompts(prompt_path)
    _make_contact_sheet([a_named, b_path, c_named], OUT_DIR / "万历十五年_ABC样张总览.png")

    manifest = {
        "sample": "万历十五年 ABC",
        "files": {
            "A": str(a_named),
            "B": str(b_path),
            "C": str(c_named),
            "contact_sheet": str(OUT_DIR / "万历十五年_ABC样张总览.png"),
            "platform_contact_sheet": platform_files["contact_sheet"],
            "platform_samples": platform_files,
            "prompts_json": str(prompt_path),
            "prompts_txt": str(prompt_path.with_suffix(".txt")),
        },
        "note": "A/C use project postprocess renderer; B is a local Pillow body-card sample for visual direction.",
    }
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
