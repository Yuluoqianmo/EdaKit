"""ES5 syntax guard for shipped CEF surfaces; browser/Capture tests remain required."""
from pathlib import Path
import esprima
import pytest

WEB = Path(__file__).resolve().parents[1] / 'src/edakit/server/web'
FILES = ['embed', 'workbench', 'properties', 'bom']
NODES = set('Program Identifier Literal ExpressionStatement BlockStatement EmptyStatement DebuggerStatement WithStatement ReturnStatement LabeledStatement BreakStatement ContinueStatement IfStatement SwitchStatement SwitchCase ThrowStatement TryStatement CatchClause WhileStatement DoWhileStatement ForStatement ForInStatement FunctionDeclaration FunctionExpression VariableDeclaration VariableDeclarator ThisExpression ArrayExpression ObjectExpression Property SequenceExpression UnaryExpression BinaryExpression AssignmentExpression UpdateExpression LogicalExpression ConditionalExpression NewExpression CallExpression MemberExpression'.split())


def visit(node, function=None):
    if not isinstance(node, dict):
        return
    kind = node.get('type')
    if kind:
        assert kind in NODES, kind
        assert not node.get('async', False) and not node.get('generator', False)
        if kind == 'VariableDeclaration': assert node['kind'] == 'var'
        if kind == 'Property': assert not node.get('method') and not node.get('computed') and not node.get('shorthand')
        if kind in ('FunctionDeclaration', 'FunctionExpression'): function = node
        if kind in ('CallExpression', 'NewExpression'):
            callee = node['callee']
            if callee.get('type') == 'Identifier': assert callee['name'] not in ('fetch', 'Promise')
            if callee.get('type') == 'MemberExpression' and not callee.get('computed'):
                prop = callee['property']['name']
                assert prop not in ('closest', 'includes', 'startsWith', 'endsWith')
                assert not (callee['object'].get('name') == 'Object' and prop == 'assign')
        if kind == 'MemberExpression' and node.get('property', {}).get('name') == 'key' and node['object'].get('name') in ('e', 'ev', 'event'):
            assert function and 'keyCode' in str(function)
    for value in node.values():
        if isinstance(value, dict): visit(value, function)
        elif isinstance(value, list):
            for child in value: visit(child, function)


@pytest.mark.parametrize('name', FILES)
def test_cef_script_es5(name):
    visit(esprima.parseScript((WEB / (name+'.js')).read_text(encoding='utf-8')).toDict())


@pytest.mark.parametrize('name', FILES)
def test_cef_styles(name):
    import re
    css = re.sub(r'/\*.*?\*/', '', (WEB / (name+'.css')).read_text(encoding='utf-8'), flags=re.S)
    assert not re.search(r'(?:^|[;{])\s*(?:gap|row-gap|column-gap)\s*:', css)
    assert not re.search(r'var\(\s*--|display\s*:\s*grid|:focus-visible|:is\(|:where\(', css)
    if '::placeholder' in css: assert '::-webkit-input-placeholder' in css
