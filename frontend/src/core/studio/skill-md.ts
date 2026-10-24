/**
 * SKILL.md as Skill Studio edits it: the frontmatter's `description` (the
 * "When should it be used?" sentence the model reads to pick the skill) and
 * the body (its instructions). Every other frontmatter line is kept as it is,
 * so editing here never drops a licence or an allowed-tools list.
 */

export interface SkillDoc {
  name: string;
  description: string;
  body: string;
  /** Frontmatter lines other than name and description, verbatim. */
  rest: string[];
}

const FENCE = "---";

function unquote(value: string): string {
  const v = value.trim();
  if (v.startsWith('"') && v.endsWith('"') && v.length >= 2) {
    try {
      return JSON.parse(v) as string;
    } catch {
      return v.slice(1, -1);
    }
  }
  if (v.startsWith("'") && v.endsWith("'") && v.length >= 2) {
    return v.slice(1, -1).replace(/''/g, "'");
  }
  return v;
}

export function parseSkillMd(content: string): SkillDoc {
  const text = content.replace(/\r\n/g, "\n");
  if (!text.startsWith(`${FENCE}\n`)) {
    return { name: "", description: "", body: text, rest: [] };
  }
  const end = text.indexOf(`\n${FENCE}`, FENCE.length);
  if (end < 0) return { name: "", description: "", body: text, rest: [] };
  const lines = text.slice(FENCE.length + 1, end).split("\n");
  const afterFence = text.slice(end + FENCE.length + 1);
  const body = afterFence.replace(/^[^\n]*\n/, "").replace(/^\n/, "");

  let name = "";
  let description = "";
  const rest: string[] = [];
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]!;
    const key = /^([A-Za-z0-9_-]+):\s?(.*)$/.exec(line);
    if (!key) {
      rest.push(line);
      continue;
    }
    const [, field, value = ""] = key;
    if (field === "name") {
      name = unquote(value);
    } else if (field === "description") {
      const v = value.trim();
      if (v === ">" || v === "|" || v === ">-" || v === "|-") {
        const block: string[] = [];
        while (i + 1 < lines.length && /^\s+\S/.test(lines[i + 1]!)) {
          block.push(lines[++i]!.trim());
        }
        description = block.join(v.startsWith(">") ? " " : "\n");
      } else {
        description = unquote(v);
      }
    } else {
      rest.push(line);
      // Keep an indented block that belongs to this key with it.
      while (i + 1 < lines.length && /^\s+\S/.test(lines[i + 1]!)) {
        rest.push(lines[++i]!);
      }
    }
  }
  return { name, description, body, rest };
}

/** YAML-safe scalar: a JSON string is a valid YAML double-quoted scalar. */
function scalar(value: string): string {
  const one = value.replace(/\s*\n\s*/g, " ").trim();
  return /^[\w .,()'/-]+$/.test(one) && !/^[-?]/.test(one)
    ? one
    : JSON.stringify(one);
}

export function composeSkillMd(doc: SkillDoc): string {
  const front = [
    FENCE,
    `name: ${doc.name}`,
    `description: ${scalar(doc.description)}`,
    ...doc.rest.filter((line) => line.trim() !== ""),
    FENCE,
  ].join("\n");
  const body = doc.body.replace(/^\n+/, "");
  return `${front}\n\n${body.endsWith("\n") ? body : `${body}\n`}`;
}

/** "Project status format" -> "project-status-format" (the skill's id). */
export function skillSlug(title: string): string {
  return title
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 64);
}

/** Where an added file goes: support files live under one of four folders. */
export function supportPathFor(fileName: string): string {
  const base = fileName.split(/[\\/]/).pop() ?? fileName;
  if (/\.(py|sh|js|ts|rb|mjs)$/i.test(base)) return `scripts/${base}`;
  if (/\.(md|txt|rst)$/i.test(base)) return `references/${base}`;
  if (/\.(j2|jinja|tmpl|template|html)$/i.test(base))
    return `templates/${base}`;
  return `assets/${base}`;
}
