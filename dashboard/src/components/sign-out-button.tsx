import { signOut } from "@/auth";

export function SignOutButton() {
  return (
    <form
      action={async () => {
        "use server";
        await signOut({ redirectTo: "/signin" });
      }}
    >
      <button type="submit" className="text-sm underline underline-offset-4">
        Sign out
      </button>
    </form>
  );
}
