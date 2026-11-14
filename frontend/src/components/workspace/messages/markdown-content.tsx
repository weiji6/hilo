"use client";

import { useMemo } from "react";
import type { ComponentProps } from "react";

import {
  MessageResponse,
  type MessageResponseProps,
} from "@/components/ai-elements/message";
import { streamdownPlugins } from "@/core/streamdown";
import type { KnowledgeCitationRegistryItem } from "@/core/threads";

import { CitationLink } from "../citations/citation-link";

const CITATION_LINK_PATTERN = /\[citation:[^\]]+\]\((?:<[^>\n]+>|[^)\n]+)\)/gi;
const NUMBERED_CITATION_PATTERN = /\[citation:\s*(\d+)\s*\](?!\()/gi;

function extractCitationHref(citation: string): string | null {
  const match = /^\[citation:[^\]]+\]\((<[^>\n]+>|[^)\n]+)\)$/i.exec(
    citation.trim(),
  );
  if (!match) {
    return null;
  }
  const rawHref = match[1]?.trim() ?? "";
  if (!rawHref) {
    return null;
  }
  if (rawHref.startsWith("<") && rawHref.endsWith(">")) {
    const unwrappedHref = rawHref.slice(1, -1).trim();
    return unwrappedHref || null;
  }
  return rawHref;
}

// Encodes URI-unsafe characters (raw spaces, Chinese chars, etc.) without
// touching characters that already participate in a valid `%xx` percent-escape.
// Plain `encodeURI` would re-encode the `%` of an existing `%E4` into `%25E4`,
// which compounds across multiple passes — and this helper is invoked at three
// points along the markdown rendering pipeline (linkify → strip → <a>), so a
// non-idempotent encode produced URLs with 3-4 levels of encoding by render
// time. Backends already send single-encoded URLs, so detect existing escapes
// and leave them alone.
const VALID_PERCENT_ESCAPE = /%[0-9A-Fa-f]{2}/;

function normalizeInternalCitationHref(href: string | null): string | null {
  if (!href) return null;
  if (
    href.startsWith("/api/knowledge/docs/") ||
    href.startsWith("/api/secure-knowledge/users/me/knowledge/docs/")
  ) {
    if (VALID_PERCENT_ESCAPE.test(href)) {
      return href;
    }
    return encodeURI(href).replace(/%253A/g, "%3A");
  }
  return href;
}

function isDisplayableCitationHref(href: string | null): boolean {
  const normalizedHref = normalizeInternalCitationHref(href);
  if (
    !normalizedHref ||
    /\s/.test(normalizedHref) ||
    /^citations?:/i.test(normalizedHref)
  ) {
    return false;
  }
  try {
    const url = normalizedHref.startsWith("/")
      ? new URL(normalizedHref, window.location.origin)
      : new URL(normalizedHref);
    if (normalizedHref.startsWith("/")) {
      return Boolean(url.pathname);
    }
    return url.protocol === "http:" || url.protocol === "https:";
  } catch {
    return false;
  }
}

function stripInvalidCitations(content: string): string {
  return content.replace(CITATION_LINK_PATTERN, (citation) => {
    const href = extractCitationHref(citation);
    const normalizedHref = normalizeInternalCitationHref(href);
    if (!isDisplayableCitationHref(normalizedHref)) {
      return "";
    }
    if (!href || !normalizedHref || href === normalizedHref) {
      return citation;
    }
    const wrappedHref = citation.includes("(<")
      ? `<${normalizedHref}>`
      : normalizedHref;
    return citation.replace(/\((<[^>\n]+>|[^)\n]+)\)$/i, `(${wrappedHref})`);
  });
}

function escapeMarkdownLinkLabel(label: string): string {
  return label.replace(/\\/g, "\\\\").replace(/\]/g, "\\]");
}

export function linkifyNumberedCitations(
  content: string,
  citationRegistry?: KnowledgeCitationRegistryItem[],
): string {
  if (!content || !citationRegistry?.length) {
    return content;
  }

  const citationsById = new Map<string, KnowledgeCitationRegistryItem>();
  for (const item of citationRegistry) {
    const id = String(item.id ?? "").trim();
    const url = String(item.url ?? "").trim();
    if (!id || !isDisplayableCitationHref(normalizeInternalCitationHref(url))) {
      continue;
    }
    citationsById.set(id, item);
  }
  if (citationsById.size === 0) {
    return content;
  }

  return content.replace(NUMBERED_CITATION_PATTERN, (marker, id) => {
    const item = citationsById.get(String(id).trim());
    if (!item) {
      return marker;
    }
    const rawUrl = String(item.url ?? "").trim();
    const href = normalizeInternalCitationHref(rawUrl);
    if (!href) {
      return marker;
    }
    const label = String(item.label ?? "").trim() || `citation:${id}`;
    return `[citation:${escapeMarkdownLinkLabel(label)}](<${href}>)`;
  });
}

export type MarkdownContentProps = {
  content: string;
  isLoading: boolean;
  rehypePlugins: MessageResponseProps["rehypePlugins"];
  className?: string;
  remarkPlugins?: MessageResponseProps["remarkPlugins"];
  components?: MessageResponseProps["components"];
  citationRegistry?: KnowledgeCitationRegistryItem[];
};

/** Renders markdown content. */
export function MarkdownContent({
  content,
  rehypePlugins,
  className,
  remarkPlugins = streamdownPlugins.remarkPlugins,
  components: componentsFromProps,
  citationRegistry,
}: MarkdownContentProps) {
  const components = useMemo(() => {
    return {
      ol: ({ className, ...props }: ComponentProps<"ol">) => (
        <ol
          className={`list-decimal list-outside pl-8 whitespace-normal${className ? ` ${className}` : ""}`}
          {...props}
        />
      ),
      a: (props: ComponentProps<"a">) => {
        const normalizedHref =
          typeof props.href === "string"
            ? normalizeInternalCitationHref(props.href)
            : null;
        if (
          typeof props.children === "string" &&
          /^citation:/i.test(props.children) &&
          !isDisplayableCitationHref(normalizedHref)
        ) {
          return null;
        }
        if (typeof props.children === "string") {
          const match = /^citation:(.+)$/.exec(props.children);
          if (match) {
            const [, text] = match;
            return (
              <CitationLink {...props} href={normalizedHref ?? props.href}>
                {text}
              </CitationLink>
            );
          }
        }
        return <a {...props} href={normalizedHref ?? props.href} />;
      },
      ...componentsFromProps,
    };
  }, [componentsFromProps]);

  if (!content) return null;
  const sanitizedContent = stripInvalidCitations(
    linkifyNumberedCitations(content, citationRegistry),
  );
  if (!sanitizedContent.trim()) return null;

  return (
    <MessageResponse
      className={className}
      remarkPlugins={remarkPlugins}
      rehypePlugins={rehypePlugins}
      components={components}
    >
      {sanitizedContent}
    </MessageResponse>
  );
}
