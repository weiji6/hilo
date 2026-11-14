"use client";

import {
  MutationCache,
  QueryCache,
  QueryClient,
  QueryClientProvider,
} from "@tanstack/react-query";
import { usePathname } from "next/navigation";
import { type CSSProperties } from "react";
import { useCallback, useEffect, useState } from "react";
import { Toaster } from "sonner";

import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { WorkspaceSidebar } from "@/components/workspace/workspace-sidebar";
import { useLocalSettings } from "@/core/settings";

function getErrorStatus(error: unknown) {
  if (!error || typeof error !== "object") {
    return undefined;
  }

  const candidate = error as {
    status?: unknown;
    response?: { status?: unknown };
  };
  const status = candidate.status ?? candidate.response?.status;
  return typeof status === "number" ? status : undefined;
}

function redirectToAuth() {
  if (typeof window === "undefined") {
    return;
  }

  const next = `${window.location.pathname}${window.location.search}`;
  const authUrl = new URL("/auth", window.location.origin);
  authUrl.searchParams.set("next", next);
  window.location.replace(authUrl.toString());
}

function handleAuthError(error: unknown) {
  if (getErrorStatus(error) === 401) {
    redirectToAuth();
  }
}

const queryClient = new QueryClient({
  queryCache: new QueryCache({
    onError: handleAuthError,
  }),
  mutationCache: new MutationCache({
    onError: handleAuthError,
  }),
  defaultOptions: {
    queries: {
      retry(failureCount, error) {
        if (getErrorStatus(error) === 401) {
          return false;
        }
        return failureCount < 3;
      },
    },
  },
});

const workspaceTheme = {
  "--background": "#fdfcf0",
  "--foreground": "#1c1917",
  "--card": "#ffffff",
  "--card-foreground": "#1c1917",
  "--popover": "#ffffff",
  "--popover-foreground": "#1c1917",
  "--primary": "#7e332e",
  "--primary-foreground": "#ffffff",
  "--secondary": "#f7f3ea",
  "--secondary-foreground": "#1c1917",
  "--muted": "#f7f3ea",
  "--muted-foreground": "#78716c",
  "--accent": "#a38a52",
  "--accent-foreground": "#ffffff",
  "--border": "rgba(126, 51, 46, 0.1)",
  "--input": "rgba(126, 51, 46, 0.1)",
  "--ring": "rgba(126, 51, 46, 0.12)",
  "--sidebar": "#fcfaf3",
  "--sidebar-foreground": "#1c1917",
  "--sidebar-primary": "#7e332e",
  "--sidebar-primary-foreground": "#ffffff",
  "--sidebar-accent": "rgba(126, 51, 46, 0.05)",
  "--sidebar-accent-foreground": "#1c1917",
  "--sidebar-border": "rgba(126, 51, 46, 0.08)",
  "--sidebar-ring": "rgba(126, 51, 46, 0.16)",
} as CSSProperties;

type WorkspaceUser = {
  name?: string | null;
  email: string;
  image?: string | null;
};

export function WorkspaceShell({
  children,
  user,
}: Readonly<{ children: React.ReactNode; user?: WorkspaceUser | null }>) {
  const pathname = usePathname();
  const [settings, setSettings] = useLocalSettings();
  const [open, setOpen] = useState(() => !settings.layout.sidebar_collapsed);
  const isImmersiveKnowledgeView = pathname.startsWith("/workspace/knowledge/view");

  useEffect(() => {
    setOpen(!settings.layout.sidebar_collapsed);
  }, [settings.layout.sidebar_collapsed]);

  const handleOpenChange = useCallback(
    (nextOpen: boolean) => {
      setOpen(nextOpen);
      setSettings("layout", { sidebar_collapsed: !nextOpen });
    },
    [setSettings],
  );

  return (
    <QueryClientProvider client={queryClient}>
      {isImmersiveKnowledgeView ? (
        <div
          className="h-screen bg-[linear-gradient(180deg,rgba(255,255,255,1),rgba(253,252,240,1))] text-foreground"
          style={workspaceTheme}
        >
          {children}
        </div>
      ) : (
        <SidebarProvider
          className="h-screen bg-[linear-gradient(180deg,rgba(255,255,255,1),rgba(253,252,240,1))] text-foreground"
          open={open}
          onOpenChange={handleOpenChange}
          style={workspaceTheme}
        >
          <WorkspaceSidebar user={user} />
          <SidebarInset className="min-w-0 bg-transparent">
            {children}
          </SidebarInset>
        </SidebarProvider>
      )}
      <Toaster position="top-center" />
    </QueryClientProvider>
  );
}
