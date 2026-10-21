"""3D 模型处理子包 (STEP 下载 + 映射生成)。"""

from .mapping import (  # noqa: F401
    build_map_xml,
    calibrate_easyeda2kicad,
    calibrate_lcsc_converter,
)
from .step import StepFetcher  # noqa: F401
