[CmdletBinding()]
param(
    [string]$Python = 'python',
    [string]$Compiler = '',
    [string]$BinaryDir = '',
    [switch]$UseExistingBinaries
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
Push-Location $projectRoot
try {
    if (!$BinaryDir) { $BinaryDir = Join-Path $projectRoot 'dist' }
    $BinaryDir = [IO.Path]::GetFullPath($BinaryDir)
    if (!$Compiler) {
        $isccCommand = Get-Command ISCC.exe -ErrorAction SilentlyContinue
        if ($isccCommand) { $Compiler = $isccCommand.Source }
        else { $Compiler = Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6/ISCC.exe' }
    }
    if (!(Test-Path -LiteralPath $Compiler)) { throw '未找到 Inno Setup 6，请通过 -Compiler 指定 ISCC.exe。' }
    $releaseVersion = (& $Python -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])").Trim()
    if ($LASTEXITCODE -ne 0) { throw '读取版本失败（构建需要 Python 3.11+）。' }
    if (!$UseExistingBinaries) {
        & $Python -m PyInstaller --noconfirm --distpath $BinaryDir edakit.spec
        if ($LASTEXITCODE -ne 0) { throw '程序打包失败。' }
    }
    foreach ($exeName in @('edakit.exe','edakit-cli.exe')) {
        if (!(Test-Path -LiteralPath "$BinaryDir/$exeName")) { throw "缺少 dist/$exeName" }
    }
    $binaryVersion = (& (Join-Path $BinaryDir edakit-cli.exe) --version).Trim()
    if ($LASTEXITCODE -ne 0 -or $binaryVersion -ne $releaseVersion) {
        throw "程序版本与源码版本不一致：$binaryVersion / $releaseVersion"
    }
    & (Join-Path $BinaryDir edakit-cli.exe) selftest
    if ($LASTEXITCODE -ne 0) { throw '冻结程序自检失败，停止生成安装包。' }
    & $Compiler "/DMyAppVersion=$releaseVersion" "/DReleaseDir=$BinaryDir" installer/setup.iss
    if ($LASTEXITCODE -ne 0) { throw 'Inno Setup 编译失败。' }
    $setupPath = Join-Path $PSScriptRoot "Output/EdaKit-$releaseVersion-Setup.exe"
    $manifest = [ordered]@{ version=$releaseVersion; builtAt=(Get-Date).ToString('o'); files=@{} }
    foreach ($releasePath in @($setupPath, "$BinaryDir/edakit.exe", "$BinaryDir/edakit-cli.exe")) {
        $manifest.files[(Split-Path $releasePath -Leaf)] = (Get-FileHash -LiteralPath $releasePath -Algorithm SHA256).Hash.ToLower()
    }
    $manifest | ConvertTo-Json -Depth 4 | Set-Content (Join-Path $PSScriptRoot 'Output/release-sha256.json') -Encoding utf8
    Write-Host "安装包：$setupPath"
} finally { Pop-Location }
