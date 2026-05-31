import { useCallback, useState } from 'react';
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

  const running = status === 'queued' || status === 'running';

  // 历史刷新标记
  const [refreshToken, setRefreshToken] = useState(0);
  const [historicalJobId, setHistoricalJobId] = useState<string | null>(null);

  // 当新报告生成时刷新历史
  if (report && refreshToken === 0 && jobId) {
    setTimeout(() => setRefreshToken((r) => r + 1), 500);
  }

  // 加载历史记录
  const loadHistorical = useCallback(
    async (clickedJobId: string) => {
      try {
        const data: ReportJson = await fetchReportJson(clickedJobId);
        setReport(data);
        setHistoricalJobId(clickedJobId);
      } catch (e) {
        alert(
          `加载失败: ${e instanceof Error ? e.message : String(e)}`,
        );
      }
    },
    [setReport],
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
          <RepoInput onSubmit={submit} disabled={running} />
          {jobId && status !== 'idle' && (
            <ProgressPanel
              jobId={jobId}
              progressPct={progressPct}
              stageLabel={stageLabel}
            />
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
