"""Regression tests for local-service boundaries, safe Tcl and downloads."""
import json
from pathlib import Path
import shutil
import subprocess
import urllib.error
import urllib.request
import pytest
from test_server import _isolate, _get, _post


def call(base, path, headers=None, body=None):
    req = urllib.request.Request(base + path, data=body, headers=headers or {})
    try:
        with urllib.request.urlopen(req) as response:
            return response.status, response.read(), response.headers
    except urllib.error.HTTPError as response:
        return response.code, response.read(), response.headers


@pytest.mark.parametrize('path', ['/api/config', '/api/bom/settings', '/api/properties/layout', '/api/es/status', '/workbench', '/static/embed.html'])
def test_unauthenticated_access_denied(_isolate, path):
    raw = _isolate.split('/auth/')[0]
    assert call(raw, path)[0] == 403


@pytest.mark.parametrize('headers', [{'Host': 'evil.example'}, {'Origin': 'http://evil.example'}, {'Origin': 'null'}, {'Referer': 'http://evil.example/'}, {'Sec-Fetch-Site': 'cross-site'}, {'Referer': 'http://['}])
def test_host_and_browser_source_checked_even_with_token(_isolate, headers):
    assert call(_isolate, '/api/config', headers)[0] == 403


def test_plain_post_and_get_placement_rejected(_isolate):
    assert call(_isolate, '/api/config', {'Content-Type':'text/plain'}, b'{}')[0] == 415
    assert call(_isolate, '/api/es/place?cid=C2040')[0] == 405


def test_jsonp_callback_and_non_ascii_credential_rejected(_isolate):
    from urllib.parse import quote
    code, body, headers = call(_isolate, '/api/es/status?cb='+quote('alert(document.domain)//'))
    assert code == 400 and b'alert(' not in body
    assert headers['X-Content-Type-Options'] == 'nosniff'
    assert call(_isolate.split('/auth/')[0], '/api/config?token='+quote('错误'))[0] == 403


def test_bootstrap_only_reveals_token_to_authorized_page(_isolate):
    code, body, headers = call(_isolate, '/workbench')
    assert code == 200 and _isolate.rsplit('/',1)[1].encode() in body
    assert headers['Referrer-Policy'] == 'no-referrer'
    assert call(_isolate.split('/auth/')[0], '/static/workbench.html')[0] == 403


def test_tcl_roundtrip_never_executes_data(tmp_path):
    from edakit.symbol.tcl import generate_place_tcl
    tcl = shutil.which('tclsh') or shutil.which('tclsh8.6')
    if not tcl: pytest.skip('tclsh not installed')
    values = ['X}}; exec AUDIT; set z {{', 'cost $5 [x]', 'line1\nline2', 'a\\b"c{d}']
    script = 'proc DboState {} {return state}\nproc PlacePart args {}\nproc exec args {error INJECTION}\n'
    for value in values:
        script += generate_place_tcl('test.olb', value, props={'Description':value})
        script += 'puts [binary encode hex [encoding convertto utf-8 [lindex $lProps 1]]]\n'
    path = tmp_path/'probe.tcl';path.write_text(script,encoding='utf-8')
    result = subprocess.run([tcl,str(path)],capture_output=True,text=True)
    assert result.returncode == 0, result.stderr
    for value in values: assert value.encode().hex() in result.stdout
    assert 'INJECTION' not in result.stderr


def test_fetch_no_retry_for_404_and_backoff_for_503(monkeypatch):
    from types import SimpleNamespace
    from edakit.fetch import Fetcher
    from edakit.errors import FetchError
    import edakit.fetch as module
    sleeps=[];monkeypatch.setattr(module.time,'sleep',sleeps.append)
    f=Fetcher();calls=[]
    def missing(*a,**kw): calls.append(1);return SimpleNamespace(status_code=404)
    monkeypatch.setattr(f.session,'get',missing)
    with pytest.raises(FetchError): f._get_json('https://example.test')
    assert len(calls)==1 and not sleeps
    responses=iter([SimpleNamespace(status_code=503),SimpleNamespace(status_code=200,json=lambda:{'ok':True})])
    monkeypatch.setattr(f.session,'get',lambda *a,**kw:next(responses))
    assert f._get_json('https://example.test')=={'ok':True} and sleeps==[.2]


def test_step_rejects_error_page_and_preserves_existing_file(tmp_path,monkeypatch):
    from edakit.threed.step import StepFetcher
    from edakit.errors import FetchError
    fetcher=StepFetcher();target=tmp_path/'part.step';target.write_bytes(b'old-good-model')
    monkeypatch.setattr(fetcher,'_get',lambda url:b'<html>upstream error</html>')
    with pytest.raises(FetchError):fetcher.download_step('valid-id',target)
    assert target.read_bytes()==b'old-good-model'
    raw=b'ISO-10303-21;\nHEADER;ENDSEC;DATA;ENDSEC;END-ISO-10303-21;'
    monkeypatch.setattr(fetcher,'_get',lambda url:raw)
    fetcher.download_step('valid-id',target)
    assert target.read_bytes()==raw and not list(tmp_path.glob('*.tmp'))
    with pytest.raises(ValueError):fetcher.download_obj_bytes('../escape?x=1')

def test_schema_profile_not_changeable_over_http(_isolate):
    code, _, _ = call(_isolate, '/api/config', {'Content-Type':'application/json'}, b'{"schema_profile":"C:/sensitive.txt"}')
    assert code == 400


def test_old_auto_receipts_expire_without_allowing_replay(tmp_path, monkeypatch):
    import time
    from edakit.bridge import queue
    monkeypatch.setenv('LOCALAPPDATA',str(tmp_path))
    seq=time.strftime('%Y%m%d%H%M%S',time.localtime(time.time()-40*86400))+'-abcdef'
    directory=queue.queue_dir()
    receipt=directory/('req_'+seq+'.submitted');receipt.write_text('digest')
    response=directory/('resp_'+seq+'.resp');response.write_text('ok=1')
    custom=directory/'req_manual.submitted';custom.write_text('digest')
    assert queue.compact_receipts(force=True)==1
    assert not receipt.exists() and not response.exists() and custom.exists()
    with pytest.raises(ValueError,match='replay protection'):
        queue.PlaceRequest(cid='C2040',seq=seq).submit()


def test_component_identifier_blocks_path_segments():
    from edakit.fetch import Fetcher
    with pytest.raises(ValueError):Fetcher().get_component('C2040/../../secret')


def test_missing_windows_api_is_a_controlled_error(monkeypatch):
    import edakit.server.lifecycle as lifecycle
    monkeypatch.setattr(lifecycle.os,'name','posix')
    with pytest.raises(OSError,match='requires Windows'):
        lifecycle.WindowsProcess(1)


def test_config_cache_does_not_return_mutable_or_stale_values(tmp_path, monkeypatch):
    from edakit.config import Config
    monkeypatch.setenv('LOCALAPPDATA',str(tmp_path))
    original=Config(footprint_lib=str(tmp_path/'first'));original.save()
    loaded=Config.load();loaded.footprint_lib='not-saved'
    assert Config.load().footprint_lib==original.footprint_lib
    original.footprint_lib=str(tmp_path/'second');original.save()
    assert Config.load().footprint_lib==original.footprint_lib


def test_capture_port_parser_accepts_capability_url():
    tcl=shutil.which('tclsh') or shutil.which('tclsh8.6')
    if not tcl:pytest.skip('tclsh not installed')
    source=Path('src/edakit/install/templates/edakit.tcl').read_text(encoding='ascii')
    start=source.index('    proc portOf ')
    end=source.index('    # Is something listening',start)
    script=source[start:end]+'puts [portOf "http://127.0.0.1:12345/auth/abcdef_123-/"]\n'
    result=subprocess.run([tcl],input=script,text=True,capture_output=True)
    assert result.stdout.strip()=='12345' and not result.stderr
