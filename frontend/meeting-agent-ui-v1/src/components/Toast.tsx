interface ToastProps {
  message: string | null;
}

export function Toast({ message }: ToastProps) {
  return (
    <div className={message ? 'toast toast-visible' : 'toast'} role="status" aria-live="polite">
      {message}
    </div>
  );
}
