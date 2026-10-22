# 诊断工具

正式入口为 src/edakit/install/templates/edakit.tcl；此目录提供诊断与原生验证辅助，不参与菜单启动。cef_probe_server.py 和 cef_probe_web 用于隔离 CEF 探测；edakit_cursor_diag.tcl 用于原生光标放置排障。运行任何辅助脚本前先阅读其参数与目标路径，不对用户工程批量运行实验。

旧 archive 已移到 E:/outputs/待清理/edakit-20261022/tools/diag/archive，由用户手动删除。当前架构及验证边界见 docs/项目交接.md。
