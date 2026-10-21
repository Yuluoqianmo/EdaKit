"""生成上机验证用的 OLB XML（v11：顶/底编号收进引脚长度范围（不再探出取景））。

用法（在项目根目录）：
    python tools/gen_verify_xmls.py <samples_json_dir> <outputs_dir>

* RP2040_v11.olb.xml —— 57 脚：57 个名字 + 46 个编号全部 CommentText 自绘
  （顶/底 14 个竖排，右侧 32 个横排在端点外）
* R0603_v11.olb.xml  —— 回归件（不应有任何 CommentText，编号开关全 1）
* 不再有顶部留白占位物：v9/v10 已证伪（取景不看自绘图元）。

v5 的 TEXT_PROBE 已经完成了标定使命，不再生成。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lcsc2cadence.easyeda.parse import parse_component
from lcsc2cadence.symbol.capture_lib import generate_lib_xml


def main(data_dir: str, out_dir: str) -> None:
    data = Path(data_dir)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    rp = parse_component(
        "C2040", json.loads((data / "C2040.json").read_text(encoding="utf-8"))
    )
    fp = rp.footprint.name if rp.footprint else "RP2040"
    (out / "RP2040_v11.olb.xml").write_text(
        generate_lib_xml(
            rp.symbol,
            lib_path="D:/cadence/lcsc_rp2040_v11.olb",
            package_name=fp,
            footprint=fp,
            refdes_prefix="U",
        ),
        encoding="utf-8",
    )

    r = parse_component(
        "C25804", json.loads((data / "C25804.json").read_text(encoding="utf-8"))
    )
    (out / "R0603_v11.olb.xml").write_text(
        generate_lib_xml(
            r.symbol,
            lib_path="D:/cadence/lcsc_r0603_v11.olb",
            package_name="R0603",
            footprint="R0603",
            refdes_prefix="R",
        ),
        encoding="utf-8",
    )

    for name in ("RP2040_v11.olb.xml", "R0603_v11.olb.xml"):
        p = out / name
        print(f"{name}: {p.stat().st_size} bytes")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
