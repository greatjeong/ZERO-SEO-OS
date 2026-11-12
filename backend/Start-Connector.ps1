$ErrorActionPreference = 'Stop'
$previous = @{}
try {
    Write-Host 'ZERO SEO OS - local WordPress connector'
    Write-Host 'Use a WordPress Application Password, not your main login password.'
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
            [Environment]::SetEnvironmentVariable("ZERO_WP_${siteId}_URL", $siteUrl, 'Process')
            [Environment]::SetEnvironmentVariable("ZERO_WP_${siteId}_USER", $siteUser, 'Process')
            [Environment]::SetEnvironmentVariable("ZERO_WP_${siteId}_APP_PASSWORD", [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer), 'Process')
        } finally {
            if ($pointer -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
            $securePassword.Dispose()
        }
    }
    if (Get-Command python -ErrorAction SilentlyContinue) { & python "$PSScriptRoot\server.py" }
    else { & py -3 "$PSScriptRoot\server.py" }
} finally {
    foreach ($key in $previous.Keys) { [Environment]::SetEnvironmentVariable($key, $previous[$key], 'Process') }
}
