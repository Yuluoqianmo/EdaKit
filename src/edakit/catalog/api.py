"""立创商城 API 客户端。

=== 关于这些端点 ===
以下端点是从立创商城官网前端代码 (static.lcsc.com/feassets/pc/nuxt/*.js) 里读出来的，
**非官方公开 API、无文档、无鉴权**。2026-10-16 实测可用:

  关键词搜索   POST https://wmsc.lcsc.com/ftps/wm/product/query/list
               {"keyword": "...", "currentPage": 1, "pageSize": 25}   → result.dataList[]
  分类浏览     POST https://wmsc.lcsc.com/ftps/wm/product/query/list
               {"currentPage":1,"pageSize":25,"catalogIdList":[941]} → result.dataList[]
  封装筛选     encapValueList，选项来自 /ftps/wm/product/query/param/group
  分类树/品牌  POST https://wmsc.lcsc.com/ftps/wm/search/v3/global
               {"keyword": "RP2040"}                                   → result.catalogVOS[]/brandVOS[]

注意:
  * third/catalog 是第三方供应商接口，不能替代主商城的分类查询。
  * `currentPage`/`pageSize` 是**必填**，缺了就报 405。
  * 上游会偶发返回 CloudFront 403 / 非 JSON，必须重试。
  * 端点随时可能变；`LcscUpstreamChanged` 就是在提示这个。
"""

from __future__ import annotations

import time
import json
import re
from typing import Any

import requests

from ..errors import FetchError, UpstreamChangedError
from .models import CategoryNode, Part, PriceLadder, SearchResult
from .facets import clean_params, normalize_facets
from .values import passive_value, value_catalog_ids

BASE = "https://wmsc.lcsc.com"
SEARCH_KEYWORD = "/ftps/wm/product/query/list"
SEARCH_CATALOG = "/ftps/wm/search/third/catalog"
SEARCH_GLOBAL = "/ftps/wm/search/v3/global"
CATALOG_LIST = "/ftps/wm/product/catalog/list"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class MallClient:
    def __init__(self, timeout: float = 20.0, retries: int = 4, budget=None) -> None:
        self.budget = budget
        self.timeout = timeout
        self.retries = retries
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": UA,
                "Referer": "https://www.lcsc.com/",
                "Content-Type": "application/json",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            }
        )

    # ------------------------------------------------------------------ #
    # 低层
    # ------------------------------------------------------------------ #
    def close(self):
        self.session.close()

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        url = BASE + path
        if self.budget is not None:
            from ..services.network import request_json
            return request_json(self.session, 'post', url, budget=self.budget, retries=self.retries, mall=True, payload=body)
        last: Exception | None = None
        for attempt in range(self.retries):
            try:
                r = self.session.post(url, json=body, timeout=self.timeout)
            except requests.RequestException as e:
                last = e
                time.sleep(0.4 * (attempt + 1))
                continue
            # 上游偶发 CloudFront 403 / 5xx —— 退避重试
            if r.status_code in (403, 429, 500, 502, 503, 504):
                last = FetchError(f"HTTP {r.status_code}: {path}")
                time.sleep(0.6 * (attempt + 1))
                continue
            if r.status_code != 200:
                raise FetchError(f"HTTP {r.status_code}: {path}")
            try:
                payload = r.json()
            except ValueError:
                last = UpstreamChangedError(f"返回非 JSON (可能端点已变): {path}")
                time.sleep(0.6 * (attempt + 1))
                continue
            code = payload.get("code")
            if code == 200:
                return payload.get("result") or {}
            # 405 = 请求字段不合法; 500 = 上游抽风
            if code in (500, 502, 503):
                last = FetchError(f"上游 {code}: {payload.get('msg')}")
                time.sleep(0.6 * (attempt + 1))
                continue
            raise UpstreamChangedError(
                f"接口返回 code={code} msg={payload.get('msg')} (字段或端点可能已变)"
            )
        raise FetchError(f"商城请求失败 (重试 {self.retries} 次): {last}")

    # ------------------------------------------------------------------ #
    # 搜索
    # ------------------------------------------------------------------ #
    def search_keyword(
        self,
        keyword: str,
        *,
        page: int = 1,
        page_size: int = 25,
        sort_field: str = "",
        sort_type: str = "",
        package: str = "",
        catalog_id: int = 0,
        catalog_ids: list[int] | None = None,
        params: dict[str, list[str]] | None = None,
        packages: list[str] | None = None,
        brand_ids: list[str] | None = None,
    ) -> SearchResult:
        """按关键词搜索 (型号 / 厂家 / 描述 / C 编号)。"""
        body: dict[str, Any] = {
            "keyword": keyword,
            "currentPage": max(1, page),
            "pageSize": max(1, min(page_size, 100)),
        }
        if sort_field:
            body["sortField"] = sort_field
            body["sortType"] = sort_type or "asc"
        if packages or package:
            body["encapValueList"] = packages or [package]
        if brand_ids:
            body["brandIdList"] = [int(v) for v in brand_ids]
        if params:
            body["paramNameValueMap"] = clean_params(params)
        if catalog_ids or catalog_id:
            body["catalogIdList"] = catalog_ids or [catalog_id]
        self._apply_value_filter(body)
        result = self._post(SEARCH_KEYWORD, body)
        items = result.get("dataList") or []
        return SearchResult(
            parts=[self._to_part(x) for x in items],
            total=int(result.get("totalRow") or 0),
            page=int(result.get("currPage") or page),
            page_size=int(result.get("pageRow") or page_size),
        )

    def browse_category(
        self, catalog_id: int, *, page: int = 1, page_size: int = 25, package: str = "",
        catalog_ids: list[int] | None = None, params: dict[str, list[str]] | None = None,
        packages: list[str] | None = None, brand_ids: list[str] | None = None,
    ) -> SearchResult:
        """按分类浏览商品。"""
        return self.search_keyword("", catalog_id=catalog_id, package=package,
                                   catalog_ids=catalog_ids, page=page, page_size=page_size,
                                   params=params, packages=packages, brand_ids=brand_ids)

    def package_options(self, catalog_ids: list[int], keyword: str = "") -> dict[str, Any]:
        """Upstream facets cover the category, not just the current result page."""
        # Facets require leaf wm IDs. Parent IDs silently return an empty result.
        value = passive_value(keyword, catalog_ids)
        if value and not catalog_ids:
            catalog_ids = value_catalog_ids(value[0])
        if not catalog_ids and keyword:
            if re.fullmatch(r"C\d+", keyword, re.I):
                # Exact-code dispatch may omit the category tree altogether.
                result = self.search_keyword(keyword, page_size=10)
                exact = [part for part in result.parts if part.cid.upper() == keyword.upper()]
                return {"packages": sorted({p.package for p in exact if p.package and p.package != "-"}),
                        "total": len(exact)}
            dispatch = self._post(SEARCH_GLOBAL, {"keyword": keyword})
            def leaves(nodes):
                result = []
                for node in nodes:
                    children = node.get("childCatelogs") or node.get("childCatalogs") or []
                    if children:
                        result.extend(leaves(children))
                    elif node.get("catalogId") is not None:
                        result.append(int(node["catalogId"]))
                return result
            catalog_ids = leaves(dispatch.get("catalogVOS") or [])
            if not catalog_ids:
                catalog_ids = leaves(dispatch.get("topResults") or [])
        if not catalog_ids:
            return {"packages": [], "total": 0}
        body = {
            "catalogIdList": catalog_ids, "keyword": keyword,
            "encapValueList": [], "paramNameValueMap": {},
        }
        self._apply_value_filter(body)
        result = self._post("/ftps/wm/product/query/param/group", body)
        values = sorted({str(item["name"]).strip() for item in result.get("Package") or []
                         if item.get("name") and str(item["name"]).strip() != "-"})
        return {"packages": values, "total": int(result.get("totalCount") or 0)}

    def facet_options(self, catalog_ids: list[int], keyword: str = "") -> dict[str, Any]:
        """Stable option universe: category + keyword/value, independent of selections.

        This deliberately avoids claiming that option counts are fully cross-filtered.
        Keeping the universe stable also lets users add OR values without self-locking.
        """
        value = passive_value(keyword, catalog_ids)
        if value and not catalog_ids:
            catalog_ids = value_catalog_ids(value[0])
        if not catalog_ids and keyword:
            if re.fullmatch(r"C\d+", keyword, re.I):
                result = self.search_keyword(keyword, page_size=10)
                exact = [p for p in result.parts if p.cid.upper() == keyword.upper()]
                packages = sorted({p.package for p in exact if p.package and p.package != "-"})
                return {"facets": normalize_facets({"Package": [{"name": p} for p in packages]}),
                        "total": len(exact), "scope": "category-keyword"}
            dispatch = self._post(SEARCH_GLOBAL, {"keyword": keyword})
            def leaves(nodes):
                ids = []
                for node in nodes:
                    children = node.get("childCatelogs") or node.get("childCatalogs") or []
                    if children:
                        ids.extend(leaves(children))
                    elif node.get("catalogId") is not None:
                        ids.append(int(node["catalogId"]))
                return ids
            catalog_ids = leaves(dispatch.get("catalogVOS") or dispatch.get("topResults") or [])
        if not catalog_ids:
            return {"facets": [], "total": 0, "scope": "category-keyword"}
        body = {"catalogIdList": catalog_ids, "keyword": keyword,
                "encapValueList": [], "paramNameValueMap": {}}
        self._apply_value_filter(body)
        raw = self._post("/ftps/wm/product/query/param/group", body)
        return {"facets": normalize_facets(raw, catalog_ids), "total": int(raw.get("totalCount") or 0),
                "scope": "category-keyword"}

    @staticmethod
    def _apply_value_filter(body: dict[str, Any]) -> None:
        value = passive_value(body.get("keyword", ""), body.get("catalogIdList") or [])
        if value:
            name, label = value
            # Clear the literal keyword too: leaving '4.7K' would still exclude
            # products whose model/description does not contain that substring.
            body["keyword"] = ""
            # The upstream stores zero-ohm jumpers under both equivalent labels.
            labels = ["0Ω", "0mΩ"] if (name, label) == ("Resistance", "0Ω") else [label]
            existing = body.setdefault("paramNameValueMap", {})
            if name in existing and not set(existing[name]).issubset(set(labels)):
                raise ValueError("关键词数值与所选参数冲突，请清空关键词或该数值筛选后重试")
            # An explicit 0Ω/0mΩ option narrows the equivalent zero-ohm group.
            existing[name] = existing.get(name) or labels
            if not body.get("catalogIdList"):
                body["catalogIdList"] = value_catalog_ids(name)

    def product_detail(self, cid: str) -> Part:
        # Exact C-code lookup returns metadata even if no EasyEDA CAD exists.
        result = self.search_keyword(cid, page_size=10)
        for part in result.parts:
            if part.cid.upper() == cid.upper():
                if part.product_id:
                    try:
                        response = self.session.get(
                            f"https://item.szlcsc.com/{int(part.product_id)}.html",
                            timeout=min(self.timeout, 8),
                        )
                        if response.status_code == 200:
                            self._enrich_product_page(part, response.text)
                    except (requests.RequestException, ValueError, TypeError, KeyError):
                        # Keep the original metadata if the public page is unavailable.
                        pass
                return part
        raise FetchError(f"商城未找到 {cid} 的商品资料")

    @staticmethod
    def _enrich_product_page(part: Part, html: str) -> None:
        match = re.search(r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
        if not match:
            return
        web = json.loads(match.group(1))["props"]["pageProps"]["webData"]
        record = web.get("productRecord") or {}
        # The two sites do not share every record; never borrow another part's PDF.
        if record.get("productCode") != part.cid:
            return
        part.package = record.get("encapsulationModel") or part.package
        part.category = (web.get("currentCatalog") or {}).get("catalogName") or part.category
        pdf = (web.get("pdfFileDetailVO") or {}).get("fileUrl") or ""
        if not pdf:
            for group in record.get("fileTypeVOList") or []:
                # Exclude RoHS/compliance certificates: these are not datasheets.
                if group.get("fileType") == "pdf_property":
                    pdf = next((f.get("fileUrl") for f in group.get("detailVOList") or [] if f.get("fileUrl")), "")
                    break
        if pdf.startswith("/") and not pdf.startswith("//"):
            pdf = "https://atta.szlcsc.com" + pdf
        if pdf.startswith("//"):
            pdf = "https:" + pdf
        if pdf.startswith(("https://", "http://")):
            part.datasheet_url = pdf

    def category_tree(self) -> list[CategoryNode]:
        """完整的商城分类树 (53 个一级分类 / 约 1200 个节点)。

        POST /ftps/wm/product/catalog/list {"parentId": 0} → result.catalogList[]
        这棵树很大且基本不变，调用方应缓存。
        """
        result = self._post(CATALOG_LIST, {"parentId": 0})
        nodes: list[CategoryNode] = []
        for raw in result.get("catalogList") or []:
            node = self._to_category(raw)
            if node:
                nodes.append(node)
        return nodes

    def suggest(self, keyword: str) -> tuple[list[Part], list[CategoryNode], list[dict]]:
        """搜索联想: 精确匹配商品 + 相关分类 + 相关品牌。

        这是 v3/global 的直接封装，用于搜索框下拉提示。
        """
        result = self._post(SEARCH_GLOBAL, {"keyword": keyword})
        exact = [self._to_part(x) for x in (result.get("exactMatchResult") or [])]
        cats: list[CategoryNode] = []
        for raw in result.get("catalogVOS") or []:
            node = self._to_category(raw)
            if node:
                cats.append(node)
        brands = [
            {
                "id": b.get("brandId"),
                "name": b.get("brandNameEn") or b.get("brandName"),
                "num": b.get("productNum"),
            }
            for b in (result.get("brandVOS") or [])
        ]
        return exact, cats, brands

    # ------------------------------------------------------------------ #
    # 归一化
    # ------------------------------------------------------------------ #
    @staticmethod
    def _to_part(raw: dict[str, Any]) -> Part:
        prices: list[PriceLadder] = []
        for p in raw.get("productPriceList") or []:
            try:
                prices.append(
                    PriceLadder(
                        qty=int(p.get("ladder") or 1),
                        price=float(
                            p.get("currencyPrice") or p.get("productPrice") or p.get("usdPrice") or 0
                        ),
                        currency=p.get("currencySymbol") or "$",
                    )
                )
            except (TypeError, ValueError):
                continue

        params: dict[str, str] = {}
        for p in raw.get("paramVOList") or []:
            name = p.get("paramName") or p.get("paramNameEn")
            val = p.get("paramValue") or p.get("paramValueEn")
            if name and val:
                params[str(name)] = str(val)

        path = [
            raw.get("firstWmCatalogNameEn"),
            raw.get("secondWmCatalogNameEn"),
            raw.get("thirdWmCatalogNameEn"),
        ]
        path = [x for x in path if x]

        code = (raw.get("productCode") or "").strip()
        return Part(
            cid=code,
            model=(raw.get("productModel") or "").strip(),
            brand=(raw.get("brandNameEn") or raw.get("lcOrderBrandNameEn") or "").strip(),
            package=(raw.get("encapStandard") or "").strip(),
            description=(raw.get("productIntroEn") or raw.get("productDescEn") or "").strip(),
            stock=int(raw.get("stockNumber") or 0),
            category=(raw.get("catalogName") or raw.get("catalogNameEn") or raw.get("wmCatalogNameEn") or "").strip(),
            category_path=path,
            catalog_id=(
                raw.get("wmCatalogId")
                or raw.get("thirdWmCatalogId")
                or raw.get("catalogId")
            ),
            image_url=raw.get("productImageUrl") or raw.get("productImageUrlBig") or "",
            datasheet_url=raw.get("pdfUrl") or raw.get("pdfLinkUrl") or "",
            prices=prices,
            params=params,
            product_id=raw.get("productId"),
            weight_g=float(raw.get("weight") or 0),
            is_basic=bool(raw.get("isBasic") or raw.get("isBasicPart")),
            is_preferred=bool(raw.get("isPreferred")),
            url=raw.get("url") or (f"https://www.lcsc.com/product-detail/{code}.html" if code else ""),
            raw=raw,
        )

    @staticmethod
    def _to_category(raw: dict[str, Any]) -> CategoryNode | None:
        cid = raw.get("catalogId")
        if cid is None:
            return None
        node = CategoryNode(
            catalog_id=int(cid),
            name=(raw.get("catalogName") or raw.get("catalogNameEn") or "").strip(),
            parent_id=raw.get("parentId"),
            product_num=int(raw.get("productNum") or 0),
        )
        for child in raw.get("childCatelogs") or raw.get("childCatalogs") or []:
            sub = MallClient._to_category(child)
            if sub:
                node.children.append(sub)
        return node
