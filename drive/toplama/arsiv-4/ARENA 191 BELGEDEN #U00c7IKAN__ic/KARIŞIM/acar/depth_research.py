"""Statik görünür derinlik üzerinde çevrimdışı maliyet tahmini.
Gerçek emir veya gerçek borsa uyumu yoktur; kuyruk, piyasa etkisi ve değişen
likiditeyi bilemez. Her çağrı bağımsız bir varsayımsal senaryodur.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, localcontext


def dec(value, name, *, positive=False, nonnegative=False):
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise ValueError('invalid ' + name)
    try:
        x = Decimal(str(value))
        if not x.is_finite() or len(x.as_tuple().digits) > 30 or abs(x.as_tuple().exponent) > 18 or abs(x) > Decimal('1e18'):
            raise ValueError('invalid ' + name)
        if positive and x <= 0 or nonnegative and x < 0:
            raise ValueError('invalid ' + name)
        return x
    except (InvalidOperation, OverflowError):
        raise ValueError('invalid ' + name) from None


def fmt(x):
    with localcontext() as ctx:
        ctx.prec = 80
        return format(x.normalize(), 'f') if x else '0'

@dataclass(frozen=True)
class MarketRules:
    symbol: str
    qty_step: str
    price_tick: str
    min_qty: str
    min_notional: str


def estimate_depth(*, book, rules, side, quantity, now, max_age, fee_rate, limit_price=None):
    """Taker için tek snapshot derinlik tüketimini tahmin et; girdileri değiştirme.
    Bilinmeyen veri reddedilir; snapshot ve kural seti kullanıcıya aittir.
    Return fiyat/miktarlar decimal metindir; kalan miktar dolmuş varsayılmaz.
    Minimum nominal yaklaşık kontrolü yalnız tahmini dolan notional için uygulanır.
    """
    if not isinstance(book, dict) or not isinstance(rules, MarketRules):
        raise ValueError('book or rules unknown')
    if not isinstance(rules.symbol, str) or not rules.symbol or book.get('symbol') != rules.symbol:
        raise ValueError('symbol mismatch')
    if side not in ('buy', 'sell'):
        raise ValueError('invalid side')
    now = dec(now, 'now', nonnegative=True)
    observed = dec(book.get('observed_at'), 'observed_at', nonnegative=True)
    max_age = dec(max_age, 'max_age', nonnegative=True)
    if observed > now or now-observed > max_age:
        raise ValueError('stale or future book')
    qty = dec(quantity, 'quantity', positive=True)
    step = dec(rules.qty_step, 'qty_step', positive=True)
    tick = dec(rules.price_tick, 'price_tick', positive=True)
    minimum = dec(rules.min_qty, 'min_qty', nonnegative=True)
    min_notional = dec(rules.min_notional, 'min_notional', nonnegative=True)
    fee = dec(fee_rate, 'fee_rate', nonnegative=True)
    if fee > 1:
        raise ValueError('fee outside [0,1]')
    limit = dec(limit_price, 'limit_price', positive=True) if limit_price is not None else None
    with localcontext() as ctx:
        ctx.prec = 80
        if qty < minimum or qty % step != 0:
            raise ValueError('quantity violates rules')
        if limit is not None and limit % tick != 0:
            raise ValueError('limit violates tick')
        def levels(key, descending):
            rows = book.get(key)
            if not isinstance(rows, (tuple, list)) or not rows:
                raise ValueError('empty book')
            out = []
            for row in rows:
                if not isinstance(row, (tuple, list)) or len(row) != 2:
                    raise ValueError('bad level')
                p, q = dec(row[0], 'level price', positive=True), dec(row[1], 'level quantity', positive=True)
                if p % tick != 0:
                    raise ValueError('level violates tick')
                if out and (p >= out[-1][0] if descending else p <= out[-1][0]):
                    raise ValueError('unsorted or duplicate level')
                out.append((p, q))
            return out
        bids = levels('bids', True); asks = levels('asks', False)
        if bids[0][0] >= asks[0][0]:
            raise ValueError('crossed book')
        available = asks if side == 'buy' else bids
        best = available[0][0]
        left = qty; notional = Decimal(0); fills = []
        for price, vol in available:
            if limit is not None and (price > limit if side == 'buy' else price < limit):
                break
            # Yarım lotluk görüntülenmiş miktarı dolmuş sayma.
            usable = (vol // step) * step
            take = min(left, usable)
            if take:
                fills.append({'price':fmt(price), 'qty':fmt(take)})
                notional += price * take; left -= take
            if left == 0: break
        filled = qty-left
        if filled and notional < min_notional:
            raise ValueError('estimated filled notional below minimum; no simulated fill committed')
        vwap = notional/filled if filled else None
        impact = ((vwap/best-1) if side=='buy' else (1-vwap/best))*10000 if vwap else None
        return {'symbol':rules.symbol,'side':side,'status':'FILLED' if not left else 'PARTIAL' if filled else 'UNFILLED',
                'requested_qty':fmt(qty),'filled_qty':fmt(filled),'remaining_qty':fmt(left),
                'notional':fmt(notional),'fee_estimate':fmt(notional*fee),
                'average_price':fmt(vwap.quantize(Decimal('0.000000000001'))) if vwap is not None else None,
                'impact_vs_best_bps':fmt(impact.quantize(Decimal('0.000000000001'))) if impact is not None else None,
                'levels':fills,'observed_at':fmt(observed),
                'warning':'Çevrimdışı tek snapshot tahmini; sıra, yenilenen likidite ve gerçek dolum değildir.'}
