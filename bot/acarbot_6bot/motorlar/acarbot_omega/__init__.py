# -*- coding: utf-8 -*-
"""
ACARBOT OMEGA v1.0 — Sıfırdan Kurumsal Çoklu-AI & Mikroyapı Vadeli İşlem Sistemi
================================================================================
Gmail + Google Drive'daki 16 bot ailesinin (PHOENIX V4, ACARBOT V6.2/V10/V20/V22,
APEX v1.1, KRIPTO-BOT v9.5.3, OMNISTUDIO 20-YZ Konseyi, NIHAL, AI-HUB) ve
TURBO v3.1 motorunun en güçlü mühendislik özelliklerinin sıfırdan temiz sentezi.
"""
from .config import OmegaConfig
from .contracts import ContractSpec, CostBreakdown, CostModel, parse_contract_spec
from .engine import AcarbotOmegaEngine

__version__ = "1.0.0-omega"
__all__ = [
    "__version__",
    "OmegaConfig",
    "ContractSpec",
    "CostBreakdown",
    "CostModel",
    "parse_contract_spec",
    "AcarbotOmegaEngine",
]
