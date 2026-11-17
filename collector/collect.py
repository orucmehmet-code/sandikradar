#!/usr/bin/env python3
"""SandikRadar veri iscisi — GitHub Actions (ya da yerel) tarafindan calistirilir.

Kullanim:
    python collector/collect.py                      # otomatik mod
    python collector/collect.py --provider sim       # DEMO veri
    python collector/collect.py --provider euler --seconds 150

Ortam degiskenleri:
    EULER_API_KEY     EulerStream Business anahtari (yoksa DEMO)
    EULER_REGIONS     TR,VN  (varsayilan TR)
    WATCHLIST         @hesap1,@hesap2 — feed olmadan da dinlenecek hesaplar
    MAX_ROOMS         ayni anda dinlenecek oda sayisi (varsayilan 12)
    DATA_PROVIDER     sim | euler | auto
    OUT_DIR           cikti klasoru (varsayilan docs/data)

Cikti:  docs/data/rooms.json  (+ meta.json)
Cikis kodu her zaman 0'dir; durum/hatalar meta.json icine yazilir ki gecici
TikTok/Euler sorunlari Actions isini kirmizi yakmasin.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import livecore as L  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "docs" / "data"


def log(msg: str) -> None:
    print(f"[collect] {msg}", flush=True)


def env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def parse_list(value: str) -> list[str]:
    return [p.strip() for p in (value or "").replace(";", ",").split(",") if p.strip()]


def watchlist_file() -> list[str]:
    """`data/watchlist.txt` — WATCHLIST ortam degiskeni bossa buradan okunur.

    Bir satir bir hesap: `@hesap`, `hesap` ya da `tiktok.com/@hesap/live` linki.
    `#` ile baslayan satirlar ve bos satirlar yok sayilir.
    """
    path = ROOT / "data" / "watchlist.txt"
    if not path.exists():
        return []
    out: list[str] = []
    try:
        for raw in path.read_text("utf-8", "replace").splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            for part in line.replace(";", ",").split(","):
                part = part.strip()
                if not part:
                    continue
                m = re.search(r"tiktok\.com/@([A-Za-z0-9._]+)", part, re.I)
                out.append(("@" + m.group(1)) if m else part)
    except Exception as exc:
        log(f"watchlist.txt okunamadi: {type(exc).__name__}")
    return out


# --------------------------------------------------------------- euler yakalama
def _gift_fields(event) -> dict:
    """TikTokLive GiftEvent -> jeton alanlari (kutuphane surumleri arasinda esnek).

    `diamond_count` bazi surumlerde `gift.diamonds`, bazi protokollerde
    `diamondCount` olarak gelir; hepsi denenir. Combo hediyede `repeat_count`
    artarak gelir, gercek sayim GiftFlow icinde fark uzerinden yapilir.
    """
    gift = getattr(event, "gift", None)
    user = getattr(event, "user", None)

    diamonds = 0
    for src in (gift, event):
        if src is None:
            continue
        for attr in ("diamond_count", "diamondCount", "diamonds"):
            val = getattr(src, attr, None)
            if val in (None, ""):
                continue
            try:
                diamonds = int(val)
            except (TypeError, ValueError):
                diamonds = 0
            if diamonds:
                break
        if diamonds:
            break

    gift_id = ""
    gift_name = ""
    for src in (gift, event):
        if src is None:
            continue
        gift_id = gift_id or str(getattr(src, "id", "") or getattr(src, "gift_id", "") or "")
        gift_name = gift_name or str(getattr(src, "name", "") or "")

    sender = ""
    nickname = ""
    if user is not None:
        sender = str(getattr(user, "unique_id", "") or getattr(user, "uniqueId", "")
                     or getattr(user, "user_id", "") or getattr(user, "id", "") or "")
        nickname = str(getattr(user, "nickname", "") or "")

    try:
        repeat_count = int(getattr(event, "repeat_count", 0) or getattr(event, "repeatCount", 0) or 0)
    except (TypeError, ValueError):
        repeat_count = 0
    repeat_end = bool(getattr(event, "repeat_end", True))

    return {
        "user": sender.lstrip("@"),
        "nickname": nickname,
        "gift_id": gift_id,
        "gift_name": gift_name,
        "diamonds": diamonds,
        "repeat_count": repeat_count,
        "repeat_end": repeat_end,
    }


def _envelope_fields(info, meta: dict) -> dict:
    return {
        "envelope_id": str(getattr(info, "envelope_id", "") or ""),
        "room_id": str(getattr(info, "room_id", "") or meta.get("room_id") or ""),
        "diamond_count": int(getattr(info, "diamond_count", 0) or 0),
        "people_count": int(getattr(info, "people_count", 0) or 0),
        "unpack_at": int(getattr(info, "unpack_at", 0) or 0),
        "skin_id": int(getattr(info, "skin_id", 0) or 0),
    }


async def _capture(api_key: str, regions: list[str], watchlist: list[str],
                   seconds: int, max_rooms: int) -> tuple[list[dict], str]:
    """Feed ile hedef odalari bul; hediyelerden jeton akisi, zarf gelirse sandik cikar.

    Mantik: her dinlenen odada GiftEvent'ler jeton akisina (kind='live') yazilir.
    Sandik yalnizca EnvelopeEvent yakalanirsa listeye girer (kind='chest'); ayni
    odanin akis satiri da `envelope_id` ile "sandik var" olarak isaretlenir.

    Sirasi onemli: once feed denenir (anahtar/plan hatasi dogrudan gorunur), sonra
    kutuphane import edilir. Kutuphane yoksa bile feed'in ne dedigi raporlanir.
    """
    targets: dict[str, dict] = {}
    feed_error = ""
    if api_key:
        for region in regions[:3]:
            try:
                rows = L.euler_feed(api_key, region)
                log(f"feed {region}: {len(rows)} oda")
                for row in rows:
                    key = row["room_id"] or f"@{row['user']}"
                    targets[key] = row
            except L.ProviderError as exc:
                feed_error = str(exc)
                log(f"feed {region} hatasi: {exc}")

    # izleme listesi her zaman eklenir (feed olmasa da calisir)
    for handle in watchlist:
        h = handle.lstrip("@")
        targets.setdefault(f"@{h}", {"room_id": "", "user": h, "nickname": h, "avatar": "",
                                     "title": "", "viewers": 0, "thumb": "", "region": ""})

    if not targets:
        return [], feed_error or "hedef oda yok (feed bos, izleme listesi bos)"

    try:
        from TikTokLive import TikTokLiveClient  # type: ignore
        from TikTokLive.events import EnvelopeEvent, GiftEvent  # type: ignore
    except Exception as exc:
        msg = (f"TikTokLive yok ({type(exc).__name__}); feed {len(targets)} oda dondurdu "
               f"ama canli yakalama yapilamadi")
        return [], (msg + (f" | feed: {feed_error}" if feed_error else ""))

    # Izleyici sayisini canli tut: v7'de RoomUserSeqEvent, eski surumlerde ViewerCountEvent.
    ViewerEvents: list = []
    for name in ("RoomUserSeqEvent", "ViewerCountEvent"):
        try:
            ViewerEvents.append(getattr(__import__("TikTokLive.events", fromlist=[name]), name))
        except Exception:
            continue

    picked = sorted(targets.values(), key=lambda r: int(r.get("viewers") or 0), reverse=True)[:max_rooms]
    log(f"dinlenecek oda: {len(picked)} / {len(targets)}")

    flows = L.GiftFlow()
    chests: dict[str, dict] = {}
    raw_envelopes: list[dict] = []
    raw_gifts: list[dict] = []
    offline: dict[str, str] = {}
    started = time.time()

    async def watch(meta: dict) -> None:
        handle = meta.get("user") or ""
        if not handle:
            return
        room_key = f"@{handle}"
        client = TikTokLiveClient(unique_id=handle)

        @client.on(GiftEvent)  # type: ignore[misc]
        async def _on_gift(event):  # noqa: ANN001
            fields = _gift_fields(event)
            gained = flows.add_gift(room_key, meta, user=fields["user"], gift_id=fields["gift_id"],
                                    diamonds=fields["diamonds"], repeat_count=fields["repeat_count"],
                                    repeat_end=fields["repeat_end"], gift_name=fields["gift_name"])
            raw_gifts.append({**fields, "room": handle, "gained": gained, "at": int(time.time())})
            if gained:
                who = fields["nickname"] or fields["user"] or "?"
                what = fields["gift_name"] or fields["gift_id"] or "hediye"
                log(f"jeton: @{handle} +{gained} ({who} → {what})")

        @client.on(EnvelopeEvent)  # type: ignore[misc]
        async def _on_envelope(event):  # noqa: ANN001
            info = getattr(event, "envelope_info", None)
            if info is None:
                return
            fields = _envelope_fields(info, meta)
            raw_envelopes.append({**fields, "user": handle, "at": int(time.time())})
            flows.mark_envelope(room_key, meta, fields["envelope_id"])
            chest = L.chest_from_envelope_fields(fields, meta)
            if chest:
                chests[chest["id"]] = chest
                log(f"sandik: @{handle} {chest['coins']} jeton / {chest['slots']} kisi")

        for event_type in ViewerEvents:
            @client.on(event_type)  # type: ignore[misc]
            async def _on_viewers(event):  # noqa: ANN001
                count = 0
                for attr in ("viewer_count", "count", "total", "total_user"):
                    try:
                        val = int(getattr(event, attr, 0) or 0)
                    except (TypeError, ValueError):
                        val = 0
                    count = count or val
                if count > 0:
                    meta["viewers"] = count

        try:
            await client.connect()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            reason = type(exc).__name__
            offline[handle] = reason
            log(f"@{handle}: baglanti hatasi ({reason}: {str(exc)[:80]})")

    tasks = [asyncio.create_task(watch(meta)) for meta in picked]
    try:
        await asyncio.sleep(max(10, seconds))
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    window = max(1.0, time.time() - started)
    _append_jsonl("envelopes.jsonl", raw_envelopes)
    _append_jsonl("gifts.jsonl", raw_gifts)

    flow_rows = flows.rows(int(time.time() * 1000), window_seconds=window)
    if flow_rows:
        log(f"jeton akisi: {len(flow_rows)} oda, "
            f"{sum(int(r.get('gift_coins') or 0) for r in flow_rows)} jeton / {round(window)} sn")

    rooms = sorted(list(chests.values()) + flow_rows,
                   key=lambda r: int(r.get("coins") or 0), reverse=True)

    detail = ""
    if not rooms and len(offline) >= len(picked):
        # Hicbir odaya baglanilamadi: sebebi net soyle (yayinda degil / anahtar / imza).
        reasons = sorted({v for v in offline.values()})
        detail = (f"{len(picked)} odanin hicbirine baglanilamadi: {', '.join(reasons)}"
                  + (f" | feed: {feed_error}" if feed_error else ""))
    elif not rooms and feed_error:
        detail = feed_error
    elif not rooms:
        detail = f"dinlenen {len(picked)} odada hediye/zarf gelmedi"
    elif not chests:
        detail = "jeton akisi olculdu, dinleme suresinde sandik zarfi gelmedi"
    return rooms, detail


def _append_jsonl(name: str, rows: list[dict]) -> None:
    """Ham websocket kayitlarini data/<name> altina ekle (hata olsa da is surer)."""
    if not rows:
        return
    try:
        logfile = ROOT / "data" / name
        logfile.parent.mkdir(parents=True, exist_ok=True)
        with logfile.open("a", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        pass


def collect_euler(seconds: int, max_rooms: int, extra_watch: list[str] | None = None) -> tuple[list[dict], str]:
    api_key = env("EULER_API_KEY")
    regions = [r.upper() for r in parse_list(env("EULER_REGIONS", "TR"))] or ["TR"]
    watchlist = parse_list(env("WATCHLIST")) or watchlist_file()
    for handle in (extra_watch or []):
        if handle and handle not in watchlist:
            watchlist.append(handle)
    if not api_key and not watchlist:
        return [], "EULER_API_KEY yok, WATCHLIST bos (data/watchlist.txt de bos)"
    log(f"izleme listesi: {len(watchlist)} hesap" + (f" ({', '.join(watchlist[:6])}…)" if len(watchlist) > 6 else f" ({', '.join(watchlist)})" if watchlist else ""))
    return asyncio.run(_capture(api_key, regions, watchlist, seconds, max_rooms))


# ----------------------------------------------------------------------- yazma
def write_output(out_dir: Path, snap: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "rooms.json"
    tmp = out_dir / "rooms.json.tmp"
    tmp.write_text(json.dumps(snap, ensure_ascii=False, separators=(",", ":")), "utf-8")
    tmp.replace(target)
    meta = {k: v for k, v in snap.items() if k != "rooms"}
    meta["rooms"] = snap.get("total", 0)
    (out_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), "utf-8")
    log(f"yazildi: {target.name} ({target.stat().st_size // 1024} KB, {snap.get('total')} oda)")


def load_previous(out_dir: Path) -> dict | None:
    path = out_dir / "rooms.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text("utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description="SandikRadar veri iscisi")
    ap.add_argument("--provider", default=env("DATA_PROVIDER", "auto"),
                    choices=["auto", "sim", "euler"])
    ap.add_argument("--seconds", type=int, default=int(env("CAPTURE_SECONDS", "150")))
    ap.add_argument("--max-rooms", type=int, default=int(env("MAX_ROOMS", "12")))
    ap.add_argument("--out", default=env("OUT_DIR", str(DEFAULT_OUT)))
    ap.add_argument("--watch", default="",
                    help="izlenecek hesaplar: '@a,@b' (WATCHLIST / data/watchlist.txt'e eklenir)")
    args = ap.parse_args()

    out_dir = Path(args.out)
    if not out_dir.is_absolute():
        out_dir = ROOT / out_dir

    extra_watch = parse_list(args.watch)
    provider = args.provider
    if provider == "auto":
        provider = "euler" if (env("EULER_API_KEY") or env("WATCHLIST") or watchlist_file() or extra_watch) else "sim"

    now = int(time.time() * 1000)
    log(f"provider={provider} out={out_dir}")

    if provider == "sim":
        rooms = L.sim_rooms(now) + L.sim_flow_rooms(now)
        snap = L.build_snapshot("sim", rooms, now, demo=True,
                                notice="DEMO veri — gercek TikTok yayini degil. "
                                       "Gercek sandik/jeton akisi icin EULER_API_KEY ekle.")
        write_output(out_dir, snap)
        return 0

    rooms, detail = collect_euler(max(15, args.seconds), max(1, args.max_rooms), extra_watch)
    if rooms:
        snap = L.build_snapshot("euler", rooms, now, demo=False,
                                notice="EulerStream feed + hediye jeton akisi + zarf (sandik) yakalama")
        write_output(out_dir, snap)
        return 0

    prev = load_previous(out_dir)
    if prev and int(prev.get("total") or 0) > 0:
        prev = dict(prev)
        prev["error"] = detail
        prev["stale"] = True
        prev["last_attempt"] = now
        write_output(out_dir, prev)
        log(f"yeni sandik yok, onceki liste korundu: {detail}")
        return 0

    snap = L.build_snapshot("euler", [], now, demo=False,
                            notice="Henuz sandik yakalanmadi", error=detail)
    write_output(out_dir, snap)
    log(f"bos liste yazildi: {detail}")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass
    raise SystemExit(main())
