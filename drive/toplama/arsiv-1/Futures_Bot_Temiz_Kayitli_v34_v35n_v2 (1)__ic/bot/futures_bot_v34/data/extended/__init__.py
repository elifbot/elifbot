"""Phase C — genişletilmiş veri kaynakları (doğrulanmamış / kullanılamıyor)."""
from __future__ import annotations


class DataUnavailableError(RuntimeError):
    """İstenen veri kaynağı doğrulanmadığında veya erişilemediğinde fırlatılır."""
