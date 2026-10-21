"""部署子包。"""

from . import allegro_env  # noqa: F401
from .deploy import deploy, find_capture_tcl_root, target_dir, undeploy  # noqa: F401
