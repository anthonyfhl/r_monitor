"""Manually verified historical public facts, never applied to the current period.

Bank scans linked by the operator's article were read page by page on 2026-10-03.
Pages 1-2: enrollment eligibility; 3: cap, balance convention and balance tiers;
4-5: all three account classes and task tiers; 6: 365-day basis.
"""
import hashlib
import json

JULY_URL = 'https://yolkinsight.hk/wp-content/uploads/2026/07/2026-07-07-%E5%A4%A7%E6%96%B0360%C2%B0%E3%80%8C%E6%98%93%E5%87%BA%E7%B3%A7%E3%80%8D%E6%9C%8D%E5%8B%99%E9%87%8D%E6%96%B0%E7%99%BB%E8%A8%98%E6%A2%9D%E6%AC%BE%E5%8F%8A%E7%B4%B0%E5%89%87-7-9%E6%9C%88%E4%BB%BD.pdf'
APRIL_URL = 'https://yolkinsight.hk/wp-content/uploads/2026/04/%E9%87%8D%E6%96%B0%E7%99%BB%E8%A8%98360%E6%98%93%E5%87%BA%E7%B3%A7%E6%9C%8D%E5%8B%99%E6%A2%9D%E6%AC%BE%E5%8F%8A%E7%B4%B0%E5%89%87-2026%E5%B9%B44%E6%9C%88.pdf'


def archived_rules():
    result = []
    for month, reg_day, reg_end, end, debit, rates, url, digest in [
        ('2026-04', '01', '2026-06-30', '2026-09-30', [2000, 6000], [.5, .9], APRIL_URL,
         '619700e0ac5e5883d5a55219ab345683dfadac69316a6c82d047c38edffd85e6'),
        ('2026-07', '02', '2026-09-30', '2026-12-31', [2000, 5000, 10000], [.5, .9, 1.1], JULY_URL,
         '43e5a426f04d9a01556e163587c3183524b70fb26c7f9301f8883dca82321e72'),
    ]:
        accounts = {}
        for account in ['vip', 'you', 'standard']:
            accounts[account] = {
                'debit': [{'min': amount, 'rate': rate if account != 'standard' else 0} for amount, rate in zip(debit, rates)],
                'credit': [{'min': 3000, 'rate': .3}],
                'fx': [{'min': 10000, 'rate': .6 if account == 'vip' else .5}],
                'stock': [{'min': 30000, 'rate': .9 if account == 'vip' else .8}]}
        rule = {'id': month, 'reg_start': month+'-'+reg_day, 'reg_end': reg_end,
                'reward_start': month+'-01', 'reward_end': end, 'cap': 6000, 'day_basis': 365,
                'balance_basis': 'previous_workday', 'minimum_balance': 10000,
                'base_tiers': [{'min': 10000, 'rate': .05}, {'min': 500000, 'rate': .1}],
                'thresholds': {'debit': debit, 'credit': [3000], 'fx': [10000], 'fund': 100000, 'stock': [30000]},
                'accounts': accounts, 'max_core_rate': round(.1+rates[-1]+.3+.6+.9, 6),
                'source_kind': 'bank_scan_mirror', 'scope': 'returning_customer', 'source_url': url,
                'terms_hash': digest, 'requires_prior_expiry': True,
                'scope_note': '已核對銀行重新登記文件副本；原優惠須先完結，並在重新登記後有合資格出糧。歷史 VIP 額外利息條款未另行核對。',
                'checked_at': '2026-10-03T13:00:00+08:00'}
        rule['revision'] = month+'-'+hashlib.sha256(json.dumps(rule, sort_keys=True).encode()).hexdigest()[:12]
        result.append(rule)
    return result


def calendar_2024():
    names = {'2024-01-01': '一月一日', '2024-02-10': '農曆年初一', '2024-02-12': '農曆年初三',
             '2024-02-13': '農曆年初四', '2024-03-29': '耶穌受難節', '2024-03-30': '耶穌受難節翌日',
             '2024-04-01': '復活節星期一', '2024-04-04': '清明節', '2024-05-01': '勞動節',
             '2024-05-15': '佛誕', '2024-06-10': '端午節', '2024-07-01': '香港特別行政區成立紀念日',
             '2024-09-18': '中秋節翌日', '2024-10-01': '國慶日', '2024-10-11': '重陽節',
             '2024-12-25': '聖誕節', '2024-12-26': '聖誕節後第一個周日'}
    return {'years': [2024], 'dates': sorted(names), 'names': names,
            'source_url': 'https://www.info.gov.hk/gia/general/202305/25/P2023052500209.htm',
            'checked_at': '2026-10-03T13:00:00+08:00'}
