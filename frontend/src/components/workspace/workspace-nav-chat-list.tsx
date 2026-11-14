"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/components/ui/sidebar";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

export function WorkspaceNavChatList() {
  const { t } = useI18n();
  const pathname = usePathname();
  const { state } = useSidebar();
  const isCollapsed = state === "collapsed";
  const isChatsActive = pathname === "/workspace/chats";

  if (isCollapsed) {
    return (
      <SidebarMenuItem className="collapsed-stack-item group/menu-item">
        <SidebarMenuButton
          isActive={isChatsActive}
          asChild
          className="size-full rounded-none p-0! transition-colors group-data-[collapsible=icon]:size-full! hover:bg-transparent data-[active=true]:bg-transparent"
        >
          <Link
            className="group/item flex size-full flex-col items-center justify-center gap-2 px-1 py-3 font-serif transition-transform"
            href="/workspace/chats"
          >
            <span className="text-xl font-bold text-primary transition-all group-hover/menu-item:scale-105">
              壹
            </span>
            <span
              className={cn(
                "writing-vertical text-center text-xs font-medium tracking-[0.2em] text-sidebar-foreground transition-opacity duration-200 group-hover/menu-item:opacity-100",
                isChatsActive ? "opacity-100" : "opacity-0",
              )}
            >
              对话
            </span>
          </Link>
        </SidebarMenuButton>
      </SidebarMenuItem>
    );
  }

  return (
    <SidebarMenu className="px-2">
      <SidebarMenuItem>
        <SidebarMenuButton
          isActive={isChatsActive}
          asChild
          className="h-auto py-2.5 transition-colors hover:bg-sidebar-accent data-[active=true]:bg-sidebar-accent"
        >
          <Link
            className="flex w-full items-center gap-3 font-serif"
            href="/workspace/chats"
          >
            <div className="flex flex-col items-center text-xs font-bold">
              <span className="text-sidebar-foreground">壹</span>
            </div>
            <span className="text-sm font-medium">对话</span>
          </Link>
        </SidebarMenuButton>
      </SidebarMenuItem>
    </SidebarMenu>
  );
}
