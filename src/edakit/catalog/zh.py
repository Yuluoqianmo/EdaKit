"""Local Chinese display names. Upstream IDs and English originals stay intact."""
import re
from .glossary import CATEGORY_LABELS

_EXACT = {}
for _line in '''Audio Products|音频器件
Battery|电池
Battery Products|电池及配件
Boxes, Enclosures, Racks|机箱、外壳与机架
Cable Assemblies|线缆组件
Cables, Wires|线缆与导线
Cables, Wires - Management|线缆管理
Capacitors|电容器
Circuit Protection|电路保护
Computer Equipment|计算机设备
Connectors, Interconnects|连接器与互连器件
Development Boards, Kits, Programmers|开发板、套件与编程器
Discrete Semiconductors|分立半导体
Embedded Computers|嵌入式计算机
Fans, Blowers, Thermal Management|风扇、鼓风机与热管理
Fans, Thermal Management, HVAC|风扇、散热与暖通
Filters|滤波器
Finished Cable Assemblies|成品线缆组件
Hardware, Fasteners, Accessories|五金、紧固件与配件
Industrial Automation and Controls|工业自动化与控制
Integrated Circuits (ICs)|集成电路
Isolators|隔离器
Kits|套件
Labels, Signs, Barriers, Identification|标签、标识与防护
Lighting|照明
Line Protection, Distribution, Backups|线路保护、配电与后备电源
Maintenance, Repair & Operations|维护、维修与作业用品
Maker/DIY, Educational|创客、DIY 与教学
Material Handling|物料搬运
Measuring & Inspecting|测量与检测
Memory - Modules, Cards|存储模块与存储卡
Motors, Actuators, Solenoids and Drivers|电机、执行器、电磁铁与驱动器
Networking Solutions|网络设备
Office Supplies|办公用品
Optoelectronics|光电器件
Passives|无源器件
Power Supplies|电源
Power Supplies - Board Mount|板载电源
Power Supplies - External/Internal (Off-Board)|外置及内置电源（非板载）
Prototyping, Fabrication Products|原型制作与加工用品
Relays|继电器
Resistors|电阻器
RF and Wireless|射频与无线
Safety Products|安全防护用品
Sensors, Transducers|传感器与变送器
Soldering, Desoldering, Rework Products|焊接、拆焊与返修用品
Switches|开关
Tapes, Adhesives, Materials|胶带、胶粘剂与材料
Temporary|临时分类
Test and Measurement|测试与测量
Tools|工具
Tools & Consumables|工具与耗材
Transformers|变压器
Chip Resistor - Surface Mount|贴片电阻
Chip Resistors|贴片电阻
Through Hole Resistors|直插电阻
Current Sense Resistors|电流采样电阻
Resistor Networks, Arrays|排阻与电阻网络
Ceramic Capacitors|陶瓷电容
Aluminum Electrolytic Capacitors|铝电解电容
Tantalum Capacitors|钽电容
Film Capacitors|薄膜电容
Fixed Inductors|固定电感
Ferrite Beads and Chips|磁珠
Common Mode Chokes|共模电感
Microcontrollers|微控制器
Embedded MCU, DSP Evaluation Boards|微控制器、DSP 评估板
Real Time Clocks|实时时钟
Operational Amplifiers|运算放大器
Op Amp Evaluation Boards|运算放大器评估板
Batteries Non-Rechargeable (Primary)|一次电池（不可充电）
Batteries Rechargeable (Secondary)|二次电池（可充电）
Headers, Male Pins|排针
Headers, Receptacles, Female Sockets|排母与插座
Uncategorized|未分类
Global Source|全球货源
Accessories|配件
Specialized|专用器件
Miscellaneous|其他
'''.splitlines():
    if '|' in _line:
        _a, _b = _line.split('|', 1)
        _EXACT[_a.lower()] = _b

# Product nomenclature is composed from a local technical vocabulary. Exact
# electronics names above take precedence; originalName remains available as
# a tooltip so abbreviations and uncommon upstream names can be checked.
_WORDS = {}
for _pair in '''accessory=配件 and=与 connector=连接器 power=电源 sensor=传感器 switch=开关 cable=线缆 industrial=工业 assembly=组件 module=模块 board=板 wire=导线 converter=转换器 kit=套件 fiber=光纤 capacitor=电容器 protection=保护 adapter=适配器 relay=继电器 driver=驱动器 optic=光学 specialized=专用 evaluation=评估 lighting=照明 controller=控制器 modular=模块式 supply=电源 solid=固态 management=管理 circuit=电路 memory=存储器 product=产品 ethernet=以太网 state=状态 to=至 sub=子类 flat=扁平 current=电流 housing=外壳 socket=插座 terminal=端子 analog=模拟 filter=滤波器 output=输出 transformer=变压器 battery=电池 card=卡 circular=圆形 shaped=形 voltage=电压 equipment=设备 digital=数字 logic=逻辑 safety=安全 component=元件 coaxial=同轴 rectangular=矩形 thermal=热管理 type=类型 panel=面板 linear=线性 soldering=焊接 audio=音频 barrel=圆筒式 purpose=用途 heavy=重型 duty=工业 mount=安装 embedded=嵌入式 potentiometer=电位器 configurable=可配置 resistor=电阻器 desoldering=拆焊 diode=二极管 off=离线 programmable=可编程 fan=风扇 transmitter=发射器 oscillator=振荡器 signal=信号 regulator=稳压器 isolator=隔离器 test=测试 tie=扎带 shrink=热缩 label=标签 solder=焊锡 specialty=专用 blade=刀片式 edge=边缘 pressure=压力 flexible=柔性 array=阵列 block=模块 interface=接口 magnetic=磁性 programmer=编程器 variable=可变 special=专用 tape=胶带 temperature=温度 proximity=接近 transducer=变送器 receiver=接收器 light=光 measuring=测量 detector=检测器 transceiver=收发器 tool=工具 holder=支架 rack=机架 development=开发 pluggable=可插拔 line=线路 single=单 fastener=紧固件 tubing=管材 breaker=断路器 plug=插头 backplane=背板 spacer=间隔柱 pin=引脚 wireless=无线 discrete=分立 hardware=五金 position=位置 machine=机械 integrated=集成 clock=时钟 motor=电机 optoisolator=光耦隔离器 optical=光学 cleaning=清洁 station=工作站 rework=返修 clip=夹具 box=盒 enclosure=外壳 jumper=跳线 video=视频 conductor=导体 up=向上 grip=夹持件 support=支撑件 boot=护套 cap=盖 fuse=熔断器 keystone=梯形模块 photovoltaic=光伏 solar=太阳能 header=排针 distribution=分配 strip=条带 computer=计算机 finished=成品 wrench=扳手 automation=自动化 encoder=编码器 cell=电池 camera=摄像 camera/sensors=相机与传感器 monitor=监测器 microcontroller=微控制器 gate=门极 amplifier=放大器 divider=分频器 comparator=比较器 switching=开关式 display=显示器 inspecting=检测 crystal=晶体 external=外置 internal=内置 contactor=接触器 unit=单元 stop=停止 batteries=电池 between=之间 series=系列 firewire=火线 flex=柔性 grommet=护线圈 wrap=绕包 sleeving=套管 duct=线槽 raceway=布线槽 gas=气体 receptacle=插座 insert=嵌件 tip=针尖 jack=插孔 clamp=夹具 terminator=终端器 multi=多 magnetics=磁性器件 direct=直接 transistor=晶体管 rail=导轨 turret=塔式 disconnect=断开 bridge=桥式 through=贯穿 standoff=支撑柱 miscellaneous=其他 washer=垫圈 numeric=数字 color=颜色 level=液位 flow=流量 load=负载 thermostat=温控器 meter=仪表 pneumatic=气动 time=时间 delay=延时 timing=定时 buffer=缓冲器 frequency=频率 touch=触摸 field=现场 device=器件 multiplexer=多路复用器 splitter=分配器 inverter=反相器 hot=热插拔 over=超过 sign=标牌 adhesive=胶粘剂 brush=刷子 paper=纸 tweezers=镊子 film=薄膜 bar=条 educational=教学 networking=网络 solution=方案 router=路由器 storage=存储 lamp=灯 optoelectronics=光电器件 indicator=指示器 resonator=谐振器 attenuator=衰减器 antenna=天线 material=材料 gauge=测量计 reed=干簧 pushbutton=按钮 rotary=旋转 electric=电动 iron=烙铁 fabrication=加工 tester=测试仪 measurement=测量 drive=驱动 network=网络 inductor=电感器 photo=光电 applicator=施胶器 alarm=报警器 buzzer=蜂鸣器 siren=警笛 rechargeable=可充电 patchbay=配线架 centronics=并行接口 ribbon=排线 multiple=多 hook=挂钩 bushing=衬套 cord=电源线 mounting=安装 zip=捆扎 labeling=标注 sleeve=套管 spiral=螺旋 expandable=可扩展 electrical=电气 fuseholder=熔断器座 discharge=放电 tube=管 arrester=避雷器 inrush=浪涌 limiter=限制器 surge=浪涌 transient=瞬态 suppressor=抑制器 thyristor=晶闸管 varistor=压敏电阻 interconnect=互连 entry=输入 hard=硬质 standard=标准 banana=香蕉 backshell=后壳 spring=弹簧 loaded=加载 hood=罩 frame=框架 with=带有 shunt=短路帽 for=用于 barrier=隔离栅 channel=通道 junction=接线 system=系统 terminals=端子 quick=快速 screw=螺钉 splice=接续 complex=复杂 regulator=稳压器 semiconductor=半导体 regulation=调节 rectifier=整流器 pad=焊盘 brushless=无刷 finger=指形 guard=防护件 sink=散热器 assortment=组合 hole=孔 nut=螺母 rivet=铆钉 bolt=螺栓 tap=丝锥 control=控制 float=浮球 force=力 speed=速度 mechanical=机械 ultrasonic=超声波 hydraulic=液压 hose=软管 application=应用 specific=专用 generator=发生器 data=数据 front=前端 end=端 array=阵列 chip=芯片 decoder=解码器 modem=调制解调器 universal=通用 counter=计数器 latch=锁存器 charger=充电器 laser=激光 optocoupler=光耦 identification=识别 sticker=贴纸 decal=贴花 tag=标签 work=作业 protective=防护 miniature=微型 residual=剩余 heating=加热 lab=实验室 glass=玻璃 container=容器 laboratory=实验室 weighing=称重 maker=创客 robotics=机器人 handling=搬运 shipping=运输 packaging=包装 dimensional=尺寸 actuator=执行器 solenoid=电磁铁 gateway=网关 media=介质 serial=串行 server=服务器 office=办公 double=双 magnifying=放大 optics=光学器件 graph=图表 circuitry=电路 incandescent=白炽 neon=霓虹 engine=模组 indication=指示 passive=无源器件 supplier=电源 electromechanical=机电式 directional=定向 coupler=耦合器 shield=屏蔽罩 fingerstock=指形簧片 gasket=衬垫 shielding=屏蔽 absorbing=吸收 foot=脚踏 multifunction=多功能 particle=颗粒 dust=粉尘 strain=应变 pull=拉线 emergency=紧急 interlock=联锁 keylock=钥匙 limit=限位 rocker=翘板 selector=选择 tactile=轻触 temporary=临时 uncategorized=未分类 consumable=耗材 assorted=组合 pump=泵 drill=钻头 file=锉刀 hammer=锤 handle=手柄 gun=枪 air=空气 plier=钳 punch=冲头 sandpaper=砂纸 screwdriver=螺丝刀 pot=锡炉 stand=支架 welding=焊接 workbench=工作台 prototyping=原型制作 angle=角度 environmental=环境 character=字符 aluminum=铝 polymer=聚合物 ceramic=陶瓷 tantalum=钽 choke=扼流圈 ferrite=铁氧体 coil=线圈 adjustable=可调 slide=滑动 thumbwheel=拨轮 surface=表面 sense=检测 compass=罗盘 magnet=磁铁 motion=运动 photointerrupter=光电断续器 slot=槽型 reflective=反射式 thermistor=热敏电阻 probe=探头 crimper=压接钳 press=压机 step=级 buzzer=蜂鸣器 element=元件 piezo=压电 bender=弯曲片 microphone=麦克风 speaker=扬声器 non=非 primary=一次 secondary=二次 guide=导轨 pre=预 leads=引线 extension=延长 smart=智能 marker=标记 resettable=自恢复 suppression=抑制 cutoff=截止 mixed=混合 technology=技术 metric=公制 edgeboard=板边 pogo=弹簧探针 leadframe=引线框架 jackscrew=锁紧螺钉 base=底座 faceplate=面板 inline=直插 mezzanine=夹层 in=插入 stacker=堆叠件 free=自由 hanging=悬挂 male=公 female=母 bullet=子弹头 foil=箔 knife=刀式 lug=接线片 post=柱 connect=连接 ring=环形 spade=叉形 demonstration=演示 expansion=扩展 daughter=子卡 op=运算 amp=放大器 emulator=仿真器 debugger=调试器 programming=编程 software=软件 service=服务 solderless=免焊 breadboard=面包板 capacitance=电容 varicap=变容二极管 varactor=变容二极管 zener=稳压二极管 bipolar=双极 unijunction=单结 blower=鼓风机 blanket=加热毯 heater=加热器 sheet=片材 feed=馈通 pass=直通 bumper=缓冲垫 feet=脚垫 hanger=挂架 insulator=绝缘体 tapered=锥形 knob=旋钮 bracket=支架 reclosable=可重复闭合 shim=垫片 shoulder=轴肩 graphical=图形 process=过程 photoelectric=光电 vision=视觉 fitting=接头 piping=管道 stackable=可堆叠 tower=塔式 beacon=信号灯 synthesizer=合成器 timer=定时器 real=实 acquisition=采集 screen=屏幕 processor=处理器 microprocessor=微处理器 on=片上 demultiplexer=解复用器 synthesis=合成 active=有源 expander=扩展器 capacitive=电容式 serializer=串行器 deserializer=解串器 repeater=中继器 telecom=电信 asynchronous=异步 voice=语音 record=录音 playback=播放 multiplier=乘法器 processing=处理 flip=触发 flop=器 function=功能 multivibrator=多谐振荡器 parity=奇偶 checker=校验器 shift=移位 register=寄存器 translator=转换器 shifter=移位器 bus=总线 configuration=配置 offline=离线 switcher=开关电源 energy=能量 metering=计量 full=全 half=半 swap=热插拔 ballast=镇流器 ideal=理想 factor=因数 correction=校正 supervisor=监控器 reference=基准 low=低 drop=压降 out=输出 triac=双向晶闸管 blank=空白 preprinted=预印 lockout=锁定 padlock=挂锁 backup=后备 maintenance=维护 repair=维修 operation=作业 sealant=密封剂 cold=冷 grounding=接地 braid=编织带 strap=带 fabric=织物 pulling=牵引 leakage=漏电 janitorial=清洁 rag=抹布 sponge=海绵 wipe=擦拭布 bearing=轴承 lock=锁 pipe=管 retaining=固定 throat=喉口 conditioner=调节器 anti=防 static=静电 asbestos=石棉 net=网 bioculture=生物培养 borescope=内窥镜 centrifuge=离心机 bottle=瓶 sterilization=灭菌 wiping=擦拭 cover=盖片 slips=载片 microscope=显微镜 crucible=坩埚 membrane=滤膜 funnel=漏斗 knives=刀 scissors=剪刀 shovel=铲 spoon=勺 forceps=镊子 swab=棉签 sample=样品 sealing=密封 stirring=搅拌 testing=测试 pan=盘 weight=砝码 absorbent=吸附材料 tray=托盘 dolly=搬运车 calibrating=校准 hub=集线器 scanner=扫描器 docking=扩展坞 sided=面 file=文件 printing=打印 ruler=尺 transparent=透明 sound=声音 inspection=检查 arm=支臂 task=工作 mirror=镜 security=安防 arc=电弧 flash=闪光 electrostatic=静电 exit=出口 eye=眼部 fall=防坠 fire=消防 first=急救 aid=用品 hand=手部 rescue=救援 surveillance=监控 curtain=光幕 automatic=自动 transfer=转换 fume=烟雾 extractor=抽取器 torch=喷灯 core=磁芯 ionizing=离子 feeder=送料器 gadget=小工具 gizmo=小装置 locker=储物柜 bin=料箱 tote=周转箱 square=角尺 caliper=卡尺 level=水平仪 micrometer=千分尺 multimeter=万用表 analyzer=分析仪 pen=笔 point=点 disk=磁盘 backlight=背光 graphic=图形 addressable=可寻址 dot=点 matrix=矩阵 cluster=集群 emitter=发射器 infrared=红外 visible=可见光 white=白光 lens=透镜 pilot=指示 reflector=反射器 vacuum=真空 fluorescent=荧光 xenon=氙气 electrolytic=电解 layer=层 supercapacitor=超级电容 lithium=锂 ion=离子 mica=云母 start=启动 run=运行 niobium=铌 oxide=氧化物 silicon=硅 thin=薄 trimmer=微调 selectable=可选择 alone=独立 controlled=控制型 common=共 mode=模 bead=磁珠 monolithic=单片 fixed=固定 charging=充电 bobbin=骨架 former=骨架 rheostat=变阻器 scale=刻度 dial=盘 value=数值 chassis=机箱 desktop=桌面 wall=墙式 breakout=转接 etching=蚀刻 automotive=汽车 high=高 balun=巴伦 circulator=环行器 misc=其他 mixer=混频器 modulator=调制器 reader=读卡器 transponder=应答器 access=访问 monitoring=监测 subscriber=用户 human=人身 personal=个人 humidity=湿度 moisture=水分 differential=差动 accelerometer=加速度计 gyroscope=陀螺仪 inertial=惯性 inclinometer=倾角计 tilt=倾斜 vibration=振动 ambient=环境 distance=距离 image=图像 remote=遥控 photodiode=光电二极管 photonics=光子 photon=光子 counting=计数 phototransistor=光电晶体管 photoresistor=光敏电阻 occupancy=占用 shock=冲击 resistance=电阻 thermocouple=热电偶 stencil=钢网 template=模板 nozzle=喷嘴 seal=密封件 body=主体 contact=触点 metal=金属 dome=锅仔片 navigation=导航 joystick=摇杆 hall=霍尔 effect=效应 toggle=拨动 glue=胶水 global=全球 source=货源 oscilloscope=示波器 abrasive=磨料 conditioning=处理 hex=六角 torx=梅花 key=扳手 insertion=插入 extraction=拔出 stripper=剥线工具 saw=锯 chisel=凿 isolation=隔离 autotransformer=自耦变压器 down=降压 pulse=脉冲'''.split():
    _key, _value = _pair.split('=', 1)
    _WORDS[_key] = _value


_WORDS.update({"heat": "散热", "crimped": "压接", "din": "DIN"})
_EXACT.update({
    "arinc": "航空标准连接器（ARINC）",
    "din 41612": "DIN 41612 标准连接器",
    "jfets": "结型场效应管（JFET）",
    "diacs, sidacs": "触发二极管（DIAC、SIDAC）",
    "scrs": "可控硅（SCR）",
    "fets, mosfets": "场效应管（FET、MOSFET）",
    "igbts": "绝缘栅双极晶体管（IGBT）",
    "codecs": "编解码器",
    "thin film capacitors": "薄膜电容器",
    "electric double layer capacitors (edlc), supercapacitors": "双电层电容、超级电容（EDLC）",
})

_EXACT.update({
    'fpgas (field programmable gate array)': '现场可编程门阵列（FPGA）',
    'gates and inverters': '逻辑门与反相器',
    'gates and inverters - multi-function, configurable': '多功能/可配置逻辑门与反相器',
    'translators, level shifters': '电平转换芯片',
    'voltage regulators - linear, low drop out (ldo) regulators': '线性稳压器/LDO',
    'voltage regulators - linear regulator controllers': '线性稳压控制器',
    'voltage regulators - linear + switching': '线性/开关组合稳压器',
    'ac dc converters, offline switchers': 'AC-DC 转换器/离线式开关电源',
    'power management - specialized': '专用电源管理芯片',
    'buffers, drivers, receivers, transceivers': '缓冲器/驱动器/接收器/收发器',
    'flip flops': '触发器', 'shift registers': '移位寄存器',
    'logic - signal switches, multiplexers, decoders': '信号开关/多路复用器/译码器',
    'analog switches, multiplexers, demultiplexers': '模拟开关/多路复用器/解复用器',
    'instrumentation, op amps, buffer amps': '仪表放大器/运算放大器/缓冲放大器',
    'adcs/dacs - special purpose': '专用 ADC/DAC',
})


def category_zh(name: str) -> str:
    value = name.strip()
    if re.search(r'[\u4e00-\u9fff]', value):
        return value
    exact = CATEGORY_LABELS.get(value.lower()) or _EXACT.get(value.lower())
    if exact:
        return exact
    def word(match):
        token = match.group()
        low = token.lower()
        if low in _WORDS:
            return _WORDS[low]
        if low.endswith('ies') and low[:-3] + 'y' in _WORDS:
            return _WORDS[low[:-3] + 'y']
        if low.endswith('s') and low[:-1] in _WORDS:
            return _WORDS[low[:-1]]
        if low.endswith('es') and low[:-2] in _WORDS:
            return _WORDS[low[:-2]]
        return token  # Retain technical acronyms / previously unseen names.
    result = re.sub(r'[A-Za-z]+', word, value)
    result = re.sub(r'(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])', '', result)
    return result.replace(', ', '、').replace(' - ', ' · ')
