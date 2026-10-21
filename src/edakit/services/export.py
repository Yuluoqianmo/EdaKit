"""Use one conversion pipeline for installed staging and standalone bundles."""
from pathlib import Path
from ..config import Config
from ..pipeline import stage_component
from ..storage import atomic_write
from ..symbol.tcl import generate_capture_run_tcl, generate_place_tcl


class ExportService:
    def __init__(self, stage=stage_component):
        self.stage = stage

    def bundle(self, component, directory: Path, *, calib="easyeda2kicad", download_step=False, dll=""):
        # Standalone output must not adopt or alter the installed library settings.
        cfg = Config(footprint_lib=str(directory), calib=calib)
        staged = self.stage(component, cfg, download_step=download_step, output_dir=directory)
        work = staged.workdir
        cid = component.cid
        atomic_write(work / "capture_run.tcl", generate_capture_run_tcl(
            dll_path=dll, xml_path=str(staged.symbol_xml or work / f"{cid}.olb.xml"),
            olb_path=str(work / f"{cid}.olb"), roundtrip_path=str(work / f"{cid}.roundtrip.xml")))
        atomic_write(work / "capture_place.tcl", generate_place_tcl(
            olb_path=str(work / f"{cid}.olb"), part_name=staged.part_name or cid,
            props={"PCB Footprint": staged.footprint_name} if component.footprint else {}))
        # Preserve the standalone map alias used by existing CLI consumers.
        if component.model3d:
            from ..threed.mapping import build_map_xml, calibrate
            atomic_write(work / "part.map.xml", build_map_xml(
                calibrate(component.model3d, mode=calib), package_name=staged.footprint_name))
        return staged
