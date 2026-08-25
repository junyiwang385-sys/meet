import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { meetingApi, runtimeInfo } from '../../api';
import { formatDuration } from '../../api/meeting-api';
import type { FileHealthState, MeetingDetail, MeetingListItem, RetryMeetingScope } from '../../api/types';
import { Brand } from '../../components/Brand';
import { Toast } from '../../components/Toast';
import './ResultUnavailablePage.css';

const healthCopy: Record<FileHealthState, { label: string; tone: 'available' | 'unavailable' | 'neutral' }> = {
  available: { label: '可用', tone: 'available' },
  partial: { label: '部分可用', tone: 'neutral' },
  not_created: { label: '未生成', tone: 'neutral' },
  missing: { label: '未找到', tone: 'unavailable' },
  invalid: { label: '文件损坏', tone: 'unavailable' },
  unreadable: { label: '不可读取', tone: 'unavailable' },
  deleted: { label: '已删除', tone: 'unavailable' },
};

function meetingTarget(meeting: MeetingListItem | MeetingDetail) {
  if (['created', 'recording', 'uploading', 'processing', 'finalizing', 'failed'].includes(meeting.state)) {
    return `/meetings/${meeting.meeting_id}/processing`;
  }
  if (meeting.state === 'finalized') return `/meetings/${meeting.meeting_id}/formal`;
  return `/meetings/${meeting.meeting_id}/review`;
}

function fullDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

export function ResultUnavailablePage() {
  const { meetingId = '' } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const toastTimerRef = useRef<number | null>(null);
  const [checkedCopy, setCheckedCopy] = useState('刚刚检查');
  const [removeDialogOpen, setRemoveDialogOpen] = useState(false);
  const [removed, setRemoved] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  const detailQuery = useQuery({
    queryKey: ['meeting', meetingId],
    queryFn: () => meetingApi.getMeeting(meetingId),
    enabled: Boolean(meetingId),
    retry: false,
  });

  const meetingsQuery = useQuery({
    queryKey: ['meetings', 'result-unavailable-recent'],
    queryFn: () => meetingApi.listMeetings({ sort: 'updated_desc' }),
  });

  useEffect(() => () => {
    if (toastTimerRef.current !== null) window.clearTimeout(toastTimerRef.current);
  }, []);

  function showToast(message: string) {
    setToast(message);
    if (toastTimerRef.current !== null) window.clearTimeout(toastTimerRef.current);
    toastTimerRef.current = window.setTimeout(() => setToast(null), 2300);
  }

  const rescanMutation = useMutation({
    mutationFn: () => meetingApi.rescanMeeting(meetingId),
    onMutate: () => setCheckedCopy('正在检查'),
    onSuccess: (response) => {
      setCheckedCopy('刚刚重新检查');
      queryClient.setQueryData<MeetingDetail>(['meeting', meetingId], (current) => current ? {
        ...current,
        file_health: response.file_health,
        capabilities: { ...current.capabilities, ...response.capabilities },
      } : current);
      if (response.file_health.result === 'available' || response.file_health.result === 'partial') {
        const detail = detailQuery.data;
        navigate(detail ? meetingTarget(detail) : `/meetings/${meetingId}/processing`, { replace: true });
        return;
      }
      showToast(runtimeInfo.apiMode === 'mock' ? 'Mock 文件状态没有变化' : '文件状态没有变化');
    },
    onError: (error) => {
      setCheckedCopy('检查失败');
      showToast(error instanceof Error ? error.message : '重新读取文件失败');
    },
  });

  const retryMutation = useMutation({
    mutationFn: (scope: RetryMeetingScope) => meetingApi.retryMeeting(meetingId, scope),
    onSuccess: () => {
      queryClient.removeQueries({ queryKey: ['meeting', meetingId], exact: true });
      queryClient.removeQueries({ queryKey: ['meeting-result', meetingId], exact: true });
      navigate(`/meetings/${meetingId}/processing`, { replace: true });
    },
  });

  const revealMutation = useMutation({
    mutationFn: () => meetingApi.revealMeeting(meetingId, 'meeting_dir'),
    onSuccess: () => showToast(runtimeInfo.apiMode === 'mock' ? 'Mock 目录操作已完成' : '已打开会议目录'),
    onError: (error) => showToast(error instanceof Error ? error.message : '无法打开会议目录'),
  });

  const removeMutation = useMutation({
    mutationFn: () => meetingApi.removeMeetingIndex(meetingId),
    onSuccess: () => {
      setRemoveDialogOpen(false);
      setRemoved(true);
      void queryClient.invalidateQueries({ queryKey: ['meetings'] });
      showToast(runtimeInfo.apiMode === 'mock' ? 'Mock 会议记录已移出，文件未删除' : '会议记录已移出，文件未删除');
    },
  });

  const detail = detailQuery.data;
  const formalUrl = useMemo(() => meetingId ? meetingApi.getMeetingExportUrl(meetingId, 'html') : null, [meetingId]);

  useEffect(() => {
    if (!detail || removed) return;
    if (detail.file_health.result === 'available' || detail.file_health.result === 'partial') {
      navigate(meetingTarget(detail), { replace: true });
    }
  }, [detail, navigate, removed]);

  if (detailQuery.isError) {
    return <div className="result-unavailable-page-state"><Brand /><strong>无法读取会议记录</strong><Link to="/meetings">返回会议库</Link></div>;
  }

  if (detailQuery.isPending || !detail) {
    return <div className="result-unavailable-page-state"><Brand /><span>正在读取会议文件状态</span></div>;
  }

  const resultHealth = detail.file_health.result;
  const sourceHealth = detail.file_health.source_audio;
  const sourceAvailable = sourceHealth === 'available';
  const formalAvailable = [detail.file_health.formal_html, detail.file_health.formal_txt, detail.file_health.formal_json].includes('available');
  const canRetry = sourceAvailable && detail.capabilities.can_retry_all;
  const retryScope: RetryMeetingScope = detail.capabilities.can_retry_summary && detail.availability.transcript ? 'summary' : 'all';
  const noRecoverySource = !sourceAvailable;

  let pageTitle = '会议结果不可用';
  let pageContext = resultHealth === 'unreadable' ? '会议结果文件不可读取' : resultHealth === 'invalid' ? '会议结果文件无法读取' : '未找到会议结果文件';
  let panelTitle = resultHealth === 'unreadable' ? 'result.json 不可读取' : resultHealth === 'invalid' ? 'result.json 无法读取' : '未找到 result.json';
  let panelCopy = sourceAvailable ? '原始音频仍可用，可以重新处理生成会议结果' : '可以检查会议目录，或将无效记录移出会议库';
  let panelCode = resultHealth === 'unreadable' ? 'RESULT_UNREADABLE' : resultHealth === 'invalid' ? 'RESULT_INVALID' : 'RESULT_MISSING';

  if (formalAvailable) {
    pageTitle = '仅正式版本可用';
    pageContext = '编辑数据不可用，已确认版本仍可查看';
    panelTitle = 'result.json 无法读取';
    panelCopy = '已确认的正式版本仍保留在本地';
    panelCode = 'FORMAL_VERSION_ONLY';
  } else if (noRecoverySource) {
    pageTitle = '会议内容无法恢复';
    pageContext = '结果文件和原始音频均不可用';
    panelTitle = '缺少可恢复的会议文件';
    panelCode = 'SOURCE_AND_RESULT_MISSING';
  }

  if (removed) {
    pageTitle = '记录已移出会议库';
    pageContext = '本地会议目录继续保留';
  }

  const fileRows = [
    { name: 'metadata.json', use: '会议名称、日期和来源', health: detail.file_health.metadata },
    { name: detail.source.original_name ?? 'source audio', use: '原始会议音频', health: sourceHealth },
    { name: 'result.json', use: '全文、章节、决策和待办', health: resultHealth },
    { name: 'draft.json', use: '人工核对草稿', health: detail.file_health.draft },
    { name: 'exports/formal_minutes.html', use: '正式 HTML 版本', health: detail.file_health.formal_html },
    { name: 'exports/formal_minutes.txt', use: '正式 TXT 版本', health: detail.file_health.formal_txt },
    { name: 'exports/formal_minutes.json', use: '正式 JSON 版本', health: detail.file_health.formal_json },
  ];

  const recentMeetings = (meetingsQuery.data?.items ?? []).filter((meeting) => meeting.meeting_id !== meetingId).slice(0, 2);

  return (
    <>
      <div className="result-unavailable-layout">
        <aside className="result-unavailable-sidebar">
          <Brand />
          <label className="result-unavailable-search-wrap"><span className="result-unavailable-search"><span aria-hidden="true">⌕</span><input type="search" placeholder="搜索会议" disabled /></span></label>
          <div className="result-unavailable-list-label">最近会议</div>
          <nav className="result-unavailable-meeting-list" aria-label="最近会议">
            <div className="result-unavailable-meeting-item result-unavailable-meeting-item-active"><span className="result-unavailable-meeting-name">{detail.title}</span><span className="result-unavailable-meeting-meta"><span>{formatDuration(detail.audio.duration_ms)}</span><span>{fullDate(detail.meeting_date).slice(5)}</span></span></div>
            {recentMeetings.map((meeting) => <Link className="result-unavailable-meeting-item" to={meetingTarget(meeting)} key={meeting.meeting_id}><span className="result-unavailable-meeting-name">{meeting.title}</span><span className="result-unavailable-meeting-meta"><span>{formatDuration(meeting.audio.duration_ms)}</span><span>{fullDate(meeting.meeting_date).slice(5)}</span></span></Link>)}
          </nav>
          <div className={`result-unavailable-sidebar-foot ${removed ? 'result-unavailable-sidebar-foot-retained' : ''}`}><span className="result-unavailable-status-dot" /><span>{removed ? '本地文件已保留' : '会议结果不可用'}</span></div>
        </aside>

        <main className="result-unavailable-main">
          <header className="result-unavailable-topbar">
            <div className="result-unavailable-crumb">会议库 <span>/</span> <strong>结果不可用</strong></div>
            <div className="result-unavailable-top-actions"><button className="result-unavailable-top-button" type="button" disabled={revealMutation.isPending} onClick={() => revealMutation.mutate()}>{revealMutation.isPending ? '正在打开' : '打开会议目录'}</button><Link className="result-unavailable-top-button" to="/meetings">返回会议库</Link></div>
          </header>

          <div className="result-unavailable-content">
            <div className="result-unavailable-eyebrow">文件状态</div>
            <h1>{pageTitle}</h1>
            <div className={`result-unavailable-context ${removed ? 'result-unavailable-context-recovered' : ''}`}><span />{pageContext}</div>

            <section className="result-unavailable-summary">
              <div className="result-unavailable-summary-cell"><span>会议</span><strong>{detail.title}</strong></div>
              <div className="result-unavailable-summary-cell"><span>日期</span><strong>{fullDate(detail.meeting_date)}</strong></div>
              <div className="result-unavailable-summary-cell"><span>时长</span><strong className="mono">{formatDuration(detail.audio.duration_ms)}</strong></div>
              <div className="result-unavailable-summary-cell"><span>来源</span><strong>{detail.source_label}</strong></div>
            </section>

            <section className="result-unavailable-panel" aria-labelledby="resultUnavailableTitle">
              <div className="result-unavailable-panel-head"><div><h2 id="resultUnavailableTitle">{panelTitle}</h2><p>{panelCopy}</p></div><code>{panelCode}</code></div>
              <div className="result-unavailable-panel-actions">
                <button className="result-unavailable-action" type="button" disabled={removed || rescanMutation.isPending} onClick={() => rescanMutation.mutate()}>{rescanMutation.isPending ? '读取中' : '重新读取文件'}</button>
                {formalAvailable ? (
                  formalUrl ? <a className="result-unavailable-action result-unavailable-action-primary" href={formalUrl} target="_blank" rel="noreferrer">查看正式版本</a> : <button className="result-unavailable-action result-unavailable-action-primary" type="button" onClick={() => showToast('Mock 正式 HTML 版本已保留')}>查看正式版本</button>
                ) : (
                  <button className="result-unavailable-action result-unavailable-action-primary" type="button" disabled={removed || !canRetry || retryMutation.isPending} onClick={() => retryMutation.mutate(retryScope)}>{retryMutation.isPending ? '正在提交' : canRetry ? '重新处理原始音频' : '无法重新处理'}</button>
                )}
              </div>
              {retryMutation.isError ? <div className="result-unavailable-action-error" role="alert">{retryMutation.error instanceof Error ? retryMutation.error.message : '重新处理失败'}</div> : null}
              {detail.capabilities.can_remove_index ? <button className="result-unavailable-remove" type="button" disabled={removed} onClick={() => setRemoveDialogOpen(true)}>{removed ? '已移出会议库' : '从会议库移除此记录'}</button> : null}
            </section>

            <section className="result-unavailable-files" aria-labelledby="localFilesTitle">
              <div className="result-unavailable-section-head"><h2 id="localFilesTitle">本地文件</h2><span>{checkedCopy}</span></div>
              {fileRows.map((file) => {
                const health = healthCopy[file.health];
                return <div className="result-unavailable-file-row" key={file.name}><span className="result-unavailable-file-name">{file.name}</span><span className="result-unavailable-file-use">{file.use}</span><strong className={`result-unavailable-file-state result-unavailable-file-state-${health.tone}`}>{health.label}</strong></div>;
              })}
            </section>
          </div>
        </main>

        <aside className="result-unavailable-inspector">
          <div className="result-unavailable-inspector-head"><div>恢复条件</div></div>
          <div className="result-unavailable-inspector-body">
            <div className="result-unavailable-detail-group">
              <div className="result-unavailable-detail-row"><span>会议记录</span><strong className="result-unavailable-available">{removed ? '已移出索引' : '存在'}</strong></div>
              <div className="result-unavailable-detail-row"><span>原始音频</span><strong className={sourceAvailable ? 'result-unavailable-available' : 'result-unavailable-unavailable'}>{sourceAvailable ? '可用' : '不可用'}</strong></div>
              <div className="result-unavailable-detail-row"><span>会议结果</span><strong className="result-unavailable-unavailable">不可用</strong></div>
              <div className="result-unavailable-detail-row"><span>正式版本</span><strong className={formalAvailable ? 'result-unavailable-available' : ''}>{formalAvailable ? '可用' : '未生成'}</strong></div>
            </div>
            <div className="result-unavailable-path-block"><span>会议 ID</span><strong>{detail.meeting_id}</strong></div>
            <button className="result-unavailable-inspector-button" type="button" disabled={revealMutation.isPending} onClick={() => revealMutation.mutate()}>打开本地目录</button>
          </div>
        </aside>
      </div>

      {removeDialogOpen ? (
        <div className="result-unavailable-dialog-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setRemoveDialogOpen(false); }}>
          <section className="result-unavailable-dialog" role="dialog" aria-modal="true" aria-labelledby="removeMeetingIndexTitle">
            <h2 id="removeMeetingIndexTitle">从会议库移除此记录？</h2>
            <p>只移除会议库索引，本地会议目录和其中的文件继续保留。</p>
            <div className="result-unavailable-dialog-id">{detail.meeting_id}</div>
            {removeMutation.isError ? <div className="result-unavailable-dialog-error">{removeMutation.error instanceof Error ? removeMutation.error.message : '移除失败'}</div> : null}
            <div className="result-unavailable-dialog-actions"><button type="button" onClick={() => setRemoveDialogOpen(false)}>取消</button><button className="result-unavailable-dialog-danger" type="button" disabled={removeMutation.isPending} onClick={() => removeMutation.mutate()}>{removeMutation.isPending ? '正在移除' : '确认移除'}</button></div>
          </section>
        </div>
      ) : null}

      <Toast message={toast} />
    </>
  );
}
