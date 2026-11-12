"use client";

import { useEffect, useRef, useState } from "react";
import type { BookragClient } from "@/lib/api";
import { errorMessage } from "@/lib/api";

export function PdfViewer({
  documentId,
  filename,
  page,
  samplePassageId,
  client,
}: {
  documentId: string;
  filename: string;
  page: number;
  samplePassageId?: string;
  client: BookragClient;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [message, setMessage] = useState("Loading page…");
  const [pageCount, setPageCount] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function render() {
      setMessage("Opening PDF…");
      const data = samplePassageId
        ? await client.getCitationPagePdf(documentId, samplePassageId)
        : await client.getPdf(documentId);
      const pdfjs = await import("pdfjs-dist");
      // Served from public/; next.config copies pdfjs-dist's worker so Next does not bundle it.
      pdfjs.GlobalWorkerOptions.workerSrc = "/pdf.worker.min.mjs";
      const bytes = new Uint8Array(data).slice();
      const task = pdfjs.getDocument({ data: bytes });
      const pdf = await task.promise;
      if (cancelled) return;
      setPageCount(pdf.numPages);
      const target = samplePassageId ? 1 : Math.min(Math.max(1, page), pdf.numPages);
      const pdfPage = await pdf.getPage(target);
      const narrow = typeof window !== "undefined" && window.innerWidth < 720;
      const viewport = pdfPage.getViewport({ scale: narrow ? 0.95 : 1.2 });
      const canvas = canvasRef.current;
      if (!canvas) return;
      const context = canvas.getContext("2d");
      if (!context) return;
      canvas.width = viewport.width;
      canvas.height = viewport.height;
      await pdfPage.render({ canvasContext: context, viewport }).promise;
      if (!cancelled) {
        setMessage(samplePassageId
          ? `${filename} · cited PDF page ${page}`
          : `${filename} · PDF page ${target}${pdf.numPages ? ` of ${pdf.numPages}` : ""}`);
      }
    }
    void render().catch((err) => {
      if (!cancelled) setMessage(errorMessage(err));
    });
    return () => {
      cancelled = true;
    };
  }, [client, documentId, filename, page, samplePassageId]);

  return (
    <section aria-label="PDF page viewer">
      <h2>PDF page</h2>
      <p className="status">{message}</p>
      <div className="pdf-frame">
        <canvas ref={canvasRef} aria-label={pageCount ? `Page ${page}` : "PDF canvas"} />
      </div>
    </section>
  );
}
