from __future__ import annotations

import json
import os
import smtplib
import traceback
import zipfile
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = Path(os.environ.get("QUANLAN_CULTURE_RUN_SWITCH_FILE") or (PROJECT_ROOT / "config" / "运行开关.json"))
DEFAULT_PASSWORD_FILE = PROJECT_ROOT / "smtp_password.txt"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _get_nested(data: dict[str, Any], key: str, default: Any = None) -> Any:
    cur: Any = data
    for part in key.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur.get(part)
    return cur


def _as_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [x.strip() for x in value.split(",") if x.strip()]
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    return []


def _smtp_password_info(config: dict[str, Any]) -> tuple[str, str, str]:
    env_name = str(config.get("password_env") or "AMP_SMTP_PASSWORD").strip()
    if env_name and os.getenv(env_name):
        return str(os.getenv(env_name) or "").strip(), f"环境变量 {env_name}", ""
    password_file = str(config.get("password_file") or "").strip()
    path = Path(password_file) if password_file else DEFAULT_PASSWORD_FILE
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    env_hint = f"环境变量 {env_name}" if env_name else "环境变量"
    try:
        if not path.exists():
            return "", "", f"未设置{env_hint}，且授权码文件不存在：{path}"
        value = path.read_text(encoding="utf-8").strip()
        if not value:
            return "", "", f"未设置{env_hint}，且授权码文件为空：{path}"
        return value, f"授权码文件 {path}", ""
    except Exception as exc:
        return "", "", f"未设置{env_hint}，且授权码文件读取失败：{path}（{exc}）"


def _smtp_password(config: dict[str, Any]) -> str:
    password, _source, _reason = _smtp_password_info(config)
    return password


def load_email_config() -> dict[str, Any]:
    root = _read_json(CONFIG_PATH)
    config = _get_nested(root, "email_delivery", {})
    return config if isinstance(config, dict) else {}


def email_delivery_enabled(config: dict[str, Any] | None = None) -> bool:
    config = config if config is not None else load_email_config()
    return bool(config.get("enabled"))


def _smtp_runtime_config(config: dict[str, Any]) -> dict[str, Any]:
    recipients = _as_list(config.get("to"))
    sender = str(config.get("from") or config.get("username") or "").strip()
    username = str(config.get("username") or sender).strip()
    host = str(config.get("smtp_host") or "").strip()
    try:
        port = int(config.get("smtp_port") or 465)
    except Exception:
        port = 465
    use_ssl = bool(config.get("use_ssl", True))
    password, password_source, password_reason = _smtp_password_info(config)
    return {
        "recipients": recipients,
        "sender": sender,
        "username": username,
        "host": host,
        "port": port,
        "use_ssl": use_ssl,
        "password": password,
        "password_source": password_source,
        "password_reason": password_reason,
    }


def _smtp_public_config(settings: dict[str, Any]) -> dict[str, Any]:
    return {
        "host": settings.get("host") or "",
        "port": settings.get("port") or 0,
        "use_ssl": bool(settings.get("use_ssl")),
        "username": settings.get("username") or "",
        "sender": settings.get("sender") or "",
        "recipients": list(settings.get("recipients") or []),
        "password_source": settings.get("password_source") or "",
    }


def _smtp_config_warnings(settings: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    host = str(settings.get("host") or "").lower()
    username = str(settings.get("username") or "").strip().lower()
    sender = str(settings.get("sender") or "").strip().lower()
    if "qq.com" in host and username and sender and username != sender:
        warnings.append("QQ 邮箱建议登录账号和发件人保持一致；授权码必须属于登录账号对应的邮箱。")
    if "qq.com" in host and int(settings.get("port") or 0) == 465 and not settings.get("use_ssl"):
        warnings.append("QQ 邮箱使用 465 端口时应勾选 SSL。")
    return warnings


def _smtp_error_hint(settings: dict[str, Any], exc: BaseException) -> str:
    host = str(settings.get("host") or "").lower()
    message = str(exc)
    if "qq.com" in host and ("535" in message or "Login fail" in message or "Authentication" in type(exc).__name__):
        return (
            "QQ SMTP 已连通但登录被拒绝。请确认：1）SMTP/IMAP 服务已在 QQ 邮箱网页端开启；"
            "2）smtp_password.txt 里的授权码属于“登录账号”这个邮箱，不是收件箱或另一个 QQ 邮箱；"
            "3）登录账号和发件人最好填写同一个 QQ 邮箱；4）如果短时间多次失败，稍等后重新生成授权码再测。"
        )
    if "unexpectedly closed" in message.lower():
        return "SMTP 服务器主动断开连接。常见原因是认证方式被拒绝、授权码不匹配、账号安全限制或登录频率过高。"
    return ""


def _smtp_missing_fields(settings: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    if not settings.get("host"):
        missing.append("smtp_host")
    if not settings.get("sender"):
        missing.append("from/username")
    if not settings.get("username"):
        missing.append("username")
    if not settings.get("password"):
        missing.append(settings.get("password_reason") or "SMTP 授权码（password_env 或 password_file）")
    if not settings.get("recipients"):
        missing.append("to")
    return missing


def _smtp_exception_payload(exc: BaseException, *, stage: str) -> dict[str, Any]:
    return {
        "stage": stage,
        "error_type": type(exc).__name__,
        "error": str(exc),
        "traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).rstrip(),
    }


def _close_smtp(smtp: smtplib.SMTP | smtplib.SMTP_SSL | None) -> None:
    if smtp is None:
        return
    try:
        smtp.quit()
    except Exception:
        try:
            smtp.close()
        except Exception:
            pass


def _open_smtp(settings: dict[str, Any]) -> smtplib.SMTP | smtplib.SMTP_SSL:
    if settings["use_ssl"]:
        return smtplib.SMTP_SSL(settings["host"], int(settings["port"]), timeout=30)
    return smtplib.SMTP(settings["host"], int(settings["port"]), timeout=30)


def _prepare_smtp_session(smtp: smtplib.SMTP | smtplib.SMTP_SSL, settings: dict[str, Any], emit: Any | None = None) -> None:
    code, resp = smtp.ehlo()
    if emit is not None:
        emit(f"EHLO 返回：{code} {resp!r}")
    if not settings["use_ssl"]:
        if emit is not None:
            emit("开始 STARTTLS。")
        code, resp = smtp.starttls()
        if emit is not None:
            emit(f"STARTTLS 返回：{code} {resp!r}")
        code, resp = smtp.ehlo()
        if emit is not None:
            emit(f"STARTTLS 后 EHLO 返回：{code} {resp!r}")


def _auth_login_only(smtp: smtplib.SMTP | smtplib.SMTP_SSL, username: str, password: str) -> tuple[int, bytes]:
    smtp.user = username
    smtp.password = password
    return smtp.auth("LOGIN", smtp.auth_login, initial_response_ok=False)


def _connect_and_login(settings: dict[str, Any], emit: Any | None = None) -> tuple[smtplib.SMTP | smtplib.SMTP_SSL, str]:
    smtp: smtplib.SMTP | smtplib.SMTP_SSL | None = None
    try:
        if emit is not None:
            emit("开始连接 SMTP_SSL 服务器。" if settings["use_ssl"] else "开始连接 SMTP 服务器。")
        smtp = _open_smtp(settings)
        if emit is not None:
            emit("SMTP 连接已建立。")
        _prepare_smtp_session(smtp, settings, emit)
        if emit is not None:
            emit("开始 SMTP 登录（标准模式）。")
        smtp.login(str(settings["username"]), str(settings["password"]))
        if emit is not None:
            emit("SMTP 登录成功（标准模式）。")
        return smtp, "standard"
    except (smtplib.SMTPServerDisconnected, smtplib.SMTPAuthenticationError, smtplib.SMTPException) as first_exc:
        if emit is not None:
            emit(f"标准 SMTP 登录失败，准备重连并改用 AUTH LOGIN：{type(first_exc).__name__} - {first_exc}")
        _close_smtp(smtp)
        smtp = None
        try:
            if emit is not None:
                emit("开始重新连接 SMTP 服务器。")
            smtp = _open_smtp(settings)
            if emit is not None:
                emit("SMTP 重新连接已建立。")
            _prepare_smtp_session(smtp, settings, emit)
            if emit is not None:
                emit("开始 SMTP 登录（AUTH LOGIN 兜底模式）。")
            code, resp = _auth_login_only(smtp, str(settings["username"]), str(settings["password"]))
            if code not in (235, 503):
                raise smtplib.SMTPAuthenticationError(code, resp)
            if emit is not None:
                emit(f"SMTP 登录成功（AUTH LOGIN）：{code} {resp!r}")
            return smtp, "auth_login"
        except Exception:
            _close_smtp(smtp)
            raise


def test_email_connection(*, send_test: bool = True, logger: Any | None = None) -> dict[str, Any]:
    """Test SMTP config without exposing the authorization code."""
    config = load_email_config()
    settings = _smtp_runtime_config(config)
    result: dict[str, Any] = {
        "ok": False,
        "sent": False,
        "time": datetime.now().isoformat(timespec="seconds"),
        "smtp": _smtp_public_config(settings),
        "steps": [],
    }

    def emit(message: str) -> None:
        result["steps"].append(message)
        if logger is not None:
            try:
                logger(message)
            except Exception:
                pass

    emit(f"读取邮箱配置：SMTP={settings['host']}:{settings['port']}，SSL={bool(settings['use_ssl'])}")
    emit(f"发件人={settings['sender'] or '未填写'}，登录账号={settings['username'] or '未填写'}")
    emit(f"收件人={', '.join(settings['recipients']) if settings['recipients'] else '未填写'}")
    emit(f"授权码来源={settings['password_source'] or settings['password_reason'] or '未找到'}")
    for warning in _smtp_config_warnings(settings):
        emit("配置提醒：" + warning)

    missing = _smtp_missing_fields(settings)
    if missing:
        result["reason"] = "邮件配置缺失：" + "、".join(missing)
        emit("配置检查失败：" + result["reason"])
        return result

    smtp: smtplib.SMTP | smtplib.SMTP_SSL | None = None
    stage = "connect_or_login"
    try:
        smtp, auth_mode = _connect_and_login(settings, emit)
        result["auth_mode"] = auth_mode

        if send_test:
            stage = "send_test"
            msg = EmailMessage()
            msg["From"] = str(settings["sender"])
            msg["To"] = ", ".join(settings["recipients"])
            msg["Subject"] = "著作解读邮箱测试"
            msg.set_content(
                "这是一封来自著作解读工具的 SMTP 测试邮件。\n"
                f"测试时间：{datetime.now().isoformat(timespec='seconds')}\n"
                "如果你收到这封邮件，说明 SMTP 登录和发送均正常。"
            )
            emit("开始发送测试邮件。")
            smtp.send_message(msg)
            result["sent"] = True
            emit("测试邮件发送成功。")

        result["ok"] = True
        return result
    except Exception as exc:
        payload = _smtp_exception_payload(exc, stage=stage)
        result.update(payload)
        result["reason"] = f"{payload['stage']} 阶段失败：{payload['error_type']} - {payload['error']}"
        hint = _smtp_error_hint(settings, exc)
        if hint:
            result["hint"] = hint
            emit("排查建议：" + hint)
        emit("测试失败：" + str(result["reason"]))
        emit(str(result["traceback"]))
        return result
    finally:
        if smtp is not None:
            _close_smtp(smtp)
            emit("SMTP 连接已关闭。")


def _iter_package_files(part_dir: Path, include_patterns: list[str], exclude_patterns: list[str]) -> list[Path]:
    files: list[Path] = []
    for pattern in include_patterns:
        files.extend([p for p in part_dir.glob(pattern) if p.is_file()])
    unique: dict[Path, Path] = {}
    for path in files:
        rel = path.relative_to(part_dir)
        if any(rel.match(pattern) for pattern in exclude_patterns):
            continue
        unique[path.resolve()] = path
    return sorted(unique.values(), key=lambda p: p.relative_to(part_dir).as_posix())


def package_split_part(part_dir: Path, *, max_mb: int = 20) -> dict[str, Any]:
    part_dir = Path(part_dir)
    package_dir = part_dir / "_邮件发送"
    package_dir.mkdir(parents=True, exist_ok=True)
    zip_path = package_dir / f"{part_dir.name}.zip"
    include_patterns = [
        "*.mp4",
        "*.mov",
        "*.m4v",
        "01_台词.lrc",
        "04_视频简介.txt",
        "04_视频简介.json",
        "images/*",
    ]
    exclude_patterns = ["_邮件发送/*"]
    files = _iter_package_files(part_dir, include_patterns, exclude_patterns)
    if not files:
        return {"ok": False, "reason": "分集目录中没有可打包文件", "zip": ""}
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            zf.write(path, path.relative_to(part_dir).as_posix())
    size_bytes = zip_path.stat().st_size
    max_bytes = int(max_mb) * 1024 * 1024
    if max_bytes > 0 and size_bytes > max_bytes:
        return {
            "ok": False,
            "reason": f"附件超过限制：{size_bytes / 1024 / 1024:.1f}MB > {max_mb}MB",
            "zip": str(zip_path),
            "size_bytes": size_bytes,
        }
    return {"ok": True, "zip": str(zip_path), "size_bytes": size_bytes, "file_count": len(files)}


def send_split_part_email(part_dir: Path, *, title: str = "", part_no: int = 0, dry_run: bool = False) -> dict[str, Any]:
    config = load_email_config()
    result: dict[str, Any] = {
        "enabled": bool(config.get("enabled")),
        "sent": False,
        "time": datetime.now().isoformat(timespec="seconds"),
    }
    if not config.get("enabled"):
        result["reason"] = "email_delivery.enabled 未开启"
        return result

    settings = _smtp_runtime_config(config)
    recipients = list(settings["recipients"])
    sender = str(settings["sender"])
    username = str(settings["username"])
    host = str(settings["host"])
    port = int(settings["port"])
    use_ssl = bool(settings["use_ssl"])
    password = str(settings["password"])
    result["smtp"] = _smtp_public_config(settings)
    warnings = _smtp_config_warnings(settings)
    if warnings:
        result["warnings"] = warnings
    if settings.get("password_source"):
        result["password_source"] = settings["password_source"]
    max_mb = int(config.get("max_attachment_mb") or 20)

    missing = _smtp_missing_fields(settings)
    if missing:
        result["reason"] = "邮件配置缺失：" + "、".join(missing)
        return result

    package = package_split_part(Path(part_dir), max_mb=max_mb)
    result["package"] = package
    if not package.get("ok"):
        result["reason"] = str(package.get("reason") or "打包失败")
        return result

    zip_path = Path(str(package["zip"]))
    subject_template = str(config.get("subject_template") or "著作解读分集完成：{part_name}")
    context = {
        "part_name": Path(part_dir).name,
        "title": title or Path(part_dir).name,
        "part_no": part_no,
    }
    try:
        subject = subject_template.format(**context)
    except Exception:
        subject = f"著作解读分集完成：{Path(part_dir).name}"

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.set_content(
        "\n".join([
            "分集已生成完成，附件为本集素材包。",
            "",
            f"分集目录：{part_dir}",
            f"分集标题：{title or Path(part_dir).name}",
            f"附件大小：{int(package.get('size_bytes') or 0) / 1024 / 1024:.1f}MB",
        ])
    )
    msg.add_attachment(zip_path.read_bytes(), maintype="application", subtype="zip", filename=zip_path.name)

    if dry_run:
        result.update({"sent": False, "dry_run": True, "to": recipients, "zip": str(zip_path)})
        return result

    stage = "connect_or_login"
    smtp: smtplib.SMTP | smtplib.SMTP_SSL | None = None
    try:
        smtp, auth_mode = _connect_and_login(settings)
        result["auth_mode"] = auth_mode
        result["smtp_stage"] = "logged_in"
        stage = "send_message"
        smtp.send_message(msg)
    except Exception as exc:
        result.update(_smtp_exception_payload(exc, stage=stage))
        result["reason"] = f"{stage} 阶段失败：{type(exc).__name__} - {exc}"
        hint = _smtp_error_hint(settings, exc)
        if hint:
            result["hint"] = hint
        return result
    finally:
        _close_smtp(smtp)

    result.update({"sent": True, "to": recipients, "zip": str(zip_path)})
    return result


def write_email_result(part_dir: Path, result: dict[str, Any]) -> None:
    _write_json(Path(part_dir) / "_邮件发送" / "发送结果.json", result)
