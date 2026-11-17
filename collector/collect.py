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


# --------------------------------------------------------------- euler yakalama
async def _capture(api_key: str, regions: list[str], watchlist: list[str],
                   seconds: int, max_rooms: int) -> tuple[list[dict], str]:
    """Feed ile hedef odalari bul, websocket zarflarindan sandik/canta cikar.

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
        from TikTokLive.events import EnvelopeEvent  # type: ignore
    except Exception as exc:
        msg = (f"TikTokLive yok ({type(exc).__name__}); feed {len(targets)} oda dondurdu "
               f"ama canli yakalama yapilamadi")
        return [], (msg + (f" | feed: {feed_error}" if feed_error else ""))

    picked = sorted(targets.values(), key=lambda r: int(r.get("viewers") or 0), reverse=True)[:max_rooms]
    log(f"dinlenecek oda: {len(picked)} / {len(targets)}")

    found: dict[str, dict] = {}
    seen_raw: list[dict] = []

    async def watch(meta: dict) -> None:
        handle = meta.get("user") or ""
        if not handle:
            return
        client = TikTokLiveClient(unique_id=handle)

        @client.on(EnvelopeEvent)  # type: ignore[misc]
        async def _on_envelope(event):  # noqa: ANN001
            info = getattr(event, "envelope_info", None)
            if info is None:
                return
            fields = {
                "envelope_id": str(getattr(info, "envelope_id", "") or ""),
                "room_id": str(getattr(info, "room_id", "") or meta.get("room_id") or ""),
                "diamond_count": int(getattr(info, "diamond_count", 0) or 0),
                "people_count": int(getattr(info, "people_count", 0) or 0),
                "unpack_at": int(getattr(info, "unpack_at", 0) or 0),
                "skin_id": int(getattr(info, "skin_id", 0) or 0),
            }
            seen_raw.append({**fields, "user": handle, "at": int(time.time())})
            chest = L.chest_from_envelope_fields(fields, meta)
            if chest:
                found[chest["id"]] = chest
                log(f"sandik: @{handle} {chest['coins']} jeton / {chest['slots']} kisi")

        try:
            await client.connect()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log(f"@{handle}: baglanti hatasi ({type(exc).__name__}: {str(exc)[:80]})")

    tasks = [asyncio.create_task(watch(meta)) for meta in picked]
    try:
        await asyncio.sleep(max(10, seconds))
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    if seen_raw:
        try:
            logfile = ROOT / "data" / "envelopes.jsonl"
            logfile.parent.mkdir(parents=True, exist_ok=True)
            with logfile.open("a", encoding="utf-8") as fh:
                for row in seen_raw:
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        except Exception:
            pass

    detail = ""
    if not found and feed_error:
        detail = feed_error
    elif not found:
        detail = "dinleme suresinde sandik zarfi gelmedi"
    return list(found.values()), detail


def collect_euler(seconds: int, max_rooms: int) -> tuple[list[dict], str]:
    api_key = env("EULER_API_KEY")
    regions = [r.upper() for r in parse_list(env("EULER_REGIONS", "TR"))] or ["TR"]
    watchlist = parse_list(env("WATCHLIST"))
    if not api_key and not watchlist:
        return [], "EULER_API_KEY yok, WATCHLIST bos"
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
    args = ap.parse_args()

    out_dir = Path(args.out)
    if not out_dir.is_absolute():
        out_dir = ROOT / out_dir

    provider = args.provider
    if provider == "auto":
        provider = "euler" if (env("EULER_API_KEY") or env("WATCHLIST")) else "sim"

    now = int(time.time() * 1000)
    log(f"provider={provider} out={out_dir}")

    if provider == "sim":
        rooms = L.sim_rooms(now)
        snap = L.build_snapshot("sim", rooms, now, demo=True,
                                notice="DEMO veri — gercek TikTok yayini degil. "
                                       "Gercek sandik icin EULER_API_KEY ekle.")
        write_output(out_dir, snap)
        return 0

    rooms, detail = collect_euler(max(15, args.seconds), max(1, args.max_rooms))
    if rooms:
        snap = L.build_snapshot("euler", rooms, now, demo=False,
                                notice="EulerStream feed + websocket zarf yakalama")
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
