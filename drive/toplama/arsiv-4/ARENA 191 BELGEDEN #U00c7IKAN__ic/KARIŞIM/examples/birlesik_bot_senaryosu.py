"""İnternet/gerçek para olmadan iki sembollü BÜTÜNLEŞİK sentetik senaryo.
Sadece geçici bir SQLite dosyası kullanır, sonunda onu siler.
"""
import json,tempfile
from pathlib import Path
from acar.data import Bar
from acar.depth_research import MarketRules
from acar.unified_simulator import UnifiedSimulator
from acar.unified_bot import OfflineUnifiedBot

def make_bars(base,step):
    return [Bar(1704067200+i*60,base+step*i,base+step*i+step,base+step*i-step,base+step*i+step*.5,10) for i in range(220)]
def main():
    btc=make_bars(100,1);eth=make_bars(50,.5);now=btc[-1].timestamp+60
    br=MarketRules('BTC','0.1','0.1','0.1','0');er=MarketRules('ETH','0.1','0.1','0.1','0')
    bb={'symbol':'BTC','observed_at':now,'bids':[['319.4','1']],'asks':[['319.6','1']]}
    eb={'symbol':'ETH','observed_at':now,'bids':[['159.7','1']],'asks':[['159.8','1']]}
    with tempfile.TemporaryDirectory(prefix='acar-unified-') as d:
        sim=UnifiedSimulator.create(Path(d)/'unified.sqlite');bot=OfflineUnifiedBot(sim)
        entries=[]
        entries.append(bot.on_candles('btc-entry',symbol='BTC',bars=btc,quantity='0.2',leverage='2',next_funding=now+1000,now=now,book_id='btc-1',book=bb,rules=br))
        entries.append(bot.on_candles('eth-entry',symbol='ETH',bars=eth,quantity='0.5',leverage='2',next_funding=now+100,now=now,book_id='eth-1',book=eb,rules=er))
        before=sim.snapshot()
        stopbook={'symbol':'BTC','observed_at':now+1,'bids':[['315','0.1']],'asks':[['315.2','1']]}
        stop=bot.on_book('btc-stop-partial',symbol='BTC',book_id='btc-2',book=stopbook,rules=br,now=now+1)
        funding=sim.settle_funding('eth-funding',symbol='ETH',settlement_ts=now+100,finalized_at=now+100,rate='0.001',mark_price='160',next_funding=now+500,now=now+100)
        eth_exit_book={'symbol':'ETH','observed_at':now+101,'bids':[['164','1']],'asks':[['164.1','1']]}
        eth_exit=bot.on_book('eth-target',symbol='ETH',book_id='eth-2',book=eth_exit_book,rules=er,now=now+101)
        btc_exit_book={'symbol':'BTC','observed_at':now+102,'bids':[['314.9','1']],'asks':[['315','1']]}
        btc_exit=bot.on_book('btc-stop-final',symbol='BTC',book_id='btc-3',book=btc_exit_book,rules=br,now=now+102)
        unlock=sim.clear_entry_lock('operator-unlock',now+102)
        final=sim.snapshot()
    print(json.dumps({'mode':'OFFLINE_SYNTHETIC','entries':entries,'shared_wallet_before':before['state']['cash'],
       'partial_protection':stop,'funding':funding,'eth_target':eth_exit,'btc_remaining_exit':btc_exit,'operator_unlock':unlock,
       'final':final,'warning':'Tamamen sentetik verilerle yazılım doğrulaması; canlı PAPER/gerçek borsa/performans testi değildir.'},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
