# EdaKit / EDA 工具箱

## 最新进度与换机接续（2026-10-21）

请先读[回家接续开发](docs/回家接续开发-20261021.md)：包含开发分支、拉取与环境命令、可重建测试路径及下一步操作。本轮 Allegro C2040（57 引脚）原生创建、编译和重开通过；Capture P5R2 经原生 PlaceNew 放置通过，格点连线及网表导入仍待验收。源码已升级 P5；当前已安装 exe 仍是旧 P4，未重新打包部署。隔离验收材料已收入 [samples/acceptance-20261021](samples/acceptance-20261021/README.md)。

## 较早已发布基线与开发记录

2026-10-21 PCB 规划重整：见[PCB 封装生成方案](docs/PCB封装生成方案.md)。源码新增符号／封装引脚配对硬校验及功能名映射清单；最新可用 exe 仍为用户确认的厂家属性版，尚未重新打包部署 PCB 改动。旧构建移到项目外备份，见[整理记录](docs/PCB方案重整与验证-20261021.md)。

当前更新（2026-10-21）：**厂家属性放置继承已修复并经用户实测通过**。四字段从封装属性改写到符号属性层，内部库名升级为 _P4 避免复用旧定义。生成的 Capture 元件库包含精确名称 `Description`、`PCBFootprint`、`Manufacturer`、`Manufacturer_PN`；随新器件放置继承，默认不额外显示在图面。`PCBFootprint` 与内置 `PCB Footprint` 同值；源数据缺失时保留空值。已有实例不自动改写。

用户已确认电容符号、连续放置、字体及按钮状态测试通过；厂家及厂家型号属性修复也已在 Capture 实际放置后确认正常。本轮完整回归 380 passed / 1 skipped，另有 8 份 XML 通过 Capture 17.2 XSD 校验；GUI/CLI 各 11 项自检、六种器件的冻结程序输出及包含 C98220/C60490/C95204 的 HTTP 放置准备通过。项目源码与文档现由同名 GitHub 私有仓库管理；本机 exe、构建缓存和回滚副本不纳入源码仓库。历史证据与发布文件状态见[项目交接](docs/项目交接.md)。

在 OrCAD Capture 内搜索立创器件，查看符号、封装、3D 和数据手册，通过 PlaceNew 跟随光标放置。主方案为原生 CEF 右侧停靠工作台；菜单提供 LCSC Mall 和 Diagnostics。架构加固、会话定向队列、后台退出管理和工作台 V2 沿用已实施版本。

## 从这里开始

- [当前技术方案](docs/技术方案.md)：CEF 宿主、服务和放置链路、兼容边界。
- [项目交接](docs/项目交接.md)：当前版本、开发命令、机器状态和下一轮工作。
- [文档索引](docs/README.md)：当前文档与历史证据分级。
- [GitHub 管理](docs/GitHub管理.md)：仓库范围、提交流程、发布与回退约定。
- [真机操作与回退](docs/CEF正式接入与验证.md)：操作顺序、预期结果和异常反馈。
- [文件整理记录](docs/项目文件整理-20261021.md)：归档规则、移动清单及核对方法。

## 使用

1. Capture 菜单 **EdaKit → LCSC Mall** 打开右侧工作台；同一服务地址下重复点击只唤回，不重置查询与选中状态。
2. 选择分类、关键词、封装、参数或品牌，点击查询。修改筛选条件后需重新查询，翻页沿用已提交条件。
3. 单击器件查看符号、封装、3D；点击数据手册打开对应文档。
4. 点击放置，切回原理图，单击落位，Esc 退出。
5. 需要排障时打开 **EdaKit → Diagnostics** 的能力检测或日志；旧方案入口已从菜单删除。

## 项目结构

| 路径 | 用途 |
|---|---|
| `src/edakit/` | 正式 Python 服务、页面、渲染、放置队列和安装模板 |
| `tests/` | 离线回归与样本；Tcl 回归需要 Cadence tclsh |
| `tools/diag/` | 当前 CEF 能力检测与光标排障工具，见其 README |
| `tools/diag/archive/` | 旧方案实验及配套样本，禁止当作正式入口使用 |
| `docs/` | 当前说明、索引及保留原位置的历史验证记录 |
| `dist/edakit.exe` | 唯一主程序路径；菜单和 exe_path.txt 指向这里 |
| `dist/symbol-properties/` | 当前版本留档 |
| `dist/rollback-before-symbol-properties/` | 最近一次可用回退；更早发布包移至项目外备份 |
| `build/` | 保留 symbol-properties 构建；旧构建移至项目外备份 |
| `design/`、`installer/`、`samples/`、`licenses/` | 设计参考、安装辅助、样例及许可 |

当前 exe SHA256：C3BFA7984F939CBE5F0D2967347F5562847F9050647EEBE35F349459D0B6603F。当前 Tcl SHA256：2D8A6692E77C74E7EAB579CA314C5AFF8F15F3FE9ADD3B23708942DAA9265415。

## 开发与发布

```powershell
Set-Location -LiteralPath 'E:\outputs\edakit'
$env:PATH = 'D:\Cadence\SPB_17.2\tools\bin;' + $env:PATH
$taskTestTemp = Join-Path 'E:\outputs' ('.edakit-tests-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
& 'C:\Users\32657\lcsc2cadence-build\.venv\Scripts\python.exe' -m pytest -q --basetemp $taskTestTemp
node --check .\src\edakit\server\web\embed.js
```

构建使用 `build_exe.bat`，或输出独立阶段包：

```powershell
& 'C:\Users\32657\lcsc2cadence-build\.venv\Scripts\python.exe' -m PyInstaller --noconfirm --distpath dist\next-release --workpath build\next-release edakit.spec
.\dist\next-release\edakit-cli.exe selftest
```

网页与 Tcl 均打入 exe。修改源码后需重打包；更换主程序前备份并检查占用。更新 Tcl 时保存工程、退出 Capture，使用包含新模板的 edakit-cli.exe 执行 `deploy --cadence-root 'D:\Cadence\SPB_17.2' --no-allegro` 后重开 Capture。仅页面文案更新无需 deploy。

## 验证与约束

本轮完整回归为 380 passed / 1 skipped（缺 lxml 的测试已另用 .NET 完成 8 份 XSD 校验），GUI/CLI 各 11 项自检通过；用户确认 Capture 新放置后的厂家及厂家型号属性正常。长期稳定性、多 DPI 和提速比例不据此作结论。

实际 CEF 为 Chrome 45，探针未取得 WebGL1/2 上下文。继续使用兼容页面和服务端 PNG，不默认升级现代语法、GPU 3D 或框架。Tcl 必须纯 ASCII。原放置队列和 PlaceNew 路径保持；Allegro 扩展继续暂缓。运行配置、日志、队列和 OLB 位于 `%LOCALAPPDATA%\edakit`，不得作为项目缓存清理。
