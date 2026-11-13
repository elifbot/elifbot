"""Exactly two preregistered candidates on old, already exposed v9.3 data."""
from dataclasses import asdict,replace
from pathlib import Path
import json,time
import pandas as pd
from backtests.chronological_portfolio import ChronologicalPortfolioEngine
from src.adaptive_policy import AdaptivePolicy

ROOT=Path(__file__).resolve().parent.parent

def main():
    data=json.loads((ROOT/'reports/development_v93_snapshot.json').read_text())
    frames={s:pd.DataFrame(rows) for s,rows in data['frames'].items()}
    base=next(iter(frames.values()));start=int(base.open_time.iloc[600]);end=int(base.open_time.iloc[-1])+300000
    candidates={'A':AdaptivePolicy(),'B':replace(AdaptivePolicy(),activation_r=2.,trail_atr=2.5)}
    results={};cache={};started=time.monotonic()
    for name,policy in candidates.items():
        engine=ChronologicalPortfolioEngine(frames,policy=policy);engine.feature_cache=cache
        result=engine.run(start,end);cache=engine.feature_cache
        results[name]={'policy':asdict(policy),'result':result}
        print(name,result['trade_count'],result['net_pnl'],result['max_equity_drawdown_usdt'],flush=True)
    selected=max(results,key=lambda x:(results[x]['result']['net_pnl'],-results[x]['result']['max_equity_drawdown_usdt'],x=='A'))
    report={'development_only':True,'exposed_old_holdout_not_oos':True,'selection_rule':'max development net; tie lower equity DD; tie A',
            'selected':selected,'candidates':results,'elapsed_sec':time.monotonic()-started}
    (ROOT/'reports/v94_development_results.json').write_text(json.dumps(report,indent=2))
    (ROOT/'configs/v94_selected_policy.json').write_text(json.dumps(results[selected]['policy'],indent=2))
    print('SELECTED',selected,flush=True)
if __name__=='__main__':main()
