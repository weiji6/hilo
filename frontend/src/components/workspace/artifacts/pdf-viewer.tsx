"use client";

import {
  ChevronLeftIcon,
  ChevronRightIcon,
  DownloadIcon,
  LoaderIcon,
  MinusIcon,
  PlusIcon,
} from "lucide-react";
import { type ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

pdfjs.GlobalWorkerOptions.workerSrc = `//unpkg.com/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.mjs`;

export interface PdfViewerProps {
  url: string;
  initialPage?: number;
  page?: number;
  className?: string;
  onPageChange?: (page: number) => void;
  toolbarExtra?: ReactNode;
}

export function PdfViewer({
  url,
  initialPage = 0,
  page,
  className,
  onPageChange,
  toolbarExtra,
}: PdfViewerProps) {
  const [numPages, setNumPages] = useState<number | null>(null);
  const [pageNumber, setPageNumber] = useState<number>(initialPage + 1);
  const [scale, setScale] = useState<number>(1.0);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [pageInputValue, setPageInputValue] = useState<string>("");
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (initialPage >= 0) {
      setPageNumber(initialPage + 1);
    }
  }, [initialPage]);

  useEffect(() => {
    if (typeof page === "number" && page >= 0) {
      setPageNumber(page + 1);
    }
  }, [page]);

  const onDocumentLoadSuccess = useCallback(
    ({ numPages }: { numPages: number }) => {
      setNumPages(numPages);
      setIsLoading(false);
      setError(null);
      if (initialPage >= 0 && initialPage < numPages) {
        setPageNumber(initialPage + 1);
      }
    },
    [initialPage],
  );

  const onDocumentLoadError = useCallback((error: Error) => {
    setError(error);
    setIsLoading(false);
  }, []);

  const goToPrevPage = useCallback(() => {
    setPageNumber((prev) => {
      const newPage = Math.max(prev - 1, 1);
      onPageChange?.(newPage - 1);
      return newPage;
    });
  }, [onPageChange]);

  const goToNextPage = useCallback(() => {
    setPageNumber((prev) => {
      const newPage = Math.min(prev + 1, numPages ?? prev);
      onPageChange?.(newPage - 1);
      return newPage;
    });
  }, [numPages, onPageChange]);

  const goToPage = useCallback(
    (page: number) => {
      if (numPages && page >= 1 && page <= numPages) {
        setPageNumber(page);
        onPageChange?.(page - 1);
      }
    },
    [numPages, onPageChange],
  );

  const handlePageInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      setPageInputValue(e.target.value);
    },
    [],
  );

  const handlePageInputKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === "Enter") {
        const page = parseInt(pageInputValue, 10);
        if (!isNaN(page)) {
          goToPage(page);
        }
        setPageInputValue("");
      }
    },
    [pageInputValue, goToPage],
  );

  const handlePageInputBlur = useCallback(() => {
    setPageInputValue("");
  }, []);

  const zoomIn = useCallback(() => {
    setScale((prev) => Math.min(prev + 0.25, 3.0));
  }, []);

  const zoomOut = useCallback(() => {
    setScale((prev) => Math.max(prev - 0.25, 0.5));
  }, []);

  const resetZoom = useCallback(() => {
    setScale(1.0);
  }, []);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement) return;

      switch (e.key) {
        case "ArrowLeft":
        case "PageUp":
          goToPrevPage();
          break;
        case "ArrowRight":
        case "PageDown":
          goToNextPage();
          break;
        case "+":
        case "=":
          if (e.ctrlKey || e.metaKey) {
            e.preventDefault();
            zoomIn();
          }
          break;
        case "-":
          if (e.ctrlKey || e.metaKey) {
            e.preventDefault();
            zoomOut();
          }
          break;
        case "0":
          if (e.ctrlKey || e.metaKey) {
            e.preventDefault();
            resetZoom();
          }
          break;
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [goToPrevPage, goToNextPage, zoomIn, zoomOut, resetZoom]);

  if (error) {
    return (
      <div
        className={cn(
          "flex h-full flex-col items-center justify-center gap-4 p-4",
          className,
        )}
      >
        <p className="text-destructive text-sm">加载PDF失败: {error.message}</p>
        <a href={url} target="_blank" rel="noopener noreferrer">
          <Button variant="outline" size="sm">
            <DownloadIcon className="mr-2 size-4" />
            下载PDF
          </Button>
        </a>
      </div>
    );
  }

  return (
    <div className={cn("flex h-full flex-col", className)}>
      {/* Toolbar */}
      <div className="flex items-center justify-between border-b bg-muted/50 px-2 py-1.5">
        {/* Page navigation */}
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="icon"
            className="size-8"
            onClick={goToPrevPage}
            disabled={pageNumber <= 1}
          >
            <ChevronLeftIcon className="size-4" />
          </Button>
          <div className="flex items-center gap-1 text-sm">
            <Input
              type="text"
              className="h-7 w-12 text-center"
              value={pageInputValue || pageNumber}
              onChange={handlePageInputChange}
              onKeyDown={handlePageInputKeyDown}
              onBlur={handlePageInputBlur}
              onFocus={() => setPageInputValue(String(pageNumber))}
            />
            <span className="text-muted-foreground">/ {numPages ?? "?"}</span>
          </div>
          <Button
            variant="ghost"
            size="icon"
            className="size-8"
            onClick={goToNextPage}
            disabled={!numPages || pageNumber >= numPages}
          >
            <ChevronRightIcon className="size-4" />
          </Button>
        </div>

        {/* Zoom controls */}
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="icon"
            className="size-8"
            onClick={zoomOut}
            disabled={scale <= 0.5}
          >
            <MinusIcon className="size-4" />
          </Button>
          <button
            className="min-w-[4rem] text-center text-sm hover:underline"
            onClick={resetZoom}
          >
            {Math.round(scale * 100)}%
          </button>
          <Button
            variant="ghost"
            size="icon"
            className="size-8"
            onClick={zoomIn}
            disabled={scale >= 3.0}
          >
            <PlusIcon className="size-4" />
          </Button>
        </div>

        <div className="flex items-center gap-1">
          {toolbarExtra}
          <a href={url} target="_blank" rel="noopener noreferrer">
            <Button variant="ghost" size="icon" className="size-8">
              <DownloadIcon className="size-4" />
            </Button>
          </a>
        </div>
      </div>

      {/* PDF Content */}
      <div
        ref={containerRef}
        className="relative flex-1 overflow-auto bg-muted/30"
      >
        {isLoading && (
          <div className="absolute inset-0 flex items-center justify-center">
            <LoaderIcon className="size-8 animate-spin text-muted-foreground" />
          </div>
        )}
        <div className="flex min-h-full items-start justify-center p-4">
          <Document
            file={url}
            onLoadSuccess={onDocumentLoadSuccess}
            onLoadError={onDocumentLoadError}
            loading={null}
            className="shadow-lg"
          >
            <Page
              pageNumber={pageNumber}
              scale={scale}
              renderTextLayer={true}
              renderAnnotationLayer={true}
              className="bg-white"
            />
          </Document>
        </div>
      </div>
    </div>
  );
}
