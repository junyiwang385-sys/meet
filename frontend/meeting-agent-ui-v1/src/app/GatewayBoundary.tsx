import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useState, type ReactNode } from 'react';
import { useLocation } from 'react-router-dom';
import { meetingApi, runtimeInfo } from '../api';
import { Brand } from '../components/Brand';
import { GatewayOfflinePage } from '../features/system/GatewayOfflinePage';

type GatewayBoundaryState = 'checking' | 'ready' | 'offline';

interface GatewayBoundaryProps {
  children: ReactNode;
}

export function GatewayBoundary({ children }: GatewayBoundaryProps) {
  const location = useLocation();
  const queryClient = useQueryClient();
  const [state, setState] = useState<GatewayBoundaryState>(
    runtimeInfo.apiMode === 'gateway' ? 'checking' : 'ready',
  );

  const isOfflinePreview = location.pathname === '/system/gateway-offline';

  useEffect(() => {
    if (runtimeInfo.apiMode !== 'gateway' || isOfflinePreview) return undefined;

    let active = true;
    let networkFailure = false;
    const markOffline = () => {
      networkFailure = true;
      if (active) setState('offline');
    };

    window.addEventListener('meeting-agent:gateway-offline', markOffline);
    meetingApi.getGatewayInfo().then(
      () => {
        if (active) setState('ready');
      },
      () => {
        if (!active) return;
        setState(networkFailure ? 'offline' : 'ready');
      },
    );

    return () => {
      active = false;
      window.removeEventListener('meeting-agent:gateway-offline', markOffline);
    };
  }, [isOfflinePreview]);

  if (isOfflinePreview || runtimeInfo.apiMode !== 'gateway') return children;

  if (state === 'checking') {
    return (
      <div className="gateway-boundary-checking" role="status" aria-live="polite">
        <Brand />
        <div className="gateway-boundary-spinner" aria-hidden="true" />
        <strong>正在连接本地服务</strong>
        <span>{runtimeInfo.gatewayUrl}</span>
      </div>
    );
  }

  if (state === 'offline') {
    return (
      <GatewayOfflinePage
        onConnected={() => {
          setState('ready');
          void queryClient.invalidateQueries();
        }}
      />
    );
  }

  return children;
}
