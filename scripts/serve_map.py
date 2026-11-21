#!/usr/bin/env python3
"""
Local same-origin server + streaming LLM proxy for interactive-code-map HTMLs.

Zero third-party dependencies (Python 3 stdlib only). Bound strictly to 127.0.0.1.

Modes:
  1. Launch viewer + proxy:
       python serve_map.py <path-to-html> [--port 18765] [--no-browser]
  2. Emit Windows double-click .bat launcher next to the HTML:
       python serve_map.py --emit-bat <path-to-html> [--bat-out <path-to-bat>]
"""

from __future__ import annotations

import argparse
import functools
import http.server
import json
import os
import pathlib
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

DEFAULT_PORT = 18765
PORT_SCAN_LIMIT = 50
UPSTREAM_TIMEOUT_SEC = 120


def norm_path_str(p: pathlib.Path) -> str:
    return os.path.normcase(os.path.abspath(str(p.resolve())))


def emit_bat_launcher(html_path: pathlib.Path, bat_out: pathlib.Path | None) -> pathlib.Path:
    if not html_path.is_file():
        raise FileNotFoundError(f"HTML file not found: {html_path}")

    resolved_html = html_path.resolve()
    target_bat = (bat_out.resolve() if bat_out else resolved_html.parent / f"{resolved_html.stem}-AI导师.bat")
    target_bat.parent.mkdir(parents=True, exist_ok=True)

    script_abs = str(pathlib.Path(__file__).resolve())
    if norm_path_str(target_bat.parent) == norm_path_str(resolved_html.parent):
        target_expr = f"%~dp0{resolved_html.name}"
    else:
        try:
            rel = os.path.relpath(str(resolved_html), str(target_bat.parent))
            target_expr = f"%~dp0{rel}"
        except ValueError:
            target_expr = str(resolved_html)

    lines = [
        "@echo off",
        "chcp 65001 >nul",
        "setlocal",
        'set "PYTHONUTF8=1"',
        f'set "SCRIPT={script_abs}"',
        f'set "TARGET={target_expr}"',
        'if not exist "%SCRIPT%" goto :missing_script',
        'if not exist "%TARGET%" goto :missing_target',
        "where python >nul 2>nul",
        "if not errorlevel 1 goto :run_python",
        "where py >nul 2>nul",
        "if not errorlevel 1 goto :run_py",
        "echo [ERROR] Python 3 not found on PATH.",
        "pause",
        "exit /b 1",
        ":run_python",
        'python "%SCRIPT%" "%TARGET%"',
        "goto :done",
        ":run_py",
        'py -3 "%SCRIPT%" "%TARGET%"',
        ":done",
        'set "RC=%errorlevel%"',
        'if not "%RC%"=="0" pause',
        "exit /b %RC%",
        ":missing_script",
        'echo [ERROR] serve_map.py not found: "%SCRIPT%"',
        "pause",
        "exit /b 1",
        ":missing_target",
        'echo [ERROR] Target HTML not found: "%TARGET%"',
        "pause",
        "exit /b 1",
    ]
    content = "\r\n".join(lines) + "\r\n"
    # Strictly UTF-8 WITHOUT BOM so cmd.exe never trips on @echo off
    with open(target_bat, "w", encoding="utf-8", newline="") as f:
        f.write(content)
    return target_bat


def probe_existing_server(port: int, html_path: pathlib.Path) -> bool:
    url = f"http://127.0.0.1:{port}/__llm_proxy__/health"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(urllib.request.Request(url, method="GET"), timeout=1.0) as resp:
            if resp.status != 200:
                return False
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
            if not isinstance(data, dict) or not data.get("ok"):
                return False
            existing = data.get("filePath")
            if not existing:
                return False
            return norm_path_str(pathlib.Path(existing)) == norm_path_str(html_path)
    except Exception:
        return False


def is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.25)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def build_upstream_opener(endpoint: str) -> urllib.request.OpenerDirector:
    parsed = urllib.parse.urlsplit(endpoint)
    host = (parsed.hostname or "").lower()
    is_local = host in ("127.0.0.1", "localhost", "::1") or host.startswith("127.")
    if is_local or (host and urllib.request.proxy_bypass(host)):
        return urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return urllib.request.build_opener()


class LoopbackThreadingServer(http.server.ThreadingHTTPServer):
    allow_reuse_address = False
    daemon_threads = True


class CodeMapHandler(http.server.BaseHTTPRequestHandler):
    def __init__(self, *args, html_path: pathlib.Path, **kwargs):
        self.html_path = html_path
        super().__init__(*args, **kwargs)

    def log_message(self, format: str, *args) -> None:
        # Keep stdout clean; proxy status is logged explicitly on POST /__llm_proxy__
        return

    def _send_bytes(self, status: int, content_type: str, body: bytes, no_store: bool = True) -> None:
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            if no_store:
                self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            if body:
                self.wfile.write(body)
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _send_json(self, status: int, data: dict) -> None:
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self._send_bytes(status, "application/json; charset=utf-8", raw, no_store=True)

    def do_GET(self) -> None:
        req_path = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path)

        if req_path == "/__llm_proxy__/health":
            self._send_json(
                200,
                {
                    "ok": True,
                    "mode": "local-proxy",
                    "version": "3.1",
                    "file": self.html_path.name,
                    "filePath": str(self.html_path),
                },
            )
            return

        if req_path == "/favicon.ico":
            self._send_bytes(204, "image/x-icon", b"", no_store=True)
            return

        if req_path in ("/", "/index.html", f"/{self.html_path.name}"):
            try:
                html_bytes = self.html_path.read_text(encoding="utf-8").encode("utf-8")
            except OSError as exc:
                self._send_json(500, {"error": {"message": f"无法读取 HTML 文件：{exc}"}})
                return
            self._send_bytes(200, "text/html; charset=utf-8", html_bytes, no_store=True)
            return

        self._send_json(404, {"error": {"message": f"Not found: {req_path}"}})

    def do_POST(self) -> None:
        req_path = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path)
        if req_path != "/__llm_proxy__":
            self._send_json(404, {"error": {"message": f"Not found: {req_path}"}})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json(400, {"error": {"message": "Invalid Content-Length"}})
            return

        if length <= 0:
            self._send_json(400, {"error": {"message": "Empty request body"}})
            return

        try:
            raw_req = self.rfile.read(length)
            req_obj = json.loads(raw_req.decode("utf-8"))
        except Exception as exc:
            self._send_json(400, {"error": {"message": f"Invalid JSON request: {exc}"}})
            return

        if not isinstance(req_obj, dict):
            self._send_json(400, {"error": {"message": "Request body must be a JSON object"}})
            return

        endpoint = req_obj.get("endpoint")
        api_key = req_obj.get("apiKey") or ""
        payload = req_obj.get("payload")

        if not isinstance(endpoint, str) or not endpoint.strip():
            self._send_json(400, {"error": {"message": "Missing upstream endpoint"}})
            return

        endpoint = endpoint.strip()
        parsed = urllib.parse.urlsplit(endpoint)
        if parsed.scheme.lower() not in ("http", "https") or not parsed.netloc:
            self._send_json(400, {"error": {"message": f"Unsupported endpoint URL: {endpoint}"}})
            return

        if not isinstance(payload, dict):
            self._send_json(400, {"error": {"message": "Missing JSON payload object"}})
            return

        headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream, application/json",
            "Accept-Encoding": "identity",
        }
        if isinstance(api_key, str) and api_key.strip():
            headers["Authorization"] = f"Bearer {api_key.strip()}"

        body_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        upstream_req = urllib.request.Request(endpoint, data=body_bytes, headers=headers, method="POST")
        opener = build_upstream_opener(endpoint)
        want_stream = bool(payload.get("stream"))

        try:
            upstream_resp = opener.open(upstream_req, timeout=UPSTREAM_TIMEOUT_SEC)
        except urllib.error.HTTPError as exc:
            err_body = exc.read()
            err_ctype = (exc.headers.get("Content-Type") if exc.headers else None) or "application/json; charset=utf-8"
            print(f"[proxy] POST {endpoint} -> {exc.code}", flush=True)
            self._send_bytes(exc.code, err_ctype, err_body, no_store=True)
            return
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            print(f"[proxy] POST {endpoint} -> 502 ({reason})", flush=True)
            self._send_json(
                502,
                {"error": {"message": f"本地代理无法连接上游地址 {endpoint}：{reason}"}},
            )
            return

        try:
            status = getattr(upstream_resp, "status", 200)
            ctype = upstream_resp.headers.get("Content-Type") or (
                "text/event-stream; charset=utf-8" if want_stream else "application/json; charset=utf-8"
            )
            print(f"[proxy] POST {endpoint} -> {status}", flush=True)

            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()

            if want_stream or "text/event-stream" in ctype.lower():
                while True:
                    line = upstream_resp.readline()
                    if not line:
                        break
                    self.wfile.write(line)
                    self.wfile.flush()
            else:
                while True:
                    chunk = upstream_resp.read(4096)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            try:
                upstream_resp.close()
            except Exception:
                pass


def serve_html(html_path: pathlib.Path, base_port: int, open_browser: bool) -> int:
    if not html_path.is_file():
        print(f"[ERROR] HTML file not found: {html_path}", file=sys.stderr)
        return 1

    resolved = html_path.resolve()
    handler_cls = functools.partial(CodeMapHandler, html_path=resolved)
    server: LoopbackThreadingServer | None = None
    chosen_port: int | None = None

    for port in range(base_port, base_port + PORT_SCAN_LIMIT + 1):
        if probe_existing_server(port, resolved):
            url = f"http://127.0.0.1:{port}/"
            print(f"[serve_map] 已检测到同文件本地服务正在运行：{url}", flush=True)
            if open_browser:
                webbrowser.open(url)
            return 0
        if is_port_in_use(port):
            continue
        try:
            server = LoopbackThreadingServer(("127.0.0.1", port), handler_cls)
            chosen_port = port
            break
        except OSError:
            continue

    if server is None or chosen_port is None:
        print(
            f"[ERROR] 无法在 127.0.0.1:{base_port}..{base_port + PORT_SCAN_LIMIT} 上找到可用端口。",
            file=sys.stderr,
        )
        return 1

    url = f"http://127.0.0.1:{chosen_port}/"
    print("============================================================", flush=True)
    print(f"  Interactive Code Map v3.1 本地工作台已启动（无 CORS 限制）", flush=True)
    print(f"  页面地址：{url}", flush=True)
    print(f"  源码导图：{resolved}", flush=True)
    print("  提示：保持本窗口运行即可在浏览器使用 AI 源码导师；按 Ctrl+C 停止。", flush=True)
    print("============================================================", flush=True)

    if open_browser:
        webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[serve_map] 已停止本地服务。", flush=True)
    finally:
        server.server_close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Serve interactive-code-map HTML with a local same-origin streaming LLM proxy."
    )
    parser.add_argument("html", type=pathlib.Path, help="Path to generated interactive-code-map HTML")
    parser.add_argument(
        "--emit-bat",
        action="store_true",
        help="Generate a Windows double-click .bat launcher instead of starting the server",
    )
    parser.add_argument(
        "--bat-out",
        type=pathlib.Path,
        default=None,
        help="Optional output path for .bat launcher (defaults to <stem>-AI导师.bat beside HTML)",
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Starting loopback port (default: {DEFAULT_PORT})")
    parser.add_argument("--no-browser", action="store_true", help="Do not auto-open the system browser")
    args = parser.parse_args()

    if args.emit_bat:
        try:
            bat_path = emit_bat_launcher(args.html, args.bat_out)
        except OSError as exc:
            print(f"[ERROR] 生成启动脚本失败：{exc}", file=sys.stderr)
            return 1
        print(f"[OK] Generated launcher: {bat_path}", flush=True)
        return 0

    return serve_html(args.html, args.port, not args.no_browser)


if __name__ == "__main__":
    sys.exit(main())
