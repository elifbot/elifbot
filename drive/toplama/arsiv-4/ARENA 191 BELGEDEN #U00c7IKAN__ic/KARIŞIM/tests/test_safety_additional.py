import unittest
from acar.market_safety import funding_gate,SequenceBook,BookSyncError
class SafetyAdditionalTests(unittest.TestCase):
 def test_extreme_number_funding_fails_closed(self):
  self.assertFalse(funding_gate('long',10**400,120,100,100)['allowed'])
 def test_extreme_book_price_invalidates_book(self):
  b=SequenceBook();b.apply('snapshot',1,[[99,1]],[[101,1]])
  with self.assertRaises(BookSyncError):b.apply('update',2,[[10**400,1]],[],prev_seq=1)
  with self.assertRaises(BookSyncError):b.top()
if __name__=='__main__':unittest.main()
