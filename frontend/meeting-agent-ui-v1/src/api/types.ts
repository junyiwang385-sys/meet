export type MeetingSourceType = 'local_upload' | 'pc_record' | 'board_record';

export type MeetingState =
  | 'created'
  | 'recording'
  | 'uploading'
  | 'processing'
  | 'review_ready'
  | 'finalizing'
  | 'finalized'
  | 'failed'
  | 'cancelled';

export type MeetingPhase =
  | 'awaiting_source'
  | 'recording'
  | 'uploading'
  | 'converting'
  | 'transcribing'
  | 'synthesizing'
  | 'exporting'
  | 'ready'
  | 'cancelled';

export type AudioState =
  | 'pending'
  | 'recording'
  | 'uploading'
  | 'converting'
  | 'available'
  | 'deleted'
  | 'missing'
  | 'unreadable';

export type ReviewStatus = 'pending' | 'reviewed' | 'edited';
export type MeetingFilter = 'all' | 'processing' | 'failed' | 'review' | 'confirmed' | 'deleted';

export interface ResultAvailability {
  transcript: boolean;
  speakers: boolean;
  minutes: boolean;
  chapters: boolean;
  decisions: boolean;
  action_items: boolean;
  evidence: boolean;
  formal_version: boolean;
}

export interface MeetingCapabilities {
  can_cancel: boolean;
  can_retry_all: boolean;
  can_retry_summary: boolean;
  can_edit: boolean;
  can_save_draft: boolean;
  can_finalize: boolean;
  can_play_audio: boolean;
  can_delete_audio: boolean;
  can_reveal_files: boolean;
  can_remove_index: boolean;
}

export interface MeetingProgress {
  percent: number;
  estimated: boolean;
  elapsed_seconds: number;
  estimated_total_seconds: number | null;
  estimated_remaining_seconds: number | null;
}

export interface MeetingReviewSummary {
  pending_count: number;
  reviewed_count: number;
  dirty: boolean;
  draft_revision?: number;
}

export interface MeetingAudioSummary {
  state: AudioState;
  duration_ms: number | null;
  size_bytes: number | null;
}

export interface MeetingListItem {
  meeting_id: string;
  title: string;
  source_type: MeetingSourceType;
  source_label: string;
  state: MeetingState;
  phase: MeetingPhase;
  progress: MeetingProgress;
  availability: ResultAvailability;
  review: MeetingReviewSummary;
  audio: MeetingAudioSummary;
  meeting_date: string;
  created_at: string;
  updated_at: string;
}

export interface MeetingDiagnostics {
  schema_version?: string;
  meeting_id?: string;
  board_task_id?: string | null;
  task_kind?: string | null;
  stage?: string | null;
  product_phase?: MeetingPhase | string | null;
  code?: string | null;
  message?: string | null;
  return_code?: number | null;
  elapsed_seconds?: number | null;
  run_id?: string | null;
  cause?: string | null;
  finish_reason?: string | null;
  context_truncated?: boolean | null;
  request_id?: string | null;
  diagnostic_source?: string | null;
  stage_details?: Record<string, unknown> | null;
  artifact_refs?: Record<string, string>;
  worker_log_ref?: string | null;
  truncated?: boolean;
}

export interface ApiError {
  code: string;
  message: string;
  phase?: MeetingPhase;
  request_id?: string;
  retryable: boolean;
  retry_scope?: 'upload' | 'all' | 'summary' | 'exports';
  preserved?: {
    audio: boolean;
    transcript: boolean;
    speakers: boolean;
    summary: boolean;
    formal_version: boolean;
  };
  details?: Record<string, unknown>;
}

export type FileHealthState =
  | 'available'
  | 'partial'
  | 'not_created'
  | 'missing'
  | 'invalid'
  | 'unreadable'
  | 'deleted';

export interface MeetingDetail extends MeetingListItem {
  language: string;
  source: {
    type: MeetingSourceType;
    original_name: string | null;
    original_extension: string | null;
    mime_type: string | null;
    size_bytes: number | null;
    sha256: string | null;
    requires_conversion: boolean;
  };
  raw_stage: string | null;
  seq: number;
  capabilities: MeetingCapabilities;
  audio: MeetingAudioSummary & {
    playable: boolean;
    deleted_at: string | null;
  };
  file_health: Record<
    'metadata' | 'source_audio' | 'result' | 'draft' | 'formal_html' | 'formal_txt' | 'formal_json',
    FileHealthState
  >;
  error: ApiError | null;
  diagnostics?: MeetingDiagnostics;
}

export interface TranscriptSegment {
  segment_id: string;
  start_ms: number;
  end_ms: number;
  speaker_id: string;
  text: string;
  chapter_id: string | null;
  confidence: number | null;
  review_status: ReviewStatus;
  user_edited: boolean;
}

export interface Speaker {
  speaker_id: string;
  display_name: string;
  segment_count: number;
  duration_ms: number;
  user_renamed: boolean;
}

// 后端尚未返回时保持可选；摘要内容与 speaker 统计分开，便于未来扩展核对和证据字段。
export interface SpeakerSummary {
  speaker_id: string;
  summary: string | null;
  action_item_ids: string[];
}

export interface Evidence {
  evidence_id: string;
  segment_id: string;
  start_ms: number;
  end_ms: number;
  speaker_id: string;
  quote: string;
}

export interface Decision {
  decision_id: string;
  text: string;
  evidence_ids: string[];
  review_status: ReviewStatus;
  user_edited: boolean;
}

export interface ActionItem {
  action_id: string;
  text: string;
  owner: string | null;
  due_date: string | null;
  evidence_ids: string[];
  review_status: ReviewStatus;
  user_edited: boolean;
}

export interface MeetingMinutes {
  overview: string;
  outline: Array<{
    node_id: string;
    level: number;
    title: string;
    text: string | null;
    evidence_ids: string[];
    review_status: ReviewStatus;
    user_edited: boolean;
  }>;
}

export interface MeetingChapter {
  chapter_id: string;
  index: number;
  title: string;
  summary: string;
  start_ms: number;
  end_ms: number;
  evidence_ids: string[];
  review_status: ReviewStatus;
  user_edited: boolean;
}

export interface MeetingResultV1 {
  schema_version: 'meeting-result.v1';
  meeting_id: string;
  result_revision: number;
  language: string;
  duration_ms: number;
  generated_at: string;
  availability: ResultAvailability;
  transcript: {
    complete: boolean;
    segment_count: number;
    segments: TranscriptSegment[];
  } | null;
  speakers: Speaker[] | null;
  speaker_summaries?: SpeakerSummary[] | null;
  minutes: MeetingMinutes | null;
  chapters: MeetingChapter[] | null;
  decisions: Decision[] | null;
  action_items: ActionItem[] | null;
  evidence: Evidence[] | null;
  diagnostics: MeetingDiagnostics | Record<string, unknown> | null;
}

export interface TranscriptEdit {
  segment_id: string;
  text: string;
  speaker_id: string;
}

export interface MeetingDraftContent {
  title: string;
  speaker_names: Record<string, string>;
  transcript_edits: TranscriptEdit[];
  minutes: MeetingMinutes | null;
  chapters: MeetingChapter[];
  decisions: Decision[];
  action_items: ActionItem[];
  review_marks: Record<string, ReviewStatus>;
}

export interface MeetingDraft {
  schema_version: 'meeting-draft.v1';
  meeting_id: string;
  revision: number;
  base_result_revision: number;
  updated_at: string | null;
  dirty: boolean;
  content: MeetingDraftContent;
}

export interface SaveMeetingDraftInput {
  expected_revision: number;
  base_result_revision: number;
  content: MeetingDraftContent;
}

export interface SaveMeetingDraftResponse {
  meeting_id: string;
  revision: number;
  base_result_revision: number;
  saved_at: string;
  review: MeetingReviewSummary;
}

export type ExportFormat = 'html' | 'txt' | 'json';
export type ExportState = 'queued' | 'generating' | 'ready' | 'failed';

export interface ExportItem {
  format: ExportFormat;
  state: ExportState;
  file_name: string | null;
  size_bytes: number | null;
  created_at: string | null;
  content_url: string | null;
  error: ApiError | null;
}

export interface MeetingExportsResponse {
  meeting_id: string;
  state: MeetingState;
  items: ExportItem[];
}

export interface FinalizeMeetingInput {
  draft_revision: number;
  formats: ExportFormat[];
  confirmed: true;
}

export interface FinalizeMeetingResponse {
  meeting_id: string;
  state: 'finalizing' | 'finalized';
  phase: 'exporting' | 'ready';
  draft_revision: number;
  exports: ExportItem[];
}

export interface DeleteMeetingAudioResponse {
  meeting_id: string;
  audio: {
    state: 'deleted';
    playable: false;
    deleted_at: string;
  };
  freed_bytes: number;
  retained: {
    transcript: true;
    speakers: true;
    minutes: true;
    chapters: true;
    decisions: true;
    action_items: true;
    evidence_text: true;
    evidence_timestamps: true;
    formal_versions: true;
  };
}

export interface MeetingListResponse {
  items: MeetingListItem[];
  page: number;
  page_size: number;
  total: number;
  has_more: boolean;
  facets: Record<MeetingFilter, number>;
}

export interface CreateMeetingInput {
  title: string;
  source_type: MeetingSourceType;
  language?: string;
  source_file?: {
    name: string;
    size_bytes: number;
    mime_type: string;
    last_modified_at: string;
  };
}

export interface CreatedMeeting {
  meeting_id: string;
  title: string;
  state: MeetingState;
  phase: MeetingPhase;
  source_type: MeetingSourceType;
  created_at: string;
}

export interface MeetingQuery {
  q?: string;
  status?: MeetingFilter;
  sort?: 'updated_desc' | 'created_desc' | 'title_asc';
}

export type BoardRecordingState =
  | 'starting'
  | 'recording'
  | 'stopping'
  | 'stopped'
  | 'disconnected'
  | 'unknown'
  | 'failed';

export type BoardConnectionState = 'online' | 'disconnected' | 'unknown';

export interface StartBoardRecordingResponse {
  meeting_id: string;
  recording_id: string;
  state: 'recording';
  recording: {
    state: 'recording';
    device_id: string;
    started_at: string;
    elapsed_seconds: number;
    audio_saved: boolean;
    connection: BoardConnectionState;
  };
}

export interface BoardRecordingStatusResponse {
  meeting_id: string;
  recording_id: string;
  state: BoardRecordingState;
  device_id: string;
  started_at: string;
  elapsed_seconds: number;
  audio_saved: boolean | null;
  connection: BoardConnectionState;
  error: ApiError | null;
}

export interface StopBoardRecordingResponse {
  meeting_id: string;
  recording_id: string;
  recording: {
    state: 'stopped';
    elapsed_seconds: number;
    audio_saved: boolean;
  };
  state: 'processing';
  phase: 'transcribing';
}

export interface GatewayInfo {
  service: string;
  version: string;
  api_contract_version: string;
  status: 'ready';
  local_only: boolean;
  base_url: string;
  board_url: string;
  capabilities: {
    meeting_library: boolean;
    local_upload: boolean;
    pc_record: boolean;
    board_record: boolean;
    partial_result: boolean;
    draft: boolean;
    finalize: boolean;
    audio_delete: boolean;
    settings?: boolean;
    storage_management?: boolean;
    diagnostics?: boolean;
  };
}

export type RetryMeetingScope = 'upload' | 'all' | 'summary' | 'exports';

export interface RetryMeetingResponse {
  meeting_id: string;
  state: MeetingState;
  phase: MeetingPhase;
  retry_scope: RetryMeetingScope;
  result_revision: number;
  availability: ResultAvailability;
}

export interface RescanMeetingResponse {
  meeting_id: string;
  file_health: MeetingDetail['file_health'];
  capabilities: Partial<MeetingCapabilities>;
  scanned_at: string;
}

export type MeetingRevealTarget = 'meeting_dir' | 'audio' | 'exports';

export interface MeetingRevealResponse {
  meeting_id: string;
  opened: boolean;
  target: MeetingRevealTarget;
}

export interface RemoveMeetingIndexResponse {
  meeting_id: string;
  removed_from_library: boolean;
  files_deleted: false;
  files_retained: true;
}

export interface MeetingSettings {
  device_name: string;
  board: {
    address: string;
    port: number;
    base_url: string;
  };
  model_profile: string;
  meeting_library_path: string;
  keep_audio_until_finalized: boolean;
  default_export_formats: ExportFormat[];
  default_language: string;
}

export interface UpdateMeetingSettingsInput {
  device_name: string;
  board: {
    address: string;
    port: number;
  };
  meeting_library_path: string;
  keep_audio_until_finalized: boolean;
  default_export_formats: ExportFormat[];
  default_language: string;
}

export interface BoardConnectionCheckResponse {
  status: 'online' | 'offline';
  board_id: string | null;
  protocol_version: string | null;
  agent_version: string | null;
  model_profile: string | null;
  compatible: boolean;
  latency_ms: number | null;
}

export interface StoragePathCheckResponse {
  exists: boolean;
  writable: boolean;
  total_bytes: number;
  free_bytes: number;
  compatible: boolean;
}

export type StorageStatus = 'ok' | 'warning' | 'insufficient' | 'unavailable';

export interface StorageSummary {
  path: string;
  writable: boolean;
  total_bytes: number;
  used_bytes: number;
  free_bytes: number;
  status: StorageStatus;
  categories: {
    audio_bytes: number;
    results_bytes: number;
    exports_bytes: number;
    temp_bytes: number;
    other_bytes: number;
  };
  thresholds: {
    warning_free_bytes: number;
    minimum_free_bytes: number;
  };
  updated_at: string;
}

export type RevealTarget = 'meeting_library' | 'gateway_scripts';

export interface RevealResponse {
  opened: boolean;
  target: RevealTarget;
}

export interface StorageMeetingItem {
  meeting_id: string;
  title: string;
  meeting_state: MeetingState;
  audio_state: AudioState;
  audio_size_bytes: number | null;
  meeting_date: string;
  can_delete_audio: boolean;
}

export interface StorageMeetingListResponse {
  items: StorageMeetingItem[];
  page: number;
  page_size: number;
  total: number;
  has_more: boolean;
}

export interface CleanupTemporaryFilesResponse {
  freed_bytes: number;
  deleted_file_count: number;
  skipped_active_file_count: number;
  storage: {
    free_bytes: number;
    status: StorageStatus;
  };
}
