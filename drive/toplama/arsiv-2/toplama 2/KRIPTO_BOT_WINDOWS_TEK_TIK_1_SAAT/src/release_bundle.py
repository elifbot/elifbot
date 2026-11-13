"""Her yeni hazır bot sürümü için 4'lü e-posta ve yerel yedek paketi üretici.

Üretilen 4 Standart Dosya (backups/ altında):
  1. KRIPTO-BOT-{version}-MAIL-PAKETI.zip          (Tam proje + DB + tüm ekler)
  2. KRIPTO-BOT-{version}.patch                    (Temiz kaynak kod Git yaması)
  3. KRIPTO_BOT_{ver_slug}_TEK_DOSYA_KURUCU.py     (Tek parça öz-kurucu Python betiği)
  4. KRIPTO_BOT_{ver_slug}_TUM_KODLAMASYON.md      (Mimari + tüm açık kaynak kod kitabı)
"""
from __future__ import annotations

import argparse
import base64
import subprocess
import zipfile
import zlib
from pathlib import Path


def build_release_bundle(version: str = "v7.7", base_ref: str = "71ab07b") -> dict[str, str]:
    root = Path(__file__).resolve().parent.parent
    backups = root / "backups"
    backups.mkdir(exist_ok=True)
    slug = version.replace(".", "_").replace("-", "_")

    patch_bytes = subprocess.check_output(
        [
            "git",
            "diff",
            f"{base_ref}..HEAD",
            "--",
            "src",
            "tests",
            "configs",
            ".github",
            "config.yaml",
            "requirements.txt",
            "test_hizli.py",
            "test_bot_v7.py",
        ],
        cwd=root,
    )
    patch_path = backups / f"KRIPTO-BOT-{version}.patch"
    patch_path.write_bytes(patch_bytes)

    code_files: list[Path] = []
    for pattern in (
        "config.yaml",
        "requirements.txt",
        "README.md",
        "src/*.py",
        "configs/*.json",
        "tests/*.py",
        "test_hizli.py",
        "test_bot_v7.py",
        ".github/workflows/*.yml",
    ):
        for p in sorted(root.glob(pattern)):
            if p.is_file() and p not in code_files:
                code_files.append(p)

    bundle_dict = {
        str(p.relative_to(root)): base64.b64encode(
            zlib.compress(p.read_bytes(), level=9)
        ).decode("ascii")
        for p in code_files
    }
    installer_py = backups / f"KRIPTO_BOT_{slug}_TEK_DOSYA_KURUCU.py"
    installer_py.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                f'"""KRIPTO-BOT {version} — Tek Dosya Öz-Kurucu Python Paketi."""',
                "from __future__ import annotations",
                "import argparse, base64, zlib",
                "from pathlib import Path",
                f"FILES: dict[str, str] = {repr(bundle_dict)}",
                "def extract_all(target_dir: Path) -> int:",
                "    target_dir.mkdir(parents=True, exist_ok=True)",
                "    for rel_path, payload in FILES.items():",
                "        dest = target_dir / rel_path",
                "        dest.parent.mkdir(parents=True, exist_ok=True)",
                "        dest.write_bytes(zlib.decompress(base64.b64decode(payload.encode('ascii'))))",
                "    return len(FILES)",
                "def main() -> None:",
                f"    p = argparse.ArgumentParser(description='KRIPTO-BOT {version} Kurucu')",
                f"    p.add_argument('--hedef', default='kripto-bot-{version}')",
                "    out = Path(p.parse_args().hedef).resolve()",
                "    n = extract_all(out)",
                f"    print(f'✅ KRIPTO-BOT {version} kuruldu: {{out}} ({{n}} dosya)')",
                "if __name__ == '__main__':",
                "    main()",
                "",
            ]
        ),
        encoding="utf-8",
    )

    core_src = [root / "config.yaml", root / "requirements.txt"] + sorted(
        (root / "src").glob("*.py")
    )
    md_lines = [
        f"# 🤖 KRIPTO-BOT {version} — Tam Kodlamasyon ve Açık Kaynak Kod Kitabı",
        "",
    ]
    for fp in core_src:
        if not fp.exists():
            continue
        lang = (
            "yaml"
            if fp.suffix in (".yaml", ".yml")
            else ("python" if fp.suffix == ".py" else "text")
        )
        rel = fp.relative_to(root).as_posix()
        txt = fp.read_text(encoding="utf-8", errors="replace").rstrip()
        md_lines.append(f"## 📄 `{rel}`\n\n```{lang}\n{txt}\n```\n\n---\n")

    kodlamasyon_md = backups / f"KRIPTO_BOT_{slug}_TUM_KODLAMASYON.md"
    kodlamasyon_md.write_text("\n".join(md_lines), encoding="utf-8")

    mail_zip = backups / f"KRIPTO-BOT-{version}-MAIL-PAKETI.zip"
    with zipfile.ZipFile(mail_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for p in code_files:
            zf.write(p, f"kripto-bot-{version}/{p.relative_to(root).as_posix()}")
        zf.write(patch_path, f"EK_1_PATCH/{patch_path.name}")
        zf.write(installer_py, f"EK_2_TEK_DOSYA_PYTHON/{installer_py.name}")
        zf.write(kodlamasyon_md, f"EK_3_KODLAMASYON/{kodlamasyon_md.name}")
        db_p = backups / "kriptobot_kalici_hafiza.db"
        if db_p.exists():
            zf.write(db_p, f"EK_4_KALICI_VERITABANI/{db_p.name}")

    return {
        "zip": str(mail_zip),
        "patch": str(patch_path),
        "python_installer": str(installer_py),
        "kodlamasyon_md": str(kodlamasyon_md),
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default="v7.7")
    print(build_release_bundle(ap.parse_args().version))
