import { useMutation, useQuery } from '@tanstack/react-query';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { meetingApi } from '../../api';
import { formatDuration, formatMeetingDate, getStorageInsufficientDetails } from '../../api/meeting-api';
import type { MeetingListItem } from '../../api/types';
import { useUploadDraft } from '../../app/upload-draft';
import { Brand } from '../../components/Brand';
import './PcRecordingPage.css';

type RecorderState =
  | 'idle'
  | 'requesting'
  | 'recording'
  | 'paused'
  | 'stopping'
  | 'finished'
  | 'uploading'
  | 'error';

interface RecordingFormat {
  mimeType: string;
  extension: string;
}

const waveformBars = Array.from({ length: 42 }, (_, index) => ({
  height: 16 + ((index * 17) % 49),
  speed: 0.48 + ((index * 7) % 7) * 0.07,
  delay: -((index * 3) % 10) / 10,
}));

function formatClock(milliseconds: number): string {
  const totalSeconds = Math.max(0, Math.floor(milliseconds / 1000));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
}

function selectRecordingFormat(): RecordingFormat {
  const candidates: RecordingFormat[] = [
    { mimeType: 'audio/mp4;codecs=mp4a.40.2', extension: 'm4a' },
    { mimeType: 'audio/mp4', extension: 'm4a' },
    { mimeType: 'audio/ogg;codecs=opus', extension: 'ogg' },
    { mimeType: 'audio/webm;codecs=opus', extension: 'webm' },
    { mimeType: 'audio/webm', extension: 'webm' },
  ];
  return candidates.find((candidate) => MediaRecorder.isTypeSupported(candidate.mimeType))
    ?? { mimeType: '', extension: 'webm' };
}

function recorderErrorMessage(error: unknown): string {
  if (error instanceof DOMException) {
    if (error.name === 'NotAllowedError' || error.name === 'SecurityError') return '麦克风权限未开启';
    if (error.name === 'NotFoundError' || error.name === 'OverconstrainedError') return '未检测到可用的麦克风';
    if (error.name === 'NotReadableError') return '麦克风正在被其他程序使用';
  }
  return error instanceof Error && error.message ? error.message : '无法使用麦克风';
}

function meetingTarget(meeting: MeetingListItem): string {
  if (meeting.state === 'review_ready' || meeting.state === 'finalized' || meeting.state === 'finalizing') {
    return `/meetings/${meeting.meeting_id}/review`;
  }
  return `/meetings/${meeting.meeting_id}/processing`;
}

function stateHeading(state: RecorderState): string {
  if (state === 'requesting') return '正在连接麦克风';
  if (state === 'recording') return '正在录音';
  if (state === 'paused') return '录音已暂停';
  if (state === 'stopping') return '正在保存录音';
  if (state === 'finished') return '录音已结束';
  if (state === 'uploading') return '正在创建会议';
  if (state === 'error') return '无法开始录音';
  return '准备录音';
}

function stateLabel(state: RecorderState): string {
  if (state === 'requesting') return '正在请求麦克风权限';
  if (state === 'recording') return '正在录音';
  if (state === 'paused') return '录音已暂停';
  if (state === 'stopping') return '正在保存本地录音';
  if (state === 'finished') return '录音已保留';
  if (state === 'uploading') return '正在发送完整录音';
  if (state === 'error') return '麦克风不可用';
  return '等待开始';
}

export function PcRecordingPage() {
  const navigate = useNavigate();
  const { setFile: setPendingFile, setStorageIssue } = useUploadDraft();
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const formatRef = useRef<RecordingFormat>({ mimeType: '', extension: 'webm' });
  const accumulatedMsRef = useRef(0);
  const clockStartedAtRef = useRef<number | null>(null);
  const resumeAfterDialogRef = useRef(false);
  const createdMeetingIdRef = useRef<string | null>(null);

  const [state, setState] = useState<RecorderState>('idle');
  const [title, setTitle] = useState('未命名会议');
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]);
  const [selectedDeviceId, setSelectedDeviceId] = useState('');
  const [elapsedMs, setElapsedMs] = useState(0);
  const [recordedFile, setRecordedFile] = useState<File | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [stopDialogOpen, setStopDialogOpen] = useState(false);
  const [exitDialogOpen, setExitDialogOpen] = useState(false);

  const recentMeetingsQuery = useQuery({
    queryKey: ['meetings', 'pc-record-recent'],
    queryFn: () => meetingApi.listMeetings({ sort: 'updated_desc' }),
  });

  const refreshDevices = useCallback(async () => {
    if (!navigator.mediaDevices?.enumerateDevices) return;
    const allDevices = await navigator.mediaDevices.enumerateDevices();
    setDevices(allDevices.filter((device) => device.kind === 'audioinput'));
  }, []);

  useEffect(() => {
    void refreshDevices().catch(() => undefined);
    const mediaDevices = navigator.mediaDevices;
    if (!mediaDevices?.addEventListener) return;
    const handleDeviceChange = () => void refreshDevices().catch(() => undefined);
    mediaDevices.addEventListener('devicechange', handleDeviceChange);
    return () => mediaDevices.removeEventListener('devicechange', handleDeviceChange);
  }, [refreshDevices]);

  useEffect(() => {
    if (state !== 'recording') return;
    const timer = window.setInterval(() => {
      const startedAt = clockStartedAtRef.current;
      if (startedAt === null) return;
      setElapsedMs(accumulatedMsRef.current + performance.now() - startedAt);
    }, 200);
    return () => window.clearInterval(timer);
  }, [state]);

  useEffect(() => {
    const active = ['requesting', 'recording', 'paused', 'stopping', 'uploading'].includes(state)
      || Boolean(recordedFile);
    if (!active) return;
    const handleBeforeUnload = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener('beforeunload', handleBeforeUnload);
    return () => window.removeEventListener('beforeunload', handleBeforeUnload);
  }, [recordedFile, state]);

  useEffect(() => () => {
    const recorder = mediaRecorderRef.current;
    if (recorder && recorder.state !== 'inactive') recorder.stop();
    streamRef.current?.getTracks().forEach((track) => track.stop());
  }, []);

  const processRecording = useMutation({
    mutationFn: async (file: File) => {
      setState('uploading');
      let meetingId = createdMeetingIdRef.current;
      if (!meetingId) {
        const created = await meetingApi.createMeeting({
          title: title.trim() || '未命名会议',
          source_type: 'pc_record',
          language: 'zh-CN',
          source_file: {
            name: file.name,
            size_bytes: file.size,
            mime_type: file.type || 'application/octet-stream',
            last_modified_at: new Date(file.lastModified).toISOString(),
          },
        });
        meetingId = created.meeting_id;
        createdMeetingIdRef.current = meetingId;
      }
      await meetingApi.uploadAudio(meetingId, file);
      return meetingId;
    },
    onSuccess: (meetingId) => {
      setPendingFile(null);
      setStorageIssue(null);
      navigate(`/meetings/${meetingId}/processing`);
    },
    onError: (error, file) => {
      const storage = getStorageInsufficientDetails(error);
      const meetingId = createdMeetingIdRef.current;
      if (storage && meetingId) {
        setPendingFile(file);
        setStorageIssue({
          meetingId,
          title: title.trim() || '未命名会议',
          sourceType: 'pc_record',
          fileName: file.name,
          fileSizeBytes: file.size,
          requiredBytes: Math.max(storage.requiredBytes, file.size),
          freeBytes: storage.freeBytes,
          returnPath: '/record/pc',
        });
        navigate('/storage/insufficient');
        return;
      }
      setState('finished');
      setErrorMessage(error instanceof Error ? error.message : '录音发送失败');
    },
  });

  function startClock(reset = false) {
    if (reset) {
      accumulatedMsRef.current = 0;
      setElapsedMs(0);
    }
    clockStartedAtRef.current = performance.now();
  }

  function pauseClock() {
    const startedAt = clockStartedAtRef.current;
    if (startedAt !== null) accumulatedMsRef.current += performance.now() - startedAt;
    clockStartedAtRef.current = null;
    setElapsedMs(accumulatedMsRef.current);
  }

  function releaseStream() {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
  }

  async function startRecording() {
    setErrorMessage(null);
    setRecordedFile(null);
    setPendingFile(null);
    setStorageIssue(null);
    createdMeetingIdRef.current = null;
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      setState('error');
      setErrorMessage('当前浏览器不支持麦克风录音');
      return;
    }

    setState('requesting');
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: selectedDeviceId
          ? {
              deviceId: { exact: selectedDeviceId },
              channelCount: 1,
              echoCancellation: true,
              noiseSuppression: true,
            }
          : {
              channelCount: 1,
              echoCancellation: true,
              noiseSuppression: true,
            },
      });
      streamRef.current = stream;
      await refreshDevices();
      const format = selectRecordingFormat();
      formatRef.current = format;
      chunksRef.current = [];
      const recorder = format.mimeType
        ? new MediaRecorder(stream, { mimeType: format.mimeType })
        : new MediaRecorder(stream);
      mediaRecorderRef.current = recorder;
      recorder.addEventListener('dataavailable', (event) => {
        if (event.data.size > 0) chunksRef.current.push(event.data);
      });
      recorder.addEventListener('error', () => {
        pauseClock();
        setState('error');
        setErrorMessage('录音过程发生错误');
        releaseStream();
      });
      recorder.start(1000);
      startClock(true);
      setState('recording');
    } catch (error) {
      releaseStream();
      setState('error');
      setErrorMessage(recorderErrorMessage(error));
    }
  }

  function togglePause() {
    const recorder = mediaRecorderRef.current;
    if (!recorder) return;
    if (state === 'recording' && recorder.state === 'recording') {
      recorder.pause();
      pauseClock();
      setState('paused');
      return;
    }
    if (state === 'paused' && recorder.state === 'paused') {
      recorder.resume();
      startClock();
      setState('recording');
    }
  }

  function requestStop() {
    const recorder = mediaRecorderRef.current;
    if (!recorder || !['recording', 'paused'].includes(state)) return;
    resumeAfterDialogRef.current = state === 'recording';
    if (state === 'recording' && recorder.state === 'recording') {
      recorder.pause();
      pauseClock();
      setState('paused');
    }
    setStopDialogOpen(true);
  }

  function continueRecording() {
    setStopDialogOpen(false);
    if (!resumeAfterDialogRef.current) return;
    const recorder = mediaRecorderRef.current;
    if (recorder?.state === 'paused') {
      recorder.resume();
      startClock();
      setState('recording');
    }
  }

  function stopRecorder(): Promise<File> {
    const recorder = mediaRecorderRef.current;
    if (!recorder) return Promise.reject(new Error('录音尚未开始'));
    return new Promise((resolve, reject) => {
      const handleStop = () => {
        const mimeType = recorder.mimeType || formatRef.current.mimeType || 'audio/webm';
        const blob = new Blob(chunksRef.current, { type: mimeType });
        const now = new Date();
        const stamp = [
          now.getFullYear(),
          String(now.getMonth() + 1).padStart(2, '0'),
          String(now.getDate()).padStart(2, '0'),
          '-',
          String(now.getHours()).padStart(2, '0'),
          String(now.getMinutes()).padStart(2, '0'),
          String(now.getSeconds()).padStart(2, '0'),
        ].join('');
        const file = new File(
          [blob],
          `pc-recording-${stamp}.${formatRef.current.extension}`,
          { type: mimeType, lastModified: Date.now() },
        );
        releaseStream();
        resolve(file);
      };
      const handleError = () => reject(new Error('录音文件生成失败'));
      recorder.addEventListener('stop', handleStop, { once: true });
      recorder.addEventListener('error', handleError, { once: true });
      recorder.stop();
    });
  }

  async function confirmStop() {
    setStopDialogOpen(false);
    pauseClock();
    setState('stopping');
    try {
      const file = await stopRecorder();
      setRecordedFile(file);
      setState('finished');
      processRecording.mutate(file);
    } catch (error) {
      setState('error');
      setErrorMessage(recorderErrorMessage(error));
    }
  }

  function requestExit() {
    if (state === 'idle' || state === 'error') {
      navigate('/meetings');
      return;
    }
    setExitDialogOpen(true);
  }

  function discardAndExit() {
    const recorder = mediaRecorderRef.current;
    if (recorder && recorder.state !== 'inactive') recorder.stop();
    releaseStream();
    navigate('/meetings');
  }

  const deviceName = devices.find((device) => device.deviceId === selectedDeviceId)?.label
    || (selectedDeviceId ? '已选择麦克风' : '系统默认麦克风');
  const clock = formatClock(elapsedMs);
  const recordingActive = state === 'recording';
  const paused = state === 'paused';
  const canStart = ['idle', 'error'].includes(state);
  const canPause = recordingActive || paused;
  const canStop = recordingActive || paused;
  const canRetryProcess = state === 'finished' && Boolean(recordedFile);
  const heading = stateHeading(state);
  const recentMeetings = recentMeetingsQuery.data?.items.slice(0, 2) ?? [];
  const deviceState = state === 'requesting'
    ? '请求权限'
    : state === 'error'
      ? '不可用'
      : recordingActive
        ? '录音中'
        : paused
          ? '已暂停'
          : streamRef.current
            ? '已连接'
            : '待授权';
  const recorderClass = recordingActive
    ? 'pc-recorder pc-recorder-recording'
    : paused
      ? 'pc-recorder pc-recorder-paused'
      : 'pc-recorder';

  return (
    <>
      <div className="pc-record-layout">
        <aside className="pc-record-sidebar">
          <Brand />
          <nav className="pc-record-side-nav" aria-label="主导航">
            <Link className="pc-record-side-link" to="/meetings"><span>会议库</span><span>›</span></Link>
            <span className="pc-record-side-link pc-record-side-link-active"><span>新建会议</span><span>PC 录音</span></span>
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
          <div className="pc-record-sidebar-foot"><span className="pc-record-live-dot" /><span>录音保存在当前电脑</span></div>
        </aside>

        <main className="pc-record-main">
          <header className="pc-record-topbar">
            <div className="pc-record-crumb"><Link to="/meetings">会议库</Link><span>/</span><span>新建会议</span><span>/</span><strong>PC 录音</strong></div>
            <button className="pc-record-quiet-button" type="button" disabled={state === 'uploading'} onClick={requestExit}>退出录音</button>
          </header>

          <div className="pc-record-content">
            <div className="pc-record-eyebrow">PC 录音</div>
            <h1>{heading}</h1>
            <div className={`pc-record-context pc-record-context-${state}`}><span className="pc-record-status-dot" /><span>{stateLabel(state)}</span></div>

            <div className="pc-record-setup-grid">
              <label className="pc-record-field">
                <span>会议名称</span>
                <input value={title} maxLength={200} autoComplete="off" disabled={state === 'uploading'} onChange={(event) => setTitle(event.target.value)} />
              </label>
              <label className="pc-record-field">
                <span>输入设备</span>
                <select value={selectedDeviceId} disabled={!canStart} onChange={(event) => setSelectedDeviceId(event.target.value)}>
                  <option value="">系统默认麦克风</option>
                  {devices.map((device, index) => (
                    <option value={device.deviceId} key={device.deviceId || `device-${index}`}>
                      {device.label || `麦克风 ${index + 1}`}
                    </option>
                  ))}
                </select>
              </label>
            </div>

            <section className={recorderClass} aria-labelledby="pcRecorderTitle">
              <div className="pc-recorder-head"><div className="pc-recorder-title" id="pcRecorderTitle">录音控制</div><div className={`pc-device-state pc-device-state-${state}`}>{deviceState}</div></div>
              <div className="pc-recorder-body">
                <div className="pc-record-timer">{clock}</div>
                <div className="pc-record-timer-caption">
                  {recordingActive
                    ? '录音正在保存在当前电脑'
                    : paused
                      ? '暂停期间不计入录音时长'
                      : state === 'finished'
                        ? '录音已保留在当前页面'
                        : state === 'uploading'
                          ? '正在发送完整录音'
                          : '录音尚未开始'}
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
                    className="pc-record-control pc-record-control-primary"
                    type="button"
                    disabled={(!canStart && !canRetryProcess) || state === 'requesting' || state === 'uploading'}
                    onClick={() => {
                      if (canRetryProcess && recordedFile) processRecording.mutate(recordedFile);
                      else void startRecording();
                    }}
                  >
                    {state === 'requesting'
                      ? '正在连接'
                      : state === 'recording'
                        ? '录音中'
                        : state === 'paused'
                          ? '录音已暂停'
                          : state === 'stopping'
                            ? '正在保存'
                            : state === 'uploading'
                              ? '正在处理'
                              : canRetryProcess
                                ? '重新处理'
                                : '开始录音'}
                  </button>
                  <button className="pc-record-control" type="button" disabled={!canPause} onClick={togglePause}>{paused ? '继续录音' : '暂停'}</button>
                  <button className="pc-record-control pc-record-control-stop" type="button" disabled={!canStop} onClick={requestStop}>结束录音</button>
                </div>
                {errorMessage ? <div className="pc-record-error" role="alert">{errorMessage}</div> : null}
              </div>
            </section>

            <div className="pc-record-route" aria-label="PC 录音处理链路">
              <div className="pc-record-route-node"><strong>PC 采集</strong><span>保留本地录音</span></div>
              <span className="pc-record-route-arrow" />
              <div className="pc-record-route-node"><strong>局域网发送</strong><span>结束后完整传输</span></div>
              <span className="pc-record-route-arrow" />
              <div className="pc-record-route-node"><strong>RK1828 处理</strong><span>结果返回会议库</span></div>
            </div>
          </div>
        </main>

        <aside className="pc-record-inspector">
          <div className="pc-record-inspector-head"><div className="pc-record-inspector-title">录音信息</div></div>
          <div className="pc-record-inspector-body">
            <div className="pc-record-detail-group">
              <div className="pc-record-detail-row"><span>来源</span><strong>PC 麦克风</strong></div>
              <div className="pc-record-detail-row"><span>会议名称</span><strong>{title.trim() || '未命名会议'}</strong></div>
              <div className="pc-record-detail-row"><span>当前时长</span><strong className="mono">{clock}</strong></div>
              <div className="pc-record-detail-row"><span>录音格式</span><strong>{formatRef.current.extension.toUpperCase()}</strong></div>
            </div>
            <div className="pc-record-section-title">设备状态</div>
            <div className="pc-record-check-list">
              <div className="pc-record-check-item"><span className={`pc-record-check-dot pc-record-check-dot-${state}`} /><span>PC 输入设备</span><span>{deviceState}</span></div>
              <div className="pc-record-check-item"><span className="pc-record-check-dot" /><span>输入来源</span><span>{deviceName}</span></div>
              <div className="pc-record-check-item"><span className="pc-record-check-dot" /><span>发送方式</span><span>结束后发送</span></div>
            </div>
            <div className="pc-record-privacy-note">录音先保存在当前电脑。结束后发送完整音频；网络中断时从头重试。</div>
          </div>
        </aside>
      </div>

      {stopDialogOpen ? (
        <div className="pc-record-dialog-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) continueRecording(); }}>
          <section className="pc-record-dialog" role="dialog" aria-modal="true" aria-labelledby="pcStopTitle">
            <h2 id="pcStopTitle">结束本次录音？</h2>
            <p>结束后将创建会议并发送完整录音。</p>
            <div className="pc-record-dialog-time mono">{clock}</div>
            <div className="pc-record-dialog-actions">
              <button className="pc-record-control" type="button" onClick={continueRecording}>{resumeAfterDialogRef.current ? '继续录音' : '返回录音'}</button>
              <button className="pc-record-control pc-record-control-primary" type="button" onClick={() => void confirmStop()}>结束并处理</button>
            </div>
          </section>
        </div>
      ) : null}

      {exitDialogOpen ? (
        <div className="pc-record-dialog-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setExitDialogOpen(false); }}>
          <section className="pc-record-dialog" role="dialog" aria-modal="true" aria-labelledby="pcExitTitle">
            <h2 id="pcExitTitle">退出本次录音？</h2>
            <p>尚未处理的录音不会进入会议库。</p>
            <div className="pc-record-dialog-actions">
              <button className="pc-record-control" type="button" onClick={() => setExitDialogOpen(false)}>{canPause ? '继续录音' : '返回页面'}</button>
              <button className="pc-record-control pc-record-control-stop" type="button" onClick={discardAndExit}>退出录音</button>
            </div>
          </section>
        </div>
      ) : null}
    </>
  );
}
