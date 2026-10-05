"""The authenticated save verifies backfill arithmetic and snapshot provenance."""
import copy

import pytest

from test_dsb import event, files  # reuse the existing isolated record fixture
from src import dsb
from src.state import read_json


def submission():
    result = event()
    payload = result['payload']
    payload['balances'] = {'2026-09-30': 85000, '2026-10-01': 85000,
                           '2026-10-02': 85000, '2026-10-03': 105000, '2026-10-04': 105000}
    payload['record']['planning_date'] = '2026-10-05'
    payload['record']['current_balance'] = 100000
    payload['record']['balance_backfill'] = {
        'start_date': '2026-09-30', 'anchor_date': '2026-10-05', 'anchor_balance': 100000,
        'captured_at': '2026-10-05T00:00:00Z', 'confirmed_complete': True, 'provisional': True,
        'net_changes': {'2026-10-01': 0, '2026-10-02': 0, '2026-10-03': 2000000,
                        '2026-10-04': 0, '2026-10-05': -500000}}
    return result


def test_backfill_commits_all_historical_days_and_provisional_snapshot_without_today_ledger(files):
    saved = dsb.save(submission(), files)
    assert saved['committed'] and saved['dsb']['version'] == 1
    assert '2026-10-05' not in saved['dsb']['balances']
    assert saved['dsb']['balances']['2026-09-30'] == 85000
    assert saved['dsb']['months']['2026-10']['balance_backfill']['provisional'] is True
    assert dsb.save(submission(), files)['dsb']['version'] == 1
    assert read_json(files / 'dsb-records.json') == saved['dsb']


@pytest.mark.parametrize('defect', ['mismatch', 'missing_net', 'unconfirmed', 'final_today', 'date_shift',
                                   'bad_timestamp', 'negative', 'fractional_cent', 'boolean_net'])
def test_invalid_backfill_never_changes_canonical_file(files, defect):
    bad = copy.deepcopy(submission())
    payload = bad['payload']
    audit = payload['record']['balance_backfill']
    if defect == 'mismatch':
        payload['balances']['2026-10-02'] += .01
    elif defect == 'missing_net':
        del audit['net_changes']['2026-10-02']
    elif defect == 'unconfirmed':
        audit['confirmed_complete'] = False
    elif defect == 'final_today':
        payload['balances']['2026-10-05'] = 100000
    elif defect == 'date_shift':
        payload['record']['planning_date'] = '2026-10-04'
    elif defect == 'bad_timestamp':
        audit['captured_at'] = '2026-10-05T00:00:00'
    elif defect == 'negative':
        audit['net_changes']['2026-10-03'] = 200000000
    elif defect == 'fractional_cent':
        audit['anchor_balance'] = payload['record']['current_balance'] = 100000.001
    elif defect == 'boolean_net':
        audit['net_changes']['2026-10-02'] = True
    before = dsb.RECORDS_FILE.read_bytes()
    with pytest.raises(ValueError):
        dsb.save(bad, files)
    assert dsb.RECORDS_FILE.read_bytes() == before


def test_historical_anchor_can_be_final_when_earlier_than_capture_day(files):
    value = submission()
    audit = value['payload']['record']['balance_backfill']
    audit.update(anchor_date='2026-10-04', anchor_balance=105000, provisional=False)
    del audit['net_changes']['2026-10-05']
    assert dsb.save(value, files)['committed']
