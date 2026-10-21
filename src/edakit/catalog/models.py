"""商城数据模型。

字段名对应立创商城 (wmsc) 接口的原始字段，这里做一层统一，前端只认这里的名字。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .zh import category_zh


@dataclass
class PriceLadder:
    qty: int = 1
    price: float = 0.0
    currency: str = "$"


@dataclass
class Part:
    """商城里的一个元件 (一条搜索结果)。"""

    cid: str = ""  # 立创编号 C2040
    model: str = ""  # 型号 RP2040
    brand: str = ""  # 厂家 Raspberry Pi
    package: str = ""  # 封装 LQFN-56(7x7)
    description: str = ""  # 简介
    stock: int = 0
    category: str = ""  # 所属分类名
    category_path: list[str] = field(default_factory=list)  # 分类路径
    catalog_id: int | None = None  # 用于分类浏览的 id
    image_url: str = ""
    datasheet_url: str = ""
    prices: list[PriceLadder] = field(default_factory=list)
    params: dict[str, str] = field(default_factory=dict)  # 参数表
    product_id: int | None = None
    weight_g: float = 0.0
    is_basic: bool = False
    is_preferred: bool = False
    url: str = ""  # 商城页面链接
    # 本工具附加: 是否已确认有 EasyEDA 符号/封装 (None = 未知)
    eco_has_cad: bool | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def price_str(self) -> str:
        if not self.prices:
            return "-"
        p = self.prices[0]
        return f"{p.currency}{p.price:g}"


@dataclass
class SearchResult:
    parts: list[Part] = field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 25

    @property
    def total_pages(self) -> int:
        if self.page_size <= 0:
            return 1
        return max(1, (self.total + self.page_size - 1) // self.page_size)


@dataclass
class CategoryNode:
    """分类树节点。"""

    catalog_id: int
    name: str
    parent_id: int | None = None
    product_num: int = 0
    children: list["CategoryNode"] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.catalog_id,
            "name": category_zh(self.name),
            "originalName": self.name,
            "parentId": self.parent_id,
            "productNum": self.product_num,
            "children": [c.to_dict() for c in self.children],
        }
