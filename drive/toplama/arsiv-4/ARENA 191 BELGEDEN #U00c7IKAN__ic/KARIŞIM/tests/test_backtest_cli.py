"""Offline CLI güvenlik kontrolleri; ağ veya PAPER süreçleri başlatmaz."""
import subprocess,sys,unittest,tempfile
from pathlib import Path
class CliSafetyTests(unittest.TestCase):
 def test_walkforward_cannot_be_mislabelled_as_confluence10_or_breakout(self):
  for strategy in ('confluence10','breakout'):
   with tempfile.TemporaryDirectory() as d:
    out=Path(d)/'out.json'
    p=subprocess.run([sys.executable,'backtest.py',str(Path(d)/'missing.csv'),'--out',str(out),'--strategy',strategy,'--walk-forward'],capture_output=True,text=True,timeout=5)
    self.assertNotEqual(p.returncode,0);self.assertIn('yalnız eski confluence',p.stderr);self.assertFalse(out.exists())
