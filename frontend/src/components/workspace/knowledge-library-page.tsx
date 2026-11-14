"use client";

import {
  FileTextIcon,
  Loader2Icon,
  PlusIcon,
  Trash2Icon,
  UploadIcon,
} from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import { KnowledgeDocumentDetail } from "@/components/workspace/artifacts/knowledge-document-detail";
import { UserKnowledgeSpaceSwitcher } from "@/components/workspace/user-knowledge-space-switcher";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { buildKnowledgeDocumentUrl, type KnowledgeFileInfo } from "@/core/knowledge/api";
import { useKnowledgeFiles } from "@/core/knowledge/hooks";
import type { UserKnowledgeRecord } from "@/core/knowledge/user-api";
import {
  useDeleteUserKnowledgeRecord,
  useUploadUserKnowledgeFiles,
  useUserKnowledgeRecords,
  useUserKnowledgeSpaces,
} from "@/core/knowledge/user-hooks";
import { env } from "@/env";
import { cn } from "@/lib/utils";

type CombinedKnowledgeItem = {
  id: string;
  scope: "user" | "global";
  sourceLabel: string;
  title: string;
  subtitle: string;
  dateValue?: string | number | null;
  previewUrl: string | null;
  initialPdfPageNo: number;
  originFilename: string;
  originTitle: string;
  deleteRecordId?: string | null;
};

function formatListDate(value?: string | number | null) {
  if (!value) {
    return "";
  }
  const date =
    typeof value === "number"
      ? new Date(value < 1_000_000_000_000 ? value * 1000 : value)
      : new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  return date.toLocaleDateString("zh-CN", {
    month: "numeric",
    day: "numeric",
  });
}

function stripExtension(filename?: string | null) {
  return String(filename ?? "").replace(/\.[^.]+$/, "").trim();
}

function getRecordTitle(record: UserKnowledgeRecord) {
  return record.filename ?? record.origin_filename ?? record.display_title ?? record.title ?? "未命名";
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

function resolveRecordDocumentUrl(
  record: UserKnowledgeRecord,
  options?: { preferPreview?: boolean },
) {
  if (options?.preferPreview) {
    if (record.preview_artifact_url) {
      return record.preview_artifact_url;
    }
    if (record.preview_filename) {
      return buildKnowledgeDocumentUrl("user", record.preview_filename);
    }
  }
  if (record.artifact_url) {
    return record.artifact_url;
  }
  if (record.origin_scope === "global" && record.origin_filename) {
    return buildKnowledgeDocumentUrl("global", record.origin_filename);
  }
  if (record.origin_scope === "user" && record.origin_filename) {
    return buildKnowledgeDocumentUrl("user", record.origin_filename);
  }
  return null;
}

function isPdfRecord(record: UserKnowledgeRecord) {
  const filename = record.filename ?? record.origin_filename ?? "";
  return filename.toLowerCase().endsWith(".pdf");
}

function isReferenceRecord(record: UserKnowledgeRecord) {
  return ["upload", "import_ref"].includes(record.source_kind);
}

function sortRecords(records: UserKnowledgeRecord[]) {
  return [...records].sort((left, right) => {
    const leftTime = new Date(left.updated_at ?? left.created_at ?? 0).getTime();
    const rightTime = new Date(right.updated_at ?? right.created_at ?? 0).getTime();
    return rightTime - leftTime;
  });
}

function buildKnowledgePreviewUrl(record: UserKnowledgeRecord) {
  const baseUrl = resolveRecordDocumentUrl(record, { preferPreview: !isPdfRecord(record) });
  if (!baseUrl) {
    return null;
  }

  try {
    const url = new URL(baseUrl, window.location.origin);
    const pageNo = getOriginAnchorNumber(record, "page_no");
    const pdfPageNo = getOriginAnchorNumber(record, "pdf_page_no");
    const paragraphNo = getOriginAnchorNumber(record, "paragraph_no");
    const sourceTitle = getRecordTitle(record);

    if (pageNo) {
      url.searchParams.set("page_no", String(pageNo));
    }
    if (pdfPageNo) {
      url.searchParams.set("pdf_page_no", String(pdfPageNo));
    }
    if (paragraphNo) {
      url.searchParams.set("paragraph_no", String(paragraphNo));
    }
    if (sourceTitle) {
      url.searchParams.set("citation_source_title", sourceTitle);
    }
    if (record.source_kind === "import_ref") {
      url.searchParams.set("citation_source_label", "个人知识库收藏");
    } else {
      url.searchParams.set("citation_source_label", "知识库文件");
    }
    if (record.origin_filename && record.origin_filename !== sourceTitle) {
      url.searchParams.set("citation_origin_title", record.origin_filename);
    }

    return `${url.pathname}${url.search}`;
  } catch {
    return baseUrl;
  }
}

function buildGlobalKnowledgePreviewUrl(file: KnowledgeFileInfo) {
  const baseUrl =
    file.preview_artifact_url ??
    file.artifact_url ??
    buildKnowledgeDocumentUrl("global", file.preview_filename ?? file.filename);

  try {
    const url = new URL(baseUrl, window.location.origin);
    const sourceTitle = stripExtension(file.filename) || file.filename;
    if (sourceTitle) {
      url.searchParams.set("citation_source_title", sourceTitle);
    }
    url.searchParams.set("citation_source_label", "系统知识库");
    return `${url.pathname}${url.search}`;
  } catch {
    return baseUrl;
  }
}

export default function KnowledgeLibraryPage() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [deletingRecordId, setDeletingRecordId] = useState<string | null>(null);
  const [selectedRecordId, setSelectedRecordId] = useState<string | null>(null);
  const [isUploadDialogOpen, setIsUploadDialogOpen] = useState(false);
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);
  const selectedSpaceIdFromQuery = searchParams.get("space");

  const spacesQuery = useUserKnowledgeSpaces();
  const personalSpaces = useMemo(
    () => (spacesQuery.data?.spaces ?? []).filter((space) => space.type === "personal"),
    [spacesQuery.data?.spaces],
  );
  const activeSpaceId = useMemo(() => {
    if (selectedSpaceIdFromQuery && personalSpaces.some((space) => space.id === selectedSpaceIdFromQuery)) {
      return selectedSpaceIdFromQuery;
    }
    return personalSpaces.find((space) => space.is_default)?.id ?? personalSpaces[0]?.id ?? null;
  }, [personalSpaces, selectedSpaceIdFromQuery]);

  const { data, isLoading, error } = useUserKnowledgeRecords(activeSpaceId);
  const globalFilesQuery = useKnowledgeFiles();
  const deleteMutation = useDeleteUserKnowledgeRecord();
  const uploadMutation = useUploadUserKnowledgeFiles();

  const personalRecords = useMemo(
    () => sortRecords((data?.records ?? []).filter(isReferenceRecord)),
    [data?.records],
  );
  const globalRecords = useMemo(
    () =>
      [...(globalFilesQuery.data?.files ?? [])].sort((left, right) => {
        const timeDelta = (right.modified ?? 0) - (left.modified ?? 0);
        if (timeDelta !== 0) {
          return timeDelta;
        }
        return left.filename.localeCompare(right.filename, "zh-CN");
      }),
    [globalFilesQuery.data?.files],
  );
  const items = useMemo<CombinedKnowledgeItem[]>(() => {
    const personalItems = personalRecords.map<CombinedKnowledgeItem>((record) => ({
      id: `user:${record.id}`,
      scope: "user",
      sourceLabel: "个人资料",
      title: getRecordTitle(record),
      subtitle: record.knowledge_space_name ?? "个人知识库",
      dateValue: record.updated_at ?? record.created_at,
      previewUrl: buildKnowledgePreviewUrl(record),
      initialPdfPageNo:
        getOriginAnchorNumber(record, "pdf_page_no")
        ?? getOriginAnchorNumber(record, "page_no")
        ?? 1,
      originFilename: record.origin_filename ?? record.filename ?? "未知文档",
      originTitle: getRecordTitle(record),
      deleteRecordId: record.id,
    }));
    const systemItems = globalRecords.map<CombinedKnowledgeItem>((file) => ({
      id: `global:${file.filename}`,
      scope: "global",
      sourceLabel: "系统书籍",
      title: stripExtension(file.filename) || file.filename,
      subtitle: file.folder ?? "系统知识库",
      dateValue: file.modified,
      previewUrl: buildGlobalKnowledgePreviewUrl(file),
      initialPdfPageNo: 1,
      originFilename: file.filename,
      originTitle: stripExtension(file.filename) || file.filename,
      deleteRecordId: null,
    }));
    return [...personalItems, ...systemItems].sort((left, right) => {
      const leftTime =
        typeof left.dateValue === "number"
          ? left.dateValue
          : new Date(left.dateValue ?? 0).getTime();
      const rightTime =
        typeof right.dateValue === "number"
          ? right.dateValue
          : new Date(right.dateValue ?? 0).getTime();
      return rightTime - leftTime;
    });
  }, [globalRecords, personalRecords]);
  const groupedItems = useMemo(
    () => ({
      user: items.filter((item) => item.scope === "user"),
      global: items.filter((item) => item.scope === "global"),
    }),
    [items],
  );
  const requestedRecordId = searchParams.get("record");

  useEffect(() => {
    document.title = "知识库 - Hilo";
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
    if (items.length === 0) {
      setSelectedRecordId(null);
      return;
    }
    setSelectedRecordId((current) =>
      current && items.some((item) => item.id === current)
        ? current
        : items[0]?.id ?? null,
    );
  }, [items]);

  useEffect(() => {
    if (!requestedRecordId) {
      return;
    }
    const requestedItem = items.find((item) => item.id === requestedRecordId);
    if (!requestedItem) {
      return;
    }
    setSelectedRecordId(requestedRecordId);
  }, [items, requestedRecordId]);

  const selectedItem = items.find((item) => item.id === selectedRecordId) ?? items[0] ?? null;

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

  const handleUpload = async () => {
    if (pendingFiles.length === 0) {
      toast.error("请选择要上传的文件");
      return;
    }
    if (!activeSpaceId) {
      toast.error("当前没有可用的个人知识库文件夹");
      return;
    }
    try {
      await uploadMutation.mutateAsync({
        files: pendingFiles,
        options: {
          knowledgeSpaceId: activeSpaceId,
        },
      });
      toast.success(`已提交 ${pendingFiles.length} 个文件`);
      setPendingFiles([]);
      setIsUploadDialogOpen(false);
    } catch (uploadError) {
      toast.error((uploadError as Error).message ?? "上传失败");
    }
  };

  if (env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true") {
    return (
      <WorkspaceContainer>
        <WorkspaceHeader />
        <WorkspaceBody className="items-center justify-center px-6 py-10">
          <div className="text-sm text-muted-foreground">
            当前为静态模式，知识库功能不可用。
          </div>
        </WorkspaceBody>
      </WorkspaceContainer>
    );
  }

  const selectedIsDeleting =
    deleteMutation.isPending && deletingRecordId === selectedItem?.deleteRecordId;
  const combinedLoading = isLoading || globalFilesQuery.isLoading;
  const combinedError = error ?? globalFilesQuery.error;

  return (
    <WorkspaceContainer>
      <WorkspaceHeader />
      <WorkspaceBody className="min-h-0 overflow-hidden bg-white">
        <div className="border-b border-slate-200 bg-white px-4 py-3 md:px-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <div className="text-base font-medium text-slate-900">知识库</div>
              <div className="text-sm text-slate-500">
                个人资料和系统书籍统一浏览；系统书籍当前按只读展示。
              </div>
            </div>
            {personalSpaces.length > 0 ? (
              <UserKnowledgeSpaceSwitcher
                spaces={personalSpaces}
                selectedSpaceId={activeSpaceId ?? personalSpaces[0]!.id}
                onSelect={(spaceId) => {
                  const params = new URLSearchParams(searchParams.toString());
                  params.set("space", spaceId);
                  params.delete("record");
                  router.push(`${pathname}?${params.toString()}`);
                }}
              />
            ) : null}
          </div>
        </div>

        <div className="flex h-full min-h-0 w-full overflow-hidden bg-white">
          <aside className="flex min-h-0 w-full shrink-0 flex-col border-b border-slate-200 bg-white lg:w-[240px] lg:border-r lg:border-b-0">
            <div className="flex items-center justify-between border-b border-slate-200 px-3 py-2">
              <div className="text-xs text-slate-500">{items.length} 项</div>
              <div className="flex items-center gap-1">
                {selectedItem?.scope === "user" && selectedItem.deleteRecordId ? (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-8 rounded-md px-2 text-slate-700 hover:bg-slate-100 hover:text-slate-900"
                    disabled={deleteMutation.isPending}
                    onClick={() => void handleDelete(selectedItem.deleteRecordId ?? "")}
                  >
                    {selectedIsDeleting ? (
                      <Loader2Icon className="size-4 animate-spin" />
                    ) : (
                      <Trash2Icon className="size-4" />
                    )}
                  </Button>
                ) : null}
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-8 rounded-md px-2 text-slate-700 hover:bg-slate-100 hover:text-slate-900"
                  disabled={!activeSpaceId}
                  onClick={() => setIsUploadDialogOpen(true)}
                >
                  <PlusIcon className="size-4" />
                  上传
                </Button>
              </div>
            </div>

            <ScrollArea className="min-h-0 flex-1">
              {combinedLoading ? (
                <div className="flex min-h-[240px] items-center justify-center gap-2 text-sm text-slate-500">
                  <Loader2Icon className="size-4 animate-spin" />
                  正在加载
                </div>
              ) : combinedError ? (
                <div className="m-4 border border-red-500/20 bg-red-500/6 p-4 text-sm text-red-600">
                  {combinedError.message}
                </div>
              ) : items.length === 0 ? (
                <div className="p-4 text-sm text-slate-500">暂无资料。</div>
              ) : (
                <div className="py-2">
                  {([
                    ["个人资料", groupedItems.user],
                    ["系统书籍", groupedItems.global],
                  ] as const).map(([label, sectionItems]) =>
                    sectionItems.length > 0 ? (
                      <div key={label} className="mb-2">
                        <div className="px-4 py-2 text-xs font-medium text-slate-400">
                          {label}
                        </div>
                        {sectionItems.map((item) => (
                          <button
                            key={item.id}
                            type="button"
                            onClick={() => setSelectedRecordId(item.id)}
                            className={cn(
                              "grid w-full min-w-0 grid-cols-[minmax(0,1fr)_auto] gap-3 border-l-2 px-4 py-2 text-left transition",
                              selectedItem?.id === item.id
                                ? "border-l-primary bg-stone-50 text-slate-900"
                                : "border-l-transparent text-slate-700 hover:bg-slate-50",
                            )}
                          >
                            <div className="min-w-0">
                              <div className="truncate text-sm">{item.title}</div>
                              <div className="mt-1 flex items-center gap-2 text-[11px] text-slate-400">
                                <span>{item.sourceLabel}</span>
                                <span className="truncate">{item.subtitle}</span>
                              </div>
                            </div>
                            <span className="shrink-0 pt-0.5 text-xs text-slate-400">
                              {formatListDate(item.dateValue)}
                            </span>
                          </button>
                        ))}
                      </div>
                    ) : null,
                  )}
                </div>
              )}
            </ScrollArea>
          </aside>

          <section className="flex min-h-0 min-w-0 flex-1 flex-col bg-white">
            {!selectedItem ? (
              <div className="flex min-h-0 flex-1 items-center justify-center px-6 py-16">
                <div className="text-center">
                  <div className="mx-auto flex h-10 w-10 items-center justify-center text-slate-400">
                    <FileTextIcon className="size-5" />
                  </div>
                  <div className="mt-3 text-sm text-slate-500">
                    选择左侧资料查看内容
                  </div>
                </div>
              </div>
            ) : !selectedItem.previewUrl ? (
              <div className="flex min-h-0 flex-1 items-center justify-center px-6 py-16">
                <div className="text-center">
                  <div className="mx-auto flex h-10 w-10 items-center justify-center text-slate-400">
                    <FileTextIcon className="size-5" />
                  </div>
                  <div className="mt-3 text-sm text-slate-500">
                    当前文件暂时没有可展示的预览地址
                  </div>
                  <div className="mt-2 flex items-center justify-center gap-2 text-xs text-slate-400">
                    <span>来源：{selectedItem.originFilename}</span>
                    <span>{selectedItem.sourceLabel}</span>
                  </div>
                </div>
              </div>
            ) : (
              <div className="min-h-0 flex-1 p-4 md:p-6">
                <KnowledgeDocumentDetail
                  className="h-full min-h-[640px]"
                  displayName={selectedItem.originFilename}
                  documentUrl={selectedItem.previewUrl}
                  initialPdfPageNo={selectedItem.initialPdfPageNo}
                  knowledgeSpaceId={activeSpaceId ?? undefined}
                  originFilename={selectedItem.originFilename}
                  originTitle={selectedItem.originTitle}
                />
              </div>
            )}
          </section>
        </div>

        <Dialog open={isUploadDialogOpen} onOpenChange={setIsUploadDialogOpen}>
          <DialogContent className="sm:max-w-xl border-slate-200 bg-white">
            <DialogHeader>
              <DialogTitle className="text-slate-900">
                上传资料到{personalSpaces.find((space) => space.id === activeSpaceId)?.name ?? "当前文件夹"}
              </DialogTitle>
            </DialogHeader>
            <div className="space-y-3">
              <input
                ref={fileInputRef}
                type="file"
                multiple
                className="hidden"
                onChange={(event) => {
                  setPendingFiles(Array.from(event.target.files ?? []));
                }}
              />
              <Button
                variant="outline"
                className="w-full"
                onClick={() => fileInputRef.current?.click()}
              >
                <UploadIcon className="size-4" />
                选择文件
              </Button>
              <div className="border border-slate-200 p-3 text-xs text-slate-600">
                {pendingFiles.length === 0
                  ? "尚未选择文件"
                  : `已选择 ${pendingFiles.length} 个文件：${pendingFiles.map((file) => file.name).join("，")}`}
              </div>
            </div>
            <DialogFooter>
              <Button
                variant="outline"
                onClick={() => {
                  setPendingFiles([]);
                  setIsUploadDialogOpen(false);
                }}
                disabled={uploadMutation.isPending}
              >
                取消
              </Button>
              <Button
                className="bg-primary text-white hover:bg-primary/90"
                onClick={() => void handleUpload()}
                disabled={uploadMutation.isPending || pendingFiles.length === 0}
              >
                {uploadMutation.isPending ? (
                  <Loader2Icon className="size-4 animate-spin" />
                ) : null}
                上传
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}
