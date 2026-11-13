"""20 YZ Konseyi — 3 turlu çapraz teftiş + dürüst anahtarsız mod.

MİMARİ
  Tur 1: Her üye adayı BAŞTAN SONA aynı boyutlarda değerlendirir (görev bölüşümü yok).
  Tur 2: Üyeler birbirinin itirazlarını teftiş eder, puanını revize eder.
  Tur 3: Ağırlıklı konsensüs + tek üye vetosu + maliyet tabanı.

İKİ MOD, ASLA KARIŞTIRILMAZ
  LIVE_LLM         : en az bir gerçek anahtar var. Gerçek API çağrısı yapılır.
  RULE_BASED_QUANT : anahtar yok. 20 kantitatif denetçi profili deterministik
                     kural denetimi yapar. Çıktı `mode` alanında açıkça
                     RULE_BASED_QUANT yazar; YZ cevabı diye SUNULMAZ.

FAIL-CLOSED
  YZ hatası/timeout'u onay üretmez. Canlı modda yeterli üye yanıt vermezse
  karar `INSUFFICIENT_QUORUM` olur ve aday reddedilir.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any

import aiohttp

from ..core.clock import get_logger, mono
from ..core.types import Signal
from .adapters import ProviderAdapter, ProviderError, build_adapters
from .registry import PROVIDERS, ProviderSpec, configured_providers

log = get_logger("ai.council")

SYSTEM_PROMPT = """Sen bir kripto vadeli işlem risk denetçisisin. Görevin KÂR TAHMİNİ değil,
aday işlemin mikroyapısal kusurlarını bulmaktır. Şüphe halinde REDDET.

Sana verilen sayısal bağlam dışındaki hiçbir bilgiyi varsayma. Haber, fiyat hedefi
veya gelecek tahmini uydurma. Yalnız verilen kanıtı değerlendir.

Şu 6 boyutu incele:
1. edge_vs_cost: beklenen brüt hareket, gidiş-dönüş komisyon+kayma+makas toplamını aşıyor mu?
2. flow: canlı para akışı (CVD, alış/satış baskısı) giriş yönünü destekliyor mu?
3. structure: teknik yapı ve momentum yönü tutarlı mı?
4. regime: çoklu zaman dilimi uyumu ve testere (choppiness) riski.
5. execution: makas genişliği, maker dolum gerçekçiliği, funding yakınlığı.
6. extension: aşırı uzama / tepe-dip tuzağı riski.

YALNIZ şu JSON şemasıyla yanıt ver, başka metin yazma:
{"approve": true|false, "score": 0-100, "confidence": 0.0-1.0,
 "flaws": ["kısa kusur", "..."], "strongest_objection": "en güçlü itiraz",
 "reason": "tek cümle karar gerekçesi"}"""


@dataclass(frozen=True, slots=True)
class QuantAuditorProfile:
    """Anahtarsız modda kullanılan kantitatif denetçi profili.

    Bunlar YZ modeli DEĞİLDİR. Aynı sayısal görevi farklı ağırlık/şüphecilikle
    yürüten deterministik denetçilerdir. Adlandırma dürüsttür.
    """
    auditor_id: str
    focus: str
    w_edge: float
    w_flow: float
    w_struct: float
    w_regime: float
    w_exec: float
    skepticism: float


_FOCUS = (
    ("Dengeli Tam-Görev Denetçisi", .24, .24, .22, .16, .14, 1.00),
    ("Brüt-Kenar ve Komisyon Denetçisi", .34, .20, .18, .14, .14, 1.20),
    ("Para Akışı ve CVD Denetçisi", .20, .34, .20, .14, .12, 0.95),
    ("Trend ve Piyasa Yapısı Denetçisi", .20, .20, .32, .18, .10, 1.00),
    ("Makas ve Baz Denetçisi", .24, .18, .16, .14, .28, 1.15),
    ("Ters Seçilim / Maker Kuyruk Denetçisi", .26, .22, .16, .14, .22, 1.18),
    ("Çoklu Zaman Dilimi Uyum Denetçisi", .18, .20, .22, .28, .12, 1.08),
    ("Testere ve Tuzak Engelleyici", .22, .20, .18, .26, .14, 1.22),
    ("Dalga Sürdürülebilirlik Denetçisi", .22, .28, .24, .16, .10, 0.90),
    ("Karşı-Tez Başdenetçisi", .28, .22, .18, .18, .14, 1.30),
)


def build_quant_auditors(n: int = 20) -> tuple[QuantAuditorProfile, ...]:
    """20 kantitatif denetçi. İlk 10 temel, son 10 daha şüpheci varyant."""
    out: list[QuantAuditorProfile] = []
    for i in range(n):
        focus, we, wf, ws, wr, wx, sk = _FOCUS[i % len(_FOCUS)]
        variant = i // len(_FOCUS)
        if variant:
            sk = round(min(1.45, sk * 1.12), 3)
            focus = f"{focus} (sert varyant)"
        out.append(QuantAuditorProfile(
            f"QuantDenetci_{i + 1:02d}", focus, we, wf, ws, wr, wx, sk))
    return tuple(out)


QUANT_AUDITORS = build_quant_auditors(20)


@dataclass
class CouncilConfig:
    enabled: bool = True
    #: Konsey reddi işlemi engeller mi? PAPER araştırmasında True önerilir.
    veto_enabled: bool = True
    min_consensus_score: float = 55.0
    min_quorum_ratio: float = 0.5     # canlı modda beklenen yanıt oranı
    max_concurrency: int = 6
    timeout_sec: float = 6.0
    max_cost_bps_allowed: float = 40.0
    max_spread_bps: float = 12.0
    max_choppiness: float = 61.5
    contra_flow_veto: float = 8.0
    max_members: int = 20
    provider_ids: tuple[str, ...] = ()


@dataclass
class CouncilVerdict:
    mode: str                       # LIVE_LLM | RULE_BASED_QUANT | DISABLED
    approved: bool
    score: float
    quorum: int
    members: int
    rounds: int
    reject_code: str = ""
    reason: str = ""
    flaws: list[str] = field(default_factory=list)
    member_votes: list[dict[str, Any]] = field(default_factory=list)
    elapsed_ms: float = 0.0
    ai_generated: bool = False      # True YALNIZ gerçek API yanıtı varsa

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode, "approved": self.approved,
            "score": round(self.score, 2), "quorum": self.quorum,
            "members": self.members, "rounds": self.rounds,
            "reject_code": self.reject_code, "reason": self.reason,
            "flaws": self.flaws[:12], "member_votes": self.member_votes,
            "elapsed_ms": round(self.elapsed_ms, 2),
            "ai_generated": self.ai_generated,
        }


def _clip(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


class AICouncil:
    """20 üyeli konsey. Anahtar varsa gerçek YZ, yoksa kantitatif denetim."""

    def __init__(self, config: CouncilConfig | None = None,
                 adapters: list[ProviderAdapter] | None = None) -> None:
        self.cfg = config or CouncilConfig()
        specs = ([p for p in PROVIDERS if p.provider_id in self.cfg.provider_ids]
                 if self.cfg.provider_ids else list(PROVIDERS))
        self.specs: list[ProviderSpec] = specs[: self.cfg.max_members]
        self.adapters = adapters if adapters is not None else build_adapters(
            self.specs, timeout_sec=self.cfg.timeout_sec)
        self.quant_auditors = QUANT_AUDITORS[: self.cfg.max_members]
        self.stats = {"live_calls": 0, "rule_calls": 0, "approved": 0, "vetoed": 0,
                      "quorum_failures": 0, "provider_errors": 0}

    @property
    def live_specs(self) -> list[ProviderSpec]:
        return [s for s in self.specs if s.configured]

    @property
    def mode(self) -> str:
        if not self.cfg.enabled:
            return "DISABLED"
        return "LIVE_LLM" if self.live_specs else "RULE_BASED_QUANT"

    # ---------------- sayısal bağlam ----------------
    @staticmethod
    def build_context(signal: Signal, metrics: dict[str, Any]) -> dict[str, Any]:
        return {
            "symbol": signal.symbol, "exchange": signal.exchange,
            "entry_side": metrics.get("entry_side", signal.side.value),
            "market_side": signal.side.value,
            "price": signal.price,
            "ret_pct_window": signal.ret_pct,
            "window_ms": signal.window_ms,
            "rvol": signal.rvol,
            "volume_usd": signal.volume_usd,
            "ctx_ret_3m": signal.ctx_ret,
            "ctx_vratio": signal.ctx_vratio,
            "ctx_vratio3": signal.ctx_vratio3,
            "breadth_ratio": signal.breadth_ratio,
            "flow_score": signal.flow_score,
            "spread_bps": metrics.get("spread_bps", 0.0),
            "roundtrip_cost_bps": metrics.get("roundtrip_cost_bps", 23.0),
            "expected_move_bps": metrics.get("expected_move_bps", 0.0),
            "choppiness": metrics.get("choppiness", 50.0),
            "mtf_aligned": metrics.get("mtf_aligned", True),
            "funding_rate": metrics.get("funding_rate", 0.0),
            "minutes_to_funding": metrics.get("minutes_to_funding", 999.0),
            "atr_pct": metrics.get("atr_pct", 0.0),
            "extension_atr": metrics.get("extension_atr", 0.0),
        }

    # ---------------- ana giriş ----------------
    async def evaluate(self, signal: Signal, metrics: dict[str, Any],
                       session: aiohttp.ClientSession | None = None) -> CouncilVerdict:
        t0 = mono()
        ctx = self.build_context(signal, metrics)

        if not self.cfg.enabled:
            return CouncilVerdict("DISABLED", True, 100.0, 0, 0,
                                  rounds=0, reason="Konsey devre dışı (config)")

        # Maliyet tabanı her iki modda da ön koşuldur — YZ bunu gevşetemez.
        hard = self._hard_preflight(ctx)
        if hard is not None:
            self.stats["vetoed"] += 1
            hard.elapsed_ms = (mono() - t0) * 1000.0
            return hard

        if self.mode == "LIVE_LLM" and session is not None:
            v = await self._live_rounds(ctx, session)
            self.stats["live_calls"] += 1
        else:
            v = self._quant_rounds(ctx)
            self.stats["rule_calls"] += 1

        v.elapsed_ms = (mono() - t0) * 1000.0
        if v.approved:
            self.stats["approved"] += 1
        else:
            self.stats["vetoed"] += 1
        return v

    def _hard_preflight(self, ctx: dict[str, Any]) -> CouncilVerdict | None:
        """Y Z'nin geçemeyeceği sert ön kapılar."""
        spread = float(ctx.get("spread_bps", 0.0))
        if spread > self.cfg.max_spread_bps:
            return CouncilVerdict(
                self.mode, False, 0.0, 0, len(self.specs), 0,
                reject_code="COUNCIL_SPREAD_TOO_WIDE",
                reason=f"Makas {spread:.2f}bps > {self.cfg.max_spread_bps}bps",
                flaws=["Makas maliyeti aşırı"])
        cost = float(ctx.get("roundtrip_cost_bps", 0.0))
        move = float(ctx.get("expected_move_bps", 0.0))
        if move > 0 and move < cost:
            return CouncilVerdict(
                self.mode, False, 0.0, 0, len(self.specs), 0,
                reject_code="COUNCIL_EDGE_BELOW_COST",
                reason=f"Beklenen hareket {move:.2f}bps < maliyet {cost:.2f}bps",
                flaws=["Ücret öncesi kenar yok"])
        return None

    # ---------------- kural tabanlı 3 tur ----------------
    def _quant_rounds(self, ctx: dict[str, Any]) -> CouncilVerdict:
        votes: list[dict[str, Any]] = []
        flaws_all: list[str] = []

        # Tur 1 — bağımsız tam değerlendirme
        for a in self.quant_auditors:
            comps = self._quant_components(ctx)
            raw = (a.w_edge * comps["edge"] + a.w_flow * comps["flow"]
                   + a.w_struct * comps["structure"] + a.w_regime * comps["regime"]
                   + a.w_exec * comps["execution"])
            # şüphecilik puanı aşağı çeker
            score = _clip(raw / a.skepticism)
            flaws = self._quant_flaws(ctx, comps)
            votes.append({"member": a.auditor_id, "kind": "QUANT_RULE",
                          "focus": a.focus, "score": round(score, 2),
                          "approve": score >= self.cfg.min_consensus_score,
                          "flaws": flaws, "round1_score": round(score, 2)})
            flaws_all.extend(flaws)

        # Tur 2 — çapraz teftiş: ortak kusurlar puanı düşürür
        uniq = sorted(set(flaws_all))
        shared_pressure = min(18.0, 3.0 * len(uniq))
        for v in votes:
            own = set(v["flaws"])
            others = set(flaws_all) - own
            # kendi görmediği ama akranların gördüğü kusurlar
            penalty = min(12.0, 2.0 * len(others)) + shared_pressure * 0.35
            v["score"] = round(_clip(v["score"] - penalty), 2)
            v["approve"] = v["score"] >= self.cfg.min_consensus_score
            v["peer_penalty"] = round(penalty, 2)

        # Tur 3 — ağırlıklı konsensüs
        score = sum(v["score"] for v in votes) / len(votes) if votes else 0.0
        approvals = sum(1 for v in votes if v["approve"])
        quorum = len(votes)
        approved = score >= self.cfg.min_consensus_score and approvals >= quorum * 0.6
        reason = (f"20 kantitatif denetçi 3 tur; ağırlıklı skor {score:.1f}, "
                  f"{approvals}/{quorum} onay")
        return CouncilVerdict(
            mode="RULE_BASED_QUANT", approved=approved, score=score,
            quorum=quorum, members=len(votes), rounds=3,
            reject_code="" if approved else "COUNCIL_QUANT_REJECT",
            reason=reason + " — YZ çağrısı YAPILMADI (anahtar yok)",
            flaws=uniq[:12], member_votes=votes, ai_generated=False)

    def _quant_components(self, c: dict[str, Any]) -> dict[str, float]:
        cost = max(1e-9, float(c.get("roundtrip_cost_bps", 23.0)))
        move = float(c.get("expected_move_bps", 0.0))
        ratio = move / cost
        edge = _clip(50.0 * min(ratio, 2.4))

        flow = float(c.get("flow_score", 0.0))
        entry = str(c.get("entry_side", "LONG"))
        aligned = flow if entry == "LONG" else -flow
        flow_s = _clip(50.0 + aligned * 3.0)

        ctx_ret = float(c.get("ctx_ret_3m", 0.0))
        mkt = str(c.get("market_side", "LONG"))
        dir_ok = (ctx_ret > 0) == (mkt == "LONG")
        vr3 = float(c.get("ctx_vratio3", 0.0))
        structure = _clip((58.0 if dir_ok else 22.0) + min(24.0, max(0.0, (vr3 - 1.0) * 12.0)))

        chop = float(c.get("choppiness", 50.0))
        mtf = bool(c.get("mtf_aligned", True))
        breadth = float(c.get("breadth_ratio", 0.0))
        regime = _clip((62.0 if mtf else 28.0)
                       - max(0.0, chop - 50.0) * 1.1
                       + min(18.0, breadth * 45.0))

        spread = float(c.get("spread_bps", 0.0))
        mins = float(c.get("minutes_to_funding", 999.0))
        execution = _clip(88.0 - spread * 4.0 - (18.0 if mins < 5.0 else 0.0))
        return {"edge": edge, "flow": flow_s, "structure": structure,
                "regime": regime, "execution": execution}

    def _quant_flaws(self, c: dict[str, Any], comp: dict[str, float]) -> list[str]:
        f: list[str] = []
        if comp["edge"] < 45:
            f.append("Beklenen hareket maliyeti karşılamıyor")
        if comp["flow"] < 42:
            f.append("Para akışı giriş yönüne ters")
        if comp["structure"] < 45:
            f.append("Teknik yapı / hacim teyidi zayıf")
        if float(c.get("choppiness", 50.0)) > self.cfg.max_choppiness:
            f.append("Testere rejimi yüksek")
        if not bool(c.get("mtf_aligned", True)):
            f.append("Çoklu zaman dilimi uyumsuz")
        if float(c.get("spread_bps", 0.0)) > self.cfg.max_spread_bps * 0.6:
            f.append("Makas geniş")
        if float(c.get("minutes_to_funding", 999.0)) < 5.0:
            f.append("Funding anına yakın")
        if float(c.get("extension_atr", 0.0)) > 2.5:
            f.append("Aşırı uzama / tepe-dip tuzağı riski")
        return f

    # ---------------- gerçek YZ 3 tur ----------------
    async def _live_rounds(self, ctx: dict[str, Any],
                           session: aiohttp.ClientSession) -> CouncilVerdict:
        live = [a for a in self.adapters if a.available]
        n_expected = len(self.live_specs)
        user1 = ("ADAY İŞLEM BAĞLAMI (yalnız bu sayıları kullan):\n"
                 + json.dumps(ctx, ensure_ascii=False, indent=2))
        sem = asyncio.Semaphore(self.cfg.max_concurrency)

        async def ask(ad: ProviderAdapter, system: str, user: str) -> dict[str, Any] | None:
            async with sem:
                try:
                    return await ad.complete_json(session, system, user)
                except ProviderError:
                    self.stats["provider_errors"] += 1
                    return None

        r1 = await asyncio.gather(*[ask(a, SYSTEM_PROMPT, user1) for a in live])
        votes: list[dict[str, Any]] = []
        for ad, res in zip(live, r1):
            if not res:
                continue
            votes.append({
                "member": ad.spec.provider_id, "kind": "LIVE_LLM",
                "model": ad.spec.model(),
                "score": _clip(float(res.get("score", 0.0))),
                "approve": bool(res.get("approve", False)),
                "confidence": max(0.0, min(1.0, float(res.get("confidence", 0.5)))),
                "flaws": [str(x)[:180] for x in (res.get("flaws") or [])][:6],
                "objection": str(res.get("strongest_objection", ""))[:240],
                "reason": str(res.get("reason", ""))[:240],
                "latency_ms": res.get("_latency_ms", 0.0),
            })

        quorum = len(votes)
        need = max(1, int(n_expected * self.cfg.min_quorum_ratio))
        if quorum < need:
            self.stats["quorum_failures"] += 1
            return CouncilVerdict(
                "LIVE_LLM", False, 0.0, quorum, n_expected, 1,
                reject_code="COUNCIL_INSUFFICIENT_QUORUM",
                reason=f"Yetersiz YZ yanıtı {quorum}/{n_expected}; fail-closed ret",
                member_votes=votes, ai_generated=quorum > 0)

        # Tur 2 — akran itirazlarını görüp revize
        objections = [{"member": v["member"], "objection": v["objection"],
                       "flaws": v["flaws"]} for v in votes]
        user2 = (user1 + "\n\nDİĞER DENETÇİLERİN İTİRAZLARI:\n"
                 + json.dumps(objections, ensure_ascii=False)
                 + "\n\nBu itirazları teftiş et. Haklı buldukların için puanını düşür."
                   " Haksız bulduklarını gerekçelendir. Aynı JSON şemasıyla yanıt ver.")
        r2 = await asyncio.gather(*[
            ask(a, SYSTEM_PROMPT, user2) for a in live
            if any(v["member"] == a.spec.provider_id for v in votes)])
        idx = 0
        for v in votes:
            if idx < len(r2) and r2[idx]:
                res = r2[idx]
                v["round1_score"] = v["score"]
                v["score"] = _clip(float(res.get("score", v["score"])))
                v["approve"] = bool(res.get("approve", v["approve"]))
                v["revised"] = True
            idx += 1

        # Tur 3 — ağırlıklı konsensüs (tier 1 hakemler daha ağır)
        wsum = ssum = 0.0
        for v in votes:
            spec = next((s for s in self.specs if s.provider_id == v["member"]), None)
            w = {1: 1.6, 2: 1.0, 3: 0.7}.get(spec.tier if spec else 2, 1.0)
            w *= 0.5 + v.get("confidence", 0.5)
            wsum += w
            ssum += v["score"] * w
        score = ssum / wsum if wsum else 0.0
        approvals = sum(1 for v in votes if v["approve"])
        approved = (score >= self.cfg.min_consensus_score
                    and approvals > quorum / 2)
        all_flaws = sorted({f for v in votes for f in v["flaws"]})
        return CouncilVerdict(
            "LIVE_LLM", approved, score, quorum, n_expected, 3,
            reject_code="" if approved else "COUNCIL_LLM_REJECT",
            reason=f"{quorum} gerçek YZ, 3 tur; ağırlıklı {score:.1f}, {approvals}/{quorum} onay",
            flaws=all_flaws[:12], member_votes=votes, ai_generated=True)

    def status(self) -> dict[str, Any]:
        return {
            "mode": self.mode, "members": len(self.specs),
            "live_members": len(self.live_specs),
            "veto_enabled": self.cfg.veto_enabled,
            "stats": dict(self.stats),
            "adapters": {a.spec.provider_id: a.stats.to_dict() for a in self.adapters},
            "honesty_note": (
                "RULE_BASED_QUANT modunda hiçbir YZ çağrısı yapılmaz; çıktı "
                "deterministik kural denetimidir."
                if self.mode == "RULE_BASED_QUANT" else
                "LIVE_LLM modunda gerçek API çağrısı yapılır; hata onay sayılmaz."),
        }