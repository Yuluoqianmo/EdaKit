# EdaKit

**面向 OrCAD Capture 与 Allegro PCB Editor 的器件库、属性编辑和 BOM 工具箱。**

EdaKit 将立创器件检索、原理图器件放置、PCB 封装生成、器件属性维护、BOM 导出和交互式焊接辅助整合到 Cadence 工作流程中，减少在不同工具之间复制和整理数据的操作。

**稳定版：v0.1.7** · Windows 64 位 · 主要验证环境：Cadence 17.2

[下载安装包](https://github.com/Yuluoqianmo/EdaKit/releases/latest) · [发布说明](https://github.com/Yuluoqianmo/EdaKit/releases/tag/v0.1.7) · [使用文档](docs/README.md) · [问题反馈](https://github.com/Yuluoqianmo/EdaKit/issues)

## 功能介绍

| 功能 | 说明 |
| --- | --- |
| 器件商城与建库 | 在 Capture 内搜索立创器件，预览符号、PCB 封装和 3D 模型，查看数据手册，并放置原理图器件；自动生成 PCB 封装，下载并绑定 STEP 模型。 |
| 工程器件属性 | 以表格查看工程器件，自定义显示字段，排序、搜索、批量编辑、拖拽向下填充和双击位号定位，并将修改同步到 Capture；字段保留 `Manufacturer` 等原生属性名称。 |
| BOM 预览与导出 | 使用 Excel 模板生成中文 BOM，编辑名称、制表人和日期，按 `Manufacturer_PN` 匹配公司物料编码，手工补充编码、增加物料或排除无需导出的项目。 |
| Allegro 交互式 BOM | 从当前 PCB 生成可离线打开的 HTML，支持二维板图、真实模型三维预览、BOM 与器件双向定位、搜索筛选、焊接完成标记和本地进度保存，支持手机横竖屏及触屏操作。 |

Capture 中的商城、器件属性和 BOM 共用内嵌工作台，可通过顶部标签切换。

## 环境要求

- Windows 64 位，已安装 OrCAD Capture 与 Allegro PCB Editor。
- 当前原生功能主要在 **Cadence 17.2** 验证，其他版本需要实际测试。
- 安装器需要找到 Capture 的 `tclscripts` 目录和 Allegro 的 `ipc2581_out.exe` 导出工具。
- 商城搜索、数据手册及模型下载需要联网；导出的交互式 BOM 可离线查看。
- 使用安装包无需单独安装 Python、Node.js 或构建工具。

## 下载与安装

1. 打开 [Releases](https://github.com/Yuluoqianmo/EdaKit/releases/latest)，下载 `EdaKit-0.1.7-Setup.exe`。可使用同页的 `SHA256SUMS.txt` 校验文件完整性。
2. 保存工程并退出 Capture、Allegro。
3. 使用实际运行 Cadence 的同一 Windows 账号启动安装包，选择 EdaKit 安装目录和 **Cadence SPB 根目录**，例如 `D:\Cadence\SPB_17.2`。
4. 等待插件部署完成，重新打开 Capture 或 Allegro，检查菜单栏中的 **EdaKit**。
5. 首次使用时，在商城设置中确认原理图库、PCB/焊盘库和 STEP 库路径。

默认库目录如下，可在设置中修改：

| 库 | 默认路径 |
| --- | --- |
| 原理图符号 | `D:\EdaKit\Libraries\Symbols` |
| PCB 封装与焊盘 | `D:\EdaKit\Libraries\Footprints` |
| STEP 模型 | `D:\EdaKit\Libraries\STEP` |

如果电脑没有 D 盘，请将库目录改为实际可写的位置。更新后重新启动 Capture 和 Allegro；修改 PCB 或更新程序后，需要重新导出交互式 BOM。

卸载会移除插件入口和自有配置块，保留用户配置、器件库及导出文件。

## 使用方法

### 1. 搜索器件、放置符号与生成封装

1. 在 Capture 中选择 **EdaKit → LCSC Mall**。
2. 搜索并选择器件，查看符号、封装、3D 模型和数据手册。
3. 点击“放置到原理图”，回到图纸中单击落位，按 Esc 结束。
4. 点击“生成 PCB 封装”，等待后台完成转换、编译和模型绑定。

### 2. 批量维护器件属性

1. 选择 **EdaKit → Component Properties**，读取工程器件。
2. 在字段设置中选择需要显示的原生属性，通过搜索和排序定位器件。
3. 双击 `Reference` 单元格定位原理图中的对应器件；多单元器件先选择具体单元。
4. 直接编辑单元格、批量填写，或从 Excel 粘贴数据。选中可编辑单元格后，拖动右下角黑色填充柄，向下复制该值；按当前页筛选、排序后的显示顺序填充，可撤销本次填充。
5. 点击“同步到 Capture”，将修改写回工程器件。编辑和拖拽只修改草稿，不会立即写入工程。

### 3. 生成 Excel BOM

1. 选择 **EdaKit → BOM Preview**，读取整个工程。
2. 选择 BOM 模板，填写 BOM 名称、制表人、日期等信息。
3. 如需公司物料编码，导入编码表并配置列匹配；厂家型号使用 `Manufacturer_PN`。
4. 检查分类及匹配结果，按需补填编码、增加手工物料或取消导出部分物料。
5. 点击“导出 Excel”。字段不完整也允许导出，可在 Excel 中继续修改。

### 4. 导出交互式 BOM，用于焊接

1. 在 Allegro 中打开 PCB，选择 **EdaKit → Interactive BOM...**。
2. 设置输出目录。默认使用板内器件信息；需要最终物料编码时，可改为关联外部 BOM。
3. 点击导出，查看实际处理进度，完成后用浏览器打开生成的 HTML。
4. 在 BOM 与板图之间点击定位，切换顶底面或 3D 预览，逐项标记焊接完成状态。

将生成的 HTML 传到手机后，在支持 JavaScript 的浏览器中打开。竖屏通过“物料 / 板图”切换，点击物料可聚焦器件；二维支持单指平移、双指缩放，三维支持单指旋转、双指缩放和平移。横屏使用右侧导航、两列物料列表及适配比例的板图。更新插件后需重新导出，旧 HTML 不会自动更新。详见 [移动端使用说明](docs/交互式BOM移动端.md)。

三维预览优先使用板上绑定的 STEP 模型或 Allegro 真实网格缓存。缺少模型时本体留空，仅保留焊盘与封装丝印；丝印位号只显示当前选中的器件，以减少观察干扰。

### 5. 查看版本、检查更新与诊断

选择 **EdaKit → About EdaKit**，查看版本、GitHub 仓库及发布说明。可手动检查新版本，也可设置启动时自动检查（每天最多一次）。发现更高正式版后，可下载安装包并校验完整性；点击安装前先保存工程，更新助手会等待 Capture、Allegro 和旧服务退出，再打开安装向导。

“关于”页面还提供 **环境诊断** 和 **打开日志文件夹**。诊断仅在点击时执行，结果显示在页面并写入日志。日志目录为 `%LOCALAPPDATA%\edakit`，反馈问题可附 `edakit.log`、`service.log`。

自动更新的真实跨版本覆盖安装尚未完成实机验收，也可直接从 Releases 下载并手动安装。

## 常见问题

**安装后没有出现 EdaKit 菜单？**

确认安装时选择了正确的 SPB 根目录，并完整退出后重新打开 Cadence。部署失败时检查 EdaKit 安装目录中的 `deployment.log`，修正路径或权限后重新运行安装包。

**模型未显示或与预期不同？**

检查 PCB 中的 STEP 绑定和 Allegro 库路径，再重新导出 HTML。缺失或无法解析的模型不会生成替代方块，当前导出也不等同于 Allegro 完整机械视图。

**可以把交互式 BOM 发给其他人吗？**

可以，HTML 内嵌所需查看资源，可离线打开。焊接进度保存在当前浏览器本地，不会自动同步到其他电脑或浏览器。

## 支持范围与限制

- Windows / Cadence 17.2 已完成实机验证；其他 Cadence 版本需要实际测试。
- **Linux 尚未进行项目整体测试**。Linux CI 仅验证部分自动化用例，不代表安装及 Cadence 集成功能可用。
- 缺少 JSON 能力的旧版 IE 只支持只读查询，安全放置请使用 CEF 工作台。
- 不同 Cadence 版本、新电脑及跨管理员账号安装仍需进一步验证。
- iBOM 板厚默认为 **1.6 mm 示意**，尚未覆盖完整铜走线、过孔、槽孔和全部丝印图层。

## 文档

- [安装、升级、卸载与构建](docs/安装包开发-20261023.md)
- [器件属性编辑器](docs/器件属性编辑器-20261022.md) · [定位与拖拽填充](docs/器件属性定位与填充.md)
- [关于、更新与诊断](docs/关于更新与诊断.md)
- [BOM 预览与导出](docs/BOM预览与导出-20261022.md)
- [Allegro 交互式 BOM](docs/Allegro交互式BOM-20261023.md) · [手机横竖屏操作](docs/交互式BOM移动端.md)
- [STEP 模型绑定与方向](docs/STP自动绑定与方向验证-20261022.md)
- [当前项目交接](docs/项目交接.md) · [完整文档索引](docs/README.md)

## 开发与构建

普通使用者直接下载安装包即可。开发者可检出发布标签，使用 Python 3.13（与依赖锁文件及 CI 一致）在 Windows 上构建：

```powershell
git clone https://github.com/Yuluoqianmo/EdaKit.git
cd EdaKit
git checkout v0.1.7
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-build.lock
$env:PYTHONPATH = "$PWD/src"
# 按实际 Cadence 安装路径修改；Tcl 回归需要 tclsh。
$env:PATH = 'D:\Cadence\SPB_17.2\tools\bin;' + $env:PATH
python -m pytest -q
python -m PyInstaller --noconfirm edakit.spec
.\dist\edakit-cli.exe selftest
```

生成安装包还需要 Inno Setup 6：

```powershell
.\installer\build.ps1 -Python python -Compiler 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe'
```

| 目录 | 用途 |
| --- | --- |
| `src/edakit/` | 服务、转换、渲染、Cadence 桥接和插件模板 |
| `frontend/` | 内嵌页面源码 |
| `installer/` | 安装脚本、构建与安装验收工具 |
| `tests/` | 回归测试与必要样本 |
| `docs/` | 使用说明、技术文档和版本记录 |
| `licenses/`、`NOTICE` | 第三方许可与归属说明 |

## 许可与反馈

欢迎通过 [Issues](https://github.com/Yuluoqianmo/EdaKit/issues) 反馈问题。请附上 EdaKit 版本、Cadence 版本、复现步骤和相关日志，提交前移除工程中的敏感信息。

EdaKit 原创代码采用 [MIT License](LICENSE)，允许按许可条款使用、修改和再分发。第三方组件及模型、器件数据不因项目许可而改变各自权利；第三方许可与归属见 [NOTICE](NOTICE) 和 [licenses](licenses)。EdaKit 为独立开发的辅助工具，与 Cadence、立创及其产品不存在官方隶属关系。
