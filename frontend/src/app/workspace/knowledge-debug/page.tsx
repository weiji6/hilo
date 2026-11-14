import { ArtifactsProvider } from "@/components/workspace/artifacts/context";
import KnowledgeDebugPage from "@/components/workspace/knowledge-debug-page";

export default function WorkspaceKnowledgeDebugPage() {
  return (
    <ArtifactsProvider>
      <KnowledgeDebugPage />
    </ArtifactsProvider>
  );
}
