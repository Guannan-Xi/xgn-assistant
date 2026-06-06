from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
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
    size: str,
    fps: int,
    crf: int,
    preset: str,
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

        if audio_path:
            _run(
                [
                    ffmpeg,
                    "-hide_banner",
                    "-y",
                    "-i",
                    str(video_tmp),
                    "-i",
                    str(audio_path),
                    "-map",
                    "0:v:0",
                    "-map",
                    "1:a:0",
                    "-c:v",
                    "copy",
                    "-c:a",
                    "aac",
                    "-shortest",
                    str(output_video),
                ]
            )
        else:
            shutil.copy2(video_tmp, output_video)


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

    audio_path = _find_audio_for_lrc(lrc_path)
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
        size=args.size,
        fps=int(args.fps),
        crf=int(args.crf),
        preset=args.preset,
    )

    report = {
        "lrc": str(lrc_path),
        "audio": str(audio_path) if audio_path else "",
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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="按 LRC 里的画面编号自动匹配图片并合成视频。")
    parser.add_argument("--images", required=True, help="图片素材文件夹，文件名需包含 B26、B027 等画面编号")
    parser.add_argument("--lrc", required=True, help="LRC 素材文件夹")
    parser.add_argument("--output", required=True, help="输出文件夹")
    parser.add_argument("--size", default="1080x1920", help="输出尺寸，默认 1080x1920")
    parser.add_argument("--fps", default="30", help="输出帧率，默认 30")
    parser.add_argument("--last-seconds", default="4", help="没有同名音频时，最后一张图默认停留秒数")
    parser.add_argument("--crf", default="20", help="H.264 质量，越小越清晰")
    parser.add_argument("--preset", default="veryfast", help="x264 编码预设")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
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
