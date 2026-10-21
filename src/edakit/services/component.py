"""Provider-independent component loading and conversion entry points."""
import re
from .cache import Cache
from .providers import ComponentProvider
from typing import Callable


class ComponentService:
    def __init__(self, fetcher: Callable[[], ComponentProvider], parser, cache=None):
        self.fetcher, self.parser = fetcher, parser
        self.cache = cache if cache is not None else Cache(128, 3600)

    def get(self, cid):
        cid = str(cid).strip().upper()
        if not cid.startswith("C"):
            cid = "C" + cid
        if not re.fullmatch(r"C[0-9]+", cid):
            raise ValueError("无效的立创编号")
        return self.cache.get_or_load(cid, lambda: self.parser(cid, self.fetcher().get_component(cid)))
