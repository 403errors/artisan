import Link from "next/link";

export default function AccessDeniedPage() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4 p-8 text-center">
      <h1 className="text-2xl font-semibold">Access denied</h1>
      <p className="max-w-md text-sm text-muted-foreground">
        Your GitHub account doesn&apos;t have collaborator access to the repo this dashboard
        tracks. Ask a maintainer to add you, then sign in again.
      </p>
      <Link href="/signin" className="text-sm underline underline-offset-4">
        Back to sign in
      </Link>
    </div>
  );
}
