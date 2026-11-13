"""Tamamen sentetik ve çevrimdışı örnek; asıl PAPER defterini kullanmaz."""
import json, tempfile
from decimal import Decimal
from pathlib import Path
from acar.depth_research import MarketRules,estimate_depth
from acar.order_journal_research import ResearchJournal
from acar.funding_research import Settlement
from acar.funding_store_research import FundingResearchStore

def main():
    book={'symbol':'BTC-USDT-SWAP','observed_at':100,'bids':[['99','0.5'],['98','1']], 'asks':[['101','0.4'],['102','0.3']]}
    rules=MarketRules('BTC-USDT-SWAP','0.1','1','0.1','0')
    estimate=estimate_depth(book=book,rules=rules,side='buy',quantity='1',now=101,max_age=5,fee_rate='0.001')
    with tempfile.TemporaryDirectory(prefix='acar-research-') as temp:
        journal=ResearchJournal.create(Path(temp)/'orders.sqlite')
        journal.submit('demo-order','BTC-USDT-SWAP','buy','1');journal.acknowledge('demo-order')
        # Sentetik örnekteki düzeyleri ayrı ayrı varsayımsal dolum olarak kaydet.
        for i,fill in enumerate(estimate['levels']):journal.record_fill('demo-order',f'demo-fill-{i}',fill['qty'],fill['price'],str(Decimal(fill['qty'])*Decimal(fill['price'])*Decimal('0.001')))
        journal.request_cancel('demo-order');journal.reconcile_final('demo-order','CANCELED',estimate['filled_qty'])
        order=journal.snapshot('demo-order')
        funding=FundingResearchStore.create(Path(temp)/'funding.sqlite',1000)
        event=Settlement('OKX','BTC-USDT-SWAP',200,201,.001,100,True)
        pos={'id':'independent-demo-position','venue':'OKX','instrument':'BTC-USDT-SWAP','side':'long','qty_base':.7,'opened_at':100,'closed_at':None}
        settlement=funding.settle(event,pos);summary=funding.snapshot()
    print(json.dumps({'mode':'OFFLINE_SYNTHETIC','depth_estimate':estimate,'simulated_order_journal':order,
       'separate_hypothetical_funding':{'settlement':settlement,'summary':summary},
       'warning':'Örnekler varsayımsaldır. İki defter bağlantılı değildir; geçici dosyalar silindi; PAPER veya borsa işlemi değildir.'},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
