"""工具统一异常。每个失败都要能被上层区分，绝不返回半个对象。"""


class LcscError(Exception):
    """所有本工具异常的基类。"""


class FetchError(LcscError):
    """网络取数失败 (超时 / HTTP 非 200 / 上游结构变化)。"""


class UpstreamChangedError(FetchError):
    """上游返回了非预期结构 —— 大概率是免鉴权端点被改了。"""


class ParseError(LcscError):
    """EasyEDA shape 解析失败。"""


class UnsupportedGeometryError(LcscError):
    """遇到了当前无法安全转换的几何 (例如带内孔的铜焊盘)。

    故意抛出而不是静默填实 —— 宁可让用户看到失败，也不要产出丢了几何的库。
    """


class DeployError(LcscError):
    """部署到 Cadence 安装树失败。"""
