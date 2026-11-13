from math import floor


def plan(signal,equity,cfg,open_positions=0,same_side=0,instrument=None):
    r=cfg['risk']; px=float(signal['entry']);
    if px<=0:return None,'bad_price'
    margin=float(r.get('margin_per_trade_usd',50.0)); leverage=int(r.get('leverage',10)); notional=margin*leverage
    if equity < margin*float(r.get('min_free_margin_multiple',1.05)): return None,'insufficient_free_margin'
    qty=notional/px
    if instrument is not None:
        step=float(getattr(instrument,'qty_step',0) or 0)
        minq=float(getattr(instrument,'min_qty',0) or 0)
        if step>0: qty=floor(qty/step+1e-12)*step
        if qty<minq:return None,'below_exchange_min_qty'
    if qty<=0:return None,'zero_qty'
    # User requested a $20 stop across BTC, DOGE, etc. For linear USDT contracts,
    # fixed notional means the same adverse percentage move produces the same gross PnL.
    # We reserve estimated fees/slippage so the expected all-in loss stays near the budget.
    loss_budget=float(r.get('stop_loss_usd',20.0))
    fee_reserve=notional*float(cfg['execution'].get('fee_bps_roundtrip',8.0))/10000
    slip_reserve=notional*float(cfg['execution'].get('slippage_bps_side',2.5))/10000
    price_loss=max(0.01,loss_budget-fee_reserve-slip_reserve)
    stop_dist=price_loss/max(qty,1e-12)
    stop=px-stop_dist if signal['side']=='LONG' else px+stop_dist
    target=float(signal.get('target') or 0)
    if signal['side']=='LONG' and target<=px:return None,'bad_target'
    if signal['side']=='SHORT' and target>=px:return None,'bad_target'
    lev=max(1,min(int(r.get('leverage_max',10)),leverage))
    return {'qty':qty,'notional':notional,'margin':margin,'risk_cash':loss_budget,'estimated_fee_reserve':fee_reserve,'estimated_slippage_reserve':slip_reserve,'gross_price_loss_budget':price_loss,'leverage':lev,'stop':stop,'target':target},'ok'
