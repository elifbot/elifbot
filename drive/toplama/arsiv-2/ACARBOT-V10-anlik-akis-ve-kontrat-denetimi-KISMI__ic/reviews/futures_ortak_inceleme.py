import asyncio
from pathlib import Path
import acarbot.ai_review as review
review.FILES=('acarbot/futures_market.py','acarbot/futures_paper.py','acarbot/ledger.py','acarbot/strategy.py')
review.PROVIDERS=(
 ('Kilo','cohere/north-mini-code:free','https://api.kilo.ai/api/gateway/chat/completions'),
 ('Kilo','nvidia/nemotron-3.5-lightning:free','https://api.kilo.ai/api/gateway/chat/completions'),
 ('Kilo','dots-studio/dots-3-note-preview:free','https://api.kilo.ai/api/gateway/chat/completions'),
 ('Kilo','nvidia/nemotron-3-ultra-550b-a55b:free','https://api.kilo.ai/api/gateway/chat/completions'),
 ('OVHcloud','Mistral-Small-3.2-24B-Instruct-2506','https://oai.endpoints.kepler.ai.cloud.ovh.net/v1/chat/completions'),
 ('OVHcloud','Qwen3.8-27B','https://oai.endpoints.kepler.ai.cloud.ovh.net/v1/chat/completions'),
 ('OVHcloud','Qwen3.5-397B-A17B','https://oai.endpoints.kepler.ai.cloud.ovh.net/v1/chat/completions'),
 ('OVHcloud','Meta-Llama-3_3-70B-Instruct','https://oai.endpoints.kepler.ai.cloud.ovh.net/v1/chat/completions'),
 ('OVHcloud','Qwen3.6-27B','https://oai.endpoints.kepler.ai.cloud.ovh.net/v1/chat/completions'),
)
def make_prompt():
 return ('Act as independent software and exchange-risk auditor. Current experiment: Binance USD-M/COIN-M and OKX SWAP/FUTURES discovered 1661; 614 cannot paper trade. 51 percent of 5-minute closed candles were stale because REST scans 1661 symbols. We need fast near-real-time accumulation and correct simulated long/short, fees, settlement, contract size, lots, delivery and funding in each settlement currency. Propose concrete safe architecture, explain websocket closed-candle synchronization/reconnect/gaps/backfill, PnL formulas and examples, distinguish unverified assumptions and failure modes. Never suggest relaxing data freshness or fake conversions, never assume real fills or trade profitability. Review following exact current source; give prioritized precise fixes. Other model suggestions will be reviewed independently, not auto-applied.\n' + ''.join('\n### '+p+'\n'+(review.ROOT/p).read_text() for p in review.FILES))
review.prompt=make_prompt
asyncio.run(review.review(review.ROOT/'reviews'/'futures-ortak-inceleme-20261105'))
