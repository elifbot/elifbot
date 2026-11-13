"""
tools/file_writer.py — CrewAI ajanlarının gerçek dosya yazmasını sağlayan araç.

Neden gerekli: Bu crew'in önceki sürümünde "dosya yazma aracı yok" deniyor ve
tüm kod düz metin olarak döktürülüyordu. Sonuç: çalıştırılabilir bir ZIP değil,
kopyalanması gereken bir metin yığını. Bu araç, ajanın çıktısını doğrudan
diske yazmasını sağlar.

Güvenlik: yazma işlemi `base_dir` (varsayılan: output/) içinde kalır.
Mutlak yollar ve `..` ile dışarı çıkma denemeleri reddedilir.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field


class FileWriterInput(BaseModel):
    """Dosya yazma girdisi."""

    path: str = Field(
        ...,
        description="output/ altına göreli yol, örn. 'futures_bot/main.py'",
    )
    content: str = Field(..., description="Dosyanın tam içeriği")


class FileWriterTool(BaseTool):
    """Ajanın ürettiği dosyayı diske yazar (output/ dizini altına)."""

    name: str = "Dosya Yazıcı"
    description: str = (
        "Üretilen kaynak kodu, test veya dokümanı diske yazar. "
        "'path' alanı output/ dizinine GÖRELİ olmalıdır (örn. 'futures_bot/main.py'). "
        "Her dosya için bir kez çağır; içerik eksiksiz olmalı, '...' gibi kısaltma kullanma."
    )
    args_schema: Type[BaseModel] = FileWriterInput
    base_dir: str = "output"

    def _safe_target(self, rel_path: str) -> Path:
        """Yolu base_dir içine hapseder; kaçış denemelerini reddeder."""
        base = Path(self.base_dir).resolve()
        if rel_path.startswith("/") or rel_path.startswith("\\") or ":" in rel_path[:3]:
            raise ValueError("mutlak yol kabul edilmez; output/ altına göreli yol verin")
        target = (base / rel_path).resolve()
        if base not in target.parents and target != base:
            raise ValueError("base_dir dışına yazma reddedildi (path traversal)")
        return target

    def _run(self, path: str, content: str) -> str:
        try:
            target = self._safe_target(path)
        except ValueError as exc:
            return f"REDDEDİLDİ: {exc}"

        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(content)

        lines = content.count("\n") + 1
        size = os.path.getsize(target)
        return f"YAZILDI: {target} ({lines} satır, {size} bayt)"
