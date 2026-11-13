"""Check this health-only release's own freeze; do not reuse v9.4.1 manifests."""
from pathlib import Path
import hashlib,json
ROOT=Path(__file__).resolve().parents[1]
def main():
    m=json.loads((ROOT/'reports/v943_freeze_manifest.json').read_text())
    bad=[n for n,h in m['source_sha256'].items() if not (ROOT/n).exists() or hashlib.sha256((ROOT/n).read_bytes()).hexdigest()!=h]
    if bad:raise RuntimeError('v9.4.3 frozen source changed: '+str(bad))
    print('v9.4.3 source integrity OK:',len(m['source_sha256']),'files')
if __name__=='__main__':main()
