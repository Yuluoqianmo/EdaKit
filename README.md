# EdaKit

当前正式版本 **v0.1.0**：[下载安装包](https://github.com/Yuluoqianmo/EdaKit/releases/tag/v0.1.0) · [发布说明](docs/发布说明-v0.1.0.md) · [安装与构建](docs/安装包开发-20261023.md)。

在 OrCAD Capture 17.2 中搜索器件、查看符号/PCB/3D、放置原理图器件、编辑工程器件属性，并由独立 Allegro 后台进程生成 PCB 库。当前状态见 [项目交接](docs/项目交接.md)，技术说明见 [文档索引](docs/README.md)。

## 使用

Allegro PCB 端新增 `EdaKit → Interactive BOM...`：自动取当前板快照并生成带二维板图与真实模型三维预览的离线交互式 HTML。可直接使用 PCB 属性，或为当前板选择最终 BOM，详见 [Allegro 交互式 BOM](docs/Allegro交互式BOM-20261023.md)。

商城、器件属性和 BOM 现在共用一个 EdaKit 工作台，顶部标签切换，页面状态保留；原有菜单入口会选中对应标签。更新后完整重启 Capture，详见 [统一工作台](docs/统一工作台-20261022.md)。

1. Capture 菜单 EdaKit → LCSC Mall 打开工作台。
2. 设置中选择库目录并保存。默认原理图库 `D:/EdaKit/Libraries/Symbols`，PCB/焊盘库 `D:/EdaKit/Libraries/Footprints`，独立 STP 库 `D:/EdaKit/Libraries/STEP`，原理图累积库为 Symbols/EdaKit.olb。安装目录自动检测，也可手动选择。
3. 搜索并选中器件，点击“放置到原理图”，在图纸上落位。
4. 点击“生成 PCB 封装”，等待自动编译和发布，不需要输入 SKILL 指令。
5. EdaKit → Component Properties 打开工程器件属性表，在页面内按范围和搜索条件查询器件。配置原生字段、编辑或批量粘贴后，点击“同步到 Capture”。详见 [器件属性编辑器](docs/器件属性编辑器-20261022.md)。
6. EdaKit → BOM Preview 读取整个工程，预览中文 BOM，填写名称、制表人和日期，导入模板及公司物料编码表后导出 Excel。厂家型号固定使用 `Manufacturer_PN`，详见 [BOM 预览与导出](docs/BOM预览与导出-20261022.md)。
7. 更新程序后保存工程，退出所有 Capture，再重新打开；Allegro 库搜索路径在重新启动 Allegro 后生效。

## 项目文件

- `src/edakit/`：服务、符号与封装转换、渲染、队列、安装模板。
- `frontend/`：前端源码，`tools/build_web.py` 生成 `src/edakit/server/web/` 部署资源，两者都保留。
- `tests/`、`samples/ref_capture172.xml`：回归测试及当前必要样本。
- `docs/`：当前交接、技术方案、命名和管理说明。
- `tools/diag/`：当前诊断与原生验证辅助工具。
- `dist/edakit.exe`、`dist/edakit-cli.exe`：默认构建的 GUI 与诊断程序输出位置。发布二进制在 GitHub Release 下载，不纳入 Git。
- `installer/`、`licenses/`、`NOTICE`：安装及许可文件。

历史构建包、过期样例和缓存已清理至 Windows 回收站，详见 [删除记录](docs/删除记录-20261022.json)。

## 开发与构建

```powershell
$env:PYTHONPATH = "$PWD/src"
$env:PATH = 'D:/Cadence/SPB_17.2/tools/bin;' + $env:PATH
python -m pytest -q
python tools/build_web.py
python -m PyInstaller --noconfirm edakit.spec
./dist/edakit-cli.exe selftest
```

本机 Python：`C:/Users/32657/lcsc2cadence-build/.venv/Scripts/python.exe`。新电脑先创建虚拟环境并安装 `requirements.txt`、pytest、pyinstaller，构建前更新前端资源：`python tools/build_web.py`。功能限制及原生验收记录见项目交接。用户库和配置不提交 GitHub。

最新功能：[STP 自动绑定与方向验证](docs/STP自动绑定与方向验证-20261022.md)。生成 PCB 时自动下载并绑定模型，库设置支持独立 STP 目录，3D 预览支持与 PCB 一致的俯视方向。

当前验收（2026-10-23）：用户已确认安装与主要功能初步测试正常；全量回归650通过、2跳过，冻结程序12项自检通过。完整范围和限制以项目交接及发布说明为准。
