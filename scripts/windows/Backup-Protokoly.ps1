$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '../..')
$backupPath = Join-Path (Get-Location) ('.local/backups/' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Force $backupPath | Out-Null
& docker compose stop web worker
if ($LASTEXITCODE -ne 0) { throw 'Не удалось остановить запись данных.' }
try {
    & docker compose exec -T db pg_dump -U protocols -d protocols -Fc -f /tmp/protokoly-backup.dump
    if ($LASTEXITCODE -ne 0) { throw 'Ошибка резервного копирования БД.' }
    & docker compose cp db:/tmp/protokoly-backup.dump (Join-Path $backupPath 'database.dump')
    if ($LASTEXITCODE -ne 0) { throw 'Ошибка копирования БД.' }
    & docker compose run --rm --no-deps --user 0 --volume "${backupPath}:/backup" web tar -czf /backup/files.tar.gz -C /app/var .
    if ($LASTEXITCODE -ne 0) { throw 'Ошибка архива файлов.' }
    Copy-Item '.local/secrets' (Join-Path $backupPath 'secrets') -Recurse
    Write-Host "Резервная копия: $backupPath"
} finally { & docker compose start web worker }
