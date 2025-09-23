// src/lib/hf.ts
import axios, { AxiosError } from "axios";
import { GoogleGenerativeAI } from "@google/generative-ai";

const HF_TOKEN = import.meta.env.VITE_HF_TOKEN as string;
const HF_BASE = "https://api-inference.huggingface.co";

const EMB_PRIMARY =
  (import.meta.env.VITE_EMBEDDING_MODEL as string) ||
  "BAAI/bge-small-en-v1.5"; // 384-d
const EMB_FALLBACK =
  (import.meta.env.VITE_EMBEDDING_MODEL_FALLBACK as string) ||
  "sentence-transformers/all-MiniLM-L6-v2"; // 384-d

function authHeaders() {
  if (!HF_TOKEN) throw new Error("Missing VITE_HF_TOKEN in .env");
  return { Authorization: `Bearer ${HF_TOKEN}` };
}

function l2norm(vec: number[]) {
  const n = Math.sqrt(vec.reduce((s, v) => s + v * v, 0)) || 1;
  return vec.map((v) => v / n);
}

export function formatQueryForEmbedding(q: string, modelId: string) {
  const id = modelId.toLowerCase();
  if (id.includes("bge")) return `Represent this sentence for searching relevant passages: ${q}`;
  if (id.includes("e5")) return `query: ${q}`;
  return q; // MiniLM etc.
}

async function embedWithModel(modelId: string, input: string): Promise<number[]> {
  const url = `${HF_BASE}/models/${encodeURIComponent(modelId)}`;
  const payload = { inputs: input, options: { wait_for_model: true } };
  const { data } = await axios.post<number[][]>(url, payload, { headers: authHeaders() });
  const vec = Array.isArray(data?.[0]) ? (data[0] as number[]) : ((data as unknown) as number[]);
  return l2norm(vec.map(Number));
}

export async function embedQuery(query: string): Promise<number[]> {
  try {
    const formatted = formatQueryForEmbedding(query, EMB_PRIMARY);
    return await embedWithModel(EMB_PRIMARY, formatted);
  } catch (e) {
    const status = (e as AxiosError)?.response?.status;
    if (status === 402 || status === 403 || status === 404 || status === 429) {
      console.warn(`[embed] ${EMB_PRIMARY} -> ${status}. Falling back to ${EMB_FALLBACK}`);
      const formatted = formatQueryForEmbedding(query, EMB_FALLBACK);
      return await embedWithModel(EMB_FALLBACK, formatted);
    }
    console.error("HF embed error:", (e as AxiosError).response?.data || (e as Error).message);
    throw e;
  }
}

/* --------------------------- Gemini 2.5 Flash LLM --------------------------- */

const GEMINI_KEY = import.meta.env.VITE_GEMINI_API_KEY as string;
const GEMINI_MODEL = (import.meta.env.VITE_GEMINI_MODEL as string) || "gemini-2.5-flash";

const genAI = new GoogleGenerativeAI(GEMINI_KEY);
const geminiModel = genAI.getGenerativeModel({ model: GEMINI_MODEL });

export async function generateAnswer(prompt: string): Promise<string> {
  const result = await geminiModel.generateContent({
    contents: [{ role: "user", parts: [{ text: prompt }]}],
    generationConfig: {
      temperature: 0.2,
      maxOutputTokens: 600,
    },
  });
  return result.response.text().trim();
}
