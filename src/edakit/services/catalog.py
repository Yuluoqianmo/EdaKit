"""Catalog use cases; data provider factories are injectable."""
from ..catalog.scope import electronic_categories
from .cache import Cache
from .providers import CatalogProvider
from typing import Callable


class CatalogService:
    def __init__(self, provider: Callable[[], CatalogProvider], serializer):
        self.provider, self.serialize = provider, serializer
        self.categories = Cache(1, 3600)
        self.products = Cache(128, 600)
        self.packages = Cache(32, 600)
        self.facets = Cache(32, 600)

    def category_data(self):
        return self.categories.get_or_load("tree", lambda: [node.to_dict() for node in electronic_categories(self.provider().category_tree())])

    def leaf_ids(self, cat):
        result = []
        def visit(nodes, inside=False):
            for node in nodes:
                matched = inside or node["id"] == cat
                if node["children"]:
                    visit(node["children"], matched)
                elif matched:
                    result.append(node["id"])
        visit(self.category_data())
        if not result:
            raise ValueError("分类已更新，请刷新商城后重选")
        return sorted(set(result))

    def search(self, keyword, *, page, size, cat=0, package="", filters=None):
        opts = dict(filters or {})
        if package:
            opts["package"] = package
        if cat:
            opts["catalog_ids"] = self.leaf_ids(cat)
        return self.provider().search_keyword(keyword, page=page, page_size=size, **opts)

    def browse(self, cat, *, page, size, package="", filters=None):
        opts = dict(filters or {})
        if package:
            opts["package"] = package
        return self.provider().browse_category(cat, page=page, page_size=size,
                                               catalog_ids=self.leaf_ids(cat), **opts)

    def options(self, kind, cat, keyword):
        cache = self.packages if kind == "packages" else self.facets
        def load():
            provider = self.provider()
            method = provider.package_options if kind == "packages" else provider.facet_options
            return method(self.leaf_ids(cat) if cat else [], keyword)
        return cache.get_or_load((cat, keyword), load)

    def product(self, cid):
        return self.products.get_or_load(cid, lambda: self.serialize(self.provider().product_detail(cid)))
