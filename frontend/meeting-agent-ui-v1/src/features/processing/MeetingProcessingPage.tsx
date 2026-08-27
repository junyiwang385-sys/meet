import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { Link, Navigate, useParams } from 'react-router-dom';
import { meetingApi } from '../../api';
import { formatDuration } from '../../api/meeting-api';
import type { MeetingDetail, MeetingDiagnostics, MeetingPhase, MeetingResultV1 } from '../../api/types';
import { StagePageShell } from '../shared/StagePageShell';
import './MeetingProcessingPage.css';

const phaseCopy: Record<MeetingPhase, string> = {
  awaiting_source: '等待音频',
  recording: '正在录音',
  uploading: '正在传输音频',
  converting: '正在转换音频',
  transcribing: '正在识别与转写',
  synthesizing: '正在生成纪要、决策和总结',
  exporting: '正在生成正式版本',
  ready: '会议结果已生成',
  cancelled: '任务已取消',
};

function isPolling(detail: MeetingDetail | undefined): boolean {
  return Boolean(detail && ['created', 'recording', 'uploading', 'processing', 'finalizing'].includes(detail.state));
}

function isKnownSpeaker(id: string | null | undefined): boolean {
  return Boolean(id) && id !== 'unknown';
}

// unknown 段顺延归并到相邻已知说话人（先向前顺延，开头的再向后回填），只影响展示。
function carryOverUnknownSpeakers(ids: string[]): string[] {
  const carried = [...ids];
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

function transcriptRows(result: MeetingResultV1) {
  const speakers = new Map(result.speakers?.map((speaker) => [speaker.speaker_id, speaker.display_name]));
  const segments = result.transcript?.segments ?? [];
  const carried = carryOverUnknownSpeakers(segments.map((segment) => segment.speaker_id));
  return segments.map((segment, index) => ({
    ...segment,
    speaker: speakers.get(carried[index]) ?? carried[index],
  }));
}

function milestoneClass(done: boolean, current: boolean): string {
  if (done) return 'processing-milestone processing-milestone-done';
  if (current) return 'processing-milestone processing-milestone-current';
  return 'processing-milestone';
}

function diagnosticCauseCopy(cause: string | null | undefined): string | null {
  if (!cause) return null;
  if (cause === 'finish_reason_length') return '模型输出达到长度上限';
  if (cause === 'context_truncated') return '输入上下文被截断';
  if (cause === 'invalid_json') return '模型响应不是有效 JSON';
  if (cause === 'missing_speaker_summaries') return '模型响应缺少发言人摘要';
  return cause;
}

function FailureDiagnostics({
  detail,
  diagnostics,
}: {
  detail: MeetingDetail;
  diagnostics?: MeetingDiagnostics;
}) {
  if (!detail.error && !diagnostics) return null;
  const preserved = detail.error?.preserved;
  const cause = diagnosticCauseCopy(diagnostics?.cause);
  return (
    <section className="processing-failure-panel" aria-labelledby="processingFailureTitle">
      <div className="processing-failure-head">
        <div>
          <h2 id="processingFailureTitle">失败详情</h2>
          <p>{detail.error?.message ?? '会议处理未完成'}</p>
        </div>
        <code>{detail.error?.code ?? diagnostics?.code ?? 'PROCESSING_FAILED'}</code>
      </div>
      <div className="processing-failure-grid">
        <div><span>失败阶段</span><strong>{diagnostics?.stage ?? detail.raw_stage ?? 'harness'}</strong></div>
        <div><span>产品阶段</span><strong>{detail.error?.phase ?? detail.phase}</strong></div>
        {cause ? <div><span>技术原因</span><strong>{cause}</strong></div> : null}
        {diagnostics?.return_code !== null && diagnostics?.return_code !== undefined ? <div><span>返回码</span><strong>{diagnostics.return_code}</strong></div> : null}
      </div>
      {diagnostics?.message && diagnostics.message !== detail.error?.message ? (
        <div className="processing-failure-reason"><span>有限诊断</span><strong>{diagnostics.message}</strong></div>
      ) : null}
      {preserved ? (
        <div className="processing-preserved-list">
          <span className={preserved.audio ? 'is-preserved' : ''}>原始音频 {preserved.audio ? '已保留' : '不可用'}</span>
          <span className={preserved.transcript ? 'is-preserved' : ''}>全文 {preserved.transcript ? '已保留' : '未生成'}</span>
          <span className={preserved.speakers ? 'is-preserved' : ''}>发言人 {preserved.speakers ? '已保留' : '未生成'}</span>
          <span className={preserved.summary ? 'is-preserved' : ''}>纪要 {preserved.summary ? '已保留' : '未生成'}</span>
        </div>
      ) : null}
      {diagnostics ? (
        <details className="processing-failure-technical">
          <summary>技术详情</summary>
          <div className="processing-failure-technical-grid">
            <span>Board task</span><code>{diagnostics.board_task_id ?? '—'}</code>
            <span>Run ID</span><code>{diagnostics.run_id ?? '—'}</code>
            <span>请求 ID</span><code>{diagnostics.request_id ?? '—'}</code>
            <span>耗时</span><code>{diagnostics.elapsed_seconds === null || diagnostics.elapsed_seconds === undefined ? '—' : `${diagnostics.elapsed_seconds}s`}</code>
            {diagnostics.finish_reason ? <><span>结束原因</span><code>{diagnostics.finish_reason}</code></> : null}
            {diagnostics.context_truncated !== null && diagnostics.context_truncated !== undefined ? (
              <><span>上下文截断</span><code>{diagnostics.context_truncated ? '是' : '否'}</code></>
            ) : null}
            {diagnostics.artifact_refs && Object.keys(diagnostics.artifact_refs).length > 0 ? (
              <><span>诊断产物</span><code>{Object.keys(diagnostics.artifact_refs).join(', ')}</code></>
            ) : null}
          </div>
        </details>
      ) : null}
    </section>
  );
}

function ProcessingInspector({ detail }: { detail: MeetingDetail }) {
  const transcriptReady = detail.availability.transcript;
  const minutesReady = detail.availability.minutes;
  const transcribing = detail.phase === 'transcribing';
  const synthesizing = detail.phase === 'synthesizing';

  return (
    <>
      <div className="stage-detail-group">
        <div className="stage-detail-row"><span>会议 ID</span><strong>{detail.meeting_id}</strong></div>
        <div className="stage-detail-row"><span>处理位置</span><strong>RK1828</strong></div>
        <div className="stage-detail-row"><span>状态</span><strong>{phaseCopy[detail.phase]}</strong></div>
      </div>
      <div className="stage-inspector-section-title">关键节点</div>
      <div className="processing-milestones">
        <div className={milestoneClass(transcriptReady, transcribing)}>
          <span className="processing-milestone-dot" /><span>识别与转写</span>
          <span>{transcriptReady ? '完成' : transcribing ? '进行中' : '等待'}</span>
        </div>
        <div className={milestoneClass(transcriptReady, false)}>
          <span className="processing-milestone-dot" /><span>全文与发言人</span>
          <span>{transcriptReady ? '可查看' : '等待'}</span>
        </div>
        <div className={milestoneClass(minutesReady, synthesizing)}>
          <span className="processing-milestone-dot" /><span>纪要、决策与总结</span>
          <span>{minutesReady ? '可查看' : synthesizing ? '进行中' : '等待'}</span>
        </div>
      </div>
      <div className="stage-privacy-note">预计进度会随真实处理阶段向前校正，不会用于判断会议内容质量。</div>
    </>
  );
}

export function MeetingProcessingPage() {
  const { meetingId = '' } = useParams();
  const queryClient = useQueryClient();
  const newestSequence = useRef(-1);
  const elapsedSyncRef = useRef({ elapsed: 0, at: 0 });
  const [, forceTick] = useState(0);
  const [stableDetail, setStableDetail] = useState<MeetingDetail | undefined>();
  const [cancelDialogOpen, setCancelDialogOpen] = useState(false);

  const detailQuery = useQuery({
    queryKey: ['meeting', meetingId],
    queryFn: () => meetingApi.getMeeting(meetingId),
    enabled: Boolean(meetingId),
    refetchInterval: (query) => (isPolling(query.state.data) ? 2000 : false),
  });

  const diagnosticsQuery = useQuery({
    queryKey: ['meeting-diagnostics', meetingId],
    queryFn: () => meetingApi.getMeeting(meetingId, { includeDiagnostics: true }),
    enabled: Boolean(meetingId && stableDetail?.state === 'failed'),
    retry: false,
  });

  useEffect(() => {
    const detail = detailQuery.data;
    if (!detail || detail.seq < newestSequence.current) return;
    newestSequence.current = detail.seq;
    setStableDetail(detail);
    // 记录后端已用时与收到它的墙钟时刻，供两次轮询之间在本地平滑跳秒。
    elapsedSyncRef.current = { elapsed: detail.progress.elapsed_seconds, at: Date.now() };
  }, [detailQuery.data]);

  useEffect(() => {
    const detail = diagnosticsQuery.data;
    if (!detail || detail.seq < newestSequence.current) return;
    newestSequence.current = detail.seq;
    setStableDetail(detail);
    queryClient.setQueryData(['meeting', meetingId], detail);
  }, [diagnosticsQuery.data, meetingId, queryClient]);

  // 非终态时每秒本地重渲染，让"已用时"平滑跳动、进度条保持活动反馈。
  const polling = isPolling(stableDetail);
  useEffect(() => {
    if (!polling) return;
    const timer = window.setInterval(() => forceTick((value) => value + 1), 1000);
    return () => window.clearInterval(timer);
  }, [polling]);

  const resultQuery = useQuery({
    queryKey: ['meeting-result', meetingId],
    queryFn: () => meetingApi.getMeetingResult(meetingId),
    enabled: Boolean(stableDetail?.availability.transcript),
    refetchInterval: stableDetail?.state === 'processing' ? 5000 : false,
    retry: false,
  });

  const cancelMutation = useMutation({
    mutationFn: () => meetingApi.cancelMeeting(meetingId),
    onSuccess: (detail) => {
      newestSequence.current = detail.seq;
      setStableDetail(detail);
      queryClient.setQueryData(['meeting', meetingId], detail);
      setCancelDialogOpen(false);
    },
  });

  const retryMutation = useMutation({
    mutationFn: () => meetingApi.retryMeeting(meetingId, 'all'),
    onSuccess: () => {
      queryClient.removeQueries({ queryKey: ['meeting-result', meetingId], exact: true });
      queryClient.invalidateQueries({ queryKey: ['meeting', meetingId], exact: true });
      queryClient.invalidateQueries({ queryKey: ['meetings'] });
    },
  });

  const emptyInspector = <div className="stage-privacy-note">正在读取会议状态。</div>;

  if (detailQuery.isPending && !stableDetail) {
    return (
      <StagePageShell
        className="processing-page"
        activeLabel="处理中"
        activeValue="当前会议"
        breadcrumbs={['会议库', '处理中']}
        topActions={<Link className="stage-quiet-button" to="/meetings">返回会议库</Link>}
        inspectorTitle="处理状态"
        inspector={emptyInspector}
      >
        <div className="processing-page-loading"><span /></div>
      </StagePageShell>
    );
  }

  if (detailQuery.isError || !stableDetail) {
    return (
      <StagePageShell
        className="processing-page"
        activeLabel="会议处理"
        activeValue="读取失败"
        breadcrumbs={['会议库', '会议处理']}
        topActions={<Link className="stage-quiet-button" to="/meetings">返回会议库</Link>}
        inspectorTitle="处理状态"
        inspector={<div className="stage-privacy-note">无法读取当前会议。</div>}
      >
        <div className="stage-page-eyebrow">会议处理</div>
        <h1 className="stage-page-title">无法打开会议</h1>
        <div className="processing-read-error">
          {detailQuery.error instanceof Error ? detailQuery.error.message : '会议不存在'}
        </div>
      </StagePageShell>
    );
  }

  const detail = stableDetail;

  if (detail.error?.code === 'BOARD_UNREACHABLE') {
    const returnTo = encodeURIComponent(`/meetings/${meetingId}/processing`);
    return <Navigate to={`/system/board-offline?returnTo=${returnTo}`} replace />;
  }

  if (['missing', 'invalid', 'unreadable'].includes(detail.file_health.result)) {
    return <Navigate to={`/meetings/${meetingId}/result-unavailable`} replace />;
  }

  const result = resultQuery.data;
  const diagnostics = diagnosticsQuery.data?.diagnostics as MeetingDiagnostics | undefined;
  const rows = result ? transcriptRows(result) : [];
  const completed = detail.state === 'review_ready' || detail.state === 'finalized';
  const failed = detail.state === 'failed';
  const cancelled = detail.state === 'cancelled';
  const remaining = detail.progress.estimated_remaining_seconds;
  const sync = elapsedSyncRef.current;
  const liveElapsedSeconds =
    polling && sync.at > 0
      ? sync.elapsed + Math.max(0, (Date.now() - sync.at) / 1000)
      : detail.progress.elapsed_seconds;
  const statusTitle = failed ? detail.error?.message ?? '处理未完成' : phaseCopy[detail.phase];
  const statusMessage = cancelled
    ? '本次会议处理已经停止'
    : failed
      ? detail.availability.transcript ? '全文和发言人已保留' : '原始音频已保留'
      : completed
        ? '会议已进入待核对状态'
        : detail.availability.transcript
          ? '现在可以查看会议全文和发言人'
          : '转写完成后将自动显示会议全文';
  const speakerCount = result?.speakers?.length ?? 0;

  return (
    <>
      <StagePageShell
        className="processing-page"
        activeLabel={completed ? '待核对' : failed ? '处理未完成' : cancelled ? '已取消' : '处理中'}
        activeValue="当前会议"
        breadcrumbs={['会议库', completed ? '待核对' : failed ? '处理未完成' : cancelled ? '已取消' : '处理中']}
        topActions={<Link className="stage-quiet-button" to="/meetings">返回会议库</Link>}
        inspectorTitle="处理状态"
        inspector={<ProcessingInspector detail={detail} />}
      >
        <div className="stage-page-eyebrow">{completed ? '会议已完成' : failed ? '处理未完成' : cancelled ? '任务已取消' : '会议处理中'}</div>
        <h1 className="stage-page-title">{detail.title}</h1>
        <div className="processing-context">
          <span>{detail.source_label}</span>
          <span>{detail.audio.duration_ms === null ? '待计算' : formatDuration(detail.audio.duration_ms)}</span>
          <span>{detail.source.original_name ?? '会议录音'}</span>
        </div>

        <section className={failed ? 'processing-progress-card processing-progress-card-error' : 'processing-progress-card'}>
          <div className="processing-progress-head">
            <div>
              <div className="processing-status-line">
                <span className={completed ? 'processing-status-dot processing-status-dot-complete' : failed || cancelled ? 'processing-status-dot processing-status-dot-error' : 'processing-status-dot'} />
                <strong>{statusTitle}</strong>
              </div>
              <p>{statusMessage}</p>
            </div>
            <div className="processing-progress-value">{detail.progress.percent}%</div>
          </div>
          <div className={`processing-progress-track${polling ? ' is-active' : ''}`} aria-label={`处理进度 ${detail.progress.percent}%`}>
            <span style={{ width: `${detail.progress.percent}%` }} />
          </div>
          <div className="processing-progress-meta">
            <span>已用时 {formatDuration(Math.round(liveElapsedSeconds) * 1000)}</span>
            <span>
              {completed ? '处理完成' : remaining === null ? '剩余时间待确认' : `${detail.progress.estimated ? '预计' : ''}还需 ${formatDuration(remaining * 1000)}`}
            </span>
          </div>
          <div className="processing-progress-actions">
            {detail.capabilities.can_cancel && !cancelled ? (
              <button className="processing-action-button processing-action-danger" type="button" onClick={() => setCancelDialogOpen(true)}>取消任务</button>
            ) : null}
            {completed ? <Link className="processing-action-button processing-action-primary" to={`/meetings/${meetingId}/review`}>查看完整纪要</Link> : null}
            {failed && detail.capabilities.can_retry_all ? (
              <button className="processing-action-button processing-action-primary" type="button" disabled={retryMutation.isPending} onClick={() => retryMutation.mutate()}>
                {retryMutation.isPending ? '正在重新处理' : '重新处理原始音频'}
              </button>
            ) : null}
          </div>
        </section>

        {failed ? <FailureDiagnostics detail={detail} diagnostics={diagnostics} /> : null}

        {detail.availability.transcript ? (
          <section className="processing-transcript-panel" aria-labelledby="processingTranscriptTitle">
            <div className="processing-transcript-head">
              <div>
                <h2 id="processingTranscriptTitle">会议全文</h2>
                <span>转写已完成</span>
              </div>
              <span>{speakerCount} 位发言人</span>
            </div>
            {resultQuery.isPending ? (
              <div className="processing-transcript-loading"><span /><span /><span /></div>
            ) : resultQuery.isError ? (
              <div className="processing-transcript-empty">全文暂时无法读取</div>
            ) : rows.length === 0 ? (
              <div className="processing-transcript-empty">全文结果为空</div>
            ) : (
              <div className="processing-transcript-body">
                {rows.map((segment) => (
                  <article className="processing-transcript-turn" key={segment.segment_id}>
                    <h3>{segment.speaker}:</h3>
                    <p>{segment.text}</p>
                  </article>
                ))}
              </div>
            )}
          </section>
        ) : null}

        <div className="processing-minutes-wait">
          <strong>{detail.availability.minutes ? '纪要、决策和总结已准备查看' : '纪要、决策和总结将在转写完成后继续生成'}</strong>
          <span>
            {detail.availability.minutes
              ? '可以进入会议工作区核对内容。'
              : detail.availability.transcript
                ? '全文和发言人已可查看，其他结果仍在后台生成。'
                : '全文准备好后将自动显示。'}
          </span>
        </div>
      </StagePageShell>

      {cancelDialogOpen ? (
        <div className="processing-dialog-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setCancelDialogOpen(false); }}>
          <section className="processing-dialog" role="dialog" aria-modal="true" aria-labelledby="cancelMeetingTitle">
            <h2 id="cancelMeetingTitle">取消这次处理？</h2>
            <p>取消后，本次会议不会继续生成新的处理结果。</p>
            {cancelMutation.isError ? <div className="processing-dialog-error">取消失败，请重试</div> : null}
            <div className="processing-dialog-actions">
              <button className="processing-action-button" type="button" onClick={() => setCancelDialogOpen(false)}>继续处理</button>
              <button className="processing-action-button processing-action-danger" type="button" disabled={cancelMutation.isPending} onClick={() => cancelMutation.mutate()}>
                {cancelMutation.isPending ? '正在取消' : '确认取消'}
              </button>
            </div>
          </section>
        </div>
      ) : null}
    </>
  );
}
