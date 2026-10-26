from __future__ import annotations

import argparse
import base64
import csv
import html
from html.parser import HTMLParser
import json
import math
import statistics
import mimetypes
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zipfile import ZipFile

# Native integration uses IPC geometry only; optional PDF rendering is not bundled.
fitz = None


DEFAULT_BOM_ALIASES = {
    "description": "description",
    "comment": "description",
    "comments": "description",
    "描述": "description",
    "器件描述": "description",
    "元件描述": "description",
    "物料描述": "description",
    "名称": "description",
    "value": "value",
    "component value": "value",
    "值": "value",
    "数值": "value",
    "标称值": "value",
    "参数": "value",
    "规格": "value",
    "规格型号": "value",
    "型号": "value",
    "part": "part",
    "part number": "part",
    "pn": "part",
    "料号": "part",
    "物料号": "part",
    "物料编码": "part",
    "内部料号": "part",
    "reference": "references",
    "references": "references",
    "refdes": "references",
    "ref": "references",
    "designator": "references",
    "位号": "references",
    "元件位号": "references",
    "器件位号": "references",
    "pcb footprint": "footprint",
    "footprint": "footprint",
    "package": "footprint",
    "comp package": "footprint",
    "封装": "footprint",
    "封装名称": "footprint",
    "封装型号": "footprint",
    "quantity": "quantity",
    "qty": "quantity",
    "数量": "quantity",
    "用量": "quantity",
    "manufacturer": "manufacturer",
    "mfr": "manufacturer",
    "厂家": "manufacturer",
    "制造商": "manufacturer",
    "供应商": "manufacturer",
    "manufacturer_pn": "manufacturer_pn",
    "manufacturer pn": "manufacturer_pn",
    "manufacturer part number": "manufacturer_pn",
    "mfr pn": "manufacturer_pn",
    "mfr part number": "manufacturer_pn",
    "mpn": "manufacturer_pn",
    "厂家料号": "manufacturer_pn",
    "制造商料号": "manufacturer_pn",
    "制造商型号": "manufacturer_pn",
    "订购型号": "manufacturer_pn",
}

DEFAULT_PLACEMENT_ALIASES = {
    "refdes": "refdes",
    "reference": "refdes",
    "ref": "refdes",
    "designator": "refdes",
    "refdes ": "refdes",
    "x": "x",
    "center-x": "x",
    "location x": "x",
    "sym x": "x",
    "sym_x": "x",
    "y": "y",
    "center-y": "y",
    "location y": "y",
    "sym y": "y",
    "sym_y": "y",
    "rotation": "rotation",
    "rot": "rotation",
    "angle": "rotation",
    "sym rotate": "rotation",
    "sym_rotate": "rotation",
    "side": "side",
    "layer": "side",
    "mirror": "side",
    "sym mirror": "side",
    "sym_mirror": "side",
}

REF_RANGE_RE = re.compile(r"^([A-Za-z]+)(\d+)-([A-Za-z]+)?(\d+)$")
TOOL_VERSION = "v1.2.0"


def resolve_runtime_file(file_name: str) -> Path:
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        exe_candidate = exe_dir / file_name
        if exe_candidate.exists():
            return exe_candidate
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            bundled_candidate = Path(meipass) / file_name
            if bundled_candidate.exists():
                return bundled_candidate
    script_dir = Path(__file__).resolve().parent
    external_candidate = script_dir / file_name
    if external_candidate.exists():
        return external_candidate
    return external_candidate


FIELD_MAPPING_PATH = resolve_runtime_file("field_mapping.json")


@dataclass
class BoardImage:
    side: str
    src: str


@dataclass
class BoardProfile:
    points: list[dict[str, float]]


@dataclass
class PackageGeometry:
    name: str
    pickup_x: float
    pickup_y: float
    bbox: dict[str, float] | None
    outline_polygons: list[list[dict[str, float]]]
    drawing_shapes: list[dict]
    pad_shapes: list[dict]


@dataclass
class UnitDetection:
    internal_unit: str
    source_unit: str
    scale_to_internal: float
    reason: str


@dataclass
class RuntimeOptions:
    bom: Path | None
    placement: Path | None
    ipc: Path | None
    board_top: Path | None
    board_bottom: Path | None
    board_top_pdf: Path | None
    board_bottom_pdf: Path | None
    title: str
    project: str
    author: str
    version: str
    created_at: str
    placement_unit: str
    include_test_points: bool
    testpoint_rules: dict
    image_placement: dict
    output: Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a single-file interactive BOM HTML.")
    parser.add_argument("--config", type=Path, help="Optional JSON config file for project defaults.")
    parser.add_argument("--bom", type=Path, help="Cadence BOM export file (CSV/TSV/TXT).")
    parser.add_argument("--placement", type=Path, help="Component placement file (CSV/TSV/TXT).")
    parser.add_argument("--ipc", type=Path, help="Optional IPC-2581 XML for board profile and component fallback.")
    parser.add_argument("--board-top-pdf", type=Path, help="Optional top assembly PDF.")
    parser.add_argument("--board-bottom-pdf", type=Path, help="Optional bottom assembly PDF.")
    parser.add_argument(
        "--placement-unit",
        choices=["auto", "mm", "mil"],
        default="auto",
        help="Placement coordinate unit. Default auto-detect.",
    )
    parser.add_argument(
        "--include-test-points",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Keep test points in the generated BOM. Default is to auto-exclude them.",
    )
    parser.add_argument("--board-top", type=Path, help="Optional board top image (PNG/JPG/SVG).")
    parser.add_argument("--board-bottom", type=Path, help="Optional board bottom image (PNG/JPG/SVG).")
    parser.add_argument("--title", default="Cadence Interactive BOM", help="Display title.")
    parser.add_argument("--project", default="", help="Project identifier for local progress cache.")
    parser.add_argument("--author", default="", help="Author name shown in page header.")
    parser.add_argument("--version", default="", help="Version shown in page header.")
    parser.add_argument("--created-at", default="", help="Created time shown in page header.")
    parser.add_argument("--output", default=Path("interactive_bom.html"), type=Path, help="Output HTML file.")
    return parser.parse_args()


def normalize_header(value: str) -> str:
    return " ".join(value.strip().lower().replace("_", " ").split())


def load_external_field_mappings(path: Path) -> tuple[dict[str, str], dict[str, str]]:
    bom_aliases = dict(DEFAULT_BOM_ALIASES)
    placement_aliases = dict(DEFAULT_PLACEMENT_ALIASES)
    if not path.exists():
        return bom_aliases, placement_aliases
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return bom_aliases, placement_aliases
    external_bom = raw.get("bom_aliases", {})
    if isinstance(external_bom, dict):
        for key, value in external_bom.items():
            if key and value:
                bom_aliases[normalize_header(str(key))] = str(value).strip()
    external_placement = raw.get("placement_aliases", {})
    if isinstance(external_placement, dict):
        for key, value in external_placement.items():
            if key and value:
                placement_aliases[normalize_header(str(key))] = str(value).strip()
    return bom_aliases, placement_aliases


BOM_ALIASES, PLACEMENT_ALIASES = load_external_field_mappings(FIELD_MAPPING_PATH)


def load_config(path: Path | None) -> tuple[dict, Path | None]:
    if not path:
        return {}, None
    config_path = path.expanduser().resolve()
    return json.loads(config_path.read_text(encoding="utf-8")), config_path.parent


def resolve_path(candidate: str | None, base_dir: Path | None) -> Path | None:
    if not candidate:
        return None
    path = Path(candidate)
    if not path.is_absolute() and base_dir is not None:
        path = (base_dir / path).resolve()
    return path


def resolve_runtime_options(args: argparse.Namespace) -> RuntimeOptions:
    config, config_dir = load_config(args.config)
    bom = args.bom or resolve_path(config.get("bom"), config_dir)
    board_top = args.board_top or resolve_path(config.get("boardTop"), config_dir)
    board_bottom = args.board_bottom or resolve_path(config.get("boardBottom"), config_dir)
    board_top_pdf = args.board_top_pdf or resolve_path(config.get("boardTopPdf"), config_dir)
    board_bottom_pdf = args.board_bottom_pdf or resolve_path(config.get("boardBottomPdf"), config_dir)
    title = args.title if args.title != "Cadence Interactive BOM" else config.get("title", args.title)
    project = args.project or config.get("project", title)
    author = args.author or config.get("author", "")
    version = args.version or config.get("version", "")
    created_at = args.created_at or config.get("createdAt", "")
    if not created_at:
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    placement_unit = args.placement_unit if args.placement_unit != "auto" else config.get("placementUnit", "auto")
    output = args.output
    if args.output == Path("interactive_bom.html"):
        configured_output = resolve_path(config.get("output"), config_dir)
        if configured_output is not None:
            output = configured_output
    include_test_points = args.include_test_points
    if include_test_points is None:
        include_test_points = bool(config.get("includeTestPoints", False))
    testpoint_rules = config.get("testPointRules", {})
    image_placement = config.get("imagePlacement", {})
    return RuntimeOptions(
        bom=bom,
        placement=args.placement or resolve_path(config.get("placement"), config_dir),
        ipc=args.ipc or resolve_path(config.get("ipc"), config_dir),
        board_top=board_top,
        board_bottom=board_bottom,
        board_top_pdf=board_top_pdf,
        board_bottom_pdf=board_bottom_pdf,
        title=title,
        project=project,
        author=author,
        version=version,
        created_at=created_at,
        placement_unit=placement_unit,
        include_test_points=bool(include_test_points),
        testpoint_rules=testpoint_rules,
        image_placement=image_placement,
        output=output,
    )


def validate_runtime_options(options: RuntimeOptions) -> list[str]:
    issues: list[str] = []
    if not options.bom:
        issues.append("必须选择 BOM 文件。")
    elif not options.bom.exists():
        issues.append(f"BOM 文件不存在：{options.bom}")
    if options.placement and not options.placement.exists():
        issues.append(f"Placement 文件不存在：{options.placement}")
    if options.ipc and not options.ipc.exists():
        issues.append(f"IPC 文件不存在：{options.ipc}")
    if options.board_top and not options.board_top.exists():
        issues.append(f"顶层板图不存在：{options.board_top}")
    if options.board_bottom and not options.board_bottom.exists():
        issues.append(f"底层板图不存在：{options.board_bottom}")
    if options.board_top_pdf and not options.board_top_pdf.exists():
        issues.append(f"顶层 PDF 不存在：{options.board_top_pdf}")
    if options.board_bottom_pdf and not options.board_bottom_pdf.exists():
        issues.append(f"底层 PDF 不存在：{options.board_bottom_pdf}")
    if not options.placement and not options.ipc:
        issues.append("必须至少提供 placement 或 IPC-2581 其中一种坐标来源。")
    if options.output:
        try:
            options.output.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            issues.append(f"输出目录不可写：{options.output.parent} ({exc})")
    return issues


def detect_dialect(path: Path) -> csv.Dialect:
    sample = path.read_text(encoding="utf-8-sig", errors="ignore")[:4096]
    try:
        return csv.Sniffer().sniff(sample, delimiters=",\t;")
    except csv.Error:
        class Fallback(csv.Dialect):
            delimiter = "\t" if "\t" in sample else ","
            quotechar = '"'
            doublequote = True
            skipinitialspace = False
            lineterminator = "\n"
            quoting = csv.QUOTE_MINIMAL

        return Fallback


def get_xlsx_shared_strings(archive: ZipFile) -> list[str]:
    shared: list[str] = []
    if "xl/sharedStrings.xml" not in archive.namelist():
        return shared
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    for item in root.findall(f"{ns}si"):
        texts = [node.text or "" for node in item.iter(f"{ns}t")]
        shared.append("".join(texts))
    return shared


def get_xlsx_first_sheet_rows(path: Path) -> list[list[str]]:
    ns_main = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    ns_rel = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
    with ZipFile(path) as archive:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        first_sheet = workbook.find(f"{ns_main}sheets/{ns_main}sheet")
        if first_sheet is None:
            return []
        rel_id = first_sheet.attrib.get(f"{ns_rel}id")
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        sheet_target = None
        for rel in rels:
            if rel.attrib.get("Id") == rel_id:
                sheet_target = rel.attrib.get("Target")
                break
        if not sheet_target:
            return []
        shared = get_xlsx_shared_strings(archive)
        worksheet = ET.fromstring(archive.read(f"xl/{sheet_target}"))
        rows: list[list[str]] = []
        for row in worksheet.iter(f"{ns_main}row"):
            values: list[str] = []
            for cell in row.findall(f"{ns_main}c"):
                ref = cell.attrib.get("r", "")
                col_letters = "".join(ch for ch in ref if ch.isalpha())
                col_index = 0
                for ch in col_letters:
                    col_index = col_index * 26 + (ord(ch.upper()) - ord("A") + 1)
                if col_index > 0:
                    while len(values) < col_index - 1:
                        values.append("")
                cell_type = cell.attrib.get("t")
                inline_text = cell.find(f"{ns_main}is/{ns_main}t")
                raw_value = cell.find(f"{ns_main}v")
                if inline_text is not None:
                    values.append((inline_text.text or "").strip())
                elif raw_value is None:
                    values.append("")
                elif cell_type == "s":
                    values.append(shared[int(raw_value.text)] if raw_value.text else "")
                else:
                    values.append((raw_value.text or "").strip())
            rows.append(values)
        return rows


def detect_header_index(rows: list[list[str]], aliases: dict[str, str]) -> int:
    required = set(aliases.values())
    for idx, row in enumerate(rows):
        mapped = {aliases.get(normalize_header(str(cell))) for cell in row if str(cell).strip()}
        if {"description", "references", "quantity"}.issubset(mapped):
            return idx
        if {"refdes", "x", "y"}.issubset(mapped):
            return idx
        if required.intersection(mapped) and len(mapped) >= 3:
            return idx
    return 0


def read_xlsx_table(path: Path, aliases: dict[str, str]) -> list[dict[str, str]]:
    rows = get_xlsx_first_sheet_rows(path)
    if not rows:
        return []
    header_index = detect_header_index(rows, aliases)
    header = [str(cell).strip() for cell in rows[header_index]]
    data_rows = rows[header_index + 1 :]
    records: list[dict[str, str]] = []
    header_len = len(header)
    for row in data_rows:
        padded = row + [""] * (header_len - len(row))
        record = {header[i]: str(padded[i]).strip() for i in range(header_len) if i < len(padded) and header[i]}
        if any(record.values()) and not all(set(value) <= {"_"} for value in record.values() if value):
            records.append(record)
    return records


def read_table(path: Path) -> list[dict[str, str]]:
    if path.suffix.lower() == ".xlsx":
        return read_xlsx_table(path, BOM_ALIASES)
    dialect = detect_dialect(path)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, dialect=dialect)
        rows: list[dict[str, str]] = []
        for row in reader:
            if not row:
                continue
            cleaned = {str(key).strip(): (value or "").strip() for key, value in row.items() if key}
            if any(cleaned.values()):
                rows.append(cleaned)
        return rows


def inspect_bom_headers(path: Path) -> dict:
    if path.suffix.lower() == ".xlsx":
        rows = get_xlsx_first_sheet_rows(path)
        if not rows:
            return {"headers": [], "mapped": {}}
        header_index = detect_header_index(rows, BOM_ALIASES)
        headers = [str(cell).strip() for cell in rows[header_index] if str(cell).strip()]
    else:
        dialect = detect_dialect(path)
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, dialect=dialect)
            headers = [str(field).strip() for field in (reader.fieldnames or []) if str(field).strip()]
    mapped = {}
    for header in headers:
        canonical = BOM_ALIASES.get(normalize_header(header))
        if canonical:
            mapped[header] = canonical
    return {"headers": headers, "mapped": mapped}


def remap_row(row: dict[str, str], aliases: dict[str, str]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for key, value in row.items():
        mapped = aliases.get(normalize_header(key))
        if mapped and mapped not in normalized:
            normalized[mapped] = value.strip()
    return normalized


def parse_quantity(raw: str, default: int) -> int:
    value = raw.strip()
    if not value:
        return default
    try:
        return int(float(value))
    except ValueError:
        return default


def normalize_refdes(value: str) -> str:
    return value.strip().upper().replace(" ", "")


def expand_ref_token(token: str) -> list[str]:
    token = normalize_refdes(token)
    if not token:
        return []
    match = REF_RANGE_RE.match(token)
    if not match:
        return [token]
    prefix1, start_str, prefix2, end_str = match.groups()
    prefix2 = prefix2 or prefix1
    if prefix1 != prefix2:
        return [token]
    start = int(start_str)
    end = int(end_str)
    if end < start or end - start > 1000:
        return [token]
    width = max(len(start_str), len(end_str))
    return [f"{prefix1}{index:0{width}d}" for index in range(start, end + 1)]


def parse_references(raw: str) -> list[str]:
    if not raw:
        return []
    refs: list[str] = []
    for token in re.split(r"[,;/\s]+", raw):
        refs.extend(expand_ref_token(token))
    seen: set[str] = set()
    ordered: list[str] = []
    for ref in refs:
        if ref and ref not in seen:
            seen.add(ref)
            ordered.append(ref)
    return ordered


def parse_float(raw: str) -> float | None:
    value = raw.strip().lower().replace("mm", "").replace("mil", "")
    if not value:
        return None
    value = value.replace(",", "")
    try:
        return float(value)
    except ValueError:
        return None


def is_probable_refdes(value: str) -> bool:
    return bool(re.match(r"^[A-Za-z][A-Za-z0-9_+-]*\d+[A-Za-z0-9_+-]*$", value.strip().upper()))


def normalize_side(raw: str) -> str:
    value = raw.strip().lower()
    if value in {"top", "t", "primary", "front", "topside", "no", "false"}:
        return "top"
    if value in {"bottom", "bot", "b", "secondary", "back", "bottomside", "yes", "true"}:
        return "bottom"
    return "unknown"


def load_bom_rows(path: Path) -> list[dict]:
    rows = read_table(path)
    bom_rows: list[dict] = []
    for index, row in enumerate(rows, start=1):
        mapped = remap_row(row, BOM_ALIASES)
        if not mapped.get("references"):
            candidates = [value for value in row.values() if value and ("," in value or is_probable_refdes(value))]
            for candidate in candidates:
                refs = parse_references(candidate)
                if refs:
                    mapped["references"] = candidate
                    break
        references = parse_references(mapped.get("references", ""))
        quantity = parse_quantity(mapped.get("quantity", ""), len(references) or 1)
        bom_rows.append(
            {
                "id": index,
                "description": mapped.get("description", ""),
                "value": mapped.get("value", ""),
                "part": mapped.get("part", ""),
                "footprint": mapped.get("footprint", ""),
                "quantity": quantity,
                "manufacturer": mapped.get("manufacturer", ""),
                "manufacturerPn": mapped.get("manufacturer_pn", ""),
                "references": references,
                "referenceText": mapped.get("references", ""),
            }
        )
    return bom_rows


class SimpleTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self.in_table = False
        self.in_row = False
        self.in_cell = False
        self.current_table: list[list[str]] = []
        self.current_row: list[str] = []
        self.current_cell: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self.in_table = True
            self.current_table = []
        elif tag == "tr" and self.in_table:
            self.in_row = True
            self.current_row = []
        elif tag in {"td", "th"} and self.in_row:
            self.in_cell = True
            self.current_cell = []
        elif tag == "br" and self.in_cell:
            self.current_cell.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self.in_cell:
            self.in_cell = False
            self.current_row.append("".join(self.current_cell).replace("\xa0", " ").strip())
        elif tag == "tr" and self.in_row:
            self.in_row = False
            if self.current_row:
                self.current_table.append(self.current_row)
        elif tag == "table" and self.in_table:
            self.in_table = False
            if self.current_table:
                self.tables.append(self.current_table)

    def handle_data(self, data: str) -> None:
        if self.in_cell:
            self.current_cell.append(data)


def read_html_table(path: Path) -> list[dict[str, str]]:
    parser = SimpleTableParser()
    parser.feed(path.read_text(encoding="utf-8", errors="ignore"))
    if not parser.tables:
        return []
    table = max(parser.tables, key=len)
    header = table[0]
    records: list[dict[str, str]] = []
    for row in table[1:]:
        padded = row + [""] * (len(header) - len(row))
        record = {header[i]: padded[i].strip() for i in range(len(header)) if header[i]}
        if any(record.values()):
            records.append(record)
    return records


def load_placements(path: Path | None) -> dict[str, dict]:
    if not path:
        return {}
    rows = read_html_table(path) if path.suffix.lower() in {".htm", ".html"} else (
        read_xlsx_table(path, PLACEMENT_ALIASES) if path.suffix.lower() == ".xlsx" else read_table(path)
    )
    placements: dict[str, dict] = {}
    for row in rows:
        mapped = remap_row(row, PLACEMENT_ALIASES)
        refdes = normalize_refdes(mapped.get("refdes", ""))
        if not refdes:
            continue
        placements[refdes] = {
            "refdes": refdes,
            "x": parse_float(mapped.get("x", "")),
            "y": parse_float(mapped.get("y", "")),
            "rotation": parse_float(mapped.get("rotation", "")) or 0.0,
            "side": normalize_side(mapped.get("side", "")),
            "package": row.get("COMP_PACKAGE", "") or row.get("PCB Footprint", "") or mapped.get("footprint", ""),
            "value": row.get("COMP_VALUE", "") or mapped.get("value", ""),
            "deviceType": row.get("COMP_DEVICE_TYPE", "") or row.get("Part", "") or mapped.get("part", ""),
        }
    return placements


def parse_ipc_profile(path: Path | None) -> BoardProfile | None:
    if not path:
        return None
    ns = {"ipc": "http://webstds.ipc.org/2581"}
    root = ET.parse(path).getroot()
    profile_points: list[dict[str, float]] = []
    polygon = root.find(".//ipc:Step/ipc:Profile/ipc:Polygon", ns)
    if polygon is not None:
        profile_points = parse_ipc_polygon(polygon)
    outline_points = parse_ipc_outline_points(root, ns)
    if is_valid_board_outline(profile_points, outline_points):
        return BoardProfile(points=profile_points)
    if outline_points:
        return BoardProfile(points=outline_points)
    if len(profile_points) >= 4:
        return BoardProfile(points=profile_points)
    return None


def parse_ipc_outline_points(root: ET.Element, ns: dict[str, str]) -> list[dict[str, float]]:
    layer = root.find('.//ipc:LayerFeature[@layerRef="01_OUTLINE"]', ns)
    if layer is None:
        return []
    candidates: list[tuple[float, list[dict[str, float]]]] = []
    for features in layer.findall(".//ipc:Features", ns):
        location = features.find("ipc:Location", ns)
        dx = parse_float(location.attrib.get("x", "")) if location is not None else 0.0
        dy = parse_float(location.attrib.get("y", "")) if location is not None else 0.0
        dx = dx or 0.0
        dy = dy or 0.0
        for node in list(features):
            tag = node.tag.rsplit("}", 1)[-1]
            if tag == "Location":
                continue
            if tag == "Polyline":
                points = parse_ipc_polyline(node)
            elif tag == "Polygon":
                points = parse_ipc_polygon(node)
            else:
                continue
            if dx or dy:
                points = [{"x": point["x"] + dx, "y": point["y"] + dy} for point in points]
            bbox = bbox_from_points(points)
            if not points or bbox is None:
                continue
            area = (bbox["maxX"] - bbox["minX"]) * (bbox["maxY"] - bbox["minY"])
            candidates.append((area, points))
    if not candidates:
        return []
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def is_valid_board_outline(profile_points: list[dict[str, float]], outline_points: list[dict[str, float]]) -> bool:
    if len(profile_points) < 4:
        return False
    profile_bbox = bbox_from_points(profile_points)
    if profile_bbox is None:
        return False
    profile_area = (profile_bbox["maxX"] - profile_bbox["minX"]) * (profile_bbox["maxY"] - profile_bbox["minY"])
    if profile_area <= 0:
        return False
    if not outline_points:
        return True
    outline_bbox = bbox_from_points(outline_points)
    if outline_bbox is None:
        return True
    outline_area = (outline_bbox["maxX"] - outline_bbox["minX"]) * (outline_bbox["maxY"] - outline_bbox["minY"])
    if outline_area <= 0:
        return True
    return profile_area >= outline_area * 0.2


def parse_ipc_polygon(node: ET.Element) -> list[dict[str, float]]:
    points: list[dict[str, float]] = []
    for child in list(node):
        tag = child.tag.rsplit("}", 1)[-1]
        if tag not in {"PolyBegin", "PolyStepSegment", "PolyStepCurve"}:
            continue
        x = parse_float(child.attrib.get("x", ""))
        y = parse_float(child.attrib.get("y", ""))
        if x is not None and y is not None:
            if tag == "PolyStepCurve" and points:
                cx = parse_float(child.attrib.get("centerX", ""))
                cy = parse_float(child.attrib.get("centerY", ""))
                if cx is not None and cy is not None:
                    start = points[-1]
                    angle = math.atan2(start["y"] - cy, start["x"] - cx)
                    end = math.atan2(y - cy, x - cx)
                    clockwise = child.attrib.get("clockwise", "false").lower() == "true"
                    sweep = -((angle - end) % math.tau) if clockwise else ((end - angle) % math.tau)
                    if abs(sweep) < 1e-12:
                        sweep = -math.tau if clockwise else math.tau
                    radius = math.hypot(start["x"] - cx, start["y"] - cy)
                    count = max(1, math.ceil(abs(sweep) / math.radians(2)))
                    for step in range(1, count):
                        a = angle + sweep * step / count
                        points.append({"x": cx + radius * math.cos(a), "y": cy + radius * math.sin(a)})
            points.append({"x": x, "y": y})
    return points


def parse_ipc_line_width(node: ET.Element, ns: dict[str, str]) -> float:
    line_desc = node.find("ipc:LineDesc", ns)
    if line_desc is None:
        return 0.0
    return parse_float(line_desc.attrib.get("lineWidth", "")) or 0.0


def parse_ipc_polyline(node: ET.Element) -> list[dict[str, float]]:
    return parse_ipc_polygon(node)


def rotate_point(x: float, y: float, angle_deg: float) -> tuple[float, float]:
    angle = math.radians(angle_deg)
    return (
        x * math.cos(angle) - y * math.sin(angle),
        x * math.sin(angle) + y * math.cos(angle),
    )


def parse_ipc_standard_primitives(root: ET.Element, ns: dict[str, str]) -> dict[str, dict]:
    primitives: dict[str, dict] = {}
    for ref in root.findall(".//ipc:EntryStandard", ns):
        primitive_id = ref.attrib.get("id")
        if not primitive_id:
            continue
        child = next(iter(list(ref)), None)
        if child is None:
            continue
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "RectCenter":
            width = parse_float(child.attrib.get("width", "")) or 0.0
            height = parse_float(child.attrib.get("height", "")) or 0.0
            primitives[primitive_id] = {
                "type": "rect",
                "width": width,
                "height": height,
                "bbox": {"minX": -width / 2, "minY": -height / 2, "maxX": width / 2, "maxY": height / 2},
            }
        elif tag == "Circle":
            diameter = parse_float(child.attrib.get("diameter", "")) or 0.0
            radius = diameter / 2
            primitives[primitive_id] = {
                "type": "circle",
                "diameter": diameter,
                "bbox": {"minX": -radius, "minY": -radius, "maxX": radius, "maxY": radius},
            }
        elif tag == "Oval":
            width = parse_float(child.attrib.get("width", "")) or 0.0
            height = parse_float(child.attrib.get("height", "")) or 0.0
            primitives[primitive_id] = {
                "type": "oval",
                "width": width,
                "height": height,
                "bbox": {"minX": -width / 2, "minY": -height / 2, "maxX": width / 2, "maxY": height / 2},
            }
    return primitives


def merge_bbox(target: dict[str, float] | None, bbox: dict[str, float] | None) -> dict[str, float] | None:
    if bbox is None:
        return target
    if target is None:
        return dict(bbox)
    return {
        "minX": min(target["minX"], bbox["minX"]),
        "minY": min(target["minY"], bbox["minY"]),
        "maxX": max(target["maxX"], bbox["maxX"]),
        "maxY": max(target["maxY"], bbox["maxY"]),
    }


def bbox_from_points(points: list[dict[str, float]]) -> dict[str, float] | None:
    if not points:
        return None
    xs = [point["x"] for point in points]
    ys = [point["y"] for point in points]
    return {"minX": min(xs), "minY": min(ys), "maxX": max(xs), "maxY": max(ys)}


def transform_bbox(bbox: dict[str, float], dx: float, dy: float, rotation: float) -> dict[str, float]:
    corners = [
        rotate_point(bbox["minX"], bbox["minY"], rotation),
        rotate_point(bbox["minX"], bbox["maxY"], rotation),
        rotate_point(bbox["maxX"], bbox["minY"], rotation),
        rotate_point(bbox["maxX"], bbox["maxY"], rotation),
    ]
    xs = [dx + point[0] for point in corners]
    ys = [dy + point[1] for point in corners]
    return {"minX": min(xs), "minY": min(ys), "maxX": max(xs), "maxY": max(ys)}


def parse_ipc_packages(path: Path | None) -> dict[str, PackageGeometry]:
    if not path:
        return {}
    ns = {"ipc": "http://webstds.ipc.org/2581"}
    root = ET.parse(path).getroot()
    primitives = parse_ipc_standard_primitives(root, ns)
    packages: dict[str, PackageGeometry] = {}
    for package in root.findall(".//ipc:Package", ns):
        name = package.attrib.get("name", "")
        if not name:
            continue
        pickup = package.find("ipc:PickupPoint", ns)
        pickup_x = parse_float(pickup.attrib.get("x", "")) if pickup is not None else 0.0
        pickup_y = parse_float(pickup.attrib.get("y", "")) if pickup is not None else 0.0
        pickup_x = pickup_x or 0.0
        pickup_y = pickup_y or 0.0
        bbox: dict[str, float] | None = None
        outline_polygons: list[list[dict[str, float]]] = []
        drawing_shapes: list[dict] = []
        pad_shapes: list[dict] = []
        for tag_name in ("Outline", "AssemblyDrawing", "SilkScreen", "LandPattern"):
            for section in package.findall(f"ipc:{tag_name}", ns):
                for polygon in section.findall(".//ipc:Polygon", ns):
                    points = parse_ipc_polygon(polygon)
                    if not points:
                        continue
                    outline_polygons.append(points)
                    bbox = merge_bbox(bbox, bbox_from_points(points))
                    drawing_shapes.append(
                        {
                            "type": "polygon",
                            "points": points,
                            "width": parse_ipc_line_width(section, ns),
                            "source": tag_name.lower(),
                        }
                    )
                for polyline in section.findall(".//ipc:Polyline", ns):
                    points = parse_ipc_polyline(polyline)
                    if not points:
                        continue
                    line_width = parse_ipc_line_width(polyline, ns) or parse_ipc_line_width(section, ns)
                    bbox = merge_bbox(bbox, bbox_from_points(points))
                    drawing_shapes.append(
                        {
                            "type": "polyline",
                            "points": points,
                            "width": line_width,
                            "source": tag_name.lower(),
                        }
                    )
                if tag_name == "LandPattern":
                    for pad in section.findall("ipc:Pad", ns):
                        primitive_ref = pad.find("ipc:StandardPrimitiveRef", ns)
                        location = pad.find("ipc:Location", ns)
                        xform = pad.find("ipc:Xform", ns)
                        if primitive_ref is None or location is None:
                            continue
                        primitive = primitives.get(primitive_ref.attrib.get("id", ""))
                        if not primitive or not primitive.get("bbox"):
                            continue
                        px = parse_float(location.attrib.get("x", "")) or 0.0
                        py = parse_float(location.attrib.get("y", "")) or 0.0
                        rotation = parse_float(xform.attrib.get("rotation", "")) if xform is not None else 0.0
                        bbox = merge_bbox(bbox, transform_bbox(primitive["bbox"], px, py, rotation or 0.0))
                        pad_shapes.append(
                            {
                                "primitive": primitive["type"],
                                "width": primitive.get("width", primitive.get("diameter", 0.0)),
                                "height": primitive.get("height", primitive.get("diameter", 0.0)),
                                "diameter": primitive.get("diameter", 0.0),
                                "x": px,
                                "y": py,
                                "rotation": rotation or 0.0,
                            }
                        )
        packages[name] = PackageGeometry(
            name=name,
            pickup_x=pickup_x,
            pickup_y=pickup_y,
            bbox=bbox,
            outline_polygons=outline_polygons,
            drawing_shapes=drawing_shapes,
            pad_shapes=pad_shapes,
        )
    return packages


def load_ipc_components(path: Path | None) -> dict[str, dict]:
    if not path:
        return {}
    ns = {"ipc": "http://webstds.ipc.org/2581"}
    root = ET.parse(path).getroot()
    placements: dict[str, dict] = {}
    for comp in root.findall(".//ipc:Component", ns):
        refdes = normalize_refdes(comp.attrib.get("refDes", ""))
        if not refdes:
            continue
        location = comp.find("ipc:Location", ns)
        xform = comp.find("ipc:Xform", ns)
        placements[refdes] = {
            "refdes": refdes,
            "x": parse_float(location.attrib.get("x", "")) if location is not None else None,
            "y": parse_float(location.attrib.get("y", "")) if location is not None else None,
            "rotation": parse_float(xform.attrib.get("rotation", "")) if xform is not None else 0.0,
            "side": normalize_side(comp.attrib.get("layerRef", "")),
            "package": comp.attrib.get("packageRef", ""),
            "deviceType": comp.attrib.get("part", ""),
        }
    return placements


def detect_placement_unit(
    placements: dict[str, dict], ipc_components: dict[str, dict], forced_unit: str
) -> UnitDetection:
    if forced_unit in {"mm", "mil"}:
        scale = 1.0 if forced_unit == "mm" else 0.0254
        return UnitDetection("mm", forced_unit, scale, f"user:{forced_unit}")
    if not placements:
        return UnitDetection("mm", "mm", 1.0, "no-placement")
    ratios: list[float] = []
    for refdes, placement in placements.items():
        ipc = ipc_components.get(refdes)
        if not ipc:
            continue
        for axis in ("x", "y"):
            p_value = placement.get(axis)
            i_value = ipc.get(axis)
            if p_value is None or i_value is None:
                continue
            if abs(i_value) < 1e-9 or abs(p_value) < 1e-9:
                continue
            ratios.append(abs(p_value / i_value))
    if ratios:
        median_ratio = statistics.median(ratios)
        if 900 <= median_ratio <= 1100:
            return UnitDetection("mm", "mil", 0.001, f"ipc-ratio:{median_ratio:.2f}")
        if 24 <= median_ratio <= 26.5:
            return UnitDetection("mm", "mil", 0.0254, f"ipc-ratio:{median_ratio:.2f}")
        if 0.9 <= median_ratio <= 1.1:
            return UnitDetection("mm", "mm", 1.0, f"ipc-ratio:{median_ratio:.2f}")
    coords = [abs(item.get(axis)) for item in placements.values() for axis in ("x", "y") if item.get(axis) is not None]
    if not coords:
        return UnitDetection("mm", "mm", 1.0, "no-coordinates")
    median_coord = statistics.median(coords)
    if median_coord > 200:
        return UnitDetection("mm", "mil", 0.0254, f"magnitude:{median_coord:.2f}")
    return UnitDetection("mm", "mm", 1.0, f"magnitude:{median_coord:.2f}")


def normalize_placement_units(
    placements: dict[str, dict], unit_detection: UnitDetection
) -> dict[str, dict]:
    scale = unit_detection.scale_to_internal
    if scale == 1.0:
        return placements
    normalized: dict[str, dict] = {}
    for refdes, placement in placements.items():
        normalized[refdes] = {
            **placement,
            "x": placement["x"] * scale if placement.get("x") is not None else None,
            "y": placement["y"] * scale if placement.get("y") is not None else None,
        }
    return normalized


TESTPOINT_KEYWORDS = (
    "test point",
    "testpoint",
    "testcou",
    "tp_test",
    "test coup",
)


def text_has_testpoint_hint(value: str) -> bool:
    text = normalize_header(value)
    return any(keyword in text for keyword in TESTPOINT_KEYWORDS)


def component_is_testpoint(component: dict) -> bool:
    package = component.get("package", "")
    device_type = component.get("deviceType", "")
    refdes = component.get("refdes", "")
    return (
        text_has_testpoint_hint(package)
        or text_has_testpoint_hint(device_type)
        or bool(re.match(r"^(TP\d+|VREF\d+)$", refdes))
    )


def normalize_rules_list(values: list[str] | None) -> set[str]:
    return {normalize_header(value) for value in (values or []) if value}


def row_is_testpoint(row: dict, placements: dict[str, dict], rules: dict) -> bool:
    refs = row.get("references", [])
    refdes_exclude = {value.strip().upper() for value in rules.get("refdesExclude", []) if value}
    refdes_include = {value.strip().upper() for value in rules.get("refdesInclude", []) if value}
    if any(ref in refdes_exclude for ref in refs):
        return False
    if any(ref in refdes_include for ref in refs):
        return True
    package_exclude = normalize_rules_list(rules.get("packageExclude"))
    package_include = normalize_rules_list(rules.get("packageInclude"))
    footprint_text = normalize_header(row.get("footprint", ""))
    if footprint_text and footprint_text in package_exclude:
        return False
    if footprint_text and footprint_text in package_include:
        return True
    description_exclude = normalize_rules_list(rules.get("keywordExclude"))
    description_include = normalize_rules_list(rules.get("keywordInclude"))
    row_text = " ".join(
        [
            row.get("description", ""),
            row.get("value", ""),
            row.get("part", ""),
            row.get("footprint", ""),
            row.get("manufacturerPn", ""),
        ]
    )
    normalized_row_text = normalize_header(row_text)
    if any(keyword and keyword in normalized_row_text for keyword in description_exclude):
        return False
    if any(keyword and keyword in normalized_row_text for keyword in description_include):
        return True
    if text_has_testpoint_hint(row_text):
        return True
    if not refs:
        return False
    matched = [placements.get(ref) for ref in refs if placements.get(ref)]
    if matched and all(component_is_testpoint(component) for component in matched):
        return True
    if all(re.match(r"^(TP\d+|VREF\d+)$", ref) for ref in refs):
        return True
    return False


def filter_testpoint_rows(
    bom_rows: list[dict], placements: dict[str, dict], include_test_points: bool, rules: dict
) -> list[dict]:
    if include_test_points:
        return bom_rows
    return [row for row in bom_rows if not row_is_testpoint(row, placements, rules)]


def encode_image(path: Path | None, side: str) -> BoardImage | None:
    if not path:
        return None
    return BoardImage(side=side, src=path.resolve().as_uri())


def choose_pdf_page(pdf_path: Path, side: str) -> int:
    if fitz is None:
        return 0
    doc = fitz.open(pdf_path)
    priorities = [
        f"art film - 02_top" if side == "top" else "art film - 05_bottom",
        f"silk_{side}" if side in {"top", "bottom"} else "",
        side,
    ]
    best_index = 0
    best_score = -1
    for index in range(doc.page_count):
        text = doc.load_page(index).get_text("text").lower()
        score = 0
        for rank, marker in enumerate(priorities):
            if marker and marker in text:
                score += 100 - rank * 20
        if "outline" in text:
            score -= 30
        if score > best_score:
            best_score = score
            best_index = index
    return best_index


def render_pdf_image(pdf_path: Path | None, side: str) -> BoardImage | None:
    if not pdf_path or fitz is None:
        return None
    doc = fitz.open(pdf_path)
    page = doc.load_page(choose_pdf_page(pdf_path, side))
    pix = page.get_pixmap(matrix=fitz.Matrix(2.5, 2.5), alpha=False)
    generated_dir = pdf_path.parent / ".ibom-cache"
    generated_dir.mkdir(exist_ok=True)
    out_path = generated_dir / f"{pdf_path.stem}-{side}.png"
    pix.save(out_path)
    return BoardImage(side=side, src=out_path.resolve().as_uri())


def get_image_placement(image_placement: dict) -> dict:
    defaults = {
        "top": {"x": 40, "y": 40, "width": 920, "height": 620, "opacity": 0.88},
        "bottom": {"x": 40, "y": 40, "width": 920, "height": 620, "opacity": 0.88},
    }
    result: dict[str, dict] = {}
    for side in ("top", "bottom"):
        current = defaults[side].copy()
        incoming = image_placement.get(side, {}) if isinstance(image_placement, dict) else {}
        for key in ("x", "y", "width", "height", "opacity"):
            if key in incoming:
                value = parse_float(str(incoming[key]))
                if value is not None:
                    current[key] = value
        result[side] = current
    return result


def build_components(
    bom_rows: list[dict],
    placements: dict[str, dict],
    board_profile: BoardProfile | None,
    packages: dict[str, PackageGeometry],
) -> tuple[list[dict], dict]:
    components: list[dict] = []
    min_x = math.inf
    min_y = math.inf
    max_x = -math.inf
    max_y = -math.inf

    if board_profile:
        for point in board_profile.points:
            min_x = min(min_x, point["x"])
            min_y = min(min_y, point["y"])
            max_x = max(max_x, point["x"])
            max_y = max(max_y, point["y"])

    for row in bom_rows:
        for refdes in row["references"]:
            placement = placements.get(refdes, {})
            x = placement.get("x")
            y = placement.get("y")
            package_name = placement.get("package", "") or row["footprint"]
            package = packages.get(package_name)
            rotation = placement.get("rotation", 0.0) or 0.0
            outline_polygons: list[list[dict[str, float]]] = []
            drawing_shapes: list[dict] = []
            pad_shapes: list[dict] = []
            absolute_bbox = None
            if x is not None and y is not None and package is not None:
                # Component Location is the footprint origin in Allegro IPC.
                # PickupPoint is an assembly centroid, not another translation.
                local_dx = x
                local_dy = y
                if package.bbox is not None:
                    absolute_bbox = transform_bbox(package.bbox, local_dx, local_dy, rotation)
                for polygon in package.outline_polygons:
                    absolute_polygon: list[dict[str, float]] = []
                    for point in polygon:
                        tx, ty = rotate_point(point["x"], point["y"], rotation)
                        absolute_polygon.append({"x": local_dx + tx, "y": local_dy + ty})
                    if absolute_polygon:
                        outline_polygons.append(absolute_polygon)
                for shape in package.drawing_shapes:
                    transformed_points: list[dict[str, float]] = []
                    for point in shape["points"]:
                        tx, ty = rotate_point(point["x"], point["y"], rotation)
                        transformed_points.append({"x": local_dx + tx, "y": local_dy + ty})
                    if transformed_points:
                        drawing_shapes.append(
                            {
                                "type": shape["type"],
                                "points": transformed_points,
                                "width": shape.get("width", 0.0),
                                "source": shape.get("source", ""),
                            }
                        )
                for pad in package.pad_shapes:
                    px, py = rotate_point(pad["x"], pad["y"], rotation)
                    pad_shapes.append(
                        {
                            "primitive": pad["primitive"],
                            "width": pad.get("width", 0.0),
                            "height": pad.get("height", 0.0),
                            "diameter": pad.get("diameter", 0.0),
                            "x": local_dx + px,
                            "y": local_dy + py,
                            "rotation": (rotation + pad.get("rotation", 0.0)) % 360,
                        }
                    )
                if not outline_polygons and absolute_bbox is not None:
                    outline_polygons = [[
                        {"x": absolute_bbox["minX"], "y": absolute_bbox["minY"]},
                        {"x": absolute_bbox["maxX"], "y": absolute_bbox["minY"]},
                        {"x": absolute_bbox["maxX"], "y": absolute_bbox["maxY"]},
                        {"x": absolute_bbox["minX"], "y": absolute_bbox["maxY"]},
                    ]]
            if x is not None and y is not None:
                min_x = min(min_x, x)
                min_y = min(min_y, y)
                max_x = max(max_x, x)
                max_y = max(max_y, y)
            if absolute_bbox is not None:
                min_x = min(min_x, absolute_bbox["minX"])
                min_y = min(min_y, absolute_bbox["minY"])
                max_x = max(max_x, absolute_bbox["maxX"])
                max_y = max(max_y, absolute_bbox["maxY"])
            components.append(
                {
                    "refdes": refdes,
                    "bomId": row["id"],
                    "x": x,
                    "y": y,
                    "rotation": rotation,
                    "side": placement.get("side", "unknown"),
                    "description": row["description"],
                    "value": row["value"],
                    "footprint": row["footprint"],
                    "bbox": absolute_bbox,
                    "outlinePolygons": outline_polygons,
                    "drawingShapes": drawing_shapes,
                    "padShapes": pad_shapes,
                }
            )

    board = {
        "minX": 0 if min_x is math.inf else min_x,
        "minY": 0 if min_y is math.inf else min_y,
        "maxX": 100 if max_x is -math.inf else max_x,
        "maxY": 100 if max_y is -math.inf else max_y,
    }
    return components, board


def summarize_stats(
    bom_rows: list[dict],
    placements: dict[str, dict],
    components: list[dict] | None = None,
    board_profile: BoardProfile | None = None,
    filtered_testpoint_count: int = 0,
) -> dict:
    total_groups = len(bom_rows)
    bom_refs = {ref for row in bom_rows for ref in row["references"]}
    total_refs = len(bom_refs)
    placed_refs = sum(
        1
        for ref in bom_refs
        if ref in placements and placements[ref].get("x") is not None and placements[ref].get("y") is not None
    )
    components = components or []
    top_components = sum(1 for item in components if item.get("side") == "top")
    bottom_components = sum(1 for item in components if item.get("side") == "bottom")
    unknown_side_components = sum(1 for item in components if item.get("side") not in {"top", "bottom"})
    matched_refs = sum(1 for ref in bom_refs if ref in placements)
    match_rate = (matched_refs / total_refs) if total_refs else 0.0
    return {
        "groupCount": total_groups,
        "referenceCount": total_refs,
        "placedReferenceCount": placed_refs,
        "unplacedReferenceCount": max(total_refs - placed_refs, 0),
        "matchedReferenceCount": matched_refs,
        "matchRate": match_rate,
        "topComponentCount": top_components,
        "bottomComponentCount": bottom_components,
        "unknownSideCount": unknown_side_components,
        "filteredTestPointCount": filtered_testpoint_count,
        "hasBoardOutline": bool(board_profile and board_profile.points),
    }


def build_validation_report(
    options: RuntimeOptions,
    bom_rows: list[dict],
    merged_placements: dict[str, dict],
    components: list[dict],
    board_profile: BoardProfile | None,
    stats: dict,
    filtered_testpoint_count: int,
) -> dict:
    warnings: list[str] = []
    info: list[str] = []

    if not bom_rows:
        raise ValueError("BOM 中没有可用记录，请检查表格内容或表头。")

    ref_count = stats["referenceCount"]
    if ref_count == 0:
        raise ValueError("BOM 中没有识别到位号，请检查 BOM 表头是否包含 位号/Reference。")

    if stats["matchedReferenceCount"] == 0:
        raise ValueError("BOM 与坐标/IPC 未匹配到任何位号，请检查 IPC-2581 或 placement 导出。")

    if stats["placedReferenceCount"] == 0:
        raise ValueError("所有 BOM 位号都没有可用坐标，无法生成有效的交互视图。")

    if stats["matchRate"] < 0.7:
        warnings.append(
            f"BOM 与坐标匹配率偏低：{stats['matchedReferenceCount']}/{ref_count} ({stats['matchRate'] * 100:.1f}%)。"
        )
    elif stats["matchRate"] < 0.95:
        info.append(
            f"BOM 与坐标匹配率：{stats['matchedReferenceCount']}/{ref_count} ({stats['matchRate'] * 100:.1f}%)。"
        )

    if not stats["hasBoardOutline"]:
        warnings.append("未识别到板框，页面将使用器件范围估算视图边界。")

    if stats["unplacedReferenceCount"] > 0:
        warnings.append(f"有 {stats['unplacedReferenceCount']} 个位号没有坐标，页面中将无法定位。")

    if filtered_testpoint_count > 0:
        info.append(f"已按规则剔除 {filtered_testpoint_count} 个测试点 BOM 分组。")

    if options.placement is None and options.ipc is not None:
        info.append("当前仅使用 IPC-2581 作为坐标来源。")
    elif options.placement is not None and options.ipc is None:
        info.append("当前仅使用 placement 文件作为坐标来源。")
    elif options.placement is not None and options.ipc is not None:
        info.append("当前同时使用 IPC-2581 与 placement，坐标已自动合并。")

    return {
        "ok": True,
        "warnings": warnings,
        "info": info,
        "summary": {
            "groupCount": stats["groupCount"],
            "referenceCount": stats["referenceCount"],
            "placedReferenceCount": stats["placedReferenceCount"],
            "unplacedReferenceCount": stats["unplacedReferenceCount"],
            "topComponentCount": stats["topComponentCount"],
            "bottomComponentCount": stats["bottomComponentCount"],
            "unknownSideCount": stats["unknownSideCount"],
            "filteredTestPointCount": filtered_testpoint_count,
            "hasBoardOutline": stats["hasBoardOutline"],
        },
    }


def build_payload(options: RuntimeOptions) -> dict:
    if not options.bom:
        raise ValueError("BOM file is required")
    original_bom_rows = load_bom_rows(options.bom)
    ipc_components = load_ipc_components(options.ipc)
    placements = load_placements(options.placement)
    unit_detection = detect_placement_unit(placements, ipc_components, options.placement_unit)
    placements = normalize_placement_units(placements, unit_detection)
    merged_placements = {**ipc_components, **placements}
    bom_rows = filter_testpoint_rows(
        original_bom_rows, merged_placements, options.include_test_points, options.testpoint_rules
    )
    filtered_testpoint_count = len(original_bom_rows) - len(bom_rows)
    board_profile = parse_ipc_profile(options.ipc)
    packages = parse_ipc_packages(options.ipc)
    components, board = build_components(bom_rows, merged_placements, board_profile, packages)
    stats = summarize_stats(
        bom_rows,
        merged_placements,
        components=components,
        board_profile=board_profile,
        filtered_testpoint_count=filtered_testpoint_count,
    )
    report = build_validation_report(
        options,
        bom_rows,
        merged_placements,
        components,
        board_profile,
        stats,
        filtered_testpoint_count,
    )
    top_image = encode_image(options.board_top, "top") or render_pdf_image(options.board_top_pdf, "top")
    bottom_image = encode_image(options.board_bottom, "bottom") or render_pdf_image(options.board_bottom_pdf, "bottom")
    image_placement = get_image_placement(options.image_placement)
    return {
        "meta": {
            "title": options.title,
            "projectKey": options.project or options.title,
            "author": options.author,
            "version": options.version,
            "createdAt": options.created_at,
            "sourceBom": str(options.bom),
            "sourcePlacement": str(options.placement) if options.placement else "",
            "sourceIpc": str(options.ipc) if options.ipc else "",
            "placementSourceUnit": unit_detection.source_unit,
            "internalUnit": unit_detection.internal_unit,
            "unitDetectionReason": unit_detection.reason,
            "testPointsExcluded": not options.include_test_points,
            "toolVersion": TOOL_VERSION,
        },
        "stats": stats,
        "report": report,
        "board": board,
        "bomRows": bom_rows,
        "components": components,
        "profile": board_profile.points if board_profile else [],
        "images": {
            "top": top_image.src if top_image else "",
            "bottom": bottom_image.src if bottom_image else "",
        },
        "imagePlacement": image_placement,
    }


def render_initial_stats(payload: dict) -> str:
    stats = payload["stats"]
    meta = payload["meta"]
    return (
        f'<span class="chip">BOM分组 {stats["groupCount"]}</span>'
        f'<span class="chip">位号 {stats["referenceCount"]}</span>'
        f'<span class="chip">有坐标 {stats["placedReferenceCount"]}</span>'
        f'<span class="chip">已完成 0/{stats["groupCount"]} (0%)</span>'
        f'<span class="chip">坐标源单位 {html.escape(meta.get("placementSourceUnit") or "-")}</span>'
        f'<span class="chip">测试点 {"已剔除" if meta.get("testPointsExcluded") else "保留"}</span>'
    )


def get_bom_display_title(row: dict) -> str:
    value = extract_preferred_display_value(row)
    if value:
        return value
    for key in ("manufacturerPn", "part", "description"):
        fallback = (row.get(key) or "").strip()
        if fallback:
            return fallback
    return "未命名器件"


def extract_preferred_display_value(row: dict) -> str:
    explicit = (row.get("value") or "").strip()
    if explicit:
        return explicit

    part = (row.get("part") or "").strip()
    description = (row.get("description") or "").strip()
    candidates = [part, description]

    direct_patterns = [
        r"\b\d+(?:\.\d+)?\s*[pnumkM]?F\s*/\s*\d+(?:\.\d+)?V\b",
        r"\b\d+(?:\.\d+)?\s*[pnumkM]?H\b",
        r"\b\d+(?:\.\d+)?\s*[RKM](?:\d+)?\b",
        r"\b0R\b",
    ]
    for text in candidates:
        for pattern in direct_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return re.sub(r"\s+", "", match.group(0)).upper().replace("UF", "uF").replace("NF", "nF").replace("PF", "pF").replace("MH", "mH").replace("UH", "uH")

    if part:
        simplified = re.split(r"[_\s-]", part, maxsplit=1)[0].strip()
        if simplified:
            return simplified

    return ""


def get_bom_model_text(row: dict) -> str:
    for key in ("manufacturerPn", "part"):
        value = (row.get(key) or "").strip()
        if value:
            return value
    return ""


def render_initial_bom_list(payload: dict) -> str:
    rows = payload.get("bomRows", [])
    if not rows:
        return '<div class="empty"><strong>没有 BOM 记录</strong>请检查输入文件。</div>'
    result: list[str] = []
    for index, row in enumerate(rows):
        active = " active" if index == 0 else ""
        title = html.escape(get_bom_display_title(row))
        model = html.escape(get_bom_model_text(row))
        references = html.escape(", ".join(row.get("references", [])))
        quantity = html.escape(str(row.get("quantity", "")))
        footprint = html.escape(row.get("footprint") or "-")
        result.append(
            f"""
          <article class="bom-row{active}" data-bom-id="{row["id"]}">
            <div class="bom-head">
              <div>
                <div class="bom-title">{title}</div>
                {f'<div class="muted">型号: {model}</div>' if model else ''}
              </div>
              <label class="chip">
                <input type="checkbox" data-done-id="{row["id"]}">
                完成
              </label>
            </div>
            <div class="muted">位号: {references}</div>
            <div class="bom-meta">
              <span class="tag">数量 {quantity}</span>
              <span class="tag">封装 {footprint}</span>
            </div>
          </article>
        """
        )
    return "".join(result)


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f4f1ea;
      --panel: rgba(255,255,255,0.92);
      --ink: #1f2933;
      --muted: #5b6875;
      --line: rgba(31,41,51,0.12);
      --accent: #b3472d;
      --accent-soft: rgba(179,71,45,0.14);
      --ok: #1d7a4d;
      --warn: #ad6c00;
      --chip: #ece7de;
      --shadow: 0 20px 60px rgba(51,38,24,0.12);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(179,71,45,0.08), transparent 30%),
        radial-gradient(circle at right 20%, rgba(29,122,77,0.08), transparent 28%),
        linear-gradient(180deg, #efe9dd 0%, #f8f6f1 100%);
    }}
    .layout {{
      display: grid;
      grid-template-columns: minmax(320px, 420px) minmax(0, 1fr);
      height: 100vh;
      gap: 16px;
      padding: 16px;
    }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 20px;
      box-shadow: var(--shadow);
      backdrop-filter: blur(12px);
      display: flex;
      flex-direction: column;
    }}
    .sidebar {{
      display: block;
      overflow-y: auto;
      overflow-x: hidden;
      scrollbar-gutter: stable;
      position: relative;
    }}
    .sidebar::-webkit-scrollbar {{
      width: 8px;
    }}
    .sidebar::-webkit-scrollbar-track {{
      background: transparent;
    }}
    .sidebar::-webkit-scrollbar-thumb {{
      background: rgba(120, 111, 98, 0.28);
      border-radius: 999px;
    }}
    .sidebar::-webkit-scrollbar-thumb:hover {{
      background: rgba(120, 111, 98, 0.45);
    }}
    .section {{
      padding: 12px 14px;
      border-bottom: 1px solid var(--line);
    }}
    .section:last-child {{ border-bottom: none; }}
    h1 {{
      margin: 0 0 4px;
      font-size: 20px;
      line-height: 1.2;
    }}
    #subtitle {{
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      display: block;
      max-width: 100%;
    }}
    .muted {{
      color: var(--muted);
      font-size: 12px;
    }}
    .stats {{
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
      margin-top: 0;
    }}
    .report-box {{
      margin-top: 8px;
      border: 1px solid var(--line);
      border-radius: 14px;
      background: rgba(250, 248, 244, 0.78);
      overflow: hidden;
    }}
    .report-summary {{
      width: 100%;
      border: none;
      background: transparent;
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 9px 10px;
      cursor: pointer;
      font: inherit;
      color: inherit;
      text-align: left;
    }}
    .report-summary:hover {{
      background: rgba(255,255,255,0.45);
    }}
    .report-title {{
      font-size: 11px;
      font-weight: 700;
      color: var(--ink);
    }}
    .report-caret {{
      color: var(--muted);
      font-size: 12px;
    }}
    .report-content {{
      padding: 0 10px 8px;
      border-top: 1px solid rgba(31,41,51,0.06);
    }}
    .report-box.collapsed .report-content {{
      display: none;
    }}
    .report-list {{
      display: grid;
      gap: 4px;
    }}
    .report-item {{
      font-size: 11px;
      color: var(--muted);
      line-height: 1.35;
    }}
    .report-item.warn {{
      color: #9a3412;
    }}
    .report-item.ok {{
      color: var(--ok);
    }}
    .meta-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 4px 10px;
      margin-top: 8px;
    }}
    .meta-item {{
      min-width: 0;
    }}
    .meta-label {{
      font-size: 10px;
      color: var(--muted);
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }}
    .meta-value {{
      margin-top: 1px;
      font-size: 12px;
      color: var(--ink);
      font-weight: 600;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}
    .chip {{
      padding: 6px 9px;
      border-radius: 999px;
      background: var(--chip);
      font-size: 11px;
      color: var(--muted);
    }}
    .controls {{
      display: grid;
      gap: 6px;
      background: rgba(250, 248, 244, 0.75);
      position: sticky;
      top: 0;
      z-index: 4;
      backdrop-filter: blur(10px);
    }}
    .controls input, .controls select {{
      width: 100%;
      border: 1px solid var(--line);
      background: #fff;
      border-radius: 10px;
      padding: 8px 10px;
      font: inherit;
      color: inherit;
      transition: border-color 120ms ease, box-shadow 120ms ease;
    }}
    .controls input:focus, .controls select:focus {{
      outline: none;
      border-color: rgba(179,71,45,0.48);
      box-shadow: 0 0 0 3px rgba(179,71,45,0.08);
    }}
    .toolbar {{
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
    }}
    .toolbar button {{
      border: 1px solid var(--line);
      background: #fff;
      border-radius: 999px;
      padding: 7px 11px;
      cursor: pointer;
      font: inherit;
      font-size: 12px;
      transition: border-color 120ms ease, background 120ms ease, color 120ms ease;
    }}
    .toolbar button:hover {{
      background: #f9f5ef;
    }}
    .toolbar button.active {{
      border-color: var(--accent);
      background: var(--accent-soft);
      color: var(--accent);
    }}
    .bom-list {{
      overflow: visible;
      padding: 8px 10px 10px;
      display: grid;
      gap: 8px;
      min-height: auto;
    }}
    .bom-row {{
      border: 1px solid var(--line);
      border-radius: 16px;
      background: rgba(255,255,255,0.88);
      padding: 12px;
      cursor: pointer;
      transition: transform 120ms ease, border-color 120ms ease, box-shadow 120ms ease, opacity 120ms ease, background 120ms ease;
    }}
    .bom-row:hover {{
      transform: translateY(-1px);
      box-shadow: 0 10px 25px rgba(31,41,51,0.08);
    }}
    .bom-row.active {{
      border-color: var(--accent);
      box-shadow: 0 12px 30px rgba(179,71,45,0.16);
      background: #fff7f2;
    }}
    .bom-row.match {{
      border-color: rgba(59,130,246,0.55);
      background: rgba(59,130,246,0.06);
    }}
    .bom-row.dim {{
      opacity: 0.72;
    }}
    .bom-row.done {{
      border-color: rgba(29,122,77,0.28);
      background: rgba(29,122,77,0.06);
    }}
    .bom-row.done.active {{
      box-shadow: 0 12px 30px rgba(29,122,77,0.12);
    }}
    .bom-row.locating {{
      animation: locatingPulse 0.9s ease;
    }}
    .bom-head {{
      display: flex;
      justify-content: space-between;
      gap: 8px;
      align-items: start;
      margin-bottom: 8px;
    }}
    .bom-title {{
      font-weight: 700;
      font-size: 18px;
      line-height: 1.25;
    }}
    .bom-meta {{
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
      margin-top: 10px;
    }}
    .tag {{
      border-radius: 999px;
      background: #f4efe8;
      color: #695748;
      padding: 4px 8px;
      font-size: 11px;
    }}
    .canvas-panel {{
      display: grid;
      grid-template-rows: auto minmax(0, 1fr);
      overflow: hidden;
    }}
    .canvas-toolbar {{
      padding: 12px 14px 8px;
      display: flex;
      justify-content: space-between;
      gap: 14px;
      align-items: center;
      flex-wrap: wrap;
      border-bottom: 1px solid var(--line);
      background: rgba(250, 248, 244, 0.72);
      position: relative;
      z-index: 3;
    }}
    .canvas-wrap {{
      padding: 10px 14px 14px;
      min-height: 0;
      background: rgba(226, 232, 240, 0.28);
      overflow: hidden;
      position: relative;
      z-index: 1;
    }}
    svg {{
      width: 100%;
      height: calc(100vh - 110px);
      min-height: 560px;
      border-radius: 18px;
      background:
        linear-gradient(90deg, rgba(255,255,255,0.6) 0 1px, transparent 1px 100%),
        linear-gradient(rgba(255,255,255,0.6) 0 1px, transparent 1px 100%),
        linear-gradient(180deg, #d9e3cf 0%, #c8d8b8 100%);
      background-size: 24px 24px, 24px 24px, 100% 100%;
      border: 1px solid var(--line);
      overflow: hidden;
      cursor: grab;
      touch-action: none;
      display: block;
    }}
    svg.dragging {{ cursor: grabbing; }}
    .legend {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      font-size: 12px;
      color: var(--muted);
      font-weight: 600;
    }}
    .dot {{
      display: inline-block;
      width: 10px;
      height: 10px;
      border-radius: 50%;
      margin-right: 6px;
      vertical-align: middle;
    }}
    .empty {{
      padding: 20px;
      color: var(--muted);
      text-align: center;
    }}
    .empty strong {{
      display: block;
      color: var(--ink);
      margin-bottom: 6px;
    }}
    .notice {{
      position: fixed;
      right: 24px;
      bottom: 24px;
      background: rgba(31,41,51,0.92);
      color: #fff;
      border-radius: 10px;
      padding: 10px 14px;
      font-size: 13px;
      box-shadow: 0 12px 30px rgba(31,41,51,0.2);
      opacity: 0;
      pointer-events: none;
      transform: translateY(6px);
      transition: opacity 140ms ease, transform 140ms ease;
    }}
    .notice.show {{
      opacity: 1;
      transform: translateY(0);
    }}
    .hover-tip {{
      position: fixed;
      z-index: 20;
      max-width: 320px;
      padding: 10px 12px;
      border-radius: 12px;
      background: rgba(31,41,51,0.94);
      color: #fff;
      box-shadow: 0 12px 28px rgba(31,41,51,0.24);
      font-size: 12px;
      line-height: 1.45;
      pointer-events: none;
      opacity: 0;
      transform: translateY(4px);
      transition: opacity 100ms ease, transform 100ms ease;
    }}
    .hover-tip.show {{
      opacity: 1;
      transform: translateY(0);
    }}
    .hover-tip strong {{
      display: block;
      font-size: 13px;
      margin-bottom: 4px;
    }}
    @keyframes locatingPulse {{
      0% {{ box-shadow: 0 0 0 0 rgba(239,68,68,0.0); }}
      20% {{ box-shadow: 0 0 0 4px rgba(239,68,68,0.28); }}
      100% {{ box-shadow: 0 0 0 0 rgba(239,68,68,0.0); }}
    }}
    @media (max-width: 1080px) {{
      .layout {{
        grid-template-columns: 1fr;
        height: auto;
      }}
      .sidebar {{
        grid-template-rows: auto auto minmax(320px, 1fr);
      }}
      svg {{
        height: 60vh;
        min-height: 420px;
      }}
    }}
    @media (max-height: 820px) {{
      .section {{
        padding: 8px 10px;
      }}
      h1 {{
        font-size: 18px;
      }}
      .stats {{
        margin-top: 6px;
      }}
      .meta-grid {{
        margin-top: 6px;
      }}
      .controls {{
        gap: 5px;
      }}
      .bom-title {{
        font-size: 16px;
      }}
    }}
  </style>
</head>
<body>
  <div class="layout">
    <aside class="panel sidebar">
      <section class="section">
        <h1 id="title">{title}</h1>
        <div class="muted" id="subtitle">{subtitle}</div>
        <div class="meta-grid" id="headerMeta">
          <div class="meta-item">
            <div class="meta-label">编写者</div>
            <div class="meta-value" id="metaAuthor">-</div>
          </div>
          <div class="meta-item">
            <div class="meta-label">版本 / 工具</div>
            <div class="meta-value" id="metaVersion">-</div>
          </div>
          <div class="meta-item">
            <div class="meta-label">创建时间</div>
            <div class="meta-value" id="metaCreatedAt">-</div>
          </div>
        </div>
        <div class="report-box collapsed" id="reportBox">
          <button type="button" class="report-summary" id="reportToggle">
            <span class="report-title">导入校验</span>
            <span class="report-caret" id="reportCaret">展开</span>
          </button>
          <div class="report-content">
            <div class="stats" id="stats">{stats}</div>
            <div class="report-list" id="reportList"></div>
          </div>
        </div>
      </section>
      <section class="section controls">
        <input id="searchInput" type="search" placeholder="搜索位号、料号、描述、封装">
        <select id="statusFilter">
          <option value="all">全部状态</option>
          <option value="todo">未标记</option>
          <option value="done">已标记</option>
        </select>
        <div id="imageOpacityRow" class="muted" style="display:flex; align-items:center; gap:10px;">
          <span style="white-space:nowrap;">底图透明度</span>
          <input id="imageOpacity" type="range" min="0" max="100" value="88" style="padding:0; flex:1;">
        </div>
        <div class="toolbar">
          <button type="button" data-side="top" class="active">Top</button>
          <button type="button" data-side="bottom">Bottom</button>
          <button type="button" id="toggleImage">隐藏板图</button>
          <button type="button" id="togglePlacedOnly">仅显示有坐标</button>
          <button type="button" id="exportVisibleCsv">导出CSV</button>
          <button type="button" id="exportVisibleXlsx">导出XLSX</button>
          <button type="button" id="clearDone" onclick="window.__ibomClearDone && window.__ibomClearDone()">清空进度</button>
        </div>
      </section>
      <section class="bom-list" id="bomList">{bom_list}</section>
    </aside>
    <main class="panel canvas-panel">
      <div class="canvas-toolbar">
        <div>
          <div id="selectionTitle"><strong>选择一条 BOM 记录</strong></div>
          <div class="muted" id="selectionMeta">点击左侧记录后，在右侧高亮器件位置。滚轮缩放，拖动画布。</div>
        </div>
        <div class="legend">
          <span><span class="dot" style="background:#3b82f6"></span>未选器件</span>
          <span><span class="dot" style="background:#ef4444"></span>当前 BOM</span>
          <span><span class="dot" style="background:#16a34a"></span>已标记</span>
        </div>
        <div class="toolbar">
          <button type="button" id="toggleCurrentOnly">仅当前 BOM</button>
          <button type="button" id="resetView">复位视图</button>
        </div>
      </div>
      <div class="canvas-wrap">
        <svg id="boardView" viewBox="0 0 1000 700" preserveAspectRatio="xMidYMid meet">
          <g id="sceneLayer">
            <image id="boardImage" x="40" y="40" width="920" height="620" preserveAspectRatio="none"></image>
            <g id="boardFrame"></g>
            <g id="componentLayer"></g>
          </g>
        </svg>
      </div>
    </main>
  </div>
  <div id="notice" class="notice"></div>
  <div id="hoverTip" class="hover-tip"></div>
  <script id="payload" type="application/json">{payload}</script>
  <script>
    try {{
    const data = JSON.parse(document.getElementById("payload").textContent);
    const topPlacement = data.imagePlacement && data.imagePlacement.top ? data.imagePlacement.top : null;
    const hasImages = !!((data.images && data.images.top) || (data.images && data.images.bottom));
    const hasBottomComponents = data.components.some((item) => item.side === "bottom");
    const state = {{
      side: "top",
      search: "",
      status: "all",
      boardMode: "all",
      imageVisible: hasImages,
      imageOpacity: topPlacement && typeof topPlacement.opacity === "number" ? topPlacement.opacity : 0.88,
      placedOnly: false,
      selectedBomId: null,
      searchAnchorBomId: null,
      done: loadDoneState(),
    }};

    const titleEl = document.getElementById("title");
    const subtitleEl = document.getElementById("subtitle");
    const metaAuthorEl = document.getElementById("metaAuthor");
    const metaVersionEl = document.getElementById("metaVersion");
    const metaCreatedAtEl = document.getElementById("metaCreatedAt");
    const statsEl = document.getElementById("stats");
    const reportListEl = document.getElementById("reportList");
    const reportBoxEl = document.getElementById("reportBox");
    const reportToggleEl = document.getElementById("reportToggle");
    const reportCaretEl = document.getElementById("reportCaret");
    const searchInput = document.getElementById("searchInput");
    const statusFilter = document.getElementById("statusFilter");
    const imageOpacityInput = document.getElementById("imageOpacity");
    const imageOpacityRow = document.getElementById("imageOpacityRow");
    const bomList = document.getElementById("bomList");
    const selectionTitle = document.getElementById("selectionTitle");
    const selectionMeta = document.getElementById("selectionMeta");
    const boardImage = document.getElementById("boardImage");
    const boardFrame = document.getElementById("boardFrame");
    const componentLayer = document.getElementById("componentLayer");
    const svg = document.getElementById("boardView");
    const sceneLayer = document.getElementById("sceneLayer");
    const notice = document.getElementById("notice");
    const hoverTip = document.getElementById("hoverTip");
    const sideButtons = [...document.querySelectorAll("[data-side]")];
    const toggleImageButton = document.getElementById("toggleImage");
    const placedOnlyButton = document.getElementById("togglePlacedOnly");
    const exportVisibleCsvButton = document.getElementById("exportVisibleCsv");
    const exportVisibleXlsxButton = document.getElementById("exportVisibleXlsx");
    const toggleCurrentOnlyButton = document.getElementById("toggleCurrentOnly");
    const clearDoneButton = document.getElementById("clearDone");
    const resetViewButton = document.getElementById("resetView");
    const viewBox = {{ x: 0, y: 0, width: 1000, height: 700 }};
    const zoomConfig = {{ minScale: 1, maxScale: 12, step: 1.2 }};
    const viewport = {{ scale: 1, tx: 0, ty: 0 }};
    const dragState = {{ active: false, startX: 0, startY: 0, originTx: 0, originTy: 0 }};
    let suppressDrag = false;

    function getShortPathLabel(kind, fullPath) {{
      if (!fullPath) {{
        return "";
      }}
      const normalized = String(fullPath).replace(/\\/g, "/");
      const parts = normalized.split("/").filter(Boolean);
      const fileName = parts.length ? parts[parts.length - 1] : normalized;
      return `${kind}: ${fileName}`;
    }}

    titleEl.textContent = data.meta.title;
    const sourceLabels = [
      getShortPathLabel("BOM", data.meta.sourceBom),
      getShortPathLabel("坐标", data.meta.sourcePlacement),
      getShortPathLabel("IPC", data.meta.sourceIpc),
    ].filter(Boolean);
    subtitleEl.textContent = sourceLabels.join(" | ");
    subtitleEl.title = [data.meta.sourceBom, data.meta.sourcePlacement, data.meta.sourceIpc].filter(Boolean).join("\n");
    metaAuthorEl.textContent = data.meta.author || "-";
    metaVersionEl.textContent = `${data.meta.version || "-"} / ${data.meta.toolVersion || "-"}`;
    metaCreatedAtEl.textContent = data.meta.createdAt || "-";
    renderStats();
    renderReport();
    imageOpacityInput.value = String(Math.round(state.imageOpacity * 100));
    if (!hasImages) {{
      imageOpacityRow.style.display = "none";
      toggleImageButton.style.display = "none";
    }}
    if (!hasBottomComponents) {{
      sideButtons.forEach((button) => {{
        if (button.dataset.side === "bottom") {{
          button.style.display = "none";
        }}
      }});
    }}

    searchInput.addEventListener("input", () => {{
      state.search = searchInput.value.trim().toLowerCase();
      if (state.search) {{
        state.selectedBomId = null;
        const firstMatch = getSearchMatches()[0];
        state.searchAnchorBomId = firstMatch ? firstMatch.id : null;
      }} else {{
        state.searchAnchorBomId = null;
      }}
      render();
    }});

    statusFilter.addEventListener("change", () => {{
      state.status = statusFilter.value;
      if (state.search) {{
        const firstMatch = getSearchMatches()[0];
        state.searchAnchorBomId = firstMatch ? firstMatch.id : null;
      }}
      render();
    }});

    imageOpacityInput.addEventListener("input", () => {{
      state.imageOpacity = Number(imageOpacityInput.value) / 100;
      renderBoard();
    }});

    reportToggleEl.addEventListener("click", () => {{
      const collapsed = reportBoxEl.classList.toggle("collapsed");
      reportCaretEl.textContent = collapsed ? "展开" : "收起";
    }});

    sideButtons.forEach((button) => {{
      button.addEventListener("click", () => {{
        state.side = button.dataset.side;
        sideButtons.forEach((item) => item.classList.toggle("active", item === button));
        if (state.search) {{
          const firstMatch = getSearchMatches()[0];
          state.searchAnchorBomId = firstMatch ? firstMatch.id : null;
        }}
        renderBoard();
        renderList();
      }});
    }});

    placedOnlyButton.addEventListener("click", () => {{
      state.placedOnly = !state.placedOnly;
      placedOnlyButton.classList.toggle("active", state.placedOnly);
      if (state.search) {{
        const firstMatch = getSearchMatches()[0];
        state.searchAnchorBomId = firstMatch ? firstMatch.id : null;
      }}
      render();
    }});

    exportVisibleCsvButton.addEventListener("click", () => {{
      exportCurrentRows("csv");
    }});
    exportVisibleXlsxButton.addEventListener("click", () => {{
      exportCurrentRows("xlsx");
    }});

    toggleCurrentOnlyButton.addEventListener("click", () => {{
      if (state.boardMode === "all") {{
        if (state.selectedBomId === null) {{
          showNotice("请先选择一条 BOM 记录");
          return;
        }}
        state.boardMode = "current";
        toggleCurrentOnlyButton.classList.add("active");
        toggleCurrentOnlyButton.textContent = "显示全板";
      }} else {{
        state.boardMode = "all";
        toggleCurrentOnlyButton.classList.remove("active");
        toggleCurrentOnlyButton.textContent = "仅当前 BOM";
      }}
      renderBoard();
    }});

    toggleImageButton.addEventListener("click", () => {{
      state.imageVisible = !state.imageVisible;
      toggleImageButton.classList.toggle("active", !state.imageVisible);
      toggleImageButton.textContent = state.imageVisible ? "隐藏板图" : "显示板图";
      renderBoard();
    }});

    resetViewButton.addEventListener("click", () => {{
      resetViewport();
      updateSceneTransform();
      showNotice("视图已复位");
    }});

    function loadDoneState() {{
      try {{
        return JSON.parse(localStorage.getItem(`ibom-progress:${data.meta.projectKey}`) || "{{}}");
      }} catch (error) {{
        return {{}};
      }}
    }}

    function persistDoneState() {{
      localStorage.setItem(`ibom-progress:${data.meta.projectKey}`, JSON.stringify(state.done));
    }}

    function renderStats() {{
      const doneCount = data.bomRows.filter((row) => !!state.done[row.id]).length;
      const totalCount = data.stats.groupCount || 0;
      const remainingCount = Math.max(totalCount - doneCount, 0);
      const percent = totalCount ? Math.round((doneCount / totalCount) * 100) : 0;
      const doneRefCount = data.bomRows.reduce((sum, row) => sum + (state.done[row.id] ? (row.references || []).length : 0), 0);
      const visibleRows = getVisibleRows();
      const matchedRows = getSearchMatches();
      statsEl.innerHTML = `
        <span class="chip">BOM分组 ${data.stats.groupCount}</span>
        <span class="chip">位号 ${data.stats.referenceCount}</span>
        <span class="chip">有坐标 ${data.stats.placedReferenceCount}</span>
        <span class="chip">未定位 ${data.stats.unplacedReferenceCount || 0}</span>
        <span class="chip">已完成 ${doneCount}/${totalCount} (${percent}%)</span>
        <span class="chip">剩余 ${remainingCount}</span>
        <span class="chip">完成位号 ${doneRefCount}</span>
        <span class="chip">当前可见 ${visibleRows.length}</span>
        ${state.search ? `<span class="chip">搜索命中 ${matchedRows.length}</span>` : ""}
        <span class="chip">测试点 ${data.meta.testPointsExcluded ? "已剔除" : "保留"}</span>
      `;
    }}

    function renderReport() {{
      if (!reportListEl) {{
        return;
      }}
      const entries = [];
      const summary = data.report && data.report.summary ? data.report.summary : null;
      if (summary) {{
        entries.push(`<div class="report-item ok">BOM ${summary.groupCount} 组，位号 ${summary.referenceCount}，已定位 ${summary.placedReferenceCount}，Top ${summary.topComponentCount}，Bottom ${summary.bottomComponentCount}。</div>`);
        if ((summary.filteredTestPointCount || 0) > 0) {{
          entries.push(`<div class="report-item">测试点已剔除 ${summary.filteredTestPointCount} 组，板框${summary.hasBoardOutline ? "已识别" : "未识别"}。</div>`);
        }} else {{
          entries.push(`<div class="report-item ${summary.hasBoardOutline ? "ok" : "warn"}">板框${summary.hasBoardOutline ? "已识别" : "未识别"}。</div>`);
        }}
      }}
      ((data.report && data.report.warnings) || []).forEach((message) => {{
        entries.push(`<div class="report-item warn">警告：${escapeHtml(message)}</div>`);
      }});
      if (!entries.length) {{
        entries.push(`<div class="report-item ok">导入检查通过，未发现明显问题。</div>`);
      }}
      reportListEl.innerHTML = entries.join("");
    }}

    function showNotice(message) {{
      if (!notice) {{
        return;
      }}
      notice.textContent = message;
      notice.classList.add("show");
      window.clearTimeout(showNotice.timer);
      showNotice.timer = window.setTimeout(() => {{
        notice.classList.remove("show");
      }}, 1400);
    }}

    function showHoverTip(event, item) {{
      if (!hoverTip) {{
        return;
      }}
      const row = data.bomRows.find((entry) => entry.id === item.bomId) || null;
      const valueText = row ? getRowDisplayTitle(row) : "-";
      const modelText = row ? getRowModelText(row) : "";
      const footprintText = row ? (row.footprint || "-") : "-";
      const sideText = item.side === "top" ? "Top" : item.side === "bottom" ? "Bottom" : "未知";
      const coordText = item.x === null || item.y === null ? "-" : `${formatCoord(item.x)}, ${formatCoord(item.y)}`;
      const doneText = state.done[item.bomId] ? "已标记" : "未标记";
      hoverTip.innerHTML = `
        <strong>${escapeHtml(item.refdes)}</strong>
        <div>值: ${escapeHtml(valueText)}</div>
        ${modelText ? `<div>型号: ${escapeHtml(modelText)}</div>` : ""}
        <div>封装: ${escapeHtml(footprintText)}</div>
        <div>面别: ${escapeHtml(sideText)}</div>
        <div>坐标: ${escapeHtml(coordText)}</div>
        <div>状态: ${escapeHtml(doneText)}</div>
      `;
      const offset = 14;
      const maxWidth = 320;
      const viewportWidth = window.innerWidth || document.documentElement.clientWidth || 1280;
      const viewportHeight = window.innerHeight || document.documentElement.clientHeight || 720;
      let left = event.clientX + offset;
      let top = event.clientY + offset;
      if (left + maxWidth > viewportWidth - 12) {{
        left = Math.max(12, event.clientX - maxWidth - offset);
      }}
      if (top + 110 > viewportHeight - 12) {{
        top = Math.max(12, event.clientY - 110 - offset);
      }}
      hoverTip.style.left = `${left}px`;
      hoverTip.style.top = `${top}px`;
      hoverTip.classList.add("show");
    }}

    function hideHoverTip() {{
      if (!hoverTip) {{
        return;
      }}
      hoverTip.classList.remove("show");
    }}

    function clearDoneState() {{
      state.done = {{}};
      try {{
        localStorage.removeItem(`ibom-progress:${data.meta.projectKey}`);
      }} catch (error) {{
      }}
      render();
      showNotice("进度已清空");
    }}

    window.__ibomClearDone = clearDoneState;

    clearDoneButton.addEventListener("click", () => {{
      if (!Object.keys(state.done).length) {{
        return;
      }}
      clearDoneState();
    }});

    function toggleDone(bomId) {{
      if (state.done[bomId]) {{
        delete state.done[bomId];
      }} else {{
        state.done[bomId] = true;
      }}
      persistDoneState();
      renderStats();
      renderList();
      renderBoard();
    }}

    function getSearchTokens() {{
      if (!state.search) {{
        return [];
      }}
      return state.search
        .split(/[\s,;，；、]+/)
        .map((token) => token.trim())
        .filter(Boolean);
    }}

    function isMultiSearch() {{
      return getSearchTokens().length > 1;
    }}

    function rowMatchesSearch(row) {{
      const tokens = getSearchTokens();
      if (!tokens.length) {{
        return true;
      }}
      const rawText = [
        row.description,
        row.value,
        row.part,
        row.footprint,
        row.manufacturer,
        row.manufacturerPn,
        row.references.join(" "),
      ].join(" ").toLowerCase();
      const refs = (row.references || []).map((ref) => String(ref).toLowerCase());
      return tokens.some((token) => {{
        if (refs.includes(token)) {{
          return true;
        }}
        return rawText.includes(token);
      }});
    }}

    function getVisibleRows() {{
      return data.bomRows.filter((row) => {{
        if (state.status === "done" && !state.done[row.id]) return false;
        if (state.status === "todo" && state.done[row.id]) return false;
        if (state.placedOnly) {{
          const hasPlaced = row.references.some((ref) => {{
            const component = data.components.find((item) => item.refdes === ref);
            return component && component.x !== null && component.y !== null;
          }});
          if (!hasPlaced) return false;
        }}
        if (state.side) {{
          const sideRefs = row.references.some((ref) => {{
            const component = data.components.find((item) => item.refdes === ref);
            return component && (component.side === state.side || component.side === "unknown");
          }});
          if (!sideRefs && data.components.length) return false;
        }}
        return true;
      }});
    }}

    function getSearchMatches() {{
      return getVisibleRows().filter((row) => rowMatchesSearch(row));
    }}

    function normalizeDisplayToken(token) {{
      return token
        .replace(/\\s+/g, "")
        .replace(/UF/g, "uF")
        .replace(/NF/g, "nF")
        .replace(/PF/g, "pF")
        .replace(/MH/g, "mH")
        .replace(/UH/g, "uH");
    }}

    function csvEscape(value) {{
      const text = value === null || value === undefined ? "" : String(value);
      return `"${text.replace(/"/g, '""')}"`;
    }}

    function getExportRows() {{
      const rows = state.search ? getSearchMatches() : getVisibleRows();
      if (!rows.length) {{
        showNotice("当前没有可导出的 BOM 记录");
        return null;
      }}
      return rows;
    }}

    function triggerDownload(blob, fileName) {{
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = fileName;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
    }}

    function buildExportFileBase() {{
      const stamp = new Date().toISOString().slice(0, 19).replace(/[T:]/g, "-");
      const baseName = (data.meta.project || data.meta.title || "interactive_bom").replace(/[^a-zA-Z0-9._-]+/g, "_");
      return `${baseName}_filtered_${stamp}`;
    }}

    function exportCurrentRows(format) {{
      const rows = getExportRows();
      if (!rows) {{
        return;
      }}
      const headers = ["值", "型号", "位号", "数量", "封装", "厂家", "厂家料号", "描述"];
      const tableRows = rows.map((row) => ([
          extractPreferredDisplayValue(row),
          row.part || "",
          (row.references || []).join(", "),
          row.quantity ?? "",
          row.footprint || "",
          row.manufacturer || "",
          row.manufacturerPn || "",
          row.description || "",
        ]));
      if (format === "xlsx") {{
        const blob = buildXlsxBlob(headers, tableRows);
        triggerDownload(blob, `${buildExportFileBase()}.xlsx`);
        showNotice(`已导出 ${rows.length} 条 BOM 记录 (XLSX)`);
        return;
      }}
      const lines = [headers.map(csvEscape).join(",")];
      tableRows.forEach((cells) => {{
        lines.push(cells.map(csvEscape).join(","));
      }});
      const csvContent = "\uFEFF" + lines.join("\r\n");
      const blob = new Blob([csvContent], {{ type: "text/csv;charset=utf-8;" }});
      triggerDownload(blob, `${buildExportFileBase()}.csv`);
      showNotice(`已导出 ${rows.length} 条 BOM 记录 (CSV)`);
    }}

    const CRC_TABLE = (() => {{
      const table = new Uint32Array(256);
      for (let i = 0; i < 256; i += 1) {{
        let c = i;
        for (let j = 0; j < 8; j += 1) {{
          c = (c & 1) ? (0xedb88320 ^ (c >>> 1)) : (c >>> 1);
        }}
        table[i] = c >>> 0;
      }}
      return table;
    }})();

    function crc32(bytes) {{
      let crc = 0xffffffff;
      for (const b of bytes) {{
        crc = CRC_TABLE[(crc ^ b) & 0xff] ^ (crc >>> 8);
      }}
      return (crc ^ 0xffffffff) >>> 0;
    }}

    function numberToBytes(value, length) {{
      const bytes = new Uint8Array(length);
      for (let i = 0; i < length; i += 1) {{
        bytes[i] = (value >>> (8 * i)) & 0xff;
      }}
      return bytes;
    }}

    function dosDateTime(date) {{
      const year = Math.max(1980, date.getFullYear());
      const dosTime = ((date.getHours() & 0x1f) << 11) | ((date.getMinutes() & 0x3f) << 5) | Math.floor(date.getSeconds() / 2);
      const dosDate = (((year - 1980) & 0x7f) << 9) | (((date.getMonth() + 1) & 0x0f) << 5) | (date.getDate() & 0x1f);
      return {{ dosTime, dosDate }};
    }}

    function concatArrays(parts) {{
      const total = parts.reduce((sum, part) => sum + part.length, 0);
      const merged = new Uint8Array(total);
      let offset = 0;
      parts.forEach((part) => {{
        merged.set(part, offset);
        offset += part.length;
      }});
      return merged;
    }}

    function buildStoredZip(entries) {{
      const encoder = new TextEncoder();
      const locals = [];
      const centrals = [];
      let offset = 0;
      const now = dosDateTime(new Date());
      entries.forEach((entry) => {{
        const nameBytes = encoder.encode(entry.name);
        const dataBytes = typeof entry.data === "string" ? encoder.encode(entry.data) : entry.data;
        const crc = crc32(dataBytes);
        const localHeader = concatArrays([
          numberToBytes(0x04034b50, 4),
          numberToBytes(20, 2),
          numberToBytes(0, 2),
          numberToBytes(0, 2),
          numberToBytes(now.dosTime, 2),
          numberToBytes(now.dosDate, 2),
          numberToBytes(crc, 4),
          numberToBytes(dataBytes.length, 4),
          numberToBytes(dataBytes.length, 4),
          numberToBytes(nameBytes.length, 2),
          numberToBytes(0, 2),
          nameBytes,
        ]);
        const localRecord = concatArrays([localHeader, dataBytes]);
        locals.push(localRecord);
        const centralHeader = concatArrays([
          numberToBytes(0x02014b50, 4),
          numberToBytes(20, 2),
          numberToBytes(20, 2),
          numberToBytes(0, 2),
          numberToBytes(0, 2),
          numberToBytes(now.dosTime, 2),
          numberToBytes(now.dosDate, 2),
          numberToBytes(crc, 4),
          numberToBytes(dataBytes.length, 4),
          numberToBytes(dataBytes.length, 4),
          numberToBytes(nameBytes.length, 2),
          numberToBytes(0, 2),
          numberToBytes(0, 2),
          numberToBytes(0, 2),
          numberToBytes(0, 2),
          numberToBytes(0, 4),
          numberToBytes(offset, 4),
          nameBytes,
        ]);
        centrals.push(centralHeader);
        offset += localRecord.length;
      }});
      const centralBytes = concatArrays(centrals);
      const localBytes = concatArrays(locals);
      const endRecord = concatArrays([
        numberToBytes(0x06054b50, 4),
        numberToBytes(0, 2),
        numberToBytes(0, 2),
        numberToBytes(entries.length, 2),
        numberToBytes(entries.length, 2),
        numberToBytes(centralBytes.length, 4),
        numberToBytes(localBytes.length, 4),
        numberToBytes(0, 2),
      ]);
      return concatArrays([localBytes, centralBytes, endRecord]);
    }}

    function xmlEscape(text) {{
      return String(text)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&apos;");
    }}

    function buildWorksheetXml(headers, rows) {{
      const allRows = [headers, ...rows];
      const rowXml = allRows.map((cells, rowIndex) => {{
        const cellXml = cells.map((value, cellIndex) => {{
          const ref = `${String.fromCharCode(65 + cellIndex)}${rowIndex + 1}`;
          const text = value === null || value === undefined ? "" : String(value);
          if (/^-?\d+(?:\.\d+)?$/.test(text)) {{
            return `<c r="${ref}"><v>${text}</v></c>`;
          }}
          return `<c r="${ref}" t="inlineStr"><is><t xml:space="preserve">${xmlEscape(text)}</t></is></c>`;
        }}).join("");
        return `<row r="${rowIndex + 1}">${cellXml}</row>`;
      }}).join("");
      return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>${rowXml}</sheetData></worksheet>`;
    }}

    function buildXlsxBlob(headers, rows) {{
      const worksheetXml = buildWorksheetXml(headers, rows);
      const workbookName = xmlEscape(data.meta.title || "Interactive BOM");
      const entries = [
        {{
          name: "[Content_Types].xml",
          data: `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>`,
        }},
        {{
          name: "_rels/.rels",
          data: `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>`,
        }},
        {{
          name: "docProps/app.xml",
          data: `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <Application>Cadence Interactive BOM</Application>
</Properties>`,
        }},
        {{
          name: "docProps/core.xml",
          data: `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:dcmitype="http://purl.org/dc/dcmitype/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>${workbookName}</dc:title>
  <dc:creator>${xmlEscape(data.meta.author || "Codex")}</dc:creator>
  <cp:lastModifiedBy>${xmlEscape(data.meta.author || "Codex")}</cp:lastModifiedBy>
  <dcterms:created xsi:type="dcterms:W3CDTF">${new Date().toISOString()}</dcterms:created>
  <dcterms:modified xsi:type="dcterms:W3CDTF">${new Date().toISOString()}</dcterms:modified>
</cp:coreProperties>`,
        }},
        {{
          name: "xl/_rels/workbook.xml.rels",
          data: `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>`,
        }},
        {{
          name: "xl/workbook.xml",
          data: `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="BOM" sheetId="1" r:id="rId1"/>
  </sheets>
</workbook>`,
        }},
        {{
          name: "xl/styles.xml",
          data: `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>
  <fills count="1"><fill><patternFill patternType="none"/></fill></fills>
  <borders count="1"><border/></borders>
  <cellStyleXfs count="1"><xf/></cellStyleXfs>
  <cellXfs count="1"><xf xfId="0"/></cellXfs>
  <cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>`,
        }},
        {{ name: "xl/worksheets/sheet1.xml", data: worksheetXml }},
      ];
      return new Blob([buildStoredZip(entries)], {{
        type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      }});
    }}

    function extractPreferredDisplayValue(row) {{
      if (row.value) {{
        return row.value.trim();
      }}
      const candidates = [row.part || "", row.description || ""];
      const patterns = [
        /\b\d+(?:\.\d+)?\s*[pnumkM]?F\s*\/\s*\d+(?:\.\d+)?V\b/i,
        /\b\d+(?:\.\d+)?\s*[pnumkM]?H\b/i,
        /\b\d+(?:\.\d+)?\s*[RKM](?:\d+)?\b/i,
        /\b0R\b/i,
      ];
      for (const text of candidates) {{
        for (const pattern of patterns) {{
          const match = text.match(pattern);
          if (match) {{
            return normalizeDisplayToken(match[0].toUpperCase());
          }}
        }}
      }}
      if (row.part) {{
        const simplified = row.part.split(/[_\\s-]/)[0].trim();
        if (simplified) {{
          return simplified;
        }}
      }}
      return "";
    }}

    function getRowDisplayTitle(row) {{
      return extractPreferredDisplayValue(row) || row.manufacturerPn || row.part || row.description || "未命名器件";
    }}

    function getRowModelText(row) {{
      return row.manufacturerPn || row.part || "";
    }}

    function renderSelectionState() {{
      if (state.search) {{
        const matchedRows = getSearchMatches();
        selectionTitle.innerHTML = `<strong>搜索结果</strong>`;
        selectionMeta.textContent = isMultiSearch()
          ? `当前多关键词命中 ${matchedRows.length} 项，左侧列表仅显示命中 BOM。`
          : `当前搜索命中 ${matchedRows.length} 项。橙色为搜索命中，蓝色为其他可见器件，绿色为已标记。`;
        return;
      }}
      if (state.selectedBomId === null) {{
        selectionTitle.innerHTML = `<strong>选择一条 BOM 记录</strong>`;
        selectionMeta.textContent = '点击左侧记录后，在右侧高亮器件位置。滚轮缩放，拖动画布。';
        if (state.boardMode !== "all") {{
          state.boardMode = "all";
          toggleCurrentOnlyButton.classList.remove("active");
          toggleCurrentOnlyButton.textContent = "仅当前 BOM";
        }}
      }}
    }}

    function selectRow(bomId) {{
      state.selectedBomId = bomId;
      state.searchAnchorBomId = bomId;
      const row = data.bomRows.find((item) => item.id === bomId);
      if (!row) return;
      const selectedComps = data.components.filter((item) => item.bomId === bomId && item.x !== null && item.y !== null);
      const coordText = selectedComps.length
        ? selectedComps.slice(0, 3).map((item) => `${item.refdes} (${formatCoord(item.x)}, ${formatCoord(item.y)})`).join(" | ")
        : "无坐标";
      selectionTitle.innerHTML = `<strong style="color:var(--accent)">${escapeHtml(getRowDisplayTitle(row))}</strong>`;
      selectionMeta.textContent = `${row.references.join(", ")} | 封装 ${row.footprint || "-"} | ${coordText}`;
      renderList();
      renderBoard();
      setTimeout(() => {{
        const activeElement = bomList.querySelector(".bom-row.active");
        if (activeElement) {{
          activeElement.scrollIntoView({{ behavior: "smooth", block: "nearest" }});
          activeElement.classList.remove("locating");
          void activeElement.offsetWidth;
          activeElement.classList.add("locating");
        }}
      }}, 30);
    }}

    function renderList() {{
      const rows = isMultiSearch()
        ? getSearchMatches()
        : getVisibleRows();
      if (!rows.length) {{
        bomList.innerHTML = '<div class="empty"><strong>没有匹配记录</strong>请清空搜索条件，或切换状态后再试。</div>';
        selectionTitle.innerHTML = '<strong>没有匹配记录</strong>';
        selectionMeta.textContent = '当前筛选条件下没有 BOM 项。';
        return;
      }}
      renderSelectionState();
      bomList.innerHTML = rows.map((row) => {{
        const active = row.id === state.selectedBomId ? "active" : "";
        const done = state.done[row.id] ? "done" : "";
        const match = state.search && rowMatchesSearch(row) ? "match" : "";
        const dim = state.search && !rowMatchesSearch(row) ? "dim" : "";
        return `
          <article class="bom-row ${active} ${done} ${match} ${dim}" data-bom-id="${row.id}">
            <div class="bom-head">
              <div>
                <div class="bom-title">${escapeHtml(getRowDisplayTitle(row))}</div>
                ${getRowModelText(row) ? `<div class="muted">型号: ${escapeHtml(getRowModelText(row))}</div>` : ""}
              </div>
              <label class="chip">
                <input type="checkbox" data-done-id="${row.id}" ${state.done[row.id] ? "checked" : ""} style="accent-color:#1d7a4d;">
                完成
              </label>
            </div>
            <div class="muted">位号: ${escapeHtml(row.references.join(", "))}</div>
            <div class="bom-meta">
              <span class="tag">数量 ${row.quantity}</span>
              <span class="tag">封装 ${escapeHtml(row.footprint || "-")}</span>
            </div>
          </article>
        `;
      }}).join("");

      bomList.querySelectorAll("[data-bom-id]").forEach((element) => {{
        element.addEventListener("click", (event) => {{
          if (event.target instanceof HTMLInputElement) return;
          selectRow(Number(element.dataset.bomId));
        }});
      }});

      bomList.querySelectorAll("[data-done-id]").forEach((element) => {{
        element.addEventListener("change", (event) => {{
          event.stopPropagation();
          toggleDone(Number(element.dataset.doneId));
        }});
      }});

      if (state.search && state.searchAnchorBomId !== null) {{
        requestAnimationFrame(() => {{
          const target = bomList.querySelector(`[data-bom-id="${state.searchAnchorBomId}"]`);
          if (target) {{
            target.scrollIntoView({{ behavior: "smooth", block: "nearest" }});
            target.classList.remove("locating");
            void target.offsetWidth;
            target.classList.add("locating");
          }}
        }});
      }}
    }}

    function getBoardRect() {{
      const board = data.board;
      const width = board.maxX - board.minX || 100;
      const height = board.maxY - board.minY || 100;
      const padding = 40;
      const availWidth = 1000 - padding * 2;
      const availHeight = 700 - padding * 2;
      const scale = Math.min(availWidth / width, availHeight / height);
      const drawWidth = width * scale;
      const drawHeight = height * scale;
      return {{
        x: padding + (availWidth - drawWidth) / 2,
        y: padding + (availHeight - drawHeight) / 2,
        width: drawWidth,
        height: drawHeight,
        scale: scale,
        padding: padding,
      }};
    }}

    function clamp(value, min, max) {{
      return Math.min(max, Math.max(min, value));
    }}

    function resetViewport() {{
      viewport.scale = 1;
      viewport.tx = 0;
      viewport.ty = 0;
    }}

    function updateSceneTransform() {{
      sceneLayer.setAttribute(
        "transform",
        `translate(${viewport.tx.toFixed(2)} ${viewport.ty.toFixed(2)}) scale(${viewport.scale.toFixed(4)})`
      );
    }}

    function getSvgPoint(event) {{
      const rect = svg.getBoundingClientRect();
      const clientX = event.clientX !== undefined ? event.clientX : 0;
      const clientY = event.clientY !== undefined ? event.clientY : 0;
      return {{
        x: ((clientX - rect.left) / rect.width) * viewBox.width,
        y: ((clientY - rect.top) / rect.height) * viewBox.height,
      }};
    }}

    function zoomAtPoint(anchorX, anchorY, factor) {{
      const nextScale = clamp(viewport.scale * factor, zoomConfig.minScale, zoomConfig.maxScale);
      if (Math.abs(nextScale - viewport.scale) < 0.0001) {{
        return;
      }}
      const effectiveFactor = nextScale / viewport.scale;
      viewport.tx = anchorX - (anchorX - viewport.tx) * effectiveFactor;
      viewport.ty = anchorY - (anchorY - viewport.ty) * effectiveFactor;
      viewport.scale = nextScale;
      updateSceneTransform();
    }}

    svg.addEventListener("wheel", (event) => {{
      event.preventDefault();
      const point = getSvgPoint(event);
      const factor = event.deltaY < 0 ? zoomConfig.step : 1 / zoomConfig.step;
      zoomAtPoint(point.x, point.y, factor);
    }}, {{ passive: false }});

    svg.addEventListener("pointerdown", (event) => {{
      if (suppressDrag) {{
        suppressDrag = false;
        return;
      }}
      dragState.active = true;
      dragState.startX = event.clientX;
      dragState.startY = event.clientY;
      dragState.originTx = viewport.tx;
      dragState.originTy = viewport.ty;
      svg.classList.add("dragging");
      if (svg.setPointerCapture) {{
        svg.setPointerCapture(event.pointerId);
      }}
    }});

    svg.addEventListener("pointermove", (event) => {{
      if (!dragState.active) {{
        return;
      }}
      const rect = svg.getBoundingClientRect();
      const dx = ((event.clientX - dragState.startX) / rect.width) * viewBox.width;
      const dy = ((event.clientY - dragState.startY) / rect.height) * viewBox.height;
      viewport.tx = dragState.originTx + dx;
      viewport.ty = dragState.originTy + dy;
      updateSceneTransform();
    }});

    function stopDragging(event) {{
      if (!dragState.active) {{
        return;
      }}
      dragState.active = false;
      svg.classList.remove("dragging");
      if (event && svg.releasePointerCapture) {{
        try {{
          svg.releasePointerCapture(event.pointerId);
        }} catch (error) {{
        }}
      }}
    }}

    svg.addEventListener("pointerup", stopDragging);
    svg.addEventListener("pointerleave", stopDragging);
    svg.addEventListener("pointercancel", stopDragging);

    function renderBoard() {{
      if (window.edakitIBOM3D) window.edakitIBOM3D.sync();
      const board = data.board;
      const width = board.maxX - board.minX || 100;
      const height = board.maxY - board.minY || 100;
      const boardRect = getBoardRect();
      const padding = boardRect.padding;
      const placement = (data.imagePlacement && data.imagePlacement[state.side]) || {{
        x: boardRect.x,
        y: boardRect.y,
        width: boardRect.width,
        height: boardRect.height,
        opacity: 0.88,
      }};
      const imageHref = data.images[state.side] || "";
      boardImage.setAttribute("x", placement.x);
      boardImage.setAttribute("y", placement.y);
      boardImage.setAttribute("width", placement.width);
      boardImage.setAttribute("height", placement.height);
      boardImage.setAttribute("opacity", String(state.imageOpacity));
      if (hasImages && imageHref && state.imageVisible) {{
        boardImage.setAttributeNS("http://www.w3.org/1999/xlink", "href", imageHref);
        boardImage.setAttribute("visibility", "visible");
      }} else {{
        boardImage.removeAttributeNS("http://www.w3.org/1999/xlink", "href");
        boardImage.setAttribute("visibility", "hidden");
      }}

      let frameContent = `
        <rect x="${padding}" y="${padding}" width="${1000 - padding * 2}" height="${700 - padding * 2}" rx="24"
          fill="rgba(255,255,255,0.18)" stroke="rgba(31,41,51,0.18)" stroke-width="2"></rect>
      `;
      if (data.profile && data.profile.length > 2) {{
        const profilePath = data.profile.map((point, index) => {{
          let ratioX = (point.x - board.minX) / width;
          let ratioY = 1 - ((point.y - board.minY) / height);
          const px = boardRect.x + ratioX * boardRect.width;
          const py = boardRect.y + ratioY * boardRect.height;
          return `${index === 0 ? "M" : "L"} ${px.toFixed(2)} ${py.toFixed(2)}`;
        }}).join(" ");
        frameContent += `<path d="${profilePath} Z" fill="rgba(80,110,70,0.16)" stroke="rgba(37,58,35,0.55)" stroke-width="2.4"></path>`;
      }} else {{
        frameContent += `
          <rect x="${boardRect.x.toFixed(2)}" y="${boardRect.y.toFixed(2)}"
            width="${boardRect.width.toFixed(2)}" height="${boardRect.height.toFixed(2)}" rx="12"
            fill="rgba(80,110,70,0.14)" stroke="rgba(37,58,35,0.65)" stroke-width="2.4"></rect>
        `;
      }}
      boardFrame.innerHTML = frameContent;

      const visibleRows = new Set(getVisibleRows().map((row) => row.id));
      const matchedRows = new Set(getSearchMatches().map((row) => row.id));
      const selectedBomId = state.selectedBomId;
      const comps = data.components.filter((item) => {{
        const rowVisible = visibleRows.has(item.bomId);
        const sideVisible = item.side === state.side || item.side === "unknown" || !item.side;
        const modeVisible = state.boardMode === "current" ? item.bomId === selectedBomId : true;
        return rowVisible && sideVisible && modeVisible;
      }});

      componentLayer.innerHTML = comps.map((item) => {{
        if (item.x === null || item.y === null) return "";
        const selected = item.bomId === selectedBomId;
        const done = !!state.done[item.bomId];
        const matched = state.search && matchedRows.has(item.bomId);
        const stroke = selected ? "#ef4444" : done ? "#16a34a" : matched ? "#b45309" : "#3b82f6";
        const fill = selected ? "rgba(239,68,68,0.18)" : done ? "rgba(22,163,74,0.18)" : matched ? "rgba(245,158,11,0.18)" : "rgba(59,130,246,0.12)";
        let cx = null;
        let cy = null;
        let shapeMarkup = "";
        let padMarkup = "";
        const hasPads = item.padShapes && item.padShapes.length;
        // Show the actual body together with its pads, never the package
        // envelope. Prefer assembly body polygons; use silkscreen if absent.
        let bodyShapes = (item.drawingShapes || []).filter((shape) => shape.source === "assemblydrawing");
        if (bodyShapes.some((shape) => shape.type === "polygon")) {{
          bodyShapes = bodyShapes.filter((shape) => shape.type === "polygon");
        }}
        if (!bodyShapes.length) {{
          bodyShapes = (item.drawingShapes || []).filter((shape) => shape.source === "silkscreen");
        }}
        if (bodyShapes.length) {{
          shapeMarkup = bodyShapes.map((shape) => {{
            const pointsText = shape.points.map((point) => {{
              let ratioX = (point.x - board.minX) / width;
              let ratioY = 1 - ((point.y - board.minY) / height);
              const px = boardRect.x + ratioX * boardRect.width;
              const py = boardRect.y + ratioY * boardRect.height;
              if (cx === null) {{
                cx = px;
                cy = py;
              }}
              return `${px.toFixed(2)},${py.toFixed(2)}`;
            }}).join(" ");
            const widthPx = Math.max(shape.width ? shape.width * boardRect.scale : 0, selected ? 1.8 : 1.1);
            if (shape.type === "polyline") {{
              return `<polyline points="${pointsText}" fill="none" stroke="${stroke}" stroke-width="${widthPx.toFixed(2)}" stroke-linecap="round" stroke-linejoin="round"></polyline>`;
            }}
            return `<polygon points="${pointsText}" fill="${fill}" stroke="${stroke}" stroke-width="${widthPx.toFixed(2)}" stroke-linejoin="round"></polygon>`;
          }}).join("");
        }}
        if (!hasPads && !shapeMarkup && item.bbox) {{
          const minRatioX = (item.bbox.minX - board.minX) / width;
          const maxRatioX = (item.bbox.maxX - board.minX) / width;
          const minRatioY = (item.bbox.minY - board.minY) / height;
          const maxRatioY = (item.bbox.maxY - board.minY) / height;
          const leftRatio = minRatioX;
          const rightRatio = maxRatioX;
          const topRatio = 1 - maxRatioY;
          const bottomRatio = 1 - minRatioY;
          const x0 = boardRect.x + leftRatio * boardRect.width;
          const y0 = boardRect.y + topRatio * boardRect.height;
          const w0 = (rightRatio - leftRatio) * boardRect.width;
          const h0 = (bottomRatio - topRatio) * boardRect.height;
          cx = x0 + w0 / 2;
          cy = y0 + h0 / 2;
          shapeMarkup = `<rect x="${x0.toFixed(2)}" y="${y0.toFixed(2)}" width="${w0.toFixed(2)}" height="${h0.toFixed(2)}" fill="${fill}" stroke="${stroke}" stroke-width="${selected ? 2.6 : 1.5}"></rect>`;
        }}
        if (cx === null || cy === null) {{
          let ratioX = (item.x - board.minX) / width;
          let ratioY = 1 - ((item.y - board.minY) / height);
          cx = boardRect.x + ratioX * boardRect.width;
          cy = boardRect.y + ratioY * boardRect.height;
          if (!hasPads) shapeMarkup = `<circle cx="${cx.toFixed(2)}" cy="${cy.toFixed(2)}" r="${selected ? 6.5 : 4.5}" fill="${stroke}" fill-opacity="0.92" stroke="white" stroke-width="1.5"></circle>`;
        }}
        if (hasPads) {{
          padMarkup = item.padShapes.map((pad) => {{
            let ratioX = (pad.x - board.minX) / width;
            let ratioY = 1 - ((pad.y - board.minY) / height);
            const px = boardRect.x + ratioX * boardRect.width;
            const py = boardRect.y + ratioY * boardRect.height;
            const w = (pad.width / width) * boardRect.width;
            const h = (pad.height / height) * boardRect.height;
            if (pad.primitive === "circle") {{
              const r = Math.max((pad.diameter / width) * boardRect.width / 2, 1.2);
              return `<circle cx="${px.toFixed(2)}" cy="${py.toFixed(2)}" r="${r.toFixed(2)}" fill="rgba(179,71,45,0.10)" stroke="${stroke}" stroke-width="1.2"></circle>`;
            }}
            if (pad.primitive === "oval") {{
              return `<rect x="${(px - w / 2).toFixed(2)}" y="${(py - h / 2).toFixed(2)}" width="${Math.max(w,1.2).toFixed(2)}" height="${Math.max(h,1.2).toFixed(2)}" rx="${Math.max(Math.min(w,h)/2,0.8).toFixed(2)}" ry="${Math.max(Math.min(w,h)/2,0.8).toFixed(2)}" transform="rotate(${-pad.rotation.toFixed(2)} ${px.toFixed(2)} ${py.toFixed(2)})" fill="rgba(179,71,45,0.10)" stroke="${stroke}" stroke-width="1.2"></rect>`;
            }}
            return `<rect x="${(px - w / 2).toFixed(2)}" y="${(py - h / 2).toFixed(2)}" width="${Math.max(w,1.2).toFixed(2)}" height="${Math.max(h,1.2).toFixed(2)}" transform="rotate(${-pad.rotation.toFixed(2)} ${px.toFixed(2)} ${py.toFixed(2)})" fill="rgba(179,71,45,0.10)" stroke="${stroke}" stroke-width="1.2"></rect>`;
          }}).join("");
        }}
        return `
          <g class="component" data-refdes="${item.refdes}" data-bom-id="${item.bomId}">
            ${shapeMarkup}
            ${padMarkup}
            ${!hasPads ? `<circle cx="${cx.toFixed(2)}" cy="${cy.toFixed(2)}" r="${selected ? 3.5 : 2.2}" fill="${stroke}" stroke="white" stroke-width="1"></circle>` : ""}
            ${{(() => {{
              const label = item.refdesLabel;
              if (!selected || !label || label.side !== state.side) return "";
              const lx = boardRect.x + ((label.minX + label.maxX) / 2 - board.minX) * boardRect.scale;
              const ly = boardRect.y + (board.maxY - (label.minY + label.maxY) / 2) * boardRect.scale;
              const radians = label.rotation * Math.PI / 180;
              const vertical = Math.abs(Math.sin(radians)) > Math.abs(Math.cos(radians));
              const lw = (vertical ? label.maxY-label.minY : label.maxX-label.minX) * boardRect.scale;
              const lh = (vertical ? label.maxX-label.minX : label.maxY-label.minY) * boardRect.scale;
              return `<text class="refdes-silkscreen" x="0" y="0" text-anchor="middle" dominant-baseline="central" font-family="Arial,sans-serif" font-size="${{lh.toFixed(3)}}" textLength="${{lw.toFixed(3)}}" lengthAdjust="spacingAndGlyphs" fill="${{selected ? '#b42318' : '#4b5563'}}" transform="translate(${{lx.toFixed(3)}} ${{ly.toFixed(3)}}) rotate(${{-label.rotation}}) scale(${{label.mirrored ? -1 : 1}} 1)">${{escapeHtml(item.refdes)}}</text>`;
            }})()}}
          </g>
        `;
      }}).join("");

      componentLayer.querySelectorAll(".component").forEach((element) => {{
        element.style.cursor = "pointer";
        element.addEventListener("pointerdown", (event) => {{
          suppressDrag = true;
          event.stopPropagation();
        }});
        const item = comps.find((entry) => String(entry.bomId) === String(element.dataset.bomId) && entry.refdes === element.dataset.refdes);
        if (item) {{
          element.addEventListener("pointerenter", (event) => {{
            showHoverTip(event, item);
          }});
          element.addEventListener("pointermove", (event) => {{
            showHoverTip(event, item);
          }});
          element.addEventListener("pointerleave", () => {{
            hideHoverTip();
          }});
        }}
        element.addEventListener("click", () => {{
          hideHoverTip();
          selectRow(Number(element.dataset.bomId));
          showNotice("已从视图定位到 BOM");
        }});
      }});
      updateSceneTransform();
    }}

    function escapeHtml(value) {{
      return String(value)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
    }}

    function formatCoord(value) {{
      if (value === null || value === undefined) return "-";
      if (state.unit === "mil") return `${(value / 0.0254).toFixed(1)} mil`;
      return `${value.toFixed(3)} mm`;
    }}

    function render() {{
      renderStats();
      renderList();
      renderBoard();
    }}

    resetViewport();
    render();
    if (data.bomRows.length) {{
      selectRow(data.bomRows[0].id);
    }}
    window.__ibom3d = {{data, selectRow, readState: () => state, visible: () => getVisibleRows().map(row => row.id)}};
    }} catch (error) {{
      const bomList = document.getElementById("bomList");
      const selectionTitle = document.getElementById("selectionTitle");
      const selectionMeta = document.getElementById("selectionMeta");
      if (selectionTitle) {{
        selectionTitle.innerHTML = "<strong>页面脚本异常</strong>";
      }}
      if (selectionMeta) {{
        selectionMeta.textContent = String(error && error.message ? error.message : error);
      }}
      if (bomList) {{
        bomList.innerHTML = `<div class="empty"><strong>页面脚本异常</strong>${{escapeHtml(String(error && error.message ? error.message : error))}}</div>`;
      }}
      console.error(error);
    }}
  </script>
</body>
</html>
"""


def render_html(payload: dict) -> str:
    payload_json = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    def _short_source_label(kind: str, value: str | None) -> str:
        if not value:
            return ""
        return f"{kind}: {Path(value).name}"

    subtitle = " | ".join(
        value
        for value in [
            _short_source_label("BOM", payload["meta"].get("sourceBom")),
            _short_source_label("坐标", payload["meta"].get("sourcePlacement")),
            _short_source_label("IPC", payload["meta"].get("sourceIpc")),
        ]
        if value
    )
    page = HTML_TEMPLATE.replace("{title}", "__TITLE__")
    page = page.replace("{subtitle}", "__SUBTITLE__")
    page = page.replace("{stats}", "__STATS__")
    page = page.replace("{bom_list}", "__BOM_LIST__")
    page = page.replace("{payload}", "__PAYLOAD__")
    page = page.replace("{{", "{").replace("}}", "}")
    page = page.replace("__TITLE__", html.escape(payload["meta"]["title"]))
    page = page.replace("__SUBTITLE__", html.escape(subtitle))
    page = page.replace("__STATS__", render_initial_stats(payload))
    page = page.replace("__BOM_LIST__", render_initial_bom_list(payload))
    page = page.replace("__PAYLOAD__", payload_json)
    from .preview3d import embed
    return embed(page, payload)


def render_generation_report(payload: dict, output_path: Path, batch_id: str = "") -> str:
    meta = payload.get("meta", {})
    report = payload.get("report", {})
    summary = report.get("summary", {})
    warnings = report.get("warnings", [])
    info = report.get("info", [])
    lines = [
        "Cadence Interactive BOM 生成报告",
        "",
        f"批次号: {batch_id or '-'}",
        f"工具版本: {meta.get('toolVersion', '-')}",
        f"页面标题: {meta.get('title', '-')}",
        f"项目标识: {meta.get('projectKey', '-')}",
        f"编写者: {meta.get('author', '-') or '-'}",
        f"项目版本: {meta.get('version', '-') or '-'}",
        f"创建时间: {meta.get('createdAt', '-') or '-'}",
        "",
        "输入文件",
        f"BOM: {meta.get('sourceBom', '-') or '-'}",
        f"Placement: {meta.get('sourcePlacement', '-') or '-'}",
        f"IPC-2581: {meta.get('sourceIpc', '-') or '-'}",
        "",
        "输出文件",
        f"HTML: {output_path}",
        f"报告: {output_path.with_name(output_path.stem + ('_' + batch_id if batch_id else '') + '_report.txt')}",
        "",
        "导入校验摘要",
        f"BOM分组: {summary.get('groupCount', 0)}",
        f"位号总数: {summary.get('referenceCount', 0)}",
        f"已定位: {summary.get('placedReferenceCount', 0)}",
        f"未定位: {summary.get('unplacedReferenceCount', 0)}",
        f"Top器件: {summary.get('topComponentCount', 0)}",
        f"Bottom器件: {summary.get('bottomComponentCount', 0)}",
        f"未知面别器件: {summary.get('unknownSideCount', 0)}",
        f"剔除测试点分组: {summary.get('filteredTestPointCount', 0)}",
        f"识别到板框: {'是' if summary.get('hasBoardOutline') else '否'}",
        "",
        "提示信息",
    ]
    if info:
        lines.extend([f"- {item}" for item in info])
    else:
        lines.append("- 无")
    lines.extend(["", "警告信息"])
    if warnings:
        lines.extend([f"- {item}" for item in warnings])
    else:
        lines.append("- 无")
    return "\n".join(lines) + "\n"


def main() -> None:
    args = parse_args()
    options = resolve_runtime_options(args)
    issues = validate_runtime_options(options)
    if issues:
        raise SystemExit("\n".join(issues))
    payload = build_payload(options)
    options.output.parent.mkdir(parents=True, exist_ok=True)
    options.output.write_text(render_html(payload), encoding="utf-8")
    batch_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
    report_path = options.output.with_name(f"{options.output.stem}_{batch_id}_report.txt")
    report_path.write_text(render_generation_report(payload, options.output, batch_id=batch_id), encoding="utf-8")
    print(f"Generated: {options.output}")
    print(f"Report: {report_path}")


if __name__ == "__main__":
    main()
