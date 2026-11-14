"use client";

import {
  Code2Icon,
  CopyIcon,
  EyeIcon,
  XIcon,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { Streamdown } from "streamdown";

import {
  Artifact,
  ArtifactAction,
  ArtifactActions,
  ArtifactContent,
  ArtifactHeader,
  ArtifactTitle,
} from "@/components/ai-elements/artifact";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { CodeEditor } from "@/components/workspace/code-editor";
import { useI18n } from "@/core/i18n/hooks";
import {
  getKnowledgeParagraphLocationForDocumentUrl,
  getKnowledgeStructuredPageForDocumentUrl,
  type KnowledgeParagraphLocation,
} from "@/core/knowledge/api";
import {
  getKnowledgeCitationMeta,
  getKnowledgeCitationPageRef,
} from "@/core/knowledge/citation-meta";
import { streamdownPlugins } from "@/core/streamdown";
import { cn } from "@/lib/utils";

import { CitationLink } from "../citations/citation-link";

import { KnowledgePdfReader } from "./knowledge-pdf-reader";

type PreviewVariant = "rendered" | "original" | "split";

const KNOWLEDGE_URL_BASE = "http://localhost:2026";

function parseKnowledgeDocumentUrl(documentUrl: string) {
  return new URL(documentUrl, KNOWLEDGE_URL_BASE);
}

export function KnowledgeDocumentDetail({
  className,
  documentUrl,
  displayName,
  initialPdfPageNo,
  knowledgeSpaceId,
  onClose,
  onCompareToggle,
  originFilename,
  originTitle,
}: {
  className?: string;
  documentUrl: string;
  displayName: string;
  initialPdfPageNo?: number;
  knowledgeSpaceId?: string;
  onClose?: () => void;
  onCompareToggle?: (open: boolean) => void;
  originFilename?: string;
  originTitle?: string;
}) {
  const { t } = useI18n();
  const [markdownPreviewVariant, setMarkdownPreviewVariant] =
    useState<PreviewVariant>("split");
  const [viewMode, setViewMode] = useState<"code" | "preview">("code");
  const [knowledgeContent, setKnowledgeContent] = useState<string | null>(null);
  const [isKnowledgeLoading, setIsKnowledgeLoading] = useState(false);
  const [knowledgeError, setKnowledgeError] = useState<Error | null>(null);

  const knowledgeCitationMeta = useMemo(
    () => getKnowledgeCitationMeta(documentUrl),
    [documentUrl],
  );

  const knowledgeSnippet = useMemo(() => {
    try {
      const url = parseKnowledgeDocumentUrl(documentUrl);
      const value = url.searchParams.get("snippet");
      if (!value) {
        return null;
      }
      return value.slice(0, 256);
    } catch {
      return null;
    }
  }, [documentUrl]);

  const knowledgePdfPage = useMemo(() => {
    const pageRef = getKnowledgeCitationPageRef(documentUrl);
    return pageRef.startPage ? pageRef.startPage - 1 : null;
  }, [documentUrl]);

  const isKnowledgePdf = useMemo(() => {
    try {
      const url = parseKnowledgeDocumentUrl(documentUrl);
      return url.pathname.toLowerCase().endsWith(".pdf");
    } catch {
      return false;
    }
  }, [documentUrl]);

  const knowledgePdfUrl = useMemo(() => {
    if (!isKnowledgePdf) {
      return null;
    }
    try {
      const url = parseKnowledgeDocumentUrl(documentUrl);
      url.searchParams.delete("snippet");
      url.searchParams.delete("page");
      url.searchParams.delete("page_no");
      url.searchParams.delete("pdf_page_no");
      url.searchParams.delete("paragraph_no");
      return `${url.pathname}${url.search}`;
    } catch {
      return null;
    }
  }, [documentUrl, isKnowledgePdf]);

  const knowledgePdfLocator = useMemo(() => {
    if (!isKnowledgePdf) {
      return null;
    }
    try {
      const url = parseKnowledgeDocumentUrl(documentUrl);
      const pageRef = getKnowledgeCitationPageRef(documentUrl);
      return {
        filename: decodeURIComponent(url.pathname.split("/").pop() ?? ""),
        pageNo: url.searchParams.get("page_no"),
        pdfPageNo: url.searchParams.get("pdf_page_no"),
        paragraphNo: url.searchParams.get("paragraph_no"),
        pageRef,
      };
    } catch {
      return null;
    }
  }, [documentUrl, isKnowledgePdf]);

  useEffect(() => {
    if (isKnowledgePdf) {
      return;
    }

    let cancelled = false;
    setIsKnowledgeLoading(true);
    setKnowledgeError(null);
    fetch(documentUrl)
      .then((response) => {
        if (!response.ok) {
          throw new Error("Failed to load knowledge document");
        }
        return response.text();
      })
      .then((text) => {
        if (!cancelled) {
          setKnowledgeContent(text);
        }
      })
      .catch((error) => {
        if (!cancelled) {
          console.error("Failed to load knowledge document:", error);
          setKnowledgeError(error as Error);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setIsKnowledgeLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [documentUrl, isKnowledgePdf]);

  useEffect(() => {
    setMarkdownPreviewVariant("split");
  }, [documentUrl]);

  useEffect(() => {
    if (isKnowledgePdf) {
      return;
    }
    setViewMode("preview");
  }, [documentUrl, isKnowledgePdf]);

  const displayContent = useMemo(() => {
    if (knowledgeError) {
      return knowledgeError.message;
    }
    if (isKnowledgeLoading) {
      return "Loading knowledge document...";
    }
    return knowledgeContent ?? "";
  }, [isKnowledgeLoading, knowledgeContent, knowledgeError]);

  const resolvedOriginFilename = originFilename ?? displayName;
  const resolvedOriginTitle =
    originTitle ?? displayName.replace(/\.pdf$/i, "");

  return (
    <Artifact className={cn(className)}>
      <ArtifactHeader className="px-2">
        <div className="flex items-center gap-2">
          <ArtifactTitle>
            <div className="px-2">{displayName}</div>
          </ArtifactTitle>
        </div>
        <div className="flex min-w-0 grow items-center justify-center">
          {!isKnowledgePdf && (
            <ToggleGroup
              className="mx-auto"
              type="single"
              variant="outline"
              size="sm"
              value={viewMode}
              onValueChange={(value) => setViewMode(value as "code" | "preview")}
            >
              <ToggleGroupItem value="code">
                <Code2Icon />
              </ToggleGroupItem>
              <ToggleGroupItem value="preview">
                <EyeIcon />
              </ToggleGroupItem>
            </ToggleGroup>
          )}
        </div>
        <div className="flex items-center gap-2">
          <ArtifactActions>
            {!isKnowledgePdf && (
              <ArtifactAction
                icon={CopyIcon}
                label={t.clipboard.copyToClipboard}
                disabled={!displayContent}
                onClick={async () => {
                  try {
                    await navigator.clipboard.writeText(displayContent);
                    toast.success(t.clipboard.copiedToClipboard);
                  } catch (error) {
                    toast.error("Failed to copy to clipboard");
                    console.error(error);
                  }
                }}
                tooltip={t.clipboard.copyToClipboard}
              />
            )}
            {onClose && (
              <ArtifactAction
                icon={XIcon}
                label={t.common.close}
                onClick={onClose}
                tooltip={t.common.close}
              />
            )}
          </ArtifactActions>
        </div>
      </ArtifactHeader>
      <ArtifactContent
        className={cn(
          "p-0",
          isKnowledgePdf &&
            knowledgePdfLocator?.filename &&
            (knowledgePdfLocator.pageNo ??
              knowledgePdfLocator.pdfPageNo ??
              knowledgePdfLocator.paragraphNo) &&
            "overflow-hidden",
        )}
      >
        {knowledgeCitationMeta && (
          <KnowledgeCitationSummary
            originTitle={knowledgeCitationMeta.originTitle}
            sourceLabel={knowledgeCitationMeta.sourceLabel}
            sourceTitle={knowledgeCitationMeta.sourceTitle}
          />
        )}
        {isKnowledgePdf && knowledgePdfUrl && (
          knowledgePdfLocator?.filename &&
          (knowledgePdfLocator.pageNo ||
            knowledgePdfLocator.pdfPageNo ||
            knowledgePdfLocator.paragraphNo) ? (
            <KnowledgeCitationPdfViewer
              documentUrl={knowledgePdfUrl}
              knowledgeSpaceId={knowledgeSpaceId}
              pageNo={knowledgePdfLocator.pageNo}
              pdfPageNo={knowledgePdfLocator.pdfPageNo}
              paragraphNo={knowledgePdfLocator.paragraphNo}
              pageRef={knowledgePdfLocator.pageRef}
              onCompareToggle={onCompareToggle}
            />
          ) : (
            <KnowledgeDocumentPdfViewer
              documentUrl={knowledgePdfUrl}
              initialPage={
                knowledgePdfPage ?? Math.max((initialPdfPageNo ?? 1) - 1, 0)
              }
              knowledgeSpaceId={knowledgeSpaceId}
              originFilename={resolvedOriginFilename}
              originTitle={resolvedOriginTitle}
              onCompareToggle={onCompareToggle}
            />
          )
        )}
        {!isKnowledgePdf && viewMode === "preview" && (
          <MarkdownDualPreview
            content={displayContent}
            highlightSnippet={knowledgeSnippet}
            mode={markdownPreviewVariant}
            onModeChange={setMarkdownPreviewVariant}
            rawUrl={documentUrl}
          />
        )}
        {!isKnowledgePdf && viewMode === "code" && (
          <CodeEditor
            className="size-full resize-none rounded-none border-none"
            value={displayContent}
            readonly
          />
        )}
      </ArtifactContent>
    </Artifact>
  );
}

function KnowledgeDocumentPdfViewer({
  documentUrl,
  initialPage,
  knowledgeSpaceId,
  originFilename,
  originTitle,
  onCompareToggle,
}: {
  documentUrl: string;
  initialPage: number;
  knowledgeSpaceId?: string;
  originFilename: string;
  originTitle: string;
  onCompareToggle?: (open: boolean) => void;
}) {
  useEffect(() => {
    onCompareToggle?.(false);
    return () => onCompareToggle?.(false);
  }, [onCompareToggle]);

  return (
    <KnowledgePdfReader
      documentUrl={documentUrl}
      initialPdfPageNo={initialPage + 1}
      knowledgeSpaceId={knowledgeSpaceId}
      originFilename={originFilename}
      originTitle={originTitle}
      onCompareToggle={onCompareToggle}
    />
  );
}

function KnowledgeCitationPdfViewer({
  documentUrl,
  knowledgeSpaceId,
  pageNo,
  pdfPageNo,
  paragraphNo,
  pageRef,
  onCompareToggle,
}: {
  documentUrl: string;
  knowledgeSpaceId?: string;
  pageNo: string | null;
  pdfPageNo: string | null;
  paragraphNo: string | null;
  pageRef: ReturnType<typeof getKnowledgeCitationPageRef>;
  onCompareToggle?: (open: boolean) => void;
}) {
  const [state, setState] = useState<
    | { status: "loading" }
    | { status: "error"; message: string }
    | {
        status: "ready";
        data: {
          filename: string;
          title: string;
          initialPdfPageNo: number;
          focusedPdfPageNo: number | null;
          focusedParagraphNo: number | null;
          focusedParagraphText: string | null;
        };
      }
  >({ status: "loading" });

  useEffect(() => {
    onCompareToggle?.(false);
    return () => onCompareToggle?.(false);
  }, [onCompareToggle]);

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    const isPageRange =
      pageRef.isRange && !paragraphNo && (pageRef.queryParam === "page_no" || pageRef.queryParam === "pdf_page_no");

    const request = isPageRange && pageRef.startPage
      ? getKnowledgeStructuredPageForDocumentUrl(documentUrl, {
          pageNo: pageRef.queryParam === "page_no" ? pageRef.startPage : null,
          pdfPageNo: pageRef.queryParam === "pdf_page_no" ? pageRef.startPage : null,
        }).then((data) => ({
          filename: data.filename,
          title: data.title,
          initialPdfPageNo: data.pdf_page_no ?? pageRef.startPage ?? 1,
          focusedPdfPageNo: null,
          focusedParagraphNo: null,
          focusedParagraphText: null,
        }))
      : getKnowledgeParagraphLocationForDocumentUrl(documentUrl, {
          pageNo,
          pdfPageNo,
          paragraphNo,
        }).then((data: KnowledgeParagraphLocation) => ({
          filename: data.filename,
          title: data.title,
          initialPdfPageNo: data.pdf_page_no ?? 1,
          focusedPdfPageNo: data.pdf_page_no ?? null,
          focusedParagraphNo: data.paragraph_no ?? null,
          focusedParagraphText: data.text ?? null,
        }));

    request
      .then((data) => {
        if (!cancelled) {
          setState({ status: "ready", data });
        }
      })
      .catch((error: Error) => {
        if (!cancelled) {
          setState({
            status: "error",
            message: error.message || "定位信息加载失败",
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [documentUrl, pageNo, pageRef, paragraphNo, pdfPageNo]);

  if (state.status === "loading") {
    return (
      <div className="flex size-full items-center justify-center bg-muted/30 p-4 text-sm text-muted-foreground">
        正在加载 citation 定位...
      </div>
    );
  }

  if (state.status === "error") {
    return (
      <div className="flex size-full items-center justify-center bg-red-50 p-4 text-sm text-red-700">
        {state.message}
      </div>
    );
  }

  return (
    <KnowledgePdfReader
      documentUrl={documentUrl}
      initialPdfPageNo={state.data.initialPdfPageNo}
      knowledgeSpaceId={knowledgeSpaceId}
      originFilename={state.data.filename}
      originTitle={state.data.title}
      onCompareToggle={onCompareToggle}
      focusedPdfPageNo={state.data.focusedPdfPageNo}
      focusedParagraphNo={state.data.focusedParagraphNo}
      focusedParagraphText={state.data.focusedParagraphText}
    />
  );
}

function MarkdownDualPreview({
  content,
  highlightSnippet,
  mode,
  onModeChange,
  rawUrl,
}: {
  content: string;
  highlightSnippet?: string | null;
  mode: PreviewVariant;
  onModeChange: (mode: PreviewVariant) => void;
  rawUrl: string;
}) {
  const showRendered = mode !== "original";
  const showOriginal = mode !== "rendered";
  const containerClass =
    mode === "split"
      ? "grid items-stretch gap-4 px-4 pb-4 md:grid-cols-2"
      : "px-4 pb-4";
  const panelClassName = "rounded-2xl border border-border/40 bg-muted p-4";

  return (
    <div className="space-y-3 border-t border-border/30">
      <div className="flex flex-wrap items-center gap-2 px-4 pt-4">
        <span className="text-xs font-semibold uppercase tracking-[0.2em] text-muted-foreground">
          展示方式
        </span>
        <ToggleGroup
          type="single"
          variant="outline"
          size="sm"
          value={mode}
          onValueChange={(value) => onModeChange(value as PreviewVariant)}
        >
          <ToggleGroupItem value="rendered">渲染视图</ToggleGroupItem>
          <ToggleGroupItem value="original">原文</ToggleGroupItem>
          <ToggleGroupItem value="split">双栏</ToggleGroupItem>
        </ToggleGroup>
        <a
          className="text-xs font-medium text-primary underline-offset-2 hover:underline"
          href={rawUrl}
          target="_blank"
          rel="noreferrer"
        >
          在新标签打开原文
        </a>
      </div>
      <div className={containerClass}>
        {showRendered && (
          <div className={cn(panelClassName, mode === "split" && "h-full")}>
            <HighlightedMarkdownPreview
              content={content}
              highlightSnippet={highlightSnippet}
            />
          </div>
        )}
        {showOriginal && (
          <div
            className={cn(
              "overflow-hidden rounded-2xl border border-border/40",
              mode === "split" && "h-full",
            )}
          >
            <iframe
              className="h-full min-h-[360px] w-full bg-background"
              src={rawUrl}
            />
          </div>
        )}
      </div>
    </div>
  );
}

function KnowledgeCitationSummary({
  sourceLabel,
  sourceTitle,
  originTitle,
}: {
  sourceLabel: string | null;
  sourceTitle: string | null;
  originTitle: string | null;
}) {
  if ((!sourceLabel || sourceLabel === "知识库文档") && !originTitle) {
    return null;
  }

  return (
    <div className="border-b border-border/40 bg-amber-50/55 px-4 py-3">
      <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-amber-900/70">
        引用来源
      </p>
      {sourceLabel && (
        <p className="mt-1 text-sm text-stone-900">
          这条 citation 来自{sourceLabel}
          {sourceTitle ? `《${sourceTitle}》` : ""}
        </p>
      )}
      {originTitle && originTitle !== sourceTitle && (
        <p className="mt-1 text-xs text-stone-600">
          原始出处：{originTitle}
        </p>
      )}
    </div>
  );
}

function normalizeHighlightSnippet(snippet: string | null | undefined): string | null {
  if (!snippet) {
    return null;
  }
  const firstMeaningfulLine = snippet
    .split(/\r?\n/)
    .map((line) => line.trim())
    .find(Boolean);
  if (!firstMeaningfulLine) {
    return null;
  }
  return firstMeaningfulLine.slice(0, 120);
}

function clearHighlight(root: HTMLElement) {
  root.querySelectorAll("span[data-kb-highlight='true']").forEach((node) => {
    const parent = node.parentNode;
    if (!parent) {
      return;
    }
    while (node.firstChild) {
      parent.insertBefore(node.firstChild, node);
    }
    parent.removeChild(node);
    parent.normalize();
  });
}

function applyHighlight(root: HTMLElement, snippet: string): HTMLElement | null {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      const parent = node.parentElement;
      if (!parent || !node.textContent?.trim()) {
        return NodeFilter.FILTER_SKIP;
      }
      if (["SCRIPT", "STYLE"].includes(parent.tagName)) {
        return NodeFilter.FILTER_REJECT;
      }
      return NodeFilter.FILTER_ACCEPT;
    },
  });

  while (walker.nextNode()) {
    const node = walker.currentNode as Text;
    const content = node.textContent ?? "";
    const index = content.indexOf(snippet);
    if (index === -1) {
      continue;
    }

    const startNode = node.splitText(index);
    const trailingNode = startNode.splitText(snippet.length);
    const highlight = document.createElement("span");
    highlight.dataset.kbHighlight = "true";
    highlight.className =
      "rounded-[3px] underline decoration-amber-500 decoration-2 underline-offset-4 bg-amber-100/70";
    startNode.parentNode?.insertBefore(highlight, trailingNode);
    highlight.appendChild(startNode);
    return highlight;
  }

  return null;
}

function HighlightedMarkdownPreview({
  content,
  highlightSnippet,
}: {
  content: string;
  highlightSnippet?: string | null;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const root = containerRef.current;
    if (!root) {
      return;
    }

    clearHighlight(root);
    const snippet = normalizeHighlightSnippet(highlightSnippet);
    if (!snippet) {
      return;
    }

    const timeout = window.setTimeout(() => {
      const target = applyHighlight(root, snippet);
      target?.scrollIntoView({ behavior: "smooth", block: "center" });
    }, 80);

    return () => {
      window.clearTimeout(timeout);
      clearHighlight(root);
    };
  }, [content, highlightSnippet]);

  return (
    <div ref={containerRef}>
      <Streamdown
        className="size-full"
        {...streamdownPlugins}
        components={{ a: CitationLink }}
      >
        {content}
      </Streamdown>
    </div>
  );
}
