"""v5.2 — DİNAMİK RİSK ÖLÇEKLEME (kullanıcı önerisi madde 6).

SORUN
-----
v5.1'e kadar işlem başı risk SABİTTİ: `account.max_loss_per_position`.
90 günlük doğrulamada bunun iki kötü sonucu görüldü:

  1. İlk zararlardan sonra portföy drawdown koruması (%8) devreye girip
     TÜM yeni girişleri kesti (1.117 `PORTFOLIO_DRAWDOWN_PROTECTION` reddi).
     Yani sistem "hep 25 USDT" ile başladı, duvara çarptı ve durdu.
     Kademeli küçülme olmadığı için koruma bir uçurum gibi çalıştı.

  2. Ölçülen maliyet bazı sembollerde risk bütçesini yiyor:
     DOGE gidiş-dönüş kayması ~45 bps. %1,5 stopla bu, hedef riskin
     ~%23'ü; daha dar stopta %80'e çıkıyor. Sabit risk bunu görmez.

ÇÖZÜM
-----
`RiskScaler` her girişten önce bir BÜTÇE üretir. Bütçe şu bileşenlerin
EN KÜÇÜĞÜdür (hepsi (0,1] aralığında bir ölçek):

  drawdown   : equity tepeden %2 aşağıda küçülmeye başlar, %8'de tabana iner
  streak     : ardışık kayıplar (ilk 2 bedava, sonra her biri -%15)
  expectancy : son 50 işlemin ortalama R'i negatifse orantılı küçülme
  cost       : gidiş-dönüş maliyeti / (stop + maliyet) oranı eşiği aşarsa
  recovery   : histerezis — tek kazançla tam boyuta dönülmez

Ayrıca SERT maliyet kapısı: maliyet, risk bütçesinin %60'ından fazlasını
yiyorsa işlem hiç açılmaz (`MALIYET_BUTCESI_ASIMI`). Likiditesi kötü
sembolde "25 USDT risk" diye girip 20 USDT'yi kaymaya vermek anlamsızdır.

Ölçekleme ASLA yukarı gitmez: tavan, taban risktir. Kanıtlanmamış kenarda
boyut büyütmek, kaybı hızlandırmaktan başka işe yaramaz.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from math import isfinite


@dataclass(frozen=True)
class RiskScalingConfig:
    """Dinamik risk ölçekleme ayarları.

    min_risk_usdt : ölçek 0'a inse bile inilecek taban (kullanıcı: 2,5)
    max_risk_usdt : 0 = tavan taban risktir (yukarı ölçekleme YOK)
    """

    enabled: bool = True
    min_risk_usdt: float = 2.5
    max_risk_usdt: float = 0.0

    drawdown_start_pct: float = 2.0
    drawdown_floor_pct: float = 8.0

    loss_streak_free: int = 2
    loss_streak_step: float = 0.15
    loss_streak_floor: float = 0.25

    expectancy_min_trades: int = 20
    expectancy_window: int = 50
    expectancy_r_floor: float = -0.25

    max_cost_fraction_of_risk: float = 0.35
    hard_cost_fraction_of_risk: float = 0.60

    recovery_wins: int = 3
    recovery_step: float = 0.10

    # v5.4: ölçekleyicinin istediği risk tabanın ALTINDA kalırsa ne olsun?
    #   "block"    -> işlem AÇILMAZ (dürüst; ölçekleyici 'çok pahalı' dedi)
    #   "floor_up" -> tabana YÜKSELTİLİR (eski davranış, İYİMSER, riski büyütür)
    # Eski davranış min_risk_usdt tabanını ölçekleyicinin isteğinin üstüne
    # çıkarıyordu: 0,039 USDT isteyen adaya 2,50 USDT veriliyordu (64x).
    below_floor_action: str = "block"

    def __post_init__(self) -> None:
        if self.min_risk_usdt <= 0:
            raise ValueError("min_risk_usdt pozitif olmalı")
        if self.below_floor_action not in ("block", "floor_up"):
            raise ValueError("below_floor_action: block | floor_up")
        if self.max_risk_usdt < 0:
            raise ValueError("max_risk_usdt negatif olamaz (0 = taban risk tavan)")
        if self.max_risk_usdt and self.max_risk_usdt < self.min_risk_usdt:
            raise ValueError("max_risk_usdt >= min_risk_usdt olmalı")
        if self.drawdown_start_pct < 0:
            raise ValueError("drawdown_start_pct negatif olamaz")
        if self.drawdown_floor_pct <= self.drawdown_start_pct:
            raise ValueError("drawdown_floor_pct > drawdown_start_pct olmalı")
        if self.loss_streak_free < 0:
            raise ValueError("loss_streak_free negatif olamaz")
        if not 0 < self.loss_streak_step <= 1:
            raise ValueError("loss_streak_step (0,1] aralığında olmalı")
        if not 0 < self.loss_streak_floor <= 1:
            raise ValueError("loss_streak_floor (0,1] aralığında olmalı")
        if self.expectancy_min_trades < 1:
            raise ValueError("expectancy_min_trades >= 1 olmalı")
        if self.expectancy_window < 1:
            raise ValueError("expectancy_window >= 1 olmalı")
        if self.expectancy_r_floor >= 0:
            raise ValueError("expectancy_r_floor negatif olmalı")
        if not 0 < self.max_cost_fraction_of_risk < 1:
            raise ValueError("max_cost_fraction_of_risk (0,1) aralığında olmalı")
        if not 0 < self.hard_cost_fraction_of_risk < 1:
            raise ValueError("hard_cost_fraction_of_risk (0,1) aralığında olmalı")
        if self.hard_cost_fraction_of_risk <= self.max_cost_fraction_of_risk:
            raise ValueError(
                "hard_cost_fraction_of_risk > max_cost_fraction_of_risk olmalı",
            )
        if self.recovery_wins < 1:
            raise ValueError("recovery_wins >= 1 olmalı")
        if not 0 < self.recovery_step <= 1:
            raise ValueError("recovery_step (0,1] aralığında olmalı")


@dataclass(frozen=True)
class RiskBudget:
    """Bir giriş için hesaplanan bütçe + hangi bileşenin bağladığı."""

    base_usdt: float
    budget_usdt: float
    scale: float
    components: dict[str, float] = field(default_factory=dict)
    binding: str = "none"
    blocked: bool = False
    block_reason: str | None = None

    def as_dict(self) -> dict:
        return {
            "base_usdt": round(self.base_usdt, 6),
            "budget_usdt": round(self.budget_usdt, 6),
            "scale": round(self.scale, 6),
            "components": {k: round(v, 6) for k, v in self.components.items()},
            "binding": self.binding,
            "blocked": self.blocked,
            "block_reason": self.block_reason,
        }


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


class RiskScaler:
    """Durumlu ölçekleyici. Kapanan işlemlerle beslenir, bütçe üretir.

    Deterministiktir: aynı işlem dizisi + aynı equity → aynı bütçe.
    """

    def __init__(self, config: RiskScalingConfig | None = None) -> None:
        self.config = config or RiskScalingConfig()
        self.consecutive_losses = 0
        self.consecutive_wins = 0
        self.trade_count = 0
        self.recovery_cap = 1.0
        self._recent_r: deque[float] = deque(maxlen=self.config.expectancy_window)
        self.budgets_issued = 0
        self.blocked_count = 0
        self.below_floor_blocks = 0
        self.binding_counts: dict[str, int] = {}
        self.min_scale_seen = 1.0
        self.scale_sum = 0.0

    # ------------------------------------------------------------------

    def observe(self, pnl: float, target_net_risk: float = 0.0) -> None:
        """Kapanan bir işlemi kaydet. pnl NET olmalı (ücret + kayma dâhil)."""
        if not isfinite(pnl):
            return
        self.trade_count += 1
        if target_net_risk > 0 and isfinite(target_net_risk):
            self._recent_r.append(pnl / target_net_risk)
        else:
            self._recent_r.append(0.0)
        cfg = self.config
        if pnl < 0:
            self.consecutive_losses += 1
            self.consecutive_wins = 0
            self.recovery_cap = max(
                cfg.loss_streak_floor, self.recovery_cap - cfg.loss_streak_step,
            )
        elif pnl > 0:
            self.consecutive_wins += 1
            self.consecutive_losses = 0
            if self.consecutive_wins % cfg.recovery_wins == 0:
                self.recovery_cap = min(1.0, self.recovery_cap + cfg.recovery_step)
        # pnl == 0: nötr, seri sıfırlanmaz

    # ------------------------------------------------------------------

    @property
    def mean_recent_r(self) -> float:
        if not self._recent_r:
            return 0.0
        return sum(self._recent_r) / len(self._recent_r)

    def drawdown_scale(self, drawdown_pct: float) -> float:
        cfg = self.config
        if not isfinite(drawdown_pct) or drawdown_pct <= cfg.drawdown_start_pct:
            return 1.0
        if drawdown_pct >= cfg.drawdown_floor_pct:
            return 0.0
        span = cfg.drawdown_floor_pct - cfg.drawdown_start_pct
        return _clamp(1.0 - (drawdown_pct - cfg.drawdown_start_pct) / span, 0.0, 1.0)

    def streak_scale(self) -> float:
        cfg = self.config
        excess = max(0, self.consecutive_losses - cfg.loss_streak_free)
        return _clamp(
            1.0 - excess * cfg.loss_streak_step, cfg.loss_streak_floor, 1.0,
        )

    def expectancy_scale(self) -> float:
        cfg = self.config
        if self.trade_count < cfg.expectancy_min_trades:
            return 1.0
        mean_r = self.mean_recent_r
        if mean_r >= 0:
            return 1.0
        return _clamp(1.0 - abs(mean_r) / abs(cfg.expectancy_r_floor), 0.0, 1.0)

    def cost_scale(self, cost_rate: float, stop_fraction: float) -> tuple[float, bool]:
        """Maliyetin risk bütçesindeki payı. (ölçek, sert_ret) döndürür."""
        cfg = self.config
        if cost_rate <= 0 or stop_fraction <= 0:
            return 1.0, False
        total = stop_fraction + cost_rate
        if total <= 0:
            return 1.0, False
        fraction = cost_rate / total
        if fraction >= cfg.hard_cost_fraction_of_risk:
            return 0.0, True
        if fraction <= cfg.max_cost_fraction_of_risk:
            return 1.0, False
        span = cfg.hard_cost_fraction_of_risk - cfg.max_cost_fraction_of_risk
        return _clamp(
            1.0 - (fraction - cfg.max_cost_fraction_of_risk) / span, 0.0, 1.0,
        ), False

    # ------------------------------------------------------------------

    def budget(
        self,
        base_usdt: float,
        drawdown_pct: float = 0.0,
        cost_rate: float = 0.0,
        stop_fraction: float = 0.0,
    ) -> RiskBudget:
        """Bu giriş için kullanılacak net risk bütçesi (USDT)."""
        cfg = self.config
        if base_usdt <= 0 or not isfinite(base_usdt):
            raise ValueError("base_usdt pozitif ve sonlu olmalı")
        if not cfg.enabled:
            return RiskBudget(
                base_usdt=base_usdt, budget_usdt=base_usdt, scale=1.0,
                components={"disabled": 1.0}, binding="disabled",
            )

        cost_scale, hard_block = self.cost_scale(cost_rate, stop_fraction)
        if hard_block:
            self.blocked_count += 1
            return RiskBudget(
                base_usdt=base_usdt, budget_usdt=0.0, scale=0.0,
                components={"cost": 0.0}, binding="cost",
                blocked=True, block_reason="MALIYET_BUTCESI_ASIMI",
            )

        components = {
            "drawdown": self.drawdown_scale(drawdown_pct),
            "streak": self.streak_scale(),
            "expectancy": self.expectancy_scale(),
            "cost": cost_scale,
            "recovery": self.recovery_cap,
        }
        binding = min(components, key=lambda k: components[k])
        scale = components[binding]
        # v5.4 DÜZELTME: hiçbir bileşen kısmıyorsa bağlayıcı YOKTUR.
        # min() sözlük sırasındaki ilk anahtarı ('drawdown') döndürüyordu;
        # taze hesapta 'drawdown 6 kez bağladı' diye yanlış raporlanıyordu.
        if scale >= 1.0:
            binding = "none"
        ceiling = cfg.max_risk_usdt if cfg.max_risk_usdt > 0 else base_usdt
        desired = base_usdt * scale
        # v5.4 DÜZELTME: taban, ölçekleyicinin isteğini YUKARI çekemez.
        # İstenen risk tabanın altındaysa işlem açılmaz (varsayılan).
        if desired < cfg.min_risk_usdt and cfg.below_floor_action == "block":
            self.blocked_count += 1
            self.below_floor_blocks += 1
            return RiskBudget(
                base_usdt=base_usdt, budget_usdt=0.0, scale=scale,
                components=components, binding=binding,
                blocked=True, block_reason="OLCEK_TABAN_ALTINDA",
            )
        budget = _clamp(desired, cfg.min_risk_usdt, ceiling)
        # Taban, tavanı aşamaz (küçük taban risklerde güvenlik).
        budget = min(budget, ceiling)

        self.budgets_issued += 1
        self.binding_counts[binding] = self.binding_counts.get(binding, 0) + 1
        self.min_scale_seen = min(self.min_scale_seen, scale)
        self.scale_sum += scale
        return RiskBudget(
            base_usdt=base_usdt, budget_usdt=budget, scale=scale,
            components=components, binding=binding,
        )

    # ------------------------------------------------------------------

    def stats(self) -> dict:
        return {
            "enabled": self.config.enabled,
            "budgets_issued": self.budgets_issued,
            "blocked_count": self.blocked_count,
            "below_floor_blocks": self.below_floor_blocks,
            "below_floor_action": self.config.below_floor_action,
            "binding_counts": dict(sorted(self.binding_counts.items())),
            "min_scale_seen": round(self.min_scale_seen, 6),
            "mean_scale": (
                round(self.scale_sum / self.budgets_issued, 6)
                if self.budgets_issued else 1.0
            ),
            "final_recovery_cap": round(self.recovery_cap, 6),
            "observed_trades": self.trade_count,
            "mean_recent_r": round(self.mean_recent_r, 6),
            "min_risk_usdt": self.config.min_risk_usdt,
            "max_risk_usdt": self.config.max_risk_usdt,
        }
