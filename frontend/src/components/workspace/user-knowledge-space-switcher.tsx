"use client";

import { FolderPlusIcon, Loader2Icon } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
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
import type { UserKnowledgeSpace } from "@/core/knowledge/user-api";
import { useCreateUserKnowledgeSpace } from "@/core/knowledge/user-hooks";

export function UserKnowledgeSpaceSwitcher({
  spaces,
  selectedSpaceId,
  onSelect,
}: {
  spaces: UserKnowledgeSpace[];
  selectedSpaceId: string;
  onSelect: (spaceId: string) => void;
}) {
  const createMutation = useCreateUserKnowledgeSpace();
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");

  const selectedSpace = useMemo(
    () => spaces.find((space) => space.id === selectedSpaceId) ?? spaces[0] ?? null,
    [selectedSpaceId, spaces],
  );

  const handleCreate = async () => {
    const trimmedName = name.trim();
    if (!trimmedName) {
      toast.error("请输入知识库名称");
      return;
    }
    try {
      const result = await createMutation.mutateAsync({
        name: trimmedName,
        description,
      });
      toast.success("已创建知识库");
      setName("");
      setDescription("");
      setIsCreateOpen(false);
      onSelect(result.space.id);
    } catch (error) {
      toast.error((error as Error).message || "创建失败");
    }
  };

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Select value={selectedSpace?.id ?? selectedSpaceId} onValueChange={onSelect}>
        <SelectTrigger className="h-9 min-w-[220px] border-slate-200 bg-white text-sm text-slate-900">
          <SelectValue placeholder="选择知识库文件夹" />
        </SelectTrigger>
        <SelectContent>
          {spaces.map((space) => (
            <SelectItem key={space.id} value={space.id}>
              {space.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <Button
        type="button"
        variant="outline"
        size="sm"
        className="h-9 border-slate-200"
        onClick={() => setIsCreateOpen(true)}
      >
        <FolderPlusIcon className="size-4" />
        新建文件夹
      </Button>

      <Dialog open={isCreateOpen} onOpenChange={setIsCreateOpen}>
        <DialogContent className="sm:max-w-lg border-slate-200 bg-white">
          <DialogHeader>
            <DialogTitle>新建个人知识库文件夹</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <Input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="例如：系统架构研究"
            />
            <Textarea
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              placeholder="可选说明：这个文件夹主要放哪些资料"
              className="min-h-[120px]"
            />
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              disabled={createMutation.isPending}
              onClick={() => setIsCreateOpen(false)}
            >
              取消
            </Button>
            <Button
              disabled={createMutation.isPending}
              className="bg-primary text-white hover:bg-primary/90"
              onClick={() => void handleCreate()}
            >
              {createMutation.isPending ? (
                <Loader2Icon className="size-4 animate-spin" />
              ) : null}
              创建
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
