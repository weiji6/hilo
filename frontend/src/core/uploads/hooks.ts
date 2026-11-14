/**
 * React hooks for file uploads
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { FileUIPart } from "ai";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  deleteUploadedFile,
  listUploadedFiles,
  uploadFiles,
  type UploadedFileInfo,
  type UploadResponse,
} from "./api";

/**
 * Hook to upload files
 */
export function useUploadFiles(threadId: string) {
  const queryClient = useQueryClient();

  return useMutation<UploadResponse, Error, File[]>({
    mutationFn: (files: File[]) => uploadFiles(threadId, files),
    onSuccess: () => {
      // Invalidate the uploaded files list
      void queryClient.invalidateQueries({
        queryKey: ["uploads", "list", threadId],
      });
    },
  });
}

/**
 * Hook to list uploaded files
 */
export function useUploadedFiles(threadId: string) {
  return useQuery({
    queryKey: ["uploads", "list", threadId],
    queryFn: () => listUploadedFiles(threadId),
    enabled: !!threadId,
  });
}

/**
 * Hook to delete an uploaded file
 */
export function useDeleteUploadedFile(threadId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (filename: string) => deleteUploadedFile(threadId, filename),
    onSuccess: () => {
      // Invalidate the uploaded files list
      void queryClient.invalidateQueries({
        queryKey: ["uploads", "list", threadId],
      });
    },
  });
}

/**
 * Hook to eagerly upload files to the backend immediately when they are added
 * to the PromptInput attachments (on drop or file-select), before the form is
 * submitted. The send button should be disabled while `isUploading` is true.
 *
 * @param threadId  - The active thread ID (may be null for a brand-new thread)
 * @param files     - The current attachment files from usePromptInputAttachments()
 */
export function useEagerUpload(
  threadId: string | null | undefined,
  files: (FileUIPart & { id: string })[],
): { isUploading: boolean } {
  const [uploadingCount, setUploadingCount] = useState(0);
  // Track which attachment IDs we have already started uploading so we never
  // re-trigger for the same file even if the effect re-runs.
  const startedIdsRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    if (!threadId) return;

    for (const file of files) {
      if (startedIdsRef.current.has(file.id)) continue;
      if (!file.url || !file.filename) continue;

      startedIdsRef.current.add(file.id);
      setUploadingCount((n) => n + 1);

      void (async () => {
        try {
          const response = await fetch(file.url);
          const blob = await response.blob();
          const fileObj = new File([blob], file.filename!, {
            type: file.mediaType || blob.type,
          });
          await uploadFiles(threadId, [fileObj]);
        } catch (error) {
          console.error(
            `[useEagerUpload] Failed to upload "${file.filename}":`,
            error,
          );
        } finally {
          setUploadingCount((n) => n - 1);
        }
      })();
    }

    // Clean up tracking for files that were removed from the attachment list
    const currentIds = new Set(files.map((f) => f.id));
    for (const id of startedIdsRef.current) {
      if (!currentIds.has(id)) {
        startedIdsRef.current.delete(id);
      }
    }
  }, [files, threadId]);

  return { isUploading: uploadingCount > 0 };
}

/**
 * Hook to handle file uploads in submit flow
 * Returns a function that uploads files and returns their info
 */
export function useUploadFilesOnSubmit(threadId: string) {
  const uploadMutation = useUploadFiles(threadId);

  return useCallback(
    async (files: File[]): Promise<UploadedFileInfo[]> => {
      if (files.length === 0) {
        return [];
      }

      const result = await uploadMutation.mutateAsync(files);
      return result.files;
    },
    [uploadMutation],
  );
}
