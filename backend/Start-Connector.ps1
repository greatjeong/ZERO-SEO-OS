$ErrorActionPreference = 'Stop'
$previous = @{}
try {
    Write-Host 'ZERO SEO OS - local WordPress connector'
    Write-Host 'Checking Python before asking for credentials...'
    $pythonCommand = $null
    $pythonArgs = @()
    foreach ($candidate in @('python', 'py')) {
        if (-not (Get-Command $candidate -ErrorAction SilentlyContinue)) { continue }
        $candidateArgs = @()
        if ($candidate -eq 'py') { $candidateArgs = @('-3') }
        try {
            $null = & $candidate @candidateArgs -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>$null
            if ($LASTEXITCODE -eq 0) {
                $pythonCommand = $candidate
                $pythonArgs = $candidateArgs
                break
            }
        } catch { # Try the other official Python launcher. Do not print environment values.
        }
    }
    if (-not $pythonCommand) { throw 'PYTHON_NOT_FOUND' }
    $serverFile = Join-Path $PSScriptRoot 'server.py'
    if (-not (Test-Path -LiteralPath $serverFile -PathType Leaf)) { throw 'SERVER_FILE_MISSING' }
    # Check UTF-8 and syntax without executing the connector or printing source text.
    & $pythonCommand @pythonArgs -c "import ast,pathlib,sys; p=pathlib.Path(sys.argv[1]); ast.parse(p.read_text(encoding='utf-8-sig')); print('Python and server syntax: OK')" $serverFile
    if ($LASTEXITCODE -ne 0) { throw 'SERVER_CHECK_FAILED' }
    Write-Host 'Use a WordPress Application Password, not your main login password.'
    Write-Host 'Credentials are kept only in this process, not in a file.'
    foreach ($siteId in @('A1', 'A2')) {
        $siteUrl = Read-Host "$siteId HTTPS URL (blank = skip)"
        if ([string]::IsNullOrWhiteSpace($siteUrl)) { continue }
        $siteUser = Read-Host "$siteId WordPress username"
        $securePassword = Read-Host "$siteId Application Password" -AsSecureString
        $pointer = [IntPtr]::Zero
        try {
            foreach ($suffix in @('URL', 'USER', 'APP_PASSWORD')) {
                $key = "ZERO_WP_${siteId}_$suffix"
                $previous[$key] = [Environment]::GetEnvironmentVariable($key, 'Process')
            }
            $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
            [Environment]::SetEnvironmentVariable("ZERO_WP_${siteId}_URL", $siteUrl.Trim(), 'Process')
            [Environment]::SetEnvironmentVariable("ZERO_WP_${siteId}_USER", $siteUser.Trim(), 'Process')
            [Environment]::SetEnvironmentVariable("ZERO_WP_${siteId}_APP_PASSWORD", [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer), 'Process')
        } finally {
            if ($pointer -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
            $securePassword.Dispose()
        }
    }
    Write-Host 'Starting connector on 127.0.0.1:8765. Keep this window open.'
    & $pythonCommand @pythonArgs -u $serverFile
    if ($LASTEXITCODE -ne 0) { throw 'SERVER_EXITED_WITH_ERROR' }
} catch {
    # Never dump exception objects, environment variables, or entered credentials.
    $code = [string]$_.Exception.Message
    switch ($code) {
        'PYTHON_NOT_FOUND' { Write-Host 'ERROR: Python 3.11+ was not found. Check the Python installation.' -ForegroundColor Red }
        'SERVER_FILE_MISSING' { Write-Host 'ERROR: Put this launcher in the existing backend folder beside server.py.' -ForegroundColor Red }
        'SERVER_CHECK_FAILED' { Write-Host 'ERROR: Python could not read or compile server.py. See the error above.' -ForegroundColor Red }
        'SERVER_EXITED_WITH_ERROR' { Write-Host 'ERROR: Connector stopped. See the Python error above (for example, port 8765 already in use).' -ForegroundColor Red }
        default { Write-Host 'ERROR: Launcher failed. No credentials were written to disk. Check Python and the backend folder.' -ForegroundColor Red }
    }
} finally {
    foreach ($key in $previous.Keys) { [Environment]::SetEnvironmentVariable($key, $previous[$key], 'Process') }
    Write-Host ''
    Write-Host 'Connector is stopped. Share only the error, never credentials.'
    $null = Read-Host 'Press Enter to close this window'
}
