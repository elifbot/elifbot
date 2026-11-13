"""Sonuç ölçümleri; sıfır paydaları ve düşük örnek sayısını açık gösterir."""
from collections import Counter

def trade_metrics(trades):
    pnls=[t['net_pnl'] for t in trades]
    wins=sum(x>0 for x in pnls); losses=sum(x<0 for x in pnls)
    gp=sum(x for x in pnls if x>0); gl=-sum(x for x in pnls if x<0)
    total=sum(pnls)
    return {'count':len(pnls),'wins':wins,'losses':losses,'flat':len(pnls)-wins-losses,
            'win_rate':wins/len(pnls) if pnls else None,
            'average_net_pnl':total/len(pnls) if pnls else None,
            'profit_factor':gp/gl if gl>0 else None,
            'profit_factor_note':None if gl else 'Zarar yok veya işlem yok; oran tanımsız.',
            'total_fees':sum(t['entry_fee']+t['exit_fee'] for t in trades),
            'by_exit_reason':dict(Counter(t['reason'] for t in trades)),
            'by_side':dict(Counter(t['side'] for t in trades)),
            'warning':'Az işlemde metrikler kararlılık veya kârlılık kanıtı değildir.'}
