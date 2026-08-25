import { useQuery } from '@tanstack/react-query';
import type { PropsWithChildren, ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { meetingApi } from '../../api';
import type { MeetingListItem } from '../../api/types';
import { Brand } from '../../components/Brand';
import './StagePageShell.css';

interface StagePageShellProps extends PropsWithChildren {
  className: string;
  activeLabel: string;
  activeValue: string;
  breadcrumbs: string[];
  topActions?: ReactNode;
  inspectorTitle: string;
  inspector: ReactNode;
}

function formatDuration(milliseconds: number | null): string {
  if (milliseconds === null || !Number.isFinite(milliseconds)) return '处理中';
  const totalSeconds = Math.max(0, Math.round(milliseconds / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
}

function formatMeetingDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' });
}

function meetingPath(meeting: MeetingListItem): string {
  if (meeting.state === 'review_ready' || meeting.state === 'finalized') {
    return `/meetings/${meeting.meeting_id}/review`;
  }
  return `/meetings/${meeting.meeting_id}/processing`;
}

export function StagePageShell({
  className,
  activeLabel,
  activeValue,
  breadcrumbs,
  topActions,
  inspectorTitle,
  inspector,
  children,
}: StagePageShellProps) {
  const recentMeetingsQuery = useQuery({
    queryKey: ['meetings', 'recent'],
    queryFn: () => meetingApi.listMeetings({ sort: 'updated_desc' }),
    staleTime: 5000,
  });
  const recentMeetings = recentMeetingsQuery.data?.items.slice(0, 3) ?? [];

  return (
    <div className={`stage-shell ${className}`}>
      <aside className="stage-sidebar">
        <Brand />
        <nav className="stage-side-nav" aria-label="主导航">
          <Link className="stage-side-link" to="/meetings">
            <span>会议库</span><span aria-hidden="true">›</span>
          </Link>
          <div className="stage-side-link stage-side-link-active" aria-current="page">
            <span>{activeLabel}</span><span>{activeValue}</span>
          </div>
        </nav>
        <div className="stage-list-label">最近会议</div>
        <div className="stage-meeting-list">
          {recentMeetings.length > 0 ? recentMeetings.map((meeting) => (
            <Link className="stage-meeting-item" to={meetingPath(meeting)} key={meeting.meeting_id}>
              <span className="stage-meeting-name">{meeting.title}</span>
              <span className="stage-meeting-meta">
                <span>{formatDuration(meeting.audio.duration_ms)}</span>
                <span>{formatMeetingDate(meeting.updated_at)}</span>
              </span>
            </Link>
          )) : (
            <span className="stage-meeting-empty">暂无会议</span>
          )}
        </div>
        <div className="stage-sidebar-foot">
          <span className="stage-live-dot" aria-hidden="true" />
          <span>本地通道已连接</span>
        </div>
      </aside>

      <main className="stage-main">
        <header className="stage-topbar">
          <div className="stage-crumb">
            {breadcrumbs.map((item, index) => (
              <span key={`${item}-${index}`}>
                {index > 0 ? <span className="stage-crumb-separator">/</span> : null}
                {index === breadcrumbs.length - 1 ? <strong>{item}</strong> : item}
              </span>
            ))}
          </div>
          <div className="stage-top-actions">{topActions}</div>
        </header>
        <div className="stage-content">{children}</div>
      </main>

      <aside className="stage-inspector">
        <div className="stage-inspector-head">
          <div className="stage-inspector-title">{inspectorTitle}</div>
        </div>
        <div className="stage-inspector-body">{inspector}</div>
      </aside>
    </div>
  );
}
