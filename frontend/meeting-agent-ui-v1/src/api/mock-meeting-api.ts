import type { MeetingApi } from './meeting-api';
import { meetingStatusForFilter } from './meeting-api';
import type {
  BoardConnectionCheckResponse,
  BoardRecordingStatusResponse,
  CleanupTemporaryFilesResponse,
  CreateMeetingInput,
  CreatedMeeting,
  DeleteMeetingAudioResponse,
  ExportFormat,
  ExportItem,
  FinalizeMeetingInput,
  FinalizeMeetingResponse,
  GatewayInfo,
  MeetingDetail,
  MeetingDraft,
  MeetingDraftContent,
  MeetingExportsResponse,
  MeetingFilter,
  MeetingListResponse,
  MeetingQuery,
  MeetingResultV1,
  MeetingRevealResponse,
  MeetingRevealTarget,
  MeetingSettings,
  RemoveMeetingIndexResponse,
  RescanMeetingResponse,
  RetryMeetingResponse,
  RetryMeetingScope,
  RevealResponse,
  RevealTarget,
  ReviewStatus,
  SaveMeetingDraftInput,
  SaveMeetingDraftResponse,
  StartBoardRecordingResponse,
  StopBoardRecordingResponse,
  StorageMeetingListResponse,
  StoragePathCheckResponse,
  StorageSummary,
  UpdateMeetingSettingsInput,
} from './types';
import {
  fixtureDetails,
  fixtureResults,
  partialAvailability,
} from '../fixtures/meetings';

const wait = (milliseconds = 180) => new Promise((resolve) => window.setTimeout(resolve, milliseconds));

function clone<T>(value: T): T {
  return structuredClone(value);
}

function emptyFacets(): Record<MeetingFilter, number> {
  return { all: 0, processing: 0, failed: 0, review: 0, confirmed: 0, deleted: 0 };
}

function buildReviewMarks(result: MeetingResultV1): Record<string, ReviewStatus> {
  const marks: Record<string, ReviewStatus> = {};

  for (const decision of result.decisions ?? []) {
    marks[decision.decision_id] = decision.review_status;
  }
  for (const action of result.action_items ?? []) {
    marks[action.action_id] = action.review_status;
  }
  for (const node of (result.minutes?.outline ?? []).slice(0, 2)) {
    marks[node.node_id] = node.review_status;
  }

  return marks;
}

function draftContentFromResult(
  result: MeetingResultV1,
  title: string,
  finalized: boolean,
): MeetingDraftContent {
  const normalizeStatus = (status: ReviewStatus): ReviewStatus => (finalized ? 'reviewed' : status);
  const reviewMarks = buildReviewMarks(result);

  if (finalized) {
    for (const key of Object.keys(reviewMarks)) reviewMarks[key] = 'reviewed';
  }

  return {
    title,
    speaker_names: Object.fromEntries(
      (result.speakers ?? []).map((speaker) => [speaker.speaker_id, speaker.display_name]),
    ),
    transcript_edits: [],
    minutes: result.minutes
      ? {
          ...clone(result.minutes),
          outline: result.minutes.outline.map((node) => ({
            ...clone(node),
            review_status: normalizeStatus(node.review_status),
          })),
        }
      : null,
    chapters: (result.chapters ?? []).map((chapter) => ({
      ...clone(chapter),
      review_status: normalizeStatus(chapter.review_status),
    })),
    decisions: (result.decisions ?? []).map((decision) => ({
      ...clone(decision),
      review_status: normalizeStatus(decision.review_status),
    })),
    action_items: (result.action_items ?? []).map((action) => ({
      ...clone(action),
      review_status: normalizeStatus(action.review_status),
    })),
    review_marks: reviewMarks,
  };
}

function reviewSummary(content: MeetingDraftContent) {
  const statuses = Object.values(content.review_marks);
  return {
    pending_count: statuses.filter((status) => status === 'pending').length,
    reviewed_count: statuses.filter((status) => status !== 'pending').length,
  };
}

interface MockBoardRecording {
  recording_id: string;
  device_id: string;
  started_at: string;
  started_at_ms: number;
  elapsed_seconds: number;
  state: 'recording' | 'stopped';
}

function exportItem(
  meeting: MeetingDetail,
  format: ExportFormat,
  state: ExportItem['state'],
): ExportItem {
  const safeTitle = meeting.title.replace(/[\\/:*?"<>|]/g, '-');
  const ready = state === 'ready';
  return {
    format,
    state,
    file_name: ready ? `${safeTitle}.${format}` : null,
    size_bytes: ready ? (format === 'html' ? 48240 : format === 'txt' ? 18620 : 72380) : null,
    created_at: ready ? meeting.updated_at : null,
    content_url: null,
    error: null,
  };
}

export class MockMeetingApi implements MeetingApi {
  private readonly meetings = fixtureDetails.map(clone);
  private readonly results = Object.fromEntries(
    Object.entries(fixtureResults).map(([key, value]) => [key, clone(value)]),
  );
  private readonly drafts: Record<string, MeetingDraft> = {};
  private readonly exports: Record<string, ExportItem[]> = {};
  private readonly boardRecordings: Record<string, MockBoardRecording> = {};
  private settings: MeetingSettings = {
    device_name: '会议室 RK1828',
    board: {
      address: '10.10.22.36',
      port: 18080,
      base_url: 'http://10.10.22.36:18080',
    },
    model_profile: 'qwen3-4b-v104-ctx16k',
    meeting_library_path: 'D:\\Meeting_Agent_fresh\\runtime\\meeting_library',
    keep_audio_until_finalized: true,
    default_export_formats: ['html', 'txt', 'json'],
    default_language: 'zh-CN',
  };
  private storageSummary: StorageSummary = {
    path: 'D:\\Meeting_Agent_fresh\\runtime\\meeting_library',
    writable: true,
    total_bytes: 214748364800,
    used_bytes: 83751862272,
    free_bytes: 131001502528,
    status: 'ok',
    categories: {
      audio_bytes: 58841051955,
      results_bytes: 12025908429,
      exports_bytes: 1825361100,
      temp_bytes: 11059500800,
      other_bytes: 0,
    },
    thresholds: {
      warning_free_bytes: 10737418240,
      minimum_free_bytes: 3221225472,
    },
    updated_at: new Date().toISOString(),
  };

  async getGatewayInfo(): Promise<GatewayInfo> {
    await wait(120);
    return {
      service: 'meeting-agent-gateway-mock',
      version: '1.0.0-mock',
      api_contract_version: 'meeting-agent.api.v1',
      status: 'ready',
      local_only: true,
      base_url: 'http://127.0.0.1:8787',
      board_url: 'http://10.10.22.36:18080',
      capabilities: {
        meeting_library: true,
        local_upload: true,
        pc_record: true,
        board_record: true,
        partial_result: true,
        draft: true,
        finalize: true,
        audio_delete: true,
      },
    };
  }

  async listMeetings(query: MeetingQuery = {}): Promise<MeetingListResponse> {
    await wait();
    const facets = emptyFacets();
    for (const meeting of this.meetings) {
      facets.all += 1;
      const filter = meetingStatusForFilter(meeting.state, meeting.audio.state);
      if (filter !== 'all') facets[filter] += 1;
    }

    const q = query.q?.trim().toLocaleLowerCase('zh-CN') ?? '';
    let items = this.meetings.filter((meeting) => {
      const status = query.status ?? 'all';
      const matchesStatus =
        status === 'all' || meetingStatusForFilter(meeting.state, meeting.audio.state) === status;
      const matchesQuery = !q || meeting.title.toLocaleLowerCase('zh-CN').includes(q);
      return matchesStatus && matchesQuery;
    });

    if (query.sort === 'title_asc') {
      items = [...items].sort((left, right) => left.title.localeCompare(right.title, 'zh-CN'));
    } else {
      items = [...items].sort((left, right) => right.updated_at.localeCompare(left.updated_at));
    }

    return {
      items: items.map(clone),
      page: 1,
      page_size: 30,
      total: items.length,
      has_more: false,
      facets,
    };
  }

  async createMeeting(input: CreateMeetingInput): Promise<CreatedMeeting> {
    await wait(260);
    const meetingId = `meeting-local-${Date.now()}`;
    const now = new Date().toISOString();
    const extension = input.source_file?.name.split('.').pop()?.toLowerCase() ?? null;
    const detail: MeetingDetail = {
      meeting_id: meetingId,
      title: input.title,
      source_type: input.source_type,
      source_label: input.source_type === 'local_upload' ? '本地音频' : input.source_type === 'pc_record' ? 'PC 录音' : '板端录音',
      state: 'created',
      phase: 'awaiting_source',
      progress: {
        percent: 0,
        estimated: true,
        elapsed_seconds: 0,
        estimated_total_seconds: 300,
        estimated_remaining_seconds: 300,
      },
      availability: {
        transcript: false,
        speakers: false,
        minutes: false,
        chapters: false,
        decisions: false,
        action_items: false,
        evidence: false,
        formal_version: false,
      },
      review: { pending_count: 0, reviewed_count: 0, dirty: false, draft_revision: 0 },
      audio: {
        state: 'pending',
        duration_ms: null,
        size_bytes: input.source_file?.size_bytes ?? null,
        playable: false,
        deleted_at: null,
      },
      meeting_date: now,
      created_at: now,
      updated_at: now,
      language: input.language ?? 'zh-CN',
      source: {
        type: input.source_type,
        original_name: input.source_file?.name ?? null,
        original_extension: extension,
        mime_type: input.source_file?.mime_type ?? null,
        size_bytes: input.source_file?.size_bytes ?? null,
        sha256: null,
        requires_conversion: extension !== null && extension !== 'wav',
      },
      raw_stage: 'awaiting_audio',
      seq: 1,
      capabilities: {
        can_cancel: false,
        can_retry_all: false,
        can_retry_summary: false,
        can_edit: false,
        can_save_draft: false,
        can_finalize: false,
        can_play_audio: false,
        can_delete_audio: false,
        can_reveal_files: true,
        can_remove_index: true,
      },
      file_health: {
        metadata: 'available',
        source_audio: 'not_created',
        result: 'not_created',
        draft: 'not_created',
        formal_html: 'not_created',
        formal_txt: 'not_created',
        formal_json: 'not_created',
      },
      error: null,
    };
    this.meetings.unshift(detail);
    return {
      meeting_id: meetingId,
      title: input.title,
      state: 'created',
      phase: 'awaiting_source',
      source_type: input.source_type,
      created_at: now,
    };
  }

  async uploadAudio(meetingId: string, file: File): Promise<MeetingDetail> {
    await wait(520);
    const meeting = this.findMeeting(meetingId);
    meeting.state = 'processing';
    meeting.phase = 'transcribing';
    meeting.progress = {
      percent: 12,
      estimated: true,
      elapsed_seconds: 36,
      estimated_total_seconds: 300,
      estimated_remaining_seconds: 264,
    };
    meeting.audio = {
      state: 'available',
      duration_ms: null,
      size_bytes: file.size,
      playable: true,
      deleted_at: null,
    };
    meeting.capabilities.can_cancel = true;
    meeting.capabilities.can_play_audio = true;
    meeting.file_health.source_audio = 'available';
    meeting.raw_stage = 'batch_asr';
    meeting.seq += 1;
    meeting.updated_at = new Date().toISOString();
    this.results[meetingId] = {
      schema_version: 'meeting-result.v1',
      meeting_id: meetingId,
      result_revision: 0,
      language: 'zh-CN',
      duration_ms: 0,
      generated_at: meeting.updated_at,
      availability: clone(partialAvailability),
      transcript: null,
      speakers: null,
      minutes: null,
      chapters: null,
      decisions: null,
      action_items: null,
      evidence: null,
      diagnostics: null,
    };
    return clone(meeting);
  }

  async startBoardRecording(
    meetingId: string,
    deviceId: string,
  ): Promise<StartBoardRecordingResponse> {
    await wait(320);
    const meeting = this.findMeeting(meetingId);
    if (meeting.source_type !== 'board_record') throw new Error('当前会议不是板端录音');
    if (meeting.state !== 'created') throw new Error('当前会议不可开始板端录音');

    const startedAtMs = Date.now();
    const startedAt = new Date(startedAtMs).toISOString();
    const recordingId = `recording-${startedAtMs.toString(36)}`;
    this.boardRecordings[meetingId] = {
      recording_id: recordingId,
      device_id: deviceId,
      started_at: startedAt,
      started_at_ms: startedAtMs,
      elapsed_seconds: 0,
      state: 'recording',
    };

    meeting.state = 'recording';
    meeting.phase = 'recording';
    meeting.audio = {
      state: 'recording',
      duration_ms: 0,
      size_bytes: null,
      playable: false,
      deleted_at: null,
    };
    meeting.progress = {
      percent: 0,
      estimated: false,
      elapsed_seconds: 0,
      estimated_total_seconds: null,
      estimated_remaining_seconds: null,
    };
    meeting.raw_stage = 'board_recording';
    meeting.seq += 1;
    meeting.updated_at = startedAt;

    return {
      meeting_id: meetingId,
      recording_id: recordingId,
      state: 'recording',
      recording: {
        state: 'recording',
        device_id: deviceId,
        started_at: startedAt,
        elapsed_seconds: 0,
        audio_saved: true,
        connection: 'online',
      },
    };
  }

  async getBoardRecording(meetingId: string): Promise<BoardRecordingStatusResponse> {
    await wait(90);
    const recording = this.boardRecordings[meetingId];
    if (!recording) throw new Error('板端录音会话不存在');
    const elapsedSeconds = recording.state === 'recording'
      ? Math.max(0, Math.floor((Date.now() - recording.started_at_ms) / 1000))
      : recording.elapsed_seconds;
    recording.elapsed_seconds = elapsedSeconds;

    const meeting = this.findMeeting(meetingId);
    if (recording.state === 'recording') {
      meeting.progress.elapsed_seconds = elapsedSeconds;
      meeting.audio.duration_ms = elapsedSeconds * 1000;
    }

    return {
      meeting_id: meetingId,
      recording_id: recording.recording_id,
      state: recording.state,
      device_id: recording.device_id,
      started_at: recording.started_at,
      elapsed_seconds: elapsedSeconds,
      audio_saved: true,
      connection: 'online',
      error: null,
    };
  }

  async stopBoardRecording(meetingId: string): Promise<StopBoardRecordingResponse> {
    await wait(420);
    const meeting = this.findMeeting(meetingId);
    const recording = this.boardRecordings[meetingId];
    if (!recording || recording.state !== 'recording') throw new Error('板端录音尚未开始');

    const elapsedSeconds = Math.max(1, Math.floor((Date.now() - recording.started_at_ms) / 1000));
    recording.elapsed_seconds = elapsedSeconds;
    recording.state = 'stopped';

    const updatedAt = new Date().toISOString();
    meeting.state = 'processing';
    meeting.phase = 'transcribing';
    meeting.progress = {
      percent: 12,
      estimated: true,
      elapsed_seconds: 0,
      estimated_total_seconds: 300,
      estimated_remaining_seconds: 300,
    };
    meeting.audio = {
      state: 'available',
      duration_ms: elapsedSeconds * 1000,
      size_bytes: elapsedSeconds * 32000,
      playable: true,
      deleted_at: null,
    };
    meeting.capabilities.can_cancel = true;
    meeting.capabilities.can_play_audio = true;
    meeting.file_health.source_audio = 'available';
    meeting.raw_stage = 'batch_asr';
    meeting.seq += 1;
    meeting.updated_at = updatedAt;
    this.results[meetingId] = {
      schema_version: 'meeting-result.v1',
      meeting_id: meetingId,
      result_revision: 0,
      language: meeting.language,
      duration_ms: elapsedSeconds * 1000,
      generated_at: updatedAt,
      availability: clone(partialAvailability),
      transcript: null,
      speakers: null,
      minutes: null,
      chapters: null,
      decisions: null,
      action_items: null,
      evidence: null,
      diagnostics: null,
    };

    return {
      meeting_id: meetingId,
      recording_id: recording.recording_id,
      recording: {
        state: 'stopped',
        elapsed_seconds: elapsedSeconds,
        audio_saved: true,
      },
      state: 'processing',
      phase: 'transcribing',
    };
  }

  async getSettings(): Promise<MeetingSettings> {
    await wait(140);
    return clone(this.settings);
  }

  async saveSettings(input: UpdateMeetingSettingsInput): Promise<MeetingSettings> {
    await wait(360);
    const deviceName = input.device_name.trim();
    const address = input.board.address.trim();
    const path = input.meeting_library_path.trim();
    if (!deviceName) throw new Error('请输入设备名称');
    if (!address) throw new Error('请输入 RK1828 地址');
    if (!Number.isInteger(input.board.port) || input.board.port < 1 || input.board.port > 65535) {
      throw new Error('端口必须为 1–65535');
    }
    if (!path) throw new Error('请输入会议库目录');
    if (input.default_export_formats.length === 0) throw new Error('至少选择一种默认导出格式');

    this.settings = {
      ...clone(input),
      device_name: deviceName,
      board: {
        address,
        port: input.board.port,
        base_url: `http://${address}:${input.board.port}`,
      },
      meeting_library_path: path,
      model_profile: this.settings.model_profile,
    };
    this.storageSummary = {
      ...this.storageSummary,
      path,
      updated_at: new Date().toISOString(),
    };
    return clone(this.settings);
  }

  async checkBoardConnection(
    address: string,
    port: number,
  ): Promise<BoardConnectionCheckResponse> {
    await wait(640);
    if (!address.trim() || !Number.isInteger(port) || port < 1 || port > 65535) {
      throw new Error('RK1828 地址或端口无效');
    }
    const online = address.trim().toLowerCase() !== 'offline';
    return {
      status: online ? 'online' : 'offline',
      board_id: online ? 'linaro-alip' : null,
      protocol_version: online ? 'board-agent.v1' : null,
      agent_version: online ? '0.2.0' : null,
      model_profile: online ? this.settings.model_profile : null,
      compatible: online,
      latency_ms: online ? 18 : null,
    };
  }

  async checkStoragePath(path: string): Promise<StoragePathCheckResponse> {
    await wait(280);
    const compatible = Boolean(path.trim());
    return {
      exists: compatible,
      writable: compatible,
      total_bytes: compatible ? this.storageSummary.total_bytes : 0,
      free_bytes: compatible ? this.storageSummary.free_bytes : 0,
      compatible,
    };
  }

  async getStorageSummary(): Promise<StorageSummary> {
    await wait(140);
    return clone(this.storageSummary);
  }

  async listStorageMeetings(): Promise<StorageMeetingListResponse> {
    await wait(160);
    const items = [...this.meetings]
      .sort((left, right) => (right.audio.size_bytes ?? 0) - (left.audio.size_bytes ?? 0))
      .map((meeting) => ({
        meeting_id: meeting.meeting_id,
        title: meeting.title,
        meeting_state: meeting.state,
        audio_state: meeting.audio.state,
        audio_size_bytes: meeting.audio.size_bytes,
        meeting_date: meeting.meeting_date,
        can_delete_audio: meeting.state === 'finalized'
          && meeting.capabilities.can_delete_audio
          && meeting.audio.state === 'available',
      }));
    return {
      items,
      page: 1,
      page_size: 30,
      total: items.length,
      has_more: false,
    };
  }

  async cleanupTemporaryFiles(): Promise<CleanupTemporaryFilesResponse> {
    await wait(480);
    const freedBytes = this.storageSummary.categories.temp_bytes;
    const freeBytes = Math.min(this.storageSummary.total_bytes, this.storageSummary.free_bytes + freedBytes);
    const status = freeBytes < this.storageSummary.thresholds.minimum_free_bytes
      ? 'insufficient'
      : freeBytes < this.storageSummary.thresholds.warning_free_bytes
        ? 'warning'
        : 'ok';
    this.storageSummary = {
      ...this.storageSummary,
      used_bytes: Math.max(0, this.storageSummary.used_bytes - freedBytes),
      free_bytes: freeBytes,
      status,
      categories: {
        ...this.storageSummary.categories,
        temp_bytes: 0,
      },
      updated_at: new Date().toISOString(),
    };
    return {
      freed_bytes: freedBytes,
      deleted_file_count: freedBytes > 0 ? 42 : 0,
      skipped_active_file_count: freedBytes > 0 ? 3 : 0,
      storage: {
        free_bytes: freeBytes,
        status,
      },
    };
  }

  async revealSystemTarget(target: RevealTarget): Promise<RevealResponse> {
    await wait(180);
    return { opened: true, target };
  }

  async getMeeting(meetingId: string, _options?: { includeDiagnostics?: boolean }): Promise<MeetingDetail> {
    await wait(120);
    return clone(this.findMeeting(meetingId));
  }

  async getMeetingResult(meetingId: string, _options?: { includeDiagnostics?: boolean }): Promise<MeetingResultV1> {
    await wait(120);
    const result = this.results[meetingId];
    if (!result) throw new Error('会议结果尚未可用');
    return clone(result);
  }

  async retryMeeting(
    meetingId: string,
    scope: RetryMeetingScope,
  ): Promise<RetryMeetingResponse> {
    await wait(520);
    const meeting = this.findMeeting(meetingId);
    const sourceAvailable = meeting.file_health.source_audio === 'available';
    const summaryAvailable = meeting.availability.transcript && meeting.availability.speakers;

    if ((scope === 'all' || scope === 'upload') && (!meeting.capabilities.can_retry_all || !sourceAvailable)) {
      throw new Error('原始音频不可用，无法重新处理');
    }
    if (scope === 'summary' && (!meeting.capabilities.can_retry_summary || !summaryAvailable)) {
      throw new Error('全文或发言人结果不可用，无法重新生成纪要');
    }

    const retryingSummary = scope === 'summary';
    const now = new Date().toISOString();
    meeting.state = scope === 'exports' ? 'finalizing' : 'processing';
    meeting.phase = scope === 'exports' ? 'exporting' : retryingSummary ? 'synthesizing' : 'transcribing';
    meeting.progress = {
      percent: retryingSummary ? 52 : 8,
      estimated: true,
      elapsed_seconds: 0,
      estimated_total_seconds: 300,
      estimated_remaining_seconds: 300,
    };
    meeting.error = null;
    meeting.capabilities.can_retry_all = false;
    meeting.capabilities.can_retry_summary = false;
    meeting.capabilities.can_cancel = scope !== 'exports';
    meeting.availability = retryingSummary
      ? { ...meeting.availability, minutes: false, chapters: false, decisions: false, action_items: false, formal_version: false }
      : {
          transcript: false,
          speakers: false,
          minutes: false,
          chapters: false,
          decisions: false,
          action_items: false,
          evidence: false,
          formal_version: false,
        };
    meeting.file_health.result = retryingSummary ? 'partial' : 'not_created';
    meeting.seq += 1;
    meeting.updated_at = now;
    if (!retryingSummary) delete this.results[meetingId];

    return {
      meeting_id: meetingId,
      state: meeting.state,
      phase: meeting.phase,
      retry_scope: scope,
      result_revision: (this.results[meetingId]?.result_revision ?? 1) + 1,
      availability: clone(meeting.availability),
    };
  }

  async rescanMeeting(meetingId: string): Promise<RescanMeetingResponse> {
    await wait(460);
    const meeting = this.findMeeting(meetingId);
    return {
      meeting_id: meetingId,
      file_health: clone(meeting.file_health),
      capabilities: clone(meeting.capabilities),
      scanned_at: new Date().toISOString(),
    };
  }

  async revealMeeting(
    meetingId: string,
    target: MeetingRevealTarget,
  ): Promise<MeetingRevealResponse> {
    await wait(180);
    this.findMeeting(meetingId);
    return { meeting_id: meetingId, opened: true, target };
  }

  async removeMeetingIndex(meetingId: string): Promise<RemoveMeetingIndexResponse> {
    await wait(360);
    const index = this.meetings.findIndex((meeting) => meeting.meeting_id === meetingId);
    if (index < 0) throw new Error('会议记录不存在');
    this.meetings.splice(index, 1);
    delete this.results[meetingId];
    delete this.drafts[meetingId];
    delete this.exports[meetingId];
    return {
      meeting_id: meetingId,
      removed_from_library: true,
      files_deleted: false,
      files_retained: true,
    };
  }

  getMeetingAudioUrl(): null {
    return null;
  }

  async getMeetingDraft(meetingId: string): Promise<MeetingDraft> {
    await wait(140);
    return clone(this.getOrCreateDraft(meetingId));
  }

  async saveMeetingDraft(
    meetingId: string,
    input: SaveMeetingDraftInput,
  ): Promise<SaveMeetingDraftResponse> {
    await wait(320);
    const meeting = this.findMeeting(meetingId);
    if (meeting.state !== 'review_ready' || !meeting.capabilities.can_save_draft) {
      throw new Error('当前会议不可保存草稿');
    }

    const draft = this.getOrCreateDraft(meetingId);
    if (input.expected_revision !== draft.revision) {
      throw new Error(`草稿版本冲突，当前版本为 ${draft.revision}`);
    }
    if (input.base_result_revision !== draft.base_result_revision) {
      throw new Error('会议结果已更新，请重新载入后保存');
    }

    const savedAt = new Date().toISOString();
    const revision = draft.revision + 1;
    const content = clone(input.content);
    this.drafts[meetingId] = {
      ...draft,
      revision,
      updated_at: savedAt,
      dirty: false,
      content,
    };

    const summary = reviewSummary(content);
    meeting.title = content.title.trim() || meeting.title;
    meeting.review = {
      ...summary,
      dirty: false,
      draft_revision: revision,
    };
    meeting.file_health.draft = 'available';
    meeting.seq += 1;
    meeting.updated_at = savedAt;

    return {
      meeting_id: meetingId,
      revision,
      base_result_revision: draft.base_result_revision,
      saved_at: savedAt,
      review: clone(meeting.review),
    };
  }

  async finalizeMeeting(
    meetingId: string,
    input: FinalizeMeetingInput,
  ): Promise<FinalizeMeetingResponse> {
    await wait(220);
    const meeting = this.findMeeting(meetingId);
    const draft = this.getOrCreateDraft(meetingId);

    if (meeting.state !== 'review_ready' || !meeting.capabilities.can_finalize) {
      throw new Error('当前会议不可确认');
    }
    if (!input.confirmed || input.formats.length === 0) {
      throw new Error('请选择导出格式并确认当前内容');
    }
    if (input.draft_revision !== draft.revision) {
      throw new Error(`草稿版本冲突，当前版本为 ${draft.revision}`);
    }

    const formats = [...new Set(input.formats)];
    const startedAt = new Date().toISOString();
    meeting.state = 'finalizing';
    meeting.phase = 'exporting';
    meeting.capabilities.can_edit = false;
    meeting.capabilities.can_save_draft = false;
    meeting.capabilities.can_finalize = false;
    meeting.seq += 1;
    meeting.updated_at = startedAt;
    this.exports[meetingId] = formats.map((format) => exportItem(meeting, format, 'generating'));

    await wait(760);

    const completedAt = new Date().toISOString();
    meeting.state = 'finalized';
    meeting.phase = 'ready';
    meeting.availability.formal_version = true;
    meeting.capabilities.can_delete_audio = meeting.audio.state === 'available';
    meeting.progress.percent = 100;
    meeting.progress.estimated = false;
    meeting.progress.estimated_remaining_seconds = 0;
    meeting.seq += 1;
    meeting.updated_at = completedAt;
    this.exports[meetingId] = formats.map((format) => exportItem(meeting, format, 'ready'));

    for (const format of formats) {
      if (format === 'html') meeting.file_health.formal_html = 'available';
      if (format === 'txt') meeting.file_health.formal_txt = 'available';
      if (format === 'json') meeting.file_health.formal_json = 'available';
    }

    return {
      meeting_id: meetingId,
      state: 'finalized',
      phase: 'ready',
      draft_revision: draft.revision,
      exports: clone(this.exports[meetingId]),
    };
  }

  async getMeetingExports(meetingId: string): Promise<MeetingExportsResponse> {
    await wait(120);
    const meeting = this.findMeeting(meetingId);
    if (!this.exports[meetingId] && meeting.state === 'finalized') {
      this.exports[meetingId] = (['html', 'txt', 'json'] as ExportFormat[]).map((format) =>
        exportItem(meeting, format, 'ready'),
      );
    }
    return {
      meeting_id: meetingId,
      state: meeting.state,
      items: clone(this.exports[meetingId] ?? []),
    };
  }

  getMeetingExportUrl(): null {
    return null;
  }

  async deleteMeetingAudio(
    meetingId: string,
    confirmation: string,
  ): Promise<DeleteMeetingAudioResponse> {
    await wait(360);
    const meeting = this.findMeeting(meetingId);
    if (confirmation !== '删除音频') throw new Error('确认文字不正确');
    if (meeting.state !== 'finalized' || !meeting.capabilities.can_delete_audio) {
      throw new Error('当前会议不可删除原始音频');
    }
    if (meeting.audio.state === 'deleted') throw new Error('原始音频已删除');

    const freedBytes = meeting.audio.size_bytes ?? 0;
    const deletedAt = new Date().toISOString();
    meeting.audio = {
      ...meeting.audio,
      state: 'deleted',
      size_bytes: null,
      playable: false,
      deleted_at: deletedAt,
    };
    meeting.capabilities.can_play_audio = false;
    meeting.capabilities.can_delete_audio = false;
    meeting.file_health.source_audio = 'deleted';
    meeting.seq += 1;
    meeting.updated_at = deletedAt;

    const freeBytes = Math.min(this.storageSummary.total_bytes, this.storageSummary.free_bytes + freedBytes);
    const storageStatus = freeBytes < this.storageSummary.thresholds.minimum_free_bytes
      ? 'insufficient'
      : freeBytes < this.storageSummary.thresholds.warning_free_bytes
        ? 'warning'
        : 'ok';
    this.storageSummary = {
      ...this.storageSummary,
      used_bytes: Math.max(0, this.storageSummary.used_bytes - freedBytes),
      free_bytes: freeBytes,
      status: storageStatus,
      categories: {
        ...this.storageSummary.categories,
        audio_bytes: Math.max(0, this.storageSummary.categories.audio_bytes - freedBytes),
      },
      updated_at: deletedAt,
    };

    return {
      meeting_id: meetingId,
      audio: {
        state: 'deleted',
        playable: false,
        deleted_at: deletedAt,
      },
      freed_bytes: freedBytes,
      retained: {
        transcript: true,
        speakers: true,
        minutes: true,
        chapters: true,
        decisions: true,
        action_items: true,
        evidence_text: true,
        evidence_timestamps: true,
        formal_versions: true,
      },
    };
  }

  async cancelMeeting(meetingId: string): Promise<MeetingDetail> {
    await wait(220);
    const meeting = this.findMeeting(meetingId);
    meeting.state = 'cancelled';
    meeting.phase = 'cancelled';
    meeting.raw_stage = 'cancelled';
    meeting.capabilities.can_cancel = false;
    meeting.progress.estimated_remaining_seconds = null;
    meeting.seq += 1;
    meeting.updated_at = new Date().toISOString();
    return clone(meeting);
  }

  private getOrCreateDraft(meetingId: string): MeetingDraft {
    const existing = this.drafts[meetingId];
    if (existing) return existing;

    const meeting = this.findMeeting(meetingId);
    const result = this.results[meetingId];
    if (!result) throw new Error('会议结果尚未可用');

    const revision = meeting.review.draft_revision ?? 0;
    const draft: MeetingDraft = {
      schema_version: 'meeting-draft.v1',
      meeting_id: meetingId,
      revision,
      base_result_revision: result.result_revision,
      updated_at: revision > 0 ? meeting.updated_at : null,
      dirty: false,
      content: draftContentFromResult(result, meeting.title, meeting.state === 'finalized'),
    };
    this.drafts[meetingId] = draft;
    return draft;
  }

  private findMeeting(meetingId: string): MeetingDetail {
    const meeting = this.meetings.find((item) => item.meeting_id === meetingId);
    if (!meeting) throw new Error('会议不存在');
    return meeting;
  }
}
