import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { HistoryList } from '../HistoryList';

// Mock the API module
vi.mock('@/lib/api', () => ({
  fetchHistory: vi.fn().mockResolvedValue([]),
}));

describe('HistoryList', () => {
  it('shows empty-state copy when there are no items', async () => {
    render(<HistoryList onSelect={() => undefined} />);
    // The empty state appears after the API call resolves
    expect(
      await screen.findByText('暂无历史记录'),
    ).toBeInTheDocument();
  });
});
