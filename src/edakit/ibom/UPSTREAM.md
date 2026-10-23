# Upstream renderer

Source: https://github.com/Yuluoqianmo/cadence-ibom

File: `generate_ibom.py`, blob `0b6c3bdb43426f04648077ac0aff6c3748fbc019`, v1.2.0 code supplied by the repository owner for reuse in this plugin.

Geometry corrections after native validation: Allegro IPC Component Location is the footprint origin, so PickupPoint centroid is no longer subtracted from local coordinates or placement. PolyStepCurve is sampled using its center and clockwise direction (maximum 2-degree step), rather than reduced to its endpoint. These corrections apply to the vendored copy only; native HTD100 pin coordinates were checked independently of upstream parity.

Reference labels use a native SKILL sidecar of REF DES/SILKSCREEN_TOP/BOTTOM text bounds, rotation and mirror state captured from the same current board. Original synthetic selected-component labels at a fixed 12px offset are removed. Browser glyphs are fitted to native bounds; absent labels are not invented. The original viewer's search, selection and BOM interaction are retained.

`reference.py` retains the original package parser with the native-validated coordinate and arc corrections described above. Local integration changes: disable the optional PDF import (this integration uses IPC geometry), escape HTML delimiters in embedded JSON, and display original parsed pad shapes for every component rather than only the selected BOM. Body borders prefer AssemblyDrawing polygons, then assembly lines or SilkScreen, without the Package Outline envelope or locator dots on components with pads. The previous parser layer-filtering change was reverted after comparison with the owner's local validated project. Native extraction, installation, export window, per-board settings and IPC-to-BOM adaptation are separate modules. No upstream repository is modified.
