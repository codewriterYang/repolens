"""RepoLens SQLite 持久化层。

设计：单数据库、三张表、aiosqlite 异步访问。
无 ORM — 使用原生 SQL + Pydantic 序列化。
"""

from __future__ import annotations

import json
import os
from typing import Optional

import aiosqlite

from .config import config
from .schemas import HistoryItem, JobStatus, ReportJson


# ---------------------------------------------------------------------------
# DDL — 建表语句
# ---------------------------------------------------------------------------

DDL = """
CREATE TABLE IF NOT EXISTS analyses (
    job_id        TEXT PRIMARY KEY,
    repo_url      TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'queued',
    progress_pct  INTEGER NOT NULL DEFAULT 0,
    stage_label   TEXT NOT NULL DEFAULT '',
    report_json   TEXT,
    html_report   TEXT,
    health_score  INTEGER,
    error_msg     TEXT,
    duration_ms   INTEGER,
    partial_json  TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS llm_cache (
    cache_key  TEXT PRIMARY KEY,
    response   TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


# ---------------------------------------------------------------------------
# 生命周期
# ---------------------------------------------------------------------------


async def init_db(db_path: Optional[str] = None) -> aiosqlite.Connection:
    """初始化数据库并返回连接。

    如果 data 目录和表不存在则自动创建。
    在应用启动时调用一次。
    """
    path = db_path or config.db_path
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    db = await aiosqlite.connect(path)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    await db.executescript(DDL)
    await db.commit()
    return db


async def close_db(db: aiosqlite.Connection) -> None:
    """优雅关闭数据库连接。"""
    await db.close()


# ---------------------------------------------------------------------------
# 分析任务 CRUD
# ---------------------------------------------------------------------------


async def create_job(db: aiosqlite.Connection, job_id: str, repo_url: str) -> None:
    """插入新的分析任务。"""
    await db.execute(
        "INSERT INTO analyses (job_id, repo_url) VALUES (?, ?)",
        (job_id, repo_url),
    )
    await db.commit()


async def update_job_status(
    db: aiosqlite.Connection,
    job_id: str,
    status: JobStatus,
    progress_pct: int = 0,
    stage_label: str = "",
    error_msg: Optional[str] = None,
) -> None:
    """在流水线执行过程中更新任务进度。"""
    await db.execute(
        """UPDATE analyses
           SET status = ?, progress_pct = ?, stage_label = ?,
               error_msg = ?, updated_at = datetime('now')
           WHERE job_id = ?""",
        (status.value, progress_pct, stage_label, error_msg, job_id),
    )
    await db.commit()


async def save_report(
    db: aiosqlite.Connection, job_id: str, report: ReportJson
) -> None:
    """持久化已完成的分析报告。"""
    await db.execute(
        """UPDATE analyses
           SET status = 'completed',
               report_json = ?,
               html_report = ?,
               health_score = ?,
               duration_ms = ?,
               progress_pct = 100,
               stage_label = '分析完成',
               updated_at = datetime('now')
           WHERE job_id = ?""",
        (
            report.model_dump_json(),
            report.html_report,
            report.health_score,
            report.total_duration_ms,
            job_id,
        ),
    )
    await db.commit()


async def save_partial_results(
    db: aiosqlite.Connection,
    job_id: str,
    static_result: Optional[dict] = None,
    repo_result: Optional[dict] = None,
    git_result: Optional[dict] = None,
) -> None:
    """保存分析器中间结果。

    与已有部分结果合并 — 后续调用更新而非覆盖之前保存的字段。
    """
    # 加载已有的部分结果
    cursor = await db.execute(
        "SELECT partial_json FROM analyses WHERE job_id = ?", (job_id,),
    )
    row = await cursor.fetchone()
    existing: dict = {}
    if row and row["partial_json"]:
        try:
            existing = json.loads(row["partial_json"])
        except json.JSONDecodeError:
            pass

    # 合并
    if static_result is not None:
        existing["static_analysis"] = static_result
    if repo_result is not None:
        existing["repo_analysis"] = repo_result
    if git_result is not None:
        existing["git_analysis"] = git_result

    await db.execute(
        "UPDATE analyses SET partial_json = ?, updated_at = datetime('now') WHERE job_id = ?",
        (json.dumps(existing, ensure_ascii=False), job_id),
    )
    await db.commit()


async def get_job_status(
    db: aiosqlite.Connection, job_id: str
) -> Optional[dict]:
    """获取当前任务状态供轮询，包含部分结果。"""
    cursor = await db.execute(
        """SELECT job_id, status, progress_pct, stage_label, error_msg, partial_json
           FROM analyses WHERE job_id = ?""",
        (job_id,),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    result = dict(row)

    # 如果存在 partial_json 则解析
    if result.get("partial_json"):
        try:
            result["partial"] = json.loads(result["partial_json"])
        except json.JSONDecodeError:
            result["partial"] = None
    else:
        result["partial"] = None

    return result


async def get_report(db: aiosqlite.Connection, job_id: str) -> Optional[ReportJson]:
    """按任务 ID 获取已完成的报告。"""
    cursor = await db.execute(
        "SELECT report_json FROM analyses WHERE job_id = ? AND status = 'completed'",
        (job_id,),
    )
    row = await cursor.fetchone()
    if row is None or row["report_json"] is None:
        return None
    return ReportJson.model_validate(json.loads(row["report_json"]))


async def get_html_report(db: aiosqlite.Connection, job_id: str) -> Optional[str]:
    """按任务 ID 获取 HTML 报告字符串。"""
    cursor = await db.execute(
        "SELECT html_report FROM analyses WHERE job_id = ? AND status = 'completed'",
        (job_id,),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    return row["html_report"]


async def get_history(db: aiosqlite.Connection) -> list[HistoryItem]:
    """获取所有分析历史记录，最新的在前。"""
    cursor = await db.execute(
        """SELECT job_id, repo_url, status, health_score, created_at, duration_ms
           FROM analyses ORDER BY created_at DESC LIMIT 50"""
    )
    rows = await cursor.fetchall()
    return [
        HistoryItem(
            job_id=row["job_id"],
            repo_url=row["repo_url"],
            status=JobStatus(row["status"]),
            health_score=row["health_score"],
            created_at=row["created_at"],
            duration_ms=row["duration_ms"],
        )
        for row in rows
    ]


# ---------------------------------------------------------------------------
# LLM 缓存
# ---------------------------------------------------------------------------


async def get_llm_cache(db: aiosqlite.Connection, cache_key: str) -> Optional[str]:
    """查询 LLM 响应缓存。"""
    cursor = await db.execute(
        "SELECT response FROM llm_cache WHERE cache_key = ?", (cache_key,)
    )
    row = await cursor.fetchone()
    return row["response"] if row else None


async def set_llm_cache(
    db: aiosqlite.Connection, cache_key: str, response: str
) -> None:
    """将 LLM 响应存入缓存。"""
    await db.execute(
        "INSERT OR REPLACE INTO llm_cache (cache_key, response) VALUES (?, ?)",
        (cache_key, response),
    )
    await db.commit()
