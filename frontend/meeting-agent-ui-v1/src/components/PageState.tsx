interface PageStateProps {
  title: string;
  copy?: string;
  action?: React.ReactNode;
}

export function PageState({ title, copy, action }: PageStateProps) {
  return (
    <section className="page-state" aria-live="polite">
      <span className="page-state-mark" aria-hidden="true" />
      <h2>{title}</h2>
      {copy ? <p>{copy}</p> : null}
      {action ? <div className="page-state-action">{action}</div> : null}
    </section>
  );
}
