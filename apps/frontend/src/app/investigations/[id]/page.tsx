import { InvestigationWorkspace } from "@/features/workspace/investigation-workspace";

export default async function InvestigationPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <InvestigationWorkspace id={id} />;
}
