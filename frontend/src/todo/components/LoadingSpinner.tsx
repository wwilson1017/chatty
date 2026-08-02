export function LoadingSpinner() {
  return (
    <div style={{ display: 'flex', justifyContent: 'center', padding: '48px 0' }}>
      <div className="w-6 h-6 border-2 border-ch-accent border-t-transparent rounded-full animate-spin" />
    </div>
  );
}
