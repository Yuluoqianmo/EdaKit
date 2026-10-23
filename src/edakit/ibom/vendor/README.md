# Offline iBOM 3D vendors

Unmodified runtime distributions:
- three.js 0.158.0, MIT: https://github.com/mrdoob/three.js/tree/r158
- occt-import-js 0.0.23 JavaScript + OpenCascade WASM, LGPL-2.1: https://github.com/kovacsv/occt-import-js

Files were obtained from the version-pinned npm distributions at unpkg.com.
The exported HTML embeds runtime code and license notices. STEP support and
WASM are included only if actual model data is present; no CDN is used at runtime.
Replace these files with compatible builds to replace the runtime library.
