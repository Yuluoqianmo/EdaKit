# 独立原理图 PDF 调查

目标是在插件中独立生成带网络导航的原理图 PDF，不调用 Capture 的 PDF Export。

本机 Capture 17.2 的 Tcl 数据库接口可通过页面 `NewWiresIter` 遍历连线，`GetNetName` 获取网络名，`GetStartPoint` / `GetEndPoint` 获取坐标。`orPrmDboStreamer.tcl` 中的 `streamPage` 组织了线、总线、器件、端口、电源和跨页连接符，包含符号 master 和实例变换；这是有价值的参考，但属于 Cadence 内部接口，不能假设跨版本稳定，也不能认为它涵盖原理图的所有内容。

页面批注、标题栏、图形、文字、字体、位图、层级重复实例、总线成员及网络连接范围尚需在真实工程中逐项确认。特别是相同名称的局部网络不能只按名称合并。独立 PDF 渲染必须验证缩放、旋转和镜像、中文字体、分页与网络位置，否则不能视为可交付结果。

Capture 自带的 `CapPdfPrint` 和 PDF Export 不满足本需求。现有 EasyEDA 符号 SVG 渲染器也不是 Capture 原理图渲染器。当前没有经过验证的完整页面图形提取及 PDF 渲染链路，因此尚不能构建功能测试安装包。
