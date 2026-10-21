"""PNG previews for Capture's legacy embedded browser, from the same SVG geometry."""
from functools import lru_cache

import resvg_py
from .scheduling import coalesced, bounded_render


@coalesced
@lru_cache(maxsize=24)
@bounded_render
def render_png(svg: str, size: int = 1024) -> bytes:
    """Cache bounded preview sizes; never upscale a small bitmap on the server."""
    if size not in (512, 1024, 2048, 4096):
        raise ValueError("preview size must be 512, 1024, 2048 or 4096")
    return resvg_py.svg_to_bytes(svg_string=svg, width=size, height=size,
                                 background="#f7fafc", font_family="Arial")
