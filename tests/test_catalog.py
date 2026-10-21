"""Catalog 归一化测试 (离线: 直接喂假的上游 JSON)。"""

from edakit.catalog import MallClient


def test_to_part_normalizes_search_item():
    raw = {
        "productCode": "C2040",
        "productModel": "RP2040",
        "brandNameEn": "Raspberry Pi",
        "encapStandard": "LQFN-56(7x7)",
        "productIntroEn": "ARM Cortex-M0+ ...",
        "stockNumber": 43042,
        "catalogNameEn": "Microcontrollers",
        "wmCatalogId": 941,
        "productImageUrl": "https://x/img.png",
        "pdfUrl": "https://x/ds.pdf",
        "isBasicPart": True,
        "productPriceList": [
            {"ladder": 1, "currencyPrice": 0.9975, "currencySymbol": "$"},
            {"ladder": 100, "currencyPrice": 0.85, "currencySymbol": "$"},
        ],
        "paramVOList": [{"paramName": "Voltage", "paramValue": "3.3V"}],
    }
    p = MallClient._to_part(raw)
    assert p.cid == "C2040"
    assert p.model == "RP2040"
    assert p.brand == "Raspberry Pi"
    assert p.package == "LQFN-56(7x7)"
    assert p.stock == 43042
    assert p.catalog_id == 941
    assert p.is_basic is True
    assert len(p.prices) == 2
    assert p.prices[1].qty == 100
    assert p.params["Voltage"] == "3.3V"
    # 没有 url 时按 C 编号兜一个
    assert "C2040" in p.url


def test_to_part_tolerates_missing_fields():
    p = MallClient._to_part({})
    assert p.cid == ""
    assert p.prices == []
    assert p.stock == 0
    assert p.url == ""          # 无编号时不硬编 URL


def test_to_category_builds_children():
    raw = {
        "catalogId": 1,
        "catalogNameEn": "Resistors",
        "parentId": 0,
        "productNum": 5,
        "childCatelogs": [
            {"catalogId": 11, "catalogNameEn": "Chip Resistors", "parentId": 1},
        ],
    }
    node = MallClient._to_category(raw)
    assert node is not None
    assert node.catalog_id == 1
    assert node.name == "Resistors"
    assert len(node.children) == 1
    assert node.children[0].catalog_id == 11


def test_to_category_without_id_is_none():
    assert MallClient._to_category({"catalogNameEn": "x"}) is None

def test_category_chinese_display_preserves_ids_and_original():
    from edakit.catalog.models import CategoryNode
    node = CategoryNode(30, 'Passives', children=[CategoryNode(501, 'Resistors', children=[CategoryNode(1199, 'Chip Resistor - Surface Mount')])])
    result = node.to_dict()
    assert result['name'] == '无源器件'
    assert result['children'][0]['name'] == '电阻器'
    chip = result['children'][0]['children'][0]
    assert chip['name'] == '贴片电阻'
    assert chip['id'] == 1199
    assert chip['originalName'] == 'Chip Resistor - Surface Mount'


def test_category_prefers_upstream_chinese():
    node = MallClient._to_category({'catalogId': 1, 'catalogName': '电阻器', 'catalogNameEn': 'Resistors'})
    assert node.to_dict()['name'] == '电阻器'

def test_technical_category_abbreviations_have_chinese_labels():
    import re
    from edakit.catalog.zh import category_zh
    for value in ['ARINC', 'DIN 41612', 'JFETs', 'DIACs, SIDACs', 'SCRs', 'FETs, MOSFETs', 'IGBTs', 'CODECS']:
        assert re.search('[\u4e00-\u9fff]', category_zh(value))


def test_electronic_navigation_excludes_general_merchandise_preserves_children():
    from edakit.catalog.models import CategoryNode
    from edakit.catalog.scope import electronic_categories
    resistor = CategoryNode(501, 'Resistors', children=[CategoryNode(1199, 'Chip Resistor - Surface Mount')])
    roots = [CategoryNode(15, 'Hardware, Fasteners, Accessories'),
             CategoryNode(30, 'Passives', children=[resistor]),
             CategoryNode(29, 'Office Supplies'), CategoryNode(16, 'Industrial Automation and Controls')]
    selected = electronic_categories(roots)
    assert [node.catalog_id for node in selected] == [501]
    assert selected[0].name == '电阻'
    assert selected[0].children is resistor.children
    assert selected[0].children[0].catalog_id == 1199


def test_category_and_package_filters_use_own_stock_query_schema(monkeypatch):
    calls = []
    def post(self, path, body):
        calls.append((path, body))
        return {'dataList': [{'productCode': 'C25804', 'encapStandard': '0603'}], 'totalRow': 5000, 'currPage': 2, 'pageRow': 30}
    monkeypatch.setattr(MallClient, '_post', post)
    result = MallClient().browse_category(1199, page=2, page_size=30, package='0603')
    path, body = calls[0]
    assert path == '/ftps/wm/product/query/list'
    assert body['catalogIdList'] == [1199]
    assert body['encapValueList'] == ['0603']
    assert body['currentPage'] == 2
    assert result.parts[0].package == '0603' and result.total == 5000


def test_package_options_are_upstream_facets_not_current_page(monkeypatch):
    def post(self, path, body):
        assert path.endswith('/query/param/group')
        assert body['catalogIdList'] == [1199] and body['keyword'] == 'resistor'
        return {'Package': [{'name': '0603'}, {'name': '0402'}, {'name': '-'}, {'name': '0603'}], 'totalCount': 10000}
    monkeypatch.setattr(MallClient, '_post', post)
    assert MallClient().package_options([1199], 'resistor') == {'packages': ['0402', '0603'], 'total': 10000}


def test_exact_product_metadata_does_not_take_a_different_code(monkeypatch):
    from edakit.catalog.models import Part, SearchResult
    monkeypatch.setattr(MallClient, 'search_keyword', lambda *a, **k: SearchResult(parts=[Part(cid='C11'), Part(cid='C2040', package='QFN')]))
    assert MallClient().product_detail('C2040').package == 'QFN'


def test_keyword_facets_resolve_matching_leaf_catalogs(monkeypatch):
    def post(self, path, body):
        if path.endswith('/global'):
            return {'catalogVOS': [{'catalogId': 17, 'childCatelogs': [{'catalogId': 258, 'childCatelogs': [{'catalogId': 941, 'childCatelogs': []}]}]}]}
        assert body['catalogIdList'] == [941]
        return {'Package': [{'name': 'QFN'}], 'totalCount': 1}
    monkeypatch.setattr(MallClient, '_post', post)
    assert MallClient().package_options([], 'RP2040')['packages'] == ['QFN']


def test_chinese_product_page_fills_package_and_exact_datasheet():
    import json
    from edakit.catalog.models import Part
    part = Part(cid='C2040', package='-', datasheet_url='https://international.example/old.pdf')
    web = {'productRecord': {'productCode': 'C2040', 'encapsulationModel': 'QFN-56'},
           'pdfFileDetailVO': {'fileUrl': '/upload/public/pdf/source/C2040.pdf'}}
    html = '<script id="__NEXT_DATA__">'+json.dumps({'props': {'pageProps': {'webData': web}}})+'</script>'
    MallClient._enrich_product_page(part, html)
    assert part.package == 'QFN-56'
    assert part.datasheet_url == 'https://atta.szlcsc.com/upload/public/pdf/source/C2040.pdf'
    other = Part(cid='C11')
    MallClient._enrich_product_page(other, html)
    assert other.datasheet_url == '' and other.package == ''


def test_compliance_certificate_is_not_a_datasheet():
    import json
    from edakit.catalog.models import Part
    web = {'productRecord': {'productCode': 'C11', 'fileTypeVOList': [
        {'fileType': 'certification_data', 'detailVOList': [{'fileUrl': '/RoHS.pdf'}]}]}}
    part = Part(cid='C11')
    MallClient._enrich_product_page(part, '<script id="__NEXT_DATA__">'+json.dumps({'props': {'pageProps': {'webData': web}}})+'</script>')
    assert part.datasheet_url == ''


def test_exact_code_package_option_does_not_need_global_category_tree(monkeypatch):
    from edakit.catalog.models import Part, SearchResult
    monkeypatch.setattr(MallClient, 'search_keyword', lambda *a, **k: SearchResult(parts=[Part(cid='C2040', package='QFN-56'), Part(cid='C20401', package='OTHER')]))
    assert MallClient().package_options([], 'c2040') == {'packages': ['QFN-56'], 'total': 1}
