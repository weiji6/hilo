/**
 * Chunked upload functionality for large files (10-100MB+).
 * 
 * Splits files into 5MB chunks, uploads with concurrency control,
 * and provides progress tracking.
 */

import { getBackendBaseURL } from "../config";

const DEFAULT_CHUNK_SIZE = 5 * 1024 * 1024; // 5MB
const MAX_CONCURRENT_UPLOADS = 3;
const MAX_RETRIES = 3;

export interface ChunkedUploadOptions {
  chunkSize?: number;
  onProgress?: (progress: number, uploadedBytes: number, totalBytes: number) => void;
  onChunkComplete?: (chunkIndex: number, totalChunks: number) => void;
  reindex?: boolean;
  signal?: AbortSignal;
}

export interface ChunkedUploadResult {
  status: string;
  message: string;
  filename: string;
  fileSize: number;
}

interface InitUploadResponse {
  upload_id: string;
  chunk_size: number;
  total_chunks: number;
  filename: string;
}

interface ChunkUploadResponse {
  chunk_index: number;
  received: boolean;
  chunks_received: number;
  total_chunks: number;
}

interface CompleteUploadResponse {
  status: string;
  message: string;
  filename: string;
  file_size: number;
}

async function initUpload(
  filename: string,
  fileSize: number,
  chunkSize: number,
): Promise<InitUploadResponse> {
  const res = await fetch(`${getBackendBaseURL()}/api/knowledge/uploads/init`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      filename,
      file_size: fileSize,
      chunk_size: chunkSize,
      content_type: "application/octet-stream",
    }),
  });

  if (!res.ok) {
    const error = await res.json().catch(() => ({}));
    throw new Error(error.detail ?? "Failed to initialize upload");
  }

  return res.json() as Promise<InitUploadResponse>;
}

async function uploadChunk(
  uploadId: string,
  chunkIndex: number,
  chunkData: Blob,
  retries = 0,
): Promise<ChunkUploadResponse> {
  const formData = new FormData();
  formData.append("chunk_index", chunkIndex.toString());
  formData.append("chunk", chunkData, `chunk_${chunkIndex}`);

  try {
    const res = await fetch(
      `${getBackendBaseURL()}/api/knowledge/uploads/${uploadId}/chunk`,
      {
        method: "POST",
        body: formData,
      },
    );

    if (!res.ok) {
      const error = await res.json().catch(() => ({}));
      throw new Error(error.detail ?? `Failed to upload chunk ${chunkIndex}`);
    }

    return res.json() as Promise<ChunkUploadResponse>;
  } catch (error) {
    if (retries < MAX_RETRIES) {
      await new Promise((resolve) => setTimeout(resolve, 1000 * (retries + 1)));
      return uploadChunk(uploadId, chunkIndex, chunkData, retries + 1);
    }
    throw error;
  }
}

async function completeUpload(
  uploadId: string,
  reindex: boolean,
): Promise<CompleteUploadResponse> {
  const params = new URLSearchParams();
  if (reindex) {
    params.set("reindex", "true");
  }

  const query = params.toString();
  const url =
    `${getBackendBaseURL()}/api/knowledge/uploads/${uploadId}/complete` +
    (query ? `?${query}` : "");

  const res = await fetch(url, { method: "POST" });

  if (!res.ok) {
    const error = await res.json().catch(() => ({}));
    throw new Error(error.detail ?? "Failed to complete upload");
  }

  return res.json() as Promise<CompleteUploadResponse>;
}

async function cancelUpload(uploadId: string): Promise<void> {
  try {
    await fetch(`${getBackendBaseURL()}/api/knowledge/uploads/${uploadId}`, {
      method: "DELETE",
    });
  } catch {
    // Ignore errors when cancelling
  }
}

/**
 * Upload a large file using chunked upload.
 * 
 * @param file - The file to upload
 * @param options - Upload options including progress callback
 * @returns Upload result with filename and size
 */
export async function uploadLargeFile(
  file: File,
  options: ChunkedUploadOptions = {},
): Promise<ChunkedUploadResult> {
  const {
    chunkSize = DEFAULT_CHUNK_SIZE,
    onProgress,
    onChunkComplete,
    reindex = false,
    signal,
  } = options;

  // Initialize upload session
  const initResponse = await initUpload(file.name, file.size, chunkSize);
  const { upload_id: uploadId, total_chunks: totalChunks } = initResponse;

  // Track uploaded chunks for progress
  let uploadedChunks = 0;
  const chunkPromises: Promise<void>[] = [];
  const pendingChunks: number[] = [];

  // Generate chunk indices
  for (let i = 0; i < totalChunks; i++) {
    pendingChunks.push(i);
  }

  // Semaphore for concurrency control
  let activeUploads = 0;

  const uploadNextChunk = async (): Promise<void> => {
    while (pendingChunks.length > 0) {
      // Check for abort
      if (signal?.aborted) {
        await cancelUpload(uploadId);
        throw new DOMException("Upload cancelled", "AbortError");
      }

      // Wait if at concurrency limit
      if (activeUploads >= MAX_CONCURRENT_UPLOADS) {
        await new Promise((resolve) => setTimeout(resolve, 100));
        continue;
      }

      const chunkIndex = pendingChunks.shift();
      if (chunkIndex === undefined) break;

      activeUploads++;

      try {
        const start = chunkIndex * chunkSize;
        const end = Math.min(start + chunkSize, file.size);
        const chunkData = file.slice(start, end);

        await uploadChunk(uploadId, chunkIndex, chunkData);
        uploadedChunks++;

        // Report progress
        const uploadedBytes = Math.min(uploadedChunks * chunkSize, file.size);
        onProgress?.(uploadedChunks / totalChunks, uploadedBytes, file.size);
        onChunkComplete?.(chunkIndex, totalChunks);
      } finally {
        activeUploads--;
      }
    }
  };

  // Start concurrent uploaders
  const uploaders = Array.from({ length: MAX_CONCURRENT_UPLOADS }, () =>
    uploadNextChunk(),
  );

  try {
    await Promise.all(uploaders);

    // Complete the upload
    const completeResponse = await completeUpload(uploadId, reindex);

    return {
      status: completeResponse.status,
      message: completeResponse.message,
      filename: completeResponse.filename,
      fileSize: completeResponse.file_size,
    };
  } catch (error) {
    // Cancel upload on error
    await cancelUpload(uploadId);
    throw error;
  }
}

/**
 * Check if a file should use chunked upload based on size.
 * Files larger than 10MB are recommended for chunked upload.
 */
export function shouldUseChunkedUpload(file: File): boolean {
  const CHUNKED_UPLOAD_THRESHOLD = 10 * 1024 * 1024; // 10MB
  return file.size > CHUNKED_UPLOAD_THRESHOLD;
}
