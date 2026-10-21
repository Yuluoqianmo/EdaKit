# Capture 内嵌技术与性能优化调研

日期：2026-10-20。范围：代码审计、Cadence 随附资料、Microsoft 官方资料及上游 GitHub 项目；本轮没有修改程序源码、主 exe、已安装 Tcl 或用户原理图，也没有完成新内核的 Capture 真机验证。

## 1. 建议结论

优先做独立的 **Cadence 原生 CEF 视图/停靠面板可行性验证**，同时建立性能基线。它有本机 Cadence 自带示例作为依据，可以复用现有 Python HTTP 服务和放置队列，接入成本预计低于自行开发 WebView2 原生宿主。停靠成功后，可以让器件搜索和原理图并排显示，减少页签切换；是否支持当前全部操作，仍需验证。

**WebView2 是长期候选，不是可直接替换 OpenURL 的设置项。** 它更适合现代网页及 GPU 3D，但首先要解决 Capture 中原生窗口的创建、父子关系、STA 消息循环、焦点、缩放和销毁。现有资料不足以确认 Capture 17.2 向第三方开放了可直接使用的 WebView2 停靠宿主接口。

不要先大规模换前端框架。现有延迟涉及上游接口、缓存、请求生命周期和 CPU 3D 渲染；换框架或浏览器内核不会自动解决它们。正式迁移前保留现有 OpenURL 路径作为回退。

## 2. 已核实的接入条件

| 事实 | 证据 | 边界 |
|---|---|---|
| 当前通过 OpenURL 打开内嵌页面 | `src/edakit/install/templates/edakit.tcl`；Cadence 随附 Tcl 手册第 135 页有 OpenURL 签名 | 当前代码采用旧浏览器兼容路径。历史称“IE7 内核”，本轮没有采集 UA/documentMode，不能把兼容模式直接等同于内核版本 |
| Cadence 自带 CEF 停靠面板示例 | `D:/Cadence/SPB_17.2/share/orTclscripts/tclscripts/orSE/tcl/OrHandlerSELink.tcl`，`capLaunchSESearchAndLinkWidget` | `orPrmWebComp`、`CreateControlBar`、`WF_CEF`、`LoadResource`、`ShowWidget` 为厂商随附实际代码；不等于已确认稳定公开的第三方 API 合同 |
| 同文件也有 CEF 文档视图示例 | `CreateWidget $orPrm::WTYPE_VIEW $orPrm::WF_CEF` | 先验证普通视图，再验证停靠；主工作台应避免采用阻塞原理图的模态对话框 |
| 本机 CEF 较老 | `D:/Cadence/SPB_17.2/tools/bin/libcef.dll` 版本 `3.2454.1344.g2782fb8`；CEF 上游 2454 分支兼容文件指向 Chromium 45 | Chromium 45 代属于根据分支作出的判断，不声称精确对应本机补丁构建；不能假定现代 JS/CSS/WebGL2 可用 |
| 项目曾做过 CEF 探索 | `tools/diag/lcsc2_cef_diag.tcl`；`docs/历史交接-20261020-初始版本.md` | 旧记录为窗口创建后样式/SVG未正常加载，且存在过期服务端口问题；没有充分证据判定 CEF 路线不可行。旧脚本含历史路径，不是可直接交付的验证步骤 |
| 本机已存在 WebView2 Runtime | `C:/Program Files (x86)/Microsoft/EdgeWebView/Application/155.0.4283.62/msedgewebview2.exe` | 仅证明运行时文件存在，不代表 Capture 已支持接入，也不是对全球最新版本的判断 |

随附 PDF：`D:/Cadence/SPB_17.2/tools/capture/tclscripts/OrCAD_Capture_TclTk_Extensions.pdf`，共 922 页。文本检索命中了 OpenURL，没有找到 CreateWidget/CreateControlBar/WF_CEF/orPrm 的接口说明。因此 CEF 依据主要是随附脚本，不能冒充手册明确承诺。

## 3. 路线比较

| 路线 | 预期价值 | 主要代价/限制 | 建议 |
|---|---|---|---|
| 保留 OpenURL，优化现有服务和页面 | 兼容已验证的放置流程；减少重复工作、闪白和错误等待 | 旧网页能力限制仍在，难以提供现代 GPU 3D | 作为稳定基线及回退，优化可独立开展 |
| Cadence 自带 CEF 文档视图/停靠面板 | 真实内嵌；有本机厂商示例；停靠可改善原理图与商城协同 | 内核老；资源加载、CSS/JS、GPU、焦点和 DPI 未验证 | **近期第一候选，先做小型实验** |
| 原生宿主 + WebView2 | 现代网页能力；支持进一步开发客户端 GPU 3D；可维护运行时 | 需要原生接入，Capture 宿主接口尚未确认；增加启动和内存成本 | **长期候选，先验证宿主可行性** |
| webview/pywebview 等独立伴随窗口 | 可以较快验证现代页面和 3D，本机服务可复用 | 通用窗口不自动成为 Capture 的 MDI/停靠面板；多窗口焦点管理仍需开发 | 可用于技术实验，不作为真正内嵌已经解决的证据 |
| 自带 WF_WEBKIT 旧示例 | 存在历史 HTML 扩展样例 | 也是旧路径，没有证明比 CEF 更合适 | 不优先投入 |
| 原生 Tcl/Tk 重写完整商城 | 表单可直接接入 Tcl | 需要重写复杂筛选、预览和交互；3D 仍需额外组件 | 当前不建议 |

WebView2 官方 Win32 示例可作为原生宿主参考，`webview/webview` 可作为轻量封装参考，但它们都没有替项目解决 Capture 集成。不要采用直接替换 Cadence `libcef.dll` 的方式升级，也不优先采用跨进程 SetParent 强行嵌入独立窗口；后者有明确的 DPI 兼容限制。

## 4. 代码中具体的性能问题

以下是已读代码的事实与候选措施，不是本轮已经实施的改动。

| 位置/现状 | 对体验的影响 | 候选优化 |
|---|---|---|
| `server/app.py` 的 `_send` 对所有响应统一 `Cache-Control: no-store` | 静态资源和相同预览图没有利用浏览器 HTTP 缓存 | 按资源类型区分缓存；静态资源使用内容版本，预览按器件/模型/尺寸/角度标识；状态和放置响应继续禁止缓存 |
| 多个商城处理函数为请求重新创建 `MallClient()`；其内部已有 Session | 跨本地请求的连接池复用有限 | 使用线程内客户端或有界客户端池；不要直接跨线程共享可变 Session |
| 前端 JSONP 25 秒超时；后台网络调用含多次重试 | 页面先报失败时，后台可能仍在请求，重试会叠加工作 | 建立统一总时限与请求 ID；合并同参数的在途任务；明确超时、取消和后台完成语义 |
| `cancelQuery` 使旧结果失效，没有停止后台网络工作 | 防止旧结果覆盖的逻辑已有，但不能节省已发出的请求 | 在后端阶段边界检查取消标记；保持旧响应隔离，不宣称任何网络操作都可立即中断 |
| `embed.js` 每 300ms 调用 `paintWait`，空闲时也运行 | 存在不必要的定时及 DOM 更新 | 等待存在时才启动更新；仅更新变化字段；现代内核可用 CSS 动画/按需绘制 |
| 图片加载时先隐藏当前图片 | 切换、旋转容易出现空白，放大用户的等待感 | 保留上一帧并叠加局部状态，新图就绪后替换；下载/解析/渲染使用不同文案 |
| 3D 由 `threed/preview.py` 在 Python 中逐像素生成 PNG，新角度形成新请求 | 旋转不是本地 GPU 连续交互；新角度需要 CPU 重新渲染 | 短期按窗口尺寸渲染、拖动低清/结束高清、最新任务优先；长期改为模型一次加载、浏览器本地旋转 |
| `render_model_png` 在带 LRU 的函数内部才把尺寸限制到 1024 | 2048 和 1024 可能占两个缓存键，输出却相同 | 在进入缓存函数前规范化尺寸、角度和模型标识 |
| CAD 解析结果的 `_component_cache` 分支没有总容量界限 | 长时间切换大量器件有内存增长风险，尚未量化 | 有界缓存、明确失效策略，优先按字节预算衡量模型缓存 |

已有能力应保留：HTTP 服务已经是 ThreadingHTTPServer；选中器件的商品详情与 CAD 请求已经并发；OBJ 下载、OBJ 解析、3D PNG 与二维 PNG 已有缓存；搜索结果已分页。不能把“改多线程”“增加缓存”“并行详情请求”当作尚未实现的新方案。JSONP 和文件队列目前承担旧宿主兼容，迁移初期不必同时重写稳定的放置桥接。

## 5. 3D 等待的证据

复用此前同日审计文件 `E:/outputs/.edakit-ui-qa/localization-3d-audit/3d-benchmark.json`，本轮没有重新跑性能测试。C13755 样本有 17,578 个顶点、35,072 个面：

| 场景 | 模型获取 | PNG 渲染 |
|---|---:|---:|
| 首次 1024，yaw=35 | 2.398 秒 | 0.750 秒 |
| 同模型新角度 1024，yaw=50 | 缓存命中，记录为 0 | 0.653 秒 |
| 重复同角度 | 缓存命中 | 缓存命中 |
| 新角度 512，yaw=65 | 缓存命中 | 0.364 秒 |
| 同角度 1024，yaw=65 | 缓存命中 | 0.679 秒 |

因此该样本的“每次重新下载”主要是提示混淆与新角度重绘；不能据此认定所有器件都无网络问题。只有把旋转转移到客户端，才有条件脱离每个角度的 HTTP/CPU 出图路径。

当前 Three.js WebGLRenderer 要求 WebGL2，r163 起不再支持 WebGL1。因此不能直接把当前 Three.js 放进 Chromium 45 代内核。CEF 实验必须先探测实际 GPU/WebGL 能力；若只能运行旧版库，需要评估维护成本，不把长期架构绑定到旧库。

## 6. 分阶段验证方案

### 阶段 A：建立可比较基线

1. 固定同一组数据：4.7kΩ/0603 电阻、RP2040、多参数电源芯片，以及小/大 3D 模型；记录机器、Capture 版本、窗口尺寸和 DPI。
2. 分开测“固定本地响应回放”和“真实商城联网”。前者隔离页面性能，后者记录网络及限流波动。
3. 冷启动、缓存后各重复至少 10 次，记录中位数、P95、原始样本、CPU/内存/句柄。记录点击、请求开始、上游完成、解析结束、图片完成、页面可操作各时间点。
4. 先测当前 OpenURL，再用相同数据测 CEF/WebView2。内核、网络、CPU 渲染与等待文案分别评估，避免把上游慢归因于页面。

### 阶段 B：独立 CEF 能力实验

1. 使用隔离试验入口，不替换现有 EdaKit 菜单和主 Tcl；复用已经启动的本地服务，读取当前 url.txt，不复用历史硬编码端口。
2. 先打开极简同源页面，采集 UA/documentMode、XHR、JSON、requestAnimationFrame、Flex、Canvas、WebGL1/WebGL2；记录 JS 错误及 HTML/CSS/图片的实际 HTTP 状态。
3. 再加载当前工作台，验证资源路径及兼容语法。厂商示例包含浏览器安全选项，不能不经分析直接复制其配置；优先使用同源本地 HTTP 页面与资源。
4. 普通视图通过后验证 CreateControlBar 停靠。区分“窗口成功创建”和“业务可正常使用”。旧 CEF 探索的样式/SVG异常需查请求、端口、路径、解析错误，不能仅凭现象归因。
5. 保留现有 PNG 预览，GPU 3D 另开试验，避免同时引入多个故障来源。

### 阶段 C：业务与稳定性门槛

- 搜索/分类/参数/分页/中文输入法/预览缩放/手册均正常；100%、125%、150% DPI 与三个窗口尺寸检查布局。
- 商城与原理图之间反复切换；放置后跟随光标、单击落位、引脚、Esc、重复放置均需真机回归。停靠面板不能吞掉原理图快捷键。
- 连续选择 100 个器件、开关面板 30 次，确认不会创建重复窗口或残留大量进程；观察内存/句柄是否稳定，不能用单次打开认定无泄漏。
- 弱网、超时、取消、失败重试、旧请求晚返回时，状态准确且旧结果不会覆盖新选择。
- 建议的体验目标：本地操作反馈尽量在 100ms 内；缓存后的轻量面板切换尽量在 200ms 内；GPU 3D 小模型连续旋转以 30fps 为试验目标。这些是待验证目标，不是现有成绩或对联网查询时长的承诺。
- CEF 存在阻断问题时保留 OpenURL，转入 WebView2 宿主实验，不强行迁移。

### 阶段 D：WebView2 宿主实验（有条件开展）

先确认可合法创建/取得 Capture 原生父窗口的接入方式，再参考 Microsoft Win32 C++ 示例创建控制器；验证 STA 消息循环、焦点/键盘、窗口缩放、销毁与重建。先仅加载静态页面，之后复用 HTTP 服务与放置队列。独立伴随窗口只能验证页面，不代表嵌入已完成。

若后续实施，将提供单独试验脚本、准确启动命令、每步预期结果、日志位置和清理/回退方式。本轮没有生成可直接在 Capture 执行的新脚本，无需用户部署或替换程序。

## 7. 外部一手资料

以下为本轮核对的上游来源。网址列为便于交接复查的引用地址。

- CEF 2454 分支 Chromium 兼容声明：`https://raw.githubusercontent.com/chromiumembedded/cef/2454/CHROMIUM_BUILD_COMPATIBILITY.txt`
- Microsoft WebView2 线程模型：`https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/threading-model`
- Microsoft WebView2 性能建议：`https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/performance`
- Microsoft WebView2 控制器：`https://learn.microsoft.com/en-us/microsoft-edge/webview2/reference/win32/icorewebview2controller`
- Microsoft Win32 C++ 示例：`https://github.com/MicrosoftEdge/WebView2Samples/blob/main/SampleApps/WebView2APISample/README.md`
- webview 作者项目：`https://github.com/webview/webview`
- Microsoft SetParent/DPI 限制：`https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setparent`
- Three.js WebGLRenderer：`https://threejs.org/docs/pages/WebGLRenderer.html`

Cadence 的接入结论主要来自本机随附 Tcl 手册与厂商脚本；没有从 Microsoft 或通用开源项目推导出未经证明的 Capture 专用能力。WebView2 的多进程架构也有启动/内存开销，因此最终以同机同负载测量选择，不承诺更换内核后固定提升百分比。
