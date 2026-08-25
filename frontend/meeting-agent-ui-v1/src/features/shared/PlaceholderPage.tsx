import { Link } from 'react-router-dom';
import { PageState } from '../../components/PageState';
import { WorkspaceShell } from './WorkspaceShell';

interface PlaceholderPageProps {
  section: string;
  title: string;
  copy: string;
}

export function PlaceholderPage({ section, title, copy }: PlaceholderPageProps) {
  return (
    <WorkspaceShell section={section} title={title}>
      <PageState title="此页面将在下一阶段实现" copy={copy} action={<Link className="secondary-button" to="/meetings">返回会议库</Link>} />
    </WorkspaceShell>
  );
}
