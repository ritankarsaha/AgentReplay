export function ErrorBanner({ error }: { error: { type: string; message: string } }) {
  return (
    <div className="rounded-sm border border-status-failure/40 bg-status-failure/10 px-2.5 py-1.5 font-mono text-xs text-status-failure">
      {error.type}: {error.message}
    </div>
  );
}
