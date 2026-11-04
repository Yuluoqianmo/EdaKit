"""Bounded structure-only inspection; never return arbitrary keys or values."""
import json

from .webmatch_browser import WebMatchError


class CheckpointError(WebMatchError):
    """Only diagnostics constructed here may cross the report boundary."""

    def __init__(self, reason, context):
        super().__init__('快照校验未通过（' + reason + '），未应用结果；请复制诊断报告')
        self.diagnostics = dict(context, reason=reason, containsMaterialValues=False)


def _shape(value):
    # No scalar content, arbitrary keys, exception text, or object repr.
    if value is None:
        return {'kind': 'null'}
    kinds = {str: 'string', int: 'integer', float: 'number', bool: 'boolean',
             list: 'array', dict: 'object'}
    result = {'kind': kinds.get(type(value), 'unsupported')}
    if isinstance(value, (list, dict)):
        result['size'] = min(len(value), 150001)
    return result


def read_checkpoint(payload):
    """Decode a bounded, sparse version-2 sheet snapshot in memory only.

    Row tuples carry their index, optional metadata, and indexed cell tuples.
    Unknown layouts and unapplied deltas fail closed instead of returning old data.
    """
    context = {}
    stage = 'payload'

    def fail(reason):
        raise CheckpointError(reason, dict(context, validationStage=stage))

    try:
        if not isinstance(payload, str) or len(payload) > 8_000_000:
            fail('payload_size_or_type')
        envelope = json.loads(payload)
        stage = 'document_envelope'
        document = envelope['data']['documentContent']
        checkpoint = document['checkpoint']
        if document.get('containsRollbackPoint', False):
            fail('rollback_present')
        stage = 'deltas'
        changes = document['deltas']['list']
        if not isinstance(changes, list):
            context['deltaShape'] = _shape(changes)
            fail('delta_list_type')
        context['deltaCount'] = len(changes)
        if changes:
            fail('unapplied_deltas')
        stage = 'base_version'
        if type(checkpoint.get('baseVersion')) is not int:
            context['baseVersionShape'] = _shape(checkpoint.get('baseVersion'))
            fail('base_version_type')
        stage = 'checkpoint_content'
        content = checkpoint['content']
        if not isinstance(content, str) or len(content) > 8_000_000:
            fail('checkpoint_content_size_or_type')
        root = json.loads(content)
        stage = 'schema_version'
        if type(root.get('version')) is not int or root['version'] != 2:
            context['versionShape'] = _shape(root.get('version'))
            fail('unsupported_schema_version')
        stage = 'sheets'
        sheets = root['content']
        if not isinstance(sheets, dict) or not 0 < len(sheets) <= 100:
            context['sheetsShape'] = _shape(sheets)
            fail('sheets_size_or_type')
        context['sheetCount'] = len(sheets)
        headers = ('Manufacturer_PN', '新物料编码', 'Part_Type')
        candidates = []
        for sheet_ordinal, sheet in enumerate(sheets.values()):
            stage = 'sheet'
            context = {k: v for k, v in context.items() if k in ('deltaCount', 'sheetCount')}
            context['sheetOrdinal'] = sheet_ordinal
            if not isinstance(sheet, dict) or not isinstance(sheet.get('rows'), list):
                context['sheetShape'] = _shape(sheet)
                fail('sheet_rows_type')
            count = sheet.get('rowCount')
            context['rowCountShape'] = _shape(count)
            context['serializedRows'] = len(sheet['rows'])
            if type(count) is not int or not 1 <= count <= 100000 or len(sheet['rows']) > 100000:
                fail('row_count_size_or_type')
            context['declaredRows'] = count
            rows = {}
            cell_count = 0
            for row_ordinal, entry in enumerate(sheet['rows']):
                stage = 'row_tuple'
                for key in ('cellOrdinal', 'columnShape', 'cellInfoShape', 'valueShape', 'cellShape'):
                    context.pop(key, None)
                context['rowOrdinal'] = row_ordinal
                context['rowShape'] = _shape(entry)
                if not isinstance(entry, list) or len(entry) != 3:
                    fail('row_tuple_size_or_type')
                index = entry[0]
                context['rowIndexShape'] = _shape(index)
                context['rowSlotShapes'] = [_shape(slot) for slot in entry[1:]]
                if type(index) is not int or not 0 <= index < count or index in rows:
                    fail('row_index_type' if type(index) is not int else
                         'duplicate_row_index' if index in rows else 'row_index_bounds')
                # Never infer coordinates from array order: sparse indices matter.
                slots = [slot for slot in entry[1:] if isinstance(slot, list)]
                if len(slots) != 1:
                    fail('cell_array_slot_count')
                cells = {}
                for cell_ordinal, cell in enumerate(slots[0]):
                    stage = 'cell_tuple'
                    context['cellOrdinal'] = cell_ordinal
                    context['cellShape'] = _shape(cell)
                    if not isinstance(cell, list) or len(cell) != 2:
                        fail('cell_tuple_size_or_type')
                    col, info = cell
                    context['columnShape'], context['cellInfoShape'] = _shape(col), _shape(info)
                    if type(col) is not int or not 0 <= col < 16384 or col in cells or not isinstance(info, dict):
                        fail('column_index_type' if type(col) is not int else
                             'column_index_bounds' if not 0 <= col < 16384 else
                             'duplicate_column_index' if col in cells else 'cell_info_type')
                    value = info.get('value', '')
                    if value is None:
                        value = ''
                    if not isinstance(value, (str, int, float, bool)) or isinstance(value, str) and len(value) > 32768:
                        context['valueShape'] = _shape(value)
                        fail('cell_value_size_or_type')
                    cells[col] = value
                    cell_count += 1
                    if cell_count > 150000:
                        fail('cell_count_limit')
                rows[index] = cells
            stage = 'headers'
            first = rows.get(0, {})
            columns = {}
            for header in headers:
                hits = [col for col, value in first.items() if value == header]
                if len(hits) > 1:
                    fail('duplicate_header')
                if hits:
                    columns[header] = hits[0]
            if len(columns) != len(headers):
                continue
            table = []
            numeric_models = 0
            stage = 'material_values'
            # Cell-loop locations no longer describe the row being validated.
            context = {key: context[key] for key in ('deltaCount', 'sheetCount',
                'sheetOrdinal', 'serializedRows', 'declaredRows')}
            for row_ordinal, index in enumerate(sorted(rows)):
                if index == 0:
                    continue
                values = tuple(rows[index].get(columns[h], '') for h in headers)
                model, code, typ = values
                # Spreadsheets may store digit-only model numbers as numbers.
                # Convert only exact browser-safe integers. Never coerce bools,
                # decimals, or numeric company codes, or strip text leading zeroes.
                if type(model) is int and abs(model) <= 9007199254740991:
                    model = str(model)
                    numeric_models += 1
                converted = (model, code, typ)
                # Numeric codes cannot safely preserve leading zeroes.
                if not all(isinstance(value, str) for value in converted):
                    context['rowOrdinal'] = row_ordinal
                    context['sourceRow'] = index + 1
                    context['materialValueShapes'] = [_shape(value) for value in values]
                    context['invalidFields'] = [header for header, value in zip(headers, converted)
                                                if not isinstance(value, str)]
                    fail('material_value_not_text')
                table.append(tuple(value.strip() for value in converted))
            candidates.append((table, {'serializedRows': len(rows), 'rowsScanned': len(table),
                'declaredRows': count, 'lastSerializedRow': max(rows, default=-1) + 1,
                'sheetCount': len(sheets), 'deltaCount': 0,
                'numericModelsConverted': numeric_models,
                'coverage': '唯一目标工作表的快照已序列化行；空白稀疏行未展开'}))
        if len(candidates) != 1:
            stage = 'target_sheet'
            context['candidateCount'] = len(candidates)
            fail('target_sheet_not_unique')
        return candidates[0]
    except CheckpointError:
        raise
    except (ValueError, KeyError, TypeError, AttributeError, RecursionError, OverflowError):
        raise CheckpointError('invalid_structure', dict(context, validationStage=stage)) from None


def inspect_checkpoint(payload):
    report = {'ok': False, 'containsMaterialValues': False, 'visited': 0,
              'truncated': False, 'headers': {h: 0 for h in
              ('Manufacturer_PN', '新物料编码', 'Part_Type')}, 'containers': []}
    allowed = set('version settings sheets sheet worksheets data cells cell cellData rows columns cols rowCount columnCount value values v text content blocks elements children type t index row col r c'.split())
    try:
        envelope = json.loads(payload)
        checkpoint = envelope['data']['documentContent']['checkpoint']
        content = checkpoint['content']
        if not isinstance(content, str) or len(content) > 8_000_000:
            raise ValueError()
        root = json.loads(content)
        if not isinstance(root, (dict, list)):
            raise ValueError()
        deltas = envelope['data']['documentContent'].get('deltas', {})
        changes = deltas.get('list') if isinstance(deltas, dict) else None
        report['deltaCount'] = len(changes) if isinstance(changes, list) else None
        report['baseVersionPresent'] = isinstance(checkpoint.get('baseVersion'), int)
        stack = [(root, '$', 0)]
        while stack:
            value, path, depth = stack.pop()
            report['visited'] += 1
            if report['visited'] > 150000 or depth > 40:
                report['truncated'] = True
                break
            if isinstance(value, str):
                if value in report['headers']:
                    report['headers'][value] += 1
            elif isinstance(value, (dict, list)):
                keys = list(value) if isinstance(value, dict) else list(range(len(value)))
                if depth <= 7 and len(report['containers']) < 60:
                    report['containers'].append({'path': path,
                        'kind': 'object' if isinstance(value, dict) else 'array',
                        'size': len(value), 'knownFields': [k for k in keys if k in allowed]})
                if len(stack) + len(keys) > 150000:
                    report['truncated'] = True
                    break
                stack.extend((value[k], path + '/' + (k if k in allowed else '*'), depth+1) for k in reversed(keys))
        report['ok'] = True
        report['coverage'] = 'structure_only_not_proof_of_complete_rows'
    except (ValueError, KeyError, TypeError, RecursionError):
        report['error'] = 'unrecognized_checkpoint_structure'
    return report
