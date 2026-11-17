#!/usr/bin/env python3
"""SandikRadar veri pompası — veriyi üretip GitHub'a iter (GitHub cron'u yerine).

Neden var: GitHub'ın zamanlanmış işleri bazı depolarda hiç tetiklenmiyor
(`event=schedule → total_count: 0`). Bu betik aynı işi bilgisayarından yapar:

    python tools/pump.py                 # veriyi topla, değiştiyse commit + push
    python tools/pump.py --provider sim   # DEMO veri
    python tools/pump.py --dry-run        # sadece topla, push etme

Windows Görev Zamanlayıcı (10 dakikada bir):
    schtasks /Create /TN SandikRadarPump /SC MINUTE /MO 10 /F ^
      /TR "\"C:\\...\\python.exe\" \"C:\\...\\sandikradar-web\\tools\\pump.py\""
Kaldırmak için:  schtasks /Delete /TN SandikRadarPump /F

Token: `gh auth token` (gh girişliyse) ya da GITHUB_TOKEN ortam değişkeni.
"""

from __future__ import annotations

import argparse
import atexit
import datetime
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "collector"))


def log(msg: str) -> None:
    print(f"[pump] {msg}", flush=True)


def run(cmd: list[str], check: bool = False, env: dict | None = None) -> subprocess.CompletedProcess:
    # encoding şart: Windows'ta varsayılan cp1254, collect çıktısındaki emoji/Arapça
    # kullanıcı adlarında UnicodeDecodeError atıp çıktıyı yarıda kesiyordu.
    return subprocess.run(cmd, cwd=str(ROOT), text=True, encoding="utf-8", errors="replace",
                          capture_output=True, check=check, env=env)


def token() -> str:
    tok = (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "").strip()
    if tok:
        return tok
    gh = shutil.which("gh")
    if not gh:
        return ""
    out = run([gh, "auth", "token"])
    return (out.stdout or "").strip() if out.returncode == 0 else ""


def remote_url() -> str:
    out = run(["git", "remote", "get-url", "origin"])
    return (out.stdout or "").strip()


def lock() -> bool:
    """Aynı anda iki pompa çalışmasın: elle çalıştırma + zamanlanmış görev
    `docs/data`'yı rebase sırasında ezip çakışma üretiyordu."""
    p = ROOT / ".git" / "pump.lock"
    try:
        fd = os.open(str(p), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        try:
            eski = datetime.datetime.now().timestamp() - p.stat().st_mtime
        except OSError:
            eski = 0
        if eski < 900:            # 15 dk'dan taze → gerçekten çalışıyor
            return False
        p.unlink(missing_ok=True)  # çökmüş kalmış kilit
        try:
            fd = os.open(str(p), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return False
    os.write(fd, str(os.getpid()).encode())
    os.close(fd)
    atexit.register(lambda: p.unlink(missing_ok=True))
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description="SandikRadar veri pompası")
    ap.add_argument("--provider", default=os.environ.get("DATA_PROVIDER", "auto"),
                    choices=["auto", "sim", "euler"])
    ap.add_argument("--seconds", type=int, default=int(os.environ.get("CAPTURE_SECONDS", "150")))
    ap.add_argument("--watch", default=os.environ.get("WATCHLIST", ""),
                    help="izlenecek hesaplar '@a,@b' (boşsa data/watchlist.txt okunur)")
    ap.add_argument("--dry-run", action="store_true", help="topla ama commit/push etme")
    args = ap.parse_args()

    if not (ROOT / ".git").exists():
        log(f"HATA: {ROOT} bir git deposu değil")
        return 2

    if not lock():
        log("başka bir pompa çalışıyor — bu tur atlandı")
        return 0

    # yarım kalmış turdan artık dosya kalmasın (yeniden üretilecek)
    dirty = run(["git", "status", "--porcelain", "--", "docs/data"])
    if (dirty.stdout or "").strip():
        log("önceki turdan kalan değişiklikler geri alınıyor")
        run(["git", "checkout", "--", "docs/data"])

    # 1) veriyi topla
    collect = [sys.executable, str(ROOT / "collector" / "collect.py"),
               "--provider", args.provider, "--seconds", str(args.seconds)]
    if args.watch:
        collect += ["--watch", args.watch]
    res = run(collect)
    for line in (res.stdout or "").splitlines():
        log("  " + line)
    if res.returncode != 0:
        log(f"collect hatası (kod {res.returncode}): {(res.stderr or '')[:300]}")
        return res.returncode

    if args.dry_run:
        log("dry-run: commit/push atlandı")
        return 0

    # 2) değişiklik var mı?
    run(["git", "add", "-A", "docs/data"])
    diff = run(["git", "diff", "--cached", "--quiet"])
    if diff.returncode == 0:
        log("değişiklik yok — push atlandı")
        return 0

    # 3) commit + push (bot commit'leri yarışabilir: önce rebase)
    run(["git", "-c", "user.name=sandikradar-pump",
         "-c", "user.email=actions@users.noreply.github.com",
         "commit", "-m", "data: " + datetime.datetime.now(datetime.timezone.utc)
         .strftime("%Y-%m-%dT%H:%M:%SZ")])
    run(["git", "-c", "rebase.autoStash=true", "pull", "--rebase", "--no-edit", "origin", "main"])

    url = remote_url()
    tok = token()
    push_url = url
    if tok and url.startswith("https://github.com/"):
        push_url = url.replace("https://github.com/", f"https://x-access-token:{tok}@github.com/")

    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "/bin/true"}
    out = subprocess.run(["git", "push", push_url, "main"], cwd=str(ROOT), text=True,
                         capture_output=True, env=env)
    tail = ((out.stdout or "") + (out.stderr or "")).strip().splitlines()[-3:]
    for line in tail:
        log("  " + line)
    if out.returncode != 0:
        log("push başarısız — gh auth token / yetki kontrol et")
        return out.returncode

    log("push tamam — Pages birkaç dakikada güncellenir")
    run(["git", "fetch", "--quiet", "origin"])   # takip ref'i güncel kalsın
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass
    raise SystemExit(main())
