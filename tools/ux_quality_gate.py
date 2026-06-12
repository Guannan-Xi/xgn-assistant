from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request


DEFAULT_BASE_URL = "http://127.0.0.1:8767"
OLD_CHILD_MODEL_BUTTONS = ("配置模型 Key", "配置科研模型", "配置 MiniMax Key")


def fetch_text(url: str, *, method: str = "GET", body: bytes | None = None) -> tuple[int, str]:
    req = urllib.request.Request(url, data=body, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch_no_redirect(url: str) -> tuple[int, str]:
    opener = urllib.request.build_opener(NoRedirect)
    req = urllib.request.Request(url)
    try:
        with opener.open(req, timeout=12) as resp:
            return resp.status, resp.headers.get("Location", "")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get("Location", "")


def fetch_timed(url: str, *, method: str = "GET", body: bytes | None = None) -> tuple[int, str, float]:
    started = time.monotonic()
    status, text = fetch_text(url, method=method, body=body)
    return status, text, (time.monotonic() - started) * 1000


def check(name: str, ok: bool, detail: str = "") -> dict[str, object]:
    return {"name": name, "ok": bool(ok), "detail": detail}


def run(base_url: str) -> list[dict[str, object]]:
    base_url = base_url.rstrip("/")
    results: list[dict[str, object]] = []

    status, home = fetch_text(f"{base_url}/")
    results.append(check("home loads", status == 200, str(status)))
    results.append(check("home is total console", "全澜应用总控台" in home and "home_app_grid" in home))
    results.append(check("home has app entries", all(text in home for text in ("/assistant/", "http://127.0.0.1:8787/", "http://127.0.0.1:4173/", "脑电分析平台", "全澜小猪理"))))
    results.append(check("home has unified config entry", "/assistant/#model" in home and "统一模型配置" in home))

    status, assistant = fetch_text(f"{base_url}/assistant/")
    results.append(check("assistant loads", status == 200, str(status)))
    results.append(check("assistant has app console", "app_status_grid" in assistant and "app_quick_summary" in assistant and "应用总控" in assistant))
    results.append(check("assistant buttons have feedback", 'id="toast"' in assistant and "function notify" in assistant and "beginAction" in assistant and "endAction" in assistant))
    results.append(check("assistant feedback is specific", "已点击：" not in assistant and 'openEegAnalyser(){notify(' in assistant and 'openXiaozhuli(){notify(' in assistant))
    results.append(check("assistant has separated model channels", all(text in assistant for text in ("GPT 文本", "GPT-image2", "GPT-Pro / 润色", "MiniMax 地址", "gpt_pro_api_key", "minimax_base_url"))))
    results.append(check("assistant logs link tests", "测试全部链接" in assistant and "function appendLogLine" in assistant and "function testAllModels" in assistant and "logTestResult" in assistant))
    results.append(check("assistant preview uses selected profile", "function profileModelValue" in assistant and "profileModelValue(profile,\"gpt_base_url\"" in assistant and "profileModelValue(profile,\"gpt_pro_base_url\"" in assistant))
    old_hits = [text for text in OLD_CHILD_MODEL_BUTTONS if text in assistant]
    results.append(check("child pages have no old model buttons", not old_hits, ", ".join(old_hits)))

    status, settings_raw = fetch_text(f"{base_url}/api/settings")
    try:
        settings = json.loads(settings_raw)
    except json.JSONDecodeError:
        settings = {}
    profiles = ((settings.get("model_profiles") or {}).get("profiles") or []) if isinstance(settings, dict) else []
    profile_ids = {item.get("id") for item in profiles if isinstance(item, dict)}
    secrets = settings.get("secrets") if isinstance(settings, dict) else {}
    models = settings.get("models") if isinstance(settings, dict) else {}
    results.append(check("model profiles are exactly GreatWall and DST", status == 200 and profile_ids == {"greatwall-link", "dst"}, str(sorted(profile_ids))))
    results.append(check("model keys are separate", all(bool(secrets.get(key)) for key in ("openai_api_key_configured", "image_api_key_configured", "gpt_pro_api_key_configured", "minimax_api_key_configured")) and not secrets.get("gemini_api_key_configured") and not secrets.get("deepseek_api_key_configured"), str({k: v for k, v in secrets.items() if k.endswith("_configured")})))
    results.append(check("model urls are separate", status == 200 and all(models.get(key) for key in ("foreign_base_url", "deepseek_base_url", "culture_image_base_url", "minimax_base_url")) and str(models.get("minimax_base_url", "")).rstrip("/") == "https://api.minimaxi.com/v1", str({k: models.get(k) for k in ("foreign_base_url", "deepseek_base_url", "culture_image_base_url", "minimax_base_url")})))

    status, apps_raw = fetch_text(f"{base_url}/api/apps")
    try:
        apps = json.loads(apps_raw)
    except json.JSONDecodeError:
        apps = {}
    app_ids = {item.get("id"): item for item in apps.get("apps", []) if isinstance(item, dict)}
    results.append(check("apps api loads", status == 200 and bool(app_ids), str(status)))
    for app_id in ("assistant", "xiaozhuli", "eeg"):
        item = app_ids.get(app_id) or {}
        results.append(check(f"{app_id} app is online", item.get("online") is True, str(item)))
    assistant_app = app_ids.get("assistant") or {}
    xiaozhuli_app = app_ids.get("xiaozhuli") or {}
    eeg_app = app_ids.get("eeg") or {}
    results.append(check("assistant config is total-console managed", assistant_app.get("managed") is True and assistant_app.get("sync_state") == "已同步", str(assistant_app)))
    results.append(check("xiaozhuli is isolated and controllable", xiaozhuli_app.get("isolated") is True and str(xiaozhuli_app.get("target", "")).startswith("http://127.0.0.1:8787"), str(xiaozhuli_app)))
    results.append(check("eeg remains workflow-only platform", eeg_app.get("sync_state") == "流程平台" and "通用模型" in str(eeg_app.get("config_scope", "")), str(eeg_app)))

    results.append(check(
        "child apps open through isolated service urls",
        str(xiaozhuli_app.get("route", "")).startswith("http://127.0.0.1:8787/")
        and str(eeg_app.get("route", "")).startswith("http://127.0.0.1:4173/")
        and xiaozhuli_app.get("isolated") is True
        and eeg_app.get("isolated") is True,
        str({"xiaozhuli": xiaozhuli_app.get("route"), "eeg": eeg_app.get("route")}),
    ))
    status, eeg_redirect = fetch_no_redirect(f"{base_url}/eeg/")
    results.append(check("eeg legacy root redirects to isolated service", status in {301, 302, 303, 307, 308} and eeg_redirect.startswith("http://127.0.0.1:4173/"), f"{status}, {eeg_redirect}"))
    status, eeg = fetch_text("http://127.0.0.1:4173/")
    results.append(check("eeg isolated service loads", status == 200 and "NeuroCloud" in eeg, str(status)))
    status, eeg_css = fetch_text("http://127.0.0.1:4173/styles.css")
    results.append(check("eeg login uses real visual asset", status == 200 and "publication-main-figure.png" in eeg_css, str(status)))
    results.append(check("eeg centralized note is responsive", status == 200 and ".central-config-note" in eeg_css and "flex-direction: column" in eeg_css, str(status)))
    status, eeg_js = fetch_text("http://127.0.0.1:4173/app.js")
    results.append(check("eeg collapsed nav has labels", status == 200 and "enhanceControlLabels" in eeg_js, str(status)))

    status, xiaozhuli_redirect = fetch_no_redirect(f"{base_url}/xiaozhuli/")
    results.append(check("xiaozhuli legacy root redirects to isolated service", status in {301, 302, 303, 307, 308} and xiaozhuli_redirect.startswith("http://127.0.0.1:8787/"), f"{status}, {xiaozhuli_redirect}"))
    status, xiaozhuli = fetch_text("http://127.0.0.1:8787/")
    results.append(check("xiaozhuli isolated service loads", status == 200, str(status)))
    results.append(check("xiaozhuli has own workbench shell", "全澜小猪理工作台" in xiaozhuli))
    results.append(check("xiaozhuli model panel hidden marker", 'data-centralized-config="model"' in xiaozhuli))

    status, xiaozhuli_css = fetch_text("http://127.0.0.1:8787/ui/styles.css")
    results.append(check("xiaozhuli hidden rule is enforced", status == 200 and "[hidden]" in xiaozhuli_css and "!important" in xiaozhuli_css, str(status)))

    status, xiaozhuli_js = fetch_text("http://127.0.0.1:8787/ui/app.js")
    results.append(check("xiaozhuli api client exists", status == 200 and "apiPrefix" in xiaozhuli_js and "apiUrl" in xiaozhuli_js, str(status)))

    status, status_raw, elapsed_ms = fetch_timed("http://127.0.0.1:8787/api/status")
    try:
        xiaozhuli_status = json.loads(status_raw)
    except json.JSONDecodeError:
        xiaozhuli_status = {}
    results.append(check(
        "xiaozhuli status api renders dashboard data",
        status == 200 and bool(xiaozhuli_status.get("services")) and bool(xiaozhuli_status.get("permissions")),
        f"{status}, {elapsed_ms:.0f}ms",
    ))
    results.append(check("xiaozhuli status api is responsive", status == 200 and elapsed_ms < 5000, f"{elapsed_ms:.0f}ms"))

    status, model_raw = fetch_text("http://127.0.0.1:8787/api/model")
    try:
        model = json.loads(model_raw)
    except json.JSONDecodeError:
        model = {}
    results.append(check("xiaozhuli model api readonly", status == 200 and model.get("centralized") is True and model.get("readonly") is True, str(status)))

    status, save_raw = fetch_text("http://127.0.0.1:8787/api/model", method="POST", body=b"{}")
    results.append(check("xiaozhuli model save rejected", status == 409 and "centralized" in save_raw, str(status)))

    return results


def main(argv: list[str]) -> int:
    base_url = argv[1] if len(argv) > 1 else DEFAULT_BASE_URL
    results = run(base_url)
    ok = all(item["ok"] for item in results)
    print(json.dumps({"ok": ok, "base_url": base_url, "results": results}, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

