"""RepoLens Pydantic 数据模型。

所有请求/响应模型和内部数据传输对象定义在此。
这是 API 契约的唯一真实来源。
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# 枚举定义
# ---------------------------------------------------------------------------


class JobStatus(str, Enum):
    """分析流水线生命周期状态。"""

    QUEUED = "queued"
    CLONING = "cloning"
    ANALYZING = "analyzing"
    REPORTING = "reporting"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"


class RiskLevel(str, Enum):
    """代码质量问题的严重程度。"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# ---------------------------------------------------------------------------
# 请求
# ---------------------------------------------------------------------------


class AnalyzeRequest(BaseModel):
    """前端提交的分析请求。"""

    repo_url: str = Field(
        ...,
        min_length=1,
        max_length=512,
        description="待分析的 GitHub URL 或本地文件系统路径",
        examples=["https://github.com/psf/requests"],
    )


# ---------------------------------------------------------------------------
# 响应
# ---------------------------------------------------------------------------


class AnalyzeResponse(BaseModel):
    """分析请求被接受后立即返回。"""

    job_id: str = Field(default_factory=lambda: uuid4().hex)
    status: JobStatus = JobStatus.QUEUED


class StatusResponse(BaseModel):
    """前端轮询进度的响应模型。

    当分析器已完成但完整报告尚未生成时包含 partial_results。
    """

    job_id: str
    status: JobStatus
    progress_pct: int = Field(default=0, ge=0, le=100)
    stage_label: str = ""
    error_msg: Optional[str] = None
    partial_results: Optional[dict] = Field(
        default=None,
        description="报告生成前可用的分析器中间输出",
    )


class HistoryItem(BaseModel):
    """分析历史列表中的一条记录。"""

    job_id: str
    repo_url: str
    status: JobStatus
    health_score: Optional[int] = None
    created_at: str
    duration_ms: Optional[int] = None


class HealthResponse(BaseModel):
    """健康检查端点响应。"""

    status: str = "ok"


# ---------------------------------------------------------------------------
# 分析器结果模型
# ---------------------------------------------------------------------------


class LineRisk(BaseModel):
    """由静态分析标记的单行风险。"""

    line: int
    risk_level: RiskLevel
    reason: str = ""


class FunctionRisk(BaseModel):
    """圈复杂度过高的函数。"""

    file: str
    line: int
    name: str
    complexity: int
    risk_level: RiskLevel


class FileRiskSummary(BaseModel):
    """单个文件的聚合风险摘要。"""

    file: str
    risk_level: RiskLevel
    lint_issues: int = 0
    max_complexity: int = 0


class StaticResult(BaseModel):
    """静态分析器（pylint + radon）产出。"""

    high_complexity_functions: list[FunctionRisk] = Field(default_factory=list)
    file_heatmap: dict[str, list[LineRisk]] = Field(default_factory=dict)
    file_risk_summary: list[FileRiskSummary] = Field(default_factory=list)
    total_files_scanned: int = 0
    pylint_score: Optional[float] = Field(
        default=None, ge=0.0, le=10.0,
        description="所有文件的平均 pylint 评分 (0.0-10.0)",
    )
    duration_ms: int = 0
    error: Optional[str] = None


class InferredRisk(BaseModel):
    """由仓库分析器推断的项目级风险。"""

    category: str = Field(
        description="风险类别，例如：架构风险、维护风险、安全风险、依赖风险"
    )
    severity: RiskLevel
    description: str = Field(description="一句话风险描述")


class RepoResult(BaseModel):
    """仓库/LLM 分析器产出。"""

    usage_patterns: list[str] = Field(default_factory=list)
    core_modules: list[str] = Field(default_factory=list)
    summary: str = ""
    readme_quality_score: int = Field(default=0, ge=0, le=100)
    inferred_risks: list[InferredRisk] = Field(default_factory=list)
    duration_ms: int = 0
    error: Optional[str] = None


class Contributor(BaseModel):
    """单个贡献者信息：姓名、邮箱、提交次数。"""

    name: str = ""
    email: str = ""
    commits: int = 0


class ActiveFile(BaseModel):
    """频繁修改的文件及其变更次数。"""

    path: str
    changes: int


class WeeklyActivity(BaseModel):
    """单个 ISO 周的提交次数。"""

    week: str = Field(description="ISO 周字符串，例如 2024-W03")
    commits: int = 0


class GitResult(BaseModel):
    """Git 活动分析器产出。"""

    total_commits: int = 0
    commits_per_week: float = 0.0
    unique_contributors: int = 0
    active_days: int = 0
    top_contributors: list[Contributor] = Field(default_factory=list)
    active_files: list[ActiveFile] = Field(default_factory=list)
    activity_over_time: list[WeeklyActivity] = Field(default_factory=list)
    ci_cd_config: bool = Field(
        default=False,
        description="是否存在 .github/workflows 目录",
    )
    duration_ms: int = 0
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# 建议模型
# ---------------------------------------------------------------------------


class AnalysisPlan(BaseModel):
    """PlannerAgent 产出的分析计划。

    定义本次分析应执行的任务列表及优先级，
    通过 SharedMemory 写入供其他 Agent 读取。
    """

    tasks: list[str] = Field(
        default_factory=lambda: ["static_analysis", "repo_analysis", "git_analysis"],
        description="待执行的分析任务列表",
    )
    priority: str = Field(default="normal", description="normal 或 high")


class ReportResult(BaseModel):
    """ReportAgent 产出的汇总报告。

    从 SharedMemory 读取各 Agent 的分析结果后生成，
    包含结构化 JSON 摘要和可渲染 HTML。
    """

    repo_name: str = Field(default="", description="仓库名")
    repo_url: str = Field(default="", description="仓库 URL")
    analysis_id: str = Field(default="", description="分析任务 ID")

    # 摘要统计
    total_files_scanned: int = 0
    pylint_score: float | None = None
    total_commits: int = 0
    unique_contributors: int = 0
    ci_cd_detected: bool = False
    readme_quality_score: int = 0

    # Agent 状态
    agents_available: list[str] = Field(default_factory=list)

    # HTML 报告（可折叠结构）
    html_report: str = Field(default="", description="自包含 HTML 报告")


class Recommendation(BaseModel):
    """最终报告中的一条可操作改进建议。"""

    priority: int = Field(ge=1, le=3, description="1=高, 2=中, 3=低")
    category: str
    title: str
    detail: str


# ---------------------------------------------------------------------------
# 最终报告模型
# ---------------------------------------------------------------------------


class ReportJson(BaseModel):
    """返回给前端的完整分析报告。"""

    job_id: str
    repo_url: str
    health_score: int = Field(default=0, ge=0, le=100)
    static_analysis: Optional[StaticResult] = None
    repo_analysis: Optional[RepoResult] = None
    git_analysis: Optional[GitResult] = None
    recommendations: list[Recommendation] = Field(default_factory=list)
    html_report: str = ""
    total_duration_ms: int = 0
    created_at: str = Field(
        default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )
