import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { meetingApi } from '../../api';
import {
  formatDuration,
  formatMeetingDate,
  meetingFilterLabels,
  meetingStatusForFilter,
} from '../../api/meeting-api';
import type { MeetingFilter, MeetingListItem } from '../../api/types';
import { Brand } from '../../components/Brand';
import { NewMeetingPopover } from '../../components/NewMeetingPopover';
import { PageState } from '../../components/PageState';
import { SearchIcon } from '../../components/Icons';
import { Toast } from '../../components/Toast';
import './MeetingLibraryPage.css';

const filters = Object.keys(meetingFilterLabels) as MeetingFilter[];

function useDebouncedValue<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delay);
    return () => window.clearTimeout(timer);
  }, [delay, value]);
  return debounced;
}

function meetingStatusCopy(meeting: MeetingListItem): string {
  if (meeting.state === 'failed') return meeting.availability.transcript ? '纪要生成未完成' : '转写未完成';
  if (meeting.state === 'review_ready') {
    return meeting.review.pending_count > 0 ? `待核对 · ${meeting.review.pending_count} 条` : '待核对';
  }
  if (meeting.state === 'finalized' && meeting.audio.state === 'deleted') return '已确认 · 音频已删除';
  if (meeting.state === 'finalized') return '已确认';
  if (meeting.state === 'cancelled') return '已取消';
  if (meeting.state === 'created') return '等待音频';
  const phaseCopy: Record<string, string> = {
    recording: '正在录音',
    uploading: '正在传输音频',
    converting: '正在转换音频',
    transcribing: '正在识别与转写',
    synthesizing: '正在生成纪要',
    exporting: '正在生成正式版本',
  };
  return `${phaseCopy[meeting.phase] ?? '处理中'} · ${meeting.progress.percent}%`;
}

function meetingTarget(meeting: MeetingListItem): string {
  if (['created', 'recording', 'uploading', 'processing', 'finalizing', 'failed'].includes(meeting.state)) {
    return `/meetings/${meeting.meeting_id}/processing`;
  }
  return `/meetings/${meeting.meeting_id}/review`;
}

export function MeetingLibraryPage() {
  const navigate = useNavigate();
  const [activeFilter, setActiveFilter] = useState<MeetingFilter>('all');
  const [query, setQuery] = useState('');
  const [popoverOpen, setPopoverOpen] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const debouncedQuery = useDebouncedValue(query, 220);

  const meetingsQuery = useQuery({
    queryKey: ['meetings', activeFilter, debouncedQuery],
    queryFn: () => meetingApi.listMeetings({ q: debouncedQuery, status: activeFilter, sort: 'updated_desc' }),
    placeholderData: keepPreviousData,
  });

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(null), 2400);
    return () => window.clearTimeout(timer);
  }, [toast]);

  const response = meetingsQuery.data;
  const items = response?.items ?? [];
  const facets = response?.facets ?? {
    all: 0,
    processing: 0,
    failed: 0,
    review: 0,
    confirmed: 0,
    deleted: 0,
  };

  return (
    <div className="library-shell">
      <aside className="library-sidebar">
        <Brand />
        <div className="sidebar-label">会议状态</div>
        <nav className="filter-nav" aria-label="会议筛选">
          {filters.map((filter) => (
            <button
              key={filter}
              className={activeFilter === filter ? 'filter-button filter-button-active' : 'filter-button'}
              type="button"
              onClick={() => setActiveFilter(filter)}
            >
              <span>{meetingFilterLabels[filter]}</span>
              <span className="filter-count">{facets[filter]}</span>
            </button>
          ))}
        </nav>
        <div className="sidebar-footer">
          <span className="connection-dot" />
          <span>本地通道已连接</span>
          <Link to="/settings">设置</Link>
        </div>
      </aside>

      <main className="library-main">
        <header className="library-topbar">
          <div className="breadcrumb"><span>会议库</span><span>/</span><strong>全部会议</strong></div>
          <div className="new-meeting-wrap">
            <button
              className="primary-button compact-button"
              type="button"
              aria-expanded={popoverOpen}
              onClick={() => setPopoverOpen((open) => !open)}
            >
              <span aria-hidden="true">＋</span> 新建会议
            </button>
            <NewMeetingPopover
              open={popoverOpen}
              onClose={() => setPopoverOpen(false)}
              onInvalidFile={setToast}
            />
          </div>
        </header>

        <div className="library-content">
          <div className="page-heading-row">
            <div>
              <div className="eyebrow">会议库</div>
              <h1>全部会议</h1>
            </div>
            <span className="visible-count">{response?.total ?? 0} 个会议</span>
          </div>

          <div className="library-toolbar">
            <label className="search-field">
              <SearchIcon />
              <input
                type="search"
                value={query}
                placeholder="搜索会议名称"
                onChange={(event) => setQuery(event.target.value)}
              />
            </label>
            <span className="sort-label">最近更新</span>
          </div>

          {meetingsQuery.isError ? (
            <PageState
              title="会议库读取失败"
              copy={meetingsQuery.error instanceof Error ? meetingsQuery.error.message : '请检查本地服务连接'}
              action={<button className="secondary-button" type="button" onClick={() => meetingsQuery.refetch()}>重新读取</button>}
            />
          ) : meetingsQuery.isPending ? (
            <div className="meeting-list-loading" aria-label="正在读取会议库">
              <span />
              <span />
              <span />
            </div>
          ) : items.length === 0 ? (
            <PageState
              title={query ? '没有找到匹配的会议' : '此状态下没有会议'}
              copy={query ? `未找到包含“${query}”的会议` : undefined}
              action={
                query ? (
                  <button className="secondary-button" type="button" onClick={() => setQuery('')}>清除搜索</button>
                ) : activeFilter !== 'all' ? (
                  <button className="secondary-button" type="button" onClick={() => setActiveFilter('all')}>查看全部会议</button>
                ) : (
                  <button className="primary-button" type="button" onClick={() => setPopoverOpen(true)}>新建会议</button>
                )
              }
            />
          ) : (
            <>
              <div className="meeting-list-head" aria-hidden="true">
                <span>会议</span><span>日期</span><span>时长</span><span>来源</span><span>音频</span>
              </div>
              <div className="meeting-list">
                {items.map((meeting) => {
                  const status = meetingStatusForFilter(meeting.state, meeting.audio.state);
                  return (
                    <button
                      key={meeting.meeting_id}
                      className="meeting-row"
                      data-status={status}
                      type="button"
                      onClick={() => navigate(meetingTarget(meeting))}
                    >
                      <span className="meeting-primary">
                        <span className="meeting-name">{meeting.title}</span>
                        <span className="meeting-subline">
                          <span className="meeting-status-dot" />
                          <span>{meetingStatusCopy(meeting)}</span>
                        </span>
                        {status === 'processing' ? (
                          <span className="mini-progress" aria-hidden="true">
                            <span style={{ width: `${meeting.progress.percent}%` }} />
                          </span>
                        ) : null}
                      </span>
                      <span className="meeting-cell">{formatMeetingDate(meeting.meeting_date)}</span>
                      <span className="meeting-cell mono">{formatDuration(meeting.audio.duration_ms)}</span>
                      <span className="meeting-cell meeting-cell-muted">{meeting.source_label}</span>
                      <span className="meeting-cell meeting-cell-muted">
                        {meeting.audio.state === 'deleted' ? '已删除' : meeting.audio.state === 'available' ? '可用' : '处理中'}
                      </span>
                    </button>
                  );
                })}
              </div>
            </>
          )}
        </div>
      </main>
      <Toast message={toast} />
    </div>
  );
}
