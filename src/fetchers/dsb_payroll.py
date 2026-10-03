"""Read published payroll terms. A changed/partial table must fail visibly."""
import hashlib
import json
import re
from datetime import datetime, date
from urllib.parse import urljoin, urlsplit

import fitz
from bs4 import BeautifulSoup
from src import http_client

PAGE_URL = 'https://www.dahsing.com/html/tc/deposit/payroll.html?intcmp=shortcut_dp_payroll'
VIP_URL = 'https://www.dahsing.com/pdf/wm/vip_promotion_tnc_tc_general.pdf'
CALENDAR_URL = 'https://www.1823.gov.hk/common/ical/tc.ics'


def _date(match):
    return date(*map(int, match)).isoformat()


def parse_terms(text, tables, source_url):
    compact = re.sub(r'\s+', '', text)
    dates = re.findall(r'(20\d{2})年(\d{1,2})月(\d{1,2})日', compact)
    registration = re.search(r'推廣期由(20\d{2})年(\d+)月(\d+)日至(20\d{2})年(\d+)月(\d+)日', compact)
    end = re.search(r'可享額外活期存款年利率優惠至(20\d{2})年(\d+)月(\d+)日', compact)
    cap = re.search(r'每個出糧戶口每月可獲之額外利息上限為([\d,]+)港元', compact)
    if not registration or not end or not cap or not dates:
        raise ValueError('Dah Sing: promotion dates or monthly cap missing')
    start, reg_end, reward_end = _date(registration.groups()[:3]), _date(registration.groups()[3:]), _date(end.groups())
    if not start <= reg_end <= reward_end:
        raise ValueError('Dah Sing: invalid promotion date order')
    if '365天（非閏年及閏年均適用）' not in compact or '上一個工作天出糧戶口內' not in compact:
        raise ValueError('Dah Sing: day basis or holiday convention changed')
    rows = [row for table in tables for row in table]
    base = [r for r in rows if len(r) == 2 and '%' in (r[1] or '')]
    if len(base) != 2:
        raise ValueError('Dah Sing: incomplete balance tiers')
    amounts = [[int(v.replace(',', '')) for v in re.findall(r'[\d,]+(?=\s*港元)', r[0])] for r in base]
    if len(amounts[0]) != 2 or amounts[1] != [amounts[0][1]]:
        raise ValueError('Dah Sing: balance tiers do not join')
    base_rates = [float(re.fullmatch(r'\s*([\d.]+)%\s*', r[1]).group(1)) for r in base]
    accounts = {key: {} for key in ('vip', 'you', 'standard')}
    task_thresholds = {}
    for letter, key, expected in [('A', 'debit', 3), ('B', 'credit', 1), ('C', 'fx', 1), ('D', 'stock', 2)]:
        found = [r for r in rows if r[0] and re.match(r'種類\s*'+letter+r'：', r[0])]
        if len(found) != 1 or len(found[0]) != 4:
            raise ValueError(f'Dah Sing: task {letter} table missing or ambiguous')
        row = found[0]
        description = re.sub(r'\s+', '', row[0])
        # Only the thresholds in the eligibility paragraph, before its notes.
        amounts = sorted({int(v.replace(',', '')) for v in re.findall(r'([\d,]+)港元', description.split('註：')[0])})
        if key == 'fx':
            if len(amounts) != 2 or '基金' not in description or '外幣兌換交易' not in description:
                raise ValueError('Dah Sing: currency/fund alternatives changed')
            task_thresholds['fund'] = amounts[1]
            amounts = amounts[:1]
        if len(amounts) != expected:
            raise ValueError(f'Dah Sing: task {letter} thresholds incomplete')
        task_thresholds[key] = amounts
        for index, account in enumerate(accounts, 1):
            cell = row[index] or ''
            rates = [float(v) for v in re.findall(r'([\d.]+)%', cell)]
            if cell.strip() == '不適用':
                rates = [0.0] * expected
            elif len(rates) != expected:
                raise ValueError(f'Dah Sing: task {letter} rates incomplete')
            accounts[account][key] = [{'min': amount, 'rate': rate} for amount, rate in zip(amounts, reversed(rates))]
    if any(not 0 <= tier['rate'] <= 20 for a in accounts.values() for tiers in a.values() for tier in tiers):
        raise ValueError('Dah Sing: invalid rate')
    maximum = base_rates[-1] + sum(t[-1]['rate'] for t in accounts['vip'].values())
    example = re.search(r'客戶可享之額外活期存款年利率為([\d.]+)%', compact)
    if not example or abs(maximum - float(example.group(1))) > 0.00001:
        raise ValueError('Dah Sing: task rates do not reconcile to bank example')
    rule = {'id': start[:7], 'reg_start': start, 'reg_end': reg_end, 'reward_start': start, 'reward_end': reward_end,
            'cap': int(cap.group(1).replace(',', '')), 'day_basis': 365, 'balance_basis': 'previous_workday',
            'minimum_balance': int(re.findall(r'[\d,]+(?=\s*港元)', base[0][0])[0].replace(',', '')),
            'base_tiers': [{'min': int(re.findall(r'[\d,]+(?=\s*港元)', r[0])[0].replace(',', '')), 'rate': rate} for r, rate in zip(base, base_rates)],
            'accounts': accounts, 'thresholds': task_thresholds, 'max_core_rate': round(maximum, 6),
            'source_url': source_url, 'source_kind': 'official', 'scope': 'new_customer',
            'scope_note': '公開文件適用於全新出糧客戶；重新登記須核對銀行給你的條款。',
            'terms_hash': hashlib.sha256(compact.encode()).hexdigest()}
    rule['revision'] = rule['id'] + '-' + rule['terms_hash'][:12]
    return rule


def parse_pdf(content, url):
    with fitz.open(stream=content, filetype='pdf') as doc:
        text = '\n'.join(page.get_text(sort=True) for page in doc)
        tables = [table.extract() for page in doc for table in page.find_tables().tables]
    return parse_terms(text, tables, url)


def parse_calendar(text):
    if 'BEGIN:VCALENDAR' not in text or 'END:VCALENDAR' not in text:
        raise ValueError('Hong Kong holiday calendar is incomplete')
    dates = sorted(set(_date((v[:4], v[4:6], v[6:])) for v in re.findall(r'DTSTART;VALUE=DATE:(\d{8})', text)))
    years = sorted({int(d[:4]) for d in dates})
    if not years or any(sum(d.startswith(str(y)) for d in dates) < 17 for y in years):
        raise ValueError('Hong Kong holiday calendar lacks a complete published year')
    names = {}
    for event in text.split('BEGIN:VEVENT')[1:]:
        day = re.search(r'DTSTART;VALUE=DATE:(\d{8})', event)
        name = re.search(r'SUMMARY:([^\r\n]+)', event)
        if day and name:
            value = day.group(1)
            names[_date((value[:4], value[4:6], value[6:]))] = name.group(1)
    return {'dates': dates, 'years': years, 'names': names, 'source_url': CALENDAR_URL}


def fetch_dsb_current():
    page = http_client.get(PAGE_URL)
    soup = BeautifulSoup(page.content, 'lxml')
    links = {urljoin(PAGE_URL, a['href']) for a in soup.find_all('a', href=True) if re.search(r'/payroll[^/]*tnc[^/]*tc\.pdf$', a['href'])}
    if len(links) != 1:
        raise ValueError('Dah Sing: current published terms link missing or ambiguous')
    url = links.pop()
    if urlsplit(url).scheme != 'https' or urlsplit(url).hostname != 'www.dahsing.com':
        raise ValueError('Dah Sing: terms must remain on the official HTTPS host')
    offer = parse_pdf(http_client.get(url).content, url)
    with fitz.open(stream=http_client.get(VIP_URL).content, filetype='pdf') as doc:
        vip = re.sub(r'\s+', '', ''.join(p.get_text() for p in doc))
    if vip.count('0.125%') < 2 or '0.25%' not in vip or '港元支票戶口' not in vip:
        raise ValueError('Dah Sing: VIP bonus rules changed; preserve previous calculation')
    offer['vip_component_rate'] = 0.125
    offer['vip_source_url'] = VIP_URL
    offer['vip_hash'] = hashlib.sha256(vip.encode()).hexdigest()
    # Monitor all terms, including restrictions that do not change the headline rate.
    offer['revision'] = offer['id'] + '-' + hashlib.sha256((offer['terms_hash'] + offer['vip_hash']).encode()).hexdigest()[:12]
    offer['checked_at'] = datetime.now().astimezone().isoformat()
    return offer


def fetch_dsb_calendar():
    result = parse_calendar(http_client.get(CALENDAR_URL).content.decode('utf-8-sig'))
    result['checked_at'] = datetime.now().astimezone().isoformat()
    return result
