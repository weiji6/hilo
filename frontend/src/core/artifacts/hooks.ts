"use client";

import { useQuery } from "@tanstack/react-query";
import { useContext, useMemo } from "react";

import { ThreadContext } from "@/components/workspace/messages/context";

import { loadArtifactContent, loadArtifactContentFromToolCall } from "./loader";

export function useArtifactContent({
  filepath,
  threadId,
  enabled,
}: {
  filepath: string;
  threadId: string;
  enabled?: boolean;
}) {
  const isWriteFile = useMemo(() => {
    return filepath.startsWith("write-file:");
  }, [filepath]);
  const threadContext = useContext(ThreadContext);
  const content = useMemo(() => {
    if (isWriteFile && threadContext?.thread) {
      return loadArtifactContentFromToolCall({ url: filepath, thread: threadContext.thread });
    }
    return null;
  }, [filepath, isWriteFile, threadContext]);
  const { data, isLoading, error } = useQuery({
    queryKey: ["artifact", filepath, threadId],
    queryFn: () => {
      return loadArtifactContent({ filepath, threadId });
    },
    enabled,
    // Cache artifact content for 5 minutes to avoid repeated fetches (especially for .skill ZIP extraction)
    staleTime: 5 * 60 * 1000,
  });
  return { content: isWriteFile ? content : data, isLoading, error };
}
