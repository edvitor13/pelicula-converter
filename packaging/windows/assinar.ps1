<#
.SYNOPSIS
    Assina arquivos do Windows (.exe, .msi) com o signtool, SE houver certificado.

.DESCRIPTION
    Lê o certificado .pfx (em base64) e a senha das variáveis de ambiente
    WINDOWS_CERT_PFX_BASE64 e WINDOWS_CERT_PASSWORD (segredos do repositório no GitHub).
    Sem elas, avisa e sai sem erro: o build continua com arquivos não assinados.
    Carimbo de tempo RFC 3161 em http://timestamp.digicert.com (a assinatura continua válida
    depois que o certificado vencer). Veja docs/ASSINATURA.md.

.EXAMPLE
    pwsh -NoProfile -File packaging\windows\assinar.ps1 dist\PeliculaConverter\PeliculaConverter.exe
#>
param(
    [Parameter(Mandatory = $true, ValueFromRemainingArguments = $true)][string[]]$Files
)

$ErrorActionPreference = "Stop"
$pfxB64 = $env:WINDOWS_CERT_PFX_BASE64
$senha = $env:WINDOWS_CERT_PASSWORD
if ([string]::IsNullOrWhiteSpace($pfxB64) -or [string]::IsNullOrEmpty($senha)) {
    Write-Host "Sem certificado (WINDOWS_CERT_PFX_BASE64 / WINDOWS_CERT_PASSWORD): nada foi assinado."
    exit 0
}

# signtool: no PATH ou no Windows SDK mais novo instalado.
$signtool = (Get-Command signtool.exe -ErrorAction SilentlyContinue).Source
if (-not $signtool) {
    $kits = Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10\bin"
    $signtool = Get-ChildItem -Path $kits -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match '^\d+(\.\d+){3}$' } |
        Sort-Object { [version]$_.Name } -Descending |
        ForEach-Object { Join-Path $_.FullName "x64\signtool.exe" } |
        Where-Object { Test-Path $_ } |
        Select-Object -First 1
}
if (-not $signtool) { throw "signtool.exe não encontrado (instale o Windows SDK)." }

$tmp = if ($env:RUNNER_TEMP) { $env:RUNNER_TEMP } else { [System.IO.Path]::GetTempPath() }
$pfx = Join-Path $tmp ("cert-" + [guid]::NewGuid().ToString("N") + ".pfx")
[System.IO.File]::WriteAllBytes($pfx, [Convert]::FromBase64String($pfxB64.Trim()))
try {
    foreach ($f in $Files) {
        if (-not (Test-Path $f)) { throw "Arquivo para assinar não existe: $f" }
        $ok = $false
        for ($i = 1; $i -le 3 -and -not $ok; $i++) {
            # O servidor de carimbo de tempo às vezes falha; tenta de novo.
            & $signtool sign /fd SHA256 /tr "http://timestamp.digicert.com" /td SHA256 `
                /d "PeliculaConverter" /du "https://github.com/edvitor13/pelicula-converter" `
                /f $pfx /p $senha $f
            if ($LASTEXITCODE -eq 0) { $ok = $true } else { Start-Sleep -Seconds (5 * $i) }
        }
        if (-not $ok) { throw "O signtool não conseguiu assinar $f." }
        & $signtool verify /pa $f
        if ($LASTEXITCODE -ne 0) { throw "A assinatura de $f não conferiu." }
        Write-Host "Assinado: $f"
    }
} finally {
    Remove-Item -Force -ErrorAction SilentlyContinue $pfx
}
