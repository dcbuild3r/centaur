const WRITE_PERMISSIONS = new Set(["write", "maintain", "admin"]);

type PermissionClient = {
  rest: {
    repos: {
      getCollaboratorPermissionLevel(input: {
        owner: string;
        repo: string;
        username: string;
      }): Promise<{ data: { permission?: unknown } }>;
    };
  };
};

/** Ask GitHub for effective repository permission, failing closed. */
export async function hasRepositoryWritePermission(
  octokit: PermissionClient,
  input: { owner: string; repo: string; username: string },
): Promise<boolean> {
  try {
    const response =
      await octokit.rest.repos.getCollaboratorPermissionLevel(input);
    const permission = response.data.permission;
    return (
      typeof permission === "string" &&
      WRITE_PERMISSIONS.has(permission.toLowerCase())
    );
  } catch {
    return false;
  }
}
