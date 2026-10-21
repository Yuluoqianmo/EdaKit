"""OLB XML 合并 —— 把新元件的 <Package> 并进已有的库 XML。

给 Capture 侧的 TCL 用：它先用 ``XMATIC_OLB2XML`` 把已有 .olb 回读成 XML，
再调本模块把新元件合进去，最后 ``XMATIC_XML2OLB`` 写回。

== 真方言（2026-10-19 从 Capture 17.2 实测得到）==

    <Lib>
      <Defn name="..."/>
      <DefaultValues> … </DefaultValues>
      <Package> <Defn name="R0603" …/> <LibPart> … </LibPart> </Package>
      <Package> <Defn name="RP2040" …/> <LibPart> … </LibPart> </Package>
    </Lib>

所以合并单位是 ``<Package>``，按它的 ``<Defn name="...">`` 去重。

== 为什么还用字符串/正则而不是 XML 解析器 ==

- 回读出来的 XML 里 `Defn` 标签满天飞，树结构本身是稳定的，但我们要做的只是
  「删掉同名 Package，插到 `</Lib>` 之前」——纯文本操作不需要理解整棵树；
- 更重要：如果上游哪天多出我们不认识的元素，树解析+重新序列化会**丢掉**它们
  （命名空间、CDATA、未知属性）。纯文本拼接则原样保留。

这两点在这个项目里都是实打实的风险，所以保守优先。
"""

from __future__ import annotations

import re
from pathlib import Path

# <Package> … </Package>（含嵌套？Package 内部没有同名嵌套，非贪婪到第一个 </Package> 即可）
_PACKAGE_RE = re.compile(r"<Package\b.*?</Package>", re.DOTALL)
# <Package ...> <Defn ... name="X" .../> —— 名字在紧跟其后的第一个 Defn 上
_PKG_NAME_RE = re.compile(
    r"<Package\b.*?<Defn\b[^>]*\bname\s*=\s*([\"'])(.*?)\1", re.DOTALL
)
# 老方言兜底
_PART_RE = re.compile(r"<\s*(?:\w+:)?Part\b.*?</\s*(?:\w+:)?Part\s*>", re.DOTALL)
_CLOSE_RE = re.compile(r"</\s*([\w:]+)\s*>\s*$", re.DOTALL)


def extract_packages(xml_text: str) -> list[str]:
    """抽出所有 ``<Package>…</Package>`` 片段。"""
    return _PACKAGE_RE.findall(xml_text)


def extract_package_names(xml_text: str) -> list[str]:
    """抽 ``<Package>`` 里 ``Defn@name`` 的值（用来去重 / 报告）。"""
    names = []
    for frag in extract_packages(xml_text):
        m = _PKG_NAME_RE.search(frag)
        if m:
            names.append(m.group(2))
    return names


def extract_parts(xml_text: str) -> list[str]:
    """兼容旧 API：返回 Package 片段；没有 Package 时退回老的 Part 片段。"""
    pkgs = extract_packages(xml_text)
    if pkgs:
        return pkgs
    return _PART_RE.findall(xml_text)


def extract_part_names(xml_text: str) -> list[str]:
    """兼容旧 API。"""
    names = extract_package_names(xml_text)
    if names:
        return names
    names = []
    for frag in _PART_RE.findall(xml_text):
        m = re.search(r'\bName\s*=\s*(["\'])(.*?)\1', frag, re.IGNORECASE | re.DOTALL)
        if m:
            names.append(m.group(2))
    return names


def _insert_before_close(result: str, frag: str) -> str:
    close = _CLOSE_RE.search(result)
    if close:
        idx = close.start()
        return result[:idx] + frag + "\n" + result[idx:]
    return result + "\n" + frag


def merge_olb_xml(base_xml: str, part_xml: str, *, replace_same_name: bool = True) -> str:
    """把 part_xml 里的元件并进 base_xml。

    base_xml 为空 → 直接返回 part_xml（相当于新建库）。
    replace_same_name → 同名元件用新的替换旧的（幂等：重复放置不会重复堆）。
    """
    if not base_xml.strip():
        return part_xml

    new_pkgs = extract_packages(part_xml)
    if new_pkgs:
        result = base_xml
        for frag in new_pkgs:
            m = _PKG_NAME_RE.search(frag)
            name = m.group(2) if m else ""

            if replace_same_name and name:
                def _drop(pkg: re.Match[str]) -> str:
                    mm = _PKG_NAME_RE.search(pkg.group(0))
                    return "" if (mm and mm.group(2) == name) else pkg.group(0)

                result = _PACKAGE_RE.sub(_drop, result)

            result = _insert_before_close(result, frag)
        return result

    # 老方言兜底（理论上用不到了，但别让历史文件把流程卡死）
    new_parts = _PART_RE.findall(part_xml)
    if not new_parts:
        return base_xml

    result = base_xml
    for frag in new_parts:
        name = ""
        m = re.search(r'\bName\s*=\s*(["\'])(.*?)\1', frag, re.IGNORECASE | re.DOTALL)
        if m:
            name = m.group(2)
        if replace_same_name and name:
            def _drop(mt: re.Match[str]) -> str:
                mm = re.search(r'\bName\s*=\s*(["\'])(.*?)\1', mt.group(0), re.DOTALL)
                return "" if (mm and mm.group(2) == name) else mt.group(0)

            result = _PART_RE.sub(_drop, result)
        result = _insert_before_close(result, frag)
    return result


def merge_files(base_path: str, part_path: str, out_path: str) -> int:
    """命令行入口用。返回合并后库里的元件数量。"""
    base = Path(base_path).read_text(encoding="utf-8") if base_path and Path(base_path).exists() else ""
    part_file = Path(part_path)
    if not part_file.exists():
        raise FileNotFoundError(f"元件 XML 不存在: {part_path}")
    part = part_file.read_text(encoding="utf-8")
    merged = merge_olb_xml(base, part)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(merged, encoding="utf-8", newline="\n")
    return len(extract_parts(merged))
