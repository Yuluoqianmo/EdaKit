# EdaKit

在 OrCAD Capture 17.2 中搜索器件、查看符号/PCB/3D、放置原理图器件，并由独立 Allegro 后台进程生成 PCB 库。当前状态见 [项目交接](docs/项目交接.md)，技术说明见 [文档索引](docs/README.md)。

## 使用

1. Capture 菜单 EdaKit → LCSC Mall 打开工作台。
2. 设置中选择库目录并保存。默认原理图库 `D:/EdaKit/Libraries/Symbols`，PCB/焊盘库 `D:/EdaKit/Libraries/Footprints`，独立 STP 库 `D:/EdaKit/Libraries/STEP`，原理图累积库为 Symbols/EdaKit.olb。安装目录自动检测，也可手动选择。
3. 搜索并选中器件，点击“放置到原理图”，在图纸上落位。
4. 点击“生成 PCB 封装”，等待自动编译和发布，不需要输入 SKILL 指令。
5. 更新程序后保存工程，退出所有 Capture，再重新打开；Allegro 库搜索路径在重新启动 Allegro 后生效。

## 项目文件

- `src/edakit/`：服务、符号与封装转换、渲染、队列、安装模板。
- `frontend/`：前端源码，`tools/build_web.py` 生成 `src/edakit/server/web/` 部署资源，两者都保留。
- `tests/`、`samples/ref_capture172.xml`：回归测试及当前必要样本。
- `docs/`：当前交接、技术方案、命名和管理说明。
- `tools/diag/`：当前诊断与原生验证辅助工具。
- `dist/edakit.exe`、`dist/edakit-cli.exe`：最新 GUI 与诊断程序。本机二进制不纳入 Git。
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

当前验收（2026-10-22）：C165948 器件测试正常，Capture 右键 Show Footprint 修复也已由用户确认正常。最近自动回归 554 passed / 2 skipped，冻结自检通过；后续进度以项目交接为准。
