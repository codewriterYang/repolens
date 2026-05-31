# RepoLens 集成测试
"""RepoLens 分析流水线的端到端验证。

覆盖：
- Schema 序列化（所有 Pydantic 模型）
- Reporter HTML 生成（所有区域存在性检查）
- 数据库操作（部分结果、完整持久化）
- 错误场景（分析器失败、None 输入）
- API 路由注册
"""
import asyncio
import json
import time


async def test_e2e():
    print("=== RepoLens 端到端验证 ===")

    # 1. Schema 序列化
    from repolens.schemas import (
        ActiveFile,
        Contributor,
        FileRiskSummary,
        FunctionRisk,
        GitResult,
        InferredRisk,
        JobStatus,
        ReportJson,
        RepoResult,
        RiskLevel,
        StaticResult,
        StatusResponse,
        WeeklyActivity,
    )

    sr = StaticResult(total_files_scanned=10, pylint_score=8.0)
    assert "total_files_scanned" in sr.model_dump_json()
    print("通过: StaticResult 序列化")

    rr = RepoResult(readme_quality_score=50)
    assert "readme_quality_score" in rr.model_dump_json()
    print("通过: RepoResult 序列化")

    gr = GitResult(total_commits=100)
    assert "total_commits" in gr.model_dump_json()
    print("通过: GitResult 序列化")

    report = ReportJson(
        job_id="test",
        repo_url="http://x",
        health_score=80,
        static_analysis=sr,
        repo_analysis=rr,
        git_analysis=gr,
    )
    report2 = ReportJson.model_validate(json.loads(report.model_dump_json()))
    assert report2.health_score == 80
    print("通过: ReportJson 往返序列化")

    status = StatusResponse(
        job_id="x",
        status=JobStatus.ANALYZING,
        progress_pct=50,
        stage_label="testing",
        partial_results={"static_analysis": sr.model_dump()},
    )
    assert "partial_results" in status.model_dump_json()
    print("通过: StatusResponse 含 partial_results")

    # 2. Reporter 含完整数据
    from repolens.reporter import Reporter

    r = Reporter()

    test_sr = StaticResult(
        total_files_scanned=100,
        pylint_score=6.8,
        high_complexity_functions=[
            FunctionRisk(file="a.py", line=10, name="f1", complexity=30, risk_level=RiskLevel.HIGH),
            FunctionRisk(file="b.py", line=20, name="f2", complexity=12, risk_level=RiskLevel.MEDIUM),
        ],
        file_risk_summary=[
            FileRiskSummary(file="a.py", risk_level=RiskLevel.HIGH, lint_issues=20, max_complexity=30),
            FileRiskSummary(file="b.py", risk_level=RiskLevel.MEDIUM, lint_issues=5, max_complexity=12),
            FileRiskSummary(file="c.py", risk_level=RiskLevel.LOW, lint_issues=1, max_complexity=3),
        ],
    )
    test_rr = RepoResult(
        usage_patterns=["Web API", "Data Pipeline"],
        core_modules=["api", "pipeline", "models"],
        summary="一个数据处理 Web API。",
        readme_quality_score=72,
        inferred_risks=[
            InferredRisk(category="维护风险", severity=RiskLevel.HIGH, description="未发现测试"),
            InferredRisk(category="安全风险", severity=RiskLevel.MEDIUM, description="无认证配置"),
        ],
    )
    test_gr = GitResult(
        total_commits=500,
        commits_per_week=8.2,
        unique_contributors=12,
        active_days=180,
        top_contributors=[
            Contributor(name="Alice", email="a@x.com", commits=200),
            Contributor(name="Bob", email="b@x.com", commits=150),
        ],
        active_files=[
            ActiveFile(path="api/routes.py", changes=80),
            ActiveFile(path="pipeline/core.py", changes=65),
        ],
        activity_over_time=[
            WeeklyActivity(week=f"2024-W{w:02d}", commits=c)
            for w, c in [(1,5),(2,12),(3,3),(4,8),(5,15),(6,7),(7,10),(8,4),(9,9),(10,6),(11,11),(12,2)]
        ],
        ci_cd_config=False,
    )

    full_report = r.render(
        "e2e-job", "https://github.com/e2e/test",
        test_sr, test_rr, test_gr,
        time.monotonic() - 5.0,
    )

    html = full_report.html_report
    assert "健康评分" in html
    assert "改进建议" in html
    assert "Git" in html
    assert "collapsible" in html
    assert "<svg" in html
    assert "breakdown" in html
    print(f"通过: Reporter HTML（评分={full_report.health_score}, 建议={len(full_report.recommendations)}条）")

    cats = {rec.category for rec in full_report.recommendations}
    assert len(cats) >= 2, f"期望 2+ 类别，实际 {cats}"
    print(f"通过: 建议涵盖类别: {cats}")

    # 3. 数据库操作
    from repolens.db import (
        close_db,
        create_job,
        get_job_status,
        get_report,
        init_db,
        save_partial_results,
        save_report,
    )

    db = await init_db(":memory:")
    await create_job(db, "e2e-db-test", "https://github.com/test/db")

    await save_partial_results(
        db, "e2e-db-test",
        static_result=test_sr.model_dump(),
        git_result=test_gr.model_dump(),
    )

    status_row = await get_job_status(db, "e2e-db-test")
    assert status_row is not None
    assert status_row["partial"] is not None
    assert "static_analysis" in status_row["partial"]
    assert "git_analysis" in status_row["partial"]
    assert "repo_analysis" not in status_row["partial"]
    print("通过: 数据库部分结果合并")

    await save_report(db, "e2e-db-test", full_report)
    loaded = await get_report(db, "e2e-db-test")
    assert loaded is not None
    assert loaded.health_score == full_report.health_score
    print("通过: 数据库完整报告持久化")

    await close_db(db)

    # 4. 错误场景
    err_sr = StaticResult(error="Pylint 未安装")
    err_rr = RepoResult(error="LLM 不可用")
    err_gr = GitResult(error="不是 Git 仓库")

    err_report = r.render("err", "https://x", err_sr, err_rr, err_gr, time.monotonic())
    assert err_report.health_score == 0
    assert len(err_report.html_report) > 500
    print("通过: 错误场景产出合法报告")

    null_report = r.render("null", "https://x", None, None, None, time.monotonic())
    assert null_report.health_score == 0
    assert len(null_report.html_report) > 300
    print("通过: 全 None 输入产出合法报告")

    # 5. API 路由
    from repolens.main import app
    routes = {r.path for r in app.routes if hasattr(r, "path") and "/api/" in r.path}
    expected = {
        "/api/analyze", "/api/status/{job_id}", "/api/report/{job_id}",
        "/api/report/{job_id}/html", "/api/history", "/api/health",
    }
    assert expected == routes, f"路由不匹配: 缺失={expected - routes}, 多余={routes - expected}"
    print(f"通过: 全部 6 个 API 路由: {sorted(routes)}")

    print()
    print("=== 全部测试通过 ===")


if __name__ == "__main__":
    asyncio.run(test_e2e())
