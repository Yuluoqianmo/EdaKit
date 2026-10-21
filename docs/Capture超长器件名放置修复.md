# Capture超长器件名放置修复

2026-10-21。用户反馈C5123614放置失败，页面返回build-olb阶段“Capture did not keep part”。

## 核查证据

- 商城显示型号HoARG0603-1/10W-5.1KR-0.1%-TCR25，CAD符号实际名 `HOARG0603-1/10W-5.1KR-0.1%-TCR25`，32个ASCII字符。
- 原始暂存XML和合并XML都存在完整Package名；失败发生在XMATIC建库/规范化后的名称回读检查，尚未调用本次PlaceNew。
- Cadence社区有同一XMATIC错误记录：`ORDBDLL-1099`、名称最大31字符，见[原帖](https://community.cadence.com/cadence_technology_forums/pcb-design/f/allegro-x-capture-cis/47734/capture-part-name-length-more-than-31-characters/1373623)。不同版本/设置可能存在差异，本项目采取兼容当前环境的31字符内部名预算，不修改Capture全局设置。
- 先前 `MF1/2W-4.7KΩ±1% T52` 原生调用正常，不能简单把斜线、百分号或Unicode一概判为非法。此次32字符超过兼容预算，与现象一致；修复后实际Capture回读与落位仍待用户重试。

## 修复

新增symbol/naming.py集中生成内部Package名。已经可用且UTF-8长度不超过31的短名保持原样；超长名生成ASCII前缀加C编号，不超过31字符。非标准编号使用确定性摘要作为后缀，避免直接截断造成重名。UTF-8字节预算只是保守兼容策略，不声称原生限制就是UTF-8字节数。

此器件的新内部名：`HOARG0603-1_10W-5_1KR-_C5123614`（31字符）。Package/CellName与放置队列共用这一值。完整CAD型号保留在PartValue，商城型号/C编号、引脚、几何和PCB封装名不变。

商城准备、CLI place、build路径同步采用规则，避免“建库名改了、放置请求仍是原名”。不放宽或绕过Tcl回读检查，不删除用户库，不重放失败队列，也不改已安装Tcl。

## 验证

- 短名RP2040、已通过电阻型号、短Unicode型号保持；31/32边界、不同C编号不重名、超长Unicode/异常编号均有用例。
- XML中Package/CellName采用内部名，PartValue仍保留32字符完整名；真实生成文件与队列一致的接口回归通过。
- 打包版隔离运行，真实获取C5123614并提交stage_only请求，确认新名31字符、XML/队列一致、Value完整，11项exe自检通过。隔离队列不连接用户Capture，没有向工程放置器件。
- 全套测试和最终哈希记录于项目交接；本轮UI和Tcl未修改，无需deploy。

## 用户重试

1. 重新点击EdaKit → LCSC Mall，启动更新后的服务；当前页面状态可能重置，无需重启Capture或deploy。
2. 搜索 `C5123614`，确认型号与预览正确，再点击放置。预期不再出现build-olb保留零件名失败，进入光标跟随。
3. 在测试原理图单击落位，检查两只引脚与Esc；测试图可不保存。
4. 再测试一个此前成功的短名称电阻，确认没有回归。
5. 若仍失败，反馈完整新错误和 `edakit.log`、`background.log` 最后80行。新错误中的零件名应为上面的短别名；若仍是32字符原名，说明旧服务/页面未切换。

## 回退

更新前GUI/CLI备份为 `dist/edakit.before-part-name-fix-20261021.exe` 和 `dist/edakit-cli.before-part-name-fix-20261021.exe`。保存工程、退出Capture并确认旧服务退出后复制回主路径即可；Tcl未改无需deploy。源码、测试和文档备份：`E:\outputs\backups\edakit-before-part-name-fix-20261021.zip`。
