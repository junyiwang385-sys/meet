import { useMutation } from '@tanstack/react-query';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { meetingApi, runtimeInfo } from '../../api';
import type { GatewayInfo } from '../../api/types';
import { Brand } from '../../components/Brand';
import { Toast } from '../../components/Toast';
import './GatewayOfflinePage.css';

type ConnectionState = 'offline' | 'checking' | 'connected';

interface GatewayOfflinePageProps {
  onConnected?: (info: GatewayInfo) => void;
}

function gatewayEndpoint() {
  try {
    const url = new URL(runtimeInfo.gatewayUrl);
    return {
      address: url.hostname,
      port: url.port || (url.protocol === 'https:' ? '443' : '80'),
      value: `${url.protocol}//${url.host}`,
    };
  } catch {
    return { address: '127.0.0.1', port: '8787', value: 'http://127.0.0.1:8787' };
  }
}

export function GatewayOfflinePage({ onConnected }: GatewayOfflinePageProps) {
  const navigate = useNavigate();
  const endpoint = useMemo(gatewayEndpoint, []);
  const redirectTimerRef = useRef<number | null>(null);
  const toastTimerRef = useRef<number | null>(null);
  const [connectionState, setConnectionState] = useState<ConnectionState>('offline');
  const [connectionCopy, setConnectionCopy] = useState('未收到本地服务响应');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  useEffect(() => () => {
    if (redirectTimerRef.current !== null) window.clearTimeout(redirectTimerRef.current);
    if (toastTimerRef.current !== null) window.clearTimeout(toastTimerRef.current);
  }, []);

  function showToast(message: string) {
    setToast(message);
    if (toastTimerRef.current !== null) window.clearTimeout(toastTimerRef.current);
    toastTimerRef.current = window.setTimeout(() => setToast(null), 2200);
  }

  const retryMutation = useMutation({
    mutationFn: () => meetingApi.getGatewayInfo(),
    onMutate: () => {
      setConnectionState('checking');
      setConnectionCopy(`正在检查 ${endpoint.address}:${endpoint.port}`);
      setErrorMessage(null);
    },
    onSuccess: (info) => {
      setConnectionState('connected');
      setConnectionCopy(runtimeInfo.apiMode === 'mock' ? 'Mock Gateway 可用' : `Gateway ${info.version} 已连接`);
      showToast(runtimeInfo.apiMode === 'mock' ? 'Mock Gateway 检查通过' : '本地 Gateway 已连接');
      redirectTimerRef.current = window.setTimeout(() => {
        if (onConnected) onConnected(info);
        else navigate('/meetings', { replace: true });
      }, 700);
    },
    onError: () => {
      setConnectionState('offline');
      setConnectionCopy('未收到本地服务响应');
      setErrorMessage('请确认 PC Gateway 已启动，并继续使用当前本地接口地址。');
    },
  });

  const connected = connectionState === 'connected';
  const checking = connectionState === 'checking';
  const panelState = connected ? '服务正常' : checking ? '正在连接' : '无响应';

  return (
    <>
      <div className="gateway-offline-layout">
        <aside className="gateway-offline-sidebar">
          <Brand />
          <label className="gateway-offline-search-wrap"><span className="gateway-offline-search"><span aria-hidden="true">⌕</span><input type="search" placeholder="搜索会议" disabled /></span></label>
          <div className="gateway-offline-list-label">最近会议</div>
          <div className="gateway-offline-library-state">{connected ? '正在重新读取会议库' : '会议库暂不可读取'}</div>
          <div className={`gateway-offline-sidebar-foot ${connected ? 'gateway-offline-sidebar-foot-connected' : ''}`}><span className="gateway-offline-status-dot" /><span>{connected ? 'PC 本地服务已连接' : 'PC 本地服务未连接'}</span></div>
        </aside>

        <main className="gateway-offline-main">
          <header className="gateway-offline-topbar"><div className="gateway-offline-crumb">会议库 <span>/</span> <strong>本地服务未连接</strong></div></header>
          <div className="gateway-offline-content">
            <div className="gateway-offline-eyebrow">本地服务</div>
            <h1>{connected ? '本地服务已连接' : 'PC 本地服务未连接'}</h1>
            <div className={`gateway-offline-context ${connected ? 'gateway-offline-context-connected' : ''}`}>{connected ? '正在重新读取会议库' : '无法读取会议库或创建会议'}</div>

            <section className="gateway-offline-panel" aria-labelledby="gatewayConnectionTitle">
              <div className="gateway-offline-panel-head"><h2 className="gateway-offline-panel-title" id="gatewayConnectionTitle">连接本地 Gateway</h2><div className={`gateway-offline-panel-state gateway-offline-panel-state-${connectionState}`}>{panelState}</div></div>
              <div className="gateway-offline-endpoint">
                <label className="gateway-offline-field"><span>地址</span><input className="mono" value={endpoint.address} readOnly /></label>
                <label className="gateway-offline-field"><span>端口</span><input className="mono" value={endpoint.port} readOnly /></label>
              </div>
              <div className={`gateway-offline-result gateway-offline-result-${connectionState}`}><span>{connectionCopy}</span><strong>{connected ? '已连接' : checking ? '检查中' : '未连接'}</strong></div>
              {errorMessage ? <div className="gateway-offline-error" role="alert">{errorMessage}</div> : null}
              <div className="gateway-offline-actions"><button className="gateway-offline-action" type="button" onClick={() => showToast(`本地接口：${endpoint.value}`)}>查看本地接口</button><button className="gateway-offline-action gateway-offline-action-primary" type="button" disabled={checking || connected} onClick={() => retryMutation.mutate()}>{checking ? '连接中' : connected ? '已连接' : '重新连接'}</button></div>
            </section>

            <section className="gateway-offline-status-section" aria-labelledby="gatewayStatusTitle">
              <div className="gateway-offline-section-head"><h2 className="gateway-offline-section-title" id="gatewayStatusTitle">当前状态</h2><div className="gateway-offline-section-meta">本地会议文件未删除</div></div>
              <div className="gateway-offline-status-row"><span className="gateway-offline-status-name">浏览器页面</span><span className="gateway-offline-status-copy">当前页面可以继续显示</span><strong className="gateway-offline-value gateway-offline-value-online">可用</strong></div>
              <div className="gateway-offline-status-row"><span className="gateway-offline-status-name">会议库</span><span className="gateway-offline-status-copy">等待 Gateway 恢复后重新读取</span><strong className={`gateway-offline-value ${connected ? 'gateway-offline-value-online' : 'gateway-offline-value-offline'}`}>{connected ? '正在读取' : '暂不可用'}</strong></div>
              <div className="gateway-offline-status-row"><span className="gateway-offline-status-name">RK1828</span><span className="gateway-offline-status-copy">当前无法通过 Gateway 检查设备</span><strong className="gateway-offline-value gateway-offline-value-unknown">待确认</strong></div>
              <div className="gateway-offline-status-row"><span className="gateway-offline-status-name">新建会议</span><span className="gateway-offline-status-copy">本地服务恢复后开放</span><strong className={`gateway-offline-value ${connected ? 'gateway-offline-value-online' : 'gateway-offline-value-offline'}`}>{connected ? '即将开放' : '不可用'}</strong></div>
            </section>
          </div>
        </main>

        <aside className="gateway-offline-inspector">
          <div className="gateway-offline-inspector-head"><div className="gateway-offline-inspector-title">服务状态</div></div>
          <div className="gateway-offline-inspector-body">
            <div className="gateway-offline-detail-group">
              <div className="gateway-offline-detail-row"><span>当前电脑</span><strong className="gateway-offline-online">在线</strong></div>
              <div className="gateway-offline-detail-row"><span>本地 Gateway</span><strong className={connected ? 'gateway-offline-online' : 'gateway-offline-offline'}>{connected ? '已连接' : '未连接'}</strong></div>
              <div className="gateway-offline-detail-row"><span>RK1828</span><strong className="gateway-offline-unknown">待确认</strong></div>
              <div className="gateway-offline-detail-row"><span>会议库</span><strong className={connected ? 'gateway-offline-online' : 'gateway-offline-offline'}>{connected ? '正在读取' : '不可读取'}</strong></div>
            </div>
            <div className="gateway-offline-endpoint-block"><div className="gateway-offline-endpoint-label">本地接口</div><div className="gateway-offline-endpoint-value">{endpoint.value}</div></div>
            <button className="gateway-offline-inspector-button" type="button" onClick={() => showToast(`Gateway 脚本目录由本机配置管理`)}>查看服务位置</button>
          </div>
        </aside>
      </div>
      <Toast message={toast} />
    </>
  );
}
