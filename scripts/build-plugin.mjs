// Build one self-contained API-v1 plugin, using pinned upstream harness code.
import { build } from "esbuild";
import { execFileSync } from "node:child_process";
import { readFile, mkdir, writeFile, realpath } from "node:fs/promises";
import { resolve, dirname, relative } from "node:path";
import { fileURLToPath } from "node:url";
const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
process.chdir(root);
const source = resolve(process.argv[2] || "/tmp/gooseagy-buzz-app-source");
const upstream = "1c0f6d68ae11d834f6ac8a9287b3b983cc967275";
if (execFileSync("git", ["-C", source, "rev-parse", "HEAD"], {encoding:"utf8"}).trim() !== upstream)
  throw new Error(`Build requires block/buzz-app at ${upstream}`);
execFileSync("git", ["-C", source, "diff", "--quiet", "HEAD", "--", "src"]);
const dest = resolve(root, "buzz-plugin/dist");
const notices = (await Promise.all(["NOTICE.md", "LICENSE", "UPSTREAM_NOTICE.md"]
  .map(name => readFile(resolve(root,"buzz-plugin",name),"utf8")))).join("\n\n");
const version = (await readFile(resolve(root,"acp_server.py"),"utf8")).match(/^VERSION = "([^"]+)"/m)[1];
await mkdir(dest, { recursive: true });
await build({
  entryPoints: [resolve(root, "buzz-plugin/entry.ts")], outfile: resolve(dest, "plugin.js"),
  bundle: true, format: "esm", platform: "browser", target: "es2022", minify: false,
  nodePaths: [resolve(root, "scripts/node_modules")],
  banner: {js: `// Built for gooseagy ACP ${version}\n` + notices.split("\n")
    .map(line => line.trimEnd() ? "// " + line.trimEnd() : "//").join("\n")},
  plugins: [{ name: "pinned-buzz-harness", setup(b) {
    b.onResolve({ filter: /^buzz-source\// }, a => ({ path: resolve(source, a.path.slice(12) + ".ts") }));
    b.onLoad({ filter: /src\/bundled\/goose\/goose\.ts$/ }, async () => ({
      contents: await readFile(resolve(root, "buzz-plugin/acp-facade.ts"), "utf8"), loader: "ts",
      resolveDir: resolve(source, "src/bundled/goose"),
    }));
    b.onLoad({ filter: /src\/bundled\/goose\/sessions\.ts$/ }, async a => ({
      contents: (await readFile(a.path, "utf8")).replace('"buzz.goose.sessions.v1"', '"local.gooseagy.sessions.v1"'),
      loader: "ts", resolveDir: dirname(a.path),
    }));
    b.onLoad({ filter: /src\/bundled\/goose\/runtime\.ts$/ }, async a => ({
      contents: 'import { fromOwner } from "../../features/agents/owner-attestation";\n' +
        (await readFile(a.path, "utf8")).replace('  fromOwner,\n', ''),
      loader: "ts", resolveDir: dirname(a.path),
    }));
    // Runtime helpers re-exported by the app's Service module must not pull
    // a second app service container into an external plugin.
    b.onLoad({ filter: /src\/features\/agents\/service\.ts$/ }, a => ({
      contents: 'export { fromOwner } from "./owner-attestation";',
      loader: "ts", resolveDir: dirname(a.path),
    }));
    b.onLoad({ filter: /\.md\?raw$/ }, async a => ({ contents: await readFile(a.path.slice(0,-4), "utf8"), loader: "text" }));
    b.onResolve({ filter: /\.md\?raw$/ }, a => ({ path: resolve(a.resolveDir, a.path) }));
  }}],
});
// esbuild's source comments otherwise depend on the upstream checkout's path.
let code = await readFile(resolve(dest,"plugin.js"),"utf8");
for (const base of new Set([source, await realpath(source)])) {
  const prefix = "// " + relative(root,base) + "/";
  code = code.split("\n").map(line => line.startsWith(prefix)
    ? "// buzz-app/" + line.slice(prefix.length) : line).join("\n");
}
await writeFile(resolve(dest,"plugin.js"),code);
execFileSync(process.execPath, ["--input-type=module", "--check"], {
  input: await readFile(resolve(dest,"plugin.js")), stdio:["pipe","pipe","pipe"],
});
await writeFile(resolve(dest, "manifest.json"), JSON.stringify({
  id: "local.gooseagy", name: "Antigravity Ultra", apiVersion: 1,
  description: "Use your Google AI Ultra account through the official agy CLI, with Buzz tools and conversation sessions.",
  discovery: { category: "agents", tags: ["Antigravity", "Gemini", "Ultra"] },
  host: { processes: [{ id: "agent", program: "agy-acp" }], mcp: true, files: true },
}, null, 2) + "\n");
console.log("Plugin ready:", dest);
