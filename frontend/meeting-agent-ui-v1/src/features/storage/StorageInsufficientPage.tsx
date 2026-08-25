import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { meetingApi, runtimeInfo } from '../../api';
import { formatDuration, formatMeetingDate, getStorageInsufficientDetails } from '../../api/meeting-api';
import type { MeetingListItem, StorageMeetingItem } from '../../api/types';
import { useUploadDraft } from '../../app/upload-draft';
import { Brand } from '../../components/Brand';
import { Toast } from '../../components/Toast';
import './StorageInsufficientPage.css';

function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined || !Number.isFinite(bytes)) return '—';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let value = Math.max(0, bytes);
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(value >= 100 || unit === 0 ? 0 : 1)} ${units[unit]}`;
}

function meetingTarget(meeting: MeetingListItem): string {
  if (['review_ready', 'finalizing', 'finalized'].includes(meeting.state)) {
    return `/meetings/${meeting.meeting_id}/review`;
  }
  return `/meetings/${meeting.meeting_id}/processing`;
}

export function StorageInsufficientPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const toastTimerRef = useRef<number | null>(null);
  const { file, setFile, storageIssue, setStorageIssue } = useUploadDraft();
  const [search, setSearch] = useState('');
  const [releasedBytes, setReleasedBytes] = useState(0);
  const [deleteTarget, setDeleteTarget] = useState<StorageMeetingItem | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const storageQuery = useQuery({
    queryKey: ['storage', 'summary'],
    queryFn: () => meetingApi.getStorageSummary(),
  });

  const storageMeetingsQuery = useQuery({
    queryKey: ['storage', 'meetings'],
    queryFn: () => meetingApi.listStorageMeetings(),
  });

  const recentMeetingsQuery = useQuery({
    queryKey: ['meetings', 'storage-insufficient-recent'],
    queryFn: () => meetingApi.listMeetings({ sort: 'updated_desc' }),
  });

  useEffect(() => () => {
    if (toastTimerRef.current !== null) window.clearTimeout(toastTimerRef.current);
  }, []);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setDeleteTarget(null);
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, []);

  function showToast(message: string) {
    setToast(message);
    if (toastTimerRef.current !== null) window.clearTimeout(toastTimerRef.current);
    toastTimerRef.current = window.setTimeout(() => setToast(null), 2400);
  }

  const deleteAudioMutation = useMutation({
    mutationFn: async (meeting: StorageMeetingItem) => ({
      meeting,
      result: await meetingApi.deleteMeetingAudio(meeting.meeting_id, '删除音频'),
    }),
    onMutate: () => setActionError(null),
    onSuccess: ({ result }) => {
      setDeleteTarget(null);
      setReleasedBytes((value) => value + result.freed_bytes);
      void queryClient.invalidateQueries({ queryKey: ['storage'] });
      void queryClient.invalidateQueries({ queryKey: ['meetings'] });
      showToast(`${runtimeInfo.apiMode === 'mock' ? 'Mock 已释放' : '已释放'} ${formatBytes(result.freed_bytes)}`);
    },
    onError: (error) => setActionError(error instanceof Error ? error.message : '原始音频删除失败'),
  });

  const retryMutation = useMutation({
    mutationFn: async () => {
      if (!storageIssue || !file) throw new Error('需要重新选择待处理音频');
      await meetingApi.uploadAudio(storageIssue.meetingId, file);
      return storageIssue.meetingId;
    },
    onMutate: () => setActionError(null),
    onSuccess: (meetingId) => {
      setFile(null);
      setStorageIssue(null);
      navigate(`/meetings/${meetingId}/processing`);
    },
    onError: (error) => {
      const storage = getStorageInsufficientDetails(error);
      if (storage && storageIssue) {
        setReleasedBytes(0);
        setStorageIssue({
          ...storageIssue,
          requiredBytes: Math.max(storage.requiredBytes, storageIssue.fileSizeBytes),
          freeBytes: storage.freeBytes,
        });
      }
      setActionError(error instanceof Error ? error.message : '音频处理未能开始');
    },
  });

  const filteredRecentMeetings = useMemo(() => {
    const query = search.trim().toLocaleLowerCase('zh-CN');
    const meetings = recentMeetingsQuery.data?.items.slice(0, 5) ?? [];
    return query
      ? meetings.filter((meeting) => meeting.title.toLocaleLowerCase('zh-CN').includes(query))
      : meetings.slice(0, 3);
  }, [recentMeetingsQuery.data, search]);

  if (storageQuery.isLoading || storageMeetingsQuery.isLoading) {
    return <div className="insufficient-state-page"><div className="insufficient-state-card"><div className="insufficient-eyebrow">存储状态</div><h1>正在读取本地存储</h1></div></div>;
  }

  if (storageQuery.isError || storageMeetingsQuery.isError || !storageQuery.data || !storageMeetingsQuery.data) {
    const error = storageQuery.error ?? storageMeetingsQuery.error;
    return (
      <div className="insufficient-state-page">
        <div className="insufficient-state-card">
          <div className="insufficient-eyebrow">存储状态</div>
          <h1>无法读取本地存储</h1>
          <p>{error instanceof Error ? error.message : '本地存储暂时不可用'}</p>
          <button type="button" onClick={() => { void storageQuery.refetch(); void storageMeetingsQuery.refetch(); }}>重新读取</button>
        </div>
      </div>
    );
  }

  const storage = storageQuery.data;
  const requiredBytes = storageIssue?.requiredBytes ?? 0;
  const effectiveFreeBytes = runtimeInfo.apiMode === 'mock' && storageIssue
    ? storageIssue.freeBytes + releasedBytes
    : storage.free_bytes;
  const effectiveUsedBytes = Math.max(0, storage.total_bytes - effectiveFreeBytes);
  const ready = Boolean(storageIssue && requiredBytes > 0 && effectiveFreeBytes >= requiredBytes);
  const shortageBytes = Math.max(0, requiredBytes - effectiveFreeBytes);
  const usagePercent = storage.total_bytes > 0
    ? Math.min(100, effectiveUsedBytes / storage.total_bytes * 100)
    : 0;
  const cleanupMeetings = storageMeetingsQuery.data.items.filter((meeting) => meeting.can_delete_audio && meeting.audio_state === 'available').slice(0, 4);
  const hasFile = Boolean(file && storageIssue);
  const pageTitle = !storageIssue ? '没有待处理音频' : ready ? '可以开始处理' : '本地空间不足';
  const pageContext = !storageIssue
    ? '返回新建会议后重新选择音频'
    : ready
      ? '空间已满足本次处理需求'
      : '会议处理尚未开始';
  const sourceActionLabel = storageIssue?.sourceType === 'pc_record' ? '重新录音' : '重新选择音频';

  return (
    <>
      <div className="insufficient-layout">
        <aside className="insufficient-sidebar">
          <Brand />
          <label className="insufficient-search-wrap">
            <span className="insufficient-search"><span aria-hidden="true">⌕</span><input type="search" placeholder="搜索会议" value={search} onChange={(event) => setSearch(event.target.value)} /></span>
          </label>
          <div className="insufficient-list-label">最近会议</div>
          <nav className="insufficient-meeting-list">
            {filteredRecentMeetings.map((meeting) => (
              <Link className="insufficient-meeting-item" to={meetingTarget(meeting)} key={meeting.meeting_id}>
                <span className="insufficient-meeting-name">{meeting.title}</span>
                <span className="insufficient-meeting-meta"><span>{formatDuration(meeting.audio.duration_ms)}</span><span>{formatMeetingDate(meeting.meeting_date)}</span></span>
              </Link>
            ))}
          </nav>
          <div className={`insufficient-sidebar-foot ${ready ? 'insufficient-sidebar-foot-ready' : ''}`}><span className="insufficient-status-dot" /><span>{ready ? '本地空间可用' : '本地空间不足'}</span></div>
        </aside>

        <main className="insufficient-main">
          <header className="insufficient-topbar">
            <div className="insufficient-crumb">新建会议 <span>/</span> <strong>本地空间不足</strong></div>
            <div className="insufficient-top-actions"><Link className="insufficient-top-button" to="/settings/storage">存储管理</Link><Link className="insufficient-top-button" to="/meetings">返回会议库</Link></div>
          </header>

          <div className="insufficient-content">
            <div className="insufficient-eyebrow">存储状态</div>
            <h1>{pageTitle}</h1>
            <div className={`insufficient-context ${ready ? 'insufficient-context-ready' : ''}`}>{pageContext}</div>
            {actionError ? <div className="insufficient-action-error" role="alert">{actionError}</div> : null}

            <section className="insufficient-storage-panel">
              <div className="insufficient-panel-head"><div className="insufficient-panel-title">{storageIssue ? '开始处理前需要更多空间' : '当前没有等待处理的文件'}</div><div className={`insufficient-panel-state ${ready ? 'insufficient-panel-state-ready' : ''}`}>{ready ? '空间充足' : storageIssue ? '需要释放空间' : '等待音频'}</div></div>
              <div className="insufficient-storage-values"><div className="insufficient-storage-used">{formatBytes(effectiveUsedBytes)} <span>/ {formatBytes(storage.total_bytes)}</span></div><div className={`insufficient-storage-free ${ready ? 'insufficient-storage-free-ready' : ''}`}>可用 {formatBytes(effectiveFreeBytes)}</div></div>
              <div className="insufficient-storage-track"><span className={ready ? 'insufficient-storage-bar-ready' : ''} style={{ width: `${usagePercent}%` }} /></div>
              <div className="insufficient-storage-path">{storage.path}</div>
              <div className={`insufficient-shortage ${ready ? 'insufficient-shortage-ready' : ''}`}>
                <span>{ready ? '释放后可用空间' : storageIssue ? '仍需释放空间' : '本次处理需求'}</span>
                <strong>{ready ? formatBytes(effectiveFreeBytes) : storageIssue ? formatBytes(shortageBytes) : '—'}</strong>
              </div>
              <div className="insufficient-panel-actions">
                <Link className="insufficient-action-button" to="/settings/storage">管理存储</Link>
                {ready && !hasFile && storageIssue ? (
                  <button className="insufficient-action-button insufficient-action-primary insufficient-action-ready" type="button" onClick={() => navigate(storageIssue.returnPath)}>{sourceActionLabel}</button>
                ) : (
                  <button className={`insufficient-action-button insufficient-action-primary ${ready ? 'insufficient-action-ready' : ''}`} type="button" disabled={!ready || !hasFile || retryMutation.isPending} onClick={() => retryMutation.mutate()}>{retryMutation.isPending ? '正在开始' : '开始处理'}</button>
                )}
              </div>
            </section>

            <section className="insufficient-section">
              <div className="insufficient-section-head"><h2 className="insufficient-section-title">待处理音频</h2><div className="insufficient-section-meta">{hasFile ? '原始文件已保留' : storageIssue ? '需要重新选择文件' : '当前没有待处理文件'}</div></div>
              {storageIssue ? (
                <div className="insufficient-source-row">
                  <div><div className="insufficient-source-name">{storageIssue.title}</div><div className="insufficient-source-file">{storageIssue.fileName}</div></div>
                  <div className="insufficient-source-value"><strong>{formatBytes(storageIssue.fileSizeBytes)}</strong></div>
                  <span />
                </div>
              ) : <div className="insufficient-empty-source">从会议库新建本地音频或 PC 录音会议。</div>}
            </section>

            <section className="insufficient-section">
              <div className="insufficient-section-head"><h2 className="insufficient-section-title">可释放空间</h2><div className="insufficient-section-meta">仅限已确认会议</div></div>
              {cleanupMeetings.map((meeting) => (
                <div className="insufficient-source-row" key={meeting.meeting_id}>
                  <div><div className="insufficient-source-name">{meeting.title}</div><div className="insufficient-source-file">原始音频 · 正式版本已生成</div></div>
                  <div className="insufficient-source-value"><strong>{formatBytes(meeting.audio_size_bytes)}</strong></div>
                  <button className="insufficient-source-button" type="button" disabled={deleteAudioMutation.isPending} onClick={() => setDeleteTarget(meeting)}>删除音频</button>
                </div>
              ))}
              {cleanupMeetings.length === 0 ? <div className="insufficient-empty-source">没有可删除的已确认会议音频。</div> : null}
              <div className="insufficient-safe-note">删除原始音频后，全文、纪要、决策、待办和正式版本继续保留。</div>
            </section>
          </div>
        </main>

        <aside className="insufficient-inspector">
          <div className="insufficient-inspector-head"><div className="insufficient-inspector-title">本地状态</div></div>
          <div className="insufficient-inspector-body">
            <div className="insufficient-detail-group">
              <div className="insufficient-detail-row"><span>PC</span><strong className="insufficient-online">在线</strong></div>
              <div className="insufficient-detail-row"><span>Gateway</span><strong className="insufficient-online">{runtimeInfo.apiMode === 'mock' ? 'Mock' : '已连接'}</strong></div>
              <div className="insufficient-detail-row"><span>RK1828</span><strong>尚未检查</strong></div>
              <div className="insufficient-detail-row"><span>本地存储</span><strong className={ready ? 'insufficient-online' : 'insufficient-warning'}>{ready ? '可用' : '不足'}</strong></div>
            </div>
            <div className="insufficient-inspector-section"><div className="insufficient-inspector-label">当前可用空间</div><div className={`insufficient-inspector-number ${ready ? 'insufficient-inspector-number-ready' : ''}`}>{formatBytes(effectiveFreeBytes)}</div></div>
            <Link className="insufficient-inspector-link" to="/settings/storage">打开存储管理</Link>
          </div>
        </aside>
      </div>

      {deleteTarget ? (
        <div className="insufficient-dialog-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setDeleteTarget(null); }}>
          <section className="insufficient-dialog" role="dialog" aria-modal="true" aria-labelledby="insufficientDeleteTitle">
            <h2 id="insufficientDeleteTitle">删除原始音频？</h2>
            <div className="insufficient-dialog-meeting">{deleteTarget.title}</div>
            <div className="insufficient-dialog-list"><div className="insufficient-dialog-row"><span>原始音频</span><strong className="insufficient-dialog-remove">{formatBytes(deleteTarget.audio_size_bytes)}</strong></div><div className="insufficient-dialog-row"><span>全文与正式版本</span><strong>保留</strong></div></div>
            <div className="insufficient-dialog-actions"><button className="insufficient-dialog-button" type="button" onClick={() => setDeleteTarget(null)}>取消</button><button className="insufficient-dialog-button insufficient-dialog-danger" type="button" disabled={deleteAudioMutation.isPending} onClick={() => deleteAudioMutation.mutate(deleteTarget)}>{deleteAudioMutation.isPending ? '正在删除' : '确认删除'}</button></div>
          </section>
        </div>
      ) : null}

      <Toast message={toast} />
    </>
  );
}
