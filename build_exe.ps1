# ============================================================
#  edakit 一键构建 exe
#  由同目录的 build_exe.bat 调用（直接双击 bat 即可）。
#
#  产出: dist\edakit.exe  (单文件)
#
#  ★ 为什么要在 %USERPROFILE%\edakit-build 里构建，而不是就在本目录？
#    本目录在 AppData 深处（Claude 的会话目录），这类路径通常被
#    杀毒软件实时扫描、同时被桌面应用的文件监视器盯着。PyInstaller 的
#    analysis 阶段要对几万个文件做 stat/open，在这种目录里会慢到看起来像卡死
#    （实测：同一份配置在普通目录 10 秒完成，在这里 10 分钟没有任何进展）。
#    所以脚本先把源码镜像到普通目录，在那儿构建，最后把 exe 拷回来。
# ============================================================

Set-Location -LiteralPath $PSScriptRoot

$ProjectRoot = $PSScriptRoot
$LogPath     = Join-Path $ProjectRoot 'build_log.txt'

# 下面这几行在 Windows 上走的是正常那支；非 Windows 那一支纯粹是为了能在
# 开发用的 Linux 沙盒里把整个脚本真跑一遍（那样才能验证控制流没写错）。
$isWinOS = ($env:OS -eq 'Windows_NT')
$exeName = 'edakit.exe'
if (-not $isWinOS) { $exeName = 'edakit' }
$FinalExe    = Join-Path $ProjectRoot (Join-Path 'dist' $exeName)

# 上一次运行的窗口可能还开着、攥着 build_log.txt —— 那时 Start-Transcript 会静默失败，
# 我们就彻底失去了排查依据。所以失败时退到带时间戳的备用日志。
$script:TranscriptOK = $false
try { Start-Transcript -Path $LogPath -Force | Out-Null; $script:TranscriptOK = $true } catch { }

if (-not $script:TranscriptOK) {
    $alt = Join-Path $ProjectRoot ('build_log_{0}.txt' -f (Get-Date -Format 'yyyyMMdd-HHmmss'))
    try {
        Start-Transcript -Path $alt -Force | Out-Null
        $LogPath = $alt
        $script:TranscriptOK = $true
    }
    catch { }
}
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch { }
# Python 把 stdout 重定向到 Transcript 时默认用系统代码页（cp936），而上面把
# Console 解码固定成 UTF-8 —— 两边不一致时自检输出的中文会变成乱码。
# 强制 Python 也按 UTF-8 输出，日志和窗口就都是可读的。
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'

$script:Failed  = $false
$script:FailWhy = ''
$script:TestsOk = $true

# 构建阶段无进展多久算卡死（秒）。Linux 上整个打包约 10 秒，所以 600 秒毫无动静
# 基本可以确定是卡住了 —— 与其无限等待，不如杀掉并给出下一步。
$NoProgressLimit = 600

function Head($m) {
    Write-Host ''
    Write-Host ('=' * 64)
    Write-Host "  $m"
    Write-Host ('=' * 64)
}

function Stop-Here($why) {
    $script:Failed  = $true
    $script:FailWhy = $why
    throw $why
}

# ---------------------------------------------------------------------------
#  探测一个 python 可执行文件是不是能用的 3.10+
#
#  ⚠ 绝不要给外部程序传带引号的参数。
#  Windows PowerShell 5.1 把参数交给原生 exe 时会吃掉双引号：
#     python -c 'print("%d" % v)'   →  python 实际收到  print(%d%v)  → SyntaxError
#  所以这里只用不带任何引号的 `--version`。
# ---------------------------------------------------------------------------
function Test-PythonExe {
    param(
        [string]   $Exe,
        [string[]] $Pre = @()
    )

    if ([string]::IsNullOrWhiteSpace($Exe)) { return $null }
    if ($Exe -like '*\WindowsApps\*') { return $null }   # Microsoft Store 占位程序
    if (-not (Test-Path -LiteralPath $Exe)) { return $null }

    $vargs = $Pre + @('--version')
    $raw   = & $Exe @vargs 2>&1
    $code  = $LASTEXITCODE
    $text  = (($raw | Out-String) -replace '\s+', ' ').Trim()

    if ($code -ne 0) {
        return @{ ok = $false; why = "退出码 $code；输出: $text" }
    }

    $mm = [regex]::Match($text, 'Python\s+(\d+)\.(\d+)')
    if (-not $mm.Success) {
        return @{ ok = $false; why = "看不懂版本号: $text" }
    }

    $maj = [int]$mm.Groups[1].Value
    $min = [int]$mm.Groups[2].Value
    if ($maj -lt 3 -or ($maj -eq 3 -and $min -lt 10)) {
        return @{ ok = $false; why = "版本太老: $text" }
    }

    return @{
        ok  = $true
        exe = $Exe
        pre = $Pre
        raw = $text
    }
}

Head 'edakit 一键构建 exe'
Write-Host "  工作目录  : $ProjectRoot"
Write-Host "  系统      : $([Environment]::OSVersion.VersionString)"
Write-Host "  PowerShell: $($PSVersionTable.PSVersion)"
Write-Host "  日志      : $LogPath"

$Work   = $ProjectRoot        # 实际构建目录（可能被换成镜像目录）
$VenvPy = $null

try {

    # ------------------------------------------------------------ 1/6 --
    Head '[1/6] 查找 Python（需要 3.10 或更高）'

    $globs = @()
    if ($env:LOCALAPPDATA) {
        $globs += (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python3*\python.exe')
    }
    if ($env:ProgramFiles) {
        $globs += (Join-Path $env:ProgramFiles 'Python3*\python.exe')
    }
    if (${env:ProgramFiles(x86)}) {
        $globs += (Join-Path ${env:ProgramFiles(x86)} 'Python3*\python.exe')
    }
    $globs += 'C:\Python3*\python.exe'
    $globs += 'D:\Python3*\python.exe'

    $cands = New-Object System.Collections.ArrayList

    foreach ($g in $globs) {
        Get-ChildItem -Path $g -ErrorAction SilentlyContinue |
            ForEach-Object {
                $dir  = Split-Path -Parent $_.FullName
                $rank = 0
                $m2 = [regex]::Match($dir, 'Python(\d+?)(\d)\b')
                if ($m2.Success) { $rank = [int]$m2.Groups[1].Value * 100 + [int]$m2.Groups[2].Value }
                [pscustomobject]@{ Exe = $_.FullName; Rank = $rank }
            } |
            Sort-Object Rank -Descending |
            ForEach-Object { [void]$cands.Add(@{ exe = $_.Exe; pre = @() }) }
    }

    $launchers = @()
    if ($env:LOCALAPPDATA) { $launchers += (Join-Path $env:LOCALAPPDATA 'Programs\Python\Launcher\py.exe') }
    if ($env:WINDIR)       { $launchers += (Join-Path $env:WINDIR 'py.exe') }
    foreach ($lp in $launchers) {
        if ($lp -and (Test-Path -LiteralPath $lp)) {
            [void]$cands.Add(@{ exe = $lp; pre = @('-3') })
            [void]$cands.Add(@{ exe = $lp; pre = @() })
        }
    }

    foreach ($n in @('python', 'python3')) {
        $c = Get-Command $n -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($c -and $c.Source) { [void]$cands.Add(@{ exe = $c.Source; pre = @() }) }
    }

    if ($cands.Count -eq 0) {
        Write-Host '  常见安装位置和 PATH 里都没有找到 python.exe。'
    }

    $py    = $null
    $tried = @{}
    foreach ($c in $cands) {
        $key = ($c.pre -join ' ') + '|' + $c.exe
        if ($tried.ContainsKey($key)) { continue }
        $tried[$key] = $true

        $shown = $c.exe
        if ($c.pre.Count -gt 0) { $shown = "$($c.exe)  $($c.pre -join ' ')" }
        Write-Host "  试      : $shown"

        $r = Test-PythonExe -Exe $c.exe -Pre $c.pre
        if ($null -eq $r) {
            Write-Host '            不可用（不存在，或是 Microsoft Store 占位程序）'
            continue
        }
        if (-not $r.ok) {
            Write-Host "            跳过 —— $($r.why)"
            continue
        }

        $py = $r
        Write-Host "  采用    : $($r.exe)    ($($r.raw))"
        break
    }

    if ($null -eq $py) {
        Write-Host ''
        Write-Host '  [错误] 没找到可用的 Python 3.10+。'
        Write-Host ''
        Write-Host '  怎么确认装没装：'
        Write-Host '    按 Win+R，输入 cmd 回车，再敲：  python --version'
        Write-Host '    能打印 Python 3.x.x 就没问题；报「不是内部或外部命令」说明没装好。'
        Write-Host ''
        Write-Host '  怎么装：'
        Write-Host '    1) 打开 https://www.python.org/downloads/windows/'
        Write-Host '    2) 下载 Windows installer (64-bit) 并运行'
        Write-Host '    3) 安装第一屏底部的 Add python.exe to PATH  一定要勾上'
        Write-Host '    4) 装完关掉本窗口，重新双击 build_exe.bat'
        Stop-Here '没找到可用的 Python'
    }

    # ------------------------------------------------------------ 2/6 --
    Head '[2/6] 准备构建目录（放到普通路径，避开 AppData 的扫描/监视）'

    $BuildRoot = $null
    if ($env:USERPROFILE) { $BuildRoot = Join-Path $env:USERPROFILE 'edakit-build' }

    if ($null -eq $BuildRoot) {
        Write-Host '  拿不到 USERPROFILE，就在本目录构建。'
    }
    elseif ([System.IO.Path]::GetFullPath($BuildRoot) -eq [System.IO.Path]::GetFullPath($ProjectRoot)) {
        Write-Host '  构建目录和工程目录是同一个，跳过镜像。'
    }
    else {
        Write-Host "  构建目录: $BuildRoot"
        try {
            New-Item -ItemType Directory -Force -Path $BuildRoot | Out-Null

            Write-Host '  · 同步源码（不含 .venv / build / dist）…'
            $robo = @(
                $ProjectRoot, $BuildRoot,
                '/E',
                '/XD', '.venv', 'build', 'dist', '__pycache__', '.pytest_cache', '.pytest_tmp',
                # 这几个日志正在被本脚本占用，robocopy 会报「文件在用」而拉高退出码
                '/XF', 'build_log.txt', 'pyinstaller_log.txt', 'pyinstaller_err.txt',
                '/NFL', '/NDL', '/NJH', '/NJS', '/NP', '/R:1', '/W:1'
            )
            & robocopy @robo | Out-Null

            # 不拿 robocopy 的退出码判生死（它 >=8 也可能只是某个无关文件没拷成），
            # 而是直接检查「构建必需的几个文件」到没到位 —— 这才是真正的需求。
            $need = @(
                'entry.py', 'edakit.spec', 'pyproject.toml',
                'src\edakit\cli.py', 'tests\data\C2040.json'
            )
            $missing = @($need | Where-Object {
                -not (Test-Path -LiteralPath (Join-Path $BuildRoot $_))
            })
            if ($missing.Count -gt 0) {
                throw "镜像里缺少必需文件: $($missing -join ', ')"
            }

            $Work = $BuildRoot
            Write-Host '    OK'
        }
        catch {
            Write-Host "    [警告] 镜像失败（$($_.Exception.Message)），改回在本目录构建。"
            Write-Host '           （构建仍然会进行，只是可能明显更慢。）'
            $Work = $ProjectRoot
        }
    }

    $venvPyRel = 'Scripts\python.exe'
    if (-not $isWinOS) { $venvPyRel = 'bin/python3' }
    $VenvPy  = Join-Path $Work (Join-Path '.venv' $venvPyRel)
    $WorkExe = Join-Path $Work (Join-Path 'dist' $exeName)
    $WorkCli = Join-Path $Work 'dist\edakit-cli.exe'
    $FinalCli = Join-Path $ProjectRoot 'dist\edakit-cli.exe'
    $PyiLog  = Join-Path $Work 'pyinstaller_log.txt'
    $PyiErr  = Join-Path $Work 'pyinstaller_err.txt'

    # ------------------------------------------------------------ 3/6 --
    Head '[3/6] 准备虚拟环境 .venv'

    if (Test-Path $VenvPy) {
        Write-Host "  已存在，直接复用：$VenvPy"
    }
    else {
        Write-Host '  第一次运行要创建，稍等十几秒…'
        $venvArgs = @($py.pre) + @('-m', 'venv', '.venv')
        Push-Location -LiteralPath $Work
        try { & $py.exe @venvArgs } finally { Pop-Location }

        if ($LASTEXITCODE -ne 0 -or -not (Test-Path $VenvPy)) {
            Write-Host ''
            Write-Host '  [提示] 创建虚拟环境失败。常见原因：'
            Write-Host '         · Python 安装时没勾 pip 组件'
            Write-Host '         · 杀毒软件拦截了 python.exe'
            Write-Host '         · Python 装在了没有写权限的位置'
            Stop-Here '创建虚拟环境失败（看上面 Python 的输出）'
        }
        Write-Host "  完成：$VenvPy"
    }

    Push-Location -LiteralPath $Work
    try {
        & $VenvPy --version
    }
    finally { Pop-Location }
    if ($LASTEXITCODE -ne 0) { Stop-Here '虚拟环境里的 python 跑不起来' }

    # ------------------------------------------------------------ 4/6 --
    Head '[4/6] 安装依赖（requests + pytest + pyinstaller）'

    Push-Location -LiteralPath $Work
    try {
        Write-Host '  · 升级 pip …'
        & $VenvPy -m pip install --upgrade pip --disable-pip-version-check
        if ($LASTEXITCODE -ne 0) { Stop-Here '升级 pip 失败。如果在用代理，请给 pip 也配上代理后重试' }

        Write-Host '  · 安装本包（含 requests）…'
        & $VenvPy -m pip install --disable-pip-version-check -e .
        if ($LASTEXITCODE -ne 0) { Stop-Here '安装本包失败。如果在用代理，请给 pip 也配上代理后重试' }

        Write-Host '  · 安装 pytest / pyinstaller …'
        & $VenvPy -m pip install --disable-pip-version-check pytest pyinstaller
        if ($LASTEXITCODE -ne 0) { Stop-Here '安装 pytest/pyinstaller 失败。如果在用代理，请给 pip 也配上代理后重试' }

        # -------------------------------------------------------- 5/6 --
        Head '[5/6] 跑测试（离线用例，不需要 Cadence、不需要联网）'
        # 不用系统 %TEMP%\pytest-of-<user>：那个目录以前被更高权限或被杀软
        # 占住之后，pytest 每个用到 tmp_path 的用例都会 WinError 5（拒绝访问）。
        # 指到构建目录下的独立 basetemp，每次重建，绕开这个坑。
        $pytestTmp = Join-Path $Work '.pytest_tmp'
        if (Test-Path -LiteralPath $pytestTmp) {
            Remove-Item -LiteralPath $pytestTmp -Recurse -Force -ErrorAction SilentlyContinue
        }
        & $VenvPy -m pytest -q tests --basetemp $pytestTmp
        $script:TestsOk = ($LASTEXITCODE -eq 0)
        if (-not $script:TestsOk) {
            Write-Host ''
            Write-Host '  [警告] 测试没全过 —— 仍然继续打包，但请把 build_log.txt 发我看看。'
        }

        # -------------------------------------------------------- 6/6 --
        Head '[6/6] 打包成单文件 exe'
        Write-Host '  （PyInstaller 的 analysis 阶段会安静好一会儿，下面是心跳，能看到进度）'

        Remove-Item -Force -ErrorAction SilentlyContinue $PyiLog, $PyiErr

        # 让子进程不缓冲 stdout —— 否则日志会一块一块地出现，看不出卡在哪
        $env:PYTHONUNBUFFERED = '1'

        $pyiArgs = @('-m', 'PyInstaller', '--clean', '--noconfirm', '--log-level', 'INFO', 'edakit.spec')
        $proc = Start-Process -FilePath $VenvPy -ArgumentList $pyiArgs `
                    -WorkingDirectory $Work -NoNewWindow -PassThru `
                    -RedirectStandardOutput $PyiLog -RedirectStandardError $PyiErr

        $t0          = Get-Date
        $lastSize    = -1
        $lastGrewAt  = Get-Date
        $warned2min  = $false
        $warned5min  = $false
        $killed      = $false

        while (-not $proc.HasExited) {
            Start-Sleep -Seconds 10
            $elapsed = [int]((Get-Date) - $t0).TotalSeconds

            # ⚠ PyInstaller 的日志走 **stderr**，stdout 基本是空的。
            #   所以两个文件都要算上，否则心跳永远显示空白，等于没做。
            $size = 0
            foreach ($f in @($PyiLog, $PyiErr)) {
                if (Test-Path -LiteralPath $f) {
                    $size = $size + (Get-Item -LiteralPath $f).Length
                }
            }
            if ($size -ne $lastSize) {
                $lastSize   = $size
                $lastGrewAt = Get-Date
            }
            $quiet = [int]((Get-Date) - $lastGrewAt).TotalSeconds

            $tail = ''
            foreach ($f in @($PyiErr, $PyiLog)) {
                if (Test-Path -LiteralPath $f) {
                    $tl = Get-Content -LiteralPath $f -Tail 1 -ErrorAction SilentlyContinue
                    if ($tl) { $tail = ("$tl").Trim(); break }
                }
            }
            if ($tail.Length -gt 80) { $tail = $tail.Substring(0, 80) }

            Write-Host ("    [{0,4}s 静默 {1,3}s] {2}" -f $elapsed, $quiet, $tail)

            if ($quiet -gt 120 -and -not $warned2min) {
                $warned2min = $true
                Write-Host '      ↑ 这一步安静是正常的（PyInstaller 在做依赖扫描），先别关。'
            }
            if ($quiet -gt 300 -and -not $warned5min) {
                $warned5min = $true
                Write-Host '      ↑ 已经安静 5 分钟了，不太正常。打开任务管理器看 python.exe 的 CPU：'
                Write-Host '        持续有占用 → 还在跑，继续等；一直 0% → 卡住了，见下面处理办法。'
            }
            if ($quiet -gt $NoProgressLimit) {
                $killed = $true
                try { $proc.Kill() } catch { }
                break
            }
        }

        if (-not $killed) { $proc.WaitForExit() }

        # 把 PyInstaller 的日志挪到工程目录，方便排查（失败时尤其重要）
        foreach ($f in @($PyiLog, $PyiErr)) {
            if (Test-Path -LiteralPath $f) {
                Copy-Item -LiteralPath $f -Destination (Join-Path $ProjectRoot (Split-Path -Leaf $f)) -Force -ErrorAction SilentlyContinue
            }
        }

        if ($killed) {
            Write-Host ''
            Write-Host "  [失败] PyInstaller 已经 $NoProgressLimit 秒没有任何输出，判定为卡死，已终止。"
            Write-Host "         完整输出: $(Join-Path $ProjectRoot 'pyinstaller_log.txt')"
            Stop-Here 'PyInstaller 卡死（已自动终止）'
        }

        $pyiCode = $proc.ExitCode
        if ($null -eq $pyiCode) { $pyiCode = 0 }
        if ($pyiCode -ne 0) {
            Write-Host ''
            Write-Host '  PyInstaller 最后 20 行（标准输出）：'
            Get-Content -LiteralPath $PyiLog -Tail 20 -ErrorAction SilentlyContinue |
                ForEach-Object { Write-Host "    $_" }
            # 真正的报错常常在 stderr —— 不打印出来等于没说
            if (Test-Path -LiteralPath $PyiErr) {
                $errTail = Get-Content -LiteralPath $PyiErr -Tail 20 -ErrorAction SilentlyContinue
                if ($errTail) {
                    Write-Host '  PyInstaller 最后 20 行（标准错误）：'
                    $errTail | ForEach-Object { Write-Host "    $_" }
                }
            }
            Stop-Here "PyInstaller 打包失败（退出码 $pyiCode，见上面的报错）"
        }

        if (-not (Test-Path -LiteralPath $WorkExe)) {
            Stop-Here "打包跑完了，但没找到 $WorkExe"
        }

        $exeSize = (Get-Item -LiteralPath $WorkExe).Length
        if ($exeSize -lt 3MB) {
            Stop-Here "exe 只有 $exeSize 字节，太小了，八成是打包不完整"
        }

        # ------------------------------------------------------- 自检 --
        # 光有文件不算成功 —— 得真的跑得起来。
        # （曾经把 src/edakit/__main__.py 当打包入口，exe 一跑就是
        #   ImportError: attempted relative import，而「打包成功」照打不误。）
        # 自检逻辑在 exe 自己里面（edakit selftest），这里只调一行。
        Head '[自检] 跑刚打出来的 exe（edakit selftest）'

        # 重定向到文件再按 UTF-8 读回来。
        # 直接让 exe 往控制台写，中文会被控制台代码页弄成「解解释释器器」这种叠字
        # （PowerShell 5.1 + UTF-8 输出的老问题），日志里就没法看了。
        $stOut = Join-Path $Work 'selftest_out.txt'
        $stErr = Join-Path $Work 'selftest_err.txt'
        Remove-Item -Force -ErrorAction SilentlyContinue $stOut, $stErr

        $stProc = Start-Process -FilePath $WorkCli -ArgumentList @('selftest') `
                    -WorkingDirectory $Work -NoNewWindow -Wait -PassThru `
                    -RedirectStandardOutput $stOut -RedirectStandardError $stErr
        if ($stProc.ExitCode -ne 0) {
            if (Test-Path -LiteralPath $stErr) {
                Get-Content -LiteralPath $stErr -Encoding UTF8 -ErrorAction SilentlyContinue |
                    ForEach-Object { Write-Host "    $_" }
            }
            Stop-Here 'exe 自检没通过 —— 见上面标着 [失败] 的项'
        }
        if (Test-Path -LiteralPath $stOut) {
            Get-Content -LiteralPath $stOut -Encoding UTF8 | ForEach-Object { Write-Host $_ }
        }
        # 留一份在工程目录，出问题时可以直接看
        if (Test-Path -LiteralPath $stOut) {
            Copy-Item -LiteralPath $stOut -Destination (Join-Path $ProjectRoot 'selftest_out.txt') -Force -ErrorAction SilentlyContinue
        }

        # exe 拷回工程目录，用户还是在老地方拿
        if ($Work -ne $ProjectRoot) {
            $destDir = Split-Path -Parent $FinalExe
            New-Item -ItemType Directory -Force -Path $destDir | Out-Null
            Copy-Item -LiteralPath $WorkExe -Destination $FinalExe -Force
            Copy-Item -LiteralPath $WorkCli -Destination $FinalCli -Force
            Write-Host "  已拷回: $FinalExe"

            # 拷回来的那一份也再自检一遍 —— 万一复制被打断（杀软扫描大文件时会发生），
            # 用户拿到的就会是个坏 exe，而这里能当场发现。
            Write-Host '  · 对拷回工程目录的那一份再自检一遍 …'
            $chk = Start-Process -FilePath $FinalCli -ArgumentList @('selftest') `
                     -NoNewWindow -Wait -PassThru `
                     -RedirectStandardOutput (Join-Path $Work 'selftest_copy.txt') `
                     -RedirectStandardError (Join-Path $Work 'selftest_copy_err.txt')
            if ($chk.ExitCode -ne 0) {
                Stop-Here "拷回后的 exe 自检失败（$FinalExe）—— 多半是复制不完整，重跑一次构建"
            }
            Write-Host '    OK'
        }
    }
    finally { Pop-Location }

}
catch {
    if (-not $script:Failed) {
        $script:Failed  = $true
        $script:FailWhy = $_.Exception.Message
    }
}

# ---------------------------------------------------------------- 结论 --
Write-Host ''
if ($script:Failed) {
    Head '构建失败'
    Write-Host "  原因    : $script:FailWhy"
    Write-Host "  完整日志: $LogPath"
    if (Test-Path -LiteralPath (Join-Path $ProjectRoot 'pyinstaller_log.txt')) {
        Write-Host "  PyInstaller 日志: $(Join-Path $ProjectRoot 'pyinstaller_log.txt')"
    }
    Write-Host ''
    Write-Host '  把 build_log.txt 发给我（或者贴出最后 30 行），我来定位。'
}
else {
    $size = (Get-Item $FinalExe).Length
    Head '构建成功'
    Write-Host "  exe     : $FinalExe"
    Write-Host ("  大小    : {0:N0} 字节  ({1:N1} MB)" -f $size, ($size / 1MB))
    if (-not $script:TestsOk) { Write-Host '  注意    : 有测试没通过，见日志。' }
    Write-Host ''
    Write-Host "  exe 在 dist 子目录里，不在工程根目录 —— 复制下面这行直接跑："
    Write-Host ''
    Write-Host ("    & `"{0}`" selftest" -f $FinalExe)
    Write-Host ''
    Write-Host '  下一步：部署后从 Capture 的 EdaKit 菜单打开内嵌商城。'
    Write-Host ("    & `"{0}`" deploy --no-allegro" -f $FinalExe)
}

try { Stop-Transcript | Out-Null } catch { }

try { Stop-Transcript | Out-Null } catch { }

if ($script:Failed) { exit 2 }
exit 0
