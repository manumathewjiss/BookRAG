"use client";

import { useCallback, useRef, useState } from "react";
import { looksLikePdf, validatePdfFile } from "@/lib/pdf/validate";

export function UploadDropzone({
  disabled,
  onFile,
}: {
  disabled?: boolean;
  onFile: (file: File) => Promise<void> | void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  const handle = useCallback(
    async (file: File | undefined) => {
      if (!file || disabled || busy) return;
      const basic = validatePdfFile(file);
      if (!basic.ok) {
        setMessage(basic.message);
        return;
      }
      const magic = await looksLikePdf(file);
      if (!magic) {
        setMessage("That file does not look like a PDF.");
        return;
      }
      setBusy(true);
      setMessage(`Selected ${file.name}. Uploading…`);
      try {
        await onFile(file);
        setMessage(`Queued ${file.name}. Indexing will update the library status.`);
      } catch (err) {
        setMessage(err instanceof Error ? err.message : "Could not upload that PDF.");
      } finally {
        setBusy(false);
        if (inputRef.current) inputRef.current.value = "";
      }
    },
    [busy, disabled, onFile],
  );

  return (
    <div
      className={`dropzone ${over ? "over" : ""}`}
      onDragOver={(e) => {
        e.preventDefault();
        if (!disabled) setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        void handle(e.dataTransfer.files[0]);
      }}
    >
      <p>
        Drag a digital-text PDF here, or{" "}
        <button
          type="button"
          className="ghost"
          disabled={disabled || busy}
          onClick={() => inputRef.current?.click()}
        >
          choose a file
        </button>
      </p>
      <p style={{ fontSize: "0.82rem", marginBottom: 0 }}>
        PDF only, 25 MB max. Scanned image-only pages may index poorly.
      </p>
      <input
        ref={inputRef}
        type="file"
        accept="application/pdf,.pdf"
        disabled={disabled || busy}
        onChange={(e) => void handle(e.target.files?.[0])}
      />
      <p className="status" aria-live="polite">
        {message}
      </p>
    </div>
  );
}
