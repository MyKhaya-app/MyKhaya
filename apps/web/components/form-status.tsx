export function FormStatus({
  message,
  error,
}: {
  message?: string;
  error?: string;
}) {
  return (
    <div aria-live="polite">
      {message && <p className="notice success">{message}</p>}
      {error && <p className="notice error">{error}</p>}
    </div>
  );
}
