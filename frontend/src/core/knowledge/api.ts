import { getBackendBaseURL } from "@/core/config";

export interface KnowledgeBaseStatus {
  enabled: boolean;
  doc_count: number;
  collection_name: string;
  docs_path: string;
}

export interface ReindexResponse {
  status: string;
  message: string;
}

export interface KnowledgeFileInfo {
  doc_id?: string | null;
  scope?: "global" | "thread" | "user" | null;
  filename: string;
  size: number;
  artifact_url: string;
  extension?: string;
  modified?: number;
  parse_method?: string;
  parse_status?: string;
  indexable?: boolean;
  preview_filename?: string | null;
  preview_artifact_url?: string | null;
  structured_filename?: string | null;
  structured_artifact_url?: string | null;
  index_target_filename?: string | null;
  index_target_artifact_url?: string | null;
  error?: string | null;
  hints?: Record<string, string>;
  type?: string | null;
  folder?: string | null;
  categories?: string[];
  eras?: string[];
  regions?: string[];
  keywords?: string[];
  summary?: string | null;
  author?: string | null;
  publisher?: string | null;
  tags?: string[];
  queue_stage?: string | null;
  queue_position?: number | null;
}

export interface KnowledgeMetadataUpdateInput {
  type?: string | null;
  folder?: string | null;
  categories?: string[];
  eras?: string[];
  regions?: string[];
  keywords?: string[];
  summary?: string | null;
  author?: string | null;
  publisher?: string | null;
  language_hint?: string | null;
  layout_hint?: string | null;
  document_type_hint?: string | null;
}

export interface KnowledgeUploadOptions {
  languageHint?: string;
  layoutHint?: string;
  documentTypeHint?: string;
  folderPath?: string | null;
}

export interface KnowledgeUploadResponse {
  success: boolean;
  files: KnowledgeFileInfo[];
  message: string;
}

export interface KnowledgeListResponse {
  files: KnowledgeFileInfo[];
  folder_path?: string | null;
  count: number;
}

export interface KnowledgeFolderSummary {
  name: string;
  path: string;
  parent_path?: string | null;
  file_count: number;
  direct_file_count: number;
}

export interface KnowledgeFolderListResponse {
  folders: KnowledgeFolderSummary[];
  count: number;
  root_file_count: number;
  total_file_count: number;
}

export interface KnowledgeParagraphLocation {
  doc_id?: string | null;
  scope?: "global" | "thread" | "user" | null;
  filename: string;
  title: string;
  page_count?: number | null;
  page_no?: number | null;
  pdf_page_no?: number | null;
  book_page_no?: number | null;
  paragraph_no?: number | null;
  bbox?: {
    x: number;
    y: number;
    width: number;
    height: number;
  } | null;
  page_meta?: {
    page_width?: number;
    page_height?: number;
  } | null;
  text: string;
  source_url?: string | null;
  original_url?: string | null;
}

export interface KnowledgeStructuredParagraph {
  paragraph_id?: string;
  paragraph_no?: number | null;
  paragraph_no_in_doc?: number | null;
  line_start?: number | null;
  line_end?: number | null;
  text: string;
  bbox?: {
    x: number;
    y: number;
    width: number;
    height: number;
  } | null;
}

export interface KnowledgeStructuredPage {
  doc_id?: string | null;
  scope?: "global" | "thread" | "user" | null;
  filename: string;
  title: string;
  layout_hint?: string | null;
  page_count?: number | null;
  page_no?: number | null;
  pdf_page_no?: number | null;
  book_page_no?: number | null;
  page_number_source?: string | null;
  page_meta?: {
    page_width?: number;
    page_height?: number;
  } | null;
  paragraphs: KnowledgeStructuredParagraph[];
  source_url?: string | null;
  original_url?: string | null;
}

export interface KnowledgeTranslationParagraphInput {
  key: string;
  text: string;
}

export interface KnowledgeTranslationParagraphResult {
  key: string;
  translation: string;
}

export interface UploadKnowledgeDocumentResponse {
  status: string;
  message: string;
  filename: string;
  markdown_filename?: string | null;
}

export interface KnowledgeDocumentInfo {
  filename: string;
  size: number;
  modified: number;
  extension: string;
}

export interface KnowledgeDocumentListResponse {
  docs: KnowledgeDocumentInfo[];
}

export interface KnowledgeDebugBookInfo {
  doc_id: string;
  title: string;
  filename: string;
  scope: string;
  folder?: string | null;
  summary?: string | null;
  language_hint?: string | null;
  parse_status?: string | null;
  indexable: boolean;
  modified?: number | null;
}

export interface KnowledgeDebugBooksResponse {
  books: KnowledgeDebugBookInfo[];
  count: number;
}

export interface KnowledgeDebugSearchRequest {
  query: string;
  doc_ids: string[];
  top_k?: number;
}

export interface KnowledgeDebugSearchResult {
  content: string;
  score: number;
  filename: string;
  title?: string | null;
  doc_id?: string | null;
  scope?: string | null;
  source: string;
  source_kind?: string | null;
  line_start?: number | null;
  line_end?: number | null;
  page_no?: number | null;
  pdf_page_no?: number | null;
  book_page_no?: number | null;
  paragraph_no?: number | null;
  matched_keywords?: string[] | null;
  source_url?: string | null;
  original_url?: string | null;
}

export interface KnowledgeDebugQdrantResponse {
  query: string;
  doc_ids: string[];
  top_k: number;
  elapsed_ms: number;
  results: KnowledgeDebugSearchResult[];
}

export interface KnowledgeDebugToolResponse {
  query: string;
  doc_ids: string[];
  elapsed_ms: number;
  output: string;
}

export type ResolvedKnowledgeDocument =
  | { scope: "global"; filename: string }
  | { scope: "user"; filename: string; basePath: string };

export function buildKnowledgeDocumentUrl(
  scope: "global" | "user",
  filename: string,
): string {
  if (scope === "global") {
    return `/api/knowledge/docs/${encodeURIComponent(filename)}`;
  }
  return `/api/secure-knowledge/users/me/knowledge/docs/${encodeURIComponent(filename)}`;
}

export function resolveKnowledgeDocumentUrl(documentUrl: string): ResolvedKnowledgeDocument | null {
  try {
    const base =
      typeof window !== "undefined"
        ? window.location.origin
        : "http://localhost:2026";
    const url = new URL(documentUrl, base);
    const globalMatch = /\/api\/knowledge\/docs\/([^/]+)$/.exec(url.pathname);
    if (globalMatch) {
      return {
        scope: "global",
        filename: decodeURIComponent(globalMatch[1] ?? ""),
      };
    }
    const userMatch = /(\/api\/secure-knowledge\/users\/me\/knowledge\/docs\/)([^/]+)$/.exec(url.pathname);
    if (userMatch) {
      return {
        scope: "user",
        basePath: userMatch[1] ?? "/api/secure-knowledge/users/me/knowledge/docs/",
        filename: decodeURIComponent(userMatch[2] ?? ""),
      };
    }
    return null;
  } catch {
    return null;
  }
}

export async function loadKnowledgeStatus(): Promise<KnowledgeBaseStatus> {
  const res = await fetch(`${getBackendBaseURL()}/api/knowledge/status`);
  if (!res.ok) {
    throw new Error("Failed to load knowledge base status");
  }
  return (await res.json()) as KnowledgeBaseStatus;
}

export async function triggerReindex(): Promise<ReindexResponse> {
  const res = await fetch(`${getBackendBaseURL()}/api/knowledge/reindex`, {
    method: "POST",
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({}));
    throw new Error(error.detail ?? "Failed to trigger reindex");
  }
  return (await res.json()) as ReindexResponse;
}

export async function uploadKnowledgeFiles(
  files: File[],
  options?: KnowledgeUploadOptions,
): Promise<KnowledgeUploadResponse> {
  const formData = new FormData();
  for (const file of files) {
    formData.append("files", file);
  }
  if (options?.languageHint) {
    formData.append("language_hint", options.languageHint);
  }
  if (options?.layoutHint) {
    formData.append("layout_hint", options.layoutHint);
  }
  if (options?.documentTypeHint) {
    formData.append("document_type_hint", options.documentTypeHint);
  }
  if (options?.folderPath) {
    formData.append("folder_path", options.folderPath);
  }

  const response = await fetch(`${getBackendBaseURL()}/api/knowledge/uploads`, {
    method: "POST",
    body: formData,
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Upload failed" }));
    throw new Error(error.detail ?? "Upload failed");
  }
  return (await response.json()) as KnowledgeUploadResponse;
}

export async function listKnowledgeFolders(): Promise<KnowledgeFolderListResponse> {
  const response = await fetch(`${getBackendBaseURL()}/api/knowledge/uploads/folders`);
  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ detail: "Failed to list folders" }));
    throw new Error(error.detail ?? "Failed to list folders");
  }
  return (await response.json()) as KnowledgeFolderListResponse;
}

export async function listKnowledgeFiles(
  folderPath?: string | null,
): Promise<KnowledgeListResponse> {
  const params = new URLSearchParams();
  if (folderPath) {
    params.set("folder_path", folderPath);
  }
  const query = params.toString();
  const response = await fetch(
    `${getBackendBaseURL()}/api/knowledge/uploads/list${query ? `?${query}` : ""}`,
  );
  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ detail: "Failed to list files" }));
    throw new Error(error.detail ?? "Failed to list files");
  }
  return (await response.json()) as KnowledgeListResponse;
}

export async function createKnowledgeFolder(
  path: string,
): Promise<{ success: boolean; folders: string[]; path?: string; message: string }> {
  const response = await fetch(`${getBackendBaseURL()}/api/knowledge/folders`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ path }),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Failed to create folder" }));
    throw new Error(error.detail ?? "Failed to create folder");
  }
  return (await response.json()) as { success: boolean; folders: string[]; path?: string; message: string };
}

export async function renameKnowledgeFolder(
  path: string,
  newPath: string,
): Promise<{ success: boolean; folders: string[]; path?: string; message: string }> {
  const response = await fetch(`${getBackendBaseURL()}/api/knowledge/folders`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ path, new_path: newPath }),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Failed to rename folder" }));
    throw new Error(error.detail ?? "Failed to rename folder");
  }
  return (await response.json()) as { success: boolean; folders: string[]; path?: string; message: string };
}

export async function deleteKnowledgeFolder(
  path: string,
): Promise<{ success: boolean; folders: string[]; deleted_path?: string; message: string }> {
  const params = new URLSearchParams({ path });
  const response = await fetch(`${getBackendBaseURL()}/api/knowledge/folders?${params.toString()}`, {
    method: "DELETE",
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Failed to delete folder" }));
    throw new Error(error.detail ?? "Failed to delete folder");
  }
  return (await response.json()) as { success: boolean; folders: string[]; deleted_path?: string; message: string };
}

export async function moveKnowledgeFolder(
  path: string,
  targetParent: string | null,
): Promise<{
  success: boolean;
  old_path: string;
  new_path: string;
  moved_files: number;
  folders: string[];
  message: string;
}> {
  const response = await fetch(`${getBackendBaseURL()}/api/knowledge/folders/move`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path, target_parent: targetParent }),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Failed to move folder" }));
    throw new Error(error.detail ?? "Failed to move folder");
  }
  return (await response.json()) as {
    success: boolean;
    old_path: string;
    new_path: string;
    moved_files: number;
    folders: string[];
    message: string;
  };
}

export async function mergeKnowledgeFolder(
  sourcePath: string,
  targetPath: string,
): Promise<{
  success: boolean;
  source_path: string;
  target_path: string;
  merged_files: number;
  folders: string[];
  message: string;
}> {
  const response = await fetch(`${getBackendBaseURL()}/api/knowledge/folders/merge`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source_path: sourcePath, target_path: targetPath }),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Failed to merge folder" }));
    throw new Error(error.detail ?? "Failed to merge folder");
  }
  return (await response.json()) as {
    success: boolean;
    source_path: string;
    target_path: string;
    merged_files: number;
    folders: string[];
    message: string;
  };
}

// ---------------------------------------------------------------------------
// Folder reorganization agent
// ---------------------------------------------------------------------------

export type FolderReorganizeOp =
  | { op: "move"; path: string; target_parent: string | null; reason: string }
  | { op: "merge"; source_path: string; target_path: string; reason: string }
  | { op: "rename"; path: string; new_path: string; reason: string };

export type FolderReorganizeEvent =
  | { type: "analyzing"; folder_count: number }
  | { type: "plan"; operations: FolderReorganizeOp[]; total: number; raw_response?: string }
  | { type: "progress"; step: number; total: number; op: FolderReorganizeOp; success: boolean; result?: Record<string, unknown>; error?: string }
  | { type: "done"; executed: number; skipped: number; message: string }
  | { type: "error"; message: string };

/**
 * Call the AI folder-reorganization agent and yield SSE events.
 * Usage:
 *   for await (const event of reorganizeKnowledgeFolders({ focusPath: "历史" })) { ... }
 */
export async function* reorganizeKnowledgeFolders(options?: {
  modelName?: string;
  focusPath?: string;
}): AsyncGenerator<FolderReorganizeEvent> {
  const response = await fetch(`${getBackendBaseURL()}/api/knowledge/folders/reorganize`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      model_name: options?.modelName ?? null,
      focus_path: options?.focusPath ?? null,
    }),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Failed to start reorganization" }));
    throw new Error(error.detail ?? "Failed to start reorganization");
  }
  const reader = response.body?.getReader();
  if (!reader) throw new Error("No response body");
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      if (line.startsWith("data: ")) {
        try {
          yield JSON.parse(line.slice(6)) as FolderReorganizeEvent;
        } catch {
          // ignore malformed frames
        }
      }
    }
  }
}

export async function deleteKnowledgeFile(
  filename: string,
): Promise<{ success: boolean; message: string }> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/knowledge/uploads/${encodeURIComponent(filename)}`,
    {
      method: "DELETE",
    },
  );
  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ detail: "Failed to delete file" }));
    throw new Error(error.detail ?? "Failed to delete file");
  }
  return (await response.json()) as { success: boolean; message: string };
}

export async function deleteKnowledgeFileArtifactsOnly(
  filename: string,
): Promise<{ success: boolean; message: string }> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/knowledge/uploads/${encodeURIComponent(filename)}/artifacts-only`,
    {
      method: "DELETE",
    },
  );
  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ detail: "Failed to delete file artifacts" }));
    throw new Error(error.detail ?? "Failed to delete file artifacts");
  }
  return (await response.json()) as { success: boolean; message: string };
}

export async function retryKnowledgeFileIndexing(
  filename: string,
): Promise<{ success: boolean; message: string }> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/knowledge/uploads/${encodeURIComponent(filename)}/reindex`,
    {
      method: "POST",
    },
  );
  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ detail: "Failed to retry indexing" }));
    throw new Error(error.detail ?? "Failed to retry indexing");
  }
  return (await response.json()) as { success: boolean; message: string };
}

export async function reparseKnowledgeFile(
  filename: string,
): Promise<{ success: boolean; message: string }> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/knowledge/uploads/${encodeURIComponent(filename)}/reparse`,
    {
      method: "POST",
    },
  );
  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ detail: "Failed to reparse file" }));
    throw new Error(error.detail ?? "Failed to reparse file");
  }
  return (await response.json()) as { success: boolean; message: string };
}

export async function updateKnowledgeFileMetadata(
  filename: string,
  payload: KnowledgeMetadataUpdateInput,
): Promise<{ success: boolean; message: string; metadata: KnowledgeMetadataUpdateInput & { tags?: string[] } }> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/knowledge/uploads/${encodeURIComponent(filename)}/metadata`,
    {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    },
  );
  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ detail: "Failed to update metadata" }));
    throw new Error(error.detail ?? "Failed to update metadata");
  }
  return (await response.json()) as { success: boolean; message: string; metadata: KnowledgeMetadataUpdateInput & { tags?: string[] } };
}

export async function regenerateKnowledgeFileMetadata(
  filename: string,
): Promise<{ success: boolean; message: string; metadata: KnowledgeMetadataUpdateInput & { tags?: string[] } }> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/knowledge/uploads/${encodeURIComponent(filename)}/metadata/regenerate`,
    {
      method: "POST",
    },
  );
  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ detail: "Failed to regenerate metadata" }));
    throw new Error(error.detail ?? "Failed to regenerate metadata");
  }
  return (await response.json()) as { success: boolean; message: string; metadata: KnowledgeMetadataUpdateInput & { tags?: string[] } };
}

export async function getKnowledgeParagraphLocation(
  filename: string,
  options: {
    pageNo?: string | number | null;
    pdfPageNo?: string | number | null;
    paragraphNo?: string | number | null;
  },
): Promise<KnowledgeParagraphLocation> {
  const params = new URLSearchParams();
  if (options.pageNo) {
    params.set("page_no", String(options.pageNo));
  }
  if (options.pdfPageNo) {
    params.set("pdf_page_no", String(options.pdfPageNo));
  }
  if (options.paragraphNo) {
    params.set("paragraph_no", String(options.paragraphNo));
  }
  const response = await fetch(
    `${getBackendBaseURL()}/api/knowledge/docs/${encodeURIComponent(filename)}/paragraph-location?${params.toString()}`,
  );
  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ detail: "Failed to fetch paragraph location" }));
    throw new Error(error.detail ?? "Failed to fetch paragraph location");
  }
  return (await response.json()) as KnowledgeParagraphLocation;
}

export async function getKnowledgeStructuredPage(
  filename: string,
  options: {
    pageNo?: string | number | null;
    pdfPageNo?: string | number | null;
  },
): Promise<KnowledgeStructuredPage> {
  const params = new URLSearchParams();
  if (options.pageNo) {
    params.set("page_no", String(options.pageNo));
  }
  if (options.pdfPageNo) {
    params.set("pdf_page_no", String(options.pdfPageNo));
  }
  const response = await fetch(
    `${getBackendBaseURL()}/api/knowledge/docs/${encodeURIComponent(filename)}/structured-page?${params.toString()}`,
  );
  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ detail: "Failed to fetch structured page" }));
    throw new Error(error.detail ?? "Failed to fetch structured page");
  }
  return (await response.json()) as KnowledgeStructuredPage;
}

export async function getKnowledgeParagraphLocationForDocumentUrl(
  documentUrl: string,
  options: {
    pageNo?: string | number | null;
    pdfPageNo?: string | number | null;
    paragraphNo?: string | number | null;
  },
): Promise<KnowledgeParagraphLocation> {
  const resolved = resolveKnowledgeDocumentUrl(documentUrl);
  if (!resolved) {
    throw new Error("Unsupported knowledge document url");
  }

  const params = new URLSearchParams();
  if (options.pageNo) {
    params.set("page_no", String(options.pageNo));
  }
  if (options.pdfPageNo) {
    params.set("pdf_page_no", String(options.pdfPageNo));
  }
  if (options.paragraphNo) {
    params.set("paragraph_no", String(options.paragraphNo));
  }

  const basePath =
    resolved.scope === "global"
      ? `${getBackendBaseURL()}/api/knowledge/docs/${encodeURIComponent(resolved.filename)}`
      : `${resolved.basePath}${encodeURIComponent(resolved.filename)}`;
  const response = await fetch(`${basePath}/paragraph-location?${params.toString()}`);
  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ detail: "Failed to fetch paragraph location" }));
    throw new Error(error.detail ?? "Failed to fetch paragraph location");
  }
  return (await response.json()) as KnowledgeParagraphLocation;
}

export async function getKnowledgeStructuredPageForDocumentUrl(
  documentUrl: string,
  options: {
    pageNo?: string | number | null;
    pdfPageNo?: string | number | null;
  },
): Promise<KnowledgeStructuredPage> {
  const resolved = resolveKnowledgeDocumentUrl(documentUrl);
  if (!resolved) {
    throw new Error("Unsupported knowledge document url");
  }

  const params = new URLSearchParams();
  if (options.pageNo) {
    params.set("page_no", String(options.pageNo));
  }
  if (options.pdfPageNo) {
    params.set("pdf_page_no", String(options.pdfPageNo));
  }

  const basePath =
    resolved.scope === "global"
      ? `${getBackendBaseURL()}/api/knowledge/docs/${encodeURIComponent(resolved.filename)}`
      : `${resolved.basePath}${encodeURIComponent(resolved.filename)}`;
  const response = await fetch(`${basePath}/structured-page?${params.toString()}`, {
    cache: "no-store",
  });
  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ detail: "Failed to fetch structured page" }));
    throw new Error(error.detail ?? "Failed to fetch structured page");
  }
  return (await response.json()) as KnowledgeStructuredPage;
}

export async function translateKnowledgeParagraphsToChineseForDocumentUrl(
  documentUrl: string,
  paragraphs: KnowledgeTranslationParagraphInput[],
  options?: {
    sourceLanguageHint?: string | null;
  },
): Promise<KnowledgeTranslationParagraphResult[]> {
  const resolved = resolveKnowledgeDocumentUrl(documentUrl);
  if (!resolved) {
    throw new Error("Unsupported knowledge document url");
  }

  const basePath =
    resolved.scope === "global"
      ? `${getBackendBaseURL()}/api/knowledge/docs/${encodeURIComponent(resolved.filename)}`
      : `${resolved.basePath}${encodeURIComponent(resolved.filename)}`;

  const response = await fetch(`${basePath}/translate-blocks`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      paragraphs,
      source_language_hint: options?.sourceLanguageHint ?? undefined,
    }),
  });
  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ detail: "Failed to translate page paragraphs" }));
    throw new Error(error.detail ?? "Failed to translate page paragraphs");
  }

  const payload = (await response.json()) as {
    translations?: Array<{ key?: string | null; translation?: string | null }>;
  };
  return (payload.translations ?? []).map((item) => ({
    key: String(item.key ?? ""),
    translation: String(item.translation ?? ""),
  }));
}

export function buildKnowledgePageImageURL(
  filename: string,
  pdfPageNo: string | number,
): string {
  const params = new URLSearchParams({
    pdf_page_no: String(pdfPageNo),
  });
  return `${getBackendBaseURL()}/api/knowledge/docs/${encodeURIComponent(filename)}/page-image?${params.toString()}`;
}

export function buildKnowledgePageImageURLForDocumentUrl(
  documentUrl: string,
  pdfPageNo: string | number,
): string {
  const resolved = resolveKnowledgeDocumentUrl(documentUrl);
  if (!resolved) {
    throw new Error("Unsupported knowledge document url");
  }
  const params = new URLSearchParams({
    pdf_page_no: String(pdfPageNo),
  });
  if (resolved.scope === "global") {
    return `${getBackendBaseURL()}/api/knowledge/docs/${encodeURIComponent(resolved.filename)}/page-image?${params.toString()}`;
  }
  return `${resolved.basePath}${encodeURIComponent(resolved.filename)}/page-image?${params.toString()}`;
}

export async function uploadKnowledgeDocument(
  file: File,
  options?: { reindex?: boolean },
): Promise<UploadKnowledgeDocumentResponse> {
  const formData = new FormData();
  formData.append("file", file);

  const params = new URLSearchParams();
  if (options?.reindex) {
    params.set("reindex", "true");
  }

  const query = params.toString();
  const url =
    `${getBackendBaseURL()}/api/knowledge/docs/upload` +
    (query ? `?${query}` : "");

  const res = await fetch(url, {
    method: "POST",
    body: formData,
  });

  if (!res.ok) {
    const error = await res.json().catch(() => ({}));
    throw new Error(error.detail ?? "Failed to upload knowledge document");
  }

  return (await res.json()) as UploadKnowledgeDocumentResponse;
}

export async function listKnowledgeDocuments(): Promise<KnowledgeDocumentListResponse> {
  const res = await fetch(`${getBackendBaseURL()}/api/knowledge/docs`);
  if (!res.ok) {
    const error = await res.json().catch(() => ({}));
    throw new Error(error.detail ?? "Failed to list knowledge documents");
  }
  return (await res.json()) as KnowledgeDocumentListResponse;
}

export async function deleteKnowledgeDocument(
  filename: string,
): Promise<{ success: boolean; message: string }> {
  const res = await fetch(
    `${getBackendBaseURL()}/api/knowledge/docs/${encodeURIComponent(filename)}`,
    { method: "DELETE" },
  );
  if (!res.ok) {
    const error = await res.json().catch(() => ({}));
    throw new Error(error.detail ?? "Failed to delete knowledge document");
  }
  return (await res.json()) as { success: boolean; message: string };
}

export async function listKnowledgeDebugBooks(): Promise<KnowledgeDebugBooksResponse> {
  const res = await fetch(`${getBackendBaseURL()}/api/knowledge/debug/books`);
  if (!res.ok) {
    const error = await res.json().catch(() => ({}));
    throw new Error(error.detail ?? "Failed to load debug books");
  }
  return (await res.json()) as KnowledgeDebugBooksResponse;
}

export async function runKnowledgeDebugQdrantSearch(
  payload: KnowledgeDebugSearchRequest,
): Promise<KnowledgeDebugQdrantResponse> {
  const res = await fetch(`${getBackendBaseURL()}/api/knowledge/debug/qdrant-search`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({}));
    throw new Error(error.detail ?? "Failed to run Qdrant debug search");
  }
  return (await res.json()) as KnowledgeDebugQdrantResponse;
}

export async function runKnowledgeDebugToolSearch(
  payload: KnowledgeDebugSearchRequest,
): Promise<KnowledgeDebugToolResponse> {
  const res = await fetch(`${getBackendBaseURL()}/api/knowledge/debug/knowledge-search`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({}));
    throw new Error(error.detail ?? "Failed to run knowledge_search debug call");
  }
  return (await res.json()) as KnowledgeDebugToolResponse;
}
