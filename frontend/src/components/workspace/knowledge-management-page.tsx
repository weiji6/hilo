"use client";

import { useRouter } from "next/navigation";
import React, { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import type { FolderReorganizeEvent, KnowledgeFileInfo } from "@/core/knowledge/api";
import { reorganizeKnowledgeFolders } from "@/core/knowledge/api";
import {
  useCreateKnowledgeFolder,
  useDeleteKnowledgeFolder,
  useDeleteKnowledgeFile,
  useDeleteKnowledgeFileArtifactsOnly,
  useKnowledgeFiles,
  useKnowledgeFolders,
  useReparseKnowledgeFile,
  useRenameKnowledgeFolder,
  useRegenerateKnowledgeFileMetadata,
  useRetryKnowledgeFileIndexing,
  useUpdateKnowledgeFileMetadata,
  useUploadKnowledgeFiles,
} from "@/core/knowledge/hooks";
import {
  useCreateUserKnowledgeFolder,
  useDeleteUserKnowledgeFolder,
  useDeleteUserKnowledgeRecord,
  useDeleteUserKnowledgeRecordArtifactsOnly,
  useMoveUserKnowledgeRecord,
  useReparseUserKnowledgeRecord,
  useRenameUserKnowledgeFolder,
  useRetryUserKnowledgeRecordIndexing,
  useUploadUserKnowledgeFiles,
  useUserKnowledgeRecords,
} from "@/core/knowledge/user-hooks";

import {
  BatchGenerateSummaryDialog,
  type BatchSummaryResult,
  CreateFolderDialog,
  MetadataDialog,
  MoveFileDialog,
  ReorganizeFolderDialog,
  UploadDialog,
} from "./knowledge-management-page.dialogs";
import {
  KnowledgeEmptyState,
  KnowledgeErrorState,
  KnowledgeFileCard,
  KnowledgeFolderGrid,
  KnowledgeLoadingState,
  KnowledgeManagementHero,
  KnowledgeManagementToolbar,
} from "./knowledge-management-page.sections";
import {
  buildScopedFolderTreeFromSummaries,
  buildFolderBreadcrumbs,
  buildManagedFileReaderHref,
  buildManagedFiles,
  buildMetadataFormState,
  buildMetadataPayload,
  buildPersonalFolderTree,
  buildSelectedMaterialsPayload,
  createEmptyMetadataFormState,
  createEmptyUploadFormState,
  filterManagedFiles,
  findFolderNode,
  getFolderDisplayName,
  isFileDirectlyInFolder,
  isFileInFolderScope,
  sortGlobalKnowledgeFiles,
  type FolderTreeNode,
  type ManagedKnowledgeFile,
} from "./knowledge-management-page.utils";

export default function KnowledgeManagementPage() {
  const router = useRouter();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const folderContextMenuRef = useRef<HTMLDivElement>(null);
  const [isUploadDialogOpen, setIsUploadDialogOpen] = useState(false);
  const [isCreateFolderDialogOpen, setIsCreateFolderDialogOpen] = useState(false);
  const [uploadForm, setUploadForm] = useState(createEmptyUploadFormState);
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedRowIds, setSelectedRowIds] = useState<string[]>([]);
  const [deletingFilename, setDeletingFilename] = useState<string | null>(null);
  const [deletingRecordId, setDeletingRecordId] = useState<string | null>(null);
  const [isBatchDeleting, setIsBatchDeleting] = useState(false);
  const [retryingRowId, setRetryingRowId] = useState<string | null>(null);
  const [reparsingRowId, setReparsingRowId] = useState<string | null>(null);
  const [movingRecord, setMovingRecord] = useState<ManagedKnowledgeFile | null>(null);
  const [moveTargetFolderPath, setMoveTargetFolderPath] = useState("");
  const [newFolderName, setNewFolderName] = useState("");
  const [renamingFolderName, setRenamingFolderName] = useState("");
  const [isRenameFolderDialogOpen, setIsRenameFolderDialogOpen] = useState(false);
  const [folderContextMenu, setFolderContextMenu] = useState<{
    x: number;
    y: number;
    folder: FolderTreeNode;
  } | null>(null);
  const [editingFile, setEditingFile] = useState<KnowledgeFileInfo | null>(null);
  const [metadataForm, setMetadataForm] = useState(createEmptyMetadataFormState);
  const [selectedFolderPath, setSelectedFolderPath] = useState("all");
  const [isReorganizeDialogOpen, setIsReorganizeDialogOpen] = useState(false);
  const [isReorganizing, setIsReorganizing] = useState(false);
  const [reorganizeEvents, setReorganizeEvents] = useState<FolderReorganizeEvent[]>([]);
  const [isBatchSummaryDialogOpen, setIsBatchSummaryDialogOpen] = useState(false);
  const [isBatchGeneratingSummary, setIsBatchGeneratingSummary] = useState(false);
  const [batchSummaryResults, setBatchSummaryResults] = useState<BatchSummaryResult[]>([]);
  const [batchSummaryTotal, setBatchSummaryTotal] = useState(0);

  const selectedGlobalFolderPath =
    selectedFolderPath.startsWith("system:")
      ? selectedFolderPath.slice("system:".length)
      : null;
  const globalFoldersQuery = useKnowledgeFolders();
  const globalFilesQuery = useKnowledgeFiles(selectedGlobalFolderPath);
  const personalRecordsQuery = useUserKnowledgeRecords();
  const uploadMutation = useUploadKnowledgeFiles();
  const uploadUserMutation = useUploadUserKnowledgeFiles();
  const createKnowledgeFolderMutation = useCreateKnowledgeFolder();
  const renameKnowledgeFolderMutation = useRenameKnowledgeFolder();
  const deleteKnowledgeFolderMutation = useDeleteKnowledgeFolder();
  const createUserFolderMutation = useCreateUserKnowledgeFolder();
  const renameUserFolderMutation = useRenameUserKnowledgeFolder();
  const deleteUserFolderMutation = useDeleteUserKnowledgeFolder();
  const deleteMutation = useDeleteKnowledgeFile();
  const deleteArtifactsOnlyMutation = useDeleteKnowledgeFileArtifactsOnly();
  const deleteUserRecordMutation = useDeleteUserKnowledgeRecord();
  const deleteUserRecordArtifactsOnlyMutation = useDeleteUserKnowledgeRecordArtifactsOnly();
  const retryMutation = useRetryKnowledgeFileIndexing();
  const reparseMutation = useReparseKnowledgeFile();
  const retryUserRecordMutation = useRetryUserKnowledgeRecordIndexing();
  const reparseUserRecordMutation = useReparseUserKnowledgeRecord();
  const moveUserRecordMutation = useMoveUserKnowledgeRecord();
  const updateMetadataMutation = useUpdateKnowledgeFileMetadata();
  const regenerateMetadataMutation = useRegenerateKnowledgeFileMetadata();
  const metadataDialogError =
    updateMetadataMutation.error ?? regenerateMetadataMutation.error;

  useEffect(() => {
    document.title = "知识库管理 - Hilo";
  }, []);

  useEffect(() => {
    if (!folderContextMenu) {
      return;
    }

    const handlePointerDown = (event: MouseEvent) => {
      const target = event.target;
      if (
        folderContextMenuRef.current &&
        target instanceof Node &&
        !folderContextMenuRef.current.contains(target)
      ) {
        setFolderContextMenu(null);
      }
    };

    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setFolderContextMenu(null);
      }
    };

    window.addEventListener("pointerdown", handlePointerDown);
    window.addEventListener("keydown", handleEscape);
    return () => {
      window.removeEventListener("pointerdown", handlePointerDown);
      window.removeEventListener("keydown", handleEscape);
    };
  }, [folderContextMenu]);

  const globalFiles = useMemo(
    () => globalFilesQuery.data?.files ?? [],
    [globalFilesQuery.data?.files],
  );
  const personalRecords = useMemo(
    () => personalRecordsQuery.data?.records ?? [],
    [personalRecordsQuery.data?.records],
  );
  const personalFolderPaths = useMemo(
    () => personalRecordsQuery.data?.folders ?? [],
    [personalRecordsQuery.data?.folders],
  );
  const sortedGlobalFiles = useMemo(
    () => sortGlobalKnowledgeFiles(globalFiles),
    [globalFiles],
  );
  const globalFileMap = useMemo(
    () => new Map(sortedGlobalFiles.map((file) => [file.filename, file])),
    [sortedGlobalFiles],
  );

  const managedFiles = useMemo(
    () =>
      buildManagedFiles({
        globalFiles: sortedGlobalFiles,
        personalRecords,
      }),
    [personalRecords, sortedGlobalFiles],
  );

  const filteredFiles = useMemo(
    () =>
      filterManagedFiles({
        files: managedFiles,
        searchQuery,
      }),
    [managedFiles, searchQuery],
  );

  const systemFolderTree = useMemo(
    () =>
      buildScopedFolderTreeFromSummaries({
        folders: globalFoldersQuery.data?.folders ?? [],
        prefix: "system:",
        source: "global",
      }),
    [globalFoldersQuery.data?.folders],
  );
  const personalFolderTree = useMemo(
    () => buildPersonalFolderTree(managedFiles, personalFolderPaths),
    [managedFiles, personalFolderPaths],
  );
  const folderTree = useMemo(
    () => [
      {
        name: "个人",
        path: "personal-root",
        fileCount: managedFiles.filter((file) => file.source === "personal").length,
        children: personalFolderTree,
        source: "personal" as const,
      },
      {
        name: "系统",
        path: "system-root",
        fileCount: globalFoldersQuery.data?.total_file_count ?? 0,
        children: systemFolderTree,
        source: "global" as const,
      },
    ],
    [globalFoldersQuery.data?.total_file_count, managedFiles, personalFolderTree, systemFolderTree],
  );

  useEffect(() => {
    if (selectedFolderPath === "all") {
      return;
    }
    const availablePaths = new Set<string>();
    const collectPaths = (nodes: FolderTreeNode[]) => {
      for (const node of nodes) {
        availablePaths.add(node.path);
        collectPaths(node.children);
      }
    };
    collectPaths(folderTree);
    if (!availablePaths.has(selectedFolderPath)) {
      setSelectedFolderPath("all");
    }
  }, [folderTree, selectedFolderPath]);

  const scopedFilteredFiles = useMemo(
    () => filteredFiles.filter((file) => isFileInFolderScope(file, selectedFolderPath)),
    [filteredFiles, selectedFolderPath],
  );
  const folderFilteredFiles = useMemo(() => {
    if (searchQuery.trim()) {
      return scopedFilteredFiles;
    }
    return scopedFilteredFiles.filter((file) =>
      isFileDirectlyInFolder(file, selectedFolderPath),
    );
  }, [scopedFilteredFiles, searchQuery, selectedFolderPath]);

  useEffect(() => {
    const visibleRowIds = new Set(folderFilteredFiles.map((file) => file.rowId));
    setSelectedRowIds((current) => current.filter((rowId) => visibleRowIds.has(rowId)));
  }, [folderFilteredFiles]);

  const selectedFiles = useMemo(
    () => folderFilteredFiles.filter((file) => selectedRowIds.includes(file.rowId)),
    [folderFilteredFiles, selectedRowIds],
  );
  const selectableVisibleFiles = folderFilteredFiles;
  const allVisibleSelected =
    selectableVisibleFiles.length > 0 &&
    selectedFiles.length === selectableVisibleFiles.length;
  const selectedMaterialsPayload = useMemo(
    () => buildSelectedMaterialsPayload(selectedFiles),
    [selectedFiles],
  );

  const uploadTargetMode =
    selectedFolderPath === "system-root" || selectedFolderPath.startsWith("system:")
      ? "global"
      : "personal";
  const selectedFolderNode = useMemo(
    () => findFolderNode(folderTree, selectedFolderPath),
    [folderTree, selectedFolderPath],
  );
  const selectedLogicalFolderPath = useMemo(() => {
    if (selectedFolderPath.startsWith("system:")) {
      return selectedFolderPath.slice("system:".length);
    }
    if (selectedFolderPath.startsWith("personal:")) {
      return selectedFolderPath.slice("personal:".length);
    }
    return "";
  }, [selectedFolderPath]);
  const uploadTargetFolderPath = selectedLogicalFolderPath || null;
  const selectedFolderScope = selectedFolderPath.startsWith("system:") || selectedFolderPath === "system-root"
    ? "global"
    : "personal";
  const uploadTargetFolderLabel = selectedFolderNode
    ? getFolderDisplayName(selectedFolderNode.name)
    : uploadTargetMode === "global"
      ? "系统根目录"
      : "个人根目录";
  const breadcrumbs = useMemo(
    () => buildFolderBreadcrumbs(folderTree, selectedFolderPath),
    [folderTree, selectedFolderPath],
  );
  const currentLevelFolderNodes = useMemo(
    () => (selectedFolderPath === "all" ? folderTree : selectedFolderNode?.children ?? []),
    [folderTree, selectedFolderNode?.children, selectedFolderPath],
  );
  const hasCurrentLevelEntries =
    currentLevelFolderNodes.length > 0 || folderFilteredFiles.length > 0;

  const openFolderContextMenu = (
    folder: FolderTreeNode,
    event: React.MouseEvent<HTMLButtonElement>,
  ) => {
    event.preventDefault();
    event.stopPropagation();
    setFolderContextMenu({
      x: event.clientX,
      y: event.clientY,
      folder,
    });
  };

  const resetUploadDialog = () => {
    setUploadForm(createEmptyUploadFormState());
    setIsUploadDialogOpen(false);
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };

  const handleFilesSelected = (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files ?? []);
    if (files.length === 0) {
      return;
    }
    setUploadForm((current) => ({ ...current, files }));
    event.target.value = "";
  };

  const handleUploadSubmit = async () => {
    if (uploadForm.files.length === 0) {
      toast.error("请先选择要上传的文件");
      return;
    }

    try {
      const uploadOptions = {
        languageHint: uploadForm.languageHint === "unknown" ? undefined : uploadForm.languageHint,
        layoutHint: uploadForm.layoutHint === "unknown" ? undefined : uploadForm.layoutHint,
        documentTypeHint:
          uploadForm.documentTypeHint === "unknown" ? undefined : uploadForm.documentTypeHint,
      };

      const result =
        uploadTargetMode === "global"
          ? await uploadMutation.mutateAsync({
              files: uploadForm.files,
              options: {
                ...uploadOptions,
                folderPath: uploadTargetFolderPath,
              },
            })
          : await uploadUserMutation.mutateAsync({
              files: uploadForm.files,
              options: {
                ...uploadOptions,
                folderPath: uploadTargetFolderPath,
              },
            });

      toast.success(result.message);
      resetUploadDialog();
      await handleRefresh();
    } catch (uploadError) {
      toast.error(uploadError instanceof Error ? uploadError.message : "上传失败");
    }
  };

  const handleDelete = async (filename: string) => {
    setDeletingFilename(filename);
    try {
      const result = await deleteMutation.mutateAsync(filename);
      toast.success(result.message);
    } catch (deleteError) {
      toast.error(deleteError instanceof Error ? deleteError.message : "删除失败");
    } finally {
      setDeletingFilename(null);
    }
  };

  const handleDeletePersonalRecord = async (recordId: string) => {
    setDeletingRecordId(recordId);
    try {
      const result = await deleteUserRecordMutation.mutateAsync(recordId);
      toast.success(result.message);
    } catch (deleteError) {
      toast.error(deleteError instanceof Error ? deleteError.message : "删除失败");
    } finally {
      setDeletingRecordId(null);
    }
  };

  // Active processing statuses — files in these states cannot be deleted at all.
  const ACTIVE_STATUSES = new Set(["queued", "queued_ocr", "parsing", "queued_embedding", "indexing"]);

  const handleBatchDelete = async () => {
    if (selectedFiles.length === 0) return;
    const confirmed = window.confirm(`确定要删除选中的 ${selectedFiles.length} 份档案吗？此操作不可撤销。`);
    if (!confirmed) return;

    setIsBatchDeleting(true);
    let successCount = 0;
    let failCount = 0;
    let skippedCount = 0;

    for (const file of selectedFiles) {
      const status = file.parseStatus ?? "";

      // Skip files that are currently being processed — deleting them mid-flight is unsafe.
      if (ACTIVE_STATUSES.has(status)) {
        skippedCount++;
        continue;
      }

      try {
        if (status === "indexed") {
          // File is in the vector index → must go through the full delete path so the
          // Qdrant index is updated accordingly.
          if (file.source === "global") {
            await deleteMutation.mutateAsync(file.filename);
          } else {
            await deleteUserRecordMutation.mutateAsync(file.userRecordId ?? "");
          }
        } else {
          // File is only uploaded / parsed / failed → skip the vector DB entirely and
          // just remove the physical files (.book-metadata, .ingestion record, PDF).
          if (file.source === "global") {
            await deleteArtifactsOnlyMutation.mutateAsync(file.filename);
          } else {
            await deleteUserRecordArtifactsOnlyMutation.mutateAsync(file.userRecordId ?? "");
          }
        }
        successCount++;
      } catch {
        failCount++;
      }
    }

    setIsBatchDeleting(false);
    setSelectedRowIds([]);

    if (skippedCount > 0 && failCount === 0) {
      toast.success(`已删除 ${successCount} 份档案，${skippedCount} 份正在处理中已跳过`);
    } else if (failCount === 0) {
      toast.success(`已删除 ${successCount} 份档案`);
    } else {
      toast.warning(`成功删除 ${successCount} 份，${failCount} 份删除失败${skippedCount > 0 ? `，${skippedCount} 份跳过` : ""}`);
    }
  };

  const handleRetryIndexing = async (file: ManagedKnowledgeFile) => {
    setRetryingRowId(file.rowId);
    try {
      const result =
        file.source === "global"
          ? await retryMutation.mutateAsync(file.filename)
          : await retryUserRecordMutation.mutateAsync(file.userRecordId ?? "");
      toast.success(result.message);
    } catch (retryError) {
      toast.error(retryError instanceof Error ? retryError.message : "重新入库失败");
    } finally {
      setRetryingRowId(null);
    }
  };

  const handleReparse = async (file: ManagedKnowledgeFile) => {
    setReparsingRowId(file.rowId);
    try {
      const result =
        file.source === "global"
          ? await reparseMutation.mutateAsync(file.filename)
          : await reparseUserRecordMutation.mutateAsync(file.userRecordId ?? "");
      toast.success(result.message);
    } catch (reparseError) {
      toast.error(reparseError instanceof Error ? reparseError.message : "重新解析失败");
    } finally {
      setReparsingRowId(null);
    }
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
      const result =
        selectedFolderScope === "global"
          ? await createKnowledgeFolderMutation.mutateAsync(nextPath)
          : await createUserFolderMutation.mutateAsync(nextPath);
      toast.success(result.message);
      setNewFolderName("");
      setIsCreateFolderDialogOpen(false);
      // Refresh first so folderTree has the new path before we navigate into it,
      // otherwise the "invalid path" useEffect would immediately reset back to "all".
      await handleRefresh();
      setSelectedFolderPath(
        selectedFolderScope === "global" ? `system:${nextPath}` : `personal:${nextPath}`,
      );
    } catch (createError) {
      toast.error(createError instanceof Error ? createError.message : "创建文件夹失败");
    }
  };

  const handleMoveFile = async () => {
    if (!movingRecord?.userRecordId || !moveTargetFolderPath) {
      return;
    }
    try {
      const result = await moveUserRecordMutation.mutateAsync({
        recordId: movingRecord.userRecordId,
        folderPath: moveTargetFolderPath,
      });
      toast.success(result.message);
      setMovingRecord(null);
      setMoveTargetFolderPath("");
    } catch (moveError) {
      toast.error(moveError instanceof Error ? moveError.message : "移动失败");
    }
  };

  const handleRenameFolder = async () => {
    const trimmedName = renamingFolderName.trim();
    if (!selectedLogicalFolderPath || !trimmedName) {
      toast.error("请输入文件夹名称");
      return;
    }
    const parentPath = selectedLogicalFolderPath.includes("/")
      ? selectedLogicalFolderPath.split("/").slice(0, -1).join("/")
      : "";
    const newPath = parentPath ? `${parentPath}/${trimmedName}` : trimmedName;
    try {
      const result =
        selectedFolderScope === "global"
          ? await renameKnowledgeFolderMutation.mutateAsync({
              path: selectedLogicalFolderPath,
              newPath,
            })
          : await renameUserFolderMutation.mutateAsync({
              path: selectedLogicalFolderPath,
              newPath,
            });
      toast.success(result.message);
      setIsRenameFolderDialogOpen(false);
      setRenamingFolderName("");
      // Refresh before navigating so the renamed path already exists in folderTree.
      await handleRefresh();
      setSelectedFolderPath(
        selectedFolderScope === "global" ? `system:${newPath}` : `personal:${newPath}`,
      );
    } catch (renameError) {
      toast.error(renameError instanceof Error ? renameError.message : "重命名失败");
    }
  };

  const handleContextRenameFolder = () => {
    if (!folderContextMenu) {
      return;
    }
    setSelectedFolderPath(folderContextMenu.folder.path);
    setRenamingFolderName(folderContextMenu.folder.name);
    setIsRenameFolderDialogOpen(true);
    setFolderContextMenu(null);
  };

  const handleContextDeleteFolder = async () => {
    if (!folderContextMenu) {
      return;
    }
    setSelectedFolderPath(folderContextMenu.folder.path);
    setFolderContextMenu(null);
    const logicalPath = folderContextMenu.folder.path.replace(/^(system:|personal:)/, "");
    try {
      const result =
        folderContextMenu.folder.path.startsWith("system:")
          ? await deleteKnowledgeFolderMutation.mutateAsync(logicalPath)
          : await deleteUserFolderMutation.mutateAsync(logicalPath);
      toast.success(result.message);
      setSelectedFolderPath(
        folderContextMenu.folder.path.startsWith("system:") ? "system-root" : "personal-root",
      );
      await handleRefresh();
    } catch (deleteError) {
      toast.error(deleteError instanceof Error ? deleteError.message : "删除文件夹失败");
    }
  };

  const renderFolderContextMenu = () => {
    if (!folderContextMenu) {
      return null;
    }
    const menuWidth = 148;
    const left =
      typeof window !== "undefined"
        ? Math.min(folderContextMenu.x, window.innerWidth - menuWidth - 12)
        : folderContextMenu.x;
    const top =
      typeof window !== "undefined"
        ? Math.min(folderContextMenu.y, window.innerHeight - 96)
        : folderContextMenu.y;

    return (
      <div
        ref={folderContextMenuRef}
        className="fixed z-50 rounded-2xl border border-stone-200 bg-white p-1.5 shadow-[0_18px_40px_-22px_rgba(28,25,23,0.4)]"
        style={{ left, top }}
        onClick={(event) => event.stopPropagation()}
      >
        <button
          type="button"
          className="flex h-9 w-full items-center rounded-xl px-3 text-sm text-stone-800 transition hover:bg-stone-100"
          onClick={handleContextRenameFolder}
        >
          重命名文件夹
        </button>
        <button
          type="button"
          className="flex h-9 w-full items-center rounded-xl px-3 text-sm text-red-700 transition hover:bg-red-50"
          onClick={() => void handleContextDeleteFolder()}
        >
          删除文件夹
        </button>
      </div>
    );
  };

  const openEditDialog = (file: KnowledgeFileInfo) => {
    setEditingFile(file);
    setMetadataForm(buildMetadataFormState(file));
  };

  const closeEditDialog = () => {
    setEditingFile(null);
    setMetadataForm(createEmptyMetadataFormState());
  };

  const handleSaveMetadata = async () => {
    if (!editingFile) {
      return;
    }
    try {
      const result = await updateMetadataMutation.mutateAsync({
        filename: editingFile.filename,
        payload: buildMetadataPayload(metadataForm),
      });
      toast.success(result.message || "标签已更新");
      closeEditDialog();
    } catch (updateError) {
      toast.error(updateError instanceof Error ? updateError.message : "标签更新失败");
    }
  };

  const handleRegenerateMetadata = async () => {
    if (!editingFile) {
      return;
    }
    try {
      const result = await regenerateMetadataMutation.mutateAsync(editingFile.filename);
      setMetadataForm(buildMetadataFormState(result.metadata));
      toast.success(result.message || "已重新生成标签");
    } catch (regenerateError) {
      toast.error(regenerateError instanceof Error ? regenerateError.message : "AI 生成失败");
    }
  };

  const toggleFileSelection = (rowId: string) => {
    setSelectedRowIds((current) =>
      current.includes(rowId)
        ? current.filter((item) => item !== rowId)
        : [...current, rowId],
    );
  };

  const handleToggleAllVisible = () => {
    if (allVisibleSelected) {
      setSelectedRowIds([]);
      return;
    }
    setSelectedRowIds(selectableVisibleFiles.map((file) => file.rowId));
  };

  const handleStartChat = () => {
    if (selectedMaterialsPayload.length === 0) {
      toast.error("请先勾选已解析的资料");
      return;
    }

    const key = `selected_materials_${Date.now()}`;
    sessionStorage.setItem(key, JSON.stringify(selectedMaterialsPayload));
    router.push(`/workspace/chats/new?materials_key=${encodeURIComponent(key)}`);
  };

  const isLoading = globalFilesQuery.isLoading || globalFoldersQuery.isLoading || personalRecordsQuery.isLoading;
  const error = globalFilesQuery.error ?? globalFoldersQuery.error ?? personalRecordsQuery.error;
  const isUploadPending = uploadMutation.isPending || uploadUserMutation.isPending;
  const isRefreshing = globalFilesQuery.isFetching || globalFoldersQuery.isFetching || personalRecordsQuery.isFetching;

  const handleRefresh = async () => {
    await Promise.all([
      globalFoldersQuery.refetch(),
      globalFilesQuery.refetch(),
      personalRecordsQuery.refetch(),
    ]);
  };

  const handleReorganize = async () => {
    setReorganizeEvents([]);
    setIsReorganizeDialogOpen(true);
    setIsReorganizing(true);
    try {
      for await (const event of reorganizeKnowledgeFolders()) {
        setReorganizeEvents((prev) => [...prev, event]);
      }
    } catch (err) {
      setReorganizeEvents((prev) => [
        ...prev,
        { type: "error", message: String(err) },
      ]);
    } finally {
      setIsReorganizing(false);
      // Refresh the folder list so changes are visible immediately after close.
      void handleRefresh();
    }
  };

  const noSummaryFiles = useMemo(
    () =>
      managedFiles.filter(
        (file) => file.source === "global" && !file.summary?.trim(),
      ),
    [managedFiles],
  );

  const handleBatchGenerateSummary = async () => {
    if (noSummaryFiles.length === 0) return;
    setBatchSummaryResults([]);
    setBatchSummaryTotal(noSummaryFiles.length);
    setIsBatchSummaryDialogOpen(true);
    setIsBatchGeneratingSummary(true);

    for (const file of noSummaryFiles) {
      let lastErr: unknown;
      let succeeded = false;
      for (let attempt = 0; attempt < 3; attempt++) {
        try {
          await regenerateMetadataMutation.mutateAsync(file.filename);
          succeeded = true;
          break;
        } catch (err) {
          lastErr = err;
        }
      }
      if (succeeded) {
        setBatchSummaryResults((prev) => [
          ...prev,
          { filename: file.filename, title: file.title, success: true },
        ]);
      } else {
        setBatchSummaryResults((prev) => [
          ...prev,
          {
            filename: file.filename,
            title: file.title,
            success: false,
            error: lastErr instanceof Error ? lastErr.message : "生成失败",
          },
        ]);
      }
    }

    setIsBatchGeneratingSummary(false);
    void handleRefresh();
  };

  return (
    <WorkspaceContainer>
      <WorkspaceHeader className="border-b border-primary/5" />
      <WorkspaceBody className="bg-transparent">
        <input
          ref={fileInputRef}
          type="file"
          multiple
          className="hidden"
          onChange={handleFilesSelected}
        />

        <UploadDialog
          open={isUploadDialogOpen}
          onOpenChange={(open) => {
            if (!open && !isUploadPending) {
              resetUploadDialog();
              return;
            }
            setIsUploadDialogOpen(open);
          }}
          form={uploadForm}
          setForm={setUploadForm}
          targetMode={uploadTargetMode}
          targetFolderLabel={uploadTargetFolderLabel}
          onPickFiles={() => fileInputRef.current?.click()}
          onCancel={resetUploadDialog}
          onSubmit={() => void handleUploadSubmit()}
          isPending={isUploadPending}
        />

        <CreateFolderDialog
          open={isCreateFolderDialogOpen}
          onOpenChange={setIsCreateFolderDialogOpen}
          title={`新建${selectedFolderScope === "global" ? "系统" : "个人"}文件夹`}
          description={
            selectedLogicalFolderPath
              ? `新文件夹会创建在“${getFolderDisplayName(selectedLogicalFolderPath)}”下。`
              : `新文件夹会创建在${selectedFolderScope === "global" ? "系统" : "个人"}根目录下。`
          }
          value={newFolderName}
          onValueChange={setNewFolderName}
          onSubmit={() => void handleCreateFolder()}
          isPending={
            createKnowledgeFolderMutation.isPending || createUserFolderMutation.isPending
          }
        />

        <CreateFolderDialog
          open={isRenameFolderDialogOpen}
          onOpenChange={(open) => {
            setIsRenameFolderDialogOpen(open);
            if (!open) {
              setRenamingFolderName("");
            }
          }}
          title="重命名文件夹"
          description="只修改当前文件夹名称，子文件夹层级会一并保留。"
          value={renamingFolderName}
          onValueChange={setRenamingFolderName}
          onSubmit={() => void handleRenameFolder()}
          isPending={
            renameKnowledgeFolderMutation.isPending || renameUserFolderMutation.isPending
          }
        />

        <MoveFileDialog
          open={Boolean(movingRecord)}
          onOpenChange={(open) => {
            if (!open) {
              setMovingRecord(null);
              setMoveTargetFolderPath("");
            }
          }}
          folders={personalFolderPaths}
          value={moveTargetFolderPath}
          onValueChange={setMoveTargetFolderPath}
          onSubmit={() => void handleMoveFile()}
          isPending={moveUserRecordMutation.isPending}
        />

        <MetadataDialog
          open={Boolean(editingFile)}
          onOpenChange={(open) => {
            if (!open && !updateMetadataMutation.isPending) {
              closeEditDialog();
            }
          }}
          form={metadataForm}
          setForm={setMetadataForm}
          errorMessage={metadataDialogError?.message}
          isSaving={updateMetadataMutation.isPending}
          isRegenerating={regenerateMetadataMutation.isPending}
          onRegenerate={() => void handleRegenerateMetadata()}
          onCancel={closeEditDialog}
          onSave={() => void handleSaveMetadata()}
        />

        <div className="flex h-full min-h-0 w-full min-w-0 flex-1 flex-col">
          <KnowledgeManagementHero
            searchQuery={searchQuery}
            onSearchQueryChange={setSearchQuery}
            selectedFolderPath={selectedFolderPath}
            systemFolderTree={systemFolderTree}
            onSelectFolder={setSelectedFolderPath}
          />

          <div className="flex min-h-0 flex-1 flex-col">
            <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
              <div className="flex w-full flex-col gap-4">
                <KnowledgeManagementToolbar
                  breadcrumbs={breadcrumbs}
                  onSelectFolder={setSelectedFolderPath}
                  onOpenUpload={() => setIsUploadDialogOpen(true)}
                  onOpenCreateFolder={() => setIsCreateFolderDialogOpen(true)}
                  onOpenReorganize={() => void handleReorganize()}
                  onOpenBatchGenerateSummary={() => void handleBatchGenerateSummary()}
                  noSummaryCount={noSummaryFiles.length}
                  onRefresh={() => void handleRefresh()}
                  isRefreshing={isRefreshing}
                  onStartChat={handleStartChat}
                  selectedCount={selectedRowIds.length}
                  onToggleAllVisible={handleToggleAllVisible}
                  allVisibleSelected={allVisibleSelected}
                  onBatchDelete={() => void handleBatchDelete()}
                  isBatchDeleting={isBatchDeleting}
                />

                {isLoading ? <KnowledgeLoadingState /> : null}
                {!isLoading && error ? <KnowledgeErrorState message={error.message} /> : null}

                {!isLoading && !error ? (
                  <>
                    <KnowledgeFolderGrid
                      folders={currentLevelFolderNodes}
                      onSelectFolder={setSelectedFolderPath}
                      onOpenFolderMenu={openFolderContextMenu}
                    />

                    {folderFilteredFiles.length > 0 ? (
                      <div className="flex flex-col gap-4 px-6 pb-12">
                        {folderFilteredFiles.map((file) => {
                          const readerHref = buildManagedFileReaderHref(file);
                          const sourceFile = globalFileMap.get(file.filename);
                          const isDeleting =
                            (file.source === "global" &&
                              deleteMutation.isPending &&
                              deletingFilename === file.filename) ||
                            (file.source === "personal" &&
                              deleteUserRecordMutation.isPending &&
                              deletingRecordId === file.userRecordId);
                          const isRetrying =
                            (file.source === "global" && retryMutation.isPending) ||
                            (file.source === "personal" && retryUserRecordMutation.isPending);
                          const isReparsing =
                            (file.source === "global" && reparseMutation.isPending) ||
                            (file.source === "personal" && reparseUserRecordMutation.isPending);

                          return (
                            <KnowledgeFileCard
                              key={file.rowId}
                              file={file}
                              isSelected={selectedRowIds.includes(file.rowId)}
                              onToggleSelection={() => toggleFileSelection(file.rowId)}
                              onOpenMetadata={() => sourceFile && openEditDialog(sourceFile)}
                              onMoveFile={() => {
                                setMovingRecord(file);
                                setMoveTargetFolderPath(file.folderDisplay);
                              }}
                              onRetry={() => void handleRetryIndexing(file)}
                              onReparse={() => void handleReparse(file)}
                              onDelete={() =>
                                file.source === "global"
                                  ? void handleDelete(file.filename)
                                  : void handleDeletePersonalRecord(file.userRecordId ?? "")
                              }
                              readerHref={readerHref}
                              personalSpacesCount={personalFolderPaths.length}
                              isDeleting={isDeleting}
                              isRetrying={isRetrying && retryingRowId === file.rowId}
                              isReparsing={isReparsing && reparsingRowId === file.rowId}
                            />
                          );
                        })}
                      </div>
                    ) : (
                      <KnowledgeEmptyState hasCurrentLevelEntries={hasCurrentLevelEntries} />
                    )}
                  </>
                ) : null}
              </div>
            </div>
          </div>
        </div>
        <ReorganizeFolderDialog
          open={isReorganizeDialogOpen}
          onOpenChange={setIsReorganizeDialogOpen}
          events={reorganizeEvents}
          isRunning={isReorganizing}
        />
        <BatchGenerateSummaryDialog
          open={isBatchSummaryDialogOpen}
          onOpenChange={setIsBatchSummaryDialogOpen}
          results={batchSummaryResults}
          total={batchSummaryTotal}
          isRunning={isBatchGeneratingSummary}
        />
      </WorkspaceBody>
      {renderFolderContextMenu()}
    </WorkspaceContainer>
  );
}
