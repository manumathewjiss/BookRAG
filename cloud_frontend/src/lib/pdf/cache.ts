const DB_NAME = "bookrag-pdf-cache-v1";
const STORE = "pdfs";

interface CachedPdf {
  id: string;
  filename: string;
  bytes: ArrayBuffer;
}

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE)) db.createObjectStore(STORE, { keyPath: "id" });
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

export async function cachePdf(id: string, file: File): Promise<void> {
  const bytes = await file.arrayBuffer();
  const db = await openDb();
  await new Promise<void>((resolve, reject) => {
    const tx = db.transaction(STORE, "readwrite");
    tx.objectStore(STORE).put({ id, filename: file.name, bytes } satisfies CachedPdf);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
  db.close();
}

export async function readCachedPdf(id: string): Promise<CachedPdf | null> {
  const db = await openDb();
  const row = await new Promise<CachedPdf | null>((resolve, reject) => {
    const tx = db.transaction(STORE, "readonly");
    const req = tx.objectStore(STORE).get(id);
    req.onsuccess = () => resolve((req.result as CachedPdf) || null);
    req.onerror = () => reject(req.error);
  });
  db.close();
  return row;
}

export async function removeCachedPdf(id: string): Promise<void> {
  const db = await openDb();
  await new Promise<void>((resolve, reject) => {
    const tx = db.transaction(STORE, "readwrite");
    tx.objectStore(STORE).delete(id);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
  db.close();
}
