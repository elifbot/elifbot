"""Çevrimdışı sentetik doğrulamalar; kârlılık veya ağ testleri değildir."""
import numpy as np
import pytest
import sweep_v2 as s

def rows(n=3,offset=0):
    return [[(offset+i)*s.MINUTE,'100','102','98','100','1',(offset+i+1)*s.MINUTE-1] for i in range(n)]

def test_decode_page_kapali_ve_tam():
    arr=s.decode_page(rows(),3*s.MINUTE-1,3)
    assert arr.shape==(3,6) and arr[-1,0]==2*s.MINUTE

def test_acik_veya_eksik_sayfa_reddedilir():
    data=rows();data[-1][6]+=1
    with pytest.raises(ValueError,match='kapanmamış'):s.decode_page(data,3*s.MINUTE-1,3)
    with pytest.raises(ValueError,match='eksik'):s.decode_page(rows(2),3*s.MINUTE-1,3)

def test_bosluk_ve_tekrar_reddedilir():
    data=rows();data[1][0]=data[0][0];data[1][6]=data[0][6]
    with pytest.raises(ValueError,match='boşluk'):s.decode_page(data,3*s.MINUTE-1,3)

def test_cache_npz_butunluk(tmp_path):
    data=s.decode_page(rows(),3*s.MINUTE-1,3);path=tmp_path/'BTC.npz'
    s.atomic_npz(path,data);assert np.array_equal(s.load_npz(path,0,2*s.MINUTE,3),data)
    with pytest.raises(ValueError):s.load_npz(path,0,2*s.MINUTE,4)

def test_ayni_mum_stop_onceligi():
    data=np.array([[i*s.MINUTE,100.,103.,97.,100.,1.] for i in range(250)])
    net,neden=s.simule(data,0,'long',1,1,.04,.05)
    assert neden=='sl' and net<0

def test_stop_acilis_gap():
    data=np.array([[i*s.MINUTE,100.,100.,100.,100.,1.] for i in range(250)])
    data[2,1:5]=[90,92,89,90]
    net,neden=s.simule(data,0,'long',5,2,.04,.05)
    assert neden=='sl_acilis' and net< -10

def test_fade_grid_320():
    data=np.array([[i*s.MINUTE,100.,100.,100.,100.,1.] for i in range(1200)])
    result,split,n=s.sweep({'BTCUSDT':data},.04,.05)
    assert len(result)==320 and n==0
    assert all(x['eg_ort']=='' and x['te_ort']=='' for x in result)
