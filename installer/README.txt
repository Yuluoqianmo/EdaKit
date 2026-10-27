EdaKit — Capture / Allegro 插件

安装前保存工程并退出 Capture 和 Allegro，选择目标 Cadence SPB 安装根目录。
安装完成后重新打开 Cadence，从 EdaKit 菜单使用商城、工程属性、BOM 和 Interactive BOM。
仅 17.2 完成原生验收；其他版本需要实际验证。

首次使用商城时，在设置中确认原理图、PCB 和 STEP 库路径。
卸载移除插件入口及 EdaKit 环境配置块，保留用户库、配置、BOM 和 HTML。

安装部署失败时，查看安装目录 deployment.log。修正后重新运行安装包。
更新程序后重新导出交互式 BOM，旧 HTML 不会自动更新。

器件属性：双击 Reference 定位原理图器件；拖拽单元格右下角填充柄向下复制属性。
编辑只修改草稿，点击“同步到 Capture”后才写入工程。

Capture 的 EdaKit → About EdaKit 可查看版本、检查更新、运行环境诊断并打开日志目录。
日志默认位于 %LOCALAPPDATA%\edakit。自动更新的真实跨版本覆盖安装尚待实机验收。

交互式 BOM 支持手机横竖屏、触屏缩放和平移。更新后请重新导出 HTML；旧文件不会自动更新。
