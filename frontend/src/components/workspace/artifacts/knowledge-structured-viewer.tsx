"use client";

import {
  ChevronLeftIcon,
  ChevronRightIcon,
  LanguagesIcon,
  ScrollTextIcon,
} from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

import { KnowledgeSidePane } from "./knowledge-side-pane";

export function KnowledgeStructuredViewer({
  className,
  documentUrl,
  initialPdfPageNo = 1,
  interactive = false,
  highlightable,
  excerptable,
  knowledgeSpaceId,
  originFilename,
  originTitle,
  currentPdfPageNo,
  onCurrentPdfPageNoChange,
  toolbarExtra,
}: {
  className?: string;
  documentUrl: string;
  initialPdfPageNo?: number;
  interactive?: boolean;
  highlightable?: boolean;
  excerptable?: boolean;
  knowledgeSpaceId?: string;
  originFilename: string;
  originTitle: string;
  currentPdfPageNo?: number;
  onCurrentPdfPageNoChange?: (page: number) => void;
  toolbarExtra?: ReactNode;
}) {
  const [showTranslation, setShowTranslation] = useState(false);
  const [translationSourceLanguage, setTranslationSourceLanguage] = useState<
    "en" | "ja" | "de"
  >("en");
  const [internalCurrentPdfPageNo, setInternalCurrentPdfPageNo] =
    useState<number>(Math.max(initialPdfPageNo, 1));
  const [pageInputValue, setPageInputValue] = useState("");
  const [pageCount, setPageCount] = useState<number | null>(null);
  const resolvedCurrentPdfPageNo = Math.max(
    currentPdfPageNo ?? internalCurrentPdfPageNo,
    1,
  );

  useEffect(() => {
    setInternalCurrentPdfPageNo(Math.max(initialPdfPageNo, 1));
    setPageInputValue("");
    setPageCount(null);
  }, [documentUrl, initialPdfPageNo]);

  useEffect(() => {
    if (typeof currentPdfPageNo === "number" && currentPdfPageNo > 0) {
      setInternalCurrentPdfPageNo(currentPdfPageNo);
    }
  }, [currentPdfPageNo]);

  const goToPage = (page: number) => {
    if (page < 1) {
      return;
    }
    if (pageCount && page > pageCount) {
      return;
    }
    setInternalCurrentPdfPageNo(page);
    onCurrentPdfPageNoChange?.(page);
    setPageInputValue("");
  };

  return (
    <div
      className={cn(
        "flex h-full min-h-0 flex-col overflow-hidden rounded-[28px] border border-[rgba(57,130,152,0.16)] bg-white",
        className,
      )}
    >
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[rgba(57,130,152,0.14)] bg-[rgb(249,252,252)] px-4 py-3">
        <div className="flex min-w-0 items-center gap-3">
          <div className="flex items-center gap-1">
            <Button
              variant="ghost"
              size="icon"
              className="size-8 rounded-xl"
              onClick={() => goToPage(resolvedCurrentPdfPageNo - 1)}
              disabled={resolvedCurrentPdfPageNo <= 1}
            >
              <ChevronLeftIcon className="size-4" />
            </Button>
            <div className="flex items-center gap-1 text-sm text-slate-700">
              <Input
                type="text"
                className="h-8 w-14 rounded-lg border-[rgba(57,130,152,0.16)] text-center"
                value={
                  pageInputValue !== ""
                    ? pageInputValue
                    : String(resolvedCurrentPdfPageNo)
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
                onFocus={() =>
                  setPageInputValue(String(resolvedCurrentPdfPageNo))
                }
              />
              <span className="text-slate-500">/ {pageCount ?? "?"}</span>
            </div>
            <Button
              variant="ghost"
              size="icon"
              className="size-8 rounded-xl"
              onClick={() => goToPage(resolvedCurrentPdfPageNo + 1)}
              disabled={
                pageCount ? resolvedCurrentPdfPageNo >= pageCount : false
              }
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
          {showTranslation && (
            <div className="mr-2 flex items-center gap-2">
              {(
                [
                  { value: "en", label: "英译中" },
                  { value: "ja", label: "日译中" },
                  { value: "de", label: "德译中" },
                ] as const
              ).map((option) => (
                <Button
                  key={option.value}
                  variant={
                    translationSourceLanguage === option.value
                      ? "default"
                      : "outline"
                  }
                  size="sm"
                  className="h-8 rounded-xl"
                  onClick={() => setTranslationSourceLanguage(option.value)}
                >
                  <LanguagesIcon className="mr-1.5 size-4" />
                  {option.label}
                </Button>
              ))}
            </div>
          )}
          <Button
            variant="default"
            size="sm"
            className="h-8 rounded-xl"
            disabled
          >
            <ScrollTextIcon className="mr-1.5 size-4" />
            原文结构
          </Button>
          <Button
            variant={showTranslation ? "default" : "outline"}
            size="sm"
            className="h-8 rounded-xl"
            onClick={() => setShowTranslation((current) => !current)}
          >
            <LanguagesIcon className="mr-1.5 size-4" />
            中文翻译
          </Button>
          {toolbarExtra}
        </div>
      </div>

      <div
        className={cn(
          "min-h-0 flex-1 overflow-hidden",
          showTranslation && "grid min-h-0 grid-cols-1 md:grid-cols-2",
        )}
      >
        <div className="min-h-0 min-w-0 overflow-hidden">
          <KnowledgeSidePane
            currentPdfPageNo={resolvedCurrentPdfPageNo}
            documentUrl={documentUrl}
            mode="compare"
            originFilename={originFilename}
            originTitle={originTitle}
            knowledgeSpaceId={knowledgeSpaceId}
            translationSourceLanguageHint={translationSourceLanguage}
            interactive={interactive}
            highlightable={highlightable}
            excerptable={excerptable}
            fluid
            bordered={false}
            onPageDataChange={(pageData) => {
              setPageCount(pageData?.page_count ?? null);
            }}
          />
        </div>
        {showTranslation && (
          <div className="min-h-0 min-w-0 overflow-hidden border-t border-[rgba(57,130,152,0.14)] md:border-t-0 md:border-l">
            <KnowledgeSidePane
              currentPdfPageNo={resolvedCurrentPdfPageNo}
              documentUrl={documentUrl}
              mode="translation"
              originFilename={originFilename}
              originTitle={originTitle}
              knowledgeSpaceId={knowledgeSpaceId}
              translationSourceLanguageHint={translationSourceLanguage}
              interactive={interactive}
              highlightable={highlightable}
              excerptable={excerptable}
              fluid
              bordered={false}
            />
          </div>
        )}
      </div>
    </div>
  );
}
