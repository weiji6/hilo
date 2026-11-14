"use client";

import type { CSSProperties, HTMLAttributes } from "react";

import { cn } from "@/lib/utils";

type KnowledgePageSurfaceProps = HTMLAttributes<HTMLDivElement> & {
  height?: number | null;
  width?: number | null;
};

export function KnowledgePageSurface({
  children,
  className,
  height,
  style,
  width,
  ...props
}: KnowledgePageSurfaceProps) {
  const resolvedStyle: CSSProperties = {
    ...style,
    ...(width ? { width: `${width}px` } : {}),
    ...(height ? { height: `${height}px` } : {}),
  };

  return (
    <div
      className={cn(
        "relative shrink-0 overflow-hidden rounded-xl bg-white shadow-[0_8px_30px_rgb(0,0,0,0.04)] ring-1 ring-slate-200/50",
        className,
      )}
      style={resolvedStyle}
      {...props}
    >
      {children}
    </div>
  );
}
