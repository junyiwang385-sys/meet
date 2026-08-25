import { useMutation } from '@tanstack/react-query';
import { useMemo, useRef, useState, type DragEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { meetingApi } from '../../api';
import {
  formatFileSize,
  getFileExtension,
  getStorageInsufficientDetails,
  isSupportedAudioFile,
} from '../../api/meeting-api';
import { useUploadDraft } from '../../app/upload-draft';
import { AudioFileIcon } from '../../components/Icons';
import { StagePageShell } from '../shared/StagePageShell';
import './LocalAudioImportPage.css';

function titleFromFile(file: File | null): string {
  if (!file) return '未命名会议';
  const dot = file.name.lastIndexOf('.');
  return dot > 0 ? file.name.slice(0, dot) : file.name;
}

export function LocalAudioImportPage() {
  const navigate = useNavigate();
  const { file, setFile, setStorageIssue } = useUploadDraft();
  const inputRef = useRef<HTMLInputElement>(null);
  const createdMeetingIdRef = useRef<string | null>(null);
  const [title, setTitle] = useState(() => titleFromFile(file));
  const [fileError, setFileError] = useState<string | null>(null);
  const [dragActive, setDragActive] = useState(false);

  const extension = useMemo(() => (file ? getFileExtension(file.name) : ''), [file]);
  const requiresConversion = Boolean(file && extension !== 'wav');

  const createAndUpload = useMutation({
    mutationFn: async () => {
      if (!file) throw new Error('请先选择音频文件');
      const meetingTitle = title.trim() || '未命名会议';
      const created = await meetingApi.createMeeting({
        title: meetingTitle,
        source_type: 'local_upload',
        language: 'zh-CN',
        source_file: {
          name: file.name,
          size_bytes: file.size,
          mime_type: file.type || 'application/octet-stream',
          last_modified_at: new Date(file.lastModified).toISOString(),
        },
      });
      createdMeetingIdRef.current = created.meeting_id;
      await meetingApi.uploadAudio(created.meeting_id, file);
      return created;
    },
    onSuccess: (created) => {
      setFile(null);
      setStorageIssue(null);
      navigate(`/meetings/${created.meeting_id}/processing`);
    },
    onError: (error) => {
      const storage = getStorageInsufficientDetails(error);
      const meetingId = createdMeetingIdRef.current;
      if (!storage || !file || !meetingId) return;
      setStorageIssue({
        meetingId,
        title: title.trim() || '未命名会议',
        sourceType: 'local_upload',
        fileName: file.name,
        fileSizeBytes: file.size,
        requiredBytes: Math.max(storage.requiredBytes, file.size),
        freeBytes: storage.freeBytes,
        returnPath: '/meetings/new/local',
      });
      navigate('/storage/insufficient');
    },
  });

  const selectFile = (selected: File | undefined) => {
    if (!selected) return;
    if (!isSupportedAudioFile(selected)) {
      setFileError('请选择 WAV、MP3、M4A、FLAC、AAC 或 OGG 文件');
      return;
    }
    setFileError(null);
    createdMeetingIdRef.current = null;
    setStorageIssue(null);
    setFile(selected);
    setTitle(titleFromFile(selected));
  };

  const handleDrop = (event: DragEvent<HTMLButtonElement>) => {
    event.preventDefault();
    setDragActive(false);
    selectFile(event.dataTransfer.files[0]);
  };

  const footerNote = !file
    ? '尚未选择音频文件'
    : requiresConversion
      ? '开始后将在本地转换为处理格式'
      : '文件已准备，可以开始处理';

  const inspector = (
    <>
      <div className="stage-detail-group">
        <div className="stage-detail-row"><span>来源</span><strong>本地音频</strong></div>
        <div className="stage-detail-row"><span>文件</span><strong>{file?.name ?? '未选择'}</strong></div>
        <div className="stage-detail-row"><span>会议名称</span><strong>{title.trim() || '未命名会议'}</strong></div>
      </div>
      <div className="stage-inspector-section-title">开始前检查</div>
      <div className="local-check-list">
        <div className={file ? 'local-check-item local-check-item-ready' : 'local-check-item'}>
          <span className="local-check-dot" /><span>音频文件</span><span>{file ? '通过' : '待选择'}</span>
        </div>
        <div className="local-check-item local-check-item-ready">
          <span className="local-check-dot" /><span>局域网通道</span><span>已连接</span>
        </div>
        <div className="local-check-item local-check-item-ready">
          <span className="local-check-dot" /><span>RK1828</span><span>可用</span>
        </div>
      </div>
      <div className="stage-privacy-note">原始音频和会议结果保存在本地；会议确认后可以单独删除音频。</div>
    </>
  );

  return (
    <StagePageShell
      className="local-import-page"
      activeLabel="新建会议"
      activeValue="本地音频"
      breadcrumbs={['会议库', '新建会议', '本地音频']}
      topActions={<Link className="stage-quiet-button" to="/meetings">返回会议库</Link>}
      inspectorTitle="导入信息"
      inspector={inspector}
    >
      <input
        ref={inputRef}
        type="file"
        accept=".wav,.mp3,.m4a,.flac,.aac,.ogg,audio/*"
        hidden
        onChange={(event) => selectFile(event.target.files?.[0])}
      />

      <div className="stage-page-eyebrow">本地音频</div>
      <h1 className="stage-page-title">导入本地音频</h1>
      <p className="stage-page-lead">选择音频文件，确认会议名称后开始处理。</p>

      <section className="local-import-panel" aria-labelledby="localImportTitle">
        <div className="local-import-head">
          <h2 id="localImportTitle">音频文件</h2>
          <span>WAV · MP3 · M4A · FLAC · AAC · OGG</span>
        </div>

        {file ? (
          <div className="local-file-card">
            <span className="local-file-icon">{extension.toUpperCase()}</span>
            <span className="local-file-copy">
              <strong>{file.name}</strong>
              <span>
                <span>{formatFileSize(file.size)}</span>
                <span>{extension.toUpperCase()} 音频</span>
                <span>{requiresConversion ? '待本地转换' : '已选择'}</span>
              </span>
            </span>
            <button className="local-replace-button" type="button" onClick={() => inputRef.current?.click()}>更换</button>
          </div>
        ) : (
          <button
            className={dragActive ? 'local-drop-zone local-drop-zone-active' : 'local-drop-zone'}
            type="button"
            onClick={() => inputRef.current?.click()}
            onDragEnter={(event) => { event.preventDefault(); setDragActive(true); }}
            onDragOver={(event) => event.preventDefault()}
            onDragLeave={() => setDragActive(false)}
            onDrop={handleDrop}
          >
            <span className="local-upload-icon"><AudioFileIcon /></span>
            <strong>拖入音频文件</strong>
            <span>支持 WAV、MP3、M4A、FLAC、AAC 和 OGG</span>
            <span className="local-select-file">选择文件</span>
          </button>
        )}

        <div className="local-form-row">
          <label className="local-field">
            <span>会议名称</span>
            <input
              value={title}
              maxLength={200}
              autoComplete="off"
              onChange={(event) => setTitle(event.target.value)}
            />
          </label>
          <div className="local-field">
            <span>语言</span>
            <div className="local-language-value">中文</div>
          </div>
        </div>

        {fileError ? <div className="local-file-error" role="alert">{fileError}</div> : null}
        {createAndUpload.isError ? (
          <div className="local-file-error" role="alert">
            {createAndUpload.error instanceof Error ? createAndUpload.error.message : '导入失败，请重试'}
          </div>
        ) : null}

        <div className="local-import-footer">
          <span>{footerNote}</span>
          <button
            className="primary-button"
            type="button"
            disabled={!file || createAndUpload.isPending}
            onClick={() => createAndUpload.mutate()}
          >
            {createAndUpload.isPending ? '正在导入' : '开始处理'}
          </button>
        </div>
      </section>
    </StagePageShell>
  );
}
