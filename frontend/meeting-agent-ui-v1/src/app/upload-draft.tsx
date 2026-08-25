import { createContext, useCallback, useContext, useMemo, useState, type PropsWithChildren } from 'react';

export interface PendingStorageIssue {
  meetingId: string;
  title: string;
  sourceType: 'local_upload' | 'pc_record';
  fileName: string;
  fileSizeBytes: number;
  requiredBytes: number;
  freeBytes: number;
  returnPath: string;
}

interface UploadDraftContextValue {
  file: File | null;
  setFile: (file: File | null) => void;
  storageIssue: PendingStorageIssue | null;
  setStorageIssue: (issue: PendingStorageIssue | null) => void;
}

const storageIssueKey = 'meeting-agent.pending-storage-issue';
const UploadDraftContext = createContext<UploadDraftContextValue | null>(null);

function readStorageIssue(): PendingStorageIssue | null {
  try {
    const value = window.sessionStorage.getItem(storageIssueKey);
    return value ? JSON.parse(value) as PendingStorageIssue : null;
  } catch {
    return null;
  }
}

export function UploadDraftProvider({ children }: PropsWithChildren) {
  const [file, setFile] = useState<File | null>(null);
  const [storageIssue, setStorageIssueState] = useState<PendingStorageIssue | null>(readStorageIssue);

  const setStorageIssue = useCallback((issue: PendingStorageIssue | null) => {
    setStorageIssueState(issue);
    try {
      if (issue) window.sessionStorage.setItem(storageIssueKey, JSON.stringify(issue));
      else window.sessionStorage.removeItem(storageIssueKey);
    } catch {
      // The in-memory upload draft remains available for the current page session.
    }
  }, []);

  const value = useMemo(
    () => ({ file, setFile, storageIssue, setStorageIssue }),
    [file, storageIssue, setStorageIssue],
  );

  return <UploadDraftContext.Provider value={value}>{children}</UploadDraftContext.Provider>;
}

export function useUploadDraft(): UploadDraftContextValue {
  const value = useContext(UploadDraftContext);
  if (!value) throw new Error('useUploadDraft must be used inside UploadDraftProvider');
  return value;
}
