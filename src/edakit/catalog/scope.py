"""按中文商城电子类目组织导航，映射到国际站可查询的原始分类 ID。

名称和分组参照 https://www.szlcsc.com/catalog.html（2026-10-20）。
中文站与国际站 ID 不同，不能将中文站 ID 直接提交到 wmsc。
筛选仍使用国际站的真实分支 ID，保留各分支的子分类。
"""
from dataclasses import replace
from .models import CategoryNode

# (真实 wmsc 分支 ID, 中文商城对应分类名称)。部分合并类目按接口实际范围标明。
ELECTRONIC_GROUPS = (
    (495, '电容'), (501, '电阻'), (10, '连接器'), (185, '二极管'),
    (263, '电源管理'), (28, '光电器件 / 显示屏'),
    (498, '电感 / 线圈'), (40, '变压器'), (11, '开发板 / 开发工具'),
    (262, '存储器'), (37, '传感器'), (34, '继电器'),
    (13, '嵌入式计算机 / 功能板卡'),
    (258, '单片机 / 微控制器 / 可编程逻辑'), (261, '逻辑器件'),
    (256, '时钟和定时'), (257, 'ADC / DAC / 数据转换'), (35, '射频芯片 / 无线模块'),
    (260, '放大器 / 比较器 / 线性器件'), (259, '通信接口芯片'),
    (1420, '三极管 / MOS管 / 晶体管'), (191, '结型场效应管（JFET）'),
    (187, '晶闸管'), (186, '功率驱动模块'), (184, '电流调节二极管 / 晶体管'),
    (496, '晶体 / 振荡器 / 谐振器'), (3, '音频器件'),
    (8, 'TVS / 保险丝 / 板级保护'), (38, '按键 / 开关'),
    (5, '连接线 / 线缆组件'), (6, '电线电缆'),
    (32, '电源模块'), (18, '光耦 / 信号隔离器件'),
    (497, '磁珠 / 滤波器 / EMI优化'), (4, '电池 / 电池配件'),
    (264, '其他专用集成电路'), (255, '音频专用芯片'),
)
ELECTRONIC_ROOT_IDS = frozenset(cid for cid, _ in ELECTRONIC_GROUPS)


def electronic_categories(nodes: list[CategoryNode]) -> list[CategoryNode]:
    index = {}
    def visit(items):
        for node in items:
            index[node.catalog_id] = node
            visit(node.children)
    visit(nodes)
    return [replace(index[cid], name=name) for cid, name in ELECTRONIC_GROUPS if cid in index]
