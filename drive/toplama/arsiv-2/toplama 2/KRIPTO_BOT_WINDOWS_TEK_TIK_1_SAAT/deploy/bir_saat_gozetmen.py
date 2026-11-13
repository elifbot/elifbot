#!/usr/bin/env python3
"""Süreli paper oturumunu child-process olarak gözetir ve plansız çökmede sürdürür.

GitHub gerekmez. Üretimde systemd bu betiği çalıştırabilir; Arena Agent Mode'da
`start_process` bu betiğin dış gözetmenidir. Bildirim preflight başarısızsa işlem
motoru hiç başlatılmaz.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_DIR = ROOT / "run"
REPORT_DIR = ROOT / "reports"


class Supervisor:
    def __init__(
        self,
        hours: float,
        db_file: str,
        max_restarts: int,
        health_url: str,
        health_grace_sec: float,
        skip_notifications: bool = False,
    ) -> None:
        self.hours = hours
        self.db_file = db_file
        self.max_restarts = max_restarts
        self.health_url = health_url
        self.health_grace_sec = health_grace_sec
        self.skip_notifications = bool(skip_notifications)
        self.child: subprocess.Popen[str] | None = None
        self.stopping = False
        self.started_at = time.time()
        self.deadline = self.started_at + hours * 3600.0 + 15 * 60.0
        RUN_DIR.mkdir(parents=True, exist_ok=True)
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime(self.started_at))
        self.log_path = RUN_DIR / f"bir_saat_gozetmen_{stamp}.log"
        self.state_path = RUN_DIR / "bir_saat_gozetmen_state.json"

    def log(self, text: str) -> None:
        line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {text}"
        print(line, flush=True)
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def write_state(self, **extra: object) -> None:
        state = {
            "supervisor_pid": os.getpid(),
            "child_pid": self.child.pid if self.child and self.child.poll() is None else None,
            "started_at": self.started_at,
            "deadline": self.deadline,
            "hours": self.hours,
            "db_file": self.db_file,
            "log_file": str(self.log_path),
            "stopping": self.stopping,
            "updated_at": time.time(),
            **extra,
        }
        temporary = self.state_path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(self.state_path)

    def env(self) -> dict[str, str]:
        env = os.environ.copy()
        env.update(
            {
                "MODE": "paper",
                "PAPER_SESSION_HOURS": str(self.hours),
                "BOT_DB_FILE": self.db_file,
                "REQUIRE_NOTIFICATIONS": "0" if self.skip_notifications else "1",
                "NOTIFICATION_STARTUP_TEST": "0" if self.skip_notifications else "1",
                "PYTHONUNBUFFERED": "1",
            }
        )
        return env

    def relay_signal(self, signum: int, _frame) -> None:
        name = signal.Signals(signum).name
        self.log(f"Dış {name} alındı; child kontrollü durduruluyor.")
        self.stopping = True
        self.write_state(reason=f"external_{name}")
        if self.child and self.child.poll() is None:
            self.child.send_signal(signal.SIGTERM)

    def preflight(self) -> bool:
        if self.skip_notifications:
            self.log(
                "Telegram/WhatsApp kontrolü kullanıcı talebiyle bu oturum için atlandı; "
                "bildirim teslimatı kabul kriteri değildir."
            )
            self.write_state(reason="notification_preflight_skipped_by_user")
            return True
        self.log("Telegram/WhatsApp bağımsız teslimat testi başlıyor.")
        result = subprocess.run(
            [sys.executable, "deploy/bildirim_testi.py"],
            cwd=ROOT,
            env=self.env(),
            text=True,
            capture_output=True,
            timeout=60,
        )
        if result.stdout:
            for line in result.stdout.splitlines():
                self.log("PREFLIGHT | " + line)
        if result.stderr:
            for line in result.stderr.splitlines():
                self.log("PREFLIGHT-ERR | " + line)
        if result.returncode != 0:
            self.log(
                f"Bildirim preflight başarısız (exit={result.returncode}); işlem motoru başlatılmadı."
            )
            self.write_state(reason="notification_preflight_failed", exit_code=78)
            return False
        self.log("Bildirim preflight başarılı; iki kanal teslimatı doğrulandı.")
        return True

    def health_ok(self) -> bool:
        try:
            with urllib.request.urlopen(self.health_url, timeout=4) as response:
                payload = json.loads(response.read().decode("utf-8"))
                return response.status == 200 and bool(payload.get("heartbeat_fresh"))
        except (OSError, ValueError, urllib.error.URLError):
            return False

    def stream_output(self, child: subprocess.Popen[str]) -> None:
        assert child.stdout is not None
        for raw in child.stdout:
            self.log("BOT | " + raw.rstrip("\n"))

    def read_last_exit_reason(self, child_started_at: float) -> str:
        """Yalnız bu child çalışmasına ait taze çıkış kaydını kabul et."""
        path = REPORT_DIR / "last_exit.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            ended_at = float(payload.get("ended_at") or 0.0)
            if ended_at + 1.0 < child_started_at:
                return ""
            return str(payload.get("value") or "")
        except (OSError, ValueError, TypeError):
            return ""

    def run_child(self, attempt: int) -> tuple[int, str]:
        self.log(f"Bot child başlatılıyor | deneme={attempt} | DB={self.db_file}")
        self.child = subprocess.Popen(
            [sys.executable, "-m", "src.main"],
            cwd=ROOT,
            env=self.env(),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
            start_new_session=True,
        )
        self.write_state(reason="running", restart_attempt=attempt)
        output_thread = threading.Thread(
            target=self.stream_output, args=(self.child,), daemon=True
        )
        output_thread.start()

        child_started = time.time()
        last_healthy = child_started
        # Ağ/borsa katalogu ve ilk heartbeat için başlangıç toleransı.
        initial_health_grace = max(150.0, self.health_grace_sec)
        while self.child.poll() is None:
            if self.stopping:
                if time.time() - child_started > 90 and self.child.poll() is None:
                    self.log("Child 90 sn içinde kapanmadı; SIGKILL uygulanıyor.")
                    self.child.kill()
                time.sleep(1)
                continue
            now = time.time()
            if now > self.deadline:
                self.log("Supervisor sert süre sınırı aşıldı; child SIGTERM alıyor.")
                self.child.send_signal(signal.SIGTERM)
                self.stopping = True
                continue
            if self.health_ok():
                last_healthy = now
            elif (
                now - child_started > initial_health_grace
                and now - last_healthy > self.health_grace_sec
            ):
                self.log(
                    f"Health {self.health_grace_sec:.0f} sn taze değil; child kontrollü yeniden başlatılacak."
                )
                self.child.send_signal(signal.SIGTERM)
                break
            self.write_state(reason="running", restart_attempt=attempt)
            time.sleep(5)

        try:
            code = self.child.wait(timeout=95)
        except subprocess.TimeoutExpired:
            self.log("Child kapanış timeout; SIGKILL uygulanıyor.")
            self.child.kill()
            code = self.child.wait(timeout=10)
        output_thread.join(timeout=5)
        reason = self.read_last_exit_reason(child_started)
        self.log(f"Bot child çıktı | exit={code} | last_exit={reason or 'yok'}")
        return code, reason

    def run(self) -> int:
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, self.relay_signal)
        self.write_state(reason="starting")
        if not self.preflight():
            return 78

        attempt = 0
        while attempt <= self.max_restarts:
            attempt += 1
            code, reason = self.run_child(attempt)
            if reason == "scheduled_paper_session_complete" and code == 0:
                self.log("Bir saatlik oturum planlı tamamlandı; supervisor başarıyla kapanıyor.")
                self.write_state(reason=reason, exit_code=0, completed=True)
                return 0
            if self.stopping:
                self.log("Supervisor dış istekle kontrollü kapandı.")
                self.write_state(reason="supervisor_stopped", exit_code=0)
                return 0
            if time.time() >= self.deadline:
                self.log("Oturum sert deadline içinde planlı tamamlanmadı.")
                self.write_state(reason="hard_deadline_failed", exit_code=1)
                return 1
            if attempt > self.max_restarts:
                self.log("Maksimum yeniden başlatma sayısı aşıldı.")
                self.write_state(reason="restart_limit_failed", exit_code=1)
                return 1
            self.log("Plansız çıkış; aynı DB ve oturum bitiş zamanı ile 5 sn sonra devam edilecek.")
            time.sleep(5)
        return 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Süreli paper oturumu gözetmeni")
    parser.add_argument("--hours", type=float, default=1.0)
    parser.add_argument(
        "--db-file",
        default=f"bot_state_acceptance_{time.strftime('%Y%m%d_%H%M%S')}.db",
    )
    parser.add_argument("--max-restarts", type=int, default=5)
    parser.add_argument("--health-url", default="http://127.0.0.1:8502/health")
    parser.add_argument("--health-grace-sec", type=float, default=180.0)
    parser.add_argument(
        "--skip-notifications",
        action="store_true",
        help="Kullanıcı açıkça istediğinde Telegram/WhatsApp preflight'ını bu oturum için atla.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.hours <= 0:
        raise SystemExit("--hours sıfırdan büyük olmalı")
    supervisor = Supervisor(
        hours=args.hours,
        db_file=args.db_file,
        max_restarts=max(0, args.max_restarts),
        health_url=args.health_url,
        health_grace_sec=max(60.0, args.health_grace_sec),
        skip_notifications=args.skip_notifications,
    )
    return supervisor.run()


if __name__ == "__main__":
    raise SystemExit(main())
