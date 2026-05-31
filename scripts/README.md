# RepoLens 开发辅助脚本

## dev.ps1（Windows）

启动后端开发服务器：

```powershell
.\scripts\dev.ps1           # 默认端口 8770
.\scripts\dev.ps1 -Port 9000
```

## smoke.ps1（Windows）

探测后端服务是否就绪：

```powershell
.\scripts\smoke.ps1                 # 默认端口 8770，超时 30s
.\scripts\smoke.ps1 -Port 9000 -TimeoutSec 60
```

## macOS / Linux

直接使用原生命令：

```bash
# 启动后端
cd backend && python -m uvicorn repolens.main:app --host 0.0.0.0 --port 8770 --reload

# 冒烟测试
curl -s http://localhost:8770/api/health
```
