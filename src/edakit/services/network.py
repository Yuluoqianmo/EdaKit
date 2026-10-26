"""Best-effort retry budget. DNS, headers and trickle reads can overrun it."""
import json
import time
import requests
from ..errors import FetchError, UpstreamChangedError


class BudgetExpired(FetchError):
    pass


def request_json(session, method, url, *, budget, retries, mall=False, payload=None):
    start = time.monotonic()
    end = start + budget
    last = None
    forbidden = 0
    def check():
        if time.monotonic() >= end:
            raise BudgetExpired('商城响应超时（已等待约 %s 秒），请稍后重试' % round(time.monotonic()-start, 1))
    for attempt in range(max(1, retries)):
        check()
        remaining = end-time.monotonic()
        if remaining <= 0:
            raise BudgetExpired('商城响应超时（已等待约 %s 秒），请稍后重试' % round(time.monotonic()-start, 1))
        response = None
        try:
            options = dict(timeout=(min(3.05, remaining), 4), stream=True)
            if method == 'post': options['json'] = payload
            response = getattr(session, method)(url, **options)
            check()
            status = response.status_code
            if status == 403:
                forbidden += 1
                if forbidden > 1: raise UpstreamChangedError('HTTP 403: 商城拒绝访问，请稍后重试')
            if status not in (200, 403, 408, 429) and status < 500:
                raise UpstreamChangedError('HTTP %s: %s' % (status, url))
            if status != 200:
                last = FetchError('HTTP %s' % status)
            else:
                chunks, size = [], 0
                for chunk in response.iter_content(4096):
                    check()
                    size += len(chunk)
                    if size > 2_000_000: raise UpstreamChangedError('商城响应超过 2 MB 限制')
                    chunks.append(chunk)
                check()
                try: data = json.loads(b''.join(chunks))
                except ValueError as exc: raise UpstreamChangedError('商城返回非 JSON 数据') from exc
                if not isinstance(data, dict): raise UpstreamChangedError('商城响应不是对象')
                if not mall: return data
                code = data.get('code')
                if code == 200: return data.get('result') or {}
                if code not in (500, 502, 503): raise UpstreamChangedError('商城返回 code=%s' % code)
                last = FetchError('商城返回 code=%s' % code)
        except requests.RequestException as exc:
            last = exc
        finally:
            if response is not None: response.close()
        check()
        if attempt + 1 < max(1, retries):
            delay = min(.4 * 2**attempt, 2)
            if end-time.monotonic()-delay < 1:
                raise BudgetExpired('商城响应超时（已等待约 %s 秒），请稍后重试' % round(time.monotonic()-start, 1))
            time.sleep(delay)
    raise FetchError('商城请求失败：%s' % last)
