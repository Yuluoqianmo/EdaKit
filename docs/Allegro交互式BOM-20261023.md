# Allegro 交互式 BOM

更新：2026-10-23。用户已确认当前显示效果可用，并要求清理项目及同步 Git。

## 使用

1. 在 Allegro PCB Editor 中打开板，选择 **EdaKit → Interactive BOM...**。
2. 在独立导出窗口设置输出目录。默认使用板内器件信息；如需最终物料编码或补充字段，取消对应勾选并选择最终 BOM 表。
3. 点击导出，等待 IPC 提取、属性读取、封装解析和 HTML 写入完成。默认自动打开结果。
4. 修改 PCB 后重新打开导出窗口，取得新的当前内存板快照。更新程序后重新导出 HTML，旧文件不会自动更新。

首次安装或原生入口更新后，保存工程并重启 Allegro。菜单只有一个导出窗口入口；目录和 BOM 设置集中在窗口中。窗口失败可重试，日志支持滚动和长路径换行；导出期间防止关闭导致快照提前清理。

菜单使用 `axlRunBatchDBProgram` 取得当前内存板的临时快照，`reloadDB=nil`，不覆盖或重新加载用户原板。直接把原板文件传给 IPC 工具不能代替该快照链；本机测试中存在 Allegro 可打开但 IPC 工具无法直接读取的原板副本。

默认输出位于原板目录的 `Output_Files/iBOM/`。每次生成带时间戳的新 HTML 和同批 `.report.txt`，不覆盖旧结果。设置仅在成功导出后保存，按原板完整路径区分。

## BOM 与二维板图

默认读取 PCB 属性及 IPC BOM，包括描述、值、封装、厂家、`Manufacturer_PN` 和内部物料号。厂家型号只取原生 `Manufacturer_PN`，不存在则留空。外部 `.xlsx/.csv/.tsv/.txt` BOM 按完整位号关联；未装记录（`populate=false` 或 `BOM_IGNORE`）不能通过外部 BOM 重新加入，测试点按原引擎 TP/testcoupf 规则排除。无坐标物料由报告列出，不猜测位置。

查看器复用 `cadence-ibom` 引擎，保留搜索、Top/Bottom、缩放平移、BOM/板图双向定位、仅当前 BOM、完成标记、本地进度保存和 CSV/XLSX 导出。真实焊盘始终显示；本体边框优先取 AssemblyDrawing 多边形，再取装配线条或 SilkScreen，不叠加 Package Outline 外围包络或定位圆点，也不虚构缺失本体。

Allegro IPC 的 Component Location 是封装原点，局部几何按实例旋转和平移，不再重复减去 PickupPoint 质心。PolyStepCurve 按圆心和顺逆时针展开圆弧，最大步进 2°。当前板 J1/J2/J8/U25 共 86 个引脚与隔离 Allegro 的原生 pin->xy 比较，最大误差约 3.18e-14 mm。

丝印位号来自同次快照的 REF DES/SILKSCREEN_TOP/BOTTOM 附属文字边界、旋转和镜像，只显示当前选中 BOM 项对应器件。使用浏览器字体拟合原生范围，不宣称逐笔复现 Cadence 字模；缺少记录时不补造标签。

## 离线三维预览

点击“3D 预览”进入，点击“简图”返回；拖动旋转、滚轮缩放、Shift 拖动平移，复位恢复初始角度。BOM 与 3D 双向选择，选中变色、橙色线框和位号数量提示；支持仅当前 BOM、完成状态和顶底面切换。相机动态收紧裁剪范围，配合对数深度和板面/焊盘偏移，减少近距离缺块。

优先读取原生 STEP 绑定及安装姿态，使用 `axlDMFindFile("ALLEGRO_STEP", ...)` 的完整路径，支持 `.stp/.step`。原 STEP 缺失时，读取 Allegro 的真实三角网格缓存：`ALLEGRO_STEP_FACET` / `STEP_FACET_PATH`，以及原生 PSM 所在库目录下的 `stepFacetFiles4Map/*.xml`。这解释了部分原 STEP 已缺失但 Allegro 内置预览仍能显示模型的情况。

缓存解析保留装配关系、单位、颜色和逐角点法线，再应用板上模型姿态；硬边拆分顶点，法线按逆转置变换。模型 RGB 按 sRGB 转换到线性空间，调整光照，避免黑色封装泛灰。所有器件共用真实焊盘与丝印绘制。背景和近黑板色是参考截图设置的显示样式，不是从原生阻焊颜色读取。

IPC PadStackDef/PadstackHoleDef 与封装 Pad 实例提供真实圆孔，按实例姿态变换后切开板体和铜焊盘，包含 BOM 外安装器件。当前未覆盖完整铜走线、过孔、槽孔和全部丝印图层；板厚仍明确标注默认 1.6 mm 示意。

模型缺失、解析失败或超限时本体留空，只显示真实焊盘和封装丝印，不生成替代方块。单模型原文件限 25 MB，内嵌模型合计限 80 MB，缓存限 50 万三角面；按内容去重。实际 STEP 与 three.js/OCCT 运行库按需内嵌，缓存模型直接内嵌网格，离线不访问 CDN。STEP/WASM 仅在有 STEP 格式数据时引入。许可及固定版本见 `src/edakit/ibom/vendor/README.md`、`UPSTREAM.md` 与 `NOTICE`。

## 验证和限制

最终全量回归 **646 passed / 2 skipped**；冻结程序 **12 项自检通过**。隔离 Allegro 的原生快照链完整导出成功；未修改或关闭用户原板。

当前验证板包含 237 个可见器件：**198 个真实模型**（6 份去重缓存），39 个缺失，其中 22 个无 STEP 绑定、17 个文件和缓存均未找到；解析 **84 个封装钻孔**。实际模型库 108 份 XML 解析成功；大写 STEP 名称和带空格原生缓存路径已验证。

Edge/Playwright 在 1450×950、850×700 验证真实厚度、双向选择、仅当前 BOM、旋转缩放、复位、切回二维与离线加载，无脚本错误或网络请求。Browser 插件未提供，因此使用现有 Playwright 环境。模型覆盖、板厚和未导出的物理图层边界以上文为准，不能将这些检查等同于 Allegro 完整机械视图。

本机验收文件（不入 Git）：

- 预览：`E:/123/HTD100_MB_V0_iBOM_appearance_review.html`。
- 最终冻结导出：`E:/outputs/edakit-ibom-appearance-frozen-output/HTD100_MB_V0_iBOM_20261023_135347_55365b6c.html`。
- 截图：`E:/outputs/edakit-ibom-appearance-detail.png`。
- 回退备份：`E:/outputs/backups/edakit-before-ibom-appearance-20261023`。

## 安装、诊断与开发

安装器在 `pcbenv/allegro.ilinit` 追加带标记的加载块，保留其他脚本字节并创建首次备份；入口为 `pcbenv/edakit/ibom.il`。常规 `edakit deploy` 一并安装，也可单独执行：

```powershell
edakit-cli.exe ibom-deploy --cadence-root D:/Cadence/SPB_17.2 --executable E:/outputs/edakit/dist/edakit.exe
```

命令行诊断（`--board` 应为可由 IPC 工具读取的板或原生临时快照）：

```powershell
edakit-cli.exe ibom-export --board <snapshot.brd> --source <original.brd> --cadence-root D:/Cadence/SPB_17.2 --output <absolute-output-directory>
```

导出作业保存在 `%LOCALAPPDATA%/edakit/ibom/jobs/`：IPC 数据、原生日志、BOM、`models3d.json` 逐位号模型文件/格式/缺失原因、结果回执及错误。输出设置和各板 BOM 选择保存在 `ibom/settings.json`，不进入 Git。独立窗口持有同批板快照及丝印/模型侧车，关闭后清理。

源码位于 `src/edakit/ibom/`，原生模板在 `src/edakit/install/templates/ibom.il`，测试在 `tests/test_ibom.py` 与 `tests/test_ibom_facets.py`。当前本机 GUI/CLI 位于 `dist/`，散列见 `dist/release-sha256.json`；二进制、用户板/库/配置及验收输出不进入 Git。清理明细见 [本轮清理记录](清理记录-Allegro交互式BOM-20261023.json)。
