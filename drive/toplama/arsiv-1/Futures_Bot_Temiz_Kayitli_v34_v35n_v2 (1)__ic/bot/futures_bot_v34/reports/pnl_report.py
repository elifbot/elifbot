"""
reports/pnl_report.py — Kâr/zarar raporu.

Sharpe oranı, MIN_TRADES_FOR_SHARPE (varsayılan 30) altında hesaplanmaz;
yerine açıkça "hesaplanamaz — yetersiz veri" yazılır.
Funding her zaman "bilinmiyor / hariç" olarak etiketlenir.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from portfolio.paper_futures import FUNDING_LABEL, TradeRecord

SHARPE_SUPPRESSED_TEXT = "hesaplanamaz — yetersiz veri"


@dataclass
class PnLReport:
    """Kapalı işlemlerden üretilen rapor."""

    trades: list[TradeRecord] = field(default_factory=list)
    starting_balance: float = 1_000.0
    ending_balance: float = 0.0
    min_trades_for_sharpe: int = 30

    # -- metrikler ---------------------------------------------------------
    @property
    def closed_count(self) -> int:
        return len(self.trades)

    @property
    def total_realized(self) -> float:
        return sum(t.realized_pnl for t in self.trades)

    @property
    def total_fees(self) -> float:
        return sum(t.entry_fee + t.exit_fee for t in self.trades)

    @property
    def wins(self) -> list[TradeRecord]:
        return [t for t in self.trades if t.realized_pnl > 0]

    @property
    def losses(self) -> list[TradeRecord]:
        return [t for t in self.trades if t.realized_pnl <= 0]

    @property
    def win_rate(self) -> float:
        return len(self.wins) / self.closed_count if self.closed_count else 0.0

    @property
    def profit_factor(self) -> float | None:
        gross_win = sum(t.realized_pnl for t in self.wins)
        gross_loss = abs(sum(t.realized_pnl for t in self.losses))
        if gross_loss == 0:
            return None if gross_win == 0 else math.inf
        return gross_win / gross_loss

    @property
    def avg_win(self) -> float:
        return sum(t.realized_pnl for t in self.wins) / len(self.wins) if self.wins else 0.0

    @property
    def avg_loss(self) -> float:
        return (
            sum(t.realized_pnl for t in self.losses) / len(self.losses)
            if self.losses
            else 0.0
        )

    @property
    def expected_value(self) -> float:
        return self.total_realized / self.closed_count if self.closed_count else 0.0

    def long_short_split(self) -> dict[str, dict[str, float]]:
        out: dict[str, dict[str, float]] = {}
        for side in ("LONG", "SHORT"):
            subset = [t for t in self.trades if t.side == side]
            out[side] = {
                "count": float(len(subset)),
                "pnl": round(sum(t.realized_pnl for t in subset), 6),
                "win_rate": round(
                    (sum(1 for t in subset if t.realized_pnl > 0) / len(subset))
                    if subset
                    else 0.0,
                    4,
                ),
            }
        return out

    def equity_curve(self) -> list[float]:
        """Kapanış sırasına göre bakiye eğrisi (başlangıç + kümülatif PnL)."""
        eq = [self.starting_balance]
        bal = self.starting_balance
        for t in sorted(self.trades, key=lambda x: (x.closed_at, x.symbol)):
            bal += t.realized_pnl
            eq.append(bal)
        return eq

    def max_drawdown(self) -> float:
        """Maksimum zirve-dip düşüşü (mutlak USDT)."""
        peak = -math.inf
        mdd = 0.0
        for v in self.equity_curve():
            peak = max(peak, v)
            mdd = max(mdd, peak - v)
        return mdd

    def sharpe(self) -> float | None:
        """
        İşlem başına getirinin (realized_pnl / margin) Sharpe'ı.

        n < min_trades_for_sharpe ise None döner ve rapor "hesaplanamaz" yazar.
        """
        if self.closed_count < self.min_trades_for_sharpe:
            return None
        rets = [t.realized_pnl / t.margin for t in self.trades if t.margin > 0]
        if len(rets) < 2:
            return None
        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
        sd = math.sqrt(var)
        if sd == 0:
            return None
        # ASSUMPTION: işlem başına getiri, örneklemli; yıllıklandırma yapılmadı.
        return mean / sd

    # -- metin -------------------------------------------------------------
    def render(self) -> str:
        """İnsan-okur metin raporu döndürür."""
        lines: list[str] = []
        lines.append("=" * 68)
        lines.append("PAPER FUTURES — KÂR/ZARAR RAPORU")
        lines.append("=" * 68)
        lines.append(f"Başlangıç bakiyesi : {self.starting_balance:.2f} USDT")
        lines.append(f"Bitiş bakiyesi     : {self.ending_balance:.2f} USDT")
        lines.append(f"Toplam gerçekleşen : {self.total_realized:+.4f} USDT")
        lines.append(f"Toplam komisyon    : {self.total_fees:.4f} USDT")
        lines.append(f"Kapalı işlem       : {self.closed_count}")
        lines.append("")

        if self.closed_count == 0:
            lines.append("İşlem yok — istatistik üretilemedi.")
        else:
            lines.append(f"Kazanma oranı      : {self.win_rate * 100:.2f}%")
            pf = self.profit_factor
            pf_txt = "inf (zarar yok)" if pf == math.inf else ("n/a" if pf is None else f"{pf:.3f}")
            lines.append(f"Profit factor      : {pf_txt}")
            lines.append(f"Ortalama kazanç    : {self.avg_win:+.4f} USDT")
            lines.append(f"Ortalama kayıp     : {self.avg_loss:+.4f} USDT")
            lines.append(f"Beklenen değer/işlem: {self.expected_value:+.4f} USDT")
            lines.append(f"Maks. düşüş (MDD)  : {self.max_drawdown():.4f} USDT")

            split = self.long_short_split()
            for side in ("LONG", "SHORT"):
                s = split[side]
                lines.append(
                    f"  {side:<5} işlem={int(s['count']):<4} pnl={s['pnl']:+.4f} "
                    f"win={s['win_rate'] * 100:.1f}%"
                )

        sharpe = self.sharpe()
        if sharpe is None:
            lines.append(
                f"Sharpe             : {SHARPE_SUPPRESSED_TEXT} "
                f"(kapalı işlem {self.closed_count} < {self.min_trades_for_sharpe})"
            )
        else:
            lines.append(f"Sharpe (işlem bazlı): {sharpe:.4f}")

        lines.append("")
        lines.append(f"Funding            : {FUNDING_LABEL}")
        lines.append("Not                : Sonuçlar yalnızca paper simülasyonudur;")
        lines.append("                     gerçek performans göstergesi DEĞİLDİR.")
        lines.append("=" * 68)
        return "\n".join(lines)


def render_table(records: list[TradeRecord], limit: int = 20) -> str:
    """Son işlemleri tablo olarak döndürür (tabulate varsa)."""
    if not records:
        return "(işlem yok)"
    rows = [
        [
            r.symbol,
            r.side,
            f"{r.entry_price:.4f}",
            f"{r.exit_price:.4f}",
            f"{r.realized_pnl:+.4f}",
            r.reason,
        ]
        for r in records[-limit:]
    ]
    headers = ["sembol", "yön", "giriş", "çıkış", "net PnL", "sebep"]
    try:
        from tabulate import tabulate

        return tabulate(rows, headers=headers, tablefmt="simple")
    except ImportError:  # tabulate yoksa düz metin
        out = [" | ".join(headers)]
        out += [" | ".join(map(str, row)) for row in rows]
        return "\n".join(out)
