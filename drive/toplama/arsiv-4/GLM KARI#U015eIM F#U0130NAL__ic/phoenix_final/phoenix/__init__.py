"""PHOENIX FINAL v3.0 — 4 sistemin (AcarBot v7.2, FUSION_PRO 4.0, sentez-bot, Phoenix v2.0)
en iyi bileşenlerinden birleştirilmiş kripto FUTURES confluence botu.

Katkı haritası:
  • Phoenix v2.0   : modüler iskelet, ccxt canlı yol, dry→testnet→canlı merdiveni
  • sentez-bot     : kötümser motor semantiği (stop-once, sonraki-açılış giriş), edge/maliyet
                     kapısı, mum boşluğu koruması, ardışık zarar duraksaması, walk-forward,
                     katkı (attribution) analizi, nedensel göstergeler
  • FUSION_PRO 4.0 : çoklu-zaman-çerçevesi (HTF) oybirliği, rejim algısı, hacim-z / sıkışma
                     vetoları, kısmi TP + iz süren runner, yayılma (spread) koruması,
                     funding settlement koruması
  • AcarBot v7.2   : oynaklığa göre dinamik kaldıraç düşürme, durum kalıcılığı, kill-switch
                     dosyası, çoklu-veri-kaynağı yedeklemesi
  (Reddedilenler: sınırsız piramitleme, çapraz kurtarma, 20x kaldıraç, %5 SL — rapora bakın)
"""

__version__ = "3.0.0"
