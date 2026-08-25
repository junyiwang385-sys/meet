import type { PropsWithChildren, ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { Brand } from '../../components/Brand';

interface WorkspaceShellProps extends PropsWithChildren {
  section: string;
  title: string;
  meta?: string;
  actions?: ReactNode;
}

export function WorkspaceShell({ section, title, meta, actions, children }: WorkspaceShellProps) {
  return (
    <div className="workspace-shell">
      <aside className="workspace-sidebar">
        <Brand />
        <nav className="workspace-nav" aria-label="主要导航">
          <Link to="/meetings">会议库</Link>
          <Link to="/record/pc">PC 录音</Link>
          <Link to="/record/board">板端录音</Link>
        </nav>
        <div className="sidebar-footer">
          <span className="connection-dot" />
          <span>本地运行</span>
          <Link to="/settings">设置</Link>
        </div>
      </aside>
      <main className="workspace-main">
        <header className="workspace-topbar">
          <div className="breadcrumb"><Link to="/meetings">会议库</Link><span>/</span><strong>{section}</strong></div>
          <div className="topbar-actions">{actions}</div>
        </header>
        <div className="workspace-content">
          <header className="workspace-heading">
            <div>
              <div className="eyebrow">{section}</div>
              <h1>{title}</h1>
            </div>
            {meta ? <span className="heading-meta">{meta}</span> : null}
          </header>
          {children}
        </div>
      </main>
    </div>
  );
}
