"""SIGINT işleyici davranışı: sentetik, dış ağ veya paper işlemi yok."""
import os
from pathlib import Path
import subprocess
import sys
import pytest

@pytest.mark.parametrize('initial', ['ignored', 'default', 'custom'])
def test_main_sigint_disposition_only_changes_ignored(initial):
    root=Path(__file__).resolve().parents[1]
    script='''
import signal, sys
import ws_bot
initial=sys.argv[1]
def custom(signum, frame): pass
handlers={'ignored': signal.SIG_IGN, 'default': signal.default_int_handler, 'custom': custom}
signal.signal(signal.SIGINT, handlers[initial])
assert signal.getsignal(signal.SIGINT) is handlers[initial]
try:
    ws_bot._main(['--help'])
except SystemExit as exc:
    assert exc.code == 0
else:
    raise AssertionError('argparse --help did not exit')
expected=signal.default_int_handler if initial=='ignored' else handlers[initial]
assert signal.getsignal(signal.SIGINT) is expected
print('SIGINT_PASS',initial)
'''
    env={**os.environ,'PYTHONPATH':str(root)}
    p=subprocess.run([sys.executable,'-c',script,initial],cwd=root,env=env,capture_output=True,text=True,timeout=20)
    assert p.returncode==0,(p.returncode,p.stdout,p.stderr)
    assert f'SIGINT_PASS {initial}' in p.stdout
