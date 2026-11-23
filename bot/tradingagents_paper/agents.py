"""TradingAgents v0.7.1: gerçek ajan grafiği, OKX verisiyle özel giriş.

Upstream Yahoo araçları yerine enstrümanın güncel OKX snapshot'ı deterministik
market_report olarak verilir. Araştırmacılar, trader, risk ve portföy yöneticisi
upstream TradingAgents düğümleridir. Model ve iş yürütme yereldir.
"""
from datetime import datetime, timezone


def create_graph(model, llm=None):
    from langchain_openai import ChatOpenAI
    from tradingagents.graph.conditional_logic import ConditionalLogic
    from tradingagents.graph.setup import GraphSetup
    import tradingagents.graph.setup as setup
    import tradingagents.graph.analyst_execution as execution
    from dataclasses import replace

    class TextOnlyLocalChat(ChatOpenAI):
        # Küçük yerel modelde yapılandırılmış araç çağrısı güvenilir değil;
        # upstream'ın kendi düz metin fallback yolunu kullanıyoruz.
        def with_structured_output(self, *args, **kwargs):
            raise NotImplementedError('local text-only model')

        def invoke(self, *args, **kwargs):
            import time
            started = time.monotonic()
            print('TradingAgents model çağrısı başladı', flush=True)
            try:
                return super().invoke(*args, **kwargs)
            finally:
                print(f'TradingAgents model çağrısı tamamlandı: {time.monotonic() - started:.1f} sn', flush=True)

    if llm is None:
        llm = TextOnlyLocalChat(model=model, api_key='ollama', base_url='http://127.0.0.1:11434/v1',
                                temperature=0, max_tokens=100, timeout=180, max_retries=0)
    execution.ANALYST_NODE_SPECS['market'] = replace(execution.ANALYST_NODE_SPECS['market'], tools=())
    setup.create_market_analyst = lambda _llm: lambda state: {'market_report': state['instrument_context']}
    return GraphSetup(llm, llm, ConditionalLogic(1, 1), 1).setup_graph(['market']).compile()


def decide(graph, symbol, snapshot):
    from tradingagents.graph.propagation import Propagator
    from tradingagents.agents.rating import run_rating

    context = (f'OKX derivatives contract {symbol}; the following public OKX data and directional '
               f'candidate signal are the only available evidence, not an equity or spot instrument. '
               f'Consider LONG and SHORT risks. A bullish Buy/Overweight rating confirms a LONG signal; '
               f'a bearish Sell/Underweight rating confirms a SHORT signal. A conflicting rating or Hold '
               f'will be rejected by the paper adapter. No news, fundamentals, funding or order book '
               f'were supplied.\n{snapshot}')
    state = Propagator(100).create_initial_state(symbol, datetime.now(timezone.utc).strftime('%Y-%m-%d'),
                                                  asset_type='crypto', instrument_context=context)
    result = graph.invoke(state, config={'recursion_limit': 100})
    return run_rating(result), result.get('final_trade_decision', ''), result.get('market_report', '')
