#!/usr/bin/env node
/**
 * aZoth Local Agent — Unified CLI & Desktop Workstation Launcher
 */

const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

const rootDir = path.resolve(__dirname, '..');
const pythonBin = fs.existsSync(path.join(rootDir, '.venv', 'bin', 'python'))
  ? path.join(rootDir, '.venv', 'bin', 'python')
  : 'python3';
const args = process.argv.slice(2);

// Check if user requested web mode, desktop app, or CLI
const isWeb = args[0] === 'web' || args.includes('--web');
const isAppRequest = !isWeb && (args.includes('--gui') || args.includes('--app') || args.includes('--desktop') || args[0] === 'app' || args[0] === 'desktop' || args[0] === 'gui');

if (isWeb) {
  console.log('⚡ Launching aZoth Local Cockpit Web UI on http://127.0.0.1:8136 ...');
  const pyChild = spawn(pythonBin, ['server.py', '--port', '8136'], {
    cwd: rootDir,
    stdio: 'inherit',
    env: {
      ...process.env,
      PORT: '8136',
      ZOTH_ZERO_EGRESS: 'true',
    },
  });
  pyChild.on('error', (pyErr) => {
    console.error('[AzothAgent] Failed to start web cockpit:', pyErr);
  });
} else if (isAppRequest) {
  console.log('⚡ Launching aZoth Local Desktop Workstation...');
  const child = spawn('electron', ['.'], {
    cwd: rootDir,
    stdio: 'inherit',
    env: {
      ...process.env,
      ELECTRON_ENABLE_LOGGING: '1',
      ZOTH_ZERO_EGRESS: 'true',
    },
  });
  child.on('error', () => {
    console.warn('[AzothAgent] Electron unavailable, falling back to Web UI on http://127.0.0.1:8136 ...');
    const pyChild = spawn(pythonBin, ['server.py', '--port', '8136'], {
      cwd: rootDir,
      stdio: 'inherit',
    });
  });
} else {
  // Delegate to Python CLI agent
  const child = spawn(pythonBin, ['agent.py', ...args], {
    cwd: rootDir,
    stdio: 'inherit',
    env: {
      ...process.env,
      ZOTH_ZERO_EGRESS: 'true',
    },
  });

  child.on('exit', (code) => {
    process.exit(code || 0);
  });
}
