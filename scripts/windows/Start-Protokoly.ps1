$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '../..')
& docker info *> $null
if ($LASTEXITCODE -ne 0) { throw 'Запустите Docker Desktop в режиме Linux containers.' }
$secretDirectory = Join-Path (Get-Location) '.local/secrets'
New-Item -ItemType Directory -Force $secretDirectory | Out-Null
$random = [Security.Cryptography.RandomNumberGenerator]::Create()
try {
    foreach ($name in @('database_password', 'encryption_key', 'local_password')) {
        $path = Join-Path $secretDirectory $name
        if (-not (Test-Path $path)) {
            $bytes = New-Object byte[] 32
            $random.GetBytes($bytes)
            $secret = [Convert]::ToBase64String($bytes).Replace('+','-').Replace('/','_')
            [IO.File]::WriteAllText($path, $secret, [Text.Encoding]::ASCII)
        }
    }
} finally { $random.Dispose() }
& docker compose up -d --build --wait --wait-timeout 180
if ($LASTEXITCODE -ne 0) { throw 'Запуск не завершён. Проверьте: docker compose logs --tail=100' }
Write-Host 'Откройте http://localhost:8000/settings/integrations. Логин: local'
Write-Host 'Пароль находится в файле .local/secrets/local_password. Храните копию всей папки .local/secrets вместе с резервной копией данных.'
