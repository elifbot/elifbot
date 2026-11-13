$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$Stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$ResultsBase = Join-Path $Root 'windows_sonuclar'
$ResultDir = Join-Path $ResultsBase $Stamp
$TranscriptPath = Join-Path $ResultDir 'windows_kurulum_ve_calisma.log'
$ErrorPath = Join-Path $ResultDir 'HATA_RAPORU.txt'
$SummaryPath = Join-Path $ResultDir 'WINDOWS_TEST_OZETI.txt'
$ZipPath = "$ResultDir.zip"
$VenvDir = Join-Path $Root '.venv-windows'
$VenvPython = Join-Path $VenvDir 'Scripts\python.exe'
$Success = $false
$SleepGuardEnabled = $false
$TranscriptStarted = $false

New-Item -ItemType Directory -Force -Path $ResultDir | Out-Null

function Write-Step([string]$Text) {
    Write-Host ""
    Write-Host ('=' * 72) -ForegroundColor DarkCyan
    Write-Host $Text -ForegroundColor Cyan
    Write-Host ('=' * 72) -ForegroundColor DarkCyan
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory=$true, Position=0)][string]$FilePath,
        [Parameter(Mandatory=$true, Position=1)][string[]]$ArgumentList
    )
    & $FilePath $ArgumentList
    if ($LASTEXITCODE -ne 0) {
        throw "Komut basarisiz (exit=$LASTEXITCODE): $FilePath $($ArgumentList -join ' ')"
    }
}

function Test-PythonCandidate {
    param([string]$Exe, [string[]]$PrefixArgs)
    if (-not $Exe -or -not (Test-Path $Exe)) { return $null }
    try {
        $version = & $Exe @PrefixArgs -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $version) { return $null }
        $parts = $version.Trim().Split('.')
        if ([int]$parts[0] -gt 3 -or ([int]$parts[0] -eq 3 -and [int]$parts[1] -ge 11)) {
            return @{ Exe=$Exe; Args=$PrefixArgs; Version=$version.Trim() }
        }
    } catch {}
    return $null
}

function Find-CompatiblePython {
    $pyLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        foreach ($selector in @('-3.12','-3.11','-3')) {
            $candidate = Test-PythonCandidate $pyLauncher.Source @($selector)
            if ($candidate) { return $candidate }
        }
    }

    $roots = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Python'),
        'C:\Program Files\Python312',
        'C:\Program Files\Python311'
    )
    foreach ($base in $roots) {
        if (Test-Path $base) {
            $found = Get-ChildItem -Path $base -Filter python.exe -Recurse -ErrorAction SilentlyContinue |
                Sort-Object FullName -Descending
            foreach ($item in $found) {
                $candidate = Test-PythonCandidate $item.FullName @()
                if ($candidate) { return $candidate }
            }
        }
    }

    foreach ($name in @('python.exe','python3.exe')) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if ($command -and $command.Source -notlike '*WindowsApps*') {
            $candidate = Test-PythonCandidate $command.Source @()
            if ($candidate) { return $candidate }
        }
    }
    return $null
}

function Enable-SleepGuard {
    try {
        Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class ArenaPowerGuard {
    [DllImport("kernel32.dll", CharSet = CharSet.Auto, SetLastError = true)]
    public static extern uint SetThreadExecutionState(uint esFlags);
}
"@
        $ES_CONTINUOUS = [uint32]0x80000000
        $ES_SYSTEM_REQUIRED = [uint32]0x00000001
        $ES_DISPLAY_REQUIRED = [uint32]0x00000002
        [void][ArenaPowerGuard]::SetThreadExecutionState($ES_CONTINUOUS -bor $ES_SYSTEM_REQUIRED -bor $ES_DISPLAY_REQUIRED)
        return $true
    } catch {
        Write-Host "Uyku engelleyici etkinlestirilemedi; bilgisayari elle uyanik tutun." -ForegroundColor Yellow
        return $false
    }
}

function Disable-SleepGuard {
    if ($SleepGuardEnabled) {
        try { [void][ArenaPowerGuard]::SetThreadExecutionState([uint32]0x80000000) } catch {}
    }
}

try {
    Start-Transcript -Path $TranscriptPath -Force | Out-Null
    $TranscriptStarted = $true
    $SleepGuardEnabled = Enable-SleepGuard

    Write-Step '1/6 - Python kontrol ediliyor'
    $Python = Find-CompatiblePython
    if (-not $Python) {
        Write-Host 'Python 3.11+ bulunamadi. winget ile Python 3.12 kurulacak...' -ForegroundColor Yellow
        $Winget = Get-Command winget.exe -ErrorAction SilentlyContinue
        if (-not $Winget) {
            throw 'Python bulunamadi ve winget bu Windows kurulumunda mevcut degil.'
        }
        & $Winget.Source install --exact --id Python.Python.3.12 --source winget --scope user --accept-source-agreements --accept-package-agreements
        if ($LASTEXITCODE -ne 0) {
            throw "Python kurulumu basarisiz (winget exit=$LASTEXITCODE)."
        }
        Start-Sleep -Seconds 5
        $Python = Find-CompatiblePython
        if (-not $Python) {
            throw 'Python kuruldu ancak bu oturumda bulunamadi. Bilgisayari yeniden baslatip BASLAT_1_SAAT.bat dosyasina tekrar cift tiklayin.'
        }
    }
    Write-Host "Python bulundu: $($Python.Version)" -ForegroundColor Green

    Write-Step '2/6 - Izole Python ortami ve bagimliliklar hazirlaniyor'
    if (-not (Test-Path $VenvPython)) {
        $VenvArgs = @($Python.Args) + @('-m', 'venv', $VenvDir)
        & $Python.Exe $VenvArgs
        if ($LASTEXITCODE -ne 0) { throw 'Python sanal ortami olusturulamadi.' }
    }
    Invoke-Checked -FilePath $VenvPython -ArgumentList @('-m', 'pip', 'install', '--disable-pip-version-check', '--upgrade', 'pip')
    Invoke-Checked -FilePath $VenvPython -ArgumentList @('-m', 'pip', 'install', '--disable-pip-version-check', '-r', (Join-Path $Root 'requirements.txt'), 'pytest')

    Write-Step '3/6 - 141 otomatik test calistiriliyor'
    $env:MODE = ''
    $env:PAPER_SESSION_HOURS = '0'
    $env:REQUIRE_NOTIFICATIONS = '0'
    $env:NOTIFICATION_STARTUP_TEST = '0'
    $env:PYTHONUNBUFFERED = '1'
    Invoke-Checked -FilePath $VenvPython -ArgumentList @('-m', 'pytest', '-q', 'tests')

    Write-Step '4/6 - Bir saatlik temiz paper oturumu baslatiliyor'
    $DatabasePath = Join-Path $ResultDir 'bot_state_windows_1saat.db'
    $env:MODE = 'paper'
    $env:PAPER_SESSION_HOURS = '1'
    $env:BOT_DB_FILE = $DatabasePath
    $env:CONFIG_FILE = (Join-Path $Root 'config.windows.yaml')
    $env:REQUIRE_NOTIFICATIONS = '0'
    $env:NOTIFICATION_STARTUP_TEST = '0'
    $env:BINANCE_PUBLIC_WWW = '1'
    $env:PYTHONUNBUFFERED = '1'

    Write-Host 'Bu pencereyi kapatmayin. Her dakika kalp atisi gorunecek.' -ForegroundColor Yellow
    Invoke-Checked -FilePath $VenvPython -ArgumentList @(
        'deploy\bir_saat_gozetmen.py', '--hours', '1', '--db-file', $DatabasePath,
        '--max-restarts', '5', '--health-grace-sec', '180', '--skip-notifications'
    )

    Write-Step '5/6 - Kabul kosullari dogrulaniyor'
    $AcceptancePath = Join-Path $ResultDir 'kabul_ozeti.json'
    Invoke-Checked -FilePath $VenvPython -ArgumentList @(
        'deploy\gitlab_kabul_kontrol.py', '--db', $DatabasePath, '--output', $AcceptancePath
    )
    $Acceptance = Get-Content -Raw -Path $AcceptancePath | ConvertFrom-Json
    if (-not $Acceptance.accepted) {
        throw 'Kabul raporu accepted=false dondu.'
    }

    @"
KRIPTO-BOT WINDOWS 1 SAATLIK TEST
Durum: KABUL EDILDI
Baslangic paketi: v7.8
Mod: PAPER
Bildirimler: Kullanici talebiyle kapali
Acik pozisyon: 0
Kabul raporu: kabul_ozeti.json
Tamamlanma: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
"@ | Set-Content -Path $SummaryPath -Encoding UTF8
    $Success = $true
    Write-Host 'BIR SAATLIK TEST BASARIYLA TAMAMLANDI.' -ForegroundColor Green

} catch {
    $Message = $_.Exception.Message
    Write-Host "HATA: $Message" -ForegroundColor Red
    @"
KRIPTO-BOT WINDOWS TEST HATASI
Tarih: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
Hata: $Message

Ayrintili log: windows_kurulum_ve_calisma.log
"@ | Set-Content -Path $ErrorPath -Encoding UTF8
} finally {
    Disable-SleepGuard
    if ($TranscriptStarted) {
        try { Stop-Transcript | Out-Null } catch {}
    }

    foreach ($folderName in @('reports','run')) {
        $source = Join-Path $Root $folderName
        if (Test-Path $source) {
            Copy-Item -Path $source -Destination (Join-Path $ResultDir $folderName) -Recurse -Force -ErrorAction SilentlyContinue
        }
    }

    try {
        if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }
        Compress-Archive -Path (Join-Path $ResultDir '*') -DestinationPath $ZipPath -CompressionLevel Optimal -Force
    } catch {
        Write-Host "Sonuc ZIP olusturulamadi: $($_.Exception.Message)" -ForegroundColor Yellow
    }

    Write-Host ''
    Write-Host "Sonuc klasoru: $ResultDir" -ForegroundColor Cyan
    if (Test-Path $ZipPath) { Write-Host "Sonuc ZIP: $ZipPath" -ForegroundColor Cyan }
    try { Start-Process explorer.exe -ArgumentList "/select,`"$ZipPath`"" } catch { Start-Process explorer.exe $ResultDir }
}

if ($Success) { exit 0 } else { exit 1 }
