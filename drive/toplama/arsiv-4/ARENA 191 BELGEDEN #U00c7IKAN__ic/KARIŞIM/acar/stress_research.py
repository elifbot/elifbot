"""Yalnız çevrimdışı OHLC maliyet duyarlılığı. Performans veya risk garantisi değil."""
from dataclasses import replace,asdict
from .data import validate_bars
from .replay import PaperEngine,Config
from .strategy import Confluence,Breakout
from .confluence10 import ResearchConfluence10

def cost_stress(bars,config,scenarios,strategy='confluence'):
    """Önceden tanımlı maliyet senaryoları bağımsız eşit-bakiye replay koşuları.

    Aynı veride çalışırlar; örneklem dışı veya ileriye dönük sonuç değildir.
    Her koşu kendi stop/target maliyetli işlemlerini yaratır; trading kararı da
    değişebilir. Simülatör funding/derinlik/marj modellemez.
    """
    if not isinstance(config,Config):raise ValueError('invalid config')
    config.validate();validate_bars(bars,config.interval)
    factories={'confluence':Confluence,'breakout':Breakout,'confluence10':ResearchConfluence10}
    if strategy not in factories:raise ValueError('invalid strategy')
    if not isinstance(scenarios,list) or not scenarios or len(scenarios)>25:raise ValueError('invalid scenarios')
    seen=set();result=[]
    for scenario in scenarios:
        if not isinstance(scenario,dict) or set(scenario)!={'name','fee_bps','spread_bps','slippage_bps'}:
            raise ValueError('scenario must include name and three costs')
        name=scenario['name']
        if not isinstance(name,str) or not name or len(name)>80 or name in seen:raise ValueError('invalid/duplicate scenario name')
        seen.add(name)
        c=replace(config,fee_bps=scenario['fee_bps'],spread_bps=scenario['spread_bps'],slippage_bps=scenario['slippage_bps'])
        c.validate()
        r=PaperEngine(c,factories[strategy]()).run(bars)
        result.append({'name':name,'fee_bps':c.fee_bps,'spread_bps':c.spread_bps,'slippage_bps':c.slippage_bps,
                       'trade_count':r['trade_count'],'net_pnl':r['net_pnl'],'max_drawdown_fraction':r['max_drawdown_fraction']})
    return {'mode':'OFFLINE_COST_SENSITIVITY','strategy':strategy,'base_config':asdict(config),'scenarios':result,
            'warning':'Aynı veri üzerinde örneklem içi duyarlılık; funding, defter derinliği, likidasyon ve gerçek yürütme yok. Gelecek performansı kanıtlamaz.'}
