$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    docker compose up --build -d
    if ($LASTEXITCODE -ne 0) { throw 'Docker起動に失敗しました。Dockerが起動しているか確認してください。' }
    Write-Host 'HACS: http://localhost:8787'
} finally {
    Pop-Location
}
