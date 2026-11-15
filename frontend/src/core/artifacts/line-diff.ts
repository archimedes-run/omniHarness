/**
 * A small line diff for the versions drawer's Compare (no library): the
 * longest common subsequence of two texts' lines, with long runs of
 * unchanged lines collapsed to a count. Pure; unit-tested in
 * tests/unit/artifacts-viewer.test.ts.
 */

export type DiffRow =
  | { type: "same" | "add" | "del"; text: string }
  | { type: "skip"; count: number };

/** Above this many line pairs the table would be too large to build. */
export const DIFF_CELL_CAP = 4_000_000;

function lines(text: string): string[] {
  const t = text.replace(/\r\n?/g, "\n");
  return t === "" ? [] : t.split("\n");
}

/** Lines of `before` and `after`, as rows; null when too large to compare. */
export function lineDiff(
  before: string,
  after: string,
  context = 3,
): DiffRow[] | null {
  const a = lines(before);
  const b = lines(after);
  // Common head and tail first: most versions differ in a few lines.
  let head = 0;
  while (head < a.length && head < b.length && a[head] === b[head]) head++;
  let tail = 0;
  while (
    tail < a.length - head &&
    tail < b.length - head &&
    a[a.length - 1 - tail] === b[b.length - 1 - tail]
  ) {
    tail++;
  }
  const midA = a.slice(head, a.length - tail);
  const midB = b.slice(head, b.length - tail);
  const n = midA.length;
  const m = midB.length;
  if ((n + 1) * (m + 1) > DIFF_CELL_CAP) return null;
  // LCS lengths, from the end.
  const w = m + 1;
  const len = new Uint32Array((n + 1) * w);
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      len[i * w + j] =
        midA[i] === midB[j]
          ? len[(i + 1) * w + j + 1]! + 1
          : Math.max(len[(i + 1) * w + j]!, len[i * w + j + 1]!);
    }
  }
  const raw: { type: "same" | "add" | "del"; text: string }[] = [];
  for (const text of a.slice(0, head)) raw.push({ type: "same", text });
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (midA[i] === midB[j]) {
      raw.push({ type: "same", text: midA[i]! });
      i++;
      j++;
    } else if (len[(i + 1) * w + j]! >= len[i * w + j + 1]!) {
      raw.push({ type: "del", text: midA[i++]! });
    } else {
      raw.push({ type: "add", text: midB[j++]! });
    }
  }
  while (i < n) raw.push({ type: "del", text: midA[i++]! });
  while (j < m) raw.push({ type: "add", text: midB[j++]! });
  for (const text of a.slice(a.length - tail)) raw.push({ type: "same", text });
  return collapse(raw, context);
}

/** Keeps `context` unchanged lines around each change; the rest become one
 * "skip" row each run. */
function collapse(
  raw: { type: "same" | "add" | "del"; text: string }[],
  context: number,
): DiffRow[] {
  const near = new Uint8Array(raw.length);
  raw.forEach((r, k) => {
    if (r.type === "same") return;
    for (
      let x = Math.max(0, k - context);
      x <= Math.min(raw.length - 1, k + context);
      x++
    ) {
      near[x] = 1;
    }
  });
  const out: DiffRow[] = [];
  let skipped = 0;
  raw.forEach((r, k) => {
    if (r.type === "same" && !near[k]) {
      skipped++;
      return;
    }
    if (skipped) out.push({ type: "skip", count: skipped });
    skipped = 0;
    out.push(r);
  });
  if (skipped) out.push({ type: "skip", count: skipped });
  return out;
}

/** True when the diff has at least one added or removed line. */
export function hasChanges(rows: DiffRow[]): boolean {
  return rows.some((r) => r.type === "add" || r.type === "del");
}
