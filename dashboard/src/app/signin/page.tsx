import { signIn } from "@/auth";

export default function SignInPage() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-6 p-8">
      <div className="flex flex-col items-center gap-2 text-center">
        <h1 className="text-2xl font-semibold">Artisan</h1>
        <p className="text-sm text-muted-foreground">
          Sign in with a GitHub account that has access to 403errors/artisan-demo.
        </p>
      </div>
      <form
        action={async () => {
          "use server";
          await signIn("github", { redirectTo: "/tickets" });
        }}
      >
        <button
          type="submit"
          className="rounded-md bg-foreground px-4 py-2 text-sm font-medium text-background hover:opacity-90"
        >
          Sign in with GitHub
        </button>
      </form>
    </div>
  );
}
