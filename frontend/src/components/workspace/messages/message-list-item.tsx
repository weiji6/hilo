import type { Message } from "@langchain/langgraph-sdk";
import { FileIcon, TriangleAlertIcon } from "lucide-react";
import { useParams } from "next/navigation";
import { memo, useMemo, type ImgHTMLAttributes } from "react";
import rehypeKatex from "rehype-katex";

import {
  Message as AIElementMessage,
  MessageContent as AIElementMessageContent,
  MessageResponse as AIElementMessageResponse,
  MessageToolbar,
} from "@/components/ai-elements/message";
import { Badge } from "@/components/ui/badge";
import { resolveArtifactURL } from "@/core/artifacts/utils";
import {
  extractContentFromMessage,
  extractReasoningContentFromMessage,
  parseUploadedFiles,
  type UploadedFile,
} from "@/core/messages/utils";
import { useRehypeSplitWordsIntoSpans } from "@/core/rehype";
import { humanMessagePlugins } from "@/core/streamdown";
import type { KnowledgeCitationRegistryItem } from "@/core/threads";
import { cn } from "@/lib/utils";

import { CopyButton } from "../copy-button";

import { MarkdownContent } from "./markdown-content";

const UNGROUNDED_MARKER = "<!-- HISTORY_RAG_UNGROUNDED -->";

export function MessageListItem({
  className,
  message,
  isLoading,
  citationRegistry,
}: {
  className?: string;
  message: Message;
  isLoading?: boolean;
  citationRegistry?: KnowledgeCitationRegistryItem[];
}) {
  const isHuman = message.type === "human";
  return (
    <AIElementMessage
      className={cn("group/conversation-message relative w-full", className)}
      from={isHuman ? "user" : "assistant"}
    >
      <MessageContent
        className={isHuman ? "w-fit" : "w-full"}
        message={message}
        isLoading={isLoading}
        citationRegistry={citationRegistry}
      />
      <MessageToolbar
        className={cn(
          isHuman ? "-bottom-9 justify-end" : "-bottom-8",
          "absolute right-0 left-0 z-20 opacity-0 transition-opacity delay-200 duration-300 group-hover/conversation-message:opacity-100",
        )}
      >
        <div className="flex gap-1">
          <CopyButton
            clipboardData={
              extractContentFromMessage(message) ??
              extractReasoningContentFromMessage(message) ??
              ""
            }
          />
        </div>
      </MessageToolbar>
    </AIElementMessage>
  );
}

/**
 * Custom image component that handles artifact URLs
 */
function MessageImage({
  src,
  alt,
  threadId,
  maxWidth = "90%",
  ...props
}: React.ImgHTMLAttributes<HTMLImageElement> & {
  threadId: string;
  maxWidth?: string;
}) {
  if (!src) return null;

  const imgClassName = cn("overflow-hidden rounded-lg", `max-w-[${maxWidth}]`);

  if (typeof src !== "string") {
    return <img className={imgClassName} src={src} alt={alt} {...props} />;
  }

  const url = src.startsWith("/mnt/") ? resolveArtifactURL(src, threadId) : src;

  return (
    <a href={url} target="_blank" rel="noopener noreferrer">
      <img className={imgClassName} src={url} alt={alt} {...props} />
    </a>
  );
}

function MessageContent_({
  className,
  message,
  isLoading = false,
  citationRegistry,
}: {
  className?: string;
  message: Message;
  isLoading?: boolean;
  citationRegistry?: KnowledgeCitationRegistryItem[];
}) {
  const rehypePlugins = useRehypeSplitWordsIntoSpans(isLoading);
  const isHuman = message.type === "human";
  const { thread_id } = useParams<{ thread_id: string }>();
  const components = useMemo(
    () => ({
      img: (props: ImgHTMLAttributes<HTMLImageElement>) => (
        <MessageImage {...props} threadId={thread_id} maxWidth="90%" />
      ),
    }),
    [thread_id],
  );

  const rawContent = extractContentFromMessage(message);
  const reasoningContent = extractReasoningContentFromMessage(message);
  const { contentToParse, uploadedFiles, isUngrounded } = useMemo(() => {
    if (!isLoading && reasoningContent && !rawContent) {
      return {
        contentToParse: reasoningContent,
        uploadedFiles: [] as UploadedFile[],
        isUngrounded: false,
      };
    }
    if (isHuman && rawContent) {
      const { files, cleanContent: contentWithoutFiles } =
        parseUploadedFiles(rawContent);
      return { contentToParse: contentWithoutFiles, uploadedFiles: files, isUngrounded: false };
    }
    const raw = rawContent ?? "";
    const hasMarker = raw.includes(UNGROUNDED_MARKER);
    return {
      contentToParse: hasMarker ? raw.replace(UNGROUNDED_MARKER, "").trimEnd() : raw,
      uploadedFiles: [] as UploadedFile[],
      isUngrounded: hasMarker,
    };
  }, [isLoading, rawContent, reasoningContent, isHuman]);

  const filesList =
    uploadedFiles.length > 0 && thread_id ? (
      <UploadedFilesList files={uploadedFiles} threadId={thread_id} />
    ) : null;

  if (isHuman) {
    const messageResponse = contentToParse ? (
      <AIElementMessageResponse
        remarkPlugins={humanMessagePlugins.remarkPlugins}
        rehypePlugins={humanMessagePlugins.rehypePlugins}
        components={components}
      >
        {contentToParse}
      </AIElementMessageResponse>
    ) : null;
    return (
      <div className={cn("ml-auto flex flex-col gap-2", className)}>
        {filesList}
        {messageResponse && (
          <AIElementMessageContent className="w-fit">
            {messageResponse}
          </AIElementMessageContent>
        )}
      </div>
    );
  }

  return (
    <AIElementMessageContent className={className}>
      {filesList}
      <MarkdownContent
        content={contentToParse}
        isLoading={isLoading}
        rehypePlugins={[...rehypePlugins, [rehypeKatex, { output: "html" }]]}
        className="my-3"
        components={components}
        citationRegistry={citationRegistry}
      />
      {isUngrounded && !isLoading && <UngroundedWarningBanner />}
    </AIElementMessageContent>
  );
}

/**
 * Get file extension and check helpers
 */
const getFileExt = (filename: string) =>
  filename.split(".").pop()?.toLowerCase() ?? "";

const FILE_TYPE_MAP: Record<string, string> = {
  json: "JSON",
  csv: "CSV",
  txt: "TXT",
  md: "Markdown",
  py: "Python",
  js: "JavaScript",
  ts: "TypeScript",
  tsx: "TSX",
  jsx: "JSX",
  html: "HTML",
  css: "CSS",
  xml: "XML",
  yaml: "YAML",
  yml: "YAML",
  pdf: "PDF",
  png: "PNG",
  jpg: "JPG",
  jpeg: "JPEG",
  gif: "GIF",
  svg: "SVG",
  zip: "ZIP",
  tar: "TAR",
  gz: "GZ",
};

const IMAGE_EXTENSIONS = ["png", "jpg", "jpeg", "gif", "webp", "svg", "bmp"];

function getFileTypeLabel(filename: string): string {
  const ext = getFileExt(filename);
  return FILE_TYPE_MAP[ext] ?? (ext.toUpperCase() || "FILE");
}

function isImageFile(filename: string): boolean {
  return IMAGE_EXTENSIONS.includes(getFileExt(filename));
}

/**
 * Uploaded files list component
 */
function UploadedFilesList({
  files,
  threadId,
}: {
  files: UploadedFile[];
  threadId: string;
}) {
  if (files.length === 0) return null;

  return (
    <div className="mb-2 flex flex-wrap justify-end gap-2">
      {files.map((file, index) => (
        <UploadedFileCard
          key={`${file.path}-${index}`}
          file={file}
          threadId={threadId}
        />
      ))}
    </div>
  );
}

/**
 * Single uploaded file card component
 */
function UploadedFileCard({
  file,
  threadId,
}: {
  file: UploadedFile;
  threadId: string;
}) {
  if (!threadId) return null;

  const isImage = isImageFile(file.filename);
  const fileUrl = resolveArtifactURL(file.path, threadId);
  const isPdf = getFileExt(file.filename) === "pdf";
  const actionLabel = isPdf ? "打开原文" : "打开文件";

  if (isImage) {
    return (
      <a
        href={fileUrl}
        target="_blank"
        rel="noopener noreferrer"
        className="group border-border/40 relative block overflow-hidden rounded-lg border"
      >
        <img
          src={fileUrl}
          alt={file.filename}
          className="h-32 w-auto max-w-[240px] object-cover transition-transform group-hover:scale-105"
        />
      </a>
    );
  }

  const cardContent = (
    <div className="bg-background border-border/40 flex max-w-[200px] min-w-[120px] flex-col gap-1 rounded-lg border p-3 shadow-sm">
      <div className="flex items-start gap-2">
        <FileIcon className="text-muted-foreground mt-0.5 size-4 shrink-0" />
        <span
          className="text-foreground truncate text-sm font-medium"
          title={file.filename}
        >
          {file.filename}
        </span>
      </div>
      <div className="flex items-center justify-between gap-2">
        <Badge
          variant="secondary"
          className="rounded px-1.5 py-0.5 text-[10px] font-normal"
        >
          {getFileTypeLabel(file.filename)}
        </Badge>
        <span className="text-muted-foreground text-[10px]">{file.size}</span>
      </div>
      <div className="flex items-center justify-between text-[11px] tracking-wide">
        <span className="text-primary underline decoration-dotted">
          {actionLabel}
        </span>
        {isPdf && <span className="text-muted-foreground">PDF 原文</span>}
      </div>
    </div>
  );

  return (
    <a
      href={fileUrl}
      target="_blank"
      rel="noopener noreferrer"
      className="group inline-block"
    >
      {cardContent}
    </a>
  );
}

function UngroundedWarningBanner() {
  return (
    <div className="mt-3 flex items-start gap-2 rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:border-amber-400/30 dark:bg-amber-400/10 dark:text-amber-300">
      <TriangleAlertIcon className="mt-0.5 size-3.5 shrink-0" />
      <span>当前回答未依据史料库检索，内容源自模型训练数据，请谨慎参考。</span>
    </div>
  );
}

const MessageContent = memo(MessageContent_);
