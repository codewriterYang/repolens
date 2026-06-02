import { create } from 'zustand';
import type { ReportJson, StatusResponse } from '@/types/contracts';

// ---------------------------------------------------------------------------
// 前端 UI 状态（简化后端细粒度状态）
// ---------------------------------------------------------------------------

export type UiJobStatus =
  | 'idle'
  | 'queued'
  | 'running'
  | 'completed'
  | 'failed';

export interface AnalysisState {
  // 当前任务
  jobId: string | null;
  repoUrl: string | null;
  status: UiJobStatus;

  // 进度
  progressPct: number;
  stageLabel: string;

  // 部分结果（分析器完成后、报告生成前可用）
  partialResults: Record<string, unknown> | null;

  // 最终报告
  report: ReportJson | null;

  // 错误
  error: string | null;

  // 操作
  startJob: (jobId: string, repoUrl: string) => void;
  updateProgress: (data: StatusResponse) => void;
  setReport: (report: ReportJson) => void;
  completeJob: (report: ReportJson) => void;
  clearReport: () => void;
  markFailed: (errorMsg: string) => void;
  reset: () => void;
}

// ---------------------------------------------------------------------------
// 初始状态
// ---------------------------------------------------------------------------

const initialState = {
  jobId: null,
  repoUrl: null,
  status: 'idle' as UiJobStatus,
  progressPct: 0,
  stageLabel: '',
  partialResults: null,
  report: null,
  error: null,
};

// ---------------------------------------------------------------------------
// Store
// ---------------------------------------------------------------------------

export const useAnalysisStore = create<AnalysisState>((set) => ({
  ...initialState,

  startJob: (jobId, repoUrl) =>
    set({
      ...initialState,
      jobId,
      repoUrl,
      status: 'queued',
    }),

  updateProgress: (data) =>
    set({
      status: data.status === 'completed' ? 'completed'
        : data.status === 'failed' || data.status === 'timeout' ? 'failed'
        : data.status === 'queued' ? 'queued'
        : 'running',
      progressPct: data.progress_pct,
      stageLabel: data.stage_label,
      partialResults: data.partial_results ?? null,
      error: data.error_msg ?? null,
    }),

  // 查看历史报告 — 仅设置 report，不改变当前任务状态
  setReport: (report) =>
    set({ report }),

  // 当前任务完成 — 同步设置完成状态
  completeJob: (report) =>
    set({
      report,
      status: 'completed',
      progressPct: 100,
      stageLabel: '分析完成',
    }),

  // 清除当前显示的报告（切回实时监控视图）
  clearReport: () =>
    set({ report: null }),

  markFailed: (errorMsg) =>
    set({
      status: 'failed',
      error: errorMsg,
    }),

  reset: () => set(initialState),
}));
