import json
import copy
import threading

import pytest

from edakit.services.webmatch_structure import inspect_checkpoint
from edakit.services.webmatch_browser import CDP
from edakit.services.webmatch_browser import WebMatchError
from edakit.services.webmatch_structure import read_checkpoint
from edakit.services.webmatch_structure import CheckpointError


def snapshot_payload():
    sheet = {'rowCount': 1000, 'rows': [
        [0, None, [[1, {'value': 'Part_Type'}], [3, {'value': 'Manufacturer_PN'}],
                    [5, {'value': '新物料编码'}]]],
        [4, None, [[3, {'value': ' TEST-A '}], [5, {'value': '00001'}], [1, {'value': '电阻'}]]],
        [9, None, [[3, {'value': 'TEST-B'}], [5, {'value': '00002'}]]]]}
    content = {'version': 2, 'content': {'PRIVATE_SHEET': sheet}}
    return {'data': {'documentContent': {'checkpoint': {'content': json.dumps(content), 'baseVersion': 1218},
                                        'deltas': {'list': []}}}}


def test_sparse_snapshot_uses_indices_and_preserves_zero_codes():
    table, metadata = read_checkpoint(json.dumps(snapshot_payload()))
    assert table == [('TEST-A', '00001', '电阻'), ('TEST-B', '00002', '')]
    assert metadata['serializedRows'] == 3 and metadata['lastSerializedRow'] == 10
    assert 'PRIVATE' not in json.dumps(metadata)


@pytest.mark.parametrize('model', [0, 12345, -12345, 9007199254740991])
def test_integer_models_convert_without_altering_text_models_or_codes(model):
    payload = snapshot_payload()
    doc = payload['data']['documentContent']
    root = json.loads(doc['checkpoint']['content'])
    rows = root['content']['PRIVATE_SHEET']['rows']
    rows[1][2][0][1]['value'] = model
    rows[2][2][0][1]['value'] = '0012345'
    doc['checkpoint']['content'] = json.dumps(root)
    table, metadata = read_checkpoint(json.dumps(payload))
    assert table == [(str(model), '00001', '电阻'), ('0012345', '00002', '')]
    assert metadata['numericModelsConverted'] == 1


@pytest.mark.parametrize('model', [True, False, 123.5, 123.0, 9007199254740992,
                                  -9007199254740992])
def test_ambiguous_numeric_models_still_stop_without_partial_results(model):
    payload = snapshot_payload()
    doc = payload['data']['documentContent']
    root = json.loads(doc['checkpoint']['content'])
    root['content']['PRIVATE_SHEET']['rows'][1][2][0][1]['value'] = model
    doc['checkpoint']['content'] = json.dumps(root)
    with pytest.raises(CheckpointError) as error:
        read_checkpoint(json.dumps(payload))
    detail = error.value.diagnostics
    assert detail['reason'] == 'material_value_not_text'
    assert detail['invalidFields'] == ['Manufacturer_PN']
    assert detail['sourceRow'] == 5
    assert not any(key in detail for key in ('cellOrdinal', 'cellShape', 'rowSlotShapes'))


def test_real_report_shaped_integer_row_passes_parser_and_matching():
    from edakit.services.webmatch import WebMatch
    rows = [[0, None, [[1, {'value': 'Part_Type'}], [3, {'value': 'Manufacturer_PN'}],
                       [5, {'value': '新物料编码'}]]]]
    for index in range(1, 828):
        rows.append([index, None, [[1, {'value': '测试类型'}],
            [3, {'value': 12345 if index == 409 else 'SYNTHETIC-' + str(index)}],
            [5, {'value': '00001' if index == 409 else 'SYNTHETIC-CODE-' + str(index)}]]])
    content = {'version': 2, 'content': {'PRIVATE_SHEET': {'rowCount': 832, 'rows': rows}}}
    payload = {'data': {'documentContent': {'checkpoint': {'content': json.dumps(content), 'baseVersion': 1},
                                          'deltas': {'list': []}}}}
    class Reader:
        def open(self, url):
            pass

        def read_table(self, cancel, progress):
            return read_checkpoint(json.dumps(payload))
    manager = WebMatch(Reader)
    manager.command({'action': 'auto', 'session': 'owner', 'snapshot': 'snapshot',
        'url': 'https://alidocs.dingtalk.com/i/nodes/PRIVATE',
        '_models': ['12345', '0012345', 'SYNTHETIC-410']})
    manager.thread.join(2)
    status = manager.status('owner')
    assert status['state'] == 'done'
    summary = status['summary']
    assert summary['serializedRows'] == 828 and summary['rowsScanned'] == 827
    assert summary['numericModelsConverted'] == 1
    assert summary['matched'] == 2 and summary['unmatchedInRange'] == 1
    result = manager.result('owner', status['run'], 'snapshot')['records']
    assert result['12345'] == [('00001', '测试类型')] and '0012345' not in result
    report = json.dumps(manager.command({'action': 'report', 'session': 'owner'}))
    assert all(value not in report for value in ('12345', '00001', 'PRIVATE', 'SYNTHETIC'))


@pytest.mark.parametrize('case', ['delta', 'missing_delta', 'rollback', 'duplicate_row',
    'duplicate_col', 'duplicate_header', 'numeric_code', 'out_of_bounds', 'two_sheets', 'version'])
def test_snapshot_rejects_ambiguous_stale_or_malformed_data(case):
    payload = snapshot_payload()
    doc = payload['data']['documentContent']
    root = json.loads(doc['checkpoint']['content'])
    sheet = root['content']['PRIVATE_SHEET']
    if case == 'delta':
        doc['deltas']['list'] = [{'PRIVATE': 'SECRET'}]
    elif case == 'missing_delta':
        del doc['deltas']
    elif case == 'rollback':
        doc['containsRollbackPoint'] = True
    elif case == 'duplicate_row':
        sheet['rows'].append(copy.deepcopy(sheet['rows'][1]))
    elif case == 'duplicate_col':
        sheet['rows'][1][2].append([3, {'value': 'PRIVATE'}])
    elif case == 'duplicate_header':
        sheet['rows'][0][2].append([4, {'value': 'Manufacturer_PN'}])
    elif case == 'numeric_code':
        sheet['rows'][1][2][1][1]['value'] = 1
    elif case == 'out_of_bounds':
        sheet['rows'][1][0] = 1000
    elif case == 'two_sheets':
        root['content']['OTHER_PRIVATE'] = copy.deepcopy(sheet)
    else:
        root['version'] = 3
    doc['checkpoint']['content'] = json.dumps(root)
    with pytest.raises(WebMatchError) as error:
        read_checkpoint(json.dumps(payload))
    assert 'PRIVATE' not in str(error.value)


@pytest.mark.parametrize('case,reason', [
    ('row_type', 'row_index_type'), ('row_count', 'row_count_size_or_type'),
    ('rich_value', 'cell_value_size_or_type'), ('code_number', 'material_value_not_text')])
def test_parser_failure_reports_safe_specific_location(case, reason):
    payload = snapshot_payload()
    doc = payload['data']['documentContent']
    root = json.loads(doc['checkpoint']['content'])
    sheet = root['content']['PRIVATE_SHEET']
    if case == 'row_type':
        sheet['rows'][1][0] = 'PRIVATE_INDEX'
    elif case == 'row_count':
        sheet['rowCount'] = 'PRIVATE_COUNT'
    elif case == 'rich_value':
        sheet['rows'][1][2][0][1]['value'] = {'PRIVATE_KEY': 'PRIVATE_VALUE'}
    else:
        sheet['rows'][1][2][1][1]['value'] = 123456789
    doc['checkpoint']['content'] = json.dumps(root)
    with pytest.raises(CheckpointError) as error:
        read_checkpoint(json.dumps(payload))
    diagnostics = error.value.diagnostics
    assert diagnostics['reason'] == reason and diagnostics['validationStage']
    assert diagnostics['containsMaterialValues'] is False
    serialized = json.dumps(diagnostics) + str(error.value)
    assert all(value not in serialized for value in ('PRIVATE', 'TEST-A', '00001', '123456789'))


def test_service_reports_parser_failure_without_publishing_result():
    from edakit.services.webmatch import WebMatch
    class Reader:
        def open(self, url):
            pass

        def read_table(self, cancel, progress):
            raise CheckpointError('row_index_type', {'rowOrdinal': 2})
    manager = WebMatch(Reader)
    manager.command({'action': 'auto', 'session': 'owner', 'snapshot': 'private-snapshot',
        'url': 'https://alidocs.dingtalk.com/i/nodes/PRIVATE', '_models': ['PRIVATE_MODEL']})
    manager.thread.join(2)
    report = manager.command({'action': 'report', 'session': 'owner'})
    assert report['state'] == 'error' and not manager.run and not manager.records
    assert report['summary']['parser']['reason'] == 'row_index_type'
    assert 'PRIVATE' not in json.dumps(report)


def test_checkpoint_match_auto_result_conflicts_cancellation_and_private_report():
    from edakit.services.webmatch import WebMatch
    class Reader:
        def open(self, url):
            pass

        def close(self):
            pass

        def read_table(self, cancel, progress):
            progress('reading')
            return [('TEST-A', '00001', '电阻'), ('TEST-A', '00001', '电阻'),
                    ('TEST-B', '00002', ''), ('TEST-B', '00003', ''),
                    ('TEST-C', '', '')], {'reader_ms': 20, 'parsing_ms': 2}
    manager = WebMatch(Reader)
    body = {'action': 'auto', 'session': 'owner', 'snapshot': 'private-snapshot',
            'url': 'https://alidocs.dingtalk.com/i/nodes/PRIVATE',
            '_models': ['test-a', 'TEST-B', 'TEST-C', 'NONE']}
    manager.command(body)
    manager.thread.join(2)
    state = manager.status('owner')
    assert state['state'] == 'done'
    summary = state['summary']
    assert (summary['matched'], summary['conflicts'], summary['emptyCodes'], summary['unmatchedInRange']) == (1, 1, 1, 1)
    assert summary['duplicateModels'] == 2 and summary['batch_ms'] >= 20
    assert manager.result('owner', state['run'], 'private-snapshot')['records']['test-a'] == [('00001', '电阻')]
    report = json.dumps(manager.command({'action': 'report', 'session': 'owner'}))
    assert all(private not in report for private in ('TEST-A', '00001', 'PRIVATE', 'private-snapshot'))
    with pytest.raises(WebMatchError):
        manager.result('owner', state['run'], 'different-snapshot')
    class CancelReader(Reader):
        def read_table(self, cancel, progress):
            result = super().read_table(cancel, progress)
            cancel.set()
            return result
    manager = WebMatch(CancelReader)
    manager.command(body)
    manager.thread.join(2)
    assert manager.status('owner')['state'] == 'cancelled' and not manager.records


def test_browser_checkpoint_reader_minimizes_reads_and_cleans_up():
    from edakit.services.webmatch_browser import BrowserReader
    calls = []
    class Client:
        structure_requests = set()
        structure_ready = []

        def call(self, method, params=None, **kwargs):
            calls.append(method)
            if method == 'Browser.getWindowForTarget':
                return {'windowId': 1}
            if method == 'Runtime.evaluate':
                self.structure_ready.append('completed')
            if method == 'Network.getResponseBody':
                return {'body': json.dumps(snapshot_payload())}
            return {}
    reader = BrowserReader.__new__(BrowserReader)
    reader.cdp, reader.target = Client(), 'target'
    reader.prepare = lambda cancel, progress: {'login_and_page_wait_ms': 1000}
    reader.connect = lambda: None
    table, metadata = reader.read_table(threading.Event(), lambda msg: None)
    assert len(table) == 2 and metadata['backgroundWindow']
    assert metadata['reader_ms'] < metadata['login_and_page_wait_ms']
    assert calls.index('Browser.setWindowBounds') < calls.index('Page.reload')
    assert calls[-1] == 'Network.disable'
    assert not reader.cdp.structure_ready

    broken = snapshot_payload()
    broken['data']['documentContent']['checkpoint']['content'] = '{}'
    original_call = reader.cdp.call
    def malformed_response(method, params=None, **kwargs):
        if method == 'Network.getResponseBody':
            return {'body': json.dumps(broken)}
        return original_call(method, params, **kwargs)
    reader.cdp.call = malformed_response
    with pytest.raises(CheckpointError) as error:
        reader.read_table(threading.Event(), lambda msg: None)
    assert error.value.diagnostics['backgroundWindow']
    assert error.value.diagnostics['response_ms'] >= 0
    assert error.value.diagnostics['parsing_ms'] >= 0
    assert calls[-1] == 'Network.disable'
    assert not reader.cdp.structure_ready


def test_structure_redacts_material_values_unknown_keys_and_credentials():
    content = {'version': 2, 'sheets': {'PRIVATE_SHEET': {'cells': [
        ['Manufacturer_PN', '新物料编码', 'Part_Type'],
        ['PRIVATE_MODEL', 'PRIVATE_CODE', 'PRIVATE_TYPE']]}}}
    payload = {'data': {'accessToken': 'PRIVATE_TOKEN', 'documentContent': {
        'checkpoint': {'content': json.dumps(content), 'baseVersion': 1218},
        'deltas': {'list': []}}}}
    result = inspect_checkpoint(json.dumps(payload))
    assert result['ok'] and result['headers']['Manufacturer_PN'] == 1
    assert result['deltaCount'] == 0
    assert 'PRIVATE' not in json.dumps(result)


def test_structure_rejects_wrong_or_missing_content():
    for payload in ('broken', '{}', '{"data":null}'):
        assert not inspect_checkpoint(payload)['ok']


def test_nonempty_deltas_are_reported_not_claimed_as_applied():
    payload = {'data': {'documentContent': {'checkpoint': {'content': '{}'},
                                         'deltas': {'list': [{'SECRET': 'VALUE'}]}}}}
    result = inspect_checkpoint(json.dumps(payload))
    assert result['ok'] and result['deltaCount'] == 1
    assert result['coverage'] == 'structure_only_not_proof_of_complete_rows'
    assert 'SECRET' not in json.dumps(result)


def test_passive_capture_filters_origin_and_waits_for_response_completion():
    class Socket:
        def send(self, value):
            pass

        def recv(self):
            return json.dumps(events.pop(0))
    client = CDP.__new__(CDP)
    client.ws, client.seq = Socket(), 0
    client.structure_requests, client.structure_ready = set(), []
    events = [
        {'method': 'Network.responseReceived', 'params': {'requestId': 'wrong',
         'response': {'url': 'https://example.com/api/document/data', 'status': 200}}},
        {'method': 'Network.loadingFinished', 'params': {'requestId': 'wrong'}},
        {'method': 'Network.responseReceived', 'params': {'requestId': 'right',
         'response': {'url': 'https://alidocs.dingtalk.com/api/document/data', 'status': 200}}},
        {'id': 1, 'result': {}}]
    client.call('Runtime.evaluate')
    assert not client.structure_ready and client.structure_requests == {'right'}
    events.extend([{'method': 'Network.loadingFinished', 'params': {'requestId': 'right'}},
                   {'id': 2, 'result': {}}])
    client.call('Runtime.evaluate')
    assert client.structure_ready == ['right']


def test_service_probe_finishes_without_exposing_or_applying_match_run():
    from edakit.services.webmatch import WebMatch
    class Reader:
        def open(self, url):
            self.url = url

        def structure_probe(self, cancel, progress):
            progress('checking')
            return {'ok': True, 'containsMaterialValues': False}
    manager = WebMatch(Reader)
    manager.command({'action': 'probe', 'session': 'test',
                     'url': 'https://alidocs.dingtalk.com/i/nodes/SYNTHETIC_TEST'})
    manager.thread.join(2)
    status = manager.status('test')
    assert not status['busy'] and status['state'] == 'done'
    assert status['stage'] == 'structure_completed' and status['run'] == ''
    assert not manager.records and status['summary']['structure']['ok']
