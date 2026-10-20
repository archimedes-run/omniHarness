import { afterEach, describe, expect, it, vi } from "vitest";

import { revealRefusal, revealSecret } from "@/core/mcp-studio/reveal";

const PASSWORD = "Str0ng!Pass99";

function respond(status: number, body: unknown) {
  return vi.fn(
    async (_url: string, _init?: RequestInit) =>
      new Response(JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/json" },
      }),
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("revealSecret", () => {
  it("POSTs the password in the JSON body, never in the URL", async () => {
    const fetchMock = respond(200, { values: { GITHUB_TOKEN: "ghp_x" } });
    vi.stubGlobal("fetch", fetchMock);
    const result = await revealSecret("srv-1", "GITHUB_TOKEN", PASSWORD);
    expect(result).toEqual({ ok: true, value: "ghp_x" });
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toContain("/api/mcp-studio/servers/srv-1/secrets/reveal");
    expect(url).not.toContain(PASSWORD);
    expect(init?.method).toBe("POST");
    expect(JSON.parse(init?.body as string)).toEqual({
      key_name: "GITHUB_TOKEN",
      password: PASSWORD,
    });
  });

  it("turns a wrong password into words, with no value", async () => {
    vi.stubGlobal("fetch", respond(403, { detail: "Password is incorrect." }));
    expect(await revealSecret("srv-1", "GITHUB_TOKEN", "nope")).toEqual({
      ok: false,
      message: "That password is not right.",
    });
  });
});

describe("revealRefusal", () => {
  it("says why for each refusal", () => {
    expect(revealRefusal(429, null)).toMatch(/Too many wrong passwords/);
    expect(revealRefusal(400, "This account signs in without a password")).toBe(
      "This account signs in without a password",
    );
    expect(revealRefusal(404, null)).toMatch(/no stored value/);
    expect(revealRefusal(500, null)).toMatch(/500/);
  });
});
