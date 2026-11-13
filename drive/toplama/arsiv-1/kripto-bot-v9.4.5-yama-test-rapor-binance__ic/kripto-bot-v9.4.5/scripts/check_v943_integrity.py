"""Validate current source freeze AND delivered file manifest, with explicit scope."""
from pathlib import Path
import argparse,hashlib,json
ROOT=Path(__file__).resolve().parents[1]
def main():
    args=argparse.ArgumentParser();args.add_argument('--sources-only',action='store_true');a=args.parse_args()
    path=ROOT/'reports/v943_packaging_freeze_manifest.json'
    if not path.exists():path=ROOT/'reports/v943_freeze_manifest.json'
    m=json.loads(path.read_text())
    bad=[n for n,h in m['source_sha256'].items() if not (ROOT/n).is_file() or hashlib.sha256((ROOT/n).read_bytes()).hexdigest()!=h]
    if bad:raise RuntimeError('Frozen source changed: '+str(bad))
    print('SOURCE OK:',len(m['source_sha256']),'files;',path.name)
    if a.sources_only:return
    pkg=ROOT/'PACKAGE_MANIFEST.json'
    if not pkg.exists():raise RuntimeError('PACKAGE_MANIFEST.json missing; cannot claim package integrity')
    inventory=json.loads(pkg.read_text())['files']
    wrong=[n for n,h in inventory.items() if not (ROOT/n).is_file() or hashlib.sha256((ROOT/n).read_bytes()).hexdigest()!=h]
    if wrong:raise RuntimeError('Delivered file hash mismatch: '+str(wrong))
    for name in ['RELEASE_STATUS.json','reports/v943_test_results.json','reports/v943_report_generation.json']:
        data=json.loads((ROOT/name).read_text())
        if 'live_operational_checks_passed' in data:raise RuntimeError('Deprecated broad acceptance field: '+name)
        if 'pending_in_flight_observed_live' not in data:raise RuntimeError('Missing explicit live evidence field: '+name)
    print('PACKAGE OK:',len(inventory),'files; canonical report and scoped JSON fields verified')
if __name__=='__main__':main()
