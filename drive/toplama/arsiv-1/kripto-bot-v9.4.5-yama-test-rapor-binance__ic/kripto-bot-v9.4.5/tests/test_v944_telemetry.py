import ast,copy,hashlib,json
from pathlib import Path
from types import SimpleNamespace
import pytest
from src.evaluation_telemetry import evaluation_telemetry_snapshot


@pytest.mark.parametrize('total,reasons,retry,other',[(0,{},0,0),(4972,{'ONE_ATTEMPT_PER_CLOSED_BAR':4596},4596,376),(10,{'ONE_ATTEMPT_PER_CLOSED_BAR':4,'POSITION_WAIT_NEXT_CLOSED_BAR':3,'HOLD_CONFIRMED_THESIS':1},7,3),(9,{'SPREAD_TOO_WIDE':2},0,9)])
def test_counter_classification_is_readonly(total,reasons,retry,other):
    e=SimpleNamespace(metrics={'signals_evaluated':total},v94_router=SimpleNamespace(rejections=reasons))
    before=copy.deepcopy(vars(e));v=evaluation_telemetry_snapshot(e)
    assert v['evaluation_calls_total']==total and v['retry_suppressed_total']==retry
    assert v['non_retry_evaluation_calls']==other and v['unique_signal_count'] is None
    assert v['counter_consistent']
    assert e.metrics==before['metrics'] and e.v94_router.rejections==before['v94_router'].rejections
    assert 'ONE_ATTEMPT_PER_CLOSED_BAR' not in v['non_retry_reason_counts']
    assert 'POSITION_WAIT_NEXT_CLOSED_BAR' not in v['non_retry_reason_counts']


def test_counter_inconsistency_not_silently_clamped():
    e=SimpleNamespace(metrics={'signals_evaluated':1},v94_router=SimpleNamespace(rejections={'ONE_ATTEMPT_PER_CLOSED_BAR':2}))
    v=evaluation_telemetry_snapshot(e)
    assert not v['counter_consistent'] and v['non_retry_evaluation_calls']==-1


def test_panel_has_counter_elements_and_interrupted_label():
    from src.live_runner import DASHBOARD_HTML as HTML
    for name in ('evalTotal','evalRetry','evalOther'):assert f'id="{name}"' in HTML
    assert "INTERRUPTED:'KESİLDİ'" in HTML and "FAILED:'HATA'" in HTML
