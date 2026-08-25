import { useMutation, useQuery } from '@tanstack/react-query';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { meetingApi } from '../../api';
import { formatDuration, formatMeetingDate, getApiErrorCode } from '../../api/meeting-api';
import type { BoardRecordingStatusResponse, MeetingListItem } from '../../api/types';
import { Brand } from '../../components/Brand';
import './PcRecordingPage.css';
import './BoardRecordingPage.css';

type BoardPageState =
  | 'idle'
  | 'starting'
  | 'recording'
  | 'stopping'
  | 'disconnected'
  | 'error';

interface BoardDevice {
  id: string;
  name: string;
}

interface StoredBoardSession {
  meetingId: string;
  title: string;
  deviceId: string;
}

const activeSessionKey = 'meeting-agent.active-board-recording';

const boardDevices: BoardDevice[] = [
  { id: 'rk1828-main-mic', name: '会议室 RK1828' },
  { id: 'rk1828-backup-mic', name: '备用 RK1828' },
];

const waveformBars = Array.from({ length: 42 }, (_, index) => ({
  height: 16 + ((index * 17) % 49),
  speed: 0.48 + ((index * 7) % 7) * 0.07,
  delay: -((index * 3) % 10) / 10,
}));

function readStoredSession(): StoredBoardSession | null {
  try {
    const value = window.sessionStorage.getItem(activeSessionKey);
    return value ? JSON.parse(value) as StoredBoardSession : null;
  } catch {
    return null;
  }
}

function storeSession(session: StoredBoardSession) {
  try {
    window.sessionStorage.setItem(activeSessionKey, JSON.stringify(session));
  } catch {
    // A blocked session store does not stop board-side recording.
  }
}

function clearStoredSession() {
  try {
    window.sessionStorage.removeItem(activeSessionKey);
  } catch {
    // The recording state remains authoritative on the board.
  }
}

function formatClock(totalSeconds: number): string {
  const seconds = Math.max(0, Math.floor(totalSeconds));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remainder = seconds % 60;
  return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(remainder).padStart(2, '0')}`;
}

function meetingTarget(meeting: MeetingListItem): string {
  if (meeting.state === 'review_ready' || meeting.state === 'finalized' || meeting.state === 'finalizing') {
    return `/meetings/${meeting.meeting_id}/review`;
  }
  return `/meetings/${meeting.meeting_id}/processing`;
}

function pageHeading(state: BoardPageState): string {
  if (state === 'starting') return '正在连接 RK1828';
  if (state === 'recording') return '板端正在录音';
  if (state === 'stopping') return '正在结束板端录音';
  if (state === 'disconnected') return '无法确认录音状态';
  if (state === 'error') return '无法开始板端录音';
  return '准备板端录音';
}

function stateLabel(state: BoardPageState): string {
  if (state === 'starting') return '正在创建会议并连接板端';
  if (state === 'recording') return '音频正在 RK1828 保存';
  if (state === 'stopping') return '正在关闭板端录音文件';
  if (state === 'disconnected') return '与板端的控制连接已中断';
  if (state === 'error') return '板端录音尚未开始';
  return '等待开始';
}

export function BoardRecordingPage() {
  const navigate = useNavigate();
  const storedSessionRef = useRef<StoredBoardSession | null>(readStoredSession());
  const createdMeetingIdRef = useRef<string | null>(storedSessionRef.current?.meetingId ?? null);

  const [state, setState] = useState<BoardPageState>(storedSessionRef.current ? 'starting' : 'idle');
  const [title, setTitle] = useState(storedSessionRef.current?.title ?? '未命名会议');
  const [selectedDeviceId, setSelectedDeviceId] = useState(storedSessionRef.current?.deviceId ?? boardDevices[0].id);
  const [meetingId, setMeetingId] = useState<string | null>(storedSessionRef.current?.meetingId ?? null);
  const [recordingId, setRecordingId] = useState<string | null>(null);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [audioSaved, setAudioSaved] = useState<boolean | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [stopDialogOpen, setStopDialogOpen] = useState(false);
  const [exitDialogOpen, setExitDialogOpen] = useState(false);
  const [reconnecting, setReconnecting] = useState(false);

  const recentMeetingsQuery = useQuery({
    queryKey: ['meetings', 'board-record-recent'],
    queryFn: () => meetingApi.listMeetings({ sort: 'updated_desc' }),
  });

  const selectedDevice = boardDevices.find((device) => device.id === selectedDeviceId) ?? boardDevices[0];

  const applyBoardStatus = useCallback((status: BoardRecordingStatusResponse) => {
    setRecordingId(status.recording_id);
    setElapsedSeconds(status.elapsed_seconds);
    setAudioSaved(status.audio_saved);

    if (status.state === 'recording' && status.connection === 'online') {
      setState('recording');
      setErrorMessage(null);
      return;
    }
    if (status.state === 'disconnected' || status.state === 'unknown' || status.connection !== 'online') {
      setState('disconnected');
      setErrorMessage(status.error?.message ?? '无法确认板端录音是否仍在进行');
      return;
    }
    if (status.state === 'failed') {
      setState('error');
      setErrorMessage(status.error?.message ?? '板端录音失败');
      return;
    }
    if (status.state === 'stopped') {
      clearStoredSession();
      navigate(`/meetings/${status.meeting_id}/processing`);
    }
  }, [navigate]);

  const syncBoardStatus = useCallback(async () => {
    if (!meetingId) return;
    try {
      const status = await meetingApi.getBoardRecording(meetingId);
      applyBoardStatus(status);
    } catch (error) {
      setState('disconnected');
      setAudioSaved(null);
      setErrorMessage(error instanceof Error ? error.message : '无法读取板端录音状态');
    }
  }, [applyBoardStatus, meetingId]);

  useEffect(() => {
    if (!meetingId) return;
    void syncBoardStatus();
    const timer = window.setInterval(() => void syncBoardStatus(), 3000);
    return () => window.clearInterval(timer);
  }, [meetingId, syncBoardStatus]);

  useEffect(() => {
    if (state !== 'recording') return;
    const timer = window.setInterval(() => setElapsedSeconds((value) => value + 1), 1000);
    return () => window.clearInterval(timer);
  }, [state]);

  useEffect(() => {
    if (!['starting', 'recording', 'stopping', 'disconnected'].includes(state)) return;
    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', handleBeforeUnload);
    return () => window.removeEventListener('beforeunload', handleBeforeUnload);
  }, [state]);

  const startMutation = useMutation({
    mutationFn: async () => {
      let currentMeetingId = createdMeetingIdRef.current;
      if (!currentMeetingId) {
        const created = await meetingApi.createMeeting({
          title: title.trim() || '未命名会议',
          source_type: 'board_record',
          language: 'zh-CN',
        });
        currentMeetingId = created.meeting_id;
        createdMeetingIdRef.current = currentMeetingId;
      }
      return meetingApi.startBoardRecording(currentMeetingId, selectedDeviceId);
    },
    onMutate: () => {
      setState('starting');
      setErrorMessage(null);
    },
    onSuccess: (response) => {
      setMeetingId(response.meeting_id);
      setRecordingId(response.recording_id);
      setElapsedSeconds(response.recording.elapsed_seconds);
      setAudioSaved(response.recording.audio_saved);
      setErrorMessage(null);
      setState('recording');
      storeSession({
        meetingId: response.meeting_id,
        title: title.trim() || '未命名会议',
        deviceId: selectedDeviceId,
      });
    },
    onError: (error) => {
      if (getApiErrorCode(error) === 'BOARD_UNREACHABLE') {
        navigate('/system/board-offline?returnTo=/record/board');
        return;
      }
      setState('error');
      setErrorMessage(error instanceof Error ? error.message : '无法开始板端录音');
    },
  });

  const stopMutation = useMutation({
    mutationFn: async () => {
      if (!meetingId) throw new Error('板端录音会话不存在');
      return meetingApi.stopBoardRecording(meetingId);
    },
    onMutate: () => {
      setStopDialogOpen(false);
      setState('stopping');
      setErrorMessage(null);
    },
    onSuccess: (response) => {
      clearStoredSession();
      navigate(`/meetings/${response.meeting_id}/processing`);
    },
    onError: (error) => {
      setState('disconnected');
      setAudioSaved(null);
      setErrorMessage(error instanceof Error ? error.message : '无法确认板端录音是否已结束');
    },
  });

  async function reconnect() {
    setReconnecting(true);
    await syncBoardStatus();
    setReconnecting(false);
  }

  function requestExit() {
    if (state === 'idle' || state === 'error') {
      navigate('/meetings');
      return;
    }
    setExitDialogOpen(true);
  }

  const clock = formatClock(elapsedSeconds);
  const recentMeetings = recentMeetingsQuery.data?.items.slice(0, 2) ?? [];
  const canStart = state === 'idle' || state === 'error';
  const recording = state === 'recording';
  const meetingCreated = Boolean(createdMeetingIdRef.current || meetingId);
  const recorderClass = recording
    ? 'pc-recorder pc-recorder-recording board-recorder'
    : 'pc-recorder board-recorder';
  const deviceState = state === 'recording'
    ? '板端已连接'
    : state === 'starting'
      ? '正在连接'
      : state === 'stopping'
        ? '正在结束'
        : state === 'disconnected'
          ? '连接中断'
          : state === 'error'
            ? '不可用'
            : '等待开始';
  const boardBadge = state === 'recording'
    ? `${selectedDevice.name} · 麦克风录音中`
    : state === 'disconnected'
      ? `${selectedDevice.name} · 状态待确认`
      : `${selectedDevice.name} · 开始时检查`;
  const storageState = audioSaved === true
    ? recording ? '正在保存' : '已确认保存'
    : audioSaved === false
      ? '未保存'
      : state === 'disconnected'
        ? '状态待确认'
        : '开始时检查';

  return (
    <>
      <div className="pc-record-layout board-record-layout">
        <aside className="pc-record-sidebar">
          <Brand />
          <nav className="pc-record-side-nav" aria-label="主导航">
            <Link className="pc-record-side-link" to="/meetings"><span>会议库</span><span>›</span></Link>
            <span className="pc-record-side-link pc-record-side-link-active"><span>新建会议</span><span>板端录音</span></span>
          </nav>
          <div className="pc-record-list-label">最近会议</div>
          <div className="pc-record-meeting-list">
            {recentMeetings.map((meeting) => (
              <Link className="pc-record-meeting-item" to={meetingTarget(meeting)} key={meeting.meeting_id}>
                <span className="pc-record-meeting-name">{meeting.title}</span>
                <span className="pc-record-meeting-meta"><span>{formatDuration(meeting.audio.duration_ms)}</span><span>{formatMeetingDate(meeting.meeting_date)}</span></span>
              </Link>
            ))}
          </div>
          <div className="pc-record-sidebar-foot">
            <span className={`pc-record-live-dot board-record-live-dot-${state}`} />
            <span>{recording ? '局域网控制已连接' : state === 'disconnected' ? '控制连接已中断' : '开始时检查本地通道'}</span>
          </div>
        </aside>

        <main className="pc-record-main">
          <header className="pc-record-topbar">
            <div className="pc-record-crumb"><Link to="/meetings">会议库</Link><span>/</span><span>新建会议</span><span>/</span><strong>板端录音</strong></div>
            <button className="pc-record-quiet-button" type="button" disabled={state === 'stopping'} onClick={requestExit}>退出录音</button>
          </header>

          <div className="pc-record-content">
            <div className="pc-record-eyebrow">板端录音</div>
            <h1>{pageHeading(state)}</h1>
            <div className={`pc-record-context pc-record-context-${state}`}><span className="pc-record-status-dot" /><span>{stateLabel(state)}</span></div>

            <div className="pc-record-setup-grid">
              <label className="pc-record-field">
                <span>会议名称</span>
                <input value={title} maxLength={200} autoComplete="off" disabled={meetingCreated || state === 'starting'} onChange={(event) => setTitle(event.target.value)} />
              </label>
              <label className="pc-record-field">
                <span>录音设备</span>
                <select value={selectedDeviceId} disabled={!canStart || startMutation.isPending} onChange={(event) => setSelectedDeviceId(event.target.value)}>
                  {boardDevices.map((device) => <option value={device.id} key={device.id}>{device.name}</option>)}
                </select>
              </label>
            </div>

            <section className={recorderClass} aria-labelledby="boardRecorderTitle">
              <div className="pc-recorder-head"><div className="pc-recorder-title" id="boardRecorderTitle">远程录音控制</div><div className={`pc-device-state pc-device-state-${state}`}>{deviceState}</div></div>
              <div className="pc-recorder-body">
                <div className={`board-record-badge board-record-badge-${state}`}>{boardBadge}</div>
                <div className="pc-record-timer board-record-timer">{clock}</div>
                <div className="pc-record-timer-caption">
                  {recording
                    ? '音频正在板端保存'
                    : state === 'stopping'
                      ? '正在关闭板端录音文件'
                      : state === 'disconnected'
                        ? '等待重新确认板端录音状态'
                        : '板端录音尚未开始'}
                </div>
                <div className="pc-record-waveform" aria-hidden="true">
                  {waveformBars.map((bar, index) => (
                    <span
                      className="pc-record-wave-bar"
                      key={index}
                      style={{
                        height: `${bar.height}px`,
                        animationDuration: `${bar.speed}s`,
                        animationDelay: `${bar.delay}s`,
                      }}
                    />
                  ))}
                </div>
                <div className="pc-record-controls">
                  <button
                    className="pc-record-control pc-record-control-primary board-record-primary"
                    type="button"
                    disabled={!canStart || startMutation.isPending}
                    onClick={() => startMutation.mutate()}
                  >
                    {state === 'starting'
                      ? '正在连接'
                      : state === 'recording'
                        ? '板端录音中'
                        : state === 'stopping'
                          ? '正在结束'
                          : state === 'error' && meetingCreated
                            ? '重新连接'
                            : '开始板端录音'}
                  </button>
                  <button className="pc-record-control pc-record-control-stop" type="button" disabled={!recording} onClick={() => setStopDialogOpen(true)}>结束录音</button>
                </div>
                {errorMessage && state !== 'disconnected' ? <div className="pc-record-error" role="alert">{errorMessage}</div> : null}
              </div>
            </section>

            <div className="pc-record-route" aria-label="板端录音处理链路">
              <div className="pc-record-route-node"><strong>PC 控制</strong><span>创建与查看状态</span></div>
              <span className="pc-record-route-arrow" />
              <div className="pc-record-route-node"><strong>RK1828 采集</strong><span>板端保存音频</span></div>
              <span className="pc-record-route-arrow" />
              <div className="pc-record-route-node"><strong>板端处理</strong><span>结果返回会议库</span></div>
            </div>
          </div>
        </main>

        <aside className="pc-record-inspector">
          <div className="pc-record-inspector-head"><div className="pc-record-inspector-title">板端信息</div></div>
          <div className="pc-record-inspector-body">
            <div className="pc-record-detail-group">
              <div className="pc-record-detail-row"><span>设备</span><strong>{selectedDevice.name}</strong></div>
              <div className="pc-record-detail-row"><span>来源</span><strong>板端麦克风</strong></div>
              <div className="pc-record-detail-row"><span>当前时长</span><strong className="mono">{clock}</strong></div>
              <div className="pc-record-detail-row"><span>录音会话</span><strong>{recordingId ?? '尚未创建'}</strong></div>
            </div>
            <div className="pc-record-section-title">设备状态</div>
            <div className="pc-record-check-list">
              <div className="pc-record-check-item"><span className={`pc-record-check-dot board-record-check-dot-${state}`} /><span>板端麦克风</span><span>{recording ? '录音中' : state === 'disconnected' ? '状态待确认' : '开始时检查'}</span></div>
              <div className="pc-record-check-item"><span className={`pc-record-check-dot board-record-check-dot-${state}`} /><span>局域网控制</span><span>{deviceState}</span></div>
              <div className="pc-record-check-item"><span className={`pc-record-check-dot board-record-check-dot-${audioSaved === true ? 'saved' : state}`} /><span>板端存储</span><span>{storageState}</span></div>
            </div>
            <div className="pc-record-privacy-note">录音与后续处理均在 RK1828 完成，PC 只发送控制指令并读取状态。</div>
          </div>
        </aside>
      </div>

      {stopDialogOpen ? (
        <div className="pc-record-dialog-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setStopDialogOpen(false); }}>
          <section className="pc-record-dialog" role="dialog" aria-modal="true" aria-labelledby="boardStopTitle">
            <h2 id="boardStopTitle">结束板端录音？</h2>
            <p>结束后板端将关闭录音文件，并进入会议处理流程。</p>
            <div className="pc-record-dialog-time mono">{clock}</div>
            <div className="pc-record-dialog-actions">
              <button className="pc-record-control" type="button" onClick={() => setStopDialogOpen(false)}>继续录音</button>
              <button className="pc-record-control pc-record-control-primary" type="button" disabled={stopMutation.isPending} onClick={() => stopMutation.mutate()}>结束并处理</button>
            </div>
          </section>
        </div>
      ) : null}

      {state === 'disconnected' ? (
        <div className="pc-record-dialog-backdrop">
          <section className="pc-record-dialog" role="dialog" aria-modal="true" aria-labelledby="boardDisconnectedTitle">
            <h2 id="boardDisconnectedTitle">与 RK1828 的连接已中断</h2>
            <p>{errorMessage ?? '无法确认板端录音是否仍在进行。重新连接后再读取板端状态。'}</p>
            <div className="pc-record-dialog-time board-record-unknown-state">录音状态待确认</div>
            <div className="pc-record-dialog-actions">
              <button className="pc-record-control" type="button" onClick={() => navigate('/meetings')}>返回会议库</button>
              <button className="pc-record-control pc-record-control-primary" type="button" disabled={reconnecting} onClick={() => void reconnect()}>{reconnecting ? '连接中' : '重新连接'}</button>
            </div>
          </section>
        </div>
      ) : null}

      {exitDialogOpen ? (
        <div className="pc-record-dialog-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setExitDialogOpen(false); }}>
          <section className="pc-record-dialog" role="dialog" aria-modal="true" aria-labelledby="boardExitTitle">
            <h2 id="boardExitTitle">退出板端录音页面？</h2>
            <p>退出页面不会结束板端录音，RK1828 将继续保存音频。</p>
            <div className="pc-record-dialog-actions">
              <button className="pc-record-control" type="button" onClick={() => setExitDialogOpen(false)}>继续录音</button>
              <button className="pc-record-control pc-record-control-stop" type="button" onClick={() => navigate('/meetings')}>退出页面</button>
            </div>
          </section>
        </div>
      ) : null}
    </>
  );
}
