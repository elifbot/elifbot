from threading import RLock
from .config import Config
from .risk import RiskManager
from .strategy import Strategy
from .position_manager import PositionManager
from .portfolio import PortfolioRisk
from .models import Position

class Engine:
    def __init__(self, cfg=None, exchange_executor=None):
        self.cfg = cfg or Config()
        self.risk = RiskManager(self.cfg)
        self.strategy = Strategy(self.cfg)
        self.positions = {}
        self.pending = {}
        self.pm = PositionManager(self.cfg)
        self.portfolio = PortfolioRisk(self.cfg.correlation_limit, self.cfg.correlation_window)
        self.exchange_executor = exchange_executor
        self._lock = RLock()
        self._halted = False

    def reserved_margin(self):
        with self._lock:
            return sum(x.margin for x in self.pending.values() if getattr(x, 'status', 'OPEN') == 'OPEN')

    def entry_allowed(self, equity, signal, returns=None):
        with self._lock:
            if self._halted:
                from .risk import RiskDecision
                return RiskDecision(False, 'global_kill_switch')
            if returns:
                blocked, symbol, corr = self.portfolio.correlated(signal.symbol, returns, self.positions.values())
                if blocked:
                    from .risk import RiskDecision
                    return RiskDecision(False, f'correlation_limit:{symbol}:{corr:.3f}')
            return self.risk.can_enter(equity, self.positions.values(), self.reserved_margin(), signal.notional)

    def register_position(self, p):
        with self._lock:
            self.positions[p.id] = p

    def load_positions(self, state):
        with self._lock:
            self.positions = {pid: Position.from_dict(data) for pid, data in state.get('positions', {}).items()}

    def save_positions(self, state):
        with self._lock:
            state['positions'] = {pid: p.to_dict() for pid, p in self.positions.items() if p.status == 'OPEN'}
            return state

    def trigger_kill_switch(self, reason='global_kill_switch'):
        with self._lock:
            self._halted = True
            results = []
            if self.exchange_executor:
                for p in list(self.positions.values()):
                    if p.status != 'OPEN':
                        continue
                    try:
                        results.append((p.id, self.exchange_executor.market_close(p)))
                    except Exception as exc:
                        results.append((p.id, {'status': 'ERROR', 'error': str(exc)}))
            return reason, results

    def manage_positions(self, marks, bars_held=None):
        out = []
        with self._lock:
            for pid, p in list(self.positions.items()):
                if p.status != 'OPEN':
                    continue
                mark = marks.get((p.exchange, p.symbol))
                if mark is None:
                    continue
                reason, net = self.pm.check(p, mark, bars_held)
                if reason:
                    out.append((pid, reason, net))
                    if reason == 'HARD_LOSS' and self.exchange_executor:
                        try:
                            out[-1] = (pid, reason, net, self.exchange_executor.market_close(p))
                        except Exception as exc:
                            out[-1] = (pid, reason, net, {'status': 'ERROR', 'error': str(exc)})
            return out
