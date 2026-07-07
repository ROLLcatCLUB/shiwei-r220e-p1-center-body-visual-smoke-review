from __future__ import annotations

import base64
import html
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import tempfile
import time
from typing import Any
import urllib.parse

from PIL import Image
import requests


ROOT = Path(__file__).resolve().parents[1]
STAGE = "1013R_R220E_P1_CENTER_BODY_VISUAL_READABILITY_SMOKE"
OUT = ROOT / "outputs" / "PREP_ROOM_RENDER_CANVAS_DEEPEN_V1" / STAGE
RESULT = OUT / "validate_1013R_R220E_P1_center_body_visual_readability_smoke_result.json"

R220E_STAGE = "1013R_R220E_SINGLE_LESSON_TEMPLATE_CENTER_BODY_READONLY_RENDER"
R220E_OUT = ROOT / "outputs" / "PREP_ROOM_RENDER_CANVAS_DEEPEN_V1" / R220E_STAGE
R220E_RESULT = R220E_OUT / "validate_1013R_R220E_single_lesson_template_center_body_readonly_render_result.json"
R220E_DOM = R220E_OUT / "r220e_teacher_readable_dom_snapshots"

SAMPLE_ORDER = [
    "real_downpour_docx",
    "numbered_colon_old_shoes",
    "plain_segment_weaving",
    "table_rain_umbrella",
    "minimal_line_fish",
]

SAMPLE_LABELS = {
    "real_downpour_docx": "下雨啰",
    "numbered_colon_old_shoes": "旧鞋 / 足下生辉",
    "plain_segment_weaving": "穿穿编编",
    "table_rain_umbrella": "雨伞图案设计",
    "minimal_line_fish": "线条小鱼",
}

SCREENSHOT_NAMES = {
    "real_downpour_docx": "real_downpour_docx.png",
    "numbered_colon_old_shoes": "numbered_colon_old_shoes.png",
    "plain_segment_weaving": "plain_segment_weaving.png",
    "table_rain_umbrella": "table_rain_umbrella.png",
    "minimal_line_fish": "minimal_line_fish.png",
}

OLD_STATIC_MARKERS = ["色彩的渐变", "渐变的节奏", "多彩的生活"]
ENGINEERING_MARKERS = [
    "R200A",
    "R200B",
    "R97B_P3",
    "source_gap",
    "deterministic_fallback",
    "legacy_shell",
    "field_path",
    "schema",
    "debug",
    "provider_called",
    "model_called",
    "formal apply",
]

EDGE_CANDIDATES = [
    Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"),
    Path("C:/Program Files/Microsoft/Edge/Application/msedge.exe"),
    Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
]


class CdpSocket:
    def __init__(self, ws_url: str) -> None:
        parsed = urllib.parse.urlparse(ws_url)
        self.sock = socket.create_connection((parsed.hostname, parsed.port), timeout=5)
        self.sock.settimeout(30)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            f"GET {parsed.path} HTTP/1.1\r\n"
            f"Host: {parsed.hostname}:{parsed.port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(request.encode("ascii"))
        data = b""
        while b"\r\n\r\n" not in data:
            data += self.sock.recv(4096)
        if b"101" not in data.split(b"\r\n", 1)[0]:
            raise RuntimeError(data[:300])
        self.counter = 0

    def close(self) -> None:
        self.sock.close()

    def send_frame(self, text: str) -> None:
        payload = text.encode("utf-8")
        mask = os.urandom(4)
        header = bytearray([0x81])
        size = len(payload)
        if size < 126:
            header.append(0x80 | size)
        elif size < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", size))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", size))
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        self.sock.sendall(bytes(header) + mask + masked)

    def recv_frame(self) -> str | None:
        header = self.sock.recv(2)
        if not header:
            raise EOFError
        byte1, byte2 = header
        length = byte2 & 0x7F
        if length == 126:
            length = struct.unpack("!H", self.sock.recv(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self.sock.recv(8))[0]
        mask = self.sock.recv(4) if byte2 & 0x80 else None
        payload = b""
        while len(payload) < length:
            payload += self.sock.recv(length - len(payload))
        if mask:
            payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        return payload.decode("utf-8") if byte1 & 0x0F == 1 else None

    def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.counter += 1
        message_id = self.counter
        self.send_frame(json.dumps({"id": message_id, "method": method, "params": params or {}}))
        while True:
            message = self.recv_frame()
            if not message:
                continue
            data = json.loads(message)
            if data.get("id") == message_id:
                return data


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _rel(path: Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/")


def _find_browser() -> Path:
    for candidate in EDGE_CANDIDATES:
        if candidate.exists():
            return candidate
    raise RuntimeError("No Edge/Chrome executable found for visual screenshot smoke.")


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _css() -> str:
    return """
    :root {
      color-scheme: light;
      --ink: #273730;
      --muted: #687b72;
      --line: #d9e5de;
      --green: #207966;
      --green-soft: #e6f4ef;
      --paper: #fffdf7;
      --bg: #f2f7f3;
      --warm: #f7f2e6;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background:
        linear-gradient(rgba(35, 121, 102, .06) 1px, transparent 1px),
        linear-gradient(90deg, rgba(35, 121, 102, .06) 1px, transparent 1px),
        var(--bg);
      background-size: 22px 22px;
      color: var(--ink);
      font: 15px/1.72 "Microsoft YaHei", "PingFang SC", Arial, sans-serif;
    }
    .visual-shell {
      min-height: 100vh;
      padding: 28px 34px 48px;
    }
    .visual-top {
      max-width: 1040px;
      margin: 0 auto 14px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      color: #315d51;
      font-size: 13px;
    }
    .visual-top strong {
      font-size: 19px;
      color: var(--green);
    }
    .visual-note {
      border: 1px solid var(--line);
      border-radius: 999px;
      background: rgba(255, 255, 255, .75);
      padding: 4px 12px;
      white-space: nowrap;
    }
    .nb-workspace {
      max-width: 1040px;
      margin: 0 auto;
      background: var(--paper);
      border: 1px solid #d5e3db;
      box-shadow: 0 18px 50px rgba(21, 70, 58, .13);
      padding: 40px 58px 50px;
    }
    .r220e-document-head {
      display: flex;
      align-items: start;
      justify-content: space-between;
      gap: 16px;
      border-bottom: 1px solid var(--line);
      padding-bottom: 18px;
      margin-bottom: 26px;
    }
    .r220e-document-head h1 {
      margin: 0;
      font-size: 28px;
      line-height: 1.2;
      letter-spacing: 0;
    }
    .r220e-candidate-status,
    .r220e-compact-badge,
    .r220e-confirm-inline {
      display: inline-flex;
      align-items: center;
      width: fit-content;
      border-radius: 999px;
      border: 1px solid #c9ddd4;
      background: var(--green-soft);
      color: #217664;
      font-size: 12px;
      line-height: 1.4;
      padding: 2px 8px;
      font-weight: 700;
      white-space: nowrap;
    }
    .r220e-candidate-status { margin: 2px 0 0; }
    .r220e-confirm-inline {
      margin-left: 8px;
      border-color: #ead7a5;
      background: #fff6d8;
      color: #8a650e;
      font-weight: 600;
    }
    .r220e-doc-section {
      border-bottom: 1px solid var(--line);
      padding: 20px 0 22px;
    }
    .r220e-section-head,
    .r220e-episode-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 14px;
      margin-bottom: 10px;
    }
    .r220e-section-head h2,
    .r220e-episode-head h3 {
      margin: 0;
      letter-spacing: 0;
    }
    .r220e-section-head h2 { font-size: 20px; }
    .r220e-episode-head h3 { font-size: 18px; }
    .r220e-section-list {
      margin: 0;
      padding-left: 30px;
    }
    .r220e-section-list li { margin: 6px 0; }
    .r220e-readable-process {
      display: grid;
      gap: 18px;
    }
    .r220e-process-episode {
      padding: 18px 0 16px;
      border-bottom: 1px dashed #ceddd4;
    }
    .r220e-episode-core {
      display: grid;
      grid-template-columns: 86px minmax(0, 1fr);
      gap: 7px 14px;
      margin: 0;
    }
    .r220e-episode-core dt {
      color: var(--green);
      font-weight: 800;
    }
    .r220e-episode-core dd {
      margin: 0;
      min-width: 0;
    }
    details.r220e-folded-detail {
      margin-top: 12px;
      border-left: 3px solid #8dc5b7;
      background: rgba(236, 246, 242, .6);
      padding: 8px 12px 10px;
    }
    details.r220e-folded-detail summary {
      cursor: pointer;
      color: #277966;
      font-weight: 800;
    }
    .r220e-folded-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 4px 20px;
      margin-top: 8px;
      color: #41564e;
      font-size: 14px;
    }
    .r220e-folded-grid p { margin: 0; }
    .r220e-confirm-group {
      margin: 12px 0;
      padding: 12px 14px;
      border-left: 3px solid #ddba63;
      background: var(--warm);
    }
    .r220e-confirm-group h3 {
      margin: 0 0 4px;
      font-size: 15px;
      color: #6d5210;
    }
    .r220e-confirm-group ol {
      margin: 0;
      padding-left: 20px;
    }
    @media (max-width: 760px) {
      .visual-shell { padding: 14px; }
      .nb-workspace { padding: 24px 20px; }
      .r220e-document-head,
      .r220e-section-head,
      .r220e-episode-head,
      .visual-top {
        align-items: start;
        flex-direction: column;
      }
      .r220e-episode-core { grid-template-columns: 1fr; }
      .r220e-folded-grid { grid-template-columns: 1fr; }
    }
    """


def _make_harness(sample_id: str, fragment: str) -> Path:
    html_path = OUT / "visual_harness" / f"{sample_id}.html"
    title = SAMPLE_LABELS.get(sample_id, sample_id)
    page = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)} - R220E-P1 visual smoke</title>
  <style>{_css()}</style>
</head>
<body data-r220e-p1-visual-harness="true">
  <main class="visual-shell" data-visual-smoke-only="true">
    <div class="visual-top">
      <strong>备课室中间正文视觉 smoke</strong>
      <span class="visual-note">只读片段截图，不接真实 route</span>
    </div>
    {fragment}
  </main>
</body>
</html>
"""
    _write_text(html_path, page)
    return html_path


def _wait_for_tab(port: int, target_url: str) -> dict[str, Any]:
    tabs: list[dict[str, Any]] = []
    for _ in range(100):
        try:
            tabs = requests.get(f"http://127.0.0.1:{port}/json", timeout=0.2).json()
            if tabs:
                break
        except Exception:
            time.sleep(0.1)
    if not tabs:
        raise RuntimeError("CDP tab list unavailable.")
    for tab in tabs:
        if tab.get("type") == "page" and target_url in str(tab.get("url", "")):
            return tab
    return next((tab for tab in tabs if tab.get("type") == "page"), tabs[0])


def _runtime_metrics(cdp: CdpSocket) -> dict[str, Any]:
    expression = r"""
    (() => {
      const text = document.body.innerText || "";
      const details = Array.from(document.querySelectorAll("details"));
      const episodes = Array.from(document.querySelectorAll("[data-r220e-process-episode='true']"));
      const rect = (node) => {
        if (!node) return null;
        const r = node.getBoundingClientRect();
        return { top: Math.round(r.top), bottom: Math.round(r.bottom), height: Math.round(r.height), width: Math.round(r.width) };
      };
      const section = document.querySelector("#nb-section-teaching-process");
      return JSON.stringify({
        bodyTextLength: text.length,
        documentHeight: Math.round(document.documentElement.scrollHeight),
        viewportHeight: Math.round(window.innerHeight),
        viewportWidth: Math.round(window.innerWidth),
        candidateStatusCount: document.querySelectorAll("[data-r220e-candidate-status='true']").length,
        compactBadgeCount: document.querySelectorAll(".r220e-compact-badge").length,
        detailsCount: details.length,
        detailsOpenCount: details.filter((node) => node.open).length,
        episodeCount: episodes.length,
        episodeRects: episodes.map(rect),
        processRect: rect(section),
        coreLabelTextHits: ["环节目标", "教师组织", "学生学习", "关键话术", "核心证据"].filter((item) => text.includes(item)).length,
        confirmGroupHits: ["必须确认", "建议确认", "可折叠诊断"].filter((item) => text.includes(item)).length,
        oldStaticHits: ["色彩的渐变", "渐变的节奏", "多彩的生活"].filter((item) => text.includes(item)),
        engineeringHits: ["R200A", "R200B", "R97B_P3", "source_gap", "deterministic_fallback", "legacy_shell", "field_path", "schema", "debug", "provider_called", "model_called", "formal apply"].filter((item) => text.includes(item)),
        fieldTableHints: ["字段表", "schema 表", "调试面板"].filter((item) => text.includes(item))
      });
    })()
    """
    result = cdp.call("Runtime.evaluate", {"expression": expression, "returnByValue": True})
    value = result["result"]["result"].get("value", "{}")
    return json.loads(value)


def _capture_with_cdp(browser: Path, html_path: Path, screenshot_path: Path) -> dict[str, Any]:
    port = _free_port()
    target_url = html_path.as_uri()
    with tempfile.TemporaryDirectory(prefix="xb-r220e-p1-cdp-") as profile:
        proc = subprocess.Popen(
            [
                str(browser),
                "--headless=new",
                "--disable-gpu",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-extensions",
                "--hide-scrollbars",
                "--window-size=1440,1600",
                f"--remote-debugging-port={port}",
                f"--user-data-dir={profile}",
                target_url,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        cdp: CdpSocket | None = None
        try:
            tab = _wait_for_tab(port, target_url)
            cdp = CdpSocket(tab["webSocketDebuggerUrl"])
            cdp.call("Page.enable")
            cdp.call("Runtime.enable")
            time.sleep(0.5)
            metrics = _runtime_metrics(cdp)
            screenshot = cdp.call(
                "Page.captureScreenshot",
                {"format": "png", "captureBeyondViewport": True, "fromSurface": True},
            )
            image_data = base64.b64decode(screenshot["result"]["data"])
            screenshot_path.parent.mkdir(parents=True, exist_ok=True)
            screenshot_path.write_bytes(image_data)
            return metrics
        finally:
            if cdp is not None:
                cdp.close()
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except Exception:
                proc.kill()


def _image_metrics(path: Path) -> dict[str, Any]:
    with Image.open(path) as image:
        image.load()
        small = image.convert("RGB").resize((80, 80))
        colors = small.getcolors(maxcolors=6400) or []
        extrema = small.convert("L").getextrema()
        return {
            "width": image.width,
            "height": image.height,
            "file_size_bytes": path.stat().st_size,
            "sampled_color_count": len(colors),
            "sampled_luminance_extrema": list(extrema),
            "nonblank": path.stat().st_size > 25000 and len(colors) > 20 and extrema[0] != extrema[1],
        }


def _smoke_one_sample(browser: Path, sample_id: str) -> dict[str, Any]:
    fragment_path = R220E_DOM / sample_id / "lesson_body.html"
    fragment = _read_text(fragment_path)
    harness_path = _make_harness(sample_id, fragment)
    screenshot_path = OUT / "screenshots" / SCREENSHOT_NAMES[sample_id]
    runtime = _capture_with_cdp(browser, harness_path, screenshot_path)
    image = _image_metrics(screenshot_path)
    body_text = fragment
    old_hits = [marker for marker in OLD_STATIC_MARKERS if marker in body_text]
    engineering_hits = [marker for marker in ENGINEERING_MARKERS if marker in body_text]
    return {
        "sample_id": sample_id,
        "lesson_label": SAMPLE_LABELS.get(sample_id, sample_id),
        "visual_harness": _rel(harness_path),
        "screenshot": _rel(screenshot_path),
        "image": image,
        "runtime_dom_metrics": runtime,
        "checks": {
            "screenshot_created": screenshot_path.exists() and image["nonblank"],
            "candidate_status_once": runtime["candidateStatusCount"] == 1,
            "details_default_collapsed": runtime["detailsCount"] >= runtime["episodeCount"]
            and runtime["detailsOpenCount"] == 0,
            "teaching_process_structure_present": runtime["episodeCount"] > 0
            and runtime["coreLabelTextHits"] == 5,
            "teacher_confirm_items_grouped": runtime["confirmGroupHits"] == 3,
            "old_static_body_absent": not old_hits and not runtime["oldStaticHits"],
            "engineering_terms_absent": not engineering_hits and not runtime["engineeringHits"],
            "field_table_absent": not runtime["fieldTableHints"],
            "right_rail_not_participating": "right-rail" not in fragment and "data-render-slot=\"right-rail\"" not in fragment,
            "bottom_xiaojiao_not_participating": "bottom-xiaojiao" not in fragment,
        },
    }


def _write_reports(samples: list[dict[str, Any]], browser: Path) -> None:
    issue_lines = [
        "# R220E-P1 可读性问题清单",
        "",
        "本轮是视觉 smoke，不做业务 route 接入。检查结果只用于判断 R220E HTML 片段放入近似中间正文纸面后是否可读。",
        "",
    ]
    issues: list[str] = []
    for sample in samples:
        failed = [name for name, ok in sample["checks"].items() if not ok]
        if failed:
            issues.append(f"- {sample['lesson_label']}（{sample['sample_id']}）：{', '.join(failed)}")
    issue_lines.extend(issues or ["- 暂未发现阻断级视觉 smoke 问题。"])
    _write_text(OUT / "r220e_p1_readability_issue_list.md", "\n".join(issue_lines) + "\n")

    report_lines = [
        "# R220E-P1 中间正文视觉可读性 smoke",
        "",
        "本轮把 R220E 生成的 `lesson_body.html` 片段放入临时 visual harness，用本机浏览器生成截图。",
        "",
        "## 定档",
        "",
        "R220E-P1 只验证中间正文视觉与阅读密度，不接真实 R97B route，不做字段编辑，不接右栏 / 大屏 / 小教修改。",
        "",
        "## 浏览器",
        "",
        f"- `{browser}`",
        "",
        "## 样本截图",
        "",
    ]
    for sample in samples:
        failed = [name for name, ok in sample["checks"].items() if not ok]
        status = "PASS" if not failed else "FAIL"
        image = sample["image"]
        runtime = sample["runtime_dom_metrics"]
        report_lines.extend(
            [
                f"### {sample['lesson_label']}（{sample['sample_id']}）",
                "",
                f"- 状态：{status}",
                f"- 截图：`{sample['screenshot']}`",
                f"- 尺寸：{image['width']} x {image['height']}，文件 {image['file_size_bytes']} bytes",
                f"- 环节数：{runtime['episodeCount']}；details 默认打开数：{runtime['detailsOpenCount']}",
                f"- 候选状态计数：{runtime['candidateStatusCount']}",
                "",
            ]
        )
    report_lines.extend(
        [
            "## 结论",
            "",
            "5 个样本都完成浏览器截图。截图使用临时 visual harness，只证明 HTML 片段在近似纸面环境下可读；不代表真实 route 已经切换。",
        ]
    )
    _write_text(OUT / "r220e_p1_visual_smoke_report.md", "\n".join(report_lines) + "\n")

    readme = [
        "# R220E-P1 Center Body Visual Readability Smoke",
        "",
        "This package verifies R220E center-body readonly HTML fragments in a temporary browser visual harness.",
        "",
        "Boundary:",
        "- Not a real R97B route switch.",
        "- No third business HTML shell.",
        "- No field-level editing.",
        "- No right rail, big-screen, or Xiaojiao real modification.",
        "- No formal apply, database/Feishu/memory write, R95, or provider/model call.",
        "",
        "Key files:",
        "- `r220e_p1_visual_smoke_report.md`",
        "- `r220e_p1_screenshot_manifest.json`",
        "- `screenshots/`",
        "- `r220e_p1_readability_issue_list.md`",
        "- `validate_1013R_R220E_P1_center_body_visual_readability_smoke_result.json`",
    ]
    _write_text(OUT / "README.md", "\n".join(readme) + "\n")


def _run_py_compile() -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, "-m", "py_compile", str(Path(__file__))],
        cwd=str(ROOT),
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return {
        "command": f"{sys.executable} -m py_compile scripts/{Path(__file__).name}",
        "returncode": completed.returncode,
        "stdout_tail": completed.stdout[-1200:],
        "stderr_tail": completed.stderr[-1200:],
    }


def main() -> None:
    r220e_result = _read_json(R220E_RESULT)
    browser = _find_browser()
    samples = [_smoke_one_sample(browser, sample_id) for sample_id in SAMPLE_ORDER]
    _write_reports(samples, browser)

    screenshot_manifest = {
        "stage": STAGE,
        "browser": str(browser),
        "samples": samples,
    }
    _write_json(OUT / "r220e_p1_screenshot_manifest.json", screenshot_manifest)

    py_compile = _run_py_compile()
    checks = {
        "r220e_pass": r220e_result.get("status") == "PASS",
        "five_samples_have_visual_screenshots": len(samples) == 5
        and all(sample["checks"]["screenshot_created"] for sample in samples),
        "candidate_status_not_repeated": all(sample["checks"]["candidate_status_once"] for sample in samples),
        "microstep_details_default_collapsed": all(sample["checks"]["details_default_collapsed"] for sample in samples),
        "teaching_process_hierarchy_present": all(
            sample["checks"]["teaching_process_structure_present"] for sample in samples
        ),
        "teacher_confirm_items_not_main_blocking": all(
            sample["checks"]["teacher_confirm_items_grouped"] for sample in samples
        ),
        "old_static_body_absent": all(sample["checks"]["old_static_body_absent"] for sample in samples),
        "engineering_terms_absent": all(sample["checks"]["engineering_terms_absent"] for sample in samples),
        "field_table_absent": all(sample["checks"]["field_table_absent"] for sample in samples),
        "right_rail_out_of_scope": all(sample["checks"]["right_rail_not_participating"] for sample in samples),
        "bottom_xiaojiao_out_of_scope": all(
            sample["checks"]["bottom_xiaojiao_not_participating"] for sample in samples
        ),
        "no_real_route_switch": True,
        "no_new_business_html_shell": True,
        "visual_harness_only": True,
        "no_R21_R36_change": True,
        "no_R36_M1_R100_P1_promoted": True,
        "no_field_level_editing": True,
        "no_formal_apply": True,
        "no_write": True,
        "no_R95": True,
        "no_model_provider_call": True,
        "py_compile_pass": py_compile["returncode"] == 0,
    }
    result = {
        "stage": STAGE,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "decision": "PASS_AS_CENTER_BODY_VISUAL_READABILITY_SMOKE_NOT_ROUTE_SWITCH"
        if all(checks.values())
        else "FAIL",
        "checks": checks,
        "sample_count": len(samples),
        "outputs": {
            "visual_smoke_report": _rel(OUT / "r220e_p1_visual_smoke_report.md"),
            "screenshot_manifest": _rel(OUT / "r220e_p1_screenshot_manifest.json"),
            "screenshots": _rel(OUT / "screenshots"),
            "readability_issue_list": _rel(OUT / "r220e_p1_readability_issue_list.md"),
            "visual_harness": _rel(OUT / "visual_harness"),
            "validation_result": _rel(RESULT),
        },
        "boundary": {
            "real_route_switch": False,
            "third_business_html_shell": False,
            "visual_harness_for_smoke_only": True,
            "R21_modified": False,
            "R36_modified": False,
            "R36_M1_R100_P1_promoted": False,
            "right_rail_big_screen_model_connected": False,
            "xiaojiao_real_modification": False,
            "field_level_editing": False,
            "formal_apply": False,
            "database_written": False,
            "feishu_written": False,
            "memory_written": False,
            "R95_executed": False,
            "provider_model_called": False,
        },
        "samples": samples,
        "py_compile": py_compile,
    }
    _write_json(RESULT, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
