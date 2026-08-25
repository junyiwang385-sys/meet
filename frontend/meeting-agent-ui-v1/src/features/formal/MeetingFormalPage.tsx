import { useQuery } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { Link, useParams } from 'react-router-dom';
import { meetingApi } from '../../api';
import type { Evidence, ExportFormat, MeetingDraftContent, MeetingResultV1 } from '../../api/types';
import { Brand } from '../../components/Brand';
import { Toast } from '../../components/Toast';
import './MeetingFormalPage.css';

function formatTimestamp(milliseconds: number | null): string {
  if (milliseconds === null || !Number.isFinite(milliseconds)) return '—';
  const totalSeconds = Math.max(0, Math.round(milliseconds / 1000));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
  }
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
}

function formatMeetingDay(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleDateString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  });
}

function formatGeneratedAt(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function getErrorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

function FormalPageState({
  title,
  copy,
  action,
}: {
  title: string;
  copy: string;
  action?: ReactNode;
}) {
  return (
    <div className="formal-state-layout">
      <header className="formal-state-bar"><Brand /></header>
      <main className="formal-state-main">
        <div className="formal-state-card">
          <span className="formal-state-mark" />
          <h1>{title}</h1>
          <p>{copy}</p>
          {action ? <div className="formal-state-action">{action}</div> : null}
        </div>
      </main>
    </div>
  );
}

function resultContent(
  title: string,
  result: MeetingResultV1,
): MeetingDraftContent {
  return {
    title,
    speaker_names: Object.fromEntries(
      (result.speakers ?? []).map((speaker) => [speaker.speaker_id, speaker.display_name]),
    ),
    transcript_edits: [],
    minutes: result.minutes,
    chapters: result.chapters ?? [],
    decisions: result.decisions ?? [],
    action_items: result.action_items ?? [],
    review_marks: {},
  };
}

export function MeetingFormalPage() {
  const { meetingId = '' } = useParams();
  const toastTimer = useRef<number | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const detailQuery = useQuery({
    queryKey: ['meeting', meetingId],
    queryFn: () => meetingApi.getMeeting(meetingId),
    enabled: Boolean(meetingId),
  });
  const detail = detailQuery.data;

  const resultQuery = useQuery({
    queryKey: ['meeting-result', meetingId],
    queryFn: () => meetingApi.getMeetingResult(meetingId),
    enabled: Boolean(meetingId && detail?.state === 'finalized'),
    retry: false,
  });

  const draftQuery = useQuery({
    queryKey: ['meeting-draft', meetingId],
    queryFn: () => meetingApi.getMeetingDraft(meetingId),
    enabled: Boolean(meetingId && resultQuery.data),
    retry: false,
  });

  const exportsQuery = useQuery({
    queryKey: ['meeting-exports', meetingId],
    queryFn: () => meetingApi.getMeetingExports(meetingId),
    enabled: Boolean(meetingId && detail?.state === 'finalized'),
    retry: false,
  });

  useEffect(() => () => {
    if (toastTimer.current !== null) window.clearTimeout(toastTimer.current);
  }, []);

  function showToast(message: string) {
    setToast(message);
    if (toastTimer.current !== null) window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), 2400);
  }

  if (detailQuery.isPending) {
    return <FormalPageState title="正在打开正式版本" copy="正在读取会议与导出状态。" />;
  }

  if (detailQuery.isError || !detail) {
    return (
      <FormalPageState
        title="无法打开会议"
        copy={getErrorMessage(detailQuery.error, '会议不存在或暂时无法读取。')}
        action={<Link className="secondary-button compact-button" to="/meetings">返回会议库</Link>}
      />
    );
  }

  if (detail.state !== 'finalized') {
    return (
      <FormalPageState
        title="正式版本尚未生成"
        copy="确认纪要并完成导出后可查看正式版本。"
        action={<Link className="primary-button compact-button" to={`/meetings/${meetingId}/review`}>返回会议工作区</Link>}
      />
    );
  }

  if (resultQuery.isPending || !resultQuery.data) {
    return <FormalPageState title="正在准备正式版本" copy="正在读取会议结果。" />;
  }

  if (resultQuery.isError) {
    return (
      <FormalPageState
        title="正式版本读取失败"
        copy={getErrorMessage(resultQuery.error, '无法读取会议结果。')}
        action={<Link className="secondary-button compact-button" to={`/meetings/${meetingId}/review`}>返回会议工作区</Link>}
      />
    );
  }

  const result = resultQuery.data;
  const content = draftQuery.data?.content ?? resultContent(detail.title, result);
  const evidence = result.evidence ?? [];
  const evidenceById = new Map(evidence.map((item) => [item.evidence_id, item]));
  const speakerNames = new Map((result.speakers ?? []).map((speaker) => [
    speaker.speaker_id,
    content.speaker_names[speaker.speaker_id] ?? speaker.display_name,
  ]));
  const exportItems = exportsQuery.data?.items ?? [];
  const htmlExport = exportItems.find((item) => item.format === 'html');
  const version = draftQuery.data?.revision ?? detail.review.draft_revision ?? 1;
  const generatedAt = htmlExport?.created_at ?? detail.updated_at;

  function evidenceLink(evidenceId: string) {
    const item = evidenceById.get(evidenceId);
    if (!item) return null;
    return `/meetings/${meetingId}/playback?t=${item.start_ms}&segment=${encodeURIComponent(item.segment_id)}`;
  }

  function handleExport(format: ExportFormat) {
    const item = exportItems.find((candidate) => candidate.format === format);
    if (item && item.state !== 'ready') {
      showToast(`${format.toUpperCase()} 正式版本尚未生成`);
      return;
    }
    const url = meetingApi.getMeetingExportUrl(meetingId, format);
    if (url) {
      window.open(url, '_blank', 'noopener');
      return;
    }
    showToast(`${format.toUpperCase()} 正式版本已保存在本地`);
  }

  return (
    <>
      <header className="formal-viewer-bar">
        <Brand />
        <div className="formal-viewer-actions">
          <Link className="formal-bar-button" to={`/meetings/${meetingId}/review`}>返回工作区</Link>
          <button className="formal-bar-button" type="button" onClick={() => handleExport('txt')}>TXT</button>
          <button className="formal-bar-button" type="button" onClick={() => handleExport('json')}>JSON</button>
          <button className="formal-bar-button formal-bar-button-primary" type="button" onClick={() => window.print()}>打印 / PDF</button>
        </div>
      </header>

      <article className="formal-document">
        <div className="formal-document-kicker">已确认 · 正式版本</div>
        <h1>{content.title}</h1>
        <div className="formal-version-line">
          <span>版本 {version}</span>
          <span>{formatGeneratedAt(generatedAt)} 生成</span>
          <span>本地保存</span>
        </div>

        <section className="formal-metadata" aria-label="会议信息">
          <div className="formal-metadata-item"><div className="formal-metadata-label">会议时间</div><div className="formal-metadata-value">{formatMeetingDay(detail.meeting_date)}</div></div>
          <div className="formal-metadata-item"><div className="formal-metadata-label">时长</div><div className="formal-metadata-value mono">{formatTimestamp(result.duration_ms)}</div></div>
          <div className="formal-metadata-item"><div className="formal-metadata-label">来源</div><div className="formal-metadata-value">{detail.source_label}</div></div>
          <div className="formal-metadata-item"><div className="formal-metadata-label">发言人</div><div className="formal-metadata-value">{result.speakers?.length ?? 0} 位</div></div>
        </section>

        <p className="formal-summary">{content.minutes?.overview ?? '会议纪要未提供概览。'}</p>

        <section className="formal-section">
          <div className="formal-section-number">01</div>
          <h2>主要讨论</h2>
          {(content.minutes?.outline ?? []).map((node, index) => (
            <div className="formal-topic" key={node.node_id}>
              <h3>{node.title}</h3>
              <div className="formal-point-list">
                <div className="formal-point">
                  <span className="formal-point-index">{index + 1}</span>
                  <div>
                    <div className="formal-point-copy">{node.text ?? '未提供详细内容。'}</div>
                    <div className="formal-inline-evidence">
                      {node.evidence_ids.map((evidenceId) => {
                        const item = evidenceById.get(evidenceId);
                        const href = evidenceLink(evidenceId);
                        return href && item ? <Link className="formal-evidence-link" to={href} key={evidenceId}>[{formatTimestamp(item.start_ms)}]</Link> : null;
                      })}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          ))}
        </section>

        <section className="formal-section">
          <div className="formal-section-number">02</div>
          <h2>决策</h2>
          <div className="formal-table-wrap">
            <table className="formal-data-table">
              <thead><tr><th>序号</th><th>决策内容</th><th>证据</th></tr></thead>
              <tbody>
                {content.decisions.map((decision, index) => (
                  <tr key={decision.decision_id}>
                    <td>{index + 1}</td>
                    <td>{decision.text}</td>
                    <td>
                      {decision.evidence_ids.map((evidenceId) => {
                        const item = evidenceById.get(evidenceId);
                        const href = evidenceLink(evidenceId);
                        return href && item ? <Link className="formal-evidence-link" to={href} key={evidenceId}>{formatTimestamp(item.start_ms)}</Link> : null;
                      })}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className="formal-section">
          <div className="formal-section-number">03</div>
          <h2>待办</h2>
          <div className="formal-table-wrap">
            <table className="formal-data-table">
              <thead><tr><th>待办事项</th><th>负责人</th><th>截止时间</th><th>证据</th></tr></thead>
              <tbody>
                {content.action_items.map((action) => (
                  <tr key={action.action_id}>
                    <td>{action.text}</td>
                    <td className={action.owner ? '' : 'formal-empty-value'}>{action.owner ?? '未提及'}</td>
                    <td className={action.due_date ? '' : 'formal-empty-value'}>{action.due_date ?? '未提及'}</td>
                    <td>
                      {action.evidence_ids.map((evidenceId) => {
                        const item = evidenceById.get(evidenceId);
                        const href = evidenceLink(evidenceId);
                        return href && item ? <Link className="formal-evidence-link" to={href} key={evidenceId}>{formatTimestamp(item.start_ms)}</Link> : null;
                      })}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className="formal-section">
          <div className="formal-section-number">04</div>
          <h2>证据索引</h2>
          <div className="formal-evidence-list">
            {evidence.map((item: Evidence) => (
              <Link className="formal-evidence" to={`/meetings/${meetingId}/playback?t=${item.start_ms}&segment=${encodeURIComponent(item.segment_id)}`} key={item.evidence_id}>
                <div className="formal-evidence-meta">
                  {formatTimestamp(item.start_ms)}–{formatTimestamp(item.end_ms)}
                  <span className="formal-evidence-speaker">{speakerNames.get(item.speaker_id) ?? item.speaker_id}</span>
                </div>
                <div className="formal-evidence-quote">“{item.quote}”</div>
              </Link>
            ))}
          </div>
        </section>

        <footer className="formal-document-footer">
          <span>极米离线纪要助手 · 本地生成</span>
          <span className="mono">formal-minutes-v1</span>
        </footer>
      </article>
      <Toast message={toast} />
    </>
  );
}
