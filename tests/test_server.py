"""本地服务路由测试 (离线: 商城/取数全部打桩)。

只验证服务本身的正确性: 路由、静态资源、错误码、放置请求的落盘。
真正访问立创商城的联调在网络可用时手工做 (见 docs/验证记录.md)。
"""

import json
import urllib.error
import urllib.request

import pytest
from conftest import DATA

from edakit.catalog.models import CategoryNode, Part, SearchResult
from edakit.easyeda.parse import parse_component
from edakit.server import app as server_app


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    server_app._model_bytes.cache_clear()

    payload = json.loads((DATA / "C2040.json").read_text(encoding="utf-8"))
    comp = parse_component("C2040", payload)

    def fake_component(self, cid):
        cid = cid.strip().upper()
        if not cid.startswith("C"):
            cid = "C" + cid
        if cid != "C2040":
            from edakit.errors import UpstreamChangedError

            raise UpstreamChangedError("Component not found")
        return comp

    monkeypatch.setattr(server_app.MallHandler, "_component", fake_component)

    class FakeMall:
        def search_keyword(self, kw, *, page=1, page_size=25, **kw2):
            return SearchResult(
                parts=[Part(cid="C2040", model="RP2040", brand="Raspberry Pi")],
                total=1, page=1, page_size=page_size,
            )

        def browse_category(self, cat, *, page=1, page_size=25, **kwargs):
            return SearchResult(parts=[], total=0, page=1, page_size=page_size)

        def category_tree(self):
            return [CategoryNode(catalog_id=501, name="Resistors", children=[CategoryNode(catalog_id=1199, name="Chip Resistor - Surface Mount")]),
                    CategoryNode(catalog_id=15, name="Hardware, Fasteners, Accessories"),
                    CategoryNode(catalog_id=29, name="Office Supplies")]

    monkeypatch.setattr(server_app.MallClient, "search_keyword", FakeMall.search_keyword)
    monkeypatch.setattr(server_app.MallClient, "browse_category", FakeMall.browse_category)
    monkeypatch.setattr(server_app.MallClient, "category_tree", FakeMall.category_tree)
    monkeypatch.setattr(server_app.MallClient, "product_detail", lambda self, cid: Part(cid=cid, package="LQFN-56(7x7)", datasheet_url="https://example.com/RP2040.pdf"))
    monkeypatch.setattr(server_app.MallClient, "package_options", lambda self, ids, keyword="": {"packages": ["0402", "0603"], "total": 10000})

    # stage_component 会下载 STEP 文件（网络）。离线测试必须打桩。
    from pathlib import Path

    from edakit.pipeline import Staged

    def fake_stage(comp, cfg, *, download_step=True, capture_only=False):
        d = Path(cfg.footprint_lib)
        d.mkdir(parents=True, exist_ok=True)
        xml = d / f"{comp.cid}.olb.xml"
        xml.write_text("<Lib/>", encoding="utf-8")
        return Staged(
            cid=comp.cid,
            workdir=d,
            symbol_xml=xml,
            footprint_name=comp.footprint.name if comp.footprint else f"{comp.cid}_PKG",
        )

    monkeypatch.setattr(server_app, "stage_component", fake_stage)

    httpd = server_app.make_server(port=0, verbose=False)
    import threading

    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def _get(base, path):
    with urllib.request.urlopen(base + path, timeout=30) as r:
        return r.status, r.read()


def _post(base, path, obj):
    req = urllib.request.Request(
        base + path, data=json.dumps(obj).encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.status, r.read()


def test_health(_isolate):
    s, b = _get(_isolate, "/api/health")
    assert s == 200 and json.loads(b)["ok"] is True


def test_index_and_static_served(_isolate):
    s, b = _get(_isolate, "/")
    assert s == 200 and b"<html" in b.lower()
    s, b = _get(_isolate, "/static/embed.css")
    assert s == 200 and len(b) > 1000


def test_static_blocks_directory_traversal(_isolate):
    with pytest.raises(urllib.error.HTTPError) as e:
        _get(_isolate, "/static/../../cli.py")
    assert e.value.code == 404


def test_search_returns_parts(_isolate):
    s, b = _get(_isolate, "/api/search?q=RP2040")
    d = json.loads(b)
    assert s == 200 and d["total"] == 1
    assert d["parts"][0]["cid"] == "C2040"


def test_part_detail_and_svgs(_isolate):
    s, b = _get(_isolate, "/api/part/C2040")
    d = json.loads(b)
    assert d["hasSymbol"] and d["hasFootprint"]
    assert d["pinCount"] == 57
    assert d["model3d"]["uuid"]
    s, b = _get(_isolate, "/api/svg/symbol/C2040.svg")
    assert s == 200 and b.startswith(b"<svg")
    s, b = _get(_isolate, "/api/svg/footprint/C2040.svg")
    assert s == 200 and b.startswith(b"<svg")


def test_unknown_part_is_502(_isolate):
    with pytest.raises(urllib.error.HTTPError) as e:
        _get(_isolate, "/api/part/C9999999")
    assert e.value.code == 502


def test_place_stages_files_and_queues(_isolate, tmp_path):
    s, b = _post(_isolate, "/api/place", {"cid": "C2040", "stage_only": True})
    d = json.loads(b)
    assert s == 200 and d["seq"]
    assert d["staged"]["footprint"] == "LQFN-56_L7.0-W7.0-P0.4-EP"
    assert d["captureOnline"] is False

    from edakit.bridge.queue import queue_dir

    reqs = list(queue_dir().glob("req_*.req"))
    assert len(reqs) == 1
    kv = {}
    for line in reqs[0].read_text(encoding="utf-8").splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            kv[k] = v
    assert kv["cid"] == "C2040"
    assert kv["stage_only"] == "1"
    assert kv["part_name"] == "RP2040"


def test_long_name_queue_matches_real_generated_package(_isolate, monkeypatch):
    from xml.etree import ElementTree as ET
    from edakit.pipeline import stage_component
    from edakit.bridge.queue import queue_dir

    component = server_app.MallHandler._component(None, "C2040")
    component.symbol.name = "HOARG0603-1/10W-5.1KR-0.1%-TCR25"
    monkeypatch.setattr(server_app, "stage_component", stage_component)
    _, body = _get(_isolate, "/api/es/place?cid=C2040&stage_only=1")
    staged = json.loads(body)["staged"]
    package = ET.parse(staged["symbolXml"]).find("./Package/Defn").get("name")
    request = next(queue_dir().glob("req_*.req")).read_text(encoding="utf-8")
    assert len(package) <= 31
    assert staged["partName"] == package
    assert f"part_name={package}\n" in request


def test_placement_queue_carries_properties_and_reuses_preparation(_isolate, monkeypatch):
    import hashlib
    from pathlib import Path
    from xml.etree import ElementTree as ET
    from edakit.pipeline import stage_component
    from edakit.bridge.queue import queue_dir

    component = server_app.MallHandler._component(None, "C2040")
    component.symbol.description = '芯片 <5V & "A">'
    component.symbol.manufacturer = "测试厂商"
    component.symbol.mpn = "REAL_MPN-123"
    monkeypatch.setattr(server_app, "stage_component", stage_component)
    _, body = _get(_isolate, "/api/es/place?cid=C2040&stage_only=1")
    first = json.loads(body)["staged"]
    _, body = _get(_isolate, "/api/es/place?cid=C2040&stage_only=1")
    second = json.loads(body)["staged"]
    assert second["preparationReused"] and second["symbolXml"] == first["symbolXml"]
    requests = list(queue_dir().glob("req_*.req"))
    assert len(requests) == 2
    for request in requests:
        fields = dict(line.split("=", 1) for line in request.read_text(encoding="utf-8").splitlines() if "=" in line)
        source = Path(fields["olb_xml"])
        assert fields["symbol_digest"] == hashlib.sha256(source.read_bytes()).hexdigest()
        package = ET.parse(source).find("Package")
        assert fields["part_name"] == package.find("Defn").get("name") == "RP2040_P6"
        assert {p.get("name"): p.get("val") for p in package.findall("LibPart/NormalView/SymbolUserProp/Defn")} == {
            "Description": component.symbol.description,
            "PCBFootprint": component.footprint.name,
            "Manufacturer": component.symbol.manufacturer,
            "Manufacturer_PN": component.symbol.mpn,
        }


def test_config_get_and_post(_isolate, tmp_path):
    s, b = _get(_isolate, "/api/config")
    assert s == 200 and "footprint_lib" in json.loads(b)
    s, b = _post(_isolate, "/api/config", {"place_mode": "cursor"})
    d = json.loads(b)
    assert d["place_mode"] == "cursor"
    s, b = _get(_isolate, "/api/config")
    assert json.loads(b)["place_mode"] == "cursor"


def test_place_status_unknown_seq(_isolate):
    s, b = _get(_isolate, "/api/place/status?seq=nope")
    assert s == 200 and json.loads(b)["result"] is None


def test_unknown_route_404(_isolate):
    with pytest.raises(urllib.error.HTTPError) as e:
        _get(_isolate, "/api/nope")
    assert e.value.code == 404


def test_preview_cache_revalidates_but_live_data_is_not_stored(_isolate):
    path = _isolate + "/api/png/footprint/C2040.png?size=512"
    with urllib.request.urlopen(path) as response:
        etag = response.headers["ETag"]
        assert "must-revalidate" in response.headers["Cache-Control"]
    with pytest.raises(urllib.error.HTTPError) as result:
        urllib.request.urlopen(urllib.request.Request(path, headers={"If-None-Match": etag}))
    assert result.value.code == 304
    with urllib.request.urlopen(_isolate + "/api/es/search?q=RP2040") as response:
        assert response.headers["Cache-Control"] == "no-store"


def test_embedded_place_prepares_capture_only(_isolate, monkeypatch):
    original = server_app.stage_component
    seen = []

    def stage(*args, **kwargs):
        seen.append(kwargs.get("capture_only"))
        return original(*args, **kwargs)

    monkeypatch.setattr(server_app, "stage_component", stage)
    _, data = _get(_isolate, "/api/es/place?cid=C2040&stage_only=1")
    assert seen == [True]
    assert json.loads(data)["preparationMs"] >= 0
    _post(_isolate, "/api/place", {"cid": "C2040", "stage_only": True})
    assert seen == [True, False]


def test_embedded_assets_replace_external_storefront():
    web = server_app.WEB_DIR
    html = (web / "embed.html").read_text(encoding="utf-8")
    assert "/static/embed.js" in html
    assert "/static/embed.css" in html
    assert not (web / "index.html").exists()
    assert not (web / "app.js").exists()


# ---------------------------------------------------------------------------
#  Capture 内嵌页签（IE7 内核）：/embed 页面 + JSONP 接口
# ---------------------------------------------------------------------------

def _get_str(base, path):
    with urllib.request.urlopen(base + path, timeout=30) as r:
        return r.status, r.read().decode("utf-8")


def test_embed_page_served_and_ie7_meta(_isolate):
    s, b = _get_str(_isolate, "/embed")
    assert s == 200
    assert "EdaKit" in b
    assert "X-UA-Compatible" in b
    assert "/static/embed.js" in b
    assert (server_app.WEB_DIR / "embed.js").is_file()


def test_embed_js_is_es3_only():
    """内嵌页签是 IE7 内核：embed.js 不能出现箭头函数 / let / const / 模板串。"""
    import re

    src = (server_app.WEB_DIR / "embed.js").read_text(encoding="utf-8")
    assert "=>" not in src
    assert not re.search(r"\b(let|const)\s+[A-Za-z_$]", src)
    assert "`" not in src
    assert "fetch(" not in src


def test_embed_js_syntax_if_node_available():
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        pytest.skip("本机没有 node，跳过 JS 语法检查")
    r = subprocess.run(
        [node, "--check", str(server_app.WEB_DIR / "embed.js")],
        capture_output=True, text=True, timeout=60,
    )
    assert r.returncode == 0, r.stderr


def test_jsonp_wraps_search(_isolate):
    s, b = _get_str(_isolate, "/api/es/search?q=RP2040&cb=cbA")
    assert s == 200
    assert b.startswith("/*lcsc*/cbA(")
    assert b.rstrip().endswith(");")
    inner = b[len("/*lcsc*/cbA("):].rstrip()[:-2]
    d = json.loads(inner)
    assert d["parts"][0]["cid"] == "C2040"


def test_jsonp_status_and_categories(_isolate):
    s, b = _get_str(_isolate, "/api/es/status?cb=cbB")
    assert s == 200 and b.startswith("/*lcsc*/cbB(")
    s, b = _get_str(_isolate, "/api/es/categories?cb=cbC")
    assert s == 200 and b.startswith("/*lcsc*/cbC(")
    assert "电阻" in b
    assert "Hardware" not in b and "Office" not in b


def test_jsonp_place_queues_and_does_not_switch_windows(_isolate, monkeypatch):
    s, b = _get_str(_isolate, "/api/es/place?cid=C2040&stage_only=1&cb=cbD")
    assert s == 200 and b.startswith("/*lcsc*/cbD(")

    from edakit.bridge.queue import queue_dir

    assert len(list(queue_dir().glob("req_*.req"))) == 1
    assert not hasattr(server_app, "switch_to_capture")

    # 普通 POST 仍会尝试切换（cursor 模式且非 stage_only）
    s2, b2 = _post(_isolate, "/api/place", {"cid": "C2040"})
    assert s2 == 200


def test_jsonp_place_status_reports_deferred_result(_isolate, monkeypatch):
    reply = {"seq": "test", "ok": False, "stage": "place", "message": "native failure"}
    monkeypatch.setattr(server_app, "read_response", lambda seq: reply if seq == "test" else None)
    status, body = _get_str(_isolate, "/api/es/place/status?seq=test&cb=placementStatus")
    assert status == 200
    data = json.loads(body[len("/*lcsc*/placementStatus("):].rstrip()[:-2])
    assert data["result"] == reply

@pytest.mark.parametrize('kind', ['symbol', 'footprint'])
def test_png_previews_are_real_images_with_requested_dimensions(_isolate, kind):
    import struct
    with urllib.request.urlopen(_isolate + '/api/png/' + kind + '/C2040.png?size=1024', timeout=30) as response:
        body = response.read()
        assert response.headers['Content-Type'].startswith('image/png')
    assert body.startswith(b'\x89PNG\r\n\x1a\n')
    assert struct.unpack('>II', body[16:24]) == (1024, 1024)
    assert len(body) > 2000


def test_png_preview_rejects_unbounded_sizes(_isolate):
    with pytest.raises(urllib.error.HTTPError) as error:
        _get(_isolate, '/api/png/footprint/C2040.png?size=999999')
    assert error.value.code == 400


def test_root_uses_the_same_embedded_storefront(_isolate):
    assert _get(_isolate, '/')[1] == _get(_isolate, '/embed')[1]
    with pytest.raises(urllib.error.HTTPError):
        _get(_isolate, '/static/app.js')




def test_package_facets_and_search_request(_isolate, monkeypatch):
    s, b = _get_str(_isolate, '/api/es/packages?cat=1199&cb=facet')
    assert s == 200 and '0402' in b and '10000' in b
    seen = {}
    def search(self, keyword, **kwargs):
        seen.update(kwargs)
        return SearchResult(parts=[], total=0)
    monkeypatch.setattr(server_app.MallClient, 'search_keyword', search)
    _get_str(_isolate, '/api/es/search?q=RP2040&package=0603&cb=result')
    assert seen['package'] == '0603'


def test_product_metadata_is_independent_of_cad(_isolate, monkeypatch):
    monkeypatch.setattr(server_app.MallHandler, '_component', lambda *a: (_ for _ in ()).throw(RuntimeError('no CAD')))
    s, b = _get_str(_isolate, '/api/es/product/C2040?cb=metadata')
    assert s == 200 and 'RP2040.pdf' in b and 'LQFN' in b


def test_datasheet_url_does_not_allow_script_links():
    assert server_app.safe_web_url('javascript:alert(1)') == ''
    assert server_app.safe_web_url('//example.com/manual.pdf') == 'https://example.com/manual.pdf'


def test_3d_png_uses_real_mesh_and_changes_with_rotation(_isolate, monkeypatch):
    from edakit.threed.step import StepFetcher
    obj = b'v 0 0 0\nv 2 0 0\nv 0 1 0\nv 0 0 3\nf 1 2 3\nf 1 2 4\nf 2 3 4\nf 3 1 4\n'
    monkeypatch.setattr(StepFetcher, 'download_obj_bytes', lambda *a: obj)
    with urllib.request.urlopen(_isolate + '/api/png/model3d/C2040.png?size=512&yaw=35') as r:
        a = r.read()
    with urllib.request.urlopen(_isolate + '/api/png/model3d/C2040.png?size=512&yaw=125') as r:
        b = r.read()
    assert a.startswith(b'\x89PNG') and b.startswith(b'\x89PNG') and a != b


def test_datasheet_click_opens_only_the_matching_product_url(_isolate, monkeypatch):
    opened = []
    monkeypatch.setattr(server_app.os, 'startfile', opened.append, raising=False)
    s, b = _get_str(_isolate, '/api/es/datasheet/open?cid=C2040&cb=openDoc')
    assert s == 200 and 'openDoc(' in b
    assert opened == ['https://example.com/RP2040.pdf']


def test_parent_category_browse_expands_to_leaf_ids(_isolate, monkeypatch):
    seen = {}
    def browse(self, cat, **kwargs):
        seen.update(kwargs)
        return SearchResult(parts=[], total=0)
    monkeypatch.setattr(server_app.MallClient, 'browse_category', browse)
    s, _ = _get_str(_isolate, '/api/es/browse?cat=501&cb=parent')
    assert s == 200 and seen['catalog_ids'] == [1199]


def test_attribute_facets_route_expands_parent_and_caches_scope(_isolate, monkeypatch):
    calls = []
    def facets(self, ids, keyword=""):
        calls.append((ids, keyword))
        return {"facets": [{"key": "Tolerance", "label": "精度", "values": [{"value": "±1%", "label": "±1%"}]}],
                "total": 123, "scope": "category-keyword"}
    monkeypatch.setattr(server_app.MallClient, "facet_options", facets)
    _, body = _get_str(_isolate, '/api/es/facets?cat=501&q=4K7&cb=facets')
    assert 'facets(' in body and '精度' in body
    _get(_isolate, '/api/facets?cat=501&q=4K7')
    _get(_isolate, '/api/facets?cat=501&q=10K')
    assert calls == [([1199], '4K7'), ([1199], '10K')]


def test_multivalue_attributes_reach_search_and_browse(_isolate, monkeypatch):
    from urllib.parse import urlencode
    seen = []
    def search(self, keyword, **kwargs):
        seen.append((keyword, kwargs))
        return SearchResult()
    monkeypatch.setattr(server_app.MallClient, 'search_keyword', search)
    monkeypatch.setattr(server_app.MallClient, 'browse_category', lambda self, cat, **kw: search(self, '', **kw))
    query = urlencode([('cat', '501'), ('package', '0603'), ('package', '0805'),
                       ('param.Tolerance', '±1%'), ('param.Tolerance', '±5%'), ('brand', '99'), ('page', '2')])
    _get(_isolate, '/api/search?q=4K7&'+query)
    _get(_isolate, '/api/browse?'+query)
    for _, kwargs in seen:
        assert kwargs['params'] == {'Tolerance': ['±1%', '±5%']}
        assert kwargs['packages'] == ['0603', '0805']
        assert kwargs['brand_ids'] == ['99']
        assert kwargs['catalog_ids'] == [1199] and kwargs['page'] == 2


def test_jsonp_errors_are_readable_and_invalid_brand_is_not_sent(_isolate, monkeypatch):
    _, body = _get_str(_isolate, '/api/es/search?q=4K7&brand=invalid&cb=failed')
    assert 'failed(' in body and 'ValueError' in body and '品牌' in body
    monkeypatch.setattr(server_app.MallClient, 'facet_options', lambda *a: (_ for _ in ()).throw(server_app.FetchError('upstream unavailable')))
    _, body = _get_str(_isolate, '/api/es/facets?cat=1199&cb=failed')
    assert 'failed(' in body and 'upstream unavailable' in body
