# Allegro 17.2 手动封装验收

日期：2026-10-21。软件内操作由用户完成；先测试两引脚，再测试 C2040。当前脚本为候选，不能预先保证编译成功。任何一步报错，停止后续操作并保留第一条错误和随后的消息。

## 已备文件

本机测试根目录 `E:/outputs/edakit-native-manual-20261021-r2`，已经生成：

- `two_pin/manual_build.il`：在已新建的专用两引脚 Package Symbol 中生成几何、保存 padstack、保存设计并尝试编译。
- `C2040/manual_build.il`：同样流程，57 个物理引脚。
- 每组另有 `pinmap.json` 和原始 `candidate.il`。本指南只加载 `manual_build.il`，不要混用自动新建的 `candidate.il`。

手动脚本检查 Package Symbol 编辑器、完整设计路径及已有 `.psm`。指定路径之外的设计会被拒绝；已有编译产物也会被拒绝。

## 第一阶段：两引脚 SMD

1. 保存自己正在编辑的工程。使用单独 PCB Editor 窗口测试，或切换到本指南的测试设计。
2. 选择 **File → New**。Drawing Type 选择 **Package symbol**，不要选择 Board、Mechanical symbol 或 Package symbol wizard。
3. Drawing Name 指定完整路径：

   `E:/outputs/edakit-native-manual-20261021-r2/two_pin/EK_NATIVE_2PIN.dra`

   如果窗口要求通过 Browse 选目录，则目录为上述 `two_pin`，文件名为 `EK_NATIVE_2PIN`；软件自动加 `.dra` 时不要重复加扩展名。按 OK；若出现 Drawing Parameters，保留默认值完成创建。当前脚本随后会设置毫米和精度。
4. 在窗口下方 **Command >** 右侧输入框执行以下命令，每条按一次 Enter。当前提示符应是 `Command >`，不是 `skill>`。

   ```text
   skill axlDesignType(t)
   ```

   预期为 package 类型（大小写可能不同）。若为 BOARD，说明仍在板级编辑器，返回步骤 2。

   ```text
   skill axlGetDrawingName()
   ```

   本机可能仅返回 `EK_NATIVE_2PIN.dra`，这不代表创建失败。继续执行下式查看按工作目录展开后的完整路径：

   ```text
   skill simplifyFilename(axlGetDrawingName())
   ```

   应返回上述两引脚 `.dra` 的完整路径。若路径不符，先将空白测试设计 Save As 到指定文件，再重新确认。修订后的脚本会展开相对路径，并打印原始名称、工作目录及展开结果；不会仅凭文件名放行。

5. 加载手动测试脚本：

   ```text
   skill load("E:/outputs/edakit-native-manual-20261021-r2/two_pin/manual_build.il")
   ```

   不需要手动编辑脚本，也不要输入 `lcsc_build_footprint` 第二次。脚本加载后自动执行。成功完成通常返回 `t`；是否成功必须同时检查错误消息、输出文件和回读结果。
6. 若没有错误，按 **F2（Zoom Fit）** 查看。检查两个矩形焊盘和丝印。在 **Find** 面板选择 Pins，用 **Display → Element** 点选焊盘查看信息；也可从 Padstack Editor 打开生成的 `.pad` 核对尺寸。

   | 项目 | 预期 |
   |---|---|
   | 物理编号 | 左 1、右 2 |
   | 坐标（mm） | 1：(-0.9, 0)，2：(0.9, 0) |
   | 铜盘尺寸 | 0.8 × 0.9 mm |
   | 中心间距 | 1.8 mm |
   | 旋转 | 0° |
   | 铜层 | TOP |
   | 孔 | 无钻孔 |
   | 阻焊/钢网 | 本测试按铜盘同尺寸，不代表制造工艺推荐 |

7. 检查 `two_pin` 文件夹中是否生成以下文件，并记录文件大小：

   - `EK_dd84e1687c6265e0f81e.pad`
   - `EK_NATIVE_2PIN.dra`
   - `EK_NATIVE_2PIN.psm`

   仅存在 `.dra` 不算编译成功。若提示缺少 reference designator、symbol 检查失败等，保留完整错误；不要为了通过测试随意补对象，这些结果用于修正生成器。
8. 若已生成 `.psm`，关闭测试设计再用 **File → Open** 打开保存的 `EK_NATIVE_2PIN.dra`，再次检查两个引脚及 padstack 是否仍然存在。`.psm` 的板内放置/回读将在后续隔离 PCB 验收中单独检查。

## 第二阶段：C2040

当前使用 r3 独立目录。r2 在创建填充区域时报告边界非法、自相交；生成器现已为全部 116 个区域显式闭合边界，并清理输出精度下连续重复点、拒绝退化区域。依据本机 `D:/Cadence/SPB_17.2/doc/algroskill/03dbcre8.html` 的 Create Shape Interface，边界起点与终点必须相等。相关 Python 测试 50 项通过；原生编译仍待本轮人工验证。保留 r2 失败现场，不在其部分生成的设计上重复加载。

仅在两引脚阶段确认通过后执行。再次 **File → New → Package symbol**，名称指定：

```text
E:/outputs/edakit-native-manual-20261021-r3/C2040/C2040_QFN56_EP.dra
```

同样先执行 `skill axlDesignType(t)`、`skill axlGetDrawingName()` 确认编辑器和路径，再执行：

这里使用不含额外点号的测试别名 `C2040_QFN56_EP`，避免 New Drawing 对文件名扩展部分的处理产生歧义。原始封装名称保留在 `pinmap.json` 的 `source_footprint_name`；此别名只用于隔离测试，正式 Capture 与 PCB 库名称映射仍需统一处理。

```text
skill load("E:/outputs/edakit-native-manual-20261021-r3/C2040/manual_build.il")
```

检查外圈编号 1–56、中心 EP 编号 57，实际共 57 个物理引脚，不能因名称 QFN-56 排除 EP。检查 `pinmap.json` 中全部编号、铜盘、中心位置、丝印和装配图层，并确认同名 `.dra/.psm` 与多个 `EK_*.pad` 输出。外圈与中心焊盘有不同几何，不应强行要求只有一个 padstack。

功能名保存在 `pinmap.json`。PCB 焊盘仍使用物理编号：两引脚测试显示 1、2，不要求显示 A、K；C2040 也不能将物理编号改成功能名称。

## 常见情况与反馈

| 情况 | 操作 |
|---|---|
| `create a Package Symbol first` / `expected package symbol` | 检查 File → New 的 Drawing Type |
| `wrong test drawing path` | 用 `skill axlGetDrawingName()` 查看实际完整路径并反馈 |
| `output already exists` | 已有 `.psm`，不要反复运行；保留产物供检查，下一轮使用新目录 |
| 其他 `*Error*`、`EdaKit: ... failed`、编译警告 | 停止后续步骤，保留第一条错误及其前后消息 |
| 看不到图形 | 无错误时先 F2；仍无显示则反馈，不判定成功 |
| 再次加载导致重复对象 | 停止，不在同一半成品设计中重跑；保留失败现场后换新目录 |

建议反馈模板：

```text
阶段：两引脚 / C2040
axlDesignType(t)：
axlGetDrawingName()：
加载后的第一条错误及前后消息：
.pad / .dra / .psm 是否生成、文件大小：
引脚数量、编号、尺寸、层核对结果：
关闭并重新打开 .dra 后的结果：
```

截图中的 `GTSys_Int` 为既有 `GTAllegro` 启动加载报错。记录即可；若本测试执行 SKILL 时也出现问题，再区分处理。当前测试不要求修改用户启动配置。

下一阶段才是原生回读报告、Capture footprint 检查及隔离 PCB 网表导入；上述检查不能替代该阶段。
