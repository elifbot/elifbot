"""Son HTML'nin JS kuralları ile Python strateji kararlarını karşılaştırır.
Python 3 + Node gerekir; çalışma zamanı bağımlılığı değildir.
"""
import json, math, random, subprocess
from pathlib import Path
from omnistudio.core.types import Candle
from acarbot.strategy import decide, STRATEGIES

def main():
    html=(Path(__file__).parent/'kaynak-v10.html').read_text(encoding='utf8')
    js=html[html.index('const Gostergeler = {'):html.index('const Motor = {')]
    harness="""const sayiMi = v => typeof v === 'number' && isFinite(v);
let CFG = {emaF:20,emaM:50,emaY:200,macdF:12,macdS:26,macdSig:9,bollP:20,bollK:2,onay:2,hacimOnay:true,hacimCarpan:1,strateji:'trend'};\n"""+js+"""
const fixtures=JSON.parse(require('fs').readFileSync(0,'utf8')); let results=[];
for (const c of fixtures) { let st=Gostergeler.hesapla(c);
 for (const strat of ['trend','rsirev','kombin','macd','bollkir','bolldon']) {
 CFG.strateji=strat; let i=st.sayi-1, sig=Sinyal.kural(st,i);
 let n=Sinyal.gerekliOnay();
 if (!['LONG','SHORT'].includes(sig) || !Sinyal.hacimUygun(st,i)) {results.push(null);continue;}
 let pass=true; for(let j=1;j<n;j++) if(Sinyal.kural(st,i-j)!==sig) pass=false;
 results.push(pass ? sig : null);
 }}
console.log(JSON.stringify(results));
"""
    rng=random.Random(714); fixtures=[]; source=[]
    for trial in range(300):
        rows=[]; data=[]; price=100; drift=rng.uniform(-.2,.2)
        for i in range(260):
            price=max(1,price+drift+rng.gauss(0,.6)+.3*math.sin(i/8))
            vol=rng.uniform(40,180); t=i*300000
            rows.append({'t':t,'o':price,'h':price+.4,'l':price-.4,'c':price,'v':vol,'kapanis':True})
            data.append(Candle('X','gateio',t,price,price+.4,price-.4,price,vol,True))
        fixtures.append(rows); source.append(data)
    expected=json.loads(subprocess.run(['node','-e',harness],input=json.dumps(fixtures),text=True,capture_output=True,check=True).stdout)
    got=[]
    for candles in source:
        for strategy in STRATEGIES:
            r=decide(candles,candles[-1].open_ms+300001,strategy)
            got.append(r.side.value if r.side else None)
    failures=[(i//6,STRATEGIES[i%6],a,b) for i,(a,b) in enumerate(zip(expected,got)) if a!=b]
    print(json.dumps({'fixtures':len(source),'strategies':len(STRATEGIES),'checks':len(got),'mismatches':len(failures),'examples':failures[:10]}))
    return bool(failures)
if __name__=='__main__': raise SystemExit(main())
