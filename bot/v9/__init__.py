# -*- coding: utf-8 -*-
"""ACARBOT v9 · ORTAK AKIL — rejim katmanlı, 4 dedektörlü, portföy sıralamalı motor.

v8'in borsa/teminat fiziğini (SimuleBorsa, boyut_hesapla, KasaKurallari) aynen kullanır;
üstüne üç katman ekler:
  1. rejim   — piyasanın hâli, sinyaller buna göre kapılanır (eşik kendi kendine kalibre olur)
  2. sinyal  — 4 dedektörün oy birliği (çelişki varsa işlem yok)
  3. portföy — adaylar skora göre sıralanır, teminat bitene kadar en iyileri girilir

Değişmez kural: 1.000 $ · 50 $ · 10x · CROSS · limitsiz · −10 $ stop.
"""
__all__ = ["rejim", "sinyaller", "motor", "cli"]
