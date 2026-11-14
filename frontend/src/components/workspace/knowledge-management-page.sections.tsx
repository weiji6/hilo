"use client";

import {
  BookmarkPlusIcon,
  BookOpenIcon,
  CheckSquareIcon,
  CheckIcon,
  ChevronDownIcon,
  ChevronRightIcon,
  FileIcon,
  FolderIcon,
  Loader2Icon,
  PencilIcon,
  PlusIcon,
  RefreshCwIcon,
  SearchIcon,
  SparklesIcon,
  SquareIcon,
  Trash2Icon,
} from "lucide-react";
import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

import {
  canOpenManagedFile,
  canReparseManagedFile,
  canRetryManagedFile,
  formatCompactTime,
  getCoverTone,
  getFolderDisplayName,
  getManagedFileCoverImageUrl,
  knowledgeTypeLabel,
  statusLabel,
  type FolderTreeNode,
  type ManagedKnowledgeFile,
} from "./knowledge-management-page.utils";

export function FolderTreeBranch({
  node,
  selectedPath,
  expandedPaths,
  onSelect,
  onToggle,
  depth = 0,
}: {
  node: FolderTreeNode;
  selectedPath: string;
  expandedPaths: string[];
  onSelect: (path: string) => void;
  onToggle: (path: string) => void;
  depth?: number;
}) {
  const isExpanded = expandedPaths.includes(node.path);
  const isSelected = selectedPath === node.path;
  const hasChildren = node.children.length > 0;

  return (
    <div>
      <button
        type="button"
        className={cn(
          "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm transition font-serif",
          isSelected
            ? "bg-primary/10 text-primary font-bold"
            : "text-stone-700 hover:bg-stone-50",
        )}
        style={{ paddingLeft: `${8 + depth * 14}px` }}
        onClick={() => onSelect(node.path)}
      >
        <span
          className="inline-flex size-4 shrink-0 items-center justify-center text-slate-400"
          onClick={(event) => {
            event.stopPropagation();
            if (hasChildren) {
              onToggle(node.path);
            }
          }}
        >
          {hasChildren ? (
            isExpanded ? <ChevronDownIcon className="size-3.5" /> : <ChevronRightIcon className="size-3.5" />
          ) : (
            <span className="size-3.5" />
          )}
        </span>
        <FolderIcon className="size-4 shrink-0 text-accent/80" />
        <span className="min-w-0 flex-1 truncate">{node.name}</span>
        <span className="shrink-0 text-[10px] text-stone-400 font-sans">({node.fileCount})</span>
      </button>

      {hasChildren && isExpanded ? (
        <div className="mt-0.5">
          {node.children.map((child) => (
            <FolderTreeBranch
              key={child.path}
              node={child}
              selectedPath={selectedPath}
              expandedPaths={expandedPaths}
              onSelect={onSelect}
              onToggle={onToggle}
              depth={depth + 1}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}

export function KnowledgeManagementHero({
  searchQuery,
  onSearchQueryChange,
  selectedFolderPath,
  systemFolderTree,
  onSelectFolder,
}: {
  searchQuery: string;
  onSearchQueryChange: (value: string) => void;
  selectedFolderPath: string;
  systemFolderTree: FolderTreeNode[];
  onSelectFolder: (path: string) => void;
}) {
  return (
    <section className="relative w-full shrink-0 overflow-hidden bg-transparent px-6 pb-2 pt-6">
      <div className="absolute inset-x-0 top-0 h-px bg-primary/5"></div>
      
      <div className="z-10 flex w-full min-w-0 flex-col">
        <div className="w-full overflow-hidden rounded-md border border-accent/20 bg-white/40 shadow-sm backdrop-blur-sm transition-all focus-within:border-accent/40 focus-within:shadow-md">
          <div className="relative h-12">
              <SearchIcon className="pointer-events-none absolute left-4 top-1/2 size-4 -translate-y-1/2 text-accent/60" />
              <Input
                value={searchQuery}
                onChange={(event) => onSearchQueryChange(event.target.value)}
                placeholder="请输入书名、标签或文件名进行馆藏检索..."
                className="h-full border-none bg-transparent pl-11 text-sm font-serif shadow-none focus-visible:ring-0 placeholder:text-stone-400"
              />
          </div>

          <div className="flex flex-wrap items-center gap-x-8 gap-y-3 border-t border-accent/10 bg-white/10 p-4 px-8 select-none overflow-x-auto">
            <CategoryCheckbox
              active={selectedFolderPath === "all"}
              label="全部属性"
              onClick={() => onSelectFolder("all")}
            />
            <div className="h-4 w-px bg-accent/20 mx-2" />
            {systemFolderTree.map((folderNode) => (
              <CategoryFolderFilter
                key={folderNode.path}
                node={folderNode}
                selectedPath={selectedFolderPath}
                onSelectFolder={onSelectFolder}
              />
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

export function KnowledgeManagementSidebar({
  folderTree,
  selectedFolderPath,
  expandedFolderPaths,
  onSelectFolder,
  onToggleFolder,
  selectedFolderNode,
  onDeleteFolder,
}: {
  folderTree: FolderTreeNode[];
  selectedFolderPath: string;
  expandedFolderPaths: string[];
  onSelectFolder: (path: string) => void;
  onToggleFolder: (path: string) => void;
  selectedFolderNode: FolderTreeNode | null;
  onDeleteFolder: () => void;
}) {
  return (
    <aside className="flex w-full shrink-0 flex-col border-b border-slate-200 bg-white md:w-80 md:border-b-0 md:border-r">
      <div className="border-b border-slate-100 px-4 py-4">
        <button
          type="button"
          onClick={() => onSelectFolder("all")}
          className={cn(
            "flex w-full items-center justify-between rounded-md px-3 py-2 text-left text-sm transition font-serif",
            selectedFolderPath === "all"
              ? "bg-primary/10 text-primary font-bold shadow-sm"
              : "text-stone-700 hover:bg-stone-50",
          )}
        >
          <span>全部资料</span>
          <span className="text-[10px] text-stone-400 font-sans">根目录</span>
        </button>
      </div>

      <div className="flex-1 space-y-2 overflow-y-auto px-3 py-4">
        {folderTree.map((node) => (
          <FolderTreeBranch
            key={node.path}
            node={node}
            selectedPath={selectedFolderPath}
            expandedPaths={expandedFolderPaths}
            onSelect={onSelectFolder}
            onToggle={onToggleFolder}
          />
        ))}
      </div>

      {selectedFolderNode ? (
        <div className="border-t border-accent/10 px-4 py-4">
          <div className="rounded-md border border-accent/20 bg-accent/5 p-3">
            <div className="text-sm font-bold text-stone-900 font-serif">
              {getFolderDisplayName(selectedFolderNode.name)}
            </div>
            <div className="mt-1 text-[10px] text-stone-500 font-sans">
              当前目录共 {selectedFolderNode.fileCount} 份资料
            </div>
            {selectedFolderNode.deletable ? (
              <Button
                type="button"
                variant="outline"
                className="mt-3 w-full rounded-sm border-red-200 text-red-700 hover:bg-red-50 text-xs font-serif"
                onClick={onDeleteFolder}
              >
                <Trash2Icon className="mr-1.5 size-3.5" />
                删除文件夹
              </Button>
            ) : null}
          </div>
        </div>
      ) : null}
    </aside>
  );
}

export function KnowledgeManagementToolbar({
  breadcrumbs,
  onSelectFolder,
  onOpenUpload,
  onOpenCreateFolder,
  onOpenReorganize,
  onOpenBatchGenerateSummary,
  noSummaryCount,
  onRefresh,
  isRefreshing,
  onStartChat,
  selectedCount,
  onToggleAllVisible,
  allVisibleSelected,
  onBatchDelete,
  isBatchDeleting,
}: {
  breadcrumbs: Array<{ name: string; path: string }>;
  onSelectFolder: (path: string) => void;
  onOpenUpload: () => void;
  onOpenCreateFolder: () => void;
  onOpenReorganize: () => void;
  onOpenBatchGenerateSummary: () => void;
  noSummaryCount: number;
  onRefresh: () => void;
  isRefreshing: boolean;
  onStartChat: () => void;
  selectedCount: number;
  onToggleAllVisible: () => void;
  allVisibleSelected: boolean;
  onBatchDelete: () => void;
  isBatchDeleting: boolean;
}) {
  return (
    <div className="sticky top-0 z-20 flex flex-col gap-4 border-b border-primary/5 bg-white/40 backdrop-blur-xl px-8 py-5 lg:flex-row lg:items-center lg:justify-between">
      <div className="flex flex-wrap items-center gap-4 text-sm font-serif">
        <button
          type="button"
          className="font-bold text-primary transition hover:opacity-80 flex items-center gap-2"
          onClick={() => onSelectFolder("all")}
        >
          <div className="size-1.5 rounded-full bg-primary" />
          全部馆藏
        </button>
        {breadcrumbs.map((breadcrumb) => (
          <div key={breadcrumb.path} className="flex items-center gap-3">
            <span className="text-[10px] text-accent/40 font-sans">/</span>
            <button
              type="button"
              className="text-stone-700 transition hover:text-primary decoration-primary/20 hover:underline underline-offset-4"
              onClick={() => onSelectFolder(breadcrumb.path)}
            >
              {getFolderDisplayName(breadcrumb.name)}
            </button>
          </div>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-4">
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="h-9 rounded-sm border-primary/40 bg-white shadow-[2px_2px_0_rgba(126,51,46,0.1)] px-4 text-xs text-primary hover:bg-primary hover:text-white transition-all active:translate-x-0.5 active:translate-y-0.5 active:shadow-none font-serif font-bold tracking-widest"
          onClick={onOpenUpload}
        >
          <PlusIcon className="mr-2 size-4" />
          上传档案
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="h-9 rounded-sm border-primary/40 bg-white shadow-[2px_2px_0_rgba(126,51,46,0.1)] px-4 text-xs text-primary hover:bg-primary hover:text-white transition-all active:translate-x-0.5 active:translate-y-0.5 active:shadow-none font-serif font-bold tracking-widest"
          onClick={onOpenCreateFolder}
        >
          <FolderIcon className="mr-2 size-4" />
          新刻文件夹
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="h-9 rounded-sm border-primary/40 bg-white shadow-[2px_2px_0_rgba(126,51,46,0.1)] px-4 text-xs text-primary hover:bg-primary hover:text-white transition-all active:translate-x-0.5 active:translate-y-0.5 active:shadow-none font-serif font-bold tracking-widest"
          onClick={onOpenReorganize}
        >
          <SparklesIcon className="mr-2 size-4" />
          AI 整理目录
        </Button>
        {noSummaryCount > 0 && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-9 rounded-sm border-primary/40 bg-white shadow-[2px_2px_0_rgba(126,51,46,0.1)] px-4 text-xs text-primary hover:bg-primary hover:text-white transition-all active:translate-x-0.5 active:translate-y-0.5 active:shadow-none font-serif font-bold tracking-widest"
            onClick={onOpenBatchGenerateSummary}
          >
            <SparklesIcon className="mr-2 size-4" />
            批量生成摘要 ({noSummaryCount})
          </Button>
        )}
        <Button
          type="button"
          variant="outline"
          size="icon"
          className="h-9 w-9 shrink-0 rounded-sm border-primary/40 bg-white shadow-[2px_2px_0_rgba(126,51,46,0.1)] text-primary hover:bg-primary hover:text-white transition-all"
          onClick={onRefresh}
          disabled={isRefreshing}
        >
          <RefreshCwIcon className={cn("size-4", isRefreshing && "animate-spin")} />
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="h-9 rounded-sm border-accent/40 bg-accent/5 px-4 text-xs text-accent hover:bg-accent hover:text-white shadow-[2px_2px_0_rgba(163,138,82,0.1)] transition-all active:translate-x-0.5 active:translate-y-0.5 active:shadow-none font-serif font-bold tracking-widest"
          onClick={onStartChat}
          disabled={selectedCount === 0}
        >
          <BookmarkPlusIcon className="mr-2 size-4" />
          选中提问 ({selectedCount})
        </Button>
        {selectedCount > 0 && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-9 rounded-sm border-red-300 bg-red-50 px-4 text-xs text-red-600 hover:bg-red-600 hover:text-white shadow-[2px_2px_0_rgba(220,38,38,0.1)] transition-all active:translate-x-0.5 active:translate-y-0.5 active:shadow-none font-serif font-bold tracking-widest"
            onClick={onBatchDelete}
            disabled={isBatchDeleting}
          >
            {isBatchDeleting ? (
              <Loader2Icon className="mr-2 size-4 animate-spin" />
            ) : (
              <Trash2Icon className="mr-2 size-4" />
            )}
            批量删除 ({selectedCount})
          </Button>
        )}
        <button
          type="button"
          className="flex h-9 items-center gap-2 px-3 text-xs font-medium text-stone-500 transition hover:text-primary group"
          onClick={onToggleAllVisible}
        >
          <div className={cn(
            "size-3.5 border transition-colors",
            allVisibleSelected ? "border-primary bg-primary" : "border-stone-300 group-hover:border-primary"
          )}>
            {allVisibleSelected && <CheckIcon className="size-3 text-white" />}
          </div>
          全选馆藏
        </button>
      </div>
    </div>
  );
}

export function KnowledgeFolderGrid({
  folders,
  onSelectFolder,
  onOpenFolderMenu,
}: {
  folders: FolderTreeNode[];
  onSelectFolder: (path: string) => void;
  onOpenFolderMenu: (folder: FolderTreeNode, event: React.MouseEvent<HTMLButtonElement>) => void;
}) {
  if (folders.length === 0) {
    return null;
  }

  return (
    <div className="flex flex-wrap items-center gap-x-12 gap-y-2 px-6 py-2 select-none">
      {folders.map((folder) => (
        <button
          key={folder.path}
          type="button"
          onClick={() => onSelectFolder(folder.path)}
          onContextMenu={(event) => onOpenFolderMenu(folder, event)}
          className="group flex flex-row items-center gap-2 transition hover:opacity-80 active:scale-95"
        >
          <div className="flex size-8 shrink-0 items-center justify-center text-accent/80 group-hover:text-primary">
            <FolderIcon className="size-4.5 stroke-[1.5]" />
          </div>
          <div className="flex flex-row items-baseline gap-2 font-serif">
            <span className="text-sm font-bold text-stone-700 group-hover:text-primary">
              {getFolderDisplayName(folder.name)}
            </span>
            <span className="text-[10px] font-medium text-stone-400 font-sans">
              ({folder.fileCount})
            </span>
          </div>
        </button>
      ))}
    </div>
  );
}

export function KnowledgeFileCard({
  file,
  isSelected,
  onToggleSelection,
  onOpenMetadata,
  onMoveFile,
  onRetry,
  onReparse,
  onDelete,
  readerHref,
  personalSpacesCount,
  isDeleting,
  isRetrying,
  isReparsing,
}: {
  file: ManagedKnowledgeFile;
  isSelected: boolean;
  onToggleSelection: () => void;
  onOpenMetadata: () => void;
  onMoveFile: () => void;
  onRetry: () => void;
  onReparse: () => void;
  onDelete: () => void;
  readerHref: string | null;
  personalSpacesCount: number;
  isDeleting: boolean;
  isRetrying: boolean;
  isReparsing: boolean;
}) {
  const coverTone = getCoverTone(file.title);
  const canOpenReader = canOpenManagedFile(file, readerHref);
  const canRetry = canRetryManagedFile(file);
  const canReparse = canReparseManagedFile(file);
  const isRefreshing = isRetrying || isReparsing;
  const coverImageUrl = useMemo(() => getManagedFileCoverImageUrl(file), [file]);
  const [coverImageFailed, setCoverImageFailed] = useState(false);
  const showCoverImage = Boolean(coverImageUrl) && !coverImageFailed;

  return (
    <article
      className={cn(
        "group relative flex overflow-hidden rounded-md border bg-white/40 shadow-sm transition hover:shadow-md backdrop-blur-sm",
        isSelected ? "border-primary ring-1 ring-primary/15" : "border-accent/20",
      )}
    >
      <div className="flex w-full flex-col lg:flex-row">
        {/* Thread-bound Cover Area */}
        <div
          className={cn(
            "relative flex w-full shrink-0 cursor-pointer flex-col items-center justify-center p-3 lg:w-[132px] overflow-hidden",
            coverTone,
          )}
          onClick={onToggleSelection}
        >
           {/* Thread-bound Stitching Details (线装孔位) */}
           <div className="absolute inset-y-0 left-2 flex flex-col justify-between py-4 opacity-40 pointer-events-none">
             {[...Array(4)].map((_, i) => (
               <div key={i} className="size-1 rounded-full bg-black/40 shadow-[0_0_0_1px_rgba(255,255,255,0.1)]" />
             ))}
           </div>
           <div className="absolute inset-y-0 left-2.5 w-px bg-black/20 opacity-30 pointer-events-none" />
           
           {/* Cover Label Strip (书签/签子) */}
           <div className="absolute right-3 top-0 h-16 w-6 bg-white shadow-[1px_1px_3px_rgba(0,0,0,0.1)] flex items-center justify-center">
             <span className="writing-vertical text-[10px] font-bold text-stone-800 font-serif tracking-widest">
               {file.extension?.replace(".", "").toUpperCase() ?? "馆藏"}
             </span>
           </div>

           <button
             type="button"
             className={cn(
               "absolute left-4 top-4 z-20 flex size-5 items-center justify-center rounded-sm bg-white/90 shadow-sm transition",
               isSelected ? "text-primary" : "text-stone-400 hover:text-primary",
             )}
             onClick={(event) => {
               event.stopPropagation();
               onToggleSelection();
             }}
           >
             {isSelected ? <CheckSquareIcon className="size-3.5" /> : <SquareIcon className="size-3.5" />}
           </button>

           {showCoverImage && coverImageUrl ? (
             <div className="relative mb-0 h-[96px] w-[68px] overflow-hidden rounded-sm border border-black/10 shadow-lg">
               <img
                 src={coverImageUrl}
                 alt={`${file.title} 封面预览`}
                 className="h-full w-full object-cover"
                 onError={() => setCoverImageFailed(true)}
               />
             </div>
           ) : (
             <div className="relative mb-0 flex size-12 items-center justify-center rounded-sm bg-white/5 text-2xl font-light text-white/50 border border-white/10">
               {file.title?.charAt(0) ?? "?"}
             </div>
           )}
        </div>

        <div className="flex min-w-0 flex-1 flex-col p-5">
           <div className="relative flex h-full min-w-0 flex-col justify-between gap-4">
                <div className="min-w-0">
                  <div className="absolute right-0 top-0 flex items-center gap-1.5 opacity-0 transition-opacity group-hover:opacity-100 p-2">
                    {file.source === "global" ? (
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        className="size-7 rounded-sm text-stone-400 hover:bg-stone-100 hover:text-primary"
                        onClick={onOpenMetadata}
                      >
                        <PencilIcon className="size-3.5" />
                      </Button>
                    ) : (
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        className="size-7 rounded-sm text-stone-400 hover:bg-stone-100 hover:text-primary"
                        onClick={onMoveFile}
                        disabled={personalSpacesCount <= 1}
                      >
                        <FolderIcon className="size-3.5" />
                      </Button>
                    )}

                    {canRetry || canReparse ? (
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon"
                            className="size-7 rounded-sm text-stone-400 hover:bg-stone-100 hover:text-primary"
                            disabled={isRefreshing}
                          >
                            {isRefreshing ? (
                              <Loader2Icon className="size-3.5 animate-spin" />
                            ) : (
                              <RefreshCwIcon className="size-3.5" />
                            )}
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end" className="min-w-32">
                          {canRetry ? (
                            <DropdownMenuItem onClick={onRetry}>
                              重新入库
                            </DropdownMenuItem>
                          ) : null}
                          {canReparse ? (
                            <DropdownMenuItem onClick={onReparse}>
                              重新解析
                            </DropdownMenuItem>
                          ) : null}
                        </DropdownMenuContent>
                      </DropdownMenu>
                    ) : null}

                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="size-7 rounded-sm text-stone-400 hover:bg-red-50 hover:text-red-600"
                      onClick={onDelete}
                      disabled={isDeleting}
                    >
                      {isDeleting ? <Loader2Icon className="size-3.5 animate-spin" /> : <Trash2Icon className="size-3.5" />}
                    </Button>

                    {readerHref && (
                      <a
                        href={readerHref}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="flex size-7 items-center justify-center rounded-sm bg-stone-50 text-stone-400 transition hover:bg-primary hover:text-white"
                      >
                        <BookOpenIcon className="size-3.5" />
                      </a>
                    ) }
                  </div>

                  <div className="min-w-0">
                    {canOpenReader && readerHref ? (
                      <a
                        href={readerHref}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="line-clamp-1 block text-lg font-bold text-stone-900 leading-tight transition hover:text-primary font-serif pr-24"
                      >
                        {file.title}
                      </a>
                    ) : (
                      <div className="line-clamp-1 text-lg font-bold text-stone-900 leading-tight font-serif pr-24">{file.title}</div>
                    )}
                    <p className="mt-2 line-clamp-2 text-[11px] leading-relaxed text-stone-500/80 font-serif">
                      <span className="font-bold text-primary/60 mr-1.5">摘要：</span>
                      {file.summary?.trim() ?? "无"}
                    </p>
                    {(!!file.author?.trim() || !!file.publisher?.trim()) && (
                      <p className="mt-1 text-[11px] leading-relaxed text-stone-500/80 font-serif">
                        {file.author?.trim() && (
                          <>
                            <span className="font-bold text-primary/60 mr-1">作者：</span>
                            <span className="mr-3">{file.author}</span>
                          </>
                        )}
                        {file.publisher?.trim() && (
                          <>
                            <span className="font-bold text-primary/60 mr-1">出版社：</span>
                            <span>{file.publisher}</span>
                          </>
                        )}
                      </p>
                    )}
                  </div>
                </div>

                <div className="flex flex-wrap items-center gap-x-5 gap-y-1 text-[10px] text-stone-401 font-sans border-t border-accent/5 pt-2">
                   <div className="flex items-center gap-1">
                     <span className="text-stone-400">来源:</span>
                     <span className="font-medium text-stone-600 font-serif">{file.source === "global" ? "系统" : "个人"}</span>
                   </div>
                   <div className="flex items-center gap-1">
                     <span className="text-stone-400">入库:</span>
                     <span className="font-medium text-stone-600">{formatCompactTime(file.modified)}</span>
                   </div>
                   <div className="flex items-center gap-1 font-serif">
                     <span className="text-stone-400">馆藏目录:</span>
                     <span className="font-bold text-accent">{file.folderDisplay}</span>
                   </div>
                   <div className="flex items-center gap-1 font-serif">
                     <span className="text-stone-400">类型:</span>
                     <span className="font-bold text-accent">{knowledgeTypeLabel(file.type)}</span>
                   </div>
                   <div className="flex items-center gap-1 font-serif">
                     <span className="text-stone-400">状态:</span>
                     <span className="font-bold text-primary">{statusLabel(file.parseStatus)}</span>
                   </div>
                </div>
             </div>
          </div>
        </div>
    </article>
  );
}

export function KnowledgeLoadingState() {
  return (
    <div className="flex flex-col items-center justify-center rounded-md border border-accent/20 bg-white/20 py-16 text-stone-500 shadow-sm font-serif">
      <Loader2Icon className="mb-4 size-8 animate-spin text-primary" />
      正在检索文献馆藏...
    </div>
  );
}

export function KnowledgeErrorState({ message }: { message: string }) {
  return (
    <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-600">
      {message}
    </div>
  );
}

export function KnowledgeEmptyState({
  hasCurrentLevelEntries,
}: {
  hasCurrentLevelEntries: boolean;
}) {
  if (hasCurrentLevelEntries) {
    return null;
  }

  return (
    <div className="flex flex-col items-center justify-center rounded-md border border-dashed border-accent/30 bg-white/10 py-16 text-stone-400 font-serif">
      <FileIcon className="mb-4 size-14 text-accent/20" />
      <p className="text-base font-bold text-stone-600">此分类下暂无相关文献文档。</p>
      <p className="mt-1 text-xs">可以尝试放宽检索条件，或切换到其他目录查看。</p>
    </div>
  );
}

function CategoryCheckbox({
  active,
  label,
  onClick,
}: {
  active: boolean;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "relative flex items-center transition select-none group focus:outline-none font-serif px-2 py-1",
        active ? "text-primary scale-105" : "text-stone-500 hover:text-stone-700",
      )}
    >
      {/* Paper Bookmark Handle (纸签手/签语项) */}
      <div className={cn(
        "absolute -left-1 top-0 bottom-0 w-0.5 bg-accent/30 transition-all",
        active ? "bg-primary w-1" : "group-hover:w-1"
      )} />
      
      <span className={cn(
        "text-sm font-bold tracking-tight transition-all",
        active ? "translate-x-1" : "group-hover:translate-x-1"
      )}>{label}</span>
      
      {active && (
        <div className="absolute -bottom-1 left-3 right-0 h-px bg-primary/40 animate-in fade-in slide-in-from-left-2 duration-300" />
      )}
    </button>
  );
}

function FolderCascaderColumn({
  nodes,
  selectedPath,
  onSelectFolder,
  onHover,
  activeChildPath,
}: {
  nodes: FolderTreeNode[];
  selectedPath: string;
  onSelectFolder: (path: string) => void;
  onHover: (node: FolderTreeNode | null) => void;
  activeChildPath?: string;
}) {
  return (
    <div className="flex min-w-48 flex-col border-r border-accent/10 last:border-r-0 py-1 bg-white/50 first:bg-transparent">
      <div className="max-h-[320px] overflow-y-auto px-1">
        {nodes.map((node) => {
          const isSelected = selectedPath === node.path || selectedPath.startsWith(`${node.path}/`);
          const isHovered = activeChildPath === node.path || activeChildPath?.startsWith(`${node.path}/`);
          const hasChildren = node.children.length > 0;
          const label = getFolderDisplayName(node.name);

          return (
            <div
              key={node.path}
              className={cn(
                "group relative flex cursor-pointer items-center gap-2 rounded-sm px-2.5 py-2 text-sm transition-all font-serif outline-none select-none",
                isHovered ? "bg-accent/10 text-primary" : "hover:bg-accent/5 text-stone-600 hover:text-stone-900",
                isSelected && "font-bold text-primary",
              )}
              onMouseEnter={() => hasChildren ? onHover(node) : onHover(null)}
              onClick={() => onSelectFolder(node.path)}
            >
              <FolderIcon className={cn(
                "size-4 shrink-0 transition-colors",
                isHovered || isSelected ? "text-primary" : "text-accent/60 group-hover:text-primary"
              )} />
              <span className="flex-1 truncate">{label}</span>
              <span className="shrink-0 text-[10px] text-stone-400 font-sans group-hover:text-primary">({node.fileCount})</span>
              {hasChildren && (
                <ChevronRightIcon className="size-3.5 shrink-0 text-accent/40 group-hover:text-primary" />
              )}
              
              {isSelected && !isHovered && (
                <div className="absolute left-0 top-1.5 bottom-1.5 w-0.5 bg-primary rounded-full" />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function FolderCascader({
  nodes,
  selectedPath,
  onSelectFolder,
}: {
  nodes: FolderTreeNode[];
  selectedPath: string;
  onSelectFolder: (path: string) => void;
}) {
  const [hoveredNodes, setHoveredNodes] = useState<FolderTreeNode[]>([]);

  // Calculate the columns to show
  // Column 0: Root nodes
  // Column 1: Children of hoveredNodes[0]...
  const columns = [nodes];
  for (const hoveredNode of hoveredNodes) {
    if (hoveredNode.children.length > 0) {
      columns.push(hoveredNode.children);
    }
  }

  const handleHover = (level: number, node: FolderTreeNode | null) => {
    if (!node) {
      setHoveredNodes(prev => prev.slice(0, level));
      return;
    }
    setHoveredNodes(prev => {
      const next = [...prev.slice(0, level), node];
      return next;
    });
  };

  return (
    <div className="flex flex-row overflow-x-auto">
      {columns.map((colNodes, index) => (
        <FolderCascaderColumn
          key={index}
          nodes={colNodes}
          selectedPath={selectedPath}
          onSelectFolder={onSelectFolder}
          onHover={(node) => handleHover(index, node)}
          activeChildPath={hoveredNodes[index]?.path}
        />
      ))}
    </div>
  );
}

function CategoryFolderFilter({
  node,
  selectedPath,
  onSelectFolder,
}: {
  node: FolderTreeNode;
  selectedPath: string;
  onSelectFolder: (path: string) => void;
}) {
  const isActive =
    selectedPath === node.path || selectedPath.startsWith(`${node.path}/`);
  const hasChildren = node.children.length > 0;

  return (
    <div className="flex items-center gap-1.5">
      <CategoryCheckbox
        active={isActive}
        label={getFolderDisplayName(node.name)}
        onClick={() => onSelectFolder(node.path)}
      />
      {hasChildren ? (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              className={cn(
                "flex size-6 items-center justify-center rounded-sm border transition",
                isActive
                  ? "border-primary bg-primary/10 text-primary"
                  : "border-accent/20 bg-white/60 text-accent/60 hover:border-primary hover:text-primary",
              )}
              aria-label={`展开 ${getFolderDisplayName(node.name)} 文件夹`}
            >
              <ChevronDownIcon className="size-3.5" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent 
            align="start" 
            className="w-fit max-w-[80vw] overflow-hidden rounded-md border-accent/20 bg-white/95 backdrop-blur-md p-0 shadow-[0_20px_50px_-12px_rgba(28,25,23,0.3)]"
          >
            <div className="flex flex-col">
              <div 
                className={cn(
                  "flex cursor-pointer items-center gap-2 px-4 py-2.5 text-sm transition font-serif border-b border-accent/10 hover:bg-accent/5",
                  selectedPath === node.path ? "font-bold text-primary bg-primary/5" : "text-stone-700"
                )}
                onClick={() => onSelectFolder(node.path)}
              >
                <CheckIcon className={cn("size-4 text-primary", selectedPath !== node.path && "opacity-0")} />
                <span className="flex-1">全部馆藏 ({node.fileCount})</span>
              </div>
              <FolderCascader
                nodes={node.children}
                selectedPath={selectedPath}
                onSelectFolder={onSelectFolder}
              />
            </div>
          </DropdownMenuContent>
        </DropdownMenu>
      ) : null}
    </div>
  );
}
