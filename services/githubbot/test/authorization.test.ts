import { describe, expect, test } from "bun:test";
import { hasRepositoryWritePermission } from "../src/authorization";

function client(permission: unknown) {
  return {
    rest: {
      repos: {
        getCollaboratorPermissionLevel: async () => ({ data: { permission } }),
      },
    },
  };
}

describe("hasRepositoryWritePermission", () => {
  test("allows effective write, maintain, and admin permission", async () => {
    for (const permission of ["write", "maintain", "admin"]) {
      expect(
        await hasRepositoryWritePermission(client(permission), {
          owner: "worldfnd",
          repo: "provekit",
          username: "alice",
        }),
      ).toBe(true);
    }
  });

  test("denies read, triage, none, missing, and unknown permission", async () => {
    for (const permission of ["read", "triage", "none", undefined, "future-role"]) {
      expect(
        await hasRepositoryWritePermission(client(permission), {
          owner: "worldfnd",
          repo: "provekit",
          username: "alice",
        }),
      ).toBe(false);
    }
  });

  test("fails closed when GitHub's permission lookup fails", async () => {
    const octokit = {
      rest: {
        repos: {
          getCollaboratorPermissionLevel: async () => {
            throw new Error("GitHub unavailable");
          },
        },
      },
    };
    expect(
      await hasRepositoryWritePermission(octokit, {
        owner: "worldfnd",
        repo: "provekit",
        username: "alice",
      }),
    ).toBe(false);
  });

  test("passes the exact repository and commenter to GitHub", async () => {
    let received: unknown;
    const octokit = {
      rest: {
        repos: {
          getCollaboratorPermissionLevel: async (input: unknown) => {
            received = input;
            return { data: { permission: "write" } };
          },
        },
      },
    };
    await hasRepositoryWritePermission(octokit, {
      owner: "worldcoin-foundation",
      repo: "centaur",
      username: "dcbuilder",
    });
    expect(received).toEqual({
      owner: "worldcoin-foundation",
      repo: "centaur",
      username: "dcbuilder",
    });
  });
});
