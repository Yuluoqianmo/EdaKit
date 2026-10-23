"""Per-process capabilities for the loopback-only browser service."""
import hmac
import json
import re
from urllib.parse import parse_qs, urlsplit, urlunsplit

CALLBACK = re.compile(r'[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*\Z')


def authorize(handler):
    try:
        return _authorize(handler)
    except (ValueError, UnicodeError):
        return False


def _authorize(handler):
    server = handler.server
    authority = '127.0.0.1:' + str(server.server_address[1])
    origin = 'http://' + authority
    if handler.headers.get_all('Host', []) != [authority]:
        return False
    source = handler.headers.get('Origin')
    referer = handler.headers.get('Referer')
    if source is not None and source != origin:
        return False
    if referer:
        parsed = urlsplit(referer)
        if parsed.scheme + '://' + parsed.netloc != origin:
            return False
    if handler.headers.get('Sec-Fetch-Site') == 'cross-site':
        return False
    parsed = urlsplit(handler.path)
    path = parsed.path
    token = handler.headers.get('X-EdaKit-Token', '')
    prefix = '/auth/' + server.access_token
    if path.startswith(prefix + '/'):
        token = server.access_token
        path = path[len(prefix):]
        handler.path = urlunsplit(('', '', path, parsed.query, ''))
    if (path.startswith('/static/') and path.endswith(('.js', '.css', '.png', '.svg', '.ico'))) or path == '/api/health':
        return True
    candidates = parse_qs(parsed.query).get('token', [])
    if not token and len(candidates) == 1:
        token = candidates[0]
    return hmac.compare_digest(token.encode("utf-8"), server.access_token.encode("ascii"))


def bootstrap(token):
    # ES5 works in Capture's older CEF. Only same-origin XHR receives the
    # credential; JSONP and images explicitly include it in their URLs.
    return ('<script>window.__edakitToken=' + json.dumps(token) + ';'
        '(function(){if(!window.XMLHttpRequest||!XMLHttpRequest.prototype)return;var p=XMLHttpRequest.prototype,o=p.open,s=p.send;'
        'p.open=function(m,u){var a=document.createElement("a");a.href=u;'
        'this.__edakitLocal=a.protocol===location.protocol&&a.host===location.host;'
        'return o.apply(this,arguments);};'
        'p.send=function(){if(this.__edakitLocal)this.setRequestHeader("X-EdaKit-Token",window.__edakitToken);'
        'return s.apply(this,arguments);};})();</script>')
