import React, { useMemo, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Loader2, Send, Sparkles } from "lucide-react";
import { semanticSearch } from "@/lib/search";
import { buildGroundedPrompt } from "@/lib/prompt";
import { generateAnswer } from "@/lib/hf";
import type { RetrievedChunk } from "@/types";

type Message = { role: "user" | "assistant"; text: string; citations?: RetrievedChunk[] };

export default function Chat() {
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [k, setK] = useState(5);
  const [lastChunks, setLastChunks] = useState<RetrievedChunk[]>([]);
  const [latency, setLatency] = useState<{ embed: number; search: number; gen: number }>({
    embed: 0,
    search: 0,
    gen: 0,
  });

  const inputRef = useRef<HTMLInputElement>(null);

  async function ask() {
    if (!q.trim() || busy) return;
    setBusy(true);
    setMessages((m) => [...m, { role: "user", text: q.trim() }]);

    try {
      // 1) retrieve
      const sr = await semanticSearch(q.trim(), k);
      setLastChunks(sr.chunks);

      // 2) compose prompt
      const prompt = buildGroundedPrompt(q.trim(), sr.chunks);

      // 3) generate
      const t0 = performance.now();
      const answer = await generateAnswer(prompt);
      const t1 = performance.now();

      // 4) track timing
      setLatency({ embed: sr.embeddingMs, search: sr.latencyMs, gen: t1 - t0 });

      // 5) show assistant message + citations stored separately
      setMessages((m) => [...m, { role: "assistant", text: answer, citations: sr.chunks }]);
    } catch (e: any) {
      setMessages((m) => [
        ...m,
        { role: "assistant", text: `Sorry, something went wrong:\n${e?.message || e}` },
      ]);
    } finally {
      setBusy(false);
      setQ("");
      inputRef.current?.focus();
    }
  }

  const info = useMemo(
    () =>
      `latency — embed: ${latency.embed.toFixed(1)}ms | search: ${latency.search.toFixed(
        1
      )}ms | gen: ${latency.gen.toFixed(1)}ms`,
    [latency]
  );

  return (
    <div className="max-w-4xl mx-auto p-4 space-y-4">
      <Card className="shadow-lg">
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle className="text-xl">JioPay RAG Chatbot</CardTitle>
          <div className="text-sm text-muted-foreground">{info}</div>
        </CardHeader>
        <Separator />
        <CardContent className="space-y-4">
          <div className="flex gap-2">
            <Input
              ref={inputRef}
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Ask about onboarding, KYC, refunds, API..."
              onKeyDown={(e) => e.key === "Enter" && ask()}
            />
            <Button onClick={ask} disabled={busy || !q.trim()}>
              {busy ? <Loader2 className="animate-spin h-4 w-4" /> : <Send className="h-4 w-4" />}
            </Button>
          </div>

          <div className="text-sm text-muted-foreground">
            Uses pgvector on Supabase (cosine), BGE embeddings, and a small HF text model.
          </div>

          <ScrollArea className="h-[60vh] rounded-md border p-3">
            <div className="space-y-4">
              {messages.map((m, i) => (
                <div key={i} className="space-y-2">
                  <div className="flex items-center gap-2">
                    <Badge variant={m.role === "user" ? "secondary" : "default"}>
                      {m.role === "user" ? "You" : "Assistant"}
                    </Badge>
                    {m.role === "assistant" && <Sparkles className="h-4 w-4 text-purple-500" />}
                  </div>
                  <div className="whitespace-pre-wrap leading-relaxed">{m.text}</div>

                  {/* show citations for assistant messages */}
                  {m.role === "assistant" && m.citations && m.citations.length > 0 && (
                    <div className="mt-2 space-y-2">
                      <div className="text-xs font-medium text-muted-foreground">Citations:</div>
                      <div className="space-y-2">
                        {m.citations.slice(0, k).map((c, idx) => (
                          <Card key={c.id} className="p-2">
                            <div className="text-xs text-muted-foreground">[{idx + 1}]</div>
                            <div className="text-sm">{c.content.slice(0, 240)}{c.content.length > 240 ? "..." : ""}</div>
                            <div className="text-xs mt-1">
                              <a
                                href={c.source_url ?? "#"}
                                target="_blank"
                                rel="noreferrer"
                                className="underline"
                              >
                                {c.source_url || "No URL"}
                              </a>{" "}
                              <span className="text-muted-foreground">
                                {c.section ? ` • ${c.section}` : ""} • sim {c.similarity.toFixed(3)}
                              </span>
                            </div>
                          </Card>
                        ))}
                      </div>
                    </div>
                  )}
                  <Separator className="my-2" />
                </div>
              ))}
            </div>
          </ScrollArea>
        </CardContent>
      </Card>
    </div>
  );
}
