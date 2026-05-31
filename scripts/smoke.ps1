# RepoLens — 冒烟测试（探测 /api/health）
# 用法：.\scripts\smoke.ps1 [-Port 8770]

param(
    [int]$Port = 8770,
    [int]$TimeoutSec = 30
)

$url = "http://localhost:$Port/api/health"
$deadline = (Get-Date).AddSeconds($TimeoutSec)

Write-Host "正在探测 $url（超时: ${TimeoutSec}s）..." -ForegroundColor Cyan

while ((Get-Date) -lt $deadline) {
    try {
        $resp = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 3
        if ($resp.StatusCode -eq 200) {
            Write-Host "通过: 后端服务正常" -ForegroundColor Green
            exit 0
        }
    } catch {
        # 尚未就绪
    }
    Start-Sleep -Seconds 2
}

Write-Host "失败: 后端服务在 ${TimeoutSec}s 内未就绪" -ForegroundColor Red
exit 1
