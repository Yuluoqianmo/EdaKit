EdaKit — Capture / Allegro 插件

安装前保存工程并退出 Capture 和 Allegro，选择目标 Cadence SPB 安装根目录。
安装完成后重新打开 Cadence，从 EdaKit 菜单使用商城、工程属性、BOM 和 Interactive BOM。
仅 17.2 完成原生验收；其他版本需要实际验证。

首次使用商城时，在设置中确认原理图、PCB 和 STEP 库路径。
卸载移除插件入口及 EdaKit 环境配置块，保留用户库、配置、BOM 和 HTML。

安装部署失败时，查看安装目录 deployment.log。修正后重新运行安装包。
更新程序后重新导出交互式 BOM，旧 HTML 不会自动更新。
