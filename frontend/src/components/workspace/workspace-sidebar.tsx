"use client";

import {
  Sidebar,
  SidebarHeader,
  SidebarContent,
  SidebarFooter,
  SidebarMenu,
  SidebarRail,
  useSidebar,
} from "@/components/ui/sidebar";
import { cn } from "@/lib/utils";

import { RecentChatList } from "./recent-chat-list";
import { WorkspaceHeader, WorkspaceLogo } from "./workspace-header";
import { WorkspaceNavChatList } from "./workspace-nav-chat-list";
import { WorkspaceUserNav } from "./workspace-user-nav";

type WorkspaceUser = {
  name?: string | null;
  email: string;
  image?: string | null;
};

export function WorkspaceSidebar({
  user,
  ...props
}: React.ComponentProps<typeof Sidebar> & {
  user?: WorkspaceUser | null;
}) {
  const { open: isSidebarOpen } = useSidebar();
  return (
    <>
      <Sidebar
        variant="sidebar"
        collapsible="icon"
        className="border-r border-[rgba(126,51,46,0.08)] bg-[linear-gradient(180deg,rgba(255,255,255,0.9),rgba(252,250,243,0.98))] font-serif shadow-none"
        {...props}
      >
        <SidebarContent
          className={cn(
            "flex flex-col gap-0",
            isSidebarOpen ? "gap-2 py-2" : "collapsed-stack",
          )}
        >
          {isSidebarOpen ? (
            <>
              <WorkspaceLogo />
              <WorkspaceNavChatList />
              <WorkspaceHeader />
              <RecentChatList />
            </>
          ) : (
            <SidebarMenu className="flex-1 gap-0">
              <WorkspaceLogo />
              <WorkspaceNavChatList />
              <WorkspaceHeader />
              <WorkspaceUserNav user={user ?? undefined} />
            </SidebarMenu>
          )}
        </SidebarContent>
        {isSidebarOpen && (
          <SidebarFooter>
            <WorkspaceUserNav user={user ?? undefined} />
          </SidebarFooter>
        )}
        <SidebarRail />
      </Sidebar>
    </>
  );
}
