import type { RetrievedChunk } from "../types";

export function buildGroundedPrompt(userQuestion: string, top: RetrievedChunk[]) {
  const context = top
    .map((c, i) => {
      const url = c.source_url ?? "";
      const sec = c.section ? ` [${c.section}]` : "";
      return `[[${i + 1}]] ${c.content}\nSOURCE: ${url}${sec}\n`;
    })
    .join("\n");

  return `You are a helpful assistant for JioPay.
Answer the question using ONLY the context.
If the answer is not in the context, say you don't know.

Question:
${userQuestion}

Context:
${context}

Instructions:
- Be concise (<= 6 sentences).
- Cite sources inline using bracket numbers like [1], [2] matching the provided SOURCES.
- Do not fabricate information.

Final Answer:`;
}
