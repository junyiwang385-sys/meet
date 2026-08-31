import { useQuery } from '@tanstack/react-query';
import { useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { meetingApi } from '../../api';
import type { MeetingDetail } from '../../api/types';
import { Brand } from '../../components/Brand';
import { PauseIcon, PlayIcon, SearchIcon } from '../../components/Icons';
import { Toast } from '../../components/Toast';
import './MeetingPlaybackPage.css';

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

function getErrorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

function HighlightedText({ text, query }: { text: string; query: string }): ReactNode {
  const needle = query.trim().toLocaleLowerCase('zh-CN');
  if (!needle) return text;
  const haystack = text.toLocaleLowerCase('zh-CN');
  const index = haystack.indexOf(needle);
  if (index < 0) return text;
  return (
    <>
      {text.slice(0, index)}
      <mark>{text.slice(index, index + needle.length)}</mark>
      {text.slice(index + needle.length)}
    </>
  );
}

function PlaybackPageState({
  title,
  copy,
  action,
}: {
  title: string;
  copy: string;
  action?: ReactNode;
}) {
  return (
    <div className="playback-state-layout">
      <aside className="playback-state-sidebar"><Brand /></aside>
      <main className="playback-state-main">
        <div className="playback-state-card">
          <span className="playback-state-mark" />
          <h1>{title}</h1>
          <p>{copy}</p>
          {action ? <div className="playback-state-action">{action}</div> : null}
        </div>
      </main>
    </div>
  );
}

function canReadDraft(detail: MeetingDetail | undefined): boolean {
  return Boolean(detail && ['review_ready', 'finalizing', 'finalized'].includes(detail.state));
}

function isKnownSpeaker(id: string | null | undefined): boolean {
  const normalized = id?.trim().toLowerCase();
  return Boolean(normalized) && normalized !== 'unknown';
}

// 仅为全文回放计算展示标签，不改写原始 speaker_id。
function carryOverUnknownSpeakers(ids: string[]): string[] {
  const carried = ids.map((id) => (isKnownSpeaker(id) ? id.trim() : 'unknown'));
  let last: string | null = null;
  for (let i = 0; i < carried.length; i += 1) {
    if (isKnownSpeaker(carried[i])) last = carried[i];
    else if (last !== null) carried[i] = last;
  }
  let next: string | null = null;
  for (let i = carried.length - 1; i >= 0; i -= 1) {
    if (isKnownSpeaker(carried[i])) next = carried[i];
    else if (next !== null) carried[i] = next;
  }
  return carried;
}

function playbackSpeakerName(
  speakerNames: Map<string, string>,
  speakerId: string,
): string {
  return isKnownSpeaker(speakerId)
    ? speakerNames.get(speakerId) ?? speakerId
    : '未识别';
}

function audioStateLabel(detail: MeetingDetail): string {
  if (detail.audio.state === 'deleted') return '原始音频已删除';
  if (detail.audio.state === 'missing') return '原始音频缺失';
  if (detail.audio.state === 'unreadable') return '原始音频不可读取';
  return detail.audio.playable ? '原始音频可用' : '原始音频不可播放';
}

export function MeetingPlaybackPage() {
  const { meetingId = '' } = useParams();
  const [searchParams] = useSearchParams();
  const audioRef = useRef<HTMLAudioElement>(null);
  const initialSeekApplied = useRef(false);
  const toastTimer = useRef<number | null>(null);
  const [query, setQuery] = useState('');
  const [currentMs, setCurrentMs] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [playbackRate, setPlaybackRate] = useState(1);
  const [audioError, setAudioError] = useState(false);
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
    enabled: Boolean(meetingId && detail?.availability.transcript),
    retry: false,
  });

  const draftQuery = useQuery({
    queryKey: ['meeting-draft', meetingId],
    queryFn: () => meetingApi.getMeetingDraft(meetingId),
    enabled: Boolean(meetingId && resultQuery.data && canReadDraft(detail)),
    retry: false,
  });

  const result = resultQuery.data;
  const draftContent = draftQuery.data?.content;
  const durationMs = result?.duration_ms ?? detail?.audio.duration_ms ?? 0;
  const audioAvailable = Boolean(
    detail?.audio.state === 'available'
      && detail.audio.playable
      && detail.capabilities.can_play_audio,
  );
  const audioUrl = useMemo(
    () => (audioAvailable ? meetingApi.getMeetingAudioUrl(meetingId) : null),
    [audioAvailable, meetingId],
  );

  const title = draftContent?.title ?? detail?.title ?? '';
  const speakerNames = useMemo(() => {
    if (!result) return new Map<string, string>();
    return new Map((result.speakers ?? []).map((speaker) => [
      speaker.speaker_id,
      draftContent?.speaker_names[speaker.speaker_id] ?? speaker.display_name,
    ]));
  }, [draftContent?.speaker_names, result]);

  const segments = useMemo(() => {
    if (!result?.transcript) return [];
    const edits = new Map(draftContent?.transcript_edits.map((edit) => [edit.segment_id, edit]) ?? []);
    const applied = result.transcript.segments.map((segment) => {
      const edit = edits.get(segment.segment_id);
      return {
        ...segment,
        text: edit?.text ?? segment.text,
        speaker_id: edit?.speaker_id ?? segment.speaker_id,
      };
    });
    const displaySpeakerIds = carryOverUnknownSpeakers(
      applied.map((segment) => segment.speaker_id),
    );
    return applied.map((segment, index) => ({
      ...segment,
      display_speaker_id: displaySpeakerIds[index] ?? segment.speaker_id,
    }));
  }, [draftContent?.transcript_edits, result]);

  const visibleSegments = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase('zh-CN');
    if (!needle) return segments;
    return segments.filter((segment) => {
      const speaker = playbackSpeakerName(speakerNames, segment.display_speaker_id);
      return segment.text.toLocaleLowerCase('zh-CN').includes(needle)
        || speaker.toLocaleLowerCase('zh-CN').includes(needle);
    });
  }, [query, segments, speakerNames]);

  const activeSegmentId = useMemo(() => {
    let active: string | null = null;
    for (const segment of segments) {
      if (segment.start_ms > currentMs) break;
      active = segment.segment_id;
    }
    return active;
  }, [currentMs, segments]);

  useEffect(() => {
    initialSeekApplied.current = false;
    setCurrentMs(0);
    setPlaying(false);
    setAudioError(false);
  }, [meetingId]);

  useEffect(() => {
    if (initialSeekApplied.current || segments.length === 0) return;
    const segmentId = searchParams.get('segment');
    const requestedMs = Number(searchParams.get('t'));
    const targetSegment = segmentId
      ? segments.find((segment) => segment.segment_id === segmentId)
      : undefined;
    const targetMs = targetSegment?.start_ms
      ?? (Number.isFinite(requestedMs) && requestedMs >= 0 ? requestedMs : null);
    initialSeekApplied.current = true;
    if (targetMs === null) return;
    setCurrentMs(Math.min(durationMs, targetMs));
    if (targetSegment) {
      window.requestAnimationFrame(() => {
        document.getElementById(`playback-${targetSegment.segment_id}`)?.scrollIntoView({
          block: 'center',
        });
      });
    }
  }, [durationMs, searchParams, segments]);

  useEffect(() => {
    if (!playing || audioUrl || !audioAvailable || durationMs <= 0) return;
    const timer = window.setInterval(() => {
      setCurrentMs((value) => {
        const next = value + 250 * playbackRate;
        if (next >= durationMs) {
          setPlaying(false);
          return durationMs;
        }
        return next;
      });
    }, 250);
    return () => window.clearInterval(timer);
  }, [audioAvailable, audioUrl, durationMs, playbackRate, playing]);

  useEffect(() => {
    if (audioRef.current) audioRef.current.playbackRate = playbackRate;
  }, [playbackRate]);

  useEffect(() => () => {
    if (toastTimer.current !== null) window.clearTimeout(toastTimer.current);
  }, []);

  function showToast(message: string) {
    setToast(message);
    if (toastTimer.current !== null) window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), 2400);
  }

  function seekTo(milliseconds: number, segmentId?: string) {
    const bounded = Math.max(0, Math.min(durationMs, milliseconds));
    setCurrentMs(bounded);
    if (audioRef.current) audioRef.current.currentTime = bounded / 1000;
    if (segmentId) {
      document.getElementById(`playback-${segmentId}`)?.scrollIntoView({
        behavior: 'smooth',
        block: 'center',
      });
    }
  }

  async function togglePlayback() {
    if (!audioAvailable || audioError) return;
    if (!audioUrl) {
      setPlaying((value) => !value);
      return;
    }

    const audio = audioRef.current;
    if (!audio) return;
    try {
      if (audio.paused) {
        audio.playbackRate = playbackRate;
        await audio.play();
      } else {
        audio.pause();
      }
    } catch {
      setAudioError(true);
      setPlaying(false);
      showToast('原始音频暂时无法播放');
    }
  }

  function handleTurnDoubleClick(startMs: number, segmentId: string) {
    seekTo(startMs, segmentId);
    if (!playing) void togglePlayback();
  }

  if (detailQuery.isPending) {
    return <PlaybackPageState title="正在打开全文" copy="正在读取会议与音频状态。" />;
  }

  if (detailQuery.isError || !detail) {
    return (
      <PlaybackPageState
        title="无法打开会议"
        copy={getErrorMessage(detailQuery.error, '会议不存在或暂时无法读取。')}
        action={<Link className="secondary-button compact-button" to="/meetings">返回会议库</Link>}
      />
    );
  }

  if (!detail.availability.transcript) {
    return (
      <PlaybackPageState
        title="全文尚未生成"
        copy="转写完成后可进入全文回放。"
        action={<Link className="primary-button compact-button" to={`/meetings/${meetingId}/processing`}>查看处理进度</Link>}
      />
    );
  }

  if (resultQuery.isPending || !result) {
    return <PlaybackPageState title="正在准备全文" copy="正在读取转写结果。" />;
  }

  if (resultQuery.isError) {
    return (
      <PlaybackPageState
        title="全文读取失败"
        copy={getErrorMessage(resultQuery.error, '无法读取会议全文。')}
        action={<Link className="secondary-button compact-button" to={`/meetings/${meetingId}/review`}>返回工作区</Link>}
      />
    );
  }

  const playerAvailable = audioAvailable && !audioError;
  const progress = durationMs > 0 ? Math.min(durationMs, currentMs) : 0;

  return (
    <>
      <div className="playback-layout">
        <aside className="playback-sidebar">
          <Brand />
          <Link className="playback-meeting-back" to="/meetings">‹ 返回会议库</Link>
          <div className="playback-meeting-identity">
            <div className="playback-meeting-label">当前会议</div>
            <div className="playback-meeting-title">{title}</div>
            <div className="playback-meeting-meta">{formatMeetingDay(detail.meeting_date)} · {formatTimestamp(durationMs)}</div>
          </div>
          <div className="playback-nav-label">会议内容</div>
          <nav className="playback-side-nav" aria-label="会议内容">
            <Link className="playback-side-link" to={`/meetings/${meetingId}/review`}><span>会议工作区</span><span>›</span></Link>
            <span className="playback-side-link playback-side-link-active"><span>全文回放</span><span>{formatTimestamp(durationMs)}</span></span>
          </nav>
          <div className="playback-sidebar-foot">{audioStateLabel(detail)}</div>
        </aside>

        <main className="playback-main">
          <header className="playback-topbar">
            <div className="playback-crumb">
              <Link to="/meetings">会议库</Link><span>/</span><span>{title}</span><span>/</span><strong>全文回放</strong>
            </div>
            <Link className="playback-top-button" to={`/meetings/${meetingId}/review`}>返回工作区</Link>
          </header>

          <div className="playback-content">
            <header className="playback-page-head">
              <div>
                <div className="playback-eyebrow">全文回放</div>
                <h1>{title}</h1>
                <div className="playback-page-meta">
                  <span>{result.speakers?.length ?? 0} 位发言人</span>
                  <span>{formatTimestamp(durationMs)}</span>
                  <span>{audioStateLabel(detail)}</span>
                </div>
              </div>
              <label className="playback-search">
                <SearchIcon />
                <input type="search" value={query} placeholder="搜索全文" onChange={(event) => setQuery(event.target.value)} />
              </label>
            </header>

            <section className={playerAvailable ? 'playback-player' : 'playback-player playback-player-disabled'} aria-label="音频播放器">
              <div className="playback-player-row">
                <button className="playback-play-button" type="button" aria-label={playing ? '暂停' : '播放'} disabled={!playerAvailable} onClick={() => void togglePlayback()}>
                  {playing ? <PauseIcon /> : <PlayIcon />}
                </button>
                <span className="playback-time">{formatTimestamp(currentMs)} / {formatTimestamp(durationMs)}</span>
                <input
                  className="playback-timeline"
                  type="range"
                  min={0}
                  max={Math.max(1, durationMs)}
                  step={100}
                  value={progress}
                  disabled={!playerAvailable}
                  aria-label="播放位置"
                  onChange={(event) => seekTo(Number(event.target.value))}
                />
                <select className="playback-speed" value={playbackRate} disabled={!playerAvailable} aria-label="播放速度" onChange={(event) => setPlaybackRate(Number(event.target.value))}>
                  <option value={1}>1.0×</option>
                  <option value={1.25}>1.25×</option>
                  <option value={1.5}>1.5×</option>
                  <option value={2}>2.0×</option>
                </select>
              </div>
              {!playerAvailable ? <div className="playback-audio-state">{audioStateLabel(detail)}，全文仍可查看</div> : null}
              {audioUrl ? (
                <audio
                  ref={audioRef}
                  src={audioUrl}
                  preload="metadata"
                  onLoadedMetadata={(event) => {
                    if (currentMs > 0) event.currentTarget.currentTime = currentMs / 1000;
                  }}
                  onPlay={() => setPlaying(true)}
                  onPause={() => setPlaying(false)}
                  onEnded={() => setPlaying(false)}
                  onTimeUpdate={(event) => setCurrentMs(event.currentTarget.currentTime * 1000)}
                  onError={() => {
                    setAudioError(true);
                    setPlaying(false);
                  }}
                />
              ) : null}
            </section>

            <section className="playback-transcript" aria-label="会议全文">
              {visibleSegments.map((segment) => (
                <article
                  className={activeSegmentId === segment.segment_id ? 'playback-turn playback-turn-active' : 'playback-turn'}
                  id={`playback-${segment.segment_id}`}
                  key={segment.segment_id}
                  onDoubleClick={() => handleTurnDoubleClick(segment.start_ms, segment.segment_id)}
                >
                  <div className="playback-turn-header">
                    <span className="playback-speaker">{playbackSpeakerName(speakerNames, segment.display_speaker_id)}:</span>
                    <button className="playback-turn-time" type="button" onClick={() => seekTo(segment.start_ms, segment.segment_id)}>{formatTimestamp(segment.start_ms)}</button>
                  </div>
                  <p className="playback-turn-copy"><HighlightedText text={segment.text} query={query} /></p>
                </article>
              ))}
              {visibleSegments.length === 0 ? <div className="playback-empty">没有匹配的转写内容</div> : null}
            </section>
          </div>
        </main>
      </div>
      <Toast message={toast} />
    </>
  );
}
