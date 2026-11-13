"""Deneysel yalnız paper aggTrade hacim kaynağı. Varsayılan değildir.

Borsada ağ kopması veya callback kaybı varsa kesin tamlık ispatlanamaz; kısa
pencereler sıkı tazelik/120 sn ısınma ile kapatılır, tahmine dönüş yapılmaz.
"""
import asyncio
import math
import time
from scanner.ind_aktif import aggtrade_ekle

class BinanceAggTradeInput:
    def __init__(self,detector,on_signal):
        self.detector=detector;self.on_signal=on_signal
        self.connected=set();self.ever=set();self.acc={};self.last_sample={};self.last_ts={};self.last_arrival={}
        self.invalid=0;self.stale=0;self.resets=0;self.accepted=0;self.signal_errors=0
        self.tasks=set();self.sessizlik_sayisi=0;self.sessizlik_max_ms=0

    def reset(self,symbol,clear_history=False):
        d=self.detector.durum('binance',symbol);d.kaynak='aggtrade'
        d.hacimler.clear();d.hiz_kisa=d.hiz_uzun=d.rvol=0.0;d.son_hacim_ts=0
        d.dakika_id=-1;d.dakika_qv=0.;d.tamamlanan_qv=0.
        d._volume_full_warmup_ms=120_000
        for name in ('_kum_onceki','_kum_dk','_kum_birikim'):
            if hasattr(d,name):delattr(d,name)
        if clear_history:
            d.dakika_kapanis.clear();d.dakika_hacim.clear();d.baglam_hazir=False
            if hasattr(d,'ind_mum'): d.ind_mum.clear(); d.ind_acik_mum=None
            d.baglam_ret=d.baglam_vratio=d.baglam_vratio3=0.0
        for dic in (self.acc,self.last_sample,self.last_ts,self.last_arrival):dic.pop(symbol,None)
        self.resets+=1

    def connection(self,symbols,up):
        for symbol in symbols:
            if up:
                self.reset(symbol,clear_history=symbol in self.ever)
                self.connected.add(symbol);self.ever.add(symbol)
            else:
                self.connected.discard(symbol);self.reset(symbol,clear_history=True)

    def trade(self,exchange,symbol,price,base,side,ts):
        if exchange!='binance' or symbol not in self.connected:return
        try:price=float(price);base=float(base);ts=int(ts)
        except (ValueError,TypeError,OverflowError):
            self.invalid+=1;self.reset(symbol,clear_history=True);return
        now=int(time.time()*1000)
        if not all(math.isfinite(x) and x>0 for x in (price,base,price*base)) or side not in ('buy','sell'):
            self.invalid+=1;self.reset(symbol,clear_history=True);return
        if ts>now+2_000 or now-ts>5_000 or ts<self.last_ts.get(symbol,0):
            self.stale+=1;self.reset(symbol,clear_history=True);return
        # v35m/H-01: Sessizlik RESET DEĞİL. Reset yalnız connection(up=False).
        # Gap kirliliği _oranlari_hesapla'da exchange-koşullu yakalanır.
        last=self.last_arrival.get(symbol)
        if last is not None and now-last > self.detector.tazelik_ms:
            self.sessizlik_sayisi = getattr(self, 'sessizlik_sayisi', 0) + 1
            _s = now - last
            if _s > getattr(self, 'sessizlik_max_ms', 0):
                self.sessizlik_max_ms = _s
        self.last_ts[symbol]=ts;self.last_arrival[symbol]=now
        self.acc[symbol]=self.acc.get(symbol,0.0)+price*base;self.accepted+=1
        if getattr(self.detector,'ind_aktif',False):
            aggtrade_ekle(self.detector.durum('binance',symbol),ts,price,base)
        if now//1000 == self.last_sample.get(symbol):return
        self.last_sample[symbol]=now//1000
        sig=self.detector.besle_hacim_kumulatif('binance',symbol,self.acc[symbol],now)
        if sig:
            task=asyncio.create_task(self.on_signal(sig));self.tasks.add(task)
            def finished(done):
                self.tasks.discard(done)
                if done.cancelled(): return
                if done.exception() is not None:
                    self.signal_errors+=1
                    self.connected.discard(symbol)
                    self.reset(symbol,clear_history=True)
            task.add_done_callback(finished)
