const USER_KNOWLEDGE_API_BASE = "/api/secure-knowledge/users/me/knowledge";

export interface UserKnowledgeRecord {
  id: string;
  user_id: string;
  source_kind:
    | "upload"
    | "import_ref"
    | "excerpt"
    | "annotation"
    | "translation"
    | "note";
  title: string;
  display_title?: string | null;
  origin_scope?: string | null;
  origin_doc_id?: string | null;
  origin_filename?: string | null;
  origin_anchor?: Record<string, unknown> | null;
  knowledge_space_id?: string | null;
  knowledge_space_name?: string | null;
  folder_path?: string | null;
  retrieval_enabled: boolean;
  filename?: string | null;
  size: number;
  extension?: string | null;
  content_type?: string | null;
  parse_method?: string | null;
  parse_status?: string | null;
  indexable?: boolean;
  artifact_url?: string | null;
  preview_filename?: string | null;
  preview_artifact_url?: string | null;
  structured_filename?: string | null;
  index_target_filename?: string | null;
  hints?: Record<string, string>;
  document_type?: string | null;
  error?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface UserKnowledgeSpace {
  id: string;
  name: string;
  description?: string | null;
  type: "personal" | "public";
  readonly: boolean;
  is_default: boolean;
  record_count?: number;
  document_count?: number;
  note_count?: number;
  latest_updated_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface UserKnowledgeListResponse {
  records: UserKnowledgeRecord[];
  folders?: string[];
  count: number;
  indexed_count: number;
  doc_count: number;
  latest_updated_at?: string | null;
}

export interface UserKnowledgeUploadResponse {
  success: boolean;
  records: UserKnowledgeRecord[];
  message: string;
}

export interface UserKnowledgeRecordContentResponse {
  record: UserKnowledgeRecord;
  title: string;
  mode: "derived" | "text" | "readonly";
  editable: boolean;
  content: string;
  editable_content: string;
  locked_excerpt: string;
  origin_filename?: string | null;
  location_label?: string | null;
}

export interface CreateUserDerivedKnowledgeInput {
  title: string;
  content: string;
  sourceKind: "excerpt" | "annotation" | "translation" | "note";
  originScope?: string | null;
  originDocId?: string | null;
  originFilename?: string | null;
  originAnchor?: Record<string, unknown> | null;
  derivedFromId?: string | null;
  hints?: Record<string, string> | null;
  knowledgeSpaceId?: string | null;
  folderPath?: string | null;
}

export interface AppendExcerptToUserNoteInput {
  excerptText: string;
  originScope?: string | null;
  originDocId?: string | null;
  originFilename?: string | null;
  originAnchor?: Record<string, unknown> | null;
}

export async function listUserKnowledgeRecords(
  knowledgeSpaceId?: string | null,
): Promise<UserKnowledgeListResponse> {
  const params = new URLSearchParams();
  if (knowledgeSpaceId) {
    params.set("knowledge_space_id", knowledgeSpaceId);
  }
  const query = params.toString();
  const response = await fetch(
    `${USER_KNOWLEDGE_API_BASE}/list${query ? `?${query}` : ""}`,
    {
      cache: "no-store",
    },
  );
  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ message: "Failed to list personal knowledge" }));
    throw new Error(
      error.message ?? error.detail ?? "Failed to list personal knowledge",
    );
  }
  return (await response.json()) as UserKnowledgeListResponse;
}

export async function uploadUserKnowledgeFiles(
  files: File[],
  options?: {
    languageHint?: string;
    layoutHint?: string;
    documentTypeHint?: string;
    knowledgeSpaceId?: string | null;
    folderPath?: string | null;
  },
): Promise<UserKnowledgeUploadResponse> {
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
  if (options?.knowledgeSpaceId) {
    formData.append("knowledge_space_id", options.knowledgeSpaceId);
  }
  if (options?.folderPath) {
    formData.append("folder_path", options.folderPath);
  }

  const response = await fetch(`${USER_KNOWLEDGE_API_BASE}/upload`, {
    method: "POST",
    body: formData,
  });
  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ message: "Upload failed" }));
    throw new Error(error.message ?? error.detail ?? "Upload failed");
  }
  return (await response.json()) as UserKnowledgeUploadResponse;
}

export async function listUserKnowledgeSpaces(): Promise<{
  spaces: UserKnowledgeSpace[];
}> {
  const response = await fetch(`${USER_KNOWLEDGE_API_BASE}/spaces`, {
    cache: "no-store",
  });
  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ message: "Failed to list knowledge spaces" }));
    throw new Error(
      error.message ?? error.detail ?? "Failed to list knowledge spaces",
    );
  }
  return (await response.json()) as { spaces: UserKnowledgeSpace[] };
}

export async function createUserKnowledgeSpace(payload: {
  name: string;
  description?: string;
}): Promise<{ success: boolean; space: UserKnowledgeSpace; message: string }> {
  const response = await fetch(`${USER_KNOWLEDGE_API_BASE}/spaces`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ message: "Failed to create knowledge space" }));
    throw new Error(
      error.message ?? error.detail ?? "Failed to create knowledge space",
    );
  }
  return (await response.json()) as {
    success: boolean;
    space: UserKnowledgeSpace;
    message: string;
  };
}

export async function deleteUserKnowledgeSpace(spaceId: string): Promise<{
  success: boolean;
  deleted_space_id: string;
  moved_record_ids: string[];
  fallback_space_id: string;
  message: string;
}> {
  const response = await fetch(
    `${USER_KNOWLEDGE_API_BASE}/spaces/${encodeURIComponent(spaceId)}`,
    {
      method: "DELETE",
    },
  );
  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ message: "Failed to delete knowledge space" }));
    throw new Error(
      error.message ?? error.detail ?? "Failed to delete knowledge space",
    );
  }
  return (await response.json()) as {
    success: boolean;
    deleted_space_id: string;
    moved_record_ids: string[];
    fallback_space_id: string;
    message: string;
  };
}

export async function importGlobalKnowledgeToPersonal(
  filename: string,
  knowledgeSpaceId?: string | null,
): Promise<{
  success: boolean;
  record: UserKnowledgeRecord;
  message: string;
}> {
  const params = new URLSearchParams();
  if (knowledgeSpaceId) {
    params.set("knowledge_space_id", knowledgeSpaceId);
  }
  const response = await fetch(
    `${USER_KNOWLEDGE_API_BASE}/import-from-global${params.toString() ? `?${params.toString()}` : ""}`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ filename }),
    },
  );
  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ message: "Failed to import document" }));
    throw new Error(
      error.message ?? error.detail ?? "Failed to import document",
    );
  }
  return (await response.json()) as {
    success: boolean;
    record: UserKnowledgeRecord;
    message: string;
  };
}

export async function createUserDerivedKnowledge(
  payload: CreateUserDerivedKnowledgeInput,
): Promise<{
  success: boolean;
  record: UserKnowledgeRecord;
  message: string;
}> {
  const response = await fetch(`${USER_KNOWLEDGE_API_BASE}/derived`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      title: payload.title,
      content: payload.content,
      source_kind: payload.sourceKind,
      origin_scope: payload.originScope,
      origin_doc_id: payload.originDocId,
      origin_filename: payload.originFilename,
      origin_anchor: payload.originAnchor,
      derived_from_id: payload.derivedFromId,
      hints: payload.hints,
      knowledge_space_id: payload.knowledgeSpaceId,
      folder_path: payload.folderPath ?? undefined,
    }),
  });
  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({
        message: "Failed to create personal knowledge document",
      }));
    throw new Error(
      error.message ??
        error.detail ??
        "Failed to create personal knowledge document",
    );
  }
  return (await response.json()) as {
    success: boolean;
    record: UserKnowledgeRecord;
    message: string;
  };
}

export async function deleteUserKnowledgeRecord(recordId: string): Promise<{
  success: boolean;
  message: string;
}> {
  const response = await fetch(
    `${USER_KNOWLEDGE_API_BASE}/${encodeURIComponent(recordId)}`,
    {
      method: "DELETE",
    },
  );
  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ message: "Failed to delete personal knowledge record" }));
    throw new Error(
      error.message ??
        error.detail ??
        "Failed to delete personal knowledge record",
    );
  }
  return (await response.json()) as { success: boolean; message: string };
}

export async function deleteUserKnowledgeRecordArtifactsOnly(recordId: string): Promise<{
  success: boolean;
  message: string;
}> {
  const response = await fetch(
    `${USER_KNOWLEDGE_API_BASE}/${encodeURIComponent(recordId)}/artifacts-only`,
    {
      method: "DELETE",
    },
  );
  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ message: "Failed to delete personal knowledge record artifacts" }));
    throw new Error(
      error.message ??
        error.detail ??
        "Failed to delete personal knowledge record artifacts",
    );
  }
  return (await response.json()) as { success: boolean; message: string };
}

export async function retryUserKnowledgeRecordIndexing(
  recordId: string,
): Promise<{
  success: boolean;
  message: string;
}> {
  const response = await fetch(
    `${USER_KNOWLEDGE_API_BASE}/${encodeURIComponent(recordId)}/reindex`,
    {
      method: "POST",
    },
  );
  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({
        message: "Failed to retry personal knowledge indexing",
      }));
    throw new Error(
      error.message ??
        error.detail ??
        "Failed to retry personal knowledge indexing",
    );
  }
  return (await response.json()) as { success: boolean; message: string };
}

export async function reparseUserKnowledgeRecord(recordId: string): Promise<{
  success: boolean;
  message: string;
}> {
  const response = await fetch(
    `${USER_KNOWLEDGE_API_BASE}/${encodeURIComponent(recordId)}/reparse`,
    {
      method: "POST",
    },
  );
  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ message: "Failed to reparse personal knowledge file" }));
    throw new Error(
      error.message ??
        error.detail ??
        "Failed to reparse personal knowledge file",
    );
  }
  return (await response.json()) as { success: boolean; message: string };
}

export async function moveUserKnowledgeRecord(
  recordId: string,
  payload: { knowledgeSpaceId?: string | null; folderPath?: string | null },
): Promise<{
  success: boolean;
  record: UserKnowledgeRecord;
  message: string;
}> {
  const response = await fetch(
    `${USER_KNOWLEDGE_API_BASE}/${encodeURIComponent(recordId)}/move`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        knowledge_space_id: payload.knowledgeSpaceId,
        folder_path: payload.folderPath,
      }),
    },
  );
  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ message: "Failed to move personal knowledge record" }));
    throw new Error(
      error.message ??
        error.detail ??
        "Failed to move personal knowledge record",
    );
  }
  return (await response.json()) as {
    success: boolean;
    record: UserKnowledgeRecord;
    message: string;
  };
}

export async function createUserKnowledgeFolder(
  path: string,
): Promise<{
  success: boolean;
  folders: string[];
  path?: string;
  message: string;
}> {
  const response = await fetch(`${USER_KNOWLEDGE_API_BASE}/folders`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ path }),
  });
  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ message: "Failed to create personal folder" }));
    throw new Error(
      error.message ?? error.detail ?? "Failed to create personal folder",
    );
  }
  return (await response.json()) as {
    success: boolean;
    folders: string[];
    path?: string;
    message: string;
  };
}

export async function renameUserKnowledgeFolder(
  path: string,
  newPath: string,
): Promise<{
  success: boolean;
  folders: string[];
  path?: string;
  message: string;
}> {
  const response = await fetch(`${USER_KNOWLEDGE_API_BASE}/folders`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ path, new_path: newPath }),
  });
  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ message: "Failed to rename personal folder" }));
    throw new Error(
      error.message ?? error.detail ?? "Failed to rename personal folder",
    );
  }
  return (await response.json()) as {
    success: boolean;
    folders: string[];
    path?: string;
    message: string;
  };
}

export async function deleteUserKnowledgeFolder(
  path: string,
): Promise<{
  success: boolean;
  folders: string[];
  deleted_path?: string;
  message: string;
}> {
  const params = new URLSearchParams({ path });
  const response = await fetch(
    `${USER_KNOWLEDGE_API_BASE}/folders?${params.toString()}`,
    {
      method: "DELETE",
    },
  );
  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ message: "Failed to delete personal folder" }));
    throw new Error(
      error.message ?? error.detail ?? "Failed to delete personal folder",
    );
  }
  return (await response.json()) as {
    success: boolean;
    folders: string[];
    deleted_path?: string;
    message: string;
  };
}

export async function getUserKnowledgeRecordContent(
  recordId: string,
): Promise<UserKnowledgeRecordContentResponse> {
  const response = await fetch(
    `${USER_KNOWLEDGE_API_BASE}/${encodeURIComponent(recordId)}/content`,
    {
      cache: "no-store",
    },
  );
  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ message: "Failed to load personal knowledge content" }));
    throw new Error(
      error.message ??
        error.detail ??
        "Failed to load personal knowledge content",
    );
  }
  return (await response.json()) as UserKnowledgeRecordContentResponse;
}

export async function updateUserKnowledgeRecordContent(
  recordId: string,
  payload: { title: string; content: string },
): Promise<UserKnowledgeRecordContentResponse> {
  const response = await fetch(
    `${USER_KNOWLEDGE_API_BASE}/${encodeURIComponent(recordId)}/content`,
    {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    },
  );
  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ message: "Failed to save personal knowledge content" }));
    throw new Error(
      error.message ??
        error.detail ??
        "Failed to save personal knowledge content",
    );
  }
  return (await response.json()) as UserKnowledgeRecordContentResponse;
}

export async function appendExcerptToUserNote(
  recordId: string,
  payload: AppendExcerptToUserNoteInput,
): Promise<{
  success: boolean;
  record: UserKnowledgeRecord;
  message: string;
}> {
  const response = await fetch(
    `${USER_KNOWLEDGE_API_BASE}/${encodeURIComponent(recordId)}/append-excerpt`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        excerpt_text: payload.excerptText,
        origin_scope: payload.originScope,
        origin_doc_id: payload.originDocId,
        origin_filename: payload.originFilename,
        origin_anchor: payload.originAnchor,
      }),
    },
  );
  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ message: "Failed to append excerpt to personal note" }));
    throw new Error(
      error.message ??
        error.detail ??
        "Failed to append excerpt to personal note",
    );
  }
  return (await response.json()) as {
    success: boolean;
    record: UserKnowledgeRecord;
    message: string;
  };
}
