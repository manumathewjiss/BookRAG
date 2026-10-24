# Later approved cloud verification checklist

This is an execution checklist, **not authorization** to deploy or spend. Use a separate test project and an explicitly approved low-cost run.

1. **Secrets and origin.** Enter `DATABASE_URL`, Supabase URL and service role key, Voyage key, OpenAI key, and the exact frontend origin in server-only secrets. Keep them out of browser builds and logs. Disable automatic provider top-ups if that is the intended budget control.
2. **Database and Storage.** Apply migrations `001_initial.sql` and `002_embedding_checkpoints.sql` in order. Confirm pgvector 1024-d works. Confirm the `bookrag-pdfs` bucket is private and only the backend service credential can upload, download, or delete.
3. **Two-user isolation.** Sign in as A and B. Upload A's PDF. Confirm B cannot list, read status, chat with, or delete A's document. Check direct Supabase table access under B's token cannot read A's rows. Try an invalid/expired token.
4. **Page accuracy.** Upload a small known two-page digital-text PDF. Confirm status becomes ready, both pages are indexed separately, and a page-2 answer cites PDF page 2 with matching source text. Reject an image-only/encrypted or oversized PDF cleanly.
5. **Search and answer.** Ask one answerable question and one genuinely unanswerable question. Check the answerable citation ID is in Sol's five supplied passages and its page comes from stored metadata. Confirm the unanswerable answer has no citation presented as proof of absence.
6. **Worker recovery.** Stop a worker after one completed batch and restart it. Verify the completed batch is reused. Simulate a definite 429 and verify only that batch retries. Simulate a timeout after dispatch and verify the job stops for operator review, without an automatic duplicate request.
7. **Limits and accounting.** Exercise upload/day, question/minute, question/day, and estimated-dollar limits. Compare stored token counts with provider dashboards. Confirm service logs do not contain keys or full prompts.
8. **Deletion.** Delete a ready document. Confirm the private Storage object, passages, checkpoints, and job are removed and both users receive 404 afterwards.
9. **Deployment behavior.** Check API health, worker startup, cold start, memory, PDF upload size, PostgreSQL connection pooling, browser CORS, and the frontend's queued/processing/failed/ready views. Keep auto-deploy off until the review is complete.

Record results and costs under a **new** verification directory. Do not overwrite the frozen benchmark or prior evaluation results.
