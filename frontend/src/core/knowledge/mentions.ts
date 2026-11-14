import type { KnowledgeFileInfo } from "./api";
import type { SelectedMaterial } from "./selection";
import type { UserKnowledgeRecord } from "./user-api";

export interface MentionableKnowledgeMaterial extends SelectedMaterial {
  bookTitle: string;
  tokenLabel: string;
  groupLabel: string;
  subtitle: string;
  searchText: string;
}

const SYSTEM_TYPE_LABELS: Record<string, string> = {
  core: "核心通用书",
  specialized: "专题支撑书",
  reference: "参考工具书",
  unknown: "系统资料",
};

function stripExtension(filename: string | null | undefined): string {
  return String(filename ?? "")
    .replace(/\.[^.]+$/, "")
    .trim();
}

function normalizeText(value: string): string {
  return value.trim().toLowerCase();
}

function buildGlobalMentionable(
  file: KnowledgeFileInfo,
): MentionableKnowledgeMaterial | null {
  const docId = String(file.doc_id ?? "").trim();
  if (!docId || (file.parse_status !== "indexed" && file.parse_status !== "parsed")) {
    return null;
  }

  const bookTitle = stripExtension(file.filename);
  if (!bookTitle) {
    return null;
  }

  const typeLabel =
    SYSTEM_TYPE_LABELS[String(file.type ?? "").toLowerCase()] ??
    SYSTEM_TYPE_LABELS.unknown ??
    "系统资料";

  return {
    doc_id: docId,
    title: bookTitle,
    bookTitle,
    filename: file.filename,
    scope: "global",
    tokenLabel: `系统知识库/${typeLabel}/${bookTitle}`,
    groupLabel: "系统知识库",
    subtitle: typeLabel,
    searchText: normalizeText(
      [
        bookTitle,
        file.filename,
        typeLabel,
        file.summary,
        ...(file.categories ?? []),
        ...(file.eras ?? []),
        ...(file.regions ?? []),
        ...(file.keywords ?? []),
        ...(file.tags ?? []),
      ]
        .filter(Boolean)
        .join(" "),
    ),
  };
}

function buildUserMentionable(
  record: UserKnowledgeRecord,
): MentionableKnowledgeMaterial | null {
  const docId = String(record.id ?? "").trim();
  if (!docId || (record.parse_status !== "indexed" && record.parse_status !== "parsed")) {
    return null;
  }

  const bookTitle =
    String(record.display_title ?? "").trim() ||
    String(record.title ?? "").trim() ||
    stripExtension(record.filename);
  if (!bookTitle) {
    return null;
  }

  const spaceName =
    String(record.knowledge_space_name ?? "").trim() || "默认空间";

  return {
    doc_id: docId,
    title: bookTitle,
    bookTitle,
    filename: record.filename ?? null,
    scope: "user",
    tokenLabel: `个人知识库/${spaceName}/${bookTitle}`,
    groupLabel: "个人知识库",
    subtitle: spaceName,
    searchText: normalizeText(
      [
        bookTitle,
        record.title,
        record.display_title,
        record.filename,
        spaceName,
        record.document_type,
      ]
        .filter(Boolean)
        .join(" "),
    ),
  };
}

function ensureUniqueTokenLabels(
  materials: MentionableKnowledgeMaterial[],
): MentionableKnowledgeMaterial[] {
  const counts = new Map<string, number>();
  for (const material of materials) {
    counts.set(material.tokenLabel, (counts.get(material.tokenLabel) ?? 0) + 1);
  }

  return materials.map((material) => {
    if ((counts.get(material.tokenLabel) ?? 0) <= 1) {
      return material;
    }

    const suffix = material.filename
      ? stripExtension(material.filename)
      : material.doc_id;
    return {
      ...material,
      tokenLabel: `${material.tokenLabel} (${suffix})`,
      searchText: `${material.searchText} ${normalizeText(suffix)}`.trim(),
    };
  });
}

export function buildMentionableKnowledgeMaterials(
  globalFiles: KnowledgeFileInfo[],
  userRecords: UserKnowledgeRecord[],
): MentionableKnowledgeMaterial[] {
  const materials = [
    ...userRecords
      .map((record) => buildUserMentionable(record))
      .filter((item): item is MentionableKnowledgeMaterial => item !== null),
    ...globalFiles
      .map((file) => buildGlobalMentionable(file))
      .filter((item): item is MentionableKnowledgeMaterial => item !== null),
  ];

  return ensureUniqueTokenLabels(materials).sort((left, right) => {
    if (left.groupLabel !== right.groupLabel) {
      return left.groupLabel === "个人知识库" ? -1 : 1;
    }
    return left.bookTitle.localeCompare(right.bookTitle, "zh-CN");
  });
}

export function resolveSelectedMaterialsFromMentions(
  text: string,
  mentionables: MentionableKnowledgeMaterial[],
): {
  normalizedText: string;
  selectedMaterials: SelectedMaterial[];
} {
  const selectedMaterials: SelectedMaterial[] = [];
  const seenDocIds = new Set<string>();
  const tokenMap = new Map(
    mentionables.map((material) => [material.tokenLabel, material] as const),
  );

  const normalizedText = text.replace(
    /@《([^》]+)》/g,
    (_match, rawLabel: string) => {
      const label = String(rawLabel ?? "").trim();
      const material = tokenMap.get(label);
      if (material && !seenDocIds.has(material.doc_id)) {
        seenDocIds.add(material.doc_id);
        selectedMaterials.push({
          doc_id: material.doc_id,
          title: material.title,
          filename: material.filename,
          scope: material.scope,
        });
      }

      return `《${material?.bookTitle ?? label.split("/").at(-1) ?? label}》`;
    },
  );

  return {
    normalizedText,
    selectedMaterials,
  };
}
