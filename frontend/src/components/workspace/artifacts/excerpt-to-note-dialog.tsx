"use client";

import { FilePlus2Icon, Loader2Icon, NotebookPenIcon } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

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
import { ScrollArea } from "@/components/ui/scroll-area";
import type { UserKnowledgeRecord } from "@/core/knowledge/user-api";
import {
  useAppendExcerptToUserNote,
  useCreateUserDerivedKnowledge,
  useUserKnowledgeRecords,
} from "@/core/knowledge/user-hooks";
import { cn } from "@/lib/utils";

type ExcerptParagraphPayload = {
  pdfPageNo: number | null;
  pageNo: number | null;
  paragraphNo: number | null;
  text: string;
};

function buildLocationLabel(paragraph: ExcerptParagraphPayload) {
  const parts: string[] = [];
  if (paragraph.pdfPageNo) {
    parts.push(`PDF 第 ${paragraph.pdfPageNo} 页`);
  } else if (paragraph.pageNo) {
    parts.push(`第 ${paragraph.pageNo} 页`);
  }
  if (paragraph.paragraphNo) {
    parts.push(`第 ${paragraph.paragraphNo} 段`);
  }
  return parts.join(" · ");
}

function getRecordTitle(record: UserKnowledgeRecord) {
  const displayTitle = record.display_title?.trim();
  if (displayTitle) {
    return displayTitle;
  }
  const title = record.title?.trim();
  return title && title.length > 0 ? title : "未命名笔记";
}

function sortNotes(records: UserKnowledgeRecord[]) {
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

function isAppendableRecord(record: UserKnowledgeRecord) {
  return !["upload", "import_ref"].includes(record.source_kind);
}

function buildDefaultNewNoteTitle(originTitle: string) {
  const trimmed = originTitle.trim();
  return trimmed ? `${trimmed} 摘录笔记` : "摘录笔记";
}

export function ExcerptToNoteDialog({
  open,
  onOpenChange,
  originTitle,
  originFilename,
  knowledgeSpaceId,
  originScope,
  originDocId,
  paragraph,
  onSuccess,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  originTitle: string;
  originFilename: string;
  knowledgeSpaceId?: string | null;
  originScope?: string | null;
  originDocId?: string | null;
  paragraph: ExcerptParagraphPayload | null;
  onSuccess?: (record: UserKnowledgeRecord) => void;
}) {
  const recordsQuery = useUserKnowledgeRecords(knowledgeSpaceId);
  const createNoteMutation = useCreateUserDerivedKnowledge();
  const appendMutation = useAppendExcerptToUserNote();
  const [selectedRecordId, setSelectedRecordId] = useState<string | null>(null);
  const [newNoteTitle, setNewNoteTitle] = useState("");

  const noteRecords = useMemo(
    () =>
      sortNotes((recordsQuery.data?.records ?? []).filter(isAppendableRecord)),
    [recordsQuery.data?.records],
  );

  useEffect(() => {
    if (!open) {
      return;
    }
    setNewNoteTitle(buildDefaultNewNoteTitle(originTitle));
  }, [open, originTitle]);

  useEffect(() => {
    if (!open || noteRecords.length === 0) {
      setSelectedRecordId(null);
      return;
    }
    setSelectedRecordId((current) =>
      current && noteRecords.some((record) => record.id === current)
        ? current
        : (noteRecords[0]?.id ?? null),
    );
  }, [noteRecords, open]);

  const isPending = createNoteMutation.isPending || appendMutation.isPending;
  const excerptPreview = paragraph?.text.trim() ?? "";
  const locationLabel = paragraph ? buildLocationLabel(paragraph) : "";

  const appendToRecord = async (record: UserKnowledgeRecord) => {
    if (!paragraph) {
      return;
    }
    const result = await appendMutation.mutateAsync({
      recordId: record.id,
      excerpt: {
        excerptText: paragraph.text,
        originScope,
        originDocId,
        originFilename,
        originAnchor: {
          pdf_page_no: paragraph.pdfPageNo,
          page_no: paragraph.pageNo,
          paragraph_no: paragraph.paragraphNo,
          text: paragraph.text,
        },
      },
    });
    toast.success(`已追加到《${getRecordTitle(result.record)}》末尾`);
    onSuccess?.(result.record);
    onOpenChange(false);
  };

  const handleAppend = async () => {
    const target = noteRecords.find((record) => record.id === selectedRecordId);
    if (!target) {
      toast.error("请先选择一个笔记");
      return;
    }
    try {
      await appendToRecord(target);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "追加摘录失败");
    }
  };

  const handleCreateAndAppend = async () => {
    if (!paragraph) {
      return;
    }
    try {
      const created = await createNoteMutation.mutateAsync({
        title: newNoteTitle.trim() || buildDefaultNewNoteTitle(originTitle),
        content: "",
        sourceKind: "note",
        knowledgeSpaceId,
      });
      await appendToRecord(created.record);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "创建笔记失败");
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl border-stone-200 bg-white p-0 shadow-[0_32px_80px_-40px_rgba(28,25,23,0.45)]">
        <DialogHeader className="border-b border-stone-200 px-6 pt-6 pb-4">
          <DialogTitle>加入到哪一卷笔记？</DialogTitle>
          <DialogDescription className="space-y-1 text-left text-stone-500">
            <div>{originFilename}</div>
            {locationLabel ? <div>{locationLabel}</div> : null}
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-5 px-6 py-5">
          <div className="rounded-2xl border border-stone-200 bg-stone-50 px-4 py-3">
            <div className="mb-2 text-[11px] font-semibold tracking-[0.18em] text-stone-500 uppercase">
              本次摘录
            </div>
            <div className="line-clamp-5 text-sm leading-7 whitespace-pre-wrap text-stone-700">
              {excerptPreview || "暂无摘录内容"}
            </div>
          </div>

          <div className="grid gap-3">
            <div className="flex items-center justify-between">
              <div className="text-sm font-medium text-stone-800">已有笔记</div>
              <div className="text-xs text-stone-400">
                {noteRecords.length} 卷
              </div>
            </div>

            <ScrollArea className="h-64 rounded-2xl border border-stone-200 bg-white">
              {recordsQuery.isLoading ? (
                <div className="flex h-64 items-center justify-center gap-2 text-sm text-stone-500">
                  <Loader2Icon className="size-4 animate-spin" />
                  正在装载笔记目录...
                </div>
              ) : noteRecords.length === 0 ? (
                <div className="flex h-64 flex-col items-center justify-center gap-3 px-6 text-center">
                  <NotebookPenIcon className="size-8 text-stone-300" />
                  <div className="text-sm text-stone-500">
                    还没有可追加的笔记，直接新建一卷吧。
                  </div>
                </div>
              ) : (
                <div className="p-2">
                  {noteRecords.map((record) => {
                    const isSelected = record.id === selectedRecordId;
                    return (
                      <button
                        key={record.id}
                        type="button"
                        onClick={() => setSelectedRecordId(record.id)}
                        className={cn(
                          "flex w-full flex-col items-start gap-1 rounded-xl border px-4 py-3 text-left transition-all",
                          isSelected
                            ? "border-primary bg-primary/5 text-primary"
                            : "border-transparent text-stone-700 hover:border-stone-200 hover:bg-stone-50",
                        )}
                      >
                        <div className="text-sm leading-6 font-medium">
                          {getRecordTitle(record)}
                        </div>
                        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-stone-400">
                          <span>
                            {record.folder_path?.trim() &&
                            record.folder_path.trim().length > 0
                              ? record.folder_path.trim()
                              : "未分类"}
                          </span>
                          <span>
                            {record.updated_at
                              ? new Date(record.updated_at).toLocaleDateString(
                                  "zh-CN",
                                )
                              : ""}
                          </span>
                        </div>
                      </button>
                    );
                  })}
                </div>
              )}
            </ScrollArea>
          </div>

          <div className="rounded-2xl border border-dashed border-stone-300 bg-stone-50/70 px-4 py-4">
            <div className="mb-3 text-sm font-medium text-stone-800">
              或者新建一卷再加入
            </div>
            <div className="flex flex-col gap-3 sm:flex-row">
              <Input
                value={newNoteTitle}
                onChange={(event) => setNewNoteTitle(event.target.value)}
                placeholder="新笔记标题"
                className="h-11 border-stone-200 bg-white"
              />
              <Button
                type="button"
                variant="outline"
                className="h-11 shrink-0 border-stone-300 bg-white"
                disabled={isPending || !paragraph}
                onClick={() => void handleCreateAndAppend()}
              >
                {isPending ? (
                  <Loader2Icon className="size-4 animate-spin" />
                ) : (
                  <FilePlus2Icon className="size-4" />
                )}
                新建后加入
              </Button>
            </div>
          </div>
        </div>

        <DialogFooter className="border-t border-stone-200 px-6 py-4">
          <Button
            type="button"
            variant="outline"
            className="border-stone-300"
            onClick={() => onOpenChange(false)}
            disabled={isPending}
          >
            取消
          </Button>
          <Button
            type="button"
            disabled={isPending || !selectedRecordId || !paragraph}
            onClick={() => void handleAppend()}
          >
            {isPending ? <Loader2Icon className="size-4 animate-spin" /> : null}
            追加到所选笔记尾部
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
