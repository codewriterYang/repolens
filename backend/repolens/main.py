"""RepoLens FastAPI 应用入口。

包含 6 个端点，无 WebSocket，无中间件复杂度。
每次 /api/analyze 调用时，编排器作为后台任务启动。
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional
from uuid import uuid4

import aiosqlite
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)

# 加载 .env（优先当前目录，其次项目根目录）
_dotenv_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(_dotenv_path)

from .config import config
from .db import close_db, create_job, get_history, get_html_report, get_job_status, get_report, init_db
from .llm_service import LLMService
from .orchestrator import Orchestrator
from .schemas import AnalyzeRequest, AnalyzeResponse, HealthResponse, HistoryItem, ReportJson, StatusResponse


# ---------------------------------------------------------------------------
# 应用状态（模块级 — 无依赖注入框架）
# ---------------------------------------------------------------------------

_db: Optional[aiosqlite.Connection] = None
_orchestrator: Optional[Orchestrator] = None


async def get_db() -> aiosqlite.Connection:
    """获取共享的数据库连接。"""
    assert _db is not None, "数据库未初始化"
    return _db


async def get_orchestrator() -> Orchestrator:
    """获取编排器实例。"""
    assert _orchestrator is not None, "编排器未初始化"
    return _orchestrator


# ---------------------------------------------------------------------------
# 生命周期
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动：初始化数据库和 LLM。关闭：断开数据库连接。"""
    global _db, _orchestrator

    _db = await init_db()
    llm = LLMService(db=_db)
    _orchestrator = Orchestrator(db=_db, llm=llm)

    yield

    await close_db(_db)


# ---------------------------------------------------------------------------
# FastAPI 应用
# ---------------------------------------------------------------------------

app = FastAPI(
    title="RepoLens",
    version="1.0.0",
    description="AI 驱动的仓库分析平台 — 代码质量、仓库意图、Git 活动、结构化洞察。",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------


@app.post("/api/analyze", response_model=AnalyzeResponse, status_code=202)
async def analyze(req: AnalyzeRequest) -> AnalyzeResponse:
    """提交仓库分析请求。

    分析在后台运行。使用 GET /api/status/{job_id} 轮询进度，
    使用 GET /api/report/{job_id} 获取结果。
    """
    job_id = uuid4().hex
    db = await get_db()

    await create_job(db, job_id, req.repo_url)

    orch = await get_orchestrator()
    asyncio.create_task(orch.run_pipeline(job_id, req.repo_url))

    return AnalyzeResponse(job_id=job_id, status="queued")


@app.get("/api/status/{job_id}", response_model=StatusResponse)
async def get_status(job_id: str) -> StatusResponse:
    """轮询当前分析任务状态。

    前端在任务运行期间每 2 秒调用一次。
    当分析器已完成但报告尚未生成时，返回 partial_results。
    """
    db = await get_db()
    row = await get_job_status(db, job_id)

    if row is None:
        raise HTTPException(status_code=404, detail="任务未找到")

    return StatusResponse(
        job_id=row["job_id"],
        status=row["status"],
        progress_pct=row["progress_pct"],
        stage_label=row["stage_label"],
        error_msg=row.get("error_msg"),
        partial_results=row.get("partial"),
    )


@app.get("/api/report/{job_id}", response_model=ReportJson)
async def get_report_endpoint(job_id: str) -> ReportJson:
    """获取已完成的分析报告（JSON 格式）。"""
    db = await get_db()
    report = await get_report(db, job_id)

    if report is None:
        raise HTTPException(status_code=404, detail="报告未找到或尚未完成")

    return report


@app.get("/api/report/{job_id}/html")
async def get_report_html(job_id: str) -> str:
    """获取已完成的分析报告（独立 HTML 格式）。"""
    from fastapi.responses import HTMLResponse

    db = await get_db()
    html = await get_html_report(db, job_id)

    if html is None:
        raise HTTPException(status_code=404, detail="报告未找到或尚未完成")

    return HTMLResponse(content=html)


@app.get("/api/history", response_model=list[HistoryItem])
async def get_history_endpoint() -> list[HistoryItem]:
    """列出最近的分析任务，最新的在前。"""
    db = await get_db()
    return await get_history(db)


@app.get("/api/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """基础健康检查。"""
    return HealthResponse()
