#!/usr/bin/env python3
"""SandikRadar yerel koprusu — FastAPI/pip GEREKTIRMEZ (sadece standart kutuphane).

Ne yapar:
  * Paneli (docs/) bu porttan servis eder  -> http://127.0.0.1:8800
  * /api/rooms, /api/config, /api/health, /api/stats  (GitHub Pages paneliyle ayni sozlesme)
  * /api/live/check  -> TikTok'a gercekten yayinda mi diye sorar (imzasiz, anahtarsiz)
  * /api/alerts + /api/alerts/test -> Telegram uyarilari (sunucu tarafinda)
  * /api/stream -> SSE: yeni oda olaylari
  * DEMO modunda veriyi canli uretir; gercek modda collector'in yazdigi
    docs/data/rooms.json dosyasini servis eder.

Kullanim:
    python local-server/bridge.py                # http://127.0.0.1:8800
    BRIDGE_PORT=9000 python local-server/bridge.py
    DATA_PROVIDER=sim python local-server/bridge.py     # varsayilan davranis
    DATA_PROVIDER=file python local-server/bridge.py    # sadece rooms.json
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
DATA_DIR = DOCS / "data"
ALERTS_FILE = ROOT / "data" / "alerts.json"
sys.path.insert(0, str(ROOT / "collector"))
import livecore as L  # noqa: E402

PORT = int(os.environ.get("BRIDGE_PORT", "8800"))
HOST = os.environ.get("BRIDGE_HOST", "127.0.0.1")
REFRESH = max(5, int(os.environ.get("BRIDGE_REFRESH", "20")))
PROVIDER = (os.environ.get("DATA_PROVIDER") or "sim").strip().lower()
if PROVIDER not in ("sim", "file", "euler", "auto"):
    PROVIDER = "sim"

DEFAULT_ALERTS = {"enabled": False, "bot_token": "", "chat_id": "", "min_ratio": 3,
                  "min_coins": 100000, "kinds": ["chest", "bag"], "cooldown_seconds": 90}

STATE: dict = {"rooms": [], "updated_at": 0, "provider": "sim", "demo": True,
               "error": "", "notice": "", "stale": False, "generated_at": 0}
LOCK = threading.Lock()
SENT: dict[str, float] = {}
SUBSCRIBERS: list = []


# --------------------------------------------------------------------- yardimci
def log(msg: str) -> None:
    print(f"[bridge] {msg}", flush=True)


def load_alerts() -> dict:
    if ALERTS_FILE.exists():
        try:
            return {**DEFAULT_ALERTS, **json.loads(ALERTS_FILE.read_text("utf-8"))}
        except Exception:
            pass
    return dict(DEFAULT_ALERTS)


def save_alerts(cfg: dict) -> dict:
    ALERTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    merged = {**DEFAULT_ALERTS, **{k: v for k, v in cfg.items() if k in DEFAULT_ALERTS}}
    ALERTS_FILE.write_text(json.dumps(merged, ensure_ascii=False, indent=2), "utf-8")
    return merged


def publish(event: dict) -> None:
    for queue in list(SUBSCRIBERS):
        try:
            queue.append(event)
        except Exception:
            pass


# ------------------------------------------------------------------ veri dongusu
def read_file_snapshot() -> dict | None:
    path = DATA_DIR / "rooms.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text("utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def refresh_loop() -> None:
    known: set[str] = set()
    while True:
        try:
            now = int(time.time() * 1000)
            mode = PROVIDER
            if mode == "auto":
                mode = "file" if read_file_snapshot() else "sim"

            if mode in ("sim",):
                rooms = L.sim_rooms(now)
                snap = {"provider": "sim", "demo": True, "rooms": rooms, "updated_at": now,
                        "generated_at": now, "stale": False, "error": "",
                        "notice": "DEMO veri — gerçek TikTok yayını değil."}
            else:
                data = read_file_snapshot()
                if data:
                    rooms = L.snapshot([r for r in (data.get("rooms") or []) if isinstance(r, dict)], now)
                    snap = {"provider": data.get("provider") or "file", "demo": bool(data.get("demo")),
                            "rooms": rooms, "updated_at": now,
                            "generated_at": int(data.get("generated_at") or 0),
                            "stale": bool(data.get("stale")), "error": data.get("error") or "",
                            "notice": data.get("notice") or ""}
                else:
                    rooms = []
                    snap = {"provider": "file", "demo": False, "rooms": [], "updated_at": now,
                            "generated_at": 0, "stale": True, "error": "rooms.json yok",
                            "notice": "python collector/collect.py çalıştır"}

            with LOCK:
                STATE.update(snap)
                STATE["tab_counts"] = L.tab_counts(rooms)

            new = [r for r in rooms if r.get("id") and r["id"] not in known]
            known = {r["id"] for r in rooms if r.get("id")}
            for room in new[:30]:
                publish({"type": "new_room", "room": room})
            publish({"type": "snapshot", "count": len(rooms), "at": now})
            send_alerts(new)
        except Exception as exc:  # dongu asla olmesin
            with LOCK:
                STATE["error"] = f"{type(exc).__name__}: {exc}"
            log(f"refresh hatasi: {exc}")
        time.sleep(REFRESH)


def send_alerts(rooms: list[dict]) -> None:
    cfg = load_alerts()
    if not cfg.get("enabled") or not cfg.get("bot_token") or not cfg.get("chat_id"):
        return
    cooldown = float(cfg.get("cooldown_seconds") or 90)
    for room in rooms:
        if not L.matches(room, cfg):
            continue
        last = SENT.get(room["id"], 0)
        if time.time() - last < cooldown:
            continue
        ok, _ = L.send_telegram(cfg["bot_token"], cfg["chat_id"], L.format_alert(room))
        if ok:
            SENT[room["id"]] = time.time()
            log(f"telegram: @{room.get('user')} {room.get('coins')} jeton")


# -------------------------------------------------------------------- HTTP katmani
MIME = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
        ".js": "text/javascript; charset=utf-8", ".json": "application/json; charset=utf-8",
        ".svg": "image/svg+xml", ".webmanifest": "application/manifest+json",
        ".png": "image/png", ".ico": "image/x-icon", ".txt": "text/plain; charset=utf-8"}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "SandikRadarBridge/" + L.VERSION

    # ------------------------------------------------------------ yardimcilar
    def _json(self, payload, code: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.send_header("cache-control", "no-store")
        self.send_header("access-control-allow-origin", "*")
        self.send_header("access-control-allow-private-network", "true")
        self.end_headers()
        self.wfile.write(body)

    def _cors(self) -> None:
        self.send_header("access-control-allow-origin", "*")
        self.send_header("access-control-allow-headers",
                         self.headers.get("access-control-request-headers") or "content-type")
        self.send_header("access-control-allow-methods", "GET, POST, OPTIONS")
        # Chrome Private Network Access: HTTPS sayfadan 127.0.0.1'e istek için şart
        self.send_header("access-control-allow-private-network", "true")
        self.send_header("access-control-max-age", "600")

    def _body(self) -> dict:
        try:
            length = int(self.headers.get("content-length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            data = json.loads(raw.decode("utf-8", "replace") or "{}")
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def log_message(self, fmt: str, *args) -> None:  # sessiz: gurultu yapmayalim
        pass

    # ---------------------------------------------------------------- yonlendirme
    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self._cors()
        self.send_header("content-length", "0")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        path, query = parsed.path, urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        params = {k: v[0] for k, v in query.items()}

        if path == "/api/health":
            with LOCK:
                return self._json({"ok": True, "provider": STATE["provider"], "demo": STATE["demo"],
                                   "rooms": len(STATE["rooms"]), "updated_at": STATE["updated_at"],
                                   "server_time": int(time.time() * 1000), "bridge": True})
        if path == "/api/config":
            with LOCK:
                return self._json({"app": L.APP, "version": L.VERSION, "provider": STATE["provider"],
                                   "demo": STATE["demo"], "refresh_seconds": REFRESH,
                                   "tabs": L.TABS, "languages": [
                                       {"code": "tr", "label": "Türkçe"},
                                       {"code": "en", "label": "English"},
                                       {"code": "vi", "label": "Tiếng Việt"}]})
        if path == "/api/rooms":
            with LOCK:
                rooms = list(STATE["rooms"])
                updated = STATE["updated_at"]
                provider, stale = STATE["provider"], STATE["stale"]
            data = L.apply_filters(rooms, params)
            counts = {}
            for tab in L.TABS:
                counts[tab["id"]] = len(L.apply_filters(rooms, {**params, **(tab.get("filter") or {})}))
            return self._json({"count": len(data), "total": len(rooms), "updated_at": updated,
                               "generated_at": STATE.get("generated_at") or 0,
                               "provider": provider, "demo": STATE.get("demo", False),
                               "stale": stale, "error": STATE.get("error", ""),
                               "notice": STATE.get("notice", ""),
                               "tabs": L.TABS, "tab_counts": counts, "rooms": data})
        if path == "/api/stats":
            with LOCK:
                rooms = list(STATE["rooms"])
            by_kind = {"chest": 0, "bag": 0}
            for room in rooms:
                k = room.get("kind", "chest")
                by_kind[k] = by_kind.get(k, 0) + 1
            with LOCK:
                return self._json({"provider": STATE["provider"], "rooms": len(rooms), "by_kind": by_kind,
                                   "updated_at": STATE["updated_at"], "refresh_seconds": REFRESH,
                                   "errors": 1 if STATE.get("error") else 0})
        if path == "/api/live/check":
            q = (params.get("q") or "").strip()
            if not q:
                return self._json({"ok": False, "error": "q parametresi bos"}, 400)
            try:
                info = L.check_live(q)
            except ValueError as exc:
                return self._json({"ok": False, "error": str(exc)}, 400)
            except Exception as exc:
                return self._json({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, 500)
            return self._json({"ok": True, **info})
        if path == "/api/alerts":
            cfg = load_alerts()
            cfg["bot_token"] = "***" if cfg.get("bot_token") else ""
            return self._json(cfg)
        if path == "/api/stream":
            return self._stream()
        if path.startswith("/api/"):
            return self._json({"ok": False, "error": "bilinmeyen uç"}, 404)

        return self._static(path)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        body = self._body()

        if path == "/api/alerts":
            current = load_alerts()
            if body.get("bot_token") in (None, "", "***"):
                body.pop("bot_token", None)
            cfg = save_alerts({**current, **body})
            return self._json({"ok": True, "enabled": cfg["enabled"]})
        if path == "/api/alerts/test":
            cfg = {**load_alerts(), **{k: v for k, v in body.items() if v not in (None, "", "***")}}
            text = body.get("text") or "✅ <b>SandıkRadar</b> test bildirimi — yerel köprü çalışıyor."
            ok, detail = L.send_telegram(cfg.get("bot_token", ""), cfg.get("chat_id", ""), text)
            return self._json({"ok": ok, "detail": detail}, 200 if ok else 400)
        if path == "/api/mode":
            return self._json({"ok": False, "error": "mod değişimi ortam değişkeniyle yapılır "
                                                    "(DATA_PROVIDER=sim|file)"}, 400)
        return self._json({"ok": False, "error": "bilinmeyen uç"}, 404)

    # -------------------------------------------------------------------- SSE
    def _stream(self) -> None:
        self.close_connection = True
        self.send_response(200)
        self.send_header("content-type", "text/event-stream; charset=utf-8")
        self.send_header("cache-control", "no-cache")
        self.send_header("connection", "close")
        self.send_header("access-control-allow-origin", "*")
        self.end_headers()
        queue: list = []
        SUBSCRIBERS.append(queue)
        try:
            self.wfile.write(b"event: hello\ndata: {\"bridge\":true}\n\n")
            self.wfile.flush()
            last = time.time()
            while time.time() - last < 300:          # 5 dk sonra kapan, panel yeniden baglanir
                if queue:
                    event = queue.pop(0)
                    payload = json.dumps(event, ensure_ascii=False)
                    self.wfile.write(f"event: {event.get('type', 'message')}\ndata: {payload}\n\n".encode("utf-8"))
                else:
                    self.wfile.write(b": keep-alive\n\n")
                self.wfile.flush()
                last = time.time()
                time.sleep(5)
        except Exception:
            pass
        finally:
            if queue in SUBSCRIBERS:
                SUBSCRIBERS.remove(queue)

    # ------------------------------------------------------------ statik dosya
    def _static(self, path: str) -> None:
        rel = urllib.parse.unquote(path).lstrip("/") or "index.html"
        target = (DOCS / rel).resolve()
        try:
            target.relative_to(DOCS.resolve())
        except ValueError:
            return self._json({"ok": False, "error": "yasak yol"}, 403)
        if target.is_dir():
            target = target / "index.html"
        if not target.exists() or not target.is_file():
            # SPA benzeri: bilinmeyen yol -> index
            target = DOCS / "index.html"
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("content-type", MIME.get(target.suffix.lower(), "application/octet-stream"))
        self.send_header("content-length", str(len(body)))
        self.send_header("cache-control", "no-store" if target.name == "rooms.json" else "no-cache")
        self.end_headers()
        self.wfile.write(body)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass
    threading.Thread(target=refresh_loop, daemon=True).start()
    time.sleep(0.4)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    log(f"hazır → http://{HOST}:{PORT}  (mod: {PROVIDER}, yenileme: {REFRESH}s)")
    log("panel: aynı adres. Kapatmak için Ctrl+C.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log("kapatıldı")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
