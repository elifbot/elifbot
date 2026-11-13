from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path
import time

from src.config import load_config, validate_config
from src.exit_rules import stagnant_adverse_exit_reason
from src.futures_catalog import (
    build_futures_catalog,
    is_non_crypto_or_pegged_perp,
    perpetual_symbol,
)
from src.moneyflow import MoneyFlow
from src.risk import RiskManager, position_limits_for_mode
from src.strategy import Strategy
from src.trade_quality import (
    adjusted_flow_entry,
    exhaustion_guard,
    flow_confidence,
    rank_symbols_for_scan,
)
from tests.test_fixed_runner import FixedBroker, fixed_executor


def _swap_market(symbol: str, **extra) -> dict:
    row = {
        "symbol": symbol,
        "active": True,
        "swap": True,
        "contract": True,
        "linear": True,
        "quote": "USDT",
        "settle": "USDT",
        "limits": {"leverage": {"max": 25}},
    }
    row.update(extra)
    return row


def test_all_us_stocks_etfs_and_tradfi_perps_from_run_40179959680_are_filtered():
    non_crypto_seen = (
        "SQQQ/USDT", "TQQQ/USDT", "TSLL/USDT", "MSTU/USDT", "SMH/USDT",
        "SHOP/USDT", "MRVL/USDT", "MVLL/USDT", "MU/USDT", "MUU/USDT",
        "JNJ/USDT", "RIVN/USDT", "RKLB/USDT", "WDC/USDT", "CRCL/USDT",
        "CRDO/USDT", "IREN/USDT", "FLNC/USDT", "CIEN/USDT", "EWY/USDT",
        "TENCENT/USDT", "POPMART/USDT", "DRAM/USDT", "RAM/USDT", "HANMI/USDT",
        "INTW/USDT", "SHAZ/USDT", "SKUU/USDT", "SPCX/USDT", "SOXS/USDT",
        "ONDS/USDT", "MP/USDT", "MRNA/USDT", "MARA/USDT", "BTCDOM/USDT",
    )
    for bad in non_crypto_seen:
        assert is_non_crypto_or_pegged_perp(bad), f"{bad} elenmeliydi"
        assert perpetual_symbol(_swap_market(f"{bad}:USDT")) is None

    # Borsa metadata (liste halinde underlyingSubType ve INDEX underlyingType) kontrolü
    assert is_non_crypto_or_pegged_perp(
        "NEWCORP/USDT",
        {"info": {"underlyingType": "COIN", "underlyingSubType": ["RWA-Stock", "TradFi"]}},
    )
    assert is_non_crypto_or_pegged_perp(
        "BASKET1/USDT",
        {"info": {"underlyingType": "INDEX"}},
    )

    # Gerçek saf kripto pariteleri (STX, AI, ONDO, T, AR dahil) kesinlikle korunmalı
    pure_cryptos = (
        "BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "SUI/USDT",
        "TAO/USDT", "NEAR/USDT", "INJ/USDT", "AVAX/USDT", "STX/USDT",
        "AI/USDT", "ONDO/USDT", "AR/USDT", "T/USDT", "CELR/USDT", "BONK/USDT",
    )
    markets = {
        "binance": {
            sym: _swap_market(
                f"{sym}:USDT",
                info={"underlyingType": "COIN", "underlyingSubType": ["Layer-1"]},
            )
            for sym in pure_cryptos
        }
    }
    for bad in ("SQQQ/USDT", "TSLL/USDT", "MRVL/USDT", "TENCENT/USDT"):
        markets["binance"][bad] = _swap_market(f"{bad}:USDT")

    symbols, _ = build_futures_catalog(markets, preferred_symbols=["BTC/USDT", "ETH/USDT", "SOL/USDT"])
    assert set(symbols) == set(pure_cryptos)


def test_flow_confidence_blocks_cold_start_low_notional_and_accepts_warm_liquid_flow():
    strat = Strategy()
    cfg = {
        "pencere_saniye": 300.0,
        "min_islem_sayisi": 10,
        "min_kapsama_saniye": 60.0,
        "min_notional_usdt": 2500.0,
        "max_defter_yasi_saniye": 15.0,
        "referans_notional_usdt": 2500.0,
        "referans_cvd_usdt": 250.0,
    }
    # Run #40179959680 4/USDT soğuk başlangıç örneği: 7.2 sn, 7 işlem, $403 hacim
    cold_snap = {
        "score": -68.7,
        "score_unclipped": -68.7,
        "score_components": {"taker_delta": -38.35, "cvd_direction": -14.0, "orderbook_depth": -16.35},
        "buy_usdt": 17.5,
        "sell_usdt": 385.4,
        "cvd_slope": -236.9,
        "trade_count": 7,
        "window_coverage_sec": 7.2,
        "book_levels": 20,
        "book_age_sec": 2.5,
    }
    fc_cold = flow_confidence(cold_snap, cfg)
    assert fc_cold["data_ready"] is False
    cold_ctx = {
        "indicators": {"score": -53.4, "regime_aware": False},
        "orderflow": cold_snap,
        "mtf": {"trend": "BEARISH", "allow_long": False, "allow_short": True},
        "decision_inputs": {"news_score": 0.0, "ml_score": -24.0, "veto": False},
    }
    adj_cold = adjusted_flow_entry(strat, cold_ctx, "SHORT", fc_cold)
    assert adj_cold["accepted"] is False

    # Olgunlaşmış (270 sn, 45 işlem, $25,000 hacim) gerçek satış akışı kabul edilmeli
    mf = MoneyFlow("SOL/USDT")
    now = time.time()
    for i in range(45):
        mf.add_trade(150.0 - i * 0.01, 4.0, True, ts=now - 270 + i * 6)
    mf.update_book([[149.4, 50.0]] * 20, [[149.5, 180.0]] * 20, depth=20, ts=now - 0.5)
    warm_snap = mf.snapshot()
    fc_warm = flow_confidence(warm_snap, cfg)
    assert fc_warm["data_ready"] is True
    warm_ctx = {
        "indicators": {"score": -48.0, "regime_aware": False},
        "orderflow": warm_snap,
        "mtf": {"trend": "BEARISH", "allow_long": False, "allow_short": True},
        "decision_inputs": {"news_score": -5.0, "ml_score": -25.0, "veto": False},
    }
    adj_warm = adjusted_flow_entry(strat, warm_ctx, "SHORT", fc_warm)
    assert adj_warm["accepted"] is True


def test_rank_symbols_for_scan_eliminates_alphabetical_abc_bias():
    universe = [
        "4/USDT", "ACH/USDT", "ALLO/USDT", "BAS/USDT", "BICO/USDT",
        "BTC/USDT", "ETH/USDT", "SOL/USDT", "SUI/USDT", "XRP/USDT", "TAO/USDT",
    ]
    flows = {
        "4/USDT": {"buy_usdt": 17.0, "sell_usdt": 385.0, "window_coverage_sec": 7.2, "trade_count": 7},
        "ACH/USDT": {"buy_usdt": 50.0, "sell_usdt": 346.0, "window_coverage_sec": 12.0, "trade_count": 5},
        "XRP/USDT": {"buy_usdt": 420_000.0, "sell_usdt": 680_000.0, "window_coverage_sec": 290.0, "trade_count": 420},
        "SUI/USDT": {"buy_usdt": 180_000.0, "sell_usdt": 350_000.0, "window_coverage_sec": 285.0, "trade_count": 260},
        "TAO/USDT": {"buy_usdt": 95_000.0, "sell_usdt": 210_000.0, "window_coverage_sec": 260.0, "trade_count": 140},
    }
    scores = {
        "XRP/USDT": {"total": -62.0},
        "SUI/USDT": {"total": -58.0},
        "TAO/USDT": {"total": 57.0},
        "4/USDT": {"total": -45.6},
    }
    ranked = rank_symbols_for_scan(
        universe,
        preferred_symbols=["BTC/USDT", "ETH/USDT", "SOL/USDT"],
        open_positions=["TAO/USDT"],
        flow_snapshots=flows,
        live_scores=scores,
    )
    assert ranked[0] == "TAO/USDT"
    assert ranked[1:4] == ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
    assert ranked[4:6] == ["XRP/USDT", "SUI/USDT"]
    assert ranked.index("XRP/USDT") < ranked.index("4/USDT")
    assert ranked.index("SUI/USDT") < ranked.index("ACH/USDT")


def test_exhaustion_guard_and_paper_same_side_position_cap():
    # BTC/USDT Run #2 dip SHORT: RSI=23.8, MFI=13.7 -> engellenmeli
    btc_bottom = exhaustion_guard(
        {"rsi": 23.8, "mfi": 13.7}, {"squeeze": "YOK"}, "SHORT"
    )
    assert btc_bottom["accepted"] is False

    # CFX/USDT Run #2: RSI=27.1, MFI=5.3 -> RSI<=30 ve MFI<=18 ile engellenmeli
    cfx_bottom = exhaustion_guard(
        {"rsi": 27.1, "mfi": 5.3}, {"squeeze": "YOK"}, "SHORT"
    )
    assert cfx_bottom["accepted"] is False

    # Dipte pozitif RSI uyumsuzluğu -> SHORT engellenmeli
    div_bottom = exhaustion_guard(
        {"rsi": 31.5, "mfi": 28.0, "pdf_v2": {"values": {"rsi_divergence": 1}}},
        {"squeeze": "YOK"},
        "SHORT",
    )
    assert div_bottom["accepted"] is False

    # Gerçek LONG_SQUEEZE tasfiye şelalesi varsa SHORT engellenmez
    liq_cascade = exhaustion_guard(
        {"rsi": 24.0, "mfi": 12.0}, {"squeeze": "LONG_SQUEEZE"}, "SHORT"
    )
    assert liq_cascade["accepted"] is True

    # Aşırı alım tepesinde geç LONG engellenmeli
    overbought = exhaustion_guard(
        {"rsi": 76.2, "mfi": 85.0}, {"squeeze": "YOK"}, "LONG"
    )
    assert overbought["accepted"] is False

    # Sağlıklı orta bölgede trend girişi serbest
    healthy = exhaustion_guard(
        {"rsi": 42.0, "mfi": 38.0}, {"squeeze": "YOK"}, "SHORT"
    )
    assert healthy["accepted"] is True

    # Paper yön tavanı: 6 pozisyon sınırı
    limits = position_limits_for_mode(
        {
            "max_pozisyon": 3,
            "mutlak_max_pozisyon": 6,
            "ayni_yon_max_pozisyon": 4,
            "paper_genis_pozisyon_limiti": True,
            "paper_max_pozisyon": 10,
            "paper_ayni_yon_max_pozisyon": 6,
        },
        "paper",
    )
    assert limits == {
        "max_positions": 10,
        "hard_max_positions": 10,
        "max_same_side_positions": 6,
    }
    rm = RiskManager(
        max_positions=limits["max_positions"],
        hard_max_positions=limits["hard_max_positions"],
        max_same_side_positions=limits["max_same_side_positions"],
        unlimited_pyramiding=False,
    )
    assert rm.can_open(6, side="SHORT", open_sides=["SHORT"] * 6)[0] is False
    assert rm.can_open(6, side="LONG", open_sides=["SHORT"] * 6)[0] is True


def test_stagnant_adverse_exit_rescues_hostage_margin_without_touching_winners():
    broker = FixedBroker()
    executor = fixed_executor(broker)
    executor.runner_exit_cfg.update(
        {
            "kosan_kar": True,
            "erken_bozulma_cikisi_aktif": True,
            "erken_bozulma_min_dakika": 18.0,
            "erken_bozulma_uzatilan_dakika": 25.0,
            "erken_bozulma_min_zarar_yuzde": 0.25,
            "erken_bozulma_ters_skor": 12.0,
        }
    )
    asyncio.run(executor._open("CFX/USDT", "SHORT", 100.0, "TEST SHORT"))
    pos = executor.positions["CFX/USDT"]

    # 1) Henüz 5 dakika geçmişken kapatmamalı
    executor._position_opened_ts["CFX/USDT"] = time.time() - 5 * 60
    assert (
        stagnant_adverse_exit_reason(
            pos, 100.5, -0.50, 300.0, {"score": 30.0}, {"direction": 1}, {"total": 20.0}, executor.runner_exit_cfg
        )
        is None
    )

    # 2) 20 dakika geçmiş ama kârda olan pozisyona asla dokunmamalı
    assert (
        stagnant_adverse_exit_reason(
            pos, 99.2, +0.80, 1200.0, {"score": 30.0}, {"direction": 1}, {"total": 20.0}, executor.runner_exit_cfg
        )
        is None
    )

    # 3) 20 dakika geçmiş, ekside (-%0.50) ve birleşik skor ters yöne (+18) dönmüş -> marjı kurtar!
    executor._position_opened_ts["CFX/USDT"] = time.time() - 20 * 60
    executor.set_supertrend("CFX/USDT", 1, 99.8)
    asyncio.run(
        executor.on_signal(
            "CFX/USDT",
            100.50,
            {"total": 18.0, "signal": "BEKLE", "entry_allowed": True},
            flow_score=25.0,
            veto=False,
        )
    )
    assert "CFX/USDT" not in executor.positions
    assert executor.stats["stagnant_adverse_exits"] == 1
    assert executor.in_cooldown("CFX/USDT") is True


def test_v74_control_profile_merges_and_validates_cleanly():
    cfg = copy.deepcopy(load_config())
    control = json.loads(
        Path("configs/paper-60-v2-control.json").read_text(encoding="utf-8")
    )

    def _deep_merge(dst: dict, src: dict) -> None:
        for k, v in src.items():
            if isinstance(v, dict) and isinstance(dst.get(k), dict):
                _deep_merge(dst[k], v)
            else:
                dst[k] = v

    _deep_merge(cfg, control["overrides"])
    validate_config(cfg)
    assert cfg["para_akisi"]["canli_akis_guveni_aktif"] is False
    assert cfg["para_akisi"]["hafif_akis_teyidi_aktif"] is True
    assert cfg["para_akisi"]["anlik_akis_tetik_aktif"] is True
    assert cfg["para_akisi"]["baslangic_isinma_saniye"] == 35.0
    assert cfg["sinyal"]["tukenme_korumasi_aktif"] is True
    assert cfg["sinyal"]["yatay_akis_engeli_aktif"] is True
    assert cfg["sinyal"]["teknik_uyum_aktif"] is True
    assert cfg["sinyal"]["likidasyon_miknatis_aktif"] is True
    assert cfg["cikis"]["erken_bozulma_cikisi_aktif"] is False
    assert cfg["risk"]["marj_modu"] == "cross"
    assert cfg["risk"]["firsat_takasi_aktif"] is False
    assert cfg["risk"]["paper_max_pozisyon"] == 6
    assert cfg["risk"]["erken_kar_kilit_tetik"] == 0.24
    assert cfg["risk"]["zirve_kar_koruma_min_usdt"] == 1.25
    assert cfg["risk"]["paper_ayni_yon_max_pozisyon"] == 4
    assert cfg["sinyal"]["kazanan_cekirdek_aktif"] is True


def test_v76_two_stage_net_profit_shield_and_aaoi_stock_filter():
    from src.risk import Position

    # Run #3'te sızan OKX optik/AI ABD hisse kontratları elenmeli
    for stock_sym in ("AAOI/USDT", "COHR/USDT", "LITE/USDT", "VRT/USDT", "ALAB/USDT"):
        assert is_non_crypto_or_pegged_perp(stock_sym) is True

    # 2 Kademeli Net Kâr Kalkanı: +%0.50 (+$2.50) gören işlem bir daha asla eksiye dönemez!
    rm = RiskManager(
        stop_model="marj",
        margin_stop_fraction=0.80,
        leverage=10,
        early_lock_trigger_pct=0.50,
        early_lock_level_pct=0.12,
        lock_trigger_pct=0.90,
        lock_level_pct=0.30,
        trail_pct=1.50,
    )
    pos = Position(
        "SYN/USDT",
        "SHORT",
        100.0,
        5.0,
        108.0,
        leverage=10,
        margin_usdt=50.0,
        entry_fee_usdt=0.25,
        exit_fee_pct=0.05,
        net_breakeven_enabled=True,
        net_profit_buffer_usdt=0.05,
    )
    # 1. Kademe: +%0.53 düşüşte (+$2.65 MFE) stop komisyon üstü net kâra (<= 99.88) iner
    rm.update(pos, 99.47)
    assert pos.locked_profit is True
    assert pos.stop <= 99.88
    # 2. Kademe: +%0.95 düşüşte stop <= 99.70 seviyesine sıkılaşır
    rm.update(pos, 99.05)
    assert pos.stop <= 99.70


def test_net_flow_inflow_and_outflow_outrank_wash_volume():
    symbols = ["WASH/USDT", "INFLOW/USDT", "OUTFLOW/USDT"]
    flows = {
        "WASH/USDT": {
            "buy_usdt": 60_000.0,
            "sell_usdt": 60_000.0,
            "score": 0.0,
            "window_coverage_sec": 95.0,
            "trade_count": 120,
        },
        "INFLOW/USDT": {
            "buy_usdt": 95_000.0,
            "sell_usdt": 5_000.0,
            "score": 89.5,
            "window_coverage_sec": 95.0,
            "trade_count": 140,
        },
        "OUTFLOW/USDT": {
            "buy_usdt": 8_000.0,
            "sell_usdt": 88_000.0,
            "score": -82.0,
            "window_coverage_sec": 95.0,
            "trade_count": 135,
        },
    }
    ranked = rank_symbols_for_scan(
        symbols, open_positions=set(), flow_snapshots=flows, live_scores={}
    )
    assert ranked == ["INFLOW/USDT", "OUTFLOW/USDT", "WASH/USDT"]


def test_cross_margin_common_pool_expands_with_unrealized_pnl_and_never_freezes_at_60pct():
    broker = FixedBroker()
    executor = fixed_executor(broker)
    executor.risk.margin_mode = "cross"
    executor.risk.cross_max_margin_pct = 95.0
    executor.risk.cross_min_free_usdt = 50.0
    executor.risk.max_positions = 100
    executor.risk.hard_max_positions = 100
    executor.risk.max_same_side_positions = 25
    executor.opportunity_swap_enabled = True
    executor.opportunity_swap_min_age_sec = 480.0

    # Eski izole %60 tavanında 12. işlemden ($600) sonra kilitlenirdi;
    # Çapraz Ortak Kasada 18 işleme ($900) kadar kesintisiz eklemeye devam eder!
    for idx in range(18):
        sym = f"COIN{idx}/USDT"
        asyncio.run(executor._open(sym, "LONG", 100.0, "PARA_GIRISI"))
        # Simulate an actual receipt; a fill alone is not a market quote.
        asyncio.run(executor.on_price_tick(sym, 100.0))
    assert len(executor.positions) == 18

    # Açık işlemler kâra geçtiğinde (+%3 fiyat = +$15/işlem -> +$270 açık kâr)
    # Ortak Kasa $1,000 -> $1,270 üstüne çıkar ve yeni sinyallere anında kapasite açar!
    for idx in range(18):
        asyncio.run(executor.on_price_tick(f"COIN{idx}/USDT", 103.0))
    assert executor.total_unrealized_usdt() > 250.0

    for idx in range(18, 22):
        sym = f"COIN{idx}/USDT"
        asyncio.run(executor._open(sym, "LONG", 100.0, "PARA_GIRISI"))
        asyncio.run(executor.on_price_tick(sym, 100.0))
    assert len(executor.positions) == 22


def test_cross_margin_opportunity_swap_replaces_stagnant_trade_when_pool_full():
    broker = FixedBroker()
    executor = fixed_executor(broker)
    executor.risk.margin_mode = "cross"
    executor.risk.cross_max_margin_pct = 95.0
    executor.risk.cross_min_free_usdt = 50.0
    executor.risk.max_positions = 100
    executor.risk.hard_max_positions = 100
    executor.risk.max_same_side_positions = 25
    executor.opportunity_swap_enabled = True
    executor.opportunity_swap_min_age_sec = 480.0

    # 19 pozisyon ($950 aktif teminat = %95 kapasite) açalım
    for idx in range(19):
        sym = f"SLOT{idx}/USDT"
        asyncio.run(executor._open(sym, "LONG", 100.0, "PARA_GIRISI"))
        asyncio.run(executor.on_price_tick(sym, 100.5))  # taze piyasa verisi
        executor._position_opened_ts[sym] = time.time() - 600.0

    # Yalnız SLOT3/USDT 12 dakikadır durgun/hafif ekside (-%0.30) bekliyor olsun
    asyncio.run(executor.on_price_tick("SLOT3/USDT", 99.70))
    executor._position_opened_ts["SLOT3/USDT"] = time.time() - 720.0
    asyncio.run(executor.on_price_tick("SUI/USDT", 100.0))

    # 20. güçlü sinyal geldiğinde kilitlenmek yerine durgun SLOT3'ü kapatıp SUI/USDT açmalı!
    asyncio.run(executor._open("SUI/USDT", "LONG", 100.0, "ANLIK_PARA_GIRISI"))
    assert "SLOT3/USDT" not in executor.positions
    assert "SUI/USDT" in executor.positions
    assert executor.stats["opportunity_swaps"] == 1


def test_whatsapp_module_and_multichannel_alerter_integration():
    from src.alerts import MultiChannelAlerter
    from src.security import mask_secrets
    from src.whatsapp import (
        is_whatsapp_configured,
        normalize_whatsapp_phone,
        whatsapp_message_chunks,
    )

    assert normalize_whatsapp_phone("0532 111 22 33") == "905321112233"
    assert normalize_whatsapp_phone("+90 (532) 111-22-33") == "905321112233"
    assert is_whatsapp_configured() is False
    assert is_whatsapp_configured(phone="05321112233", api_key="654321") is True

    empty_alerter = MultiChannelAlerter()
    assert empty_alerter.status()["whatsapp"] is False
    assert asyncio.run(empty_alerter("test mesajı")) == {}

    wa_alerter = MultiChannelAlerter(
        whatsapp_phone="+905321112233",
        whatsapp_api_key="***REDACTED***",
    )
    assert wa_alerter.status()["whatsapp"] is True
    masked = mask_secrets("Key=wa-secret-9988 Tel=+905321112233")
    assert "wa-secret-9988" not in masked
    assert "905321112233" not in masked

    chunks = whatsapp_message_chunks("Satır bilgisi\n" * 200, max_len=500)
    assert len(chunks) > 4
    assert all(len(c) <= 500 for c in chunks)


def test_v77_mfe_giveback_shield_and_atr_trailing_and_liq_magnet():
    from src.config import load_config
    from src.risk import Position, RiskManager
    from src.trade_quality import light_flow_sanity_check, liquidation_magnet_guard

    cfg = load_config("config.yaml")
    # 1) 2. Deneme akış motoru açık olmalı ($2,500 hacim boğması KAPALI)
    assert cfg["para_akisi"]["canli_akis_guveni_aktif"] is False
    assert cfg["para_akisi"]["hafif_akis_teyidi_aktif"] is True

    # Orta ölçekli altcoin kazananı (örn. CELR/CHILLGUY/BONK/OL: 4 işlem, $520 hacim, 20sn kapsama)
    alt_winner_flow = {
        "window_coverage_sec": 20.5,
        "trade_count": 4,
        "buy_usdt": 40.0,
        "sell_usdt": 480.0,
    }
    assert light_flow_sanity_check(alt_winner_flow, cfg["para_akisi"])["accepted"] is True

    # Soğuk başlangıç boş paketi (4sn, 1 işlem, $35 hacim) elenmeli
    cold_packet = {
        "window_coverage_sec": 4.0,
        "trade_count": 1,
        "buy_usdt": 35.0,
        "sell_usdt": 0.0,
    }
    assert light_flow_sanity_check(cold_packet, cfg["para_akisi"])["accepted"] is False

    # 2) Dinamik Zirve Kâr Kalkanı (+$1.75 üstünde %48 MFE kilidi)
    rm = RiskManager(
        stop_model="marj",
        margin_stop_fraction=0.80,
        leverage=10,
        early_lock_trigger_pct=0.50,
        early_lock_level_pct=0.12,
        lock_trigger_pct=0.90,
        lock_level_pct=0.30,
        trail_pct=1.50,
        mfe_lock_min_usdt=1.75,
        mfe_lock_keep_ratio=0.48,
        atr_trail_mult=2.2,
    )
    # 50 USDT × 10x = $500 büyüklük (entry=100, qty=5)
    pos_long = Position(
        symbol="ASTR/USDT",
        side="LONG",
        entry=100.0,
        qty=5.0,
        stop=92.0,
        leverage=10,
        margin_usdt=50.0,
        atr_pct=1.1,
    )
    # Fiyat 100.726 (+$3.63 brüt MFE) gördüğünde %48 = +$1.7424 (stop=100.3485) kilitlenmeli!
    res_peak = rm.update(pos_long, 100.726)
    assert res_peak["action"] == "hold"
    assert pos_long.locked_profit is True
    assert pos_long.stop >= 100.348  # +$1.74 brüt kâr garanti (Stage-1 +%0.12'nin yaklaşık 3 katı!)

    # SHORT SAFE/USDT senaryosu: +$1.81 MFE (entry=100, price=99.638) -> +%48 ($0.87) kilitlenmeli
    pos_short = Position(
        symbol="SAFE/USDT",
        side="SHORT",
        entry=100.0,
        qty=5.0,
        stop=108.0,
        leverage=10,
        margin_usdt=50.0,
    )
    rm.update(pos_short, 99.638)
    assert pos_short.locked_profit is True
    assert pos_short.stop <= 99.827  # asla eksiye dönmesine izin vermez

    # 3) 50x-100x Likidasyon Mıknatısı Kalkanı
    trap_ind = {
        "pdf_v3": {
            "liq_clusters": {
                "long_liq_zones": [99.88],
                "short_liq_zones": [101.50],
                "magnet_bias": -1,
            }
        }
    }
    blocked = liquidation_magnet_guard(
        trap_ind, {"score": 52.0, "squeeze": "YOK"}, "LONG", 100.0, cfg["sinyal"]
    )
    assert blocked["accepted"] is False
    # Ezici balina/squeeze kırılımında (>=68) engellemez
    allowed_breakout = liquidation_magnet_guard(
        trap_ind, {"score": 74.0, "squeeze": "SHORT_SQUEEZE"}, "LONG", 100.0, cfg["sinyal"]
    )
    assert allowed_breakout["accepted"] is True



