import { McpServerDetail } from "@/components/workspace/mcp/mcp-server-detail";

interface Props {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ thread?: string }>;
}

export default async function McpServerDetailPage({
  params,
  searchParams,
}: Props) {
  const { id } = await params;
  const { thread } = await searchParams;
  return <McpServerDetail serverId={id} threadId={thread} />;
}
