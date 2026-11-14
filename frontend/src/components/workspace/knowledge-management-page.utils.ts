import {
  buildKnowledgePageImageURLForDocumentUrl,
  buildKnowledgeDocumentUrl,
  type KnowledgeFileInfo,
  type KnowledgeFolderSummary,
  type KnowledgeMetadataUpdateInput,
} from "@/core/knowledge/api";
import type { UserKnowledgeRecord } from "@/core/knowledge/user-api";

export type LanguageHint = "unknown" | "zh-Hans" | "zh-Hant" | "en" | "mixed";
export type LayoutHint = "unknown" | "horizontal" | "vertical" | "mixed";
export type DocumentTypeHint =
  | "unknown"
  | "book"
  | "archive"
  | "periodical"
  | "ancient_book";
export type KnowledgeType = "core" | "specialized" | "reference" | "unknown";

export type FolderTreeNode = {
  name: string;
  path: string;
  fileCount: number;
  children: FolderTreeNode[];
  source: "global" | "personal" | "mixed";
  deletable?: boolean;
};

export type ManagedKnowledgeFile = {
  rowId: string;
  source: "global" | "personal";
  scope: "global" | "user";
  docId?: string | null;
  filename: string;
  title: string;
  folderPath: string;
  folderDisplay: string;
  size: number;
  modified?: number;
  parseMethod?: string;
  parseStatus?: string;
  indexable?: boolean;
  documentUrl?: string | null;
  artifactUrl?: string | null;
  extension?: string | null;
  previewFilename?: string | null;
  previewArtifactUrl?: string | null;
  structuredFilename?: string | null;
  type?: string | null;
  categories?: string[];
  eras?: string[];
  regions?: string[];
  keywords?: string[];
  summary?: string | null;
  author?: string | null;
  publisher?: string | null;
  tags?: string[];
  hints?: Record<string, string>;
  knowledgeSpaceId?: string | null;
  knowledgeSpaceName?: string | null;
  userRecordId?: string | null;
};

export type UploadFormState = {
  files: File[];
  languageHint: LanguageHint;
  layoutHint: LayoutHint;
  documentTypeHint: DocumentTypeHint;
};

export type MetadataFormState = {
  type: KnowledgeType;
  folder: string;
  categories: string;
  eras: string;
  regions: string;
  keywords: string;
  summary: string;
  author: string;
  publisher: string;
  languageHint: LanguageHint;
  layoutHint: LayoutHint;
  documentTypeHint: DocumentTypeHint;
};

export const KNOWLEDGE_TYPES = new Set(["core", "specialized", "reference", "unknown"]);
const ACTIVE_PARSE_STATUSES = new Set(["queued", "queued_ocr", "parsing", "queued_embedding", "indexing"]);
const FAILED_PARSE_STATUSES = new Set(["failed", "index_failed"]);
const READER_READY_STATUSES = new Set(["indexed", "parsed"]);
const RETRYABLE_PARSE_STATUSES = new Set(["failed", "index_failed", "indexed", "parsed"]);
const REPARSEABLE_PARSE_STATUSES = new Set(["failed", "index_failed", "indexed", "parsed", "uploaded", "pending_parse"]);
const EDIT_DISABLED_STATUSES = new Set(["queued", "queued_ocr", "parsing"]);

export const knowledgeTypeOptions: Array<{ value: KnowledgeType; label: string }> = [
  { value: "unknown", label: "未分类" },
  { value: "core", label: "核心通用" },
  { value: "specialized", label: "专题支撑" },
  { value: "reference", label: "参考工具" },
];

export const languageOptions: Array<{ value: LanguageHint; label: string }> = [
  { value: "unknown", label: "自动判断" },
  { value: "zh-Hans", label: "简体中文" },
  { value: "zh-Hant", label: "繁体中文" },
  { value: "en", label: "英文" },
  { value: "mixed", label: "混合语言" },
];

export const layoutOptions: Array<{ value: LayoutHint; label: string }> = [
  { value: "unknown", label: "自动判断" },
  { value: "horizontal", label: "横排" },
  { value: "vertical", label: "竖排" },
  { value: "mixed", label: "混排" },
];

export const documentTypeOptions: Array<{ value: DocumentTypeHint; label: string }> = [
  { value: "unknown", label: "普通文档" },
  { value: "book", label: "书籍" },
  { value: "archive", label: "档案材料" },
  { value: "periodical", label: "期刊报纸" },
  { value: "ancient_book", label: "古籍旧式排印" },
];

export function createEmptyUploadFormState(): UploadFormState {
  return {
    files: [],
    languageHint: "unknown",
    layoutHint: "unknown",
    documentTypeHint: "unknown",
  };
}

export function createEmptyMetadataFormState(): MetadataFormState {
  return {
    type: "unknown",
    folder: "",
    categories: "",
    eras: "",
    regions: "",
    keywords: "",
    summary: "",
    author: "",
    publisher: "",
    languageHint: "unknown",
    layoutHint: "unknown",
    documentTypeHint: "unknown",
  };
}

export function buildFileTags(file: {
  tags?: string[];
  categories?: string[];
  eras?: string[];
  regions?: string[];
  keywords?: string[];
}) {
  const tags = file.tags?.length
    ? file.tags
    : [
        ...(file.categories ?? []),
        ...(file.eras ?? []),
        ...(file.regions ?? []),
        ...(file.keywords ?? []),
      ];

  return Array.from(
    new Set(
      tags.filter(
        (tag) => tag && !KNOWLEDGE_TYPES.has(String(tag).trim().toLowerCase()),
      ),
    ),
  );
}

export function normalizeFolderPath(value?: string | null) {
  const normalized = (value ?? "")
    .replace(/\\/g, "/")
    .split("/")
    .map((segment) => segment.trim())
    .filter(Boolean)
    .join("/");
  return normalized || "未分类";
}

export function getFileFolderPath(file: { folder?: string | null; tags?: string[] }) {
  const explicit = normalizeFolderPath(file.folder);
  if (explicit !== "未分类") {
    return explicit;
  }
  const firstTag = file.tags?.find((tag) => tag?.trim());
  return normalizeFolderPath(firstTag ?? null);
}

export function buildFolderTree(files: Array<{ folder?: string | null; tags?: string[] }>): FolderTreeNode[] {
  return buildScopedFolderTree({
    filePaths: files.map((file) => getFileFolderPath(file)),
    explicitPaths: [],
    prefix: "system:",
    source: "global",
  });
}

export function buildScopedFolderTree(params: {
  filePaths: string[];
  explicitPaths: string[];
  prefix: "system:" | "personal:";
  source: "global" | "personal";
}): FolderTreeNode[] {
  type MutableNode = { children: Map<string, MutableNode>; fileCount: number };

  const ensureNode = (map: Map<string, MutableNode>, key: string): MutableNode => {
    const existing = map.get(key);
    if (existing) {
      return existing;
    }
    const next: MutableNode = { children: new Map(), fileCount: 0 };
    map.set(key, next);
    return next;
  };

  const mutableRoot = new Map<string, MutableNode>();
  const normalizedFilePaths = params.filePaths.map((item) => normalizeFolderPath(item));
  const fileCountByPath = normalizedFilePaths.reduce<Map<string, number>>((map, path) => {
    map.set(path, (map.get(path) ?? 0) + 1);
    return map;
  }, new Map());
  const allPaths = Array.from(
    new Set([...normalizedFilePaths, ...params.explicitPaths.map((item) => normalizeFolderPath(item))]),
  );

  for (const folderPath of allPaths) {
    const segments = folderPath.split("/");
    let current = mutableRoot;
    const fileCount = fileCountByPath.get(folderPath) ?? 0;
    for (const segment of segments) {
      const node = ensureNode(current, segment);
      node.fileCount += fileCount;
      current = node.children;
    }
  }

  const toTree = (map: Map<string, MutableNode>, parentPath = ""): FolderTreeNode[] =>
    Array.from(map.entries())
      .sort(([left], [right]) => left.localeCompare(right, "zh-CN"))
      .map(([name, node]) => {
        const rawPath = parentPath ? `${parentPath}/${name}` : name;
        return {
          name,
          path: `${params.prefix}${rawPath}`,
          fileCount: node.fileCount,
          children: toTree(node.children, rawPath),
          source: params.source,
          deletable: true,
        };
      });

  return toTree(mutableRoot);
}

export function buildScopedFolderTreeFromSummaries(params: {
  folders: KnowledgeFolderSummary[];
  prefix: "system:" | "personal:";
  source: "global" | "personal";
}): FolderTreeNode[] {
  const nodeByPath = new Map<string, FolderTreeNode>();
  for (const folder of params.folders) {
    nodeByPath.set(folder.path, {
      name: folder.name,
      path: `${params.prefix}${folder.path}`,
      fileCount: folder.file_count,
      children: [],
      source: params.source,
      deletable: true,
    });
  }

  const roots: FolderTreeNode[] = [];
  for (const folder of params.folders) {
    const node = nodeByPath.get(folder.path);
    if (!node) {
      continue;
    }
    const parentPath = folder.parent_path ?? null;
    const parent = parentPath ? nodeByPath.get(parentPath) : null;
    if (parent) {
      parent.children.push(node);
    } else {
      roots.push(node);
    }
  }

  const sortNodes = (nodes: FolderTreeNode[]) => {
    nodes.sort((left, right) => left.name.localeCompare(right.name, "zh-CN"));
    for (const node of nodes) {
      sortNodes(node.children);
    }
  };
  sortNodes(roots);
  return roots;
}

export function relabelSystemFolderTree(nodes: FolderTreeNode[]): FolderTreeNode[] {
  return nodes;
}

export function buildPersonalFolderTree(
  files: ManagedKnowledgeFile[],
  folders: string[],
): FolderTreeNode[] {
  return buildScopedFolderTree({
    filePaths: files.filter((file) => file.source === "personal").map((file) => file.folderDisplay),
    explicitPaths: folders,
    prefix: "personal:",
    source: "personal",
  });
}

export function isFileInFolderScope(file: ManagedKnowledgeFile, selectedFolderPath: string) {
  if (selectedFolderPath === "all") {
    return true;
  }
  if (selectedFolderPath === "personal-root") {
    return file.source === "personal";
  }
  if (selectedFolderPath === "system-root") {
    return file.source === "global";
  }
  if (selectedFolderPath.startsWith("personal:")) {
    return (
      file.folderPath === selectedFolderPath ||
      file.folderPath.startsWith(`${selectedFolderPath}/`)
    );
  }
  return (
    file.folderPath === selectedFolderPath ||
    file.folderPath.startsWith(`${selectedFolderPath}/`)
  );
}

export function isFileDirectlyInFolder(file: ManagedKnowledgeFile, selectedFolderPath: string) {
  if (
    selectedFolderPath === "all" ||
    selectedFolderPath === "personal-root"
  ) {
    return false;
  }
  if (selectedFolderPath === "system-root") {
    return file.source === "global";
  }
  return file.folderPath === selectedFolderPath;
}

export function knowledgeTypeLabel(value?: string | null) {
  switch ((value ?? "").toLowerCase()) {
    case "core":
      return "核心通用";
    case "specialized":
      return "专题支撑";
    case "reference":
      return "参考工具";
    default:
      return "未分类";
  }
}

export function statusLabel(status?: string) {
  switch (status) {
    case "queued":
    case "queued_ocr":
      return "排队中";
    case "queued_embedding":
      return "待入库";
    case "parsing":
      return "解析中";
    case "indexing":
      return "入库中";
    case "pending_parse":
      return "待进一步解析";
    case "indexed":
      return "已入库";
    case "parsed":
      return "已解析";
    case "index_failed":
      return "入库失败";
    case "failed":
      return "解析失败";
    case "uploaded":
      return "仅上传";
    default:
      return "未知";
  }
}

export function statusVariant(
  status?: string,
): "default" | "secondary" | "destructive" | "outline" {
  switch (status) {
    case "indexed":
      return "default";
    case "queued":
    case "queued_ocr":
    case "queued_embedding":
    case "parsing":
    case "indexing":
    case "parsed":
      return "secondary";
    case "pending_parse":
      return "outline";
    case "index_failed":
    case "failed":
      return "destructive";
    default:
      return "outline";
  }
}

export function formatBytes(size: number) {
  if (size < 1024) {
    return `${size} B`;
  }
  if (size < 1024 * 1024) {
    return `${(size / 1024).toFixed(1)} KB`;
  }
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

export function splitTagInput(value: string) {
  return value
    .split(/[,\n，]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

export function joinTagInput(values?: string[]) {
  return (values ?? []).join(", ");
}

export function formatCompactTime(value?: number) {
  if (!value) return "未知";
  const normalized = value < 1_000_000_000_000 ? value * 1000 : value;
  return new Date(normalized).toLocaleString("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function languageLabel(value?: string) {
  switch (value) {
    case "zh-Hans":
      return "简体中文";
    case "zh-Hant":
      return "繁体中文";
    case "en":
      return "英文";
    case "mixed":
      return "混合语言";
    default:
      return "自动判断";
  }
}

export function layoutLabel(value?: string) {
  switch (value) {
    case "horizontal":
      return "横排";
    case "vertical":
      return "竖排";
    case "mixed":
      return "混排";
    default:
      return "自动判断";
  }
}

export function documentTypeLabel(value?: string) {
  switch (value) {
    case "book":
      return "书籍";
    case "archive":
      return "档案材料";
    case "periodical":
      return "期刊报纸";
    case "ancient_book":
      return "古籍旧式排印";
    default:
      return "普通文档";
  }
}

export function parseMethodLabel(value?: string) {
  switch (value) {
    case "ocr_pdf_mineru_grpc":
    case "ocr_pdf_local":
    case "paddleocr_pdf":
      return "OCR 解析";
    case "static":
      return "直接导入";
    default:
      return "自动解析";
  }
}

export function fileStatusHint(file: {
  parse_status?: string;
  parseStatus?: string;
  parse_method?: string;
  parseMethod?: string;
  indexable?: boolean;
}) {
  const status = file.parseStatus ?? file.parse_status;
  const method = file.parseMethod ?? file.parse_method;
  switch (status) {
    case "queued":
      return "等待开始处理";
    case "queued_ocr":
      return "已上传，等待解析";
    case "queued_embedding":
      return "解析完成，等待写入知识库";
    case "parsing":
      return "正在提取文本";
    case "indexing":
      return "正在写入知识库";
    case "pending_parse":
      return "当前文件需要进一步处理后才能入库";
    case "index_failed":
      return "入库失败，请稍后重试";
    case "failed":
      return method?.includes("ocr")
        ? "解析失败，请检查解析服务后重试"
        : "处理失败，请稍后重试";
    case "uploaded":
      return file.indexable === false ? "已上传，暂不支持自动入库" : "已上传";
    default:
      return null;
  }
}

export function retryActionLabel(status?: string) {
  switch (status) {
    case "failed":
      return "重新解析";
    case "index_failed":
      return "重新入库";
    case "indexed":
      return "重新入库";
    default:
      return "重试";
  }
}

export function buildManagedFileReaderHref(file: ManagedKnowledgeFile) {
  const documentUrl =
    file.documentUrl ??
    file.artifactUrl ??
    (file.scope === "user"
      ? buildKnowledgeDocumentUrl("user", file.filename)
      : buildKnowledgeDocumentUrl("global", file.filename));

  if (!documentUrl) {
    return null;
  }

  const params = new URLSearchParams({
    mode: "reader",
    filename: file.filename,
    scope: file.scope,
    document_url: documentUrl,
    origin_title: file.title,
    origin_filename: file.filename,
    back_href: "/workspace/knowledge-manage",
    back_label: "知识库管理",
  });

  if (file.knowledgeSpaceId) {
    params.set("knowledge_space_id", file.knowledgeSpaceId);
  }

  return `/workspace/knowledge/view?${params.toString()}`;
}

export function buildKnowledgeSummary(
  globalFiles: KnowledgeFileInfo[],
  personalRecords: UserKnowledgeRecord[],
) {
  const personalUploads = personalRecords.filter((record) =>
    ["upload", "import_ref"].includes(record.source_kind),
  );
  const activeCount =
    globalFiles.filter((file) => ACTIVE_PARSE_STATUSES.has(file.parse_status ?? "")).length +
    personalUploads.filter((record) => ACTIVE_PARSE_STATUSES.has(record.parse_status ?? "")).length;
  const indexedCount =
    globalFiles.filter((file) => file.parse_status === "indexed").length +
    personalUploads.filter((record) => record.parse_status === "indexed").length;
  const failedCount =
    globalFiles.filter((file) => FAILED_PARSE_STATUSES.has(file.parse_status ?? "")).length +
    personalUploads.filter((record) => FAILED_PARSE_STATUSES.has(record.parse_status ?? "")).length;
  const total = globalFiles.length + personalUploads.length;

  return {
    total,
    indexed: indexedCount,
    failed: failedCount,
    active: activeCount,
    progress: total > 0 ? Math.round((indexedCount / total) * 100) : 0,
  };
}

export function sortGlobalKnowledgeFiles(files: KnowledgeFileInfo[]) {
  return [...files].sort((left, right) => {
    const timeDelta = (right.modified ?? 0) - (left.modified ?? 0);
    if (timeDelta !== 0) {
      return timeDelta;
    }
    return left.filename.localeCompare(right.filename, "zh-CN");
  });
}

export function buildManagedFiles(params: {
  globalFiles: KnowledgeFileInfo[];
  personalRecords: UserKnowledgeRecord[];
}): ManagedKnowledgeFile[] {
  const globalRows = params.globalFiles.map<ManagedKnowledgeFile>((file) => ({
    rowId: `global:${file.filename}`,
    source: "global",
    scope: "global",
    docId: file.doc_id ?? null,
    filename: file.filename,
    title: file.filename.replace(/\.[^.]+$/, ""),
    folderPath: `system:${getFileFolderPath(file)}`,
    folderDisplay: getFileFolderPath(file),
    size: file.size,
    modified: file.modified,
    parseMethod: file.parse_method,
    parseStatus: file.parse_status,
    indexable: file.indexable,
    documentUrl: buildKnowledgeDocumentUrl("global", file.filename),
    artifactUrl: file.artifact_url,
    extension: file.extension,
    previewFilename: file.preview_filename,
    previewArtifactUrl: file.preview_artifact_url,
    structuredFilename: file.structured_filename,
    type: file.type,
    categories: file.categories,
    eras: file.eras,
    regions: file.regions,
    keywords: file.keywords,
    summary: file.summary,
    author: file.author,
    publisher: file.publisher,
    tags: file.tags,
    hints: file.hints,
  }));

  const personalRows = params.personalRecords
    .filter((record) => ["upload", "import_ref"].includes(record.source_kind))
    .map<ManagedKnowledgeFile>((record) => {
      const sourceFilename = record.filename ?? record.origin_filename ?? `${record.id}.md`;
      const documentUrl =
        record.artifact_url ??
        (record.origin_scope === "global" && record.origin_filename
          ? buildKnowledgeDocumentUrl("global", record.origin_filename)
          : buildKnowledgeDocumentUrl("user", sourceFilename));
      const previewArtifactUrl = record.preview_artifact_url ?? documentUrl;

      return {
        rowId: `personal:${record.id}`,
        source: "personal",
        scope: "user",
        docId: record.id,
        filename: sourceFilename,
        title: record.display_title ?? record.title ?? sourceFilename.replace(/\.[^.]+$/, ""),
        folderPath: `personal:${normalizeFolderPath(record.folder_path)}`,
        folderDisplay: normalizeFolderPath(record.folder_path),
        size: record.size,
        modified: record.updated_at ? new Date(record.updated_at).getTime() : undefined,
        parseMethod: record.parse_method ?? undefined,
        parseStatus: record.parse_status ?? undefined,
        indexable: record.indexable,
        documentUrl,
        artifactUrl: documentUrl,
        extension: record.extension ?? undefined,
        previewFilename: record.preview_filename ?? undefined,
        previewArtifactUrl,
        structuredFilename: record.structured_filename ?? undefined,
        hints: record.hints ?? undefined,
        knowledgeSpaceId: record.knowledge_space_id ?? undefined,
        knowledgeSpaceName: record.knowledge_space_name ?? undefined,
        userRecordId: record.id,
      };
    });

  return [...personalRows, ...globalRows];
}

export function filterManagedFiles(params: {
  files: ManagedKnowledgeFile[];
  searchQuery: string;
}) {
  const keyword = params.searchQuery.trim().toLowerCase();

  return params.files.filter((file) => {
    if (!keyword) {
      return true;
    }

    const haystack = [
      file.title,
      file.filename,
      file.folderDisplay,
      file.type,
      ...(file.tags ?? []),
      ...(file.categories ?? []),
      ...(file.eras ?? []),
      ...(file.regions ?? []),
      ...(file.keywords ?? []),
      file.summary,
      file.parseMethod,
      file.extension,
      file.parseStatus,
      file.hints?.document_type_hint,
      file.hints?.language_hint,
      file.hints?.layout_hint,
      file.previewFilename,
      file.structuredFilename,
      file.knowledgeSpaceName,
      file.source === "global" ? "系统" : "个人",
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();

    return haystack.includes(keyword);
  });
}

export function flattenFolderPaths(nodes: FolderTreeNode[]) {
  const paths: string[] = [];
  const visit = (items: FolderTreeNode[]) => {
    for (const node of items) {
      paths.push(node.path);
      visit(node.children);
    }
  };
  visit(nodes);
  return paths;
}

export function findFolderNode(nodes: FolderTreeNode[], targetPath: string): FolderTreeNode | null {
  for (const node of nodes) {
    if (node.path === targetPath) {
      return node;
    }
    const nested = findFolderNode(node.children, targetPath);
    if (nested) {
      return nested;
    }
  }
  return null;
}

export function buildFolderBreadcrumbs(nodes: FolderTreeNode[], targetPath: string) {
  if (targetPath === "all") {
    return [];
  }

  const path: Array<{ name: string; path: string }> = [];
  const visit = (items: FolderTreeNode[]): boolean => {
    for (const node of items) {
      path.push({ name: node.name, path: node.path });
      if (node.path === targetPath) {
        return true;
      }
      if (visit(node.children)) {
        return true;
      }
      path.pop();
    }
    return false;
  };

  visit(nodes);
  return path;
}

/**
 * Returns the sequence of folder lists for each level along the target path.
 * Used for cascading navigation rows.
 */
export function getCascadingLevels(
  rootNodes: FolderTreeNode[],
  targetPath: string,
): FolderTreeNode[][] {
  const levels: FolderTreeNode[][] = [rootNodes];
  
  if (targetPath === "all" || targetPath === "personal-root" || targetPath === "system-root") {
    return levels;
  }

  const findPath = (nodes: FolderTreeNode[]): boolean => {
    for (const node of nodes) {
      if (node.path === targetPath) {
        if (node.children.length > 0) {
          levels.push(node.children);
        }
        return true;
      }
      
      const isSubPath = targetPath === node.path || targetPath.startsWith(`${node.path}/`);
      if (isSubPath) {
        if (node.children.length > 0) {
          levels.push(node.children);
          if (findPath(node.children)) {
            return true;
          }
        }
        return true;
      }
    }
    return false;
  };

  findPath(rootNodes);
  return levels;
}

export function isSelectableForChat(file: ManagedKnowledgeFile) {
  return Boolean(file.docId) && (file.parseStatus === "indexed" || file.parseStatus === "parsed");
}

export function canOpenManagedFile(file: ManagedKnowledgeFile, readerHref: string | null) {
  return Boolean(readerHref) && Boolean(file.documentUrl) && READER_READY_STATUSES.has(file.parseStatus ?? "");
}

export function canRetryManagedFile(file: ManagedKnowledgeFile) {
  return (
    (file.source === "global" || file.source === "personal") &&
    file.indexable &&
    RETRYABLE_PARSE_STATUSES.has(file.parseStatus ?? "")
  );
}

export function canReparseManagedFile(file: ManagedKnowledgeFile) {
  return (
    (file.source === "global" || file.source === "personal") &&
    file.indexable &&
    REPARSEABLE_PARSE_STATUSES.has(file.parseStatus ?? "")
  );
}

export function canEditManagedMetadata(file: ManagedKnowledgeFile) {
  const hasEditableMetadataSource =
    (file.source === "global" && Boolean(file.structuredFilename)) ||
    [".md", ".markdown", ".txt"].includes((file.extension ?? "").toLowerCase());
  return hasEditableMetadataSource && !EDIT_DISABLED_STATUSES.has(file.parseStatus ?? "");
}

export function getManagedFileCoverImageUrl(file: ManagedKnowledgeFile) {
  const extension = (file.extension ?? "").toLowerCase();
  if (extension !== ".pdf" || !file.documentUrl) {
    return null;
  }

  try {
    return buildKnowledgePageImageURLForDocumentUrl(file.documentUrl, 1);
  } catch {
    return null;
  }
}

export function buildSelectedMaterialsPayload(files: ManagedKnowledgeFile[]) {
  return files
    .filter((file) => isSelectableForChat(file))
    .map((file) => ({
      doc_id: String(file.docId),
      title: file.title,
      filename: file.filename,
      scope: file.scope,
    }));
}

export function buildMetadataFormState(metadata: {
  type?: string | null;
  folder?: string | null;
  categories?: string[];
  eras?: string[];
  regions?: string[];
  keywords?: string[];
  summary?: string | null;
  author?: string | null;
  publisher?: string | null;
  hints?: Record<string, string>;
  language_hint?: string | null;
  layout_hint?: string | null;
  document_type_hint?: string | null;
}): MetadataFormState {
  const languageHint = metadata.hints?.language_hint ?? metadata.language_hint;
  const layoutHint = metadata.hints?.layout_hint ?? metadata.layout_hint;
  const documentTypeHint =
    metadata.hints?.document_type_hint ?? metadata.document_type_hint;

  return {
    type: KNOWLEDGE_TYPES.has(String(metadata.type ?? "").toLowerCase())
      ? (String(metadata.type).toLowerCase() as KnowledgeType)
      : "unknown",
    folder: metadata.folder ?? "",
    categories: joinTagInput(metadata.categories),
    eras: joinTagInput(metadata.eras),
    regions: joinTagInput(metadata.regions),
    keywords: joinTagInput(metadata.keywords),
    summary: metadata.summary ?? "",
    author: metadata.author ?? "",
    publisher: metadata.publisher ?? "",
    languageHint: (languageHint as LanguageHint) ?? "unknown",
    layoutHint: (layoutHint as LayoutHint) ?? "unknown",
    documentTypeHint: (documentTypeHint as DocumentTypeHint) ?? "unknown",
  };
}

export function buildMetadataPayload(form: MetadataFormState): KnowledgeMetadataUpdateInput {
  return {
    type: form.type === "unknown" ? null : form.type,
    folder: form.folder.trim() || null,
    categories: splitTagInput(form.categories),
    eras: splitTagInput(form.eras),
    regions: splitTagInput(form.regions),
    keywords: splitTagInput(form.keywords),
    summary: form.summary.trim() || null,
    author: form.author.trim() || null,
    publisher: form.publisher.trim() || null,
    language_hint: form.languageHint === "unknown" ? null : form.languageHint,
    layout_hint: form.layoutHint === "unknown" ? null : form.layoutHint,
    document_type_hint:
      form.documentTypeHint === "unknown" ? null : form.documentTypeHint,
  };
}

export function getFolderDisplayName(name: string) {
  if (name === "系统") {
    return "系统知识库";
  }
  if (name === "个人") {
    return "个人空间";
  }
  return name;
}

export function getCoverTone(title: string) {
  const tones = [
    "from-stone-900 via-stone-800 to-stone-700",      // 焦墨
    "from-primary-950 via-primary-900 to-primary/80", // 朱砂
    "from-amber-950 via-amber-900 to-stone-800",      // 赭石
    "from-slate-950 via-slate-900 to-slate-800",      // 黛蓝/墨青
    "from-zinc-900 via-stone-800 to-slate-700",       // 苍灰
  ];
  const charCode = title.charCodeAt(0) || 0;
  return tones[Math.abs(charCode) % tones.length] ?? tones[0];
}
