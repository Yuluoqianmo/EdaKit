"""Prepare and submit placement independent of HTTP transport."""
from dataclasses import dataclass
import logging
import hashlib
import time
from ..bridge.queue import PlaceRequest, capture_alive
from ..bridge.sessions import resolve_target
from ..symbol.naming import capture_part_name

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PreparationOptions:
    capture_only: bool = True
    download_step: bool = False


def boolean(value):
    if type(value) is bool:
        return value
    if value in ("1", "true", 1):
        return True
    if value in (None, "", "0", "false", 0):
        return False
    raise ValueError("Invalid boolean option")


class PlacementService:
    def __init__(self, stage, target_resolver=resolve_target):
        self.stage = stage
        self.target_resolver = target_resolver

    def prepare(self, component, config, options):
        return self.stage(component, config, capture_only=options.capture_only,
                          download_step=options.download_step)

    def submit(self, component, config, options, *, target="", stage_only=False,
               follow_cursor=None, x=None, y=None):
        stage_only = boolean(stage_only)
        if component.symbol is None and not stage_only:
            raise ValueError("该元件没有原理图符号，无法放置到原理图")
        config.validate()
        target = self.target_resolver(target)
        started = time.perf_counter()
        staged = self.prepare(component, config, options)
        elapsed = round((time.perf_counter() - started) * 1000, 2)
        request = PlaceRequest(cid=component.cid,
            part_name=staged.part_name or capture_part_name((component.symbol.name if component.symbol else "") or component.cid, component.cid),
            footprint=staged.footprint_name, olb_xml=str(staged.symbol_xml or ""),
            project_olb=config.project_olb, target_session=target,
            symbol_digest=hashlib.sha256(staged.symbol_xml.read_bytes()).hexdigest() if staged.symbol_xml else "",
            follow_cursor=config.place_mode == "cursor" if follow_cursor is None else follow_cursor,
            x_mil=config.place_x_mil if x is None else x,
            y_mil=config.place_y_mil if y is None else y, stage_only=boolean(stage_only))
        # Downloads/preparation may outlive a host. Recheck before publishing.
        if target:
            self.target_resolver(target)
        request.submit()
        log.info("placement request_id=%s target=%s cid=%s preparation_ms=%s preparation_reused=%s", request.seq, target, component.cid, elapsed, staged.preparation_reused)
        return {"seq": request.seq, "captureOnline": capture_alive(),
                "staged": staged.to_dict(), "preparationMs": elapsed,
                "targetSession": target, "protocolVersion": 2}
