import { useCallback, useEffect, useRef, useState } from 'react';
import { useAnalysisJob } from '@/hooks/useAnalysisJob';
import { useAnalysisStore } from '@/store/analysisStore';
import { fetchReportJson } from '@/lib/api';
import { RepoInput } from '@/components/RepoInput';
import { ProgressPanel } from '@/components/ProgressPanel';
import { ReportViewer } from '@/components/ReportViewer';
import { HistoryList } from '@/components/HistoryList';
import { Card, CardContent } from '@/components/ui/card';
import type { ReportJson } from '@/types/contracts';

function EmptyState() {
  return (
    <Card className="h-full">
      <CardContent className="flex h-full min-h-[60vh] flex-col items-center justify-center gap-2 text-center">
        <h2 className="text-lg font-semibold">尚未生成报告</h2>
        <p className="max-w-md text-sm text-muted-foreground">
          在左侧输入 GitHub 仓库 URL 或本地路径，点击「开始分析」。
          系统将并行执行代码质量分析、仓库结构推断与 Git 活动分析，生成自包含 HTML 报告。
        </p>
      </CardContent>
    </Card>
  );
}

function LoadingSkeleton() {
  return (
    <Card className="h-full">
      <CardContent className="flex h-full min-h-[60vh] flex-col gap-4 p-6">
        <div className="h-6 w-48 animate-pulse rounded bg-muted" />
        <div className="h-4 w-72 animate-pulse rounded bg-muted" />
        <div className="mt-4 grid grid-cols-2 gap-4">
          <div className="h-24 animate-pulse rounded bg-muted" />
          <div className="h-24 animate-pulse rounded bg-muted" />
        </div>
        <div className="mt-2 h-64 animate-pulse rounded bg-muted" />
        <p className="text-center text-xs text-muted-foreground">
          正在分析仓库，请稍候…
        </p>
      </CardContent>
    </Card>
  );
}

export default function App() {
  const { submit } = useAnalysisJob();

  const jobId = useAnalysisStore((s) => s.jobId);
  const status = useAnalysisStore((s) => s.status);
  const progressPct = useAnalysisStore((s) => s.progressPct);
  const stageLabel = useAnalysisStore((s) => s.stageLabel);
  const report = useAnalysisStore((s) => s.report);
  const error = useAnalysisStore((s) => s.error);
  const setReport = useAnalysisStore((s) => s.setReport);
  const clearReport = useAnalysisStore((s) => s.clearReport);

  const running = status === 'queued' || status === 'running';

  // 历史刷新标记 — 使用 ref 避免 render 期间副作用
  const [refreshToken, setRefreshToken] = useState(0);
  const hasRefreshed = useRef(false);

  // 当前正在查看的历史 jobId（null = 查看当前任务）
  const [historicalJobId, setHistoricalJobId] = useState<string | null>(null);

  // 新任务开始时重置历史刷新标记
  if (jobId) {
    hasRefreshed.current = false;
  }

  // 当当前任务报告生成时刷新历史列表
  if (report && !hasRefreshed.current && jobId && !historicalJobId) {
    hasRefreshed.current = true;
    setTimeout(() => setRefreshToken((r) => r + 1), 500);
  }

  // 提交新分析时清理历史查看状态
  const handleSubmit = useCallback(
    async (input: { repo_url: string }) => {
      setHistoricalJobId(null);
      hasRefreshed.current = false;
      await submit(input);
    },
    [submit],
  );

  // 分析过程中自动刷新历史列表（每 3 秒），实时显示状态变化
  useEffect(() => {
    if (!running) return;
    const interval = setInterval(() => {
      setRefreshToken((r) => r + 1);
    }, 3000);
    return () => clearInterval(interval);
  }, [running]);

  // 加载历史记录
  const loadHistorical = useCallback(
    async (clickedJobId: string) => {
      // 点击当前任务 → 切回实时视图
      if (clickedJobId === jobId) {
        setHistoricalJobId(null);
        if (status === 'completed') {
          // 已完成 → 重新加载报告
          try {
            const data: ReportJson = await fetchReportJson(jobId);
            setReport(data);
          } catch {
            clearReport();
          }
        } else {
          // 运行中 → 清除旧报告显示骨架屏
          clearReport();
        }
        return;
      }

      try {
        const data: ReportJson = await fetchReportJson(clickedJobId);
        // setReport 只设置 report，不改变 status/progress（避免中断轮询）
        setReport(data);
        setHistoricalJobId(clickedJobId);
      } catch {
        alert('该任务尚未完成或报告不可用');
      }
    },
    [setReport, clearReport, jobId, status],
  );

  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="border-b border-border">
        <div className="mx-auto flex max-w-screen-2xl items-center justify-between px-4 py-3 lg:px-8">
          <h1 className="text-lg font-semibold">RepoLens</h1>
          <span className="text-xs text-muted-foreground">
            AI 驱动仓库分析
          </span>
        </div>
      </header>

      <main className="mx-auto grid max-w-screen-2xl gap-6 p-4 lg:grid-cols-[384px_1fr] lg:p-8">
        <aside className="space-y-4">
          <RepoInput onSubmit={handleSubmit} disabled={running} />

          {/* 进度面板 — 仅当前任务运行中时显示，不被历史查看覆盖 */}
          {jobId && running && (
            <ProgressPanel
              jobId={jobId}
              progressPct={progressPct}
              stageLabel={stageLabel}
            />
          )}

          {/* 有任务在后台运行时 + 查看历史 → 提示用户 */}
          {historicalJobId && running && (
            <div className="rounded-md border border-blue-200 bg-blue-50 p-2 text-xs text-blue-700">
              当前任务仍在后台进行分析
            </div>
          )}

          {error && (
            <div className="rounded-md border border-destructive/60 bg-destructive/5 p-3 text-sm text-destructive">
              {error}
            </div>
          )}

          <HistoryList
            onSelect={loadHistorical}
            activeJobId={historicalJobId ?? jobId}
            refreshToken={refreshToken}
          />
        </aside>

        <section className="min-h-[60vh]">
          {report ? (
            <ReportViewer report={report} />
          ) : running ? (
            <LoadingSkeleton />
          ) : (
            <EmptyState />
          )}
        </section>
      </main>
    </div>
  );
}
