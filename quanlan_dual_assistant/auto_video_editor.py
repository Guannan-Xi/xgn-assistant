from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
AUDIO_EXTS = (".mp3", ".wav", ".m4a", ".aac", ".flac")
LRC_TIME_RE = re.compile(r"\[(\d{1,2}):(\d{2})(?:[.:](\d{1,3}))?\](.*)")
IMAGE_ID_RE = re.compile(r"(?:【\s*)?([ABC]\d{0,4}|B\d{1,4})(?:\s*】)?", re.I)


@dataclass
class LrcEvent:
    seconds: float
    image_id: str
    text: str


@dataclass
class Scene:
    image_id: str
    start: float
    end: float
    image_path: Path


def _run(cmd: list[str], *, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
            errors="replace",
            check=check,
        )
    except subprocess.CalledProcessError as exc:
        output = (exc.stdout or "").strip()
        tail = output[-4000:] if output else str(exc)
        raise RuntimeError(tail) from exc


def _tool_exe(name: str) -> str:
    exe = f"{name}.exe" if os.name == "nt" else name
    path = shutil.which(name)
    if path:
        return path

    env_bin = os.environ.get("FFMPEG_BIN", "").strip()
    candidates: list[Path] = []
    if env_bin:
        candidates.append(Path(env_bin) / exe)

    candidates.extend(
        [
            PROJECT_ROOT / "tools" / "ffmpeg" / "bin" / exe,
            PROJECT_ROOT.parent / "tools" / "ffmpeg" / "bin" / exe,
            Path.home() / "Documents" / "Codex" / "tools" / "ffmpeg" / "bin" / exe,
        ]
    )
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)

    raise RuntimeError(
        f"未找到 {name}。请安装 FFmpeg，或设置环境变量 FFMPEG_BIN 指向 ffmpeg.exe 所在目录。"
    )


def _parse_time(minutes: str, seconds: str, frac: str | None) -> float:
    value = int(minutes) * 60 + int(seconds)
    if frac:
        value += int(frac.ljust(3, "0")[:3]) / 1000
    return float(value)


def _normalize_image_id(value: str) -> str:
    text = str(value or "").strip().upper()
    match = re.match(r"^([ABC])0*(\d+)$", text)
    if match:
        return f"{match.group(1)}{int(match.group(2))}"
    return text


def _strip_image_ids(text: str) -> str:
    return IMAGE_ID_RE.sub("", text or "").strip()


def parse_lrc(path: Path) -> list[LrcEvent]:
    events: list[LrcEvent] = []
    current_image_id = ""
    for raw in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        match = LRC_TIME_RE.match(raw.strip())
        if not match:
            continue
        ts = _parse_time(match.group(1), match.group(2), match.group(3))
        payload = (match.group(4) or "").strip()
        marker = IMAGE_ID_RE.search(payload)
        if marker:
            current_image_id = _normalize_image_id(marker.group(1))
        if not current_image_id:
            continue
        text = _strip_image_ids(payload)
        if events and abs(events[-1].seconds - ts) < 0.05 and events[-1].image_id == current_image_id:
            if text:
                events[-1].text = (events[-1].text + " " + text).strip()
            continue
        events.append(LrcEvent(seconds=ts, image_id=current_image_id, text=text))
    return events


def _image_id_candidates(image_id: str) -> set[str]:
    norm = _normalize_image_id(image_id)
    values = {norm}
    match = re.match(r"^([ABC])(\d+)$", norm)
    if match:
        prefix, number = match.group(1), int(match.group(2))
        values.add(f"{prefix}{number:02d}")
        values.add(f"{prefix}{number:03d}")
    return values


def build_image_index(image_dir: Path) -> dict[str, Path]:
    index: dict[str, Path] = {}
    for file in sorted(image_dir.rglob("*")):
        if not file.is_file() or file.suffix.lower() not in IMAGE_EXTS:
            continue
        stem = file.stem.upper()
        exact = _normalize_image_id(stem)
        index.setdefault(exact, file)
        for found in IMAGE_ID_RE.findall(stem):
            index.setdefault(_normalize_image_id(found), file)
    return index


def find_image(image_id: str, index: dict[str, Path]) -> Path | None:
    for key in _image_id_candidates(image_id):
        if key in index:
            return index[key]
    return None


def _audio_duration(ffprobe: str, audio_path: Path) -> float:
    result = _run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(audio_path),
        ]
    )
    try:
        return max(0.0, float(result.stdout.strip()))
    except Exception:
        return 0.0


def _audio_mean_volume(ffmpeg: str, audio_path: Path) -> float | None:
    result = _run([ffmpeg, "-hide_banner", "-i", str(audio_path), "-af", "volumedetect", "-f", "null", "-"], check=False)
    match = re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?)\s*dB", result.stdout or "")
    if not match:
        return None
    try:
        return float(match.group(1))
    except Exception:
        return None


def _resolve_bgm_for_lrc(args: argparse.Namespace, lrc_path: Path) -> Path | None:
    value = str(getattr(args, "bgm", "") or "").strip()
    if not value:
        return None
    path = Path(value).expanduser().resolve()
    if path.is_file():
        return path
    if path.is_dir():
        candidates = [p for p in sorted(path.iterdir()) if p.is_file() and p.suffix.lower() in AUDIO_EXTS]
        if not candidates:
            return None
        for candidate in candidates:
            if candidate.stem.lower() == lrc_path.stem.lower():
                return candidate
        return candidates[0]
    return None


def _bgm_volume_expr(ffmpeg: str, voice_path: Path, bgm_path: Path, *, duck_db: float) -> tuple[str, dict[str, float | None]]:
    voice_mean = _audio_mean_volume(ffmpeg, voice_path)
    bgm_mean = _audio_mean_volume(ffmpeg, bgm_path)
    if voice_mean is None or bgm_mean is None:
        gain_db = -18.0
    else:
        gain_db = max(-34.0, min(-8.0, voice_mean - abs(float(duck_db)) - bgm_mean))
    factor = 10 ** (gain_db / 20.0)
    return f"{factor:.6f}", {"voice_mean_db": voice_mean, "bgm_mean_db": bgm_mean, "bgm_gain_db": gain_db}


def _clean_tts_text(text: str) -> str:
    text = _strip_image_ids(text or "").strip()
    return re.sub(r"[\u3002\uff01\uff1f.!?]+(?=\s|$)", "", text).strip()


def _voice_style_prompt(style: str) -> str:
    styles = {
        "calm_story": "Read in Mandarin Chinese with a calm, steady storytelling narrator voice. Clear diction, warm but not dramatic.",
        "excited_research": "Read in Mandarin Chinese with an energetic research-progress narrator voice. Clear diction, lively discovery feeling, not shouting.",
        "documentary": "Read in Mandarin Chinese with a restrained documentary narrator voice. Clear, credible, measured pacing.",
    }
    return styles.get(str(style or "").strip(), styles["calm_story"])


def _gemini_voice_name(style: str) -> str:
    voices = {
        "calm_story": "Charon",
        "excited_research": "Puck",
        "documentary": "Kore",
    }
    return voices.get(str(style or "").strip(), "Charon")


def _wav_header(pcm: bytes, *, channels: int = 1, sample_rate: int = 24000, bits_per_sample: int = 16) -> bytes:
    byte_rate = sample_rate * channels * bits_per_sample // 8
    block_align = channels * bits_per_sample // 8
    data_size = len(pcm)
    return (
        b"RIFF" + (36 + data_size).to_bytes(4, "little") + b"WAVEfmt " + (16).to_bytes(4, "little")
        + (1).to_bytes(2, "little") + channels.to_bytes(2, "little") + sample_rate.to_bytes(4, "little")
        + byte_rate.to_bytes(4, "little") + block_align.to_bytes(2, "little") + bits_per_sample.to_bytes(2, "little")
        + b"data" + data_size.to_bytes(4, "little")
    )


def _extract_inline_audio(response) -> tuple[bytes, str]:
    for candidate in getattr(response, "candidates", []) or []:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", []) or []:
            inline = getattr(part, "inline_data", None)
            if inline:
                data = getattr(inline, "data", b"") or b""
                mime = getattr(inline, "mime_type", "") or ""
                if isinstance(data, str):
                    data = base64.b64decode(data)
                if data:
                    return data, mime
    raise RuntimeError("Gemini TTS did not return inline audio")


def synthesize_voice_from_lrc(args: argparse.Namespace, lrc_path: Path, output_dir: Path) -> Path | None:
    if not bool(getattr(args, "synthesize_voice", False)):
        return None
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY/GOOGLE_API_KEY is required for LRC voice synthesis")
    events = parse_lrc(lrc_path)
    text = "\n".join(_clean_tts_text(event.text) for event in events if _clean_tts_text(event.text))
    if not text:
        raise RuntimeError(f"LRC has no text to synthesize: {lrc_path}")
    from google import genai
    from google.genai import types

    model = str(getattr(args, "tts_model", "") or "gemini-2.5-flash-preview-tts")
    style = str(getattr(args, "voice_style", "") or "calm_story")
    client = genai.Client(api_key=key)
    response = client.models.generate_content(
        model=model,
        contents=f"{_voice_style_prompt(style)}\n\n{text}",
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=_gemini_voice_name(style))
                )
            ),
        ),
    )
    audio, mime = _extract_inline_audio(response)
    out = output_dir / f"{lrc_path.stem}_gemini_voice.wav"
    if "wav" in mime.lower():
        out.write_bytes(audio)
    else:
        out.write_bytes(_wav_header(audio) + audio)
    return out


def _find_audio_for_lrc(lrc_path: Path) -> Path | None:
    for ext in AUDIO_EXTS:
        candidate = lrc_path.with_suffix(ext)
        if candidate.exists():
            return candidate
    return None


def build_scenes(
    events: list[LrcEvent],
    image_index: dict[str, Path],
    *,
    final_end: float,
    last_seconds: float,
) -> tuple[list[Scene], list[str]]:
    changes: list[tuple[float, str]] = []
    for event in events:
        if not changes or changes[-1][1] != event.image_id:
            changes.append((event.seconds, event.image_id))

    scenes: list[Scene] = []
    missing: list[str] = []
    for index, (start, image_id) in enumerate(changes):
        end = changes[index + 1][0] if index + 1 < len(changes) else (final_end or start + last_seconds)
        if end <= start:
            end = start + max(0.5, last_seconds)
        image_path = find_image(image_id, image_index)
        if image_path is None:
            missing.append(image_id)
            continue
        scenes.append(Scene(image_id=image_id, start=start, end=end, image_path=image_path))
    return scenes, sorted(set(missing))


def write_srt(path: Path, events: list[LrcEvent], final_end: float, last_seconds: float) -> None:
    lines: list[str] = []
    text_events = [event for event in events if event.text.strip()]
    for index, event in enumerate(text_events, start=1):
        end = text_events[index].seconds if index < len(text_events) else (final_end or event.seconds + last_seconds)
        if end <= event.seconds:
            end = event.seconds + max(0.5, last_seconds)
        lines.extend([str(index), f"{_srt_time(event.seconds)} --> {_srt_time(end)}", event.text.strip(), ""])
    path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def _srt_time(seconds: float) -> str:
    ms_total = int(round(max(0.0, seconds) * 1000))
    ms = ms_total % 1000
    sec_total = ms_total // 1000
    sec = sec_total % 60
    minute_total = sec_total // 60
    minute = minute_total % 60
    hour = minute_total // 60
    return f"{hour:02d}:{minute:02d}:{sec:02d},{ms:03d}"


def _concat_file(path: Path, segments: list[Path]) -> None:
    rows = []
    for segment in segments:
        escaped = str(segment).replace("\\", "/").replace("'", "'\\''")
        rows.append(f"file '{escaped}'")
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def render_video(
    ffmpeg: str,
    scenes: list[Scene],
    output_video: Path,
    *,
    audio_path: Path | None,
    subtitle_path: Path | None,
    size: str,
    fps: int,
    crf: int,
    preset: str,
    bgm_path: Path | None = None,
    bgm_duck_db: float = 18.0,
) -> None:
    width, height = _parse_size(size)
    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},setsar=1,format=yuv420p"
    )
    with tempfile.TemporaryDirectory(prefix="auto_clip_", dir=str(output_video.parent)) as tmp_name:
        tmp = Path(tmp_name)
        segments: list[Path] = []
        for idx, scene in enumerate(scenes, start=1):
            duration = max(0.2, scene.end - scene.start)
            segment = tmp / f"scene_{idx:04d}_{scene.image_id}.mp4"
            print(f"  [{idx}/{len(scenes)}] {scene.image_id} {duration:.2f}s <- {scene.image_path.name}", flush=True)
            _run(
                [
                    ffmpeg,
                    "-hide_banner",
                    "-y",
                    "-loop",
                    "1",
                    "-t",
                    f"{duration:.3f}",
                    "-i",
                    str(scene.image_path),
                    "-vf",
                    vf,
                    "-r",
                    str(fps),
                    "-an",
                    "-c:v",
                    "libx264",
                    "-preset",
                    preset,
                    "-crf",
                    str(crf),
                    "-pix_fmt",
                    "yuv420p",
                    str(segment),
                ]
            )
            segments.append(segment)

        concat_path = tmp / "concat.txt"
        video_tmp = tmp / "video_only.mp4"
        _concat_file(concat_path, segments)
        _run([ffmpeg, "-hide_banner", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_path), "-c", "copy", str(video_tmp)])

        video_source = video_tmp
        if subtitle_path and subtitle_path.exists():
            subtitled_tmp = tmp / "subtitled.mp4"
            subtitle_filter = str(subtitle_path).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
            style = "FontName=Microsoft YaHei,FontSize=13,PrimaryColour=&H00000000,BackColour=&HC0FFFFFF,BorderStyle=4,Outline=0,Shadow=0,Alignment=2,MarginV=384"
            _run([ffmpeg, "-hide_banner", "-y", "-i", str(video_tmp), "-vf", f"subtitles='{subtitle_filter}':force_style='{style}'", "-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p", "-an", str(subtitled_tmp)])
            video_source = subtitled_tmp

        if audio_path and bgm_path:
            bgm_volume, meta = _bgm_volume_expr(ffmpeg, audio_path, bgm_path, duck_db=bgm_duck_db)
            print(f"  BGM auto volume: voice={meta['voice_mean_db']}dB bgm={meta['bgm_mean_db']}dB gain={meta['bgm_gain_db']}dB", flush=True)
            _run([ffmpeg, "-hide_banner", "-y", "-i", str(video_source), "-i", str(audio_path), "-stream_loop", "-1", "-i", str(bgm_path), "-filter_complex", f"[2:a]volume={bgm_volume},asetpts=PTS-STARTPTS[bgm];[1:a][bgm]amix=inputs=2:duration=first:dropout_transition=0[aout]", "-map", "0:v:0", "-map", "[aout]", "-c:v", "copy", "-c:a", "aac", "-shortest", str(output_video)])
        elif audio_path:
            _run([ffmpeg, "-hide_banner", "-y", "-i", str(video_source), "-i", str(audio_path), "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-shortest", str(output_video)])
        else:
            shutil.copy2(video_source, output_video)


def _parse_size(size: str) -> tuple[int, int]:
    match = re.match(r"^\s*(\d+)\s*x\s*(\d+)\s*$", str(size or "1080x1920"), re.I)
    if not match:
        raise ValueError("画面尺寸必须类似 1080x1920")
    return int(match.group(1)), int(match.group(2))


def process_lrc_file(args: argparse.Namespace, lrc_path: Path, image_index: dict[str, Path], ffmpeg: str, ffprobe: str) -> dict:
    output_dir = Path(args.output).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    out_video = output_dir / f"{lrc_path.stem}_自动剪辑.mp4"
    out_srt = output_dir / f"{lrc_path.stem}_字幕.srt"
    report_path = output_dir / f"{lrc_path.stem}_自动剪辑报告.json"

    print(f"\n处理 LRC：{lrc_path}", flush=True)
    events = parse_lrc(lrc_path)
    if not events:
        raise RuntimeError(f"未从 LRC 识别到带画面编号的时间轴：{lrc_path}")

    audio_path = synthesize_voice_from_lrc(args, lrc_path, output_dir) or _find_audio_for_lrc(lrc_path)
    bgm_path = _resolve_bgm_for_lrc(args, lrc_path)
    final_end = _audio_duration(ffprobe, audio_path) if audio_path else 0.0
    scenes, missing = build_scenes(
        events,
        image_index,
        final_end=final_end,
        last_seconds=float(args.last_seconds),
    )
    if missing:
        raise RuntimeError("缺少这些画面素材：" + ", ".join(missing))
    if not scenes:
        raise RuntimeError("没有可渲染的画面。")

    write_srt(out_srt, events, final_end, float(args.last_seconds))
    render_video(
        ffmpeg,
        scenes,
        out_video,
        audio_path=audio_path,
        subtitle_path=out_srt if bool(args.burn_subtitles) else None,
        size=args.size,
        fps=int(args.fps),
        crf=int(args.crf),
        preset=args.preset,
        bgm_path=bgm_path,
        bgm_duck_db=float(args.bgm_duck_db),
    )

    report = {
        "lrc": str(lrc_path),
        "audio": str(audio_path) if audio_path else "",
        "background_music": str(bgm_path) if bgm_path else "",
        "output_video": str(out_video),
        "subtitle": str(out_srt),
        "scene_count": len(scenes),
        "events": len(events),
        "size": args.size,
        "fps": int(args.fps),
        "scenes": [
            {
                "image_id": scene.image_id,
                "start": round(scene.start, 3),
                "end": round(scene.end, 3),
                "image": str(scene.image_path),
            }
            for scene in scenes
        ],
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"完成：{out_video}", flush=True)
    return report


def _read_book_context(root: Path) -> str:
    readable_outline = "00_\u5206\u96c6\u89e3\u8bfb\u5927\u7eb2_\u53ef\u8bfb.txt"
    json_outline = "00_\u5206\u96c6\u89e3\u8bfb\u5927\u7eb2.json"
    run_readme = "README_\u672c\u6b21\u8f93\u51fa.md"
    candidates = [
        root / readable_outline,
        root / json_outline,
        root / run_readme,
    ]
    try:
        candidates.extend(sorted(root.rglob(readable_outline))[:5])
        candidates.extend(sorted(root.rglob(json_outline))[:5])
        candidates.extend(sorted(root.rglob(run_readme))[:5])
    except Exception:
        pass
    chunks: list[str] = []
    seen: set[Path] = set()
    for path in candidates:
        if path in seen or not path.exists() or not path.is_file():
            continue
        seen.add(path)
        text = path.read_text(encoding="utf-8", errors="replace").strip()
        if text:
            chunks.append(f"[{path.name}]\n{text[:6000]}")
    return "\n\n".join(chunks)[:12000]


def _build_bgm_prompt(book_context: str, user_prompt: str = "") -> str:
    base = (
        "Create a 30-second instrumental-only background music bed for a Chinese book explainer short video. "
        "No vocals, no lyrics, no spoken words. It must sit quietly under narration, with a restrained documentary tone, "
        "warm low piano or soft marimba, subtle strings, light pulse, no sudden drops, no loud percussion, loop-friendly ending. "
        "Mood should follow the book context: thoughtful, humane, analytical, with gentle tension and hope. "
        "Mix target: background underscore, not a standalone song."
    )
    if user_prompt.strip():
        base += " Extra direction: " + user_prompt.strip()
    if book_context.strip():
        base += "\n\nBook outline/summary context:\n" + book_context.strip()
    return base


def _extract_inline_audio_parts(response) -> tuple[bytes, str, str]:
    notes: list[str] = []
    parts = getattr(response, "parts", None)
    if parts is None:
        parts = []
        for candidate in getattr(response, "candidates", []) or []:
            content = getattr(candidate, "content", None)
            parts.extend(getattr(content, "parts", []) or [])
    for part in parts:
        text = getattr(part, "text", None)
        if text:
            notes.append(str(text))
        inline = getattr(part, "inline_data", None)
        if inline:
            data = getattr(inline, "data", b"") or b""
            mime = getattr(inline, "mime_type", "") or ""
            if isinstance(data, str):
                data = base64.b64decode(data)
            if data:
                return data, mime, "\n\n".join(notes)
    raise RuntimeError("Gemini/Lyria did not return inline audio")


def _extract_inline_audio_from_json(payload: dict) -> tuple[bytes, str, str]:
    notes: list[str] = []
    for candidate in payload.get("candidates", []) or []:
        content = candidate.get("content") or {}
        for part in content.get("parts", []) or []:
            text = part.get("text")
            if text:
                notes.append(str(text))
            inline = part.get("inlineData") or part.get("inline_data") or {}
            data = inline.get("data")
            if data:
                mime = str(inline.get("mimeType") or inline.get("mime_type") or "")
                return base64.b64decode(data), mime, "\n\n".join(notes)
    raise RuntimeError("Gemini/Lyria relay did not return inline audio")


def _normalized_relay_base_url() -> str:
    base = (
        os.environ.get("NEWAPI_BASE_URL")
        or os.environ.get("FOREIGN_MODEL_BASE_URL")
        or "https://greatwalllink.top/v1"
    ).replace("greatwallink.top", "greatwalllink.top").rstrip("/")
    if not base.endswith("/v1"):
        base += "/v1"
    return base


def _generate_bgm_with_relay(key: str, model: str, prompt: str) -> tuple[bytes, str, str]:
    relay_root = _normalized_relay_base_url().rsplit("/v1", 1)[0].rstrip("/")
    url = f"{relay_root}/v1beta/models/{model}:generateContent"
    payload = json.dumps(
        {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"responseModalities": ["AUDIO"]},
        },
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    last_error = ""
    for attempt in range(1, 4):
        try:
            with urllib.request.urlopen(req, timeout=240) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
            return _extract_inline_audio_from_json(data)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:1200]
            last_error = f"HTTP {exc.code} {exc.reason}: {body or '<empty body>'}"
            if exc.code in {502, 503, 504} and attempt < 3:
                print(f"Relay BGM request got HTTP {exc.code}; retrying {attempt}/3...", flush=True)
                time.sleep(3 * attempt)
                continue
            raise RuntimeError(
                f"Gemini/Lyria relay request failed via {_normalized_relay_base_url()} model={model}: {last_error}. "
                "If this relay does not expose Lyria audio generation, switch BGM model or use an existing BGM file."
            ) from exc
        except urllib.error.URLError as exc:
            last_error = str(exc)
            if attempt < 3:
                print(f"Relay BGM request failed; retrying {attempt}/3: {last_error}", flush=True)
                time.sleep(3 * attempt)
                continue
            raise RuntimeError(f"Gemini/Lyria relay request failed via {_normalized_relay_base_url()} model={model}: {last_error}") from exc
    raise RuntimeError(f"Gemini/Lyria relay request failed via {_normalized_relay_base_url()} model={model}: {last_error}")


def generate_bgm_with_gemini(args: argparse.Namespace) -> Path:
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        raise RuntimeError("BGM generation requires Gemini Key in GEMINI_API_KEY/GOOGLE_API_KEY.")
    output_dir = Path(args.bgm_output or args.output or PROJECT_ROOT / "_temp" / "bgm_library").expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_root = Path(args.summary_root or args.output or output_dir).expanduser().resolve()
    book_context = _read_book_context(summary_root) if summary_root.exists() else ""
    prompt = _build_bgm_prompt(book_context, str(args.bgm_prompt or ""))

    model = str(args.bgm_model or "lyria-3-clip-preview")
    audio, mime, notes = _generate_bgm_with_relay(key, model, prompt)
    suffix = ".mp3" if "mpeg" in mime.lower() or "mp3" in mime.lower() or model.startswith("lyria") else ".bin"
    safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", summary_root.name or "book")[:40].strip("_") or "book"
    out = output_dir / f"bgm_{safe_name}_{len(list(output_dir.glob('bgm_*.mp3'))) + 1:03d}{suffix}"
    out.write_bytes(audio)
    out.with_suffix(".prompt.txt").write_text(prompt, encoding="utf-8")
    if notes.strip():
        out.with_suffix(".notes.txt").write_text(notes, encoding="utf-8")
    print(f"Generated BGM: {out}", flush=True)
    return out


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="按 LRC 里的画面编号自动匹配图片并合成视频。")
    parser.add_argument("--images", default="", help="图片素材文件夹，文件名需包含 B26、B027 等画面编号")
    parser.add_argument("--lrc", default="", help="LRC 素材文件夹")
    parser.add_argument("--output", default="", help="输出文件夹")
    parser.add_argument("--size", default="1080x1920", help="输出尺寸，默认 1080x1920")
    parser.add_argument("--fps", default="30", help="输出帧率，默认 30")
    parser.add_argument("--last-seconds", default="4", help="没有同名音频时，最后一张图默认停留秒数")
    parser.add_argument("--crf", default="20", help="H.264 质量，越小越清晰")
    parser.add_argument("--preset", default="veryfast", help="x264 编码预设")
    parser.add_argument("--bgm", default="", help="Background music file or folder")
    parser.add_argument("--bgm-duck-db", default="18", help="Target BGM loudness below voice mean volume, in dB")
    parser.add_argument("--synthesize-voice", action="store_true", help="Synthesize narration audio from LRC text")
    parser.add_argument("--voice-style", default="calm_story", help="TTS voice style: calm_story, excited_research, documentary")
    parser.add_argument("--tts-model", default="", help="Gemini TTS model override")
    parser.add_argument("--burn-subtitles", action="store_true", help="Burn readable subtitles into the video")
    parser.add_argument("--generate-bgm", action="store_true", help="Generate one Gemini/Lyria BGM clip and exit")
    parser.add_argument("--bgm-output", default="", help="BGM library/output folder for --generate-bgm")
    parser.add_argument("--summary-root", default="", help="Folder containing full-book outline/summary for BGM prompting")
    parser.add_argument("--bgm-prompt", default="", help="Extra music direction appended to the generated BGM prompt")
    parser.add_argument("--bgm-model", default="lyria-3-clip-preview", help="Gemini/Lyria music generation model")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if bool(getattr(args, "generate_bgm", False)):
        generate_bgm_with_gemini(args)
        return 0

    if not args.images or not args.lrc or not args.output:
        raise SystemExit("--images, --lrc and --output are required unless --generate-bgm is used")
    image_dir = Path(args.images).expanduser().resolve()
    lrc_dir = Path(args.lrc).expanduser().resolve()
    if not image_dir.is_dir():
        raise SystemExit(f"图片素材文件夹不存在：{image_dir}")
    if not lrc_dir.is_dir():
        raise SystemExit(f"LRC 素材文件夹不存在：{lrc_dir}")

    ffmpeg = _tool_exe("ffmpeg")
    ffprobe = _tool_exe("ffprobe")
    print(f"FFmpeg：{ffmpeg}", flush=True)
    print(f"图片素材：{image_dir}", flush=True)
    print(f"LRC 素材：{lrc_dir}", flush=True)
    print(f"输出目录：{Path(args.output).expanduser().resolve()}", flush=True)

    image_index = build_image_index(image_dir)
    lrc_files = sorted(lrc_dir.glob("*.lrc"))
    if not lrc_files:
        raise SystemExit(f"LRC 文件夹里没有 .lrc 文件：{lrc_dir}")
    if not image_index:
        raise SystemExit(f"图片素材文件夹里没有可用图片：{image_dir}")

    ok = 0
    failed = 0
    for lrc_path in lrc_files:
        try:
            process_lrc_file(args, lrc_path, image_index, ffmpeg, ffprobe)
            ok += 1
        except Exception as exc:
            failed += 1
            print(f"失败：{lrc_path.name}：{type(exc).__name__}: {exc}", flush=True)

    print(f"\n自动剪辑结束：成功 {ok} 个，失败 {failed} 个。", flush=True)
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
