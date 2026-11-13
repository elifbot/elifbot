"""ACARBOT v2.0 — Giriş kapıları: hız limiti, yeniden giriş beklemesi,
gölge sinyal takibi.

Şartname (A. Zorunlu 4-5, B. madde 6):
  - Giriş hız limiti: aynı anda gelen sinyallerde skora göre sırala,
    dakikada en fazla N GERÇEK giriş. Sayaç gerçek girişleri sayar,
    kapanmış işlemleri saymaz.
  - Stop sonrası yeniden giriş beklemesi (15 dk); trailing/kâr çıkışlarında
    kısa bekleme (5 dk).
  - Gölge sinyal sonucu: haber ve sweep guard'ın engellediği girişlerin
    sonraki 30/60/120 dakika getirisi kaydedilir → "engellemeseydik ne
    olurdu" sayısı.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from core.config import RiskGateConfig


class EntryRateLimiter:
    """Dakikalık GERÇEK giriş sayacı + skora göre sıralı aday kuyruğu.

    Kullanım:
      - `allow(now_ms)` → bu dakikada yeni giriş için yer var mı?
      - `record(now_ms)` → dolum GERÇEKLEŞTİĞİNDE çağrılır (pozisyon açıldı).
      - `defer(candidate)` / `flush(now_ms, allow_fn)` → hız limitine
        takılan yüksek skorlu adaylar bir sonraki boş pencerede,
        SKORA GÖRE sırayla tekrar denenir; TTL dolan aday düşer.
    """

    def __init__(self, cfg: RiskGateConfig | None = None) -> None:
        self.cfg = cfg or RiskGateConfig()
        self._fill_times: deque[int] = deque()
        self._deferred: list[_DeferredCandidate] = []
        self.deferred_expired = 0

    def allow(self, now_ms: int) -> bool:
        self._trim(now_ms)
        return len(self._fill_times) < self.cfg.entry_rate_per_min

    def record(self, now_ms: int) -> None:
        self._trim(now_ms)
        self._fill_times.append(now_ms)

    def recent_count(self, now_ms: int) -> int:
        self._trim(now_ms)
        return len(self._fill_times)

    def defer(
        self, symbol: str, side: str, score: float, created_ms: int,
        payload: dict | None = None,
    ) -> None:
        self._deferred.append(_DeferredCandidate(
            symbol=symbol, side=side, score=score,
            created_ms=created_ms, payload=payload or {},
        ))

    def flush(self, now_ms: int) -> list[_DeferredCandidate]:
        """TTL'i aşmayan adayları SKORA GÖRE (çoktan aza) döndürür."""
        self._deferred = [
            c for c in self._deferred
            if (now_ms - c.created_ms) / 1000.0 <= self.cfg.deferred_entry_ttl_s
            or self._expire(c)
        ]
        self._deferred.sort(key=lambda c: -c.score)
        return list(self._deferred)

    def pop(self, symbol: str) -> _DeferredCandidate | None:
        for i, candidate in enumerate(self._deferred):
            if candidate.symbol == symbol:
                return self._deferred.pop(i)
        return None

    def _expire(self, candidate: _DeferredCandidate) -> bool:
        self.deferred_expired += 1
        return False

    def _trim(self, now_ms: int) -> None:
        while self._fill_times and now_ms - self._fill_times[0] > 60_000:
            self._fill_times.popleft()

    def stats(self) -> dict:
        return {
            "entry_rate_per_min": self.cfg.entry_rate_per_min,
            "fills_last_minute": len(self._fill_times),
            "deferred": len(self._deferred),
            "deferred_expired": self.deferred_expired,
        }


@dataclass
class _DeferredCandidate:
    symbol: str
    side: str
    score: float
    created_ms: int
    payload: dict = field(default_factory=dict)


# Çıkış nedeni → bekleme sınıfı
_HARD_EXITS = {"stop_loss", "position_loss_stop", "liquidation"}
_SOFT_EXITS = {"trailing_stop", "momentum_end", "time_stop", "reverse_signal",
               "funding_cost_exit"}


class ReentryCooldown:
    """Kapanan pozisyonun sembolünde yeni giriş beklemesi.

    stop/likidasyon → reentry_cooldown_min (varsayılan 15 dk)
    trailing/momentum/zaman/ters sinyal → soft_exit_cooldown_min (5 dk)
    """

    def __init__(self, cfg: RiskGateConfig | None = None) -> None:
        self.cfg = cfg or RiskGateConfig()
        self._until: dict[str, int] = {}
        self._last_reason: dict[str, str] = {}

    def record_exit(self, symbol: str, now_ms: int, reason: str) -> None:
        if reason in _HARD_EXITS:
            minutes = self.cfg.reentry_cooldown_min
        elif reason in _SOFT_EXITS:
            minutes = self.cfg.soft_exit_cooldown_min
        else:
            return  # kill_switch/end_of_backtest gibi çıkışlarda bekleme yok
        self._until[symbol] = now_ms + int(minutes * 60_000)
        self._last_reason[symbol] = reason

    def blocked(self, symbol: str, now_ms: int) -> float | None:
        """Kalan bekleme süresi (dakika); engel yoksa None."""
        until = self._until.get(symbol)
        if until is None or now_ms >= until:
            return None
        return (until - now_ms) / 60_000.0

    def last_reason(self, symbol: str) -> str | None:
        return self._last_reason.get(symbol)


# ---------------------------------------------------------------------------
# Gölge sinyal takibi ("engellemeseydik ne olurdu")
# ---------------------------------------------------------------------------

@dataclass
class ShadowSignal:
    ts_ms: int
    symbol: str
    side: str
    reason: str                    # NEWS_GUARD | SWEEP_GUARD | ...
    entry_ref: float
    stop_fraction: float
    returns: dict[str, float] = field(default_factory=dict)  # "30": pct
    matured: bool = False
    # v5.2: STOP-FARKINDALIKLI sonuç. Ham getiri "kâr eder miydi?"
    # sorusunu CEVAPLAMAZ: fiyat önce stopu vurup sonra dönebilir.
    first_exit: str | None = None      # "STOP" | "HEDEF" | None
    mfe_pct: float = 0.0               # en yüksek lehimize hareket
    mae_pct: float = 0.0               # en yüksek aleyhimize hareket
    target_r: float = 1.0              # hedef, R katı

    def as_dict(self) -> dict:
        return {
            "ts_ms": self.ts_ms,
            "symbol": self.symbol,
            "side": self.side,
            "reason": self.reason,
            "entry_ref": round(self.entry_ref, 8),
            "stop_fraction": round(self.stop_fraction, 5),
            "returns": {k: round(v, 4) for k, v in self.returns.items()},
            "matured": self.matured,
            "first_exit": self.first_exit,
            "mfe_pct": round(self.mfe_pct, 4),
            "mae_pct": round(self.mae_pct, 4),
            "target_r": self.target_r,
        }


MIN_DIRECTIONAL_N = 30


class ShadowSignalTracker:
    """Engellenen girişlerin hipotetik sonucunu 30/60/120 dk takip eder.

    Getiri: engel anındaki referans fiyata göre o ufukta % değişim
    (yön-düzeltilmiş: LONG için pozitif = engellemeseydi kârdı).
    """

    def __init__(
        self, horizons_min: tuple[int, ...] = (1, 5, 15, 30, 60, 120),
    ) -> None:
        # v5.3: kısa ufuklar eklendi. Eski en kısa ufuk 30 dk idi; 15
        # dakikalık test oturumunda HİBİR gölge olgunlaşmıyordu ve
        # "kapı bizi kârdan etti mi?" sorusu canlıda cevaplanamıyordu.
        # NOT: `matured` artık tüm ufukların dolmasını ister; kısa
        # oturumda `karar_veren` (ilk temas) alanı kullanılır.
        self.horizons = horizons_min
        self.records: list[ShadowSignal] = []

    def record_blocked(
        self, symbol: str, side: str, reason: str, entry_ref: float,
        stop_fraction: float, ts_ms: int,
    ) -> ShadowSignal | None:
        if entry_ref <= 0:
            return None
        record = ShadowSignal(
            ts_ms=ts_ms, symbol=symbol, side=side, reason=reason,
            entry_ref=entry_ref, stop_fraction=stop_fraction,
        )
        self.records.append(record)
        return record

    def on_price(self, symbol: str, price: float, ts_ms: int) -> int:
        """Kapanan mum/tick fiyatı: vadesi dolan gölgeleri hesaplar."""
        updated = 0
        for record in self.records:
            if record.symbol != symbol or record.matured:
                continue
            direction = 1.0 if record.side == "LONG" else -1.0
            if record.entry_ref <= 0 or price <= 0:
                continue
            change = (price / record.entry_ref - 1.0) * 100.0 * direction
            # v5.2: lehimize/aleyhimize en uç hareket + İLK temas
            record.mfe_pct = max(record.mfe_pct, change)
            record.mae_pct = min(record.mae_pct, change)
            if record.first_exit is None and record.stop_fraction > 0:
                stop_pct = -record.stop_fraction * 100.0
                target_pct = record.stop_fraction * record.target_r * 100.0
                # Muhafazakâr: aynı gözlemde ikisi de varsa STOP sayılır.
                if change <= stop_pct:
                    record.first_exit = "STOP"
                elif change >= target_pct:
                    record.first_exit = "HEDEF"
            for horizon in self.horizons:
                key = str(horizon)
                if key in record.returns:
                    continue
                if ts_ms - record.ts_ms >= horizon * 60_000:
                    record.returns[key] = change
                    updated += 1
            if len(record.returns) == len(self.horizons):
                record.matured = True
        return updated

    def summary(self) -> dict:
        """"Engellemeseydik ne olurdu" özeti."""
        total = len(self.records)
        by_reason: dict[str, list[ShadowSignal]] = {}
        for record in self.records:
            by_reason.setdefault(record.reason, []).append(record)
        out: dict[str, dict] = {}
        for reason, rows in by_reason.items():
            # v5.2: `max(returns) > 0` İYİMSERDİ — ufuklardan en iyisini
            # seçiyordu (ileriye bakıp kiraz toplama). Yerine İLK TEMAS
            # sırası: stop önce mi vurdu, hedef önce mi?
            decided = [r for r in rows if r.first_exit is not None]
            would_stop = sum(1 for r in decided if r.first_exit == "STOP")
            would_target = sum(1 for r in decided if r.first_exit == "HEDEF")
            matured_rows = [r for r in rows if r.returns]
            # v5.3: her kaydın ELDEKİ en uzun ufkunu kullan. Sabit 120 dk
            # beklemek kısa oturumda hiç veri üretmiyordu.
            finals = []
            for r in matured_rows:
                keys = [int(k) for k in r.returns]
                if keys:
                    finals.append(r.returns[str(max(keys))])
            out[reason] = {
                "blocked": len(rows),
                "matured": len(matured_rows),
                "karar_veren": len(decided),
                "once_stop": would_stop,
                "once_hedef": would_target,
                "hedef_orani": (
                    round(would_target / len(decided), 4) if decided else 0.0
                ),
                "ort_son_getiri_pct": (
                    round(sum(finals) / len(finals), 4) if finals else 0.0
                ),
                "olgunlasan_ufuk_dakika": (
                    max(int(k) for r in matured_rows for k in r.returns)
                    if finals else 0
                ),
                "ort_mfe_pct": (
                    round(sum(r.mfe_pct for r in rows) / len(rows), 4)
                    if rows else 0.0
                ),
                "ort_mae_pct": (
                    round(sum(r.mae_pct for r in rows) / len(rows), 4)
                    if rows else 0.0
                ),
            }
            # v5.4: n<30 ise YÖN İDDİASI YASAK. Tek gözlem oran değildir.
            # Önceki raporlar 1 karar veren sinyal için "backtest ile aynı
            # yönde" diyordu; bu istatistiksel olarak bilgi taşımaz.
            n_dec = len(decided)
            out[reason]["yön_iddiasi_gecerli"] = n_dec >= MIN_DIRECTIONAL_N
            out[reason]["yön_notu"] = (
                f"n={n_dec} >= {MIN_DIRECTIONAL_N}: oran yorumlanabilir"
                if n_dec >= MIN_DIRECTIONAL_N
                else (
                    f"n={n_dec} < {MIN_DIRECTIONAL_N}: YÖN İDDİASI YASAK. "
                    "Bu yalnız gözlemdir; oran veya 'backtest ile tutarlı' "
                    "yorumu yapılamaz."
                )
            )
        return {
            "total": total,
            "min_yon_orneklemi": MIN_DIRECTIONAL_N,
            "by_reason": out,
        }


def exit_kind_for(reason: str) -> str:
    """Çıkış nedeninin bekleme sınıfı ("hard" | "soft" | "none")."""
    if reason in _HARD_EXITS:
        return "hard"
    if reason in _SOFT_EXITS:
        return "soft"
    return "none"
