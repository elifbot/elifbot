"""OKX orderbook instId düzeltmesi regresyon testi (FINAL v1.1).

Gerçek OKX /api/v5/market/books yanıtı instId DÖNDÜRMEZ (asks/bids/ts/seqId).
Taban kod result['instId'] ile KeyError veriyordu; canlıda orderbook hiç
çalışmıyordu. Bu test düzeltmeyi kilitler.
"""

from __future__ import annotations

import unittest

from infra.exchanges.okx import OKXPublic


class OkxOrderBookTests(unittest.TestCase):
    def _exchange_with_fake_api(self, include_inst_id: bool):
        ex = OKXPublic()

        def fake_get_json(path, params):
            if path == "/api/v5/market/books":
                row = {
                    "asks": [["100.2", "5", "0", "2"], ["100.1", "3", "0", "1"]],
                    "bids": [["99.9", "4", "0", "2"], ["99.8", "6", "0", "3"]],
                    "ts": "1794032704901",
                    "seqId": 123,
                }
                if include_inst_id:
                    row["instId"] = params["instId"]
                return {"code": "0", "data": [row]}
            if path == "/api/v5/public/instruments":
                return {"code": "0", "data": [{
                    "instId": "BTC-USDT-SWAP", "ctVal": "0.01",
                    "ctValCcy": "BTC", "baseCcy": "BTC",
                }]}
            raise AssertionError(f"beklenmeyen çağrı: {path}")

        ex._get_json = fake_get_json
        return ex

    def test_books_without_instid_accepted(self):
        ex = self._exchange_with_fake_api(include_inst_id=False)
        book = ex.fetch_order_book("BTC-USDT-SWAP", 100)
        self.assertEqual(book.symbol, "BTC-USDT-SWAP")
        self.assertEqual(len(book.bids), 2)
        # Kontrat dönüşümü: 4 kontrat x 0.01 BTC = 0.04 BTC
        self.assertAlmostEqual(book.bids[0][1], 0.04)
        self.assertEqual(book.timestamp_ms, 1794032704901)

    def test_books_with_instid_still_validated(self):
        ex = self._exchange_with_fake_api(include_inst_id=True)
        book = ex.fetch_order_book("BTC-USDT-SWAP", 100)
        self.assertEqual(book.symbol, "BTC-USDT-SWAP")


if __name__ == "__main__":
    unittest.main()
