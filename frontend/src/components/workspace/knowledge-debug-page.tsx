"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import {
  BookTextIcon,
  BrainCircuitIcon,
  CheckIcon,
  FileSearchIcon,
  Loader2Icon,
  SearchIcon,
  SparklesIcon,
  XIcon,
} from "lucide-react";
import { useDeferredValue, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { MarkdownContent } from "@/components/workspace/messages/markdown-content";
import {
  listKnowledgeDebugBooks,
  runKnowledgeDebugQdrantSearch,
  runKnowledgeDebugToolSearch,
  type KnowledgeDebugBookInfo,
  type KnowledgeDebugQdrantResponse,
  type KnowledgeDebugToolResponse,
} from "@/core/knowledge/api";
import { cn } from "@/lib/utils";

function formatLanguageLabel(languageHint?: string | null) {
  if (!languageHint) return "未标注";
  const labels: Record<string, string> = {
    "zh-Hans": "简体中文",
    "zh-CN": "简体中文",
    "zh-Hant": "繁体中文",
    "zh-TW": "繁体中文",
    "zh-HK": "繁体中文",
    en: "英文",
  };
  return labels[languageHint] ? `${labels[languageHint]} · ${languageHint}` : languageHint;
}

function formatStatusLabel(status?: string | null) {
  if (!status) return "未知";
  const labels: Record<string, string> = {
    indexed: "已入库",
    indexing: "入库中",
    queued_embedding: "待入库",
    parsing: "解析中",
    queued_ocr: "待解析",
    uploaded: "仅上传",
    failed: "失败",
    index_failed: "入库失败",
  };
  return labels[status] ?? status;
}

function toneOfStatus(status?: string | null) {
  if (status === "indexed") return "bg-emerald-100 text-emerald-800 border-emerald-200";
  if (status === "indexing" || status === "queued_embedding" || status === "parsing" || status === "queued_ocr") {
    return "bg-amber-100 text-amber-900 border-amber-200";
  }
  if (status === "failed" || status === "index_failed") {
    return "bg-rose-100 text-rose-800 border-rose-200";
  }
  return "bg-stone-100 text-stone-700 border-stone-200";
}

function formatElapsed(elapsedMs?: number) {
  if (typeof elapsedMs !== "number" || Number.isNaN(elapsedMs)) return "-";
  return `${elapsedMs.toFixed(1)} ms`;
}

function scoreLabel(score?: number) {
  if (typeof score !== "number" || Number.isNaN(score)) return "-";
  return score.toFixed(3);
}

function snippet(text: string, maxLength = 120) {
  const normalized = text.replace(/\s+/g, " ").trim();
  if (normalized.length <= maxLength) return normalized;
  return `${normalized.slice(0, maxLength)}…`;
}

export default function KnowledgeDebugPage() {
  const [query, setQuery] = useState("张之洞 生平 官职 总督");
  const [bookFilter, setBookFilter] = useState("");
  const deferredBookFilter = useDeferredValue(bookFilter);
  const [selectedDocIds, setSelectedDocIds] = useState<string[]>([]);
  const [topK, setTopK] = useState("8");
  const [qdrantResult, setQdrantResult] = useState<KnowledgeDebugQdrantResponse | null>(null);
  const [toolResult, setToolResult] = useState<KnowledgeDebugToolResponse | null>(null);

  useEffect(() => {
    document.title = "知识检索实验台 - Hilo";
  }, []);

  const booksQuery = useQuery({
    queryKey: ["knowledge-debug-books"],
    queryFn: listKnowledgeDebugBooks,
  });

  const books = booksQuery.data?.books ?? [];

  useEffect(() => {
    if (selectedDocIds.length > 0 || books.length === 0) {
      return;
    }
    const preferred =
      books.find((book) => book.parse_status === "indexed") ??
      books.find((book) => book.indexable) ??
      books[0];
    if (preferred) {
      setSelectedDocIds([preferred.doc_id]);
    }
  }, [books, selectedDocIds.length]);

  const filteredBooks = useMemo(() => {
    const keyword = deferredBookFilter.trim().toLowerCase();
    if (!keyword) return books;
    return books.filter((book) =>
      [book.title, book.filename, book.folder, book.summary, book.doc_id, book.language_hint]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(keyword)),
    );
  }, [books, deferredBookFilter]);

  const selectedBooks = useMemo(() => {
    const byId = new Map(books.map((book) => [book.doc_id, book]));
    return selectedDocIds
      .map((docId) => byId.get(docId))
      .filter((book): book is KnowledgeDebugBookInfo => Boolean(book));
  }, [books, selectedDocIds]);

  const allVisibleSelected = useMemo(
    () => filteredBooks.length > 0 && filteredBooks.every((book) => selectedDocIds.includes(book.doc_id)),
    [filteredBooks, selectedDocIds],
  );

  const normalizedTopK = useMemo(() => {
    const parsed = Number.parseInt(topK, 10);
    if (Number.isNaN(parsed)) return 8;
    return Math.min(20, Math.max(1, parsed));
  }, [topK]);

  const qdrantMutation = useMutation({
    mutationFn: runKnowledgeDebugQdrantSearch,
    onSuccess: (data) => {
      setQdrantResult(data);
      toast.success(`Qdrant 返回 ${data.results.length} 条结果`);
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });

  const toolMutation = useMutation({
    mutationFn: runKnowledgeDebugToolSearch,
    onSuccess: (data) => {
      setToolResult(data);
      toast.success("knowledge_search 调试调用完成");
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });

  function toggleBook(docId: string) {
    setSelectedDocIds((current) =>
      current.includes(docId)
        ? current.filter((item) => item !== docId)
        : [...current, docId],
    );
  }

  function selectVisibleBooks() {
    setSelectedDocIds((current) => {
      const merged = new Set(current);
      for (const book of filteredBooks) {
        merged.add(book.doc_id);
      }
      return Array.from(merged);
    });
  }

  function clearVisibleBooks() {
    setSelectedDocIds((current) =>
      current.filter((docId) => !filteredBooks.some((book) => book.doc_id === docId)),
    );
  }

  function buildPayload() {
    const trimmedQuery = query.trim();
    if (!trimmedQuery) {
      toast.error("请先输入检索问题");
      return null;
    }
    if (selectedDocIds.length === 0) {
      toast.error("请至少选择一本书");
      return null;
    }
    return {
      query: trimmedQuery,
      doc_ids: selectedDocIds,
      top_k: normalizedTopK,
    };
  }

  async function runQdrant() {
    const payload = buildPayload();
    if (!payload) return;
    await qdrantMutation.mutateAsync(payload);
  }

  async function runKnowledgeSearch() {
    const payload = buildPayload();
    if (!payload) return;
    await toolMutation.mutateAsync(payload);
  }

  async function runBoth() {
    const payload = buildPayload();
    if (!payload) return;
    await Promise.allSettled([
      qdrantMutation.mutateAsync(payload),
      toolMutation.mutateAsync(payload),
    ]);
  }

  const isRunning = qdrantMutation.isPending || toolMutation.isPending;

  return (
    <WorkspaceContainer>
      <WorkspaceHeader />
      <WorkspaceBody className="bg-[radial-gradient(circle_at_top_left,rgba(163,138,82,0.12),transparent_28%),linear-gradient(180deg,rgba(255,255,255,0.92),rgba(253,252,240,1))]">
        <div className="flex h-full w-full flex-col gap-4 p-4 md:p-6">
          <Card className="border-primary/10 bg-[linear-gradient(135deg,rgba(126,51,46,0.96),rgba(163,138,82,0.88))] text-primary-foreground shadow-lg">
            <CardHeader className="gap-3">
              <div className="flex items-center gap-2 text-xs uppercase tracking-[0.35em] text-primary-foreground/75">
                <SparklesIcon className="size-4" />
                Retrieval Lab
              </div>
              <CardTitle className="font-serif text-2xl md:text-3xl">知识检索实验台</CardTitle>
              <CardDescription className="max-w-3xl text-primary-foreground/80">
                同一批书、同一条问题，直接对比 Qdrant 向量检索和当前保守模式下的
                `knowledge_search` 结果。书目会自动发现，你只需要选书和改 query。
              </CardDescription>
            </CardHeader>
          </Card>

          <div className="grid min-h-0 flex-1 gap-4 xl:grid-cols-[360px_minmax(0,1fr)]">
            <Card className="min-h-0 border-primary/10 bg-white/80 shadow-sm backdrop-blur">
              <CardHeader className="space-y-3">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <CardTitle className="flex items-center gap-2 font-serif text-xl">
                      <BookTextIcon className="size-5 text-primary" />
                      选书
                    </CardTitle>
                    <CardDescription>
                      自动发现可测书目，支持多选后联合检索。
                    </CardDescription>
                  </div>
                  <Badge variant="secondary" className="border border-primary/10 bg-primary/5 text-primary">
                    已选 {selectedDocIds.length}
                  </Badge>
                </div>
                <Input
                  value={bookFilter}
                  onChange={(event) => setBookFilter(event.target.value)}
                  placeholder="筛选书名 / 目录 / 语言 / doc_id"
                  className="border-primary/10 bg-white"
                />
                <div className="flex flex-wrap gap-2">
                  <Button
                    type="button"
                    size="sm"
                    variant="secondary"
                    className="border border-primary/10"
                    onClick={allVisibleSelected ? clearVisibleBooks : selectVisibleBooks}
                    disabled={filteredBooks.length === 0}
                  >
                    {allVisibleSelected ? "取消当前筛选" : "选中当前筛选"}
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    onClick={() => setSelectedDocIds([])}
                    disabled={selectedDocIds.length === 0}
                  >
                    清空
                  </Button>
                </div>
              </CardHeader>
              <CardContent className="min-h-0">
                <ScrollArea className="h-[52vh] pr-3 xl:h-[calc(100vh-22rem)]">
                  <div className="space-y-3">
                    {booksQuery.isLoading && (
                      <div className="flex items-center gap-2 rounded-xl border border-dashed border-primary/15 bg-primary/5 px-4 py-6 text-sm text-muted-foreground">
                        <Loader2Icon className="size-4 animate-spin" />
                        正在发现书目…
                      </div>
                    )}
                    {booksQuery.error && (
                      <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-4 text-sm text-rose-700">
                        {(booksQuery.error as Error).message}
                      </div>
                    )}
                    {!booksQuery.isLoading && !booksQuery.error && filteredBooks.length === 0 && (
                      <div className="rounded-xl border border-dashed border-primary/15 bg-primary/5 px-4 py-6 text-sm text-muted-foreground">
                        当前筛选没有匹配到书。
                      </div>
                    )}
                    {filteredBooks.map((book) => {
                      const selected = selectedDocIds.includes(book.doc_id);
                      return (
                        <button
                          key={book.doc_id}
                          type="button"
                          onClick={() => toggleBook(book.doc_id)}
                          className={cn(
                            "w-full rounded-2xl border p-4 text-left transition-all",
                            selected
                              ? "border-primary bg-primary/5 shadow-sm ring-1 ring-primary/15"
                              : "border-primary/10 bg-white hover:border-primary/25 hover:bg-stone-50",
                          )}
                        >
                          <div className="flex items-start justify-between gap-3">
                            <div className="space-y-1">
                              <div className="font-serif text-base font-semibold text-foreground">
                                {book.title}
                              </div>
                              <div className="text-xs text-muted-foreground">{book.filename}</div>
                            </div>
                            <div
                              className={cn(
                                "flex size-6 shrink-0 items-center justify-center rounded-full border",
                                selected
                                  ? "border-primary bg-primary text-primary-foreground"
                                  : "border-primary/15 bg-white text-transparent",
                              )}
                            >
                              <CheckIcon className="size-3.5" />
                            </div>
                          </div>
                          <div className="mt-3 flex flex-wrap gap-2">
                            <Badge variant="outline" className="border-primary/10 bg-white/70">
                              {book.folder || "未分类"}
                            </Badge>
                            <Badge variant="outline" className="border-primary/10 bg-white/70">
                              {formatLanguageLabel(book.language_hint)}
                            </Badge>
                            <Badge className={cn("border", toneOfStatus(book.parse_status))}>
                              {formatStatusLabel(book.parse_status)}
                            </Badge>
                          </div>
                          <div className="mt-3 text-xs leading-5 text-muted-foreground">
                            {book.summary ? snippet(book.summary, 140) : "暂无 metadata 摘要"}
                          </div>
                          <div className="mt-3 truncate text-[11px] text-muted-foreground">
                            doc_id: {book.doc_id}
                          </div>
                        </button>
                      );
                    })}
                  </div>
                </ScrollArea>
              </CardContent>
            </Card>

            <div className="grid min-h-0 gap-4">
              <Card className="border-primary/10 bg-white/85 shadow-sm backdrop-blur">
                <CardHeader className="space-y-3">
                  <CardTitle className="flex items-center gap-2 font-serif text-xl">
                    <FileSearchIcon className="size-5 text-primary" />
                    检索请求
                  </CardTitle>
                  <CardDescription>
                    这里改 query 和结果条数，然后分别测试两条检索路径。
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  <Textarea
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    placeholder="例如：張之洞 生平 官職 總督"
                    className="min-h-28 border-primary/10 bg-white"
                  />
                  <div className="grid gap-4 md:grid-cols-[160px_minmax(0,1fr)]">
                    <div className="space-y-2">
                      <div className="text-sm font-medium text-foreground">Top K</div>
                      <Input
                        value={topK}
                        onChange={(event) => setTopK(event.target.value)}
                        inputMode="numeric"
                        className="border-primary/10 bg-white"
                      />
                    </div>
                    <div className="rounded-2xl border border-primary/10 bg-stone-50/80 p-4">
                      <div className="text-sm font-medium text-foreground">当前选择</div>
                      <div className="mt-2 flex flex-wrap gap-2">
                        {selectedBooks.length > 0 ? (
                          selectedBooks.map((book) => (
                            <Badge
                              key={book.doc_id}
                              variant="secondary"
                              className="border border-primary/10 bg-white text-foreground"
                            >
                              {book.title}
                            </Badge>
                          ))
                        ) : (
                          <span className="text-sm text-muted-foreground">尚未选择书籍</span>
                        )}
                      </div>
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-3">
                    <Button
                      type="button"
                      onClick={runQdrant}
                      disabled={isRunning}
                      className="bg-primary text-primary-foreground hover:bg-primary/90"
                    >
                      {qdrantMutation.isPending ? (
                        <Loader2Icon className="mr-2 size-4 animate-spin" />
                      ) : (
                        <BrainCircuitIcon className="mr-2 size-4" />
                      )}
                      测 Qdrant
                    </Button>
                    <Button
                      type="button"
                      onClick={runKnowledgeSearch}
                      disabled={isRunning}
                      variant="secondary"
                      className="border border-primary/10"
                    >
                      {toolMutation.isPending ? (
                        <Loader2Icon className="mr-2 size-4 animate-spin" />
                      ) : (
                        <SearchIcon className="mr-2 size-4" />
                      )}
                      测 knowledge_search
                    </Button>
                    <Button
                      type="button"
                      onClick={runBoth}
                      disabled={isRunning}
                      variant="outline"
                      className="border-primary/20"
                    >
                      全部跑一遍
                    </Button>
                  </div>
                </CardContent>
              </Card>

              <Tabs defaultValue="qdrant" className="min-h-0">
                <TabsList className="grid w-full grid-cols-2 bg-primary/5">
                  <TabsTrigger value="qdrant">Qdrant 向量检索</TabsTrigger>
                  <TabsTrigger value="knowledge-search">knowledge_search</TabsTrigger>
                </TabsList>

                <TabsContent value="qdrant" className="min-h-0">
                  <Card className="min-h-0 border-primary/10 bg-white/85 shadow-sm backdrop-blur">
                    <CardHeader>
                      <CardTitle className="flex items-center gap-2 font-serif text-xl">
                        <BrainCircuitIcon className="size-5 text-primary" />
                        Qdrant 结果
                      </CardTitle>
                      <CardDescription>
                        直接走向量检索，方便看 embedding 路径实际打回了什么。
                      </CardDescription>
                    </CardHeader>
                    <CardContent className="min-h-0">
                      <div className="mb-4 flex flex-wrap gap-3 text-sm text-muted-foreground">
                        <Badge variant="secondary" className="border border-primary/10 bg-primary/5 text-primary">
                          {qdrantResult ? `${qdrantResult.results.length} 条结果` : "尚未运行"}
                        </Badge>
                        <Badge variant="outline" className="border-primary/10">
                          耗时 {formatElapsed(qdrantResult?.elapsed_ms)}
                        </Badge>
                      </div>
                      <ScrollArea className="h-[42vh] pr-3 xl:h-[calc(100vh-30rem)]">
                        <div className="space-y-3">
                          {!qdrantResult && (
                            <div className="rounded-xl border border-dashed border-primary/15 bg-primary/5 px-4 py-8 text-sm text-muted-foreground">
                              先点一次“测 Qdrant”看看向量检索命中了哪些段落。
                            </div>
                          )}
                          {qdrantResult?.results.map((result, index) => (
                            <Card key={`${result.doc_id ?? result.filename}-${index}`} className="border-primary/10 bg-white">
                              <CardContent className="space-y-3 p-4">
                                <div className="flex flex-wrap items-center gap-2">
                                  <Badge className="border border-primary/10 bg-primary/5 text-primary">
                                    #{index + 1}
                                  </Badge>
                                  <Badge variant="outline" className="border-primary/10">
                                    分数 {scoreLabel(result.score)}
                                  </Badge>
                                  {result.page_no ? (
                                    <Badge variant="outline" className="border-primary/10">
                                      第 {result.page_no} 页
                                    </Badge>
                                  ) : null}
                                  {result.paragraph_no ? (
                                    <Badge variant="outline" className="border-primary/10">
                                      第 {result.paragraph_no} 段
                                    </Badge>
                                  ) : null}
                                </div>
                                <div>
                                  <div className="font-serif text-base font-semibold text-foreground">
                                    {result.title || result.filename}
                                  </div>
                                  <div className="mt-1 text-xs text-muted-foreground">
                                    {result.filename}
                                  </div>
                                </div>
                                <p className="text-sm leading-7 whitespace-pre-wrap text-foreground">
                                  {result.content}
                                </p>
                                <Separator />
                                <div className="flex flex-wrap gap-3 text-xs text-muted-foreground">
                                  {result.doc_id ? <span>doc_id: {result.doc_id}</span> : null}
                                  {result.scope ? <span>scope: {result.scope}</span> : null}
                                  {result.source_kind ? <span>source_kind: {result.source_kind}</span> : null}
                                </div>
                              </CardContent>
                            </Card>
                          ))}
                        </div>
                      </ScrollArea>
                    </CardContent>
                  </Card>
                </TabsContent>

                <TabsContent value="knowledge-search" className="min-h-0">
                  <Card className="min-h-0 border-primary/10 bg-white/85 shadow-sm backdrop-blur">
                    <CardHeader>
                      <CardTitle className="flex items-center gap-2 font-serif text-xl">
                        <SearchIcon className="size-5 text-primary" />
                        knowledge_search 输出
                      </CardTitle>
                      <CardDescription>
                        这里直接显示工具渲染后的结果，最适合检查提示词、引用和命中页是否符合预期。
                      </CardDescription>
                    </CardHeader>
                    <CardContent className="min-h-0">
                      <div className="mb-4 flex flex-wrap gap-3 text-sm text-muted-foreground">
                        <Badge variant="secondary" className="border border-primary/10 bg-primary/5 text-primary">
                          {toolResult ? "已返回渲染结果" : "尚未运行"}
                        </Badge>
                        <Badge variant="outline" className="border-primary/10">
                          耗时 {formatElapsed(toolResult?.elapsed_ms)}
                        </Badge>
                      </div>
                      <ScrollArea className="h-[42vh] pr-3 xl:h-[calc(100vh-30rem)]">
                        {!toolResult ? (
                          <div className="rounded-xl border border-dashed border-primary/15 bg-primary/5 px-4 py-8 text-sm text-muted-foreground">
                            先点一次“测 knowledge_search”查看工具的完整输出。
                          </div>
                        ) : (
                          <div className="rounded-2xl border border-primary/10 bg-white p-5">
                            <MarkdownContent
                              content={toolResult.output}
                              isLoading={false}
                              rehypePlugins={[]}
                              className="prose prose-stone max-w-none text-sm leading-7"
                            />
                          </div>
                        )}
                      </ScrollArea>
                    </CardContent>
                  </Card>
                </TabsContent>
              </Tabs>
            </div>
          </div>
        </div>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}
