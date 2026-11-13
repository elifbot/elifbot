"""v6.2 real assertions: no network, no real order, fail-closed boundaries."""
from dataclasses import replace
from unittest.mock import Mock
import logging
import sqlite3

import pytest

from core.config import SuperConfig
from live.entry_safety import EntrySafetyError, check_new_entry
from live.sync import LiveMirror
from safety.security import SecretSafeFormatter, mask_secrets, register_secret
from state.store import StateIntegrityError, StateStore


def cfg():
    return replace(SuperConfig().v2.live, enabled=True,
                   live_allowed_timeframes=('5m',), live_requires_edge_proof=False)


def exchange(filters=True):
    broker = Mock()
    rows = [{'symbol': 'BTCUSDT', 'filters': [
        {'filterType': 'PRICE_FILTER', 'tickSize': '0.1'},
        {'filterType': 'LOT_SIZE', 'stepSize': '0.001', 'minQty': '0.001'},
        {'filterType': 'MIN_NOTIONAL', 'notional': '5'},
    ]}] if filters else []
    broker.client.public_request.return_value.as_dict.return_value = {'symbols': rows}
    broker.place_entry.return_value = Mock()
    return broker


def mirror(broker, **kwargs):
    defaults = dict(binance=broker, entry_timeframe='5m', live_cfg=cfg(),
                    state_saver=lambda _d: None, state_loader=lambda: {}, entry_style='market')
    defaults.update(kwargs)
    return LiveMirror(**defaults)


def test_none_config_never_sends_entry():
    broker = exchange()
    m = mirror(broker, live_cfg=None)
    assert m.mirror_open('BTCUSDT', 'LONG', .01, 95., 's', 100.) == []
    broker.place_entry.assert_not_called()
    broker.client.public_request.assert_not_called()


def test_disabled_config_never_sends_entry():
    b = exchange()
    m = mirror(b, live_cfg=replace(cfg(), enabled=False))
    assert not m.mirror_open('BTCUSDT', 'LONG', .1, 95., 's', 100.)
    b.place_entry.assert_not_called()


def test_no_edge_proof_blocks_before_metadata():
    b = exchange()
    m = mirror(b, live_cfg=replace(cfg(), live_requires_edge_proof=True))
    assert not m.mirror_open('BTCUSDT', 'LONG', .1, 95., 's', 100.)
    b.client.public_request.assert_not_called()
    b.place_entry.assert_not_called()


def test_missing_persistence_blocks_before_orders():
    b = exchange()
    m = mirror(b, state_loader=None)
    assert not m.mirror_open('BTCUSDT', 'LONG', .1, 95., 's', 100.)
    b.place_entry.assert_not_called()


def test_corrupt_state_loader_blocks_entry_but_not_exit():
    b = exchange()
    def broken():
        raise StateIntegrityError('bad')
    m = mirror(b, state_loader=broken)
    assert not m.mirror_open('BTCUSDT', 'LONG', .1, 95., 's', 100.)
    b.place_entry.assert_not_called()
    m.mirror_close('BTCUSDT', 'LONG', .1, 'close')
    b.place_reduce_only_exit.assert_called_once()


def test_missing_metadata_blocks_entry_not_silently_trusted():
    b = exchange(False)
    m = mirror(b)
    assert not m.mirror_open('BTCUSDT', 'LONG', .1, 95., 's', 100.)
    b.place_entry.assert_not_called()


@pytest.mark.parametrize('quantity,stop,limit', [
    (.1001, 95., 100.), (.1, 95.05, 100.), (.1, 95., 100.05),
    (.1, 105., 100.), (float('nan'), 95., 100.), (.0, 95., 100.),
])
def test_invalid_qty_or_stop_blocks(quantity, stop, limit):
    b = exchange()
    assert not mirror(b).mirror_open('BTCUSDT', 'LONG', quantity, stop, 's', limit)
    b.place_entry.assert_not_called()


def test_valid_entry_sends_one_order_and_stop():
    b = exchange()
    m = mirror(b)
    actions = m.mirror_open('BTCUSDT', 'LONG', .1, 95., 's', 100.)
    assert len(actions) == 2
    b.place_entry.assert_called_once()
    b.place_protective_stop.assert_called_once()
    assert not m.mirror_open('BTCUSDT', 'LONG', .1, 95., 's', 100.)
    b.place_entry.assert_called_once()


def test_dca_closed_with_no_config_even_if_stop_record_exists():
    b = exchange()
    m = mirror(b, live_cfg=None)
    m.stop_prices['BTCUSDT'] = 95.
    assert not m.mirror_dca('BTCUSDT', 'LONG', .1, 'd1')
    b.place_entry.assert_not_called()


def test_dca_closed_if_exchange_stop_not_verified():
    b = exchange()
    m = mirror(b)
    m.stop_prices['BTCUSDT'] = 95.
    m.stop_client_ids['BTCUSDT'] = 'stop-1'
    b.fetch_positions.return_value = [Mock(symbol='BTCUSDT', side='LONG', quantity=.1)]
    b.fetch_open_orders.return_value = []
    assert not m.mirror_dca('BTCUSDT', 'LONG', .1, 'd1')
    b.place_entry.assert_not_called()


def test_dca_allowed_only_after_matching_position_and_stop():
    b = exchange()
    m = mirror(b)
    m.stop_prices['BTCUSDT'] = 95.
    m.stop_client_ids['BTCUSDT'] = 'stop-1'
    b.fetch_positions.return_value = [Mock(symbol='BTCUSDT', side='LONG', quantity=.1)]
    b.fetch_open_orders.return_value = [Mock(client_order_id='stop-1')]
    assert m.mirror_dca('BTCUSDT', 'LONG', .1, 'd1')
    b.place_entry.assert_called_once()


def test_state_saving_error_blocks_subsequent_entries():
    b = exchange()
    def saver(_):
        raise OSError('disk full')
    m = mirror(b, state_saver=saver)
    assert m.mirror_open('BTCUSDT', 'LONG', .1, 95., 'a', 100.)
    assert not m.mirror_open('BTCUSDT', 'LONG', .1, 95., 'b', 100.)
    assert b.place_entry.call_count == 1


def test_okx_missing_metadata_rejected():
    b = Mock()
    b.client.public_request.return_value.as_dict.return_value = {'data': [{'instId': 'BTC-USDT-SWAP'}]}
    with pytest.raises(EntrySafetyError):
        check_new_entry(b, 'okx', 'BTC-USDT-SWAP', 'LONG', .1, stop=95., limit=100.)


def test_okx_contract_grid_and_tick():
    b = Mock()
    b.client.public_request.return_value.as_dict.return_value = {'data': [
        {'instId': 'BTC-USDT-SWAP', 'ctVal': '.01', 'lotSz': '1', 'minSz': '1', 'tickSz': '.1'}]}
    check_new_entry(b, 'okx', 'BTC-USDT-SWAP', 'LONG', .1, stop=95., limit=100.)
    with pytest.raises(EntrySafetyError):
        check_new_entry(b, 'okx', 'BTC-USDT-SWAP', 'LONG', .105, stop=95., limit=100.)


def test_mirror_state_corrupt_json_fails_closed(tmp_path):
    with StateStore(tmp_path/'state.db') as store:
        store._connection.execute('INSERT INTO mirror_state(key,value) VALUES (?,?)', ('live_mirror', '{bad'))
        store._connection.commit()
        with pytest.raises(StateIntegrityError):
            store.load_mirror_state()
        b = exchange()
        m = mirror(b, state_loader=store.load_mirror_state)
        assert not m.mirror_open('BTCUSDT', 'LONG', .1, 95., 's', 100.)
        b.place_entry.assert_not_called()


def test_verified_backup_and_no_overwrite(tmp_path):
    with StateStore(tmp_path/'source.db') as store:
        store.save_state({'balance': 123})
        path = store.backup(tmp_path/'backup.db')
        with sqlite3.connect(path) as c:
            assert c.execute('PRAGMA quick_check').fetchall() == [('ok',)]
        before = path.read_bytes()
        with pytest.raises(FileExistsError):
            store.backup(path)
        assert path.read_bytes() == before


def test_invalid_database_fails_without_replacement(tmp_path):
    path = tmp_path/'broken.db'
    path.write_bytes(b'not an sqlite file')
    with pytest.raises(sqlite3.DatabaseError):
        StateStore(path)
    assert path.read_bytes() == b'not an sqlite file'


def test_secrets_redacted_in_formatted_exception(monkeypatch):
    secret= '***REDACTED***'
    monkeypatch.setenv('BINANCE_TESTNET_API_SECRET', secret)
    record = logging.LogRecord('test', logging.ERROR, '', 0, 'error token=%s', (secret,), None)
    assert secret not in SecretSafeFormatter('%(message)s').format(record)
    assert secret not in mask_secrets('https://some/?signature='+secret)


def test_file_secret_registered_for_redaction(tmp_path, monkeypatch):
    from live.clients import read_secret
    path = tmp_path/'secret'
    path.write_text('file_secret_123456789')
    monkeypatch.setenv('OKX_DEMO_API_SECRET_FILE', str(path))
    assert read_secret('OKX_DEMO_API_SECRET') == 'file_secret_123456789'
    assert 'file_secret_123456789' not in mask_secrets('oops file_secret_123456789')
    register_secret('other_secret_1234')
    assert 'other_secret_1234' not in mask_secrets('other_secret_1234')


def test_defaults_no_real_money():
    live = SuperConfig().v2.live
    assert not live.enabled and live.live_allowed_timeframes == ()


def test_stale_adapter_cache_replaced_with_verified_grid():
    from live.broker_clients import BinanceFuturesTestnet, SymbolFilters
    b = BinanceFuturesTestnet(Mock())
    b.client.public_request.return_value.as_dict.return_value = exchange().client.public_request.return_value.as_dict.return_value
    b._filters['BTCUSDT'] = SymbolFilters(tick_size=10, step_size=1, min_qty=1)
    check_new_entry(b, 'binance', 'BTCUSDT', 'LONG', .1, stop=95., limit=100.)
    assert b._filters['BTCUSDT'].tick_size == .1
    assert b._filters['BTCUSDT'].step_size == .001


def test_open_orders_failure_does_not_imply_fill_or_market_fallback():
    b = exchange()
    b.fetch_open_orders.side_effect = OSError('no connection')
    m = mirror(b, entry_style='post_only_market_fallback')
    assert not m.mirror_open('BTCUSDT', 'LONG', .1, 95., 'a', 100.)
    assert b.place_entry.call_count == 1
    b.place_protective_stop.assert_not_called()
    assert not m._entry_state_healthy


def test_invalid_state_root_blocks_entry():
    b = exchange()
    m = mirror(b, state_loader=lambda: [])
    assert not m.mirror_open('BTCUSDT', 'LONG', .1, 95., 'a', 100.)
    b.place_entry.assert_not_called()


def test_failed_backup_verification_raises_and_never_deletes_existing(tmp_path, monkeypatch):
    source = StateStore(tmp_path/'source.db')
    original_connect = sqlite3.connect
    previous = tmp_path/'previous.db'
    previous.write_bytes(b'previous-backup-untouched')

    class BadBackup(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            if sql == 'PRAGMA quick_check':
                return Mock(fetchall=lambda: [('corrupt',)])
            return super().execute(sql, *args, **kwargs)

    monkeypatch.setattr(sqlite3, 'connect',
                        lambda *a, **kw: original_connect(*a, factory=BadBackup, **kw))
    try:
        with pytest.raises(StateIntegrityError):
            source.backup(tmp_path/'new-backup.db')
        assert not (tmp_path/'new-backup.db').exists()
        assert previous.read_bytes() == b'previous-backup-untouched'
    finally:
        source.close()


def test_cancel_failure_never_triggers_market_fallback():
    b = exchange()
    b.fetch_open_orders.return_value = [Mock(client_order_id='ACB2-XXX')]
    ticks = iter((100, 1100, 2100, 3100))
    m = mirror(b, entry_style='post_only_market_fallback', clock=lambda: next(ticks),
               entry_fill_timeout_s=0.1)
    b.fetch_order_by_client_id.return_value = Mock(executed_quantity=0)
    b.cancel_order_by_client_id.side_effect = OSError('unknown cancellation')
    assert not m.mirror_open('BTCUSDT', 'LONG', .1, 95., 'a', 100.)
    assert b.place_entry.call_count == 1
    assert not m._entry_state_healthy
