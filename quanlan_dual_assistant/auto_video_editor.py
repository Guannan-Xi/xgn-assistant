from __future__ import annotations

import argparse
import base64
import hashlib
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
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
AUDIO_EXTS = (".mp3", ".wav", ".m4a", ".aac", ".flac")
LRC_TIME_RE = re.compile(r"\[(\d{1,2}):(\d{2})(?:[.:](\d{1,3}))?\](.*)")
IMG_TAG_RE = re.compile(r"\{\s*img\s*=\s*([ABC]\d{0,4}|B\d{1,4}|[AC])\s*\}", re.I)
IMAGE_ID_RE = re.compile(r"^\s*(?:[\[【(（]\s*)?([ABC]\d{0,4}|[AC])(?:\s*[\]】)）])?\s*", re.I)
FILE_IMAGE_ID_RE = re.compile(r"(?<![A-Z0-9])([ABC]\d{1,4}|[AC]|B\d{1,4})(?![A-Z0-9])", re.I)


@dataclass
class LrcEvent:
    seconds: float
    image_id: str
    text: str
    duration: float = 0.0


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
    if name == "ffmpeg":
        try:
            import imageio_ffmpeg

            bundled = str(imageio_ffmpeg.get_ffmpeg_exe())
            if bundled and Path(bundled).exists():
                return bundled
        except Exception:
            pass

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
    if name == "ffprobe":
        return ""

    raise RuntimeError(
        f"Could not find {name}. Install FFmpeg or set FFMPEG_BIN to the ffmpeg.exe directory."
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
    text = IMG_TAG_RE.sub("", text or "")
    return IMAGE_ID_RE.sub("", text).strip()


def parse_lrc(path: Path) -> list[LrcEvent]:
    events: list[LrcEvent] = []
    current_image_id = ""
    for raw in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        match = LRC_TIME_RE.match(raw.strip())
        if not match:
            continue
        ts = _parse_time(match.group(1), match.group(2), match.group(3))
        payload = (match.group(4) or "").strip()
        marker = IMG_TAG_RE.search(payload) or IMAGE_ID_RE.search(payload)
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
    files = [file for file in sorted(image_dir.rglob("*")) if file.is_file() and file.suffix.lower() in IMAGE_EXTS]
    preferred_files = [file for file in files if not re.search(r"(共享|底图|母图|SHARED|BASE)", file.stem, re.I)]
    fallback_files = [file for file in files if file not in preferred_files]
    for file in [*preferred_files, *fallback_files]:
        stem = file.stem.upper()
        prefix = re.match(r"^([ABC]\d{0,4}|[AC])(?:[_\-\s]|$)", stem)
        if prefix:
            index.setdefault(_normalize_image_id(prefix.group(1)), file)
    for file in [*preferred_files, *fallback_files]:
        stem = file.stem.upper()
        exact = _normalize_image_id(stem)
        index.setdefault(exact, file)
        for found in FILE_IMAGE_ID_RE.findall(stem):
            index.setdefault(_normalize_image_id(found), file)
    return index


def find_image(image_id: str, index: dict[str, Path]) -> Path | None:
    for key in _image_id_candidates(image_id):
        if key in index:
            return index[key]
    return None


def _audio_duration(ffprobe: str, audio_path: Path) -> float:
    if ffprobe:
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
            pass
    try:
        ffmpeg = _tool_exe("ffmpeg")
        result = _run([ffmpeg, "-hide_banner", "-i", str(audio_path), "-f", "null", "-"], check=False)
        match = re.search(r"Duration:\s*(\d+):(\d{2}):(\d{2}(?:\.\d+)?)", result.stdout or "")
        if match:
            return int(match.group(1)) * 3600 + int(match.group(2)) * 60 + float(match.group(3))
    except Exception:
        pass
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


def _minimax_voice_id(style: str) -> str:
    voices = {
        "calm_story": "male-qn-qingse",
        "excited_research": "male-qn-jingying",
        "documentary": "male-qn-qingse",
    }
    return os.environ.get("MINIMAX_TTS_VOICE_ID", "").strip() or voices.get(str(style or "").strip(), "male-qn-qingse")


def _minimax_voice_profile_for_text(text: str, image_id: str, default_style: str) -> dict[str, Any]:
    value = re.sub(r"\s+", "", str(text or ""))
    style = str(default_style or "calm_story").strip() or "calm_story"
    profile = {
        "role": "steady_explainer",
        "voice_id": _minimax_voice_id(style),
        "speed": 0.92,
        "pitch": 0,
        "vol": 1.0,
    }
    if str(image_id or "").upper().startswith("A"):
        profile.update({"role": "opening_hook", "speed": 0.88, "pitch": 1, "vol": 1.04})
    elif str(image_id or "").upper().startswith("C"):
        profile.update({"role": "closing_summary", "speed": 0.86, "pitch": -1, "vol": 0.98})
    elif any(token in value for token in ["为什么", "但", "反而", "奇怪", "问题", "不是", "如果"]):
        profile.update({"role": "contrast_question", "speed": 0.94, "pitch": 1, "vol": 1.02})
    elif any(token in value for token in ["900万", "5岁", "研究", "数据", "证据", "实验", "随机", "结果"]):
        profile.update({"role": "evidence_explainer", "speed": 0.90, "pitch": 0, "vol": 1.0})
    elif any(token in value for token in ["挨饿", "贫穷", "孩子", "生病", "死亡", "困境", "痛苦"]):
        profile.update({"role": "empathetic_story", "speed": 0.88, "pitch": -1, "vol": 0.98})
    if len(value) >= 70 and profile["speed"] > 0.90:
        profile["speed"] = round(float(profile["speed"]) - 0.02, 2)
    return profile


def _minimax_base_url() -> str:
    base = os.environ.get("MINIMAX_BASE_URL", "").strip().rstrip("/") or _minimax_config_value("minimax_base_url")
    if not base:
        return "https://api.minimaxi.com/v1"
    return base if base.endswith("/v1") else base + "/v1"


def _minimax_endpoint() -> str:
    endpoint = os.environ.get("MINIMAX_TTS_ENDPOINT", "").strip()
    if endpoint:
        return endpoint
    return _minimax_base_url().rstrip("/") + "/t2a_v2"


def _minimax_api_key() -> str:
    for key_file in _minimax_key_candidates():
        if key_file.exists():
            value = key_file.read_text(encoding="utf-8-sig", errors="replace").lstrip("\ufeff").strip()
            if value:
                return value
    key = (
        os.environ.get("MINIMAX_API_KEY", "")
        or os.environ.get("MINIMAX_TTS_API_KEY", "")
        or os.environ.get("MINIMAX_GROUP_API_KEY", "")
    ).lstrip("\ufeff").strip()
    if key:
        return key
    return ""


def _minimax_key_candidates() -> list[Path]:
    candidates: list[Path] = []
    provider = _minimax_provider_hint()
    if provider == "fast":
        candidates.extend([PROJECT_ROOT / "minimax_fast_api_key.txt", PROJECT_ROOT / "minimax_api_key.txt", PROJECT_ROOT / "minimax_official_api_key.txt"])
    elif provider == "official":
        candidates.extend([PROJECT_ROOT / "minimax_official_api_key.txt", PROJECT_ROOT / "minimax_api_key.txt", PROJECT_ROOT / "minimax_fast_api_key.txt"])
    profiles_file = PROJECT_ROOT / "quanlan_model_profiles.json"
    if profiles_file.exists():
        try:
            data = json.loads(profiles_file.read_text(encoding="utf-8-sig", errors="replace"))
            profile = str(data.get("active_profile") or "").strip()
            if profile:
                candidates.append(PROJECT_ROOT / ".model_profiles" / profile / "minimax_api_key.txt")
        except Exception:
            pass
    env_file = PROJECT_ROOT / ".env.quanlan-model.local"
    if env_file.exists():
        for raw in env_file.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            line = raw.strip()
            if line.startswith("MINIMAX_API_KEY_FILE="):
                value = line.split("=", 1)[1].strip().strip('"').strip("'")
                if value:
                    path = Path(value)
                    candidates.append(path if path.is_absolute() else PROJECT_ROOT / path)
                    break
    candidates.append(PROJECT_ROOT / "minimax_api_key.txt")
    seen: set[str] = set()
    unique: list[Path] = []
    for candidate in candidates:
        marker = str(candidate.resolve() if candidate.exists() else candidate)
        if marker not in seen:
            seen.add(marker)
            unique.append(candidate)
    return unique


def _minimax_provider_hint() -> str:
    base = (
        os.environ.get("MINIMAX_BASE_URL", "").strip().lower()
        or _minimax_config_value("minimax_base_url").strip().lower()
    )
    settings_file = PROJECT_ROOT / "quanlan_dual_assistant_settings.json"
    provider = ""
    if settings_file.exists():
        try:
            data = json.loads(settings_file.read_text(encoding="utf-8-sig", errors="replace"))
            provider = str(data.get("minimax_provider") or "").strip().lower()
        except Exception:
            provider = ""
    if provider == "fast" or "api.53hk.cn" in base:
        return "fast"
    if provider == "official" or "api.minimaxi.com" in base:
        return "official"
    return ""


def _minimax_config_value(key: str) -> str:
    profiles_file = PROJECT_ROOT / "quanlan_model_profiles.json"
    if profiles_file.exists():
        try:
            data = json.loads(profiles_file.read_text(encoding="utf-8-sig", errors="replace"))
            active = str(data.get("active_profile") or "").strip()
            for item in data.get("profiles", []) if isinstance(data.get("profiles"), list) else []:
                if str(item.get("id") or "").strip() == active:
                    value = str((item.get("models") or {}).get(key) or "").strip()
                    if value:
                        return value
        except Exception:
            pass
    defaults_file = PROJECT_ROOT / "quanlan_model_defaults.json"
    if defaults_file.exists():
        try:
            data = json.loads(defaults_file.read_text(encoding="utf-8-sig", errors="replace"))
            return str(data.get(key) or "").strip()
        except Exception:
            return ""
    return ""


def _short_hash(text: str) -> str:
    return hashlib.sha1(str(text or "").encode("utf-8")).hexdigest()[:12]


def _minimax_request_audio(
    *,
    api_key: str,
    model: str,
    voice_id: str,
    text: str,
    speed: float,
    pitch: int,
    vol: float,
) -> bytes:
    payload = {
        "model": model,
        "text": text,
        "stream": False,
        "language_boost": "Chinese",
        "output_format": "hex",
        "voice_setting": {
            "voice_id": voice_id,
            "speed": speed,
            "vol": vol,
            "pitch": pitch,
        },
        "audio_setting": {
            "sample_rate": 32000,
            "bitrate": 128000,
            "format": "mp3",
            "channel": 1,
        },
    }
    req = urllib.request.Request(
        _minimax_endpoint(),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:2000]
        raise RuntimeError(f"MiniMax TTS HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"MiniMax TTS request failed: {exc}") from exc

    base_resp = data.get("base_resp") if isinstance(data, dict) else None
    if isinstance(base_resp, dict) and int(base_resp.get("status_code") or 0) not in {0, 1000}:
        raise RuntimeError(f"MiniMax TTS failed: {base_resp}")
    audio_hex = ""
    if isinstance(data, dict):
        audio_hex = str((data.get("data") or {}).get("audio") or data.get("audio") or "")
    if not audio_hex:
        raise RuntimeError(f"MiniMax TTS did not return audio. keys={list(data.keys()) if isinstance(data, dict) else type(data).__name__}")
    try:
        return bytes.fromhex(audio_hex)
    except ValueError as exc:
        raise RuntimeError("MiniMax TTS returned non-hex audio data") from exc


def synthesize_minimax_voice_from_lrc(args: argparse.Namespace, lrc_path: Path, output_dir: Path) -> Path:
    api_key = _minimax_api_key()
    if not api_key:
        raise RuntimeError("MINIMAX_API_KEY is required for MiniMax LRC voice synthesis")
    events = parse_lrc(lrc_path)
    text = "\n".join(_clean_tts_text(event.text) for event in events if _clean_tts_text(event.text))
    if not text:
        raise RuntimeError(f"LRC has no text to synthesize: {lrc_path}")
    model = str(getattr(args, "tts_model", "") or "speech-2.8-hd")
    style = str(getattr(args, "voice_style", "") or "calm_story")
    voice_id = str(getattr(args, "minimax_voice_id", "") or "").strip() or _minimax_voice_id(style)
    speed = float(getattr(args, "minimax_speed", 0.92) or 0.92)
    pitch = int(float(getattr(args, "minimax_pitch", 0) or 0))
    vol = float(getattr(args, "minimax_vol", 1.0) or 1.0)
    audio = _minimax_request_audio(
        api_key=api_key,
        model=model,
        voice_id=voice_id,
        text=text,
        speed=speed,
        pitch=pitch,
        vol=vol,
    )
    safe_voice = re.sub(r"[^A-Za-z0-9_-]+", "_", voice_id).strip("_") or "voice"
    out = output_dir / f"{_safe_output_stem(lrc_path)}_minimax_{safe_voice}.mp3"
    out.write_bytes(audio)
    return out


def synthesize_minimax_segmented_voice_from_lrc(args: argparse.Namespace, lrc_path: Path, output_dir: Path) -> Path:
    api_key = _minimax_api_key()
    if not api_key:
        raise RuntimeError("MINIMAX_API_KEY is required for MiniMax segmented LRC voice synthesis")
    events = parse_lrc(lrc_path)
    text_events = [(index, event, _clean_tts_text(event.text)) for index, event in enumerate(events, start=1)]
    text_events = [(index, event, text) for index, event, text in text_events if text]
    if not text_events:
        raise RuntimeError(f"LRC has no text to synthesize: {lrc_path}")

    model = str(getattr(args, "tts_model", "") or "speech-2.8-hd")
    style = str(getattr(args, "voice_style", "") or "calm_story")
    segment_delay = max(0.0, float(getattr(args, "minimax_segment_delay", 2.2) or 0.0))
    locked_voice_id = str(getattr(args, "minimax_voice_id", "") or "").strip() or _minimax_voice_id(style)
    locked_speed = float(getattr(args, "minimax_speed", 0.92) or 0.92)
    locked_pitch = int(float(getattr(args, "minimax_pitch", 0) or 0))
    locked_vol = float(getattr(args, "minimax_vol", 1.0) or 1.0)

    ffmpeg = _tool_exe("ffmpeg")
    ffprobe = _tool_exe("ffprobe")
    safe_voice = re.sub(r"[^A-Za-z0-9_-]+", "_", locked_voice_id).strip("_") or "voice"
    segment_dir = output_dir / "_tts_segments" / f"{_safe_output_stem(lrc_path)}_{safe_voice}"
    segment_dir.mkdir(parents=True, exist_ok=True)
    concat_path = segment_dir / "concat.txt"
    out = output_dir / f"{_safe_output_stem(lrc_path)}_minimax_{safe_voice}_segmented.mp3"
    timing_path = out.with_suffix(".timing.json")

    rows: list[dict[str, Any]] = []
    audio_segments: list[Path] = []
    cursor = 0.0
    for index, event, text in text_events:
        profile = _minimax_voice_profile_for_text(text, event.image_id, style)
        profile["voice_id"] = locked_voice_id
        profile["speed"] = locked_speed
        profile["pitch"] = locked_pitch
        profile["vol"] = locked_vol
        voice_id = str(profile["voice_id"])
        speed = float(profile["speed"])
        pitch = int(profile["pitch"])
        vol = float(profile["vol"])
        cache_key = _short_hash(f"{model}|{voice_id}|{speed}|{pitch}|{vol}|{text}")
        segment = segment_dir / f"{index:03d}_{_normalize_image_id(event.image_id)}_{cache_key}.mp3"
        if not segment.exists():
            print(f"  TTS segment {index}/{len(text_events)} {event.image_id} {profile['role']}: {text[:28]}", flush=True)
            last_error: Exception | None = None
            for attempt in range(1, 5):
                try:
                    audio = _minimax_request_audio(
                        api_key=api_key,
                        model=model,
                        voice_id=voice_id,
                        text=text,
                        speed=speed,
                        pitch=pitch,
                        vol=vol,
                    )
                    break
                except RuntimeError as exc:
                    last_error = exc
                    if "rate limit" not in str(exc).lower() or attempt >= 4:
                        raise
                    wait_seconds = 45.0 * attempt
                    print(f"    MiniMax rate limit; waiting {wait_seconds:.0f}s before retry {attempt + 1}/4", flush=True)
                    time.sleep(wait_seconds)
            else:
                raise RuntimeError(f"MiniMax TTS failed after retries: {last_error}")
            segment.write_bytes(audio)
            if segment_delay:
                time.sleep(segment_delay)
        duration = _audio_duration(ffprobe, segment)
        rows.append(
            {
                "seconds": round(cursor, 6),
                "duration": round(duration, 6),
                "image_id": event.image_id,
                "text": event.text,
                "audio": str(segment),
                "voice_profile": {
                    "role": profile["role"],
                    "voice_id": voice_id,
                    "speed": speed,
                    "pitch": pitch,
                    "vol": vol,
                },
            }
        )
        cursor += max(0.05, duration)
        audio_segments.append(segment)

    _concat_file(concat_path, audio_segments)
    _run([ffmpeg, "-hide_banner", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_path), "-c", "copy", str(out)])
    timing_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


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


def synthesize_voice_from_lrc(args: argparse.Namespace, lrc_path: Path, output_dir: Path) -> Path | None:
    if not bool(getattr(args, "synthesize_voice", False)):
        return None
    provider = str(getattr(args, "tts_provider", "") or "minimax").strip().lower()
    if provider in {"", "minimax"}:
        if bool(getattr(args, "tts_segmented", False)):
            return synthesize_minimax_segmented_voice_from_lrc(args, lrc_path, output_dir)
        return synthesize_minimax_voice_from_lrc(args, lrc_path, output_dir)
    raise RuntimeError(f"Unsupported TTS provider: {provider}. This workflow uses MiniMax TTS only.")


def _find_audio_for_lrc(lrc_path: Path, output_dir: Path | None = None) -> Path | None:
    for ext in AUDIO_EXTS:
        candidate = lrc_path.with_suffix(ext)
        if candidate.exists():
            return candidate
    if output_dir and output_dir.exists():
        for ext in AUDIO_EXTS:
            candidates = sorted(output_dir.glob(f"{lrc_path.stem}_*{ext}"), key=lambda p: p.stat().st_mtime, reverse=True)
            if candidates:
                return candidates[0]
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


def _estimated_tail_seconds(event: LrcEvent | None, last_seconds: float) -> float:
    if event is None:
        return max(0.5, float(last_seconds))
    text_len = len(re.sub(r"\s+", "", event.text or ""))
    if text_len <= 0:
        return max(0.5, float(last_seconds))
    return max(float(last_seconds), min(18.0, text_len * 0.28))


def _scale_events_to_audio(events: list[LrcEvent], final_end: float, last_seconds: float) -> tuple[list[LrcEvent], float]:
    if not events or final_end <= 0:
        return events, 1.0
    planned_end = events[-1].seconds + _estimated_tail_seconds(events[-1], last_seconds)
    if planned_end <= 0 or final_end <= planned_end * 1.08:
        return events, 1.0
    scale = final_end / planned_end
    return [
        LrcEvent(seconds=event.seconds * scale, image_id=event.image_id, text=event.text, duration=event.duration)
        for event in events
    ], scale



def _speech_weight(text: str) -> float:
    value = re.sub(r"\s+", "", str(text or ""))
    if not value:
        return 1.0
    pauses = 0.0
    pauses += len(re.findall(r"[。！？!?]", value)) * 4.0
    pauses += len(re.findall(r"[，、；：,;:]", value)) * 2.0
    pauses += len(re.findall(r"[,.!?;:]", value)) * 1.5
    return max(1.0, len(value) + pauses)


def _protected_subtitle_split(value: str, pos: int) -> bool:
    protected_spans = [
        r"《[^》]{1,24}》",
        r"\d{4}年诺贝尔经济学奖",
        r"\d{4}年",
        r"诺贝尔经济学奖",
        r"反贫困研究成果",
        r"反贫困研究代表作",
        r"\d+万儿童活不到\d+岁",
        r"活不到\d+岁",
        r"\d+万儿童",
        r"\d+(?:\.\d+)?[%％]",
        r"\d+(?:\.\d+)?美元",
        r"具体问题",
        r"世界模式",
        r"有意义",
    ]
    for pattern in protected_spans:
        for match in re.finditer(pattern, value):
            if match.start() < pos < match.end():
                return True
    left = value[max(0, pos - 8):pos]
    right = value[pos:pos + 8]
    around = left + "|" + right
    if left.endswith("活不") and re.match(r"^到\d+岁", right):
        return True
    if re.search(r"\d+(?:\.\d+)?\|[%％]", around):
        return True
    if re.search(r"\d{4}\|年", around):
        return True
    if left.endswith("诺贝尔") and right.startswith("经济学奖"):
        return True
    if left.endswith("经济学") and right.startswith("奖"):
        return True
    if left.endswith("经济") and right.startswith("学奖"):
        return True
    if re.search(r"\d+\|", around) and right[:1] in set("岁美元万人亿元年月日个只张本次"):
        return True
    if left.endswith("万") and right[:1] in set("儿人学家"):
        return True
    if left.endswith("反") and right.startswith("贫困"):
        return True
    if left.endswith("贫困") and right.startswith("研究"):
        return True
    if left.endswith("一") and right[:1] in set("个项组种半只张本次"):
        return True
    if left.endswith("一个") and right.startswith("小女孩"):
        return True
    if left.endswith("小") and right[:1] in set("女男孩"):
        return True
    if left.endswith("正") and right.startswith("在"):
        return True
    if left.endswith("挨") and right.startswith("饿"):
        return True
    if left.endswith("讲") and right.startswith("起"):
        return True
    if left.endswith("下") and right.startswith("降"):
        return True
    if left.endswith("极") and right.startswith("度"):
        return True
    if left.endswith("其") and right.startswith("他"):
        return True
    if re.search(r"第\d+\|", around) and right[:1] in set("章节期个"):
        return True
    if re.search(r"[A-Za-z]\|", around) and right.startswith("形曲线"):
        return True
    return False


def _subtitle_split_allowed(value: str, pos: int) -> bool:
    if pos <= 0 or pos >= len(value):
        return False
    if _protected_subtitle_split(value, pos):
        return False
    left = value[:pos]
    right = value[pos:]
    if not left or not right:
        return False
    bad_left_endings = (
        "来自",
        "来自获得",
        "获得",
        "做过一个",
        "同意一个",
        "隐含了一个",
        "一个",
        "一个小",
        "一项",
        "一组",
        "一种",
        "这个",
        "那个",
        "这本",
        "原书",
        "诺贝尔经济学奖",
        "诺贝尔经济学奖的",
        "反贫困",
        "具体问",
        "世界模",
        "有意",
        "活不到",
        "价值",
        "一件价值",
        "正在",
        "正在挨",
        "挨",
        "下降",
        "或正在",
    )
    if left.endswith(bad_left_endings):
        return False
    if left[-1] in set("反一小正挨讲下极其"):
        return False
    if left[-1] in set("的了着过地得"):
        return False
    if right[0] in set("的了着过地得、，。；：！？,.!?;:）》】"):
        return False
    if left[-1] in set("《（【("):
        return False
    if left.endswith("这本") and right.startswith("书"):
        return False
    if left.endswith("原") and right.startswith("书"):
        return False
    if left.endswith("诺贝尔经济学奖") and right.startswith("的"):
        return False
    if left.endswith("价值") and re.match(r"^\d", right):
        return False
    if re.search(r"[A-Za-z0-9]$", left) and re.match(r"^[A-Za-z0-9]", right):
        return False
    return True


def _best_subtitle_split(value: str, max_chars: int) -> int:
    upper = min(max_chars, len(value) - 1)
    lower = max(3, upper - 13)
    if upper <= lower:
        return max(1, upper)
    for chars in ("。！？；：，、,.!?;:", "你我他她它们和与在是为把被对从到给让向"):
        for pos in range(upper, lower - 1, -1):
            if value[pos - 1] in chars and len(value) - pos > 2 and _subtitle_split_allowed(value, pos):
                return pos
    for pos in range(upper, lower - 1, -1):
        if _subtitle_split_allowed(value, pos):
            return pos
    if len(value) - upper <= 2:
        return max(lower, len(value) - max_chars)
    return upper


def _split_long_subtitle_part(value: str, max_chars: int) -> list[str]:
    part = str(value or "")
    chunks: list[str] = []
    while len(part) > max_chars:
        if len(part) == max_chars + 1 and re.search(r"[。！？；：，、,.!?;:]$", part):
            break
        split_at = _best_subtitle_split(part, max_chars)
        chunk, part = part[:split_at], part[split_at:]
        while part and re.match(r"[。！？；：，、,.!?;:]", part[0]):
            chunk += part[0]
            part = part[1:]
        chunks.append(chunk)
    if part:
        chunks.append(part)
    return chunks


def _rebalance_subtitle_chunks(chunks: list[str], max_chars: int) -> list[str]:
    values = [chunk for chunk in chunks if chunk]
    tiny_tails = set("能力浪费方式问题前提证据实验市场资金教育机会影响")
    index = 1
    while index < len(values):
        current = values[index]
        previous = values[index - 1]
        if len(current) <= 2 and len(previous) + len(current) <= max_chars + 4:
            values[index - 1] = previous + current
            del values[index]
            continue
        if current in tiny_tails and len(previous) + len(current) <= max_chars + 6:
            values[index - 1] = previous + current
            del values[index]
            continue
        index += 1
    for index in range(1, len(values)):
        while values[index] and values[index][0] in set("的了着过地得") and len(values[index - 1]) < max_chars + 2:
            values[index - 1] += values[index][0]
            values[index] = values[index][1:]
    bad_tail_patterns = (
        "来自",
        "来自获得",
        "获得",
        "做过一个",
        "同意一个",
        "隐含了一个",
        "一个",
        "一个小",
        "一项",
        "一组",
        "一种",
        "这个",
        "那个",
        "这本",
        "原书",
        "诺贝尔经济学奖",
        "诺贝尔经济学奖的",
        "反贫困",
        "活不到",
    )
    for index in range(0, len(values) - 1):
        while values[index].endswith(bad_tail_patterns) and values[index + 1] and len(values[index]) < max_chars + 4:
            values[index] += values[index + 1][0]
            values[index + 1] = values[index + 1][1:]
    return [chunk for chunk in values if chunk]


def _align_events_to_audio(events: list[LrcEvent], final_end: float, last_seconds: float) -> tuple[list[LrcEvent], str, float]:
    if not events or final_end <= 0:
        return events, "lrc", 1.0
    total_weight = sum(_speech_weight(event.text) for event in events)
    if total_weight <= 0:
        scaled, scale = _scale_events_to_audio(events, final_end, last_seconds)
        return scaled, "linear_scale", scale
    aligned: list[LrcEvent] = []
    elapsed_weight = 0.0
    for event in events:
        seconds = final_end * elapsed_weight / total_weight
        aligned.append(LrcEvent(seconds=seconds, image_id=event.image_id, text=event.text, duration=event.duration))
        elapsed_weight += _speech_weight(event.text)
    planned_end = events[-1].seconds + _estimated_tail_seconds(events[-1], last_seconds)
    scale = final_end / planned_end if planned_end > 0 else 1.0
    return aligned, "text_weighted_audio", scale


def _load_segmented_timing(audio_path: Path | None) -> list[LrcEvent]:
    if not audio_path:
        return []
    timing_path = audio_path.with_suffix(".timing.json")
    if not timing_path.exists():
        return []
    data = json.loads(timing_path.read_text(encoding="utf-8"))
    events: list[LrcEvent] = []
    for item in data if isinstance(data, list) else []:
        try:
            seconds = float(item.get("seconds") or 0.0)
        except (TypeError, ValueError):
            seconds = 0.0
        try:
            duration = float(item.get("duration") or 0.0)
        except (TypeError, ValueError):
            duration = 0.0
        image_id = _normalize_image_id(str(item.get("image_id") or ""))
        text = str(item.get("text") or "")
        if image_id and text:
            events.append(LrcEvent(seconds=seconds, image_id=image_id, text=text, duration=duration))
    return events


def _timed_events_final_end(events: list[LrcEvent]) -> float:
    ends = [event.seconds + event.duration for event in events if event.duration > 0]
    return max(ends) if ends else 0.0


def _subtitle_chunks(text: str, max_chars: int = 14) -> list[str]:
    value = re.sub(r"\s+", "", str(text or "")).strip()
    if not value:
        return []
    parts = [p for p in re.split(r"(?<=[。！？；，：、])", value) if p]
    chunks: list[str] = []
    current = ""
    for part in parts or [value]:
        if len(current) + len(part) <= max_chars:
            current += part
            continue
        if current:
            chunks.append(current)
            current = ""
        split_parts = _split_long_subtitle_part(part, max_chars)
        chunks.extend(split_parts[:-1])
        current = split_parts[-1] if split_parts else ""
    if current:
        chunks.append(current)
    chunks = _rebalance_subtitle_chunks(chunks or [value], max_chars)
    cleaned = [_clean_subtitle_display(chunk) for chunk in chunks]
    return [chunk for chunk in cleaned if chunk]


def _clean_subtitle_display(text: str) -> str:
    value = str(text or "").strip()
    value = value.lstrip("\u3002\uff0c\uff01\uff1f\u3001\uff1b\uff1a,.!?;:")
    value = value.rstrip("\u3002\uff0c\uff01\uff1f\u3001\uff1b\uff1a,.!?;:")
    return value.strip()


def _ass_time(seconds: float) -> str:
    cs_total = int(round(max(0.0, seconds) * 100))
    cs = cs_total % 100
    sec_total = cs_total // 100
    sec = sec_total % 60
    minute_total = sec_total // 60
    minute = minute_total % 60
    hour = minute_total // 60
    return f"{hour}:{minute:02d}:{sec:02d}.{cs:02d}"


def _ass_text(text: str) -> str:
    return str(text or "").replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}").replace("\n", "\\N")


def write_ass(path: Path, events: list[LrcEvent], final_end: float, last_seconds: float) -> None:
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 720",
        "PlayResY: 1280",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: Default,Microsoft YaHei,32,&H00000000,&H000000FF,&H00FFFFFF,&H80FFFFFF,0,0,0,0,100,100,0,0,4,0,0,2,52,52,82,1",
        "Style: CoverA,Microsoft YaHei,29,&H00F8F4E4,&H000000FF,&H90000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,2,48,48,92,1",
        "Style: CoverC,Microsoft YaHei,27,&H00324A5C,&H000000FF,&H00FFF9EA,&H90FFF9EA,0,0,0,0,100,100,0,0,4,0,0,2,56,56,150,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    text_events = [event for event in events if event.text.strip()]
    for index, event in enumerate(text_events):
        end = text_events[index + 1].seconds if index + 1 < len(text_events) else (final_end or event.seconds + last_seconds)
        if end <= event.seconds:
            end = event.seconds + max(0.5, last_seconds)
        normalized_image_id = _normalize_image_id(event.image_id)
        style = "Default"
        max_chars = 16
        if normalized_image_id.startswith("A"):
            style = "CoverA"
            max_chars = 18
        elif normalized_image_id.startswith("C"):
            style = "CoverC"
            max_chars = 18
        chunks = _subtitle_chunks(event.text, max_chars=max_chars)
        duration = max(0.5, end - event.seconds)
        weights = [_speech_weight(chunk) for chunk in chunks]
        total_weight = sum(weights) or float(len(chunks) or 1)
        elapsed_weight = 0.0
        for chunk_index, chunk in enumerate(chunks):
            start = event.seconds + duration * elapsed_weight / total_weight
            elapsed_weight += weights[chunk_index]
            chunk_end = end if chunk_index == len(chunks) - 1 else event.seconds + duration * elapsed_weight / total_weight
            lines.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(chunk_end)},{style},,0,0,0,,{_ass_text(chunk)}")
    path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def write_srt(path: Path, events: list[LrcEvent], final_end: float, last_seconds: float) -> None:
    lines: list[str] = []
    subtitle_index = 1
    text_events = [event for event in events if event.text.strip()]
    for index, event in enumerate(text_events):
        end = text_events[index + 1].seconds if index + 1 < len(text_events) else (final_end or event.seconds + last_seconds)
        normalized_image_id = _normalize_image_id(event.image_id)
        if end <= event.seconds:
            end = event.seconds + max(0.5, last_seconds)
        chunks = _subtitle_chunks(event.text, max_chars=16)
        duration = max(0.5, end - event.seconds)
        weights = [_speech_weight(chunk) for chunk in chunks]
        total_weight = sum(weights) or float(len(chunks) or 1)
        elapsed_weight = 0.0
        for chunk_index, chunk in enumerate(chunks):
            start = event.seconds + duration * elapsed_weight / total_weight
            elapsed_weight += weights[chunk_index]
            chunk_end = end if chunk_index == len(chunks) - 1 else event.seconds + duration * elapsed_weight / total_weight
            lines.extend([str(subtitle_index), f"{_srt_time(start)} --> {_srt_time(chunk_end)}", chunk, ""])
            subtitle_index += 1
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
            _run([ffmpeg, "-hide_banner", "-y", "-i", str(video_tmp), "-vf", f"subtitles='{subtitle_filter}'", "-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p", "-an", str(subtitled_tmp)])
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
        raise ValueError("Video size must look like 1080x1920")
    return int(match.group(1)), int(match.group(2))


def _safe_output_stem(lrc_path: Path) -> str:
    parent = lrc_path.parent.name.strip()
    stem = lrc_path.stem.strip()
    raw = f"{parent}_{stem}" if parent and parent not in {".", stem} else stem
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", raw).strip(" ._")
    return safe or stem or "video"


def process_lrc_file(args: argparse.Namespace, lrc_path: Path, image_index: dict[str, Path], ffmpeg: str, ffprobe: str) -> dict:
    output_dir = Path(args.output).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_stem = _safe_output_stem(lrc_path)
    out_video = output_dir / f"{output_stem}_自动剪辑.mp4"
    out_srt = output_dir / f"{output_stem}_字幕.srt"
    out_ass = output_dir / f"{output_stem}_字幕.ass"
    report_path = output_dir / f"{output_stem}_自动剪辑报告.json"

    print(f"\nProcessing LRC: {lrc_path}", flush=True)
    events = parse_lrc(lrc_path)
    if not events:
        raise RuntimeError(f"No timed image events found in LRC: {lrc_path}")

    audio_path = synthesize_voice_from_lrc(args, lrc_path, output_dir) or _find_audio_for_lrc(lrc_path, output_dir)
    bgm_path = _resolve_bgm_for_lrc(args, lrc_path)
    final_end = _audio_duration(ffprobe, audio_path) if audio_path else 0.0
    segmented_events = _load_segmented_timing(audio_path)
    if segmented_events:
        final_end = max(final_end, _timed_events_final_end(segmented_events))
        timeline_events, timeline_mode, timeline_scale = segmented_events, "segmented_tts", 1.0
        print("  timeline aligned to segmented TTS durations", flush=True)
    else:
        timeline_events, timeline_mode, timeline_scale = _align_events_to_audio(events, final_end, float(args.last_seconds))
    if timeline_mode == "text_weighted_audio":
        print(f"  timeline aligned to whole-file TTS by text weight: x{timeline_scale:.3f}", flush=True)
    elif timeline_scale != 1.0:
        print(f"  timeline scaled to audio: x{timeline_scale:.3f}", flush=True)
    scenes, missing = build_scenes(
        timeline_events,
        image_index,
        final_end=final_end,
        last_seconds=float(args.last_seconds),
    )
    if missing:
        raise RuntimeError("Missing image assets: " + ", ".join(missing))
    if not scenes:
        raise RuntimeError("No renderable scenes.")

    write_srt(out_srt, timeline_events, final_end, float(args.last_seconds))
    write_ass(out_ass, timeline_events, final_end, float(args.last_seconds))
    render_video(
        ffmpeg,
        scenes,
        out_video,
        audio_path=audio_path,
        subtitle_path=out_ass if bool(args.burn_subtitles) else None,
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
        "subtitle_ass": str(out_ass),
        "scene_count": len(scenes),
        "events": len(events),
        "timeline_mode": timeline_mode,
        "timeline_scale": round(timeline_scale, 4),
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
    print(f"Done: {out_video}", flush=True)
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
        "Instrumental-only background music bed for a Chinese book explainer short video. "
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
        or "https://www.fhl.mom/v1"
    ).rstrip("/")
    if not base.endswith("/v1"):
        base += "/v1"
    return base


def _minimax_music_endpoint() -> str:
    endpoint = os.environ.get("MINIMAX_MUSIC_ENDPOINT", "").strip()
    if endpoint:
        return endpoint
    return _minimax_base_url().rstrip("/") + "/music_generation"


def _minimax_music_audio(prompt: str, *, api_key: str, model: str) -> tuple[bytes, dict[str, Any]]:
    payload = {
        "model": model,
        "prompt": prompt[:2000],
        "stream": False,
        "output_format": "hex",
        "is_instrumental": True,
        "audio_setting": {
            "sample_rate": 44100,
            "bitrate": 256000,
            "format": "mp3",
        },
    }
    req = urllib.request.Request(
        _minimax_music_endpoint(),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:2000]
        raise RuntimeError(f"MiniMax BGM HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"MiniMax BGM request failed: {exc}") from exc

    base_resp = data.get("base_resp") if isinstance(data, dict) else None
    if isinstance(base_resp, dict) and int(base_resp.get("status_code") or 0) not in {0, 1000}:
        raise RuntimeError(f"MiniMax BGM failed: {base_resp}")
    audio_hex = str((data.get("data") or {}).get("audio") or "")
    audio_url = str((data.get("data") or {}).get("audio_url") or (data.get("data") or {}).get("url") or "")
    if audio_url:
        try:
            with urllib.request.urlopen(audio_url, timeout=180) as resp:
                return resp.read(), data
        except urllib.error.URLError as exc:
            raise RuntimeError(f"MiniMax BGM audio_url download failed: {exc}") from exc
    if not audio_hex:
        raise RuntimeError(f"MiniMax BGM did not return audio. keys={list(data.keys()) if isinstance(data, dict) else type(data).__name__}")
    try:
        return bytes.fromhex(audio_hex), data
    except ValueError as exc:
        try:
            return base64.b64decode(audio_hex), data
        except Exception:
            raise RuntimeError("MiniMax BGM returned non-hex/non-base64 audio data") from exc


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


def generate_bgm_with_minimax(args: argparse.Namespace) -> Path:
    key = _minimax_api_key()
    if not key:
        raise RuntimeError("BGM generation requires MINIMAX_API_KEY.")
    output_dir = Path(args.bgm_output or args.output or PROJECT_ROOT / "_temp" / "bgm_library").expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_root = Path(args.summary_root or args.output or output_dir).expanduser().resolve()
    book_context = _read_book_context(summary_root) if summary_root.exists() else ""
    prompt = _build_bgm_prompt(book_context, str(args.bgm_prompt or ""))

    model = str(args.bgm_model or "music-2.6")
    audio, response = _minimax_music_audio(prompt, api_key=key, model=model)
    safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", summary_root.name or "book")[:40].strip("_") or "book"
    out = output_dir / f"bgm_{safe_name}_{len(list(output_dir.glob('bgm_*.mp3'))) + 1:03d}.mp3"
    out.write_bytes(audio)
    out.with_suffix(".prompt.txt").write_text(prompt, encoding="utf-8")
    out.with_suffix(".response.json").write_text(json.dumps(response, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Generated MiniMax BGM: {out}", flush=True)
    return out


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render a video by matching LRC image ids to image files.")
    parser.add_argument("--images", default="", help="Image asset folder; filenames should contain ids such as A1 or B26")
    parser.add_argument("--lrc", default="", help="LRC asset folder")
    parser.add_argument("--lrc-file", default="", help="Optional single LRC filename or path to render")
    parser.add_argument("--output", default="", help="Output folder")
    parser.add_argument("--size", default="1080x1920", help="杈撳嚭灏哄锛岄粯璁?1080x1920")
    parser.add_argument("--fps", default="30", help="杈撳嚭甯х巼锛岄粯璁?30")
    parser.add_argument("--last-seconds", default="4", help="娌℃湁鍚屽悕闊抽鏃讹紝鏈€鍚庝竴寮犲浘榛樿鍋滅暀绉掓暟")
    parser.add_argument("--crf", default="20", help="H.264 璐ㄩ噺锛岃秺灏忚秺娓呮櫚")
    parser.add_argument("--preset", default="veryfast", help="x264 缂栫爜棰勮")
    parser.add_argument("--bgm", default="", help="Background music file or folder")
    parser.add_argument("--bgm-duck-db", default="18", help="Target BGM loudness below voice mean volume, in dB")
    parser.add_argument("--synthesize-voice", action="store_true", help="Synthesize narration audio from LRC text")
    parser.add_argument("--tts-provider", default="minimax", help="TTS provider: minimax")
    parser.add_argument("--tts-segmented", action="store_true", help="Synthesize one TTS audio segment per LRC event and use real segment durations as timestamps")
    parser.add_argument("--voice-style", default="calm_story", help="TTS voice style: calm_story, excited_research, documentary")
    parser.add_argument("--tts-model", default="", help="MiniMax TTS model override, default speech-2.8-hd")
    parser.add_argument("--minimax-voice-id", default="", help="MiniMax voice_id override; or set MINIMAX_TTS_VOICE_ID")
    parser.add_argument("--minimax-speed", default="0.92", help="MiniMax voice speed")
    parser.add_argument("--minimax-pitch", default="0", help="MiniMax voice pitch")
    parser.add_argument("--minimax-vol", default="1.0", help="MiniMax voice volume")
    parser.add_argument("--minimax-segment-delay", default="2.2", help="Delay between segmented MiniMax TTS requests, seconds")
    parser.add_argument("--burn-subtitles", action="store_true", help="Burn readable subtitles into the video")
    parser.add_argument("--generate-bgm", action="store_true", help="Generate one MiniMax instrumental BGM clip and exit")
    parser.add_argument("--bgm-output", default="", help="BGM library/output folder for --generate-bgm")
    parser.add_argument("--summary-root", default="", help="Folder containing full-book outline/summary for BGM prompting")
    parser.add_argument("--bgm-prompt", default="", help="Extra music direction appended to the generated BGM prompt")
    parser.add_argument("--bgm-model", default="music-2.6", help="MiniMax music generation model")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if bool(getattr(args, "generate_bgm", False)):
        generate_bgm_with_minimax(args)
        return 0

    if not args.images or not args.lrc or not args.output:
        raise SystemExit("--images, --lrc and --output are required unless --generate-bgm is used")
    image_dir = Path(args.images).expanduser().resolve()
    lrc_dir = Path(args.lrc).expanduser().resolve()
    if not image_dir.is_dir():
        raise SystemExit(f"Image folder does not exist: {image_dir}")
    if not lrc_dir.is_dir():
        raise SystemExit(f"LRC folder does not exist: {lrc_dir}")

    ffmpeg = _tool_exe("ffmpeg")
    ffprobe = _tool_exe("ffprobe")
    print(f"FFmpeg: {ffmpeg}", flush=True)
    print(f"Images: {image_dir}", flush=True)
    print(f"LRC: {lrc_dir}", flush=True)
    print(f"Output: {Path(args.output).expanduser().resolve()}", flush=True)

    image_index = build_image_index(image_dir)
    if str(getattr(args, "lrc_file", "") or "").strip():
        requested_lrc = Path(str(args.lrc_file)).expanduser()
        if not requested_lrc.is_absolute():
            requested_lrc = lrc_dir / requested_lrc
        lrc_files = [requested_lrc.resolve()]
    else:
        lrc_files = sorted(lrc_dir.glob("*.lrc"))
    if not lrc_files:
        raise SystemExit(f"No .lrc files found in: {lrc_dir}")
    for lrc_path in lrc_files:
        if not lrc_path.exists():
            raise SystemExit(f"LRC file does not exist: {lrc_path}")
    if not image_index:
        raise SystemExit(f"No usable images found in: {image_dir}")

    ok = 0
    failed = 0
    for lrc_path in lrc_files:
        try:
            process_lrc_file(args, lrc_path, image_index, ffmpeg, ffprobe)
            ok += 1
        except Exception as exc:
            failed += 1
            print(f"Failed: {lrc_path.name}: {type(exc).__name__}: {exc}", flush=True)

    print(f"\nAuto video render finished: ok={ok}, failed={failed}", flush=True)
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())


