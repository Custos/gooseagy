// Adapt the app's shared harness implementation using its plain ACP hooks.
import { AcpProcess } from "../../features/agent-harness/acp/process";
export { REQUEST_TIMEOUT_MS, TOOL_SERVER } from "../../features/agent-harness/acp/process";
export { stepLabel } from "../../features/agent-harness/acp/steps";

const hooks = {
  label: "Antigravity", program: "agent", missing: "Install agy-acp using gooseagy/install.py",
  env: {}, diagnoseStartup: true,
  select: async (process: any, session: any, want: any) => {
    for (const [key, value] of [["model", want.model], ["effort", want.effort]]) {
      const prior = key === "model" ? session.chosen.model : session.chosen.effort;
      if (value && value !== prior) {
        session.offer(await process.request("session/set_config_option", {
          sessionId: session.id, configId: key, value,
        }));
      }
    }
    session.chosen = { ...want };
  },
};
export const GooseProcess = { start: (spawn: any, launch: any) => AcpProcess.start(spawn, hooks, launch) };
