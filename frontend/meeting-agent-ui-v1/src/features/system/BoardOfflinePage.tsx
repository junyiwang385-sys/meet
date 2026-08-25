import { useMutation, useQuery } from '@tanstack/react-query';
import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { meetingApi, runtimeInfo } from '../../api';
import { formatDuration, formatMeetingDate } from '../../api/meeting-api';
import type { MeetingListItem } from '../../api/types';
import { Brand } from '../../components/Brand';
import { Toast } from '../../components/Toast';
import './BoardOfflinePage.css';

type ConnectionState = 'offline' | 'checking' | 'connected';

function meetingTarget(meeting: MeetingListItem) {
  if (['created', 'recording', 'uploading', 'processing', 'finalizing', 'failed'].includes(meeting.state)) {
    return `/meetings/${meeting.meeting_id}/processing`;
  }
  return `/meetings/${meeting.meeting_id}/review`;
}

export function BoardOfflinePage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const redirectTimerRef = useRef<number | null>(null);
  const toastTimerRef = useRef<number | null>(null);
  const initializedRef = useRef(false);
  const [address, setAddress] = useState('10.10.22.36');
  const [port, setPort] = useState('18080');
  const [search, setSearch] = useState('');
  const [connectionState, setConnectionState] = useState<ConnectionState>('offline');
  const [connectionCopy, setConnectionCopy] = useState('未连接');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const returnPath = useMemo(() => {
    const candidate = searchParams.get('returnTo');
    return candidate?.startsWith('/') ? candidate : '/meetings';
  }, [searchParams]);

  const settingsQuery = useQuery({
    queryKey: ['meeting-settings'],
    queryFn: () => meetingApi.getSettings(),
  });

  const meetingsQuery = useQuery({
    queryKey: ['meetings', 'board-offline-recent'],
    queryFn: () => meetingApi.listMeetings({ sort: 'updated_desc' }),
  });

  useEffect(() => {
    if (!settingsQuery.data || initializedRef.current) return;
    initializedRef.current = true;
    setAddress(settingsQuery.data.board.address);
    setPort(String(settingsQuery.data.board.port));
  }, [settingsQuery.data]);

  useEffect(() => () => {
    if (redirectTimerRef.current !== null) window.clearTimeout(redirectTimerRef.current);
    if (toastTimerRef.current !== null) window.clearTimeout(toastTimerRef.current);
  }, []);

  function showToast(message: string) {
    setToast(message);
    if (toastTimerRef.current !== null) window.clearTimeout(toastTimerRef.current);
    toastTimerRef.current = window.setTimeout(() => setToast(null), 2200);
  }

  const checkMutation = useMutation({
    mutationFn: async () => {
      const normalizedAddress = address.trim();
      const normalizedPort = Number(port);
      if (!normalizedAddress) throw new Error('请输入 RK1828 地址');
      if (!Number.isInteger(normalizedPort) || normalizedPort < 1 || normalizedPort > 65535) {
        throw new Error('端口必须为 1–65535');
      }
      return meetingApi.checkBoardConnection(normalizedAddress, normalizedPort);
    },
    onMutate: () => {
      setConnectionState('checking');
      setConnectionCopy(`正在检查 ${address.trim()}:${port}`);
      setErrorMessage(null);
    },
    onSuccess: (result) => {
      if (result.status !== 'online' || !result.compatible) {
        setConnectionState('offline');
        setConnectionCopy(result.status === 'offline' ? '无法连接设备' : '设备协议不兼容');
        setErrorMessage('请检查 RK1828 地址、端口和局域网连接。');
        return;
      }

      setConnectionState('connected');
      setConnectionCopy(runtimeInfo.apiMode === 'mock' ? 'Mock RK1828 可用' : `RK1828 已连接 · ${result.latency_ms ?? '—'} ms`);
      showToast(runtimeInfo.apiMode === 'mock' ? 'Mock 设备检查通过' : 'RK1828 已连接');
      redirectTimerRef.current = window.setTimeout(() => navigate(returnPath, { replace: true }), 750);
    },
    onError: (error) => {
      setConnectionState('offline');
      setConnectionCopy('连接检查失败');
      setErrorMessage(error instanceof Error ? error.message : '无法检查 RK1828 连接');
    },
  });

  const connected = connectionState === 'connected';
  const checking = connectionState === 'checking';
  const meetings = (meetingsQuery.data?.items ?? [])
    .filter((meeting) => !search.trim() || meeting.title.toLocaleLowerCase('zh-CN').includes(search.trim().toLocaleLowerCase('zh-CN')))
    .slice(0, 3);

  return (
    <>
      <div className="board-offline-layout">
        <aside className="board-offline-sidebar">
          <Brand />
          <label className="board-offline-search-wrap">
            <span className="board-offline-search"><span aria-hidden="true">⌕</span><input type="search" placeholder="搜索会议" value={search} onChange={(event) => setSearch(event.target.value)} /></span>
          </label>
          <div className="board-offline-list-label">最近会议</div>
          <nav className="board-offline-meeting-list" aria-label="最近会议">
            {meetings.map((meeting) => (
              <Link className="board-offline-meeting-item" to={meetingTarget(meeting)} key={meeting.meeting_id}>
                <span className="board-offline-meeting-name">{meeting.title}</span>
                <span className="board-offline-meeting-meta"><span>{formatDuration(meeting.audio.duration_ms)}</span><span>{formatMeetingDate(meeting.meeting_date)}</span></span>
              </Link>
            ))}
            {!meetingsQuery.isPending && meetings.length === 0 ? <div className="board-offline-meeting-empty">没有匹配的会议</div> : null}
          </nav>
          <div className={`board-offline-sidebar-foot ${connected ? 'board-offline-sidebar-foot-connected' : ''}`}><span className="board-offline-status-dot" /><span>{connected ? 'RK1828 已连接' : 'RK1828 未连接'}</span></div>
        </aside>

        <main className="board-offline-main">
          <header className="board-offline-topbar">
            <div className="board-offline-crumb">会议库 <span>/</span> <strong>设备未连接</strong></div>
            <div className="board-offline-top-actions"><Link className="board-offline-top-button" to="/meetings">返回会议库</Link><button className="board-offline-top-button" type="button" disabled>＋ 新建会议</button></div>
          </header>

          <div className="board-offline-content">
            <div className="board-offline-eyebrow">设备连接</div>
            <h1>{connected ? 'RK1828 已连接' : 'RK1828 未连接'}</h1>
            <div className={`board-offline-context ${connected ? 'board-offline-context-connected' : ''}`}><span />{connected ? '设备已恢复' : '不可创建新的板端处理任务'}</div>

            <section className="board-offline-panel" aria-labelledby="boardConnectionTitle">
              <h2 id="boardConnectionTitle">连接设备</h2>
              <div className="board-offline-fields">
                <label className="board-offline-field"><span>设备地址</span><input className="mono" value={address} onChange={(event) => { initializedRef.current = true; setAddress(event.target.value); setConnectionState('offline'); setConnectionCopy('尚未检查'); }} /></label>
                <label className="board-offline-field"><span>端口</span><input className="mono" inputMode="numeric" value={port} onChange={(event) => { initializedRef.current = true; setPort(event.target.value); setConnectionState('offline'); setConnectionCopy('尚未检查'); }} /></label>
              </div>
              <div className={`board-offline-result board-offline-result-${connectionState}`}>{connectionCopy}</div>
              {errorMessage ? <div className="board-offline-error" role="alert">{errorMessage}</div> : null}
              <div className="board-offline-actions"><Link className="board-offline-action" to="/settings">设备设置</Link><button className="board-offline-action board-offline-action-primary" type="button" disabled={checking || connected} onClick={() => checkMutation.mutate()}>{checking ? '连接中' : connected ? '已连接' : '重新连接'}</button></div>
            </section>
          </div>
        </main>

        <aside className="board-offline-inspector">
          <div className="board-offline-inspector-head"><div>本地状态</div></div>
          <div className="board-offline-inspector-body">
            <div className="board-offline-detail-group">
              <div className="board-offline-detail-row"><span>PC</span><strong className="board-offline-online">在线</strong></div>
              <div className="board-offline-detail-row"><span>PC Gateway</span><strong className="board-offline-online">在线</strong></div>
              <div className="board-offline-detail-row"><span>RK1828</span><strong className={connected ? 'board-offline-online' : 'board-offline-offline'}>{connected ? '已连接' : '未连接'}</strong></div>
              <div className="board-offline-detail-row"><span>本地会议</span><strong>可查看</strong></div>
            </div>
            <Link className="board-offline-inspector-link" to="/settings">设备与存储设置</Link>
          </div>
        </aside>
      </div>
      <Toast message={toast} />
    </>
  );
}
