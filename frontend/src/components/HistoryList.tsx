import { useEffect, useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { fetchHistory } from '@/lib/api';
import type { HistoryItem } from '@/types/contracts';

export interface HistoryListProps {
  onSelect: (jobId: string) => void;
  activeJobId?: string | null;
  refreshToken?: number;
}

const STATUS_COLORS: Record<string, string> = {
  completed: 'text-green-600 bg-green-50',
  failed: 'text-red-600 bg-red-50',
  timeout: 'text-red-600 bg-red-50',
  queued: 'text-blue-600 bg-blue-50',
  cloning: 'text-blue-600 bg-blue-50',
  analyzing: 'text-yellow-600 bg-yellow-50',
  reporting: 'text-yellow-600 bg-yellow-50',
};

const STATUS_LABELS: Record<string, string> = {
  completed: '已完成',
  failed: '失败',
  timeout: '超时',
  queued: '排队中',
  cloning: '克隆中',
  analyzing: '分析中',
  reporting: '报告中',
};

function shortenUrl(url: string, maxLen = 36): string {
  const normalized = url.replace(/\\/g, '/');
  if (normalized.length <= maxLen) return normalized;
  return '…' + normalized.slice(-(maxLen - 1));
}

export function HistoryList({
  onSelect,
  activeJobId,
  refreshToken = 0,
}: HistoryListProps) {
  const [items, setItems] = useState<HistoryItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchHistory()
      .then((data) => {
        if (!cancelled) setItems(data);
      })
      .catch((e) => {
        if (!cancelled)
          setError(e instanceof Error ? e.message : '加载失败');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [refreshToken]);

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-sm">历史记录</CardTitle>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => {
            setLoading(true);
            fetchHistory()
              .then(setItems)
              .catch((e) =>
                setError(e instanceof Error ? e.message : '加载失败'),
              )
              .finally(() => setLoading(false));
          }}
          disabled={loading}
          className="h-7 text-xs"
        >
          {loading ? '加载中' : '刷新'}
        </Button>
      </CardHeader>
      <CardContent className="p-0">
        {error && (
          <p className="px-3 pb-2 text-xs text-destructive">
            加载失败：{error}
          </p>
        )}
        {items.length === 0 && !loading && !error && (
          <p className="px-3 pb-3 text-xs text-muted-foreground">
            暂无历史记录
          </p>
        )}
        <ul className="max-h-[380px] overflow-y-auto">
          {items.map((it) => (
            <li key={it.job_id}>
              <button
                type="button"
                onClick={() => onSelect(it.job_id)}
                className={cn(
                  'block w-full border-t border-border px-3 py-2 text-left transition-colors hover:bg-secondary',
                  activeJobId === it.job_id && 'bg-secondary',
                )}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate text-xs font-medium" title={it.repo_url}>
                    {shortenUrl(it.repo_url)}
                  </span>
                  <span
                    className={cn(
                      'rounded px-1.5 py-0.5 text-[9px] font-semibold',
                      STATUS_COLORS[it.status] || 'text-gray-600 bg-gray-50',
                    )}
                  >
                    {STATUS_LABELS[it.status] || it.status}
                  </span>
                </div>
                <div className="mt-1 flex items-center justify-between text-[10px] text-muted-foreground">
                  <span>{it.created_at}</span>
                  {it.health_score != null && (
                    <span>健康度: {it.health_score}</span>
                  )}
                </div>
              </button>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
