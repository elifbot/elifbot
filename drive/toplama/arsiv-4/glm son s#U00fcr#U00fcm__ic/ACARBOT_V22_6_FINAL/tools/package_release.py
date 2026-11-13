"""Build a clean release zip (no caches, no secrets/state): python tools/package_release.py [out.zip]"""
import pathlib
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKIP_DIRS = {"__pycache__", ".pytest_cache", ".git", ".venv", "venv"}
SKIP_SUFFIX = {".pyc", ".pyo", ".log"}
SKIP_NAMES = {".env", "state.json", "paper_state.json", "trades.jsonl", "paper_trades.jsonl", "live_test_report.json"}


def build(out):
    out = pathlib.Path(out)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(ROOT.rglob("*")):
            rel = p.relative_to(ROOT)
            if p.is_dir() or SKIP_DIRS & set(rel.parts) or p.suffix in SKIP_SUFFIX or p.name in SKIP_NAMES:
                continue
            if rel.parts[0] == "reports" and p.name != ".gitkeep":
                continue
            if p.resolve() == out.resolve():
                continue
            z.write(p, pathlib.Path(ROOT.name) / rel)
    return out


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else str(ROOT.parent / f"{ROOT.name}_release.zip")
    print("wrote", build(target))
