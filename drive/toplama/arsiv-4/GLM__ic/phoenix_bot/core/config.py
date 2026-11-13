"""Yapılandırma yükleme + doğrulama + güvenli varsayılanlar."""
import copy
import yaml

VALID_TFS = {'1m': 1, '3m': 3, '5m': 5, '15m': 15, '30m': 30,
             '1h': 60, '2h': 120, '4h': 240, '6h': 360, '8h': 480,
             '12h': 720, '1d': 1440}

DEFAULTS = {
    'mode': 'paper',                 # paper | live
    'exchange': 'binanceusdm',
    'testnet': True,
    'symbols': ['BTC/USDT:USDT', 'ETH/USDT:USDT', 'SOL/USDT:USDT'],
    'timeframe': '15m',
    'leverage': 5,
    'margin_mode': 'isolated',
    'paper_equity': 10000,
    'strategy': {
        'score_threshold': 4,        # 7 faktörden minimum dönüş
        'ema_fast': 21, 'ema_slow': 55, 'ema_trend': 200,
        'rsi_len': 14, 'adx_len': 14, 'adx_min': 20,
        'atr_len': 14, 'volume_factor': 1.2,
        'bb_len': 20, 'bb_dev': 2.0,
        'min_atr_pct': 0.12,         # ölü pazar filtresi (ATR / fiyat %)
        'exhaustion_rsi': 73,        # aşırı bölgede geç giriş vetosu (simetri: 100-73)
        'mtf_timeframe': '1h', 'mtf_fast': 50, 'mtf_slow': 200,
    },
    'risk': {
        'risk_per_trade_pct': 1.0,
        'max_positions': 3,
        'max_same_side': 2,
        'max_daily_loss_pct': 5.0,
        'max_weekly_loss_pct': 12.0,
        'max_leverage': 20,
        'sl_atr_mult': 1.5,
        'swing_buffer_atr': 0.2,
        'swing_lookback': 20,
        'max_stop_pct': 8.0,         # stop mesafesi fiyatın %8'ini aşarsa işlem reddi
        'tp1_r': 1.0, 'tp1_close_pct': 50, 'tp2_r': 2.0,
        'profit_lock': [[1.0, 0.0], [1.5, 0.5]],   # [MFE(R), kilit(R)]
        'trailing_atr_mult': 1.5,
        'funding_filter_pct': 0.05,
        'cooldown_bars': 3,
        'oi_filter': True,
        'oi_min_delta_pct': -5.0,    # OI çöküşü → giriş yok
        'oi_max_abs_pct': 10.0,      # OI kaosu → giriş yok
        'max_slippage_pct': 0.30,
        'order_error_limit': 3,      # art arda emir hatası → devre kesici
    },
    'scan': {'csv': 'signals.csv'},
    'fees': {'taker': 0.0004, 'slippage': 0.0002},
}


def _deep_merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path='config.yaml'):
    try:
        with open(path, encoding='utf-8') as f:
            user = yaml.safe_load(f) or {}
    except FileNotFoundError:
        raise SystemExit(f'[HATA] Yapılandırma bulunamadı: {path}')
    except yaml.YAMLError as e:
        raise SystemExit(f'[HATA] YAML hatası: {e}')
    cfg = _deep_merge(DEFAULTS, user)
    validate(cfg)
    return cfg


def validate(cfg):
    errs = []
    if cfg['exchange'] not in ('binanceusdm', 'bybit'):
        errs.append(f"exchange desteklenmiyor: {cfg['exchange']}")
    if not isinstance(cfg['symbols'], list) or not cfg['symbols']:
        errs.append('symbols boş olamaz')
    for s in cfg['symbols']:
        if ':' not in str(s):
            errs.append(f"sembol perpetual formatında olmalı (örn BTC/USDT:USDT): {s}")
    if cfg['timeframe'] not in VALID_TFS:
        errs.append(f"timeframe geçersiz: {cfg['timeframe']}")
    st = cfg['strategy']
    if st['mtf_timeframe'] not in VALID_TFS:
        errs.append(f"mtf_timeframe geçersiz: {st['mtf_timeframe']}")
    elif VALID_TFS[st['mtf_timeframe']] <= VALID_TFS[cfg['timeframe']]:
        errs.append("mtf_timeframe, timeframe'den büyük olmalı")
    lev = float(cfg['leverage'])
    if not (1 <= lev <= float(cfg['risk']['max_leverage'])):
        errs.append(f"leverage 1-{cfg['risk']['max_leverage']} arası olmalı")
    rp = float(cfg['risk']['risk_per_trade_pct'])
    if not (0.05 <= rp <= 5):
        errs.append('risk_per_trade_pct 0.05-5 arası olmalı')
    thr = float(st['score_threshold'])
    if not (1 <= thr <= 7):
        errs.append('score_threshold 1-7 arası olmalı')
    if errs:
        raise SystemExit('[HATA] config.yaml sorunlu:\n- ' + '\n- '.join(errs))
