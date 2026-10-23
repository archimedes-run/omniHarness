import { redirect } from "next/navigation";

/**
 * "New agent" is created in place in Agent Studio from one sentence
 * (Feature 006 Phase 3; design-parity.md "Agents / new"): this route opens
 * the Agents panel with a new agent selected, so every old link lands there.
 */
export default function NewAgentPage() {
  redirect("/workspace/chats/new?panel=agents&item=new");
}
