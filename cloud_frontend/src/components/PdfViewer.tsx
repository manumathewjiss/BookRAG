"use client";

import { useEffect, useRef, useState } from "react";
import type { BookragClient } from "@/lib/api";

export function PdfViewer({
  documentId,
  filename,
  page,
  client,
}: {
  documentId: string;
  filename: string;
  page: number;
  client: BookragClient;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [message, setMessage] = useState("Loading page…");
  const [pageCount, setPageCount] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function render() {
      setMessage("Opening PDF…");
      const data = await client.getPdf(documentId);
      const pdfjs = await import("pdfjs-dist");
      pdfjs.GlobalWorkerOptions.workerSrc = new URL(
        "pdfjs-dist/build/pdf.worker.min.mjs",
        import.meta.url,
      ).toString();
      const bytes = new Uint8Array(data).slice();
      const task = pdfjs.getDocument({ data: bytes });
      const pdf = await task.promise;
      if (cancelled) return;
      setPageCount(pdf.numPages);
      const target = Math.min(Math.max(1, page), pdf.numPages);
      const pdfPage = await pdf.getPage(target);
      const viewport = pdfPage.getViewport({ scale: 1.2 });
      const canvas = canvasRef.current;
      if (!canvas) return;
      const context = canvas.getContext("2d");
      if (!context) return;
      canvas.width = viewport.width;
      canvas.height = viewport.height;
      await pdfPage.render({ canvasContext: context, viewport }).promise;
      if (!cancelled) {
        setMessage(`${filename} · PDF page ${target}${pdf.numPages ? ` of ${pdf.numPages}` : ""}`);
      }
    }
    void render().catch(() => {
      if (!cancelled) setMessage("Could not render that PDF page in this browser.");
    });
    return () => {
      cancelled = true;
    };
  }, [client, documentId, filename, page]);

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
