export type RetrievedChunk = {
  id: number;
  content: string;
  source_url: string | null;
  section: string | null;
  topic: string | null;
  token_count: number | null;
  chunk_method: string;
  metadata: any;
  similarity: number; // 0..1
};

export type SearchResult = {
  chunks: RetrievedChunk[];
  latencyMs: number;
  embeddingMs: number;
  k: number;
};
