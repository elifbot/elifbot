"""Süreç canlılığı: bayat durum/PID tekrar kullanımını CANLI sayma (Linux)."""
from __future__ import annotations
import argparse,json,os
from datetime import datetime,timezone

HEARTBEAT_ESIK_SN=15
BAYAT_ESIK_SN=30

def process_identity(pid):
    try:
        with open(f'/proc/{int(pid)}/stat',encoding='utf-8') as f: stat=f.read()
        fields=stat[stat.rfind(')')+2:].split()
        with open('/proc/sys/kernel/random/boot_id',encoding='utf-8') as f: boot=f.read().strip()
        if fields[0]=='Z' or not boot:return None
        return {'boot_id':boot,'start_ticks':int(fields[19])}
    except (OSError,ValueError,IndexError,TypeError):return None

def durum_canli_mi(durum,simdi=None,esik_sn=HEARTBEAT_ESIK_SN):
    """Kimlik/heartbeat doğrulanamazsa güvenli olarak CANLI demez."""
    if not isinstance(durum,dict) or not durum:return 'BİLİNMİYOR'
    if durum.get('calisiyor') is False or durum.get('kapanis_nedeni'):return 'KAPANDI'
    if durum.get('calisiyor') is not True or not durum.get('son_heartbeat_utc'):return 'BİLİNMİYOR'
    try:
        stamp=datetime.fromisoformat(durum['son_heartbeat_utc'].replace('Z','+00:00'))
        if stamp.tzinfo is None:return 'BİLİNMİYOR'
        now=simdi or datetime.now(timezone.utc)
        if now.tzinfo is None:return 'BİLİNMİYOR'
        age=(now-stamp).total_seconds()
        if age < -5:return 'BİLİNMİYOR'
        if age > BAYAT_ESIK_SN:return 'BAYAT'
        if age > esik_sn:return 'SÜREÇ_DOĞRULANAMADI'
        pid=durum.get('pid')
        if isinstance(pid,bool) or not isinstance(pid,int) or pid<=0:return 'SÜREÇ_DOĞRULANAMADI'
        recorded=durum.get('process_identity')
        if not isinstance(recorded,dict) or process_identity(pid)!=recorded:return 'SÜREÇ_DOĞRULANAMADI'
        os.kill(pid,0)
        return 'CANLI'
    except (KeyError,ValueError,TypeError,OSError,OverflowError):return 'SÜREÇ_DOĞRULANAMADI'

def main():
    ap=argparse.ArgumentParser();ap.add_argument('durum');args=ap.parse_args()
    try:
        with open(args.durum,encoding='utf-8') as f: d=json.load(f)
    except (OSError,ValueError):d={}
    print(durum_canli_mi(d))
if __name__=='__main__':main()
