import asyncio,json
from pathlib import Path
import acarbot.ai_review as r
j=json.loads((r.ROOT/'reviews/futures-ortak-inceleme-20261105/gorusler.json').read_text())
r.FILES=()
r.PROVIDERS=(
 ('Kilo','nvidia/nemotron-3.5-lightning:free','https://api.kilo.ai/api/gateway/chat/completions'),
 ('OVHcloud','Mistral-Small-3.2-24B-Instruct-2506','https://oai.endpoints.kepler.ai.cloud.ovh.net/v1/chat/completions'),
 ('OVHcloud','Qwen3.6-27B','https://oai.endpoints.kepler.ai.cloud.ovh.net/v1/chat/completions'))
def prompt():
 snippets='\n\n'.join('MODEL '+x['requested_model']+': '+x['answer'][:4300] for x in j['results'] if x['status']=='OK' and 'north-mini' not in x['requested_model'])
 return ('Cross-review other models independently for PAPER-only exchange simulator. Fact-check below suggestions; reject contradictions and hallucinations. Prioritize stream reconnection/gap handling, exactly-once finalized bars, and separate settlement balances, precision, contract sizing, risk, FX and expiry. Note OKX WS candle row is [ts,o,h,l,c,vol,volCcy,volCcyQuote,confirm], Binance coin-M WS q is BASE asset, Binance routes /market; 180000ms=3 minutes. Avoid assuming quote conversions are 1:1 or actual fills. Only evidence below: \n'+snippets)
r.prompt=prompt
asyncio.run(r.review(r.ROOT/'reviews'/'futures-capraz-inceleme-20261105'))
