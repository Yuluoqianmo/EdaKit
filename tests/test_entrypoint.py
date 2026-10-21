"""打包入口的回归测试。

这个 bug 让用户第一次构建出的 exe 完全跑不起来：

    ImportError: attempted relative import with no known parent package

原因：spec 原来把 ``src/edakit/__main__.py`` 直接当打包入口。PyInstaller 会把它
当成一个**独立的顶层脚本**编译，包上下文丢失，于是那句 ``from .cli import main`` 就炸了。

（``python -m edakit`` 是能跑的 —— 那种调用方式下它有父包。两条路径不一样，
所以「-m 能跑」不能证明打包能跑。这些测试就是盯这个差异。）
"""

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "entry.py"
SPEC = ROOT / "edakit.spec"
PKG_MAIN = ROOT / "src" / "edakit" / "__main__.py"


def _run_as_script(script: Path, *args: str) -> subprocess.CompletedProcess:
    """像 PyInstaller 打包出来的 exe 那样调用：把脚本当顶层脚本跑。"""
    env = dict(os.environ)
    src = str(ROOT / "src")
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True, text=True, timeout=180, env=env, cwd=str(ROOT),
    )


def test_entry_module_exists():
    assert ENTRY.is_file(), "打包入口 entry.py 不见了"


def test_entry_uses_absolute_import():
    text = ENTRY.read_text(encoding="utf-8")
    # 不能有顶层相对导入
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("from .") or s.startswith("import ."):
            raise AssertionError(f"entry.py 里有相对导入，打包后会炸: {line!r}")
    assert "from edakit.cli import main" in text


def test_entry_runs_as_toplevel_script():
    """直接以脚本方式执行 entry.py —— 这正是 PyInstaller 的方式。"""
    r = _run_as_script(ENTRY, "--version")
    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    assert r.stdout.strip() == "0.1.0"


def test_entry_subcommand_works_as_script():
    r = _run_as_script(ENTRY, "parse", "--lcsc", "C2040",
                       "--json", str(ROOT / "tests" / "data" / "C2040.json"))
    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    assert "RP2040" in r.stdout


def test_package_main_still_works_with_dash_m():
    """python -m edakit 这条路径也要保住。"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    r = subprocess.run(
        [sys.executable, "-m", "edakit", "--version"],
        capture_output=True, text=True, timeout=180, env=env, cwd=str(ROOT),
    )
    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    assert r.stdout.strip() == "0.1.0"


def _analysis_call_args() -> list[object]:
    """从 spec 里读出 ``Analysis(...)`` 第一个实参的字面量。

    spec 是合法 Python，用 ast 解析最稳 —— 不用正则去猜注释和换行。
    """
    import ast

    tree = ast.parse(SPEC.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "Analysis":
            assert node.args, "Analysis() 没传实参"
            return ast.literal_eval(node.args[0])
    raise AssertionError("spec 里没找到 Analysis(...) 调用")


def test_spec_points_at_entry_not_package_main():
    scripts = _analysis_call_args()
    assert scripts == ["entry.py"], (
        f"spec 的入口应该是 ['entry.py']，实际是 {scripts!r}；"
        "指回 __main__.py 会导致 "
        "ImportError: attempted relative import with no known parent package"
    )


def test_spec_keeps_src_on_pathex():
    spec = SPEC.read_text(encoding="utf-8")
    assert 'pathex=["src"]' in spec, "spec 丢了 pathex=[\"src\"]，entry.py 就找不到包了"


def test_relative_import_really_fails_when_run_as_script():
    """把 bug 本身钉住：__main__.py 当顶层脚本跑**必须**失败。

    如果哪天 Python/PyInstaller 变了行为让这行不再报错，这个测试会提醒我们
    重新评估（而不是让结论悄悄失效）。
    """
    r = _run_as_script(PKG_MAIN, "--version")
    assert r.returncode != 0
    assert "relative import" in (r.stderr or "")
