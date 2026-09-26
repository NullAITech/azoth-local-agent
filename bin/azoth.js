#!/usr/bin/env node
/**
 * aZoth Local Agent — Unified CLI & Desktop Workstation Launcher
 */

const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

const rootDir = path.resolve(__dirname, '..');
const args = process.argv.slice(2);

// Check if user requested web mode, desktop app, or CLI
const isWeb = args[0] === 'web' || args.includes('--web');
const isAppRequest = !isWeb && (args.length === 0 || args.includes('--gui') || args.includes('--app') || args.includes('--desktop') || args[0] === 'app' || args[0] === 'desktop' || args[0] === 'gui');

if (isWeb) {
  console.log('⚡ Launching aZoth Local Cockpit Web UI on http://127.0.0.1:8790 ...');
  const pyChild = spawn('python3', ['web_ui.py', '--port', '8790'], {
    cwd: rootDir,
    stdio: 'inherit',
    env: {
      ...process.env,
      PORT: '8790',
      ZOTH_ZERO_EGRESS: 'true',
    },
  });
  pyChild.on('error', (pyErr) => {
    console.error('[AzothAgent] Failed to start web cockpit:', pyErr);
  });
} else if (isAppRequest) {
  console.log('⚡ Launching aZoth Local Desktop Workstation...');
  
  // Find Electron in local node_modules, sibling micro-repos, or system PATH
  const candidateElectronPaths = [
    path.join(rootDir, 'node_modules', '.bin', 'electron'),
    '/media/neo/f2fdda77-178b-4603-ae80-c7aa4cd97908/zoth-micro-repos/NullAI-HexStrike-AI-Terminal/node_modules/.bin/electron',
    '/media/neo/f2fdda77-178b-4603-ae80-c7aa4cd97908/zoth-micro-repos/promptmaster-studio/node_modules/.bin/electron',
    '/media/neo/f2fdda77-178b-4603-ae80-c7aa4cd97908/zoth-micro-repos/jwt-inspector-guard/node_modules/.bin/electron',
    '/media/neo/f2fdda77-178b-4603-ae80-c7aa4cd97908/zoth-micro-repos/envguard-secrets-vault/node_modules/.bin/electron',
    '/media/neo/f2fdda77-178b-4603-ae80-c7aa4cd97908/cron-rhythm-studio/node_modules/.bin/electron',
    '/media/neo/f2fdda77-178b-4603-ae80-c7aa4cd97908/regex-droid-builder/node_modules/.bin/electron',
    '/media/neo/f2fdda77-178b-4603-ae80-c7aa4cd97908/schema-illustrator-studio/node_modules/.bin/electron',
    '/media/neo/f2fdda77-178b-4603-ae80-c7aa4cd97908/payload-entropy-studio/node_modules/.bin/electron',
    '/media/neo/f2fdda77-178b-4603-ae80-c7aa4cd97908/audiocipher-stego-engine/node_modules/.bin/electron',
    '/media/neo/f2fdda77-178b-4603-ae80-c7aa4cd97908/pwa-manifest-builder/node_modules/.bin/electron',
    '/media/neo/f2fdda77-178b-4603-ae80-c7aa4cd97908/certpath-roadmap-studio/node_modules/.bin/electron',
    '/media/neo/f2fdda77-178b-4603-ae80-c7aa4cd97908/subsweep-lead-scanner/node_modules/.bin/electron',
    '/media/neo/f2fdda77-178b-4603-ae80-c7aa4cd97908/web-security-guard/node_modules/.bin/electron',
    '/media/neo/f2fdda77-178b-4603-ae80-c7aa4cd97908/cwv-speed-engine/node_modules/.bin/electron',
    '/media/neo/f2fdda77-178b-4603-ae80-c7aa4cd97908/vector-search-engine/node_modules/.bin/electron',
    '/media/neo/f2fdda77-178b-4603-ae80-c7aa4cd97908/neuro-memory-daemon/node_modules/.bin/electron',
    '/media/neo/f2fdda77-178b-4603-ae80-c7aa4cd97908/aeo-graph-engine/node_modules/.bin/electron',
    '/media/neo/f2fdda77-178b-4603-ae80-c7aa4cd97908/polyglot-framework-exporter/node_modules/.bin/electron',
    '/media/neo/f2fdda77-178b-4603-ae80-c7aa4cd97908/zoth-webgen/node_modules/.bin/electron',
    '/media/neo/f2fdda77-178b-4603-ae80-c7aa4cd97908/deepsearch-research-agent/node_modules/.bin/electron',
    '/media/neo/f2fdda77-178b-4603-ae80-c7aa4cd97908/omnipost-social-engine/node_modules/.bin/electron',
    '/media/neo/f2fdda77-178b-4603-ae80-c7aa4cd97908/nexus-3d-scene-studio/node_modules/.bin/electron',
    '/media/neo/f2fdda77-178b-4603-ae80-c7aa4cd97908/datamosh-glitch-studio/node_modules/.bin/electron',
    '/media/neo/f2fdda77-178b-4603-ae80-c7aa4cd97908/cyber-turtle-studio/node_modules/.bin/electron',
    '/media/neo/f2fdda77-178b-4603-ae80-c7aa4cd97908/badge3d-coin-generator/node_modules/.bin/electron',
    '/media/neo/f2fdda77-178b-4603-ae80-c7aa4cd97908/ufo-sacred-geometry/node_modules/.bin/electron',
    '/media/neo/f2fdda77-178b-4603-ae80-c7aa4cd97908/vision-gesture-control/node_modules/.bin/electron',
    '/media/neo/f2fdda77-178b-4603-ae80-c7aa4cd97908/sovereign-agent-bridge/node_modules/.bin/electron',
    '/media/neo/f2fdda77-178b-4603-ae80-c7aa4cd97908/zoth-micro-repos/zoth-swarm-multiplexer/node_modules/.bin/electron',
  ];

  let electronCmd = 'electron';
  for (const p of candidateElectronPaths) {
    if (fs.existsSync(p)) {
      electronCmd = p;
      break;
    }
  }

  const child = spawn(electronCmd, ['.'], {
    cwd: rootDir,
    stdio: 'inherit',
    env: {
      ...process.env,
      ELECTRON_ENABLE_LOGGING: '1',
      ZOTH_ZERO_EGRESS: 'true',
    },
  });

  child.on('error', (err) => {
    console.warn(`[AzothAgent] Electron notice: ${err.message}. Starting web cockpit on port 8790...`);
    const pyChild = spawn('python3', ['web_ui.py', '--port', '8790'], {
      cwd: rootDir,
      stdio: 'inherit',
      env: {
        ...process.env,
        PORT: '8790',
        ZOTH_ZERO_EGRESS: 'true',
      },
    });
    pyChild.on('error', (pyErr) => {
      console.error('[AzothAgent] Failed to start backend:', pyErr);
    });
  });
} else {
  // Delegate to Python CLI
  const child = spawn('python3', ['agent.py', ...args], {
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
