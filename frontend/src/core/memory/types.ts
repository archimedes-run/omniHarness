export interface MemoryFact {
  id: string;
  content: string;
  category: string;
  confidence: number;
  createdAt: string;
  source: string;
}

export interface MemoryFactInput {
  content: string;
  category: string;
  confidence: number;
}

export interface MemoryFactPatchInput {
  content?: string;
  category?: string;
  confidence?: number;
}

export interface UserMemory {
  version: string;
  lastUpdated: string;
  user: {
    workContext: {
      summary: string;
      updatedAt: string;
    };
    personalContext: {
      summary: string;
      updatedAt: string;
    };
    topOfMind: {
      summary: string;
      updatedAt: string;
    };
  };
  history: {
    recentMonths: {
      summary: string;
      updatedAt: string;
    };
    earlierContext: {
      summary: string;
      updatedAt: string;
    };
    longTermBackground: {
      summary: string;
      updatedAt: string;
    };
  };
  facts: MemoryFact[];
}

/** A summary section's address: "user.topOfMind", "history.recentMonths". */
export type MemorySectionGroup = "user" | "history";

export interface MemoryCleanupSection {
  group: MemorySectionGroup;
  key: string;
  before: string;
  after: string;
  changed: boolean;
}

/** What the one-time cleanup would change. Nothing is saved until applied. */
export interface MemoryCleanupPreview {
  /** lastUpdated when previewed; applying is refused if memory changed. */
  version: string;
  sections: MemoryCleanupSection[];
  factsToRemove: { id: string | null; content: string; markers: string[] }[];
}
