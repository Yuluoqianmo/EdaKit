"""自动配置 Allegro 环境变量 —— 让 Allegro 能找到我们生成的封装。

Allegro 靠环境变量找库文件:
    padpath     → .pad (焊盘)        我们的封装库目录
    psmpath     → .psm / .dra (封装)
    steppath    → .step (3D 模型)
    step_mapping_path → .map (3D 映射)

这些变量定义在 Cadence 的 ``env`` 文件里:
    <SPB>\\share\\pcb\\text\\env         (全局)
    %HOME%\\pcbenv\\env                  (用户级, 优先级更高)

**只改用户级 env**，不动全局那份 —— 这样卸载时容易回滚，也不影响别人的安装。

写入的是**带标记的块**:
    # >>> lcsc2cadence begin
    padpath = ... $padpath
    # <<< lcsc2cadence end
重复配置时先删旧块再写新块，幂等。
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from ..errors import DeployError

BEGIN = "# >>> lcsc2cadence begin"
END = "# <<< lcsc2cadence end"
_BLOCK_RE = re.compile(
    re.escape(BEGIN) + r".*?" + re.escape(END) + r"\n?", re.DOTALL
)

VARS = ("padpath", "psmpath", "steppath", "step_mapping_path")


def _candidate_pcbenvs(cadence_root: str | None = None) -> list[Path]:
    """列出所有可能存放 pcbenv 的位置，**按可信度排序**。

    为什么不能只用 %USERPROFILE%：
    Cadence 安装时会把 ``HOME`` 指向它自己的数据目录（常见是
    ``D:\\Cadence\\SPB_Data``），Allegro 读的是 ``$HOME/pcbenv/env``。
    只按 USERPROFILE 找会写到一个 Allegro 根本不看的地方 —— 用户配了半天没效果。

    候选顺序：
      1. 显式给的 cadence_root 旁边的 SPB_Data/pcbenv
      2. 现有 HOME（Cadence 会话里通常已指向 SPB_Data）
      3. USERPROFILE
      4. 各盘符下 <盘>:\\Cadence\\SPB_Data\\pcbenv
    """
    cands: list[Path] = []

    def add(p: Path | None) -> None:
        if p is None:
            return
        try:
            key = str(p.resolve()).lower()
        except OSError:
            key = str(p).lower()
        for existing in cands:
            try:
                if str(existing.resolve()).lower() == key:
                    return
            except OSError:
                if str(existing).lower() == key:
                    return
        cands.append(p)

    if cadence_root:
        root = Path(cadence_root)
        add(root.parent / "SPB_Data" / "pcbenv")
        add(root / "SPB_Data" / "pcbenv")

    for var in ("HOME", "USERPROFILE"):
        v = os.environ.get(var)
        if v:
            add(Path(v) / "pcbenv")

    for drive in ("C:", "D:", "E:", "F:"):
        d = Path(drive + "\\")
        if d.is_dir():
            add(d / "Cadence" / "SPB_Data" / "pcbenv")

    return cands


def find_pcbenv(cadence_root: str | None = None) -> Path:
    """定位 Allegro 真正会读的 pcbenv 目录。

    优先选**已经有 env 文件**的那个，其次选目录已存在的，最后按候选顺序新建。
    """
    cands = _candidate_pcbenvs(cadence_root)
    if not cands:
        raise DeployError("找不到 HOME/USERPROFILE，也无法推断 Cadence 数据目录，无法定位 pcbenv")

    for c in cands:
        if (c / "env").is_file():
            return c
    for c in cands:
        if c.is_dir():
            return c
    return cands[0]


def _read_env(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        raise DeployError(f"读不到 env 文件 {path}: {e}") from e


def _write_env(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        backup = path.with_suffix(path.suffix + ".lcsc2cadence.bak")
        if not backup.exists():
            backup.write_text(path.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
    path.write_text(text, encoding="utf-8", newline="\n")


def build_block(lib_dir: str, step_dir: str | None = None) -> str:
    """生成要写进 env 的配置块。

    用 ``$var`` 形式**追加**而不是覆盖 —— 保留用户已有的库路径。
    Allegro 的 env 语法: 直接写变量名赋值，多个路径用空格分隔，``$name`` 引用自身旧值。
    """
    lib = lib_dir.replace("\\", "/")
    if any(c in lib for c in '\r\n\x00"$'):
        raise DeployError('封装库路径含 Allegro 环境文件不支持的字符')
    if any(c.isspace() for c in lib):
        lib = '"' + lib + '"'
    step = (step_dir or lib_dir).replace('\\', '/')
    if any(c in step for c in '\r\n\x00"$'):
        raise DeployError('STP 库路径含 Allegro 环境文件不支持的字符')
    if any(c.isspace() for c in step):
        step = '"' + step + '"'
    lines = [BEGIN]
    lines.append("# 由 lcsc2cadence 自动生成，请勿手改；卸载/重新配置会覆盖本块。")
    lines.append(f"padpath = {lib} $padpath")
    lines.append(f"psmpath = {lib} $psmpath")
    lines.append(f"steppath = {step} $steppath")
    lines.append(f"step_mapping_path = {lib} $step_mapping_path")
    lines.append(END)
    return "\n".join(lines) + "\n"


def configure(lib_dir: str, *, pcbenv: Path | None = None, dry_run: bool = False,
              cadence_root: str | None = None, step_dir: str | None = None) -> Path:
    """把封装库目录写进用户 env。返回被修改的 env 文件路径。"""
    target = (pcbenv or find_pcbenv(cadence_root)) / "env"
    text = _read_env(target)
    text = _BLOCK_RE.sub("", text)          # 先清掉旧块 (幂等)
    block = build_block(lib_dir, step_dir)

    if text and not text.endswith("\n"):
        text += "\n"
    text += block

    if dry_run:
        print(f"[dry-run] 将写入 {target}:\n{block}")
        return target

    _write_env(target, text)
    print(f"已更新 Allegro env: {target}")
    for line in block.splitlines():
        if "=" in line and not line.startswith("#"):
            print(f"  {line}")
    print("重启 Allegro 后生效。")
    return target


def unconfigure(*, pcbenv: Path | None = None, cadence_root: str | None = None) -> Path | None:
    """从用户 env 里移除本工具写的块 (回滚)。"""
    target = (pcbenv or find_pcbenv(cadence_root)) / "env"
    if not target.exists():
        return None
    text = _read_env(target)
    new = _BLOCK_RE.sub("", text)
    if new != text:
        _write_env(target, new)
        print(f"已从 {target} 移除 lcsc2cadence 配置块")
        return target
    return None


def show(*, pcbenv: Path | None = None, cadence_root: str | None = None) -> None:
    """打印当前状态，便于排查。"""
    target = (pcbenv or find_pcbenv(cadence_root)) / "env"
    print(f"env 文件: {target}  {'(存在)' if target.exists() else '(不存在)'}")
    if target.exists():
        text = _read_env(target)
        m = _BLOCK_RE.search(text)
        if m:
            print("当前 lcsc2cadence 配置块:")
            print(m.group(0).rstrip())
        else:
            print("尚未配置 (env 里没有 lcsc2cadence 块)")
