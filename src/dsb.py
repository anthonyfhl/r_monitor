"""Versioned public terms and private daily balances for the authenticated hub."""
from contextlib import contextmanager
from datetime import date, datetime
import hashlib
import html
import json
import math
import re
import time

from src.config import DATA_DIR, REPORTS_DIR
from src.esaver import InvalidRegistration
from src.loans import APP_URL
from src.state import read_json, write_json, file_lock, LockBusyError, recover_backup, RECOVERY_EVENTS

CATALOG_FILE = DATA_DIR / 'dsb_promotions.json'
RECORDS_FILE = DATA_DIR / 'dsb_records.json'
CALENDAR_FILE = DATA_DIR / 'dsb_holidays.json'
NOTIFY_FILE = DATA_DIR / 'dsb_notifications.json'
TASK_KEYS = {'payroll', 'debit', 'credit', 'fx', 'fund', 'stock', 'vip1', 'vip2'}
COST_KEYS = {'debit', 'credit', 'fx', 'stock', 'other'}


@contextmanager
def record_lock():
    deadline = time.monotonic() + 3
    while True:
        lock = file_lock(DATA_DIR / 'dsb_records.lock')
        try:
            lock.__enter__()
            break
        except LockBusyError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(.05)
    try:
        yield
    finally:
        lock.__exit__(None, None, None)


def empty_records():
    return {'version': 0, 'months': {}, 'balances': {}, 'enrollments': [], 'save_receipts': {}, 'sync_errors': []}


def read_records():
    def validate(path):
        item = read_json(path)
        if not isinstance(item, dict) or type(item.get('version')) is not int or any(not isinstance(item.get(k), dict) for k in ['months', 'balances', 'save_receipts']) or not isinstance(item.get('enrollments'), list):
            raise ValueError('大新正式紀錄結構損壞')
        if any(not re.fullmatch(r'\d{4}-\d{2}-\d{2}', d) or type(v) not in (int, float) or not math.isfinite(v) or v < 0 for d, v in item['balances'].items()):
            raise ValueError('大新每日結餘損壞')
        return item
    if not RECORDS_FILE.exists():
        backup = RECORDS_FILE.with_name(RECORDS_FILE.name + '.bak')
        if not backup.exists():
            raise RuntimeError('大新紀錄檔遺失；已檢查備份但未能復原，停止寫入')
        result = validate(backup)
        write_json(RECORDS_FILE, result)
        RECOVERY_EVENTS.append('大新紀錄檔遺失；已從驗證過嘅備份復原。')
        return result
    try:
        return validate(RECORDS_FILE)
    except ValueError:
        return recover_backup(RECORDS_FILE, validate)


def store_offer(offer):
    catalog = read_json(CATALOG_FILE, {'offers': [], 'rules': {}})
    if not isinstance(catalog.get('offers'), list) or not isinstance(catalog.get('rules'), dict):
        raise ValueError('Dah Sing promotion archive has an invalid schema')
    # A new revision never mutates the rule bound to a saved personal month.
    catalog['rules'].setdefault(offer['revision'], offer)
    existing = next((o for o in catalog['offers'] if o['id'] == offer['id']), None)
    summary = {k: offer[k] for k in ['id', 'reg_start', 'reg_end', 'reward_start', 'reward_end', 'revision', 'checked_at', 'max_core_rate', 'source_url']}
    if existing:
        existing.update(summary)
    else:
        catalog['offers'].append(summary)
    catalog['checked_at'] = offer['checked_at']
    write_json(CATALOG_FILE, catalog)


def store_calendar(calendar):
    """Replace published years, retaining older verified years for saved history."""
    old = read_json(CALENDAR_FILE, {})
    replaced = set(calendar['years'])
    retained = [d for d in old.get('dates', []) if int(d[:4]) not in replaced]
    merged = dict(calendar)
    merged['dates'] = sorted(set(retained + calendar['dates']))
    merged['years'] = sorted(set(old.get('years', [])) | replaced)
    merged['names'] = {d: old.get('names', {}).get(d, '') for d in retained} | calendar['names']
    sources = old.get('sources_by_year', {str(y): old.get('source_url') for y in old.get('years', [])})
    merged['sources_by_year'] = sources | {str(y): calendar['source_url'] for y in calendar['years']}
    write_json(CALENDAR_FILE, merged)


def _visible(records):
    return {k: v for k, v in records.items() if k != 'save_receipts'} | {'sync_errors': list(dict.fromkeys(records.get('sync_errors', []) + RECOVERY_EVENTS))}


def _publish(records, app_dir=None):
    visible = _visible(records)
    path = (app_dir or REPORTS_DIR / 'app') / 'dsb-records.json'
    try:
        write_json(path, visible)
    except OSError:
        RECOVERY_EVENTS.append('大新展示檔寫入失敗；已從正式紀錄即時重建。')
        visible = _visible(records)
        write_json(path, visible)
    if read_json(path) != visible:
        raise RuntimeError('大新展示紀錄未能通過寫入核對')
    return visible


def publish(app_dir=None):
    target = app_dir or REPORTS_DIR / 'app'
    write_json(target / 'dsb-public.json', {'catalog': read_json(CATALOG_FILE, {'offers': [], 'rules': {}}), 'calendar': read_json(CALENDAR_FILE)})
    if not RECORDS_FILE.exists() and not RECORDS_FILE.with_name(RECORDS_FILE.name + '.bak').exists():
        # Explicit uninitialised state, never present missing history as an empty healthy account.
        write_json(target / 'dsb-records.json', {'available': False, 'error': '大新個人紀錄尚未初始化。'})
        return
    with record_lock():
        _publish(read_records(), target)


def _number(value, label, nullable=False, signed=False):
    if value is None and nullable:
        return None
    if type(value) not in (int, float) or not math.isfinite(value) or abs(value) > 1e11 or (not signed and value < 0):
        raise InvalidRegistration(label + ' 必須為有效金額')
    return value


def _date(value):
    try:
        if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
            raise ValueError()
    except ValueError:
        raise InvalidRegistration('日期格式無效') from None
    return value


def validate_month(month, item, catalog):
    if not isinstance(month, str) or not re.fullmatch(r'\d{4}-\d{2}', month):
        raise InvalidRegistration('月份格式無效')
    first = _date(month + '-01')
    if not isinstance(item, dict):
        raise InvalidRegistration('月份紀錄格式無效')
    rule = catalog['rules'].get(item.get('rule_revision'))
    if not rule or rule['id'] != item.get('offer_id'):
        raise InvalidRegistration('所選期別未有完整計息條款')
    if rule['reward_start'][:7] > month or rule['reward_end'][:7] < month:
        raise InvalidRegistration('所選推廣不涵蓋本月')
    if item.get('account') not in ('vip', 'you', 'standard'):
        raise InvalidRegistration('戶口類別無效')
    selected = {k: item[k] for k in ['rule_revision', 'offer_id', 'account']}
    selected['basic_rate'] = _number(item.get('basic_rate'), '基本年利率', nullable=True)
    if selected['basic_rate'] is not None and selected['basic_rate'] > 20:
        raise InvalidRegistration('基本年利率超出範圍')
    for key in ['actual', 'planned']:
        tasks = item.get(key)
        if not isinstance(tasks, dict) or set(tasks) != TASK_KEYS:
            raise InvalidRegistration('每月任務資料未齊')
        selected[key] = {}
        for task, value in tasks.items():
            if task in ('payroll', 'fund', 'vip1', 'vip2'):
                if type(value) is not bool:
                    raise InvalidRegistration('任務狀態格式無效')
                selected[key][task] = value
            else:
                selected[key][task] = _number(value, '合資格交易金額')
    costs = item.get('costs')
    if not isinstance(costs, dict) or set(costs) != COST_KEYS:
        raise InvalidRegistration('成本資料格式無效')
    selected['costs'] = {k: _number(v, '成本', nullable=True) for k, v in costs.items()}
    selected['receipts'] = {k: _number((item.get('receipts') or {}).get(k), '實收利息', nullable=True) for k in ['core', 'vip', 'basic']}
    selected['planning_date'] = _date(item.get('planning_date'))
    next_month = date(int(month[:4]) + (month[5:] == '12'), int(month[5:]) % 12 + 1, 1).isoformat()
    if not first <= selected['planning_date'] <= next_month:
        raise InvalidRegistration('調整日期須在本月或下月首日')
    selected['current_balance'] = _number(item.get('current_balance'), '調整前結餘', nullable=True)
    selected['eligible_from'] = _date(item.get('eligible_from', first))
    if not first <= selected['eligible_from'] < next_month:
        raise InvalidRegistration('優惠開始計息日期須在所選月份')
    selected['terms_confirmed'] = item.get('terms_confirmed') is True
    selected['registered'] = item.get('registered') is True
    registered_on = item.get('registered_on')
    selected['registered_on'] = _date(registered_on) if registered_on else None
    if registered_on and (registered_on > date.today().isoformat() or
                          not rule.get('reg_start', rule['reward_start']) <= registered_on <= rule.get('reg_end', rule['reward_end'])):
        raise InvalidRegistration('登記日須在該期登記期間內，且不可為未來日期')
    movements = item.get('movements', [])
    if not isinstance(movements, list) or len(movements) > 62:
        raise InvalidRegistration('預計變動最多 62 筆')
    selected['movements'] = []
    for move in movements:
        if not isinstance(move, dict):
            raise InvalidRegistration('預計變動格式無效')
        d = _date(move.get('date'))
        if not selected['planning_date'] <= d < next_month:
            raise InvalidRegistration('預計變動日期須在調整日起至月底')
        selected['movements'].append({'date': d, 'amount': _number(move.get('amount'), '變動金額', signed=True)})
    return selected


def save(event, app_dir=None):
    payload = event.get('payload')
    if event.get('kind') != 'dsb_month' or not isinstance(payload, dict):
        raise InvalidRegistration('大新保存內容無效')
    token = payload.get('event_id')
    if not isinstance(token, str) or not 8 <= len(token) <= 80:
        raise InvalidRegistration('提交識別碼無效')
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, allow_nan=False).encode()).hexdigest()
    with record_lock():
        records = read_records()
        previous = records['save_receipts'].get(token)
        if previous:
            if previous != fingerprint:
                raise InvalidRegistration('同一提交識別碼不可用於不同內容')
            return {'ok': True, 'committed': True, 'event_id': token, 'dsb': _publish(records, app_dir)}
        if type(payload.get('base_version')) is not int or payload['base_version'] != records['version']:
            raise InvalidRegistration('另一裝置已更新紀錄；你的草稿已保留。請重新讀取最新紀錄後核對再保存。')
        catalog = read_json(CATALOG_FILE)
        month = payload.get('month')
        item = validate_month(month, payload.get('record'), catalog)
        balances = payload.get('balances')
        if not isinstance(balances, dict) or len(balances) > 45:
            raise InvalidRegistration('每日結餘格式無效')
        first = date.fromisoformat(month + '-01')
        for d, value in balances.items():
            actual = date.fromisoformat(_date(d))
            if d[:7] != month and not 0 < (first - actual).days <= 14:
                raise InvalidRegistration('只能保存所選月及月初所需上月結餘')
            _number(value, d + ' 結餘', nullable=True)
            if value is not None and actual > date.today():
                raise InvalidRegistration('未來結餘請記入預計資金變動，不可標為實際紀錄')
        for d, value in balances.items():
            if value is None:
                records['balances'].pop(d, None)
            else:
                records['balances'][d] = value
        records['months'][month] = item
        if rule := catalog['rules'].get(item['rule_revision']):
            if rule.get('source_kind') != 'excel':
                enrollment = next((e for e in records['enrollments'] if e['offer_id'] == rule['id']), None)
                details = {'offer_id': rule['id'], 'registered': item['registered'],
                           'registered_on': item['registered_on'], 'reward_end': rule['reward_end'],
                           'effective_month': (item['registered_on'] or rule['reward_start'])[:7],
                           'terms_confirmed': item['terms_confirmed'], 'source': 'owner saved'}
                if enrollment:
                    enrollment.update(details)
                else:
                    records['enrollments'].append(details)
        records['version'] += 1
        records['synced_at'] = event['utc']
        records['save_receipts'][token] = fingerprint
        try:
            write_json(RECORDS_FILE, records)
        except OSError:
            RECORDS_FILE.parent.mkdir(parents=True, exist_ok=True)
            write_json(RECORDS_FILE, records)
            RECOVERY_EVENTS.append('大新紀錄首次寫入失敗；已修復路徑並重新寫入及核對。')
        if read_json(RECORDS_FILE) != records:
            raise RuntimeError('大新正式紀錄未能通過寫入核對')
        return {'ok': True, 'committed': True, 'event_id': token, 'dsb': _publish(records, app_dir)}


def notify_changes(sender, state_path=None):
    path = state_path or NOTIFY_FILE
    catalog = read_json(CATALOG_FILE, {'offers': [], 'rules': {}})
    current = {o['id']: o.get('revision') for o in catalog['offers'] if o.get('revision')}
    state = read_json(path)
    if 'seen' not in state:
        write_json(path, {'seen': current})
        return True
    for key, revision in current.items():
        if state['seen'].get(key) == revision:
            continue
        rule = catalog['rules'][revision]
        title = '新一期' if key not in state['seen'] else '條款／利率更新'
        message = '\n'.join([f'🔔 <b>大新易出糧 {key} {title}</b>',
            f'💰 公開優惠最高 {rule["max_core_rate"]:.3f}%｜每月上限 ${rule["cap"]:,.0f}',
            f'📅 加息期 {rule["reward_start"]} 至 {rule["reward_end"]}',
            '📌 現有月份仍用已保存期別；新條款可在計算器選擇',
            f'<a href="{APP_URL}#dsb">🔗</a>'])
        if not sender(message):
            return False
        state['seen'][key] = revision
        write_json(path, state)
    return True
