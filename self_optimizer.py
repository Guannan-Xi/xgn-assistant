from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "modes" / "culture" / "outputs" / "self_optimizer"
STATE_FILE = OUT_DIR / "self_optimizer_state.json"
LOG_FILE = OUT_DIR / "self_optimizer_log.jsonl"
QUEUE_FILE = OUT_DIR / "self_optimizer_queue.jsonl"
EVENTS_FILE = OUT_DIR / "self_optimizer_events.jsonl"
ISSUES_FILE = OUT_DIR / "self_optimizer_issues.jsonl"
MEMORY_FILE = OUT_DIR / "self_optimizer_memory.json"
PATCH_PLAN_FILE = OUT_DIR / "self_optimizer_patch_plan.json"
ROLEPLAY_DETAIL_FILE = OUT_DIR / "self_optimizer_roleplay_detail.jsonl"
BOOK_CANDIDATES_FILE = OUT_DIR / "self_optimizer_book_candidates.json"
BOOK_CANDIDATES_FALLBACK_FILE = ROOT / ".workbench_runtime" / "self_optimizer" / "self_optimizer_book_candidates.json"
BOOK_CANDIDATES_TEMP_FILE = Path(os.environ.get("TEMP") or os.environ.get("TMP") or ".") / "xgn-assistant" / "self_optimizer" / "self_optimizer_book_candidates.json"
EMAIL_TOOL = Path(os.environ.get("XGN_SELF_OPTIMIZER_EMAIL_TOOL") or r"C:\Users\XGN\.codex\skills\quanlan-email-delivery\scripts\email_tool.py")
EMAIL_PROJECT = Path(os.environ.get("XGN_SELF_OPTIMIZER_EMAIL_PROJECT") or (ROOT / "modes" / "culture"))
EMAIL_TO = os.environ.get("XGN_SELF_OPTIMIZER_EMAIL_TO") or "399467826@qq.com"
EMAIL_OUT_DIR = OUT_DIR / "email_reports"
BUG_RE = re.compile(r"error|failed|failure|exception|traceback|timeout|fatal|crash|bug|报错|错误|失败|卡住|卡主", re.I)
INTERVAL_SECONDS = int(os.environ.get("XGN_SELF_OPTIMIZER_INTERVAL_SECONDS", "300"))
IDLE_UPDATE_MIN_SECONDS = int(os.environ.get("XGN_SELF_OPTIMIZER_IDLE_UPDATE_MIN_SECONDS", "3600"))
ROLEPLAY_UPDATE_MIN_SECONDS = int(os.environ.get("XGN_SELF_OPTIMIZER_ROLEPLAY_UPDATE_MIN_SECONDS", "3600"))
BOOK_CANDIDATE_UPDATE_MIN_SECONDS = int(os.environ.get("XGN_SELF_OPTIMIZER_BOOK_CANDIDATE_UPDATE_MIN_SECONDS", "86400"))
BOOK_PDF_SEARCH_LIMIT = int(os.environ.get("XGN_SELF_OPTIMIZER_BOOK_PDF_SEARCH_LIMIT", "6000"))
BOOK_PDF_DOWNLOAD_DIR = Path(os.environ.get("XGN_SELF_OPTIMIZER_BOOK_PDF_DOWNLOAD_DIR") or (OUT_DIR / "book_pdfs"))
BOOK_PDF_DOWNLOAD_FALLBACK_DIR = ROOT / ".workbench_runtime" / "self_optimizer" / "book_pdfs"
BOOK_PDF_DOWNLOAD_TEMP_DIR = Path(os.environ.get("TEMP") or os.environ.get("TMP") or ".") / "xgn-assistant" / "self_optimizer" / "book_pdfs"
BOOK_PDF_DOWNLOAD_TIMEOUT_SECONDS = int(os.environ.get("XGN_SELF_OPTIMIZER_BOOK_PDF_DOWNLOAD_TIMEOUT_SECONDS", "45"))
BOOK_PDF_SEARCH_ROOTS = [
    Path(part).expanduser()
    for part in (os.environ.get("XGN_SELF_OPTIMIZER_BOOK_PDF_ROOTS") or rf"D:\知识;{ROOT / 'chapter_pdf_direct_output'};{ROOT / 'modes' / 'culture' / 'outputs'}").split(";")
    if part.strip()
]


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def append_jsonl(path: Path, data: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as file:
            file.write(json.dumps({"at": now_iso(), **data}, ensure_ascii=False) + "\n")
    except PermissionError:
        return


def read_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return fallback


def write_json(path: Path, data: Any) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except PermissionError:
        return


def stable_id(parts: list[str]) -> str:
    payload = "\n".join(part for part in parts if part)
    return hashlib.sha1(payload.encode("utf-8", errors="ignore")).hexdigest()[:16]


def classify_issue(text: str, source: str = "") -> dict[str, str]:
    value = f"{source}\n{text or ''}"
    if re.search(r"封面|标题|A1|开头|前3秒|口播|台词", value, re.I):
        area = "content-hook"
    elif re.search(r"发布|release|channel|更新包|正式版|视频号", value, re.I):
        area = "release"
    elif re.search(r"观众|评论|转发|完播|不想看|看不懂", value, re.I):
        area = "audience-fit"
    elif BUG_RE.search(value):
        area = "runtime"
    else:
        area = "workflow"
    if re.search(r"正式版|发布|崩|fatal|crash|报错|错误|failed|SyntaxError|timeout", value, re.I):
        severity = "high"
    elif re.search(r"看不懂|不好|不准|建议|优化|缺少", value, re.I):
        severity = "medium"
    else:
        severity = "low"
    return {"area": area, "severity": severity}


def record_evolution_event(state: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    classified = classify_issue(str(event.get("text") or event.get("summary") or ""), str(event.get("source") or event.get("type") or ""))
    enriched = {
        "project": "自媒体小猪理",
        "stage": event.get("stage", "observe"),
        "area": event.get("area", classified["area"]),
        "severity": event.get("severity", classified["severity"]),
        **event,
    }
    append_jsonl(EVENTS_FILE, enriched)
    state["evolution_event_count"] = int(state.get("evolution_event_count", 0)) + 1
    return enriched


def record_issue(state: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    text = str(item.get("text") or item.get("summary") or "")
    classified = classify_issue(text, str(item.get("source") or item.get("type") or ""))
    issue = {
        "id": item.get("id") or stable_id(["xgn-automedia", str(item.get("source", "")), classified["area"], text[:500]]),
        "project": "自媒体小猪理",
        "status": "pending",
        "source": item.get("source", "self-optimizer"),
        "type": item.get("type", "feedback"),
        "area": item.get("area", classified["area"]),
        "severity": item.get("severity", classified["severity"]),
        "summary": str(item.get("summary") or text)[:500],
        "evidence": item.get("evidence", text),
        "next_action": item.get("next_action", "convert-to-roleplay-or-safe-patch"),
    }
    issue_ids = state.setdefault("issue_ids", [])
    if issue["id"] not in issue_ids:
        append_jsonl(ISSUES_FILE, issue)
        issue_ids.append(issue["id"])
        state["issue_ids"] = issue_ids[-1000:]
    return issue


def update_learning_memory(state: dict[str, Any], *, issues: list[dict[str, Any]], release: dict[str, Any]) -> dict[str, Any]:
    memory = read_json(MEMORY_FILE, {
        "project": "自媒体小猪理",
        "principles": [],
        "recurring_issues": {},
        "release_lessons": [],
    })
    for issue in issues:
        area = str(issue.get("area", "unknown"))
        memory["recurring_issues"][area] = int(memory["recurring_issues"].get(area, 0)) + 1
    memory["principles"] = [
        "外界互动优先看普通观众是否听懂、愿意停留、愿意转发。",
        "封面、标题、A1、C 和发布文案必须在同一传播主线。",
        "正式版更新只通过 channel_manager 打包，自动 apply 需要明确允许。",
    ]
    memory["release_lessons"].append({"at": now_iso(), **release})
    memory["release_lessons"] = memory["release_lessons"][-50:]
    write_json(MEMORY_FILE, memory)
    return memory


def write_patch_plan(state: dict[str, Any], issues: list[dict[str, Any]], roles: list[dict[str, str]]) -> dict[str, Any]:
    plan = {
        "project": "自媒体小猪理",
        "generated_at": now_iso(),
        "automation_level": "L2-L3 guarded",
        "stages": ["observe", "classify_dedupe", "roleplay_review", "audience_research", "patch_plan", "test", "idle_release", "learn"],
        "pending_issues": issues[-30:],
        "roleplay_reviews": roles,
        "external_research_sources": [
            "公开视频号/读书号观众评论方向",
            "用户反馈队列",
            "本地生成素材与发布日志",
        ],
        "safe_actions": [
            "record audience and runtime issues",
            "run audience role-play when bot is available",
            "package release update through channel_manager.py",
            "avoid automatic apply unless --apply is set",
        ],
        "requires_human_confirmation": ["brand tone rewrite", "large prompt rewrite", "release apply", "destructive cleanup"],
    }
    write_json(PATCH_PLAN_FILE, plan)
    append_jsonl(EVENTS_FILE, {"project": "自媒体小猪理", "stage": "patch_plan", "event": "patch-plan-written", "issues": len(issues)})
    return plan


def write_roleplay_details(state: dict[str, Any], roles: list[dict[str, str]], issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    details: list[dict[str, Any]] = []
    for role in roles:
        role_name = role.get("role", "")
        session_id = f"roleplay-{now_iso().replace(':', '-')}--{uuid.uuid4().hex[:8]}"
        matched: list[dict[str, Any]] = []
        for issue in issues:
            text = f"{issue.get('area', '')} {issue.get('summary', '')}"
            if role_name == "没读过原书的普通视频号观众" and re.search(r"content-hook|audience-fit|开头|看不懂|标题", text):
                matched.append(issue)
            elif role_name == "短视频运营审片人" and re.search(r"content-hook|release|标题|封面|发布", text):
                matched.append(issue)
            elif role_name == "文史爱好者" and re.search(r"workflow|audience-fit|文史|原书|不准", text):
                matched.append(issue)
            elif role_name == "发布版维护者" and re.search(r"release|runtime|发布|报错|失败", text):
                matched.append(issue)
        detail = {
            "project": "自媒体小猪理",
            "round_at": now_iso(),
            "session_id": session_id,
            "virtual_user": role_name,
            "test_focus": role.get("task", ""),
            "simulated_questions": roleplay_questions(role_name),
            "evidence_sources": [str(LOG_FILE), str(ISSUES_FILE), str(PATCH_PLAN_FILE)],
            "observed_issues": [
                {
                    "id": item.get("id", ""),
                    "area": item.get("area", "unknown"),
                    "severity": item.get("severity", "unknown"),
                    "summary": item.get("summary", ""),
                }
                for item in matched
            ],
            "conclusion": f"发现 {len(matched)} 个相关问题，需要转成内容/发布回归检查。" if matched else "本轮没有发现该角色视角下的新高优先级问题。",
            "recommendation": "优先修复开头、标题、封面、发布链路中影响真实观众理解和点击的问题。" if matched else "继续积累真实观众反馈和生成素材表现。",
            "needs_human_confirmation": any(item.get("severity") == "high" and item.get("area") in {"content-hook", "release"} for item in matched),
        }
        append_roleplay_transcript(session_id, role, detail, matched)
        append_jsonl(ROLEPLAY_DETAIL_FILE, detail)
        details.append(detail)
    state["last_roleplay_detail_file"] = str(ROLEPLAY_DETAIL_FILE)
    state["last_roleplay_details"] = details
    append_jsonl(EVENTS_FILE, {"project": "自媒体小猪理", "stage": "roleplay_review", "event": "roleplay-details-written", "roles": len(details)})
    return details


def append_roleplay_transcript(session_id: str, role: dict[str, str], detail: dict[str, Any], matched: list[dict[str, Any]]) -> None:
    role_name = role.get("role", "") or str(detail.get("virtual_user") or "")
    test_focus = role.get("task", "") or str(detail.get("test_focus") or "")
    questions = detail.get("simulated_questions")
    if not isinstance(questions, list) or not questions:
        questions = roleplay_questions(role_name)
    observed_issue = "; ".join(str(item.get("summary", "")) for item in matched[:3] if item.get("summary")) or "本轮未发现新的高优先级问题。"
    recommendation = str(detail.get("recommendation") or "继续积累真实用户反馈，并把发现转成可验证的修复项。")
    needs_human_confirmation = bool(detail.get("needs_human_confirmation"))
    coach_message = roleplay_finding_line(detail)
    for round_index, question in enumerate(questions, start=1):
        base = {
            "project": "自媒体小猪理",
            "session_id": session_id,
            "scenario": test_focus,
            "test_focus": test_focus,
            "virtual_user": role_name,
            "coach_customer_name": role_name,
            "round": round_index,
            "observed_issue": observed_issue,
            "recommendation": recommendation,
            "needs_human_confirmation": needs_human_confirmation,
            "source_module": "self_optimizer.write_roleplay_details",
            "record_type": "roleplay_transcript",
        }
        append_jsonl(ROLEPLAY_DETAIL_FILE, {
            **base,
            "timestamp": now_iso(),
            "speaker": role_name,
            "role": "virtual_user",
            "message": str(question),
        })
        append_jsonl(ROLEPLAY_DETAIL_FILE, {
            **base,
            "timestamp": now_iso(),
            "speaker": "self_optimizer",
            "role": "coach",
            "message": coach_message,
        })


def user_problem_line(issue: dict[str, Any]) -> str:
    text = re.sub(r"\s+", " ", str(issue.get("summary") or issue.get("source") or "")).strip()[:500]
    area = issue.get("area")
    if area == "content-hook" or re.search(r"封面|标题|A1|开头|前3秒|口播", text):
        return "内容开头和包装会继续优化：重点检查标题、封面、开头是否能让普通观众想点开。"
    if area == "audience-fit" or re.search(r"观众|评论|转发|看不懂", text):
        return "观众理解会继续优化：把普通观众看不懂、不想转发的问题记录为后续改进。"
    if area == "release" or re.search(r"发布|release|更新包|正式版", text):
        return "发布流程更稳：检查更新包和正式版状态，避免把有问题的版本推出去。"
    if area == "runtime" or BUG_RE.search(text):
        return "运行稳定性已被检查，报错会进入后续修复列表。"
    return text[:140] if text and not text.startswith("{") else "发现一条内部运行信号，已记录到问题单等待后续处理。"


def summarize_user_outcomes(issues: list[dict[str, Any]], idle: dict[str, Any]) -> list[str]:
    outcomes: list[str] = []
    package = idle.get("release_package_update") or {}
    audience = idle.get("audience_test_bot") or {}
    if package.get("ok"):
        outcomes.append("发布更新包已生成，后续正式版可以使用这轮优化结果。")
    if not audience.get("ok"):
        outcomes.append("观众测试工具当前不可用，已记录为待修问题，不会假装测试通过。")
    if any(issue.get("area") == "content-hook" for issue in issues):
        outcomes.append("标题、封面、开头会被优先关注，目标是让普通观众更愿意点开。")
    if not outcomes:
        outcomes.append("本轮没有发现新的用户可感知问题，主要是例行巡检和发布安全检查。")
    return outcomes


def unique_user_problem_lines(issues: list[dict[str, Any]]) -> list[str]:
    return list(dict.fromkeys(user_problem_line(issue) for issue in issues if user_problem_line(issue)))


def build_user_facing_report(issues: list[dict[str, Any]], idle: dict[str, Any]) -> dict[str, list[str]]:
    text = "\n".join(f"{issue.get('area', '')} {issue.get('summary', '')}" for issue in issues)
    package = idle.get("release_package_update") or {}
    audience = idle.get("audience_test_bot") or {}
    handled: list[str] = []
    pending: list[str] = []
    if package.get("ok"):
        handled.append("发布更新包：已生成本轮优化包，后续正式版可以使用这轮结果。")
    if re.search(r"content-hook|封面|标题|A1|开头|前3秒|口播", text):
        handled.append("内容吸引力：已把标题、封面、开头能不能吸引普通观众作为优先优化点。")
    if re.search(r"audience-fit|观众|评论|转发|看不懂", text):
        handled.append("观众理解：已把普通观众看不懂、不想转发的问题记录为后续优化。")
    if not audience.get("ok"):
        pending.append("观众测试工具：当前不可用，已记录为待修问题；系统不会假装测试通过。")
    if re.search(r"release|发布|更新包|正式版", text) and not package.get("ok"):
        pending.append("发布流程：仍需继续检查更新包和正式版状态，避免把有问题的版本推出去。")
    if re.search(r"runtime|error|failed|timeout|报错|错误|失败", text, re.I):
        pending.append("运行稳定性：报错已进入后续修复列表。")
    if not issues and not handled:
        handled.append("本轮没有发现新的用户可感知问题，后台继续巡检和发布安全检查。")
    if not handled:
        handled.extend(unique_user_problem_lines(issues))
    return {"handled": list(dict.fromkeys(handled)), "pending": list(dict.fromkeys(pending))}


def roleplay_questions(role: str) -> list[str]:
    questions = {
        "没读过原书的普通视频号观众": [
            "这个视频开头 3 秒能不能让我知道为什么要继续看？",
            "标题、封面和口播是不是普通人也看得懂、愿意点开？",
        ],
        "短视频运营审片人": [
            "这条内容的标题、封面、节奏和转发点够不够强？",
            "发布文案有没有违规、夸大、错别字或让平台误判的风险？",
        ],
        "文史爱好者": [
            "这段解读有没有偏离原书或历史语境？哪些地方需要补证据？",
            "如果我熟悉这本书，会不会觉得内容太浅或不准确？",
        ],
        "发布版维护者": [
            "更新包生成后，正式版能不能安全使用这轮优化？",
            "观众测试工具失败时，系统有没有停止假通过并记录待修？",
        ],
    }
    return questions.get(role, ["这个角色真实会追问什么？", "当前内容有没有清楚、可信、可发布？"])


def roleplay_finding_line(item: dict[str, Any]) -> str:
    observed = item.get("observed_issues") or []
    if not isinstance(observed, list):
        observed = []
    findings = list(dict.fromkeys(user_problem_line(issue) for issue in observed if user_problem_line(issue)))
    return " / ".join(findings) if findings else "暂无新的高优先级问题。"


def roleplay_email_line(item: dict[str, Any], index: int) -> str:
    user = item.get("virtual_user") or "虚拟用户"
    focus = item.get("test_focus") or "真实使用场景"
    questions = item.get("simulated_questions") if isinstance(item.get("simulated_questions"), list) else roleplay_questions(user)
    observed = item.get("observed_issues") or []
    count = len(observed) if isinstance(observed, list) else 0
    needs_confirm = "需要人工确认内容/发布类变更。" if item.get("needs_human_confirmation") else "暂不需要人工确认。"
    if count:
        result = f"发现 {count} 类需要继续优化的观众或发布风险，已进入问题单和补丁计划。"
    else:
        result = "本轮没有发现新的高优先级风险。"
    return "\n".join([
        f"- {index + 1}. {user}",
        f"  - 模拟提问：{' / '.join(str(question) for question in questions)}",
        f"  - 检查重点：{focus}",
        f"  - 本轮结果：{result}",
        f"  - 具体发现：{roleplay_finding_line(item)}",
        f"  - 下一步：{needs_confirm}",
    ])


def write_email_report(kind: str, payload: dict[str, Any]) -> Path:
    EMAIL_OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = now_iso().replace(":", "-")
    report_file = EMAIL_OUT_DIR / f"{kind}-{stamp}.txt"
    issues = payload.get("issues") or []
    roleplay_details = payload.get("roleplay_details") or []
    idle = payload.get("idle_optimization") or {}
    audience = idle.get("audience_test_bot") or {}
    package = idle.get("release_package_update") or {}
    outcomes = summarize_user_outcomes(issues, idle)
    user_facing = build_user_facing_report(issues, idle)
    issue_categories = len(unique_user_problem_lines(issues))
    lines = [
        "自媒体小猪理自优化日志",
        "",
        f"时间：{now_iso()}",
        f"本轮类型：{kind}",
        f"邮件收件人：{EMAIL_TO}",
        "",
        "一、本轮升级了什么",
        *[f"- {item}" for item in outcomes],
        "",
        "二、已经解决或加固了什么",
        *[f"- {item}" for item in user_facing["handled"]],
        "",
        "三、还没完全解决但已经保护了什么",
        *([f"- {item}" for item in user_facing["pending"]] if user_facing["pending"] else ["- 暂无需要你立刻处理的遗留风险。"]),
        "",
        "四、本轮结果",
        f"- 观众测试：{'成功' if audience.get('ok') else '失败或跳过'}",
        f"- 发布更新包：{'成功' if package.get('ok') else '失败或未运行'}",
        f"- 本轮主要处理的用户风险类型：{issue_categories} 类",
        "",
        "五、具体处理清单",
    ]
    if issues:
        lines.extend(f"- {index + 1}. {item}" for index, item in enumerate(unique_user_problem_lines(issues)))
    else:
        lines.append("- 没有发现需要立刻处理的新问题。")
    lines.extend([
        "",
        "六、虚拟用户测试详细记录",
    ])
    if roleplay_details:
        lines.extend(roleplay_email_line(item, index) for index, item in enumerate(roleplay_details))
    else:
        lines.append("- 本轮未生成虚拟用户明细。")
    lines.extend([
        f"- 详细逐轮对话 JSONL：{ROLEPLAY_DETAIL_FILE}",
        "",
        "七、下一步",
        "- 下一轮会继续把这些用户问题转成提示词、内容包装和发布检查；观众测试工具仍需优先修复。",
        "",
        "八、追溯文件",
        f"- 运行日志：{LOG_FILE}",
        f"- 事件流：{EVENTS_FILE}",
        f"- 问题单：{ISSUES_FILE}",
        f"- 补丁计划：{PATCH_PLAN_FILE}",
        f"- 学习记忆：{MEMORY_FILE}",
        f"- 虚拟用户详细逐轮对话 JSONL：{ROLEPLAY_DETAIL_FILE}",
    ])
    try:
        report_file.write_text("\n".join(str(line) for line in lines) + "\n", encoding="utf-8")
        return report_file
    except PermissionError:
        fallback = Path(os.environ.get("TEMP") or os.environ.get("TMP") or ".") / report_file.name
        fallback.write_text("\n".join(str(line) for line in lines) + "\n", encoding="utf-8")
        return fallback


def email_optimization_log(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    report_file = write_email_report(kind, payload)
    result: dict[str, Any] = {"ok": False, "error": "not-started"}
    for attempt in range(1, 3):
        result = run([
            sys.executable,
            str(EMAIL_TOOL),
            "send",
            "--project",
            str(EMAIL_PROJECT),
            "--path",
            str(report_file),
            "--to",
            EMAIL_TO,
            "--subject",
            f"自媒体小猪理自优化日志：{kind}",
            "--body",
            report_file.read_text(encoding="utf-8"),
        ], timeout=90)
        result["attempt"] = attempt
        if result.get("ok"):
            break
        if attempt < 2:
            time.sleep(2)
    result["report_file"] = str(report_file)
    append_jsonl(LOG_FILE, {
        "event": "optimization-log-email-sent" if result.get("ok") else "optimization-log-email-failed",
        "kind": kind,
        "to": EMAIL_TO,
        "result": result,
    })
    append_jsonl(EVENTS_FILE, {
        "project": "自媒体小猪理",
        "stage": "notify",
        "event": "email-sent" if result.get("ok") else "email-failed",
        "kind": kind,
        "to": EMAIL_TO,
        "result": result,
    })
    return result


def extract_release_event_from_idle(idle_result: dict[str, Any]) -> dict[str, Any]:
    package = idle_result.get("release_package_update") or {}
    stdout = str(package.get("stdout") or "")
    if package.get("ok") and "已生成发布版待升级包" in stdout:
        return {"sent_worthy": True, "reason": "release-package-created", "details": package}
    if package and not package.get("ok"):
        return {"sent_worthy": True, "reason": "release-package-failed", "details": package}
    return {"sent_worthy": False, "reason": "no-release-package-change", "details": package}


def maybe_email_optimization_log(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    release = payload.get("release_event") or {}
    if not release.get("sent_worthy"):
        reason = release.get("reason") or "no-release-or-package-change"
        append_jsonl(LOG_FILE, {"event": "optimization-log-email-skipped", "kind": kind, "reason": reason})
        append_jsonl(EVENTS_FILE, {
            "project": "自媒体小猪理",
            "stage": "notify",
            "event": "email-skipped",
            "kind": kind,
            "reason": reason,
        })
        return {"ok": True, "skipped": True, "reason": reason}
    github = sync_release_to_github(release)
    append_jsonl(LOG_FILE, {"event": "github-sync-complete" if github.get("ok") else "github-sync-failed", "kind": kind, "release_reason": release.get("reason"), "github": github})
    append_jsonl(EVENTS_FILE, {
        "project": "自媒体小猪理",
        "stage": "github",
        "event": "github-sync-complete" if github.get("ok") else "github-sync-failed",
        "kind": kind,
        "release_reason": release.get("reason"),
        "github": github,
    })
    return email_optimization_log(kind, payload)


def sync_release_to_github(release_event: dict[str, Any]) -> dict[str, Any]:
    if not release_event.get("sent_worthy"):
        return {"ok": True, "skipped": True, "reason": "no-release-event"}
    message = f"chore: sync release optimization {release_event.get('reason') or 'release'}"
    status = run(["git", "status", "--porcelain"], timeout=30)
    if not status.get("ok"):
        return {"ok": False, "stage": "status", "error": status.get("stderr") or status.get("stdout")}
    if not str(status.get("stdout") or "").strip():
        return {"ok": True, "skipped": True, "reason": "no-git-changes"}
    add_tracked = run(["git", "add", "-u"], timeout=60)
    if not add_tracked.get("ok"):
        return {"ok": False, "stage": "add-tracked", "error": add_tracked.get("stderr") or add_tracked.get("stdout")}
    run(["git", "add", "self_optimizer.py", "run_self_optimizer.bat", "tools/channel_manager.py"], timeout=60)
    staged = run(["git", "diff", "--cached", "--name-only"], timeout=30)
    if not staged.get("ok"):
        return {"ok": False, "stage": "staged", "error": staged.get("stderr") or staged.get("stdout")}
    safe_files = []
    for file in str(staged.get("stdout") or "").splitlines():
        normalized = file.replace("\\", "/")
        if re.search(r"(^|/)(node_modules|_temp|\.release_updates|modes/culture/outputs)/", normalized):
            continue
        if re.search(r"\.(log|jsonl|lock)$", normalized, re.I):
            continue
        if re.search(r"smtp_password|password|secret|token", normalized, re.I):
            continue
        safe_files.append(file)
    if not safe_files:
        run(["git", "reset"], timeout=30)
        return {"ok": True, "skipped": True, "reason": "no-safe-staged-files"}
    run(["git", "reset"], timeout=30)
    add_safe = run(["git", "add", *safe_files], timeout=60)
    if not add_safe.get("ok"):
        return {"ok": False, "stage": "add-safe", "error": add_safe.get("stderr") or add_safe.get("stdout")}
    commit = run(["git", "commit", "-m", message], timeout=120)
    if not commit.get("ok") and "nothing to commit" not in str(commit.get("stderr") or commit.get("stdout")).lower():
        return {"ok": False, "stage": "commit", "error": commit.get("stderr") or commit.get("stdout")}
    branch = (run(["git", "branch", "--show-current"], timeout=30).get("stdout") or "main").strip() or "main"
    push = run(["git", "push", "origin", branch], timeout=180)
    if not push.get("ok"):
        return {"ok": False, "stage": "push", "error": push.get("stderr") or push.get("stdout")}
    return {"ok": True, "branch": branch, "files": safe_files}


def run(args: list[str], timeout: int = 180) -> dict[str, Any]:
    proc = subprocess.run(
        args,
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=timeout,
    )
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout": proc.stdout[-1200:],
        "stderr": proc.stderr[-1200:],
    }


def source_has_pending_feedback() -> bool:
    if not QUEUE_FILE.exists():
        return False
    try:
        lines = QUEUE_FILE.read_text(encoding="utf-8-sig").splitlines()[-200:]
    except OSError:
        return False
    for line in lines:
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if item.get("status") != "pending":
            continue
        if item.get("type") in {"user-feedback", "add-feedback", "add-bug"}:
            return True
    return False


def log_files() -> list[Path]:
    skip = {".git", ".workbench_runtime", "__pycache__", ".release_updates"}
    files: list[Path] = []
    for path in ROOT.rglob("*.log"):
        if any(part in skip for part in path.parts):
            continue
        if "site-packages" in path.parts:
            continue
        files.append(path)
    return files[:200]


def scan_runtime_bugs(state: dict[str, Any]) -> list[dict[str, Any]]:
    offsets = state.setdefault("log_offsets", {})
    recorded: list[dict[str, Any]] = []
    for file in log_files():
        try:
            stat = file.stat()
        except FileNotFoundError:
            continue
        key = str(file.relative_to(ROOT))
        old_offset = int(offsets.get(key, 0) or 0)
        start = 0 if stat.st_size < old_offset else old_offset
        if stat.st_size == start:
            continue
        with file.open("rb") as handle:
            handle.seek(max(start, stat.st_size - 512_000))
            text = handle.read().decode("utf-8", errors="replace")
        for line in [line for line in text.splitlines() if BUG_RE.search(line)][-20:]:
            issue = record_issue(state, {
                "type": "bug",
                "source": key,
                "summary": line[:500],
                "evidence": line,
                "next_action": "reproduce-and-add-content-or-release-regression",
            })
            item = {"type": "runtime-bug", "source": key, "summary": line[:500], "status": "pending", "issue_id": issue["id"]}
            append_jsonl(QUEUE_FILE, item)
            record_evolution_event(state, {"stage": "observe", "event": "runtime-bug-detected", "source": key, "text": line, "issue_id": issue["id"]})
            recorded.append(item)
        offsets[key] = stat.st_size
    append_jsonl(LOG_FILE, {"event": "runtime-bug-scan", "recorded": len(recorded)})
    return recorded


def add_feedback(text: str, source: str) -> dict[str, Any]:
    state = read_json(STATE_FILE, {})
    issue = record_issue(state, {
        "type": "bug" if source == "add-bug" else "feedback",
        "source": source,
        "summary": text,
        "evidence": text,
        "next_action": "classify-and-convert-to-audience-or-release-test",
    })
    item = {"type": source, "text": text.strip(), "status": "pending", "issue_id": issue["id"]}
    append_jsonl(QUEUE_FILE, item)
    record_evolution_event(state, {"stage": "observe", "event": "user-feedback-recorded", "source": source, "text": text, "issue_id": issue["id"]})
    write_json(STATE_FILE, state)
    append_jsonl(LOG_FILE, {"event": "feedback-recorded", "source": source, "length": len(item["text"])})
    return item


def role_play_plan(state: dict[str, Any]) -> list[dict[str, str]]:
    roles = [
        "没读过原书的普通视频号观众",
        "短视频运营审片人",
        "文史爱好者",
        "发布版维护者",
    ]
    plan = [
        {
            "role": role,
            "task": "结合内外部资料和现有素材，检查开头、封面、标题、口播、发布文案和发布稳定性。",
        }
        for role in roles
    ]
    state["role_play_reviews"] = plan
    append_jsonl(LOG_FILE, {"event": "role-play-plan-refreshed", "roles": len(plan)})
    return plan


def _seed_book_candidates() -> list[dict[str, Any]]:
    return [
        {
            "title": "枪炮、病菌与钢铁",
            "author": "贾雷德·戴蒙德",
            "category": "历史",
            "reason": "全球史入门读者基数大，适合解释地理、技术扩散与文明差异。",
            "future_angle": "用一个普通人的生活半径，讲清农业、疾病和国家形成如何改变命运。",
            "source_status": "copyrighted",
            "search_queries": ["枪炮、病菌与钢铁 PDF 本地", "Guns Germs and Steel legal ebook"],
        },
        {
            "title": "人类简史",
            "author": "尤瓦尔·赫拉利",
            "category": "历史/哲学",
            "reason": "大众阅读量高，观点鲜明，容易拆成认知革命、农业革命、想象共同体等短视频主题。",
            "future_angle": "把宏大叙事压成可争论的问题：人类是被故事组织起来的吗？",
            "source_status": "copyrighted",
            "search_queries": ["人类简史 PDF 本地", "Sapiens legal ebook"],
        },
        {
            "title": "国富论",
            "author": "亚当·斯密",
            "category": "财经/经典",
            "reason": "经济学源头经典，适合从分工、市场协调和道德情感关系切入。",
            "future_angle": "从一支铅笔或一顿饭开始讲分工，而不是先讲抽象市场。",
            "source_status": "public_domain_text",
            "legal_source_pages": ["https://www.gutenberg.org/ebooks/3300"],
            "search_queries": ["国富论 PDF 本地", "Wealth of Nations public domain PDF"],
        },
        {
            "title": "资本论",
            "author": "卡尔·马克思",
            "category": "财经/哲学",
            "reason": "争议和讨论度长期很高，适合做概念拆解与时代语境还原。",
            "future_angle": "用商品、劳动时间和剩余价值三层递进，避免口号化解读。",
            "source_status": "public_domain_pdf",
            "legal_source_pages": ["https://www.marxists.org/archive/marx/works/1867-c1/"],
            "legal_pdf_urls": ["https://www.marxists.org/archive/marx/works/download/pdf/Capital-Volume-I.pdf"],
            "search_queries": ["资本论 第一卷 PDF 本地", "Capital Volume I Marxists PDF"],
        },
        {
            "title": "贫穷的本质",
            "author": "阿比吉特·班纳吉 / 埃斯特·迪弗洛",
            "category": "财经/社会科学",
            "reason": "现代发展经济学代表作，案例强，适合转成有故事感的现实议题。",
            "future_angle": "从穷人为什么做出看似不理性的选择切入，讲约束而非评判。",
            "source_status": "copyrighted",
            "search_queries": ["贫穷的本质 PDF 本地", "Poor Economics legal ebook"],
        },
        {
            "title": "思考，快与慢",
            "author": "丹尼尔·卡尼曼",
            "category": "财经/心理学",
            "reason": "高知名度行为经济学经典，能连接消费、投资、判断偏误和日常选择。",
            "future_angle": "每集只讲一个偏误，用生活例子收束到决策建议。",
            "source_status": "copyrighted",
            "search_queries": ["思考快与慢 PDF 本地", "Thinking Fast and Slow legal ebook"],
        },
        {
            "title": "理想国",
            "author": "柏拉图",
            "category": "哲学",
            "reason": "哲学入门常青经典，洞穴隐喻和正义问题有天然传播性。",
            "future_angle": "从洞穴隐喻讲信息茧房，再回到柏拉图真正关心的灵魂秩序。",
            "source_status": "public_domain_text",
            "legal_source_pages": ["https://www.gutenberg.org/ebooks/1497", "https://en.wikisource.org/wiki/The_Republic_of_Plato"],
            "search_queries": ["理想国 PDF 本地", "Plato Republic public domain PDF"],
        },
        {
            "title": "论语",
            "author": "孔子及其弟子",
            "category": "哲学/经典",
            "reason": "中文语境熟悉度极高，适合做反直觉、去鸡汤化的经典重读。",
            "future_angle": "把常见金句放回春秋秩序和师生对话里重讲。",
            "source_status": "public_domain_text",
            "legal_source_pages": ["https://www.gutenberg.org/ebooks/4094"],
            "search_queries": ["论语 PDF 本地", "Analects Confucius public domain PDF"],
        },
        {
            "title": "笛卡尔的错误",
            "author": "安东尼奥·达马西奥",
            "category": "神经科学经典",
            "reason": "连接情绪、身体和理性决策，是神经科学大众写作的经典入口。",
            "future_angle": "用病人案例说明：没有情绪的人，反而更难做决定。",
            "source_status": "copyrighted",
            "search_queries": ["笛卡尔的错误 PDF 本地", "Descartes' Error legal ebook"],
        },
        {
            "title": "寻找斯宾诺莎",
            "author": "安东尼奥·达马西奥",
            "category": "神经科学/哲学",
            "reason": "能把神经科学与哲学名著连接起来，适合做跨学科系列。",
            "future_angle": "从身体感受如何变成情绪，接到斯宾诺莎的心身问题。",
            "source_status": "copyrighted",
            "search_queries": ["寻找斯宾诺莎 PDF 本地", "Looking for Spinoza legal ebook"],
        },
        {
            "title": "意识探秘",
            "author": "克里斯托夫·科赫",
            "category": "神经科学经典",
            "reason": "意识研究代表性大众读物，适合解释神经相关物、主观体验和科学边界。",
            "future_angle": "先问机器或动物有没有体验，再讲科学家如何寻找意识线索。",
            "source_status": "copyrighted",
            "search_queries": ["意识探秘 PDF 本地", "Quest for Consciousness legal ebook"],
        },
        {
            "title": "记忆之谜",
            "author": "埃里克·坎德尔",
            "category": "神经科学经典",
            "reason": "诺奖科学家的自传式科学史，兼具故事、实验和记忆机制。",
            "future_angle": "从海兔实验讲到人类记忆：为什么记住不是录像，而是重塑。",
            "source_status": "copyrighted",
            "search_queries": ["记忆之谜 PDF 本地", "In Search of Memory legal ebook"],
        },
        {
            "title": "万历十五年",
            "author": "黄仁宇",
            "category": "历史",
            "reason": "中文历史读者熟悉度高，适合把制度、财政和人物命运讲成系列。",
            "future_angle": "从一个看似平静的年份，讲大明制度为什么已经疲惫。",
            "source_status": "copyrighted",
            "search_queries": ["万历十五年 PDF 本地", "万历十五年 合法电子书"],
        },
        {
            "title": "乡土中国",
            "author": "费孝通",
            "category": "社会科学/经典",
            "reason": "中文社科经典，概念短小有力，适合做差序格局、礼治秩序等短视频拆解。",
            "future_angle": "从熟人社会为什么不是简单的人情社会讲起。",
            "source_status": "copyrighted",
            "search_queries": ["乡土中国 PDF 本地", "乡土中国 合法电子书"],
        },
        {
            "title": "君主论",
            "author": "尼科洛·马基雅维利",
            "category": "政治哲学/经典",
            "reason": "公共领域经典，争议性强，适合讲权力、现实主义和道德判断的张力。",
            "future_angle": "先问马基雅维利是不是在教坏人，再回到他面对的乱世。",
            "source_status": "public_domain_text",
            "legal_source_pages": ["https://www.gutenberg.org/ebooks/1232"],
            "search_queries": ["君主论 PDF 本地", "The Prince public domain PDF"],
        },
        {
            "title": "社会契约论",
            "author": "让-雅克·卢梭",
            "category": "政治哲学/经典",
            "reason": "现代政治哲学常青入口，适合讲自由、共同意志和现代国家。",
            "future_angle": "从人为什么会服从自己参与制定的规则讲起。",
            "source_status": "public_domain_text",
            "legal_source_pages": ["https://www.gutenberg.org/ebooks/46333"],
            "search_queries": ["社会契约论 PDF 本地", "Social Contract Rousseau public domain PDF"],
        },
        {
            "title": "道德情操论",
            "author": "亚当·斯密",
            "category": "哲学/财经经典",
            "reason": "能和《国富论》互补，避免把斯密讲成单纯市场崇拜者。",
            "future_angle": "从旁观者视角讲同情心如何参与社会秩序。",
            "source_status": "public_domain_text",
            "legal_source_pages": ["https://www.gutenberg.org/ebooks/67363"],
            "search_queries": ["道德情操论 PDF 本地", "Theory of Moral Sentiments public domain PDF"],
        },
        {
            "title": "影响力",
            "author": "罗伯特·西奥迪尼",
            "category": "心理学/商业",
            "reason": "大众阅读量高，案例型强，适合转成传播、营销和日常决策选题。",
            "future_angle": "每集讲一个被说服机制，再提醒它如何被滥用。",
            "source_status": "copyrighted",
            "search_queries": ["影响力 PDF 本地", "Influence Cialdini legal ebook"],
        },
        {
            "title": "错把妻子当帽子",
            "author": "奥利弗·萨克斯",
            "category": "神经科学经典",
            "reason": "病例故事极强，适合把神经心理学讲得有人味。",
            "future_angle": "从一个离奇病例讲大脑如何拼出我们以为理所当然的世界。",
            "source_status": "copyrighted",
            "search_queries": ["错把妻子当帽子 PDF 本地", "The Man Who Mistook His Wife for a Hat legal ebook"],
        },
        {
            "title": "脑中魅影",
            "author": "拉马钱德兰",
            "category": "神经科学经典",
            "reason": "幻肢、失认等案例传播性强，适合做认知神经科学入门。",
            "future_angle": "从幻肢痛讲大脑地图如何塑造身体感。",
            "source_status": "copyrighted",
            "search_queries": ["脑中魅影 PDF 本地", "Phantoms in the Brain legal ebook"],
        },
        {
            "title": "原则",
            "author": "瑞·达利欧",
            "category": "财经/管理",
            "reason": "商业读者熟悉度高，能连接决策、组织和投资周期。",
            "future_angle": "从一次错误决策讲为什么原则是可复盘的算法。",
            "source_status": "copyrighted",
            "search_queries": ["原则 PDF 本地", "Principles Ray Dalio legal ebook"],
        },
        {
            "title": "债务危机",
            "author": "瑞·达利欧",
            "category": "财经",
            "reason": "适合讲经济周期、杠杆和危机机制，财经选题长期可复用。",
            "future_angle": "用家庭负债类比国家和市场的去杠杆周期。",
            "source_status": "copyrighted",
            "search_queries": ["债务危机 PDF 本地", "Big Debt Crises legal PDF"],
        },
    ]


def _normalize_match_text(value: str) -> str:
    return re.sub(r"[\s\-_《》〈〉:：,，.。·/\\()\[\]（）【】]+", "", value).lower()


def _safe_pdf_name(title: str, author: str = "") -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", f"{title}_{author}".strip("_"))
    value = re.sub(r"\s+", "_", value).strip("._")
    return (value or "book_candidate")[:120] + ".pdf"


def _iter_candidate_pdfs() -> list[Path]:
    found: list[Path] = []
    seen: set[str] = set()
    for root in BOOK_PDF_SEARCH_ROOTS:
        if not root.exists():
            continue
        try:
            iterator = root.rglob("*.pdf")
            for path in iterator:
                key = str(path).lower()
                if key in seen:
                    continue
                seen.add(key)
                found.append(path)
                if len(found) >= BOOK_PDF_SEARCH_LIMIT:
                    return found
        except OSError:
            append_jsonl(LOG_FILE, {"event": "book-pdf-scan-skipped-root", "root": str(root), "reason": "access-error"})
    return found


def download_legal_candidate_pdf(item: dict[str, Any]) -> dict[str, Any]:
    urls = item.get("legal_pdf_urls") if isinstance(item.get("legal_pdf_urls"), list) else []
    urls = [str(url).strip() for url in urls if str(url).strip().lower().startswith(("https://", "http://"))]
    if not urls:
        return {"ok": False, "skipped": True, "reason": "legal_source_required"}
    download_dir = BOOK_PDF_DOWNLOAD_DIR
    for candidate_dir in (BOOK_PDF_DOWNLOAD_DIR, BOOK_PDF_DOWNLOAD_FALLBACK_DIR, BOOK_PDF_DOWNLOAD_TEMP_DIR):
        try:
            candidate_dir.mkdir(parents=True, exist_ok=True)
            download_dir = candidate_dir
            break
        except PermissionError:
            continue
    else:
        return {"ok": False, "reason": "download-dir-permission-denied"}
    target = download_dir / _safe_pdf_name(str(item.get("title") or ""), str(item.get("author") or ""))
    if target.exists() and target.stat().st_size > 0:
        return {"ok": True, "skipped": True, "reason": "already-downloaded", "path": str(target)}
    last_error = ""
    for url in urls:
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "xgn-assistant-self-optimizer/1.0"})
            with urllib.request.urlopen(request, timeout=BOOK_PDF_DOWNLOAD_TIMEOUT_SECONDS) as response:
                content_type = str(response.headers.get("Content-Type") or "").lower()
                data = response.read(80 * 1024 * 1024)
            if not data.startswith(b"%PDF") and "pdf" not in content_type:
                last_error = f"not-pdf-content: {content_type or 'unknown'}"
                continue
            target.write_bytes(data)
            return {"ok": True, "path": str(target), "url": url, "bytes": len(data)}
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
    return {"ok": False, "reason": "download-failed", "error": last_error}


def attach_pdf_matches(candidates: list[dict[str, Any]], *, allow_download: bool = True) -> dict[str, Any]:
    pdfs = _iter_candidate_pdfs()
    indexed = [(path, _normalize_match_text(path.stem), _normalize_match_text(str(path.parent))) for path in pdfs]
    matched = 0
    missing = 0
    downloaded = 0
    legal_source_required = 0
    for item in candidates:
        title_key = _normalize_match_text(str(item.get("title") or ""))
        author_key = _normalize_match_text(str(item.get("author") or "").split("/")[0])
        hits: list[str] = []
        for path, stem_key, parent_key in indexed:
            haystack = f"{stem_key}{parent_key}"
            if title_key and title_key in haystack:
                hits.append(str(path))
            elif author_key and len(author_key) >= 3 and author_key in haystack:
                hits.append(str(path))
            if len(hits) >= 5:
                break
        item["pdf_status"] = "found" if hits else "missing_pdf"
        item["pdf_matches"] = hits
        item["pdf_search_roots"] = [str(root) for root in BOOK_PDF_SEARCH_ROOTS]
        if hits:
            item["download_status"] = "not_needed"
            matched += 1
        else:
            download = download_legal_candidate_pdf(item) if allow_download else {"ok": False, "skipped": True, "reason": "download-disabled"}
            item["download_result"] = download
            if download.get("ok") and download.get("path"):
                item["pdf_status"] = "downloaded"
                item["pdf_matches"] = [str(download["path"])]
                item["download_status"] = "downloaded" if not download.get("skipped") else str(download.get("reason") or "downloaded")
                matched += 1
                downloaded += 0 if download.get("skipped") else 1
            else:
                item["download_status"] = str(download.get("reason") or "missing_pdf")
                if item["download_status"] == "legal_source_required":
                    legal_source_required += 1
                missing += 1
    return {
        "scanned_pdfs": len(pdfs),
        "matched": matched,
        "downloaded": downloaded,
        "missing_pdf": missing,
        "legal_source_required": legal_source_required,
        "download_dir": str(BOOK_PDF_DOWNLOAD_DIR),
        "download_fallback_dir": str(BOOK_PDF_DOWNLOAD_FALLBACK_DIR),
        "download_temp_dir": str(BOOK_PDF_DOWNLOAD_TEMP_DIR),
    }


def refresh_book_candidates(state: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
    last_at = float(state.get("last_book_candidate_epoch", 0) or 0)
    if not force and last_at and time.time() - last_at < BOOK_CANDIDATE_UPDATE_MIN_SECONDS:
        return {
            "ok": True,
            "skipped": True,
            "reason": "book-candidate-update-throttled",
            "path": str(BOOK_CANDIDATES_FILE),
        }
    candidates = _seed_book_candidates()
    pdf_scan = attach_pdf_matches(candidates)
    payload = {
        "project": "自媒体小猪理",
        "updated_at": now_iso(),
        "purpose": "空闲时维护的未来选题书单；仅供人工选择，不自动生成素材。",
        "selection_note": "当前为离线保守种子清单，优先覆盖历史、财经、哲学、神经科学经典；后续可接入公开阅读量/评分源再校准。pdf_status=missing_pdf 表示本地搜索根目录暂未找到对应 PDF；download_status=legal_source_required 表示没有配置合法公开 PDF 下载源，不会自动下载疑似盗版文件。",
        "pdf_scan": pdf_scan,
        "candidates": candidates,
    }
    written_path = BOOK_CANDIDATES_FILE
    for candidate_path in (BOOK_CANDIDATES_FILE, BOOK_CANDIDATES_FALLBACK_FILE, BOOK_CANDIDATES_TEMP_FILE):
        try:
            candidate_path.parent.mkdir(parents=True, exist_ok=True)
            candidate_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            written_path = candidate_path
            break
        except PermissionError:
            continue
    else:
        written_path = BOOK_CANDIDATES_TEMP_FILE
    state["last_book_candidate_epoch"] = time.time()
    state["last_book_candidates_file"] = str(written_path)
    append_jsonl(EVENTS_FILE, {
        "project": "自媒体小猪理",
        "stage": "audience_research",
        "event": "book-candidates-refreshed",
        "count": len(payload["candidates"]),
        "pdf_scan": pdf_scan,
        "path": str(written_path),
    })
    return {"ok": True, "count": len(payload["candidates"]), "pdf_scan": pdf_scan, "path": str(written_path)}


def audience_bot_available() -> dict[str, Any]:
    bot_path = ROOT / "modes" / "culture" / "automedia_core" / "audience_test_bot.py"
    if not bot_path.exists():
        return {"ok": False, "reason": "missing", "path": str(bot_path)}
    check = run([sys.executable, "-m", "py_compile", str(bot_path)], timeout=60)
    if check["ok"]:
        return {"ok": True, "path": str(bot_path)}
    return {
        "ok": False,
        "reason": "py_compile_failed",
        "path": str(bot_path),
        "stderr": check["stderr"],
    }


def idle_optimization(apply: bool, package_release: bool = True, state: dict[str, Any] | None = None) -> dict[str, Any]:
    availability = audience_bot_available()
    if availability["ok"]:
        bot_cmd = [sys.executable, "-m", "modes.culture.automedia_core.audience_test_bot", "--online"]
        if apply:
            bot_cmd.append("--apply")
        bot = run(bot_cmd, timeout=240)
    else:
        append_jsonl(QUEUE_FILE, {
            "type": "runtime-bug",
            "source": "audience_test_bot.py",
            "status": "pending",
            "summary": f"Audience test bot unavailable: {availability.get('reason')}",
            "detail": availability,
        })
        bot = {
            "ok": False,
            "returncode": None,
            "stdout": "",
            "stderr": json.dumps(availability, ensure_ascii=False),
        }
    if package_release:
        package = run(
            [sys.executable, "tools/channel_manager.py", "package-update", "--note", "self-optimizer release update"],
            timeout=240,
        )
    else:
        package = {"ok": True, "skipped": True, "reason": "no-new-issues-or-feedback"}
    state = state if state is not None else read_json(STATE_FILE, {})
    book_candidates = refresh_book_candidates(state)
    result = {"audience_test_bot": bot, "release_package_update": package, "book_candidates": book_candidates, "apply": apply}
    append_jsonl(LOG_FILE, {"event": "idle-optimization", "result": result})
    return result


def optimize_once(force: bool = False, apply: bool = False) -> dict[str, Any]:
    state = read_json(STATE_FILE, {})
    bugs = scan_runtime_bugs(state)
    last_roleplay_at = float(state.get("last_roleplay_epoch", 0) or 0)
    roleplay_due = force or bool(bugs) or not last_roleplay_at or time.time() - last_roleplay_at >= ROLEPLAY_UPDATE_MIN_SECONDS
    roles = role_play_plan(state) if roleplay_due else state.get("role_play_reviews", [])
    issues = [
        {
            "id": bug.get("issue_id", ""),
            "source": bug.get("source", ""),
            **classify_issue(str(bug.get("summary", "")), str(bug.get("source", ""))),
            "summary": bug.get("summary", ""),
        }
        for bug in bugs
    ]
    patch_plan = write_patch_plan(state, issues, roles) if roleplay_due or issues else {"pending_issues": []}
    roleplay_details = write_roleplay_details(state, roles, issues) if roleplay_due else state.get("last_roleplay_details", [])
    if roleplay_due:
        state["last_roleplay_epoch"] = time.time()
    book_candidates = refresh_book_candidates(state, force=force)
    last_idle_at = state.get("last_idle_optimization_epoch", 0)
    idle_due = force or not last_idle_at or time.time() - float(last_idle_at) >= IDLE_UPDATE_MIN_SECONDS
    if idle_due:
        package_release = bool(issues) or source_has_pending_feedback()
        idle_result = idle_optimization(apply=apply or force or os.environ.get("XGN_SELF_OPTIMIZER_APPLY") == "true", package_release=package_release, state=state)
        release_event = extract_release_event_from_idle(idle_result)
        maybe_email_optimization_log("release-optimization", {"idle_optimization": idle_result, "release_event": release_event, "issues": issues[-10:], "roleplay_details": roleplay_details})
        state["last_idle_optimization_epoch"] = time.time()
    else:
        idle_result = {"skipped": True, "reason": "idle-update-throttled"}
    state["last_seen_at"] = now_iso()
    state["last_result"] = {
        "bugs": len(bugs),
        "roles": len(roles),
        "patch_plan": len(patch_plan["pending_issues"]),
        "book_candidates": book_candidates,
        "idle_optimization": idle_result,
    }
    update_learning_memory(state, issues=issues, release=idle_result)
    write_json(STATE_FILE, state)
    append_jsonl(LOG_FILE, {"event": "self-optimizer-tick", **state["last_result"]})
    return state["last_result"]


def main() -> int:
    parser = argparse.ArgumentParser(description="xgn-assistant self optimizer")
    parser.add_argument("command", nargs="?", default="once", choices=["once", "daemon", "add-feedback", "add-bug"])
    parser.add_argument("text", nargs="*")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    if args.command in {"add-feedback", "add-bug"}:
        sys.stdout.buffer.write((json.dumps(add_feedback(" ".join(args.text), args.command), ensure_ascii=False, indent=2) + "\n").encode("utf-8", errors="replace"))
        return 0

    if args.command == "once":
        sys.stdout.buffer.write((json.dumps(optimize_once(force=args.force, apply=args.apply), ensure_ascii=False, indent=2) + "\n").encode("utf-8", errors="replace"))
        return 0

    append_jsonl(LOG_FILE, {"event": "self-optimizer-started", "mode": "daemon", "interval_seconds": INTERVAL_SECONDS})
    while True:
        try:
            optimize_once(force=args.force, apply=args.apply)
        except Exception as exc:
            append_jsonl(LOG_FILE, {"event": "self-optimizer-failed", "error": f"{type(exc).__name__}: {exc}"})
        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    raise SystemExit(main())
