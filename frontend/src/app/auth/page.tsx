import { redirect } from "next/navigation";
import { SilkRibbon } from "@/components/workspace/silk-ribbon";
import { AuthForm } from "@/components/auth/auth-form";
import { env } from "@/env";
import { getSession } from "@/server/better-auth/server";

function resolveNextPath(nextPath: string | string[] | undefined) {
  const candidate = Array.isArray(nextPath) ? nextPath[0] : nextPath;
  if (candidate?.startsWith("/") !== true) {
    return "/workspace";
  }
  return candidate;
}

export default async function AuthPage({
  searchParams,
}: {
  searchParams?: Promise<{ next?: string | string[] }>;
}) {
  if (env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true") {
    redirect("/workspace");
  }

  const params = await searchParams;
  const nextPath = resolveNextPath(params?.next);
  const session = await getSession();
  if (session) {
    redirect(nextPath);
  }

  return (
    <main className="relative flex min-h-screen flex-col items-center justify-center overflow-hidden bg-background px-6 py-12">
      <div className="relative z-10 w-full max-w-md">
        <div className="mb-12 text-center">
          <h1 className="font-serif text-4xl font-bold tracking-[0.2em] text-foreground">
            Hilo <br />
            <span className="text-primary italic opacity-90">让知识成为线索</span>
          </h1>
          <div className="mx-auto mt-6 h-px w-24 bg-primary/30" />
        </div>
        
        <div className="flex justify-center">
          <AuthForm />
        </div>
      </div>

      <SilkRibbon />
    </main>
  );
}
