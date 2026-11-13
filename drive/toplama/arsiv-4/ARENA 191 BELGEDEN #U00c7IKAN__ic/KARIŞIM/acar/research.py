"""Bağımsız PAPER defterlerle farklı karar eşiklerini karşılaştırır."""
from .replay import PaperEngine
from .strategy import Confluence, Breakout

def compare_thresholds(bars, config, higher_factor=5):
    results={}
    for threshold in (2,3,4):
        r=PaperEngine(config,Confluence(threshold,higher_factor)).run(bars)
        results[str(threshold)]={'starting_cash':r['starting_cash'],'ending_cash':r['ending_cash'],'net_pnl':r['net_pnl'],'trade_count':r['trade_count'],'max_drawdown_fraction':r['max_drawdown_fraction']}
    return {'method':'independent_same_data_paper_ledgers','results':results,'warning':'Bu karşılaştırma örneklem içidir; seçilen eşiğin gelecekte üstün olduğunu kanıtlamaz.'}

def walk_forward(bars, config, train_bars=250, test_bars=100, higher_factor=5):
    """Kayan, çakışmayan test pencereleri. Başlangıç bakiyesi her pencerede sıfırlanır.

    Eğitimde net PnL ile 2/3/4 eşiklerinden seçim yapılır; eşitlikte düşük eşik.
    Test, yalnız eğitim geçmişini ısınma olarak görür; ısınma bölümünde işlem yoktur.
    Pozisyonlar pencere sonunda kapatılır; pencerelerin PnL'leri bileşik değildir.
    """
    from .data import validate_bars
    validate_bars(bars,config.interval)
    if isinstance(train_bars,bool) or not isinstance(train_bars,int) or train_bars<max(35,10*higher_factor):
        raise ValueError('eğitim penceresi strateji ısınması için yetersiz')
    if isinstance(test_bars,bool) or not isinstance(test_bars,int) or test_bars<2:
        raise ValueError('test penceresi en az 2 mum olmalı')
    if len(bars)<train_bars+test_bars: raise ValueError('tam eğitim ve test penceresi için veri yetersiz')
    windows=[]
    for start in range(0,len(bars)-train_bars-test_bars+1,test_bars):
        train=bars[start:start+train_bars]
        test=bars[start+train_bars:start+train_bars+test_bars]
        candidates={}
        for t in (2,3,4):
            r=PaperEngine(config,Confluence(t,higher_factor)).run(train)
            candidates[t]={'net_pnl':r['net_pnl'],'trades':r['trade_count']}
        chosen=max((2,3,4),key=lambda t:(candidates[t]['net_pnl'],-t))
        strategy=Confluence(chosen,higher_factor)
        def gated(history):
            return strategy(history) if len(history)>train_bars else None
        result=PaperEngine(config,gated).run(train+test)
        windows.append({'train_start':train[0].timestamp,'train_end_open':train[-1].timestamp,
                        'test_start':test[0].timestamp,'test_end_open':test[-1].timestamp,
                        'selected_threshold':chosen,'training':candidates,
                        'test_net_pnl':result['net_pnl'],'test_trades':result['trade_count'],
                        'test_drawdown_fraction':result['max_drawdown_fraction'],
                        'test_trade_details':result['trades']})
    return {'method':'rolling_train_disjoint_test','train_bars':train_bars,'test_bars':test_bars,
            'window_count':len(windows),'windows':windows,
            'sum_independent_test_pnl':sum(w['test_net_pnl'] for w in windows),
            'warning':'Pencereler bağımsız bakiyeyle başlar; sonuçlar bileşik getiri veya gelecekte kârlılık kanıtı değildir. Funding ve gerçek piyasa etkisi modellenmez.'}


def compare_strategies(bars,config,higher_factor=5):
    out={}
    for name,strategy in [('confluence',Confluence(3,higher_factor)),('breakout',Breakout())]:
        r=PaperEngine(config,strategy).run(bars)
        out[name]={'net_pnl':r['net_pnl'],'trade_count':r['trade_count'],
                   'max_drawdown_fraction':r['max_drawdown_fraction'],'trade_metrics':r['trade_metrics']}
    return {'method':'independent_same_data','strategies':out,
            'warning':'Aynı veri üzerinde örneklem içi karşılaştırma, ileriye dönük doğrulama değildir.'}
