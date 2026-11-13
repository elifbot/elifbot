```python
import ccxt
import pandas as pd
import numpy as np
import time
import logging
import asyncio
import json
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Literal
from datetime import datetime, timezone
from collections import deque

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ============================================================
# CONFIG & DATA CLASSES
# ============================================================
@dataclass
class BotConfig:
    symbols: List[str] = field(default_factory=lambda: ["BTC/USDT", "ETH/USDT", "SOL/USDT"])
    timeframe: str = "5m"
    lookback: int = 500
    paper_mode: bool = True
    exchange_ids: List[str] = field(default_factory=lambda: ["okx", "binance"])
    risk_per_trade_pct: float = 1.0
    max_open_positions: int = 3
    cooldown_bars: int = 3

    # Ensemble Weights (sum = 1.0)
    w_trend: float = 0.25
    w_momentum: float = 0.20
    w_breakout: float = 0.20
    w_volflow: float = 0.15
    w_fade: float = 0.20

    # Thresholds
    signal_threshold: float = 0.15
    rsi_pump_block: float = 70.0
    rsi_dump_block: float = 30.0

    # Risk Management
    tp_r: float = 1.0
    sl_atr_mult: float = 2.2
    sl_min_pct: float = 1.2
    sl_max_pct: float = 4.5
    be_trigger_pct: float = 1.5
    trail_trigger_pct: float = 2.0
    trail_callback_pct: float = 1.0

@dataclass
class Position:
    symbol: str
    side: Literal["long", "short"]
    entry_price: float
    size: float
    entry_time: int
    stop_loss: float
    take_profit: float
    highest_price: float
    lowest_price: float
    be_activated: bool = False
    trail_activated: bool = False
    exchange: str = "binance"
    id: str = field(default_factory=lambda: f"pos_{int(time.time()*1000)}")

@dataclass
class SignalResult:
    symbol: str
    score: float
    side: Literal["long", "short", "none"]
    details: Dict
    timestamp: int

# ============================================================
# INDICATORS (Vectorized, No Talib Dependency)
# ============================================================
class Indicators:
    @staticmethod
    def ema(series: pd.Series, period: int) -> pd.Series:
        return series.ewm(span=period, adjust=False).mean()

    @staticmethod
    def rsi(series: pd.Series, period: int = 14) -> pd.Series:
        delta = series.diff()
        gain = delta.where(delta > 0, 0).rolling(period).mean()
        loss = -delta.where(delta < 0, 0).rolling(period).mean()
        rs = gain / loss.replace(0, np.nan)
        return 100 - (100 / (1 + rs))

    @staticmethod
    def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
        tr1 = high - low
        tr2 = (high - close.shift()).abs()
        tr3 = (low - close.shift()).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return tr.rolling(period).mean()

    @staticmethod
    def macd(series: pd.Series, fast=12, slow=26, signal=9) -> Tuple[pd.Series, pd.Series, pd.Series]:
        ema_fast = Indicators.ema(series, fast)
        ema_slow = Indicators.ema(series, slow)
        macd_line = ema_fast - ema_slow
        signal_line = Indicators.ema(macd_line, signal)
        hist = macd_line - signal_line
        return macd_line, signal_line, hist

    @staticmethod
    def bollinger_bands(series: pd.Series, period: int = 20, std_dev: float = 2.0) -> Tuple[pd.Series, pd.Series, pd.Series]:
        mid = series.rolling(period).mean()
        std = series.rolling(period).std()
        upper = mid + std_dev * std
        lower = mid - std_dev * std
        return upper, mid, lower

    @staticmethod
    def supertrend(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 10, mult: float = 3.0) -> Tuple[pd.Series, pd.Series]:
        atr_val = Indicators.atr(high, low, close, period)
        hl2 = (high + low) / 2
        upper = hl2 + mult * atr_val
        lower = hl2 - mult * atr_val
        
        trend = pd.Series(1, index=close.index)
        st = pd.Series(0.0, index=close.index)
        
        for i in range(1, len(close)):
            if close.iloc[i] > upper.iloc[i-1]:
                trend.iloc[i] = 1
            elif close.iloc[i] < lower.iloc[i-1]:
                trend.iloc[i] = -1
            else:
                trend.iloc[i] = trend.iloc[i-1]
                if trend.iloc[i] == 1 and lower.iloc[i] < lower.iloc[i-1]:
                    lower.iloc[i] = lower.iloc[i-1]
                if trend.iloc[i] == -1 and upper.iloc[i] > upper.iloc[i-1]:
                    upper.iloc[i] = upper.iloc[i-1]
            st.iloc[i] = lower.iloc[i] if trend.iloc[i] == 1 else upper.iloc[i]
        return st, trend

    @staticmethod
    def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
        return (np.sign(close.diff()) * volume).fillna(0).cumsum()

    @staticmethod
    def vwap(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series) -> pd.Series:
        tp = (high + low + close) / 3
        return (tp * volume).cumsum() / volume.cumsum()

# ============================================================
# ENSEMBLE STRATEGY GROUPS
# ============================================================
class StrategyEnsemble:
    def __init__(self, cfg: BotConfig):
        self.cfg = cfg

    def analyze(self, df: pd.DataFrame) -> Tuple[float, Dict]:
        if len(df) < 50: return 0.0, {}
        
        scores = {}
        details = {}

        # 1. TREND (Supertrend + EMA Alignment)
        st, st_trend = Indicators.supertrend(df['high'], df['low'], df['close'])
        ema50 = Indicators.ema(df['close'], 50)
        ema200 = Indicators.ema(df['close'], 200)
        
        trend_score = 0.0
        if st_trend.iloc[-1] == 1 and df['close'].iloc[-1] > ema50.iloc[-1] > ema200.iloc[-1]: trend_score = 1.0
        elif st_trend.iloc[-1] == -1 and df['close'].iloc[-1] < ema50.iloc[-1] < ema200.iloc[-1]: trend_score = -1.0
        else: trend_score = 0.0
        scores['trend'] = trend_score * self.cfg.w_trend
        details['trend'] = {"st": st_trend.iloc[-1], "ema50": ema50.iloc[-1], "ema200": ema200.iloc[-1]}

        # 2. MOMENTUM (RSI + MACD)
        rsi = Indicators.rsi(df['close'])
        macd_l, macd_s, macd_h = Indicators.macd(df['close'])
        
        mom_score = 0.0
        if rsi.iloc[-1] < 70 and macd_h.iloc[-1] > 0 and macd_h.iloc[-2] <= 0: mom_score = 1.0
        elif rsi.iloc[-1] > 30 and macd_h.iloc[-1] < 0 and macd_h.iloc[-2] >= 0: mom_score = -1.0
        scores['momentum'] = mom_score * self.cfg.w_momentum
        details['momentum'] = {"rsi": rsi.iloc[-1], "macd_hist": macd_h.iloc[-1]}

        # 3. BREAKOUT (Bollinger Band Squeeze + Volume)
        bb_u, bb_m, bb_l = Indicators.bollinger_bands(df['close'])
        bb_width = (bb_u - bb_l) / bb_m
        vol_avg = df['volume'].rolling(20).mean()
        
        brk_score = 0.0
        if bb_width.iloc[-1] < bb_width.rolling(50).mean().iloc[-1]: # Squeeze
            if df['close'].iloc[-1] > bb_u.iloc[-1] and df['volume'].iloc[-1] > vol_avg.iloc[-1] * 1.5: brk_score = 1.0
            elif df['close'].iloc[-1] < bb_l.iloc[-1] and df['volume'].iloc[-1] > vol_avg.iloc[-1] * 1.5: brk_score = -1.0
        scores['breakout'] = brk_score * self.cfg.w_breakout
        details['breakout'] = {"bb_width": bb_width.iloc[-1], "vol_ratio": df['volume'].iloc[-1] / vol_avg.iloc[-1]}

        # 4. VOLUME FLOW (OBV + VWAP)
        obv = Indicators.obv(df['close'], df['volume'])
        vwap = Indicators.vwap(df['high'], df['low'], df['close'], df['volume'])
        obv_slope = (obv.iloc[-1] - obv.iloc[-5]) / 5
        
        vf_score = 0.0
        if obv_slope > 0 and df['close'].iloc[-1] > vwap.iloc[-1]: vf_score = 1.0
        elif obv_slope < 0 and df['close'].iloc[-1] < vwap.iloc[-1]: vf_score = -1.0
        scores['volflow'] = vf_score * self.cfg.w_volflow
        details['volflow'] = {"obv_slope": obv_slope, "vwap_dist": (df['close'].iloc[-1] - vwap.iloc[-1]) / vwap.iloc[-1]}

        # 5. FADE (Mean Reversion / Pump-Dump Detection)
        # Pump: Rapid up move + High RSI + Volume Spike -> SHORT
        # Dump: Rapid down move + Low RSI + Volume Spike -> LONG
        ret_5 = df['close'].pct_change(5).iloc[-1]
        vol_spike = df['volume'].iloc[-1] > vol_avg.iloc[-1] * 2.0
        
        fade_score = 0.0
        # Pump -> Short
        if ret_5 > 0.03 and rsi.iloc[-1] > self.cfg.rsi_pump_block and vol_spike:
            fade_score = -1.0
        # Dump -> Long
        elif ret_5 < -0.03 and rsi.iloc[-1] < self.cfg.rsi_dump_block and vol_spike:
            fade_score = 1.0
        scores['fade'] = fade_score * self.cfg.w_fade
        details['fade'] = {"ret_5": ret_5, "rsi": rsi.iloc[-1], "vol_spike": vol_spike}

        total_score = sum(scores.values())
        details['scores'] = scores
        return total_score, details

# ============================================================
# EXCHANGE WRAPPER (Paper + Live Ready)
# ============================================================
class ExchangeManager:
    def __init__(self, cfg: BotConfig):
        self.cfg = cfg
        self.exchanges: Dict[str, ccxt.Exchange] = {}
        self.markets: Dict[str, Dict] = {}
        self.balances: Dict[str, float] = {"USDT": 10000.0} # Paper starting balance
        self._init_exchanges()

    def _init_exchanges(self):
        for ex_id in self.cfg.exchange_ids:
            try:
                ex_class = getattr(ccxt, ex_id)
                ex = ex_class({'enableRateLimit': True, 'options': {'defaultType': 'future'}})
                if self.cfg.paper_mode:
                    ex.set_sandbox_mode(True) # Use sandbox if available, else mock
                ex.load_markets()
                self.exchanges[ex_id] = ex
                self.markets[ex_id] = ex.markets
                logger.info(f"Exchange {ex_id} loaded ({'Paper' if self.cfg.paper_mode else 'Live'})")
            except Exception as e:
                logger.error(f"Failed to init {ex_id}: {e}")

    def get_best_exchange(self, symbol: str) -> Tuple[str, ccxt.Exchange]:
        # Simple logic: prefer OKX for liquidity, fallback Binance
        for pref in ["okx", "binance"]:
            if pref in self.exchanges and symbol in self.exchanges[pref].markets:
                return pref, self.exchanges[pref]
        raise ValueError(f"Symbol {symbol} not found on configured exchanges")

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
        ex_id, ex = self.get_best_exchange(symbol)
        try:
            data = ex.fetch_ohlcv(symbol, timeframe, limit=limit)
            df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
            return df
        except Exception as e:
            logger.error(f"Fetch OHLCV error {symbol}: {e}")
            return pd.DataFrame()

    def get_balance(self, currency: str = "USDT") -> float:
        if self.cfg.paper_mode:
            return self.balances.get(currency, 0.0)
        # Live implementation would query exchange
        return 0.0

    def create_order(self, symbol: str, side: str, amount: float, price: float = None, params: dict = {}) -> Dict:
        ex_id, ex = self.get_best_exchange(symbol)
        order_type = 'market' # FORCE MARKET ORDER
        
        if self.cfg.paper_mode:
            exec_price = price if price else self.get_last_price(symbol)
            # Simulate fill
            cost = amount * exec_price
            fee = cost * 0.0005 # 0.05% taker fee sim
            
            if side == 'buy':
                if self.balances['USDT'] < cost + fee: raise ValueError("Insufficient Paper Balance")
                self.balances['USDT'] -= (cost + fee)
            else: # sell short
                # In paper mode we just track PnL on close, margin check simplified
                pass
            
            order = {
                'id': f"paper_{int(time.time()*1000)}", 'symbol': symbol, 'side': side,
                'amount': amount, 'price': exec_price, 'status': 'closed', 'fee': fee,
                'timestamp': int(time.time()*1000), 'type': 'market'
            }
            logger.info(f"PAPER ORDER FILLED: {side} {amount} {symbol} @ {exec_price}")
            return order
        else:
            return ex.create_order(symbol, order_type, side, amount, price, params)

    def get_last_price(self, symbol: str) -> float:
        ex_id, ex = self.get_best_exchange(symbol)
        ticker = ex.fetch_ticker(symbol)
        return ticker['last']

    def update_paper_balance(self, pnl: float):
        if self.cfg.paper_mode:
            self.balances['USDT'] += pnl

# ============================================================
# RISK MANAGER
# ============================================================
class RiskManager:
    def __init__(self, cfg: BotConfig, exch: ExchangeManager):
        self.cfg = cfg
        self.exch = exch

    def calculate_position_size(self, symbol: str, entry: float, sl: float) -> float:
        balance = self.exch.get_balance("USDT")
        risk_usdt = balance * (self.cfg.risk_per_trade_pct / 100.0)
        sl_dist_pct = abs(entry - sl) / entry
        if sl_dist_pct == 0: return 0
        size = risk_usdt / (entry * sl_dist_pct)
        
        # Round to exchange precision
        _, ex = self.exch.get_best_exchange(symbol)
        market = ex.market(symbol)
        precision = market['precision']['amount']
        size = float(f"{size:.{precision}f}")
        return max(size, market['limits']['amount']['min'] or 0)

    def calculate_sl_tp(self, df: pd.DataFrame, side: str, entry: float) -> Tuple[float, float]:
        atr = Indicators.atr(df['high'], df['low'], df['close']).iloc[-1]
        atr_pct = (atr / entry) * 100
        sl_dist_pct = max(self.cfg.sl_min_pct, min(self.cfg.sl_max_pct, atr_pct * self.cfg.sl_atr_mult))
        
        if side == "long":
            sl = entry * (1 - sl_dist_pct / 100)
            tp = entry * (1 + sl_dist_pct / 100 * self.cfg.tp_r)
        else:
            sl = entry * (1 + sl_dist_pct / 100)
            tp = entry * (1 - sl_dist_pct / 100 * self.cfg.tp_r)
        return sl, tp

    def update_trailing_stop(self, pos: Position, current_price: float) -> Optional[float]:
        if pos.side == "long":
            pos.highest_price = max(pos.highest_price, current_price)
            profit_pct = (current_price - pos.entry_price) / pos.entry_price * 100
            
            if not pos.be_activated and profit_pct >= self.cfg.be_trigger_pct:
                pos.be_activated = True
                pos.stop_loss = pos.entry_price
                logger.info(f"BREAKEVEN: {pos.symbol} SL -> Entry ({pos.entry_price})")
                return pos.stop_loss

            if not pos.trail_activated and profit_pct >= self.cfg.trail_trigger_pct:
                pos.trail_activated = True
            
            if pos.trail_activated:
                new_sl = pos.highest_price * (1 - self.cfg.trail_callback_pct / 100)
                if new_sl > pos.stop_loss:
                    pos.stop_loss = new_sl
                    logger.info(f"TRAILING UP: {pos.symbol} SL -> {pos.stop_loss}")
                    return pos.stop_loss
        else:
            pos.lowest_price = min(pos.lowest_price, current_price)
            profit_pct = (pos.entry_price - current_price) / pos.entry_price * 100
            
            if not pos.be_activated and profit_pct >= self.cfg.be_trigger_pct:
                pos.be_activated = True
                pos.stop_loss = pos.entry_price
                logger.info(f"BREAKEVEN: {pos.symbol} SL -> Entry ({pos.entry_price})")
                return pos.stop_loss

            if not pos.trail_activated and profit_pct >= self.cfg.trail_trigger_pct:
                pos.trail_activated = True
            
            if pos.trail_activated:
                new_sl = pos.lowest_price * (1 + self.cfg.trail_callback_pct / 100)
                if new_sl < pos.stop_loss:
                    pos.stop_loss = new_sl
                    logger.info(f"TRAILING DOWN: {pos.symbol} SL -> {pos.stop_loss}")
                    return pos.stop_loss
        return None

# ============================================================
# MAIN BOT ENGINE
# ============================================================
class SuperBot:
    def __init__(self, config: BotConfig):
        self.cfg = config
        self.exch = ExchangeManager(config)
        self.strat = StrategyEnsemble(config)
        self.risk = RiskManager(config, self.exch)
        self.positions: Dict[str, Position] = {}
        self.cooldowns: Dict[str, int] = {s: 0 for s in config.symbols}
        self.running = False

    async def run(self):
        self.running = True
        logger.info("=== SUPER BOT STARTED ===")
        while self.running:
            try:
                await self._main_loop()
            except Exception as e:
                logger.error(f"Main loop error: {e}", exc_info=True)
            await asyncio.sleep(10) # Heartbeat

    async def _main_loop(self):
        # 1. Manage Open Positions
        await self._manage_positions()

        # 2. Scan for New Entries
        if len(self.positions) < self.cfg.max_open_positions:
            for symbol in self.cfg.symbols:
                if self.cooldowns[symbol] > 0:
                    self.cooldowns[symbol] -= 1
                    continue
                if symbol in self.positions: continue
                
                signal = await self._analyze_symbol(symbol)
                if signal.side != "none":
                    await self._execute_entry(signal)
                    self.cooldowns[symbol] = self.cfg.cooldown_bars

    async def _analyze_symbol(self, symbol: str) -> SignalResult:
        df = self.exch.fetch_ohlcv(symbol, self.cfg.timeframe, self.cfg.lookback)
        if df.empty or len(df) < 50:
            return SignalResult(symbol, 0, "none", {}, int(time.time()))

        score, details = self.strat.analyze(df)
        current_price = df['close'].iloc[-1]
        rsi = Indicators.rsi(df['close']).iloc[-1]

        side = "none"
        # PUMP TOP FILTER: Block Long if RSI > 70
        if score > self.cfg.signal_threshold:
            if rsi > self.cfg.rsi_pump_block:
                logger.warning(f"BLOCK LONG {symbol}: RSI {rsi:.1f} > {self.cfg.rsi_pump_block} (Pump Top Filter)")
                side = "none"
            else:
                side = "long"
        elif score < -self.cfg.signal_threshold:
            if rsi < self.cfg.rsi_dump_block:
                logger.warning(f"BLOCK SHORT {symbol}: RSI {rsi:.1f} < {self.cfg.rsi_dump_block} (Dump Bottom Filter)")
                side = "none"
            else:
                side = "short"

        return SignalResult(symbol, score, side, details, int(time.time()))

    async def _execute_entry(self, signal: SignalResult):
        symbol = signal.symbol
        side = signal.side
        df = self.exch.fetch_ohlcv(symbol, self.cfg.timeframe, 50)
        if df.empty: return
        
        entry_price = df['close'].iloc[-1] # Market order assumption
        sl, tp = self.risk.calculate_sl_tp(df, side, entry_price)
        size = self.risk.calculate_position_size(symbol, entry_price, sl)
        
        if size <= 0:
            logger.warning(f"Size calc failed for {symbol}")
            return

        try:
            # Execute Market Order
            order_side = 'buy' if side == 'long' else 'sell'
            order = self.exch.create_order(symbol, order_side, size)
            
            pos = Position(
                symbol=symbol, side=side, entry_price=entry_price, size=size,
                entry_time=int(time.time()), stop_loss=sl, take_profit=tp,
                highest_price=entry_price, lowest_price=entry_price
            )
            self.positions[symbol] = pos
            logger.info(f"ENTRY {side.upper()} {symbol} | Size: {size} | Entry: {entry_price:.4f} | SL: {sl:.4f} | TP: {tp:.4f} | Score: {signal.score:.3f}")
        except Exception as e:
            logger.error(f"Entry execution failed {symbol}: {e}")

    async def _manage_positions(self):
        to_close = []
        for symbol, pos in self.positions.items():
            current_price = self.exch.get_last_price(symbol)
            if not current_price: continue

            # Update Trailing / BE
            self.risk.update_trailing_stop(pos, current_price)

            # Check Exit Conditions
            hit_sl = (pos.side == "long" and current_price <= pos.stop_loss) or \
                     (pos.side == "short" and current_price >= pos.stop_loss)
            hit_tp = (pos.side == "long" and current_price >= pos.take_profit) or \
                     (pos.side == "short" and current_price <= pos.take_profit)

            if hit_sl or hit_tp:
                reason = "SL" if hit_sl else "TP"
                await self._close_position(pos, current_price, reason)
                to_close.append(symbol)
        
        for s in to_close: del self.positions[s]

    async def _close_position(self, pos: Position, exit_price: float, reason: str):
        order_side = 'sell' if pos.side == 'long' else 'buy'
        try:
            self.exch.create_order(pos.symbol, order_side, pos.size)
            
            # PnL Calc
            if pos.side == "long":
                pnl_pct = (exit_price - pos.entry_price) / pos.entry_price * 100
            else:
                pnl_pct = (pos.entry_price - exit_price) / pos.entry_price * 100
            
            pnl_usdt = pos.size * pos.entry_price * pnl_pct / 100
            self.exch.update_paper_balance(pnl_usdt)
            
            logger.info(f"EXIT {reason} {pos.symbol} | Side: {pos.side} | Exit: {exit_price:.4f} | PnL: {pnl_pct:.2f}% (${pnl_usdt:.2f}) | Balance: ${self.exch.get_balance():.2f}")
        except Exception as e:
            logger.error(f"Close failed {pos.symbol}: {e}")

    def stop(self):
        self.running = False
        logger.info("Bot stopping...")

# ============================================================
# ENTRY POINT
# ============================================================
async def main():
    cfg = BotConfig(
        symbols=["BTC/USDT", "ETH/USDT", "SOL/USDT", "ARB/USDT", "OP/USDT"],
        paper_mode=True, # SET FALSE FOR LIVE (NEEDS API KEYS IN CCXT CONFIG)
        risk_per_trade_pct=1.0,
        max_open_positions=3
    )
    
    bot = SuperBot(cfg)
    
    # Handle Ctrl+C
    loop = asyncio.get_running_loop()
    for sig in ('SIGINT', 'SIGTERM'):
        try:
            loop.add_signal_handler(getattr(__import__('signal'), sig), bot.stop)
        except NotImplementedError:
            pass # Windows

    await bot.run()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutdown complete.")
```