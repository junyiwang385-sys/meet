import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { Link, Navigate, useParams } from 'react-router-dom';
import { meetingApi } from '../../api';
import { formatDuration, formatFileSize } from '../../api/meeting-api';
import type {
  ExportFormat,
  MeetingDetail,
  MeetingDraft,
  MeetingDraftContent,
  MeetingExportsResponse,
  MeetingResultV1,
  ReviewStatus,
  TranscriptSegment,
} from '../../api/types';
import { Brand } from '../../components/Brand';
import {
  ChaptersIcon,
  MinutesIcon,
  PlayIcon,
  SearchIcon,
  SpeakersIcon,
  TasksIcon,
  TranscriptIcon,
} from '../../components/Icons';
import { Toast } from '../../components/Toast';
import './MeetingReviewPage.css';

type ReviewView = 'minutes' | 'transcript' | 'chapters' | 'speakers' | 'structured';
type StructuredKind = 'decision' | 'action';

interface SaveVariables {
  content: MeetingDraftContent;
  expectedRevision: number;
  baseResultRevision: number;
  editVersion: number;
}

interface FinalizeVariables {
  revision: number;
  formats: ExportFormat[];
}

const viewLabels: Record<ReviewView, string> = {
  minutes: '会议纪要',
  transcript: '全文转写',
  chapters: '章节',
  speakers: '发言人',
  structured: '决策与待办',
};

const exportLabels: Record<ExportFormat, string> = {
  html: 'HTML',
  txt: 'TXT',
  json: 'JSON',
};

function clone<T>(value: T): T {
  return structuredClone(value);
}

function getErrorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
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

function reviewStatusLabel(status: ReviewStatus): string {
  if (status === 'pending') return '待核对';
  if (status === 'edited') return '已编辑';
  return '已核对';
}

function meetingStateLabel(detail: MeetingDetail): string {
  if (detail.state === 'finalizing') return '正在生成正式版本';
  if (detail.state === 'finalized' && detail.audio.state === 'deleted') return '音频已删除';
  if (detail.state === 'finalized') return '已确认';
  return detail.review.pending_count > 0 ? '待核对' : '已核对';
}

function speakerName(
  content: MeetingDraftContent,
  result: MeetingResultV1,
  speakerId: string,
): string {
  return content.speaker_names[speakerId]
    ?? result.speakers?.find((speaker) => speaker.speaker_id === speakerId)?.display_name
    ?? speakerId;
}

function WorkspaceIcon({ view }: { view: ReviewView }) {
  if (view === 'minutes') return <MinutesIcon />;
  if (view === 'transcript') return <TranscriptIcon />;
  if (view === 'chapters') return <ChaptersIcon />;
  if (view === 'speakers') return <SpeakersIcon />;
  return <TasksIcon />;
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

function ReviewPageState({
  title,
  copy,
  action,
}: {
  title: string;
  copy: string;
  action?: ReactNode;
}) {
  return (
    <div className="review-state-layout">
      <aside className="review-state-sidebar"><Brand /></aside>
      <main className="review-state-main">
        <div className="review-state-card">
          <span className="review-state-mark" />
          <h1>{title}</h1>
          <p>{copy}</p>
          {action ? <div className="review-state-action">{action}</div> : null}
        </div>
      </main>
    </div>
  );
}

export function MeetingReviewPage() {
  const { meetingId = '' } = useParams();
  const queryClient = useQueryClient();
  const initializedMeeting = useRef<string | null>(null);
  const editVersion = useRef(0);
  const toastTimer = useRef<number | null>(null);

  const [activeView, setActiveView] = useState<ReviewView>('minutes');
  const [content, setContent] = useState<MeetingDraftContent | null>(null);
  const [draftRevision, setDraftRevision] = useState(0);
  const [baseResultRevision, setBaseResultRevision] = useState(0);
  const [dirty, setDirty] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [minutesEditing, setMinutesEditing] = useState(false);
  const [transcriptEditing, setTranscriptEditing] = useState(false);
  const [chaptersEditing, setChaptersEditing] = useState(false);
  const [structuredEditing, setStructuredEditing] = useState(false);
  const [transcriptSearch, setTranscriptSearch] = useState('');
  const [selectedEvidenceId, setSelectedEvidenceId] = useState<string | null>(null);
  const [selectedSegmentId, setSelectedSegmentId] = useState<string | null>(null);
  const [currentAudioMs, setCurrentAudioMs] = useState(0);
  const [pendingScrollId, setPendingScrollId] = useState<string | null>(null);
  const [renameSpeakerId, setRenameSpeakerId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState('');
  const [finalizeDialogOpen, setFinalizeDialogOpen] = useState(false);
  const [finalizeFormats, setFinalizeFormats] = useState<ExportFormat[]>(['html', 'txt', 'json']);
  const [finalizeAgreement, setFinalizeAgreement] = useState(false);
  const [finalizeSubmitted, setFinalizeSubmitted] = useState(false);
  const [finalizeComplete, setFinalizeComplete] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [deleteConfirmation, setDeleteConfirmation] = useState('');

  const showToast = useCallback((message: string) => {
    setToast(message);
    if (toastTimer.current !== null) window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), 2600);
  }, []);

  useEffect(() => () => {
    if (toastTimer.current !== null) window.clearTimeout(toastTimer.current);
  }, []);

  const detailQuery = useQuery({
    queryKey: ['meeting', meetingId],
    queryFn: () => meetingApi.getMeeting(meetingId),
    enabled: Boolean(meetingId),
    refetchInterval: (query) => (query.state.data?.state === 'finalizing' ? 1200 : false),
  });

  const detail = detailQuery.data;
  const reviewAvailable = detail?.state === 'review_ready'
    || detail?.state === 'finalizing'
    || detail?.state === 'finalized';

  const resultQuery = useQuery({
    queryKey: ['meeting-result', meetingId],
    queryFn: () => meetingApi.getMeetingResult(meetingId),
    enabled: Boolean(meetingId && reviewAvailable && detail?.availability.transcript),
    retry: false,
  });

  const draftQuery = useQuery({
    queryKey: ['meeting-draft', meetingId],
    queryFn: () => meetingApi.getMeetingDraft(meetingId),
    enabled: Boolean(meetingId && reviewAvailable && resultQuery.data),
    retry: false,
  });

  const exportsQuery = useQuery({
    queryKey: ['meeting-exports', meetingId],
    queryFn: () => meetingApi.getMeetingExports(meetingId),
    enabled: Boolean(meetingId && (detail?.state === 'finalizing' || detail?.state === 'finalized')),
    refetchInterval: (query) => {
      const data = query.state.data;
      return data?.state === 'finalizing'
        || data?.items.some((item) => item.state === 'queued' || item.state === 'generating')
        ? 1200
        : false;
    },
    retry: false,
  });

  const saveMutation = useMutation({
    mutationFn: (variables: SaveVariables) => meetingApi.saveMeetingDraft(meetingId, {
      expected_revision: variables.expectedRevision,
      base_result_revision: variables.baseResultRevision,
      content: variables.content,
    }),
    onSuccess: (response, variables) => {
      setDraftRevision(response.revision);
      setBaseResultRevision(response.base_result_revision);
      if (editVersion.current === variables.editVersion) setDirty(false);
      queryClient.setQueryData<MeetingDraft>(['meeting-draft', meetingId], (current) => current
        ? {
            ...current,
            revision: response.revision,
            base_result_revision: response.base_result_revision,
            updated_at: response.saved_at,
            dirty: false,
            content: clone(variables.content),
          }
        : current);
      void queryClient.invalidateQueries({ queryKey: ['meeting', meetingId] });
      void queryClient.invalidateQueries({ queryKey: ['meetings'] });
    },
  });

  const finalizeMutation = useMutation({
    mutationFn: (variables: FinalizeVariables) => meetingApi.finalizeMeeting(meetingId, {
      draft_revision: variables.revision,
      formats: variables.formats,
      confirmed: true,
    }),
    onSuccess: (response) => {
      setFinalizeSubmitted(true);
      queryClient.setQueryData<MeetingDetail>(['meeting', meetingId], (current) => current
        ? {
            ...current,
            state: response.state,
            phase: response.phase,
            availability: {
              ...current.availability,
              formal_version: response.state === 'finalized',
            },
            capabilities: {
              ...current.capabilities,
              can_edit: false,
              can_save_draft: false,
              can_finalize: false,
              can_delete_audio: response.state === 'finalized' && current.audio.state === 'available',
            },
          }
        : current);
      queryClient.setQueryData<MeetingExportsResponse>(['meeting-exports', meetingId], {
        meeting_id: meetingId,
        state: response.state,
        items: response.exports,
      });
      if (response.state === 'finalized') setFinalizeComplete(true);
      void queryClient.invalidateQueries({ queryKey: ['meeting', meetingId] });
      void queryClient.invalidateQueries({ queryKey: ['meeting-exports', meetingId] });
      void queryClient.invalidateQueries({ queryKey: ['meetings'] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: () => meetingApi.deleteMeetingAudio(meetingId, deleteConfirmation),
    onSuccess: (response) => {
      queryClient.setQueryData<MeetingDetail>(['meeting', meetingId], (current) => current
        ? {
            ...current,
            state: 'finalized',
            phase: 'ready',
            audio: {
              ...current.audio,
              state: response.audio.state,
              size_bytes: null,
              playable: response.audio.playable,
              deleted_at: response.audio.deleted_at,
            },
            capabilities: {
              ...current.capabilities,
              can_edit: false,
              can_save_draft: false,
              can_finalize: false,
              can_play_audio: false,
              can_delete_audio: false,
            },
            file_health: {
              ...current.file_health,
              source_audio: 'deleted',
            },
          }
        : current);
      setDeleteDialogOpen(false);
      setDeleteConfirmation('');
      showToast(`原始音频已删除，释放 ${formatFileSize(response.freed_bytes)}`);
      void queryClient.invalidateQueries({ queryKey: ['meetings'] });
    },
  });

  useEffect(() => {
    initializedMeeting.current = null;
    editVersion.current = 0;
    setContent(null);
    setDraftRevision(0);
    setBaseResultRevision(0);
    setDirty(false);
    setActiveView('minutes');
    setSelectedEvidenceId(null);
    setSelectedSegmentId(null);
    setCurrentAudioMs(0);
  }, [meetingId]);

  useEffect(() => {
    const draft = draftQuery.data;
    if (!draft) return;
    const firstLoad = initializedMeeting.current !== meetingId;
    const newerSavedDraft = !dirty && draft.revision > draftRevision;
    if (!firstLoad && !newerSavedDraft) return;
    initializedMeeting.current = meetingId;
    setContent(clone(draft.content));
    setDraftRevision(draft.revision);
    setBaseResultRevision(draft.base_result_revision);
    setDirty(false);
  }, [draftQuery.data, draftRevision, dirty, meetingId]);

  useEffect(() => {
    const evidence = resultQuery.data?.evidence?.[0];
    if (!evidence || selectedEvidenceId || selectedSegmentId) return;
    setSelectedEvidenceId(evidence.evidence_id);
    setSelectedSegmentId(evidence.segment_id);
    setCurrentAudioMs(evidence.start_ms);
  }, [resultQuery.data, selectedEvidenceId, selectedSegmentId]);

  useEffect(() => {
    if (!pendingScrollId || activeView !== 'transcript') return;
    const frame = window.requestAnimationFrame(() => {
      document.getElementById(`review-${pendingScrollId}`)?.scrollIntoView({
        behavior: 'smooth',
        block: 'center',
      });
      setPendingScrollId(null);
    });
    return () => window.cancelAnimationFrame(frame);
  }, [activeView, pendingScrollId]);

  useEffect(() => {
    if (!finalizeSubmitted || detail?.state !== 'finalized') return;
    setFinalizeComplete(true);
  }, [detail?.state, finalizeSubmitted]);

  const result = resultQuery.data;
  const readOnly = !detail
    || detail.state !== 'review_ready'
    || !detail.capabilities.can_edit;

  const appliedSegments = useMemo(() => {
    if (!result?.transcript || !content) return [];
    const edits = new Map(content.transcript_edits.map((edit) => [edit.segment_id, edit]));
    return result.transcript.segments.map((segment) => {
      const edit = edits.get(segment.segment_id);
      return {
        ...segment,
        text: edit?.text ?? segment.text,
        speaker_id: edit?.speaker_id ?? segment.speaker_id,
        user_edited: Boolean(edit) || segment.user_edited,
      };
    });
  }, [content, result]);

  const visibleSegments = useMemo(() => {
    if (!content || !result) return [];
    const query = transcriptSearch.trim().toLocaleLowerCase('zh-CN');
    if (!query) return appliedSegments;
    return appliedSegments.filter((segment) => {
      const name = speakerName(content, result, segment.speaker_id);
      return segment.text.toLocaleLowerCase('zh-CN').includes(query)
        || name.toLocaleLowerCase('zh-CN').includes(query);
    });
  }, [appliedSegments, content, result, transcriptSearch]);

  const selectedEvidence = result?.evidence?.find(
    (evidence) => evidence.evidence_id === selectedEvidenceId,
  ) ?? null;
  const selectedSegment = appliedSegments.find(
    (segment) => segment.segment_id === selectedSegmentId,
  ) ?? null;
  const durationMs = result?.duration_ms ?? detail?.audio.duration_ms ?? 0;
  const audioProgress = durationMs > 0
    ? Math.min(100, Math.max(0, (currentAudioMs / durationMs) * 100))
    : 0;
  const marks = content ? Object.values(content.review_marks) : [];
  const pendingCount = marks.length
    ? marks.filter((status) => status === 'pending').length
    : detail?.review.pending_count ?? 0;
  const reviewedCount = marks.length
    ? marks.filter((status) => status !== 'pending').length
    : detail?.review.reviewed_count ?? 0;
  const exportItems = exportsQuery.data?.items ?? finalizeMutation.data?.exports ?? [];

  function editContent(mutator: (next: MeetingDraftContent) => void) {
    if (readOnly) return;
    editVersion.current += 1;
    setContent((current) => {
      if (!current) return current;
      const next = clone(current);
      mutator(next);
      return next;
    });
    setDirty(true);
  }

  function selectEvidence(evidenceId: string) {
    const evidence = result?.evidence?.find((item) => item.evidence_id === evidenceId);
    if (!evidence) return;
    setSelectedEvidenceId(evidence.evidence_id);
    setSelectedSegmentId(evidence.segment_id);
    setCurrentAudioMs(evidence.start_ms);
  }

  function selectSegment(segment: TranscriptSegment) {
    const evidence = result?.evidence?.find((item) => item.segment_id === segment.segment_id);
    setSelectedEvidenceId(evidence?.evidence_id ?? null);
    setSelectedSegmentId(segment.segment_id);
    setCurrentAudioMs(segment.start_ms);
  }

  function openChapter(chapterId: string, startMs: number) {
    const segment = appliedSegments.find((item) => item.chapter_id === chapterId)
      ?? appliedSegments.find((item) => item.start_ms >= startMs);
    setActiveView('transcript');
    if (segment) {
      selectSegment(segment);
      setPendingScrollId(segment.segment_id);
    }
  }

  function updateTranscript(segment: TranscriptSegment, text: string) {
    editContent((next) => {
      const existing = next.transcript_edits.find((edit) => edit.segment_id === segment.segment_id);
      if (existing) {
        existing.text = text;
      } else {
        next.transcript_edits.push({
          segment_id: segment.segment_id,
          text,
          speaker_id: segment.speaker_id,
        });
      }
    });
  }

  function updateStructuredStatus(kind: StructuredKind, id: string, status: ReviewStatus) {
    editContent((next) => {
      const items = kind === 'decision' ? next.decisions : next.action_items;
      const item = items.find((candidate) => (
        kind === 'decision'
          ? 'decision_id' in candidate && candidate.decision_id === id
          : 'action_id' in candidate && candidate.action_id === id
      ));
      if (item) item.review_status = status;
      next.review_marks[id] = status;
    });
  }

  async function saveCurrentDraft(): Promise<number> {
    if (!content) throw new Error('草稿尚未载入');
    if (!dirty) return draftRevision;
    const variables: SaveVariables = {
      content: clone(content),
      expectedRevision: draftRevision,
      baseResultRevision,
      editVersion: editVersion.current,
    };
    const response = await saveMutation.mutateAsync(variables);
    return response.revision;
  }

  async function handleSave() {
    try {
      await saveCurrentDraft();
      showToast(dirty ? '草稿已保存' : '当前没有未保存更改');
    } catch (error) {
      showToast(getErrorMessage(error, '草稿保存失败'));
    }
  }

  function openFinalizeDialog() {
    setFinalizeFormats(['html', 'txt', 'json']);
    setFinalizeAgreement(false);
    setFinalizeSubmitted(false);
    setFinalizeComplete(detail?.state === 'finalized');
    setFinalizeDialogOpen(true);
  }

  async function handleFinalize() {
    if (!finalizeAgreement || finalizeFormats.length === 0) return;
    try {
      const revision = await saveCurrentDraft();
      await finalizeMutation.mutateAsync({ revision, formats: finalizeFormats });
    } catch (error) {
      setFinalizeSubmitted(false);
      showToast(getErrorMessage(error, '正式版本生成失败'));
    }
  }

  function toggleFormat(format: ExportFormat) {
    setFinalizeFormats((current) => current.includes(format)
      ? current.filter((item) => item !== format)
      : [...current, format]);
  }

  function openRename(speakerId: string) {
    if (!content || !result) return;
    setRenameSpeakerId(speakerId);
    setRenameValue(speakerName(content, result, speakerId));
  }

  function confirmRename() {
    const value = renameValue.trim();
    if (!renameSpeakerId || !value) return;
    editContent((next) => {
      next.speaker_names[renameSpeakerId] = value;
    });
    setRenameSpeakerId(null);
    setRenameValue('');
  }

  if (detailQuery.isPending) {
    return <ReviewPageState title="正在打开会议" copy="正在读取会议内容与核对草稿。" />;
  }

  if (detailQuery.isError || !detail) {
    return (
      <ReviewPageState
        title="无法打开会议"
        copy={getErrorMessage(detailQuery.error, '会议不存在或暂时无法读取。')}
        action={<Link className="secondary-button compact-button" to="/meetings">返回会议库</Link>}
      />
    );
  }

  if (['missing', 'invalid', 'unreadable'].includes(detail.file_health.result)) {
    return <Navigate to={`/meetings/${meetingId}/result-unavailable`} replace />;
  }

  if (!reviewAvailable) {
    return (
      <ReviewPageState
        title="会议尚未进入核对阶段"
        copy="当前会议仍在处理，结果完成后可进入会议工作区。"
        action={<Link className="primary-button compact-button" to={`/meetings/${meetingId}/processing`}>查看处理进度</Link>}
      />
    );
  }

  if (resultQuery.isPending || draftQuery.isPending || !content || !result) {
    return <ReviewPageState title="正在准备工作区" copy="正在读取全文、纪要和草稿。" />;
  }

  if (resultQuery.isError || draftQuery.isError) {
    return (
      <ReviewPageState
        title="会议内容读取失败"
        copy={getErrorMessage(resultQuery.error ?? draftQuery.error, '无法读取会议结果或核对草稿。')}
        action={<Link className="secondary-button compact-button" to="/meetings">返回会议库</Link>}
      />
    );
  }

  const counts: Record<ReviewView, number> = {
    minutes: content.minutes ? 1 : 0,
    transcript: appliedSegments.length,
    chapters: content.chapters.length,
    speakers: result.speakers?.length ?? 0,
    structured: content.decisions.length + content.action_items.length,
  };
  const audioDeleted = detail.audio.state === 'deleted';
  const canDeleteAudio = detail.state === 'finalized'
    && detail.capabilities.can_delete_audio
    && !audioDeleted;
  const evidenceQuote = selectedEvidence?.quote ?? selectedSegment?.text ?? '选择证据或全文时间点';
  const evidenceSpeaker = selectedEvidence
    ? speakerName(content, result, selectedEvidence.speaker_id)
    : selectedSegment
      ? speakerName(content, result, selectedSegment.speaker_id)
      : '—';
  const evidenceTime = selectedEvidence?.start_ms ?? selectedSegment?.start_ms ?? currentAudioMs;
  const saveState = detail.state === 'finalizing'
    ? '正在生成正式版本'
    : detail.state === 'finalized'
      ? '正式版本已生成'
      : saveMutation.isPending
        ? '正在保存'
        : dirty
          ? '有未保存更改'
          : draftRevision > 0
            ? `草稿修订 ${draftRevision}`
            : '所有更改已保存';

  return (
    <>
      <div className="review-workspace">
        <aside className="review-sidebar">
          <Brand />
          <Link className="review-meeting-back" to="/meetings">‹ 返回会议库</Link>
          <div className="review-meeting-identity">
            <div className="review-meeting-label">当前会议</div>
            <div className="review-meeting-title">{content.title}</div>
            <div className={`review-meeting-status review-meeting-status-${detail.state}`}>
              {detail.state === 'review_ready' && pendingCount > 0
                ? `${pendingCount} 条待核对`
                : meetingStateLabel(detail)}
            </div>
          </div>
          <div className="review-workspace-label">会议内容</div>
          <nav className="review-workspace-nav" aria-label="会议工作区">
            {(Object.keys(viewLabels) as ReviewView[]).map((view) => (
              <button
                className={activeView === view ? 'review-workspace-tab review-workspace-tab-active' : 'review-workspace-tab'}
                type="button"
                key={view}
                onClick={() => setActiveView(view)}
              >
                <span className="review-tab-icon"><WorkspaceIcon view={view} /></span>
                <span>{viewLabels[view]}</span>
                <span className="review-tab-count">{counts[view]}</span>
              </button>
            ))}
          </nav>
          <div className="review-sidebar-foot">
            <span className={dirty ? 'review-live-dot review-live-dot-dirty' : 'review-live-dot'} />
            <span>
              {detail.state === 'finalized'
                ? '正式版本已生成'
                : dirty
                  ? '草稿有未保存更改'
                  : '草稿已保存在本地'}
            </span>
          </div>
        </aside>

        <main className="review-main">
          <header className="review-topbar">
            <div className="review-crumb">
              <Link to="/meetings">会议库</Link>
              <span>/</span>
              <span>{content.title}</span>
              <span>/</span>
              <strong>{viewLabels[activeView]}</strong>
            </div>
            <div className="review-top-actions">
              <Link className="review-quiet-button" to={`/meetings/${meetingId}/playback`}>
                {audioDeleted ? '查看全文' : '全文回放'}
              </Link>
              {detail.capabilities.can_save_draft ? (
                <button
                  className="review-quiet-button"
                  type="button"
                  disabled={saveMutation.isPending || finalizeMutation.isPending}
                  onClick={() => void handleSave()}
                >
                  {saveMutation.isPending ? '正在保存' : '保存草稿'}
                </button>
              ) : (
                <button
                  className="review-quiet-button"
                  type="button"
                  disabled
                  title="当前无法保存草稿：草稿保存接口能力暂不可用"
                >
                  保存草稿（暂不可用）
                </button>
              )}
              {detail.capabilities.can_finalize ? (
                <button
                  className="review-primary-button"
                  type="button"
                  disabled={saveMutation.isPending || finalizeMutation.isPending}
                  onClick={openFinalizeDialog}
                >
                  确认纪要
                </button>
              ) : detail.state === 'finalizing' ? (
                <button className="review-primary-button" type="button" disabled>正在生成</button>
              ) : detail.state === 'finalized' ? (
                <Link className="review-quiet-button" to={`/meetings/${meetingId}/formal`}>正式版本</Link>
              ) : (
                <button
                  className="review-primary-button"
                  type="button"
                  disabled
                  title="当前无法确认纪要：确认与导出接口能力暂不可用"
                >
                  确认纪要（暂不可用）
                </button>
              )}
            </div>
          </header>

          <div className="review-content">
            <header className="review-page-head">
              <div>
                <div className="review-eyebrow">{viewLabels[activeView]}</div>
                <h1>{content.title}</h1>
                <div className="review-page-context">
                  <span>{meetingStateLabel(detail)}</span>
                  <span>{detail.source_label}</span>
                  <span className="mono">{formatMeetingDay(detail.meeting_date)} · {formatTimestamp(durationMs)}</span>
                </div>
              </div>
              <div className={dirty ? 'review-save-state review-save-state-dirty' : 'review-save-state'}>{saveState}</div>
            </header>

            {activeView === 'minutes' ? (
              <section className="review-view-panel">
                {content.minutes ? (
                  <article className="review-document">
                    <div className="review-document-head">
                      <div className="review-document-brand"><span className="review-minutes-star" /><span>会议纪要</span></div>
                      {!readOnly ? (
                        <button className={minutesEditing ? 'review-tool-button review-tool-button-active' : 'review-tool-button'} type="button" onClick={() => setMinutesEditing((value) => !value)}>
                          {minutesEditing ? '完成编辑' : '编辑'}
                        </button>
                      ) : null}
                    </div>
                    <div className="review-document-body">
                      {minutesEditing ? (
                        <textarea
                          className="review-minutes-overview-input"
                          value={content.minutes.overview}
                          onChange={(event) => editContent((next) => {
                            if (next.minutes) next.minutes.overview = event.target.value;
                          })}
                        />
                      ) : (
                        <p className="review-minutes-intro">{content.minutes.overview}</p>
                      )}
                      <div className="review-minutes-outline">
                        {content.minutes.outline.map((node) => (
                          <section className="review-minutes-section" key={node.node_id}>
                            {minutesEditing ? (
                              <input
                                className="review-minutes-title-input"
                                value={node.title}
                                onChange={(event) => editContent((next) => {
                                  const target = next.minutes?.outline.find((item) => item.node_id === node.node_id);
                                  if (!target) return;
                                  target.title = event.target.value;
                                  target.review_status = 'edited';
                                  target.user_edited = true;
                                  next.review_marks[node.node_id] = 'edited';
                                })}
                              />
                            ) : (
                              <div className="review-minutes-section-title">{node.title}</div>
                            )}
                            {minutesEditing ? (
                              <textarea
                                className="review-minutes-copy-input"
                                value={node.text ?? ''}
                                onChange={(event) => editContent((next) => {
                                  const target = next.minutes?.outline.find((item) => item.node_id === node.node_id);
                                  if (!target) return;
                                  target.text = event.target.value;
                                  target.review_status = 'edited';
                                  target.user_edited = true;
                                  next.review_marks[node.node_id] = 'edited';
                                })}
                              />
                            ) : (
                              <p className="review-minutes-copy">{node.text}</p>
                            )}
                            <div className="review-inline-evidence">
                              {node.evidence_ids.map((evidenceId) => {
                                const evidence = result.evidence?.find((item) => item.evidence_id === evidenceId);
                                return (
                                  <button className="review-evidence-link" type="button" key={evidenceId} onClick={() => selectEvidence(evidenceId)}>
                                    {evidence ? formatTimestamp(evidence.start_ms) : evidenceId}
                                  </button>
                                );
                              })}
                            </div>
                          </section>
                        ))}
                      </div>
                    </div>
                  </article>
                ) : <div className="review-empty-view">会议纪要尚未生成</div>}
              </section>
            ) : null}

            {activeView === 'transcript' ? (
              <section className="review-view-panel">
                <div className="review-panel-toolbar">
                  <div>
                    <div className="review-panel-title">全文转写</div>
                    <div className="review-panel-sub">{visibleSegments.length} / {appliedSegments.length} 个片段</div>
                  </div>
                  <div className="review-toolbar-actions">
                    <label className="review-search-box">
                      <SearchIcon />
                      <input value={transcriptSearch} type="search" placeholder="搜索全文" onChange={(event) => setTranscriptSearch(event.target.value)} />
                    </label>
                    {!readOnly ? (
                      <button className={transcriptEditing ? 'review-tool-button review-tool-button-active' : 'review-tool-button'} type="button" onClick={() => setTranscriptEditing((value) => !value)}>
                        {transcriptEditing ? '完成编辑' : '编辑全文'}
                      </button>
                    ) : null}
                  </div>
                </div>
                <div className="review-transcript">
                  <div className="review-turn-list">
                    {visibleSegments.length ? visibleSegments.map((segment) => (
                      <article className={selectedSegmentId === segment.segment_id ? 'review-turn review-turn-selected' : 'review-turn'} id={`review-${segment.segment_id}`} key={segment.segment_id}>
                        <div className="review-turn-header">
                          <span className="review-speaker">{speakerName(content, result, segment.speaker_id)}:</span>
                          <button className="review-turn-time" type="button" onClick={() => selectSegment(segment)}>{formatTimestamp(segment.start_ms)}</button>
                        </div>
                        {transcriptEditing ? (
                          <textarea className="review-turn-input" value={segment.text} onChange={(event) => updateTranscript(segment, event.target.value)} />
                        ) : (
                          <p className="review-turn-copy"><HighlightedText text={segment.text} query={transcriptSearch} /></p>
                        )}
                      </article>
                    )) : <div className="review-empty-view">未找到匹配内容</div>}
                  </div>
                </div>
              </section>
            ) : null}

            {activeView === 'chapters' ? (
              <section className="review-view-panel">
                <div className="review-panel-toolbar">
                  <div><div className="review-panel-title">章节</div><div className="review-panel-sub">按会议内容整理</div></div>
                  {!readOnly ? (
                    <button className={chaptersEditing ? 'review-tool-button review-tool-button-active' : 'review-tool-button'} type="button" onClick={() => setChaptersEditing((value) => !value)}>
                      {chaptersEditing ? '完成编辑' : '编辑'}
                    </button>
                  ) : null}
                </div>
                <div className="review-chapter-list">
                  {content.chapters.map((chapter) => (
                    <article className="review-chapter" key={chapter.chapter_id}>
                      <span className="review-chapter-time">{formatTimestamp(chapter.start_ms)}–{formatTimestamp(chapter.end_ms)}</span>
                      <div>
                        {chaptersEditing ? (
                          <input className="review-chapter-title-input" value={chapter.title} onChange={(event) => editContent((next) => {
                            const target = next.chapters.find((item) => item.chapter_id === chapter.chapter_id);
                            if (!target) return;
                            target.title = event.target.value;
                            target.review_status = 'edited';
                            target.user_edited = true;
                            next.review_marks[chapter.chapter_id] = 'edited';
                          })} />
                        ) : <div className="review-chapter-title">{chapter.title}</div>}
                        {chaptersEditing ? (
                          <textarea className="review-chapter-copy-input" value={chapter.summary} onChange={(event) => editContent((next) => {
                            const target = next.chapters.find((item) => item.chapter_id === chapter.chapter_id);
                            if (!target) return;
                            target.summary = event.target.value;
                            target.review_status = 'edited';
                            target.user_edited = true;
                            next.review_marks[chapter.chapter_id] = 'edited';
                          })} />
                        ) : <p className="review-chapter-copy">{chapter.summary}</p>}
                        <div className="review-inline-evidence">
                          {chapter.evidence_ids.map((evidenceId) => (
                            <button className="review-evidence-link" type="button" key={evidenceId} onClick={() => selectEvidence(evidenceId)}>证据</button>
                          ))}
                        </div>
                      </div>
                      <button className="review-chapter-open" type="button" onClick={() => openChapter(chapter.chapter_id, chapter.start_ms)}>查看全文</button>
                    </article>
                  ))}
                </div>
              </section>
            ) : null}

            {activeView === 'speakers' ? (
              <section className="review-view-panel">
                <div className="review-panel-toolbar"><div><div className="review-panel-title">发言人</div><div className="review-panel-sub">名称同步到全文和证据</div></div></div>
                <div className="review-speaker-list">
                  {(result.speakers ?? []).map((speaker, index) => (
                    <article className="review-speaker-row" key={speaker.speaker_id}>
                      <span className="review-speaker-avatar">{String(index + 1).padStart(2, '0')}</span>
                      <div>
                        <div className="review-speaker-name">{speakerName(content, result, speaker.speaker_id)}</div>
                        <div className="review-speaker-meta">{speaker.segment_count} 个片段 · {formatDuration(speaker.duration_ms)}</div>
                      </div>
                      {!readOnly ? <button className="review-rename-button" type="button" onClick={() => openRename(speaker.speaker_id)}>重命名</button> : null}
                    </article>
                  ))}
                </div>
              </section>
            ) : null}

            {activeView === 'structured' ? (
              <section className="review-view-panel">
                <div className="review-panel-toolbar">
                  <div><div className="review-panel-title">决策与待办</div><div className="review-panel-sub">{content.decisions.length} 项决策 · {content.action_items.length} 项待办</div></div>
                  {!readOnly ? (
                    <button className={structuredEditing ? 'review-tool-button review-tool-button-active' : 'review-tool-button'} type="button" onClick={() => setStructuredEditing((value) => !value)}>
                      {structuredEditing ? '完成编辑' : '编辑'}
                    </button>
                  ) : null}
                </div>
                <div className="review-structured-list">
                  <section className="review-structured-group">
                    <div className="review-structured-head"><strong>决策</strong><span>{content.decisions.length}</span></div>
                    {content.decisions.map((decision, index) => (
                      <article className="review-structured-row" key={decision.decision_id}>
                        <span className="review-structured-index">{index + 1}</span>
                        <div>
                          {structuredEditing ? (
                            <textarea className="review-structured-input" value={decision.text} onChange={(event) => editContent((next) => {
                              const target = next.decisions.find((item) => item.decision_id === decision.decision_id);
                              if (!target) return;
                              target.text = event.target.value;
                              target.review_status = 'edited';
                              target.user_edited = true;
                              next.review_marks[decision.decision_id] = 'edited';
                            })} />
                          ) : <div className="review-structured-title">{decision.text}</div>}
                          <div className="review-structured-meta">
                            <span className={decision.review_status === 'pending' ? 'review-status-pending' : ''}>{reviewStatusLabel(decision.review_status)}</span>
                            {decision.evidence_ids.map((evidenceId) => (
                              <button className="review-evidence-link" type="button" key={evidenceId} onClick={() => selectEvidence(evidenceId)}>证据</button>
                            ))}
                          </div>
                        </div>
                        {!readOnly && decision.review_status === 'pending' ? (
                          <button className="review-mark-button" type="button" onClick={() => updateStructuredStatus('decision', decision.decision_id, 'reviewed')}>标记已核对</button>
                        ) : null}
                      </article>
                    ))}
                  </section>

                  <section className="review-structured-group">
                    <div className="review-structured-head"><strong>待办</strong><span>{content.action_items.length}</span></div>
                    {content.action_items.map((action, index) => (
                      <article className="review-structured-row" key={action.action_id}>
                        <span className="review-structured-index">{index + 1}</span>
                        <div>
                          {structuredEditing ? (
                            <textarea className="review-structured-input" value={action.text} onChange={(event) => editContent((next) => {
                              const target = next.action_items.find((item) => item.action_id === action.action_id);
                              if (!target) return;
                              target.text = event.target.value;
                              target.review_status = 'edited';
                              target.user_edited = true;
                              next.review_marks[action.action_id] = 'edited';
                            })} />
                          ) : <div className="review-structured-title">{action.text}</div>}
                          <div className="review-structured-meta">
                            <span className={action.review_status === 'pending' ? 'review-status-pending' : ''}>{reviewStatusLabel(action.review_status)}</span>
                            <span>负责人：{action.owner ?? '未提及'}</span>
                            <span>截止时间：{action.due_date ?? '未提及'}</span>
                            {action.evidence_ids.map((evidenceId) => (
                              <button className="review-evidence-link" type="button" key={evidenceId} onClick={() => selectEvidence(evidenceId)}>证据</button>
                            ))}
                          </div>
                        </div>
                        {!readOnly && action.review_status === 'pending' ? (
                          <button className="review-mark-button" type="button" onClick={() => updateStructuredStatus('action', action.action_id, 'reviewed')}>标记已核对</button>
                        ) : null}
                      </article>
                    ))}
                  </section>
                </div>
              </section>
            ) : null}
          </div>
        </main>

        <aside className="review-inspector">
          <div className="review-inspector-head"><div className="review-inspector-title">核对与证据</div></div>
          <div className="review-inspector-body">
            <section className="review-audio-player">
              <div className="review-audio-top">
                <button
                  className="review-play-button"
                  type="button"
                  aria-label="播放当前定位"
                  disabled={audioDeleted || !detail.capabilities.can_play_audio}
                  onClick={() => showToast(`已定位到 ${formatTimestamp(currentAudioMs)}`)}
                >
                  <PlayIcon />
                </button>
                <span className="review-audio-time">{formatTimestamp(currentAudioMs)} / {formatTimestamp(durationMs)}</span>
              </div>
              <div className="review-audio-track">
                <div className="review-audio-progress" style={{ width: `${audioProgress}%` }} />
                <span className="review-audio-marker" style={{ left: `${audioProgress}%` }} />
              </div>
            </section>

            <div className="review-inspector-section-title">核对状态</div>
            <div className="review-review-group">
              <div className="review-review-row"><span>待核对</span><strong className="review-status-pending">{pendingCount}</strong></div>
              <div className="review-review-row"><span>已核对</span><strong>{reviewedCount}</strong></div>
              <div className="review-review-row"><span>发言人</span><strong>{result.speakers?.length ?? 0}</strong></div>
            </div>

            <div className="review-inspector-section-title">当前证据</div>
            <section className="review-evidence-box">
              <div className="review-evidence-label">
                <span>{selectedEvidence?.evidence_id.toUpperCase() ?? (selectedSegment ? '全文定位' : '未选择')}</span>
                <span className="review-evidence-time">{formatTimestamp(evidenceTime)}</span>
              </div>
              <div className="review-evidence-quote">“{evidenceQuote}”</div>
              <div className="review-evidence-speaker">{evidenceSpeaker}</div>
            </section>

            {exportItems.length ? (
              <>
                <div className="review-inspector-section-title">正式版本</div>
                <div className="review-inspector-exports">
                  {exportItems.map((item) => (
                    <div className="review-inspector-export" key={item.format}>
                      <strong>{exportLabels[item.format]}</strong>
                      <span>{item.state === 'ready' ? '已生成' : item.state === 'failed' ? '生成失败' : '生成中'}</span>
                    </div>
                  ))}
                </div>
              </>
            ) : null}

            <div className="review-audio-note">
              {audioDeleted
                ? '原始音频已删除，文字结果与证据时间点已保留。'
                : detail.state === 'finalized'
                  ? '原始音频可单独删除。'
                  : '确认纪要后可单独删除原始音频。'}
            </div>
            {canDeleteAudio ? (
              <button className="review-audio-delete" type="button" onClick={() => setDeleteDialogOpen(true)}>删除原始音频</button>
            ) : null}
          </div>
        </aside>
      </div>

      {renameSpeakerId ? (
        <div className="review-dialog-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setRenameSpeakerId(null); }}>
          <section className="review-dialog" role="dialog" aria-modal="true" aria-labelledby="reviewRenameTitle">
            <h2 id="reviewRenameTitle">重命名发言人</h2>
            <p>{content.speaker_names[renameSpeakerId] ?? renameSpeakerId}</p>
            <input className="review-dialog-input" value={renameValue} autoFocus onChange={(event) => setRenameValue(event.target.value)} />
            <div className="review-dialog-actions">
              <button className="review-quiet-button" type="button" onClick={() => setRenameSpeakerId(null)}>取消</button>
              <button className="review-primary-button" type="button" disabled={!renameValue.trim()} onClick={confirmRename}>保存</button>
            </div>
          </section>
        </div>
      ) : null}

      {finalizeDialogOpen ? (
        <div className="review-dialog-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !finalizeMutation.isPending) setFinalizeDialogOpen(false); }}>
          <section className="review-dialog review-finalize-dialog" role="dialog" aria-modal="true" aria-labelledby="reviewFinalizeTitle">
            {finalizeComplete ? (
              <>
                <div className="review-success-mark">✓</div>
                <h2 id="reviewFinalizeTitle">正式版本已生成</h2>
                <div className="review-export-list">
                  {exportItems.map((item) => (
                    <div className="review-export-row" key={item.format}>
                      <span className="review-export-type">{exportLabels[item.format]}</span>
                      <span className="review-export-name">{item.file_name ?? '正式会议纪要'}</span>
                      <span className={item.state === 'ready' ? 'review-export-state' : 'review-export-state review-export-state-pending'}>
                        {item.state === 'ready' ? '已生成' : item.state === 'failed' ? '失败' : '生成中'}
                      </span>
                    </div>
                  ))}
                </div>
                <div className="review-dialog-actions">
                  <Link className="review-quiet-button" to={`/meetings/${meetingId}/formal`} onClick={() => setFinalizeDialogOpen(false)}>查看正式纪要</Link>
                  <button className="review-primary-button" type="button" onClick={() => setFinalizeDialogOpen(false)}>完成</button>
                </div>
              </>
            ) : finalizeSubmitted || finalizeMutation.isPending ? (
              <>
                <h2 id="reviewFinalizeTitle">正在生成正式版本</h2>
                <div className="review-finalize-progress"><span /><span /><span /></div>
                <div className="review-export-list">
                  {(exportItems.length ? exportItems : finalizeFormats.map((format) => ({ format, state: 'generating' as const }))).map((item) => (
                    <div className="review-export-row" key={item.format}>
                      <span className="review-export-type">{exportLabels[item.format]}</span>
                      <span className="review-export-name">正式会议纪要</span>
                      <span className="review-export-state review-export-state-pending">生成中</span>
                    </div>
                  ))}
                </div>
              </>
            ) : (
              <>
                <h2 id="reviewFinalizeTitle">确认纪要</h2>
                <div className="review-finalize-meeting">{content.title}</div>
                <div className="review-confirm-list">
                  <div className="review-confirm-row"><span>会议纪要</span><span className="review-confirm-state">{dirty ? '有修改' : '已保存'}</span></div>
                  <div className="review-confirm-row"><span>发言人</span><span className="review-confirm-state">{result.speakers?.length ?? 0} 位</span></div>
                  <div className="review-confirm-row"><span>决策与待办</span><span className={pendingCount ? 'review-confirm-state review-status-pending' : 'review-confirm-state'}>{pendingCount ? `${pendingCount} 条待核对` : '已核对'}</span></div>
                </div>
                <div className="review-format-title">生成格式</div>
                <div className="review-format-list">
                  {(Object.keys(exportLabels) as ExportFormat[]).map((format) => (
                    <label className="review-format-option" key={format}>
                      <input type="checkbox" checked={finalizeFormats.includes(format)} onChange={() => toggleFormat(format)} />
                      <span>{exportLabels[format]}</span>
                    </label>
                  ))}
                </div>
                <label className="review-agreement">
                  <input type="checkbox" checked={finalizeAgreement} onChange={(event) => setFinalizeAgreement(event.target.checked)} />
                  <span>我已完成核对，确认以当前内容生成正式版本</span>
                </label>
                <div className="review-dialog-actions">
                  <button className="review-quiet-button" type="button" onClick={() => setFinalizeDialogOpen(false)}>取消</button>
                  <button className="review-primary-button" type="button" disabled={!finalizeAgreement || finalizeFormats.length === 0 || finalizeMutation.isPending} onClick={() => void handleFinalize()}>
                    确认并生成
                  </button>
                </div>
              </>
            )}
          </section>
        </div>
      ) : null}

      {deleteDialogOpen ? (
        <div className="review-dialog-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !deleteMutation.isPending) setDeleteDialogOpen(false); }}>
          <section className="review-dialog" role="dialog" aria-modal="true" aria-labelledby="reviewDeleteTitle">
            <h2 id="reviewDeleteTitle">删除原始音频？</h2>
            <div className="review-delete-warning"><strong>此操作无法撤销</strong>音频删除后不能播放或回听原声。</div>
            <div className="review-delete-summary">
              <div><span>原始音频</span><strong className="review-delete-remove">永久删除</strong></div>
              <div><span>会议全文与发言人</span><strong>保留</strong></div>
              <div><span>纪要、决策与待办</span><strong>保留</strong></div>
              <div><span>证据文字与时间点</span><strong>保留</strong></div>
            </div>
            <input className="review-dialog-input review-delete-input" value={deleteConfirmation} placeholder="输入“删除音频”确认" onChange={(event) => setDeleteConfirmation(event.target.value)} />
            {deleteMutation.isError ? <div className="review-dialog-error">{getErrorMessage(deleteMutation.error, '音频删除失败')}</div> : null}
            <div className="review-dialog-actions">
              <button className="review-quiet-button" type="button" disabled={deleteMutation.isPending} onClick={() => setDeleteDialogOpen(false)}>取消</button>
              <button className="review-primary-button review-danger-button" type="button" disabled={deleteConfirmation !== '删除音频' || deleteMutation.isPending} onClick={() => deleteMutation.mutate()}>
                {deleteMutation.isPending ? '正在删除' : '确认删除'}
              </button>
            </div>
          </section>
        </div>
      ) : null}

      <Toast message={toast} />
    </>
  );
}
