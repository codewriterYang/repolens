"""RepoLens Agent 架构测试覆盖专项。

Phase 7.5: 覆盖 agents/、context/、memory/、planner/ 全部核心模块。

测试原则：
- 验证真实业务行为，不为覆盖率写无意义测试
- 输入 → 处理 → 输出 完整链路
- 边界条件覆盖
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

# 确保 backend 可导入
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))


# =========================================================================
# 1. SharedMemory — Agent 协作核心总线
# =========================================================================

class TestSharedMemory:
    """SharedMemory 线程安全 KV 存储的完整功能验证。"""

    @pytest.fixture
    def memory(self):
        from repolens.memory import SharedMemory
        return SharedMemory()

    def test_set_and_get(self, memory):
        """验证基础读写。"""
        memory.set("key1", "value1")
        memory.set("key2", 42)
        assert memory.get("key1") == "value1"
        assert memory.get("key2") == 42

    def test_get_missing_key_returns_none(self, memory):
        """验证不存在的 key 返回 None。"""
        assert memory.get("nope") is None

    def test_get_missing_key_with_default(self, memory):
        """验证自定义默认值。"""
        assert memory.get("nope", "fallback") == "fallback"
        assert memory.get("nope", 100) == 100

    def test_has_existing_and_missing(self, memory):
        """验证存在性检查。"""
        memory.set("exists", 1)
        assert memory.has("exists") is True
        assert memory.has("missing") is False

    def test_delete_removes_key(self, memory):
        """验证删除操作。"""
        memory.set("temp", "x")
        memory.delete("temp")
        assert memory.has("temp") is False
        memory.delete("nonexistent")  # 不应报错

    def test_keys_returns_all(self, memory):
        """验证 keys 返回完整列表。"""
        memory.set("a", 1)
        memory.set("b", 2)
        keys = memory.keys()
        assert set(keys) == {"a", "b"}

    def test_clear_empties_store(self, memory):
        """验证 clear 清空所有数据。"""
        memory.set("a", 1)
        memory.set("b", 2)
        memory.clear()
        assert memory.keys() == []
        assert len(memory) == 0

    def test_snapshot_is_copy_not_reference(self, memory):
        """验证 snapshot 返回副本，修改不影响原值。"""
        memory.set("a", 1)
        snap = memory.snapshot()
        snap["a"] = 999
        assert memory.get("a") == 1  # 原值不变

    def test_len(self, memory):
        """验证计数。"""
        assert len(memory) == 0
        memory.set("x", 1)
        assert len(memory) == 1

    def test_overwrite_existing_key(self, memory):
        """验证覆盖写入。"""
        memory.set("key", "old")
        memory.set("key", "new")
        assert memory.get("key") == "new"

    def test_multiple_data_types(self, memory):
        """验证多种数据类型存储。"""
        memory.set("str_val", "hello")
        memory.set("int_val", 42)
        memory.set("list_val", [1, 2, 3])
        memory.set("dict_val", {"nested": True})
        memory.set("none_val", None)
        assert memory.get("dict_val") == {"nested": True}
        assert memory.get("none_val") is None


# =========================================================================
# 2. MemoryManager
# =========================================================================

class TestMemoryManager:
    """MemoryManager 生命周期验证。"""

    def test_create_returns_memory(self):
        from repolens.memory import MemoryManager
        manager = MemoryManager()
        memory = manager.create()
        assert memory is not None
        assert isinstance(memory, type(manager.get_memory()))

    def test_get_memory_before_create_returns_none(self):
        from repolens.memory import MemoryManager
        manager = MemoryManager()
        assert manager.get_memory() is None

    def test_get_memory_after_create(self):
        from repolens.memory import MemoryManager
        manager = MemoryManager()
        mem = manager.create()
        assert manager.get_memory() is mem

    def test_create_replaces_old_reference(self):
        from repolens.memory import MemoryManager
        manager = MemoryManager()
        mem1 = manager.create()
        mem1.set("old", True)
        mem2 = manager.create()
        assert manager.get_memory() is mem2
        assert mem2.get("old") is None  # 新实例无旧数据

    def test_clear_empties_current_memory(self):
        from repolens.memory import MemoryManager
        manager = MemoryManager()
        memory = manager.create()
        memory.set("data", "keep")
        assert len(memory) == 1
        manager.clear()
        assert len(memory) == 0


# =========================================================================
# 3. RepositoryContext
# =========================================================================

class TestRepositoryContext:
    """RepositoryContext 不可变上下文的完整性验证。"""

    def test_construction_all_fields(self):
        from repolens.context import RepositoryContext
        ctx = RepositoryContext(
            repo_url="https://github.com/a/b",
            repo_path="/tmp/repo",
            repo_name="b",
            analysis_id="abc123",
        )
        assert ctx.repo_url == "https://github.com/a/b"
        assert ctx.repo_path == "/tmp/repo"
        assert ctx.repo_name == "b"
        assert ctx.analysis_id == "abc123"

    def test_is_frozen_immutable(self):
        from repolens.context import RepositoryContext
        ctx = RepositoryContext("url", "/path", "name", "id")
        with pytest.raises(Exception):
            ctx.repo_url = "new"

    def test_started_at_default(self):
        from repolens.context import RepositoryContext
        ctx = RepositoryContext("url", "/path", "name", "id")
        assert isinstance(ctx.started_at, datetime)

    def test_make_context_extracts_name_from_url(self):
        from repolens.context import make_context
        ctx = make_context(
            repo_url="https://github.com/owner/my-project",
            repo_path="/tmp/repo",
            analysis_id="test123",
        )
        assert ctx.repo_name == "my-project"

    def test_make_context_handles_git_suffix(self):
        from repolens.context import make_context
        ctx = make_context(
            repo_url="https://github.com/a/repo.git",
            repo_path="/tmp/repo",
            analysis_id="test",
        )
        assert ctx.repo_name == "repo"

    def test_make_context_handles_windows_path(self):
        from repolens.context import make_context
        ctx = make_context(
            repo_url="C:\\Users\\admin\\my-project",
            repo_path="C:\\Users\\admin\\my-project",
            analysis_id="test",
        )
        assert ctx.repo_name == "my-project"


# =========================================================================
# 4. ContextManager
# =========================================================================

class TestContextManager:
    """ContextManager 生命周期验证。"""

    def test_create_returns_valid_context(self):
        from repolens.context import ContextManager
        manager = ContextManager()
        ctx = manager.create(
            repo_url="https://github.com/a/b",
            repo_path=os.getcwd(),  # 真实存在的目录
            analysis_id="test123",
        )
        assert ctx.repo_name == "b"

    def test_create_and_validate_succeeds_on_valid_dir(self):
        from repolens.context import ContextManager
        manager = ContextManager()
        ctx = manager.create_and_validate(
            repo_url="url",
            repo_path=os.getcwd(),
            analysis_id="test",
        )
        assert ctx is not None

    def test_create_and_validate_fails_on_missing_dir(self):
        from repolens.context import ContextManager
        manager = ContextManager()
        ctx = manager.create(
            repo_url="url",
            repo_path="/nonexistent/path/xyz",
            analysis_id="test",
        )
        with pytest.raises(ValueError):
            manager.validate(ctx)


# =========================================================================
# 5. PlanningRules — 规则引擎核心验证
# =========================================================================

class TestPlanningRules:
    """PlanningRules 规则引擎业务逻辑验证。"""

    @pytest.fixture
    def rules(self):
        from repolens.planner import PlanningRules
        return PlanningRules()

    # ---------- static 策略（Phase 8: skip → strategy） ----------

    def test_fast_strategy_for_large_repo(self, rules):
        """file_count > 1000 → static = "fast"。"""
        plan = rules.evaluate({"file_count": 2000, "has_readme": True})
        assert plan.strategy.static == "fast"
        assert "static_analysis" in plan.tasks          # 始终执行

    def test_fast_strategy_confidence_50(self, rules):
        """fast 模式置信度 50%。"""
        plan = rules.evaluate({"file_count": 2000, "has_readme": True})
        assert plan.strategy.static_confidence == 50

    def test_sampled_strategy_for_medium_repo(self, rules):
        """501-1000 文件 → static = "sampled"。"""
        plan = rules.evaluate({"file_count": 750, "has_readme": True})
        assert plan.strategy.static == "sampled"
        assert plan.strategy.static_confidence == 75

    def test_full_strategy_for_small_repo(self, rules):
        """≤500 文件 → static = "full"。"""
        plan = rules.evaluate({"file_count": 100, "has_readme": True})
        assert plan.strategy.static == "full"
        assert plan.strategy.static_confidence == 100

    def test_boundary_1000_is_fast(self, rules):
        """恰好 1000 文件 → sampled（>1000 才是 fast）。"""
        plan = rules.evaluate({"file_count": 1000, "has_readme": True})
        assert plan.strategy.static == "sampled"

    # ---------- repo/git 始终 full ----------

    def test_repo_always_full(self, rules):
        """repo 分析始终保持 full。"""
        plan = rules.evaluate({"file_count": 5000, "has_readme": False})
        assert plan.strategy.repo == "full"

    def test_git_always_full(self, rules):
        """git 分析始终保持 full。"""
        plan = rules.evaluate({"file_count": 5000, "has_readme": False})
        assert plan.strategy.git == "full"

    # ---------- 组合场景 ----------

    def test_all_tasks_always_executed(self, rules):
        """无论仓库大小，所有任务始终在执行列表中。"""
        plan = rules.evaluate({"file_count": 5000, "has_readme": False})
        assert "static_analysis" in plan.tasks
        assert "repo_analysis" in plan.tasks
        assert "git_analysis" in plan.tasks

    def test_reasons_contain_strategy_rationale(self, rules):
        """reasons 包含策略选择理由。"""
        plan = rules.evaluate({"file_count": 2000, "has_readme": True})
        assert "fast" in plan.reasons.get("static", "")

    def test_priority_high_for_fast_strategy(self, rules):
        """fast 策略时 priority=high。"""
        plan = rules.evaluate({"file_count": 2000, "has_readme": True})
        assert plan.priority == "high"

    def test_priority_normal_for_full_strategy(self, rules):
        """full 策略时 priority=normal。"""
        plan = rules.evaluate({"file_count": 10, "has_readme": True})
        assert plan.priority == "normal"


# =========================================================================
# 6. DynamicPlanner — Profiler + Rules 编排层
# =========================================================================

class TestDynamicPlanner:
    """DynamicPlanner 编排层验证。"""

    @pytest.fixture
    def planner(self):
        from repolens.planner import DynamicPlanner
        return DynamicPlanner()

    def test_plan_on_real_directory(self, planner):
        """用真实目录（当前目录）测试 plan，确保不崩溃。"""
        plan = planner.plan(os.getcwd())
        assert isinstance(plan.tasks, list)
        assert isinstance(plan.reasons, dict)
        assert len(plan.tasks) > 0
        assert hasattr(plan, "strategy")

    def test_plan_all_tasks_small_dir(self, planner, tmp_path):
        """小目录 → 全部任务执行。"""
        (tmp_path / "README.md").write_text("# Test")
        plan = planner.plan(str(tmp_path))
        assert "static_analysis" in plan.tasks
        assert plan.strategy.static == "full"

    def test_plan_falls_back_for_missing_dir(self, planner):
        """不存在的目录 → 不崩溃，返回默认 plan。"""
        plan = planner.plan("/nonexistent/directory/xyz")
        assert plan is not None
        assert "static_analysis" in plan.tasks


# =========================================================================
# 7. AgentRegistry — 注册/获取/注入
# =========================================================================

class DummyAgent:
    """用于测试 AgentRegistry 的假 Agent。"""
    name = "dummy"

    def __init__(self):
        self.memory = None

    def inject_memory(self, mem):
        self.memory = mem

    async def run(self, ctx, **kwargs):
        return {"status": "ok"}


class TestAgentRegistry:
    """AgentRegistry 注册中心验证。"""

    @pytest.fixture
    def registry(self):
        from repolens.agents import AgentRegistry
        return AgentRegistry()

    def test_register_and_get(self, registry):
        agent = DummyAgent()
        registry.register(agent)
        assert registry.get("dummy") is agent

    def test_get_unregistered_returns_none(self, registry):
        assert registry.get("nope") is None

    def test_duplicate_register_raises(self, registry):
        registry.register(DummyAgent())
        with pytest.raises(ValueError):
            registry.register(DummyAgent())

    def test_inject_memory_propagates_to_all(self, registry):
        from repolens.memory import SharedMemory
        a1 = DummyAgent()
        a1.name = "a1"
        a2 = DummyAgent()
        a2.name = "a2"
        registry.register(a1)
        registry.register(a2)

        memory = SharedMemory()
        registry.inject_memory(memory)

        assert a1.memory is memory
        assert a2.memory is memory

    def test_list_returns_registered_names(self, registry):
        registry.register(DummyAgent())
        assert "dummy" in registry.list()

    def test_len_and_contains(self, registry):
        registry.register(DummyAgent())
        assert len(registry) == 1
        assert "dummy" in registry
        assert "nope" not in registry

    def test_clear_empties(self, registry):
        registry.register(DummyAgent())
        registry.clear()
        assert len(registry) == 0
        assert registry.get("dummy") is None


# =========================================================================
# 8. PlannerAgent — Plan 写入 Memory
# =========================================================================

class TestPlannerAgent:
    """PlannerAgent 行为验证。"""

    @pytest.fixture
    def context(self):
        from repolens.context import RepositoryContext
        return RepositoryContext(
            repo_url="https://github.com/test/repo",
            repo_path=os.getcwd(),
            repo_name="repo",
            analysis_id="test123",
        )

    def test_plan_written_to_memory(self, context):
        from repolens.agents import PlannerAgent
        from repolens.memory import SharedMemory
        from repolens.schemas import AnalysisPlan

        memory = SharedMemory()
        agent = PlannerAgent(memory=memory)

        import asyncio
        plan = asyncio.run(agent.run(context))

        assert isinstance(plan, AnalysisPlan)
        assert memory.has("analysis_plan")
        stored = memory.get("analysis_plan")
        assert isinstance(stored, AnalysisPlan)

    def test_plan_without_memory_does_not_crash(self, context):
        from repolens.agents import PlannerAgent
        from repolens.schemas import AnalysisPlan

        agent = PlannerAgent(memory=None)

        import asyncio
        plan = asyncio.run(agent.run(context))
        assert isinstance(plan, AnalysisPlan)

    def test_plan_tasks_not_empty(self, context):
        from repolens.agents import PlannerAgent
        from repolens.memory import SharedMemory

        memory = SharedMemory()
        agent = PlannerAgent(memory=memory)

        import asyncio
        plan = asyncio.run(agent.run(context))
        assert len(plan.tasks) > 0


# =========================================================================
# 9. ReportAgent — 从 Memory 读取并生成报告
# =========================================================================

class TestReportAgent:
    """ReportAgent 行为验证。"""

    @pytest.fixture
    def context(self):
        from repolens.context import RepositoryContext
        return RepositoryContext(
            repo_url="https://github.com/test/repo",
            repo_path=os.getcwd(),
            repo_name="repo",
            analysis_id="test123",
        )

    def test_empty_memory_produces_valid_report(self, context):
        """空 Memory → 不崩溃，产出合法报告。"""
        from repolens.agents import ReportAgent
        from repolens.memory import SharedMemory
        from repolens.schemas import ReportResult

        memory = SharedMemory()
        agent = ReportAgent(memory=memory)

        import asyncio
        result = asyncio.run(agent.run(context))

        assert isinstance(result, ReportResult)
        assert result.agents_available == []

    def test_report_written_to_memory(self, context):
        """结果写回 Memory。"""
        from repolens.agents import ReportAgent
        from repolens.memory import SharedMemory

        memory = SharedMemory()
        agent = ReportAgent(memory=memory)

        import asyncio
        result = asyncio.run(agent.run(context))

        assert memory.has("report_result")
        stored = memory.get("report_result")
        assert stored.analysis_id == "test123"

    def test_html_report_contains_basic_structure(self, context):
        """HTML 报告包含基本结构标签。"""
        from repolens.agents import ReportAgent
        from repolens.memory import SharedMemory

        memory = SharedMemory()
        agent = ReportAgent(memory=memory)

        import asyncio
        result = asyncio.run(agent.run(context))

        html = result.html_report
        assert "<html" in html.lower()
        assert "RepoLens" in html
        assert context.repo_name in html

    def test_html_report_includes_plan_summary(self, context):
        """HTML 报告包含 Plan Summary。"""
        from repolens.agents import ReportAgent
        from repolens.memory import SharedMemory
        from repolens.schemas import AnalysisPlan, AnalysisStrategy

        memory = SharedMemory()
        plan = AnalysisPlan(
            tasks=["static_analysis", "repo_analysis", "git_analysis"],
            strategy=AnalysisStrategy(static="fast", repo="full", git="full"),
            reasons={"static": "超大仓库，fast 模式"},
        )
        memory.set("analysis_plan", plan)

        agent = ReportAgent(memory=memory)

        import asyncio
        result = asyncio.run(agent.run(context))

        assert "Plan Summary" in result.html_report
        assert "分析策略" in result.html_report
        assert "fast" in result.html_report

    def test_reads_memory_for_agent_results(self, context):
        """从 Memory 读取各 Agent 结果。"""
        from repolens.agents import ReportAgent
        from repolens.memory import SharedMemory
        from repolens.schemas import AnalysisPlan, GitResult, StaticResult

        memory = SharedMemory()
        # 模拟 Pipeline 写入
        memory.set("analysis_plan", AnalysisPlan())
        memory.set("static_result", StaticResult(total_files_scanned=10, pylint_score=8.0))
        memory.set("git_result", GitResult(total_commits=100))

        agent = ReportAgent(memory=memory)

        import asyncio
        result = asyncio.run(agent.run(context))

        assert "static" in result.agents_available
        assert "git" in result.agents_available
        assert result.total_files_scanned == 10
        assert result.total_commits == 100
