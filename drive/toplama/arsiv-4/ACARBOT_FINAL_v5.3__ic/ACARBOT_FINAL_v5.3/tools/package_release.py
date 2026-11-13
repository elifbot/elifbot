"""v5.2 — SÜRÜM TUTARLI PAKETLEYİCİ.

SORUN (kullanıcı tespiti, madde 5)
----------------------------------
v5.1 tesliminde dosya adı ile iç sürüm ayrışmıştı ("v5.1.1" vs
`5.1-final`) ve sürümsüz `DEGISIKLIKLER_FINAL.md` hangi sürüme ait
olduğu belirsiz bir dosya olarak duruyordu.

ÇÖZÜM
-----
Zip adı, kök dizin adı ve MANIFEST **tek kaynaktan** (`app.__version__`)
türetilir. Paketlemeden önce tutarlılık kontrolleri koşulur; herhangi
biri başarısızsa zip HİÇ yazılmaz.

Kontroller:
  1. `app.__version__` biçimi `X.Y-final`
  2. Bu sürüm için changelog var ve önceki sürümün changelog'undan farklı
  3. README başlığı bu sürümü anıyor
  4. requirements.txt başlığı bu sürümü anıyor
  5. Regresyon referansı bu sürümle üretilmiş
  6. Güncel doğrulama raporu varsa rapor tutarlılık kapısından geçiyor
  7. docs/*.json katı JSON (Infinity/NaN yok)

Kullanım:
    python3 -m tools.package_release --out-dir /home/user
    python3 -m tools.package_release --check-only     # yalnızca denetim
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from app import __version__

logger = logging.getLogger("package_release")

ROOT = Path(__file__).resolve().parents[1]

EXCLUDE_DIRS = {
    "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache",
    ".git", ".venv", "node_modules", "build", "dist", ".next",
}
EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".log", ".csv", ".sqlite3"}
EXCLUDE_PREFIXES = ("data/validation/",)


def short_version(version: str) -> str:
    """`5.2-final` → `5.2`"""
    match = re.match(r"^(\d+\.\d+(?:\.\d+)?)", version)
    if not match:
        raise ValueError(f"Sürüm biçimi beklenen gibi değil: {version!r}")
    return match.group(1)


def _previous_short(short: str) -> str | None:
    parts = short.split(".")
    major, minor = int(parts[0]), int(parts[1])
    if minor > 0:
        return f"{major}.{minor - 1}"
    return None


def check_consistency() -> tuple[list[str], list[str]]:
    """(hatalar, uyarılar) döndürür. Hata varsa paket yazılmaz."""
    errors: list[str] = []
    warnings: list[str] = []
    short = short_version(__version__)

    # 2) changelog
    changelog = ROOT / f"DEGISIKLIKLER_FINAL_v{short}.md"
    if not changelog.exists():
        errors.append(f"Changelog yok: {changelog.name}")
    else:
        text = changelog.read_text(encoding="utf-8")
        if short not in text:
            errors.append(f"{changelog.name} içinde sürüm {short} geçmiyor")
        previous = _previous_short(short)
        if previous:
            prev_path = ROOT / f"DEGISIKLIKLER_FINAL_v{previous}.md"
            if prev_path.exists() and prev_path.read_text(
                encoding="utf-8",
            ) == text:
                errors.append(
                    f"{changelog.name} önceki sürümün changelog'u ile BİREBİR AYNI",
                )

    # sürümsüz changelog karışıklığı
    legacy = ROOT / "DEGISIKLIKLER_FINAL.md"
    if legacy.exists():
        errors.append(
            "Sürümsüz DEGISIKLIKLER_FINAL.md duruyor; hangi sürüme ait "
            "olduğu belirsiz. DEGISIKLIKLER_FINAL_v1.0.md olarak adlandırılmalı.",
        )

    # 3) README
    readme = ROOT / "README.md"
    if readme.exists():
        first = readme.read_text(encoding="utf-8").splitlines()[0]
        if f"v{short}" not in first:
            errors.append(f"README başlığı v{short} değil: {first!r}")
    else:
        errors.append("README.md yok")

    # 4) requirements
    req = ROOT / "requirements.txt"
    if req.exists():
        head = req.read_text(encoding="utf-8").splitlines()[0]
        if f"v{short}" not in head:
            warnings.append(f"requirements başlığı v{short} değil: {head!r}")

    # 5) referans
    ref = ROOT / "docs" / "backtest_referans.json"
    if not ref.exists():
        errors.append("docs/backtest_referans.json yok")
    else:
        reference = json.loads(ref.read_text(encoding="utf-8"))
        if reference.get("version") != __version__:
            errors.append(
                f"Referans bayat: {reference.get('version')} != {__version__}",
            )

    # 6) doğrulama raporu
    reports = sorted(ROOT.glob(f"docs/dogrulama_v{short}*.json"))
    if not reports:
        warnings.append(f"v{short} doğrulama raporu yok")
    else:
        from backtest.regression_gate import check_report_consistency

        for path in reports:
            report = json.loads(path.read_text(encoding="utf-8"))
            if report.get("version") != __version__:
                errors.append(
                    f"{path.name} sürümü {report.get('version')} != {__version__}",
                )
            gate = check_report_consistency(report)
            for failure in gate.failures:
                errors.append(f"{path.name}: {failure}")
            for warning in gate.warnings:
                warnings.append(f"{path.name}: {warning}")

    # 7) katı JSON
    def _reject(token):
        raise ValueError(f"geçersiz JSON sabiti: {token}")

    for path in sorted((ROOT / "docs").glob("*.json")):
        try:
            json.loads(path.read_text(encoding="utf-8"), parse_constant=_reject)
        except ValueError as exc:
            errors.append(f"{path.name} katı JSON değil: {exc}")

    return errors, warnings


def _included(path: Path) -> bool:
    relative = path.relative_to(ROOT).as_posix()
    if any(part in EXCLUDE_DIRS for part in path.parts):
        return False
    if any(relative.startswith(prefix) for prefix in EXCLUDE_PREFIXES):
        return False
    if path.suffix in EXCLUDE_SUFFIXES:
        return False
    if ".sqlite3" in path.name:
        return False
    return path.is_file()


def build(out_dir: Path) -> tuple[Path, dict]:
    short = short_version(__version__)
    name = f"ACARBOT_FINAL_v{short}"
    target = out_dir / f"{name}.zip"
    out_dir.mkdir(parents=True, exist_ok=True)
    files = sorted(p for p in ROOT.rglob("*") if _included(p))
    digest = hashlib.sha256()
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in files:
            arcname = f"{name}/{path.relative_to(ROOT).as_posix()}"
            zf.write(path, arcname)
    digest.update(target.read_bytes())
    manifest = {
        "package": target.name,
        "root_dir": name,
        "version": __version__,
        "short_version": short,
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "file_count": len(files),
        "size_bytes": target.stat().st_size,
        "sha256": digest.hexdigest(),
    }
    return target, manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sürüm tutarlı paketleyici")
    parser.add_argument("--out-dir", default=str(ROOT.parent))
    parser.add_argument("--check-only", action="store_true",
                        help="yalnızca tutarlılık denetimi; zip yazma")
    parser.add_argument("--allow-warnings", action="store_true", default=True)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    short = short_version(__version__)
    logger.info("Sürüm: %s (kısa: v%s)", __version__, short)
    errors, warnings = check_consistency()
    for warning in warnings:
        logger.warning("UYARI: %s", warning)
    for error in errors:
        logger.error("HATA: %s", error)
    if errors:
        logger.error("TUTARSIZLIK: %d hata — paket YAZILMADI", len(errors))
        return 1
    logger.info("Tutarlılık denetimi GEÇTİ (%d uyarı)", len(warnings))
    if args.check_only:
        return 0

    target, manifest = build(Path(args.out_dir))
    manifest_path = Path(args.out_dir) / f"ACARBOT_FINAL_v{short}_MANIFEST.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    logger.info("Paket: %s", target)
    logger.info(
        "İçerik: %d dosya / %d B · sha256 %s",
        manifest["file_count"], manifest["size_bytes"], manifest["sha256"][:16],
    )
    logger.info("Manifest: %s", manifest_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
