import unittest
from acar.data import Bar
from acar.correlation_research import correlation_gate

def series(n=40,inverse=False,flat=False,start=1704067200):
 price=100.;bars=[]
 for i in range(n):
  r=0 if flat else (0.001 if i%3==0 else -0.002 if i%3==1 else 0.0003)
  price*=1-r if inverse else 1+r
  bars.append(Bar(start+i*60,price,price*1.01,price*.99,price,10))
 return bars
class CorrelationTests(unittest.TestCase):
 def setUp(self):self.a=series();self.now=self.a[-1].timestamp+60
 def gate(self,b=None,side='long',other_side='long',**kw):return correlation_gate(self.a,side,{'ETH':{'side':other_side,'bars':self.a if b is None else b}},self.now,**kw)
 def test_same_direction_positive_correlation_blocks(self):
  r=self.gate();self.assertEqual(r['reason'],'CORRELATED_EXPOSURE');self.assertAlmostEqual(r['correlations']['ETH']['price_return_correlation'],1)
 def test_hedged_direction_allowed(self):self.assertTrue(self.gate(other_side='short')['allowed'])
 def test_inverse_returns_and_opposite_direction_blocks(self):
  r=self.gate(b=series(inverse=True),other_side='short');self.assertEqual(r['reason'],'CORRELATED_EXPOSURE');self.assertAlmostEqual(r['correlations']['ETH']['price_return_correlation'],-1,places=10)
 def test_missing_unaligned_or_constant_is_unknown(self):
  for b in ([],series(start=1704067260),series(flat=True)):
   with self.subTest(n=len(b)):self.assertEqual(self.gate(b=b)['reason'],'CORRELATION_UNKNOWN')
 def test_future_and_stale_fail_closed(self):
  self.assertEqual(correlation_gate(self.a,'long',{},self.now-1)['reason'],'CORRELATION_UNKNOWN')
  self.assertEqual(correlation_gate(self.a,'long',{},self.now+31)['reason'],'CORRELATION_UNKNOWN')
 def test_extreme_threshold_rejected(self):
  for threshold in (float('nan'),10**400,True):
   with self.subTest(threshold=threshold),self.assertRaises(ValueError):self.gate(threshold=threshold)
 def test_future_suffix_cannot_affect_prefix(self):
  a=series(42);prefix=a[:40];now=prefix[-1].timestamp+60
  x=correlation_gate(prefix,'long',{'x':{'side':'short','bars':prefix}},now)
  a[-1]=Bar(a[-1].timestamp,100,110,90,105,10)
  self.assertEqual(x,correlation_gate(a[:40],'long',{'x':{'side':'short','bars':a[:40]}},now))
if __name__=='__main__':unittest.main()
