import asyncio,json
from pathlib import Path
from scripts.probe_v944_pending import run_probe


def test_controlled_http_contract_for_four_intent_tables(tmp_path):
    result=asyncio.run(run_probe(tmp_path/'controlled'))
    assert result['http_samples']==33
    assert result['young_owned_pending_200_cases']==4
    assert result['all_health_requests_durable_db_unchanged']
    assert result['controlled_pending_http_verified']
    assert result['pending_in_flight_observed_live'] is False
