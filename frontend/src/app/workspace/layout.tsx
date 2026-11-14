import { redirect } from "next/navigation";

import { WorkspaceShellBoundary } from "@/components/workspace/workspace-shell-boundary";
import { env } from "@/env";
import { getSession } from "@/server/better-auth/server";

export default async function WorkspaceLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  let user:
    | {
        name?: string | null;
        email: string;
        image?: string | null;
      }
    | null
    | undefined;

  if (env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY !== "true") {
    const session = await getSession();
    if (!session) {
      redirect("/auth?next=%2Fworkspace");
    }

    user = session.user.email
      ? {
          email: session.user.email,
          image: session.user.image,
          name: session.user.name,
        }
      : null;
  }

  return (
    <WorkspaceShellBoundary user={user}>{children}</WorkspaceShellBoundary>
  );
}
