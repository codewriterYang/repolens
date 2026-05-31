# RepoLens — 启动后端开发服务器
# 用法：.\scripts\dev.ps1

param(
    [int]$Port = 8770
)

$root = Split-Path -Parent $PSScriptRoot

Write-Host "=== RepoLens 开发服务器 ===" -ForegroundColor Cyan
Write-Host "后端启动中: http://localhost:$Port" -ForegroundColor Green
Write-Host ""

Set-Location "$root\backend"
$env:PYTHONPATH = (Get-Location).Path

python -m uvicorn repolens.main:app --host 0.0.0.0 --port $Port --reload
