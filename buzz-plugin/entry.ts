// Uses the released app's documented API-v1 injection and agent registration.
import { GooseRuntime, DEFAULT_CONFIG, config } from "buzz-source/src/bundled/goose/runtime";
import { gooseRun } from "buzz-source/src/bundled/goose/run";

export const inject = ["agents", "host", "react"];
export function apply(ctx: any) {
  const { agents, host, react: React } = ctx;
  if (!host.spawn || !host.serveMcp || !host.resolveDirectory || !host.readFile) return;
  // Every connection with this token has the same agent/conversation authority.
  // agy reconnects its MCP client on each turn; no other agent shares the token.
  const native = {
    spawn: host.spawn.bind(host), readFile: host.readFile.bind(host),
    resolveDirectory: host.resolveDirectory.bind(host),
    serveMcp: (handler: any) => host.serveMcp(handler, { sharedSession: true }),
  };
  const runtime = new GooseRuntime(native as any, agents.relay,
    (key: any, signal: any) => agents.core(key, signal), localStorage,
    () => agents.tools());
  const type = `${ctx.pluginOwner.id}/antigravity`;
  const defaults = { ...DEFAULT_CONFIG, model: "gemini-4-argon-high", effort: "high" };
  const sync = () => {
    const state = agents.snapshot();
    if (state.status !== "loading") runtime.sync(state.running.filter((a: any) => a.type === type));
  };
  const stop = agents.subscribe(sync);
  sync();
  ctx.effect(() => () => { stop(); runtime.dispose(); });
  const run = gooseRun(runtime);
  const controls = run.sessionControls!;
  run.sessionControls = { ...controls, run: (agent: any, place: any, action: any) => {
    if (action === "compact") return Promise.reject(new Error(
      "Antigravity handles context internally. Use New session to reset this conversation."));
    return controls.run(agent, place, action);
  } };

  // Native, labelled controls inside the host-owned creation/settings surfaces.
  function Fields({ value, change, disabled }: any) {
    const control = (label: string, key: string, multiline = false) =>
      React.createElement("label", { key }, label,
        React.createElement(multiline ? "textarea" : "input", {
          value: value[key] ?? "", disabled,
          onChange: (e: any) => change({ ...value, [key]: e.target.value }),
        }));
    return React.createElement("div", null,
      control("Model", "model"), control("Reasoning effort", "effort"),
      control("Working directory", "workspace"), control("Agent instructions", "instructions", true));
  }
  function Create(props: any) {
    return React.createElement(Fields, { value: props.config, change: props.onChange, disabled: props.disabled });
  }
  function Settings({ agent, save }: any) {
    const [draft, setDraft] = React.useState(() => config(agent.config));
    const [error, setError] = React.useState("");
    const [saving, setSaving] = React.useState(false);
    React.useEffect(() => { setDraft(config(agent.config)); }, [agent.key, agent.config]);
    return React.createElement("form", { onSubmit: async (e: any) => {
      e.preventDefault(); setSaving(true); setError("");
      try { await save(draft); } catch (e: any) { setError(e.message); }
      finally { setSaving(false); }
    } }, React.createElement(Fields, { value: draft, change: setDraft, disabled: saving }),
    React.createElement("button", { type: "submit", disabled: saving }, saving ? "Saving…" : "Save settings"),
    error && React.createElement("p", { role: "alert" }, error));
  }
  agents.register({
    id: "antigravity", title: "Antigravity (Ultra)",
    description: "Your Google AI Ultra subscription through the official Antigravity CLI on this computer.",
    defaults: () => ({ config: defaults }),
    Create, summary: (a: any) => config(a.config).model || defaults.model,
    carry: (saved: any) => ({ instructions: config(saved).instructions, workspace: config(saved).workspace }),
    adopt: (carry: any, saved: any) => ({ ...saved, ...carry }),
    tabs: [{ id: "settings", title: "Settings", role: "settings", component: Settings }],
    sessions: { list: (key: any) => runtime.sessions(key).map((s: any) => {
      const [channelId, root] = s.key.split("/");
      return { channelId, ...(root && { root }), at: s.at, status: s.busy ? "Working" : "Idle" };
    }), subscribe: (listener: any) => runtime.subscribe(listener) },
    ...run,
  });
}
