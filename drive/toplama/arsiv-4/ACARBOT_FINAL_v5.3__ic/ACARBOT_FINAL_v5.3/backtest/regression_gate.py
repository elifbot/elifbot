"""v5.1 — SÜRÜM REGRESYON KAPISI.

SORUN
-----
v5.0 paketindeki `docs/backtest_gercek_veri.json` v3.0/v4.0'tan kalma bir
sonuçtu ve v5.0 ile YENİDEN ÜRETİLMEMİŞTİ. Belge eski sayıları yeni sürümün
kanıtı gibi sunuyordu. Bunu insan gözüyle fark etmek zorunda değil.

ÇÖZÜM
-----
`docs/backtest_referans.json` bir "kanıt parmak izi" taşır:
  • version         — paketin `__version__` değeri
  • generated_at    — üretim zamanı
  • dataset         — sembol sayısı, gün, bar sayısı, veri parmak izi
  • cost_model      — maliyetler açık mı, ölçülmüş mü
  • fixture_metrics — ÇEVRİMDIŞI, deterministik sentetik veri kümesinin
                      metrikleri (CI ağ olmadan yeniden üretebilir)
  • real_metrics    — gerçek veri koşusunun metrikleri (provenans)

Kapı şunları ZORUNLU kılar:
  1. referans sürümü paket sürümüyle AYNI (bayat sonuç → KIRMIZI)
  2. maliyetler AÇIK (iyimser backtest → KIRMIZI)
  3. deterministik fixture metrikleri YENİDEN ÜRETİLEBİLİYOR
     (motor davranışı değiştiyse → KIRMIZI, referans güncellenmeli)
  4. veri kümesi çok sembollü ve uzun (tek sembol 7 gün → UYARI/KIRMIZI)

Kapı kârlılık İDDİA ETMEZ; sadece kanıtın güncel ve yeniden üretilebilir
olmasını şart koşar. Kârlılık hükmü `tools/validate_strategy.py`'dedir.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from infra.market_data.models import Candle

REFERENCE_PATH = "docs/backtest_referans.json"
MIN_SYMBOLS = 3
MIN_DAYS = 90
FIXTURE_TOLERANCE = 1e-6


@dataclass
class GateResult:
    ok: bool = True
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def fail(self, message: str) -> None:
        self.ok = False
        self.failures.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def as_dict(self) -> dict:
        return {
            "ok": self.ok, "failures": list(self.failures),
            "warnings": list(self.warnings),
        }


# ----------------------------------------------------------------------
# Deterministik fixture — ağ gerektirmez, CI'da yeniden üretilebilir
# ----------------------------------------------------------------------

def build_fixture(bars: int = 400) -> dict[str, list[Candle]]:
    """Sabit, tekrarlanabilir sentetik veri: FADE sinyali üreten dip çevrimleri.

    Rastgelelik YOK; aynı kod her zaman aynı mumları üretir. Amaç gerçek
    piyasa taklidi değil, motor davranışının parmak izini almaktır.
    Şekil, canlıda doğrulanmış FADE kurulumunu taklit eder: uzun yatay
    seyir → hacim patlamalı sert dip → temas mumu (maker dolumu).
    """
    out: dict[str, list[Candle]] = {}
    base_ms = 1_699_999_800_000  # 5m ızgarasına hizalı
    for index, symbol in enumerate(("okx:FIXA-USDT-SWAP", "okx:FIXB-USDT-SWAP")):
        candles: list[Candle] = []
        level = 100.0 + index * 25.0
        for i in range(bars):
            phase = i % 40
            cycle = i // 40
            losing_cycle = cycle % 3 == 2  # her üçüncü çevrim stopla biter
            if losing_cycle and 33 <= phase <= 35:
                open_price = level * (0.975 - (phase - 33) * 0.012)
                close = level * (0.963 - (phase - 33) * 0.012)
                volume = 300.0
            elif phase == 30:
                open_price, close = level, level * 0.982
                volume = 10.0
            elif phase == 31:
                open_price, close = level * 0.982, level * 0.980
                volume = 40.0
            elif phase == 32:
                open_price, close = level * 0.980, level * 0.9795
                volume = 500.0
            else:
                open_price = close = level
                volume = 10.0
            spread = max(abs(close - open_price), level * 0.001)
            high = max(open_price, close) + spread * 0.15
            low = min(open_price, close) - spread * 0.15
            candles.append(Candle(
                timestamp=base_ms + i * 300_000,
                open=open_price, high=high, low=low, close=close,
                volume=volume,
            ))
        out[symbol] = candles
    return out


def dataset_fingerprint(candles_by_symbol: dict[str, list[Candle]]) -> str:
    """Veri kümesinin kararlı parmak izi (sıra bağımsız)."""
    digest = hashlib.sha256()
    for symbol in sorted(candles_by_symbol):
        digest.update(symbol.encode("utf-8"))
        for candle in candles_by_symbol[symbol]:
            digest.update(
                f"{candle.timestamp}|{candle.open:.10g}|{candle.high:.10g}|"
                f"{candle.low:.10g}|{candle.close:.10g}|{candle.volume:.10g};".encode(),
            )
    return digest.hexdigest()


def canonical_config():
    """Fixture'ın KANONİK profili — paketin varsayılan APEX ayarları.

    Kapı, çağıranın config'inden bağımsız olarak her zaman bu profili
    kullanır; aksi hâlde aynı referans farklı profillerle farklı sonuç
    üretir ve kapı yanlış alarm verir.
    """
    from app.main import apply_profile, build_parser
    from core.config import SuperConfig

    # Tam CLI varsayılanları: apply_profile çok sayıda bayrağa bakar,
    # eksik Namespace AttributeError verirdi.
    args = build_parser().parse_args(["--mode", "paper", "--paper", "--profile", "apex"])
    return apply_profile(args, SuperConfig())


def run_fixture(config=None) -> dict:
    """Deterministik fixture'ı maliyet açık koşar ve metrikleri döndürür."""
    from backtest.costs import CostModel
    from backtest.engine import BacktestEngine
    from backtest.metrics import compute_metrics

    config = config if config is not None else canonical_config()
    candles = build_fixture()
    engine = BacktestEngine(config, initial_balance=1_000.0)
    result = engine.run(candles, cost_model=CostModel())
    metrics = compute_metrics(
        list(result.trades), 1_000.0, result.final_balance, result.equity_curve,
    )
    def _finite(value):
        # Sonsuz profit_factor (hiç kayıp yok) JSON'da taşınamaz; 0.0 = tanımsız
        try:
            from math import isfinite

            return value if isfinite(float(value)) else 0.0
        except (TypeError, ValueError):
            return value

    return {
        "fingerprint": dataset_fingerprint(candles),
        "net_pnl": round(result.net_pnl, 6),
        "trade_count": result.trade_count,
        "final_balance": round(result.final_balance, 6),
        "win_rate": round(metrics.win_rate, 6),
        "profit_factor": round(_finite(metrics.profit_factor), 6),
        "rejection_counts": dict(sorted(result.rejection_counts.items())),
        "cost_model_source": result.cost_model.get("source"),
        "risk_audit_max_ratio": result.risk_audit.get(
            "max_realized_over_target", 0.0,
        ),
    }


# ----------------------------------------------------------------------
# Kapı
# ----------------------------------------------------------------------

def check_reference(
    reference: dict, current_version: str,
    fixture: dict | None = None, strict_dataset: bool = True,
) -> GateResult:
    result = GateResult()
    if not reference:
        result.fail("Referans dosyası boş veya okunamadı")
        return result

    ref_version = str(reference.get("version", ""))
    if ref_version != current_version:
        result.fail(
            f"BAYAT REFERANS: referans sürümü '{ref_version}' != paket "
            f"sürümü '{current_version}'. Backtest bu sürümle yeniden "
            f"koşulmalı ve referans güncellenmeli "
            f"(python3 -m tools.make_reference).",
        )

    costs = reference.get("cost_model") or {}
    if costs.get("optimistic_warning") or not costs.get("enabled", True):
        result.fail(
            "Referans backtest MALİYETSİZ koşulmuş (spread/kayma/gecikme "
            "kapalı). İyimser sonuç kanıt sayılamaz.",
        )
    if costs.get("source") != "measured":
        result.warn(
            "Maliyetler ölçülmemiş; muhafazakâr varsayım kullanılmış. "
            "tools/measure_costs.py ile ölçüm alınmalı.",
        )

    dataset = reference.get("dataset") or {}
    symbols = int(dataset.get("symbols", 0))
    days = int(dataset.get("days", 0))
    if symbols < MIN_SYMBOLS or days < MIN_DAYS:
        message = (
            f"Veri kümesi yetersiz: {symbols} sembol / {days} gün "
            f"(en az {MIN_SYMBOLS} sembol / {MIN_DAYS} gün gerekli)."
        )
        if strict_dataset:
            result.fail(message)
        else:
            result.warn(message)

    recorded = reference.get("fixture_metrics") or {}
    if not recorded:
        result.fail("Referansta deterministik fixture metrikleri yok")
        return result
    actual = fixture if fixture is not None else run_fixture()
    for key in (
        "fingerprint", "trade_count", "net_pnl", "final_balance",
        "win_rate", "profit_factor",
    ):
        if key not in recorded:
            result.fail(f"Fixture metriği eksik: {key}")
            continue
        expected, got = recorded[key], actual.get(key)
        if isinstance(expected, (int, float)) and isinstance(got, (int, float)):
            if abs(float(expected) - float(got)) > FIXTURE_TOLERANCE:
                result.fail(
                    f"Fixture metriği değişti: {key} referans={expected} "
                    f"şimdi={got}. Motor davranışı değişmiş — referans "
                    f"bilinçli olarak güncellenmeli.",
                )
        elif expected != got:
            result.fail(
                f"Fixture metriği değişti: {key} referans={expected} şimdi={got}",
            )
    if recorded.get("rejection_counts") != actual.get("rejection_counts"):
        result.fail(
            "Red sayaçları değişti — sinyal kapıları veya filtreler "
            "değişmiş olabilir. Referans gözden geçirilmeli.",
        )
    return result


def load_reference(path: str | Path = REFERENCE_PATH) -> dict:
    target = Path(path)
    if not target.exists():
        return {}
    return json.loads(target.read_text(encoding="utf-8"))


def make_reference(
    current_version: str, real_report: dict | None = None,
    config=None,
) -> dict:
    """Referans dosyasını üretir. `real_report` = validate_strategy çıktısı."""
    # Kapı her zaman kanonik profille ölçer (çağıran config'i yok sayılır)
    fixture = run_fixture(canonical_config())
    reference = {
        "version": current_version,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fixture_metrics": fixture,
        "note": (
            "Bu dosya bir KANIT PARMAK İZİDİR. fixture_metrics çevrimdışı "
            "yeniden üretilebilir; real_metrics gerçek veri koşusunun "
            "sonucudur. Sürüm değişince yeniden üretilmelidir."
        ),
    }
    if real_report:
        primary = (real_report.get("runs") or [{}])[0]
        reference["dataset"] = real_report.get("dataset", {})
        reference["cost_model"] = real_report.get("cost_model", {})
        reference["profile"] = real_report.get("profile")
        reference["target_net_risk"] = real_report.get("target_net_risk")
        reference["real_metrics"] = {
            "net_pnl": primary.get("net_pnl"),
            "trade_count": primary.get("trade_count"),
            "metrics": primary.get("metrics", {}),
            "monte_carlo": primary.get("monte_carlo", {}),
            "risk_audit": primary.get("risk_audit", {}),
            "path_source": primary.get("path_source"),
            # v5.2: WF ve kapsama da parmak izine girer — hukumun
            # dayandigi kanit referansla birlikte dondurulur.
            "walk_forward": primary.get("walk_forward", {}),
            "intrabar": primary.get("intrabar", {}),
            "risk_scaling": primary.get("risk_scaling", {}),
            "label": primary.get("label"),
        }
        reference["verdict"] = real_report.get("verdict")
        reference["verdict_detail"] = real_report.get("verdict_detail", {})
        reference["fine_pass"] = real_report.get("fine_pass", {})
        reference["bounds_interval"] = real_report.get("bounds_interval", {})
        reference["optimism_gap"] = real_report.get("optimism_gap", {})
        reference["cost_coverage"] = real_report.get("cost_coverage", {})
        reference["cost_quality"] = real_report.get("cost_quality", {})
    else:
        reference["dataset"] = {"symbols": 0, "days": 0}
        from backtest.costs import CostModel

        reference["cost_model"] = CostModel().as_dict()
        reference["real_metrics"] = {}
        reference["verdict"] = (
            "Gerçek veri koşusu YAPILMADI — yalnızca fixture parmak izi var."
        )
    return reference

# ----------------------------------------------------------------------
# v5.2: RAPOR TUTARLILIK KAPISI
# ----------------------------------------------------------------------
# Kullanıcı tespiti: v5.1 raporu "örneklem yetersiz" diyordu ama aynı
# raporun walk-forward bölümü 0/6 kârlı pencere ve -433 USDT gösteriyordu.
# Bu kapı, hükmün raporun KENDİ verisiyle çelişmesini yakalar. Böylece
# hüküm metni elle düzenlenirse veya bayatlarsa pipeline kırılır.

def check_report_consistency(report: dict) -> GateResult:
    """Doğrulama raporunun iç tutarlılığını denetler."""
    from backtest.verdict import decide

    result = GateResult()
    if not report:
        result.fail("Rapor boş veya okunamadı")
        return result

    runs = report.get("runs") or []
    if not runs:
        result.fail("Raporda hiç koşu yok")
        return result

    detail = report.get("verdict_detail") or {}
    if not detail.get("code"):
        result.fail(
            "Rapor yapılandırılmış hüküm taşımıyor (verdict_detail.code yok). "
            "v5.2 öncesi raporlar hükmün kanıtla çelişip çelişmediğini "
            "denetleyemez.",
        )
    else:
        recomputed = decide(
            runs,
            min_trades=int(
                (detail.get("evidence") or {}).get("min_trades", 200),
            ),
            min_wf_trades=int(
                (detail.get("evidence") or {}).get("min_wf_trades", 30),
            ),
            cost_model=report.get("cost_model"),
            min_trades_source=str(
                (detail.get("evidence") or {}).get("min_trades_source", "all"),
            ),
        )
        if recomputed.code != detail["code"]:
            result.fail(
                f"HÜKÜM TUTARSIZ: raporda '{detail['code']}' yazıyor ama "
                f"raporun kendi verisi '{recomputed.code}' gerektiriyor. "
                f"Rapor bayat veya hüküm elle değiştirilmiş.",
            )

    primary = runs[0]
    intrabar = primary.get("intrabar") or {}
    coverage = float(intrabar.get("real_coverage_ratio", 0.0))
    label = str(primary.get("label", ""))
    if coverage <= 0 and "gercek 1m yol" in label.replace("ç", "c"):
        result.fail(
            "ETİKET YALANI: koşu 'gerçek 1m yol' diyor ama "
            "real_coverage_ratio = 0.0.",
        )
    if coverage <= 0:
        result.warn(
            "Mum içi yol gerçek 1m verisiyle DOĞRULANMADI "
            "(kapsama %0). Sonuç sentetik yola dayanıyor.",
        )

    for block in runs:
        wf = block.get("walk_forward") or {}
        if not wf:
            continue
        if not isinstance(wf.get("total_windows"), int):
            result.fail(
                "walk_forward.total_windows sayı olmalı "
                f"(bulunan: {type(wf.get('total_windows')).__name__}).",
            )
        windows = wf.get("windows")
        if not isinstance(windows, list):
            result.fail("walk_forward.windows liste olmalı.")

    costs = report.get("cost_model") or {}
    if costs.get("source") == "measured":
        symbols = (report.get("dataset") or {}).get("symbol_list") or []
        measured = set(costs.get("measured_slippage_bps") or {})
        missing = [s for s in symbols if s not in measured]
        if missing:
            result.warn(
                f"{len(missing)}/{len(symbols)} sembol ölçülmedi; "
                f"borsa varsayımı kullanıldı: {', '.join(missing[:5])}",
            )
    quality = report.get("cost_quality") or {}
    if quality.get("grade") == "thin":
        result.warn(
            "Maliyet ölçüm tabanı İNCE; küçük coinlerde kayma daha kötü "
            "olabilir. Sonuçlar bu yönde iyimser.",
        )

    bounds = report.get("bounds_interval") or {}
    if not bounds:
        result.warn(
            "Sentetik alt/üst sınır koşuları yok (--bounds kapalı). "
            "Mum içi belirsizlik aralığı raporlanmamış.",
        )
    elif bounds.get("spans_zero"):
        result.warn(
            "Sentetik sınır aralığı sıfırı kapsıyor: tek sayı ile "
            "kârlılık iddia edilemez.",
        )
    if not report.get("optimism_gap"):
        result.warn(
            "Maliyetsiz karşılaştırma yok (--compare-no-costs kapalı); "
            "iyimserlik farkı görünmüyor.",
        )
    return result
