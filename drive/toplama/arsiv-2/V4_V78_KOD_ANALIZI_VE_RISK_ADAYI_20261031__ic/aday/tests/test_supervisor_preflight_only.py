"""Supervisor dry preflight never starts any process, on pass or fail."""
import importlib.util
from pathlib import Path
import pytest

@pytest.mark.parametrize('ok',[True,False])
def test_preflight_only_never_launches_bot(ok,monkeypatch,capsys,tmp_path):
    root=Path(__file__).resolve().parents[2]
    monkeypatch.setenv('V78_RUN_DIR',str(tmp_path))
    spec=importlib.util.spec_from_file_location('supervisor_preflight_test',root/'paper_5dk_supertrend_supervisor.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    monkeypatch.setattr(m,'sample',lambda:{'ok':ok,'synthetic':True})
    def forbidden(*a,**kw):raise AssertionError('bot must not start during preflight')
    monkeypatch.setattr(m.subprocess,'Popen',forbidden)
    monkeypatch.setattr(m,'run',forbidden)
    assert m.main(['--preflight-only'])==(0 if ok else 1)
    assert 'synthetic' in capsys.readouterr().out


@pytest.mark.parametrize('kernel,expected',[
    ({'state':0,'status':0,'synchronized':True},True),
    ({'state':5,'status':64,'synchronized':False},False),
    ({'state':5,'status':4096,'synchronized':False},False),
])
def test_clock_guard_requires_kernel_and_timedatectl_agreement(kernel,expected):
    root=Path(__file__).resolve().parents[2]
    spec=importlib.util.spec_from_file_location('clock_sample_test',root/'gozlem/saat_kontrolu.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    from types import SimpleNamespace
    def runner(args,**kwargs):
        if args[0]=='timedatectl':return SimpleNamespace(stdout='yes\n')
        return SimpleNamespace(stdout='Stratum : 2\nSystem time : 0.001 seconds fast\nRoot delay : 0.001 seconds\nRoot dispersion : 0.001 seconds\nLeap status : Normal\n')
    value=m.sample(runner=runner,kernel_reader=lambda:kernel)
    assert value['ok'] is expected and value['timedatectl_synchronized'] is True
    assert value['kernel_synchronized'] is kernel['synchronized']


def test_kernel_read_failure_is_fail_closed():
    root=Path(__file__).resolve().parents[2]
    spec=importlib.util.spec_from_file_location('clock_sample_failure',root/'gozlem/saat_kontrolu.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    from types import SimpleNamespace
    def runner(args,**kwargs):
        return SimpleNamespace(stdout='yes\n' if args[0]=='timedatectl' else 'Stratum : 2\nSystem time : 0.001 seconds fast\nRoot delay : 0.001 seconds\nRoot dispersion : 0.001 seconds\nLeap status : Normal\n')
    def fail():raise OSError('not available')
    assert m.sample(runner=runner,kernel_reader=fail)['ok'] is False
