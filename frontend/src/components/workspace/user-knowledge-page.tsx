"use client";

import { Placeholder } from "@tiptap/extension-placeholder";
import {
  EditorContent,
  Node,
  NodeViewWrapper,
  ReactNodeViewRenderer,
  mergeAttributes,
  useEditor,
  type JSONContent,
  type ReactNodeViewProps,
} from "@tiptap/react";
import { StarterKit } from "@tiptap/starter-kit";
import {
  ChevronDownIcon,
  ChevronRightIcon,
  ExternalLinkIcon,
  FileTextIcon,
  FolderIcon,
  Loader2Icon,
  FolderPlusIcon,
  PlusIcon,
  Trash2Icon,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from "@/components/ui/resizable";
import { ScrollArea } from "@/components/ui/scroll-area";
import { CreateFolderDialog } from "@/components/workspace/knowledge-management-page.dialogs";
import {
  getFolderDisplayName,
  normalizeFolderPath,
} from "@/components/workspace/knowledge-management-page.utils";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { buildKnowledgeDocumentUrl } from "@/core/knowledge/api";
import type { UserKnowledgeRecord } from "@/core/knowledge/user-api";
import {
  useCreateUserDerivedKnowledge,
  useCreateUserKnowledgeFolder,
  useDeleteUserKnowledgeRecord,
  useMoveUserKnowledgeRecord,
  useRenameUserKnowledgeFolder,
  useUpdateUserKnowledgeRecordContent,
  useUserKnowledgeRecordContent,
  useUserKnowledgeRecords,
  useUserKnowledgeSpaces,
} from "@/core/knowledge/user-hooks";
import { env } from "@/env";
import { cn } from "@/lib/utils";

function formatTime(value?: string | null) {
  if (!value) {
    return "未知";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "未知";
  }
  return date.toLocaleString("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function stripFileExtension(value: string) {
  return value.replace(/\.[^.]+$/, "");
}

function getReadableRecordTitle(record: UserKnowledgeRecord) {
  const displayTitle = record.display_title?.trim();
  const title = record.title?.trim();
  const readableTitle =
    displayTitle && displayTitle.length > 0 ? displayTitle : title;
  if (readableTitle) {
    return readableTitle;
  }
  const sourceName = record.origin_filename ?? record.filename;
  if (sourceName) {
    return stripFileExtension(sourceName);
  }
  return "未命名";
}

function isNoteRecord(record: UserKnowledgeRecord) {
  return !["upload", "import_ref"].includes(record.source_kind);
}

function getOriginAnchorNumber(
  record: UserKnowledgeRecord,
  key: "page_no" | "pdf_page_no" | "paragraph_no",
) {
  const value = record.origin_anchor?.[key];
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string") {
    const parsed = parseInt(value, 10);
    return Number.isNaN(parsed) ? null : parsed;
  }
  return null;
}

function buildOriginalJumpHref(
  record: UserKnowledgeRecord,
  recordId: string,
  knowledgeSpaceId?: string | null,
) {
  if (!record.origin_filename) {
    return null;
  }
  if (record.origin_scope !== "global" && record.origin_scope !== "user") {
    return null;
  }

  const pdfPageNo = getOriginAnchorNumber(record, "pdf_page_no");
  const pageNo = getOriginAnchorNumber(record, "page_no");
  const initialPage = pdfPageNo ?? pageNo;
  if (!initialPage) {
    return null;
  }

  const documentUrl = buildKnowledgeDocumentUrl(
    record.origin_scope,
    record.origin_filename,
  );
  const params = new URLSearchParams({
    mode: "reader",
    filename: record.origin_filename,
    scope: record.origin_scope,
    document_url: documentUrl,
    origin_filename: record.origin_filename,
    pdf_page_no: String(initialPage),
    back_href: `/workspace/notes?space=${encodeURIComponent(knowledgeSpaceId ?? record.knowledge_space_id ?? "")}&record=${encodeURIComponent(recordId)}`,
    back_label: "笔记",
  });
  return `/workspace/knowledge/view?${params.toString()}`;
}

type ParsedExcerpt = {
  filename: string;
  scope?: string;
  location?: string;
  text: string;
};

type NoteSegment =
  | { kind: "text"; text: string }
  | { kind: "excerpt"; excerpt: ParsedExcerpt };

const EXCERPT_HEADER = "## 原文摘录";

function parseNoteSegments(content: string): NoteSegment[] {
  const normalized = content.replace(/\r\n/g, "\n");
  const lines = normalized.split("\n");
  const segments: NoteSegment[] = [];
  let textBuffer: string[] = [];
  let i = 0;

  const flushText = () => {
    if (textBuffer.length === 0) {
      return;
    }
    const text = textBuffer.join("\n").replace(/^\n+/, "").replace(/\n+$/, "");
    segments.push({ kind: "text", text });
    textBuffer = [];
  };

  const lineAt = (idx: number): string => lines[idx] ?? "";

  while (i < lines.length) {
    if (lineAt(i).trim() === EXCERPT_HEADER) {
      flushText();
      i++;
      while (i < lines.length && lineAt(i).trim() === "") i++;

      let filename = "";
      if (i < lines.length && lineAt(i).startsWith("来源：")) {
        filename = lineAt(i).slice("来源：".length).trim();
        i++;
      }

      let scope: string | undefined;
      if (i < lines.length && lineAt(i).startsWith("范围：")) {
        scope = lineAt(i).slice("范围：".length).trim();
        i++;
      }

      let location: string | undefined;
      if (i < lines.length && lineAt(i).startsWith("定位：")) {
        location = lineAt(i).slice("定位：".length).trim();
        i++;
      }

      while (i < lines.length && lineAt(i).trim() === "") i++;

      const quoteLines: string[] = [];
      while (i < lines.length && lineAt(i).startsWith(">")) {
        const line = lineAt(i);
        if (line === ">") {
          quoteLines.push("");
        } else if (line.startsWith("> ")) {
          quoteLines.push(line.slice(2));
        } else {
          quoteLines.push(line.slice(1).replace(/^\s/, ""));
        }
        i++;
      }

      segments.push({
        kind: "excerpt",
        excerpt: {
          filename,
          scope,
          location,
          text: quoteLines.join("\n").replace(/\n+$/, ""),
        },
      });
    } else {
      textBuffer.push(lineAt(i));
      i++;
    }
  }

  flushText();

  const firstSeg = segments[0];
  if (!firstSeg) {
    segments.push({ kind: "text", text: "" });
  } else if (firstSeg.kind !== "text") {
    segments.unshift({ kind: "text", text: "" });
  }

  return segments;
}


function sortRecords(records: UserKnowledgeRecord[]) {
  return [...records].sort((left, right) => {
    const leftTime = new Date(
      left.updated_at ?? left.created_at ?? 0,
    ).getTime();
    const rightTime = new Date(
      right.updated_at ?? right.created_at ?? 0,
    ).getTime();
    return rightTime - leftTime;
  });
}

function SidebarFolderNode({
  node,
  selectedFolderPath,
  selectedRecordId,
  expandedFolderPaths,
  onToggleFolder,
  onSelectFolder,
  onSelectRecord,
  onCreateNoteInFolder,
  onCreateFolderInFolder,
  registerRecordRef,
  dropTargetFolderPath,
  onRecordDragStart,
  onFolderDragStartNode,
  onDragEnd,
  onFolderDragEnter,
  onFolderDragLeave,
  onFolderDrop,
  depth = 0,
}: {
  node: NoteTreeFolderNode;
  selectedFolderPath: string;
  selectedRecordId: string | null;
  expandedFolderPaths: string[];
  onToggleFolder: (path: string) => void;
  onSelectFolder: (path: string) => void;
  onSelectRecord: (record: UserKnowledgeRecord) => void;
  onCreateNoteInFolder: (path: string) => void;
  onCreateFolderInFolder: (path: string) => void;
  registerRecordRef: (
    recordId: string,
  ) => (element: HTMLButtonElement | null) => void;
  dropTargetFolderPath: string | null;
  onRecordDragStart: (recordId: string) => void;
  onFolderDragStartNode: (path: string) => void;
  onDragEnd: () => void;
  onFolderDragEnter: (path: string) => void;
  onFolderDragLeave: () => void;
  onFolderDrop: (path: string) => void;
  depth?: number;
}) {
  const isSelected = selectedFolderPath === node.path;
  const isExpanded = expandedFolderPaths.includes(node.path);
  const hasChildren = node.children.length > 0 || node.records.length > 0;
  const isDropTarget = dropTargetFolderPath === node.path;

  return (
    <div className="mb-0.5">
      <div
        data-sidebar-folder-row
        className={cn(
          "group flex items-center rounded-md pr-2 transition-colors",
          isSelected
            ? "bg-primary/10 text-primary font-medium"
            : "text-stone-600 hover:bg-stone-200/50 hover:text-stone-900",
          isDropTarget && "ring-primary/40 bg-primary/10 ring-2",
        )}
        style={{ paddingLeft: `${8 + depth * 14}px` }}
        onDragOver={(e) => {
          e.preventDefault();
          e.dataTransfer.dropEffect = "move";
        }}
        onDragEnter={(e) => {
          e.preventDefault();
          onFolderDragEnter(node.path);
        }}
        onDragLeave={(e) => {
          if (!e.currentTarget.contains(e.relatedTarget as HTMLElement | null)) {
            onFolderDragLeave();
          }
        }}
        onDrop={(e) => {
          e.preventDefault();
          e.stopPropagation();
          onFolderDrop(node.path);
        }}
      >
        <button
          type="button"
          onClick={(event) => {
            event.stopPropagation();
            if (hasChildren) {
              onToggleFolder(node.path);
            }
          }}
          className={cn(
            "flex size-7 shrink-0 items-center justify-center rounded-sm transition-colors",
            isSelected ? "hover:bg-primary/20" : "hover:bg-stone-300/50",
            !hasChildren && "pointer-events-none opacity-0"
          )}
          aria-label={isExpanded ? "折叠文件夹" : "展开文件夹"}
        >
          {isExpanded ? (
            <ChevronDownIcon className="size-3.5 opacity-70" />
          ) : (
            <ChevronRightIcon className="size-3.5 opacity-70" />
          )}
        </button>
        <button
          type="button"
          draggable
          onClick={() => onSelectFolder(node.path)}
          onDragStart={(e) => {
            e.dataTransfer.effectAllowed = "move";
            onFolderDragStartNode(node.path);
          }}
          onDragEnd={onDragEnd}
          className="flex min-w-0 flex-1 items-center gap-2 py-1.5 pl-0.5 pr-2 text-left text-sm"
        >
          <FolderIcon className={cn("size-4 shrink-0", isSelected ? "opacity-90" : "opacity-50")} />
          <span className="min-w-0 flex-1 truncate tracking-wide">
            {getFolderDisplayName(node.name)}
          </span>
          <span className="text-[10px] font-medium opacity-40">{node.fileCount}</span>
        </button>
        <div className="mr-1 flex items-center gap-0.5 opacity-0 transition-opacity group-hover:opacity-100">
          <button
            type="button"
            onClick={(event) => {
              event.stopPropagation();
              onCreateNoteInFolder(node.path);
            }}
            className={cn(
              "flex size-6 items-center justify-center rounded-sm",
              isSelected ? "hover:bg-primary/20" : "hover:bg-stone-300/50"
            )}
            title="在此文件夹新建笔记"
          >
            <PlusIcon className="size-3.5 opacity-70" />
          </button>
          <button
            type="button"
            onClick={(event) => {
              event.stopPropagation();
              onCreateFolderInFolder(node.path);
            }}
            className={cn(
              "flex size-6 items-center justify-center rounded-sm",
              isSelected ? "hover:bg-primary/20" : "hover:bg-stone-300/50"
            )}
            title="在此文件夹新建子文件夹"
          >
            <FolderPlusIcon className="size-3.5 opacity-70" />
          </button>
        </div>
      </div>
      {hasChildren && isExpanded ? (
        <div className="mt-0.5 space-y-0.5">
          {node.children.map((child) => (
            <SidebarFolderNode
              key={child.path}
              node={child}
              selectedFolderPath={selectedFolderPath}
              selectedRecordId={selectedRecordId}
              expandedFolderPaths={expandedFolderPaths}
              onToggleFolder={onToggleFolder}
              onSelectFolder={onSelectFolder}
              onSelectRecord={onSelectRecord}
              onCreateNoteInFolder={onCreateNoteInFolder}
              onCreateFolderInFolder={onCreateFolderInFolder}
              registerRecordRef={registerRecordRef}
              dropTargetFolderPath={dropTargetFolderPath}
              onRecordDragStart={onRecordDragStart}
              onFolderDragStartNode={onFolderDragStartNode}
              onDragEnd={onDragEnd}
              onFolderDragEnter={onFolderDragEnter}
              onFolderDragLeave={onFolderDragLeave}
              onFolderDrop={onFolderDrop}
              depth={depth + 1}
            />
          ))}
          {node.records.map((record) => {
            const isActive = selectedRecordId === record.id;
            return (
              <button
                key={record.id}
                ref={registerRecordRef(record.id)}
                type="button"
                draggable
                onClick={() => onSelectRecord(record)}
                onDragStart={(e) => {
                  e.dataTransfer.effectAllowed = "move";
                  onRecordDragStart(record.id);
                }}
                onDragEnd={onDragEnd}
                className={cn(
                  "my-0.5 flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-[13px] transition-colors",
                  isActive
                    ? "bg-primary text-primary-foreground shadow-sm"
                    : "text-stone-600 hover:bg-stone-200/50 hover:text-stone-900",
                )}
                style={{ paddingLeft: `${36 + depth * 14}px` }}
              >
                <FileTextIcon className={cn("size-3.5 shrink-0", isActive ? "opacity-90" : "opacity-40")} />
                <span className="min-w-0 truncate tracking-wide">
                  {getReadableRecordTitle(record)}
                </span>
              </button>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}

type NoteTreeFolderNode = {
  name: string;
  path: string;
  fileCount: number;
  children: NoteTreeFolderNode[];
  records: UserKnowledgeRecord[];
};

function buildNoteFolderTree(
  records: UserKnowledgeRecord[],
  folderPaths: string[],
): NoteTreeFolderNode[] {
  type MutableNode = {
    name: string;
    path: string;
    children: Map<string, MutableNode>;
    records: UserKnowledgeRecord[];
  };

  const root = new Map<string, MutableNode>();

  const ensureNode = (
    map: Map<string, MutableNode>,
    rawPath: string,
    name: string,
  ) => {
    const existing = map.get(rawPath);
    if (existing) {
      return existing;
    }
    const next: MutableNode = {
      name,
      path: rawPath,
      children: new Map(),
      records: [],
    };
    map.set(rawPath, next);
    return next;
  };

  const allFolderPaths = Array.from(
    new Set([
      ...folderPaths.map((folderPath) => normalizeFolderPath(folderPath)),
      ...records.map((record) => normalizeFolderPath(record.folder_path)),
    ]),
  );

  for (const folderPath of allFolderPaths) {
    const segments = folderPath.split("/");
    let current = root;
    let currentPath = "";
    for (const segment of segments) {
      currentPath = currentPath ? `${currentPath}/${segment}` : segment;
      const node = ensureNode(current, `personal:${currentPath}`, segment);
      current = node.children;
    }
  }

  for (const record of records) {
    const folderPath = normalizeFolderPath(record.folder_path);
    const segments = folderPath.split("/");
    let current = root;
    let currentNode: MutableNode | null = null;
    let currentPath = "";
    for (const segment of segments) {
      currentPath = currentPath ? `${currentPath}/${segment}` : segment;
      currentNode = ensureNode(current, `personal:${currentPath}`, segment);
      current = currentNode.children;
    }
    currentNode?.records.push(record);
  }

  const toTree = (map: Map<string, MutableNode>): NoteTreeFolderNode[] =>
    Array.from(map.values())
      .sort((left, right) => left.name.localeCompare(right.name, "zh-CN"))
      .map((node) => {
        const children = toTree(node.children);
        const sortedRecords = sortRecords(node.records);
        return {
          name: node.name,
          path: node.path,
          fileCount:
            sortedRecords.length +
            children.reduce((sum, child) => sum + child.fileCount, 0),
          children,
          records: sortedRecords,
        };
      });

  return toTree(root);
}

function buildAncestorFolderPaths(folderPath: string) {
  const normalized = normalizeFolderPath(folderPath);
  const segments = normalized.split("/");
  const paths: string[] = [];
  let current = "";
  for (const segment of segments) {
    current = current ? `${current}/${segment}` : segment;
    paths.push(`personal:${current}`);
  }
  return paths;
}

function buildNoteTreeBreadcrumbs(
  nodes: NoteTreeFolderNode[],
  targetPath: string,
) {
  if (!targetPath) {
    return [];
  }
  const path: Array<{ name: string; path: string }> = [];
  const visit = (items: NoteTreeFolderNode[]): boolean => {
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

function ReadonlyRecordState({ record }: { record: UserKnowledgeRecord }) {
  return (
    <div className="border-y border-slate-200 py-4 text-slate-700">
      <div className="text-sm leading-7 text-slate-500">
        {record.source_kind === "import_ref"
          ? "这是收藏映射，当前不直接编辑正文。去原文页面摘录或批注后，会在这里形成可编辑文档。"
          : "这个条目当前不支持直接编辑正文。"}
      </div>
      <div className="mt-5 text-sm">
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 py-3">
          <span className="text-slate-500">来源</span>
          <span className="text-right text-slate-900">
            {record.origin_filename ?? record.filename ?? "未知"}
          </span>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 py-3">
          <span className="text-slate-500">更新时间</span>
          <span className="text-right text-slate-900">
            {formatTime(record.updated_at)}
          </span>
        </div>
      </div>
    </div>
  );
}

function markdownToTiptapDoc(markdown: string): JSONContent {
  const segments = parseNoteSegments(markdown);
  const nodes: JSONContent[] = [];

  for (const seg of segments) {
    if (seg.kind === "text") {
      const lines = seg.text.split("\n");
      for (const line of lines) {
        if (line === "") {
          nodes.push({ type: "paragraph" });
        } else {
          nodes.push({ type: "paragraph", content: [{ type: "text", text: line }] });
        }
      }
    } else {
      nodes.push({
        type: "excerptBlock",
        attrs: {
          filename: seg.excerpt.filename,
          scope: seg.excerpt.scope ?? null,
          location: seg.excerpt.location ?? null,
          text: seg.excerpt.text,
        },
      });
    }
  }

  if (nodes.length === 0) {
    nodes.push({ type: "paragraph" });
  }

  return { type: "doc", content: nodes };
}

function extractInlineText(node: JSONContent): string {
  if (node.type === "hardBreak") return "\n";
  if (node.type === "text") return node.text ?? "";
  if (node.content) return node.content.map(extractInlineText).join("");
  return "";
}

function tiptapDocToMarkdown(doc: JSONContent): string {
  const content = doc.content ?? [];
  const parts: string[] = [];
  const textBuffer: string[] = [];

  const flushText = () => {
    if (textBuffer.length > 0) {
      parts.push(textBuffer.join("\n"));
      textBuffer.length = 0;
    }
  };

  for (const node of content) {
    if (node.type === "excerptBlock") {
      flushText();
      const { filename, scope, location, text } = (node.attrs ?? {}) as {
        filename?: string;
        scope?: string | null;
        location?: string | null;
        text?: string;
      };
      const lines: string[] = [EXCERPT_HEADER, "", `来源：${filename ?? "未知来源"}`];
      if (scope) lines.push(`范围：${scope}`);
      if (location) lines.push(`定位：${location}`);
      lines.push("");
      const textStr = text ?? "";
      const quoteLines =
        textStr.length > 0
          ? textStr.split("\n").map((l) => (l ? `> ${l}` : ">"))
          : ["> "];
      lines.push(...quoteLines);
      parts.push(lines.join("\n"));
    } else {
      textBuffer.push(extractInlineText(node));
    }
  }

  flushText();
  return parts.join("\n\n");
}

function buildExcerptJumpHref(
  filename: string,
  scope: string | null,
  location: string | null,
): string | null {
  if (!filename || !location) return null;
  const resolvedScope = scope ?? "global";
  if (resolvedScope !== "global" && resolvedScope !== "user") return null;
  const pageMatch = /PDF 第 (\d+) 页/.exec(location);
  if (!pageMatch) return null;
  const pdfPageNo = pageMatch[1] ?? "";
  const documentUrl = buildKnowledgeDocumentUrl(resolvedScope, filename);
  const params = new URLSearchParams({
    mode: "reader",
    filename,
    scope: resolvedScope,
    document_url: documentUrl,
    origin_filename: filename,
    pdf_page_no: pdfPageNo,
    back_href: "/workspace/notes",
    back_label: "笔记",
  });
  return `/workspace/knowledge/view?${params.toString()}`;
}

function ExcerptBlockNodeView({ node, deleteNode }: ReactNodeViewProps) {
  const { filename, scope, location, text } = node.attrs as {
    filename: string;
    scope: string | null;
    location: string | null;
    text: string;
  };
  const jumpHref = buildExcerptJumpHref(filename, scope, location);
  return (
    <NodeViewWrapper>
      <div
        className="group relative my-4 rounded-2xl border border-stone-200 bg-stone-50/80 p-5"
        contentEditable={false}
      >
        <button
          type="button"
          onClick={deleteNode}
          className="absolute top-3 right-3 flex size-7 items-center justify-center rounded-full text-stone-400 opacity-0 transition-all hover:bg-red-50 hover:text-red-500 group-hover:opacity-100"
          title="移除此摘录"
        >
          <Trash2Icon className="size-3.5" />
        </button>
        <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-1 pr-10 text-sm text-stone-500">
          {filename ? (
            <span className="flex items-center gap-1.5">
              <span className="opacity-60">来源：</span>
              <span className="font-medium text-stone-700">{filename}</span>
            </span>
          ) : null}
          {location ? <span>{location}</span> : null}
          {jumpHref ? (
            <a
              href={jumpHref}
              target="_blank"
              rel="noopener noreferrer"
              className="text-accent hover:text-accent/80 inline-flex items-center gap-1 font-medium transition-all hover:translate-x-0.5"
            >
              跳转原文
              <ExternalLinkIcon className="size-3.5" />
            </a>
          ) : null}
        </div>
        <div className="border-l-2 border-stone-200 pl-4 font-serif text-[15px] leading-relaxed whitespace-pre-wrap text-stone-600 italic">
          {text}
        </div>
      </div>
    </NodeViewWrapper>
  );
}

const ExcerptBlockExtension = Node.create({
  name: "excerptBlock",
  group: "block",
  atom: true,
  selectable: true,
  addAttributes() {
    return {
      filename: { default: "" },
      scope: { default: null },
      location: { default: null },
      text: { default: "" },
    };
  },
  parseHTML() {
    return [{ tag: 'div[data-type="excerpt-block"]' }];
  },
  renderHTML({ HTMLAttributes }) {
    return ["div", mergeAttributes(HTMLAttributes, { "data-type": "excerpt-block" }), 0];
  },
  addNodeView() {
    return ReactNodeViewRenderer(ExcerptBlockNodeView);
  },
});

function NoteEditor({
  editorKey,
  content,
  onChange,
  placeholder,
}: {
  editorKey: string;
  content: string;
  onChange: (next: string) => void;
  placeholder: string;
}) {
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const initialDoc = useMemo(() => markdownToTiptapDoc(content), [editorKey]);
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;

  const editor = useEditor(
    {
      extensions: [
        StarterKit.configure({ heading: false, codeBlock: false, blockquote: false }),
        Placeholder.configure({ placeholder }),
        ExcerptBlockExtension,
      ],
      content: initialDoc,
      onUpdate({ editor: e }) {
        onChangeRef.current(tiptapDocToMarkdown(e.getJSON()));
      },
      editorProps: {
        attributes: {
          class:
            "outline-none font-serif text-[18px] leading-[2.2] text-stone-800 min-h-[600px] py-2",
          spellcheck: "false",
        },
      },
    },
    [editorKey],
  );

  return (
    <div className="note-editor w-full">
      <EditorContent editor={editor} />
    </div>
  );
}

export default function NotesPage() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const recordElementRefs = useRef<Map<string, HTMLButtonElement>>(new Map());
  const [deletingRecordId, setDeletingRecordId] = useState<string | null>(null);
  const [selectedRecordId, setSelectedRecordId] = useState<string | null>(null);
  const [dropTargetFolderPath, setDropTargetFolderPath] = useState<string | null>(null);
  const draggingItemRef = useRef<
    | { type: "record"; id: string }
    | { type: "folder"; path: string }
    | null
  >(null);
  const [selectedFolderPath, setSelectedFolderPath] = useState("");
  const [expandedFolderPaths, setExpandedFolderPaths] = useState<string[]>([]);
  const [isCreateFolderDialogOpen, setIsCreateFolderDialogOpen] =
    useState(false);
  const [newFolderName, setNewFolderName] = useState("");
  const [titleDraft, setTitleDraft] = useState("");
  const [contentDraft, setContentDraft] = useState("");
  const [draftRecordId, setDraftRecordId] = useState<string | null>(null);
  const [titleInputWidth, setTitleInputWidth] = useState<number>(320);
  const titleMeasureRef = useRef<HTMLSpanElement | null>(null);
  const selectedSpaceIdFromQuery = searchParams.get("space");

  useEffect(() => {
    const nextWidth = titleMeasureRef.current?.offsetWidth;
    if (!nextWidth) {
      return;
    }
    setTitleInputWidth(Math.max(240, nextWidth + 12));
  }, [titleDraft]);

  const spacesQuery = useUserKnowledgeSpaces();
  const personalSpaces = useMemo(
    () =>
      (spacesQuery.data?.spaces ?? []).filter(
        (space) => space.type === "personal",
      ),
    [spacesQuery.data?.spaces],
  );
  const activeSpaceId = useMemo(() => {
    if (
      selectedSpaceIdFromQuery &&
      personalSpaces.some((space) => space.id === selectedSpaceIdFromQuery)
    ) {
      return selectedSpaceIdFromQuery;
    }
    return (
      personalSpaces.find((space) => space.is_default)?.id ??
      personalSpaces[0]?.id ??
      null
    );
  }, [personalSpaces, selectedSpaceIdFromQuery]);

  const { data, isLoading, error } = useUserKnowledgeRecords(activeSpaceId);
  const createMutation = useCreateUserDerivedKnowledge();
  const createFolderMutation = useCreateUserKnowledgeFolder();
  const deleteMutation = useDeleteUserKnowledgeRecord();
  const moveMutation = useMoveUserKnowledgeRecord();
  const renameFolderMutation = useRenameUserKnowledgeFolder();
  const updateMutation = useUpdateUserKnowledgeRecordContent();

  const records = useMemo(
    () => sortRecords((data?.records ?? []).filter(isNoteRecord)),
    [data?.records],
  );
  const personalFolderPaths = useMemo(
    () => data?.folders ?? [],
    [data?.folders],
  );
  const folderTree = useMemo(
    () => buildNoteFolderTree(records, personalFolderPaths),
    [personalFolderPaths, records],
  );
  const selectedLogicalFolderPath = useMemo(() => {
    if (selectedFolderPath.startsWith("personal:")) {
      return selectedFolderPath.slice("personal:".length);
    }
    return "";
  }, [selectedFolderPath]);
  const folderBreadcrumbs = useMemo(() => {
    if (!selectedFolderPath) {
      return [];
    }
    return buildNoteTreeBreadcrumbs(folderTree, selectedFolderPath);
  }, [folderTree, selectedFolderPath]);
  const requestedRecordId = searchParams.get("record");

  useEffect(() => {
    document.title = "笔记 - Hilo";
  }, []);

  useEffect(() => {
    if (!activeSpaceId || selectedSpaceIdFromQuery === activeSpaceId) {
      return;
    }
    const params = new URLSearchParams(searchParams.toString());
    params.set("space", activeSpaceId);
    router.replace(`${pathname}?${params.toString()}`);
  }, [activeSpaceId, pathname, router, searchParams, selectedSpaceIdFromQuery]);

  useEffect(() => {
    if (records.length === 0) {
      setSelectedRecordId(null);
      return;
    }
    setSelectedRecordId((current) =>
      current && records.some((record) => record.id === current)
        ? current
        : (records[0]?.id ?? null),
    );
  }, [records]);

  useEffect(() => {
    if (!requestedRecordId) {
      return;
    }
    const requestedRecord = records.find(
      (record) => record.id === requestedRecordId,
    );
    if (!requestedRecord) {
      return;
    }
    setSelectedRecordId(requestedRecordId);
  }, [requestedRecordId, records]);

  const selectedRecord =
    records.find((record) => record.id === selectedRecordId) ??
    records[0] ??
    null;

  const contentQuery = useUserKnowledgeRecordContent(
    selectedRecord?.id ?? null,
  );

  useEffect(() => {
    if (!contentQuery.data || !selectedRecord?.id) {
      return;
    }
    setDraftRecordId(selectedRecord.id);
    setTitleDraft(contentQuery.data.title);
    setContentDraft(contentQuery.data.editable_content);
  }, [contentQuery.data, selectedRecord?.id]);

  useEffect(() => {
    if (!selectedRecord) {
      return;
    }
    const ancestorPaths = buildAncestorFolderPaths(
      selectedRecord.folder_path ?? "",
    );
    setExpandedFolderPaths((current) =>
      Array.from(new Set([...current, ...ancestorPaths])),
    );
    const folderPath = ancestorPaths[ancestorPaths.length - 1] ?? "";
    if (folderPath) {
      setSelectedFolderPath(folderPath);
    }
  }, [selectedRecord]);

  useEffect(() => {
    const topLevelPaths = folderTree.map((node) => node.path);
    if (topLevelPaths.length === 0) {
      return;
    }
    setExpandedFolderPaths((current) =>
      Array.from(new Set([...topLevelPaths, ...current])),
    );
  }, [folderTree]);

  useEffect(() => {
    if (!selectedRecordId) {
      return;
    }
    const element = recordElementRefs.current.get(selectedRecordId);
    if (!element) {
      return;
    }
    element.scrollIntoView({ block: "nearest" });
  }, [selectedRecordId, expandedFolderPaths]);

  const isDraftDirty = useMemo(() => {
    if (!contentQuery.data || draftRecordId !== selectedRecord?.id) {
      return false;
    }
    return (
      titleDraft !== contentQuery.data.title ||
      contentDraft !== contentQuery.data.editable_content
    );
  }, [
    contentDraft,
    contentQuery.data,
    draftRecordId,
    selectedRecord?.id,
    titleDraft,
  ]);

  const handleDelete = async (recordId: string) => {
    setDeletingRecordId(recordId);
    try {
      await deleteMutation.mutateAsync(recordId);
      toast.success("已删除");
    } catch (deleteError) {
      toast.error((deleteError as Error).message ?? "删除失败");
    } finally {
      setDeletingRecordId(null);
    }
  };

  const toggleFolderExpanded = (path: string) => {
    setExpandedFolderPaths((current) =>
      current.includes(path)
        ? current.filter((item) => item !== path)
        : [...current, path],
    );
  };

  const handleSelectFolder = (path: string) => {
    setSelectedFolderPath(path);
  };

  const handleSelectRecord = (record: UserKnowledgeRecord) => {
    setSelectedRecordId(record.id);
    const ancestors = buildAncestorFolderPaths(record.folder_path ?? "");
    setExpandedFolderPaths((current) =>
      Array.from(new Set([...current, ...ancestors])),
    );
    const leafPath = ancestors[ancestors.length - 1] ?? "";
    if (leafPath) {
      setSelectedFolderPath(leafPath);
    }
  };

  const registerRecordRef =
    (recordId: string) => (element: HTMLButtonElement | null) => {
      if (element) {
        recordElementRefs.current.set(recordId, element);
        return;
      }
      recordElementRefs.current.delete(recordId);
    };

  const handleCreateNoteInFolderPath = async (folderPath: string | null) => {
    if (!activeSpaceId) {
      toast.error("当前没有可用的个人知识库文件夹");
      return;
    }
    try {
      const created = await createMutation.mutateAsync({
        title: "未命名笔记",
        content: "",
        sourceKind: "note",
        knowledgeSpaceId: activeSpaceId,
        folderPath,
      });
      setSelectedRecordId(created.record.id);
      toast.success("已新建笔记");
    } catch (createError) {
      toast.error((createError as Error).message ?? "新建笔记失败");
    }
  };

  const handleCreateNote = async () => {
    await handleCreateNoteInFolderPath(selectedLogicalFolderPath || null);
  };

  const handleCreateNoteInFolder = (path: string) => {
    void handleCreateNoteInFolderPath(path.replace(/^personal:/, ""));
  };

  const handleOpenCreateFolderDialog = (path?: string) => {
    if (path) {
      setSelectedFolderPath(path);
      setExpandedFolderPaths((current) =>
        current.includes(path) ? current : [...current, path],
      );
    }
    setIsCreateFolderDialogOpen(true);
  };

  const handleCreateFolder = async () => {
    const trimmedName = newFolderName.trim();
    if (!trimmedName) {
      toast.error("请输入文件夹名称");
      return;
    }
    const nextPath = selectedLogicalFolderPath
      ? `${selectedLogicalFolderPath}/${trimmedName}`
      : trimmedName;
    try {
      await createFolderMutation.mutateAsync(nextPath);
      setExpandedFolderPaths((current) =>
        Array.from(
          new Set([...current, ...buildAncestorFolderPaths(nextPath)]),
        ),
      );
      setSelectedFolderPath(`personal:${nextPath}`);
      setNewFolderName("");
      setIsCreateFolderDialogOpen(false);
      toast.success("已新建文件夹");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "新建文件夹失败");
    }
  };

  const handleRecordDragStart = (recordId: string) => {
    draggingItemRef.current = { type: "record", id: recordId };
  };

  const handleFolderDragStartNode = (path: string) => {
    draggingItemRef.current = { type: "folder", path };
  };

  const handleDragEnd = () => {
    draggingItemRef.current = null;
    setDropTargetFolderPath(null);
  };

  const handleFolderDragEnter = (path: string) => {
    const item = draggingItemRef.current;
    if (item?.type === "folder" && item.path === path) {
      return;
    }
    setDropTargetFolderPath(path);
  };

  const handleFolderDragLeave = () => {
    setDropTargetFolderPath(null);
  };

  const handleFolderDrop = async (folderPath: string) => {
    const item = draggingItemRef.current;
    draggingItemRef.current = null;
    setDropTargetFolderPath(null);
    if (!item) {
      return;
    }
    const targetLogical = folderPath.replace(/^personal:/, "");

    if (item.type === "record") {
      const record = records.find((r) => r.id === item.id);
      if (record && normalizeFolderPath(record.folder_path) === targetLogical) {
        return;
      }
      try {
        await moveMutation.mutateAsync({
          recordId: item.id,
          folderPath: targetLogical,
        });
        toast.success("已移动");
      } catch (moveError) {
        toast.error(
          moveError instanceof Error ? moveError.message : "移动失败",
        );
      }
      return;
    }

    const sourceLogical = item.path.replace(/^personal:/, "");
    if (!sourceLogical || sourceLogical === targetLogical) {
      return;
    }
    if (targetLogical === `${sourceLogical}` || targetLogical.startsWith(`${sourceLogical}/`)) {
      toast.error("不能把文件夹移到它自己的子目录里");
      return;
    }
    const basename = sourceLogical.split("/").pop() ?? sourceLogical;
    const newPath = targetLogical ? `${targetLogical}/${basename}` : basename;
    if (newPath === sourceLogical) {
      return;
    }
    try {
      await renameFolderMutation.mutateAsync({
        path: sourceLogical,
        newPath,
      });
      toast.success("已移动");
    } catch (renameError) {
      toast.error(
        renameError instanceof Error ? renameError.message : "移动失败",
      );
    }
  };

  const handleSave = async () => {
    if (!selectedRecord?.id || !contentQuery.data?.editable) {
      return;
    }
    try {
      await updateMutation.mutateAsync({
        recordId: selectedRecord.id,
        title: titleDraft,
        content: contentDraft,
      });
      toast.success("已保存");
    } catch (saveError) {
      toast.error((saveError as Error).message ?? "保存失败");
    }
  };

  if (env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true") {
    return (
      <WorkspaceContainer>
        <WorkspaceHeader />
        <WorkspaceBody className="items-center justify-center px-6 py-10">
          <div className="text-muted-foreground text-sm">
            当前为静态模式，笔记功能不可用。
          </div>
        </WorkspaceBody>
      </WorkspaceContainer>
    );
  }

  const selectedIsDeleting =
    deleteMutation.isPending && deletingRecordId === selectedRecord?.id;
  const hasLegacyLockedExcerpt = Boolean(
    contentQuery.data?.mode === "derived" && contentQuery.data.locked_excerpt,
  );
  const originalJumpHref =
    hasLegacyLockedExcerpt && selectedRecord
      ? buildOriginalJumpHref(selectedRecord, selectedRecord.id, activeSpaceId)
      : null;

  return (
    <WorkspaceContainer>
      <WorkspaceHeader className="border-primary/5 border-b" />
      <WorkspaceBody className="min-h-0 overflow-hidden bg-white">
        <CreateFolderDialog
          open={isCreateFolderDialogOpen}
          onOpenChange={(open) => {
            setIsCreateFolderDialogOpen(open);
            if (!open) {
              setNewFolderName("");
            }
          }}
          title="新建笔记文件夹"
          description={
            selectedLogicalFolderPath
              ? `新文件夹会创建在“${selectedLogicalFolderPath}”下。`
              : "新文件夹会创建在个人笔记根目录下。"
          }
          value={newFolderName}
          onValueChange={setNewFolderName}
          onSubmit={() => void handleCreateFolder()}
          isPending={createFolderMutation.isPending}
        />
        <ResizablePanelGroup
          orientation="horizontal"
          className="h-full min-h-0 w-full"
        >
          <ResizablePanel
            defaultSize="28%"
            minSize="15%"
            maxSize="60%"
            className="flex min-h-0 flex-col border-r border-stone-200 bg-stone-50/50"
          >
            <div className="border-b border-stone-200/50 bg-stone-50 p-5">
              <div className="flex gap-2">
                <Button
                  size="sm"
                  className="bg-primary/90 text-primary-foreground hover:bg-primary group h-10 flex-1 justify-start gap-2 rounded-md font-serif shadow-sm transition-all"
                  disabled={createMutation.isPending}
                  onClick={() => void handleCreateNote()}
                >
                  {createMutation.isPending ? (
                    <Loader2Icon className="size-4 animate-spin" />
                  ) : (
                    <PlusIcon className="size-4 opacity-80 transition-transform group-hover:rotate-90" />
                  )}
                  <span className="whitespace-nowrap tracking-widest">新建笔记</span>
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  className="h-10 w-10 shrink-0 rounded-md border-stone-200 bg-white px-0 text-stone-500 shadow-sm transition-colors hover:bg-stone-100 hover:text-stone-700"
                  disabled={createFolderMutation.isPending}
                  onClick={() => handleOpenCreateFolderDialog()}
                  title={
                    selectedLogicalFolderPath
                      ? `在 ${selectedLogicalFolderPath} 下新建文件夹`
                      : "新建文件夹"
                  }
                >
                  {createFolderMutation.isPending ? (
                    <Loader2Icon className="size-4 animate-spin" />
                  ) : (
                    <FolderPlusIcon className="size-4 opacity-80" />
                  )}
                </Button>
              </div>
              <div className="mt-4 flex items-center gap-1.5 font-serif text-[13px] text-stone-500">
                <span className="shrink-0 opacity-80">当前:</span>
                <span className="truncate font-medium text-stone-700">
                  {selectedFolderPath && folderBreadcrumbs.length > 0
                    ? folderBreadcrumbs.map((crumb) => getFolderDisplayName(crumb.name)).join(" / ")
                    : "笔记总览"}
                </span>
              </div>
            </div>

            <ScrollArea
              className="min-h-0 flex-1"
              onClick={(e) => {
                const target = e.target as HTMLElement;
                if (!target.closest("button") && !target.closest("[data-sidebar-folder-row]")) {
                  setSelectedFolderPath("");
                }
              }}
              onDragOver={(e) => {
                if (draggingItemRef.current) {
                  e.preventDefault();
                  e.dataTransfer.dropEffect = "move";
                }
              }}
              onDrop={(e) => {
                const target = e.target as HTMLElement;
                if (target.closest("[data-sidebar-folder-row]")) {
                  return;
                }
                e.preventDefault();
                void handleFolderDrop("personal:");
              }}
            >
              {isLoading ? (
                <div className="flex min-h-[240px] items-center justify-center gap-2 text-sm text-stone-400">
                  <Loader2Icon className="size-4 animate-spin opacity-50" />
                  <span className="font-serif tracking-widest">加载中...</span>
                </div>
              ) : error ? (
                <div className="m-4 rounded-md border border-red-500/20 bg-red-500/5 p-4 text-sm text-red-600">
                  {error.message}
                </div>
              ) : records.length === 0 ? (
                <div className="p-8 text-center font-serif text-sm text-stone-400">
                  暂无笔记。
                </div>
              ) : (
                <div className="space-y-0.5 px-3 py-4">
                  {folderTree.map((node) => (
                    <SidebarFolderNode
                      key={node.path}
                      node={node}
                      selectedFolderPath={selectedFolderPath}
                      selectedRecordId={selectedRecord?.id ?? null}
                      expandedFolderPaths={expandedFolderPaths}
                      onToggleFolder={toggleFolderExpanded}
                      onSelectFolder={handleSelectFolder}
                      onSelectRecord={handleSelectRecord}
                      onCreateNoteInFolder={handleCreateNoteInFolder}
                      onCreateFolderInFolder={handleOpenCreateFolderDialog}
                      registerRecordRef={registerRecordRef}
                      dropTargetFolderPath={dropTargetFolderPath}
                      onRecordDragStart={handleRecordDragStart}
                      onFolderDragStartNode={handleFolderDragStartNode}
                      onDragEnd={handleDragEnd}
                      onFolderDragEnter={handleFolderDragEnter}
                      onFolderDragLeave={handleFolderDragLeave}
                      onFolderDrop={(path) => void handleFolderDrop(path)}
                    />
                  ))}
                </div>
              )}
            </ScrollArea>
          </ResizablePanel>

          <ResizableHandle 
            withHandle 
            className="w-1.5 bg-stone-100 hover:bg-primary/20 active:bg-primary/30 transition-colors" 
          />

          <ResizablePanel minSize="20%" className="flex min-h-0 flex-col bg-white">
            <div className="border-accent/20 border-b px-6 py-4 shadow-sm">
              <div className="flex items-start gap-6">
                <div className="min-w-0 flex-1">
                  {selectedRecord ? (
                    <div className="relative inline-flex max-w-full items-center gap-2 align-middle">
                      <Input
                        value={titleDraft}
                        onChange={(event) =>
                          setTitleDraft(event.target.value)
                        }
                        disabled={!contentQuery.data?.editable}
                        className="text-primary h-auto !w-auto max-w-full min-w-[120px] rounded-none border-0 bg-transparent px-0 py-0 font-serif text-2xl font-bold shadow-none focus-visible:ring-0 disabled:opacity-100"
                        style={{ width: `${titleInputWidth}px` }}
                      />
                      <span
                        ref={titleMeasureRef}
                        aria-hidden="true"
                        className="pointer-events-none invisible absolute top-0 left-0 px-0 font-serif text-2xl font-bold whitespace-pre"
                      >
                        {titleDraft || "未命名笔记"}
                      </span>
                    </div>
                  ) : null}
                </div>
                <div className="ml-auto flex items-center gap-4">
                  {selectedRecord ? (
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-8 w-8 rounded-full p-0 text-stone-300 transition-all hover:rotate-12 hover:bg-red-50 hover:text-red-500"
                      disabled={deleteMutation.isPending}
                      onClick={() => void handleDelete(selectedRecord.id)}
                      title="废弃此卷 (删除)"
                    >
                      {selectedIsDeleting ? (
                        <Loader2Icon className="size-4 animate-spin" />
                      ) : (
                        <Trash2Icon className="size-4" />
                      )}
                    </Button>
                  ) : null}
                </div>
              </div>
            </div>

            {!selectedRecord ? (
              <div className="flex min-h-0 flex-1 items-center justify-center px-6 py-16">
                <div className="text-center">
                  <div className="mx-auto flex h-10 w-10 items-center justify-center text-slate-400">
                    <FileTextIcon className="size-5" />
                  </div>
                  <div className="mt-3 text-sm text-slate-500">
                    选择左侧笔记查看或编辑
                  </div>
                </div>
              </div>
            ) : contentQuery.isLoading ? (
              <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-4 text-stone-400">
                <div className="relative">
                  <Loader2Icon className="text-primary/20 size-8 animate-spin" />
                  <div className="absolute inset-0 flex items-center justify-center">
                    <div className="bg-primary size-1 animate-pulse rounded-full" />
                  </div>
                </div>
                <div className="font-serif tracking-widest italic">
                  正在开启卷宗...
                </div>
              </div>
            ) : contentQuery.error ? (
              <div className="flex min-h-0 flex-1 items-center justify-center px-6 py-10">
                <div className="w-full max-w-[920px] border border-red-500/20 bg-red-500/6 p-6 text-sm text-red-600">
                  {contentQuery.error.message}
                </div>
              </div>
            ) : (
              <div className="relative flex min-h-0 flex-1 flex-col">
                <ScrollArea className="min-h-0 flex-1">
                  <div className="w-full px-6 py-6 md:px-10">
                    <div className="pt-4 pb-32">
                      {hasLegacyLockedExcerpt ? (
                        <div className="mb-8 rounded-2xl border border-stone-200 bg-stone-50/80 p-5">
                          <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-stone-500">
                            {selectedRecord?.origin_filename ? (
                              <span className="flex items-center gap-1.5">
                                <span className="opacity-60">来源：</span>
                                <span className="font-medium text-stone-700">
                                  {selectedRecord.origin_filename}
                                </span>
                              </span>
                            ) : null}
                            {contentQuery.data?.location_label ? (
                              <span>{contentQuery.data.location_label}</span>
                            ) : null}
                            {originalJumpHref ? (
                              <Link
                                href={originalJumpHref}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="text-accent hover:text-accent/80 inline-flex items-center gap-1 font-medium transition-all hover:translate-x-0.5"
                              >
                                跳转原文
                                <ExternalLinkIcon className="size-3.5" />
                              </Link>
                            ) : null}
                          </div>
                          <div className="border-l-2 border-stone-200 pl-4 font-serif text-[15px] leading-relaxed whitespace-pre-wrap text-stone-600 italic">
                            {contentQuery.data?.locked_excerpt}
                          </div>
                        </div>
                      ) : null}
                      {contentQuery.data?.editable ? (
                        <NoteEditor
                          editorKey={draftRecordId ?? ""}
                          content={contentDraft}
                          onChange={setContentDraft}
                          placeholder={
                            contentQuery.data.mode === "derived"
                              ? "在这里继续写你的摘抄、理解或批注。"
                              : "输入正文内容"
                          }
                        />
                      ) : (
                        <ReadonlyRecordState record={selectedRecord} />
                      )}
                    </div>
                  </div>
                </ScrollArea>

                {contentQuery.data?.editable && (
                  <button
                    type="button"
                    disabled={updateMutation.isPending || !isDraftDirty}
                    onClick={() => void handleSave()}
                    className={cn(
                      "absolute right-10 bottom-10 z-30 flex size-20 flex-col items-center justify-center transition-all",
                      updateMutation.isPending || !isDraftDirty
                        ? "cursor-not-allowed opacity-30 grayscale"
                        : "cursor-pointer opacity-100 hover:scale-110 active:scale-95",
                    )}
                  >
                    <div className="relative flex size-full items-center justify-center">
                      <div className="bg-primary absolute inset-0 shadow-lg" />
                      <div className="relative z-10 flex size-[85%] flex-col items-center justify-center border-2 border-white/40 font-serif text-white">
                        <span className="text-2xl leading-none font-bold">
                          {updateMutation.isPending ? "载" : "印"}
                        </span>
                        <span className="mt-0.5 text-[10px] font-medium tracking-tighter opacity-80">
                          {updateMutation.isPending ? "记录中" : "封卷保存"}
                        </span>
                      </div>
                      {/* Decorative corner accent */}
                      <div className="absolute -top-1 -left-1 size-3 border-t-2 border-l-2 border-white/20" />
                    </div>
                  </button>
                )}
              </div>
            )}
          </ResizablePanel>
        </ResizablePanelGroup>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}
