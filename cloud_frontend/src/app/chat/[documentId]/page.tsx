import { AppShell } from "@/components/AppShell";
import { ChatWorkspace } from "@/components/ChatWorkspace";

export default async function ChatPage({
  params,
}: {
  params: Promise<{ documentId: string }>;
}) {
  const { documentId } = await params;
  return (
    <AppShell>
      <ChatWorkspace documentId={documentId} />
    </AppShell>
  );
}
