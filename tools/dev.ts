// `npm run dev`: the Python API server (restarted when server/ changes) and Vite's dev server for the page.
import { spawn } from "node:child_process";

const procs = [
  spawn("uv", ["run", "python", "-m", "server", "--reload"], { stdio: "inherit" }),
  spawn(process.execPath, ["node_modules/vite/bin/vite.js"], { stdio: "inherit" }),
];
const stop = () => { for (const p of procs) p.kill(); };
for (const p of procs) p.on("exit", code => { stop(); process.exitCode = code ?? 0; });
process.on("SIGINT", stop);
process.on("SIGTERM", stop);
