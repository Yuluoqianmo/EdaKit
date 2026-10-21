; ============================================================
;  edakit Inno Setup 安装脚本
;  用 Inno Setup 6+ 编译: iscc installer\setup.iss
;  产出 installer\Output\edakit-setup.exe
;  会自动把 Capture TCL 插件装进 capAutoLoad 并配好 Allegro env；卸载可回滚。
; ============================================================

#define MyAppName "EdaKit / EDA 工具箱"
#define MyAppVersion "0.1.0"
#define MyAppExeName "edakit.exe"

[Setup]
AppId={{8B3F2C1A-4E7D-4A9B-9C22-LCSC2CADENCE01}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={autopf}\edakit
DefaultGroupName=edakit
DisableProgramGroupPage=yes
OutputBaseFilename=edakit-setup
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
WizardStyle=modern

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Files]
; 单文件 exe (内含商城网页资源与 TCL 模板)
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Run]
; 安装完自动部署插件到 Cadence (需要用户机器上装了 SPB)。
; 同时把封装库目录写进 %HOME%\pcbenv\env 的 padpath/psmpath/steppath/step_mapping_path。
Filename: "{app}\{#MyAppExeName}"; Parameters: "deploy"; \
  StatusMsg: "正在部署 Capture 插件并配置 Allegro 环境..."; \
  Flags: runhidden waituntilterminated

[UninstallRun]
; 卸载时移除插件目录，并回滚写进 pcbenv\env 的配置块 (只删自己的块)
Filename: "{app}\{#MyAppExeName}"; Parameters: "undeploy --remove-allegro"; \
  Flags: runhidden waituntilterminated

[Icons]
; 装完有个入口能直接开商城界面 (平时也可从 Capture 菜单「EDA 工具箱」打开)
Name: "{group}\卸载 edakit"; Filename: "{uninstallexe}"

[Registry]
; 记录 exe 路径，供 Capture 的 TCL 插件用环境变量找到 (菜单「打开EDA 工具箱」靠它)
Root: HKCU; Subkey: "Environment"; ValueType: string; \
  ValueName: "EDAKIT_EXE"; ValueData: "{app}\{#MyAppExeName}"; Flags: uninsdeletevalue
