# PCB 封装生成与校验方案

更新：2026-10-21。目标宿主为本机 OrCAD Capture / Allegro 17.2。本文替代早期“生成 .il 即完成封装”的规划。当前实现是 **EasyEDA 现有几何转换 + 生成前编号校验 + SKILL 候选脚本**；尚未取得 Allegro 原生验收结果，也尚未实现 IPC 参数化计算。

## 依据与取舍

| 一手资料 | 核对内容 | 本项目采用方式 |
|---|---|---|
| 本机 Cadence 17.2 `doc/cap_ug/Assigning_Footprint_Properties.html`，Assigning footprints to components | 符号与 PCB footprint 引脚数量及编号必须匹配 | 生成文件、复用 Capture 缓存之前执行硬校验 |
| 本机 `doc/algrolibdev/chap3.html`，Package Symbols / Adding Pins；`chap5.html`，PINORDER | 逻辑编号与 package pin number 匹配；机械孔可无电气编号；器件功能名另有逻辑映射 | 不把 GPIO/GND 当成物理焊盘编号，不把无号铜焊盘猜作机械孔 |
| [Cadence Allegro PCB Librarian 官方说明](https://login.cadence.com/content/dam/cadence-www/global/en_US/documents/tools/pcb-design-analysis/allegro-pcb-librarian-xl-ds.pdf) | footprint validation 比对符号与封装编号，详细 packaging check 包括网表和布局 | 自动测试之后增加原生回读、网表及隔离 PCB 导入验收 |
| [uPesy/easyeda2kicad.py 的 PAD 模型](https://github.com/uPesy/easyeda2kicad.py/blob/master/easyeda2kicad/easyeda/parameters_easyeda.py) | PAD 存在 number、net、几何、孔与镀铜字段，没有独立功能名 | 核对字段定义，保留原始数据；不把 net 当 pin name |
| [pointhi/kicad-footprint-generator](https://github.com/pointhi/kicad-footprint-generator/blob/master/README.md) | 参数文件、封装族脚本与几何树分离；仓库已声明迁往 KiCad GitLab | 借鉴“输入参数 → 几何模型 → 目标格式输出”；其 KiCad 输出不能直接当 Allegro API 用 |
| [Footprint Expert：Calculation Mode Options](https://www.pcblibraries.com/Products/FPX/UserGuide/Calculation%20Mode%20Options/) | Min/Max 模式使用尺寸公差及焊点目标；Nominal 使用标称尺寸 | 后续参数化路线明确模式、标准版本、参数与公差，禁止仅凭封装字符串猜尺寸 |
| [Footprint Expert：FPX File Guidelines](https://www.pcblibraries.com/Products/FPX/UserGuide/FPX%20File%20Guidelines/) | 封装尺寸、厂家推荐焊盘、旋转与逻辑属性；用户选项分离保存；要求核对厂家手册 | 厂家推荐图形、源几何转换、参数计算分别标记来源，统一版本化工艺配置 |

本机官方文档根目录：`D:/Cadence/SPB_17.2/doc/`。API 签名查 `algroskill` 对应函数页，不能用其他版本或开源转换器的调用代替本机手册。外部代码仅作为设计参考，本轮没有引入其源码或新增运行依赖。

## 数量、编号与名称的统一规则

1. **物理编号精确一致。** Capture `Pin.number` 对 Allegro package `pin number`，保留 `A1`、`01` 等字符串，不改大小写、不补号、不按列表顺序重编号。NC、EP、散热焊盘只要属于电气引脚就计入；例如 C2040 实际为 57 个引脚，不能按封装名中的 56 排除 EP。
2. **比较实际物理引脚。** 同编号、同位置、同旋转的跨层形状经验证后合为一个 padstack；同层重复编号直接报错。合并结果必须与原始 pads 重算结果相同，防止过期 padstack 被输出。本阶段不支持重复逻辑引脚／多位置同号铜盘，遇到此类真实器件需先设计显式映射，不能自动丢弃。
3. **功能名称随编号继承。** 生成 `<cid>.pinmap.json`，保存每个编号的原理图名称，例如 `9 → GPIO7`。若 PCB 输入另外提供可靠功能名，则逐号精确校验；冲突即阻断。当前 EasyEDA Standard PAD 不提供独立功能名，清单明确 `independent_pad_names_checked=false`、`name_status=symbol_name_mapping_only`。这表示“名称映射已保存”，不等于“两个独立来源名称已核对”。
4. **编号与功能名分开存储。** PCB 原生 pin number 必须仍是 `9`，不能改为 `GPIO7`。功能名保存在配对元数据；今后需要在 PCB 中显示功能名时，再通过经原生验证的属性或注释承载，不改变连接标识。
5. **机械孔单独建模。** 独立 HOLE 不计电气数量；当前 SKILL 对 HOLE 尚不支持，完整封装候选仍会拒绝。无号 PAD 不猜测用途，生成前拒绝，待增加明确的机械／NPTH 模型后支持。
6. **不匹配为错误。** `PinMappingError` 在写入配对文件或复用缓存前抛出，适用于完整导出和 Capture-only。已有成功结果不覆盖。缺少符号或封装时保留现有单项导出兼容行为，并显示缺项警告；不能声称完成配对验证。

## 两条生成路线

**路线 A：已有封装几何转换，当前优先。** 从器件 CAD 数据读出真实焊盘／丝印／装配／填充及模型原点，转成 mm 中间模型，执行编号、几何与层检查，再输出隔离候选。源尺寸保持原值，不自动用 IPC 推荐值替换。坐标原点来自 canvas，封装 Y 不翻转；方向与旋转仍要用带方向性的样例在 Allegro 对照确认。

**路线 B：指定封装的参数化生成，后续开发。** 用户选择封装族并给出厂家数据手册版本及页面、引脚布局、尺寸和公差、热焊盘、安装高度、厂家推荐 land pattern（如有）。再选择厂家推荐尺寸或明确版本的计算模式，配置 toe/heel/side、密度、阻焊扩展、钢网缩减、丝印间距、装配及放置边界。缺少必要参数即停止计算。先实现 Chip 两端、SOIC/SOP、QFP、QFN/DFN，再扩展 BGA、连接器和槽孔。不能把“0603 / QFN-56”字符串直接作为完整尺寸依据，也不能将当前的 1:1 阻焊／钢网复制宣称为 IPC 计算结果。

两条路线共用 `Symbol / Footprint / Padstack → 配对校验 → 几何检查 → Allegro 输出 → 原生验收`。工艺选项、计算模式和数据来源应与器件几何分别版本化；参数改变重新计算、重新验收。路线 B 尚处于设计阶段。

## 原生输出和发布门槛

| 阶段 | 产物／检查 | 当前状态 |
|---|---|---|
| 输入 | 原始 JSON、精确编号、功能名映射、mm 坐标 | 已有六个真实离线样本 |
| 配对预检 | 集合、数量、重复、名称冲突、跨层合并与过期数据检查；pinmap JSON | 本轮实现 |
| 候选输出 | `.il`；矩形／圆／OBLONG padstack、直线、圆、M/L/Z 区域、PLACE_BOUND | 已有；API 调用仍待真机验收 |
| 几何缺项 | ARC、独立 HOLE、RECT、未知层／曲线路径等 | 拒绝相应 PCB 脚本；完整 stage 可返回 Capture/STEP 子项及 warning，不能算 PCB 导出成功 |
| 原生构建 | 隔离符号编辑器生成 `.pad/.dra/.psm`；检查返回值与输出文件 | 待完成 |
| 回读和导入 | 回读实际编号、位置、尺寸、层；Capture footprint 检查；网表导入隔离 PCB | 待完成 |
| 发布／复用 | 通过验收后写入库索引和内容摘要；同名异几何不能复用 | 后续实现；当前脚本拒绝覆盖 `.dra/.psm` |

当前以几何内容散列命名 padstack，仍需验证已有同名 `.pad` 的内容、孔镀铜、内层规则、阻焊／钢网选项、文字及高度等完整性。脚本文本出现某个 SKILL 函数不证明原生签名或编译结果正确。最近可用的 Capture 程序继续保持已验收版本，本轮源码尚未重新打包部署。

## 下一步验收顺序

1. 在独立工作目录先验证两端 SMD：确认单位、原点、方向、旋转、pin number、padstack、位号和保存编译。
2. 验证 C2040：57 个物理引脚、EP=57、116 个填充区域，逐层比较，查实际 `.psm` 编号集合；核对 DOCUMENT/BOARD_OUTLINE 与极性层的暂定映射。
3. 增加圆孔通孔、底层焊盘、槽孔／NPTH 模型；每类先建立原生参考再实现，暂不对不支持几何作近似替换。
4. 用生成 Capture 符号建立最小测试原理图，运行 footprint pin 检查，生成网表并导入隔离 PCB，核对连线、名称映射、EP 和 DRC；保存原生日志与截图。
5. 确认上述链路后，再加入工作台“生成 PCB 封装”入口、候选／已验收状态和参数化封装族编辑。

自动化回归覆盖输入及输出约束，不能替代以上 Allegro 17.2 原生验收。项目整理与测试结果见[本轮记录](PCB方案重整与验证-20261021.md)。

2026-10-21 接续：已准备两引脚与 C2040 隔离输入及启动探针；自动启动未到达 SKILL，原生验收尚未开始。详见 [Allegro 原生验收记录](Allegro原生验收-20261021.md)。

后续手动验收：两引脚样本补齐绘图范围与 REF DES 对象后，在用户本机编译成功；C2040、尺寸回读和网表导入仍待验证。REF DES 前缀现从原理图 `Symbol.prefix` 传入，丝印及装配一致生成 R*/C*/L*/U* 等占位文字，支持原始多字母前缀，不按封装名猜测器件类别。
