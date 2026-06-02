import { useMemo, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';

export interface RepoInputProps {
  onSubmit: (input: { repo_url: string }) => void;
  disabled?: boolean;
}

const GITHUB_URL = /^https:\/\/github\.com\/[\w.-]+\/[\w.-]+?(?:\.git)?\/?$/;
const UNIX_PATH = /^\/(?:[^<>:"|?*\r\n\0]+\/?)*$/;
const WINDOWS_PATH = /^[a-zA-Z]:[\\/](?:[^<>:"|?*\r\n]+[\\/]?)*$/;

function isValidInput(value: string): boolean {
  const trimmed = value.trim();
  if (!trimmed) return false;
  return (
    GITHUB_URL.test(trimmed) ||
    UNIX_PATH.test(trimmed) ||
    WINDOWS_PATH.test(trimmed)
  );
}

export function RepoInput({ onSubmit, disabled = false }: RepoInputProps) {
  const [value, setValue] = useState('');

  const isValid = useMemo(() => isValidInput(value), [value]);

  const handleSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!isValid || disabled) return;
    onSubmit({ repo_url: value.trim() });
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>仓库分析</CardTitle>
        <CardDescription>
          输入 GitHub URL 或本地仓库路径，获取代码质量、结构洞察与 Git 活动报告
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-3" noValidate>
          <Input
            value={value}
            placeholder="https://github.com/owner/repo 或 /path/to/repo"
            onChange={(e) => setValue(e.target.value)}
            disabled={disabled}
          />
          <Button
            type="submit"
            disabled={disabled || !isValid}
            className="w-full"
          >
            {disabled ? '分析中…' : '开始分析'}
          </Button>
        </form>
        <p className="mt-2 text-[10px] text-muted-foreground">
          分析包含代码质量（Pylint + Radon）、仓库结构（LLM 推理）、Git 活动三个维度，生成自包含 HTML 报告。
        </p>
      </CardContent>
    </Card>
  );
}
