"""One guarded send function for every fetcher and Telegram call.

Refusals stop all calls to the same account, persist across processes, and
lengthen the cooldown on repeats. Only GET network/5xx faults get one retry.
"""
import hashlib
import logging
import math
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

import requests as transport

from src.config import DATA_DIR, REQUEST_TIMEOUT
from src.state import file_lock, read_json, write_json

logger = logging.getLogger(__name__)
STATE_FILE = DATA_DIR / "http_guard.json"
LOCK_FILE = DATA_DIR / "http_guard.lock"
PER_RUN_CAP = 32
PER_DAY_CAP = 64  # Local safety budget, NOT a claimed provider limit.
MIN_INTERVAL = 1.0
_run_calls = 0


class GuardError(RuntimeError):
    pass


class RefusalError(GuardError):
    pass


def _account(url, kwargs):
    host = urlsplit(url).hostname or "unknown"
    host = "hsbc.com.hk" if host.endswith(".hsbc.com.hk") else host.removeprefix("www.")
    secret = str((kwargs.get("params") or {}).get("api_key", ""))
    if host == "api.telegram.org":
        secret = urlsplit(url).path.split("/")[1]
    suffix = ":" + hashlib.sha256(secret.encode()).hexdigest()[:16] if secret else ""
    return host + suffix


def _retry_after(resp, now):
    seconds = 0.0
    raw = resp.headers.get("Retry-After", "")
    if raw:
        try:
            seconds = float(raw)
        except ValueError:
            try:
                seconds = parsedate_to_datetime(raw).timestamp() - now
            except (ValueError, TypeError, OverflowError):
                logger.warning("Unrecognised Retry-After header; conservative refusal cooldown applies")
    reset = resp.headers.get("X-RateLimit-Reset", "")
    if reset:
        try:
            seconds = max(seconds, float(reset) - now)
        except ValueError:
            logger.warning("Unrecognised rate-limit reset header")
    if "application/json" in resp.headers.get("Content-Type", ""):
        try:
            seconds = max(seconds, float(resp.json().get("parameters", {}).get("retry_after", 0)))
        except (ValueError, TypeError, AttributeError):
            logger.warning("Unrecognised JSON retry-after value; conservative refusal cooldown applies")
    return max(0, seconds) if math.isfinite(seconds) else 0


def _refusal_body(body):
    """Recognise account refusals and verification interstitials, not article quotes."""
    if re.search(r"too many requests|account.{0,25}(?:suspended|banned)|cf-chl-|cf-challenge|verify you are human", body):
        return True
    # The observed public mirror response used HTTP 200 and an obfuscated
    # challenge, with neither Cloudflare markers nor the word captcha.
    title = re.search(r"<title\b[^>]*>\s*one moment,\s*please\.{0,3}\s*</title>", body)
    return bool(title and re.search(r"please wait while your request is being verified", body))


def request(method, url, *, retry_network=True, **kwargs):
    global _run_calls
    account = _account(url, kwargs)
    kwargs.setdefault("timeout", REQUEST_TIMEOUT)
    # No implicit requests redirects: each redirect also needs the guard.
    kwargs["allow_redirects"] = False
    attempts = 2 if method.upper() == "GET" and retry_network else 1
    for attempt in range(attempts):
        with file_lock(LOCK_FILE):
            state = read_json(STATE_FILE)
            info = state.setdefault(account, {})
            now = time.time()
            if info.get("blocked_until", 0) > now:
                until = datetime.fromtimestamp(info["blocked_until"], timezone.utc).isoformat()
                raise RefusalError(f"{account}: refusal cooldown until {until}; no request sent")
            verification = info.get("blocked_until", 0) > info.get("verified_after_refusal", 0)
            day = datetime.now(timezone.utc).date().isoformat()
            if info.get("day") != day:
                info.update(day=day, calls=0)
            if info.get("calls", 0) >= PER_DAY_CAP or _run_calls >= PER_RUN_CAP:
                raise GuardError(f"{account}: safety call budget reached; no request sent")
            pause = max(0, MIN_INTERVAL - (now - info.get("last_call", 0)))
            if pause:
                time.sleep(pause)
            info["last_call"] = time.time()
            info["calls"] = info.get("calls", 0) + 1
            _run_calls += 1
            write_json(STATE_FILE, state)
            try:
                resp = transport.request(method, url, **kwargs)
            except transport.RequestException as exc:
                # Never expose credential-bearing URLs from requests exceptions.
                if attempt + 1 < attempts and not verification:
                    logger.warning("%s network failure; repair: one bounded retry", account)
                    time.sleep(2 ** (attempt + 1) + __import__("random").uniform(0, 0.5))
                    continue
                raise GuardError(f"{account}: {type(exc).__name__}; bounded network repair failed") from None
            body = resp.text[:30000].lower() if "text" in resp.headers.get("Content-Type", "") or "json" in resp.headers.get("Content-Type", "") else ""
            refusal_body = _refusal_body(body)
            telegram_failure = False
            if account.startswith("api.telegram.org") and resp.status_code == 200:
                telegram_failure = resp.json().get("ok") is False
            refused = (400 <= resp.status_code < 500 and resp.status_code not in (400, 404, 422)) or refusal_body or telegram_failure
            if refused:
                strikes = info.get("refusals", 0) + 1
                cooldown=max(86400*2**min(strikes-1,5),info.get("cooldown_seconds",0)*2,_retry_after(resp,time.time())+60)
                info.update(refusals=strikes,blocked_until=time.time()+cooldown,cooldown_seconds=cooldown,last_status=resp.status_code)
                write_json(STATE_FILE, state)
                raise RefusalError(f"{account}: HTTP {resp.status_code} refusal; stopped account calls, cooldown extended (event {strikes})")
            if 500 <= resp.status_code:
                if attempt + 1 < attempts and not verification:
                    logger.warning("%s HTTP %s; repair: one bounded retry", account, resp.status_code)
                    time.sleep(2 ** (attempt + 1) + __import__("random").uniform(0, 0.5))
                    continue
                raise GuardError(f"{account}: HTTP {resp.status_code}; bounded server repair failed")
            if resp.status_code in (400, 404, 422):
                detail=""
                if "json" in resp.headers.get("Content-Type", ""):
                    try:
                        description=str(resp.json().get("description", ""))[:200]
                        description=re.sub(r"https?://\S+", "[URL removed]",description)
                        for secret in [urlsplit(url).path.split('/')[1] if account.startswith('api.telegram.org') else '',str((kwargs.get('params') or {}).get('api_key',''))]:
                            if secret: description=description.replace(secret,"[credential removed]")
                        detail="; "+description if description else ""
                    except (ValueError,AttributeError):
                        logger.warning("Bad request body could not be decoded; original status retained")
                raise GuardError(f"{account}: HTTP {resp.status_code} bad request{detail}; same request will not be retried")
            if resp.status_code == 304 and method.upper() == 'GET' and any(
                    key.lower() in ('if-none-match', 'if-modified-since') for key in kwargs.get('headers', {})):
                if verification:
                    info["verified_after_refusal"] = info["blocked_until"]
                    write_json(STATE_FILE, state)
                return resp  # A conditional GET verified the caller's local cache.
            if 300 <= resp.status_code < 400:
                raise GuardError(f"{account}: HTTP {resp.status_code} redirect; update the source URL before another call")
            if verification:
                info["verified_after_refusal"] = info["blocked_until"]
                write_json(STATE_FILE, state)
            return resp
    raise GuardError(f"{account}: retry budget exhausted")


def get(url, **kwargs):
    return request("GET", url, **kwargs)


def post(url, **kwargs):
    return request("POST", url, **kwargs)
