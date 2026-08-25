import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { meetingApi, runtimeInfo } from '../../api';
import { formatMeetingDate } from '../../api/meeting-api';
import type { MeetingState, StorageMeetingItem, StorageStatus } from '../../api/types';
import { Brand } from '../../components/Brand';
import { Toast } from '../../components/Toast';
import './SettingsPage.css';
import './StorageManagementPage.css';

const categoryDefinitions = [
  { key: 'audio_bytes', label: '原始音频', className: 'storage-category-audio' },
  { key: 'results_bytes', label: '会议结果', className: 'storage-category-results' },
  { key: 'exports_bytes', label: '正式版本', className: 'storage-category-exports' },
  { key: 'temp_bytes', label: '临时文件', className: 'storage-category-temp' },
] as const;

function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined || !Number.isFinite(bytes)) return '—';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let value = Math.max(0, bytes);
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const digits = value >= 100 || unit === 0 ? 0 : 1;
  return `${value.toFixed(digits)} ${units[unit]}`;
}

function meetingStateLabel(state: MeetingState): string {
  if (state === 'finalized') return '已确认';
  if (state === 'review_ready') return '待核对';
  if (state === 'failed') return '处理失败';
  if (state === 'cancelled') return '已取消';
  if (state === 'recording') return '录音中';
  if (state === 'created') return '等待音频';
  return '处理中';
}

function audioStateLabel(item: StorageMeetingItem): string {
  if (item.audio_state === 'deleted') return '原始音频已删除';
  if (item.audio_state === 'available' && item.meeting_state === 'finalized') return '正式版本已生成';
  if (item.audio_state === 'available') return '原始音频可用';
  if (item.audio_state === 'recording') return '正在录音';
  if (item.audio_state === 'missing') return '原始音频缺失';
  if (item.audio_state === 'unreadable') return '原始音频不可读';
  return '原始音频尚未生成';
}

function deleteActionLabel(item: StorageMeetingItem): string {
  if (item.audio_state === 'deleted') return '已删除';
  if (item.can_delete_audio) return '删除音频';
  if (['recording', 'uploading', 'processing', 'finalizing'].includes(item.meeting_state)) return '处理中';
  if (item.meeting_state === 'review_ready') return '确认后可删';
  return '不可删除';
}

function storageStatusLabel(status: StorageStatus): string {
  if (status === 'warning') return '可用空间偏低';
  if (status === 'insufficient') return '可用空间不足';
  if (status === 'unavailable') return '本地存储不可用';
  return '本地存储可用';
}

function meetingPage(item: StorageMeetingItem): string {
  if (['review_ready', 'finalizing', 'finalized'].includes(item.meeting_state)) {
    return `/meetings/${item.meeting_id}/review`;
  }
  return `/meetings/${item.meeting_id}/processing`;
}

export function StorageManagementPage() {
  const queryClient = useQueryClient();
  const toastTimerRef = useRef<number | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<StorageMeetingItem | null>(null);
  const [cleanupDialogOpen, setCleanupDialogOpen] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const storageQuery = useQuery({
    queryKey: ['storage', 'summary'],
    queryFn: () => meetingApi.getStorageSummary(),
  });

  const meetingsQuery = useQuery({
    queryKey: ['storage', 'meetings'],
    queryFn: () => meetingApi.listStorageMeetings(),
  });

  useEffect(() => () => {
    if (toastTimerRef.current !== null) window.clearTimeout(toastTimerRef.current);
  }, []);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      setDeleteTarget(null);
      setCleanupDialogOpen(false);
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, []);

  function showToast(message: string) {
    setToast(message);
    if (toastTimerRef.current !== null) window.clearTimeout(toastTimerRef.current);
    toastTimerRef.current = window.setTimeout(() => setToast(null), 2400);
  }

  const cleanupMutation = useMutation({
    mutationFn: () => meetingApi.cleanupTemporaryFiles(),
    onMutate: () => setActionError(null),
    onSuccess: (result) => {
      setCleanupDialogOpen(false);
      void queryClient.invalidateQueries({ queryKey: ['storage', 'summary'] });
      const message = result.freed_bytes > 0
        ? `${runtimeInfo.apiMode === 'mock' ? 'Mock 已释放' : '已释放'} ${formatBytes(result.freed_bytes)} 临时文件`
        : '没有可安全清理的临时文件';
      showToast(message);
    },
    onError: (error) => setActionError(error instanceof Error ? error.message : '临时文件清理失败'),
  });

  const deleteAudioMutation = useMutation({
    mutationFn: async (meeting: StorageMeetingItem) => ({
      meeting,
      result: await meetingApi.deleteMeetingAudio(meeting.meeting_id, '删除音频'),
    }),
    onMutate: () => setActionError(null),
    onSuccess: ({ result }) => {
      setDeleteTarget(null);
      void queryClient.invalidateQueries({ queryKey: ['storage'] });
      void queryClient.invalidateQueries({ queryKey: ['meetings'] });
      void queryClient.invalidateQueries({ queryKey: ['meeting', result.meeting_id] });
      showToast(`${runtimeInfo.apiMode === 'mock' ? 'Mock 已释放' : '已释放'} ${formatBytes(result.freed_bytes)}`);
    },
    onError: (error) => setActionError(error instanceof Error ? error.message : '原始音频删除失败'),
  });

  const revealMutation = useMutation({
    mutationFn: () => meetingApi.revealSystemTarget('meeting_library'),
    onSuccess: () => showToast(runtimeInfo.apiMode === 'mock' ? `会议库目录：${storageQuery.data?.path ?? ''}` : '已打开会议库目录'),
    onError: (error) => setActionError(error instanceof Error ? error.message : '无法打开会议库目录'),
  });

  const categories = useMemo(() => {
    const summary = storageQuery.data;
    if (!summary) return [];
    const maximum = Math.max(1, ...categoryDefinitions.map((category) => summary.categories[category.key]));
    return categoryDefinitions.map((category) => ({
      ...category,
      bytes: summary.categories[category.key],
      totalPercent: summary.total_bytes > 0 ? summary.categories[category.key] / summary.total_bytes * 100 : 0,
      categoryPercent: summary.categories[category.key] / maximum * 100,
    }));
  }, [storageQuery.data]);

  if (storageQuery.isLoading || meetingsQuery.isLoading) {
    return <div className="settings-state-page"><div className="settings-state-card"><div className="settings-eyebrow">本地存储</div><h1>正在读取存储</h1></div></div>;
  }

  if (storageQuery.isError || meetingsQuery.isError || !storageQuery.data || !meetingsQuery.data) {
    const error = storageQuery.error ?? meetingsQuery.error;
    return (
      <div className="settings-state-page">
        <div className="settings-state-card">
          <div className="settings-eyebrow">本地存储</div>
          <h1>无法读取存储</h1>
          <p>{error instanceof Error ? error.message : '本地存储暂时不可用'}</p>
          <button className="settings-row-button" type="button" onClick={() => { void storageQuery.refetch(); void meetingsQuery.refetch(); }}>重新读取</button>
        </div>
      </div>
    );
  }

  const storage = storageQuery.data;
  const meetings = meetingsQuery.data.items;
  const tempBytes = storage.categories.temp_bytes;
  const statusLabel = storageStatusLabel(storage.status);

  return (
    <>
      <div className="settings-layout storage-layout">
        <aside className="settings-sidebar">
          <Brand />
          <div className="settings-nav-label">设置</div>
          <nav className="settings-side-nav" aria-label="设置导航">
            <Link className="settings-side-link" to="/meetings"><span>全部会议</span><span>›</span></Link>
            <Link className="settings-side-link" to="/settings"><span>设备与存储</span><span>›</span></Link>
            <span className="settings-side-link settings-side-link-active"><span>存储管理</span><span>›</span></span>
          </nav>
          <div className={`settings-sidebar-foot storage-sidebar-foot-${storage.status}`}><span className="settings-live-dot" /><span>{statusLabel}</span></div>
        </aside>

        <main className="settings-main">
          <header className="settings-topbar">
            <div className="settings-crumb">设置 <span>/</span> <strong>存储管理</strong></div>
            <div className="storage-top-actions">
              <button className="storage-top-button" type="button" disabled={revealMutation.isPending} onClick={() => revealMutation.mutate()}>打开目录</button>
              <Link className="storage-top-button" to="/settings">返回设置</Link>
            </div>
          </header>

          <div className="storage-content">
            <div className="settings-eyebrow">本地存储</div>
            <h1>存储管理</h1>
            <div className="storage-path" title={storage.path}>{storage.path}</div>
            {actionError ? <div className="storage-action-error" role="alert">{actionError}</div> : null}

            <section className="storage-usage" aria-label="存储总览">
              <div className="storage-usage-head">
                <div className="storage-usage-value">{formatBytes(storage.used_bytes)} <span>/ {formatBytes(storage.total_bytes)}</span></div>
                <div className={`storage-usage-free storage-usage-free-${storage.status}`}>可用 {formatBytes(storage.free_bytes)}</div>
              </div>
              <div className="storage-usage-track" aria-hidden="true">
                {categories.map((category) => <span className={`storage-usage-segment ${category.className}`} style={{ width: `${category.totalPercent}%` }} key={category.key} />)}
              </div>
              <div className="storage-legend">
                {categories.map((category) => <span className="storage-legend-item" key={category.key}><i className={`storage-legend-dot ${category.className}`} />{category.label}</span>)}
              </div>
            </section>

            <section className="storage-section" aria-labelledby="storageCategoriesTitle">
              <div className="storage-section-head">
                <h2 className="storage-section-title" id="storageCategoriesTitle">存储分类</h2>
                <button className="storage-section-action" type="button" disabled={tempBytes === 0 || cleanupMutation.isPending} onClick={() => setCleanupDialogOpen(true)}>{tempBytes === 0 ? '已清理' : '清理临时文件'}</button>
              </div>
              {categories.map((category) => (
                <div className="storage-category-row" key={category.key}>
                  <span className="storage-category-name">{category.label}</span>
                  <span className="storage-category-bar"><span className={category.className} style={{ width: `${category.categoryPercent}%` }} /></span>
                  <span className="storage-category-size">{formatBytes(category.bytes)}</span>
                </div>
              ))}
            </section>

            <section className="storage-section" aria-labelledby="storageAudioTitle">
              <div className="storage-section-head"><h2 className="storage-section-title" id="storageAudioTitle">会议音频</h2></div>
              <div className="storage-list-head"><span>会议</span><span>状态</span><span>大小</span><span>日期</span><span>操作</span></div>
              <div className="storage-audio-list">
                {meetings.map((meeting) => (
                  <div className="storage-audio-row" key={meeting.meeting_id}>
                    <div className="storage-meeting-summary"><Link className="storage-meeting-name" to={meetingPage(meeting)}>{meeting.title}</Link><div className="storage-meeting-state">{audioStateLabel(meeting)}</div></div>
                    <span className="storage-cell">{meetingStateLabel(meeting.meeting_state)}</span>
                    <span className="storage-cell mono">{formatBytes(meeting.audio_size_bytes)}</span>
                    <span className="storage-cell storage-cell-muted">{formatMeetingDate(meeting.meeting_date)}</span>
                    <button className="storage-delete-button" type="button" disabled={!meeting.can_delete_audio || deleteAudioMutation.isPending} onClick={() => setDeleteTarget(meeting)}>{deleteActionLabel(meeting)}</button>
                  </div>
                ))}
                {meetings.length === 0 ? <div className="storage-empty-list">当前没有会议音频</div> : null}
              </div>
            </section>
          </div>
        </main>
      </div>

      {deleteTarget ? (
        <div className="storage-dialog-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setDeleteTarget(null); }}>
          <section className="storage-dialog" role="dialog" aria-modal="true" aria-labelledby="storageDeleteTitle">
            <h2 id="storageDeleteTitle">删除原始音频？</h2>
            <div className="storage-dialog-meeting">{deleteTarget.title}</div>
            <div className="storage-dialog-list">
              <div className="storage-dialog-row"><span>原始音频</span><strong className="storage-dialog-remove">{formatBytes(deleteTarget.audio_size_bytes)}</strong></div>
              <div className="storage-dialog-row"><span>会议全文与纪要</span><strong>保留</strong></div>
              <div className="storage-dialog-row"><span>正式版本</span><strong>保留</strong></div>
            </div>
            <div className="storage-dialog-actions">
              <button className="storage-dialog-button" type="button" onClick={() => setDeleteTarget(null)}>取消</button>
              <button className="storage-dialog-button storage-dialog-danger" type="button" disabled={deleteAudioMutation.isPending} onClick={() => deleteAudioMutation.mutate(deleteTarget)}>{deleteAudioMutation.isPending ? '正在删除' : '确认删除'}</button>
            </div>
          </section>
        </div>
      ) : null}

      {cleanupDialogOpen ? (
        <div className="storage-dialog-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setCleanupDialogOpen(false); }}>
          <section className="storage-dialog" role="dialog" aria-modal="true" aria-labelledby="storageCleanupTitle">
            <h2 id="storageCleanupTitle">清理临时文件？</h2>
            <p className="storage-dialog-copy">只清理失败上传文件、可重建中间文件和过期临时日志。原始音频、会议结果、草稿、正式版本和活动任务文件不会删除。</p>
            <div className="storage-dialog-list"><div className="storage-dialog-row"><span>可安全清理</span><strong className="storage-dialog-remove">{formatBytes(tempBytes)}</strong></div></div>
            <div className="storage-dialog-actions">
              <button className="storage-dialog-button" type="button" onClick={() => setCleanupDialogOpen(false)}>取消</button>
              <button className="storage-dialog-button storage-dialog-danger" type="button" disabled={cleanupMutation.isPending} onClick={() => cleanupMutation.mutate()}>{cleanupMutation.isPending ? '正在清理' : '确认清理'}</button>
            </div>
          </section>
        </div>
      ) : null}

      <Toast message={toast} />
    </>
  );
}
