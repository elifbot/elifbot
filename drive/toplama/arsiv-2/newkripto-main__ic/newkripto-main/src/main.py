"""KRIPTO-BOT ana programı — güvenlik odaklı asenkron işlem döngüsü (v7.2).

  • A) Multi-Exchange Failover (Borsa Kesinti Sigortası):
    - Birincil borsada (Binance) ardı ardına 3 timeout/ağ hatası gelirse işlem ağırlığı
      ve yeni pozisyonlar kesintisiz olarak yedek borsaya (OKX) kaydırılır.
  • B) SQLite WAL Modu & 24 Saatlik `VACUUM` Çöp Toplayıcı (Garbage Collector):
    - `bot_state.db` otomatik WAL modunda çalışır; her 24 saatte bir eski kayıtları
      `.jsonl.gz` arşivine sıkıştırır ve `VACUUM` ile veritabanı şişmesini önler.
  • C) Gerçek Zamanlı Metrikler (Prometheus `/metrics` & `/health` Endpoint):
    - Bulut sunucularda dış izleme araçlarının her saniye botun hayatta ve sağlıklı
      olduğunu kontrol etmesi için hafif HTTP `/health` ve `/metrics` sunar.
  • Sabit 50 USDT marj / 10x / 40 USDT stop + trailing ve order-flow kâr çıkışı
  • Güvenlik Zırhlaması + %0.30 Kayma Filtresi & Chase Order
  • İki Yönlü Telegram Botu (`/durum`, `/kill`, `/durdur`, `/baslat`, `/sigorta`)
  • WebSocket Keep-Alive (Ping/Pong) + Kopma Anında SQLite Durum Kurtarma

Çalıştırma:
    python -m src.main            (paper mod = sanal para, güvenli)
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

import pandas as pd

from .arbitrage import ArbitrageEngine
from .attribution import build_session_analysis, render_session_analysis
from .circuit_breaker import CircuitBreaker
from .config import BASE_DIR, TIMEFRAME_MS, load_config
from .derivatives_intel import DerivativesIntelEngine
from .exchanges import ExchangeManager
from .executor import Executor
from .health import HealthCheckServer
from .indicators import Indicators, indicator_score, multi_timeframe_filter
from .market_data import MarketData
from .ml_predictor import MLPredictor
from .moneyflow import MoneyFlow
from .news import NewsEngine
from .pdf_indicators import pdf_v2_snapshot
from .pdf_v3_prep import pdf_v3_snapshot
from .risk import RiskManager, position_limits_for_mode
from .security import is_auth_or_permission_error, mask_secrets, safe_exception_msg
from .shadow_lab import ShadowLab, render_shadow_report
from .sizing import PositionSizer
from .state_store import StateStore
from .strategy import Strategy
from .telegram import InteractiveTelegramBot, make_alerter



def ohlcv_to_df(
    rows: list,
    timeframe: str | None = None,
    now_ms: float | None = None,
) -> pd.DataFrame:
    """OHLCV verisini temizler ve oluşmakta olan son mumu güvenli biçimde atar.

    Sinyal/ML yalnızca kapanmış mumlarla üretilir; böylece aynı mum içinde
    değişen göstergeler (repaint) geçmiş performansı yapay olarak iyileştirmez.
    """
    columns = ["ts", "open", "high", "low", "close", "volume"]
    if not rows:
        return pd.DataFrame(columns=columns, dtype=float)
    df = pd.DataFrame(rows, columns=columns).astype(float)
    df = df.dropna().drop_duplicates(subset="ts", keep="last").sort_values("ts")
    if timeframe:
        if timeframe not in TIMEFRAME_MS:
            raise ValueError(f"Desteklenmeyen zaman dilimi: {timeframe}")
        current_ms = float(now_ms if now_ms is not None else time.time() * 1000)
        close_times = df["ts"] + TIMEFRAME_MS[timeframe]
        df = df.loc[close_times <= current_ms]
    return df.reset_index(drop=True)


def load_optimized_params(cfg: dict) -> dict | None:
    opt = cfg.get("optimizasyon", {})
    if not opt.get("otomatik_params"):
        return None
    p = Path(opt.get("params_dosyasi", "params_best.json"))
    if not p.is_absolute():
        p = BASE_DIR / p
    try:
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        print(
            f"⚠️ optimize params okunamadı ({safe_exception_msg(e)}), varsayılan kullanılıyor."
        )
    return None


class PaperSessionComplete(Exception):
    """Süreli paper oturumu raporu sonrası planlı kapanış."""


async def main():
    cfg = load_config()
    g, r, sn = cfg["genel"], cfg["risk"], cfg["sinyal"]
    pf, nw, hz = cfg["para_akisi"], cfg["haberler"], cfg["hiz"]
    bz, em = cfg.get("boyutlandirma", {}), cfg.get("emirler", {})
    sg = cfg.get("sigorta", {})
    ml_cfg = cfg.get("makine_ogrenmesi", {})
    plan_cfg = cfg.get("islem_plani", {})
    exit_cfg = cfg.get("cikis", {})
    arb_cfg = cfg.get("arbitraj", {})
    futures_cfg = cfg.get("futures", {})
    db_cfg = cfg.get("veritabani", {})
    hc_cfg = cfg.get("health_check", {})
    api = cfg["api"]
    symbols: list[str] = g["semboller"]
    exchanges: list[str] = g["borsalar"]
    mode = g["mod"]
    leverage = int(g.get("kaldıraç", bz.get("kaldirac", 20)) or 20)
    capital_pct = float(r.get("kasa_giris_yuzde", bz.get("kasa_yuzde", 10.0)))
    all_futures = (
        bool(futures_cfg.get("tum_pariteler", False))
        and leverage > 1
        and mode == "paper"
    )
    session_hours = float(os.getenv("PAPER_SESSION_HOURS", "0") or 0)
    if session_hours < 0:
        raise ValueError("PAPER_SESSION_HOURS negatif olamaz")
    if session_hours > 0 and mode != "paper":
        raise ValueError("Süreli oturum yalnız paper modunda kullanılabilir")

    op = load_optimized_params(cfg)
    if op:
        sn = {
            **sn,
            "agirlik_indikator": op.get("w_ind", sn["agirlik_indikator"]),
            "agirlik_para_akisi": op.get("w_flow", sn["agirlik_para_akisi"]),
            "agirlik_haber": op.get("w_news", sn["agirlik_haber"]),
            "long_esik": op.get("long_th", sn["long_esik"]),
            "short_esik": op.get("short_th", sn["short_esik"]),
            "cikis_esik": op.get("exit_th", sn["cikis_esik"]),
        }
        print(f"🧠 Walk-forward parametreleri yüklendi: {op.get('meta', {})}")

    broker = ExchangeManager(cfg)
    futures_info: dict = {"symbols": symbols, "support": {}, "errors": {}, "per_exchange": {}}
    if all_futures:
        print("🔎 Binance/OKX aktif USDT perpetual Futures katalogu yükleniyor...", flush=True)
        futures_info = await broker.discover_futures(
            preferred_symbols=symbols,
            min_leverage=int(futures_cfg.get("min_kaldirac", 10)),
            max_symbols=int(futures_cfg.get("max_parite", 0)),
            exclude_non_crypto=bool(futures_cfg.get("kripto_disi_filtre", True)),
        )
        symbols = list(futures_info["symbols"])
        # Executor/RiskManager dahil tüm alt sistemler aynı keşfedilmiş evreni kullanır.
        g["semboller"] = symbols
        print(
            f"✅ Futures evreni: {len(symbols)} parite | "
            + ", ".join(
                f"{name.upper()}={count}" for name, count in futures_info["per_exchange"].items()
            ),
            flush=True,
        )
        restricted_count = len(futures_info.get("restricted_leverage_symbols", []))
        if restricted_count:
            print(
                f"ℹ️ {restricted_count} parite {int(futures_cfg.get('min_kaldirac', 10))}x "
                "desteklemediği için yalnız analiz edilecek; işlem açılmayacak.",
                flush=True,
            )

    print("=" * 74)
    scope = f"{len(symbols)} USDT perpetual" if all_futures else ", ".join(symbols)
    print(f"🤖 KRIPTO-BOT v7.3 (PDF v3 + Türev İstihbaratı) başlatılıyor | MOD: {mode.upper()} | {scope}")
    plan_active = bool(plan_cfg.get("aktif", True))
    fixed_margin = float(bz.get("sabit_marj_usdt", 50.0))
    if bz.get("mod") == "sabit_usdt":
        sizing_desc = f"${fixed_margin:g} marj × sabit {leverage}x"
    elif plan_active:
        sizing_desc = f"%{r['islem_basina_risk_yuzde']:g} risk / ATR-swing stop"
    else:
        sizing_desc = f"%{capital_pct:g} marj × {leverage}x"
    if plan_active:
        stop_desc = "ATR + swing + 1R/2R"
    elif r.get("stop_modeli") == "marj":
        stop_desc = f"${fixed_margin * float(r.get('marj_zarar_orani', 0.8)):g} (marjın %{float(r.get('marj_zarar_orani', 0.8)) * 100:g})"
    else:
        stop_desc = f"%{r['stop_loss_yuzde']}"
    print(
        f"   Borsalar: {', '.join(exchanges)} (Multi-Exchange Failover AÇIK) | "
        f"Boyut: {sizing_desc} | Stop: {stop_desc} | "
        f"Max Kayma: %{r.get('max_kayma_yuzde', 0.30)}"
    )
    print(
        "   Altyapı: SQLite WAL + 24s VACUUM GC AÇIK | /health & /metrics AÇIK | "
        "Sır Maskeleme + .env İzolasyonu + İki Yönlü Telegram AÇIK"
    )
    print("=" * 74, flush=True)
    if mode == "live":
        print("⚠️  CANLI MOD: GERÇEK PARA ile işlem yapılacak! (devam etmek için 5 sn)")
        await asyncio.sleep(5)

    state_store = StateStore(
        BASE_DIR / os.getenv("BOT_DB_FILE", db_cfg.get("dosya", "bot_state.db")),
        maintenance_interval_sec=float(db_cfg.get("cop_toplayici_saniye", 86400.0)),
    )
    circuit_breaker = CircuitBreaker(
        max_consecutive_errors=int(sg.get("max_ardisik_emir_hatasi", 3)),
        daily_max_loss_pct=float(
            sg.get("gunluk_max_zarar_yuzde", r.get("gunluk_max_zarar_yuzde", 5.0))
        ),
        max_ws_disconnect_sec=float(sg.get("ws_kopma_saniye", 10.0)),
        flash_crash_pct=float(sg.get("flash_crash_yuzde", 8.0)),
        max_consecutive_auth_errors=int(sg.get("max_ardisik_yetki_hatasi", 3)),
        state_store=state_store,
        global_shock_symbols=sg.get("global_sok_sembolleri", ["BTC/USDT", "ETH/USDT"]),
        symbol_shock_cooldown_sec=float(sg.get("altcoin_sok_mola_saniye", 900.0)),
    )

    if mode == "paper":
        saved_paper = state_store.get_meta("paper_account", {}) or {}
        try:
            if "balance" in saved_paper:
                broker.paper.balance = float(saved_paper["balance"])
            broker.paper.total_fees_usdt = float(saved_paper.get("total_fees_usdt", 0.0))
            broker.paper.total_funding_usdt = float(saved_paper.get("total_funding_usdt", 0.0))
        except (TypeError, ValueError):
            print("⚠️ Paper hesap kaydı okunamadı; yapılandırılan başlangıç kasası kullanılıyor.")
        print(
            f"💰 Paper kasa: ${broker.paper.balance:,.2f} | "
            f"Başlangıç: ${broker.paper.start_balance:,.2f}",
            flush=True,
        )
    position_limits = position_limits_for_mode(r, mode)
    risk = RiskManager(
        stop_loss_pct=r["stop_loss_yuzde"],
        stop_model=r.get("stop_modeli", "fiyat_yuzde"),
        margin_stop_fraction=float(r.get("marj_zarar_orani", 0.80)),
        margin_stop_liq_buffer=float(r.get("marj_stop_likidasyon_tamponu", 0.85)),
        lock_trigger_pct=r["kar_kilit_tetikleyici"],
        lock_level_pct=r["kar_kilit_seviyesi"],
        trail_pct=r["trailing_yuzde"],
        risk_per_trade_pct=r["islem_basina_risk_yuzde"],
        max_positions=position_limits["max_positions"],
        daily_max_loss_pct=r["gunluk_max_zarar_yuzde"],
        capital_pct_per_entry=capital_pct,
        leverage=leverage,
        unlimited_pyramiding=bool(r.get("sinirsiz_ekleme", True)),
        pyramid_min_profit_pct=float(r.get("ekleme_min_kar_yuzde", 0.25)),
        pair_rescue_enabled=bool(r.get("capraz_kurtarma", True)),
        rescue_min_loser_pct=float(r.get("kurtarma_min_zarar_yuzde", 0.5)),
        max_slippage_pct=float(r.get("max_kayma_yuzde", 0.30)),
        dynamic_leverage_enabled=bool(r.get("dinamik_kaldirac", True)),
        atr_high_volatility_pct=float(r.get("atr_yuksek_oynaklik_yuzde", 1.5)),
        atr_extreme_volatility_pct=float(r.get("atr_asiri_oynaklik_yuzde", 3.0)),
        max_layers=int(r.get("max_kademe", 6)),
        hard_max_positions=position_limits["hard_max_positions"],
        max_same_side_positions=position_limits["max_same_side_positions"],
        max_total_margin_pct=float(r.get("toplam_marj_tavani_yuzde", 60.0)),
        weekly_max_loss_pct=float(r.get("haftalik_max_zarar_yuzde", 12.0)),
        liq_stop_buffer=float(r.get("likidasyon_stop_tamponu", 0.70)),
        state_store=state_store,
    )
    use_ml = bool(ml_cfg.get("aktif", True))
    strategy = Strategy(
        sn["agirlik_indikator"],
        sn["agirlik_para_akisi"],
        sn["agirlik_haber"],
        sn["long_esik"],
        sn["short_esik"],
        sn["cikis_esik"],
        g.get("short_izni", True),
        w_ml=float(sn.get("agirlik_ml", 0.15)) if use_ml else 0.0,
        flow_trigger=bool(sn.get("para_akisi_tetik", True)),
        flow_th=float(sn.get("para_akisi_esik", 50.0)),
        flow_ind_min=float(sn.get("tetik_indikator_min", 10.0)),
        flow_min_total=float(sn.get("tetik_min_toplam", 15.0)),
        regime_filter=bool(sn.get("rejim_bazli", True)),
        breakout_flow_confirmation=bool(sn.get("breakout_akim_onayi", True)),
        orderflow_filter=bool(sn.get("orderflow_onayi", True)),
        runner_exit=bool(exit_cfg.get("kosan_kar", True)),
    )

    size_mode = bz.get("mod", "kasa_10_20x")
    sizer = PositionSizer(
        base_risk_pct=r["islem_basina_risk_yuzde"],
        atr_mult=bz.get("atr_katsayi", 1.5),
        kelly_on=size_mode in ("kelly", "atr_kelly"),
        kelly_fraction=bz.get("kelly_kesir", 0.5),
        kelly_min_risk=bz.get("kelly_min_risk", 0.25),
        kelly_max_risk=bz.get("kelly_max_risk", 2.0),
        kelly_min_trades=bz.get("kelly_min_islem", 20),
        stats_path=BASE_DIR / "kelly_stats.json",
        mode=size_mode,
        capital_pct=capital_pct,
        leverage=leverage,
        fixed_margin_usdt=float(bz.get("sabit_marj_usdt", 50.0)),
    )

    mtf_cfg = cfg.get("mtf_filtre", {})
    notification_cfg = cfg.get("bildirimler", {})
    telegram_enabled = bool(notification_cfg.get("telegram_aktif", True))
    alert = make_alerter(
        api["telegram_token"] if telegram_enabled else "",
        api["telegram_chat"] if telegram_enabled else "",
        discord_webhook=(
            api.get("discord_webhook", "")
            if notification_cfg.get("discord_aktif", True)
            else ""
        ),
        pagerduty_routing_key=(
            api.get("pagerduty_routing_key", "")
            if notification_cfg.get("pagerduty_aktif", True)
            else ""
        ),
    )
    executor = Executor(
        broker,
        risk,
        strategy,
        sizer,
        alert,
        r["mola_saniye"],
        em.get("giris_tipi", "maker"),
        em.get("maker_zaman_asimi_sn", 3),
        em.get("borsa_korumasi", True),
        state_store=state_store,
        circuit_breaker=circuit_breaker,
        supertrend_trailing=bool(sn.get("supertrend_iz_takibi", True)),
        trade_plan_cfg=plan_cfg,
        runner_exit_cfg=exit_cfg,
        exit_fee_pct=float(em.get("komisyon_taker_yuzde", 0.05)),
        net_breakeven_enabled=bool(exit_cfg.get("net_basabas_aktif", False)),
        net_profit_buffer_usdt=float(exit_cfg.get("net_kar_tamponu_usdt", 0.0)),
        min_bb_width_pct=float(sn.get("min_bb_genisligi_yuzde", 0.0)),
        min_atr_pct=float(sn.get("min_atr_yuzde", 0.0)),
        dedup_twin_assets=bool(sn.get("ikiz_varlik_korumasi", True)),
    )
    tg_bot = InteractiveTelegramBot(
        token=api["telegram_token"] if telegram_enabled else "",
        allowed_chat_id=api["telegram_chat"] if telegram_enabled else "",
        executor=executor,
        circuit_breaker=circuit_breaker,
        broker=broker,
        state_store=state_store,
        periodic_reports=bool(
            telegram_enabled and notification_cfg.get("telegram_periyodik_rapor", True)
        ),
        report_interval_sec=float(notification_cfg.get("telegram_rapor_araligi_sn", 300)),
        initial_report_delay_sec=float(
            notification_cfg.get("telegram_ilk_rapor_gecikmesi_sn", 10)
        ),
        detailed_reports=bool(notification_cfg.get("telegram_detayli_rapor", False)),
    )

    paper_session: dict = {}
    if mode == "paper" and session_hours > 0:
        now = time.time()
        previous = (
            state_store.get_meta("paper_24h_session", {}) or {}
            if mode == "paper" and session_hours > 0
            else {}
        )
        if previous and not previous.get("report_sent"):
            paper_session = previous
        else:
            start_equity = broker.paper.balance + executor.total_unrealized_usdt()
            paper_session = {
                "start_ts": now,
                "end_ts": now + session_hours * 3600.0,
                "hours": session_hours,
                "start_balance": broker.paper.balance,
                "start_equity": start_equity,
                "start_fees": broker.paper.total_fees_usdt,
                "start_funding": broker.paper.total_funding_usdt,
                "symbol_count": len(symbols),
                "all_futures": all_futures,
                "entries": 0,
                "report_sent": False,
            }
        state_store.set_meta("paper_24h_session", paper_session)
        print(
            f"⏱️ Süreli paper oturumu: {session_hours:g} saat | "
            f"Başlangıç özsermayesi: ${paper_session['start_equity']:,.2f} | "
            f"Bitiş: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(paper_session['end_ts']))}",
            flush=True,
        )

    shadow_cfg = cfg.get("shadow_lab", {})
    shadow_lab: ShadowLab | None = None
    if shadow_cfg.get("aktif", False):
        if mode != "paper" or session_hours <= 0:
            raise ValueError("Shadow Lab yalnız süreli paper oturumunda etkinleştirilebilir")
        shadow_lab = ShadowLab(
            strategy=strategy,
            baseline_risk=risk,
            runner_exit_cfg=exit_cfg,
            supertrend_trailing=bool(sn.get("supertrend_iz_takibi", True)),
            fee_cfg=em,
            config={
                **shadow_cfg,
                "flow": {
                    "pencere_saniye": pf.get("pencere_saniye", 300),
                    **shadow_cfg.get("flow", {}),
                },
            },
        )
        executor.add_position_observer(shadow_lab)
        print(
            f"🧪 Shadow Lab aktif: {len(shadow_lab.variants)} izole varyant | ana strateji sabit | gerçek emir yok",
            flush=True,
        )

    def write_paper_checkpoint() -> None:
        """Erken iptalde dahi kanıt bırak; bunu nihai closeout raporu sayma.

        GitHub Actions iptali her zaman Python'un kontrollü kapanış bloğuna
        ulaşma fırsatı vermez. Bu nedenle periyodik dosyalar ayrı ``partial_``
        önekiyle yazılır; normal süre-sonu raporlarının yerine geçmez.
        """
        if not paper_session:
            return
        try:
            generated_at = time.time()
            trades = state_store.get_trades_since(float(paper_session["start_ts"]))
            analysis = build_session_analysis(trades)
            status = state_store.get_meta("bot_status", {}) or {}
            universe = status.get("futures_universe", {}) or {}
            analysis["exchange_evidence"] = {
                "catalog": universe.get("per_exchange", {}),
                "errors": universe.get("errors", {}),
                "rest": broker.rest_stats_snapshot(),
                "websocket": market.data_stats_snapshot(),
            }
            analysis["session"] = {
                **paper_session,
                "partial_checkpoint": True,
                "checkpoint_at": generated_at,
                "open_positions": len(executor.positions),
                "planned_closeout_completed": False,
            }
            analysis["paper_account"] = {
                "balance_usdt": broker.paper.balance,
                "equity_usdt": broker.paper.balance + executor.total_unrealized_usdt(),
                "total_fees_usdt": broker.paper.total_fees_usdt,
                "total_funding_usdt": broker.paper.total_funding_usdt,
            }
            report_dir = BASE_DIR / "reports"
            report_dir.mkdir(parents=True, exist_ok=True)

            def atomic_write(path: Path, text: str) -> None:
                temporary = path.with_name(path.name + ".tmp")
                temporary.write_text(text, encoding="utf-8")
                temporary.replace(path)

            shadow_report = shadow_lab.report() if shadow_lab is not None else None
            report_text = (
                "⚠️ ARA CHECKPOINT — ERKEN DURDURMA İHTİMALİ; NİHAİ RAPOR DEĞİL\n\n"
                + render_session_analysis(analysis)
            )
            if shadow_report is not None:
                shadow_report["partial_checkpoint"] = True
                shadow_report["planned_closeout_completed"] = False
                atomic_write(
                    report_dir / "partial_shadow_analysis.json",
                    json.dumps(shadow_report, ensure_ascii=False, indent=2, default=str),
                )
                atomic_write(
                    report_dir / "partial_shadow_report.md",
                    "⚠️ ARA CHECKPOINT — planlı Shadow closeout değildir.\n\n"
                    + render_shadow_report(shadow_report),
                )
            atomic_write(report_dir / "partial_gunluk.txt", report_text)
            atomic_write(
                report_dir / "partial_oturum_analizi.json",
                json.dumps(analysis, ensure_ascii=False, indent=2, default=str),
            )
            atomic_write(
                report_dir / "partial_islem_gecmisi.json",
                json.dumps(trades, ensure_ascii=False, indent=2, default=str),
            )
        except Exception as e:
            # Checkpoint raporlama yardımcısı ana işlem döngüsünü düşürmemeli.
            print(f"⚠️ Paper checkpoint yazılamadı: {safe_exception_msg(e)}", flush=True)

    initial_balance = broker.paper.balance if mode == "paper" else 0.0
    state_store.set_meta(
        "bot_status",
        {
            "ts": time.time(),
            "mode": mode.upper(),
            "primary_exchange": broker.primary,
            "balance_usdt": initial_balance,
            "equity_usdt": initial_balance + executor.total_unrealized_usdt(),
            "open_positions": len(executor.positions),
            "circuit_breaker": circuit_breaker.snapshot(),
            "exchange_health": broker.exchange_health_snapshot(),
            "sqlite_wal": state_store.get_wal_status(),
            "futures_universe": {
                "all_futures": all_futures,
                "symbol_count": len(symbols),
                "trade_symbol_count": len(futures_info.get("trade_symbols", symbols)),
                "analysis_only_symbols": futures_info.get("restricted_leverage_symbols", []),
                "per_exchange": futures_info.get("per_exchange", {}),
                "errors": futures_info.get("errors", {}),
            },
            "stats": executor.stats,
        },
    )

    # C) Bağımsız Gerçek Zamanlı /health & /metrics Sunucusu
    health_server: HealthCheckServer | None = None
    if hc_cfg.get("aktif", True):
        health_server = HealthCheckServer(
            state_store,
            host=str(hc_cfg.get("host", "0.0.0.0")),
            port=int(hc_cfg.get("port", 8502)),
        )
        try:
            await health_server.start()
            print(
                f"🩺 Sağlık & Prometheus sunucusu aktif: "
                f"http://{hc_cfg.get('host', '0.0.0.0')}:{hc_cfg.get('port', 8502)}/health & /metrics",
                flush=True,
            )
        except Exception:
            health_server = None

    flows = {
        s: MoneyFlow(
            s,
            pf["balina_esik_usdt"],
            pf["pencere_saniye"],
            pf["hacim_patlama_katsayi"],
            pf.get("likidasyon_squeeze_usdt", 50_000),
            book_depth_levels=int(pf.get("emir_defteri_kademe", 20)),
            divergence_min_price_pct=float(pf.get("divergence_min_fiyat_yuzde", 0.05)),
            absorption_min_usdt=float(pf.get("absorption_min_usdt", 25_000)),
            absorption_ratio=float(pf.get("absorption_oran", 1.5)),
            vpvr_window_sec=int(pf.get("vpvr_pencere_saniye", 21_600)),
            vpvr_bins=int(pf.get("vpvr_bin", 48)),
            compact_history=all_futures,
        )
        for s in symbols
    }
    ml_models = {
        s: MLPredictor(
            horizon=int(ml_cfg.get("ufuk_mum", 3)),
            min_train_bars=int(ml_cfg.get("min_egitim_mumu", 80)),
            retrain_every=int(ml_cfg.get("yeniden_egitim_araligi", 15)),
        )
        for s in symbols
    }
    arb = ArbitrageEngine(
        min_net_spread_pct=float(arb_cfg.get("min_net_kar_yuzde", 0.08)),
        fee_per_leg_pct=float(em.get("komisyon_taker_yuzde", 0.05)),
        trade_notional_usdt=float(arb_cfg.get("islem_tutari_usdt", 1000.0)),
        cooldown_sec=float(arb_cfg.get("mola_saniye", 10.0)),
        enabled=bool(arb_cfg.get("aktif", True)),
        state_store=state_store,
    )
    news = NewsEngine(
        nw["kaynaklar"],
        nw["kontrol_saniye"],
        api["cryptopanic_key"],
        fear_greed_on=nw.get("korku_acgozluluk", True),
        fear_veto_low=nw.get("korku_veto_alt", 15),
        greed_long_veto_high=nw.get("acgozluluk_long_veto_ust", 85),
        llm_url=api.get("llm_url", ""),
        llm_key=api.get("llm_key", ""),
        llm_model=api.get("llm_model", ""),
    )
    tg_bot.news_engine = news

    last_ind: dict[str, float] = {s: 0.0 for s in symbols}
    last_indicators: dict[str, dict] = {}
    last_candle_ts: dict[str, float] = {}
    last_btc_df: dict[str, pd.DataFrame | None] = {"df": None}
    last_squeeze_alert_ts: dict[str, float] = {}
    pdf_v3_cfg = cfg.get("pdf_v3", {})
    deriv_engine: DerivativesIntelEngine | None = (
        DerivativesIntelEngine(ttl_sec=float(pdf_v3_cfg.get("turev_cache_sn", 180.0)))
        if bool(pdf_v3_cfg.get("aktif", True) and pdf_v3_cfg.get("turev_istihbarat_aktif", True))
        else None
    )
    last_ml: dict[str, dict] = {
        s: {"score": 0.0, "prob_up": 0.5, "direction": "NOTR", "backend": "numpy_gbdt"}
        for s in symbols
    }
    live_scores: dict[str, dict] = {}
    tick_count = {"n": 0}
    t_start = time.time()

    # Paralel analizde iki sinyal aynı anda risk/marj kontrolünü geçemesin.
    signal_lock = asyncio.Lock()

    async def evaluate(s: str, price: float):
        ind = last_ind.get(s, 0.0)
        flow_snap = flows[s].snapshot()
        flow = flow_snap["score"]
        mood = news.mood()
        fg = mood.get("fear_greed", 50.0)
        veto_app = bool(mood.get("veto_approaching"))
        executor.set_market_mood(fear_greed=fg, veto_approaching=veto_app)
        dyn_lev, lev_why = executor.get_dynamic_leverage(s, price)

        fg_tilt = fg - 50.0
        news_blended = round(mood["score"] * 0.7 + fg_tilt * 0.6, 1)
        ml_info = last_ml.get(s, {})
        ml_sc = ml_info.get("score", 0.0) if use_ml else None
        market_context = {
            **last_indicators.get(s, {}),
            "cvd_slope": flow_snap.get("cvd_slope", 0.0),
            "cvd_divergence": flow_snap.get("cvd_divergence", "YOK"),
            "absorption": flow_snap.get("absorption", "YOK"),
            "oi_signal": flow_snap.get("oi_signal", "NOTR"),
            "oi_change_pct": flow_snap.get("oi_change_pct", 0.0),
            "price_change_pct": flow_snap.get("price_change_pct", 0.0),
        }
        combined = strategy.combine(
            ind, flow, news_blended, ml_sc, market_context=market_context
        )
        mtf_info = executor.get_mtf_trend(s) or (
            {
                "trend": "UNKNOWN",
                "score": 0.0,
                "allow_long": False,
                "allow_short": False,
            }
            if mtf_cfg.get("aktif", True)
            else {
                "trend": "NEUTRAL",
                "score": 0.0,
                "allow_long": True,
                "allow_short": True,
            }
        )

        live_scores[s] = {
            "symbol": s,
            **last_indicators.get(s, {}),
            "price": round(price, 4),
            "total": combined["total"],
            "signal": combined["signal"],
            "raw_signal": combined.get("raw_signal", combined["signal"]),
            "entry_allowed": combined.get("entry_allowed", True),
            "entry_block_reason": combined.get("entry_block_reason", ""),
            "indikator": round(ind, 1),
            "para_akisi": round(flow, 1),
            "haber": news_blended,
            "ml_skor": round(ml_sc or 0.0, 1),
            "ml_prob_up": ml_info.get("prob_up", 0.5),
            "ml_backend": ml_info.get("backend", "numpy_gbdt"),
            "fear_greed": fg,
            "dynamic_leverage": dyn_lev,
            "leverage_reason": lev_why,
            "active_exchange": broker.choose_symbol_exchange(s),
            "mtf_trend": mtf_info.get("trend", "NEUTRAL")
            if isinstance(mtf_info, dict)
            else str(mtf_info),
            "mtf_score": mtf_info.get("score", 0.0)
            if isinstance(mtf_info, dict)
            else 0.0,
            "bid_ask_ratio": flow_snap.get("bid_ask_ratio", 1.0),
            "wall_signal": flow_snap.get("wall_signal", "DENGELI"),
            "bid_depth_usdt": flow_snap.get("bid_depth_usdt", 0.0),
            "ask_depth_usdt": flow_snap.get("ask_depth_usdt", 0.0),
            "squeeze": flow_snap.get("squeeze", "YOK"),
            "oi": flow_snap.get("open_interest", 0.0),
            "oi_change_pct": flow_snap.get("oi_change_pct", 0.0),
            "oi_signal": flow_snap.get("oi_signal", "NOTR"),
            "oi_flow_confirmation": flow_snap.get("oi_flow_confirmation", "CVD_VERI_YOK"),
            "price_change_pct": flow_snap.get("price_change_pct", 0.0),
            "cvd_slope": flow_snap.get("cvd_slope", 0.0),
            "cvd_divergence": flow_snap.get("cvd_divergence", "YOK"),
            "absorption": flow_snap.get("absorption", "YOK"),
            "orderflow_veto": combined.get("orderflow_veto", ""),
            "vpvr_poc": flow_snap.get("vpvr_poc", 0.0),
            "vpvr_vah": flow_snap.get("vpvr_vah", 0.0),
            "vpvr_val": flow_snap.get("vpvr_val", 0.0),
            "vpvr_trades": flow_snap.get("vpvr_trades", 0),
            "vpvr_coverage_sec": flow_snap.get("vpvr_coverage_sec", 0.0),
            "vpvr_warm": flow_snap.get("vpvr_warm", False),
            "short_liq_usdt": flow_snap.get("short_liq_usdt", 0.0),
            "long_liq_usdt": flow_snap.get("long_liq_usdt", 0.0),
            "veto": bool(mood["veto"]),
        }
        if s in broker.leverage_restricted_symbols and s not in executor.positions:
            live_scores[s]["entry_allowed"] = False
            live_scores[s]["entry_block_reason"] = (
                f"Sabit {leverage}x desteklenmiyor; yalnız analiz"
            )
            return

        deriv_intel: dict = {}
        if (
            deriv_engine is not None
            and combined.get("signal") in ("LONG", "SHORT")
            and s not in executor.positions
        ):
            deriv_period = g.get("zaman_dilimi", "5m")
            if deriv_period not in ("5m", "15m", "30m", "1h", "4h"):
                deriv_period = "5m"
            deriv_intel = await deriv_engine.fetch_symbol_intel(s, period=deriv_period)
            if bool(pdf_v3_cfg.get("asiri_kalabalik_engeli", True)):
                crowding = (deriv_intel.get("crowding") or {}) if isinstance(deriv_intel, dict) else {}
                c_state = str(crowding.get("crowding_state") or "DENGELI")
                sm_div = str(crowding.get("smart_money_divergence") or "YOK")
                sig_now = combined.get("signal")
                retail_trap = (
                    sig_now == "LONG"
                    and c_state == "LONG_KALABALIK"
                    and sm_div == "TOP_TRADER_SHORT_PERAKENDE_LONG"
                ) or (
                    sig_now == "SHORT"
                    and c_state == "SHORT_KALABALIK"
                    and sm_div == "TOP_TRADER_LONG_PERAKENDE_SHORT"
                )
                if retail_trap:
                    executor.stats["crowding_filtered"] = (
                        executor.stats.get("crowding_filtered", 0) + 1
                    )
                    combined = {
                        **combined,
                        "signal": "BEKLE",
                        "entry_allowed": False,
                        "entry_block_reason": f"Türev kalabalık tuzağı ({c_state} / {sm_div})",
                    }
                    live_scores[s]["signal"] = "BEKLE"
                    live_scores[s]["entry_allowed"] = False
                    live_scores[s]["entry_block_reason"] = combined["entry_block_reason"]

        entry_context = {
            "indicators": last_indicators.get(s, {}),
            "combined": {
                key: combined.get(key)
                for key in (
                    "total", "signal", "raw_signal", "trigger", "entry_allowed",
                    "entry_block_reason", "orderflow_veto", "regime",
                )
                if key in combined
            },
            "orderflow": flow_snap,
            "derivatives_intel": deriv_intel,
            "news": mood,
            "mtf": mtf_info,
            "ml": ml_info,
            "decision_inputs": {
                "news_score": float(news_blended),
                "ml_score": ml_sc,
                "veto": bool(mood["veto"]) and nw.get("veto_guc", True),
                "veto_long": bool(mood.get("veto_long")),
                "veto_short": bool(mood.get("veto_short")),
            },
            "dynamic_leverage": {"value": dyn_lev, "reason": lev_why},
        }
        async with signal_lock:
            before_positions = set(executor.positions) if paper_session else set()
            await executor.on_signal(
                s,
                price,
                combined,
                flow,
                bool(mood["veto"]) and nw.get("veto_guc", True),
                bool(mood.get("veto_long")),
                bool(mood.get("veto_short")),
                mtf_trend=mtf_info,
                entry_context=entry_context,
            )
            if paper_session:
                new_positions = set(executor.positions) - before_positions
                if new_positions:
                    paper_session["entries"] = int(paper_session.get("entries", 0)) + len(new_positions)
                    state_store.set_meta("paper_24h_session", paper_session)

    def is_strategy_route(exchange: str, symbol: str) -> bool:
        """Bir sembolün sinyal/defter verisi yalnız işlem yaptığı borsadan gelir."""
        pos = executor.positions.get(symbol)
        selected = (
            (getattr(pos, "exchange", None) or exchanges[0])
            if pos is not None
            else broker.choose_symbol_exchange(symbol)
        )
        return exchange == selected

    async def on_trade(
        exchange: str, symbol: str, price: float, qty: float, buyer_maker: bool
    ):
        tick_count["n"] += 1
        if not is_strategy_route(exchange, symbol):
            return
        whale = flows[symbol].add_trade(price, qty, buyer_maker)
        pos = executor.positions.get(symbol)
        if pos is None or (getattr(pos, "exchange", None) or exchanges[0]) == exchange:
            await executor.on_price_tick(symbol, price)
            await executor.maybe_orderflow_exit(
                symbol,
                price,
                lambda: flows[symbol].snapshot(include_vpvr=False),
            )
            if shadow_lab is not None:
                shadow_lab.on_trade_tick(
                    symbol, price, flows[symbol].snapshot(include_vpvr=False)
                )
        if whale is not None:
            if notification_cfg.get("balina_uyarilari", False):
                await alert(
                    f"🐋 BALİNA {whale.side} {symbol}: "
                    f"${whale.notional_usdt:,.0f} @ {price:,.4f}"
                )
            # Bildirim kapalı olsa da balina/para akışı stratejiyi beslemeye devam eder.
            await evaluate(symbol, price)

    async def on_price(exchange: str, symbol: str, price: float):
        arb.update_quote(exchange, symbol, price, price)
        if is_strategy_route(exchange, symbol):
            await executor.on_price_tick(symbol, price)
            if shadow_lab is not None:
                shadow_lab.on_price_tick(symbol, price)
        opp = arb.check_opportunity(symbol)
        if opp:
            await arb.execute_arbitrage(opp, broker, alert)

    async def on_book(exchange: str, symbol: str, bids, asks):
        if is_strategy_route(exchange, symbol):
            flows[symbol].update_book(bids, asks)
        if bids and asks:
            arb.update_quote(exchange, symbol, float(bids[0][0]), float(asks[0][0]))
            opp = arb.check_opportunity(symbol)
            if opp:
                await arb.execute_arbitrage(opp, broker, alert)

    async def on_liquidation(
        exchange: str, symbol: str, side: str, price: float, qty: float
    ):
        if not is_strategy_route(exchange, symbol):
            return
        ev = flows[symbol].add_liquidation(side, price, qty)
        snap = flows[symbol].snapshot()
        if snap.get("squeeze") in ("SHORT_SQUEEZE", "LONG_SQUEEZE"):
            now_liq = time.time()
            min_single_liq = float(pf.get("squeeze_min_tekil_usdt", 25000.0))
            liq_cooldown = float(pf.get("squeeze_bildirim_mola_sn", 300.0))
            if (
                ev.notional_usdt >= min_single_liq
                and (now_liq - last_squeeze_alert_ts.get(symbol, 0.0)) >= liq_cooldown
            ):
                last_squeeze_alert_ts[symbol] = now_liq
                await alert(
                    f"💥 {snap['squeeze']} ALGILANDI | {symbol} | "
                    f"Tasfiye: ${ev.notional_usdt:,.0f} @ {price:,.4f}"
                )
            await evaluate(symbol, price)

    contract_sizes = await broker.get_contract_sizes()
    market = MarketData(
        symbols,
        exchanges,
        on_trade,
        on_price,
        on_book,
        hz["reconnect_saniye"],
        on_liquidation=on_liquidation,
        on_ws_heartbeat=circuit_breaker.heartbeat_ws,
        state_store=state_store,
        executor=executor,
        ping_interval_sec=float(hz.get("ws_ping_saniye", 15.0)),
        market_type=broker.default_type,
        contract_sizes=contract_sizes,
        symbol_exchanges=broker.symbol_exchanges,
        stream_batch_size=int(futures_cfg.get("ws_grup_boyutu", 50)),
        depth_update_ms=int(futures_cfg.get("ws_derinlik_guncelleme_ms", 100)),
    )

    async def reconcile_loop():
        """Açılışta ve her 5 dakikada bir bot kaydı ↔ borsa gerçeği mutabakatı (live/testnet)."""
        await asyncio.sleep(5)
        while True:
            try:
                await executor.reconcile_with_exchange()
            except Exception as e:
                print(f"⚠️ mutabakat hatası: {safe_exception_msg(e)}", flush=True)
            await asyncio.sleep(300)

    async def refresh_loop():
        await asyncio.sleep(3)
        refresh_semaphore = asyncio.Semaphore(
            int(futures_cfg.get("tarama_paralellik", 4))
        )
        while True:
            try:
                async def refresh_one(s: str):
                    async with refresh_semaphore:
                        try:
                            open_pos = executor.positions.get(s)
                            position_exchange = (
                                getattr(open_pos, "exchange", None) if open_pos else None
                            )
                            rows = await broker.fetch_ohlcv(
                                s, g["zaman_dilimi"], 300, exchange=position_exchange
                            )
                            df = ohlcv_to_df(rows, g["zaman_dilimi"])
                            if len(df) < 60:
                                raise ValueError(f"{s} için yeterli kapanmış mum yok ({len(df)}/60)")
                            candle_ts = float(df["ts"].iloc[-1])
                            is_new_candle = last_candle_ts.get(s) != candle_ts
                            funding = await broker.fetch_funding(
                                s, exchange=getattr(open_pos, "exchange", None) if open_pos else None
                            )

                            # ML ve göstergeler yalnızca yeni KAPANMIŞ mumda yeniden
                            # eğitilir/hesaplanır; 15 saniyelik yenileme mum sayısı değildir.
                            if is_new_candle:
                                if s.split(":", 1)[0] == "BTC/USDT":
                                    last_btc_df["df"] = df
                                ind = indicator_score(
                                    df,
                                    funding,
                                    regime_aware=bool(sn.get("rejim_bazli", True)),
                                    volume_z_threshold=float(sn.get("breakout_hacim_z_esik", 1.5)),
                                )
                                last_ind[s] = ind["score"]
                                pdf_cfg = cfg.get("pdf_v2", {})
                                pdf_shadow_cfg = shadow_cfg.get("pdf_confluence", {})
                                research = (
                                    pdf_v2_snapshot(df)
                                    if pdf_cfg.get("aktif", False) or pdf_shadow_cfg.get("aktif", False)
                                    else None
                                )
                                pdf_v3_shadow_cfg = shadow_cfg.get("pdf_v3_confluence", {})
                                v3_research = (
                                    pdf_v3_snapshot(
                                        df,
                                        btc_df=(
                                            last_btc_df["df"]
                                            if s.split(":", 1)[0] != "BTC/USDT"
                                            else None
                                        ),
                                    )
                                    if pdf_v3_cfg.get("aktif", True)
                                    or pdf_v3_shadow_cfg.get("aktif", False)
                                    else None
                                )
                                last_indicators[s] = {
                                    **ind.get("snapshot", {}),
                                    **({"pdf_v2": research} if research is not None else {}),
                                    **({"pdf_v3": v3_research} if v3_research is not None else {}),
                                    "components": ind.get("components", {}),
                                    "active_components": ind.get("active_components", {}),
                                    "active_score_unclipped": ind.get(
                                        "active_score_unclipped", ind["score"]
                                    ),
                                    "funding_rate": funding,
                                    "candle_ts": candle_ts,
                                }
                                snap = ind.get("snapshot", {})
                                executor.set_supertrend(
                                    s,
                                    int(snap.get("supertrend_direction", 1)),
                                    float(snap.get("supertrend", 0.0)),
                                )
                                if shadow_lab is not None:
                                    shadow_lab.set_supertrend(
                                        s,
                                        int(snap.get("supertrend_direction", 1)),
                                        float(snap.get("supertrend", 0.0)),
                                    )
                                    shadow_lab.update_market_frame(
                                        s, candle_ts, float(df["close"].iloc[-1])
                                    )
                                last_candle_ts[s] = candle_ts
                                if use_ml:
                                    last_ml[s] = ml_models[s].predict(df)

                                if mtf_cfg.get("aktif", True):
                                    try:
                                        rows_1h = await broker.fetch_ohlcv(
                                            s, "1h", 220, exchange=position_exchange
                                        )
                                        rows_4h = await broker.fetch_ohlcv(
                                            s, "4h", 220, exchange=position_exchange
                                        )
                                        mtf_res = multi_timeframe_filter(
                                            ohlcv_to_df(rows_1h, "1h"),
                                            ohlcv_to_df(rows_4h, "4h"),
                                            bearish_block_th=float(
                                                mtf_cfg.get("dusus_engelleme_esigi", -15.0)
                                            ),
                                            bullish_block_th=float(
                                                mtf_cfg.get("yukselis_engelleme_esigi", 15.0)
                                            ),
                                        )
                                        executor.set_mtf_trend(s, mtf_res)
                                    except Exception as mtf_error:
                                        # Trend bilinmiyorsa yeni girişleri iki yönde de
                                        # engelle; açık pozisyonların stop takibi sürer.
                                        executor.set_mtf_trend(
                                            s,
                                            {
                                                "trend": "UNKNOWN",
                                                "score": 0.0,
                                                "allow_long": False,
                                                "allow_short": False,
                                            },
                                        )
                                        print(
                                            f"⚠️ {s} MTF verisi alınamadı; girişler güvenli biçimde bloklandı: "
                                            f"{safe_exception_msg(mtf_error)}",
                                            flush=True,
                                        )

                                atr_s = Indicators.atr(
                                    df["high"], df["low"], df["close"], bz.get("atr_periyot", 14)
                                )
                                atr_value = float(atr_s.iloc[-1])
                                if pd.notna(atr_value) and atr_value > 0:
                                    executor.set_atr(s, atr_value)
                                    structure = df.tail(int(plan_cfg.get("swing_mum", 20)))
                                    executor.set_market_structure(
                                        s,
                                        float(structure["low"].min()),
                                        float(structure["high"].max()),
                                    )

                            route_exchange = (
                                getattr(open_pos, "exchange", None)
                                if open_pos is not None
                                else broker.choose_symbol_exchange(s)
                            )
                            price = market.get_price(s, route_exchange) or float(
                                df["close"].iloc[-1]
                            )
                            if mode == "paper":
                                executor.apply_funding(
                                    s, funding, price, enabled=broker.paper_funding_enabled
                                )
                                if shadow_lab is not None and broker.paper_funding_enabled:
                                    shadow_lab.apply_funding(s, funding, price)
                            oi = await broker.fetch_open_interest(
                                s, exchange=position_exchange
                            )
                            if oi is not None and oi > 0:
                                flows[s].update_open_interest(oi, price)
                            await evaluate(s, price)
                        except Exception as e:
                            err_msg = safe_exception_msg(e)
                            print(f"⚠️ {s} yenileme hatası: {err_msg}", flush=True)
                            # Veri okuma hatası emir hatası değildir. Yalnızca kimlik/
                            # yetki hataları sigortanın emir sayacına dahil edilir.
                            if is_auth_or_permission_error(e) and circuit_breaker.record_order_error(e):
                                await alert(f"🚨 SİGORTA ATTI: {circuit_breaker.trip_reason}")
                                await executor.close_all_positions(circuit_breaker.trip_reason)

                await asyncio.gather(
                    *(refresh_one(s) for s in symbols), return_exceptions=True
                )
                state_store.set_meta("live_scores", live_scores)
                bal = await broker.fetch_balance_usdt()
                unreal = executor.total_unrealized_usdt()
                state_store.record_equity(bal, bal + unreal, len(executor.positions))
                if mode == "paper":
                    state_store.set_meta(
                        "paper_account",
                        {
                            "balance": broker.paper.balance,
                            "start_balance": broker.paper.start_balance,
                            "total_fees_usdt": broker.paper.total_fees_usdt,
                            "total_funding_usdt": broker.paper.total_funding_usdt,
                            "realistic_execution": broker.paper_realistic,
                        },
                    )
                state_store.set_meta("arb_quotes", arb.scan_all(symbols))
                st = state_store.get_meta("bot_status", {}) or {}
                st.update(
                    {
                        "ts": time.time(),
                        "mode": mode.upper(),
                        "primary_exchange": broker.primary,
                        "balance_usdt": bal,
                        "equity_usdt": bal + unreal,
                        "open_positions": len(executor.positions),
                        "circuit_breaker": circuit_breaker.snapshot(),
                        "exchange_health": broker.exchange_health_snapshot(),
                        "sqlite_wal": state_store.get_wal_status(),
                        "stats": executor.stats,
                        "telegram": dict(tg_bot.report_stats),
                        "news": news.mood(),
                        "market_data": {
                            "market_type": broker.default_type,
                            "latency_ms": round(market.avg_latency_ms(), 1),
                            "last_message_ts": market.last_message_ts,
                            "reconnect_count": market.reconnect_count,
                            "per_exchange": market.data_stats_snapshot(),
                        },
                        "rest_data": broker.rest_stats_snapshot(),
                        "arb_total_profit": arb.total_profit_usdt,
                    }
                )
                state_store.set_meta("bot_status", st)
            except Exception as e:
                print(
                    f"⚠️ yenileme döngüsü hatası: {safe_exception_msg(e)}",
                    flush=True,
                )
            scan_delay = (
                float(futures_cfg.get("tarama_araligi_saniye", 300))
                if all_futures else hz["mum_yenileme_saniye"]
            )
            await asyncio.sleep(scan_delay)

    async def command_and_watchdog_loop():
        while True:
            await asyncio.sleep(1.0)
            try:
                if circuit_breaker.check_ws_health():
                    await alert(f"🚨 SİGORTA ATTI: {circuit_breaker.trip_reason}")
                    await executor.close_all_positions("WS >10 SN KOPMA SİGORTASI")

                cmds = state_store.pop_commands()
                for c in cmds:
                    name = c["cmd"]
                    pl = c.get("payload", {})
                    if name == "KILL_SWITCH":
                        circuit_breaker.trip("WEB PANELİ ACİL KILL-SWITCH")
                        await executor.close_all_positions(
                            "WEB PANELİ ACİL KILL-SWITCH"
                        )
                    elif name == "PAUSE":
                        circuit_breaker.set_paused(True)
                    elif name == "RESUME":
                        circuit_breaker.set_paused(False)
                    elif name == "RESET_BREAKER":
                        circuit_breaker.reset()
                    elif name == "RUN_GC":
                        state_store.run_garbage_collector()
                    elif name == "CLOSE_SYMBOL":
                        sym = pl.get("symbol")
                        if sym and sym in executor.positions:
                            pos = executor.positions[sym]
                            px = executor.last_prices.get(sym, pos.entry)
                            pnl = risk.profit_pct(pos, px)
                            closed = await executor._close(
                                sym, px, "WEB PANELİ MANUEL KAPAMA", pnl
                            )
                            if not closed:
                                await alert(f"⚠️ {sym} web paneli kapama emri başarısız; pozisyon takipte tutuluyor.")
            except Exception as e:
                # Özellikle kill-switch hataları sessizce yutulmamalı.
                print(f"⚠️ komut/watchdog hatası: {safe_exception_msg(e)}", flush=True)

    async def heartbeat():
        while True:
            await asyncio.sleep(60)
            up = int(time.time() - t_start)
            mood = news.mood()
            risk_pct, kinfo = sizer.risk_pct()
            parts = []
            data_rows = market.data_stats_snapshot()
            data_desc = " ".join(
                f"{name.upper()} t={int(row.get('trade_messages', 0))}"
                f"/b={int(row.get('book_messages', 0))}"
                for name, row in data_rows.items()
            )
            if all_futures:
                priced = sum(market.get_price(s) is not None for s in symbols)
                parts.append(f"Futures={len(symbols)} parite, fiyat akışı={priced}")
            else:
                for s in symbols:
                    p = market.get_price(s)
                    parts.append(f"{s}={p:,.2f}" if p else f"{s}=?")
            print(
                mask_secrets(
                    f"💓 {up // 60}dk | tick={tick_count['n']} | borsa={broker.primary.upper()} | "
                    f"gecikme={market.avg_latency_ms():.0f}ms | {data_desc} | "
                    f"haber={mood['score']:+.0f} FG={mood.get('fear_greed', 50):.0f} | "
                    f"mod=%{risk_pct:g}({kinfo.get('kaynak')}) | "
                    f"sigorta={circuit_breaker.snapshot()['status']} | "
                    f"açık={list(executor.positions)} | {' '.join(parts)} | "
                    f"istatistik={executor.stats}"
                ),
                flush=True,
            )
            write_paper_checkpoint()

    async def paper_session_loop():
        if not paper_session:
            return
        await asyncio.sleep(max(0.0, float(paper_session["end_ts"]) - time.time()))
        # Önce yeni girişleri durdur, sonra açık pozisyonları gerçekleşen
        # maliyetleriyle kapat. Böylece net oturum K/Z'si açık K/Z tahminine
        # dayanmaz ve her giriş bileşeni kapanmış işlem kohortunda ölçülür.
        circuit_breaker.set_paused(True)
        await executor.close_all_positions(
            "SÜRELİ PAPER ÖLÇÜMÜ SONU", urgent=False
        )
        shadow_report = None
        if shadow_lab is not None:
            shadow_lab.close_all("SÜRELİ PAPER ÖLÇÜMÜ SONU — SHADOW")
            shadow_report = shadow_lab.report()
            paper_session["shadow_closeout_completed"] = bool(
                shadow_report["closeout_completed"]
            )
        paper_session["closeout_open_positions"] = len(executor.positions)
        paper_session["closeout_completed"] = not executor.positions
        paper_session["closed_at"] = time.time()
        state_store.set_meta("paper_24h_session", paper_session)

        trades = state_store.get_trades_since(float(paper_session["start_ts"]))
        analysis = build_session_analysis(trades)
        status = state_store.get_meta("bot_status", {}) or {}
        universe = status.get("futures_universe", {}) or {}
        analysis["exchange_evidence"] = {
            "catalog": universe.get("per_exchange", {}),
            "errors": universe.get("errors", {}),
            "rest": broker.rest_stats_snapshot(),
            "websocket": market.data_stats_snapshot(),
        }
        analysis["session"] = dict(paper_session)
        report_text = (
            await tg_bot._format_daily_report()
            + "\n\n"
            + render_session_analysis(analysis)
        )
        report_dir = BASE_DIR / "reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime())
        report_path = report_dir / f"gunluk_{stamp}.txt"
        analysis_path = report_dir / f"oturum_analizi_{stamp}.json"
        trades_path = report_dir / f"islem_gecmisi_{stamp}.json"
        shadow_analysis_path = None
        shadow_report_path = None
        if shadow_report is not None:
            shadow_analysis_path = report_dir / f"shadow_analysis_{stamp}.json"
            shadow_report_path = report_dir / f"shadow_report_{stamp}.md"
            shadow_analysis_path.write_text(
                json.dumps(
                    shadow_report, ensure_ascii=False, indent=2,
                    default=str, allow_nan=False,
                ),
                encoding="utf-8",
            )
            shadow_report_path.write_text(
                render_shadow_report(shadow_report), encoding="utf-8"
            )
            shadow_summary = ["", "🧪 SHADOW LAB (ana strateji sabit)"]
            for variant in shadow_report["variants"]:
                stats = variant["analysis"]["overall"]
                shadow_summary.append(
                    f"{variant['name']}: {stats['count']} işlem | "
                    f"net {stats['net_pnl_usdt']:+.2f} USDT | "
                    f"ret {variant['rejected_entries']}"
                )
            report_text += "\n" + "\n".join(shadow_summary)
        report_path.write_text(report_text, encoding="utf-8")
        analysis_path.write_text(
            json.dumps(analysis, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        trades_path.write_text(
            json.dumps(trades, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        delivered = False
        for attempt in range(3):
            delivered = await tg_bot.send_daily_report(report_text)
            if delivered:
                break
            if attempt < 2:
                await asyncio.sleep(5)
        paper_session.update(
            {
                "report_sent": True,
                "report_delivered": delivered,
                "report_file": str(report_path),
                "analysis_file": str(analysis_path),
                "trades_file": str(trades_path),
                "shadow_analysis_file": (
                    str(shadow_analysis_path) if shadow_analysis_path else None
                ),
                "shadow_report_file": (
                    str(shadow_report_path) if shadow_report_path else None
                ),
                "reported_at": time.time(),
            }
        )
        state_store.set_meta("paper_24h_session", paper_session)
        print(
            f"📅 {float(paper_session.get('hours', 24)):g} saatlik oturum tamamlandı | "
            f"Kapanan={len(trades)} | Açık kalan={len(executor.positions)} | "
            f"Rapor: {report_path} | Telegram: {'gönderildi' if delivered else 'GÖNDERİLEMEDİ'}",
            flush=True,
        )
        if executor.positions:
            raise RuntimeError(
                f"Süre sonu kontrollü kapanış tamamlanmadı; açık pozisyonlar: {list(executor.positions)}"
            )
        if shadow_report is not None and not shadow_report["closeout_completed"]:
            raise RuntimeError("Shadow Lab kontrollü kapanışı tamamlanmadı")
        raise PaperSessionComplete()

    tasks = [
        asyncio.create_task(market.run_forever()),
        asyncio.create_task(news.run_forever()),
        asyncio.create_task(refresh_loop()),
        asyncio.create_task(reconcile_loop()),
        asyncio.create_task(command_and_watchdog_loop()),
        asyncio.create_task(tg_bot.poll_forever()),
        asyncio.create_task(tg_bot.periodic_report_forever()),
        asyncio.create_task(state_store.maintenance_loop()),
        asyncio.create_task(heartbeat()),
    ]
    if paper_session:
        tasks.append(asyncio.create_task(paper_session_loop()))
    try:
        await asyncio.gather(*tasks)
    except PaperSessionComplete:
        print("\n✅ Süreli paper oturumu planlandığı gibi tamamlandı.")
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("\n🛑 Bot durduruluyor...")
    finally:
        market.stop()
        news.stop()
        tg_bot.stop()
        if health_server:
            await health_server.stop()
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if mode == "paper" and paper_session and not paper_session.get("report_sent"):
            write_paper_checkpoint()
        if deriv_engine is not None:
            await deriv_engine.close()
        await broker.close()
        print(f"📊 Son istatistik: {executor.stats}")
        if mode == "paper":
            # Süreli oturumda kontrollü kapanış sonrası kasa ve işlem bazlı
            # net K/Z aynı gerçekleşen maliyetlerle mutabık olmalı. Manuel
            # durdurmada kalan açık pozisyonlar ayrı ve açıkça yazılır.
            unreal = executor.total_unrealized_usdt()
            equity = broker.paper.balance + unreal
            session_start_equity = float(
                (paper_session or {}).get(
                    "start_equity", broker.paper.start_balance
                )
            )
            print(f"💰 Kasa (paper): ${broker.paper.balance:,.2f}")
            print(
                "🧾 PAPER MUTABAKAT | "
                f"komisyon=${broker.paper.total_fees_usdt:,.4f} | "
                f"funding=${broker.paper.total_funding_usdt:+,.4f} | "
                f"açık K/Z=${unreal:+,.4f} | "
                f"özsermaye=${equity:,.4f} | "
                f"net oturum K/Z=${equity - session_start_equity:+,.4f} | "
                f"açık pozisyon={len(executor.positions)}",
                flush=True,
            )


if __name__ == "__main__":
    asyncio.run(main())
