"""edakit — 立创(EasyEDA/LCSC) 元件库 → Cadence 一键放置工具.

模块划分:
    fetch       取数 (EasyEDA 免鉴权端点)
    easyeda     EasyEDA 格式解析 (shape / 单位 / 数据模型)
    symbol      符号 → Capture (OLB XML + TCL 插件)
    footprint   封装 → Allegro (SKILL .il)
    threed      3D → STEP 下载 + 映射 (.map / 3D Mapper XML)
    install     部署到 Cadence 安装树
"""

__version__ = "0.1.6"
