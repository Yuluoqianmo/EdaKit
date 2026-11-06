"""Fill the two-sheet engineering report layouts without rebuilding their styles."""
import io
import re
import zipfile
from copy import deepcopy
from pathlib import Path
from xml.etree import ElementTree as ET

from . import bom


def path(kind):
    return Path(__file__).parents[1]/'ibom'/'templates'/(kind+'.xlsx')


def fill(data, rows, metadata, numeric=()):
    with bom.workbook(data) as z:
        sheets = bom.sheets(z)
        if len(sheets) != 2:
            raise ValueError('报告模板必须包含封面和数据表')
        parts = {i.filename: z.read(i.filename) for i in z.infolist()}
        # Source workbooks may retain obsolete links and calculation caches.
        removed = {n for n in parts if n.startswith('xl/externalLinks/') or n == 'xl/calcChain.xml'}
        for name in removed:
            del parts[name]
        for name in list(parts):
            if name.endswith('.rels') or name in ('[Content_Types].xml', 'xl/workbook.xml'):
                root = bom.xml(parts[name])
                for parent in root.iter():
                    for child in list(parent):
                        if (child.tag.endswith('externalReferences') or
                            'externalLink' in child.get('Type', '') or
                            child.get('TargetMode') == 'External' or
                            'calcChain' in child.get('Type', '') or
                            child.get('PartName', '').lstrip('/') in removed):
                            parent.remove(child)
                parts[name] = ET.tostring(root, encoding='utf-8', xml_declaration=True)
        strings = []
        if 'xl/sharedStrings.xml' in parts:
            strings = list(bom.xml(parts['xl/sharedStrings.xml']))
        roots = []
        for _, name in sheets:
            root = bom.xml(parts[name]); roots.append(root)
            for c in root.iter(bom.tag('c')):
                if c.get('t') == 's':
                    inline = deepcopy(strings[int(c.find(bom.tag('v')).text)])
                    inline.tag = bom.tag('is')
                    c.remove(c.find(bom.tag('v')))
                    c.set('t', 'inlineStr'); c.append(inline)
        cover, table = roots
        title = metadata.get('title', '')
        def set_value(root, ref, value):
            c = next(c for c in root.iter(bom.tag('c')) if c.get('r') == ref)
            replacement = bom.cell(ref, value, c.get('s', '0'))
            c.clear(); c.attrib.update(replacement.attrib); c.extend(replacement)
        cover_title = metadata.get('coverTitle') or re.sub(r'[_ -]*(?:单板物料清单|单板BOM清单|PCB坐标文件|坐标文件)$', '', title)
        cover_cell = next(c for c in cover.iter(bom.tag('c')) if c.get('r') == 'A1')
        if not cover_cell.findall(bom.tag('is')+'/'+bom.tag('r')):
            # Migrate earlier two-sheet exports whose cover lost rich text.
            kind = 'coordinates' if len(next(r for r in table.find(bom.tag('sheetData')) if r.get('r') == '2')) == 9 else 'bom'
            with bom.workbook(path(kind).read_bytes()) as default:
                original = bom.xml(default.read(bom.sheets(default)[0][1]))
                rich = original.find('.//'+bom.tag('c')+'[@r="A1"]/'+bom.tag('is'))
                for child in list(cover_cell): cover_cell.remove(child)
                cover_cell.set('t', 'inlineStr'); cover_cell.append(deepcopy(rich))
        for run in cover_cell.findall(bom.tag('is')+'/'+bom.tag('r')):
            text = run.find(bom.tag('t'))
            if text is None: continue
            value = text.text or ''
            size = run.find(bom.tag('rPr')+'/'+bom.tag('sz'))
            font = run.find(bom.tag('rPr')+'/'+bom.tag('rFont'))
            if (size is not None and size.get('val') == '48') or '{{title}}' in value:
                text.text = cover_title+'\n'
            elif '文件编号：' in value:
                value = re.sub(r'文件编号：[^\r\n]*', lambda m: '文件编号：'+metadata.get('documentNumber', ''), value)
                text.text = value
            elif font is not None and font.get('val') == 'Wingdings 2':
                status = metadata.get('documentStatus', '正式')
                # There are two checkbox runs: temporary, then formal.
                checkbox_runs = [r for r in cover_cell.findall(bom.tag('is')+'/'+bom.tag('r')) if r.find(bom.tag('rPr')+'/'+bom.tag('rFont')) is not None and r.find(bom.tag('rPr')+'/'+bom.tag('rFont')).get('val') == 'Wingdings 2']
                text.text = 'R' if (run is checkbox_runs[0]) == (status == '临时') else '£'
        # Template signatures and project values must not leak into another job.
        for c in cover.iter(bom.tag('c')):
            if c.get('r') != 'A1':
                for child in list(c): c.remove(child)
                c.attrib.pop('t', None)
        for ref, value in {
            'J25': '共', 'L25': '页',
            'A27': '版  本', 'B27': metadata.get('version', ''),
            'D27': '编  制', 'E27': metadata.get('author', ''),
            'G27': '审  核', 'H27': metadata.get('reviewer', ''),
            'J27': '批  准', 'K27': metadata.get('approver', ''),
            'A28': '日  期', 'B28': metadata.get('date', ''),
            'A29': '更改项：'+metadata.get('changes', ''),
        }.items():
            set_value(cover, ref, value)
        sd = table.find(bom.tag('sheetData'))
        sample = next(r for r in sd if r.get('r') == '3')
        styles = {re.sub(r'\d', '', c.get('r')): c.get('s', '0') for c in sample}
        for r in list(sd):
            if int(r.get('r')) >= 3: sd.remove(r)
        set_value(table, 'A1', title)
        header_cells = list(next(r for r in sd if r.get('r') == '2'))
        count = len(header_cells)
        meta_ref = 'I1' if count == 10 else 'H1'
        set_value(table, meta_ref, '制表人：'+metadata.get('author', '')+'\n版本号：'+metadata.get('version', '')+'\n时间：'+metadata.get('date', ''))
        for number, values in enumerate(rows, 3):
            row = ET.SubElement(sd, bom.tag('row'), r=str(number), ht=str(max(30, min(409, max((len(str(v))//30+1)*16 for v in values)))), customHeight='1')
            for i, value in enumerate(values):
                col = chr(65+i)
                row.append(bom.cell(col+str(number), value, styles.get(col, '0'), i in numeric and value != ''))
        dim = table.find(bom.tag('dimension'))
        if dim is not None: dim.set('ref', 'A1:'+chr(64+count)+str(max(2, len(rows)+2)))
        for (_, name), root in zip(sheets, roots):
            parts[name] = ET.tostring(root, encoding='utf-8', xml_declaration=True)
        if 'xl/sharedStrings.xml' in parts:
            parts['xl/sharedStrings.xml'] = ('<sst xmlns="'+bom.NS+'" count="0" uniqueCount="0"/>').encode()
        for name in ('docProps/core.xml',):
            if name in parts:
                root = bom.xml(parts[name])
                for c in root: c.text = ''
                parts[name] = ET.tostring(root, encoding='utf-8', xml_declaration=True)
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as target:
            for name, content in parts.items(): target.writestr(name, content)
        return output.getvalue()
