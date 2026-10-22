"""Preview preparation shared independently of HTTP route handling."""
from functools import lru_cache
from ..render import render_symbol_svg, render_footprint_svg
from ..render.png import render_png
from ..render.scheduling import coalesced
from ..threed.preview import render_model_png
from ..threed.step import StepFetcher


class PreviewMissing(ValueError):
    pass


@coalesced
@lru_cache(maxsize=8)
def model_bytes(uuid):
    return StepFetcher().download_obj_bytes(uuid)


class PreviewService:
    def __init__(self, model_loader=model_bytes):
        self.model_loader = model_loader

    def svg(self, component, kind):
        geometry = component.symbol if kind == "symbol" else component.footprint
        if geometry is None:
            raise PreviewMissing("no_" + kind)
        if kind == "symbol":
            from ..symbol.capture_lib import normalize_capture_symbol
            return render_symbol_svg(normalize_capture_symbol(geometry))
        return render_footprint_svg(geometry)

    def png(self, component, kind, size, yaw=35, pitch=55):
        if kind == "model3d":
            if component.model3d is None:
                raise PreviewMissing("no_model3d")
            from ..threed.assembly import placement
            data = self.model_loader(component.model3d.uuid)
            return render_model_png(data, size, yaw, pitch, placement(component.model3d, data))
        return render_png(self.svg(component, kind), size)
