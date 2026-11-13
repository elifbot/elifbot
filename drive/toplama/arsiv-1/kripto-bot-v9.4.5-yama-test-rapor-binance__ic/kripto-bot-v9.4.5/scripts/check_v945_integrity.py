"""Check current v9.4.5 source freeze and the delivered file manifest."""
from pathlib import Path
import argparse,hashlib,json
ROOT=Path(__file__).resolve().parents[1]


def main():
    p=argparse.ArgumentParser();p.add_argument('--sources-only',action='store_true');a=p.parse_args()
    frozen=json.loads((ROOT/'reports/v945/source_freeze.json').read_text())['source_sha256']
    def mismatches(files):
        return [n for n,h in files.items() if not (ROOT/n).is_file() or hashlib.sha256((ROOT/n).read_bytes()).hexdigest()!=h]
    bad=mismatches(frozen)
    if bad:raise RuntimeError('Source mismatch: '+str(bad))
    print('SOURCE OK:',len(frozen),'files')
    if a.sources_only:return
    files=json.loads((ROOT/'PACKAGE_MANIFEST.json').read_text())['files'];bad=mismatches(files)
    if bad:raise RuntimeError('Package mismatch: '+str(bad))
    s=json.loads((ROOT/'RELEASE_STATUS.json').read_text())
    assert s['version']=='9.4.5' and isinstance(s['pending_in_flight_observed_live'], bool)
    assert s['real_money_approved'] is False and 'live_operational_checks_passed' not in s
    assert s['controlled_pending_http_verified'] is True
    print('PACKAGE OK:',len(files),'files; synthetic/live evidence scope explicit')


if __name__=='__main__':main()
