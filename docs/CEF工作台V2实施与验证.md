# CEF工作台V2实施与验证

2026-10-21。用户确认概念后实施：停靠优先的选型界面，以及放置准备、预览和请求调度优化。CEF继续作为主方案，Chrome45兼容约束保留。

## 界面交付

- 808px/700px停靠：上方全宽结果表，下方资料与预览；上下分隔条支持拖动和方向键微调。
- 1050px以上：左结果、右详情。小于640px：列表/详情切换，详情提供返回结果，同一选中项可再次打开。
- 顶部压缩为品牌状态、搜索、分类路径/封装/品牌、已选条件。分类按需展开；全部参数仍独立面板，保留搜索、多选、原始值与显式应用。
- 型号优先分配宽度，厂商/封装/库存/价格为默认列，说明进入详情；列设置可显隐这些辅助列，型号始终保留。
- 放置按钮位置固定，资料内容可滚动；真实符号、封装、3D仍由CAD数据驱动。不会把概念图中的模型、库存或价格写入产品。
- 保留草稿/已查询条件区分、分页、取消/重试、安静等待、中文与原生放置提示。无全局游动条、任务浮层或控制台黑窗。

## 性能实现

| 改动 | 实际边界 |
|---|---|
| CEF放置走capture_only准备 | 生成原有同内容的Capture符号XML及封装名称，不在放置关键路径生成SKILL/下载STEP；既有完整stage/build及非CEF POST接口保持完整导出，旧产物不删除 |
| CEF优先XHR/JSON，旧入口JSONP | 取消可中止前端连接；不声称终止已经开始的服务端网络或CPU工作 |
| 512/1024/2048/4096按容器和DPI选择 | 普通小窗通常512，放大跨档才请求新图；3D最高1024，仍为CPU渲染PNG |
| 相同并发下载/渲染合并 | OBJ下载、2D和3D缓存外加同key并发合并；共享CPU渲染槽限制实际渲染并发为1，缓存命中不占槽 |
| 快速旋转只保留最新待处理视角 | 当前图片完成前，后续视角覆盖待处理项，不按每个中间角度请求；同器件更新时保留已显示图并局部提示 |
| 内容ETag及条件请求 | 静态CSS/JS与PNG可304校验复用传输，HTML和商品/库存API继续no-store；不是无限期强缓存，不会锁死旧版本 |
| resize合并 | requestAnimationFrame合并窗口调整；分辨率未跨档时不重复请求PNG |
| CAD缓存上限 | CAD解析对象上限128，商品资料既有128项/600秒策略保留；模型/PNG既有LRU继续使用 |

Tcl、PlaceNew、OLB规范化、400ms轮询和已安装插件均未修改。原始放置库XML及封装名与完整准备路径逐字节/值比较通过。未开展Allegro扩展，也未移除既有导出命令。

## 可量化的样本

本机现有OBJ样本，单次冷渲染包含OBJ解析，固定yaw35/pitch55；与1024比较512，不含商城网络、图片解码或Capture操作。它衡量尺寸策略的收益，不是本轮前后算法跑分，也不代表所有模型。

| 样本 | 1024px冷渲染 | 512px冷渲染 | PNG字节（1024→512） |
|---|---:|---:|---:|
| C2040 | 354.94ms | 140.60ms | 13935→5174 |
| C13755 | 842.54ms | 473.41ms | 29349→11245 |

缓存命中在此样本约0.015–0.018ms，属于函数返回时间，不是完整显示时间。快速连续三次旋转的模拟请求为yaw35和最终125两个，未发送中间65/95。最终冻结包真实C13755资料已缓存后，隔离Capture准备样本为7.23ms；不含CAD首次下载、Tcl库转换与用户落位，不用其推算整体放置提速。

## 验证结果

- 完整pytest：305 passed / 1 skipped；跳过缺lxml的XSD验证。新增Capture准备不调用STEP/SKILL、符号一致、并发合并与失败恢复、PNG304及活数据no-store、CEF与完整接口分流测试。
- 浏览器：Browser插件不可用，使用已有Playwright + Edge；808×850、700×600、550×800、1440×900。
- 检查：页面身份、非空内容、无错误覆盖层、无脚本异常；宽窄布局、同项再次选择、分隔条、参数多选与分页、列设置、详情/预览、大图/Esc、XHR取消/失败重试、旧入口JSONP均通过。
- 图片调度：初始512px；808→810px调整不产生新PNG请求；连续旋转只保留最终待处理项。
- 冻结包：GUI/CLI子系统正确，11项自检，真实库XML合并成功及失败非零退出，包内HTML/CSS/JS/Tcl与源码一致。
- 最终exe隔离服务连接真实商城：LM5116返回4项，C13755 CAD符号/封装、512px PNG、ETag304、capture_only准备通过。stage_only请求仅写隔离测试队列，没有向用户工程放置器件。

现代Edge与模拟documentMode仅验证兼容分支，不替代Capture Chrome45真机显示、输入法、焦点、引脚、Esc、多DPI和长期稳定性回归。

## 与批准概念的核对

概念：[dock-concept.png](../design/cef-workbench-v2/dock-concept.png)。已用view_image同时查看批准图和最终浏览器截图，并在808px实际宽度核对：

| 项目 | 实施结果 |
|---|---|
| 紧凑标题与搜索 | 保留EdaKit/元件工作台、连接状态、查询与重置，缩小品牌占用 |
| 分类/条件层级 | 分类路径、封装/品牌、全部参数、已选条件分层；保留清空参数及未查询提示 |
| 全宽表格 | 型号/C编号主列，厂商、封装、库存、价格清晰对齐；表头固定、分页固定 |
| 选中详情/预览 | 下方左右分区，资料滚动与真实CAD预览，符号/封装/3D标签齐全 |
| 主操作 | 放置到原理图与数据手册固定在资料区下方 |
| 颜色与密度 | 白底、冷灰细边、深色文字、青绿色选中及主操作；无装饰动画 |

有意差异：概念是示例数据/示意封装，最终使用真实库存、原币种价格、CAD图及实际参数，不能照图编造；Capture自带窗口控制不在网页重复实现；保留原有搜索范围说明、取消/错误和分页反馈；为短高度提供更紧凑行高，为窄于640px提供切换。首屏文案差异限于上述真实数据与必要业务反馈。主结构按批准方向实现并核对，未做概念图片切片或假按钮。

截图与脚本位于 `E:\outputs\.edakit-ui-qa`：workbench-v2-final-dock.png、workbench-v2-final-wide.png、workbench-v2-final-small.png、workbench-v2-parameters.png；workbench-v2-qa.cjs、workbench-v2-flow-qa.cjs、workbench-v2-final-shots.cjs、workbench-v2-frozen-qa.py、workbench-v2-preview-benchmark.json。最终图使用当日真实商城快照和缓存真实CAD，测试服务Capture状态为未连接。

## 真机操作

本轮无需deploy或重启Capture。主程序更新后，从菜单重开加载新服务地址，旧查询可能重置。请用不保存的测试原理图：

1. 打开 **EdaKit → LCSC Mall**，确认无黑窗，约800px宽时上列表、下详情；拖宽至约1100px检查左右布局。
2. 输入4.7K，分类按钮选择电阻/贴片电阻，在封装选0603；更多技术参数通过全部参数选择。查询前后条件、清空、多选、翻页均应保持正确语义。
3. 查看型号、封装、库存、价格；用列设置隐藏库存、显示说明后再恢复。拖动中间分隔条，检查列表、预览和放置按钮不重叠。
4. 连续选择不同器件，再选同一器件；符号/封装/3D切换，缩放、大图、Esc。连续旋转后应显示最终角度，无任务浮层；CPU PNG仍非GPU实时拖动，首次模型可能需下载。
5. 点击放置：预期不再等待STEP准备，仍进入原生光标跟随；单击落位、引脚正常、Esc退出。分别回归0603电阻与RP2040；不要把“已armed”当作实际落位成功。
6. 中文输入法、粘贴、原理图/面板焦点，窄宽切换及100%/125%/150%DPI按需补测。异常时记录C编号、条件、停止步骤、截图和两个日志。

```powershell
Get-Content "$env:LOCALAPPDATA\edakit\edakit.log" -Tail 80
Get-Content "$env:LOCALAPPDATA\edakit\background.log" -Tail 80
```

建议反馈：布局/筛选查询/列设置/预览与旋转/放置引脚Esc/中文焦点分别正常或异常；首次与重复操作主观等待是否改善。若数据不一致先反馈，不反复放置或保存异常测试图。

## 交付与回退

新阶段包：`dist/workbench-v2/edakit.exe` 与 `edakit-cli.exe`；主路径保持 `dist/edakit.exe` 与CLI。当前哈希见项目交接。回退包为 `dist/edakit.before-workbench-v2-20261021.exe` 和 `dist/edakit-cli.before-workbench-v2-20261021.exe`。

保存工程、退出Capture并确认主路径服务退出后，执行：

```powershell
Copy-Item -LiteralPath 'E:\outputs\edakit\dist\edakit.before-workbench-v2-20261021.exe' -Destination 'E:\outputs\edakit\dist\edakit.exe'
Copy-Item -LiteralPath 'E:\outputs\edakit\dist\edakit-cli.before-workbench-v2-20261021.exe' -Destination 'E:\outputs\edakit\dist\edakit-cli.exe'
```

重开Capture恢复旧UI与旧放置准备；无需deploy，配置、队列和器件库不删除。源码/测试/文档备份：`E:\outputs\backups\edakit-before-workbench-v2-20261021.zip`。
