import Link from "next/link";
import { usePathname } from "next/navigation";

import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarTrigger,
  useSidebar,
} from "@/components/ui/sidebar";
import { useI18n } from "@/core/i18n/hooks";
import { env } from "@/env";
import { cn } from "@/lib/utils";

export function WorkspaceLogo({ className }: { className?: string }) {
  const { state, toggleSidebar } = useSidebar();
  const isCollapsed = state === "collapsed";

  return (
    <>
      {!isCollapsed && (
        <div
          className={cn(
            "group/workspace-header flex h-14 flex-col justify-center border-b border-primary/10",
            className,
          )}
        >
          <div className="flex items-center justify-between gap-2 px-2">
            <div className="flex items-center gap-2">
              <div
                className="bg-primary text-primary-foreground flex size-7 cursor-pointer items-center justify-center rounded-sm font-serif text-xs font-bold shadow-sm ring-1 ring-white/10"
                onClick={toggleSidebar}
              >
                H
              </div>
              <div className="text-primary font-serif text-sm font-bold tracking-wider">
                Hilo
              </div>
            </div>
            <SidebarTrigger />
          </div>
        </div>
      )}

      {isCollapsed && (
        <SidebarMenuItem className="collapsed-stack-item logo-stack-item group/logo transition-all">
          <SidebarMenuButton
            size="lg"
            className="flex size-full rounded-none items-center justify-center p-0! group-data-[collapsible=icon]:size-full! hover:bg-transparent data-[active=true]:bg-transparent"
            onClick={toggleSidebar}
            tooltip="展開選單"
          >
            <div className="flex flex-col gap-0.5">
              <span className="h-0.5 w-5 rounded-full bg-[#A38A52]"></span>
              <span className="h-0.5 w-5 rounded-full bg-[#A38A52]"></span>
              <span className="h-0.5 w-5 rounded-full bg-[#A38A52]"></span>
            </div>
          </SidebarMenuButton>
        </SidebarMenuItem>
      )}
    </>
  );
}

export function WorkspaceHeader({ className }: { className?: string }) {
  const { state } = useSidebar();
  const pathname = usePathname();
  const isCollapsed = state === "collapsed";
  const isNewChatActive = pathname === "/workspace/chats/new";
  const isNotesActive = pathname === "/workspace/notes";
  const isKnowledgeManageActive = pathname === "/workspace/knowledge-manage";
  const isKnowledgeDebugActive = pathname === "/workspace/knowledge-debug";

  if (isCollapsed) {
    return (
      <>
        <SidebarMenuItem className="collapsed-stack-item group/menu-item">
          <SidebarMenuButton
            isActive={isNewChatActive}
            asChild
            className="size-full rounded-none p-0! transition-colors group-data-[collapsible=icon]:size-full! hover:bg-transparent data-[active=true]:bg-transparent"
          >
            <Link
              className="group/item flex size-full flex-col items-center justify-center gap-2 px-1 py-3 font-serif transition-transform"
              href="/workspace/chats/new"
            >
              <span className="text-xl font-bold text-primary transition-all group-hover/menu-item:scale-105">
                貳
              </span>
              <span
                className={cn(
                  "writing-vertical text-center text-xs font-medium tracking-[0.2em] text-sidebar-foreground transition-opacity duration-200 group-hover/menu-item:opacity-100",
                  isNewChatActive ? "opacity-100" : "opacity-0",
                )}
              >
                新会话
              </span>
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>
        {env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY !== "true" && (
          <>
            <SidebarMenuItem className="collapsed-stack-item group/menu-item">
              <SidebarMenuButton
                isActive={isNotesActive}
                asChild
                className="size-full rounded-none p-0! transition-colors group-data-[collapsible=icon]:size-full! hover:bg-transparent data-[active=true]:bg-transparent"
              >
                <Link
                  className="group/item flex size-full flex-col items-center justify-center gap-2 px-1 py-3 font-serif transition-transform"
                  href="/workspace/notes"
                >
                  <span className="text-xl font-bold text-primary transition-all group-hover/menu-item:scale-105">
                    參
                  </span>
                  <span
                    className={cn(
                      "writing-vertical text-center text-xs font-medium tracking-[0.2em] text-sidebar-foreground transition-opacity duration-200 group-hover/menu-item:opacity-100",
                      isNotesActive ? "opacity-100" : "opacity-0",
                    )}
                  >
                    笔记
                  </span>
                </Link>
              </SidebarMenuButton>
            </SidebarMenuItem>
            <SidebarMenuItem className="collapsed-stack-item group/menu-item">
              <SidebarMenuButton
                isActive={isKnowledgeManageActive}
                asChild
                className="size-full rounded-none p-0! transition-colors group-data-[collapsible=icon]:size-full! hover:bg-transparent data-[active=true]:bg-transparent"
              >
                <Link
                  className="group/item flex size-full flex-col items-center justify-center gap-2 px-1 py-3 font-serif transition-transform"
                  href="/workspace/knowledge-manage"
                >
                  <span className="text-xl font-bold text-primary transition-all group-hover/menu-item:scale-105">
                    肆
                  </span>
                  <span
                    className={cn(
                      "writing-vertical text-center text-xs font-medium tracking-[0.2em] text-sidebar-foreground transition-opacity duration-200 group-hover/menu-item:opacity-100",
                      isKnowledgeManageActive ? "opacity-100" : "opacity-0",
                    )}
                  >
                    知识库
                  </span>
                </Link>
              </SidebarMenuButton>
            </SidebarMenuItem>
            {/* <SidebarMenuItem className="collapsed-stack-item group/menu-item">
              <SidebarMenuButton
                isActive={isKnowledgeDebugActive}
                asChild
                className="size-full rounded-none p-0! transition-colors group-data-[collapsible=icon]:size-full! hover:bg-transparent data-[active=true]:bg-transparent"
              >
                <Link
                  className="group/item flex size-full flex-col items-center justify-center gap-2 px-1 py-3 font-serif transition-transform"
                  href="/workspace/knowledge-debug"
                >
                  <span className="text-xl font-bold text-primary transition-all group-hover/menu-item:scale-105">
                    伍
                  </span>
                  <span
                    className={cn(
                      "writing-vertical text-center text-xs font-medium tracking-[0.2em] text-sidebar-foreground transition-opacity duration-200 group-hover/menu-item:opacity-100",
                      isKnowledgeDebugActive ? "opacity-100" : "opacity-0",
                    )}
                  >
                    实验台
                  </span>
                </Link>
              </SidebarMenuButton>
            </SidebarMenuItem> */}
          </>
        )}
      </>
    );
  }

  return (
    <SidebarMenu className="gap-1 px-2">
      <SidebarMenuItem>
        <SidebarMenuButton
          isActive={isNewChatActive}
          asChild
          className="h-auto py-2.5 transition-colors hover:bg-sidebar-accent data-[active=true]:bg-sidebar-accent"
        >
          <Link
            className="flex w-full items-center gap-3 font-serif"
            href="/workspace/chats/new"
          >
            <div className="flex flex-col items-center">
              <span className="text-sidebar-foreground text-xs font-bold">貳</span>
            </div>
            <span className="text-sm font-medium">
              开启新对话
            </span>
          </Link>
        </SidebarMenuButton>
      </SidebarMenuItem>
      {env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY !== "true" && (
        <>
          <SidebarMenuItem>
            <SidebarMenuButton
              isActive={isNotesActive}
              asChild
              className="h-auto py-2.5 transition-colors hover:bg-sidebar-accent data-[active=true]:bg-sidebar-accent"
            >
              <Link
                className="flex w-full items-center gap-3 font-serif"
                href="/workspace/notes"
              >
                <div className="flex flex-col items-center">
                  <span className="text-sidebar-foreground text-xs font-bold">參</span>
                </div>
                <span className="text-sm font-medium">
                  笔记
                </span>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
          <SidebarMenuItem>
            <SidebarMenuButton
              isActive={isKnowledgeManageActive}
              asChild
              className="h-auto py-2.5 transition-colors hover:bg-sidebar-accent data-[active=true]:bg-sidebar-accent"
            >
              <Link
                className="flex w-full items-center gap-3 font-serif"
                href="/workspace/knowledge-manage"
              >
                <div className="flex flex-col items-center">
                  <span className="text-sidebar-foreground text-xs font-bold">肆</span>
                </div>
                <span className="text-sm font-medium">
                  知识管理
                </span>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
          {/* test   */}
          {/* <SidebarMenuItem>
            <SidebarMenuButton
              isActive={isKnowledgeDebugActive}
              asChild
              className="h-auto py-2.5 transition-colors hover:bg-sidebar-accent data-[active=true]:bg-sidebar-accent"
            >
              <Link
                className="flex w-full items-center gap-3 font-serif"
                href="/workspace/knowledge-debug"
              >
                <div className="flex flex-col items-center">
                  <span className="text-sidebar-foreground text-xs font-bold">伍</span>
                </div>
                <span className="text-sm font-medium">
                  检索实验台
                </span>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem> */}
        </>
      )}
    </SidebarMenu>
  );
}
