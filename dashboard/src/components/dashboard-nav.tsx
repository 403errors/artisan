import Link from "next/link";

import { SignOutButton } from "@/components/sign-out-button";

export function DashboardNav() {
  return (
    <nav className="flex items-center justify-between border-b p-4">
      <div className="flex items-center gap-4">
        <span className="font-semibold">Artisan</span>
        <Link href="/tickets" className="text-sm underline underline-offset-4">
          Tickets
        </Link>
      </div>
      <SignOutButton />
    </nav>
  );
}
