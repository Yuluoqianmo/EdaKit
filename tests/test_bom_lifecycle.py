"""Rendered regression for BOM/workbench lifecycle; synthetic data only."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest


def test_bom_lifecycle_in_browser(tmp_path):
    root = Path(__file__).resolve().parents[1]
    node = shutil.which('node') or 'C:/Users/32657/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe'
    if not Path(node).is_file() and not shutil.which(node):
        pytest.skip('Node not available')
    env = os.environ.copy()
    bundled = Path('C:/Users/32657/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright')
    if not env.get('EDAKIT_PLAYWRIGHT_MODULE') and bundled.is_dir():
        env['EDAKIT_PLAYWRIGHT_MODULE'] = str(bundled)
    probe = subprocess.run([node, '-e', "try{require(process.env.EDAKIT_PLAYWRIGHT_MODULE||'playwright')}catch(e){process.exit(2)}"],
                           check=False, env=env, capture_output=True, text=True, timeout=15)
    if probe.returncode:
        pytest.skip('Playwright not available')
    env['EDAKIT_QA_OUT'] = str(tmp_path / 'screenshots')
    result = subprocess.run([node, str(root / 'tools/diag/bom_lifecycle_qa.cjs')],
                            check=False, env=env, cwd=root, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'PASS BOM lifecycle' in result.stdout
