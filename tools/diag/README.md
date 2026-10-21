# 诊断工具

正式入口位于 `src/edakit/install/templates/edakit.tcl`，此目录不参与打包和菜单启动。

| 文件 | 用途 |
|---|---|
| cef_probe_server.py、cef_probe_web/ | 独立CEF能力探针，使用隔离运行目录 |
| edakit_cef_probe.tcl | 独立view/dock试验；重复open会重载，行为与正式面板不同 |
| edakit_cursor_diag.tcl | 原生光标放置排障，仅在实际异常时使用 |
| archive/pre-cef-baseline-20261021/ | 旧OpenURL/CEF/菜单/PlacePart/引脚实验和样本，按历史资料保留 |

日常使用正式菜单，不必source试验脚本。CEF探针操作见 `docs/CEF内嵌试验与验证.md`。历史脚本可能包含旧机器绝对路径或会执行放置，必须先阅读，不批量source。Tcl保持纯ASCII。
