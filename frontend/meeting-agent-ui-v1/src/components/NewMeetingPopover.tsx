import { useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { useUploadDraft } from '../app/upload-draft';
import {
  ArrowRightIcon,
  AudioFileIcon,
  BoardIcon,
  CloseIcon,
  MicrophoneIcon,
} from './Icons';

interface NewMeetingPopoverProps {
  open: boolean;
  onClose: () => void;
  onInvalidFile: (message: string) => void;
}

const supportedExtensions = new Set(['wav', 'mp3', 'm4a', 'flac', 'aac', 'ogg']);

export function NewMeetingPopover({ open, onClose, onInvalidFile }: NewMeetingPopoverProps) {
  const navigate = useNavigate();
  const { setFile } = useUploadDraft();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    const closeOnOutsideClick = (event: MouseEvent) => {
      if (!panelRef.current?.contains(event.target as Node)) onClose();
    };
    document.addEventListener('keydown', closeOnEscape);
    document.addEventListener('mousedown', closeOnOutsideClick);
    return () => {
      document.removeEventListener('keydown', closeOnEscape);
      document.removeEventListener('mousedown', closeOnOutsideClick);
    };
  }, [onClose, open]);

  const selectLocalFile = (file: File | undefined) => {
    if (!file) return;
    const extension = file.name.split('.').pop()?.toLowerCase() ?? '';
    if (!supportedExtensions.has(extension)) {
      onInvalidFile('请选择 WAV、MP3、M4A、FLAC、AAC 或 OGG 文件');
      return;
    }
    setFile(file);
    onClose();
    navigate('/meetings/new/local');
  };

  return (
    <>
      <input
        ref={fileInputRef}
        type="file"
        accept=".wav,.mp3,.m4a,.flac,.aac,.ogg,audio/*"
        hidden
        onChange={(event) => selectLocalFile(event.target.files?.[0])}
      />
      {open ? (
        <div className="new-meeting-popover" ref={panelRef} role="dialog" aria-label="新建会议">
          <div className="popover-header">
            <strong>新建会议</strong>
            <button className="icon-button" type="button" onClick={onClose} aria-label="关闭">
              <CloseIcon />
            </button>
          </div>
          <div className="source-list">
            <button className="source-option" type="button" onClick={() => fileInputRef.current?.click()}>
              <span className="source-option-icon"><AudioFileIcon /></span>
              <span className="source-option-copy">
                <strong>本地音频</strong>
                <span>WAV、MP3、M4A、FLAC 等</span>
              </span>
              <ArrowRightIcon className="source-option-arrow" />
            </button>
            <button
              className="source-option"
              type="button"
              onClick={() => {
                onClose();
                navigate('/record/pc');
              }}
            >
              <span className="source-option-icon"><MicrophoneIcon /></span>
              <span className="source-option-copy">
                <strong>PC 录音</strong>
                <span>使用当前电脑的麦克风</span>
              </span>
              <ArrowRightIcon className="source-option-arrow" />
            </button>
            <button
              className="source-option"
              type="button"
              onClick={() => {
                onClose();
                navigate('/record/board');
              }}
            >
              <span className="source-option-icon"><BoardIcon /></span>
              <span className="source-option-copy">
                <strong>板端录音</strong>
                <span>由 RK1828 采集</span>
              </span>
              <ArrowRightIcon className="source-option-arrow" />
            </button>
          </div>
        </div>
      ) : null}
    </>
  );
}
