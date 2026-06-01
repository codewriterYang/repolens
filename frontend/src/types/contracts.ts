// 与后端 Pydantic v2 schemas 完全对齐
// 字段名保持 snake_case，避免序列化转换层

// ---------------------------------------------------------------------------
// 枚举
// ---------------------------------------------------------------------------

export type JobStatus =
  | 'queued'
  | 'cloning'
  | 'analyzing'
  | 'reporting'
  | 'completed'
  | 'failed'
  | 'timeout';

export type RiskLevel = 'low' | 'medium' | 'high';

// ---------------------------------------------------------------------------
// 请求
// ---------------------------------------------------------------------------

export interface AnalyzeRequest {
  repo_url: string;
}

// ---------------------------------------------------------------------------
// 响应
// ---------------------------------------------------------------------------

export interface AnalyzeResponse {
  job_id: string;
  status: string;
}

export interface StatusResponse {
  job_id: string;
  status: JobStatus;
  progress_pct: number;
  stage_label: string;
  error_msg?: string | null;
  partial_results?: Record<string, unknown> | null;
}

export interface HistoryItem {
  job_id: string;
  repo_url: string;
  status: JobStatus;
  health_score?: number | null;
  created_at: string;
  duration_ms?: number | null;
}

export interface HealthResponse {
  status: string;
}

// ---------------------------------------------------------------------------
// 分析器结果
// ---------------------------------------------------------------------------

export interface FunctionRisk {
  file: string;
  line: number;
  name: string;
  complexity: number;
  risk_level: RiskLevel;
}

export interface FileRiskSummary {
  file: string;
  risk_level: RiskLevel;
  lint_issues: number;
  max_complexity: number;
}

export interface LineRisk {
  line: number;
  risk_level: RiskLevel;
  reason: string;
}

export interface StaticResult {
  high_complexity_functions: FunctionRisk[];
  file_heatmap: Record<string, LineRisk[]>;
  file_risk_summary: FileRiskSummary[];
  total_files_scanned: number;
  pylint_score?: number | null;
  duration_ms: number;
  error?: string | null;
}

export interface InferredRisk {
  category: string;
  severity: RiskLevel;
  description: string;
}

export interface RepoResult {
  usage_patterns: string[];
  core_modules: string[];
  summary: string;
  readme_quality_score: number;
  inferred_risks: InferredRisk[];
  duration_ms: number;
  error?: string | null;
}

export interface Contributor {
  name: string;
  email: string;
  commits: number;
}

export interface ActiveFile {
  path: string;
  changes: number;
}

export interface WeeklyActivity {
  week: string;
  commits: number;
}

export interface GitResult {
  total_commits: number;
  commits_per_week: number;
  unique_contributors: number;
  active_days: number;
  top_contributors: Contributor[];
  active_files: ActiveFile[];
  activity_over_time: WeeklyActivity[];
  ci_cd_config: boolean;
  duration_ms: number;
  error?: string | null;
}

// ---------------------------------------------------------------------------
// 建议与报告
// ---------------------------------------------------------------------------

export interface Recommendation {
  priority: number; // 1=高, 2=中, 3=低
  category: string;
  title: string;
  detail: string;
}

export interface ReportJson {
  job_id: string;
  repo_url: string;
  health_score: number;
  static_analysis?: StaticResult | null;
  repo_analysis?: RepoResult | null;
  git_analysis?: GitResult | null;
  recommendations: Recommendation[];
  html_report: string;
  strategy: string;
  total_duration_ms: number;
  created_at: string;
}
