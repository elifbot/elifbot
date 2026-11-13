#!/usr/bin/env python3
"""Kapanmış işlemler için ayrı funding mutabakat CSV'si üretir."""
import argparse
import asyncio
from reports.funding_reconcile import reconcile_file

def main():
    p = argparse.ArgumentParser()
    p.add_argument('girdi', help='paper islem CSV yolu')
    p.add_argument('cikti', help='olusturulacak AYRI CSV yolu')
    args = p.parse_args()
    n, unknown = asyncio.run(reconcile_file(args.girdi, args.cikti))
    print(f'{n} işlem; funding belirsiz: {unknown}; rapor: {args.cikti}')
    print('OKX mark 1 dakika açılış tahminidir; orijinal dosya ve bakiye değiştirilmedi.')
    return 0 if unknown == 0 else 2

if __name__ == '__main__':
    raise SystemExit(main())
