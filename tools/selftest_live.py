#!/usr/bin/env python3
"""Uçtan uca çevrimdışı test: sahte TikTokLive kütüphanesiyle collect.py akışı.

    python tools/selftest_live.py

Gerçek TikTokLive kurulu olmasa da `collector/collect.py::_capture` içindeki
olay bağlama (GiftEvent -> jeton akışı, EnvelopeEvent -> sandık) zincirini
çalıştırır: sahte bir `TikTokLive` paketi sys.path'e eklenir, iki oda dinlenir,
hediye + zarf olayları yayınlanır ve üretilen satırlar doğrulanır.
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import textwrap
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "collector"))

FAKE_PKG = textwrap.dedent('''
    """Sahte TikTokLive: yalnizca test icin."""
    import asyncio
    import time

    EVENTS_ROOM = "oda1"

    EVENTS = []

    class _User:
        def __init__(self, unique_id, nickname):
            self.unique_id = unique_id
            self.nickname = nickname

    class _Gift:
        def __init__(self, gid, name, diamonds):
            self.id = gid
            self.name = name
            self.diamond_count = diamonds

    class _EnvelopeInfo:
        def __init__(self, envelope_id, diamonds, people, unpack_at):
            self.envelope_id = envelope_id
            self.room_id = EVENTS_ROOM
            self.diamond_count = diamonds
            self.people_count = people
            self.unpack_at = unpack_at
            self.skin_id = 1

    class TikTokLiveClient:
        def __init__(self, unique_id):
            self.unique_id = unique_id
            self.handlers = {}
            self._task = None

        def on(self, event_type):
            def deco(fn):
                self.handlers[event_type] = fn
                return fn
            return deco

        async def connect(self):
            async def emit():
                from TikTokLive.events import GiftEvent, EnvelopeEvent, ViewerCountEvent
                await asyncio.sleep(0.05)
                # 1. oda: combo hediye + zarf; 2. oda: yalnizca hediye
                combos = [(1, 100), (2, 100), (3, 100)] if self.unique_id == "oda1" else [(1, 50)]
                for count, diamonds in combos:
                    ev = GiftEvent()
                    ev.user = _User(f"izleyici_{self.unique_id}", "İzleyici")
                    ev.gift = _Gift("5655", "Rose", diamonds)
                    ev.repeat_count = count
                    ev.repeat_end = count == 3
                    await self._fire(GiftEvent, ev)
                if self.unique_id == "oda1":
                    env = EnvelopeEvent()
                    env.envelope_info = _EnvelopeInfo("env-test-1", 5000, 50, int(time.time()) + 90)
                    await self._fire(EnvelopeEvent, env)
                if ViewerCountEvent in self.handlers:
                    vc = ViewerCountEvent()
                    vc.viewer_count = 321
                    await self._fire(ViewerCountEvent, vc)
                await asyncio.sleep(3600)

            self._task = asyncio.create_task(emit())

        async def _fire(self, event_type, event):
            fn = self.handlers.get(event_type)
            if fn:
                await fn(event)
''')

EVENTS_ROOM = "'oda1'"


def build_fake(tmp: Path) -> None:
    pkg = tmp / "TikTokLive"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text(
        "from .client import TikTokLiveClient, _User, _Gift, _EnvelopeInfo\n", "utf-8")
    (pkg / "client.py").write_text(FAKE_PKG, "utf-8")
    (pkg / "events.py").write_text(textwrap.dedent('''
        class _Evt:
            pass

        class GiftEvent(_Evt):
            pass

        class EnvelopeEvent(_Evt):
            pass

        class ViewerCountEvent(_Evt):
            pass
    '''), "utf-8")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmpdir:
        build_fake(Path(tmpdir))
        sys.path.insert(0, tmpdir)
        import collect as C  # sahte paket sys.path'te iken import edilir

        real_sleep = asyncio.sleep
        calls = {"n": 0}

        async def fast_sleep(delay, *a, **kw):
            """Dinleme suresini kisalt: yalnizca buyuk beklemeleri 1 sn'ye indir."""
            calls["n"] += 1
            if delay and delay >= 5 and calls["n"] > 2:
                return await real_sleep(0.5)
            return await real_sleep(min(delay, 5) if delay else delay, *a, **kw)

        C.asyncio.sleep = fast_sleep
        started = time.time()
        rooms, detail = asyncio.run(C._capture("", [], ["oda1", "oda2"], 10, 4))
        took = time.time() - started

    by_kind = {}
    for room in rooms:
        by_kind.setdefault(room["kind"], []).append(room)

    chests = by_kind.get("chest", [])
    flows = by_kind.get("live", [])
    print(json.dumps({"detail": detail, "odalar": len(rooms),
                      "sandik": len(chests), "akis": len(flows), "sure": round(took, 1)},
                     ensure_ascii=False, indent=1))
    for row in flows:
        print(f"  akis @{row['user']}: {row['gift_coins']} jeton, "
              f"{row['diamonds_per_min']}/dk, envelope={row['envelope_id'] or '-'}")
    for row in chests:
        print(f"  sandik @{row['user']}: {row['coins']} jeton / {row['slots']} kisi")

    fails = []
    if len(flows) != 2:
        fails.append(f"akis satiri {len(flows)} (beklenen 2)")
    if len(chests) != 1:
        fails.append(f"sandik {len(chests)} (beklenen 1)")
    oda1 = next((r for r in flows if r["user"] == "oda1"), None)
    oda2 = next((r for r in flows if r["user"] == "oda2"), None)
    if not oda1 or oda1["gift_coins"] != 300:
        fails.append(f"oda1 jeton {oda1 and oda1['gift_coins']} (beklenen 300)")
    if not oda1 or oda1["envelope_id"] != "env-test-1":
        fails.append("oda1 zarf isareti yok")
    if not oda2 or oda2["gift_coins"] != 50:
        fails.append(f"oda2 jeton {oda2 and oda2['gift_coins']} (beklenen 50)")
    if oda1 and oda1.get("viewers") != 321:
        fails.append(f"oda1 izleyici {oda1 and oda1.get('viewers')} (beklenen 321)")

    if fails:
        print("\nBASARISIZ: " + "; ".join(fails))
        return 1
    print("\nuctan uca akis testi gecti")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
