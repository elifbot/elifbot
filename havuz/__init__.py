# -*- coding: utf-8 -*-
"""havuz — arşivdeki her dosyayı indeksler ve konu bazlı sindirilmiş demetler üretir.

Neden: GitHub Models 8.000 girdi token sınırı koyuyor; 32 MB'lık arşiv doğrudan
verilemez. Havuz, 2.414 dosyayı kaybetmeden etiketler ve her konuda en kanıtlı
satırları `dosya:satır` referansıyla çıkarır.
"""
