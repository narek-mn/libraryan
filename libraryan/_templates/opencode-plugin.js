// Libraryan: block OpenCode edits to docs Libraryan owns, through the same guard as the other tools' hooks.
// The installer fills in the guard command (install.GUARD_CMD) below.
export const Libraryan = async ({ $, directory }) => ({
  "tool.execute.before": async (input, output) => {
    if (!["edit", "write", "patch"].includes(input.tool)) return
    const a = output.args || {}
    const payload = input.tool === "patch"  // ponytail: patch arg name UNVERIFIED, both spellings tried
      ? { tool_name: "apply_patch", tool_input: { patch: a.patchText ?? a.patch ?? "" }, cwd: directory }
      : { tool_name: "Write", tool_input: { file_path: a.filePath }, cwd: directory }
    const r = await $`sh -c ${__GUARD_CMD__} < ${new Response(JSON.stringify(payload))}`
      .cwd(directory).nothrow().quiet()
    if (r.exitCode === 2) throw new Error(String(r.stderr))
  },
})
