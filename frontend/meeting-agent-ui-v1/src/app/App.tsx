import { Navigate, Route, Routes } from 'react-router-dom';
import { MeetingFormalPage } from '../features/formal/MeetingFormalPage';
import { LocalAudioImportPage } from '../features/import/LocalAudioImportPage';
import { MeetingLibraryPage } from '../features/meetings/MeetingLibraryPage';
import { MeetingPlaybackPage } from '../features/playback/MeetingPlaybackPage';
import { MeetingProcessingPage } from '../features/processing/MeetingProcessingPage';
import { BoardRecordingPage } from '../features/recording/BoardRecordingPage';
import { PcRecordingPage } from '../features/recording/PcRecordingPage';
import { MeetingReviewPage } from '../features/review/MeetingReviewPage';
import { SettingsPage } from '../features/settings/SettingsPage';
import { StorageManagementPage } from '../features/settings/StorageManagementPage';
import { StorageInsufficientPage } from '../features/storage/StorageInsufficientPage';
import { BoardOfflinePage } from '../features/system/BoardOfflinePage';
import { GatewayOfflinePage } from '../features/system/GatewayOfflinePage';
import { ResultUnavailablePage } from '../features/system/ResultUnavailablePage';
import { GatewayBoundary } from './GatewayBoundary';

export function App() {
  return (
    <GatewayBoundary>
      <Routes>
        <Route path="/" element={<Navigate to="/meetings" replace />} />
        <Route path="/meetings" element={<MeetingLibraryPage />} />
        <Route path="/meetings/new/local" element={<LocalAudioImportPage />} />
        <Route path="/meetings/:meetingId/processing" element={<MeetingProcessingPage />} />
        <Route path="/meetings/:meetingId/review" element={<MeetingReviewPage />} />
        <Route path="/meetings/:meetingId/playback" element={<MeetingPlaybackPage />} />
        <Route path="/meetings/:meetingId/formal" element={<MeetingFormalPage />} />
        <Route path="/record/pc" element={<PcRecordingPage />} />
        <Route path="/record/board" element={<BoardRecordingPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/settings/storage" element={<StorageManagementPage />} />
        <Route path="/storage/insufficient" element={<StorageInsufficientPage />} />
        <Route path="/system/gateway-offline" element={<GatewayOfflinePage />} />
        <Route path="/system/board-offline" element={<BoardOfflinePage />} />
        <Route path="/meetings/:meetingId/result-unavailable" element={<ResultUnavailablePage />} />
        <Route path="*" element={<Navigate to="/meetings" replace />} />
      </Routes>
    </GatewayBoundary>
  );
}
