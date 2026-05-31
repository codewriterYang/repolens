import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { RepoInput } from '../RepoInput';

describe('RepoInput', () => {
  it('shows the submit button disabled when input is empty', () => {
    render(<RepoInput onSubmit={() => undefined} />);
    expect(screen.getByRole('button', { name: /开始分析/ })).toBeDisabled();
  });

  it('enables submit when a valid GitHub URL is entered', () => {
    render(<RepoInput onSubmit={() => undefined} />);
    const input = screen.getByPlaceholderText(/https:\/\/github\.com\/owner\/repo/);
    fireEvent.change(input, {
      target: { value: 'https://github.com/foo/bar' },
    });
    expect(
      screen.getByRole('button', { name: /开始分析/ }),
    ).not.toBeDisabled();
  });

  it('calls onSubmit with repo_url when valid GitHub URL is submitted', () => {
    const onSubmit = vi.fn();
    render(<RepoInput onSubmit={onSubmit} />);

    const input = screen.getByPlaceholderText(/https:\/\/github\.com\/owner\/repo/);
    fireEvent.change(input, {
      target: { value: 'https://github.com/foo/bar' },
    });

    fireEvent.click(screen.getByRole('button', { name: /开始分析/ }));
    expect(onSubmit).toHaveBeenCalledWith({
      repo_url: 'https://github.com/foo/bar',
    });
  });

  it('calls onSubmit with local path when a valid path is entered', () => {
    const onSubmit = vi.fn();
    render(<RepoInput onSubmit={onSubmit} />);

    const input = screen.getByPlaceholderText(/https:\/\/github\.com\/owner\/repo/);
    fireEvent.change(input, {
      target: { value: '/home/user/repo' },
    });

    fireEvent.click(screen.getByRole('button', { name: /开始分析/ }));
    expect(onSubmit).toHaveBeenCalledWith({
      repo_url: '/home/user/repo',
    });
  });

  it('disables submit button while disabled prop is true', () => {
    render(<RepoInput onSubmit={() => undefined} disabled />);
    const input = screen.getByPlaceholderText(/https:\/\/github\.com\/owner\/repo/);
    fireEvent.change(input, {
      target: { value: 'https://github.com/foo/bar' },
    });
    expect(screen.getByRole('button', { name: /分析中…/ })).toBeDisabled();
  });
});
