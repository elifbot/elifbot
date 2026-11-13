"""Kripto Bot v9.1 — Katı Gürültü Filtreli Hakem Katmanı (`LiveLLMReferee`).

v9.1 Yükseltmeleri:
  1. Kör "Fail-Open" (`approved=True`) Kaldırıldı:
     - Canlı LLM API anahtarı tanımlıysa gerçek zamanlı JSON risk hakemliği yapar.
     - API anahtarı yoksa veya ağ zaman aşımı oluşursa sinyali körü körüne onaylamak yerine
       `strict_quant_noise_audit` (Katı Kantitatif Gürültü Denetimi) çalıştırarak sınırda kalan,
       ters para akışına çarpan veya testere rejimindeki gürültülü sinyalleri eler.
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import aiohttp


DEFAULT_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


class LiveLLMReferee:
    """Aday sinyalleri gürültüye karşı denetleyen hibrit LLM + Katı Mikroyapı Hakemi."""

    def __init__(
        self,
        *,
        api_key: str = "",
        api_url: str = DEFAULT_OPENROUTER_URL,
        model: str = "deepseek/deepseek-chat",
        timeout_sec: float = 2.5,
        enabled: bool = True,
        strict_noise_filter: bool = True,
        min_consensus_score: float = 40.0,
        max_allowed_choppiness: float = 61.5,
        contra_flow_veto: float = 8.0,
    ) -> None:
        self.api_key = str(api_key or "").strip()
        self.api_url = str(api_url or DEFAULT_OPENROUTER_URL).strip()
        self.model = str(model or "deepseek/deepseek-chat").strip()
        self.timeout_sec = max(0.5, float(timeout_sec))
        self.enabled = bool(enabled)
        self.strict_noise_filter = bool(strict_noise_filter)
        self.min_consensus_score = float(min_consensus_score)
        self.max_allowed_choppiness = float(max_allowed_choppiness)
        self.contra_flow_veto = float(contra_flow_veto)
        self.stats = {
            "mode": "LIVE_LLM" if (self.enabled and bool(self.api_key)) else "STRICT_QUANT_REFEREE",
            "calls": 0,
            "approved": 0,
            "vetoed": 0,
            "fallbacks": 0,
            "quant_audits": 0,
        }

    @classmethod
    def from_config_dict(
        cls,
        api_cfg: dict[str, Any] | None = None,
        *,
        timeout_sec: float = 2.5,
        ref_cfg: dict[str, Any] | None = None,
    ) -> "LiveLLMReferee":
        d = api_cfg or {}
        rc = ref_cfg or {}
        return cls(
            api_key=str(d.get("llm_key") or d.get("llm_api_key") or ""),
            api_url=str(d.get("llm_url") or d.get("llm_api_url") or DEFAULT_OPENROUTER_URL),
            model=str(d.get("llm_model") or "deepseek/deepseek-chat"),
            timeout_sec=timeout_sec,
            enabled=bool(rc.get("aktif", True)),
            strict_noise_filter=bool(rc.get("siki_gurultu_filtresi", True)),
            min_consensus_score=float(rc.get("min_konsensus_skoru", 40.0)),
            max_allowed_choppiness=float(rc.get("maks_izin_choppiness", 61.5)),
            contra_flow_veto=float(rc.get("ters_akis_veto_esigi", 8.0)),
        )

    @property
    def is_live_configured(self) -> bool:
        return self.enabled and bool(self.api_key)

    def strict_quant_noise_audit(self, candidate: dict[str, Any]) -> dict[str, Any]:
        """Kör onay yerine mikroyapı, rejim, choppiness ve akış tutarlılığını denetler."""
        self.stats["quant_audits"] += 1
        if not self.strict_noise_filter:
            self.stats["approved"] += 1
            return {
                "mode": "RULE_ONLY",
                "approved": True,
                "status": "RULE_ONLY_BYPASS",
                "model": None,
                "latency_ms": 0.0,
                "rationale": "Gürültü filtresi devre dışı.",
            }

        side = str(candidate.get("side") or "").upper()
        playbook = str(candidate.get("playbook") or "")
        macro = str(candidate.get("macro_regime") or candidate.get("regime") or "")
        vol_declining = bool(candidate.get("volume_declining", False))
        chop = float(candidate.get("choppiness_14", 50.0))
        flow_score = float(candidate.get("flow_score", 0.0))
        consensus = float(candidate.get("consensus_score", 50.0))
        rvol = float(candidate.get("rvol", 1.0))

        # 1) Çöküş veya aşırı testere gürültüsü
        if macro == "CRASH_RISK_OFF":
            self.stats["vetoed"] += 1
            return {
                "mode": "STRICT_QUANT_REFEREE",
                "approved": False,
                "status": "VETO_CRASH_REGIME",
                "model": None,
                "latency_ms": 0.0,
                "rationale": "Çöküş rejiminde yeni pozisyon hakem tarafından reddedildi.",
            }

        if chop >= self.max_allowed_choppiness and playbook != "VOLUME_DIVERGENCE_SHORT":
            self.stats["vetoed"] += 1
            return {
                "mode": "STRICT_QUANT_REFEREE",
                "approved": False,
                "status": "VETO_HIGH_CHOPPINESS",
                "model": None,
                "latency_ms": 0.0,
                "rationale": f"Yüksek testere endeksi (chop={chop:.1f} >= {self.max_allowed_choppiness:.1f}).",
            }

        # 2) Ayı trendi veya Yatay Dağıtımda düşen hacimli LONG çift-kilit reddi
        if side == "LONG" and vol_declining and macro in ("BEARISH_TREND", "YATAY_DAGITIM"):
            self.stats["vetoed"] += 1
            return {
                "mode": "STRICT_QUANT_REFEREE",
                "approved": False,
                "status": "VETO_BEARISH_DISTRIBUTION_LONG",
                "model": None,
                "latency_ms": 0.0,
                "rationale": f"{macro} ve düşen hacimde LONG hakem tarafından veto edildi.",
            }

        # 3) Güçlü ters orderflow çelişkisi
        if (side == "LONG" and flow_score <= -self.contra_flow_veto) or (
            side == "SHORT" and flow_score >= self.contra_flow_veto
        ):
            self.stats["vetoed"] += 1
            return {
                "mode": "STRICT_QUANT_REFEREE",
                "approved": False,
                "status": "VETO_CONTRA_ORDERFLOW",
                "model": None,
                "latency_ms": 0.0,
                "rationale": f"Yön ({side}) ile canlı orderflow ({flow_score:+.1f}) çelişiyor.",
            }

        # 4) Sınırda (zayıf) konsensüs elenmesi
        if consensus < self.min_consensus_score and playbook != "VOLUME_DIVERGENCE_SHORT":
            if not (rvol >= 1.30 and abs(flow_score) >= 22.0):
                self.stats["vetoed"] += 1
                return {
                    "mode": "STRICT_QUANT_REFEREE",
                    "approved": False,
                    "status": "VETO_WEAK_CONSENSUS",
                    "model": None,
                    "latency_ms": 0.0,
                    "rationale": f"Sınırda sinyal elendi (konsensüs={consensus:.1f} < {self.min_consensus_score:.1f}).",
                }

        self.stats["approved"] += 1
        return {
            "mode": "STRICT_QUANT_REFEREE",
            "approved": True,
            "status": "APPROVED_CLEAN_SIGNAL",
            "model": None,
            "latency_ms": 0.0,
            "rationale": f"Temiz sinyal onaylandı (playbook={playbook}, chop={chop:.1f}, konsensüs={consensus:.1f}).",
        }

    async def adjudicate(
        self,
        candidate: dict[str, Any],
        *,
        session: aiohttp.ClientSession | None = None,
    ) -> dict[str, Any]:
        """Önce katı gürültü denetimini uygular; canlı LLM aktifse ek derin değerlendirme yapar."""
        quant_check = self.strict_quant_noise_audit(candidate)
        if not quant_check["approved"] or not self.is_live_configured:
            return quant_check

        # Canlı LLM aktifse quant_check verdiği `approved` sayacını geri alıp nihai sayacı LLM kararına bırak
        self.stats["approved"] = max(0, self.stats["approved"] - 1)
        self.stats["calls"] += 1
        t0 = time.monotonic()
        prompt = (
            "Sen kurumsal bir kripto vadeli işlem risk hakemisin. "
            "Testere/gürültü, düşen hacimde ayı tuzağı veya sahte kırılım görürsen VETO ver. "
            "YALNIZCA geçerli JSON döndür: "
            '{"verdict":"APPROVE"|"VETO","confidence":0.0-1.0,"reason":"kisa_gerekce"}.\n'
            f"Aday: {json.dumps(candidate, ensure_ascii=False)}"
        )
        payload = {
            "model": self.model,
            "temperature": 0.0,
            "max_tokens": 120,
            "messages": [{"role": "user", "content": prompt}],
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        timeout = aiohttp.ClientTimeout(total=self.timeout_sec)

        try:
            owns_session = session is None
            active_session = session if session is not None else aiohttp.ClientSession(timeout=timeout)
            try:
                async with active_session.post(
                    self.api_url, json=payload, headers=headers, timeout=timeout
                ) as resp:
                    latency_ms = round((time.monotonic() - t0) * 1000.0, 2)
                    if resp.status != 200:
                        self.stats["fallbacks"] += 1
                        self.stats["approved"] += 1
                        return {
                            **quant_check,
                            "status": f"FALLBACK_HTTP_{resp.status}_QUANT_APPROVED",
                            "latency_ms": latency_ms,
                        }
                    data = await resp.json(content_type=None)
            finally:
                if owns_session:
                    await active_session.close()

            raw_txt = (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                .strip()
            )
            start_idx = raw_txt.find("{")
            end_idx = raw_txt.rfind("}")
            parsed = json.loads(raw_txt[start_idx : end_idx + 1]) if start_idx >= 0 and end_idx > start_idx else {}
            verdict = str(parsed.get("verdict", "APPROVE")).upper()
            approved = verdict != "VETO"
            if approved:
                self.stats["approved"] += 1
            else:
                self.stats["vetoed"] += 1
            return {
                "mode": "LIVE_LLM",
                "approved": approved,
                "status": "LIVE_VERDICT",
                "model": self.model,
                "latency_ms": latency_ms,
                "confidence": float(parsed.get("confidence", 0.75) or 0.75),
                "rationale": str(parsed.get("reason") or "LLM hakem kararı"),
            }
        except (asyncio.TimeoutError, Exception):
            self.stats["fallbacks"] += 1
            self.stats["approved"] += 1
            return {
                **quant_check,
                "status": "FALLBACK_QUANT_APPROVED",
                "latency_ms": round((time.monotonic() - t0) * 1000.0, 2),
            }
