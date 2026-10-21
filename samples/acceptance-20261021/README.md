# 2026-10-21 隔离验收材料

用于跨电脑继续验证，非正式发布库。详见 ../../docs/回家接续开发-20261021.md。

- allegro：r3 C2040 Package Symbol 的 .dra/.psm、全部配套 .pad、pinmap 和编译日志。用户已确认创建、保存、编译、重开及人工几何核对。
- capture：P5R2 输入 XML、Capture 规范化 XML、最终 OLB 与回读 XML、名称和坐标映射。用户确认经原生 PlaceNew 放置显示正常；Place Part 面板曾显示散乱。
- screenshots：用户确认的 Allegro 重开及 Capture 原生放置截图。
- manifest.json：以上验收证据逐文件大小与 SHA256。

不含用户工作工程。包含的历史机器路径是测试证据，不是家中机器配置。请用仓库 tools/diag 的生成器重建本机脚本，按交接文档进行连线、网表和 PCB 导入验收。
