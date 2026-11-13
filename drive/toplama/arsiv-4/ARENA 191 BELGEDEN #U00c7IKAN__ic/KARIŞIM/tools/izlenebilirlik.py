"""191 kaynak için doğrulanabilir statik sınıflandırma; sır/içerik kopyalamaz."""
import json,re
from pathlib import Path
root=Path(__file__).resolve().parents[1];dataset=json.loads((root/'reference/statik_indeks.json').read_text(encoding='utf-8'))
records=dataset['files'];assert len(records)==191

names={'veri_kapanmis_mum':'kapalı mum/veri','strateji_sinyal':'strateji/sinyal','risk_boyut':'risk/boyut','stop_ve_cikis':'stop/çıkış','dca_pyramiding':'DCA/kademe','emir_yurutme':'emir/yürütme','funding_liquidation':'funding/marj','orderflow':'emir defteri/akış','koruma_ve_operasyon':'sağlık/defter','arastirma_istatistik':'araştırma/test','ai_haber':'YZ/haber','dis_baglanti':'dış ağ','riskli_kod_isareti':'kod inceleme işareti','sir_belirteci':'gizlilik işareti'}
def classify(r):
 n=int(r['name'].split('_')[1]);name=r['name'].lower();ext=r['extension']
 if n==176:return 'Sır içerebilen kaynak; token kopyalanmadı, iptal/yenileme önerildi.'
 if n==153:return 'Kaydedilmiş oturum; kişisel içerik aktarılmadı, kaynak kabulü yapılmadı.'
 if n in (128,167):return 'Gömülü proje statik incelendi; özel emir kodu çalıştırılmadı/aktarılmadı.'
 if name.find('test_')>=0 or 'test_hizli' in name:return 'Eski test referansı; birebir çalıştırılmadı. Yeni testler bağımsız; kapsam paritesi yok.'
 if ext=='.json':return 'Eski istek/durum kaydı; otomatik yürütülmedi ve ayarları devralınmadı.'
 if ext in ('.md','.txt') and 'html' not in r:return 'Belge/metin; iddialar deney kanıtı olarak otomatik kabul edilmedi.'
 if 'html' in r:
  if n in (154,155,156):return 'Kaydedilmiş web kaynağı; işlevsel strateji sayılmadı.'
  return 'HTML statik incelendi; 10-oy araştırma fikri kısmen uygulandı, JS paritesi/doğrulaması yok.'
 if ext=='.py':
  if any(x in name for x in ('executor','exchanges','broker','live_runner')):return 'Yürütme referansı; yalnız PAPER kuralları yeniden tasarlandı, özel borsa emir yolu aktarılmadı.'
  if any(x in name for x in ('state_store','reconcile','circuit_breaker','health')):return 'Defter/koruma referansı; atomik kayıt ve sınırlı aritmetik kontrol var; tam recovery yok.'
  if any(x in name for x in ('risk','sizing')):return 'Risk referansı; portföy kapısı kısmi, marj/likidasyon/Kelly ve tüm sürümler eşdeğer değil.'
  if any(x in name for x in ('backtest','walkforward','shadow','attribution','cohort')):return 'Araştırma referansı; çevrimdışı replay ve sınırlı walk-forward var; atıf/eşli gölge paritesi yok.'
  if any(x in name for x in ('indicator','yetenek','strategy','core','finl')):return 'Gösterge/strateji referansı; bazı bağımsız göstergeler ve 10-oy araştırma adayı var; parite yok.'
  if any(x in name for x in ('market_data','moneyflow','derivatives','futures_catalog')):return 'Veri referansı; kapalı mum ve kotasyon var; akış/defter/katalog bileşenleri eksik.'
  if any(x in name for x in ('telegram','whatsapp','alert','dashboard','news','sentiment','ml_')):return 'Bildirim/model/arayüz referansı; bazı panel parçaları var, dış model ve bildirim entegrasyonu yok.'
  return 'Python statik tarandı; davranış ve bağımlılıkların tamamı aktarılmadı/doğrulanmadı.'
 return 'Statik sınıflandırıldı; doğrudan yürütülmedi.'

out=['# 191 kaynak için işleme ve izlenebilirlik matrisi','','Her dosya statik olarak sınıflandırıldı ve aşağıdaki kaynak hatlarıyla ilişkilendirildi. Bu tablo semantik satır satır güvenlik denetiminin, eski testleri çalıştırmanın veya 191 dosyanın tüm özelliklerini aktarmanın tamamlandığı anlamına gelmez. Eşleşmeler regex göstergesidir: yorum veya eski örnek de eşleşebilir. Verilen L değerleri kaynaktaki ilk konu eşleşmesidir. Sır, URL, sohbet ve JSON değerleri kopyalanmadı.','', '| Kaynak | Tür / satır | Konu kanıtları (ilk satır) | Karar ve uygulama durumu |','|---|---:|---|---|']
for r in records:
 cats=[]
 for k,v in r.get('indicators',{}).items():
  cats.append(f"{names.get(k,k)} L{v['lines'][0]}")
 info='; '.join(cats) if cats else 'önceden tanımlı konu deseni yok'
 typ='HTML içeriği' if 'html' in r else r['extension'].lstrip('.') or 'metin'
 out.append('| '+r['name'].replace('|','/')+' | '+typ+' / '+str(r['lines'])+' | '+info+' | '+classify(r).replace('|','/')+' |')
out+=['','## Özet kısıtlar','- Envanter tek başına her özellik için tasarım/aktarım/parite testi değildir.','- Özel API, gerçek emir, sırrı içeren kayıt veya kaydedilmiş sohbet çalıştırılmadı.','- Derin önceki inceleme: `KRITIK_BULGULAR.md`, `SURUM_AST_FARKLARI.md` ve makine-okunur `reference/statik_indeks.json`.','- Araştırma stratejisi yalnız çevrimdışı olup canlı PAPER sinyaline bağlanmadı.','- `funding_research` bağımsızdır; gerçek veri ve aktif defterle bütünleştirilmedi.']
(root/'docs/TUM_191_KAYNAK_IZLENEBILIRLIK.md').write_text('\n'.join(out)+'\n',encoding='utf-8')
print('191 kaynak haritalandı; tüm özellikler tamamlandı anlamına gelmez.')
