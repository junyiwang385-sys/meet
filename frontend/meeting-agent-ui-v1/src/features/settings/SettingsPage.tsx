import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { meetingApi, runtimeInfo } from '../../api';
import type { ExportFormat, MeetingSettings, UpdateMeetingSettingsInput } from '../../api/types';
import { Brand } from '../../components/Brand';
import { Toast } from '../../components/Toast';
import './SettingsPage.css';

interface SettingsDraft {
  deviceName: string;
  boardAddress: string;
  boardPort: string;
  meetingLibraryPath: string;
  keepAudioUntilFinalized: boolean;
  defaultExportFormats: ExportFormat[];
  defaultLanguage: string;
}

type ConnectionState = 'idle' | 'checking' | 'online' | 'failed';

const exportFormats: Array<{ value: ExportFormat; label: string }> = [
  { value: 'html', label: 'HTML' },
  { value: 'txt', label: 'TXT' },
  { value: 'json', label: 'JSON' },
];

function settingsDraft(settings: MeetingSettings): SettingsDraft {
  return {
    deviceName: settings.device_name,
    boardAddress: settings.board.address,
    boardPort: String(settings.board.port),
    meetingLibraryPath: settings.meeting_library_path,
    keepAudioUntilFinalized: settings.keep_audio_until_finalized,
    defaultExportFormats: [...settings.default_export_formats],
    defaultLanguage: settings.default_language,
  };
}

function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined || !Number.isFinite(bytes)) return '—';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let value = Math.max(0, bytes);
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value >= 100 || unit === 0 ? Math.round(value) : value.toFixed(1)} ${units[unit]}`;
}

function equalDraft(left: SettingsDraft | null, right: SettingsDraft | null): boolean {
  if (!left || !right) return left === right;
  return JSON.stringify(left) === JSON.stringify(right);
}

export function SettingsPage() {
  const queryClient = useQueryClient();
  const initializedRef = useRef(false);
  const toastTimerRef = useRef<number | null>(null);
  const [draft, setDraft] = useState<SettingsDraft | null>(null);
  const [savedDraft, setSavedDraft] = useState<SettingsDraft | null>(null);
  const [connectionState, setConnectionState] = useState<ConnectionState>('idle');
  const [connectionDetail, setConnectionDetail] = useState('尚未检查');
  const [formError, setFormError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const settingsQuery = useQuery({
    queryKey: ['settings'],
    queryFn: () => meetingApi.getSettings(),
  });

  const storageQuery = useQuery({
    queryKey: ['storage', 'summary'],
    queryFn: () => meetingApi.getStorageSummary(),
  });

  useEffect(() => {
    if (!settingsQuery.data || initializedRef.current) return;
    const initialDraft = settingsDraft(settingsQuery.data);
    setDraft(initialDraft);
    setSavedDraft(initialDraft);
    initializedRef.current = true;
  }, [settingsQuery.data]);

  useEffect(() => () => {
    if (toastTimerRef.current !== null) window.clearTimeout(toastTimerRef.current);
  }, []);

  function showToast(message: string) {
    setToast(message);
    if (toastTimerRef.current !== null) window.clearTimeout(toastTimerRef.current);
    toastTimerRef.current = window.setTimeout(() => setToast(null), 2400);
  }

  function updateDraft(update: Partial<SettingsDraft>) {
    setDraft((current) => current ? { ...current, ...update } : current);
    setFormError(null);
  }

  function resetConnectionCheck(update: Partial<SettingsDraft>) {
    updateDraft(update);
    setConnectionState('idle');
    setConnectionDetail('尚未检查');
  }

  const dirty = useMemo(() => !equalDraft(draft, savedDraft), [draft, savedDraft]);

  const boardCheckMutation = useMutation({
    mutationFn: async () => {
      if (!draft) throw new Error('设置尚未载入');
      const port = Number(draft.boardPort);
      if (!draft.boardAddress.trim()) throw new Error('请输入 RK1828 地址');
      if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('端口必须为 1–65535');
      return meetingApi.checkBoardConnection(draft.boardAddress.trim(), port);
    },
    onMutate: () => {
      setConnectionState('checking');
      setConnectionDetail('检查中');
      setFormError(null);
    },
    onSuccess: (result) => {
      if (result.status === 'online' && result.compatible) {
        setConnectionState('online');
        setConnectionDetail(`${runtimeInfo.apiMode === 'mock' ? 'Mock 可用' : '已连接'} · ${result.latency_ms ?? '—'} ms`);
        showToast(runtimeInfo.apiMode === 'mock' ? 'Mock 连接检查通过' : 'RK1828 连接正常');
        return;
      }
      setConnectionState('failed');
      setConnectionDetail(result.status === 'offline' ? '无法连接' : '协议不兼容');
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : '连接检查失败';
      setConnectionState('failed');
      setConnectionDetail(message);
      setFormError(message);
    },
  });

  const saveMutation = useMutation({
    mutationFn: async () => {
      if (!draft) throw new Error('设置尚未载入');
      const port = Number(draft.boardPort);
      if (!draft.deviceName.trim()) throw new Error('请输入设备名称');
      if (!draft.boardAddress.trim()) throw new Error('请输入 RK1828 地址');
      if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('端口必须为 1–65535');
      if (!draft.meetingLibraryPath.trim()) throw new Error('会议库目录不能为空');
      if (draft.defaultExportFormats.length === 0) throw new Error('至少选择一种默认导出格式');

      const storageCheck = await meetingApi.checkStoragePath(draft.meetingLibraryPath);
      if (!storageCheck.compatible || !storageCheck.writable) throw new Error('会议库目录不可写');

      const input: UpdateMeetingSettingsInput = {
        device_name: draft.deviceName.trim(),
        board: {
          address: draft.boardAddress.trim(),
          port,
        },
        meeting_library_path: draft.meetingLibraryPath,
        keep_audio_until_finalized: draft.keepAudioUntilFinalized,
        default_export_formats: draft.defaultExportFormats,
        default_language: draft.defaultLanguage,
      };
      return meetingApi.saveSettings(input);
    },
    onMutate: () => setFormError(null),
    onSuccess: (saved) => {
      const nextDraft = settingsDraft(saved);
      setDraft(nextDraft);
      setSavedDraft(nextDraft);
      queryClient.setQueryData(['settings'], saved);
      void queryClient.invalidateQueries({ queryKey: ['storage', 'summary'] });
      showToast(runtimeInfo.apiMode === 'mock' ? 'Mock 设置已保存' : '设置已保存到当前电脑');
    },
    onError: (error) => setFormError(error instanceof Error ? error.message : '设置保存失败'),
  });

  const revealMutation = useMutation({
    mutationFn: () => meetingApi.revealSystemTarget('meeting_library'),
    onSuccess: () => showToast(runtimeInfo.apiMode === 'mock' ? `会议库目录：${draft?.meetingLibraryPath ?? ''}` : '已打开会议库目录'),
    onError: (error) => setFormError(error instanceof Error ? error.message : '无法打开会议库目录'),
  });

  if (settingsQuery.isError) {
    return (
      <div className="settings-state-page">
        <div className="settings-state-card">
          <div className="settings-eyebrow">本地设置</div>
          <h1>无法读取设置</h1>
          <p>{settingsQuery.error instanceof Error ? settingsQuery.error.message : 'Gateway 暂时不可用'}</p>
          <button className="settings-row-button" type="button" onClick={() => void settingsQuery.refetch()}>重新读取</button>
        </div>
      </div>
    );
  }

  if (settingsQuery.isLoading || !draft) {
    return (
      <div className="settings-state-page">
        <div className="settings-state-card"><div className="settings-eyebrow">本地设置</div><h1>正在读取设置</h1></div>
      </div>
    );
  }

  const modelProfile = settingsQuery.data?.model_profile ?? '—';
  const freeSpace = storageQuery.isError ? '无法读取' : formatBytes(storageQuery.data?.free_bytes);
  const storageStatus = storageQuery.data?.status === 'warning'
    ? '空间偏低'
    : storageQuery.data?.status === 'insufficient'
      ? '空间不足'
      : storageQuery.data?.status === 'unavailable'
        ? '存储不可用'
        : storageQuery.isLoading
          ? '正在读取'
          : '可用';
  const saveState = saveMutation.isPending
    ? '正在保存设置'
    : formError
      ? formError
      : dirty
        ? '有未保存更改'
        : '所有设置已保存';

  return (
    <>
      <div className="settings-layout">
        <aside className="settings-sidebar">
          <Brand />
          <div className="settings-nav-label">设置</div>
          <nav className="settings-side-nav" aria-label="设置导航">
            <Link className="settings-side-link" to="/meetings"><span>全部会议</span><span>›</span></Link>
            <span className="settings-side-link settings-side-link-active"><span>设备与存储</span><span>›</span></span>
          </nav>
          <div className={`settings-sidebar-foot ${settingsQuery.isSuccess ? '' : 'settings-sidebar-foot-failed'}`}><span className="settings-live-dot" /><span>{settingsQuery.isSuccess ? '本地 Gateway 已连接' : '本地 Gateway 未连接'}</span></div>
        </aside>

        <main className="settings-main">
          <header className="settings-topbar">
            <div className="settings-crumb">设置 <span>/</span> <strong>设备与存储</strong></div>
            <button className="settings-save-button" type="button" disabled={!dirty || saveMutation.isPending} onClick={() => saveMutation.mutate()}>{saveMutation.isPending ? '正在保存' : '保存设置'}</button>
          </header>

          <div className="settings-content">
            <div className="settings-eyebrow">本地设置</div>
            <h1>设备与存储</h1>
            <div className={`settings-save-state ${formError ? 'settings-save-state-error' : ''}`}>{saveState}</div>

            <section className="settings-section" aria-labelledby="settingsBoardTitle">
              <h2 className="settings-section-head" id="settingsBoardTitle">RK1828</h2>
              <div className="settings-row">
                <div className="settings-label">设备名称</div>
                <div className="settings-value"><input className="settings-field" value={draft.deviceName} onChange={(event) => updateDraft({ deviceName: event.target.value })} /></div>
                <span />
              </div>
              <div className="settings-row">
                <div className="settings-label">Agent API</div>
                <div className="settings-value settings-field-group">
                  <input className="settings-field mono" aria-label="RK1828 地址" value={draft.boardAddress} onChange={(event) => resetConnectionCheck({ boardAddress: event.target.value })} />
                  <input className="settings-field mono" aria-label="RK1828 端口" inputMode="numeric" value={draft.boardPort} onChange={(event) => resetConnectionCheck({ boardPort: event.target.value })} />
                </div>
                <button className="settings-row-button" type="button" disabled={boardCheckMutation.isPending} onClick={() => boardCheckMutation.mutate()}>{boardCheckMutation.isPending ? '检查中' : '检查连接'}</button>
              </div>
              <div className="settings-row">
                <div className="settings-label">连接状态</div>
                <div className="settings-value"><span className={`settings-connection settings-connection-${connectionState}`}>{connectionDetail}</span></div>
                <span />
              </div>
              <div className="settings-row">
                <div className="settings-label">模型配置</div>
                <div className="settings-value"><strong className="mono">{modelProfile}</strong></div>
                <span />
              </div>
            </section>

            <section className="settings-section" aria-labelledby="settingsStorageTitle">
              <h2 className="settings-section-head" id="settingsStorageTitle">本地存储</h2>
              <div className="settings-row">
                <div className="settings-label">会议库目录</div>
                <div className="settings-value settings-path" title={draft.meetingLibraryPath}>{draft.meetingLibraryPath}</div>
                <button className="settings-row-button" type="button" disabled={revealMutation.isPending} onClick={() => revealMutation.mutate()}>打开目录</button>
              </div>
              <div className="settings-row">
                <div className="settings-label">可用空间</div>
                <div className="settings-value"><strong>{freeSpace}</strong><span className={`settings-storage-status settings-storage-status-${storageQuery.data?.status ?? 'loading'}`}>{storageStatus}</span></div>
                <Link className="settings-row-button" to="/settings/storage">管理存储</Link>
              </div>
              <div className="settings-row">
                <div className="settings-label">原始音频</div>
                <div className="settings-value">
                  <label className="settings-toggle"><input type="checkbox" checked={draft.keepAudioUntilFinalized} onChange={(event) => updateDraft({ keepAudioUntilFinalized: event.target.checked })} />确认正式版本前保留</label>
                </div>
                <span />
              </div>
            </section>

            <section className="settings-section" aria-labelledby="settingsExportTitle">
              <h2 className="settings-section-head" id="settingsExportTitle">正式版本</h2>
              <div className="settings-row">
                <div className="settings-label">默认生成格式</div>
                <div className="settings-value settings-checks">
                  {exportFormats.map((format) => (
                    <label className="settings-check" key={format.value}>
                      <input
                        type="checkbox"
                        checked={draft.defaultExportFormats.includes(format.value)}
                        onChange={(event) => updateDraft({
                          defaultExportFormats: event.target.checked
                            ? [...draft.defaultExportFormats, format.value]
                            : draft.defaultExportFormats.filter((value) => value !== format.value),
                        })}
                      />
                      {format.label}
                    </label>
                  ))}
                </div>
                <span />
              </div>
              <div className="settings-row">
                <div className="settings-label">默认语言</div>
                <div className="settings-value"><strong>{draft.defaultLanguage === 'zh-CN' ? '中文' : draft.defaultLanguage}</strong></div>
                <span />
              </div>
            </section>
          </div>
        </main>
      </div>
      <Toast message={toast} />
    </>
  );
}
