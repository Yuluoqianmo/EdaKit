"""Allegro env 配置测试 —— 幂等、可回滚、不覆盖用户已有配置。"""

from pathlib import Path

from edakit.install import allegro_env


def _pcbenv(tmp_path: Path) -> Path:
    d = tmp_path / "pcbenv"
    d.mkdir()
    return d


def test_configure_creates_block(tmp_path):
    pcbenv = _pcbenv(tmp_path)
    target = allegro_env.configure(str(tmp_path / "lib"), pcbenv=pcbenv)
    text = target.read_text(encoding="utf-8")
    assert allegro_env.BEGIN in text and allegro_env.END in text
    for var in allegro_env.VARS:
        assert f"{var} = " in text
    # 路径统一成正斜杠
    assert (str(tmp_path / "lib")).replace("\\", "/") in text


def test_configure_preserves_existing_content(tmp_path):
    pcbenv = _pcbenv(tmp_path)
    env = pcbenv / "env"
    env.write_text("padpath = C:/mine $padpath\nother = 1\n", encoding="utf-8")
    allegro_env.configure(str(tmp_path / "lib"), pcbenv=pcbenv)
    text = env.read_text(encoding="utf-8")
    assert "C:/mine" in text          # 用户旧配置还在
    assert "other = 1" in text
    assert "$padpath" in text         # 我们的块是追加而非覆盖


def test_configure_is_idempotent(tmp_path):
    pcbenv = _pcbenv(tmp_path)
    for _ in range(3):
        allegro_env.configure(str(tmp_path / "lib"), pcbenv=pcbenv)
    text = (pcbenv / "env").read_text(encoding="utf-8")
    assert text.count(allegro_env.BEGIN) == 1
    assert text.count(allegro_env.END) == 1


def test_configure_backs_up_once(tmp_path):
    pcbenv = _pcbenv(tmp_path)
    env = pcbenv / "env"
    env.write_text("padpath = C:/mine $padpath\n", encoding="utf-8")
    allegro_env.configure(str(tmp_path / "lib"), pcbenv=pcbenv)
    bak = pcbenv / "env.lcsc2cadence.bak"
    assert bak.exists()
    assert "C:/mine" in bak.read_text(encoding="utf-8")


def test_unconfigure_removes_block_only(tmp_path):
    pcbenv = _pcbenv(tmp_path)
    env = pcbenv / "env"
    env.write_text("padpath = C:/mine $padpath\n", encoding="utf-8")
    allegro_env.configure(str(tmp_path / "lib"), pcbenv=pcbenv)
    allegro_env.unconfigure(pcbenv=pcbenv)
    text = env.read_text(encoding="utf-8")
    assert allegro_env.BEGIN not in text
    assert "C:/mine" in text


def test_unconfigure_missing_file_is_noop(tmp_path):
    pcbenv = _pcbenv(tmp_path)
    assert allegro_env.unconfigure(pcbenv=pcbenv) is None


def test_build_block_uses_forward_slashes(tmp_path):
    block = allegro_env.build_block(r"C:\Users\me\lib")
    assert "C:/Users/me/lib" in block
    assert "\\" not in block


# ---------------------------------------------------------------------------
#  pcbenv 定位：不能只看 %USERPROFILE%
#
#  Cadence 安装时会把 HOME 指向它自己的数据目录（用户机器上是 D:/Cadence/SPB_Data）。
#  Allegro 读的是 $HOME/pcbenv/env；只按 USERPROFILE 找会写到一个 Allegro 不看的地方，
#  用户配了半天毫无效果 —— 这个坑必须在测试里锁死。
# ---------------------------------------------------------------------------

def test_find_pcbenv_prefers_cadence_data_dir(tmp_path, monkeypatch):
    spb = tmp_path / "D_drive" / "Cadence" / "SPB_17.2"
    tcl = spb / "tools" / "capture" / "tclscripts"
    tcl.mkdir(parents=True)

    data_env = tmp_path / "D_drive" / "Cadence" / "SPB_Data" / "pcbenv"
    data_env.mkdir(parents=True)
    (data_env / "env").write_text("padpath = X $padpath\n", encoding="utf-8")

    user_pcbenv = tmp_path / "user" / "pcbenv"
    user_pcbenv.mkdir(parents=True)

    monkeypatch.setenv("HOME", str(tmp_path / "user"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "user"))

    got = allegro_env.find_pcbenv(str(spb))
    assert got == data_env, f"应该选 SPB_Data 里的 pcbenv，实际选了 {got}"


def test_find_pcbenv_uses_home_when_no_cadence_root(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / "pcbenv").mkdir(parents=True)
    (home / "pcbenv" / "env").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "other"))
    assert allegro_env.find_pcbenv() == home / "pcbenv"


def test_find_pcbenv_prefers_dir_with_env_file(tmp_path, monkeypatch):
    a = tmp_path / "a" / "pcbenv"
    b = tmp_path / "b" / "pcbenv"
    a.mkdir(parents=True)
    b.mkdir(parents=True)
    (b / "env").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(tmp_path / "a"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "b"))
    assert allegro_env.find_pcbenv() == b


def test_spb_root_from_tcl():
    from edakit.install.deploy import spb_root_from_tcl
    from pathlib import Path

    tcl = Path("/x/Cadence/SPB_17.2/tools/capture/tclscripts")
    assert spb_root_from_tcl(tcl) == Path("/x/Cadence/SPB_17.2")
    assert spb_root_from_tcl(Path("/tmp/whatever")) is None
