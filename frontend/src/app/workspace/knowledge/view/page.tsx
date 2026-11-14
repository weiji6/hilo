"use client";

import { ExternalLinkIcon, Loader2Icon } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { KnowledgeDocumentDetail } from "@/components/workspace/artifacts/knowledge-document-detail";
import {
  buildKnowledgeDocumentUrl,
  buildKnowledgePageImageURLForDocumentUrl,
  getKnowledgeParagraphLocationForDocumentUrl,
  getKnowledgeStructuredPageForDocumentUrl,
  type KnowledgeParagraphLocation,
} from "@/core/knowledge/api";
import { getKnowledgeCitationPageRef } from "@/core/knowledge/citation-meta";

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: KnowledgeParagraphLocation };

export default function KnowledgeViewPage() {
  const searchParams = useSearchParams();
  const mode = searchParams.get("mode");
  const filename = searchParams.get("filename") ?? "";
  const scope = searchParams.get("scope");
  const rawDocumentUrl = normalizeOptionalUrl(searchParams.get("document_url"));
  const pageNo = searchParams.get("page_no");
  const pdfPageNo = searchParams.get("pdf_page_no");
  const paragraphNo = searchParams.get("paragraph_no");
  const explicitOriginalUrl = normalizeOptionalUrl(searchParams.get("original_url"));
  const originTitle = searchParams.get("origin_title") ?? (filename || "未命名资料");
  const originFilename = searchParams.get("origin_filename") ?? (filename || "未知文件");
  const knowledgeSpaceId = searchParams.get("knowledge_space_id");
  const documentUrl = useMemo(() => {
    if (rawDocumentUrl) {
      return rawDocumentUrl;
    }
    if (!filename) {
      return null;
    }
    return buildKnowledgeDocumentUrl(scope === "user" ? "user" : "global", filename);
  }, [filename, rawDocumentUrl, scope]);

  if (mode === "reader") {
    return (
      <KnowledgeReaderPage
        documentUrl={documentUrl}
        filename={filename}
        originFilename={originFilename}
        originTitle={originTitle}
        initialPdfPageNo={parsePositiveInteger(pdfPageNo) ?? 1}
        knowledgeSpaceId={knowledgeSpaceId}
      />
    );
  }

  return (
    <KnowledgeCitationView
      documentUrl={documentUrl}
      pageNo={pageNo}
      pdfPageNo={pdfPageNo}
      paragraphNo={paragraphNo}
      explicitOriginalUrl={explicitOriginalUrl}
    />
  );
}

function KnowledgeReaderPage({
  documentUrl,
  filename,
  originFilename,
  originTitle,
  initialPdfPageNo,
  knowledgeSpaceId,
}: {
  documentUrl: string | null;
  filename: string;
  originFilename: string;
  originTitle: string;
  initialPdfPageNo: number;
  knowledgeSpaceId: string | null;
}) {
  return (
    <div className="h-screen bg-[rgb(247,251,252)] p-0">
      {!documentUrl ? (
        <div className="m-6 rounded-xl bg-red-50 p-8 text-sm text-red-700 shadow-sm">
          缺少文档地址，无法打开结构化阅读器。
        </div>
      ) : (
        <div className="h-full min-h-0 w-full">
          <KnowledgeDocumentDetail
            className="h-full"
            displayName={originFilename || filename}
            documentUrl={documentUrl}
            initialPdfPageNo={initialPdfPageNo}
            knowledgeSpaceId={knowledgeSpaceId ?? undefined}
            originFilename={originFilename || filename}
            originTitle={originTitle}
          />
        </div>
      )}
    </div>
  );
}

function KnowledgeCitationView({
  documentUrl,
  pageNo,
  pdfPageNo,
  paragraphNo,
  explicitOriginalUrl,
}: {
  documentUrl: string | null;
  pageNo: string | null;
  pdfPageNo: string | null;
  paragraphNo: string | null;
  explicitOriginalUrl: string | null;
}) {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const pageRef = useMemo(() => {
    if (!documentUrl) {
      return {
        queryParam: null,
        startPage: null,
        endPage: null,
        isRange: false,
        label: null,
      } as ReturnType<typeof getKnowledgeCitationPageRef>;
    }
    return getKnowledgeCitationPageRef(documentUrl);
  }, [documentUrl]);

  useEffect(() => {
    if (!documentUrl || (!pageNo && !pdfPageNo && !paragraphNo)) {
      setState({ status: "error", message: "缺少定位参数，无法打开 citation viewer。" });
      return;
    }

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
          page_count: data.page_count ?? null,
          page_no: data.page_no ?? null,
          pdf_page_no: data.pdf_page_no ?? pageRef.startPage ?? null,
          book_page_no: data.book_page_no ?? null,
          paragraph_no: null,
          bbox: null,
          page_meta: data.page_meta ?? null,
          text: "",
          source_url: data.source_url ?? null,
          original_url: data.original_url ?? null,
        }))
      : getKnowledgeParagraphLocationForDocumentUrl(documentUrl, {
          pageNo,
          pdfPageNo,
          paragraphNo,
        });

    request
      .then((data) => {
        if (!cancelled) {
          setState({ status: "ready", data });
        }
      })
      .catch((error: Error) => {
        if (!cancelled) {
          setState({ status: "error", message: error.message || "定位信息加载失败" });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [documentUrl, pageNo, pageRef, paragraphNo, pdfPageNo]);

  const originalUrl = explicitOriginalUrl
    ?? (state.status === "ready" ? state.data.original_url ?? null : null);

  return (
    <div className="min-h-screen px-6 py-8">
      <div className="mx-auto flex max-w-6xl flex-col gap-4">
        <div className="space-y-3">
          {originalUrl && (
            <div className="flex justify-end">
              <a
                href={originalUrl}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 rounded-md border border-border/60 bg-white px-3 py-1.5 text-sm text-foreground shadow-sm hover:bg-muted/40"
              >
                打开原文
                <ExternalLinkIcon className="size-4" />
              </a>
            </div>
          )}
          {state.status === "ready" && (
            <div className="space-y-1 text-center">
              <h1 className="text-xl font-semibold tracking-tight text-foreground">
                {state.data.title}
              </h1>
              <div className="text-sm text-muted-foreground">
                {formatLocationLabel(
                  state.data.page_no ?? null,
                  state.data.paragraph_no ?? null,
                )}
              </div>
            </div>
          )}
        </div>

        {state.status === "loading" && (
          <div className="flex items-center gap-2 rounded-xl bg-white p-8 text-sm text-muted-foreground shadow-sm">
            <Loader2Icon className="size-4 animate-spin" />
            正在加载页码与段落定位信息...
          </div>
        )}

        {state.status === "error" && (
          <div className="rounded-xl bg-red-50 p-8 text-sm text-red-700 shadow-sm">
            {state.message}
          </div>
        )}

        {state.status === "ready" && (
          <CitationViewer
            data={state.data}
            documentUrl={documentUrl}
          />
        )}
      </div>
    </div>
  );
}

function CitationViewer({
  data,
  documentUrl,
}: {
  data: KnowledgeParagraphLocation;
  documentUrl: string | null;
}) {
  const [imageSize, setImageSize] = useState<{ width: number; height: number } | null>(null);
  const pageWidth = data.page_meta?.page_width ?? null;
  const pageHeight = data.page_meta?.page_height ?? null;
  const bbox = data.bbox;
  const imageUrl = useMemo(() => {
    if (!documentUrl || !data.pdf_page_no) {
      return null;
    }
    return buildKnowledgePageImageURLForDocumentUrl(documentUrl, data.pdf_page_no);
  }, [data.pdf_page_no, documentUrl]);
  const overlayStyle =
    bbox && pageWidth && pageHeight && imageSize
      ? {
          left: `${(bbox.x / pageWidth) * imageSize.width}px`,
          top: `${(bbox.y / pageHeight) * imageSize.height}px`,
          width: `${(bbox.width / pageWidth) * imageSize.width}px`,
          height: `${(bbox.height / pageHeight) * imageSize.height}px`,
        }
      : null;

  return (
    <div>
      {imageUrl ? (
        <div className="overflow-auto">
          <div className="relative flex justify-center">
            <img
              src={imageUrl}
              alt={`${data.title} PDF page ${data.pdf_page_no ?? ""}`}
              className="max-w-full bg-white"
              onLoad={(event) => {
                const img = event.currentTarget;
                setImageSize({ width: img.clientWidth, height: img.clientHeight });
              }}
            />
            {overlayStyle && (
              <div
                className="pointer-events-none absolute rounded-md border-2 border-emerald-500/90 bg-emerald-300/12"
                style={overlayStyle}
              />
            )}
          </div>
        </div>
      ) : (
        <div className="rounded-lg bg-muted/40 p-6 text-sm text-muted-foreground">
          当前缺少 PDF 页码，无法渲染页面截图。
        </div>
      )}
    </div>
  );
}

function normalizeOptionalUrl(url: string | null): string | null {
  if (!url) {
    return null;
  }
  try {
    return decodeURI(url);
  } catch {
    return url;
  }
}

function parsePositiveInteger(value: string | null) {
  if (!value) {
    return null;
  }
  const parsed = parseInt(value, 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

function formatLocationLabel(pageNo: number | null, paragraphNo: number | null) {
  const parts: string[] = [];
  if (pageNo) {
    parts.push(`第 ${pageNo} 页`);
  }
  if (paragraphNo) {
    parts.push(`第 ${paragraphNo} 段`);
  }
  return parts.join(" · ") || "已定位";
}
