"use client";

import { WorkspaceShell } from "./workspace-shell";

export function WorkspaceShellBoundary({
  children,
  user,
}: Readonly<{
  children: React.ReactNode;
  user?: {
    name?: string | null;
    email: string;
    image?: string | null;
  } | null;
}>) {
  return <WorkspaceShell user={user}>{children}</WorkspaceShell>;
}
