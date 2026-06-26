export default function RegisterPage() {
  return (
    <div className="w-full max-w-sm space-y-6 rounded-lg border border-border bg-card p-6">
      <h1 className="text-2xl font-semibold">Create account</h1>
      <p className="text-sm text-muted-foreground">
        Registration UI lands in the user-journey card. This page exists so the
        route resolves and the theme renders correctly.
      </p>
      <button
        type="button"
        disabled
        className="w-full rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground opacity-50"
      >
        Create account (coming soon)
      </button>
    </div>
  );
}