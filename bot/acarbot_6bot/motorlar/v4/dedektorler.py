# -*- coding: utf-8 -*-
"""v4 dedektör kurulumu — 4 orijinal motor (v1) sinyal üreticisi olarak kullanılır.

Dedektörlerin kendi defterleri ayrıdır; füzyon botu yalnızca "yeni pozisyon açtı"
olayını oy olarak okur. Böylece orijinal botların kodu hiç değişmeden sinyal kaynağı olur.
"""
from __future__ import annotations

import acarbot_omega
import apex_bot
import hybrid_bot
import turbo_engine


def dedektorleri_kur(fuzyon_motor) -> None:
    fuzyon_motor.dedektor_ekle("TURBO", turbo_engine.RealTimeVolumeShockEngine(), "ingest_batch")
    fuzyon_motor.dedektor_ekle("OMEGA", acarbot_omega.AcarbotOmegaEngine(), "ingest_ticks")
    fuzyon_motor.dedektor_ekle("HYBRID", hybrid_bot.HybridV2(), "ingest_batch")
    fuzyon_motor.dedektor_ekle("APEX", apex_bot.Apex(), "ingest_batch")
