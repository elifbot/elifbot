"""Paper-only v7-like pre-context candidates on the same feed as v37.

Never substitutes market freshness, ATR/VWAP, enrichment or portfolio controls.
Legacy thresholds here share v37's first-stage detector and current feed, so
this is not a full historical v7 replay. The callback never mutates v37 cooldown.
"""
from __future__ import annotations
import asyncio
import json
import os
import time
from collections import Counter
from scanner.ws_scanner import Sinyal
from scanner.ind_aktif import giris_karari
from scanner.vwap_cvd_shadow import vwap_shadow, flow_shadow

class V7Compare:
    def __init__(self, bot):
        self.bot=bot
        self.last={}
        self.counts=Counter()
        self.path=os.path.join(os.path.dirname(bot.profit_protection_csv),'v7_karsilastirma.jsonl')
        self.last_error=None

    def status(self):
        return {'active':True,'mode':'v7-like first-stage; v37 context bypass only for legacy candidate; remaining v37 guards intact',
                'counts':dict(self.counts),'last_error':self.last_error}

    def observe(self, d, ts, ret, rvol, hacim):
        b=self.bot; det=b.detektor
        if b.asama!='tarama' or not b.indikator_hazir or b.yeni_giris_kapali:
            return
        now=int(time.time()*1000)
        if ts>now+2000 or now-ts>5000 or not (0<=now-d.son_fiyat_ts<=det.tazelik_ms):
            self.counts['stale']+=1; return
        key=(d.exchange,d.symbol)
        if d.exchange=='binance' and (b._real_volume is None or d.symbol not in b._real_volume.connected or not d.hiz_uzun):
            self.counts['feed_unready']+=1; return
        if key in self.last and ts-self.last[key]<det.soguma_ms: return
        self.last[key]=ts
        market_side='LONG' if ret>0 else 'SHORT'
        side='SHORT' if market_side=='LONG' else 'LONG'
        ctx='pass'
        if det.baglam_aktif:
            if not det.baglam_guncelle(d,ts): ctx='baglam_isinma'
            elif abs(d.baglam_ret)<det.baglam_min_ret: ctx='baglam_ret_alt'
            elif det.baglam_maks_ret and abs(d.baglam_ret)>det.baglam_maks_ret: ctx='baglam_ret_ust'
            elif det.baglam_min_vratio and d.baglam_vratio<det.baglam_min_vratio: ctx='baglam_vratio'
            elif det.baglam_min_vratio3 and d.baglam_vratio3<det.baglam_min_vratio3: ctx='baglam_vratio3'
            elif det.baglam_ayni_yon and (d.baglam_ret>0)!=(ret>0): ctx='baglam_yon'
        if ctx=='pass' and det.min_genislik_oran>0 and det.genislik_oran<det.min_genislik_oran:
            ctx='genislik'
        tol=getattr(det, 'vwap_tolerans_pct', 0.0)
        ind_ok, ind_reason, values=(giris_karari(d,ts,d.son_fiyat,side,vwap_tolerans_pct=tol)
                                    if tol else giris_karari(d,ts,d.son_fiyat,side))
        self.counts['legacy_candidate']+=1
        self.counts['context_'+ctx]+=1
        self.counts['v7_side_ind_'+('pass' if ind_ok else ind_reason)]+=1
        # When baseline context passes, the original v37 detector owns the
        # decision, avoiding duplicate/conflicting triggers on the same event.
        send=ctx!='pass' and ind_ok
        if send and len(b._akis_gorevler)>=128:
            send=False; self.counts['task_limit']+=1
        signal=Sinyal(ts_ms=ts,exchange=d.exchange,symbol=d.symbol,yon=market_side,
             etiket='V7_FADE_ADAY',fiyat=d.son_fiyat,ret_pct=round(ret,3),
             rvol=round(rvol,2),hacim_usd=round(hacim,0),gecen_ms=det.ret_pencere_ms,
             baglam_ret=round(d.baglam_ret,3),baglam_vratio=round(d.baglam_vratio,2),
             baglam_vratio3=round(d.baglam_vratio3,2))
        # Salt gözlem: her aday için, normal karar/ret mekanizmasına müdahale etmez.
        try:
            flow_diagnostic=flow_shadow(getattr(b,'akis',None),d.exchange,d.symbol,ts,side)
        except Exception as exc:
            flow_diagnostic={'available':False,'reason':'shadow_error','error':str(exc)[:100]}
            self.counts['flow_shadow_error']+=1
        vwap_diagnostic=vwap_shadow(d.son_fiyat,side,values)
        row={'ts_ms':ts,'exchange':d.exchange,'symbol':d.symbol,'market_direction':market_side,
             'v7_fade_direction':side,'price':d.son_fiyat,'ret_pct':ret,'rvol':rvol,
             'short_volume_usd':hacim,'v37_context_first_result':ctx,
             'v7_direction_indicator_pass':ind_ok,'indicator_reason':ind_reason,
             'indicator_values':values,'dispatched_to_v37_guards':send,
             'vwap_shadow':vwap_diagnostic,'flow_shadow':flow_diagnostic,
             'active_vwap_tolerance_pct':tol,
             'band_only_pass':bool(ind_ok and vwap_diagnostic.get('available') and not vwap_diagnostic.get('strict_pass'))}
        try:
            with open(self.path,'a',encoding='utf8') as f:
                f.write(json.dumps(row,ensure_ascii=False,allow_nan=False,default=str)+'\n')
        except (OSError,ValueError,TypeError) as exc:
            # Fail closed: no paper entry if candidate attribution wasn't saved.
            self.counts['record_error']+=1;self.last_error=f'{type(exc).__name__}: {exc}';return
        if send:
            if row['band_only_pass']: self.counts['band_only_dispatched']+=1
            self.counts['dispatched']+=1
            task=asyncio.create_task(b._sinyal_dispatch(signal),name='v7-compare-dispatch')
            b._akis_gorevler.add(task)
            def done(t):
                b._akis_gorevler.discard(t)
                if not t.cancelled() and t.exception() is not None:
                    self.counts['dispatch_error']+=1
                    self.last_error=str(t.exception())[:200]
            task.add_done_callback(done)
