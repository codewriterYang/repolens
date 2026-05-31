import axios, { type AxiosInstance } from 'axios';
import type {
  AnalyzeRequest,
  AnalyzeResponse,
  HistoryItem,
  ReportJson,
  StatusResponse,
} from '@/types/contracts';

const BASE_URL =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? '/api';

function createClient(): AxiosInstance {
  const client = axios.create({
    baseURL: BASE_URL,
    timeout: 30_000,
    headers: {
      'Content-Type': 'application/json',
    },
  });
  return client;
}

export const apiClient = createClient();

/** 提交仓库分析请求 */
export async function startAnalysis(
  payload: AnalyzeRequest,
): Promise<AnalyzeResponse> {
  const { data } = await apiClient.post<AnalyzeResponse>('/analyze', payload);
  return data;
}

/** 轮询任务进度 */
export async function fetchJobStatus(
  jobId: string,
): Promise<StatusResponse> {
  const { data } = await apiClient.get<StatusResponse>(`/status/${jobId}`);
  return data;
}

/** 获取 JSON 报告 */
export async function fetchReportJson(
  jobId: string,
): Promise<ReportJson> {
  const { data } = await apiClient.get<ReportJson>(`/report/${jobId}`);
  return data;
}

/** 获取 HTML 报告（纯文本） */
export async function fetchReportHtml(jobId: string): Promise<string> {
  const { data } = await apiClient.get<string>(`/report/${jobId}/html`, {
    responseType: 'text',
    transformResponse: [(raw) => raw as string],
  });
  return data;
}

/** 获取分析历史 */
export async function fetchHistory(): Promise<HistoryItem[]> {
  const { data } = await apiClient.get<HistoryItem[]>('/history');
  return data;
}
