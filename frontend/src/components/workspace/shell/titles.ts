/**
 * The top bar's title when the page has not set one (a thread sets its own,
 * through useShellTitle). Most specific first.
 */
const TITLES: [RegExp, string][] = [
  [/^\/workspace\/(agents\/[^/]+\/)?chats\/new$/, "New chat"],
  [/^\/workspace\/chats\/?$/, "Chats"],
  [/^\/workspace\/home/, "Home"],
  [/^\/workspace\/sessions/, "Coding sessions"],
  [/^\/workspace\/connections/, "Connections"],
  [/^\/workspace\/(mcp|tool-sources)/, "MCP Suite"],
  [/^\/workspace\/settings/, "Settings"],
  [/^\/workspace\/projects/, "Projects"],
  [/^\/workspace\/agents/, "Agents"],
  [/^\/workspace\/(automations|triggers|workflows)/, "Automations"],
  [/^\/workspace\/policy/, "Policy"],
];

export function defaultTitle(pathname: string | null): string {
  if (!pathname) return "";
  return TITLES.find(([re]) => re.test(pathname))?.[1] ?? "";
}
