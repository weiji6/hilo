"use client";

import {
  BookOpenIcon,
  PencilIcon,
  RefreshCwIcon,
  Trash2Icon,
  UploadIcon,
  XIcon,
} from "lucide-react";
import { useMemo, useRef, useState, type ChangeEvent } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Item,
  ItemContent,
  ItemDescription,
  ItemTitle,
} from "@/components/ui/item";
import { Progress } from "@/components/ui/progress";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useI18n } from "@/core/i18n/hooks";
import type { KnowledgeFileInfo } from "@/core/knowledge/api";
import { shouldUseChunkedUpload } from "@/core/knowledge/chunked-upload";
import {
  useDeleteKnowledgeFile,
  useKnowledgeFiles,
  useKnowledgeStatus,
  useReindexKnowledgeBase,
  useSmartUploadKnowledgeDocument,
  useUpdateKnowledgeFileMetadata,
} from "@/core/knowledge/hooks";

import { SettingsSection } from "./settings-section";

const ACTIVE_KNOWLEDGE_JOB_STATUSES = [
  "queued",
  "queued_ocr",
  "parsing",
  "queued_embedding",
  "indexing",
];

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${(bytes / Math.pow(k, i)).toFixed(1)} ${sizes[i]}`;
}

function splitTagInput(value: string): string[] {
  return value
    .split(/[,\n，]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function buildTags(file: KnowledgeFileInfo): string[] {
  const tags = file.tags?.length
      ? file.tags
      : [
        ...(file.type ? [file.type] : []),
        ...(file.categories ?? []),
        ...(file.eras ?? []),
        ...(file.regions ?? []),
        ...(file.keywords ?? []),
      ];

  return Array.from(new Set(tags.filter(Boolean)));
}

function formatQueueStatus(file: KnowledgeFileInfo): string | null {
  if (!file.parse_status) {
    return null;
  }
  if (file.queue_stage && file.queue_position) {
    return `${file.parse_status} · ${file.queue_stage} 队列第 ${file.queue_position} 个`;
  }
  if (file.queue_stage) {
    return `${file.parse_status} · ${file.queue_stage} 队列`;
  }
  return file.parse_status;
}

export function KnowledgeSettingsPage() {
  const { t } = useI18n();
  const { status, isLoading, error } = useKnowledgeStatus();
  const { data: knowledgeFilesData, isLoading: isFilesLoading, error: filesError } =
    useKnowledgeFiles();
  const reindexMutation = useReindexKnowledgeBase();
  const updateMetadataMutation = useUpdateKnowledgeFileMetadata();
  const {
    upload,
    cancel: cancelUpload,
    reset: resetUpload,
    isUploading,
    uploadProgress,
    error: uploadError,
  } = useSmartUploadKnowledgeDocument();
  const deleteMutation = useDeleteKnowledgeFile();

  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [autoReindex, setAutoReindex] = useState(true);
  const [uploadSuccess, setUploadSuccess] = useState(false);
  const [editingFile, setEditingFile] = useState<KnowledgeFileInfo | null>(null);
  const [typeInput, setTypeInput] = useState("");
  const [categoriesInput, setCategoriesInput] = useState("");
  const [erasInput, setErasInput] = useState("");
  const [regionsInput, setRegionsInput] = useState("");
  const [keywordsInput, setKeywordsInput] = useState("");
  const [summaryInput, setSummaryInput] = useState("");
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const knowledgeFiles = useMemo(
    () => knowledgeFilesData?.files ?? [],
    [knowledgeFilesData?.files],
  );

  const statusDescription = useMemo(() => {
    if (!status) return "";
    if (!status.enabled) {
      return t.settings.knowledge.status.disabled;
    }
    return t.settings.knowledge.status.enabled;
  }, [
    status,
    t.settings.knowledge.status.disabled,
    t.settings.knowledge.status.enabled,
  ]);

  const isLargeFile = useMemo(() => {
    return selectedFile ? shouldUseChunkedUpload(selectedFile) : false;
  }, [selectedFile]);

  const hasActiveKnowledgeJobs = useMemo(() => {
    return knowledgeFiles.some((file) =>
      ACTIVE_KNOWLEDGE_JOB_STATUSES.includes(file.parse_status ?? ""),
    );
  }, [knowledgeFiles]);

  const isKnowledgeMutating =
    isUploading ||
    deleteMutation.isPending ||
    reindexMutation.isPending ||
    hasActiveKnowledgeJobs;

  const handleFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0] ?? null;
    setSelectedFile(file);
    setUploadSuccess(false);
    resetUpload();
  };

  const handleUpload = async () => {
    if (!selectedFile) return;
    setUploadSuccess(false);
    try {
      await upload(selectedFile, { reindex: autoReindex });
      setSelectedFile(null);
      setUploadSuccess(true);
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
    } catch {
      // Error is handled by the hook.
    }
  };

  const handleCancelUpload = () => {
    cancelUpload();
    setSelectedFile(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };

  const openEditDialog = (file: KnowledgeFileInfo) => {
    setEditingFile(file);
    setTypeInput(file.type ?? "");
    setCategoriesInput((file.categories ?? []).join(", "));
    setErasInput((file.eras ?? []).join(", "));
    setRegionsInput((file.regions ?? []).join(", "));
    setKeywordsInput((file.keywords ?? []).join(", "));
    setSummaryInput(file.summary ?? "");
  };

  const closeEditDialog = () => {
    setEditingFile(null);
    setTypeInput("");
    setCategoriesInput("");
    setErasInput("");
    setRegionsInput("");
    setKeywordsInput("");
    setSummaryInput("");
  };

  const handleSaveMetadata = async () => {
    if (!editingFile) {
      return;
    }

    await updateMetadataMutation.mutateAsync({
      filename: editingFile.filename,
      payload: {
        type: typeInput.trim() || null,
        categories: splitTagInput(categoriesInput),
        eras: splitTagInput(erasInput),
        regions: splitTagInput(regionsInput),
        keywords: splitTagInput(keywordsInput),
        summary: summaryInput.trim() || null,
      },
    });

    closeEditDialog();
  };

  return (
    <div className="space-y-8">
      <SettingsSection
        title={t.settings.knowledge.title}
        description={t.settings.knowledge.description}
      >
        {isLoading ? (
          <div className="text-muted-foreground text-sm">
            {t.common.loading}
          </div>
        ) : error ? (
          <div>Error: {error.message}</div>
        ) : (
          status && (
            <Item variant="outline" className="w-full">
              <ItemContent>
                <ItemTitle>
                  <div className="flex items-center gap-2">
                    <BookOpenIcon className="size-4" />
                    <span>{statusDescription}</span>
                  </div>
                </ItemTitle>
                <ItemDescription className="text-xs md:text-sm">
                  <span className="grid gap-1 md:grid-cols-3">
                    <span className="block">
                      <span className="font-medium">
                        {t.settings.knowledge.status.docsPath}
                      </span>
                      <span className="ml-1 break-all text-muted-foreground">
                        {status.docs_path}
                      </span>
                    </span>
                    <span className="block">
                      <span className="font-medium">
                        {t.settings.knowledge.status.docCount}
                      </span>
                      <span className="ml-1 text-muted-foreground">
                        {status.doc_count}
                      </span>
                    </span>
                    <span className="block">
                      <span className="font-medium">
                        {t.settings.knowledge.status.collectionName}
                      </span>
                      <span className="ml-1 text-muted-foreground">
                        {status.collection_name}
                      </span>
                    </span>
                  </span>
                </ItemDescription>
              </ItemContent>
            </Item>
          )
        )}
      </SettingsSection>

      <SettingsSection
        title={t.settings.knowledge.actions.reindexTitle}
        description={t.settings.knowledge.actions.reindexDescription}
      >
        <Button
          type="button"
          variant="outline"
          disabled={isKnowledgeMutating}
          onClick={() => reindexMutation.mutate()}
        >
          <RefreshCwIcon className="mr-2 size-4" />
          {reindexMutation.isPending
            ? t.settings.knowledge.actions.reindexing
            : t.settings.knowledge.actions.reindex}
        </Button>
        {reindexMutation.error && (
          <p className="text-destructive mt-2 text-xs md:text-sm">
            {t.settings.knowledge.actions.reindexError}:{" "}
            {reindexMutation.error.message}
          </p>
        )}
        {reindexMutation.isSuccess && !reindexMutation.error && (
          <p className="text-muted-foreground mt-2 text-xs md:text-sm">
            {t.settings.knowledge.actions.reindexSuccess}
          </p>
        )}
      </SettingsSection>

      <SettingsSection
        title={t.settings.knowledge.upload.title}
        description={t.settings.knowledge.upload.description}
      >
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
            <div className="flex flex-col gap-2">
              <div className="flex items-center gap-2">
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".md,.markdown,.pdf,.txt"
                  className="hidden"
                  onChange={handleFileChange}
                  disabled={isKnowledgeMutating}
                />
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => fileInputRef.current?.click()}
                  disabled={isKnowledgeMutating}
                >
                  <UploadIcon className="mr-2 size-4" />
                  {t.settings.knowledge.upload.selectFile}
                </Button>
              </div>
              <div className="text-muted-foreground text-xs md:text-sm">
                {selectedFile ? (
                  <span>
                    {t.settings.knowledge.upload.selectedFile}: {selectedFile.name}
                    <span className="ml-2 text-muted-foreground">
                      ({formatBytes(selectedFile.size)})
                    </span>
                    {isLargeFile && (
                      <span className="ml-2 text-blue-500">(分片上传)</span>
                    )}
                  </span>
                ) : (
                  t.settings.knowledge.upload.noFile
                )}
              </div>
            </div>

            <div className="flex flex-col items-start gap-2 md:items-end">
              <div className="flex items-center gap-2">
                <Switch
                  checked={autoReindex}
                  onCheckedChange={setAutoReindex}
                  disabled={isKnowledgeMutating}
                />
                <span className="text-xs md:text-sm">
                  {t.settings.knowledge.upload.autoReindex}
                </span>
              </div>
              <div className="flex items-center gap-2">
                {isUploading && (
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={handleCancelUpload}
                  >
                    <XIcon className="mr-2 size-4" />
                    取消
                  </Button>
                )}
                <Button
                  type="button"
                  size="sm"
                  disabled={!selectedFile || isKnowledgeMutating}
                  onClick={() => void handleUpload()}
                >
                  {isUploading
                    ? t.settings.knowledge.upload.uploading
                    : t.settings.knowledge.upload.uploadButton}
                </Button>
              </div>
            </div>
          </div>

          {isUploading && uploadProgress && (
            <div className="space-y-2">
              <div className="flex items-center justify-between text-xs text-muted-foreground">
                <span>上传进度</span>
                <span>
                  {formatBytes(uploadProgress.uploadedBytes)} /{" "}
                  {formatBytes(uploadProgress.totalBytes)} (
                  {Math.round(uploadProgress.progress * 100)}%)
                </span>
              </div>
              <Progress value={uploadProgress.progress * 100} className="h-2" />
            </div>
          )}

          {uploadError && (
            <p className="text-destructive text-xs md:text-sm">
              {t.settings.knowledge.upload.error}: {uploadError.message}
            </p>
          )}

          {uploadSuccess && !uploadError && (
            <p className="text-muted-foreground text-xs md:text-sm">
              {t.settings.knowledge.upload.success}
            </p>
          )}

          {hasActiveKnowledgeJobs && (
            <p className="text-muted-foreground text-xs md:text-sm">
              知识库正在解析或重建索引，暂时不能上传、删除或重新索引。
            </p>
          )}
        </div>
      </SettingsSection>

      <SettingsSection
        title={t.settings.knowledge.docs.title}
        description={t.settings.knowledge.docs.description}
      >
        {isFilesLoading ? (
          <div className="text-muted-foreground text-sm">
            {t.common.loading}
          </div>
        ) : filesError ? (
          <div>Error: {filesError.message}</div>
        ) : knowledgeFiles.length === 0 ? (
          <div className="text-muted-foreground text-sm">
            {t.settings.knowledge.docs.empty}
          </div>
        ) : (
          <div className="border-border divide-border rounded-md border text-xs md:text-sm">
            <div className="bg-muted grid grid-cols-[minmax(0,2fr)_minmax(0,2fr)_minmax(0,1fr)_96px] gap-3 border-b px-3 py-2 font-medium">
              <div>{t.settings.knowledge.docs.filename}</div>
              <div>Tag</div>
              <div>{t.settings.knowledge.docs.size}</div>
              <div className="text-right">
                {t.settings.knowledge.docs.actions}
              </div>
            </div>
            <div className="divide-y">
              {knowledgeFiles.map((file) => {
                const tags = buildTags(file);
                const queueStatus = formatQueueStatus(file);
                const editDisabled = ["queued", "queued_ocr", "parsing"].includes(
                  file.parse_status ?? "",
                );

                return (
                  <div
                    key={file.filename}
                    className="grid grid-cols-[minmax(0,2fr)_minmax(0,2fr)_minmax(0,1fr)_96px] items-start gap-3 px-3 py-3"
                  >
                    <div className="min-w-0">
                      <div className="truncate font-medium">{file.filename}</div>
                      {queueStatus && (
                        <div className="text-muted-foreground mt-1 text-[11px]">
                          {queueStatus}
                        </div>
                      )}
                    </div>
                    <div className="flex min-h-9 flex-wrap gap-1">
                      {tags.length > 0 ? (
                        tags.map((tag) => (
                          <Badge key={`${file.filename}-${tag}`} variant="outline">
                            {tag}
                          </Badge>
                        ))
                      ) : (
                        <span className="text-muted-foreground">-</span>
                      )}
                    </div>
                    <div className="text-muted-foreground">
                      {formatBytes(file.size)}
                    </div>
                    <div className="flex justify-end gap-1">
                      <Button
                        type="button"
                        size="icon"
                        variant="ghost"
                        disabled={editDisabled || updateMetadataMutation.isPending}
                        onClick={() => openEditDialog(file)}
                      >
                        <PencilIcon className="size-4" />
                      </Button>
                      <Button
                        type="button"
                        size="icon"
                        variant="ghost"
                        className="text-destructive hover:text-destructive"
                        disabled={isKnowledgeMutating}
                        onClick={() => deleteMutation.mutate(file.filename)}
                      >
                        <Trash2Icon className="size-4" />
                      </Button>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </SettingsSection>

      <Dialog open={Boolean(editingFile)} onOpenChange={(open) => !open && closeEditDialog()}>
        <DialogContent className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>编辑书籍标签</DialogTitle>
            <DialogDescription>
              这里改的是书级 metadata。多个标签可用英文逗号、中文逗号或换行分隔。
            </DialogDescription>
          </DialogHeader>

          <div className="grid gap-4">
            <div className="grid gap-2">
              <label className="text-sm font-medium">类型</label>
              <Input
                value={typeInput}
                onChange={(event) => setTypeInput(event.target.value)}
                placeholder="core / specialized / reference"
              />
            </div>

            <div className="grid gap-2 md:grid-cols-2">
              <div className="grid gap-2">
                <label className="text-sm font-medium">分类</label>
                <Input
                  value={categoriesInput}
                  onChange={(event) => setCategoriesInput(event.target.value)}
                  placeholder="架构, 运维, API"
                />
              </div>
              <div className="grid gap-2">
                <label className="text-sm font-medium">时代</label>
                <Input
                  value={erasInput}
                  onChange={(event) => setErasInput(event.target.value)}
                  placeholder="先秦, 汉, 唐, 明清"
                />
              </div>
            </div>

            <div className="grid gap-2 md:grid-cols-2">
              <div className="grid gap-2">
                <label className="text-sm font-medium">地域</label>
                <Input
                  value={regionsInput}
                  onChange={(event) => setRegionsInput(event.target.value)}
                  placeholder="全国, 江南, 四川"
                />
              </div>
              <div className="grid gap-2">
                <label className="text-sm font-medium">关键词</label>
                <Input
                  value={keywordsInput}
                  onChange={(event) => setKeywordsInput(event.target.value)}
                  placeholder="盐政, 赋税, 科举"
                />
              </div>
            </div>

            <div className="grid gap-2">
              <label className="text-sm font-medium">摘要</label>
              <Textarea
                value={summaryInput}
                onChange={(event) => setSummaryInput(event.target.value)}
                placeholder="补充这本书的大致主题和覆盖范围"
                rows={5}
              />
            </div>

            {updateMetadataMutation.error && (
              <p className="text-destructive text-sm">
                保存失败: {updateMetadataMutation.error.message}
              </p>
            )}
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={closeEditDialog}
              disabled={updateMetadataMutation.isPending}
            >
              取消
            </Button>
            <Button
              type="button"
              onClick={() => void handleSaveMetadata()}
              disabled={updateMetadataMutation.isPending}
            >
              {updateMetadataMutation.isPending ? "保存中..." : "保存"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
