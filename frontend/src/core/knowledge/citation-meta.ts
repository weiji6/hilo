export interface KnowledgeCitationMeta {
  scope: string | null;
  sourceKind: string | null;
  sourceLabel: string | null;
  sourceTitle: string | null;
  originTitle: string | null;
}

export interface KnowledgeCitationPageRef {
  queryParam: "page" | "page_no" | "pdf_page_no" | null;
  startPage: number | null;
  endPage: number | null;
  isRange: boolean;
  label: string | null;
}

function parsePositiveInteger(value: string | null): number | null {
  if (!value) {
    return null;
  }
  const parsed = parseInt(value, 10);
  return Number.isNaN(parsed) || parsed <= 0 ? null : parsed;
}

function parseNonNegativeInteger(value: string | null): number | null {
  if (value === null || value === "") {
    return null;
  }
  const parsed = parseInt(value, 10);
  return Number.isNaN(parsed) || parsed < 0 ? null : parsed;
}

function parsePositiveIntegerRange(value: string | null): {
  startPage: number;
  endPage: number;
} | null {
  if (!value) {
    return null;
  }

  const normalized = value.trim();
  const match = /^(\d+)\s*-\s*(\d+)$/.exec(normalized);
  if (!match) {
    return null;
  }

  const startPage = parsePositiveInteger(match[1] ?? null);
  const endPage = parsePositiveInteger(match[2] ?? null);
  if (!startPage || !endPage || endPage < startPage) {
    return null;
  }

  return { startPage, endPage };
}

function fallbackSourceLabel(scope: string | null, sourceKind: string | null): string | null {
  if (scope === "user") {
    if (sourceKind && ["excerpt", "annotation", "translation", "note"].includes(sourceKind)) {
      return "你的笔记";
    }
    if (sourceKind === "upload") {
      return "你上传的文档";
    }
    return "你的文档";
  }

  if (scope === "thread") {
    return "你上传的文档";
  }

  if (scope === "global") {
    return "知识库文档";
  }

  return null;
}

export function getKnowledgeCitationPageRef(documentUrl: string): KnowledgeCitationPageRef {
  try {
    const base =
      typeof window !== "undefined"
        ? window.location.origin
        : "http://localhost:2026";
    const url = new URL(documentUrl, base);

    const pageValue = url.searchParams.get("page");
    if (pageValue) {
      const parsedPage = parseNonNegativeInteger(pageValue);
      if (parsedPage !== null) {
        return {
          queryParam: "page",
          startPage: parsedPage + 1,
          endPage: parsedPage + 1,
          isRange: false,
          label: `第 ${parsedPage + 1} 页`,
        };
      }
    }

    for (const key of ["pdf_page_no", "page_no"] as const) {
      const rawValue = url.searchParams.get(key);
      const range = parsePositiveIntegerRange(rawValue);
      if (range) {
        return {
          queryParam: key,
          startPage: range.startPage,
          endPage: range.endPage,
          isRange: range.startPage !== range.endPage,
          label: `第 ${range.startPage}-${range.endPage} 页`,
        };
      }

      const parsedPage = parsePositiveInteger(rawValue);
      if (parsedPage) {
        return {
          queryParam: key,
          startPage: parsedPage,
          endPage: parsedPage,
          isRange: false,
          label: `第 ${parsedPage} 页`,
        };
      }
    }
  } catch {
    return {
      queryParam: null,
      startPage: null,
      endPage: null,
      isRange: false,
      label: null,
    };
  }

  return {
    queryParam: null,
    startPage: null,
    endPage: null,
    isRange: false,
    label: null,
  };
}

export function getKnowledgeCitationMeta(documentUrl: string): KnowledgeCitationMeta {
  try {
    const base =
      typeof window !== "undefined"
        ? window.location.origin
        : "http://localhost:2026";
    const url = new URL(documentUrl, base);
    const scope = url.searchParams.get("citation_scope");
    const sourceKind = url.searchParams.get("citation_source_kind");
    return {
      scope,
      sourceKind,
      sourceLabel:
        url.searchParams.get("citation_source_label") ??
        fallbackSourceLabel(scope, sourceKind),
      sourceTitle: url.searchParams.get("citation_source_title"),
      originTitle: url.searchParams.get("citation_origin_title"),
    };
  } catch {
    return {
      scope: null,
      sourceKind: null,
      sourceLabel: null,
      sourceTitle: null,
      originTitle: null,
    };
  }
}
