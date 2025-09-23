import { sb } from "./supabase";
import { embedQuery } from "./hf";
import type { RetrievedChunk, SearchResult } from "../types";

export async function semanticSearch(query: string, k = 5): Promise<SearchResult> {
  const t0 = performance.now();
  const emb = await embedQuery(query);
  const t1 = performance.now();

  const { data, error } = await sb.rpc("jiopay_similarity_search", {
    query_embedding: emb,
    match_count: k,
    source_filter: null,
    topic_filter: null,
    content_type_filter: null,
    min_similarity: 0.0,
    metadata_filter: {},
  });

  if (error) throw new Error(error.message);

  const t2 = performance.now();
  const chunks = (data as RetrievedChunk[]) || [];
  return { chunks, latencyMs: t2 - t1, embeddingMs: t1 - t0, k };
}
