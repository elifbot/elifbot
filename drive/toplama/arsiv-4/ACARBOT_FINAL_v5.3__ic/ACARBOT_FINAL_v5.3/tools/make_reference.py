"""v5.2 — Referans dosyası üretici (sürüm regresyon kapısı için).

    # Gerçek doğrulama raporundan referans üret:
    python3 -m tools.make_reference --from docs/dogrulama_v5.2.json

    # Yalnızca deterministik fixture parmak izi (ağ yok):
    python3 -m tools.make_reference --fixture-only

Sürüm numarası değiştiğinde bu komut ÇALIŞTIRILMALIDIR; aksi hâlde
`tests/test_regression_gate.py` bayat referansı yakalar ve kırmızı verir.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from app import __version__
from backtest.regression_gate import REFERENCE_PATH, check_reference, make_reference

logger = logging.getLogger("make_reference")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backtest referansı üretici")
    parser.add_argument("--from", dest="source", default=None,
                        help="validate_strategy JSON raporu")
    parser.add_argument("--fixture-only", action="store_true")
    parser.add_argument("--out", default=REFERENCE_PATH)
    parser.add_argument("--profile", default="apex")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    config = None
    if not args.fixture_only:
        from tools.validate_strategy import _profile_config

        try:
            config = _profile_config(args.profile, None)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Profil yüklenemedi (%s) — varsayılan config", exc)
    real = None
    if args.source:
        real = json.loads(Path(args.source).read_text(encoding="utf-8"))
        if real.get("version") != __version__:
            logger.warning(
                "Kaynak rapor sürümü %s, paket sürümü %s — referans PAKET "
                "sürümüyle yazılacak, raporun bayat olduğu not edilecek",
                real.get("version"), __version__,
            )
            real["stale_source_warning"] = True
    reference = make_reference(__version__, real, config)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(reference, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    logger.info("Referans yazıldı: %s (sürüm %s)", out, __version__)
    gate = check_reference(reference, __version__, strict_dataset=False)
    for failure in gate.failures:
        logger.error("KAPI KIRMIZI: %s", failure)
    for warning in gate.warnings:
        logger.warning("KAPI UYARI: %s", warning)
    if gate.ok:
        logger.info("KAPI YEŞİL (fixture yeniden üretilebilir, maliyetler açık)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
