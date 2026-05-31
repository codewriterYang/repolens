import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

export interface ProgressPanelProps {
  jobId: string;
  progressPct: number;
  stageLabel: string;
}

export function ProgressPanel({
  jobId,
  progressPct,
  stageLabel,
}: ProgressPanelProps) {
  const stageText = stageLabel || (progressPct < 100 ? '分析中...' : '分析完成');

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center justify-between">
          <span>分析进度</span>
          <span className="text-xs font-normal text-muted-foreground">
            {progressPct}%
          </span>
        </CardTitle>
        <p className="truncate text-xs text-muted-foreground" title={jobId}>
          Job: {jobId}
        </p>
      </CardHeader>
      <CardContent>
        <div className="w-full rounded-full bg-secondary h-2.5 mb-2">
          <div
            className="h-2.5 rounded-full bg-primary transition-all duration-500"
            style={{ width: `${Math.min(100, Math.max(0, progressPct))}%` }}
          />
        </div>
        <p className="text-xs text-muted-foreground text-center">{stageText}</p>
      </CardContent>
    </Card>
  );
}
