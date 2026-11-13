# HAVUZ DEMETİ · OPS

**Soru:** Operasyon: log, gözlem, kopma, yeniden başlatma ve silah bırakma (kill switch). Bir botu 7/24 ayakta tutmak için asgari ne gerekir?

Kanıt parçaları `dosya:satır` ile işaretlidir. Yalnızca bu kanıta dayan; kanıt yoksa 'veri yok' de, uydurma.

#### drive/toplama/arsiv-4/ACARBOT_V6.2_NORMAL__ic/ACARBOT_V6.2_NORMAL/app/main.py:860-866
```
        if config.portfolio.daily_soft_loss <= 0 and config.portfolio.daily_hard_loss <= 0:
            logger.info("Günlük zarar freni: KAPALI")
        # v5.0: hacim filtresi + boyutlama + stop korumaları afişte
        logger.info(
            "HACİM FİLTRESİ v5.0: taban hacim < %.2f USDT/sn → LİKİDİTE DÜŞÜK "
            "(bilgi, sinyal yok) | taban üstünde RVOL > %.0fx → RVOL ŞÜPHELİ "
            "(uyarı) | log aralığı %.0f sn/sembol",
```

#### drive/toplama/arsiv-4/ACARBOT_V6.2_NORMAL__ic/ACARBOT_V6.2_NORMAL/app/main.py:1537-1543
```
    Anahtar yoksa eşleme başlatılmaz ve uyarı loglanır (fail-closed).
    Kontrol listesi (para çekme izni KAPALI olmalı) loglanır.

    Dönüş: (LiveMirror, EmergencyController, RestartRecovery) veya (None,)*3.
    v3.0: OKX için de TAM emir eşlemesi (conditional algo stop dâhil);
    mirror durumu store.save_mirror_state/load_mirror_state ile kalıcıdır;
    RestartRecovery başlangıçta bağlanır (bayat emir iptali + stop restore).
```

#### drive/toplama/arsiv-4/ACARBOT_V6.2_NORMAL__ic/ACARBOT_V6.2_NORMAL/app/main.py:2049-2055
```
                logger.info("ANALİST | %s", obs)
            for sug in report["analyst"].get("suggestions", []):
                logger.info("ANALİST ÖNERİ | %s", sug)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Analist ajanı hatası (rapor etkilenmez): %s", exc)
    logger.info(
        "OTURUM RAPORU | süre=%.1f sn | bakiye %.2f → %.2f | equity %.2f\n%s",
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5_6_2__ic/ACARBOT_FINAL_v5.6.2/app/main.py:853-859
```
        if config.portfolio.daily_soft_loss <= 0 and config.portfolio.daily_hard_loss <= 0:
            logger.info("Günlük zarar freni: KAPALI")
        # v5.0: hacim filtresi + boyutlama + stop korumaları afişte
        logger.info(
            "HACİM FİLTRESİ v5.0: taban hacim < %.2f USDT/sn → LİKİDİTE DÜŞÜK "
            "(bilgi, sinyal yok) | taban üstünde RVOL > %.0fx → RVOL ŞÜPHELİ "
            "(uyarı) | log aralığı %.0f sn/sembol",
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5_6_2__ic/ACARBOT_FINAL_v5.6.2/app/main.py:1530-1536
```
    Anahtar yoksa eşleme başlatılmaz ve uyarı loglanır (fail-closed).
    Kontrol listesi (para çekme izni KAPALI olmalı) loglanır.

    Dönüş: (LiveMirror, EmergencyController, RestartRecovery) veya (None,)*3.
    v3.0: OKX için de TAM emir eşlemesi (conditional algo stop dâhil);
    mirror durumu store.save_mirror_state/load_mirror_state ile kalıcıdır;
    RestartRecovery başlangıçta bağlanır (bayat emir iptali + stop restore).
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5_6_2__ic/ACARBOT_FINAL_v5.6.2/app/main.py:2042-2048
```
                logger.info("ANALİST | %s", obs)
            for sug in report["analyst"].get("suggestions", []):
                logger.info("ANALİST ÖNERİ | %s", sug)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Analist ajanı hatası (rapor etkilenmez): %s", exc)
    logger.info(
        "OTURUM RAPORU | süre=%.1f sn | bakiye %.2f → %.2f | equity %.2f\n%s",
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5.3__ic/ACARBOT_FINAL_v5.3/app/main.py:807-813
```
        if config.portfolio.daily_soft_loss <= 0 and config.portfolio.daily_hard_loss <= 0:
            logger.info("Günlük zarar freni: KAPALI")
        # v5.0: hacim filtresi + boyutlama + stop korumaları afişte
        logger.info(
            "HACİM FİLTRESİ v5.0: taban hacim < %.2f USDT/sn → LİKİDİTE DÜŞÜK "
            "(bilgi, sinyal yok) | taban üstünde RVOL > %.0fx → RVOL ŞÜPHELİ "
            "(uyarı) | log aralığı %.0f sn/sembol",
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5.3__ic/ACARBOT_FINAL_v5.3/app/main.py:1484-1490
```
    Anahtar yoksa eşleme başlatılmaz ve uyarı loglanır (fail-closed).
    Kontrol listesi (para çekme izni KAPALI olmalı) loglanır.

    Dönüş: (LiveMirror, EmergencyController, RestartRecovery) veya (None,)*3.
    v3.0: OKX için de TAM emir eşlemesi (conditional algo stop dâhil);
    mirror durumu store.save_mirror_state/load_mirror_state ile kalıcıdır;
    RestartRecovery başlangıçta bağlanır (bayat emir iptali + stop restore).
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5.3__ic/ACARBOT_FINAL_v5.3/app/main.py:1992-1998
```
                logger.info("ANALİST | %s", obs)
            for sug in report["analyst"].get("suggestions", []):
                logger.info("ANALİST ÖNERİ | %s", sug)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Analist ajanı hatası (rapor etkilenmez): %s", exc)
    logger.info(
        "OTURUM RAPORU | süre=%.1f sn | bakiye %.2f → %.2f | equity %.2f\n%s",
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5.1 (1)__ic/ACARBOT_FINAL_v5.1/app/main.py:794-800
```
        if config.portfolio.daily_soft_loss <= 0 and config.portfolio.daily_hard_loss <= 0:
            logger.info("Günlük zarar freni: KAPALI")
        # v5.0: hacim filtresi + boyutlama + stop korumaları afişte
        logger.info(
            "HACİM FİLTRESİ v5.0: taban hacim < %.2f USDT/sn → LİKİDİTE DÜŞÜK "
            "(bilgi, sinyal yok) | taban üstünde RVOL > %.0fx → RVOL ŞÜPHELİ "
            "(uyarı) | log aralığı %.0f sn/sembol",
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5.1 (1)__ic/ACARBOT_FINAL_v5.1/app/main.py:1471-1477
```
    Anahtar yoksa eşleme başlatılmaz ve uyarı loglanır (fail-closed).
    Kontrol listesi (para çekme izni KAPALI olmalı) loglanır.

    Dönüş: (LiveMirror, EmergencyController, RestartRecovery) veya (None,)*3.
    v3.0: OKX için de TAM emir eşlemesi (conditional algo stop dâhil);
    mirror durumu store.save_mirror_state/load_mirror_state ile kalıcıdır;
    RestartRecovery başlangıçta bağlanır (bayat emir iptali + stop restore).
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5.1 (1)__ic/ACARBOT_FINAL_v5.1/app/main.py:1823-1829
```
                logger.info("ANALİST | %s", obs)
            for sug in report["analyst"].get("suggestions", []):
                logger.info("ANALİST ÖNERİ | %s", sug)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Analist ajanı hatası (rapor etkilenmez): %s", exc)
    logger.info(
        "OTURUM RAPORU | süre=%.1f sn | bakiye %.2f → %.2f | equity %.2f\n%s",
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5.0__ic/ACARBOT_FINAL_v5.0/app/main.py:756-762
```
        if config.portfolio.daily_soft_loss <= 0 and config.portfolio.daily_hard_loss <= 0:
            logger.info("Günlük zarar freni: KAPALI")
        # v5.0: hacim filtresi + boyutlama + stop korumaları afişte
        logger.info(
            "HACİM FİLTRESİ v5.0: taban hacim < %.2f USDT/sn → LİKİDİTE DÜŞÜK "
            "(bilgi, sinyal yok) | taban üstünde RVOL > %.0fx → RVOL ŞÜPHELİ "
            "(uyarı) | log aralığı %.0f sn/sembol",
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5.0__ic/ACARBOT_FINAL_v5.0/app/main.py:1433-1439
```
    Anahtar yoksa eşleme başlatılmaz ve uyarı loglanır (fail-closed).
    Kontrol listesi (para çekme izni KAPALI olmalı) loglanır.

    Dönüş: (LiveMirror, EmergencyController, RestartRecovery) veya (None,)*3.
    v3.0: OKX için de TAM emir eşlemesi (conditional algo stop dâhil);
    mirror durumu store.save_mirror_state/load_mirror_state ile kalıcıdır;
    RestartRecovery başlangıçta bağlanır (bayat emir iptali + stop restore).
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5.0__ic/ACARBOT_FINAL_v5.0/app/main.py:1753-1759
```
                logger.info("ANALİST | %s", obs)
            for sug in report["analyst"].get("suggestions", []):
                logger.info("ANALİST ÖNERİ | %s", sug)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Analist ajanı hatası (rapor etkilenmez): %s", exc)
    logger.info(
        "OTURUM RAPORU | süre=%.1f sn | bakiye %.2f → %.2f | equity %.2f\n%s",
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v4.0__ic/ACARBOT_FINAL_v4.0/app/main.py:240-246
```
def setup_logging(level: str) -> None:
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(fmt)
    # v3.0: log ROTASYONU — 7/24 oturumda paper_bot.log sınırsız büyümez
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v4.0__ic/ACARBOT_FINAL_v4.0/app/main.py:1398-1404
```
    Anahtar yoksa eşleme başlatılmaz ve uyarı loglanır (fail-closed).
    Kontrol listesi (para çekme izni KAPALI olmalı) loglanır.

    Dönüş: (LiveMirror, EmergencyController, RestartRecovery) veya (None,)*3.
    v3.0: OKX için de TAM emir eşlemesi (conditional algo stop dâhil);
    mirror durumu store.save_mirror_state/load_mirror_state ile kalıcıdır;
    RestartRecovery başlangıçta bağlanır (bayat emir iptali + stop restore).
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v4.0__ic/ACARBOT_FINAL_v4.0/app/main.py:1685-1691
```
                logger.info("ANALİST | %s", obs)
            for sug in report["analyst"].get("suggestions", []):
                logger.info("ANALİST ÖNERİ | %s", sug)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Analist ajanı hatası (rapor etkilenmez): %s", exc)
    logger.info(
        "OTURUM RAPORU | süre=%.1f sn | bakiye %.2f → %.2f | equity %.2f\n%s",
```

#### drive/toplama/arsiv-2/toplama 2/live_runner.py:233-239
```
    document.getElementById('bnStatus').textContent = `BINANCE: ${bn.healthy ? 'AKTİF' : 'BEKLİYOR'} (${((bn.ticks||0)+(bn.bbo_updates||0)).toLocaleString()} pkt | ${s.universe_counts.binance_pure} coin)`;
    document.getElementById('okxStatus').textContent = `OKX: ${ok.healthy ? 'AKTİF' : 'BEKLİYOR'} (${((ok.ticks||0)+(ok.bbo_updates||0)).toLocaleString()} pkt | ${s.universe_counts.okx_pure} coin)`;

    const opHealth = (s.analytics && s.analytics.operational_health) || {healthy:false, alarms:['ANALYTICS_YOK']};
    const hp = document.getElementById('healthPill');
    hp.textContent = opHealth.healthy ? `${opHealth.ledger_status === "IN_FLIGHT" ? "İŞLEM BEKLİYOR" : "MUTABAKAT: TAM"} (Lag ${opHealth.feed_lag_sec}s)` : `ALARM: ${opHealth.alarms.join(',')}`;
    hp.style.color = opHealth.healthy ? '#34d399' : '#ef4444';
```

#### drive/toplama/arsiv-2/toplama 2/live_runner.py:1503-1509
```
        if monitor: monitor.timing("analytics_snapshot_including_ledger", monotonic() - analytics_started)
        supervision = monitor.snapshot() if monitor else {"enabled": False, "alarms": [], "healthy": True}
        if supervision["alarms"]:
            op_h = dict(analytics.get("operational_health") or {})
            op_h["alarms"] = list(op_h.get("alarms") or []) + supervision["alarms"]
            op_h["healthy"] = False
            analytics = {**analytics, "operational_health": op_h}
```

#### drive/toplama/arsiv-2/toplama 2/live_runner.py:1644-1650
```
        monitor = self.runtime_supervision
        monitor.progress(getattr(self.engine, "metrics", {}).get("signals_evaluated", 0))
        monitor.check_tasks()
        before_mono, before_wall = monotonic(), time.time()
        await asyncio.sleep(seconds)
        monitor.sleep_observed(seconds, before_mono, before_wall)
        monitor.progress(getattr(self.engine, "metrics", {}).get("signals_evaluated", 0))
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v3.0__ic/ACARBOT_FINAL_v3.0/app/main.py:166-172
```
def setup_logging(level: str) -> None:
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(fmt)
    # v3.0: log ROTASYONU — 7/24 oturumda paper_bot.log sınırsız büyümez
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v3.0__ic/ACARBOT_FINAL_v3.0/app/main.py:925-931
```
    Anahtar yoksa eşleme başlatılmaz ve uyarı loglanır (fail-closed).
    Kontrol listesi (para çekme izni KAPALI olmalı) loglanır.

    Dönüş: (LiveMirror, EmergencyController, RestartRecovery) veya (None,)*3.
    v3.0: OKX için de TAM emir eşlemesi (conditional algo stop dâhil);
    mirror durumu store.save_mirror_state/load_mirror_state ile kalıcıdır;
    RestartRecovery başlangıçta bağlanır (bayat emir iptali + stop restore).
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v3.0__ic/ACARBOT_FINAL_v3.0/app/main.py:1168-1174
```
async def _report_events(alerts: AlertManager, events: list[dict]) -> None:
    for event in events:
        etype = event.get("type", "")
        if etype in {"ENTRY_FILLED", "OPEN", "PARTIAL_CLOSE", "CLOSE"}:
            alerts.notify_event(str(event))
        elif etype in {"MARGIN_WARNING", "GAP_BLOCKED", "FUNDING"}:
            alerts.notify(str(event), "warning")
```

#### drive/toplama/arsiv-2/V4_V78_KOD_ANALIZI_VE_RISK_ADAYI_20261031__ic/aday/ws_bot.py:71-77
```
DURUM_JSON = os.path.join(TABAN, "logs", "ws_durum.json")
TELEMETRI_CSV = os.path.join(TABAN, "logs", "ws_cikis_telemetri.csv")
GOLGE_CSV = os.path.join(TABAN, "logs", "ws_golge_cikis.csv")
AKIS_SINYAL_CSV = os.path.join(TABAN, "logs", "ws_akis_sinyal.csv")
AKIS_KAPANIS_CSV = os.path.join(TABAN, "logs", "ws_akis_kapanis.csv")
AKIS_GOLGE_OLAY_CSV = os.path.join(TABAN, "logs", "ws_akis_golge_olay.csv")
AKIS_GOLGE_KAPANIS_CSV = os.path.join(TABAN, "logs", "ws_akis_golge_kapanis.csv")
```

#### drive/toplama/arsiv-2/V4_V78_KOD_ANALIZI_VE_RISK_ADAYI_20261031__ic/aday/ws_bot.py:1944-1950
```
                        "uygulanan": getattr(self.funding_izleyici, "applied", 0),
                        "kapanmis_uygulanan": getattr(self.funding_izleyici, "closed_applied", 0),
                        "hata": getattr(self.funding_izleyici, "errors", 0),
                        "son_hata": getattr(self.funding_izleyici, "last_error", None),
                        "son_tarama_ms": getattr(self.funding_izleyici, "last_poll_ms", 0)},
            "kapi_sayaclari": getattr(self.detektor, "kapi_sayaclari", {}),
            "kapi_borsa": getattr(self.detektor, "kapi_borsa", {}),
```

#### drive/toplama/arsiv-2/V4_V78_KOD_ANALIZI_VE_RISK_ADAYI_20261031__ic/aday/ws_bot.py:2306-2312
```
                gorevler.append(asyncio.create_task(self.trend_paper_motor.run(), name='supertrend-paper-sinyal'))
            if self.funding_aktif:
                self.funding_izleyici = FundingWatcher(self.portfoy,
                    journal_path=os.path.join(TABAN, 'logs', 'funding_olaylari.csv'),
                    on_change=self._funding_state_kaydet,
                    on_materialize=self._funding_csv_mutabakat)
                gorevler.append(asyncio.create_task(self.funding_izleyici.run(oturum), name='funding'))
```

#### drive/toplama/arsiv-2/v37_vwap02_paper_paketi_20261030__ic/v37_vwap02_paper_paketi_20261030/ws_bot.py:69-75
```
DURUM_JSON = os.path.join(TABAN, "logs", "ws_durum.json")
TELEMETRI_CSV = os.path.join(TABAN, "logs", "ws_cikis_telemetri.csv")
GOLGE_CSV = os.path.join(TABAN, "logs", "ws_golge_cikis.csv")
AKIS_SINYAL_CSV = os.path.join(TABAN, "logs", "ws_akis_sinyal.csv")
AKIS_KAPANIS_CSV = os.path.join(TABAN, "logs", "ws_akis_kapanis.csv")
AKIS_GOLGE_OLAY_CSV = os.path.join(TABAN, "logs", "ws_akis_golge_olay.csv")
AKIS_GOLGE_KAPANIS_CSV = os.path.join(TABAN, "logs", "ws_akis_golge_kapanis.csv")
```

#### drive/toplama/arsiv-2/v37_vwap02_paper_paketi_20261030__ic/v37_vwap02_paper_paketi_20261030/ws_bot.py:1703-1709
```
                        "uygulanan": getattr(self.funding_izleyici, "applied", 0),
                        "kapanmis_uygulanan": getattr(self.funding_izleyici, "closed_applied", 0),
                        "hata": getattr(self.funding_izleyici, "errors", 0),
                        "son_hata": getattr(self.funding_izleyici, "last_error", None),
                        "son_tarama_ms": getattr(self.funding_izleyici, "last_poll_ms", 0)},
            "kapi_sayaclari": getattr(self.detektor, "kapi_sayaclari", {}),
            "kapi_borsa": getattr(self.detektor, "kapi_borsa", {}),
```

#### drive/toplama/arsiv-2/v37_vwap02_paper_paketi_20261030__ic/v37_vwap02_paper_paketi_20261030/ws_bot.py:1983-1989
```
                    log.info("%.2f dakikalik asıl test sayaci indikatör hazirligi tamamlandiktan sonra basladi",
                             self.sure_dk)
                else:
                    log.info("%.2f dakikalik tarama Binance on-dolgusundan sonra basladi", self.sure_dk)
                if self.v78_akis_motor is not None:
                    gorevler.append(asyncio.create_task(self.v78_akis_motor.run(), name='v78-akis-tetik'))
                    log.info('v7.8 esinli paper akış tetikleyicisi aktif; derinlik/likidasyon yok, haber nötr, ML yok')
```

#### drive/toplama/arsiv-2/kripto-bot-v9.4.4-Phase1-dogruluk-yamasi__ic/kripto-bot-v9.4.4/src/live_runner.py:231-237
```
    document.getElementById('bnStatus').textContent = `BINANCE: ${bn.healthy ? 'AKTİF' : 'BEKLİYOR'} (${((bn.ticks||0)+(bn.bbo_updates||0)).toLocaleString()} pkt | ${s.universe_counts.binance_pure} coin)`;
    document.getElementById('okxStatus').textContent = `OKX: ${ok.healthy ? 'AKTİF' : 'BEKLİYOR'} (${((ok.ticks||0)+(ok.bbo_updates||0)).toLocaleString()} pkt | ${s.universe_counts.okx_pure} coin)`;

    const opHealth = (s.analytics && s.analytics.operational_health) || {healthy:false, alarms:['ANALYTICS_YOK']};
    const hp = document.getElementById('healthPill');
    hp.textContent = opHealth.healthy ? `${opHealth.ledger_status === "IN_FLIGHT" ? "İŞLEM BEKLİYOR" : "MUTABAKAT: TAM"} (Lag ${opHealth.feed_lag_sec}s)` : `ALARM: ${opHealth.alarms.join(',')}`;
    hp.style.color = opHealth.healthy ? '#34d399' : '#ef4444';
```

#### drive/toplama/arsiv-2/kripto-bot-v9.4.4-Phase1-dogruluk-yamasi__ic/kripto-bot-v9.4.4/src/live_runner.py:1494-1500
```
        ok_feed = venue_feed_status(self.venue_stats["okx"], now_s, started_at=self.start_ts)
        feed_alarms = [f"{v.upper()}_{a}" for v, fs in (("binance", bn_feed), ("okx", ok_feed)) for a in fs["alarms"]]
        if feed_alarms:
            op_h = dict(analytics.get("operational_health") or {})
            op_h["alarms"] = list(op_h.get("alarms") or []) + feed_alarms
            op_h["healthy"] = False
            analytics = {**analytics, "operational_health": op_h}
```

#### drive/toplama/arsiv-2/kripto-bot-v9.4.4-Phase1-dogruluk-yamasi__ic/kripto-bot-v9.4.4/src/live_runner.py:1587-1593
```
            status_code = 200 if op["healthy"] else 503
            return web.json_response(
                {
                    "status": "ok" if op["healthy"] else "degraded",
                    "version": self.product_version,
                    "binance_healthy": st["venues"]["binance"]["healthy"],
                    "okx_healthy": st["venues"]["okx"]["healthy"],
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v2.0.1__ic/ACARBOT_FINAL_v2.0.1/app/main.py:34-40
```
from infra.feed import DataIntegrityManager
from infra.market_data.models import Candle
from monitor.report import PerformanceReporter, SimpleMetrics, utc_midnight_ms
from safety.alerts import AlertManager, TelegramNotifier
from state.store import StateStore

logger = logging.getLogger("paper_bot")
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v2.0.1__ic/ACARBOT_FINAL_v2.0.1/app/main.py:155-161
```
def setup_logging(level: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s"
    ))
    file_handler = logging.FileHandler("paper_bot.log", encoding="utf-8")
    file_handler.setFormatter(logging.Formatter(
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v2.0.1__ic/ACARBOT_FINAL_v2.0.1/app/main.py:1012-1018
```
async def _report_events(alerts: AlertManager, events: list[dict]) -> None:
    for event in events:
        etype = event.get("type", "")
        if etype in {"ENTRY_FILLED", "OPEN", "PARTIAL_CLOSE", "CLOSE"}:
            alerts.notify_event(str(event))
        elif etype in {"MARGIN_WARNING", "GAP_BLOCKED", "FUNDING"}:
            alerts.notify(str(event), "warning")
```

#### drive/toplama/arsiv-2/kripto-bot-v9.4.3-GUNCEL-r3__ic/kripto-bot-v9.4.3/src/live_runner.py:224-230
```
    document.getElementById('bnStatus').textContent = `BINANCE: ${bn.healthy ? 'AKTİF' : 'BEKLİYOR'} (${((bn.ticks||0)+(bn.bbo_updates||0)).toLocaleString()} pkt | ${s.universe_counts.binance_pure} coin)`;
    document.getElementById('okxStatus').textContent = `OKX: ${ok.healthy ? 'AKTİF' : 'BEKLİYOR'} (${((ok.ticks||0)+(ok.bbo_updates||0)).toLocaleString()} pkt | ${s.universe_counts.okx_pure} coin)`;

    const opHealth = (s.analytics && s.analytics.operational_health) || {healthy:false, alarms:['ANALYTICS_YOK']};
    const hp = document.getElementById('healthPill');
    hp.textContent = opHealth.healthy ? `${opHealth.ledger_status === "IN_FLIGHT" ? "İŞLEM BEKLİYOR" : "MUTABAKAT: TAM"} (Lag ${opHealth.feed_lag_sec}s)` : `ALARM: ${opHealth.alarms.join(',')}`;
    hp.style.color = opHealth.healthy ? '#34d399' : '#ef4444';
```

#### drive/toplama/arsiv-2/kripto-bot-v9.4.3-GUNCEL-r3__ic/kripto-bot-v9.4.3/src/live_runner.py:1487-1493
```
        ok_feed = venue_feed_status(self.venue_stats["okx"], now_s, started_at=self.start_ts)
        feed_alarms = [f"{v.upper()}_{a}" for v, fs in (("binance", bn_feed), ("okx", ok_feed)) for a in fs["alarms"]]
        if feed_alarms:
            op_h = dict(analytics.get("operational_health") or {})
            op_h["alarms"] = list(op_h.get("alarms") or []) + feed_alarms
            op_h["healthy"] = False
            analytics = {**analytics, "operational_health": op_h}
```

#### drive/toplama/arsiv-2/kripto-bot-v9.4.3-GUNCEL-r3__ic/kripto-bot-v9.4.3/src/live_runner.py:1571-1577
```
            status_code = 200 if op["healthy"] else 503
            return web.json_response(
                {
                    "status": "ok" if op["healthy"] else "degraded",
                    "version": self.product_version,
                    "binance_healthy": st["venues"]["binance"]["healthy"],
                    "okx_healthy": st["venues"]["okx"]["healthy"],
```
