/**
 * "/" commands at the start of a message. Every one here does something real
 * in the app; nothing is listed that only looks like it works.
 */
export type PickerTab =
  | "projects"
  | "agents"
  | "integrations"
  | "skills"
  | "files";

export type CommandAction =
  | { kind: "new-chat" }
  | { kind: "open-picker"; tab: PickerTab }
  | { kind: "attach" };

export interface SlashCommand {
  name: string;
  description: string;
  action: CommandAction;
}

export const BUILTIN_COMMANDS: readonly SlashCommand[] = [
  {
    name: "new",
    description: "Start a new chat",
    action: { kind: "new-chat" },
  },
  {
    name: "project",
    description: "Attach this chat to a project",
    action: { kind: "open-picker", tab: "projects" },
  },
  {
    name: "agent",
    description: "Call in an agent",
    action: { kind: "open-picker", tab: "agents" },
  },
  {
    name: "integrations",
    description: "Choose the integrations this chat can use",
    action: { kind: "open-picker", tab: "integrations" },
  },
  {
    name: "skill",
    description: "See the skills this chat's agent may use",
    action: { kind: "open-picker", tab: "skills" },
  },
  {
    name: "attach",
    description: "Attach files",
    action: { kind: "attach" },
  },
];

export function matchCommands(query: string): SlashCommand[] {
  const q = query.toLowerCase();
  return BUILTIN_COMMANDS.filter((c) => c.name.startsWith(q));
}
