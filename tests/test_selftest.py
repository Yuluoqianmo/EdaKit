"""``selftest`` 子命令测试。

这个命令的存在理由：用户第一次构建出的 exe 因为打包入口写错，一跑就 ImportError，
而构建脚本照样报「打包成功」。所以必须有一条「文件生成了 ≠ 真能用」的检查，
而且这条检查要能在打包产物里跑起来（不依赖 tests/、不联网、不需要 Cadence）。

这里在开发环境下测它；打包后的真实运行由 build_exe 脚本每天跑。
"""

import json

import pytest

from edakit import cli


def _run(argv, capsys):
    code = cli.main(argv)
    return code, capsys.readouterr().out


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))


def test_selftest_passes_in_dev_environment(capsys):
    code, out = _run(["selftest"], capsys)
    assert code == 0, out
    assert "自检全部通过" in out
    for label in ("网页资源", "TCL 模板", "解析器", "符号 XML 生成",
                  "封装 SKILL 生成", "SVG 预览渲染", "HTTP 服务"):
        assert label in out, f"自检没报 {label}"
    assert "[失败]" not in out


def test_selftest_reports_parse_failure(capsys, monkeypatch):
    """样例找不到时必须报失败、返回非 0 —— 不能静默当成通过。"""
    monkeypatch.setattr(cli, "_sample_component_path", lambda: None)
    code, out = _run(["selftest"], capsys)
    assert code == 2
    assert "[失败]" in out
    assert "自检未通过" in out


def test_selftest_detects_corrupt_sample(capsys, monkeypatch, tmp_path):
    bad = tmp_path / "C2040.json"
    bad.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(cli, "_sample_component_path", lambda: bad)
    code, out = _run(["selftest"], capsys)
    assert code == 2
    assert "解析器" in out


def test_selftest_detects_missing_web_assets(capsys, monkeypatch, tmp_path):
    from edakit.server import app as server_app

    monkeypatch.setattr(server_app, "WEB_DIR", tmp_path)   # 空目录
    code, out = _run(["selftest"], capsys)
    assert code == 2
    assert "网页资源" in out
    assert "[失败]" in out


def test_sample_component_path_resolves_in_dev():
    p = cli._sample_component_path()
    assert p is not None and p.is_file()
    # 能真解析出来
    from edakit.easyeda.parse import parse_component

    comp = parse_component("C2040", json.loads(p.read_text(encoding="utf-8")))
    assert comp.symbol is not None and comp.footprint is not None


def test_selftest_listed_in_help(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    out = capsys.readouterr().out
    assert "selftest" in out
