from dataclasses import dataclass
from time import time

@dataclass
class PendingOrder:
    id: str
    signal: object
    created_at: float
    reserved_margin: float
    status: str = 'OPEN'
    requotes: int = 0
    exchange_order_id: str | None = None

class MakerExecutor:
    """Local maker-order lifecycle; optional cancel callback keeps exchange state authoritative."""
    def __init__(self, timeout_sec=45, requote_bps=1.0, cancel_callback=None):
        self.timeout_sec = timeout_sec
        self.requote_bps = requote_bps
        self.cancel_callback = cancel_callback
        self.pending = {}

    def reserve(self, order_id, signal, exchange_order_id=None):
        p = PendingOrder(order_id, signal, time(), signal.margin, exchange_order_id=exchange_order_id)
        self.pending[order_id] = p
        return p

    def expire(self, now=None):
        now = time() if now is None else now
        out = []
        for oid, p in list(self.pending.items()):
            if now - p.created_at >= self.timeout_sec and p.status == 'OPEN':
                if p.exchange_order_id and self.cancel_callback:
                    try:
                        self.cancel_callback(p.exchange_order_id, p.signal.symbol)
                    except Exception:
                        p.status = 'CANCEL_FAILED'
                        out.append(p)
                        continue
                p.status = 'CANCELLED'
                out.append(self.pending.pop(oid))
        return out

    def fill(self, order_id):
        p = self.pending.pop(order_id)
        p.status = 'FILLED'
        return p

    def cancel(self, order_id):
        p = self.pending.pop(order_id)
        if p.exchange_order_id and self.cancel_callback:
            self.cancel_callback(p.exchange_order_id, p.signal.symbol)
        p.status = 'CANCELLED'
        return p
