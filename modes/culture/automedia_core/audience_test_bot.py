from __future__ import annotations

import argparse
import json
import re
import time
import urllib.parse
import urllib.request
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[3]
PROMPTS_DIR = PROJECT_ROOT / "prompts"
DEFAULT_BOT_DIR = PROJECT_ROOT / "outputs" / "audience_test_bot"
SETTINGS_FILE = REPO_ROOT / "quanlan_dual_assistant_settings.json"
BOOK_REPORT_FOLDER = "小猪理观众测试"

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

AUDIENCE_QUERIES = [
    "名著解读 视频号 观众 评论 读书",
    "经典名著 解读 短视频 观众 想看",
    "微信视频号 读书号 观众 喜欢 什么内容",
    "名著解读 公众号 选题 评论",
    "读书博主 名著解读 评论 区",
]

PERSONAS = [
    {
        "name": "没读过原书的普通观众",
        "pain": "第一句话必须听懂，不要先堆作者、章节、术语。",
        "must": ["清晰问题", "具体人物或处境", "少抽象名词"],
    },
    {
        "name": "愿意转发到朋友圈的观众",
        "pain": "需要一个能解释为什么值得转发的现实处境。",
        "must": ["转发对象", "可复述判断", "不鸡汤"],
    },
    {
        "name": "文史爱好者",
        "pain": "讨厌把经典讲成权谋爽文或现代职场段子。",
        "must": ["尊重原书", "术语准确", "人物不扁平"],
    },
    {
        "name": "中年微信视频号观众",
        "pain": "喜欢人情、规矩、处境和选择压力，不喜欢网梗。",
        "must": ["人情规矩", "选择后果", "克制口播"],
    },
    {
        "name": "短视频运营审片人",
        "pain": "标题、封面、A1、C 和发布文案必须在同一条传播主线。",
        "must": ["前3秒问题", "前15秒冲突", "C承接下一集"],
    },
]

MATERIAL_FILE_CANDIDATES = {
    "intro_json": ["04_视频简介.json", "04_瑙嗛绠€浠?json"],
    "intro_txt": ["04_视频简介.txt", "04_瑙嗛绠€浠?txt"],
    "lrc": ["01_台词.lrc", "01_鍙拌瘝.lrc"],
    "script": ["02_脚本.json", "02_鑴氭湰.json"],
    "quality": ["230人评审质检清单.json", "230浜鸿瘎瀹¤川妫€娓呭崟.json"],
    "meta": ["封面片尾元数据.json", "灏侀潰鐗囧熬鍏冩暟鎹?json"],
}
DISCOVERY_MARKERS = [name for names in MATERIAL_FILE_CANDIDATES.values() for name in names]


@dataclass
class Finding:
    severity: str
    area: str
    message: str
    target: str
    suggestion: str
    auto_fixable: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "area": self.area,
            "message": self.message,
            "target": self.target,
            "suggestion": self.suggestion,
            "auto_fixable": self.auto_fixable,
        }


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _read_text(path: Path, max_chars: int = 120_000) -> str:
    try:
        return path.read_text(encoding="utf-8-sig", errors="replace")[:max_chars]
    except Exception:
        return ""


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None


def _load_json_from_text(text: str) -> Any:
    try:
        return json.loads(text)
    except Exception:
        return None


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _append_jsonl(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(data, ensure_ascii=False) + "\n")


def _candidate_book_pdf(path_text: str | None) -> Path | None:
    if not path_text:
        return None
    path = Path(str(path_text).strip().strip('"'))
    if path.suffix.lower() != ".pdf":
        return None
    return path


def _settings_book_pdf() -> Path | None:
    settings = _load_json(SETTINGS_FILE)
    if not isinstance(settings, dict):
        return None
    for key in ("culture_book", "book_pdf", "source_book", "pdf_path"):
        path = _candidate_book_pdf(settings.get(key))
        if path:
            return path
    return None


def resolve_report_paths(book_pdf_arg: str | None) -> dict[str, Path | None]:
    book_pdf = _candidate_book_pdf(book_pdf_arg) or _settings_book_pdf()
    report_dir = book_pdf.parent / BOOK_REPORT_FOLDER if book_pdf else DEFAULT_BOT_DIR
    try:
        report_dir.relative_to(REPO_ROOT)
    except ValueError:
        report_dir = DEFAULT_BOT_DIR
    return {
        "book_pdf": book_pdf,
        "report_dir": report_dir,
        "report_file": report_dir / "latest_audience_test_report.json",
        "issue_file": report_dir / "audience_test_issues.jsonl",
        "patch_log": report_dir / "auto_patch_log.jsonl",
    }


def _safe_fetch(url: str, timeout: int = 12) -> str:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 audience-test-bot/1.0; public-signal-only; no-contact"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read(160_000).decode("utf-8", errors="replace")


def collect_public_signals(*, online: bool = False, limit: int = 5) -> list[dict[str, str]]:
    signals: list[dict[str, str]] = []
    if not online:
        for persona in PERSONAS:
            signals.append(
                {
                    "source": "built_in_persona",
                    "query": persona["name"],
                    "summary": f"{persona['pain']} 必须满足：{'、'.join(persona['must'])}",
                }
            )
        return signals

    for query in AUDIENCE_QUERIES[:limit]:
        search_url = "https://www.bing.com/search?q=" + urllib.parse.quote(query)
        try:
            html = _safe_fetch(search_url)
            text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S | re.I)
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text).strip()
            signals.append({"source": "bing_public_search", "query": query, "summary": text[:900]})
            time.sleep(1.0)
        except Exception as exc:
            signals.append({"source": "fetch_error", "query": query, "summary": f"{type(exc).__name__}: {exc}"})
    return signals


def discover_material_dirs(root: Path) -> list[Path]:
    root = Path(root)
    if not root.exists():
        return []
    candidates: set[Path] = set()
    for marker in DISCOVERY_MARKERS:
        for path in root.rglob(marker):
            candidates.add(path.parent)
    return sorted(candidates)


def _first_existing(material_dir: Path, names: list[str]) -> Path | None:
    for name in names:
        path = material_dir / name
        if path.exists():
            return path
    return None


def _material_text(material_dir: Path) -> dict[str, str]:
    texts: dict[str, str] = {}
    for key, names in MATERIAL_FILE_CANDIDATES.items():
        path = _first_existing(material_dir, names)
        if path:
            texts[key] = _read_text(path)
    return texts


def _intro_data(texts: dict[str, str]) -> dict[str, Any]:
    if texts.get("intro_json"):
        data = _load_json_from_text(texts["intro_json"])
        if isinstance(data, dict):
            return data
    return {}


def _count_lrc_lines(text: str) -> int:
    return len([line for line in text.splitlines() if re.search(r"[ABC]\d*|【[ABC]", line)])


def _postprocess_data(texts: dict[str, str]) -> tuple[dict[str, Any], dict[str, Any]]:
    quality = _load_json_from_text(texts.get("quality", ""))
    if not isinstance(quality, dict):
        quality = {}
    meta = _load_json_from_text(texts.get("meta", ""))
    if not isinstance(meta, dict):
        meta = {}
    return quality, meta


def _evaluate_postprocess(material_dir: Path, texts: dict[str, str]) -> list[Finding]:
    findings: list[Finding] = []
    quality, meta = _postprocess_data(texts)
    target = str(material_dir)

    if not quality and not meta:
        return findings

    review_team = quality.get("review_team") if isinstance(quality.get("review_team"), dict) else {}
    if review_team.get("total") != 230:
        findings.append(
            Finding(
                "medium",
                "postprocess_review",
                "后处理质检清单没有明确体现 230 人评审团总人数。",
                target,
                "在 230 人评审质检清单里补上 total=230，并明确三组人数。",
                True,
            )
        )

    if not isinstance(quality.get("one_vote_veto"), list) or len(quality.get("one_vote_veto") or []) < 3:
        findings.append(
            Finding(
                "medium",
                "postprocess_review",
                "后处理质检清单缺少明确的一票否决规则。",
                target,
                "补足文学/运营/观众三组的一票否决标准。",
                True,
            )
        )

    if not isinstance(quality.get("visual_checklist"), list) or len(quality.get("visual_checklist") or []) < 4:
        findings.append(
            Finding(
                "medium",
                "postprocess_review",
                "后处理视觉检查项太少，难以覆盖封面、片尾和品牌区。",
                target,
                "补充 A1/A2/A01/A02/C、品牌区、缩略图可读性的检查项。",
                True,
            )
        )

    if not isinstance(quality.get("content_checklist"), list) or len(quality.get("content_checklist") or []) < 4:
        findings.append(
            Finding(
                "medium",
                "postprocess_review",
                "后处理内容检查项太少，无法兜住标题、C 预告和转发理由。",
                target,
                "补充 A1、B 段、C、发布包联动检查项。",
                True,
            )
        )

    covers = meta.get("covers") if isinstance(meta.get("covers"), dict) else {}
    endcards = meta.get("endcards") if isinstance(meta.get("endcards"), dict) else {}
    if not covers:
        findings.append(
            Finding(
                "medium",
                "postprocess_assets",
                "后处理元数据里没有封面产物列表。",
                target,
                "在封面片尾元数据中保留 A1/A2/A01/A02 的输出路径。",
                True,
            )
        )
    if not endcards:
        findings.append(
            Finding(
                "medium",
                "postprocess_assets",
                "后处理元数据里没有片尾产物列表。",
                target,
                "在封面片尾元数据中保留 C 片尾的输出路径。",
                True,
            )
        )

    for asset_group, assets in (("covers", covers), ("endcards", endcards)):
        for asset_id, asset_info in assets.items():
            if not isinstance(asset_info, dict):
                findings.append(
                    Finding(
                        "medium",
                        "postprocess_assets",
                        f"{asset_group} 里的 {asset_id} 元数据结构不完整。",
                        target,
                        "把输出路径和尺寸信息写成字典。",
                        True,
                    )
                )
                continue
            path_text = str(asset_info.get("path") or "")
            if not path_text:
                findings.append(
                    Finding(
                        "medium",
                        "postprocess_assets",
                        f"{asset_group} 里的 {asset_id} 没有输出路径。",
                        target,
                        "把该图片的 path 写入封面片尾元数据。",
                        True,
                    )
                )
                continue
            if not Path(path_text).exists():
                findings.append(
                    Finding(
                        "high",
                        "postprocess_assets",
                        f"{asset_group} 里的 {asset_id} 输出文件不存在。",
                        path_text,
                        "检查后处理是否真的生成了该图片。",
                        False,
                    )
                )

    config_path = str(meta.get("config_path") or "")
    if config_path and not Path(config_path).exists():
        findings.append(
            Finding(
                "medium",
                "postprocess_assets",
                "后处理配置文件路径存在，但文件本身不存在。",
                config_path,
                "确认封面片尾配置已经写盘。",
                False,
            )
        )

    quality_path = str(meta.get("quality_path") or "")
    if quality_path and not Path(quality_path).exists():
        findings.append(
            Finding(
                "medium",
                "postprocess_assets",
                "后处理质检清单路径存在，但文件本身不存在。",
                quality_path,
                "确认 230 人评审质检清单已经写盘。",
                False,
            )
        )

    if findings:
        return findings

    findings.append(
        Finding(
            "pass",
            "postprocess_overall",
            "后处理评审项已覆盖封面、片尾和内容联动。",
            target,
            "继续在真实产物上复测。",
        )
    )
    return findings


def evaluate_material(material_dir: Path, signals: list[dict[str, str]]) -> list[Finding]:
    texts = _material_text(material_dir)
    findings: list[Finding] = []
    intro = _intro_data(texts)
    lrc = texts.get("lrc", "")
    combined = "\n".join(texts.values())
    target = str(material_dir)

    if not texts:
        findings.append(
            Finding(
                "high",
                "missing_material",
                "没有找到可评测的台词、简介或封面元数据。",
                target,
                "先生成分集素材或指向正确输出目录。",
            )
        )
        return findings

    if lrc and _count_lrc_lines(lrc) < 12:
        findings.append(
            Finding(
                "medium",
                "retention",
                "台词行数过少，可能像摘要而不是完整短视频。",
                target,
                "检查分集是否过短，必要时补足 B 段正文覆盖。",
            )
        )

    first_lines = [line for line in lrc.splitlines() if line.strip()][:4]
    first_blob = " ".join(first_lines)
    if first_blob and re.search(r"本章|本文|这一节|主要讲|接下来我们", first_blob):
        findings.append(
            Finding(
                "high",
                "opening",
                "开头像课程目录或摘要，普通观众首屏不容易停留。",
                target,
                "重写 A1：先给人物困境、制度矛盾或具体问题，再自然亮书名。",
                True,
            )
        )
    if first_blob and len(re.findall(r"制度|机制|结构|逻辑|治理|背景|体系", first_blob)) >= 3:
        findings.append(
            Finding(
                "high",
                "opening",
                "前几句抽象名词过密，观众可能听不懂。",
                target,
                "前 8 秒改成“谁遇到什么麻烦、被什么规则卡住”。",
                True,
            )
        )

    if intro:
        publish_title = str(intro.get("publish_title") or "")
        if len(publish_title) > 28 or len(publish_title) < 8:
            findings.append(
                Finding(
                    "medium",
                    "publish_title",
                    "视频号标题长度不稳，可能影响停留。",
                    target,
                    "标题控制在 16-24 个中文字符，写成具体问题或冲突。",
                    True,
                )
            )
        if not re.search(r"[？?]|为什么|为何|怎么|谁|困|难|穷|卡|人情|矛盾|选择|规则|代价|后果", publish_title):
            findings.append(
                Finding(
                    "medium",
                    "publish_title",
                    "标题缺少问题、冲突或处境压力。",
                    target,
                    "标题补一个具体矛盾，不要只写章节名。",
                    True,
                )
            )
        if not str(intro.get("pinned_comment") or ""):
            findings.append(
                Finding(
                    "medium",
                    "comments",
                    "缺少置顶评论，浪费互动入口。",
                    target,
                    "补一个普通观众能马上回答的选择题或处境题。",
                    True,
                )
            )
        share_text = str(intro.get("moments_text") or "") + str(intro.get("group_text") or "")
        if share_text and not re.search(r"适合|转给|正在|遇到|被.*卡住|看懂|关心", share_text):
            findings.append(
                Finding(
                    "medium",
                    "share",
                    "朋友圈/微信群文案没有明确转发对象或转发理由。",
                    target,
                    "写清适合谁看、帮谁看懂什么问题。",
                    True,
                )
            )

    bad_words = ["底层逻辑", "认知升级", "命运齿轮", "时代洪流", "封神", "天花板", "狠狠共鸣", "值得深思"]
    hits = [word for word in bad_words if word in combined]
    if hits:
        findings.append(
            Finding(
                "medium",
                "language",
                f"发现空泛爆款词：{'、'.join(hits)}。",
                target,
                "替换为具体人物处境、规则压力或选择后果。",
                True,
            )
        )

    if not any(
        "转发" in signal.get("summary", "") or "评论" in signal.get("summary", "") or "想看" in signal.get("summary", "")
        for signal in signals
    ):
        findings.append(
            Finding(
                "low",
                "audience_signal",
                "本轮公开观众信号较弱，无法确认外部需求。",
                target,
                "保留问题单；下轮开启 --online 或补充真实评论样本。",
            )
        )

    findings.extend(_evaluate_postprocess(material_dir, texts))

    if not findings:
        findings.append(
            Finding(
                "pass",
                "overall",
                "本轮自动观众评测未发现硬伤。",
                target,
                "继续积累真实数据后复测。",
            )
        )
    return findings


def auto_patch_prompts(findings: list[Finding], *, apply: bool, patch_log: Path) -> list[dict[str, str]]:
    if not apply:
        return []
    fixable = [finding for finding in findings if finding.auto_fixable and finding.severity in {"high", "medium"}]
    if not fixable:
        return []

    patch_note = "\n\n【自动观众测试机器人追加要求】\n"
    areas = sorted({finding.area for finding in fixable})
    if "opening" in areas:
        patch_note += "- 若评测发现开头像课程目录、摘要或抽象名词过密，下一轮必须重写 A1：先讲谁被什么规则/处境卡住，再亮书名和章节。\n"
    if "publish_title" in areas or "share" in areas or "comments" in areas:
        patch_note += "- 发布包必须补足传播闭环：标题抓具体矛盾，朋友圈/微信群写清适合谁看，置顶评论问一个普通人能回答的问题。\n"
    if "language" in areas:
        patch_note += "- 自动删除空泛爆款词，改成具体人物、制度后果、选择代价或原书证据。\n"

    changed: list[dict[str, str]] = []
    targets = [
        PROMPTS_DIR / "12_DeepSeek终稿润色提示词.md",
        PROMPTS_DIR / "11_视频简介提示词.md",
    ]
    for path in targets:
        text = _read_text(path, max_chars=500_000)
        if not text or patch_note.strip() in text:
            continue
        path.write_text(text.rstrip() + patch_note, encoding="utf-8")
        item = {"path": str(path), "note": patch_note.strip(), "time": _now()}
        _append_jsonl(patch_log, item)
        changed.append(item)
    return changed


def run_bot(args: argparse.Namespace) -> int:
    root = Path(args.material_root or PROJECT_ROOT / "outputs")
    report_paths = resolve_report_paths(args.book_pdf)
    report_dir = report_paths["report_dir"]
    report_file = report_paths["report_file"]
    issue_file = report_paths["issue_file"]
    patch_log = report_paths["patch_log"]
    assert isinstance(report_dir, Path)
    assert isinstance(report_file, Path)
    assert isinstance(issue_file, Path)
    assert isinstance(patch_log, Path)

    report_dir.mkdir(parents=True, exist_ok=True)
    signals = collect_public_signals(online=bool(args.online), limit=int(args.query_limit))
    material_dirs = discover_material_dirs(root)
    if args.max_materials:
        material_dirs = material_dirs[: int(args.max_materials)]

    all_findings: list[Finding] = []
    for material_dir in material_dirs:
        all_findings.extend(evaluate_material(material_dir, signals))
    if not material_dirs:
        all_findings.append(
            Finding(
                "high",
                "missing_material",
                f"未在 {root} 找到可评测素材。",
                str(root),
                "生成文史素材后再运行，或用 --material-root 指定输出目录。",
            )
        )

    changed = auto_patch_prompts(all_findings, apply=bool(args.apply), patch_log=patch_log)
    report = {
        "time": _now(),
        "policy": "public-signal-only; no-contact; no-spam; no-private-message",
        "book_pdf": str(report_paths["book_pdf"]) if report_paths["book_pdf"] else "",
        "report_dir": str(report_dir),
        "material_root": str(root),
        "online": bool(args.online),
        "signals": signals,
        "materials": [str(path) for path in material_dirs],
        "findings": [finding.as_dict() for finding in all_findings],
        "auto_patches": changed,
        "unfixed": [
            finding.as_dict()
            for finding in all_findings
            if finding.severity in {"high", "medium"} and not finding.auto_fixable
        ],
    }
    _write_json(report_file, report)
    for finding in all_findings:
        if finding.severity in {"high", "medium"} and not finding.auto_fixable:
            _append_jsonl(issue_file, {"time": _now(), **finding.as_dict()})
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if any(finding.severity == "high" for finding in all_findings) else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="文史小秘自动观众评测机器人（公开信号 + 本地素材审片）")
    parser.add_argument("--material-root", default="", help="素材输出目录；默认 modes/culture/outputs")
    parser.add_argument("--book-pdf", default="", help="源书 PDF 路径；测试结果会写到源书同目录的小猪理观众测试文件夹")
    parser.add_argument("--online", action="store_true", help="读取公开搜索结果作为观众需求信号；不会联系真人")
    parser.add_argument("--apply", action="store_true", help="把可安全修复的问题追加进提示词")
    parser.add_argument("--query-limit", type=int, default=5)
    parser.add_argument("--max-materials", type=int, default=30)
    return run_bot(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
