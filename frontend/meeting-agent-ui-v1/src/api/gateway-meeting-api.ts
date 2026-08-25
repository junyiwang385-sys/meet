import type { MeetingApi } from './meeting-api';
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

interface ErrorEnvelope {
  error?: ApiError;
  request_id?: string;
}

export class MeetingApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly payload?: ApiError,
    readonly requestId?: string,
  ) {
    super(message);
    this.name = 'MeetingApiError';
  }
}

export class GatewayMeetingApi implements MeetingApi {
  constructor(private readonly baseUrl: string) {}

  async getGatewayInfo(): Promise<GatewayInfo> {
    return this.request('/api/info');
  }

  async listMeetings(query: MeetingQuery = {}): Promise<MeetingListResponse> {
    const params = new URLSearchParams();
    if (query.q) params.set('q', query.q);
    if (query.status && query.status !== 'all') params.set('status', query.status);
    if (query.sort) params.set('sort', query.sort);
    const suffix = params.size ? `?${params.toString()}` : '';
    return this.request(`/api/meetings${suffix}`);
  }

  async createMeeting(input: CreateMeetingInput): Promise<CreatedMeeting> {
    return this.request('/api/meetings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(input),
    });
  }

  async uploadAudio(meetingId: string, file: File): Promise<MeetingDetail> {
    return this.request(`/api/meetings/${encodeURIComponent(meetingId)}/audio`, {
      method: 'PUT',
      headers: {
        'Content-Type': file.type || 'application/octet-stream',
        'X-File-Name': encodeURIComponent(file.name),
      },
      body: file,
    });
  }

  async startBoardRecording(
    meetingId: string,
    deviceId: string,
  ): Promise<StartBoardRecordingResponse> {
    return this.request(`/api/meetings/${encodeURIComponent(meetingId)}/record/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ device_id: deviceId }),
    });
  }

  async getBoardRecording(meetingId: string): Promise<BoardRecordingStatusResponse> {
    return this.request(`/api/meetings/${encodeURIComponent(meetingId)}/record`);
  }

  async stopBoardRecording(meetingId: string): Promise<StopBoardRecordingResponse> {
    return this.request(`/api/meetings/${encodeURIComponent(meetingId)}/record/stop`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{}',
    });
  }

  async getSettings(): Promise<MeetingSettings> {
    return this.request('/api/settings');
  }

  async saveSettings(input: UpdateMeetingSettingsInput): Promise<MeetingSettings> {
    return this.request('/api/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(input),
    });
  }

  async checkBoardConnection(
    address: string,
    port: number,
  ): Promise<BoardConnectionCheckResponse> {
    return this.request('/api/settings/board/check', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ address, port }),
    });
  }

  async checkStoragePath(path: string): Promise<StoragePathCheckResponse> {
    return this.request('/api/settings/storage/check', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path }),
    });
  }

  async getStorageSummary(): Promise<StorageSummary> {
    return this.request('/api/storage');
  }

  async listStorageMeetings(): Promise<StorageMeetingListResponse> {
    return this.request('/api/storage/meetings?sort=audio_size_desc&page=1&page_size=30');
  }

  async cleanupTemporaryFiles(): Promise<CleanupTemporaryFilesResponse> {
    return this.request('/api/storage/cleanup-temp', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ categories: ['temp'] }),
    });
  }

  async revealSystemTarget(target: RevealTarget): Promise<RevealResponse> {
    return this.request('/api/system/reveal', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ target }),
    });
  }

  async getMeeting(
    meetingId: string,
    options: { includeDiagnostics?: boolean } = {},
  ): Promise<MeetingDetail> {
    const suffix = options.includeDiagnostics ? '?include=diagnostics' : '';
    return this.request(`/api/meetings/${encodeURIComponent(meetingId)}${suffix}`);
  }

  async getMeetingResult(
    meetingId: string,
    options: { includeDiagnostics?: boolean } = {},
  ): Promise<MeetingResultV1> {
    const suffix = options.includeDiagnostics ? '?include=diagnostics' : '';
    return this.request(`/api/meetings/${encodeURIComponent(meetingId)}/result${suffix}`);
  }

  async retryMeeting(
    meetingId: string,
    scope: RetryMeetingScope,
  ): Promise<RetryMeetingResponse> {
    return this.request(`/api/meetings/${encodeURIComponent(meetingId)}/retry`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scope }),
    });
  }

  async rescanMeeting(meetingId: string): Promise<RescanMeetingResponse> {
    return this.request(`/api/meetings/${encodeURIComponent(meetingId)}/rescan`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{}',
    });
  }

  async revealMeeting(
    meetingId: string,
    target: MeetingRevealTarget,
  ): Promise<MeetingRevealResponse> {
    return this.request(`/api/meetings/${encodeURIComponent(meetingId)}/reveal`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ target }),
    });
  }

  async removeMeetingIndex(meetingId: string): Promise<RemoveMeetingIndexResponse> {
    return this.request(`/api/meetings/${encodeURIComponent(meetingId)}?mode=index_only`, {
      method: 'DELETE',
    });
  }

  getMeetingAudioUrl(meetingId: string): string {
    return `${this.baseUrl}/api/meetings/${encodeURIComponent(meetingId)}/audio`;
  }

  async getMeetingDraft(meetingId: string): Promise<MeetingDraft> {
    return this.request(`/api/meetings/${encodeURIComponent(meetingId)}/draft`);
  }

  async saveMeetingDraft(
    meetingId: string,
    input: SaveMeetingDraftInput,
  ): Promise<SaveMeetingDraftResponse> {
    return this.request(`/api/meetings/${encodeURIComponent(meetingId)}/draft`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(input),
    });
  }

  async finalizeMeeting(
    meetingId: string,
    input: FinalizeMeetingInput,
  ): Promise<FinalizeMeetingResponse> {
    const idempotencyKey =
      typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
        ? crypto.randomUUID()
        : `finalize-${meetingId}-${Date.now()}`;
    return this.request(`/api/meetings/${encodeURIComponent(meetingId)}/finalize`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Idempotency-Key': idempotencyKey,
      },
      body: JSON.stringify(input),
    });
  }

  async getMeetingExports(meetingId: string): Promise<MeetingExportsResponse> {
    return this.request(`/api/meetings/${encodeURIComponent(meetingId)}/exports`);
  }

  getMeetingExportUrl(meetingId: string, format: ExportFormat): string {
    return `${this.baseUrl}/api/meetings/${encodeURIComponent(meetingId)}/exports/${format}`;
  }

  async deleteMeetingAudio(
    meetingId: string,
    confirmation: string,
  ): Promise<DeleteMeetingAudioResponse> {
    return this.request(`/api/meetings/${encodeURIComponent(meetingId)}/audio/delete`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ confirmation }),
    });
  }

  async cancelMeeting(meetingId: string): Promise<MeetingDetail> {
    return this.request(`/api/meetings/${encodeURIComponent(meetingId)}/cancel`, {
      method: 'POST',
    });
  }

  private async request<T>(path: string, init?: RequestInit): Promise<T> {
    let response: Response;
    try {
      response = await fetch(`${this.baseUrl}${path}`, {
        cache: 'no-store',
        ...init,
      });
    } catch (error) {
      window.dispatchEvent(new CustomEvent('meeting-agent:gateway-offline'));
      throw error;
    }
    if (!response.ok) {
      let envelope: ErrorEnvelope | undefined;
      try {
        envelope = (await response.json()) as ErrorEnvelope;
      } catch {
        envelope = undefined;
      }
      const requestId = envelope?.request_id ?? response.headers.get('X-Request-ID') ?? undefined;
      if (envelope?.error && requestId && !envelope.error.request_id) {
        envelope.error.request_id = requestId;
      }
      throw new MeetingApiError(
        envelope?.error?.message ?? `请求失败（${response.status}）`,
        response.status,
        envelope?.error,
        requestId,
      );
    }
    return (await response.json()) as T;
  }
}
