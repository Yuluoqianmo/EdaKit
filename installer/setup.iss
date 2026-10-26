; Build with installer/build.ps1. All inputs come from the staged release.
#ifndef ReleaseDir
  #define ReleaseDir "..\dist"
#endif
#ifndef MyAppVersion
  #define MyAppVersion "0.1.2"
#endif
[Setup]
AppId={{8B3F2C1A-4E7D-4A9B-9C22-LCSC2CADENCE01}
AppName=EdaKit
AppVersion={#MyAppVersion}
DefaultDirName={autopf}\EdaKit
DefaultGroupName=EdaKit
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename=EdaKit-{#MyAppVersion}-Setup
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=commandline
WizardStyle=modern
CloseApplications=no
RestartApplications=no
SetupLogging=yes
UninstallDisplayIcon={app}\edakit.exe
[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "chinesesimplified"; MessagesFile: "ChineseSimplified.isl"
[Files]
Source: "{#ReleaseDir}\edakit.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#ReleaseDir}\edakit-cli.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\NOTICE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\licenses\*"; DestDir: "{app}\licenses"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\src\edakit\ibom\vendor\*.LICENSE"; DestDir: "{app}\licenses"; Flags: ignoreversion
Source: "..\src\edakit\ibom\UPSTREAM.md"; DestDir: "{app}\licenses"; Flags: ignoreversion
Source: "README.txt"; DestDir: "{app}"; Flags: ignoreversion
[Icons]
Name: "{group}\使用说明"; Filename: "{app}\README.txt"
Name: "{group}\卸载 EdaKit"; Filename: "{uninstallexe}"
[Code]
var
  CadencePage: TInputDirWizardPage;
  DeployPlugins: Boolean;
  LastInstallDir: String;
function HasCapture(Root: String): Boolean;
begin
  Result := DirExists(AddBackslash(Root) + 'tools\capture\tclscripts');
end;
function FindCadence: String;
var
  Drives, Versions: TArrayOfString;
  I, J: Integer;
  Candidate: String;
begin
  Result := GetEnv('CDSROOT');
  if HasCapture(Result) then exit;
  Drives := ['C:', 'D:', 'E:', 'F:'];
  Versions := ['17.2', '17.4', '22.1', '23.1', '24.1', '25.1'];
  for I := 0 to GetArrayLength(Drives) - 1 do
    for J := 0 to GetArrayLength(Versions) - 1 do begin
      Candidate := Drives[I] + '\Cadence\SPB_' + Versions[J];
      if HasCapture(Candidate) then begin Result := Candidate; exit; end;
    end;
  Result := '';
end;
procedure InitializeWizard;
begin
  DeployPlugins := ExpandConstant('{param:DEPLOY|1}') <> '0';
  CadencePage := CreateInputDirPage(wpSelectDir, 'Cadence 安装位置',
    '选择需要安装 EdaKit 插件的 Cadence 版本',
    '请选择 SPB 安装根目录（例如 D:\Cadence\SPB_17.2）。安装前请保存工程并退出 Capture 和 Allegro。', False, '');
  CadencePage.Add('Cadence 根目录：');
  CadencePage.Values[0] := ExpandConstant('{param:CADENCEROOT|}') ;
  if CadencePage.Values[0] = '' then
    CadencePage.Values[0] := FindCadence;
end;
procedure CurPageChanged(CurPageID: Integer);
begin
  { The application directory is not initialized in InitializeWizard. Read
    upgrade metadata only after the user reaches the Cadence page. }
  if (CurPageID = CadencePage.ID) and (LastInstallDir <> WizardDirValue) then begin
    LastInstallDir := WizardDirValue;
    if ExpandConstant('{param:CADENCEROOT|}') = '' then
      CadencePage.Values[0] := GetIniString('Cadence', 'Root', FindCadence,
        AddBackslash(WizardDirValue) + 'deployment.ini');
  end;
end;
function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := (PageID = CadencePage.ID) and not DeployPlugins;
end;
function PrepareToInstall(var NeedsRestart: Boolean): String;
var I: Integer; OldRoot: String;
begin
  Result := '';
  OldRoot := GetIniString('Cadence', 'Root', '', ExpandConstant('{app}\deployment.ini'));
  if DeployPlugins and (OldRoot <> '') and
     (CompareText(RemoveBackslashUnlessRoot(OldRoot), RemoveBackslashUnlessRoot(CadencePage.Values[0])) <> 0) then begin
    Result := '本目录已部署到其他 Cadence 版本。请先卸载旧版本，再选择新的 Cadence 目录。'; exit;
  end;
  { Native SKILL launcher requires ASCII paths. }
  for I := 1 to Length(WizardDirValue) do
    if Ord(WizardDirValue[I]) > 127 then begin
      Result := 'EdaKit 安装目录必须使用英文路径，例如 C:\Program Files\EdaKit。'; exit;
    end;
  if DeployPlugins and not HasCapture(CadencePage.Values[0]) then begin
    Result := '所选 Cadence 目录中未找到 tools\capture\tclscripts，请检查安装位置。'; exit;
  end;
  if DeployPlugins and not FileExists(AddBackslash(CadencePage.Values[0]) + 'tools\bin\ipc2581_out.exe') then
    Result := '所选 Cadence 目录缺少 Allegro IPC-2581 导出工具，无法安装完整插件。';
end;
procedure CurStepChanged(CurStep: TSetupStep);
var Code: Integer; Args, State, LogPath: String;
begin
  if (CurStep = ssPostInstall) and DeployPlugins then begin
    State := ExpandConstant('{app}\deployment.ini');
    SetIniString('Cadence', 'Root', CadencePage.Values[0], State);
    LogPath := ExpandConstant('{app}\deployment.log');
    Args := 'deploy --strict --cadence-root "' + CadencePage.Values[0] +
      '" --deployment-log "' + LogPath + '"';
    if not Exec(ExpandConstant('{app}\edakit-cli.exe'), Args, '', SW_HIDE, ewWaitUntilTerminated, Code) then
      RaiseException('无法启动插件部署程序。请查看安装日志。');
    if Code <> 0 then
      RaiseException('插件部署未完成。程序已复制，请查看 ' + LogPath + '，修正路径或权限后重新运行安装包。');
    SetIniString('Cadence', 'Complete', '1', State);
  end;
end;
function InitializeUninstall: Boolean;
begin
  Result := True;
  if not UninstallSilent then
    Result := MsgBox('请先保存工程并退出 Capture 和 Allegro。卸载保留用户配置、器件库和已导出的文件。继续卸载？', mbConfirmation, MB_YESNO) = IDYES;
end;
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var Root: String; Code: Integer;
begin
  if CurUninstallStep = usUninstall then begin
    Root := GetIniString('Cadence', 'Root', '', ExpandConstant('{app}\deployment.ini'));
    if Root <> '' then begin
      if not Exec(ExpandConstant('{app}\edakit-cli.exe'), 'undeploy --remove-allegro --cadence-root "' + Root + '"', '', SW_HIDE, ewWaitUntilTerminated, Code) then
        RaiseException('无法运行插件卸载程序，未删除程序文件。');
      if Code <> 0 then RaiseException('插件入口清理失败，未删除程序文件。请检查目录权限后重试。');
    end;
  end;
end;
[UninstallDelete]
Type: files; Name: "{app}\deployment.ini"
Type: files; Name: "{app}\deployment.log"
