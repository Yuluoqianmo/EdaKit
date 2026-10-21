# Capture 原生 CEF 独立试验

**2026-10-21 更新**：正式入口接入已实施并部署，详见 [CEF正式接入与验证](CEF正式接入与验证.md)。本文继续保留独立试验操作与历史真机证据；其中“正式菜单未迁移”只描述当时状态。本轮正式版本尚待真机回归。

更新：2026-10-20。按用户最新要求，**跳过性能基线，直接验证第二项 CEF 内嵌路线**。本次交付独立探针和 Tcl 入口，不修改主 exe、现有菜单、已安装 Tcl 或放置队列。没有进行性能对比，也不据此承诺提速。

接口依据：本机 Cadence 随附 `D:/Cadence/SPB_17.2/share/orTclscripts/tclscripts/orSE/tcl/OrHandlerSELink.tcl` 中的 `CreateWidget` / `CreateControlBar` / `WF_CEF` / `LoadResource` / `ShowWidget` / `DestroyWidget` 示例。试验不复制其关闭网页安全检查或打开全局调试的设置。接口是否适用于当前 Capture、实际页面是否正常，需要以下真机验证。

## 1. 启动独立检测服务

打开一个 **PowerShell** 窗口，复制执行：

```powershell
& 'C:\Users\32657\lcsc2cadence-build\.venv\Scripts\python.exe' 'E:\outputs\edakit\tools\diag\cef_probe_server.py'
```

预期打印 `CEF probe: http://127.0.0.1:某端口/`、URL 文件和日志路径。**保持此窗口打开**。端口每次启动可能变化，不要复制上次的端口。

探针只提供检测页和日志，不启动商城，不读取/修改生产配置。日志独立保存在 `%LOCALAPPDATA%\edakit-cef-probe`。默认 URL 文件供下方 Tcl 自动读取；不要同时启动两个探针服务。

## 2. 打开 CEF 普通视图

打开 Capture，保留一个可操作的测试原理图。在 Capture 底部 **Tcl 命令窗口**依次执行，不能在 PowerShell 执行：

```tcl
source E:/outputs/edakit/tools/diag/edakit_cef_probe.tcl
::edakitCefProbe::open view probe
```

预期出现 `EdaKit CEF view (probe)` 视图，内容为“EdaKit · Capture 内嵌能力验证”。`CREATED` 仅代表接口调用成功，不能视为页面已通过。

检查：

1. 浅绿色提示框、左右分开的 Flex 检查条和电阻 SVG 图片可见，没有白屏或乱码。
2. 自动检测结束显示“检测完成，日志已保存到 events.jsonl”。点击“重新检测并保存日志”后能够再次完成。
3. 页面输出包含 `userAgent`、`documentMode`、`json`、`xhr`、`requestAnimationFrame`、`canvas2d`、`webgl1`、`webgl2`、`cssBorder`、`flexDisplay`、`svgLoaded`、`sameOriginXHR`。保留原始输出，**WebGL2 为 false 不代表整个 CEF 试验失败**，但会限制后续 3D 方案。
4. 输入框用中文输入法输入 `电阻 4.7kΩ`，检查候选窗、选字、删除和复制粘贴。切到原理图后检查键盘焦点能恢复。
5. 拖动窗口边界调整大小，检查内容随窗口变化。

若白屏：先看 PowerShell 是否仍在运行，检查 `capture.log` 是否有 `FAILED`，再查看 `events.jsonl` 是否收到 HTML/CSS/JS/SVG 请求。有请求不代表图片已显示；图片实际结果看 `svgLoaded` 和截图。一直显示“脚本尚未运行”表示 JS 没有完成初始化，应保留截图和日志。**普通视图不通过时先停止，不继续停靠和真实业务。**

## 3. 验证真实工作台

先从 Capture 现有 **EdaKit 菜单**打开元件工作台，确认原入口可以查询。它负责启动真实商城服务并刷新生产 `url.txt`。不要手工修改 URL 文件。

再在 Capture Tcl 窗口执行：

```tcl
::edakitCefProbe::open view workbench
```

这会读取当前商城地址，在 CEF 中加载现有完整页面；业务功能仍使用当前 exe 和原有队列。探针日志只记录能力检测页的 HTTP 请求，**不会记录真实工作台的接口请求**；工作台仍使用 `%LOCALAPPDATA%\edakit\edakit.log`。

按顺序检查：

1. 中文输入搜索 `4.7k`，选择电阻/贴片电阻及 `0603`，点击“查询”；结果、封装与筛选条件可见。
2. 选择多参数电源管理器件，打开“全部参数”，选择、关闭、应用查询和滚动均正常。
3. 选一个器件，切换 PCB 封装/原理图符号，测试放大、缩小、拖动与大图。
4. 有 3D 的器件切到“3D 模型”，检查初次展示及旋转。当前仍是服务端 PNG，不以它验证客户端 GPU 3D。
5. 点击数据手册，确认对应文档能打开。检查查询过程的等待、取消、失败反馈。
6. 在测试原理图上验证“放置”：点击后回到原理图，器件跟随光标，单击可落位、引脚正常，按 Esc 可退出。测试图不必保存。若焦点切换异常，立即记录停止点。

## 4. 普通视图通过后，再验证右侧停靠

先打开检测页停靠：

```tcl
::edakitCefProbe::open dock probe
```

重复步骤 2 的显示、输入、缩放和焦点检查。通过后打开真实工作台停靠：

```tcl
::edakitCefProbe::open dock workbench
```

拖宽面板，重复步骤 3 的搜索、预览、放置与 Esc；重点观察面板和原理图并排时，点击原理图能恢复键盘输入。重复执行相同 `open` 命令应复用已有面板，Tcl 显示 `REUSED`，不要出现同名新面板堆积。

第一轮先做 3 次关闭/重开。功能正常后，再补充连续开关 30 次、多个器件切换和 100%/125%/150% DPI 检查；这些结果才用于评估正式迁移。未完成时不能标记稳定性已通过。

## 5. 关闭、日志与反馈

先在 Capture 执行：

```tcl
::edakitCefProbe::closeAll
```

只销毁本脚本记录的 CEF 视图/面板。原有 OpenURL 页签可手动关闭。然后在 PowerShell 服务窗口按 **Ctrl+C**；正常退出会移除探针 `url.txt`，保留日志。若手动关闭的面板使句柄失效，清理可能输出 `CLOSE FAILED`，保留该记录；不要据此重复创建许多窗口，结束试验后重启 Capture 可清除残留宿主状态。

另开 PowerShell 查看结果：

```powershell
Get-Content "$env:LOCALAPPDATA\edakit-cef-probe\capture.log" -Tail 60
Get-Content "$env:LOCALAPPDATA\edakit-cef-probe\events.jsonl" -Tail 30
```

请反馈下面这组结果，并附异常截图；日志较长时提供日志文件即可：

```text
CEF 普通检测页：正常 / 白屏 / 报错
中文输入、切回原理图焦点：正常 / 异常
CEF 真实工作台搜索、筛选、预览、手册：正常 / 异常（注明步骤）
CEF 放置、引脚、Esc：正常 / 异常
CEF 停靠检测页与工作台：正常 / 异常
重复打开是否复用：是 / 否
Capture 版本、显示缩放比例：
```

本次可回退方式就是关闭试验面板，继续用现有 EdaKit 菜单。无需复制 exe 或重新安装 Tcl。旧 `lcsc2_cef_diag.tcl` 为历史脚本，本次使用新的 `edakit_cef_probe.tcl`。

## 6. 交付前检查与边界

- 使用现有 Python 3.13 / Tcl 8.6 检查模拟宿主的创建、显示、复用、动态端口、普通视图/停靠分支、失败清理、销毁失败保留句柄、缺少 API/常量和 URL 校验。模拟测试未调用 Capture 接口。
- 本次会话没有 Browser 插件，使用现有 Playwright + 现代 Edge。1100×800、700×600 检查页标题、非空显示、无错误覆盖层、控制台、CSS、SVG、XHR、输入、重新检测及日志落盘通过。程序化输入只验证文本框，不替代 Capture 中文输入法验证。截图位于 `E:/outputs/.edakit-ui-qa/cef-probe-test/desktop.png` 与 `dock-width.png`。
- HTTP 检查覆盖资源类型、未知路径、异常报告拒绝、报告保存。服务仅绑定 127.0.0.1，使用独立日志目录。
- 主 exe SHA256 仍为 `F9A50B596805C4861478CC8E8C7A0EA05401088F97D2B41B4310998C5A42591E`；已安装 Tcl 仍为 `C65C44235A7241A92B27682C62E94413E7CC1188253EACF0ADA8584190B8AD57`。
- 尚未测得 Capture 实际 UA/GPU 能力、内嵌页面效果、焦点与稳定性，也未修改业务性能策略。完成前述真机验证后，再决定是否正式接入 CEF 或转向 WebView2。

## 7. 首轮 Capture 真机结果（2026-10-20）

本节为后续真实结果，更新上一节的交付时状态。已读取本机 `%LOCALAPPDATA%/edakit-cef-probe/events.jsonl` 和 `capture.log`，并对照用户三张截图：

| 项目 | 结果及边界 |
|---|---|
| 普通视图检测页 | 已显示；HTML/CSS/JS/SVG、ping、报告请求均 200，重复检测成功 |
| 停靠检测页 | 已显示；700×851 视口，资源、同源 XHR 与报告保存正常 |
| 实际 UA | 两种宿主均报告 Chrome/45.0.2454.101；documentMode=null |
| 页面能力 | JSON、XHR、requestAnimationFrame、Canvas2D、Flex、SVG 均通过；探针 errors=[]；devicePixelRatio=1 |
| WebGL | WebGL1=false、WebGL2=false。只说明当前两种试验上下文未获得 WebGL，不推断具体 GPU/驱动原因或所有设置均不可用 |
| 真实普通工作台 | 截图可见电容分类、容值条件、查询结果、选中详情与原理图符号；不能由截图认定全部业务操作通过 |
| 真实停靠工作台 | 已加载空闲页面，尚未取得该面板中实际查询和放置的验收结果 |
| 关闭清理 | 19:05:45–46 日志记录四个试验窗口 CLOSED，未见 CLOSE FAILED；尚非 30 次稳定性验证 |
| 仍待确认 | CEF 放置/引脚/Esc、中文输入法与原理图焦点、停靠业务、重复复用/连续开关、缩放和 3D/手册 |

截图中的 `invalid command name "Debugging"` 是 Tcl 尝试执行 `Debugging` 命令的错误；`Capture> Debugging Port Info: localhost:13752` 是宿主输出，无需作为命令再输入。探针日志未记录对应 CEF 创建失败；它与窗口加载成功可以并存。这里不把该消息当作 CEF 页面故障。

当前结论：CEF 视图/停靠的页面接入可行，未证明性能提升或正式迁移完成。WebGL 未通过，因此此试验状态下不能直接推进客户端 WebGL 3D。下一步关闭多余试验窗，只保留一个停靠工作台与原理图，补齐放置/焦点/查询与复用验证。

## 8. 第二轮用户真机确认（2026-10-20）

用户针对上一轮逐项验证指令反馈“均正常”，确认范围为：停靠查询、放置跟随与落位、引脚、Esc、中文输入/焦点和窗口复用。附件截图显示原理图中已放置电阻 `RC0603FR-074K7L`，右侧为 CEF 工作台；命令窗口有 `REUSED dock,workbench id=2`。复用命令会重新加载页面，因此截图中查询条件回到初始状态符合当前试验脚本行为。

阶段 B（CEF 普通视图/停靠接入）及上述核心业务真机回归已通过。此确认不扩展为所有器件、数据手册、3D、30 次开关、100 个器件切换或多 DPI 长时间稳定性验收，也不构成性能提升测量。

后续实施依据：CEF 停靠可进入正式入口接入候选；复用已有面板时应优先只显示，不主动刷新，以保留查询与选中状态；服务地址改变或窗口失效时再处理重载/重建。保留旧入口回退，继续沿用已验证的放置队列。当前正式菜单/已安装 Tcl 仍未迁移，不能把试验通过标记为已部署。
