import type {
  ApiError,
  BoardConnectionCheckResponse,
  BoardRecordingStatusResponse,
  CleanupTemporaryFilesResponse,
  CreateMeetingInput,
  CreatedMeeting,
  DeleteMeetingAudioResponse,
  ExportFormat,
  FinalizeMeetingInput,
  FinalizeMeetingResponse,
  GatewayInfo,
  MeetingDetail,
  MeetingDraft,
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
  SaveMeetingDraftInput,
  SaveMeetingDraftResponse,
  StartBoardRecordingResponse,
  StopBoardRecordingResponse,
  StorageMeetingListResponse,
  StoragePathCheckResponse,
  StorageSummary,
  UpdateMeetingSettingsInput,
} from './types';

export interface MeetingApi {
  getGatewayInfo(): Promise<GatewayInfo>;
  listMeetings(query?: MeetingQuery): Promise<MeetingListResponse>;
  createMeeting(input: CreateMeetingInput): Promise<CreatedMeeting>;
  uploadAudio(meetingId: string, file: File): Promise<MeetingDetail>;
  startBoardRecording(meetingId: string, deviceId: string): Promise<StartBoardRecordingResponse>;
  getBoardRecording(meetingId: string): Promise<BoardRecordingStatusResponse>;
  stopBoardRecording(meetingId: string): Promise<StopBoardRecordingResponse>;
  getSettings(): Promise<MeetingSettings>;
  saveSettings(input: UpdateMeetingSettingsInput): Promise<MeetingSettings>;
  checkBoardConnection(address: string, port: number): Promise<BoardConnectionCheckResponse>;
  checkStoragePath(path: string): Promise<StoragePathCheckResponse>;
  getStorageSummary(): Promise<StorageSummary>;
  listStorageMeetings(): Promise<StorageMeetingListResponse>;
  cleanupTemporaryFiles(): Promise<CleanupTemporaryFilesResponse>;
  revealSystemTarget(target: RevealTarget): Promise<RevealResponse>;
  getMeeting(meetingId: string, options?: { includeDiagnostics?: boolean }): Promise<MeetingDetail>;
  getMeetingResult(meetingId: string, options?: { includeDiagnostics?: boolean }): Promise<MeetingResultV1>;
  retryMeeting(meetingId: string, scope: RetryMeetingScope): Promise<RetryMeetingResponse>;
  rescanMeeting(meetingId: string): Promise<RescanMeetingResponse>;
  revealMeeting(meetingId: string, target: MeetingRevealTarget): Promise<MeetingRevealResponse>;
  removeMeetingIndex(meetingId: string): Promise<RemoveMeetingIndexResponse>;
  getMeetingAudioUrl(meetingId: string): string | null;
  getMeetingDraft(meetingId: string): Promise<MeetingDraft>;
  saveMeetingDraft(meetingId: string, input: SaveMeetingDraftInput): Promise<SaveMeetingDraftResponse>;
  finalizeMeeting(meetingId: string, input: FinalizeMeetingInput): Promise<FinalizeMeetingResponse>;
  getMeetingExports(meetingId: string): Promise<MeetingExportsResponse>;
  getMeetingExportUrl(meetingId: string, format: ExportFormat): string | null;
  deleteMeetingAudio(meetingId: string, confirmation: string): Promise<DeleteMeetingAudioResponse>;
  cancelMeeting(meetingId: string): Promise<MeetingDetail>;
}

export interface StorageInsufficientDetails {
  requiredBytes: number;
  freeBytes: number;
}

export function getApiErrorCode(error: unknown): string | null {
  if (!error || typeof error !== 'object') return null;
  const code = (error as { payload?: ApiError }).payload?.code;
  return typeof code === 'string' ? code : null;
}

export function getStorageInsufficientDetails(error: unknown): StorageInsufficientDetails | null {
  if (!error || typeof error !== 'object') return null;
  const candidate = error as { status?: unknown; payload?: ApiError };
  const storageError = candidate.status === 507 || candidate.payload?.code === 'STORAGE_INSUFFICIENT';
  if (!storageError) return null;
  const requiredBytes = Number(candidate.payload?.details?.required_bytes);
  const freeBytes = Number(candidate.payload?.details?.free_bytes);
  return {
    requiredBytes: Number.isFinite(requiredBytes) && requiredBytes >= 0 ? requiredBytes : 0,
    freeBytes: Number.isFinite(freeBytes) && freeBytes >= 0 ? freeBytes : 0,
  };
}

export const meetingFilterLabels: Record<MeetingFilter, string> = {
  all: '全部会议',
  processing: '处理中',
  failed: '处理失败',
  review: '待核对',
  confirmed: '已确认',
  deleted: '音频已删除',
};

export function meetingStatusForFilter(
  state: MeetingDetail['state'],
  audioState: MeetingDetail['audio']['state'],
): MeetingFilter {
  if (state === 'failed') return 'failed';
  if (['recording', 'uploading', 'processing', 'finalizing'].includes(state)) return 'processing';
  if (state === 'review_ready') return 'review';
  if (state === 'finalized' && audioState === 'deleted') return 'deleted';
  if (state === 'finalized') return 'confirmed';
  return 'all';
}

export function formatDuration(durationMs: number | null): string {
  if (durationMs === null || !Number.isFinite(durationMs)) return '—';
  const totalSeconds = Math.max(0, Math.round(durationMs / 1000));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
  }
  return `${minutes}:${String(seconds).padStart(2, '0')}`;
}

export function formatMeetingDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  const today = new Date();
  const dateKey = `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`;
  const todayKey = `${today.getFullYear()}-${today.getMonth()}-${today.getDate()}`;
  if (dateKey === todayKey) return '今天';
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  const yesterdayKey = `${yesterday.getFullYear()}-${yesterday.getMonth()}-${yesterday.getDate()}`;
  if (dateKey === yesterdayKey) return '昨天';
  return `${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

export function formatFileSize(bytes: number | null): string {
  if (bytes === null || !Number.isFinite(bytes)) return '—';
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function getFileExtension(fileName: string): string {
  const dot = fileName.lastIndexOf('.');
  return dot >= 0 ? fileName.slice(dot + 1).toLowerCase() : '';
}

export function isSupportedAudioFile(file: File): boolean {
  return new Set(['wav', 'mp3', 'm4a', 'flac', 'aac', 'ogg']).has(getFileExtension(file.name));
}
