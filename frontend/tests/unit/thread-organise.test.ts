import { describe, expect, it } from "vitest";

import {
  archivePatch,
  folderOf,
  foldersOf,
  isArchived,
  TESTS_FOLDER,
  unarchivePatch,
} from "@/core/threads/organise";

/** Archive and folders for chats: the patch bodies and the reading rules. */
describe("chat archive and folders", () => {
  it("builds the PATCH metadata the gateway accepts", () => {
    expect(archivePatch()).toEqual({ archived: true });
    expect(archivePatch(TESTS_FOLDER)).toEqual({
      archived: true,
      folder: "Tests",
    });
    expect(unarchivePatch()).toEqual({ archived: false });
    for (const bad of ["", " Tests", "a".repeat(41), "../x", "<b>"]) {
      expect(() => archivePatch(bad), bad).toThrow();
    }
  });

  it("reads archived and folder strictly", () => {
    expect(isArchived({ metadata: { archived: true } })).toBe(true);
    expect(isArchived({ metadata: { archived: "true" } })).toBe(false);
    expect(isArchived({ metadata: {} })).toBe(false);
    expect(folderOf({ metadata: { folder: "Tests" } })).toBe("Tests");
    expect(folderOf({ metadata: { folder: "<script>" } })).toBeNull();
    expect(folderOf({ metadata: {} })).toBeNull();
  });

  it("lists folders with Tests first", () => {
    expect(
      foldersOf([
        { metadata: { folder: "Zeta" } },
        { metadata: { folder: "Tests" } },
        { metadata: { folder: "Alpha" } },
        { metadata: { folder: "Alpha" } },
        { metadata: {} },
      ]),
    ).toEqual(["Tests", "Alpha", "Zeta"]);
  });
});
