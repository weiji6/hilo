"use client";

import { ArrowRightIcon, CheckIcon, Loader2Icon, PlusIcon, SparklesIcon, UploadIcon, XIcon } from "lucide-react";
import type { Dispatch, SetStateAction } from "react";

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
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import type { FolderReorganizeEvent, FolderReorganizeOp } from "@/core/knowledge/api";

import {
  documentTypeOptions,
  getFolderDisplayName,
  knowledgeTypeOptions,
  languageOptions,
  layoutOptions,
  type DocumentTypeHint,
  type LanguageHint,
  type LayoutHint,
  type MetadataFormState,
  type UploadFormState,
} from "./knowledge-management-page.utils";

export function UploadDialog({
  open,
  onOpenChange,
  form,
  setForm,
  targetMode,
  targetFolderLabel,
  onPickFiles,
  onCancel,
  onSubmit,
  isPending,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  form: UploadFormState;
  setForm: Dispatch<SetStateAction<UploadFormState>>;
  targetMode: "global" | "personal";
  targetFolderLabel: string;
  onPickFiles: () => void;
  onCancel: () => void;
  onSubmit: () => void;
  isPending: boolean;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl border-accent/20 bg-white shadow-xl">
        <DialogHeader>
          <DialogTitle className="text-slate-900">
            上传到{targetFolderLabel}
          </DialogTitle>
          <DialogDescription className="text-slate-600">
            {targetMode === "global"
              ? "文件会进入当前系统文件夹。"
              : "文件会进入当前个人文件夹。"}
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-4">
          <div className="rounded-xl border border-accent/10 bg-white p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <div className="text-sm font-medium text-slate-900">选择文件</div>
                <div className="text-xs text-slate-500">
                  PDF、Markdown、Office 文档都可以批量上传。
                </div>
              </div>
              <Button
                type="button"
                variant="outline"
                className="border-primary/20 bg-white text-primary hover:bg-primary/5"
                onClick={onPickFiles}
                disabled={isPending}
              >
                选择文件
              </Button>
            </div>

            <div className="mt-3 rounded-lg border border-dashed border-accent/20 bg-stone-50/50 p-3">
              {form.files.length === 0 ? (
                <div className="text-sm text-slate-500">还没有选择文件。</div>
              ) : (
                <div className="space-y-1">
                  <div className="text-sm font-medium text-slate-900">
                    已选择 {form.files.length} 个文件
                  </div>
                  <div className="max-h-28 space-y-1 overflow-auto text-xs text-slate-600">
                    {form.files.map((file) => (
                      <div key={`${file.name}-${file.size}`}>{file.name}</div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>

          <div className="grid gap-3 rounded-xl border border-accent/10 bg-white p-4 md:grid-cols-3">
            <SelectField
              label="文档类型"
              value={form.documentTypeHint}
              options={documentTypeOptions}
              onValueChange={(value) =>
                setForm((current) => ({
                  ...current,
                  documentTypeHint: value as DocumentTypeHint,
                }))
              }
            />
            <SelectField
              label="语言线索"
              value={form.languageHint}
              options={languageOptions}
              onValueChange={(value) =>
                setForm((current) => ({
                  ...current,
                  languageHint: value as LanguageHint,
                }))
              }
            />
            <SelectField
              label="版式线索"
              value={form.layoutHint}
              options={layoutOptions}
              onValueChange={(value) =>
                setForm((current) => ({
                  ...current,
                  layoutHint: value as LayoutHint,
                }))
              }
            />
          </div>
        </div>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={onCancel} disabled={isPending}>
            取消
          </Button>
          <Button
            type="button"
            className="bg-primary text-white hover:bg-primary/90"
            onClick={onSubmit}
            disabled={isPending || form.files.length === 0}
          >
            {isPending ? <Loader2Icon className="size-4 animate-spin" /> : <UploadIcon className="size-4" />}
            开始上传
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function CreateFolderDialog({
  open,
  onOpenChange,
  title,
  description,
  value,
  onValueChange,
  onSubmit,
  isPending,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  value: string;
  onValueChange: (value: string) => void;
  onSubmit: () => void;
  isPending: boolean;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md border-accent/20 bg-white shadow-xl">
        <DialogHeader>
          <DialogTitle className="text-slate-900">{title}</DialogTitle>
          <DialogDescription className="text-slate-600">{description}</DialogDescription>
        </DialogHeader>

        <div className="grid gap-2">
          <label className="text-sm font-medium text-slate-800">文件夹名称</label>
          <Input
            value={value}
            onChange={(event) => onValueChange(event.target.value)}
            placeholder="例如：系统架构"
            className="bg-white"
          />
        </div>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={isPending}>
            取消
          </Button>
          <Button
            type="button"
            className="bg-primary text-white hover:bg-primary/90"
            onClick={onSubmit}
            disabled={isPending}
          >
            {isPending ? <Loader2Icon className="size-4 animate-spin" /> : <PlusIcon className="size-4" />}
            创建
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function MoveFileDialog({
  open,
  onOpenChange,
  folders,
  value,
  onValueChange,
  onSubmit,
  isPending,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  folders: string[];
  value: string;
  onValueChange: (value: string) => void;
  onSubmit: () => void;
  isPending: boolean;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md border-accent/20 bg-white shadow-xl">
        <DialogHeader>
          <DialogTitle className="text-slate-900">移动文件</DialogTitle>
          <DialogDescription className="text-slate-600">
            将个人文件移动到另一个个人文件夹。
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-2">
          <label className="text-sm font-medium text-slate-800">目标文件夹</label>
          <Select value={value} onValueChange={onValueChange}>
            <SelectTrigger className="bg-white text-sm">
              <SelectValue placeholder="选择文件夹" />
            </SelectTrigger>
            <SelectContent>
              {folders.map((folder) => (
                <SelectItem key={folder} value={folder}>
                  {getFolderDisplayName(folder)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={isPending}>
            取消
          </Button>
          <Button
            type="button"
            className="bg-primary text-white hover:bg-primary/90"
            onClick={onSubmit}
            disabled={isPending || !value}
          >
            {isPending ? <Loader2Icon className="size-4 animate-spin" /> : <ArrowRightIcon className="size-4" />}
            移动
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function MetadataDialog({
  open,
  onOpenChange,
  form,
  setForm,
  errorMessage,
  isSaving,
  isRegenerating,
  onRegenerate,
  onCancel,
  onSave,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  form: MetadataFormState;
  setForm: Dispatch<SetStateAction<MetadataFormState>>;
  errorMessage?: string | null;
  isSaving: boolean;
  isRegenerating: boolean;
  onRegenerate: () => void;
  onCancel: () => void;
  onSave: () => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl border-accent/20 bg-white shadow-xl">
        <DialogHeader>
          <DialogTitle className="text-slate-900">修改书籍标签</DialogTitle>
          <DialogDescription className="text-slate-600">
            修改的是书级 metadata，会影响书目路由和候选排序，但不会重跑 OCR 或向量化。
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-4">
          <div className="grid gap-3 md:grid-cols-2">
            <SelectField
              label="检索类型"
              value={form.type}
              options={knowledgeTypeOptions}
              onValueChange={(value) =>
                setForm((current) => ({
                  ...current,
                  type: value as MetadataFormState["type"],
                }))
              }
            />

            <div className="grid gap-2">
              <label className="text-sm font-medium text-slate-800">文件夹路径</label>
              <Input
                value={form.folder}
                onChange={(event) =>
                  setForm((current) => ({ ...current, folder: event.target.value }))
                }
                placeholder="例如：技术文档/架构"
                className="bg-white"
              />
              <p className="text-xs text-slate-500">
                使用 `/` 表示多级目录；留空时会按首个标签回退归档。
              </p>
            </div>
          </div>

          <div className="grid gap-3 md:grid-cols-2">
            <SelectField
              label="语言线索"
              value={form.languageHint}
              options={languageOptions}
              onValueChange={(value) =>
                setForm((current) => ({
                  ...current,
                  languageHint: value as LanguageHint,
                }))
              }
            />
            <SelectField
              label="版式线索"
              value={form.layoutHint}
              options={layoutOptions}
              onValueChange={(value) =>
                setForm((current) => ({
                  ...current,
                  layoutHint: value as LayoutHint,
                }))
              }
            />
          </div>

          <div className="grid gap-2">
            <SelectField
              label="文档类型线索"
              value={form.documentTypeHint}
              options={documentTypeOptions}
              onValueChange={(value) =>
                setForm((current) => ({
                  ...current,
                  documentTypeHint: value as DocumentTypeHint,
                }))
              }
            />
            <p className="text-xs text-slate-500">
              修改线索后不会自动重跑 OCR；保存后可直接点击“重新入库”验证召回效果。
            </p>
          </div>

          <div className="grid gap-3 md:grid-cols-2">
            <TextField
              label="分类"
              value={form.categories}
              placeholder="架构, 运维, API"
              onChange={(value) => setForm((current) => ({ ...current, categories: value }))}
            />
            <TextField
              label="时代"
              value={form.eras}
              placeholder="先秦, 唐宋, 明清"
              onChange={(value) => setForm((current) => ({ ...current, eras: value }))}
            />
          </div>

          <div className="grid gap-3 md:grid-cols-2">
            <TextField
              label="地域"
              value={form.regions}
              placeholder="全国, 江南, 四川"
              onChange={(value) => setForm((current) => ({ ...current, regions: value }))}
            />
            <TextField
              label="关键词"
              value={form.keywords}
              placeholder="赋税, 盐政, 漕运"
              onChange={(value) => setForm((current) => ({ ...current, keywords: value }))}
            />
          </div>

          <div className="grid gap-2">
            <label className="text-sm font-medium text-slate-800">摘要</label>
            <Textarea
              value={form.summary}
              onChange={(event) =>
                setForm((current) => ({ ...current, summary: event.target.value }))
              }
              placeholder="补充这本书的覆盖范围或定位"
              rows={5}
              className="bg-white"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="grid gap-2">
              <label className="text-sm font-medium text-slate-800">作者</label>
              <Input
                value={form.author}
                onChange={(event) =>
                  setForm((current) => ({ ...current, author: event.target.value }))
                }
                placeholder="张之洞"
                className="bg-white"
              />
            </div>
            <div className="grid gap-2">
              <label className="text-sm font-medium text-slate-800">出版社</label>
              <Input
                value={form.publisher}
                onChange={(event) =>
                  setForm((current) => ({ ...current, publisher: event.target.value }))
                }
                placeholder="商务印书馆"
                className="bg-white"
              />
            </div>
          </div>

          {errorMessage ? <p className="text-sm text-destructive">{errorMessage}</p> : null}
        </div>

        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            onClick={onRegenerate}
            disabled={isSaving || isRegenerating}
          >
            {isRegenerating ? <Loader2Icon className="size-4 animate-spin" /> : null}
            AI 生成
          </Button>
          <Button
            type="button"
            variant="outline"
            onClick={onCancel}
            disabled={isSaving || isRegenerating}
          >
            取消
          </Button>
          <Button
            type="button"
            className="bg-primary text-white hover:bg-primary/90"
            onClick={onSave}
            disabled={isSaving || isRegenerating}
          >
            {isSaving ? <Loader2Icon className="size-4 animate-spin" /> : null}
            保存
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// Batch Generate Summary Dialog
// ---------------------------------------------------------------------------

export interface BatchSummaryResult {
  filename: string;
  title: string;
  success: boolean;
  error?: string;
}

export function BatchGenerateSummaryDialog({
  open,
  onOpenChange,
  results,
  total,
  isRunning,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  results: BatchSummaryResult[];
  total: number;
  isRunning: boolean;
}) {
  const current = results.length;
  const successCount = results.filter((r) => r.success).length;
  const failCount = results.filter((r) => !r.success).length;

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!isRunning) onOpenChange(o); }}>
      <DialogContent className="max-w-xl border-accent/20 bg-white shadow-xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-slate-900">
            <SparklesIcon className="size-4 text-primary" />
            批量生成摘要
          </DialogTitle>
          <DialogDescription className="text-slate-600">
            {isRunning
              ? `正在处理第 ${current} / ${total} 本（每本最多重试 3 次），请稍候…`
              : current === 0
              ? "准备就绪"
              : `完成：成功 ${successCount} 本${failCount > 0 ? `，失败 ${failCount} 本` : ""}`}
          </DialogDescription>
        </DialogHeader>

        <div className="max-h-80 overflow-y-auto rounded-lg border border-stone-100 bg-stone-50 p-3 text-sm font-mono">
          {isRunning && current === 0 && (
            <div className="flex items-center gap-2 text-stone-500">
              <Loader2Icon className="size-3.5 animate-spin shrink-0" />
              <span>正在初始化…</span>
            </div>
          )}

          {results.map((result, i) => (
            <div
              key={result.filename}
              className={`flex items-start gap-2 py-1 ${i > 0 ? "border-t border-stone-200/60" : ""}`}
            >
              <span className="mt-0.5 shrink-0">
                {result.success ? (
                  <CheckIcon className="size-3.5 text-green-600" />
                ) : (
                  <XIcon className="size-3.5 text-red-500" />
                )}
              </span>
              <div className="min-w-0 flex-1">
                <div className="truncate text-stone-700">{result.title || result.filename}</div>
                {!result.success && result.error && (
                  <div className="text-xs text-red-500">{result.error}</div>
                )}
              </div>
            </div>
          ))}

          {isRunning && current > 0 && (
            <div className="flex items-center gap-2 border-t border-stone-200/60 py-1 text-stone-400">
              <Loader2Icon className="size-3.5 animate-spin shrink-0" />
              <span>处理中…</span>
            </div>
          )}
        </div>

        <DialogFooter>
          <Button
            type="button"
            className="bg-primary text-white hover:bg-primary/90"
            onClick={() => onOpenChange(false)}
            disabled={isRunning}
          >
            {isRunning ? <Loader2Icon className="mr-2 size-4 animate-spin" /> : null}
            {isRunning ? "生成中…" : "完成"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// Reorganize Folder Dialog
// ---------------------------------------------------------------------------

function opLabel(op: FolderReorganizeOp): string {
  if (op.op === "move") {
    const dest = op.target_parent ?? "根目录";
    return `移动  "${op.path}"  →  "${dest}/${op.path.split("/").at(-1)}"`;
  }
  if (op.op === "merge") {
    return `合并  "${op.source_path}"  →  "${op.target_path}"`;
  }
  return `重命名  "${op.path}"  →  "${op.new_path}"`;
}

export function ReorganizeFolderDialog({
  open,
  onOpenChange,
  events,
  isRunning,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  events: FolderReorganizeEvent[];
  isRunning: boolean;
}) {
  // Derive state from the event stream
  const planEvent = events.find(
    (e): e is Extract<FolderReorganizeEvent, { type: "plan" }> => e.type === "plan",
  );
  const doneEvent = events.find(
    (e): e is Extract<FolderReorganizeEvent, { type: "done" }> => e.type === "done",
  );
  const errorEvent = events.find(
    (e): e is Extract<FolderReorganizeEvent, { type: "error" }> => e.type === "error",
  );
  const progressEvents = events.filter(
    (e): e is Extract<FolderReorganizeEvent, { type: "progress" }> => e.type === "progress",
  );

  const operations = planEvent?.operations ?? [];
  const isDone = Boolean(doneEvent);
  const hasError = Boolean(errorEvent);
  const isAnalyzing = isRunning && !planEvent;

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!isRunning) onOpenChange(o); }}>
      <DialogContent className="max-w-xl border-accent/20 bg-white shadow-xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-slate-900">
            <SparklesIcon className="size-4 text-primary" />
            AI 目录整理
          </DialogTitle>
          <DialogDescription className="text-slate-600">
            {isAnalyzing
              ? "正在分析目录结构，请稍候…"
              : isRunning
              ? `共 ${operations.length} 个操作，正在逐步执行…`
              : isDone
              ? doneEvent?.message
              : hasError
              ? "整理失败"
              : "准备就绪"}
          </DialogDescription>
        </DialogHeader>

        <div className="max-h-96 overflow-y-auto rounded-lg border border-stone-100 bg-stone-50 p-3 text-sm font-mono">
          {/* Analyzing phase */}
          {isAnalyzing && (
            <div className="flex items-center gap-2 text-stone-500">
              <Loader2Icon className="size-3.5 animate-spin shrink-0" />
              <span>正在分析目录结构…</span>
            </div>
          )}

          {/* Error */}
          {hasError && (
            <div className="flex items-start gap-2 text-red-600">
              <XIcon className="mt-0.5 size-3.5 shrink-0" />
              <span>{errorEvent?.message}</span>
            </div>
          )}

          {/* Operation list */}
          {operations.map((op, i) => {
            const prog = progressEvents.find((e) => e.step === i + 1);
            const isPending = isRunning && !prog && Boolean(planEvent);
            const isCurrent = isRunning && !prog && progressEvents.length === i;
            return (
              <div key={i} className={`flex items-start gap-2 py-1 ${i > 0 ? "border-t border-stone-200/60" : ""}`}>
                <span className="mt-0.5 shrink-0">
                  {prog?.success === true ? (
                    <CheckIcon className="size-3.5 text-green-600" />
                  ) : prog?.success === false ? (
                    <XIcon className="size-3.5 text-red-500" />
                  ) : isCurrent ? (
                    <Loader2Icon className="size-3.5 animate-spin text-primary" />
                  ) : (
                    <span className="inline-block size-3.5 rounded-full border border-stone-300 bg-white" />
                  )}
                </span>
                <div className="min-w-0 flex-1">
                  <div className={`truncate ${isPending ? "text-stone-400" : "text-stone-700"}`}>
                    {opLabel(op)}
                  </div>
                  {op.reason && (
                    <div className="truncate text-xs text-stone-400">{op.reason}</div>
                  )}
                  {prog?.success === false && prog.error && (
                    <div className="text-xs text-red-500">{prog.error}</div>
                  )}
                </div>
              </div>
            );
          })}

          {/* Done summary */}
          {isDone && (
            <div className="mt-2 border-t border-stone-200 pt-2 text-xs text-stone-500">
              完成：执行 {doneEvent?.executed} 个，跳过 {doneEvent?.skipped} 个
            </div>
          )}
        </div>

        <DialogFooter>
          <Button
            type="button"
            className="bg-primary text-white hover:bg-primary/90"
            onClick={() => onOpenChange(false)}
            disabled={isRunning}
          >
            {isRunning ? <Loader2Icon className="mr-2 size-4 animate-spin" /> : null}
            {isRunning ? "整理中…" : "完成"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function SelectField({
  label,
  value,
  options,
  onValueChange,
}: {
  label: string;
  value: string;
  options: Array<{ value: string; label: string }>;
  onValueChange: (value: string) => void;
}) {
  return (
    <div className="grid gap-2">
      <label className="text-sm font-medium text-slate-800">{label}</label>
      <Select value={value} onValueChange={onValueChange}>
        <SelectTrigger className="bg-white text-sm">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {options.map((option) => (
            <SelectItem key={option.value} value={option.value}>
              {option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

function TextField({
  label,
  value,
  placeholder,
  onChange,
}: {
  label: string;
  value: string;
  placeholder: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className="grid gap-2">
      <label className="text-sm font-medium text-slate-800">{label}</label>
      <Input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        className="bg-white"
      />
    </div>
  );
}
