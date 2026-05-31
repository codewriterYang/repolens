import { useCallback, useEffect, useRef } from 'react';
import { useAnalysisStore } from '@/store/analysisStore';
import {
  startAnalysis,
  fetchJobStatus,
  fetchReportJson,
} from '@/lib/api';
import type { AnalyzeRequest } from '@/types/contracts';

const POLL_INTERVAL_MS = 2000;

export function useAnalysisJob() {
  const { startJob, updateProgress, setReport, markFailed, reset } =
    useAnalysisStore();

  const jobId = useAnalysisStore((s) => s.jobId);
  const status = useAnalysisStore((s) => s.status);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // 停止轮询
  const stopPolling = useCallback(() => {
    if (pollRef.current !== null) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  // 当任务完成或失败时停止轮询
  useEffect(() => {
    if (status === 'completed' || status === 'failed') {
      stopPolling();
    }
  }, [status, stopPolling]);

  // 组件卸载时清理
  useEffect(() => {
    return () => stopPolling();
  }, [stopPolling]);

  // 提交分析
  const submit = useCallback(
    async (input: { repo_url: string }) => {
      reset();
      try {
        const resp = await startAnalysis({ repo_url: input.repo_url } as AnalyzeRequest);
        startJob(resp.job_id, input.repo_url);

        // 开始轮询
        stopPolling();
        pollRef.current = setInterval(async () => {
          try {
            const progress = await fetchJobStatus(resp.job_id);
            updateProgress(progress);

            if (progress.status === 'completed') {
              stopPolling();
              try {
                const report = await fetchReportJson(resp.job_id);
                setReport(report);
              } catch {
                // 报告可能尚未就绪，重试一次
                setTimeout(async () => {
                  try {
                    const report = await fetchReportJson(resp.job_id);
                    setReport(report);
                  } catch {
                    markFailed('无法加载分析报告');
                  }
                }, 2000);
              }
            } else if (progress.status === 'failed' || progress.status === 'timeout') {
              stopPolling();
              markFailed(progress.error_msg || '分析失败');
            }
          } catch {
            // 轮询失败不中断，继续尝试
          }
        }, POLL_INTERVAL_MS);
      } catch (err) {
        markFailed(err instanceof Error ? err.message : '提交分析请求失败');
      }
    },
    [startJob, updateProgress, setReport, markFailed, reset, stopPolling],
  );

  return { submit, jobId, status };
}
