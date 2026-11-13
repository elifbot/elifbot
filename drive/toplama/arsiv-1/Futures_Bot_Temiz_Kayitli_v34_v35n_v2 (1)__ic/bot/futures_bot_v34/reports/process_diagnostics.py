"""Paper süreç telemetrisi. SIGKILL, OOM ve güç kesintisi uygulamadan görülemez."""
from __future__ import annotations
import atexit
import asyncio as _asyncio_v31
import faulthandler
import json
import os
import platform
import signal
import sys
import threading
import time
from datetime import datetime,timezone

class ProcessSignal(Exception):
    def __init__(self,number):
        self.number=number
        super().__init__(signal.Signals(number).name)

class Diagnostics:
    def __init__(self,base):
        self.finished=False;self.base=base;self.path=os.path.join(base,'logs','process_diagnostics.jsonl');self.fault=None
    def emit(self,event,**fields):
        data={'ts_utc':datetime.now(timezone.utc).isoformat(),'event':event,'pid':os.getpid(),**fields}
        try:
            os.makedirs(os.path.dirname(self.path),exist_ok=True)
            with open(self.path,'a',encoding='utf-8') as fh:
                fh.write(json.dumps(data,ensure_ascii=False,default=str)+'\n');fh.flush()
        except OSError:
            # Tanılama arızası tanılama aracını veya botu sessizce çökertmesin.
            print('UYARI: süreç tanı kaydı yazılamadı',file=sys.stderr,flush=True)
    def start(self):
        os.makedirs(os.path.dirname(self.path),exist_ok=True)
        try:
            self.fault=open(os.path.join(self.base,'logs','faulthandler.log'),'a',encoding='utf-8')
            faulthandler.enable(file=self.fault,all_threads=True)
        except (OSError,RuntimeError,ValueError) as e:self.emit('faulthandler_unavailable',error=type(e).__name__)
        atexit.register(self._atexit)
        self.emit('startup',ppid=os.getppid(),argv=sys.argv[1:],python=platform.python_version(),platform=platform.platform(),
                  # Ortam değişkenleri kimlik bilgisi içerebilir; bunları kaydetme.
                  env_recorded=False)
        old_sys=sys.excepthook
        def sys_hook(typ,value,tb):
            self.emit('uncaught_exception',exception=typ.__name__,message=str(value)[:300]);old_sys(typ,value,tb)
        sys.excepthook=sys_hook
        old_thread=threading.excepthook
        def thread_hook(args):
            self.emit('thread_exception',thread=getattr(args.thread,'name',None),exception=args.exc_type.__name__,message=str(args.exc_value)[:300])
            old_thread(args)
        threading.excepthook=thread_hook
        for sig in (signal.SIGTERM,signal.SIGHUP):
            signal.signal(sig,self._handle_signal)
    def _handle_signal(self,number,frame):
        # Bu kayıt sinyalin kim tarafından gönderildiğini kanıtlamaz.
        self.emit('signal',signal=signal.Signals(number).name)
        raise ProcessSignal(number)
    def _atexit(self):
        self.emit('atexit',tamamlanmis_kapanis=self.finished,
                  not_='atexit SIGKILL veya güç kesintisinde çalışmaz')
    def thread_snapshot(self):
        self.emit('thread_snapshot',threads=[{'name':t.name,'alive':t.is_alive()}
                                           for t in threading.enumerate()])
    def attach_loop(self,loop):
        previous=loop.get_exception_handler()
        def handler(current,context):
            exc=context.get('exception')
            self.emit('asyncio_exception',kaynak='asyncio_exception_handler',
                      message=str(context.get('message',''))[:300],
                      exception=type(exc).__name__ if exc else None)
            if previous:previous(current,context)
            else:current.default_exception_handler(context)
        loop.set_exception_handler(handler)
        return previous
    def watch_future(self,future):
        # Executor hataları Future içinde tutulur, threading.excepthook'a düşmez.
        # Bu callback yalnız izlenen Future için çalışır; her Future'ı kapsamaz.
        def done(f):
            if not f.cancelled():
                exc=f.exception()
                if exc is not None:self.emit('future_exception_observed',kaynak='future_callback',exception=type(exc).__name__)
        future.add_done_callback(done)
        return future
    def ws_ping(self,okx,bnc,agg=None):
        self.emit('ws_ping', **ws_ping_kayit(okx,bnc,agg))
    def event_yuk(self,bot):
        self.emit('event_yuk', **event_yuk_kayit(bot))
    def sample(self,bot=None):
        rss=None;fd=None
        try:
            with open('/proc/self/status',encoding='utf-8') as fh:
                for line in fh:
                    if line.startswith('VmRSS:'):rss=int(line.split()[1]);break
            fd=len(os.listdir('/proc/self/fd'))
        except (OSError,ValueError,IndexError):pass
        threads=[{'name':t.name,'alive':t.is_alive(),'daemon':t.daemon} for t in threading.enumerate()]
        outbox=getattr(getattr(bot,'portfoy',None),'funding_outbox',None)
        kaynak=getattr(bot,'_real_volume',None)
        pending={'funding_outbox':len(outbox) if isinstance(outbox,list) else None,
                 'aggtrade_signal_tasks':len(getattr(kaynak,'tasks',())) if kaynak is not None else None,
                 'regime_tasks':len(getattr(bot,'_regime_tasks',())) if bot is not None else None}
        self.emit('resource_sample',rss_kib=rss,fd_count=fd,threads=threads,
                  ws_ping_pong_ms=None,bekleyenler=pending,
                  unavailable='WS pong gecikmesi ve gerçek event queue boyu henüz ölçülmüyor')
    def finish(self):
        self.finished=True
        if self.fault is not None:
            try:faulthandler.disable();self.fault.close()
            except (OSError,RuntimeError):pass


def ws_ping_kayit(okx,bnc,agg=None):
    """Son alınan uygulama mesajları; RTT ve pong durumu ölçülmez."""
    return {'okx_son_receive_unix':getattr(okx,'_son_receive_utc',None),
            'binance_son_receive_unix':getattr(bnc,'_son_receive_utc',None),
            'binance_aggtrade_son_receive_unix':getattr(agg,'_son_receive_utc',None),
            "heartbeat_sn": 20, "rtt": "olculmedi",
            'rtt_neden':'Mevcut aiohttp baglantilarinda ping/pong RTT olcumu uygulanmadi',
            'aiohttp_ic_buffer':'olculmedi',
            'aiohttp_ic_buffer_neden':'aiohttp ic tamponu izlenmiyor',
            'not':'Zaman son gorulen uygulama mesajidir; sessizlik kopma kaniti degildir; OKX baglantilar arasi toplamlidir'}

def event_yuk_kayit(bot):
    """Görev setlerini ölç; bulunmayan kuyruğu uydurma."""
    source=getattr(bot,'_real_volume',None)
    try:total=len(_asyncio_v31.all_tasks())
    except RuntimeError:total=None
    return {'akis_gorev':len(getattr(bot,'_akis_gorevler',())),
            'regime_gorev':len(getattr(bot,'_regime_tasks',())),
            'aggtrade_gorev':len(source.tasks) if source is not None else None,
            'asyncio_toplam':total,
            'not':'queue yok; aktif gorev sayisi',
            'kapsam':'Uygulama olay queue olcumlenmiyor; aiohttp ic tampon olculmuyor; takip edilen task setleri'}
