import { spawn, spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

function getWindowsInstallCandidates() {
  if (process.platform !== "win32") return [];
  const dirs = [
    process.env.LOCALAPPDATA
      ? path.join(process.env.LOCALAPPDATA, "Programs", "Python")
      : null,
    process.env.ProgramFiles
      ? path.join(process.env.ProgramFiles, "Python")
      : null,
    process.env.ProgramFiles || null,
  ].filter(Boolean);

  const found = [];
  for (const base of dirs) {
    try {
      for (const entry of fs.readdirSync(base)) {
        if (/^Python3\d+$/i.test(entry)) {
          found.push([path.join(base, entry, "python.exe"), []]);
        }
      }
    } catch {
      // Directory does not exist
    }
  }
  return found;
}

function findPython() {
  const cwd = process.cwd();
  const candidates = [
    [path.join(cwd, ".venv", "Scripts", "python.exe"), []],
    [path.join(cwd, "venv", "Scripts", "python.exe"), []],
    [path.join(cwd, ".venv", "bin", "python"), []],
    [path.join(cwd, "venv", "bin", "python"), []],
    ["python3", []],
    ["python", []],
    ["py", ["-3"]],
    ["py", []],
    ...getWindowsInstallCandidates(),
  ];

  for (const [cmd, prefixArgs] of candidates) {
    if (cmd.includes(path.sep) && !fs.existsSync(cmd)) {
      continue;
    }
    const probe = spawnSync(cmd, [...prefixArgs, "--version"], {
      encoding: "utf-8",
      stdio: ["ignore", "pipe", "pipe"],
    });
    const output = `${probe.stdout || ""}${probe.stderr || ""}`.trim();
    if (probe.status === 0 && output.startsWith("Python 3.")) {
      return { cmd, prefixArgs };
    }
  }

  return null;
}

const args = process.argv.slice(2);
if (args.length === 0) {
  console.error("Usage: node run_python.mjs <python-args...>");
  process.exit(1);
}

const python = findPython();
if (!python) {
  console.error(
    [
      "Python 3 was not found on PATH or in .venv/venv.",
      "To fix this in Windows / Visual Studio:",
      "  1. Install Python 3.11+ from https://www.python.org/downloads/ (check 'Add python.exe to PATH')",
      "  2. Or disable the Windows Store python3 alias: Settings > Apps > Advanced app settings > App execution aliases",
      "  3. Or run directly with your Visual Studio Python environment: .\\.venv\\Scripts\\python.exe server.py",
    ].join("\n")
  );
  process.exit(1);
}

const child = spawn(python.cmd, [...python.prefixArgs, ...args], {
  stdio: "inherit",
});

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => {
    child.kill(signal);
  });
}

child.on("exit", (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
  } else {
    process.exit(code ?? 0);
  }
});
