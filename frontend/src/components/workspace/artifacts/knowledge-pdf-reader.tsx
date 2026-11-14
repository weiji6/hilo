"use client";

import {
  CheckIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  CopyIcon,
  FileTextIcon,
  LanguagesIcon,
  Loader2Icon,
  ScrollTextIcon,
} from "lucide-react";
import { useRouter } from "next/navigation";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  buildKnowledgePageImageURLForDocumentUrl,
  getKnowledgeStructuredPageForDocumentUrl,
  resolveKnowledgeDocumentUrl,
  translateKnowledgeParagraphsToChineseForDocumentUrl,
  type KnowledgeStructuredPage,
  type KnowledgeStructuredParagraph,
} from "@/core/knowledge/api";
import { cn } from "@/lib/utils";

import { ExcerptToNoteDialog } from "./excerpt-to-note-dialog";
import { KnowledgePageSurface } from "./knowledge-page-surface";
import { KnowledgeSidePane } from "./knowledge-side-pane";

type ReaderMode = "pdf" | "translation";
type TranslationSourceLanguage = "en" | "ja" | "de";

const LANGUAGE_OPTIONS: Array<{
  value: TranslationSourceLanguage;
  label: string;
}> = [
  { value: "en", label: "英译中" },
  { value: "ja", label: "日译中" },
  { value: "de", label: "德译中" },
];

type PageState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: KnowledgeStructuredPage };

type ContextParagraph = {
  key: string;
  pdfPageNo: number | null;
  pageNo: number | null;
  paragraphNo: number | null;
  text: string;
};

type ContextMenuState = {
  x: number;
  y: number;
  paragraph: ContextParagraph;
};

type ContextMenuTranslationState = {
  loading: boolean;
  error: string | null;
  text: string;
};

type TranslationLayoutItem = {
  contextParagraph: ContextParagraph;
  paragraph: KnowledgeStructuredParagraph;
  source: "current" | "previous-spill";
  baseWidth: number;
  baseHeight: number;
  blockWidth: number;
  blockHeight: number;
  overflowWidth: number;
  overflowHeight: number;
  blockLeft: number;
  blockTop: number;
  textLeft: number;
  textTop: number;
  textWidth: number;
  textHeight: number;
  translatedText: string;
};

type RenderParagraphItem = {
  key: string;
  contextParagraph: ContextParagraph;
  paragraph: KnowledgeStructuredParagraph;
  source: "current" | "previous-spill";
  textLeft: number;
  textTop: number;
  textWidth: number;
  textHeight: number;
  visibleLeft: number;
  visibleTop: number;
  visibleWidth: number;
  visibleHeight: number;
};

const TRANSLATION_LINE_HEIGHT = 1.48;
const VERTICAL_TRANSLATION_LINE_HEIGHT = 1.18;
const TRANSLATION_BLOCK_PADDING_X = 8;
const TRANSLATION_BLOCK_PADDING_Y = 6;
const TRANSLATION_BLOCK_OUTER_PADDING = 8;
const PAGE_OVERFLOW_TOLERANCE = 8;

function paragraphKey(
  page: KnowledgeStructuredPage,
  paragraph: KnowledgeStructuredParagraph,
) {
  return `${page.pdf_page_no ?? page.page_no ?? "page"}:${paragraph.paragraph_id ?? paragraph.paragraph_no ?? paragraph.text}`;
}

function buildContextParagraph(
  page: KnowledgeStructuredPage,
  paragraph: KnowledgeStructuredParagraph,
): ContextParagraph {
  return {
    key: paragraphKey(page, paragraph),
    pdfPageNo: page.pdf_page_no ?? null,
    pageNo: page.page_no ?? null,
    paragraphNo: paragraph.paragraph_no ?? null,
    text: paragraph.text,
  };
}

function characterWidthWeight(character: string) {
  if (!character.trim()) {
    return 0.34;
  }
  if (/[A-Z0-9]/.test(character)) {
    return 0.62;
  }
  if (/[a-z]/.test(character)) {
    return 0.56;
  }
  if (
    /[\u2e80-\u2eff\u2f00-\u2fdf\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff00-\uffef]/.test(
      character,
    )
  ) {
    return 1;
  }
  return 0.48;
}

function estimateTextHeight(text: string, width: number, fontSize: number) {
  const normalizedWidth = Math.max(width / fontSize, 1);
  const lines = text.split("\n").reduce((total, line) => {
    const lineUnits = Array.from(line).reduce(
      (sum, character) => sum + characterWidthWeight(character),
      0,
    );
    return total + Math.max(1, Math.ceil(lineUnits / normalizedWidth));
  }, 0);
  return lines * fontSize * TRANSLATION_LINE_HEIGHT;
}

function estimateVerticalTextWidth(
  text: string,
  height: number,
  fontSize: number,
) {
  const normalizedHeight = Math.max(height / fontSize, 1);
  const columns = text.split("\n").reduce((total, line) => {
    const lineUnits = Array.from(line).reduce(
      (sum, character) => sum + characterWidthWeight(character),
      0,
    );
    return total + Math.max(1, Math.ceil(lineUnits / normalizedHeight));
  }, 0);
  return columns * fontSize * 1.14;
}

function paragraphFontSize(
  paragraph: KnowledgeStructuredParagraph,
  text: string,
  layoutHint: string | null | undefined,
) {
  const bbox = paragraph.bbox;
  if (!bbox) {
    return 14;
  }

  const availableWidth = Math.max(bbox.width - TRANSLATION_BLOCK_PADDING_X, 18);
  const availableHeight = Math.max(
    bbox.height - TRANSLATION_BLOCK_PADDING_Y,
    14,
  );
  const maxSize = Math.max(9, Math.min(28, Math.floor(availableHeight * 0.72)));
  const isVertical = String(layoutHint ?? "").toLowerCase() === "vertical";
  let low = 8;
  let high = maxSize;
  let best = 8;

  while (low <= high) {
    const mid = Math.floor((low + high) / 2);
    const fits = isVertical
      ? estimateVerticalTextWidth(text, availableHeight, mid) <= availableWidth
      : estimateTextHeight(text, availableWidth, mid) <= availableHeight;
    if (fits) {
      best = mid;
      low = mid + 1;
    } else {
      high = mid - 1;
    }
  }

  return best;
}

function buildRenderableParagraphItems(
  currentPage: KnowledgeStructuredPage | null,
  previousPage: KnowledgeStructuredPage | null,
  layoutHint: string | null | undefined,
) {
  if (!currentPage) {
    return [];
  }

  const currentPageWidth = currentPage.page_meta?.page_width ?? 0;
  const currentPageHeight = currentPage.page_meta?.page_height ?? 0;
  if (currentPageWidth <= 0 || currentPageHeight <= 0) {
    return [];
  }

  const isVertical = String(layoutHint ?? "").toLowerCase() === "vertical";
  const items: RenderParagraphItem[] = [];

  for (const paragraph of currentPage.paragraphs ?? []) {
    const bbox = paragraph.bbox;
    if (!bbox) {
      continue;
    }

    const visibleLeft = Math.max(bbox.x, 0);
    const visibleTop = Math.max(bbox.y, 0);
    const visibleRight = Math.min(bbox.x + bbox.width, currentPageWidth);
    const visibleBottom = Math.min(bbox.y + bbox.height, currentPageHeight);
    if (visibleRight <= visibleLeft || visibleBottom <= visibleTop) {
      continue;
    }

    items.push({
      key: paragraphKey(currentPage, paragraph),
      contextParagraph: buildContextParagraph(currentPage, paragraph),
      paragraph,
      source: "current",
      textLeft: bbox.x,
      textTop: bbox.y,
      textWidth: bbox.width,
      textHeight: bbox.height,
      visibleLeft,
      visibleTop,
      visibleWidth: visibleRight - visibleLeft,
      visibleHeight: visibleBottom - visibleTop,
    });
  }

  const previousPageWidth = previousPage?.page_meta?.page_width ?? 0;
  const previousPageHeight = previousPage?.page_meta?.page_height ?? 0;
  if (previousPage && previousPageWidth > 0 && previousPageHeight > 0) {
    for (const paragraph of previousPage.paragraphs ?? []) {
      const bbox = paragraph.bbox;
      if (!bbox) {
        continue;
      }

      const overflowDetected = isVertical
        ? bbox.x + bbox.width > previousPageWidth + PAGE_OVERFLOW_TOLERANCE
        : bbox.y + bbox.height > previousPageHeight + PAGE_OVERFLOW_TOLERANCE;
      if (!overflowDetected) {
        continue;
      }

      const projectedLeft = isVertical ? bbox.x - previousPageWidth : bbox.x;
      const projectedTop = isVertical ? bbox.y : bbox.y - previousPageHeight;
      const visibleLeft = Math.max(projectedLeft, 0);
      const visibleTop = Math.max(projectedTop, 0);
      const visibleRight = Math.min(
        projectedLeft + bbox.width,
        currentPageWidth,
      );
      const visibleBottom = Math.min(
        projectedTop + bbox.height,
        currentPageHeight,
      );
      if (visibleRight <= visibleLeft || visibleBottom <= visibleTop) {
        continue;
      }

      items.push({
        key: `${paragraphKey(previousPage, paragraph)}:spill-${currentPage.pdf_page_no ?? currentPage.page_no ?? "page"}`,
        contextParagraph: buildContextParagraph(previousPage, paragraph),
        paragraph,
        source: "previous-spill",
        textLeft: projectedLeft,
        textTop: projectedTop,
        textWidth: bbox.width,
        textHeight: bbox.height,
        visibleLeft,
        visibleTop,
        visibleWidth: visibleRight - visibleLeft,
        visibleHeight: visibleBottom - visibleTop,
      });
    }
  }

  return items.sort((left, right) => {
    if (isVertical) {
      if (left.visibleLeft !== right.visibleLeft) {
        return right.visibleLeft - left.visibleLeft;
      }
      return left.visibleTop - right.visibleTop;
    }
    if (left.visibleTop !== right.visibleTop) {
      return left.visibleTop - right.visibleTop;
    }
    return left.visibleLeft - right.visibleLeft;
  });
}

export function KnowledgePdfReader({
  documentUrl,
  initialPdfPageNo = 1,
  knowledgeSpaceId,
  originFilename,
  originTitle,
  onCompareToggle,
  focusedPdfPageNo,
  focusedParagraphNo,
  focusedParagraphText,
}: {
  documentUrl: string;
  initialPdfPageNo?: number;
  knowledgeSpaceId?: string;
  originFilename: string;
  originTitle: string;
  onCompareToggle?: (open: boolean) => void;
  focusedPdfPageNo?: number | null;
  focusedParagraphNo?: number | null;
  focusedParagraphText?: string | null;
}) {
  const router = useRouter();
  const pdfViewportRef = useRef<HTMLDivElement | null>(null);
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const contextMenuRef = useRef<HTMLDivElement | null>(null);
  const pageImageRef = useRef<HTMLImageElement | null>(null);
  const translationBlockRefs = useRef<Record<string, HTMLDivElement | null>>(
    {},
  );

  const [mode, setMode] = useState<ReaderMode>("pdf");
  const [sourceLanguage, setSourceLanguage] =
    useState<TranslationSourceLanguage>("en");
  const [showStructure, setShowStructure] = useState(true);
  const [currentPdfPageNo, setCurrentPdfPageNo] = useState<number>(
    Math.max(initialPdfPageNo, 1),
  );
  const [pageInputValue, setPageInputValue] = useState("");
  const [pageState, setPageState] = useState<PageState>({ status: "loading" });
  const [previousPageData, setPreviousPageData] =
    useState<KnowledgeStructuredPage | null>(null);
  const [hoveredKey, setHoveredKey] = useState<string | null>(null);
  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(null);
  const [selectedExcerptParagraph, setSelectedExcerptParagraph] =
    useState<ContextParagraph | null>(null);
  const [isExcerptDialogOpen, setIsExcerptDialogOpen] = useState(false);
  const [translationCache, setTranslationCache] = useState<
    Record<string, Record<string, string>>
  >({});
  const [translationLoading, setTranslationLoading] = useState(false);
  const [translationError, setTranslationError] = useState<string | null>(null);
  const [contextMenuTranslations, setContextMenuTranslations] = useState<
    Record<string, ContextMenuTranslationState>
  >({});
  const [copiedParagraphKey, setCopiedParagraphKey] = useState<string | null>(
    null,
  );
  const [translationBlockMetrics, setTranslationBlockMetrics] = useState<
    Record<string, { width: number; height: number }>
  >({});
  const [canvasWidth, setCanvasWidth] = useState(0);
  const [pageImageSize, setPageImageSize] = useState({ width: 0, height: 0 });
  const resolvedDocument = useMemo(
    () => resolveKnowledgeDocumentUrl(documentUrl),
    [documentUrl],
  );

  useEffect(() => {
    setCurrentPdfPageNo(Math.max(initialPdfPageNo, 1));
    setPageInputValue("");
    setPageState({ status: "loading" });
    setPreviousPageData(null);
    setContextMenu(null);
    setContextMenuTranslations({});
    setCopiedParagraphKey(null);
    setHoveredKey(null);
    setPageImageSize({ width: 0, height: 0 });
  }, [documentUrl, initialPdfPageNo]);

  useEffect(() => {
    let cancelled = false;
    setPageState({ status: "loading" });
    setPreviousPageData(null);
    setContextMenu(null);
    setCopiedParagraphKey(null);
    setHoveredKey(null);

    const previousPagePromise =
      currentPdfPageNo > 1
        ? getKnowledgeStructuredPageForDocumentUrl(documentUrl, {
            pdfPageNo: currentPdfPageNo - 1,
          }).catch(() => null)
        : Promise.resolve(null);

    Promise.all([
      getKnowledgeStructuredPageForDocumentUrl(documentUrl, {
        pdfPageNo: currentPdfPageNo,
      }),
      previousPagePromise,
    ])
      .then(([data, previousPage]) => {
        if (!cancelled) {
          setPreviousPageData(previousPage);
          setPageState({ status: "ready", data });
        }
      })
      .catch((error: Error) => {
        if (!cancelled) {
          setPreviousPageData(null);
          setPageState({
            status: "error",
            message: error.message || "结构化页加载失败",
          });
        }
      });

    return () => {
      cancelled = true;
    };
  }, [currentPdfPageNo, documentUrl]);

  useEffect(() => {
    const closeMenu = (event: Event) => {
      if (event instanceof PointerEvent && event.button === 2) {
        return;
      }
      if (
        contextMenuRef.current &&
        event.target instanceof Node &&
        contextMenuRef.current.contains(event.target)
      ) {
        return;
      }
      setContextMenu(null);
    };

    window.addEventListener("pointerdown", closeMenu);
    window.addEventListener("scroll", closeMenu, true);
    return () => {
      window.removeEventListener("pointerdown", closeMenu);
      window.removeEventListener("scroll", closeMenu, true);
    };
  }, []);

  const pageData = pageState.status === "ready" ? pageState.data : null;
  const pageCount = pageData?.page_count ?? null;
  const pageWidth = pageData?.page_meta?.page_width ?? 0;
  const pageHeight = pageData?.page_meta?.page_height ?? 0;
  const layoutHint = pageData?.layout_hint ?? null;
  const isVerticalLayout =
    String(layoutHint ?? "").toLowerCase() === "vertical";
  const pageImageUrl = useMemo(
    () =>
      buildKnowledgePageImageURLForDocumentUrl(documentUrl, currentPdfPageNo),
    [currentPdfPageNo, documentUrl],
  );

  const translationCacheKey = useMemo(() => {
    if (!pageData) {
      return null;
    }
    return `${pageData.filename}:${pageData.pdf_page_no ?? pageData.page_no ?? "page"}:${sourceLanguage}`;
  }, [pageData, sourceLanguage]);

  const translationMap = translationCacheKey
    ? (translationCache[translationCacheKey] ?? null)
    : null;

  useEffect(() => {
    onCompareToggle?.(showStructure || mode === "translation");
    return () => onCompareToggle?.(false);
  }, [mode, onCompareToggle, showStructure]);

  const renderParagraphItems = useMemo(
    () => buildRenderableParagraphItems(pageData, previousPageData, layoutHint),
    [layoutHint, pageData, previousPageData],
  );

  useEffect(() => {
    const viewport = pdfViewportRef.current;
    if (!viewport || !pageWidth) {
      setCanvasWidth(0);
      return;
    }

    const updateCanvasWidth = () => {
      const availableWidth = Math.max(viewport.clientWidth - 48, 1);
      setCanvasWidth(Math.min(availableWidth, pageWidth));
    };

    updateCanvasWidth();
    const observer = new ResizeObserver(updateCanvasWidth);
    observer.observe(viewport);
    return () => {
      observer.disconnect();
    };
  }, [pageWidth, mode, currentPdfPageNo, showStructure]);

  useEffect(() => {
    setTranslationBlockMetrics({});
    translationBlockRefs.current = {};
  }, [translationCacheKey]);

  useEffect(() => {
    if (
      mode !== "translation" ||
      !pageData ||
      !translationCacheKey ||
      translationMap ||
      renderParagraphItems.length === 0
    ) {
      return;
    }

    let cancelled = false;
    setTranslationLoading(true);
    setTranslationError(null);

    translateKnowledgeParagraphsToChineseForDocumentUrl(
      documentUrl,
      renderParagraphItems.map((item) => ({
        key: item.contextParagraph.key,
        text: item.contextParagraph.text,
      })),
      {
        sourceLanguageHint: sourceLanguage,
      },
    )
      .then((items) => {
        if (cancelled) {
          return;
        }
        const nextMap = Object.fromEntries(
          items
            .filter((item) => item.key && item.translation)
            .map((item) => [item.key, item.translation]),
        );
        setTranslationCache((current) => ({
          ...current,
          [translationCacheKey]: nextMap,
        }));
      })
      .catch((error: Error) => {
        if (!cancelled) {
          setTranslationError(error.message || "翻译失败");
        }
      })
      .finally(() => {
        if (!cancelled) {
          setTranslationLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [
    documentUrl,
    mode,
    pageData,
    renderParagraphItems,
    sourceLanguage,
    translationCacheKey,
    translationMap,
  ]);

  useEffect(() => {
    const image = pageImageRef.current;
    if (!image) {
      setPageImageSize({ width: 0, height: 0 });
      return;
    }

    const updateImageSize = () => {
      setPageImageSize({
        width: image.clientWidth,
        height: image.clientHeight,
      });
    };

    updateImageSize();
    const observer = new ResizeObserver(updateImageSize);
    observer.observe(image);
    return () => {
      observer.disconnect();
    };
  }, [currentPdfPageNo, pageImageUrl]);

  const focusedKey = useMemo(() => {
    if (!renderParagraphItems.length) {
      return null;
    }
    if (focusedPdfPageNo && currentPdfPageNo !== focusedPdfPageNo) {
      return null;
    }

    if (focusedParagraphNo) {
      const paragraphMatch = renderParagraphItems.find(
        (item) =>
          item.contextParagraph.paragraphNo === focusedParagraphNo &&
          (!focusedPdfPageNo ||
            item.contextParagraph.pdfPageNo === focusedPdfPageNo),
      );
      if (paragraphMatch) {
        return paragraphMatch.contextParagraph.key;
      }
    }

    const normalizedText = focusedParagraphText?.trim();
    if (!normalizedText) {
      return null;
    }

    const textMatch = renderParagraphItems.find((item) => {
      const paragraphText = item.contextParagraph.text.trim();
      return (
        paragraphText.includes(normalizedText) ||
        normalizedText.includes(paragraphText)
      );
    });
    return textMatch?.contextParagraph.key ?? null;
  }, [
    currentPdfPageNo,
    focusedParagraphNo,
    focusedParagraphText,
    focusedPdfPageNo,
    renderParagraphItems,
  ]);

  const activeKey = contextMenu?.paragraph.key ?? hoveredKey ?? focusedKey;

  const goToPage = useCallback(
    (page: number) => {
      if (page < 1) {
        return;
      }
      if (pageCount && page > pageCount) {
        return;
      }
      setCurrentPdfPageNo(page);
      setPageInputValue("");
    },
    [pageCount],
  );

  const openContextMenu = useCallback(
    (paragraph: ContextParagraph, position: { x: number; y: number }) => {
      setCopiedParagraphKey(null);
      setContextMenu({
        x: position.x,
        y: position.y,
        paragraph,
      });
    },
    [],
  );

  const handleCopyParagraph = useCallback(
    async (paragraph: ContextParagraph) => {
      try {
        await navigator.clipboard.writeText(paragraph.text);
        setCopiedParagraphKey(paragraph.key);
        toast.success("已复制原文");
        window.setTimeout(() => {
          setCopiedParagraphKey((current) =>
            current === paragraph.key ? null : current,
          );
        }, 1800);
      } catch (error) {
        console.error(error);
        toast.error("复制失败");
      }
    },
    [],
  );

  const handleTranslateParagraph = useCallback(
    async (paragraph: ContextParagraph) => {
      const cachedTranslation = translationMap?.[paragraph.key];
      if (cachedTranslation) {
        setContextMenuTranslations((current) => ({
          ...current,
          [paragraph.key]: {
            loading: false,
            error: null,
            text: cachedTranslation,
          },
        }));
        return;
      }

      setContextMenuTranslations((current) => ({
        ...current,
        [paragraph.key]: {
          loading: true,
          error: null,
          text: current[paragraph.key]?.text ?? "",
        },
      }));

      try {
        const [result] =
          await translateKnowledgeParagraphsToChineseForDocumentUrl(
            documentUrl,
            [{ key: paragraph.key, text: paragraph.text }],
            {
              sourceLanguageHint: sourceLanguage,
            },
          );
        const translationText = result?.translation?.trim() ?? "";
        setContextMenuTranslations((current) => ({
          ...current,
          [paragraph.key]: {
            loading: false,
            error: translationText ? null : "该段翻译暂未返回结果。",
            text: translationText,
          },
        }));
      } catch (error) {
        console.error(error);
        setContextMenuTranslations((current) => ({
          ...current,
          [paragraph.key]: {
            loading: false,
            error: error instanceof Error ? error.message : "翻译失败",
            text: current[paragraph.key]?.text ?? "",
          },
        }));
      }
    },
    [documentUrl, sourceLanguage, translationMap],
  );

  const handleCreateExcerpt = useCallback((paragraph: ContextParagraph) => {
    setSelectedExcerptParagraph(paragraph);
    setContextMenu(null);
    setIsExcerptDialogOpen(true);
  }, []);

  const renderContextMenu = () => {
    if (!contextMenu) {
      return null;
    }

    const paragraph = contextMenu.paragraph;
    const cachedTranslation = translationMap?.[paragraph.key];
    const translationState = contextMenuTranslations[paragraph.key] ?? {
      loading: false,
      error: null,
      text: "",
    };
    const displayedTranslation = cachedTranslation ?? translationState.text;
    const isCopied = copiedParagraphKey === paragraph.key;
    const menuWidth = 320;
    const left =
      typeof window !== "undefined"
        ? Math.min(contextMenu.x, window.innerWidth - menuWidth - 12)
        : contextMenu.x;
    const top =
      typeof window !== "undefined"
        ? Math.min(contextMenu.y, window.innerHeight - 280)
        : contextMenu.y;

    return (
      <div
        ref={contextMenuRef}
        className="fixed z-50 w-80 rounded-2xl border border-stone-200 bg-white p-2 shadow-[0_18px_40px_-22px_rgba(28,25,23,0.4)]"
        style={{ left, top }}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="grid grid-cols-3 gap-1.5">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-9 justify-start rounded-xl px-3 text-stone-800 hover:bg-stone-100"
            disabled={translationState.loading}
            onClick={() => void handleTranslateParagraph(paragraph)}
          >
            {translationState.loading ? (
              <Loader2Icon className="mr-1.5 size-4 animate-spin" />
            ) : (
              <LanguagesIcon className="mr-1.5 size-4" />
            )}
            翻译
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-9 justify-start rounded-xl px-3 text-stone-800 hover:bg-stone-100"
            onClick={() => void handleCopyParagraph(paragraph)}
          >
            {isCopied ? (
              <CheckIcon className="mr-1.5 size-4 text-emerald-600" />
            ) : (
              <CopyIcon className="mr-1.5 size-4" />
            )}
            复制
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-9 justify-start rounded-xl px-3 text-stone-800 hover:bg-stone-100"
            onClick={() => void handleCreateExcerpt(paragraph)}
          >
            <FileTextIcon className="mr-1.5 size-4" />
            加入笔记
          </Button>
        </div>
        {translationState.loading ||
        translationState.error ||
        displayedTranslation ? (
          <div className="mt-2 rounded-xl border border-stone-200 bg-stone-50 px-3 py-2.5">
            <div className="mb-1 text-[11px] font-semibold tracking-wide text-stone-500">
              翻译结果
            </div>
            {translationState.loading ? (
              <div className="flex items-center text-sm text-stone-500">
                <Loader2Icon className="mr-2 size-4 animate-spin" />
                正在翻译...
              </div>
            ) : translationState.error ? (
              <div className="text-sm leading-6 text-rose-600">
                {translationState.error}
              </div>
            ) : (
              <div className="max-h-48 overflow-y-auto text-sm leading-6 whitespace-pre-wrap text-stone-700">
                {displayedTranslation}
              </div>
            )}
          </div>
        ) : null}
      </div>
    );
  };

  const displayScale =
    pageWidth > 0 ? Math.min((canvasWidth || pageWidth) / pageWidth, 1) : 1;

  useLayoutEffect(() => {
    const image = pageImageRef.current;
    if (!image) {
      return;
    }

    const updateImageSize = () => {
      setPageImageSize({
        width: image.clientWidth,
        height: image.clientHeight,
      });
    };

    updateImageSize();
    const frame = window.requestAnimationFrame(updateImageSize);
    return () => {
      window.cancelAnimationFrame(frame);
    };
  }, [displayScale, mode, showStructure]);

  const translationLayoutItems = useMemo(() => {
    if (!pageData || pageWidth <= 0 || pageHeight <= 0) {
      return [];
    }

    const items: TranslationLayoutItem[] = [];
    let verticalOffset = 0;
    let horizontalOffset = 0;

    for (const renderItem of renderParagraphItems) {
      const contextParagraph = renderItem.contextParagraph;
      const translatedText = translationMap
        ? (translationMap[contextParagraph.key] ?? renderItem.paragraph.text)
        : "";
      const textLeft = renderItem.textLeft * displayScale;
      const textTop =
        renderItem.textTop * displayScale +
        (isVerticalLayout ? 0 : verticalOffset);
      const textWidth = renderItem.textWidth * displayScale;
      const textHeight = renderItem.textHeight * displayScale;
      const baseWidth = textWidth;
      const baseHeight = textHeight;
      const blockMetrics = translationBlockMetrics[contextParagraph.key];
      const blockWidth = isVerticalLayout
        ? Math.max(baseWidth, blockMetrics?.width ?? baseWidth)
        : baseWidth;
      const blockHeight = Math.max(
        baseHeight,
        blockMetrics?.height ?? baseHeight,
      );
      const overflowWidth = Math.max(0, blockWidth - baseWidth);
      const overflowHeight = Math.max(0, blockHeight - baseHeight);
      const blockLeft = isVerticalLayout
        ? textLeft - horizontalOffset - overflowWidth
        : textLeft;
      const blockTop = textTop;

      items.push({
        contextParagraph,
        paragraph: renderItem.paragraph,
        source: renderItem.source,
        baseWidth,
        baseHeight,
        blockWidth,
        blockHeight,
        overflowWidth,
        overflowHeight,
        blockLeft,
        blockTop,
        textLeft,
        textTop,
        textWidth,
        textHeight,
        translatedText,
      });

      if (isVerticalLayout && overflowWidth > 0) {
        horizontalOffset += overflowWidth;
      }
      if (!isVerticalLayout && overflowHeight > 0) {
        verticalOffset += overflowHeight;
      }
    }

    return items;
  }, [
    displayScale,
    isVerticalLayout,
    pageData,
    pageHeight,
    pageWidth,
    renderParagraphItems,
    translationBlockMetrics,
    translationMap,
  ]);

  const translationCanvasWidth = useMemo(() => {
    if (!pageWidth) {
      return 0;
    }

    return Math.max(
      pageWidth * displayScale,
      ...translationLayoutItems.map((item) => item.blockLeft + item.blockWidth),
    );
  }, [displayScale, pageWidth, translationLayoutItems]);

  const translationCanvasHeight = useMemo(() => {
    if (!pageHeight) {
      return 0;
    }

    if (isVerticalLayout) {
      return pageHeight * displayScale;
    }

    return Math.max(
      pageHeight * displayScale,
      ...translationLayoutItems.map(
        (item) => item.textTop + item.baseHeight + item.overflowHeight,
      ),
    );
  }, [displayScale, isVerticalLayout, pageHeight, translationLayoutItems]);

  useLayoutEffect(() => {
    if (mode !== "translation") {
      return;
    }

    const nextMetrics: Record<string, { width: number; height: number }> = {};
    for (const [key, element] of Object.entries(translationBlockRefs.current)) {
      if (!element) {
        continue;
      }
      nextMetrics[key] = {
        width: Math.max(
          0,
          Math.ceil(element.scrollWidth) - TRANSLATION_BLOCK_OUTER_PADDING,
        ),
        height: Math.max(
          0,
          Math.ceil(element.scrollHeight) - TRANSLATION_BLOCK_OUTER_PADDING,
        ),
      };
    }

    const currentKeys = Object.keys(translationBlockMetrics);
    const nextKeys = Object.keys(nextMetrics);
    const changed =
      currentKeys.length !== nextKeys.length ||
      nextKeys.some((key) => {
        const current = translationBlockMetrics[key];
        const next = nextMetrics[key];
        return (
          current?.width !== next?.width || current?.height !== next?.height
        );
      });

    if (changed) {
      setTranslationBlockMetrics(nextMetrics);
    }
  }, [mode, translationBlockMetrics, translationLayoutItems]);

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-[24px] border border-slate-200 bg-zinc-50/50 shadow-sm">
      <ExcerptToNoteDialog
        open={isExcerptDialogOpen}
        onOpenChange={setIsExcerptDialogOpen}
        originTitle={originTitle}
        originFilename={pageData?.filename ?? originFilename}
        knowledgeSpaceId={knowledgeSpaceId}
        originScope={resolvedDocument?.scope ?? "global"}
        originDocId={resolvedDocument?.filename ?? pageData?.doc_id ?? null}
        paragraph={selectedExcerptParagraph}
        onSuccess={(record) => {
          router.push(
            `/workspace/notes?space=${encodeURIComponent(
              knowledgeSpaceId ?? record.knowledge_space_id ?? "",
            )}&record=${encodeURIComponent(record.id)}`,
          );
        }}
      />
      <div className="sticky top-0 z-20 flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 bg-white/80 px-4 py-2.5 backdrop-blur-md">
        <div className="flex min-w-0 items-center gap-3">
          <div className="flex items-center gap-1">
            <Button
              variant="ghost"
              size="icon"
              className="size-8 rounded-xl"
              onClick={() => goToPage(currentPdfPageNo - 1)}
              disabled={currentPdfPageNo <= 1}
            >
              <ChevronLeftIcon className="size-4" />
            </Button>
            <div className="flex items-center gap-1.5 px-2 text-sm font-medium text-slate-600">
              <Input
                type="text"
                className="focus-visible:ring-primary/30 h-7 w-12 rounded-md border-slate-200 bg-white px-1 text-center text-xs shadow-sm"
                value={
                  pageInputValue !== ""
                    ? pageInputValue
                    : String(currentPdfPageNo)
                }
                onChange={(event) => setPageInputValue(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key !== "Enter") {
                    return;
                  }
                  const page = parseInt(pageInputValue, 10);
                  if (!Number.isNaN(page)) {
                    goToPage(page);
                  }
                }}
                onBlur={() => setPageInputValue("")}
                onFocus={() => setPageInputValue(String(currentPdfPageNo))}
              />
              <span className="text-slate-400">/ {pageCount ?? "?"}</span>
            </div>
            <Button
              variant="ghost"
              size="icon"
              className="size-8 rounded-xl"
              onClick={() => goToPage(currentPdfPageNo + 1)}
              disabled={pageCount ? currentPdfPageNo >= pageCount : false}
            >
              <ChevronRightIcon className="size-4" />
            </Button>
          </div>

          <div className="hidden min-w-0 md:block">
            <div className="truncate text-sm font-medium text-slate-900">
              {originTitle}
            </div>
            <div className="truncate text-xs text-slate-500">
              {originFilename}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {mode === "translation" && (
            <div className="mr-4 flex items-center gap-1 rounded-xl bg-slate-100/50 p-1 ring-1 ring-slate-200/50">
              {LANGUAGE_OPTIONS.map((option) => (
                <Button
                  key={option.value}
                  variant="ghost"
                  size="sm"
                  className={cn(
                    "h-7 rounded-lg px-2.5 text-[11px] font-bold transition-all",
                    sourceLanguage === option.value
                      ? "text-primary bg-white shadow-sm ring-1 ring-slate-200/30"
                      : "text-slate-500 hover:text-slate-700",
                  )}
                  onClick={() => setSourceLanguage(option.value)}
                >
                  {option.label}
                </Button>
              ))}
            </div>
          )}

          <div className="flex items-center gap-1.5 overflow-hidden rounded-xl bg-slate-100/30 p-1 ring-1 ring-slate-200/50">
            <Button
              variant={showStructure ? "secondary" : "ghost"}
              size="sm"
              className={cn(
                "h-7 rounded-lg px-3 text-[11px] font-bold transition-all",
                showStructure
                  ? "text-primary bg-white shadow-sm ring-1 ring-slate-200/30"
                  : "text-slate-500 hover:text-slate-700",
              )}
              onClick={() => setShowStructure((current) => !current)}
            >
              <ScrollTextIcon className="mr-1.5 size-3" />
              原文结构
            </Button>
            <Button
              variant={mode === "translation" ? "secondary" : "ghost"}
              size="sm"
              className={cn(
                "h-7 rounded-lg px-3 text-[11px] font-bold transition-all",
                mode === "translation"
                  ? "text-primary bg-white shadow-sm ring-1 ring-slate-200/30"
                  : "text-slate-500 hover:text-slate-700",
              )}
              onClick={() =>
                setMode((current) =>
                  current === "translation" ? "pdf" : "translation",
                )
              }
            >
              <LanguagesIcon className="mr-1.5 size-3" />
              中文译文
            </Button>
          </div>
          <div className="hidden border-l border-slate-200 pl-3 text-[11px] font-medium text-slate-400 md:block">
            双栏对照模式
          </div>
        </div>
      </div>

      <div className="relative min-h-0 flex-1 overflow-hidden">
        {pageState.status === "loading" && (
          <div className="flex h-full items-center justify-center text-sm text-stone-500">
            <Loader2Icon className="mr-2 size-4 animate-spin" />
            正在加载页面...
          </div>
        )}

        {pageState.status === "error" && (
          <div className="flex h-full items-center justify-center px-6 text-sm text-red-600">
            {pageState.message}
          </div>
        )}

        {pageState.status === "ready" && (
          <div
            className={cn(
              "grid h-full min-h-0 grid-cols-1",
              showStructure && mode === "translation" && "xl:grid-cols-3",
              (showStructure || mode === "translation") &&
                !(showStructure && mode === "translation") &&
                "xl:grid-cols-2",
            )}
          >
            <div
              ref={pdfViewportRef}
              className="min-h-0 overflow-auto bg-zinc-50/30"
            >
              <div className="flex min-h-full items-start justify-center p-6">
                <div className="relative">
                  <img
                    ref={pageImageRef}
                    src={pageImageUrl}
                    alt={`${pageState.data.title} 第 ${currentPdfPageNo} 页`}
                    className="block rounded-sm bg-white shadow-[0_18px_36px_-18px_rgba(15,23,42,0.24)]"
                    style={{
                      width: `${pageWidth * displayScale}px`,
                      height: "auto",
                    }}
                    onLoad={(event) => {
                      const image = event.currentTarget;
                      setPageImageSize({
                        width: image.clientWidth,
                        height: image.clientHeight,
                      });
                    }}
                  />
                  <div className="absolute inset-0 overflow-hidden">
                    {renderParagraphItems.map((item) => {
                      if (
                        pageWidth <= 0 ||
                        pageHeight <= 0 ||
                        pageImageSize.width <= 0 ||
                        pageImageSize.height <= 0
                      ) {
                        return null;
                      }

                      const isActive = activeKey === item.contextParagraph.key;
                      return (
                        <div
                          key={item.key}
                          className={cn(
                            "absolute rounded-[4px] border-2 transition-all duration-200",
                            isActive
                              ? "border-primary bg-primary/10 shadow-[0_0_12px_rgba(126,51,46,0.15)]"
                              : "hover:border-primary/60 hover:bg-primary/5 border-transparent bg-transparent",
                            item.source === "previous-spill" && "border-dashed",
                          )}
                          style={{
                            left: `${(item.visibleLeft / pageWidth) * pageImageSize.width}px`,
                            top: `${(item.visibleTop / pageHeight) * pageImageSize.height}px`,
                            width: `${(item.visibleWidth / pageWidth) * pageImageSize.width}px`,
                            height: `${(item.visibleHeight / pageHeight) * pageImageSize.height}px`,
                          }}
                          onMouseEnter={() =>
                            setHoveredKey(item.contextParagraph.key)
                          }
                          onMouseLeave={() =>
                            setHoveredKey((current) =>
                              current === item.contextParagraph.key
                                ? null
                                : current,
                            )
                          }
                          onPointerDownCapture={(event) => {
                            if (event.button !== 2) {
                              return;
                            }
                            event.preventDefault();
                            event.stopPropagation();
                            openContextMenu(item.contextParagraph, {
                              x: event.clientX,
                              y: event.clientY,
                            });
                          }}
                          onContextMenuCapture={(event) => {
                            event.preventDefault();
                            event.stopPropagation();
                            openContextMenu(item.contextParagraph, {
                              x: event.clientX,
                              y: event.clientY,
                            });
                          }}
                        />
                      );
                    })}
                  </div>
                </div>
              </div>
            </div>

            {showStructure && (
              <div className="min-h-0 min-w-0 overflow-hidden border-t border-slate-200 bg-zinc-50/30 xl:border-t-0 xl:border-l">
                <KnowledgeSidePane
                  currentPdfPageNo={currentPdfPageNo}
                  documentUrl={documentUrl}
                  mode="compare"
                  originFilename={originFilename}
                  originTitle={originTitle}
                  knowledgeSpaceId={knowledgeSpaceId}
                  fluid
                  bordered={false}
                  forceScale={displayScale}
                  translationSourceLanguageHint={sourceLanguage}
                  externalHoveredKey={hoveredKey}
                  onHoveredKeyChange={setHoveredKey}
                />
              </div>
            )}

            {mode === "translation" && (
              <div
                ref={viewportRef}
                className="min-h-0 min-w-0 overflow-x-hidden overflow-y-auto border-t border-slate-200 bg-zinc-50/30 xl:border-t-0 xl:border-l"
              >
                <div className="min-h-full p-6">
                  <div className="flex items-start justify-center">
                    <KnowledgePageSurface
                      width={translationCanvasWidth}
                      height={translationCanvasHeight}
                      className="shadow-[0_24px_50px_-30px_rgba(15,23,42,0.28)]"
                      style={{
                        minWidth: `${translationCanvasWidth}px`,
                        minHeight: `${translationCanvasHeight}px`,
                      }}
                    >
                      <div
                        className="relative"
                        style={{
                          width: `${translationCanvasWidth}px`,
                          height: `${translationCanvasHeight}px`,
                        }}
                      >
                        {translationError && !translationMap ? (
                          <div className="mx-4 mt-4 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                            {translationError}
                          </div>
                        ) : null}

                        {translationLoading && !translationMap ? (
                          <div className="mx-4 mt-4 flex min-h-[120px] items-center justify-center rounded-2xl border border-stone-200 bg-stone-50 text-sm text-stone-500">
                            <Loader2Icon className="mr-2 size-4 animate-spin" />
                            正在翻译本页为中文...
                          </div>
                        ) : null}

                        {translationLayoutItems.map((item) => {
                          const isActive =
                            activeKey === item.contextParagraph.key;
                          const content =
                            item.translatedText || item.paragraph.text;
                          const fontSize = Math.max(
                            Math.min(
                              paragraphFontSize(
                                item.paragraph,
                                content,
                                layoutHint,
                              ) * displayScale,
                              isVerticalLayout ? 24 : 20,
                            ),
                            isVerticalLayout ? 11 : 12,
                          );

                          return (
                            <div
                              key={item.contextParagraph.key}
                              ref={(node) => {
                                translationBlockRefs.current[
                                  item.contextParagraph.key
                                ] = node;
                              }}
                              className={cn(
                                "absolute rounded-lg border text-left transition-all duration-200",
                                isActive
                                  ? "border-primary/40 bg-primary/5 shadow-[0_4px_12px_-2px_rgba(126,51,46,0.1)]"
                                  : "hover:border-primary/30 border-transparent hover:bg-stone-50/40",
                              )}
                              style={{
                                left: `${item.blockLeft - 4}px`,
                                top: `${item.blockTop - 4}px`,
                                width: `${item.blockWidth + 8}px`,
                                minHeight: `${item.blockHeight + 8}px`,
                                padding: "4px",
                              }}
                              onMouseEnter={() =>
                                setHoveredKey(item.contextParagraph.key)
                              }
                              onMouseLeave={() =>
                                setHoveredKey((current) =>
                                  current === item.contextParagraph.key
                                    ? null
                                    : current,
                                )
                              }
                              onPointerDownCapture={(event) => {
                                if (event.button !== 2) {
                                  return;
                                }
                                event.preventDefault();
                                event.stopPropagation();
                                openContextMenu(item.contextParagraph, {
                                  x: event.clientX,
                                  y: event.clientY,
                                });
                              }}
                              onContextMenuCapture={(event) => {
                                event.preventDefault();
                                event.stopPropagation();
                                openContextMenu(item.contextParagraph, {
                                  x: event.clientX,
                                  y: event.clientY,
                                });
                              }}
                            >
                              <div
                                className="break-words whitespace-pre-wrap text-stone-800"
                                style={{
                                  minHeight: `${item.baseHeight}px`,
                                  minWidth: isVerticalLayout
                                    ? `${item.blockWidth}px`
                                    : undefined,
                                  width: isVerticalLayout
                                    ? `${item.blockWidth}px`
                                    : undefined,
                                  height: isVerticalLayout
                                    ? `${item.baseHeight}px`
                                    : undefined,
                                  fontSize: `${fontSize}px`,
                                  lineHeight: isVerticalLayout
                                    ? VERTICAL_TRANSLATION_LINE_HEIGHT
                                    : TRANSLATION_LINE_HEIGHT,
                                  letterSpacing: "0.01em",
                                  writingMode: isVerticalLayout
                                    ? "vertical-rl"
                                    : undefined,
                                  textOrientation: isVerticalLayout
                                    ? "mixed"
                                    : undefined,
                                }}
                              >
                                {content}
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </KnowledgePageSurface>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {renderContextMenu()}
    </div>
  );
}
