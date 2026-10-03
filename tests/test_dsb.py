"""Public terms parsing and verified, idempotent private balance saves."""
import copy
import json
from pathlib import Path

import pytest

from src import dsb
from src.fetchers.dsb_payroll import parse_terms, parse_calendar
from src.state import write_json, read_json, RECOVERY_EVENTS, file_lock


def official_rule():
    fixture = json.loads((Path(__file__).parent / 'fixtures/dsb_terms.json').read_text(encoding='utf-8'))
    return parse_terms(fixture['text'], fixture['tables'], 'https://www.dahsing.com/pdf/deposit/payroll_tnc_tc.pdf')


def test_actual_bank_tables_reconcile_and_keep_account_differences():
    rule = official_rule()
    assert (rule['reg_start'], rule['reg_end'], rule['reward_end']) == ('2026-10-01', '2026-12-31', '2027-06-30')
    assert rule['cap'] == 6000 and rule['max_core_rate'] == 3.5
    assert rule['day_basis'] == 365 and rule['balance_basis'] == 'previous_workday'
    assert rule['base_tiers'] == [{'min': 10000, 'rate': .05}, {'min': 500000, 'rate': .1}]
    assert rule['accounts']['vip']['debit'] == [{'min': 2000, 'rate': .6}, {'min': 5000, 'rate': 1.0}, {'min': 10000, 'rate': 1.2}]
    assert all(t['rate'] == 0 for t in rule['accounts']['standard']['debit'])
    assert rule['scope'] == 'new_customer'  # never imply returning-customer verification


def test_partial_terms_fail_loud():
    fixture = json.loads((Path(__file__).parent / 'fixtures/dsb_terms.json').read_text(encoding='utf-8'))
    with pytest.raises(ValueError):
        parse_terms(fixture['text'], [], 'test')
    with pytest.raises(ValueError):
        parse_terms(fixture['text'].replace('365', '366'), fixture['tables'], 'test')


def test_calendar_rejects_partial_year():
    with pytest.raises(ValueError, match='complete published year'):
        parse_calendar('BEGIN:VCALENDAR\nBEGIN:VEVENT\nDTSTART;VALUE=DATE:20261001\nSUMMARY:國慶日\nEND:VEVENT\nEND:VCALENDAR')


def test_archived_rates_and_calendar_are_separate_from_current():
    from src.dsb_reference import archived_rules, calendar_2024
    april, july = archived_rules()
    assert (april['max_core_rate'], july['max_core_rate'], official_rule()['max_core_rate']) == (2.8, 3.0, 3.5)
    assert april['thresholds']['debit'] == [2000, 6000]
    assert july['reg_start'] == '2026-07-02' and july['requires_prior_expiry']
    assert 'vip_component_rate' not in july  # no retroactive use of current VIP terms
    assert len(calendar_2024()['dates']) == 17


@pytest.mark.parametrize('status', [401, 403, 429])
def test_dsb_refusal_stops_before_any_more_source_calls(monkeypatch, status):
    from src.fetchers import dsb_payroll
    from src.http_client import RefusalError
    calls = []
    def refuse(url):
        calls.append(url)
        raise RefusalError('simulated refusal '+str(status))
    monkeypatch.setattr(dsb_payroll.http_client, 'get', refuse)
    with pytest.raises(RefusalError):
        dsb_payroll.fetch_dsb_current()
    assert calls == [dsb_payroll.PAGE_URL]


def test_workbook_numeric_reader_never_executes_formulas():
    from scripts.import_dsb import numeric
    import openpyxl
    sheet = openpyxl.Workbook().active
    sheet['A1'] = 1000000
    sheet['A2'] = '=A1*3.5%/365'
    assert numeric(sheet, 'A2') == pytest.approx(1000000*.035/365)
    sheet['A3'] = '=__import__("os").system("echo bad")'
    with pytest.raises(ValueError, match='Unsupported'):
        numeric(sheet, 'A3')


def test_new_offer_notification_only_commits_after_confirmed_delivery(files):
    path = dsb.DATA_DIR / 'notifications.json'
    first = official_rule() | {'checked_at': '2026-10-03', 'revision': 'first'}
    dsb.store_offer(first)
    sent = []
    assert dsb.notify_changes(lambda msg: sent.append(msg) or True, path)
    assert not sent  # initial baseline
    dsb.store_offer(first | {'revision': 'changed', 'cap': 5000})
    assert not dsb.notify_changes(lambda msg: False, path)
    assert read_json(path)['seen'][first['id']] == 'first'
    assert dsb.notify_changes(lambda msg: sent.append(msg) or True, path)
    assert len(sent) == 1 and '#dsb' in sent[0] and '>🔗</a>' in sent[0]
    assert dsb.notify_changes(lambda msg: sent.append(msg) or True, path)
    assert len(sent) == 1


@pytest.fixture
def files(tmp_path, monkeypatch):
    RECOVERY_EVENTS.clear()
    monkeypatch.setattr(dsb, 'DATA_DIR', tmp_path)
    for name in ['CATALOG_FILE', 'RECORDS_FILE', 'CALENDAR_FILE']:
        monkeypatch.setattr(dsb, name, tmp_path / (name + '.json'))
    rule = official_rule()
    write_json(dsb.CATALOG_FILE, {'offers': [], 'rules': {rule['revision']: rule}})
    write_json(dsb.RECORDS_FILE, dsb.empty_records())
    return tmp_path / 'app'


def event(token='dsb-request-12345', version=0):
    rule = official_rule()
    tasks = {k: False if k in ('payroll', 'fund', 'vip1', 'vip2') else 0 for k in dsb.TASK_KEYS}
    record = {'rule_revision': rule['revision'], 'offer_id': rule['id'], 'account': 'vip',
              'basic_rate': None, 'actual': tasks.copy(), 'planned': tasks.copy(),
              'costs': dict.fromkeys(dsb.COST_KEYS), 'planning_date': '2026-10-03',
              'eligible_from': '2026-10-01', 'current_balance': None, 'registered': True,
              'registered_on': None, 'movements': []}
    return {'kind': 'dsb_month', 'utc': '2026-10-03T00:00:00Z',
            'payload': {'event_id': token, 'base_version': version, 'month': '2026-10',
                        'record': record, 'balances': {'2026-09-30': 1000000, '2026-10-02': 2000000}}}


def test_verified_save_independent_of_bank_lock_preserves_enrollment(files):
    with file_lock(dsb.DATA_DIR / 'monitor.lock'):
        result = dsb.save(event(), files)
    assert result['committed'] and result['dsb']['version'] == 1
    assert read_json(files / 'dsb-records.json') == result['dsb']
    assert 'save_receipts' not in result['dsb']
    assert result['dsb']['enrollments'][0]['registered'] is True
    assert result['dsb']['enrollments'][0]['reward_end'] == '2027-06-30'
    assert result['dsb']['months']['2026-10']['registered'] is True


def test_lost_reply_replay_and_stale_device_never_overwrite(files):
    dsb.save(event(), files)
    changed = event('dsb-request-later', 1)
    changed['payload']['balances']['2026-10-02'] = 1500000
    dsb.save(changed, files)
    retry = dsb.save(event(), files)
    assert retry['dsb']['version'] == 2
    assert retry['dsb']['balances']['2026-10-02'] == 1500000
    with pytest.raises(ValueError, match='另一裝置'):
        dsb.save(event('dsb-request-stale'), files)
    assert read_json(dsb.RECORDS_FILE)['version'] == 2


def test_duplicate_token_with_changed_payload_rejected(files):
    dsb.save(event(), files)
    changed = event()
    changed['payload']['balances']['2026-10-02'] = 12
    with pytest.raises(ValueError, match='識別碼'):
        dsb.save(changed, files)


def test_commit_then_view_failure_is_repaired_by_same_request(files, monkeypatch):
    original = dsb.write_json
    def fail(path, value):
        if path == files / 'dsb-records.json':
            raise OSError('simulated view write failure')
        original(path, value)
    monkeypatch.setattr(dsb, 'write_json', fail)
    with pytest.raises(OSError):
        dsb.save(event(), files)
    assert read_json(dsb.RECORDS_FILE)['version'] == 1
    monkeypatch.setattr(dsb, 'write_json', original)
    assert dsb.save(event(), files)['dsb']['version'] == 1


def test_corrupt_canonical_restores_verified_backup_visibly(files):
    write_json(dsb.RECORDS_FILE, dsb.empty_records())
    dsb.RECORDS_FILE.write_text('{"version":null}', encoding='utf-8')
    result = dsb.save(event(), files)
    assert result['committed'] and result['dsb']['sync_errors']
    assert list(dsb.DATA_DIR.glob('quarantine/*.broken'))


def test_missing_without_backup_never_creates_fake_empty_account(files):
    dsb.RECORDS_FILE.unlink()
    with pytest.raises(RuntimeError, match='遺失'):
        dsb.save(event(), files)
    assert not dsb.RECORDS_FILE.exists()


@pytest.mark.parametrize('path,value', [('registered_on', '2026-09-01'), ('registered_on', '2099-10-01'),
                                       ('basic_rate', -1), ('current_balance', -1), ('movements', [3])])
def test_invalid_inputs_leave_canonical_untouched(files, path, value):
    before = dsb.RECORDS_FILE.read_bytes()
    bad = event()
    bad['payload']['record'][path] = value
    with pytest.raises(ValueError):
        dsb.save(bad, files)
    assert dsb.RECORDS_FILE.read_bytes() == before


def test_new_terms_never_mutate_saved_revision_and_calendar_retains_old_years(files):
    rule = official_rule() | {'checked_at': '2026-10-03', 'revision': 'old'}
    dsb.store_offer(rule)
    changed = copy.deepcopy(rule) | {'revision': 'new', 'cap': 5000}
    dsb.store_offer(changed)
    catalog = read_json(dsb.CATALOG_FILE)
    assert catalog['rules']['old']['cap'] == 6000 and catalog['rules']['new']['cap'] == 5000
    dsb.store_calendar({'years': [2025, 2026], 'dates': ['2025-01-01', '2026-01-01'], 'names': {'2025-01-01': '元旦'}, 'source_url': 'old'})
    dsb.store_calendar({'years': [2026, 2027], 'dates': ['2026-10-01', '2027-01-01'], 'names': {'2026-10-01': '國慶日'}, 'source_url': 'new'})
    calendar = read_json(dsb.CALENDAR_FILE)
    assert calendar['years'] == [2025, 2026, 2027]
    assert calendar['dates'] == ['2025-01-01', '2026-10-01', '2027-01-01']
