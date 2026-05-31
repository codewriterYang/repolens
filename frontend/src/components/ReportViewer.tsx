import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useCallback, useRef, useState } from 'react';
import type { ReportJson } from '@/types/contracts';

export interface ReportViewerProps {
  report: ReportJson;
}

function scoreColor(score: number): string {
  if (score >= 70) return 'text-green-600';
  if (score >= 40) return 'text-yellow-600';
  return 'text-red-600';
}

export function ReportViewer({ report }: ReportViewerProps) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [iframeHeight, setIframeHeight] = useState(800);

  const hasData =
    (report.static_analysis && !report.static_analysis.error) ||
    (report.repo_analysis && !report.repo_analysis.error) ||
    (report.git_analysis && !report.git_analysis.error);

  // iframe 加载后测量内容实际高度
  const onIframeLoad = useCallback(() => {
    try {
      const doc = iframeRef.current?.contentDocument;
      if (doc) {
        const h = doc.documentElement.scrollHeight;
        if (h > 0) setIframeHeight(h + 16);
      }
    } catch {
      // 被 sandbox 限制时保留默认高度
    }
  }, []);

  return (
    <div className="space-y-6">
      {/* 健康评分摘要 */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            <span>分析报告</span>
            <span className={`rounded-full px-3 py-1 text-xs font-semibold bg-primary/10 ${scoreColor(report.health_score)}`}>
              健康度 {report.health_score}
            </span>
          </CardTitle>
          <p className="text-xs text-muted-foreground">
            {report.repo_url} · 总耗时: {(report.total_duration_ms / 1000).toFixed(1)} s
          </p>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
            {report.static_analysis && !report.static_analysis.error && (
              <div className="rounded border p-2">
                <p className="text-muted-foreground text-xs">扫描文件</p>
                <p className="text-lg font-bold">
                  {report.static_analysis.total_files_scanned}
                </p>
              </div>
            )}
            {report.repo_analysis && !report.repo_analysis.error && (
              <div className="rounded border p-2">
                <p className="text-muted-foreground text-xs">README 质量</p>
                <p className="text-lg font-bold">
                  {report.repo_analysis.readme_quality_score}/100
                </p>
              </div>
            )}
            {report.git_analysis && !report.git_analysis.error && (
              <>
                <div className="rounded border p-2">
                  <p className="text-muted-foreground text-xs">总提交</p>
                  <p className="text-lg font-bold">
                    {report.git_analysis.total_commits}
                  </p>
                </div>
                <div className="rounded border p-2">
                  <p className="text-muted-foreground text-xs">贡献者</p>
                  <p className="text-lg font-bold">
                    {report.git_analysis.unique_contributors}
                  </p>
                </div>
              </>
            )}
          </div>
        </CardContent>
      </Card>

      {/* 建议列表 */}
      {report.recommendations.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>改进建议 ({report.recommendations.length} 条)</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {report.recommendations.map((rec, idx) => (
              <div
                key={`${rec.title}-${idx}`}
                className={`rounded border-l-4 p-3 text-sm ${
                  rec.priority === 1
                    ? 'border-red-500 bg-red-50'
                    : rec.priority === 2
                      ? 'border-yellow-500 bg-yellow-50'
                      : 'border-blue-500 bg-blue-50'
                }`}
              >
                <div className="font-medium">
                  [{rec.category}] {rec.title}
                </div>
                <p className="mt-1 text-muted-foreground text-xs">{rec.detail}</p>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {/* 无数据状态 */}
      {!hasData && !report.html_report && (
        <Card>
          <CardContent className="py-8 text-center">
            <p className="text-muted-foreground">
              {report.health_score === 0
                ? '所有分析器均未能产出结果，请检查仓库是否可访问。'
                : '分析完成，详细报告见下方。'}
            </p>
          </CardContent>
        </Card>
      )}

      {/* HTML 报告 — 通过 iframe 渲染以保留交互 JS */}
      {report.html_report && (
        <Card>
          <CardHeader>
            <CardTitle>完整报告</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <iframe
              ref={iframeRef}
              srcDoc={report.html_report}
              sandbox="allow-scripts allow-same-origin"
              onLoad={onIframeLoad}
              scrolling="no"
              style={{
                width: '100%',
                height: `${iframeHeight}px`,
                border: 'none',
                display: 'block',
                overflow: 'hidden',
              }}
              title="RepoLens 分析报告"
            />
          </CardContent>
        </Card>
      )}
    </div>
  );
}
