import { GatewayMeetingApi } from './gateway-meeting-api';
import type { MeetingApi } from './meeting-api';
import { MockMeetingApi } from './mock-meeting-api';

const apiMode = import.meta.env.VITE_API_MODE ?? 'mock';
const gatewayUrl = (import.meta.env.VITE_GATEWAY_URL ?? 'http://127.0.0.1:8787').replace(/\/$/, '');

export const meetingApi: MeetingApi =
  apiMode === 'gateway' ? new GatewayMeetingApi(gatewayUrl) : new MockMeetingApi();

export const runtimeInfo = {
  apiMode,
  gatewayUrl,
};
