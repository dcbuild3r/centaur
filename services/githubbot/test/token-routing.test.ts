import { describe, expect, test } from "bun:test";
import { repositoryOwnerFromWebhook } from "../src/index";

describe("repositoryOwnerFromWebhook", () => {
  test("normalizes the repository owner for PAT routing", () => {
    expect(
      repositoryOwnerFromWebhook(
        JSON.stringify({ repository: { owner: { login: "WorldFND" } } }),
      ),
    ).toBe("worldfnd");
  });

  test("fails closed to the default token for malformed or incomplete bodies", () => {
    expect(repositoryOwnerFromWebhook("not-json")).toBeUndefined();
    expect(repositoryOwnerFromWebhook(JSON.stringify({ repository: {} }))).toBeUndefined();
  });
});
