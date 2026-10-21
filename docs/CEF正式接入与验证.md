# CEF 正式入口接入与请求优化

更新：2026-10-21。正式版本已部署，用户反馈实际测试“基本没问题”，并确认后续以CEF作为主技术方案。下文保留首次接入阶段的构建、验收步骤和回退证据；当前包与文件位置以[项目交接](项目交接.md)为准。长期稳定性、多DPI和性能提升尚未完整验收。

后续用户反馈：正式版本实际测试“基本没问题”，主要问题是3D每次拖动仍出现“首次可能需要下载模型”。已据此将3D提示简化为“正在生成3D视角预览”。此反馈不扩大为多DPI、长期稳定性或提速测量通过；下方哈希与交付表记录首次正式接入包，新文案包位于 `dist\cef-preview-label`。

新文案已替换主 exe；更新时仅停止主路径的两个服务实例，未关闭 Capture。下次点击菜单重新启动服务并加载新页面。JS语法检查、包内JS与源码一致检查通过，旧提示已从包内移除。当前主 exe SHA256：`6836903C8932E889153D7F4E339EAB6BDFD989921A6747F57950879526C4AF65`；替换前备份：`dist\edakit.before-preview-label-20261021.exe`。Tcl未改，无需deploy。

## 当前行为

- `EdaKit → LCSC Mall` 默认创建右侧 700px CEF 工作台。相同服务地址重复打开只显示已有面板，不调用 LoadResource，保留查询和选中状态。
- 服务地址改变时重新加载；ShowWidget/LoadResource 报错后先销毁旧句柄再创建。销毁失败保留句柄并记日志，避免创建重复面板。手动关闭后宿主是否报告失效，仍需真机确认。
- `EdaKit → LCSC Mall (Legacy Viewer)` 保留原 OpenURL 入口。CEF API 调用失败自动使用旧入口；页面白屏但 API 没有报错时，需要手动选择旧入口。
- 详情加载期间连续选择同一器件不重复请求 CAD/商品资料；详情失败后可重新选择重试。连接状态轮询在前一请求结束前不发第二次。
- 3D 等待文案改为“正在生成3D视角预览（首次可能需要下载模型）”，避免把每次旋转误称为下载。继续使用服务端 PNG，未启用 WebGL。
- 放置/轮询源码与修改前备份一致；未开展 Allegro 扩展或改动用户原理图。

## 已完成验证

| 项目 | 结果 |
|---|---|
| 完整 pytest | 297 passed / 1 skipped；跳过缺少 lxml 的 XML XSD 验证 |
| Tcl | Cadence tclsh 执行；纯 ASCII；模拟同 URL 复用、新 URL 重载、失效重建、销毁失败保留句柄和菜单回归通过 |
| JS | node --check 通过 |
| 页面 | Browser plugin not available；使用既有 Playwright + Edge，1440×900、700×851，页面身份/非空/无错误覆盖层/控制台/截图/交互通过 |
| 重复请求 | 延迟详情下连续点击三次：part=1、product=1；状态响应延迟12秒，状态请求最大并发=1 |
| 冻结包 | 11项自检通过；HTML/CSS/JS/Tcl 包内内容与源码逐字节一致 |
| 部署 | 更新前未检测到 Capture/edakit 进程；主 exe 与阶段包一致；模板、手拷副本、已安装 Tcl 三者一致 |

页面验证使用隔离测试服务和样本数据，不代表商城当前联网性能。未测量提速比例、长时间稳定性、多 DPI 或本轮 Capture 真机行为。实际已知内核 Chrome 45，WebGL1/2 不可用；现代 Edge 验证不替代旧 CEF 回归。

证据：`E:\outputs\.edakit-ui-qa\cef-integration-result.json`、`cef-integration-desktop.png`、`cef-integration-dock.png`、`cef-pack-check.py`。源码备份：`E:\outputs\backups\edakit-before-cef-integration-20261021.zip`。

## 当前交付

- 主程序：`E:\outputs\edakit\dist\edakit.exe`；阶段包：`dist\cef-integration\edakit.exe`。
- 两者 SHA256：`FF82F9AB8D1F494EB5590BE21A6F7B5D63F507E50EF235358559A9EAF94A53E1`。
- Tcl SHA256：`2102CCB615A0CE53ED151E43F7A7CF093B54919F851C5594D642C78F8EB66C81`。
- 已安装到 `D:\Cadence\SPB_17.2\tools\capture\tclscripts\capAutoLoad\edakit\edakit.tcl`，无需再次 deploy；启动新的 Capture 进程加载。

## 真机验证步骤

1. 启动 Capture，打开可编辑的测试原理图，不必保存测试放置结果。点击 **EdaKit → LCSC Mall**。预期右侧出现工作台，中文正常；服务启动首次可能等待数秒。不要再 source 独立试验脚本，以免混淆试验与正式面板。
2. 输入 `4.7k`，选电阻/贴片电阻与 `0603`，点击查询。选中一个器件并等待详情与预览。记下条件、页码和 C 编号。
3. 连续点击菜单三次，切回原理图再点击菜单。预期始终是同一面板，条件、页码、选中器件和预览保持，日志出现 `CEF dock reused`。重复打开不应回到初始页。
4. 更换器件，加载期间快速重复点同一行。预期不出现持续闪烁、等待状态卡住或详情串料；查询中重复点击查询应被禁用。取消后可重新查询，失败后可重试。
5. 选一个有原理图符号的器件，点击放置；回到原理图后跟随光标，单击落位，引脚正常，Esc退出。再验证另一器件。若异常，保留 C 编号和停止步骤，不保存测试工程。
6. 中文输入 `电阻`，检查输入法候选、删除、复制粘贴；切换原理图/面板检查焦点。调整面板宽度，打开全部参数并滚动、选项、应用查询。
7. 检查符号/封装/大图、缩放拖动；有模型时查看3D并旋转，等待提示不再声称每次都下载。检查数据手册对应当前器件。
8. 手动关闭面板，再点击正式菜单，预期恢复或重建可用面板。先测试3次；之后再进行30次关闭/重开及100%/125%/150%缩放。后者属于补充稳定性验收，不能仅凭前三次认定长期稳定。
9. 点击 **LCSC Mall (Legacy Viewer)**，确认旧入口仍能查询。若 CEF 白屏但未自动回退，使用此入口继续工作并反馈；旧入口有独立网页状态，不共享CEF查询。

服务重启导致地址变化的重载分支已模拟验证，不要求为了验收强制杀死生产服务。真正服务退出后，下次菜单调用会重新启动；地址变化时允许查询状态重置。

查看日志（PowerShell）：

```powershell
Get-Content "$env:LOCALAPPDATA\edakit\edakit.log" -Tail 100
```

反馈格式：

```text
Capture版本/显示缩放：
正式菜单右侧CEF：正常 / 异常
重复菜单保持条件、页码、选中：正常 / 异常
关闭再开：正常 / 异常（次数）
查询、详情、取消、重试、等待：正常 / 异常
放置、引脚、Esc（C编号）：正常 / 异常
中文输入/焦点/参数/预览/手册：
旧入口：正常 / 异常
异常停止步骤、截图、日志：
```

## 回退

优先使用菜单 **LCSC Mall (Legacy Viewer)**，无需替换程序。若要完整恢复旧版本：保存工程并退出 Capture；确认没有主路径 edakit.exe 进程后，在 PowerShell 执行：

```powershell
Copy-Item -LiteralPath 'E:\outputs\edakit\dist\edakit.before-cef-integration-20261021.exe' -Destination 'E:\outputs\edakit\dist\edakit.exe'
& 'E:\outputs\edakit\dist\edakit.exe' deploy --cadence-root 'D:\Cadence\SPB_17.2' --no-allegro
```

再启动 Capture 即恢复旧菜单和页面。不要在新程序仍运行时覆盖 exe；可先用 `Get-Process edakit -ErrorAction SilentlyContinue | Select-Object Id,Path` 核对路径，避免停止无关进程。旧已安装 Tcl 与手拷副本另存于 `E:\outputs\backups\edakit-installed-before-cef-20261021.zip`；旧 exe 为已验收前的统一汉化包。回退不删除配置、队列、OLB或运行数据。
