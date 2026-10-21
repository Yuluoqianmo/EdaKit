# CEF workbench source

Run `python tools/build_web.py` after changes. `--check` checks freshness; packaging rejects stale bundles.

Numbered JavaScript modules are composed into one private closure in dependency order. There is no runtime loader, extra network request, or modern syntax dependency. Functions form the internal module contract; DOM event wiring stays in `10-events.js`. State is grouped by owner: catalog, selection, preview, layout, placement, feedback. Modules may read another owner's state through these explicit groups.

The two CSS layers preserve the tested cascade: legacy-compatible foundation and current workbench presentation. Do not append ad hoc release overrides; change the owning layer. The shipped files in `src/edakit/server/web` are generated artifacts used by source runs, wheels and frozen builds.

Continue to validate ES3 syntax plus XHR and legacy JSONP paths. The real Capture CEF has no usable WebGL, so server-rendered PNG previews remain the default.
