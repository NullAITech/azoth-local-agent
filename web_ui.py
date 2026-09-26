#!/usr/bin/env python3
"""a-bot Web Cockpit — Google Material 3 / Gemini Production-Grade UI.

Features:
- Google Material 3 / Gemini Aesthetic & Palette with responsive elevation and smooth micro-interactions.
- Clean Markdown Chat Rendering: Marked.js, Highlight.js syntax highlighting, code copy badges, tables, lists.
- Toast Notification System: Rich animated snackbars for actions (file save, DuckyScript run, engine switch, copy).
- Keyboard Shortcuts & Command Palette: Ctrl+K / Cmd+K Spotlight-style launcher, Ctrl+Enter send, Escape modal dismiss.
- DuckyScript Studio: Interactive runner with preset selector, step-by-step progress timeline, and quick syntax chips.
- Interactive Browser Viewport Canvas: Smooth zoom controls, click ripple pulse, live coordinate tracker, multi-tab strip.
- a-bot Mascot Studio: Real-time particle canvas, responsive shapes, multi-theme gradients, and custom animations.
- Workspace File Manager & Code Editor: View, edit, save, delete, and create workspace files with Ctrl+S shortcut.
- Multi-Engine Agent Router: Hermes Agent CLI, AGY CLI, Codex CLI, Grok CLI, Claude, Gemini, Ollama.
- Waveform Indicator: Real-time animated signal waveform with bar equalizer and line overlay (Ctrl+W).
- Topology Map: Interactive network graph showing agent nodes, connections, live status, hover tooltips.
- Scan Line Effect: CRT-style scan line overlay with moving highlight and horizontal striping (Ctrl+L).
- Stealth Mode: Minimal UI — hides sidebar, dims labels, obscures input; toggleable (Ctrl+S).
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from pathlib import Path
from typing import Any, AsyncGenerator, Optional

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from openai import OpenAI

from tools.browser import get_browser
from tools.code_runner import run_python
from tools.deep_search import deep_search
from tools.definitions import AGENT_TOOLS, execute_tool
from tools.duckyscript import DUCKY_PRESETS, run_duckyscript
from tools.workspace import WORKSPACE_DIR, delete_file, list_files, read_file, write_file
from tools.x_intelligence import draft_x_thread, inspect_x_post_browser, scout_x_trends, search_x
from tools.vm_manager import guest_os
from tools.terminal_bridge import handle_terminal_websocket
from engines.manager import EngineRegistry, EnvConfigManager, execute_cli_agent, execute_cli_agent_stream
from agent import build_system_prompt, agent_step, extract_thinking
from prompts.modes import DEFAULT_MODE, MODES, get_mode, list_modes

ROOT = Path(__file__).resolve().parent
MEMORY_PATH = ROOT / "MEMORY.md"
ENV_PATH = ROOT / ".env"

app = FastAPI(title="aZoth Cockpit")
STATIC_DIR = ROOT / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Active Engine & Mode State
active_state = {
    "engine": "ollama",
    "model": "qwen2.5-coder:1.5b",
    "base_url": "http://localhost:11434/v1",
    "api_key": "ollama",
    "mode": EnvConfigManager.get("AGENT_MODE", DEFAULT_MODE),
}

chat_history: list[dict] = [{"role": "system", "content": build_system_prompt(active_state["mode"])}]


def get_client_for_engine() -> tuple[OpenAI, str]:
    engine = active_state["engine"]
    model = active_state["model"]
    base_url = active_state["base_url"]
    api_key = active_state["api_key"]

    if engine == "ollama":
        base_url = os.getenv("OPENAI_BASE_URL", "http://localhost:11434/v1")
        api_key = "ollama"
    elif engine == "xai":
        base_url = "https://api.x.ai/v1"
        api_key = os.getenv("XAI_API_KEY", "") or api_key
    elif engine == "openai":
        base_url = "https://api.openai.com/v1"
        api_key = os.getenv("OPENAI_API_KEY", "") or api_key
    elif engine == "openrouter":
        base_url = "https://openrouter.ai/api/v1"
        api_key = os.getenv("OPENROUTER_API_KEY", "") or api_key
    elif engine == "gemini":
        base_url = "https://generativelanguage.googleapis.com/v1beta/openai/"
        api_key = os.getenv("GEMINI_API_KEY", "") or api_key

    client = OpenAI(api_key=api_key or "placeholder", base_url=base_url)
    return client, model


class MessageRequest(BaseModel):
    message: str


class EngineConfigRequest(BaseModel):
    engine: str
    model: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None


class BrowserInputRequest(BaseModel):
    type: str  # click, key, type, wheel, navigate, new_tab, switch_tab, close_tab
    x: Optional[int] = None
    y: Optional[int] = None
    key: Optional[str] = None
    text: Optional[str] = None
    delta_y: Optional[int] = None
    url: Optional[str] = None
    tab_index: Optional[int] = None


class DuckyRunRequest(BaseModel):
    script: str
    target: str = "browser"


class FileSaveRequest(BaseModel):
    path: str
    content: str


class FileDeleteRequest(BaseModel):
    path: str


class ModeRequest(BaseModel):
    mode: str


class DeepSearchRequest(BaseModel):
    topic: str
    max_sources: Optional[int] = 6


class XSearchRequest(BaseModel):
    query: str
    max_results: Optional[int] = 8


class PythonRunRequest(BaseModel):
    code: str
    timeout_sec: Optional[int] = 20


class VMExecRequest(BaseModel):
    command: str
    timeout: Optional[int] = 60
    workdir: Optional[str] = None


class VMInstallRequest(BaseModel):
    package: str


class BrowserLoginRequest(BaseModel):
    url: Optional[str] = None
    username: str
    password: str
    user_selector: Optional[str] = None
    pass_selector: Optional[str] = None
    submit_selector: Optional[str] = None


class BrowserAuthRequest(BaseModel):
    url: Optional[str] = None


class BrowserHumanClickRequest(BaseModel):
    selector: str


class BrowserHumanTypeRequest(BaseModel):
    selector: str
    text: str
    press_enter: Optional[bool] = False
    clear_first: Optional[bool] = True


class BrowserFormRequest(BaseModel):
    fields: dict[str, str]
    submit_selector: Optional[str] = None


class BrowserTakeoverRequest(BaseModel):
    url: Optional[str] = "https://x.com"
    reason: Optional[str] = ""


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>aZoth-local — Autonomous Agent & Grok-Grade Intelligence Studio</title>
  
  <!-- Local Offline Assets: 100% Private, Zero Third-Party Tracking Cookies -->
  <link rel="stylesheet" href="/static/highlight.css">
  <link rel="stylesheet" href="/static/xterm.css">
  <script src="/static/tailwind.js"></script>
  <script src="/static/marked.min.js"></script>
  <script src="/static/highlight.min.js"></script>
  <script src="/static/xterm.js"></script>
  <script src="/static/xterm-addon-fit.js"></script>

  <script>
    tailwind.config = {
      theme: {
        extend: {
          fontFamily: {
            sans: ['-apple-system', 'BlinkMacSystemFont', '"Segoe UI"', 'Roboto', 'Inter', 'system-ui', 'sans-serif'],
            display: ['-apple-system', 'BlinkMacSystemFont', '"Segoe UI"', 'Roboto', 'sans-serif'],
            mono: ['ui-monospace', 'SFMono-Regular', '"Roboto Mono"', 'Menlo', 'Monaco', 'Consolas', 'monospace'],
          },
          colors: {
            gblue: '#1a73e8',
            gblueHover: '#1557b0',
            gblueLight: '#e8f0fe',
            gblueContainer: '#d2e3fc',
            gred: '#ea4335',
            gredLight: '#fce8e6',
            gyellow: '#fbbc04',
            gyellowLight: '#fef7e0',
            ggreen: '#34a853',
            ggreenLight: '#e6f4ea',
            gdark: '#202124',
            glight: '#f8fafd',
            gsurface: '#ffffff',
            gsurfaceVariant: '#f1f3f4',
            gborder: '#dadce0',
            gborderLight: '#e8eaed',
            gtext: '#3c4043',
            gsub: '#5f6368',
            geminiPurple: '#7c3aed',
            geminiIndigo: '#4f46e5',
            geminiCyan: '#06b6d4',
          },
          boxShadow: {
            'm3-1': '0 1px 2px rgba(60,64,67,0.3), 0 1px 3px 1px rgba(60,64,67,0.15)',
            'm3-2': '0 1px 2px rgba(60,64,67,0.3), 0 2px 6px 2px rgba(60,64,67,0.15)',
            'm3-3': '0 4px 8px 3px rgba(60,64,67,0.15), 0 1px 3px rgba(60,64,67,0.3)',
            'm3-focus': '0 0 0 3px rgba(26,115,232,0.25)',
          }
        }
      }
    }
  </script>

  <style>
    body { font-family: 'Google Sans', Inter, sans-serif; }
    
    ::-webkit-scrollbar { width: 6px; height: 6px; }
    ::-webkit-scrollbar-track { background: transparent; }
    ::-webkit-scrollbar-thumb { background: #dadce0; border-radius: 9999px; }
    ::-webkit-scrollbar-thumb:hover { background: #bdc1c6; }

    /* Mascot Animations */
    @keyframes bot-breathe {
      0%, 100% { transform: translateY(0px) scale(1); }
      50% { transform: translateY(-7px) scale(1.04); }
    }
    @keyframes bot-pulse {
      0%, 100% { transform: scale(1); filter: drop-shadow(0 0 10px var(--glow-color, rgba(66,133,244,0.5))); }
      50% { transform: scale(1.09); filter: drop-shadow(0 0 22px var(--glow-color, rgba(66,133,244,0.85))); }
    }
    @keyframes bot-bounce {
      0%, 100% { transform: translateY(0); }
      30% { transform: translateY(-12px) rotate(-4deg); }
      60% { transform: translateY(2px) rotate(4deg); }
    }
    @keyframes bot-wave {
      0%, 100% { transform: skewX(0deg) scale(1); }
      25% { transform: skewX(-6deg) scale(1.03); }
      75% { transform: skewX(6deg) scale(0.97); }
    }
    @keyframes bot-gyro {
      0% { transform: perspective(400px) rotateY(0deg) rotateX(10deg); }
      50% { transform: perspective(400px) rotateY(180deg) rotateX(-10deg); }
      100% { transform: perspective(400px) rotateY(360deg) rotateX(10deg); }
    }
    @keyframes bot-sparkle {
      0%, 100% { transform: scale(1) rotate(0deg); filter: brightness(1) drop-shadow(0 0 8px var(--glow-color, #7c3aed)); }
      50% { transform: scale(1.08) rotate(6deg); filter: brightness(1.25) drop-shadow(0 0 24px var(--glow-color, #06b6d4)); }
    }

    .anim-breathe { animation: bot-breathe 3.5s ease-in-out infinite; }
    .anim-pulse { animation: bot-pulse 2s ease-in-out infinite; }
    .anim-bounce { animation: bot-bounce 1.8s ease-in-out infinite; }
    .anim-wave { animation: bot-wave 2.5s ease-in-out infinite; }
    .anim-gyro { animation: bot-gyro 6s linear infinite; }
    .anim-sparkle { animation: bot-sparkle 2.2s ease-in-out infinite; }

    /* Mascot Gradient Palettes */
    .palette-google {
      background: linear-gradient(135deg, #4285F4 0%, #EA4335 35%, #FBBC05 70%, #34A853 100%);
      --glow-color: rgba(66, 133, 244, 0.6);
    }
    .palette-gemini {
      background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 50%, #06b6d4 100%);
      --glow-color: rgba(124, 58, 237, 0.65);
    }
    .palette-ocean {
      background: linear-gradient(135deg, #00c6ff 0%, #0072ff 100%);
      --glow-color: rgba(0, 198, 255, 0.6);
    }
    .palette-emerald {
      background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%);
      --glow-color: rgba(56, 239, 125, 0.6);
    }
    .palette-solar {
      background: linear-gradient(135deg, #ff8c00 0%, #e52d27 100%);
      --glow-color: rgba(255, 140, 0, 0.6);
    }
    .palette-nebula {
      background: linear-gradient(135deg, #8a2387 0%, #e94057 50%, #f27121 100%);
      --glow-color: rgba(233, 64, 87, 0.6);
    }

    /* Mascot Shapes */
    .shape-circle { border-radius: 9999px !important; }
    .shape-squircle { border-radius: 28% !important; }
    .shape-sparkle { border-radius: 40% 60% 60% 40% / 60% 40% 60% 40% !important; }
    .shape-pill { border-radius: 22px !important; }
    .shape-hexagon { clip-path: polygon(50% 0%, 100% 25%, 100% 75%, 50% 100%, 0% 75%, 0% 25%); }

    /* Click Ripple Animation */
    @keyframes canvas-ripple {
      0% { transform: translate(-50%, -50%) scale(0.2); opacity: 1; }
      100% { transform: translate(-50%, -50%) scale(2.8); opacity: 0; }
    }
    .canvas-ripple-fx {
      position: absolute;
      width: 32px;
      height: 32px;
      border-radius: 9999px;
      border: 2px solid #1a73e8;
      background: rgba(26, 115, 232, 0.25);
      pointer-events: none;
      animation: canvas-ripple 0.6s cubic-bezier(0, 0, 0.2, 1) forwards;
    }

    /* Toast Animations */
    @keyframes toast-slide-in {
      0% { transform: translateY(16px) scale(0.95); opacity: 0; }
      100% { transform: translateY(0) scale(1); opacity: 1; }
    }
    @keyframes toast-slide-out {
      0% { transform: translateY(0) scale(1); opacity: 1; }
      100% { transform: translateY(16px) scale(0.95); opacity: 0; }
    }
    .toast-enter { animation: toast-slide-in 0.25s cubic-bezier(0, 0, 0.2, 1) forwards; }
    .toast-exit { animation: toast-slide-out 0.2s cubic-bezier(0.4, 0, 1, 1) forwards; }

    /* Markdown Rich Styling */
    .markdown-body {
      color: #3c4043;
      font-size: 0.925rem;
      line-height: 1.65;
    }
    .markdown-body p { margin-bottom: 0.75rem; }
    .markdown-body p:last-child { margin-bottom: 0; }
    .markdown-body h1, .markdown-body h2, .markdown-body h3, .markdown-body h4 {
      color: #202124;
      font-weight: 700;
      margin-top: 1rem;
      margin-bottom: 0.5rem;
    }
    .markdown-body h1 { font-size: 1.35rem; border-bottom: 1px solid #e8eaed; padding-bottom: 0.35rem; }
    .markdown-body h2 { font-size: 1.15rem; }
    .markdown-body h3 { font-size: 1.025rem; }
    .markdown-body ul { list-style-type: disc; padding-left: 1.4rem; margin-bottom: 0.75rem; }
    .markdown-body ol { list-style-type: decimal; padding-left: 1.4rem; margin-bottom: 0.75rem; }
    .markdown-body li { margin-bottom: 0.25rem; }
    .markdown-body code:not(pre code) {
      font-family: 'Roboto Mono', monospace;
      font-size: 0.825rem;
      background: #f1f3f4;
      color: #c5221f;
      padding: 0.15rem 0.4rem;
      border-radius: 6px;
      border: 1px solid #e8eaed;
    }
    .markdown-body pre {
      margin: 0.85rem 0;
      border-radius: 14px;
      overflow: hidden;
      background: #1e1e24;
      border: 1px solid #33353a;
    }
    .markdown-body blockquote {
      border-left: 4px solid #1a73e8;
      background: #f8fafd;
      padding: 0.5rem 1rem;
      margin: 0.75rem 0;
      border-radius: 0 8px 8px 0;
      color: #5f6368;
      font-style: italic;
    }
    .markdown-body table {
      width: 100%;
      border-collapse: collapse;
      margin: 0.85rem 0;
      font-size: 0.85rem;
      overflow-x: auto;
      display: block;
      border: 1px solid #dadce0;
      border-radius: 10px;
    }
    .markdown-body th {
      background: #f1f3f4;
      color: #202124;
      font-weight: 600;
      padding: 0.6rem 0.85rem;
      text-align: left;
      border-bottom: 1px solid #dadce0;
    }
    .markdown-body td {
      padding: 0.55rem 0.85rem;
      border-bottom: 1px solid #e8eaed;
    }
    .markdown-body tr:nth-child(even) { background: #f8fafd; }
    .markdown-body a { color: #1a73e8; text-decoration: underline; text-underline-offset: 2px; }
    .markdown-body a:hover { color: #1557b0; }

    /* Scan Line Effect (CRT-style) */
    @keyframes scanline-move {
      0% { top: -5%; }
      100% { top: 105%; }
    }
    .scanline-overlay {
      position: fixed;
      inset: 0;
      pointer-events: none;
      z-index: 9999;
      opacity: 0;
      transition: opacity 0.4s ease;
    }
    .scanline-overlay.active {
      opacity: 1;
    }
    .scanline-overlay.active::before {
      content: '';
      position: absolute;
      left: 0;
      width: 100%;
      height: 3px;
      background: linear-gradient(90deg, transparent, rgba(0,255,65,0.12), transparent);
      animation: scanline-move 4s linear infinite;
    }
    .scanline-overlay.active::after {
      content: '';
      position: absolute;
      inset: 0;
      background: repeating-linear-gradient(
        0deg,
        transparent,
        transparent 2px,
        rgba(0,0,0,0.06) 2px,
        rgba(0,0,0,0.06) 4px
      );
    }

    /* Waveform Indicator */
    #waveform-canvas { border-radius: 8px; }

    /* Topology Map */
    #topology-canvas { border-radius: 12px; background: #0a0e1a; }
    .topo-node { cursor: pointer; transition: all 0.2s; }
    .topo-node:hover { filter: brightness(1.3); }

    /* Stealth Mode */
    body.stealth-mode .sidebar-panel { display: none !important; }
    body.stealth-mode .header-logo-text { opacity: 0; width: 0; overflow: hidden; }
    body.stealth-mode #header-mode-badge,
    body.stealth-mode #header-engine-label { opacity: 0; width: 0; overflow: hidden; padding: 0; margin: 0; border: 0; }
    body.stealth-mode #chat-box { max-width: 100%; }
    body.stealth-mode #user-input { background: rgba(0,0,0,0.6); color: transparent; caret-color: transparent; }
    body.stealth-mode #user-input::placeholder { color: transparent; }
    body.stealth-mode:hover #user-input { background: rgba(0,0,0,0.6); }
    body.stealth-mode #user-input:focus { color: #3c4043; caret-color: #3c4043; }
    body.stealth-mode #user-input:focus::placeholder { color: #5f6368; }
    body.stealth-mode .scanline-overlay { opacity: 0.3 !important; }

    /* Code Block Header Styling */
    .code-container {
      position: relative;
      margin: 0.85rem 0;
      border-radius: 14px;
      overflow: hidden;
      background: #181820;
      border: 1px solid #2e3038;
      box-shadow: 0 2px 6px rgba(0,0,0,0.12);
    }
    .code-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0.45rem 0.85rem;
      background: #20212c;
      border-bottom: 1px solid #2e3038;
      font-family: 'Roboto Mono', monospace;
      font-size: 0.75rem;
      color: #9aa0a6;
    }
  </style>
</head>
<body class="bg-glight text-gtext h-screen flex flex-col antialiased overflow-hidden select-none">

  <!-- Scan Line Effect Overlay -->
  <div id="scanline-overlay" class="scanline-overlay"></div>

  <!-- Toast Notification Floating Container -->
  <div id="toast-container" class="fixed bottom-5 right-5 z-50 flex flex-col space-y-2 pointer-events-none max-w-sm w-full"></div>

  <!-- Command Palette Modal (Ctrl+K / Cmd+K) -->
  <div id="command-palette-modal" class="fixed inset-0 bg-black/45 backdrop-blur-xs z-50 hidden flex items-start justify-center pt-20 p-4 transition-all">
    <div class="bg-white rounded-3xl max-w-xl w-full shadow-m3-3 border border-gborder flex flex-col overflow-hidden animate-in fade-in zoom-in-95 duration-150">
      
      <!-- Search Input Header -->
      <div class="p-4 border-b border-gborder flex items-center space-x-3 bg-gray-50/70">
        <svg class="w-5 h-5 text-gblue shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"></path></svg>
        <input type="text" id="command-input" placeholder="Type a command or search actions (e.g. switch engine, run ducky, browse)..."
               oninput="filterCommands()" onkeydown="handleCommandKey(event)"
               class="flex-1 bg-transparent text-sm text-gdark placeholder-gray-400 focus:outline-none font-medium">
        <span class="text-[10px] font-mono text-gsub bg-white px-2 py-0.5 rounded-md border border-gborder">ESC</span>
      </div>

      <!-- Filtered Action List -->
      <div id="command-results" class="max-h-80 overflow-y-auto p-2 space-y-1 text-xs">
        <!-- Dynamically Populated -->
      </div>

      <!-- Footer Quick Tips -->
      <div class="p-2.5 px-4 bg-gray-50 border-t border-gborderLight flex items-center justify-between text-[11px] text-gsub">
        <div class="flex items-center space-x-3">
          <span><strong class="font-mono text-gdark">↑↓</strong> Navigate</span>
          <span><strong class="font-mono text-gdark">ENTER</strong> Select</span>
          <span><strong class="font-mono text-gdark">ESC</strong> Close</span>
        </div>
        <span class="text-gblue font-medium">a-bot Quick Commander</span>
      </div>

    </div>
  </div>

  <!-- Top Navigation Header -->
  <header class="h-16 bg-gsurface border-b border-gborderLight px-6 flex items-center justify-between shadow-[0_1px_2px_rgba(60,64,67,0.06)] shrink-0 z-20">
    <div class="flex items-center space-x-3.5">
      
      <!-- Header Mascot Icon -->
      <div id="header-bot-preview" onclick="setTab('customizer')" title="Click to customize mascot" class="w-10 h-10 rounded-full flex items-center justify-center shadow-sm transition-all duration-300 palette-google anim-breathe text-white cursor-pointer hover:scale-105 active:scale-95">
        <span class="text-base font-bold tracking-tight">aZ</span>
      </div>
      
      <div>
        <div class="flex items-center space-x-2">
          <span class="font-bold text-lg text-gdark tracking-tight">aZoth-local</span>
          <span class="text-[11px] font-semibold text-purple-700 bg-purple-50 px-2.5 py-0.5 rounded-full border border-purple-200 flex items-center space-x-1">
            <span class="w-1.5 h-1.5 rounded-full bg-purple-600 animate-pulse"></span>
            <span>Grok-Grade Intelligence</span>
          </span>
        </div>
        <p class="text-[11px] text-gsub font-normal">DeepSearch Citations • Live X Scouting • Sandbox Browser • Python REPL</p>
      </div>
    </div>

    <!-- Header Action Bar -->
    <div class="flex items-center space-x-2.5">
      
      <!-- Grok Mode Switcher Shortcut -->
      <button onclick="cycleMode()" id="header-mode-badge" title="Cycle Grok Persona Mode (Regular, Fun, Think, Coder)" class="px-3.5 py-1.5 text-xs font-semibold text-purple-900 bg-purple-50 border border-purple-200 rounded-full hover:bg-purple-100 transition flex items-center space-x-1.5 shadow-2xs">
        <span id="header-mode-icon">⚡</span>
        <span id="header-mode-label">Truth Mode</span>
      </button>

      <!-- Command Palette Trigger Button (Ctrl+K) -->
      <button onclick="openCommandPalette()" title="Open Command Palette (Ctrl+K)" class="px-3.5 py-1.5 text-xs text-gsub hover:text-gdark bg-gray-50 hover:bg-gray-100 border border-gborder rounded-full transition flex items-center space-x-2 shadow-2xs">
        <svg class="w-3.5 h-3.5 text-gsub" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"></path></svg>
        <span class="font-medium">Quick Actions</span>
        <span class="font-mono text-[10px] text-gray-400 bg-white px-1.5 py-0.5 rounded border border-gborder">⌘K</span>
      </button>

      <!-- Active Engine Switcher Shortcut -->
      <button onclick="setTab('engines')" title="Switch AI Agent Engine" class="px-3.5 py-1.5 text-xs font-semibold text-gdark bg-gray-50 border border-gborder rounded-full hover:bg-blue-50 hover:border-gblue transition flex items-center space-x-2 shadow-2xs">
        <span id="header-engine-icon" class="text-sm">🦙</span>
        <span id="header-engine-label">Ollama</span>
        <svg class="w-3 h-3 text-gsub" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"></path></svg>
      </button>

      <!-- DuckyScript Studio Tab Shortcut -->
      <button onclick="setTab('ducky')" title="Open DuckyScript Automation Studio" class="px-3.5 py-1.5 text-xs font-semibold text-amber-900 bg-amber-50 border border-amber-200 rounded-full hover:bg-amber-100 transition flex items-center space-x-1.5 shadow-2xs">
        <span>🦆</span>
        <span>Ducky Studio</span>
      </button>

      <!-- Live Interactive Browser Shortcut -->
      <button onclick="setTab('browser')" title="Open Interactive Browser Sandbox" class="px-3.5 py-1.5 text-xs font-semibold text-gblue bg-blue-50 border border-blue-200 rounded-full hover:bg-blue-100 transition flex items-center space-x-2 shadow-2xs">
        <span class="w-2 h-2 rounded-full bg-gblue animate-ping"></span>
        <span>Live Browser</span>
      </button>

      <!-- OS Terminal / Virtual Environment Shortcut -->
      <button onclick="setTab('terminal')" title="Open Isolated Linux Guest OS & Web Terminal" class="px-3.5 py-1.5 text-xs font-semibold text-cyan-900 bg-cyan-50 border border-cyan-200 rounded-full hover:bg-cyan-100 transition flex items-center space-x-1.5 shadow-2xs">
        <span class="w-2 h-2 rounded-full bg-cyan-500 animate-pulse"></span>
        <span>OS Terminal</span>
      </button>

      <!-- Waveform Indicator -->
      <button onclick="toggleWaveform()" id="waveform-btn" title="Toggle Waveform Indicator (Ctrl+W)" class="p-1.5 px-2.5 bg-gray-50 hover:bg-gray-100 border border-gborder rounded-full transition flex items-center space-x-1 shadow-2xs">
        <svg class="w-3.5 h-3.5 text-gsub" viewBox="0 0 40 16" fill="none"><rect id="waveform-bars" x="0" y="0" width="40" height="16" rx="8" fill="none" stroke="#5f6368" stroke-width="1"/><polyline id="waveform-line" points="0,8 10,4 20,12 30,2 40,8" fill="none" stroke="#1a73e8" stroke-width="1.5"/></svg>
        <span class="text-[10px] font-mono text-gsub">WAVE</span>
      </button>

      <!-- Stealth Mode Toggle -->
      <button onclick="toggleStealthMode()" id="stealth-btn" title="Toggle Stealth Mode (Ctrl+S)" class="p-1.5 px-2.5 bg-gray-50 hover:bg-gray-100 border border-gborder rounded-full transition flex items-center space-x-1 shadow-2xs">
        <svg class="w-3.5 h-3.5 text-gsub" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.878 9.878L6.64 6.64m3.238 3.238l-3.24-3.24m7.425 7.425l3.24 3.24M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
        <span class="text-[10px] font-mono text-gsub">STEALTH</span>
      </button>

      <!-- Scan Line Toggle -->
      <button onclick="toggleScanline()" id="scanline-btn" title="Toggle Scan Line Effect (Ctrl+L)" class="p-1.5 px-2.5 bg-gray-50 hover:bg-gray-100 border border-gborder rounded-full transition flex items-center space-x-1 shadow-2xs">
        <svg class="w-3.5 h-3.5 text-gsub" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h16"></path></svg>
        <span class="text-[10px] font-mono text-gsub">SCAN</span>
      </button>

      <!-- Clear Chat Action -->
      <button onclick="clearChat()" title="Reset Chat Conversation" class="p-2 text-gsub hover:text-gred hover:bg-red-50 rounded-full transition">
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg>
      </button>

    </div>
  </header>

  <!-- Main Work Area Split -->
  <div class="flex-1 flex overflow-hidden relative">

    <!-- Left: AI Chat & Reasoning Canvas -->
    <main class="flex-1 flex flex-col bg-glight relative overflow-hidden">
      
      <!-- Chat Stream Area -->
      <div id="chat-box" class="flex-1 p-6 md:p-8 overflow-y-auto space-y-6 max-w-4xl w-full mx-auto">
        
        <!-- Welcome Hero Banner Card -->
        <div class="bg-white rounded-3xl p-6 border border-gborder shadow-sm flex items-start space-x-5 transition hover:shadow-m3-1">
          <div id="hero-bot-avatar" onclick="setTab('customizer')" title="Click to customize aZoth" class="w-16 h-16 rounded-3xl flex items-center justify-center shadow-md transition-all duration-300 palette-google anim-breathe text-white shrink-0 cursor-pointer">
            <span class="text-2xl font-bold">aZ</span>
          </div>
          <div class="space-y-2 flex-1">
            <div class="flex items-center justify-between">
              <h2 class="text-lg font-bold text-gdark flex items-center space-x-2">
                <span>Welcome Neal, I'm <span class="bg-clip-text text-transparent bg-gradient-to-r from-purple-600 via-blue-600 to-cyan-500 font-extrabold">aZoth-local</span></span>
                <span class="text-xs text-gsub font-normal">• Grok-Grade Autonomous Agent</span>
              </h2>
              <span class="text-[11px] bg-green-50 text-ggreen font-semibold px-2.5 py-1 rounded-full border border-green-200 flex items-center space-x-1.5">
                <span class="w-1.5 h-1.5 rounded-full bg-ggreen"></span>
                <span>Chrome Sandboxed Ready</span>
              </span>
            </div>
            <p class="text-sm text-gsub leading-relaxed">
              Engineered with Grok-grade intelligence: live X (Twitter) scouting, multi-source DeepSearch with verifiable citations, sandbox Python execution, and persistent headed browser automation ("VM-ish vibes").
            </p>
            
            <!-- Grok Sparks Suggestion Chips -->
            <div class="pt-2 flex flex-wrap gap-2">
              <button onclick="triggerSpark('Search live tech discussions and breaking trends on X today')" class="text-xs bg-purple-50 hover:bg-purple-100 text-purple-900 font-medium px-3.5 py-1.5 rounded-full border border-purple-200 transition flex items-center space-x-1.5 shadow-2xs">
                <span>🔥</span><span>Trending on X</span>
              </button>
              <button onclick="triggerSpark('DeepSearch the latest AI agent frameworks and breakthroughs this month')" class="text-xs bg-cyan-50 hover:bg-cyan-100 text-cyan-900 font-medium px-3.5 py-1.5 rounded-full border border-cyan-200 transition flex items-center space-x-1.5 shadow-2xs">
                <span>🔬</span><span>DeepSearch AI News</span>
              </button>
              <button onclick="triggerSpark('Run a Python benchmark in the sandbox workspace to test execution speed and file creation')" class="text-xs bg-emerald-50 hover:bg-emerald-100 text-emerald-900 font-medium px-3.5 py-1.5 rounded-full border border-emerald-200 transition flex items-center space-x-1.5 shadow-2xs">
                <span>🐍</span><span>Python Sandbox</span>
              </button>
              <button onclick="triggerSpark('Search X for recent posts from @elonmusk about xAI Grok')" class="text-xs bg-blue-50 hover:bg-blue-100 text-blue-900 font-medium px-3.5 py-1.5 rounded-full border border-blue-200 transition flex items-center space-x-1.5 shadow-2xs">
                <span>🐦</span><span>Scout Elon on X</span>
              </button>
              <button onclick="runPresetDucky('x_post')" class="text-xs bg-amber-50 hover:bg-amber-100 text-amber-900 font-medium px-3.5 py-1.5 rounded-full border border-amber-200 transition flex items-center space-x-1.5 shadow-2xs">
                <span>🦆</span><span>Ducky Post to X</span>
              </button>
            </div>
          </div>
        </div>

      </div>

      <!-- Bottom Floating Chat Input Capsule -->
      <div class="p-4 md:p-6 bg-transparent max-w-4xl w-full mx-auto shrink-0">
        
        <!-- Grok Mode Selector Bar & Quick Tool Chips -->
        <div class="flex items-center justify-between px-3 pb-2 text-xs">
          <div class="flex items-center space-x-1 bg-white/90 backdrop-blur-md p-1 rounded-full border border-gborder shadow-2xs">
            <span class="text-[10px] font-bold text-gsub uppercase tracking-wider px-2">Mode:</span>
            <button type="button" onclick="setMode('regular')" id="mode-btn-regular" class="mode-btn px-2.5 py-1 rounded-full font-medium transition text-gdark hover:bg-gray-100 flex items-center space-x-1">
              <span>⚡</span><span>Truth</span>
            </button>
            <button type="button" onclick="setMode('fun')" id="mode-btn-fun" class="mode-btn px-2.5 py-1 rounded-full font-medium transition text-gdark hover:bg-gray-100 flex items-center space-x-1">
              <span>🌶️</span><span>Fun</span>
            </button>
            <button type="button" onclick="setMode('think')" id="mode-btn-think" class="mode-btn px-2.5 py-1 rounded-full font-medium transition text-gdark hover:bg-gray-100 flex items-center space-x-1">
              <span>🧠</span><span>Think</span>
            </button>
            <button type="button" onclick="setMode('coder')" id="mode-btn-coder" class="mode-btn px-2.5 py-1 rounded-full font-medium transition text-gdark hover:bg-gray-100 flex items-center space-x-1">
              <span>💻</span><span>Coder</span>
            </button>
          </div>
          <div class="flex items-center space-x-2">
            <button type="button" onclick="promptDeepSearch()" title="Exhaustive multi-source search with citations" class="text-xs bg-cyan-50 hover:bg-cyan-100 text-cyan-900 border border-cyan-200 px-3 py-1 rounded-full font-medium transition flex items-center space-x-1 shadow-2xs">
              <span>🔬</span><span>DeepSearch</span>
            </button>
            <button type="button" onclick="promptXScout()" title="Search live posts and handles on X" class="text-xs bg-blue-50 hover:bg-blue-100 text-blue-900 border border-blue-200 px-3 py-1 rounded-full font-medium transition flex items-center space-x-1 shadow-2xs">
              <span>🐦</span><span>X Scout</span>
            </button>
          </div>
        </div>

        <form id="chat-form" onsubmit="sendMessage(event)" class="bg-white rounded-full shadow-[0_2px_10px_rgba(60,64,67,0.1)] border border-gborder p-2 pl-6 flex items-center space-x-3 focus-within:shadow-m3-2 focus-within:border-gblue transition-all duration-200">
          <input type="text" id="user-input" placeholder="Ask aZoth to DeepSearch, scout X/Twitter, execute Python code, run DuckyScript, browse live, or code..." 
                 onkeydown="handleChatInputKey(event)"
                 class="flex-1 bg-transparent text-sm text-gdark placeholder-gray-400 focus:outline-none py-2 font-medium">
          
          <button type="button" onclick="openCommandPalette()" title="Commands (⌘K)" class="p-2 text-gsub hover:text-gblue hover:bg-blue-50 rounded-full transition">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"></path></svg>
          </button>

          <button type="button" onclick="setTab('browser')" title="Open Interactive Browser" class="p-2 text-gsub hover:text-gblue hover:bg-blue-50 rounded-full transition">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 01-9 9m9-9a9 9 0 00-9-9m9 9H3m9 9a9 9 0 01-9-9m9 9c1.657 0 3-4.03 3-9s-1.343-9-3-9m0 18c-1.657 0-3-4.03-3-9s1.343-9 3-9m-9 9a9 9 0 019-9"></path></svg>
          </button>

          <button type="submit" id="send-btn" title="Send (Ctrl+Enter)" class="w-10 h-10 rounded-full bg-gblue hover:bg-gblueHover text-white flex items-center justify-center shadow-md transition disabled:opacity-50 shrink-0 active:scale-95">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14 5l7 7m0 0l-7 7m7-7H3"></path></svg>
          </button>
        </form>
      </div>

    </main>

    <!-- Right: Multi-Tool Inspector Sidebar -->
    <aside class="w-[520px] bg-white border-l border-gborder flex flex-col shadow-sm select-text">
      
      <!-- Tab Navigation Header -->
      <div class="flex border-b border-gborder bg-gray-50/70 text-xs font-semibold shrink-0">
        <button onclick="setTab('browser')" id="tab-btn-browser" class="flex-1 py-3 text-gblue border-b-2 border-gblue bg-white font-bold flex items-center justify-center space-x-1 transition">
          <span>🌐</span><span>Browser</span>
        </button>
        <button onclick="setTab('terminal')" id="tab-btn-terminal" class="flex-1 py-3 text-gsub hover:text-gdark border-b-2 border-transparent flex items-center justify-center space-x-1 transition">
          <span>💻</span><span>OS Env</span>
        </button>
        <button onclick="setTab('ducky')" id="tab-btn-ducky" class="flex-1 py-3 text-gsub hover:text-gdark border-b-2 border-transparent flex items-center justify-center space-x-1 transition">
          <span>🦆</span><span>Ducky</span>
        </button>
        <button onclick="setTab('engines')" id="tab-btn-engines" class="flex-1 py-3 text-gsub hover:text-gdark border-b-2 border-transparent flex items-center justify-center space-x-1 transition">
          <span>⚡</span><span>Engines</span>
        </button>
        <button onclick="setTab('workspace')" id="tab-btn-workspace" class="flex-1 py-3 text-gsub hover:text-gdark border-b-2 border-transparent flex items-center justify-center space-x-1 transition">
          <span>📁</span><span>Files</span>
        </button>
        <button onclick="setTab('customizer')" id="tab-btn-customizer" class="flex-1 py-3 text-gsub hover:text-gdark border-b-2 border-transparent flex items-center justify-center space-x-1 transition">
          <span>🎨</span><span>Studio</span>
        </button>
        <button onclick="setTab('topology')" id="tab-btn-topology" class="flex-1 py-3 text-gsub hover:text-gdark border-b-2 border-transparent flex items-center justify-center space-x-1 transition">
          <span>🌐</span><span>Topo</span>
        </button>
      </div>

      <!-- Tab Content Area -->
      <div class="flex-1 p-4 overflow-y-auto space-y-3 flex flex-col">
        
        <!-- 1. INTERACTIVE LIVE BROWSER TAB -->
        <div id="tab-browser" class="space-y-3 flex-1 flex flex-col">
          
          <!-- Browser Tab Strip -->
          <div class="flex items-center space-x-1 bg-gray-100 p-1 rounded-2xl border border-gborderLight overflow-x-auto text-xs shrink-0">
            <div id="browser-tabs-bar" class="flex items-center space-x-1 flex-1 overflow-x-auto"></div>
            <button onclick="browserNewTabPrompt()" title="Open New Tab" class="p-1 px-2.5 text-gsub hover:text-gdark hover:bg-white rounded-xl transition font-bold shadow-2xs">+</button>
          </div>

          <!-- Browser Address & Controls Bar -->
          <div class="flex items-center space-x-1.5 shrink-0">
            <input type="text" id="browser-url-input" placeholder="https://x.com" 
                   onkeydown="if(event.key==='Enter') browserGo()"
                   class="flex-1 bg-gray-50 border border-gborder rounded-xl px-3 py-1.5 text-xs font-mono text-gdark focus:outline-none focus:border-gblue">
            <button onclick="browserGo()" class="px-3 py-1.5 bg-gblue text-white text-xs font-bold rounded-xl hover:bg-gblueHover transition shadow-2xs">Go</button>
            <button onclick="refreshLiveBrowser()" title="Refresh Frame" class="p-1.5 px-2 bg-gray-100 hover:bg-gray-200 text-gtext rounded-xl transition text-xs">🔄</button>
          </div>

          <!-- Quick Bookmark Pills & Canvas View Controls -->
          <div class="flex items-center justify-between text-[11px] shrink-0">
            <div class="flex flex-wrap gap-1">
              <button onclick="browserNav('https://x.com')" class="px-2 py-0.5 bg-gray-50 hover:bg-gray-100 border border-gborder rounded-md text-gsub transition">X.com</button>
              <button onclick="browserNav('https://google.com')" class="px-2 py-0.5 bg-gray-50 hover:bg-gray-100 border border-gborder rounded-md text-gsub transition">Google</button>
              <button onclick="browserNav('https://github.com')" class="px-2 py-0.5 bg-gray-50 hover:bg-gray-100 border border-gborder rounded-md text-gsub transition">GitHub</button>
              <button onclick="browserNav('https://youtube.com')" class="px-2 py-0.5 bg-gray-50 hover:bg-gray-100 border border-gborder rounded-md text-gsub transition">YouTube</button>
            </div>

            <!-- Viewport Zoom Controls & Coordinate Readout -->
            <div class="flex items-center space-x-1.5 bg-gray-100 px-2 py-0.5 rounded-lg border border-gborder text-gsub font-mono text-[10px]">
              <span id="canvas-coord-readout">X: — Y: —</span>
              <span class="text-gray-300">|</span>
              <button onclick="adjustCanvasZoom(-0.15)" title="Zoom Out" class="hover:text-gdark font-bold px-1">−</button>
              <span id="canvas-zoom-badge">100%</span>
              <button onclick="adjustCanvasZoom(0.15)" title="Zoom In" class="hover:text-gdark font-bold px-1">+</button>
              <button onclick="resetCanvasZoom()" title="Reset Zoom" class="hover:text-gblue text-[9px] px-1 font-semibold">1:1</button>
            </div>
          </div>

          <!-- CAPTCHA / Challenge Banner Alert -->
          <div id="captcha-banner" class="hidden p-2.5 bg-red-50 border border-red-200 rounded-xl text-xs text-gred font-semibold flex items-center justify-between shrink-0">
            <span id="captcha-msg">🚨 Challenge detected! Click directly in canvas below to solve.</span>
          </div>

          <!-- Auth & Login Assistant Bar -->
          <div class="bg-gray-50 border border-gborder rounded-xl px-3 py-2 flex flex-wrap items-center justify-between gap-2 text-xs shrink-0">
            <div class="flex items-center space-x-2">
              <span class="font-semibold text-gdark flex items-center space-x-1">
                <span>🔐</span>
                <span>Session State:</span>
              </span>
              <span id="browser-auth-badge" class="px-2 py-0.5 rounded-full text-[11px] font-semibold bg-gray-200 text-gray-700">
                ⚪ Unchecked
              </span>
              <span id="browser-auth-user" class="text-[11px] text-gsub hidden truncate max-w-[150px]"></span>
            </div>
            
            <div class="flex items-center space-x-1.5">
              <button onclick="checkBrowserAuth()" id="btn-check-auth" class="px-2.5 py-1 bg-white hover:bg-gray-100 border border-gborder text-gdark font-medium rounded-lg text-[11px] transition shadow-2xs flex items-center space-x-1">
                <span>🔍</span>
                <span>Check Auth</span>
              </button>
              <button onclick="openSmartLoginModal()" class="px-2.5 py-1 bg-gblue hover:bg-blue-600 text-white font-medium rounded-lg text-[11px] transition shadow-2xs flex items-center space-x-1">
                <span>🔑</span>
                <span>Smart Login</span>
              </button>
              <button onclick="triggerBrowserTakeover()" class="px-2.5 py-1 bg-white hover:bg-gray-100 border border-gborder text-amber-700 font-medium rounded-lg text-[11px] transition shadow-2xs flex items-center space-x-1" title="Open visible host window to manually solve 2FA/CAPTCHA">
                <span>🖥️</span>
                <span>Takeover / 2FA</span>
              </button>
              <button onclick="exportBrowserSession()" class="px-2.5 py-1 bg-white hover:bg-gray-100 border border-gborder text-gsub hover:text-gdark font-medium rounded-lg text-[11px] transition shadow-2xs" title="Export session cookies to persistent storage">
                💾 Save Cookies
              </button>
            </div>
          </div>

          <!-- INTERACTIVE BROWSER CANVAS VIEWPORT -->
          <div class="relative border border-gborder rounded-2xl overflow-hidden bg-gray-950 shadow-inner flex-1 min-h-[300px] flex items-center justify-center cursor-crosshair group select-none"
               id="browser-viewport-container"
               onmousemove="trackCanvasCoords(event)"
               onmouseleave="clearCanvasCoords()">
            
            <div id="browser-zoom-wrapper" class="w-full h-full flex items-center justify-center transition-transform duration-100 origin-center">
              <img id="browser-live-img" src="" alt="Browser Canvas" 
                   class="w-full h-full object-contain hidden pointer-events-auto"
                   onclick="handleCanvasClick(event)"
                   onwheel="handleCanvasWheel(event)">
            </div>
            
            <div id="browser-loading-placeholder" class="text-center p-6 text-gray-400 text-xs">
              <div class="w-8 h-8 mx-auto border-2 border-gblue border-t-transparent rounded-full animate-spin mb-2"></div>
              <span class="font-medium">Connecting to Sandboxed Chrome...</span>
            </div>

            <!-- Coordinate Ripple Layer -->
            <div id="canvas-ripple-layer" class="absolute inset-0 pointer-events-none overflow-hidden"></div>
          </div>

          <!-- Live Keyboard Relay Input -->
          <div class="bg-gray-50 p-3 rounded-2xl border border-gborder space-y-2 shrink-0">
            <div class="flex items-center justify-between text-[11px] font-semibold text-gdark">
              <span class="flex items-center space-x-1">
                <span>⌨️</span><span>Type Directly Into Active Page:</span>
              </span>
              <span class="text-gsub text-[10px]">Relays Enter, Tab, Esc & Text</span>
            </div>
            <div class="flex space-x-1.5">
              <input type="text" id="browser-type-input" placeholder="Type here and press Enter to send to page..." 
                     onkeydown="handleDirectKey(event)"
                     class="flex-1 bg-white border border-gborder rounded-xl px-3 py-2 text-xs text-gdark focus:outline-none focus:border-gblue">
              <button onclick="sendTypedText()" class="px-3.5 py-2 bg-gray-200 hover:bg-gray-300 text-gdark text-xs font-semibold rounded-xl transition shadow-2xs">Send</button>
            </div>
          </div>

        </div>

        <!-- 2. DUCKY SCRIPT STUDIO TAB -->
        <div id="tab-ducky" class="hidden space-y-3 flex-1 flex flex-col">
          <div class="flex items-center justify-between shrink-0">
            <div class="flex items-center space-x-1.5">
              <span class="text-lg">🦆</span>
              <h3 class="text-xs font-bold uppercase tracking-wider text-gdark">DuckyScript Studio</h3>
            </div>
            <select id="ducky-preset-select" onchange="loadSelectedPreset()" class="text-xs bg-gray-50 border border-gborder rounded-lg px-2.5 py-1 text-gdark font-medium focus:outline-none focus:border-gblue">
              <option value="">Load Preset Payload...</option>
            </select>
          </div>

          <!-- Preset Description Tag -->
          <div id="ducky-preset-desc" class="text-[11px] text-gsub bg-amber-50/70 border border-amber-100 rounded-xl p-2 font-normal hidden shrink-0">
          </div>

          <!-- Quick Syntax Insert Chips -->
          <div class="flex flex-wrap gap-1 text-[10px] font-mono shrink-0">
            <button onclick="insertDuckySnippet('NAVIGATE https://x.com')" class="px-2 py-0.5 bg-gray-100 hover:bg-gray-200 rounded border border-gborder text-gdark">+ NAVIGATE</button>
            <button onclick="insertDuckySnippet('DELAY 1500')" class="px-2 py-0.5 bg-gray-100 hover:bg-gray-200 rounded border border-gborder text-gdark">+ DELAY</button>
            <button onclick="insertDuckySnippet('STRING Hello World!')" class="px-2 py-0.5 bg-gray-100 hover:bg-gray-200 rounded border border-gborder text-gdark">+ STRING</button>
            <button onclick="insertDuckySnippet('CTRL+ENTER')" class="px-2 py-0.5 bg-amber-100 hover:bg-amber-200 rounded border border-amber-300 text-amber-900 font-bold">+ CTRL+ENTER</button>
            <button onclick="insertDuckySnippet('ENTER')" class="px-2 py-0.5 bg-gray-100 hover:bg-gray-200 rounded border border-gborder text-gdark">+ ENTER</button>
            <button onclick="insertDuckySnippet('SCROLL 400')" class="px-2 py-0.5 bg-gray-100 hover:bg-gray-200 rounded border border-gborder text-gdark">+ SCROLL</button>
          </div>

          <!-- DuckyScript Code Editor -->
          <textarea id="ducky-editor" rows="9" 
                    placeholder="NAVIGATE https://x.com/compose/post&#10;DELAY 3500&#10;STRING Hello from DuckyScript! 🦆&#10;CTRL+ENTER" 
                    onkeydown="handleDuckyEditorKey(event)"
                    class="w-full flex-1 bg-gray-950 text-emerald-400 font-mono text-xs p-3.5 rounded-2xl border border-gborder focus:outline-none focus:border-gblue leading-relaxed resize-none shadow-inner"></textarea>

          <!-- Execution Controls -->
          <div class="flex items-center justify-between pt-1 shrink-0">
            <div class="flex items-center space-x-2 text-xs">
              <label class="text-gsub font-semibold">Target:</label>
              <select id="ducky-target" class="bg-gray-50 border border-gborder rounded-lg px-2.5 py-1 text-xs font-medium">
                <option value="browser">Sandboxed Chrome (Zero-Detection)</option>
                <option value="os">Native Desktop (X11)</option>
              </select>
            </div>

            <div class="flex items-center space-x-2">
              <button onclick="clearDuckyLogs()" title="Clear Console" class="px-3 py-2 bg-gray-100 hover:bg-gray-200 text-gsub rounded-xl text-xs transition">Clear</button>
              <button onclick="runDuckyScript()" id="ducky-run-btn" class="px-5 py-2 bg-amber-500 hover:bg-amber-600 active:scale-95 text-white font-bold rounded-xl text-xs shadow-md transition flex items-center space-x-1.5">
                <span>▶ Run Payload (Ctrl+Enter)</span>
              </button>
            </div>
          </div>

          <!-- Execution Step-by-Step Live Log Console -->
          <div class="space-y-1.5 shrink-0">
            <div class="flex items-center justify-between text-[11px] font-semibold text-gdark">
              <span>Live Execution Log:</span>
              <span id="ducky-step-counter" class="text-gsub text-[10px]">0 steps</span>
            </div>
            <div id="ducky-output-console" class="p-3 bg-gray-900 rounded-xl border border-gborder text-[11px] font-mono text-gray-300 max-h-36 overflow-y-auto space-y-1 shadow-inner">
              <div class="text-gray-500 italic">Payload output & step timeline will stream here.</div>
            </div>
          </div>
        </div>

        <!-- 3. ENGINES ROUTER TAB -->
        <div id="tab-engines" class="hidden space-y-3 flex-1 flex flex-col">
          <div class="flex items-center justify-between">
            <h3 class="text-xs font-bold uppercase tracking-wider text-gsub">Select AI Engine / Agent CLI</h3>
            <div class="flex items-center space-x-2">
              <button onclick="openConfigModal()" class="text-[11px] text-gblue font-semibold hover:underline bg-blue-50 border border-blue-200 px-2 py-0.5 rounded-lg flex items-center space-x-1"><span>🔑</span><span>API Keys & .env</span></button>
              <span class="text-[11px] text-gsub cursor-pointer font-semibold hover:underline" onclick="loadEngines()">Refresh</span>
            </div>
          </div>
          <div id="engines-list" class="space-y-2.5 text-xs flex-1 overflow-y-auto">
            <div class="text-gray-400 italic p-3 text-center">Scanning installed engines...</div>
          </div>
        </div>

        <!-- 4. WORKSPACE FILE MANAGER TAB -->
        <div id="tab-workspace" class="hidden space-y-3 flex-1 flex flex-col">
          <div class="flex items-center justify-between">
            <h3 class="text-xs font-bold uppercase tracking-wider text-gsub">Sandbox Workspace Directory</h3>
            <div class="flex items-center space-x-2">
              <button onclick="promptCreateFile()" class="text-xs text-gblue font-bold hover:underline">+ New File</button>
              <button onclick="loadWorkspace()" class="text-xs text-gsub hover:text-gdark">Refresh</button>
            </div>
          </div>
          <div id="workspace-file-list" class="space-y-2 text-xs font-mono flex-1 overflow-y-auto">
            <div class="text-gray-400 italic p-3 text-center">Loading files...</div>
          </div>
        </div>

        <!-- 5. MASCOT STUDIO TAB -->
        <div id="tab-customizer" class="hidden space-y-4 flex-1 flex flex-col overflow-y-auto">
          
          <!-- Mascot Hero Stage with Ambient Particle Canvas -->
          <div class="relative text-center p-6 bg-radial from-blue-50/60 to-gray-50 rounded-3xl border border-gborder overflow-hidden group">
            <canvas id="mascot-particles" class="absolute inset-0 pointer-events-none w-full h-full"></canvas>
            
            <div id="studio-bot-preview" onclick="burstMascotParticles()" title="Click for particle spark!" class="relative z-10 w-24 h-24 mx-auto rounded-full flex items-center justify-center shadow-m3-2 transition-all duration-300 palette-google anim-breathe text-white mb-3 cursor-pointer hover:scale-105 active:scale-95">
              <span class="text-4xl font-bold">a</span>
            </div>
            
            <h4 class="font-bold text-gdark text-base">a-bot Mascot Studio</h4>
            <p class="text-xs text-gsub mt-0.5">Customize personality, geometry & radiant aura</p>
          </div>

          <!-- Mascot Shape Selector -->
          <div class="space-y-2">
            <label class="text-xs font-bold text-gdark uppercase tracking-wider">Mascot Shape Geometry</label>
            <div class="grid grid-cols-2 gap-2 text-xs">
              <button onclick="setBotShape('circle')" class="p-2.5 rounded-xl border border-gborder hover:border-gblue text-left font-medium bg-white transition flex items-center space-x-2 shadow-2xs">
                <span class="w-4 h-4 rounded-full bg-gblue inline-block"></span>
                <span>Sphere Orb</span>
              </button>
              <button onclick="setBotShape('squircle')" class="p-2.5 rounded-xl border border-gborder hover:border-gblue text-left font-medium bg-white transition flex items-center space-x-2 shadow-2xs">
                <span class="w-4 h-4 rounded-lg bg-gblue inline-block"></span>
                <span>Squircle</span>
              </button>
              <button onclick="setBotShape('sparkle')" class="p-2.5 rounded-xl border border-gborder hover:border-gblue text-left font-medium bg-white transition flex items-center space-x-2 shadow-2xs">
                <span class="text-gblue font-bold">✦</span>
                <span>Gemini Star</span>
              </button>
              <button onclick="setBotShape('pill')" class="p-2.5 rounded-xl border border-gborder hover:border-gblue text-left font-medium bg-white transition flex items-center space-x-2 shadow-2xs">
                <span class="w-5 h-3 rounded-full bg-gblue inline-block"></span>
                <span>Capsule Pill</span>
              </button>
            </div>
          </div>

          <!-- Animation Styles -->
          <div class="space-y-2">
            <label class="text-xs font-bold text-gdark uppercase tracking-wider">Organic Motion Style</label>
            <div class="grid grid-cols-2 gap-2 text-xs">
              <button onclick="setBotAnim('anim-breathe')" class="p-2.5 rounded-xl border border-gborder hover:border-gblue text-left font-medium bg-white transition shadow-2xs">
                🌿 Float Breathe
              </button>
              <button onclick="setBotAnim('anim-pulse')" class="p-2.5 rounded-xl border border-gborder hover:border-gblue text-left font-medium bg-white transition shadow-2xs">
                ⚡ Radiant Pulse
              </button>
              <button onclick="setBotAnim('anim-bounce')" class="p-2.5 rounded-xl border border-gborder hover:border-gblue text-left font-medium bg-white transition shadow-2xs">
                🎈 Playful Bounce
              </button>
              <button onclick="setBotAnim('anim-wave')" class="p-2.5 rounded-xl border border-gborder hover:border-gblue text-left font-medium bg-white transition shadow-2xs">
                🌊 Liquid Wave
              </button>
              <button onclick="setBotAnim('anim-gyro')" class="p-2.5 rounded-xl border border-gborder hover:border-gblue text-left font-medium bg-white transition shadow-2xs">
                🌀 Quantum Gyro
              </button>
              <button onclick="setBotAnim('anim-sparkle')" class="p-2.5 rounded-xl border border-gborder hover:border-gblue text-left font-medium bg-white transition shadow-2xs">
                ✨ Hyper Sparkle
              </button>
            </div>
          </div>

          <!-- Radiant Color Palettes -->
          <div class="space-y-2">
            <label class="text-xs font-bold text-gdark uppercase tracking-wider">Radiant Aura Palette</label>
            <div class="grid grid-cols-2 gap-2 text-xs">
              <button onclick="setBotPalette('palette-google')" class="p-2.5 rounded-xl border border-gborder hover:border-gblue text-left font-medium bg-white transition flex items-center space-x-2.5 shadow-2xs">
                <div class="w-5 h-5 rounded-full palette-google shadow-2xs shrink-0"></div>
                <span class="truncate">Google Spectrum</span>
              </button>
              <button onclick="setBotPalette('palette-gemini')" class="p-2.5 rounded-xl border border-gborder hover:border-gblue text-left font-medium bg-white transition flex items-center space-x-2.5 shadow-2xs">
                <div class="w-5 h-5 rounded-full palette-gemini shadow-2xs shrink-0"></div>
                <span class="truncate">Gemini Aurora</span>
              </button>
              <button onclick="setBotPalette('palette-ocean')" class="p-2.5 rounded-xl border border-gborder hover:border-gblue text-left font-medium bg-white transition flex items-center space-x-2.5 shadow-2xs">
                <div class="w-5 h-5 rounded-full palette-ocean shadow-2xs shrink-0"></div>
                <span class="truncate">Deep Ocean</span>
              </button>
              <button onclick="setBotPalette('palette-emerald')" class="p-2.5 rounded-xl border border-gborder hover:border-gblue text-left font-medium bg-white transition flex items-center space-x-2.5 shadow-2xs">
                <div class="w-5 h-5 rounded-full palette-emerald shadow-2xs shrink-0"></div>
                <span class="truncate">Emerald Cyber</span>
              </button>
              <button onclick="setBotPalette('palette-solar')" class="p-2.5 rounded-xl border border-gborder hover:border-gblue text-left font-medium bg-white transition flex items-center space-x-2.5 shadow-2xs">
                <div class="w-5 h-5 rounded-full palette-solar shadow-2xs shrink-0"></div>
                <span class="truncate">Solar Flare</span>
              </button>
              <button onclick="setBotPalette('palette-nebula')" class="p-2.5 rounded-xl border border-gborder hover:border-gblue text-left font-medium bg-white transition flex items-center space-x-2.5 shadow-2xs">
                <div class="w-5 h-5 rounded-full palette-nebula shadow-2xs shrink-0"></div>
                <span class="truncate">Cosmic Nebula</span>
              </button>
            </div>
          </div>

        </div>

        <!-- 6. OS SANDBOX & WEB TERMINAL TAB -->
        <div id="tab-terminal" class="hidden space-y-3 flex-1 flex flex-col overflow-hidden">
          
          <!-- OS Vitals & Status Card -->
          <div class="p-3.5 bg-gray-900 text-white rounded-2xl border border-gray-800 space-y-2.5 shadow-xs shrink-0">
            <div class="flex items-center justify-between text-xs">
              <div class="flex items-center space-x-2">
                <span id="terminal-status-dot" class="w-2.5 h-2.5 rounded-full bg-emerald-400 animate-pulse"></span>
                <span id="terminal-status-text" class="font-bold text-gray-200">Guest OS: Running</span>
                <span id="terminal-backend-badge" class="px-2 py-0.5 text-[10px] bg-cyan-950 text-cyan-300 rounded border border-cyan-800 font-mono font-bold">DOCKER</span>
              </div>
              <div class="flex items-center space-x-1.5">
                <button onclick="restartGuestOS()" title="Restart Guest OS Environment" class="px-2.5 py-1 text-[11px] bg-gray-800 hover:bg-gray-700 text-gray-300 rounded-lg transition border border-gray-700 flex items-center space-x-1">
                  <span>🔄</span><span>Restart</span>
                </button>
                <button onclick="reconnectTerminal()" title="Reconnect Interactive Web Terminal" class="px-2.5 py-1 text-[11px] bg-cyan-950 hover:bg-cyan-900 text-cyan-200 rounded-lg transition border border-cyan-700 flex items-center space-x-1 font-semibold">
                  <span>⚡</span><span>Reconnect</span>
                </button>
              </div>
            </div>

            <!-- Vitals Row -->
            <div class="grid grid-cols-3 gap-2 text-[11px] font-mono text-gray-300 pt-1.5 border-t border-gray-800">
              <div>
                <span class="text-gray-500 block text-[9px] uppercase tracking-wider">Distro</span>
                <span id="terminal-distro" class="text-white font-medium truncate block">Debian 12 Bookworm</span>
              </div>
              <div>
                <span class="text-gray-500 block text-[9px] uppercase tracking-wider">RAM Usage</span>
                <span id="terminal-memory" class="text-emerald-400 font-medium truncate block">Active</span>
              </div>
              <div>
                <span class="text-gray-500 block text-[9px] uppercase tracking-wider">Workspace</span>
                <span id="terminal-disk" class="text-cyan-400 font-medium truncate block">/workspace</span>
              </div>
            </div>
          </div>

          <!-- Quick Actions & Command Chips -->
          <div class="flex items-center space-x-1.5 overflow-x-auto text-[11px] shrink-0 py-0.5">
            <span class="text-gsub font-semibold text-[10px] uppercase tracking-wider px-1 shrink-0">Chips:</span>
            <button onclick="sendTerminalCmd('uname -a\n')" class="px-2.5 py-1 bg-gray-100 hover:bg-gray-200 text-gdark rounded-lg font-mono border border-gborder shadow-2xs shrink-0">uname -a</button>
            <button onclick="sendTerminalCmd('whoami; pwd; ls -la\n')" class="px-2.5 py-1 bg-gray-100 hover:bg-gray-200 text-gdark rounded-lg font-mono border border-gborder shadow-2xs shrink-0">ls -la</button>
            <button onclick="sendTerminalCmd('python3 --version; pip list | head -n 10\n')" class="px-2.5 py-1 bg-gray-100 hover:bg-gray-200 text-gdark rounded-lg font-mono border border-gborder shadow-2xs shrink-0">python</button>
            <button onclick="sendTerminalCmd('top -b -n 1 | head -n 12\n')" class="px-2.5 py-1 bg-gray-100 hover:bg-gray-200 text-gdark rounded-lg font-mono border border-gborder shadow-2xs shrink-0">top</button>
            <button onclick="clearTerminalScreen()" class="px-2.5 py-1 bg-gray-100 hover:bg-gray-200 text-gdark rounded-lg font-mono border border-gborder shadow-2xs shrink-0">clear</button>
          </div>

          <!-- The xterm.js Terminal Container Viewport -->
          <div id="terminal-wrapper" class="flex-1 bg-[#090d16] rounded-2xl border border-gray-800 p-2 overflow-hidden flex flex-col relative min-h-[380px] shadow-inner">
            <div id="terminal-box" class="w-full h-full"></div>
          </div>

        </div>

        <!-- 7. TOPOLOGY MAP TAB -->
        <div id="tab-topology" class="hidden space-y-3 flex-1 flex flex-col overflow-hidden">
          <div class="flex items-center justify-between shrink-0">
            <div class="flex items-center space-x-1.5">
              <span class="text-lg">🗺️</span>
              <h3 class="text-xs font-bold uppercase tracking-wider text-gdark">Network Topology</h3>
            </div>
            <div class="flex items-center space-x-1.5">
              <button onclick="toggleTopoLabels()" id="topo-labels-btn" class="px-2.5 py-1 text-[11px] bg-gray-100 hover:bg-gray-200 text-gdark rounded-lg border border-gborder transition shadow-2xs">Labels</button>
              <button onclick="resetTopoView()" class="px-2.5 py-1 text-[11px] bg-gray-100 hover:bg-gray-200 text-gdark rounded-lg border border-gborder transition shadow-2xs">Reset</button>
            </div>
          </div>
          <div class="flex-1 relative rounded-2xl border border-gborder overflow-hidden bg-[#0a0e1a] shadow-inner min-h-[400px]">
            <canvas id="topology-canvas" class="w-full h-full block"></canvas>
            <div id="topo-tooltip" class="absolute hidden bg-gray-900/95 text-white text-[11px] px-3 py-2 rounded-xl border border-gray-700 shadow-m3-2 pointer-events-none z-10 space-y-1 max-w-[220px]"></div>
          </div>
          <div class="grid grid-cols-3 gap-2 text-[11px] shrink-0">
            <div class="p-2.5 bg-gray-50 rounded-xl border border-gborder text-center">
              <span class="font-bold text-gdark" id="topo-node-count">0</span> <span class="text-gsub">Nodes</span>
            </div>
            <div class="p-2.5 bg-gray-50 rounded-xl border border-gborder text-center">
              <span class="font-bold text-gdark" id="topo-edge-count">0</span> <span class="text-gsub">Links</span>
            </div>
            <div class="p-2.5 bg-gray-50 rounded-xl border border-gborder text-center">
              <span class="font-bold text-ggreen" id="topo-status">Online</span>
            </div>
          </div>
        </div>

      </div>
    </aside>

  </div>

  <!-- Workspace File Editor Modal -->
  <div id="file-modal" class="fixed inset-0 bg-black/45 backdrop-blur-xs z-50 hidden flex items-center justify-center p-6">
    <div class="bg-white rounded-3xl p-6 max-w-3xl w-full shadow-m3-3 border border-gborder flex flex-col space-y-4 max-h-[88vh] animate-in fade-in zoom-in-95 duration-150">
      <div class="flex items-center justify-between">
        <div class="flex items-center space-x-2">
          <span class="text-base">📄</span>
          <h3 id="modal-file-name" class="font-bold text-gdark text-sm font-mono truncate">file.txt</h3>
        </div>
        <button onclick="closeFileModal()" class="text-gray-400 hover:text-gdark font-bold text-lg p-1">×</button>
      </div>
      
      <textarea id="modal-file-content" rows="16" 
                onkeydown="handleFileEditorKey(event)"
                class="w-full flex-1 bg-gray-950 text-gray-100 font-mono text-xs p-4 rounded-2xl border border-gborder focus:outline-none focus:border-gblue leading-relaxed resize-none shadow-inner"></textarea>
      
      <div class="flex items-center justify-between pt-2">
        <button onclick="deleteCurrentFile()" class="px-4 py-2 bg-red-50 hover:bg-red-100 text-gred font-bold rounded-xl text-xs transition">Delete File</button>
        <div class="flex items-center space-x-2">
          <span class="text-[11px] text-gsub font-mono">Ctrl+S to save</span>
          <button onclick="closeFileModal()" class="px-4 py-2 bg-gray-100 hover:bg-gray-200 text-gdark rounded-xl text-xs font-semibold transition">Cancel</button>
          <button onclick="saveCurrentFile()" class="px-5 py-2 bg-gblue hover:bg-gblueHover text-white font-bold rounded-xl text-xs transition shadow-md">Save Changes</button>
        </div>
      </div>
    </div>
  </div>

  <!-- Persistent Config & API Keys Modal -->
  <div id="config-modal" class="fixed inset-0 bg-black/45 backdrop-blur-xs z-50 hidden flex items-center justify-center p-6">
    <div class="bg-white rounded-3xl p-6 max-w-xl w-full shadow-m3-3 border border-gborder flex flex-col space-y-4 max-h-[88vh] animate-in fade-in zoom-in-95 duration-150">
      <div class="flex items-center justify-between border-b border-gborder pb-3">
        <div class="flex items-center space-x-2">
          <span class="text-xl">🔑</span>
          <div>
            <h3 class="font-bold text-gdark text-sm">Engine API Keys & .env Config</h3>
            <p class="text-[11px] text-gsub">Changes are atomically persisted to <code class="bg-gray-100 px-1 py-0.5 rounded text-[10px]">.env</code></p>
          </div>
        </div>
        <button onclick="closeConfigModal()" class="text-gray-400 hover:text-gdark font-bold text-lg p-1">×</button>
      </div>

      <div class="space-y-3 overflow-y-auto flex-1 pr-1 text-xs">
        <div>
          <label class="block font-semibold text-gdark mb-1">xAI API Key (Grok)</label>
          <input type="password" id="cfg-xai-key" placeholder="xai-..." class="w-full bg-gray-50 border border-gborder rounded-xl px-3 py-2 text-xs font-mono focus:outline-none focus:border-gblue">
        </div>
        <div>
          <label class="block font-semibold text-gdark mb-1">OpenAI API Key</label>
          <input type="password" id="cfg-openai-key" placeholder="sk-..." class="w-full bg-gray-50 border border-gborder rounded-xl px-3 py-2 text-xs font-mono focus:outline-none focus:border-gblue">
        </div>
        <div>
          <label class="block font-semibold text-gdark mb-1">Anthropic API Key (Claude)</label>
          <input type="password" id="cfg-anthropic-key" placeholder="sk-ant-..." class="w-full bg-gray-50 border border-gborder rounded-xl px-3 py-2 text-xs font-mono focus:outline-none focus:border-gblue">
        </div>
        <div>
          <label class="block font-semibold text-gdark mb-1">Google Gemini API Key</label>
          <input type="password" id="cfg-gemini-key" placeholder="AIza..." class="w-full bg-gray-50 border border-gborder rounded-xl px-3 py-2 text-xs font-mono focus:outline-none focus:border-gblue">
        </div>
        <div>
          <label class="block font-semibold text-gdark mb-1">OpenRouter API Key</label>
          <input type="password" id="cfg-openrouter-key" placeholder="sk-or-..." class="w-full bg-gray-50 border border-gborder rounded-xl px-3 py-2 text-xs font-mono focus:outline-none focus:border-gblue">
        </div>
        <div class="pt-2 border-t border-gborderLight">
          <label class="block font-semibold text-gdark mb-1">OpenAI / Ollama Base URL</label>
          <input type="text" id="cfg-base-url" placeholder="http://localhost:11434/v1" class="w-full bg-gray-50 border border-gborder rounded-xl px-3 py-2 text-xs font-mono focus:outline-none focus:border-gblue">
        </div>
        <div>
          <label class="block font-semibold text-gdark mb-1">Default Model</label>
          <input type="text" id="cfg-model" placeholder="qwen2.5-coder:1.5b" class="w-full bg-gray-50 border border-gborder rounded-xl px-3 py-2 text-xs font-mono focus:outline-none focus:border-gblue">
        </div>
      </div>

      <div class="flex items-center justify-between pt-3 border-t border-gborder">
        <span id="cfg-save-status" class="text-[11px] text-gsub"></span>
        <div class="flex items-center space-x-2">
          <button onclick="closeConfigModal()" class="px-4 py-2 bg-gray-100 hover:bg-gray-200 text-gdark rounded-xl text-xs font-semibold transition">Cancel</button>
          <button onclick="saveConfigKeys()" class="px-5 py-2 bg-gblue hover:bg-gblueHover text-white font-bold rounded-xl text-xs transition shadow-md">Save & Apply</button>
        </div>
      </div>
    </div>
  </div>

  <!-- Smart Browser Login Modal -->
  <div id="login-modal" class="fixed inset-0 bg-black/45 backdrop-blur-xs z-50 hidden flex items-center justify-center p-6">
    <div class="bg-white rounded-3xl p-6 max-w-md w-full shadow-m3-3 border border-gborder flex flex-col space-y-4 animate-in fade-in zoom-in-95 duration-150">
      <div class="flex items-center justify-between border-b border-gborder pb-3">
        <div class="flex items-center space-x-2">
          <span class="text-xl">🔐</span>
          <div>
            <h3 class="font-bold text-gdark text-sm">Smart Human Login</h3>
            <p class="text-[11px] text-gsub">Natural bezier cursor cadence, multi-step & 2FA support</p>
          </div>
        </div>
        <button onclick="closeSmartLoginModal()" class="text-gray-400 hover:text-gdark font-bold text-lg p-1">×</button>
      </div>

      <div class="space-y-3 text-xs">
        <div>
          <label class="block font-semibold text-gdark mb-1">Target Page URL</label>
          <input type="text" id="login-modal-url" placeholder="https://x.com/i/flow/login" class="w-full bg-gray-50 border border-gborder rounded-xl px-3 py-2 text-xs font-mono focus:outline-none focus:border-gblue">
        </div>
        <div>
          <label class="block font-semibold text-gdark mb-1">Username / Email / Handle</label>
          <input type="text" id="login-modal-user" placeholder="username or user@email.com" class="w-full bg-gray-50 border border-gborder rounded-xl px-3 py-2 text-xs focus:outline-none focus:border-gblue">
        </div>
        <div>
          <label class="block font-semibold text-gdark mb-1">Password</label>
          <input type="password" id="login-modal-pass" placeholder="••••••••••••" class="w-full bg-gray-50 border border-gborder rounded-xl px-3 py-2 text-xs font-mono focus:outline-none focus:border-gblue">
        </div>

        <!-- Optional custom selectors toggle -->
        <details class="text-[11px] text-gsub cursor-pointer pt-1">
          <summary class="hover:text-gdark select-none font-medium">Advanced: Custom Selectors (Optional)</summary>
          <div class="space-y-2 mt-2 pl-2 border-l-2 border-gray-100">
            <div>
              <label class="block text-[10px] text-gray-500 mb-0.5">Username Selector</label>
              <input type="text" id="login-modal-sel-user" placeholder="Auto-detect (input[autocomplete=username], ...)" class="w-full bg-gray-50 border border-gborder rounded-lg px-2 py-1 text-[11px] font-mono">
            </div>
            <div>
              <label class="block text-[10px] text-gray-500 mb-0.5">Password Selector</label>
              <input type="text" id="login-modal-sel-pass" placeholder="Auto-detect (input[type=password], ...)" class="w-full bg-gray-50 border border-gborder rounded-lg px-2 py-1 text-[11px] font-mono">
            </div>
            <div>
              <label class="block text-[10px] text-gray-500 mb-0.5">Submit Button Selector</label>
              <input type="text" id="login-modal-sel-submit" placeholder="Auto-detect (button[type=submit], ...)" class="w-full bg-gray-50 border border-gborder rounded-lg px-2 py-1 text-[11px] font-mono">
            </div>
          </div>
        </details>
      </div>

      <div class="flex items-center justify-between pt-3 border-t border-gborder">
        <span id="login-modal-status" class="text-[11px] text-gsub"></span>
        <div class="flex items-center space-x-2">
          <button onclick="closeSmartLoginModal()" class="px-4 py-2 bg-gray-100 hover:bg-gray-200 text-gdark rounded-xl text-xs font-semibold transition">Cancel</button>
          <button onclick="submitSmartLogin()" id="btn-submit-smart-login" class="px-5 py-2 bg-gblue hover:bg-gblueHover text-white font-bold rounded-xl text-xs transition shadow-md flex items-center space-x-1.5">
            <span>🚀</span>
            <span>Execute Login</span>
          </button>
        </div>
      </div>
    </div>
  </div>

  <!-- JavaScript Client Core -->
  <script>
    let activeEngine = 'ollama';
    let activeMode = 'regular';
    let availableEngines = [];
    let duckyPresets = [];
    let currentEditingPath = '';
    let canvasZoomLevel = 1.0;

    const MODE_METADATA = {
      regular: { name: 'Truth Mode', icon: '⚡', tagline: 'Objective & direct' },
      fun: { name: 'Fun Mode', icon: '🌶️', tagline: 'Witty, sharp, and unfiltered' },
      think: { name: 'Think Mode', icon: '🧠', tagline: 'Chain-of-thought & citations' },
      coder: { name: 'Coder Mode', icon: '💻', tagline: 'Sandbox scripting & builder' }
    };

    async function setMode(modeId) {
      try {
        const res = await fetch('/api/mode', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({mode: modeId})
        });
        const data = await res.json();
        if (data.ok) {
          activeMode = modeId;
          updateModeUI();
          const meta = MODE_METADATA[modeId] || { name: modeId, icon: '⚡' };
          showToast(`Switched to Grok ${meta.name} ${meta.icon}`, 'engine');
        }
      } catch (err) {
        showToast(`Failed to switch mode: ${err.message}`, 'error');
      }
    }

    function updateModeUI() {
      document.querySelectorAll('.mode-btn').forEach(btn => {
        btn.classList.remove('bg-purple-600', 'bg-gblue', 'text-white', 'shadow-2xs');
        btn.classList.add('text-gdark');
      });
      const activeBtn = document.getElementById('mode-btn-' + activeMode);
      if (activeBtn) {
        activeBtn.classList.add('bg-purple-600', 'text-white', 'shadow-2xs');
        activeBtn.classList.remove('text-gdark');
      }
      const meta = MODE_METADATA[activeMode] || { name: 'Truth Mode', icon: '⚡' };
      const badgeLabel = document.getElementById('header-mode-label');
      const badgeIcon = document.getElementById('header-mode-icon');
      if (badgeLabel) badgeLabel.textContent = meta.name;
      if (badgeIcon) badgeIcon.textContent = meta.icon;
    }

    function cycleMode() {
      const modes = ['regular', 'fun', 'think', 'coder'];
      const nextIdx = (modes.indexOf(activeMode) + 1) % modes.length;
      setMode(modes[nextIdx]);
    }

    function triggerSpark(promptText) {
      const input = document.getElementById('user-input');
      if (input) {
        input.value = promptText;
        input.focus();
      }
    }

    function promptDeepSearch() {
      const query = prompt("Enter a topic for DeepSearch (multi-source verified research):");
      if (query && query.trim()) {
        triggerSpark(`/deep ${query.trim()}`);
        sendMessage();
      }
    }

    function promptXScout() {
      const query = prompt("Enter keywords or handle to search on X (Twitter):");
      if (query && query.trim()) {
        triggerSpark(`/x ${query.trim()}`);
        sendMessage();
      }
    }

    async function loadModes() {
      try {
        const res = await fetch('/api/modes');
        const data = await res.json();
        if (data.ok && data.active) {
          activeMode = data.active;
          updateModeUI();
        }
      } catch (err) {
        console.error('Failed to load modes', err);
      }
    }

    let botConfig = {
      shape: localStorage.getItem('abot_shape') || 'circle',
      anim: localStorage.getItem('abot_anim') || 'anim-breathe',
      palette: localStorage.getItem('abot_palette') || 'palette-google',
    };

    // Configure Marked.js with Highlight.js
    if (window.marked) {
      marked.setOptions({
        gfm: true,
        breaks: true,
        highlight: function(code, lang) {
          if (lang && hljs.getLanguage(lang)) {
            try { return hljs.highlight(code, { language: lang }).value; } catch (e) {}
          }
          try { return hljs.highlightAuto(code).value; } catch (e) { return code; }
        }
      });
    }

    function renderMarkdown(rawText) {
      if (!window.marked) return escapeHtml(rawText);
      try {
        let parsed = marked.parse(rawText);
        // Enhance pre blocks with code-header & copy button
        parsed = parsed.replace(/<pre><code class="language-([a-zA-Z0-9_\-]+)">([\s\S]*?)<\/code><\/pre>/g, function(match, lang, code) {
          return `
            <div class="code-container">
              <div class="code-header">
                <span class="font-bold">${lang.toUpperCase()}</span>
                <button onclick="copyCodeBlock(this)" class="hover:text-white flex items-center space-x-1 transition text-[11px] px-2 py-0.5 rounded hover:bg-gray-700/60">
                  <span>📋</span><span>Copy</span>
                </button>
              </div>
              <pre class="p-3.5 text-xs font-mono overflow-x-auto text-gray-200"><code class="language-${lang}">${code}</code></pre>
            </div>
          `;
        });
        // Default code blocks without explicit language
        parsed = parsed.replace(/<pre><code>([\s\S]*?)<\/code><\/pre>/g, function(match, code) {
          return `
            <div class="code-container">
              <div class="code-header">
                <span class="font-bold">CODE</span>
                <button onclick="copyCodeBlock(this)" class="hover:text-white flex items-center space-x-1 transition text-[11px] px-2 py-0.5 rounded hover:bg-gray-700/60">
                  <span>📋</span><span>Copy</span>
                </button>
              </div>
              <pre class="p-3.5 text-xs font-mono overflow-x-auto text-gray-200"><code>${code}</code></pre>
            </div>
          `;
        });
        return parsed;
      } catch (err) {
        return escapeHtml(rawText);
      }
    }

    function escapeHtml(text) {
      const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' };
      return text.replace(/[&<>"']/g, m => map[m]);
    }

    // --- TOAST NOTIFICATION SYSTEM ---
    function showToast(message, type = 'info', duration = 3200) {
      const container = document.getElementById('toast-container');
      const toast = document.createElement('div');
      
      const icons = {
        success: '✔',
        error: '❌',
        info: 'ℹ',
        warning: '⚠️',
        ducky: '🦆',
        engine: '⚡',
        copy: '📋',
      };
      
      const colorClasses = {
        success: 'bg-emerald-900/90 text-emerald-100 border-emerald-700',
        error: 'bg-rose-900/90 text-rose-100 border-rose-700',
        info: 'bg-gray-900/95 text-white border-gray-700',
        warning: 'bg-amber-900/90 text-amber-100 border-amber-700',
        ducky: 'bg-amber-950/95 text-amber-200 border-amber-800',
        engine: 'bg-indigo-950/95 text-indigo-200 border-indigo-800',
        copy: 'bg-cyan-950/95 text-cyan-200 border-cyan-800',
      };

      const icon = icons[type] || 'ℹ';
      const colorClass = colorClasses[type] || colorClasses.info;

      toast.className = `pointer-events-auto p-3.5 rounded-2xl shadow-m3-3 border backdrop-blur-md flex items-center justify-between space-x-3 text-xs font-medium toast-enter ${colorClass}`;
      toast.innerHTML = `
        <div class="flex items-center space-x-2.5">
          <span class="text-sm">${icon}</span>
          <span>${message}</span>
        </div>
        <button onclick="this.parentElement.remove()" class="opacity-60 hover:opacity-100 font-bold ml-2">×</button>
      `;

      container.appendChild(toast);

      setTimeout(() => {
        toast.classList.remove('toast-enter');
        toast.classList.add('toast-exit');
        setTimeout(() => toast.remove(), 220);
      }, duration);
    }

    function copyCodeBlock(btn) {
      const pre = btn.closest('.code-container').querySelector('pre code');
      if (pre) {
        navigator.clipboard.writeText(pre.innerText).then(() => {
          showToast('Code snippet copied to clipboard!', 'copy');
          btn.innerHTML = '<span>✔</span><span>Copied</span>';
          setTimeout(() => {
            btn.innerHTML = '<span>📋</span><span>Copy</span>';
          }, 2000);
        });
      }
    }

    function copyMessageText(btn) {
      const bubble = btn.closest('.message-bubble');
      if (bubble) {
        navigator.clipboard.writeText(bubble.innerText).then(() => {
          showToast('Message text copied to clipboard!', 'copy');
        });
      }
    }

    // --- MASCOT CUSTOMIZER LOGIC ---
    function applyBotTheme() {
      const targets = [
        document.getElementById('header-bot-preview'),
        document.getElementById('hero-bot-avatar'),
        document.getElementById('studio-bot-preview'),
      ];

      targets.forEach(el => {
        if (!el) return;
        el.className = 'flex items-center justify-center shadow-md transition-all duration-300 text-white cursor-pointer ' + 
          (el.id === 'header-bot-preview' ? 'w-10 h-10 ' : el.id === 'hero-bot-avatar' ? 'w-16 h-16 shrink-0 ' : 'w-24 h-24 mx-auto mb-3 ');
        
        if (botConfig.shape === 'circle') el.classList.add('shape-circle');
        else if (botConfig.shape === 'squircle') el.classList.add('shape-squircle');
        else if (botConfig.shape === 'sparkle') el.classList.add('shape-sparkle');
        else if (botConfig.shape === 'pill') el.classList.add('shape-pill');

        el.classList.add(botConfig.palette);
        el.classList.add(botConfig.anim);
      });

      document.querySelectorAll('.chat-bot-icon').forEach(el => {
        el.className = 'w-8 h-8 flex items-center justify-center text-white text-xs font-bold shadow-sm transition-all chat-bot-icon shrink-0 ';
        if (botConfig.shape === 'circle') el.classList.add('shape-circle');
        else if (botConfig.shape === 'squircle') el.classList.add('shape-squircle');
        else if (botConfig.shape === 'sparkle') el.classList.add('shape-sparkle');
        else if (botConfig.shape === 'pill') el.classList.add('shape-pill');
        el.classList.add(botConfig.palette);
        el.classList.add(botConfig.anim);
      });
    }

    function setBotShape(shape) {
      botConfig.shape = shape;
      localStorage.setItem('abot_shape', shape);
      applyBotTheme();
      showToast(`Mascot shape set to ${shape}`, 'info');
    }

    function setBotAnim(anim) {
      botConfig.anim = anim;
      localStorage.setItem('abot_anim', anim);
      applyBotTheme();
      showToast(`Animation updated`, 'info');
    }

    function setBotPalette(palette) {
      botConfig.palette = palette;
      localStorage.setItem('abot_palette', palette);
      applyBotTheme();
      showToast(`Aura palette updated`, 'engine');
    }

    // Mascot Ambient Particles Canvas
    let particles = [];
    function initMascotParticles() {
      const canvas = document.getElementById('mascot-particles');
      if (!canvas) return;
      const ctx = canvas.getContext('2d');
      canvas.width = canvas.offsetWidth;
      canvas.height = canvas.offsetHeight;

      particles = [];
      for (let i = 0; i < 22; i++) {
        particles.push({
          x: Math.random() * canvas.width,
          y: Math.random() * canvas.height,
          size: Math.random() * 2.5 + 1,
          speedX: (Math.random() - 0.5) * 0.6,
          speedY: (Math.random() - 0.5) * 0.6,
          opacity: Math.random() * 0.6 + 0.2,
        });
      }

      function animate() {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        particles.forEach(p => {
          p.x += p.speedX;
          p.y += p.speedY;
          if (p.x < 0) p.x = canvas.width;
          if (p.x > canvas.width) p.x = 0;
          if (p.y < 0) p.y = canvas.height;
          if (p.y > canvas.height) p.y = 0;

          ctx.beginPath();
          ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
          ctx.fillStyle = `rgba(66, 133, 244, ${p.opacity})`;
          ctx.fill();
        });
        requestAnimationFrame(animate);
      }
      animate();
    }

    function burstMascotParticles() {
      const canvas = document.getElementById('mascot-particles');
      if (!canvas) return;
      const ctx = canvas.getContext('2d');
      for (let i = 0; i < 15; i++) {
        particles.push({
          x: canvas.width / 2,
          y: canvas.height / 2,
          size: Math.random() * 3.5 + 1.5,
          speedX: (Math.random() - 0.5) * 4,
          speedY: (Math.random() - 0.5) * 4,
          opacity: 1,
        });
      }
      showToast('Spark burst activated! ✨', 'engine', 1500);
    }

    // --- COMMAND PALETTE (Ctrl+K / Cmd+K) ---
    const COMMAND_LIST = [
      { id: 'mode-regular', title: 'Grok Mode: ⚡ Truth & Regular Mode', category: 'Grok Modes', icon: '⚡', action: () => setMode('regular') },
      { id: 'mode-fun', title: 'Grok Mode: 🌶️ Fun Mode (Witty & Unfiltered)', category: 'Grok Modes', icon: '🌶️', action: () => setMode('fun') },
      { id: 'mode-think', title: 'Grok Mode: 🧠 DeepSearch & Think (Citations)', category: 'Grok Modes', icon: '🧠', action: () => setMode('think') },
      { id: 'mode-coder', title: 'Grok Mode: 💻 Coder & Builder (Sandbox Scripts)', category: 'Grok Modes', icon: '💻', action: () => setMode('coder') },
      { id: 'tool-deepsearch', title: 'DeepSearch: Multi-Source Citation Investigation', category: 'Grok Tools', icon: '🔬', action: () => promptDeepSearch() },
      { id: 'tool-xscout', title: 'Live X Scout: Real-Time Social Search', category: 'Grok Tools', icon: '🐦', action: () => promptXScout() },
      
      { id: 'eng-ollama', title: 'Switch Engine: Ollama (Local)', category: 'Engines', icon: '🦙', action: () => selectEngine('ollama') },
      { id: 'eng-hermes', title: 'Switch Engine: Hermes Agent CLI', category: 'Engines', icon: '⚡', action: () => selectEngine('hermes') },
      { id: 'eng-agy', title: 'Switch Engine: AGY CLI Agent', category: 'Engines', icon: '🪐', action: () => selectEngine('agy') },
      { id: 'eng-codex', title: 'Switch Engine: Codex CLI', category: 'Engines', icon: '🤖', action: () => selectEngine('codex') },
      { id: 'eng-grok', title: 'Switch Engine: Grok CLI', category: 'Engines', icon: '🚀', action: () => selectEngine('grok_cli') },
      { id: 'eng-gemini', title: 'Switch Engine: Google Gemini API', category: 'Engines', icon: '✨', action: () => selectEngine('gemini') },
      { id: 'eng-openai', title: 'Switch Engine: OpenAI GPT-4o', category: 'Engines', icon: '🧠', action: () => selectEngine('openai') },
      { id: 'eng-claude', title: 'Switch Engine: Anthropic Claude', category: 'Engines', icon: '🎭', action: () => selectEngine('claude') },
      { id: 'eng-openrouter', title: 'Switch Engine: OpenRouter', category: 'Engines', icon: '🌐', action: () => selectEngine('openrouter') },
      
      { id: 'ducky-x', title: 'DuckyScript: Auto-Post to X / Twitter', category: 'DuckyScript', icon: '🦆', action: () => runPresetDucky('x_post') },
      { id: 'ducky-google', title: 'DuckyScript: Google Search & Inspect', category: 'DuckyScript', icon: '🔍', action: () => runPresetDucky('google_search') },
      { id: 'ducky-tabs', title: 'DuckyScript: Multi-Tab Setup', category: 'DuckyScript', icon: '📑', action: () => runPresetDucky('tab_cycle') },
      { id: 'ducky-scroll', title: 'DuckyScript: Smooth Page Reader', category: 'DuckyScript', icon: '📜', action: () => runPresetDucky('scroll_reader') },
      
      { id: 'nav-x', title: 'Browser: Open X.com', category: 'Browser', icon: '🐦', action: () => browserNav('https://x.com') },
      { id: 'nav-google', title: 'Browser: Open Google.com', category: 'Browser', icon: '🌐', action: () => browserNav('https://google.com') },
      { id: 'nav-github', title: 'Browser: Open GitHub.com', category: 'Browser', icon: '🐙', action: () => browserNav('https://github.com') },
      { id: 'nav-youtube', title: 'Browser: Open YouTube.com', category: 'Browser', icon: '▶️', action: () => browserNav('https://youtube.com') },
      { id: 'nav-newtab', title: 'Browser: Open New Tab', category: 'Browser', icon: '➕', action: () => browserNewTabPrompt() },
      { id: 'nav-refresh', title: 'Browser: Refresh Active Page Frame', category: 'Browser', icon: '🔄', action: () => refreshLiveBrowser() },
      { id: 'browser-check-auth', title: 'Browser: Check Authentication & Session State', category: 'Browser', icon: '🔍', action: () => checkBrowserAuth() },
      { id: 'browser-smart-login', title: 'Browser: Smart Human Login Modal', category: 'Browser', icon: '🔐', action: () => openSmartLoginModal() },
      { id: 'browser-takeover', title: 'Browser: Takeover & Manual 2FA / CAPTCHA', category: 'Browser', icon: '🖥️', action: () => triggerBrowserTakeover() },
      { id: 'browser-save-cookies', title: 'Browser: Export Session Cookies to Disk', category: 'Browser', icon: '💾', action: () => exportBrowserSession() },
      
      { id: 'ws-new', title: 'Workspace: Create New File', category: 'Workspace', icon: '📄', action: () => promptCreateFile() },
      { id: 'ws-refresh', title: 'Workspace: Refresh File Tree', category: 'Workspace', icon: '📁', action: () => loadWorkspace() },
      
      { id: 'tab-browser', title: 'View Tab: Interactive Browser', category: 'Navigation', icon: '🌐', action: () => setTab('browser') },
      { id: 'tab-ducky', title: 'View Tab: DuckyScript Studio', category: 'Navigation', icon: '🦆', action: () => setTab('ducky') },
      { id: 'tab-engines', title: 'View Tab: Engines Router', category: 'Navigation', icon: '⚡', action: () => setTab('engines') },
      { id: 'tab-workspace', title: 'View Tab: Workspace Files', category: 'Navigation', icon: '📁', action: () => setTab('workspace') },
      { id: 'tab-customizer', title: 'View Tab: Mascot Studio', category: 'Navigation', icon: '🎨', action: () => setTab('customizer') },
      
      { id: 'toggle-waveform', title: 'Toggle: Waveform Indicator', category: 'Visual', icon: '📊', action: () => toggleWaveform() },
      { id: 'toggle-scanline', title: 'Toggle: Scan Line Effect', category: 'Visual', icon: '📺', action: () => toggleScanline() },
      { id: 'toggle-stealth', title: 'Toggle: Stealth Mode', category: 'Visual', icon: '🕵️', action: () => toggleStealthMode() },

      { id: 'topology', title: 'View: Network Topology Map', category: 'Navigation', icon: '🗺️', action: () => setTab('topology') },

      { id: 'chat-clear', title: 'Chat: Clear Conversation History', category: 'Chat', icon: '🗑️', action: () => clearChat() },
    ];

    let selectedCommandIndex = 0;
    let filteredCommands = [...COMMAND_LIST];

    function openCommandPalette() {
      const modal = document.getElementById('command-palette-modal');
      const input = document.getElementById('command-input');
      modal.classList.remove('hidden');
      input.value = '';
      filterCommands();
      input.focus();
    }

    function closeCommandPalette() {
      document.getElementById('command-palette-modal').classList.add('hidden');
    }

    function filterCommands() {
      const query = document.getElementById('command-input').value.toLowerCase().trim();
      filteredCommands = COMMAND_LIST.filter(c => 
        c.title.toLowerCase().includes(query) || c.category.toLowerCase().includes(query)
      );
      selectedCommandIndex = 0;
      renderCommandResults();
    }

    function renderCommandResults() {
      const el = document.getElementById('command-results');
      if (filteredCommands.length === 0) {
        el.innerHTML = '<div class="text-gray-400 italic p-4 text-center">No matching commands found.</div>';
        return;
      }
      el.innerHTML = filteredCommands.map((c, idx) => `
        <div onclick="executeCommand(${idx})" 
             class="p-2.5 px-3 rounded-2xl flex items-center justify-between cursor-pointer transition ${idx === selectedCommandIndex ? 'bg-blue-50 text-gblue font-semibold border border-blue-200' : 'hover:bg-gray-50 text-gdark border border-transparent'}">
          <div class="flex items-center space-x-2.5">
            <span class="text-base">${c.icon}</span>
            <span class="text-xs">${c.title}</span>
          </div>
          <span class="text-[10px] text-gsub bg-gray-100 px-2 py-0.5 rounded-full border border-gborder">${c.category}</span>
        </div>
      `).join('');
    }

    function handleCommandKey(e) {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        selectedCommandIndex = (selectedCommandIndex + 1) % Math.max(1, filteredCommands.length);
        renderCommandResults();
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        selectedCommandIndex = (selectedCommandIndex - 1 + filteredCommands.length) % Math.max(1, filteredCommands.length);
        renderCommandResults();
      } else if (e.key === 'Enter') {
        e.preventDefault();
        executeCommand(selectedCommandIndex);
      } else if (e.key === 'Escape') {
        closeCommandPalette();
      }
    }

    function executeCommand(index) {
      const cmd = filteredCommands[index];
      if (cmd && cmd.action) {
        closeCommandPalette();
        cmd.action();
      }
    }

    // --- INTERACTIVE BROWSER LOGIC ---
    async function refreshLiveBrowser() {
      try {
        const res = await fetch('/api/browser/state');
        const data = await res.json();
        
        if (data.ok) {
          const img = document.getElementById('browser-live-img');
          const placeholder = document.getElementById('browser-loading-placeholder');
          
          if (data.screenshot) {
            img.src = data.screenshot;
            img.classList.remove('hidden');
            placeholder.classList.add('hidden');
          }

          document.getElementById('browser-url-input').value = data.url || '';
          renderTabs(data.tabs || [], data.active_tab || 0);

          const banner = document.getElementById('captcha-banner');
          if (data.verification && data.verification.detected) {
            banner.classList.remove('hidden');
            document.getElementById('captcha-msg').innerText = `🚨 ${data.verification.type.toUpperCase()} Challenge Detected! Click canvas below to solve.`;
          } else {
            banner.classList.add('hidden');
          }
        }
      } catch (err) {
        console.error('Failed to refresh browser state:', err);
      }
    }

    function renderTabs(tabs, activeIndex) {
      const bar = document.getElementById('browser-tabs-bar');
      bar.innerHTML = tabs.map((t, idx) => `
        <div onclick="browserSwitchTab(${t.index})" class="flex items-center space-x-1.5 px-3 py-1 rounded-xl text-xs cursor-pointer border transition shrink-0 ${t.active ? 'bg-white text-gblue font-bold border-gborder shadow-2xs' : 'bg-transparent text-gsub hover:text-gdark border-transparent'}">
          <span class="truncate max-w-[120px]">${t.title || 'Tab ' + (t.index + 1)}</span>
          <span onclick="event.stopPropagation(); browserCloseTab(${t.index})" class="text-gray-400 hover:text-gred font-bold ml-1">×</span>
        </div>
      `).join('');
    }

    function trackCanvasCoords(e) {
      const img = document.getElementById('browser-live-img');
      if (img.classList.contains('hidden')) return;
      const rect = img.getBoundingClientRect();
      const scaleX = 1280 / rect.width;
      const scaleY = 800 / rect.height;
      const realX = Math.round(Math.max(0, Math.min(1280, (e.clientX - rect.left) * scaleX)));
      const realY = Math.round(Math.max(0, Math.min(800, (e.clientY - rect.top) * scaleY)));
      document.getElementById('canvas-coord-readout').innerText = `X: ${realX} Y: ${realY}`;
    }

    function clearCanvasCoords() {
      document.getElementById('canvas-coord-readout').innerText = 'X: — Y: —';
    }

    function adjustCanvasZoom(delta) {
      canvasZoomLevel = Math.max(0.5, Math.min(2.5, canvasZoomLevel + delta));
      document.getElementById('browser-zoom-wrapper').style.transform = `scale(${canvasZoomLevel})`;
      document.getElementById('canvas-zoom-badge').innerText = `${Math.round(canvasZoomLevel * 100)}%`;
      showToast(`Zoom: ${Math.round(canvasZoomLevel * 100)}%`, 'info', 1200);
    }

    function resetCanvasZoom() {
      canvasZoomLevel = 1.0;
      document.getElementById('browser-zoom-wrapper').style.transform = 'scale(1)';
      document.getElementById('canvas-zoom-badge').innerText = '100%';
      showToast('Zoom reset to 100%', 'info', 1200);
    }

    async function handleCanvasClick(e) {
      const img = document.getElementById('browser-live-img');
      const rect = img.getBoundingClientRect();
      const scaleX = 1280 / rect.width;
      const scaleY = 800 / rect.height;
      const realX = Math.round((e.clientX - rect.left) * scaleX);
      const realY = Math.round((e.clientY - rect.top) * scaleY);

      // Create click ripple effect
      const layer = document.getElementById('canvas-ripple-layer');
      const containerRect = document.getElementById('browser-viewport-container').getBoundingClientRect();
      const ripple = document.createElement('div');
      ripple.className = 'canvas-ripple-fx';
      ripple.style.left = (e.clientX - containerRect.left) + 'px';
      ripple.style.top = (e.clientY - containerRect.top) + 'px';
      layer.appendChild(ripple);
      setTimeout(() => ripple.remove(), 600);

      await fetch('/api/browser/input', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({type: 'click', x: realX, y: realY})
      });
      setTimeout(refreshLiveBrowser, 250);
    }

    async function handleCanvasWheel(e) {
      e.preventDefault();
      await fetch('/api/browser/input', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({type: 'wheel', delta_y: Math.sign(e.deltaY) * 320})
      });
      setTimeout(refreshLiveBrowser, 200);
    }

    async function handleDirectKey(e) {
      if (['Enter', 'Backspace', 'Tab', 'Escape', 'ArrowDown', 'ArrowUp', 'ArrowLeft', 'ArrowRight'].includes(e.key)) {
        e.preventDefault();
        await fetch('/api/browser/input', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({type: 'key', key: e.key})
        });
        showToast(`Key pressed: ${e.key}`, 'info', 1000);
        setTimeout(refreshLiveBrowser, 250);
      }
    }

    async function sendTypedText() {
      const input = document.getElementById('browser-type-input');
      const text = input.value;
      if (!text) return;
      await fetch('/api/browser/input', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({type: 'type', text: text})
      });
      showToast(`Typed text sent to browser page`, 'info', 1500);
      input.value = '';
      setTimeout(refreshLiveBrowser, 300);
    }

    async function browserGo() {
      const url = document.getElementById('browser-url-input').value.trim();
      if (!url) return;
      showToast(`Navigating to ${url}...`, 'info');
      await fetch('/api/browser/input', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({type: 'navigate', url: url})
      });
      refreshLiveBrowser();
    }

    function browserNav(url) {
      document.getElementById('browser-url-input').value = url;
      setTab('browser');
      browserGo();
    }

    async function browserNewTabPrompt() {
      const url = prompt("Enter destination URL for new tab:", "https://google.com");
      if (url === null) return;
      await fetch('/api/browser/input', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({type: 'new_tab', url: url || 'https://google.com'})
      });
      showToast('Opened new browser tab', 'success');
      refreshLiveBrowser();
    }

    async function browserSwitchTab(idx) {
      await fetch('/api/browser/input', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({type: 'switch_tab', tab_index: idx})
      });
      showToast(`Switched to tab ${idx + 1}`, 'info', 1200);
      refreshLiveBrowser();
    }

    async function browserCloseTab(idx) {
      await fetch('/api/browser/input', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({type: 'close_tab', tab_index: idx})
      });
      showToast(`Closed tab`, 'warning', 1200);
      refreshLiveBrowser();
    }

    // --- BROWSER AUTH & LOGIN ASSISTANT ---
    async function checkBrowserAuth() {
      const btn = document.getElementById('btn-check-auth');
      const badge = document.getElementById('browser-auth-badge');
      const userEl = document.getElementById('browser-auth-user');
      const originalText = btn ? btn.innerHTML : '';
      if (btn) {
        btn.innerHTML = '<span>⏳</span><span>Checking...</span>';
        btn.disabled = true;
      }

      try {
        const currentUrl = document.getElementById('browser-url-input').value.trim();
        const res = await fetch('/api/browser/check_auth', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ url: currentUrl || undefined })
        });
        const data = await res.json();

        if (badge) {
          if (data.authenticated) {
            badge.className = 'px-2 py-0.5 rounded-full text-[11px] font-semibold bg-green-100 text-green-800 border border-green-300';
            badge.innerHTML = '🟢 Authenticated';
            if (data.user && userEl) {
              userEl.innerText = `@${data.user}`;
              userEl.classList.remove('hidden');
            } else if (userEl) {
              userEl.classList.add('hidden');
            }
            showToast(`Authenticated session verified on ${data.domain || 'page'}!`, 'success');
          } else if (data.challenge_detected) {
            badge.className = 'px-2 py-0.5 rounded-full text-[11px] font-semibold bg-red-100 text-red-800 border border-red-300';
            badge.innerHTML = '🔴 2FA / Challenge';
            if (userEl) userEl.classList.add('hidden');
            showToast(`Challenge or 2FA detected! Click Takeover to solve.`, 'warning');
          } else {
            badge.className = 'px-2 py-0.5 rounded-full text-[11px] font-semibold bg-amber-100 text-amber-800 border border-amber-300';
            badge.innerHTML = '🟡 Guest / Unverified';
            if (userEl) userEl.classList.add('hidden');
            showToast(`No logged-in user profile detected on page.`, 'info');
          }
        }
      } catch (err) {
        console.error('Failed to check auth:', err);
        showToast('Error checking authentication state', 'error');
      } finally {
        if (btn) {
          btn.innerHTML = originalText;
          btn.disabled = false;
        }
      }
    }

    function openSmartLoginModal() {
      const currentUrl = document.getElementById('browser-url-input').value.trim();
      if (currentUrl) {
        document.getElementById('login-modal-url').value = currentUrl;
      }
      document.getElementById('login-modal-status').innerText = '';
      document.getElementById('login-modal').classList.remove('hidden');
      document.getElementById('login-modal-user').focus();
    }

    function closeSmartLoginModal() {
      document.getElementById('login-modal').classList.add('hidden');
    }

    async function submitSmartLogin() {
      const url = document.getElementById('login-modal-url').value.trim();
      const username = document.getElementById('login-modal-user').value.trim();
      const password = document.getElementById('login-modal-pass').value;
      const userSel = document.getElementById('login-modal-sel-user').value.trim() || null;
      const passSel = document.getElementById('login-modal-sel-pass').value.trim() || null;
      const submitSel = document.getElementById('login-modal-sel-submit').value.trim() || null;
      const statusEl = document.getElementById('login-modal-status');
      const btn = document.getElementById('btn-submit-smart-login');

      if (!username || !password) {
        statusEl.className = 'text-[11px] text-gred font-medium';
        statusEl.innerText = 'Username and password required.';
        return;
      }

      const origBtnHtml = btn.innerHTML;
      btn.innerHTML = '<div class="w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin"></div><span>Logging In...</span>';
      btn.disabled = true;
      statusEl.className = 'text-[11px] text-gblue font-medium';
      statusEl.innerText = 'Simulating human typing & navigation...';

      try {
        const res = await fetch('/api/browser/login', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            url: url || undefined,
            username: username,
            password: password,
            user_selector: userSel,
            pass_selector: passSel,
            submit_selector: submitSel
          })
        });
        const result = await res.json();

        if (result.success) {
          showToast(`Logged in successfully! Step: ${result.step}`, 'success');
          closeSmartLoginModal();
          refreshLiveBrowser();
          checkBrowserAuth();
        } else if (result.requires_takeover || result.step === 'challenge_detected') {
          showToast(`2FA or verification required!`, 'warning');
          statusEl.className = 'text-[11px] text-amber-600 font-medium';
          statusEl.innerText = '2FA challenge detected. Use Takeover / 2FA button to complete.';
          refreshLiveBrowser();
          checkBrowserAuth();
        } else {
          statusEl.className = 'text-[11px] text-gred font-medium';
          statusEl.innerText = `Login failed: ${result.error || result.step || 'Unknown error'}`;
          showToast(`Login failed: ${result.error || result.step}`, 'error');
          refreshLiveBrowser();
        }
      } catch (err) {
        console.error('Login request error:', err);
        statusEl.className = 'text-[11px] text-gred font-medium';
        statusEl.innerText = `Error: ${err.message}`;
        showToast('Login request failed', 'error');
      } finally {
        btn.innerHTML = origBtnHtml;
        btn.disabled = false;
      }
    }

    async function triggerBrowserTakeover() {
      const currentUrl = document.getElementById('browser-url-input').value.trim() || 'https://x.com';
      try {
        const res = await fetch('/api/browser/takeover', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ url: currentUrl, reason: 'User requested manual 2FA / CAPTCHA takeover' })
        });
        const data = await res.json();
        if (data.ok) {
          showToast('Opened visible browser window on host desktop for manual interaction.', 'warning', 4000);
        } else {
          showToast(`Takeover: ${data.message || data.error}`, 'info');
        }
        setTimeout(refreshLiveBrowser, 1000);
      } catch (err) {
        showToast('Takeover request failed', 'error');
      }
    }

    async function exportBrowserSession() {
      try {
        const res = await fetch('/api/browser/session/export', { method: 'POST' });
        const data = await res.json();
        if (data.success) {
          showToast(`Exported ${data.cookies_count} session cookies to disk!`, 'success');
        } else {
          showToast(`Export failed: ${data.error}`, 'error');
        }
      } catch (err) {
        showToast('Session export failed', 'error');
      }
    }

    // --- DUCKY SCRIPT LOGIC ---
    async function loadDuckyPresets() {
      try {
        const res = await fetch('/api/ducky/presets');
        const data = await res.json();
        duckyPresets = data.presets || [];
        const select = document.getElementById('ducky-preset-select');
        select.innerHTML = '<option value="">Load Preset Payload...</option>' + 
          duckyPresets.map(p => `<option value="${p.id}">${p.title}</option>`).join('');
      } catch (err) {
        console.error('Failed to load ducky presets', err);
      }
    }

    function loadSelectedPreset() {
      const id = document.getElementById('ducky-preset-select').value;
      const preset = duckyPresets.find(p => p.id === id);
      const descEl = document.getElementById('ducky-preset-desc');
      if (preset) {
        document.getElementById('ducky-editor').value = preset.template;
        descEl.innerText = preset.description || '';
        descEl.classList.remove('hidden');
        showToast(`Loaded preset: ${preset.title}`, 'ducky');
      } else {
        descEl.classList.add('hidden');
      }
    }

    function insertDuckySnippet(snippet) {
      const editor = document.getElementById('ducky-editor');
      editor.value += (editor.value ? '\n' : '') + snippet;
      editor.focus();
    }

    function clearDuckyLogs() {
      document.getElementById('ducky-output-console').innerHTML = '<div class="text-gray-500 italic">Payload output & step timeline will stream here.</div>';
      document.getElementById('ducky-step-counter').innerText = '0 steps';
    }

    function handleDuckyEditorKey(e) {
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        e.preventDefault();
        runDuckyScript();
      }
    }

    async function runPresetDucky(presetId) {
      setTab('ducky');
      const preset = duckyPresets.find(p => p.id === presetId);
      if (preset) {
        document.getElementById('ducky-editor').value = preset.template;
        document.getElementById('ducky-preset-select').value = presetId;
      }
      runDuckyScript();
    }

    async function runDuckyScript() {
      const script = document.getElementById('ducky-editor').value.trim();
      const target = document.getElementById('ducky-target').value;
      const out = document.getElementById('ducky-output-console');
      const btn = document.getElementById('ducky-run-btn');

      if (!script) {
        showToast('Please enter DuckyScript commands to run.', 'warning');
        return;
      }

      btn.disabled = true;
      showToast('Executing DuckyScript payload...', 'ducky');
      out.innerHTML = '<div class="text-amber-400 animate-pulse flex items-center space-x-2"><span>⏳</span><span>Running DuckyScript execution pipeline...</span></div>';

      try {
        const res = await fetch('/api/ducky/run', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({script: script, target: target})
        });
        const data = await res.json();
        
        if (data.ok) {
          const steps = data.executed_steps || [];
          document.getElementById('ducky-step-counter').innerText = `${steps.length} steps executed`;
          
          out.innerHTML = `
            <div class="text-emerald-400 font-bold flex items-center space-x-1 mb-2">
              <span>✔</span><span>${data.summary}</span>
            </div>
            <div class="space-y-1 pl-1 border-l-2 border-emerald-800">
              ${steps.map((st, i) => `
                <div class="flex items-center space-x-2 text-gray-300">
                  <span class="text-gray-500 font-mono text-[10px]">#${i+1}</span>
                  <span class="text-emerald-300 font-mono">${st}</span>
                </div>
              `).join('')}
            </div>
          `;
          showToast(`DuckyScript executed ${steps.length} steps!`, 'success');
          refreshLiveBrowser();
        } else {
          out.innerHTML = `<div class="text-rose-400 font-bold">❌ Error: ${data.error}</div>`;
          showToast(`DuckyScript error: ${data.error}`, 'error');
        }
      } catch (err) {
        out.innerHTML = `<div class="text-rose-400 font-bold">❌ Error: ${err.message}</div>`;
        showToast(`Execution failed: ${err.message}`, 'error');
      } finally {
        btn.disabled = false;
      }
    }

    // --- ENGINES ROUTER LOGIC ---
    async function loadEngines() {
      const el = document.getElementById('engines-list');
      try {
        const res = await fetch('/api/engines');
        const data = await res.json();
        availableEngines = data.engines;
        activeEngine = data.active.engine;

        document.getElementById('header-engine-label').innerText = data.active_engine_name || 'Ollama';
        document.getElementById('header-engine-icon').innerText = data.active_engine_icon || '🦙';

        el.innerHTML = availableEngines.map(e => {
          const isActive = e.id === activeEngine;
          return `
            <div onclick="selectEngine('${e.id}')" class="p-3.5 rounded-2xl border cursor-pointer transition ${isActive ? 'bg-blue-50/90 border-gblue shadow-m3-1' : 'bg-white border-gborder hover:border-gray-300 shadow-2xs'}">
              <div class="flex items-center justify-between">
                <div class="flex items-center space-x-2.5">
                  <span class="text-xl">${e.icon}</span>
                  <div>
                    <h4 class="font-bold text-gdark text-xs">${e.name}</h4>
                    <span class="text-[10px] text-gsub">${e.type === 'cli' ? 'CLI Agent Binary' : 'Direct API Model'}</span>
                  </div>
                </div>
                <span class="text-[10px] font-bold px-2 py-0.5 rounded-full ${e.available ? 'bg-emerald-100 text-ggreen' : 'bg-gray-100 text-gray-400'}">${e.badge}</span>
              </div>
              <p class="text-[11px] text-gsub mt-2">${e.type === 'cli' ? 'Path: ' + (e.path || 'System PATH') : (e.models ? e.models.slice(0, 3).join(', ') : 'Direct Endpoint')}</p>
              ${isActive ? '<div class="text-[11px] text-gblue font-bold mt-2 flex items-center space-x-1"><span>✔ Currently Active Agent</span></div>' : ''}
            </div>
          `;
        }).join('');
      } catch (err) {
        el.innerHTML = '<div class="text-gred p-3 text-xs">Failed to scan engine status.</div>';
      }
    }

    async function selectEngine(engineId) {
      try {
        const res = await fetch('/api/engine/set', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({engine: engineId})
        });
        const data = await res.json();
        if (data.ok) {
          showToast(`Switched active engine to ${engineId.toUpperCase()}`, 'engine');
          loadEngines();
        }
      } catch (err) {
        showToast('Error setting engine: ' + err.message, 'error');
      }
    }

    async function openConfigModal() {
      const modal = document.getElementById('config-modal');
      modal.classList.remove('hidden');
      document.getElementById('cfg-save-status').innerText = 'Loading configuration...';
      try {
        const res = await fetch('/api/config');
        const data = await res.json();
        if (data.ok) {
          const cfg = data.configs || {};
          document.getElementById('cfg-xai-key').value = '';
          document.getElementById('cfg-xai-key').placeholder = cfg.XAI_API_KEY ? `Current: ${cfg.XAI_API_KEY}` : 'xai-...';
          document.getElementById('cfg-openai-key').value = '';
          document.getElementById('cfg-openai-key').placeholder = cfg.OPENAI_API_KEY ? `Current: ${cfg.OPENAI_API_KEY}` : 'sk-...';
          document.getElementById('cfg-anthropic-key').value = '';
          document.getElementById('cfg-anthropic-key').placeholder = cfg.ANTHROPIC_API_KEY ? `Current: ${cfg.ANTHROPIC_API_KEY}` : 'sk-ant-...';
          document.getElementById('cfg-gemini-key').value = '';
          document.getElementById('cfg-gemini-key').placeholder = cfg.GEMINI_API_KEY ? `Current: ${cfg.GEMINI_API_KEY}` : 'AIza...';
          document.getElementById('cfg-openrouter-key').value = '';
          document.getElementById('cfg-openrouter-key').placeholder = cfg.OPENROUTER_API_KEY ? `Current: ${cfg.OPENROUTER_API_KEY}` : 'sk-or-...';
          document.getElementById('cfg-base-url').value = cfg.OPENAI_BASE_URL || '';
          document.getElementById('cfg-model').value = cfg.MODEL || '';
          document.getElementById('cfg-save-status').innerText = '';
        }
      } catch (err) {
        document.getElementById('cfg-save-status').innerText = 'Failed to load configs: ' + err.message;
      }
    }

    function closeConfigModal() {
      document.getElementById('config-modal').classList.add('hidden');
    }

    async function saveConfigKeys() {
      const updates = {};
      const xai = document.getElementById('cfg-xai-key').value.trim();
      if (xai) updates['XAI_API_KEY'] = xai;
      const openai = document.getElementById('cfg-openai-key').value.trim();
      if (openai) updates['OPENAI_API_KEY'] = openai;
      const anthropic = document.getElementById('cfg-anthropic-key').value.trim();
      if (anthropic) updates['ANTHROPIC_API_KEY'] = anthropic;
      const gemini = document.getElementById('cfg-gemini-key').value.trim();
      if (gemini) updates['GEMINI_API_KEY'] = gemini;
      const openrouter = document.getElementById('cfg-openrouter-key').value.trim();
      if (openrouter) updates['OPENROUTER_API_KEY'] = openrouter;

      const baseUrl = document.getElementById('cfg-base-url').value.trim();
      if (baseUrl) updates['OPENAI_BASE_URL'] = baseUrl;
      const model = document.getElementById('cfg-model').value.trim();
      if (model) updates['MODEL'] = model;

      const statusEl = document.getElementById('cfg-save-status');
      statusEl.innerText = 'Saving configuration to .env...';

      try {
        const res = await fetch('/api/config/save', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({updates: updates})
        });
        const data = await res.json();
        if (data.ok) {
          showToast('Configuration saved and applied!', 'success');
          closeConfigModal();
          loadEngines();
        } else {
          statusEl.innerText = 'Error saving config';
        }
      } catch (err) {
        statusEl.innerText = 'Error: ' + err.message;
      }
    }

    // --- WORKSPACE & FILE EDITING LOGIC ---
    async function loadWorkspace() {
      const el = document.getElementById('workspace-file-list');
      try {
        const res = await fetch('/api/workspace');
        const data = await res.json();
        if (!data.entries || data.entries.length === 0) {
          el.innerHTML = '<div class="text-gray-400 italic p-3 text-center">Workspace is empty. Click "+ New File" to create one.</div>';
          return;
        }
        el.innerHTML = data.entries.map(e => `
          <div onclick="openFileModal('${e.name}')" class="flex items-center justify-between p-3 bg-gray-50 hover:bg-gray-100 rounded-2xl border border-gborder cursor-pointer transition shadow-2xs">
            <span class="${e.is_dir ? 'text-amber-700 font-semibold' : 'text-gdark font-medium'}">${e.is_dir ? '📁 ' : '📄 '} ${e.name}</span>
            <span class="text-gsub text-[10px]">${e.size_bytes ? e.size_bytes + ' B' : ''}</span>
          </div>
        `).join('');
      } catch (err) {
        el.innerHTML = '<div class="text-gred p-2">Failed to load files</div>';
      }
    }

    async function openFileModal(filename) {
      currentEditingPath = filename;
      document.getElementById('modal-file-name').innerText = filename;
      try {
        const res = await fetch(`/api/workspace/file?path=${encodeURIComponent(filename)}`);
        const data = await res.json();
        document.getElementById('modal-file-content').value = data.content || '';
        document.getElementById('file-modal').classList.remove('hidden');
        document.getElementById('modal-file-content').focus();
      } catch (err) {
        showToast('Error reading file: ' + err.message, 'error');
      }
    }

    function promptCreateFile() {
      const name = prompt("Enter new filename (e.g. script.py, data.json, notes.md):");
      if (!name) return;
      currentEditingPath = name;
      document.getElementById('modal-file-name').innerText = name;
      document.getElementById('modal-file-content').value = '';
      document.getElementById('file-modal').classList.remove('hidden');
    }

    function closeFileModal() {
      document.getElementById('file-modal').classList.add('hidden');
    }

    function handleFileEditorKey(e) {
      if ((e.ctrlKey || e.metaKey) && e.key === 's') {
        e.preventDefault();
        saveCurrentFile();
      } else if (e.key === 'Escape') {
        closeFileModal();
      }
    }

    async function saveCurrentFile() {
      const content = document.getElementById('modal-file-content').value;
      try {
        await fetch('/api/workspace/file', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({path: currentEditingPath, content: content})
        });
        showToast(`File saved: ${currentEditingPath}`, 'success');
        closeFileModal();
        loadWorkspace();
      } catch (err) {
        showToast('Error saving file: ' + err.message, 'error');
      }
    }

    async function deleteCurrentFile() {
      if (!confirm(`Are you sure you want to delete ${currentEditingPath}?`)) return;
      try {
        await fetch('/api/workspace/file/delete', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({path: currentEditingPath})
        });
        showToast(`Deleted file: ${currentEditingPath}`, 'warning');
        closeFileModal();
        loadWorkspace();
      } catch (err) {
        showToast('Error deleting file: ' + err.message, 'error');
      }
    }

    // --- CHAT LOGIC (SSE Streaming) ---
    function handleChatInputKey(e) {
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        e.preventDefault();
        sendMessage();
      }
    }

    // Active SSE abort controller (one at a time)
    let _activeSseController = null;

    async function sendMessage(e) {
      if (e) e.preventDefault();
      const input = document.getElementById('user-input');
      const text = input.value.trim();
      if (!text) return;

      // Abort any in-progress stream
      if (_activeSseController) {
        _activeSseController.abort();
        _activeSseController = null;
      }

      appendMessage('user', text);
      input.value = '';

      const btn = document.getElementById('send-btn');
      btn.disabled = true;

      // Create the bot bubble (empty, will fill as tokens stream in)
      const bubbleId = appendStreamingMessage();

      const controller = new AbortController();
      _activeSseController = controller;

      try {
        const res = await fetch('/api/chat/stream', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({message: text}),
          signal: controller.signal,
        });

        if (!res.ok) {
          const errData = await res.json().catch(() => ({error: 'Stream failed'}));
          updateStreamingMessage(bubbleId, '', `Error: ${errData.error || res.statusText}`, null, null);
          return;
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let accumulatedText = '';
        let thinkingText = null;
        let toolCards = [];  // [{name, args, summary, done}]

        while (true) {
          const {done, value} = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, {stream: true});
          const lines = buffer.split('\n');
          buffer = lines.pop(); // last potentially-incomplete line

          let eventType = null;
          let dataLine = null;

          for (const line of lines) {
            if (line.startsWith('event: ')) {
              eventType = line.slice(7).trim();
            } else if (line.startsWith('data: ')) {
              dataLine = line.slice(6).trim();
            } else if (line === '' && eventType && dataLine !== null) {
              // Dispatch SSE event
              let payload;
              try { payload = JSON.parse(dataLine); } catch { payload = {}; }

              if (eventType === 'token') {
                accumulatedText += payload.text || '';
                renderStreamingBubble(bubbleId, accumulatedText, thinkingText, toolCards);
              } else if (eventType === 'think') {
                thinkingText = payload.text || '';
                renderStreamingBubble(bubbleId, accumulatedText, thinkingText, toolCards);
              } else if (eventType === 'tool') {
                toolCards.push({name: payload.name, args: payload.args, summary: null, done: false});
                renderStreamingBubble(bubbleId, accumulatedText, thinkingText, toolCards);
              } else if (eventType === 'tool_done') {
                const card = toolCards.find(c => c.name === payload.name && !c.done);
                if (card) { card.done = true; card.summary = payload.summary; }
                renderStreamingBubble(bubbleId, accumulatedText, thinkingText, toolCards);
              } else if (eventType === 'done') {
                // Final render with metadata
                updateStreamingMessage(bubbleId, accumulatedText, null, thinkingText, toolCards);
                loadWorkspace();
                refreshLiveBrowser();
              } else if (eventType === 'error') {
                updateStreamingMessage(bubbleId, accumulatedText,
                  `⚠️ ${payload.message || 'Unknown error'}`, thinkingText, toolCards);
              }
              eventType = null;
              dataLine = null;
            }
          }
        }
      } catch (err) {
        if (err.name !== 'AbortError') {
          updateStreamingMessage(bubbleId, '', `Error: ${err.message}`, null, null);
        }
      } finally {
        btn.disabled = false;
        _activeSseController = null;
      }
    }

    function _buildToolCardHtml(toolCards) {
      if (!toolCards || toolCards.length === 0) return '';
      const TOOL_ICONS = {
        browser_navigate: '🌐', browser_click: '🖱️', browser_type: '⌨️',
        browser_extract: '📄', browser_search: '🔍', browser_screenshot: '📸',
        browser_login: '🔑', browser_check_auth: '🔒', run_python: '🐍',
        deep_search: '🔬', search_x: '🐦', scout_x_trends: '📈',
        vm_exec: '⚙️', vm_install: '📦', read_file: '📂', write_file: '💾',
      };
      return `
        <div class="flex flex-col gap-1.5 mb-3">
          ${toolCards.map(c => {
            const icon = TOOL_ICONS[c.name] || '⚡';
            const argsPreview = Object.entries(c.args || {}).slice(0, 2)
              .map(([k, v]) => `${k}=${JSON.stringify(v).slice(0, 30)}`).join(', ');
            return c.done ? `
              <div class="flex items-center space-x-2 bg-emerald-50 border border-emerald-200 px-3 py-1.5 rounded-xl text-[11px] text-emerald-800">
                <span>${icon}</span>
                <span class="font-semibold">${c.name}</span>
                <span class="text-emerald-600 flex-1 truncate">(${argsPreview || 'no args'})</span>
                <span class="text-[10px] bg-emerald-100 px-1.5 py-0.5 rounded-full font-medium ml-auto truncate max-w-[120px]">✔ ${c.summary || 'Done'}</span>
              </div>
            ` : `
              <div class="flex items-center space-x-2 bg-blue-50 border border-blue-200 px-3 py-1.5 rounded-xl text-[11px] text-blue-800 animate-pulse">
                <span>${icon}</span>
                <span class="font-semibold">${c.name}</span>
                <span class="text-blue-500 flex-1 truncate">(${argsPreview || 'running...'})</span>
                <div class="w-3 h-3 rounded-full border-2 border-blue-400 border-t-transparent animate-spin ml-auto shrink-0"></div>
              </div>
            `;
          }).join('')}
        </div>
      `;
    }

    function appendStreamingMessage() {
      const chat = document.getElementById('chat-box');
      const id = 'msg-' + Date.now();
      const div = document.createElement('div');
      div.className = 'flex items-start space-x-4 text-sm';
      div.innerHTML = `
        <div class="chat-bot-icon w-8 h-8 flex items-center justify-center text-white text-xs font-bold shadow-sm transition-all shrink-0">aZ</div>
        <div class="bg-white border border-gborder rounded-3xl rounded-tl-sm px-6 py-4 max-w-[85%] text-gtext shadow-sm leading-relaxed flex flex-col space-y-2 flex-1">
          <div id="${id}-tools"></div>
          <div id="${id}-think"></div>
          <div id="${id}" class="markdown-body message-bubble">
            <span class="inline-flex items-center space-x-1.5 text-gsub text-xs">
              <span class="w-1.5 h-1.5 rounded-full bg-purple-500 animate-ping"></span>
              <span>Thinking...</span>
            </span>
          </div>
          <div id="${id}-meta" class="pt-2 border-t border-gborderLight flex items-center justify-between text-[11px] text-gsub hidden">
            <span class="font-mono text-[10px]">aZoth • ${activeEngine.toUpperCase()} • ${activeMode.toUpperCase()}</span>
            <button onclick="copyMessageText(this)" class="hover:text-gblue transition flex items-center space-x-1">
              <span>📋</span><span>Copy Response</span>
            </button>
          </div>
        </div>
      `;
      chat.appendChild(div);
      chat.scrollTop = chat.scrollHeight;
      applyBotTheme();
      return id;
    }

    function renderStreamingBubble(id, text, thinking, toolCards) {
      const el = document.getElementById(id);
      const toolsEl = document.getElementById(id + '-tools');
      const thinkEl = document.getElementById(id + '-think');

      if (toolsEl) toolsEl.innerHTML = _buildToolCardHtml(toolCards);

      if (thinkEl && thinking) {
        thinkEl.innerHTML = `
          <details class="mb-3 rounded-2xl bg-amber-50/80 border border-amber-200/90 p-3 text-xs text-amber-950 shadow-2xs">
            <summary class="cursor-pointer font-semibold flex items-center space-x-2 text-amber-900 select-none">
              <span class="animate-pulse">🧠</span>
              <span>Grok-Style Thought Process</span>
              <span class="text-[10px] bg-amber-200/70 px-2 py-0.5 rounded-full ml-auto">Click to expand</span>
            </summary>
            <div class="mt-2 pt-2 border-t border-amber-200/60 font-mono text-[11px] leading-relaxed whitespace-pre-wrap">${escapeHtml(thinking)}</div>
          </details>
        `;
      }

      if (el) {
        if (text) {
          el.innerHTML = renderMarkdown(text) + '<span class="inline-block w-0.5 h-4 bg-purple-500 animate-pulse ml-0.5 align-middle"></span>';
        }
        const chat = document.getElementById('chat-box');
        chat.scrollTop = chat.scrollHeight;
      }
    }

    function updateStreamingMessage(id, text, errorMsg, thinking, toolCards) {
      const el = document.getElementById(id);
      const toolsEl = document.getElementById(id + '-tools');
      const thinkEl = document.getElementById(id + '-think');
      const metaEl = document.getElementById(id + '-meta');

      if (toolsEl) toolsEl.innerHTML = _buildToolCardHtml(toolCards);

      if (thinkEl && thinking) {
        thinkEl.innerHTML = `
          <details class="mb-3 rounded-2xl bg-amber-50/80 border border-amber-200/90 p-3 text-xs text-amber-950 shadow-2xs">
            <summary class="cursor-pointer font-semibold flex items-center space-x-2 text-amber-900 select-none">
              <span>🧠</span><span>Grok-Style Thought Process</span>
              <span class="text-[10px] bg-amber-200/70 px-2 py-0.5 rounded-full ml-auto">Click to expand</span>
            </summary>
            <div class="mt-2 pt-2 border-t border-amber-200/60 font-mono text-[11px] leading-relaxed whitespace-pre-wrap">${escapeHtml(thinking)}</div>
          </details>
        `;
      }

      if (el) {
        if (errorMsg) {
          el.innerHTML = `<span class="text-gred font-semibold text-xs">${escapeHtml(errorMsg)}</span>`;
        } else if (text) {
          el.innerHTML = renderMarkdown(text);
        } else {
          el.innerHTML = '<span class="text-gsub italic text-xs">(no response)</span>';
        }
        const chat = document.getElementById('chat-box');
        chat.scrollTop = chat.scrollHeight;
      }

      if (metaEl) metaEl.classList.remove('hidden');
    }

    function appendMessage(role, rawContent) {
      const chat = document.getElementById('chat-box');
      const id = 'msg-' + Date.now();
      const isUser = role === 'user';
      const div = document.createElement('div');
      div.className = isUser ? 'flex items-start justify-end space-x-3 text-sm' : 'flex items-start space-x-4 text-sm';
      const formattedContent = isUser ? escapeHtml(rawContent) : renderMarkdown(rawContent);
      div.innerHTML = isUser ? `
        <div class="bg-gblue text-white rounded-3xl rounded-tr-sm px-5 py-3.5 max-w-[80%] shadow-m3-1 leading-relaxed">${formattedContent}</div>
        <div class="w-8 h-8 rounded-full bg-gray-200 text-gdark flex items-center justify-center font-bold text-xs shrink-0 shadow-2xs">You</div>
      ` : `
        <div class="chat-bot-icon w-8 h-8 flex items-center justify-center text-white text-xs font-bold shadow-sm transition-all shrink-0">aZ</div>
        <div class="bg-white border border-gborder rounded-3xl rounded-tl-sm px-6 py-4 max-w-[85%] text-gtext shadow-sm leading-relaxed flex flex-col space-y-2">
          <div id="${id}" class="markdown-body message-bubble">${formattedContent}</div>
          <div class="pt-2 border-t border-gborderLight flex items-center justify-between text-[11px] text-gsub">
            <span class="font-mono text-[10px]">aZoth • ${activeEngine.toUpperCase()} • ${activeMode.toUpperCase()}</span>
            <button onclick="copyMessageText(this)" class="hover:text-gblue transition flex items-center space-x-1">
              <span>📋</span><span>Copy Response</span>
            </button>
          </div>
        </div>
      `;
      chat.appendChild(div);
      chat.scrollTop = chat.scrollHeight;
      applyBotTheme();
      return id;
    }

    function updateMessage(id, rawContent, thinking, meta) {
      const el = document.getElementById(id);
      if (el) {
        let html = '';
        if (thinking) {
          html += `
            <details class="mb-3 rounded-2xl bg-amber-50/80 border border-amber-200/90 p-3 text-xs text-amber-950 shadow-2xs group select-text">
              <summary class="cursor-pointer font-semibold flex items-center space-x-2 text-amber-900 select-none">
                <span class="animate-pulse">🧠</span>
                <span>Grok-Style Thought Process</span>
                <span class="text-[10px] bg-amber-200/70 text-amber-900 px-2 py-0.5 rounded-full ml-auto group-open:hidden">Click to expand</span>
              </summary>
              <div class="mt-2.5 pt-2 border-t border-amber-200/60 font-mono text-[11px] leading-relaxed whitespace-pre-wrap">${escapeHtml(thinking)}</div>
            </details>
          `;
        }
        html += renderMarkdown(rawContent);
        el.innerHTML = html;
        const chat = document.getElementById('chat-box');
        chat.scrollTop = chat.scrollHeight;
      }
    }

    async function clearChat() {
      if (!confirm('Are you sure you want to clear conversation history?')) return;
      try {
        await fetch('/api/chat/clear', { method: 'POST' });
        const chat = document.getElementById('chat-box');
        chat.innerHTML = '';
        showToast('Chat history reset.', 'info');
      } catch (err) {
        console.error('Failed to clear chat', err);
      }
    }

    function setTab(tab) {
      ['browser', 'terminal', 'ducky', 'engines', 'workspace', 'customizer', 'topology'].forEach(t => {
        const el = document.getElementById('tab-' + t);
        const btn = document.getElementById('tab-btn-' + t);
        const isActive = t === tab;
        if (el) el.classList.toggle('hidden', !isActive);
        if (btn) {
          if (isActive) {
            btn.className = 'flex-1 py-3 text-gblue border-b-2 border-gblue bg-white font-bold flex items-center justify-center space-x-1 transition';
          } else {
            btn.className = 'flex-1 py-3 text-gsub hover:text-gdark border-b-2 border-transparent flex items-center justify-center space-x-1 transition';
          }
        }
      });
      if (tab === 'browser') refreshLiveBrowser();
      if (tab === 'terminal') initTerminal();
      if (tab === 'ducky') loadDuckyPresets();
      if (tab === 'workspace') loadWorkspace();
      if (tab === 'engines') loadEngines();
      if (tab === 'customizer') setTimeout(initMascotParticles, 100);
      if (tab === 'topology') { initTopology(); drawTopology(); }
    }

    // Interactive Web Terminal & Guest OS Controller
    let term = null;
    let fitAddon = null;
    let termSocket = null;
    let termInitialized = false;

    function initTerminal() {
      if (termInitialized) {
        if (fitAddon) {
          setTimeout(() => { try { fitAddon.fit(); } catch(e) {} }, 100);
        }
        refreshVMStatus();
        return;
      }
      termInitialized = true;

      const container = document.getElementById('terminal-box');
      if (!container) return;

      term = new Terminal({
        cursorBlink: true,
        cursorStyle: 'block',
        fontFamily: '"Roboto Mono", SFMono-Regular, Menlo, Monaco, Consolas, monospace',
        fontSize: 12.5,
        lineHeight: 1.25,
        theme: {
          background: '#090d16',
          foreground: '#e5e7eb',
          cursor: '#22d3ee',
          cursorAccent: '#090d16',
          selectionBackground: '#1e3a8a',
          black: '#1f2937',
          red: '#ef4444',
          green: '#10b981',
          yellow: '#f59e0b',
          blue: '#3b82f6',
          magenta: '#a855f7',
          cyan: '#06b6d4',
          white: '#f3f4f6',
          brightBlack: '#4b5563',
          brightRed: '#f87171',
          brightGreen: '#34d399',
          brightYellow: '#fbbf24',
          brightBlue: '#60a5fa',
          brightMagenta: '#c084fc',
          brightCyan: '#22d3ee',
          brightWhite: '#ffffff'
        }
      });

      if (window.FitAddon && window.FitAddon.FitAddon) {
        fitAddon = new window.FitAddon.FitAddon();
        term.loadAddon(fitAddon);
      }

      term.open(container);
      if (fitAddon) {
        setTimeout(() => { try { fitAddon.fit(); } catch(e) {} }, 150);
      }

      connectTerminalSocket();
      refreshVMStatus();

      window.addEventListener('resize', () => {
        if (fitAddon && termSocket && termSocket.readyState === WebSocket.OPEN) {
          try {
            fitAddon.fit();
            termSocket.send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }));
          } catch(e) {}
        }
      });

      term.onData(data => {
        if (termSocket && termSocket.readyState === WebSocket.OPEN) {
          termSocket.send(data);
        }
      });
    }

    function connectTerminalSocket() {
      const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
      const url = `${protocol}//${location.host}/ws/terminal`;
      
      if (termSocket) {
        try { termSocket.close(); } catch(e) {}
      }

      termSocket = new WebSocket(url);

      termSocket.onopen = () => {
        updateTerminalStatus(true, 'Guest OS: Running');
        if (fitAddon && term) {
          try {
            fitAddon.fit();
            termSocket.send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }));
          } catch(e) {}
        }
      };

      termSocket.onmessage = (event) => {
        if (term) term.write(event.data);
      };

      termSocket.onclose = () => {
        updateTerminalStatus(false, 'Guest OS: Disconnected');
        if (term) term.write('\r\n\x1b[33m⚡ [Session disconnected. Click Reconnect to restart terminal.]\x1b[0m\r\n');
      };

      termSocket.onerror = (err) => {
        console.error('Terminal WebSocket error:', err);
        updateTerminalStatus(false, 'Connection Error');
      };
    }

    function sendTerminalCmd(cmd) {
      if (termSocket && termSocket.readyState === WebSocket.OPEN) {
        termSocket.send(cmd);
        if (term) term.focus();
      } else {
        reconnectTerminal();
        setTimeout(() => {
          if (termSocket && termSocket.readyState === WebSocket.OPEN) {
            termSocket.send(cmd);
          }
        }, 600);
      }
    }

    function clearTerminalScreen() {
      if (term) {
        term.clear();
        sendTerminalCmd('clear\n');
      }
    }

    function reconnectTerminal() {
      if (term) {
        term.reset();
      }
      connectTerminalSocket();
      refreshVMStatus();
    }

    async function refreshVMStatus() {
      try {
        const res = await fetch('/api/vm/status');
        const data = await res.json();
        if (data) {
          const distroEl = document.getElementById('terminal-distro');
          const memEl = document.getElementById('terminal-memory');
          const diskEl = document.getElementById('terminal-disk');
          const badgeEl = document.getElementById('terminal-backend-badge');
          if (distroEl) distroEl.textContent = data.os_release || data.hostname || 'Debian 12';
          if (memEl) memEl.textContent = data.memory || 'Active';
          if (diskEl) diskEl.textContent = data.disk ? data.disk.split(' ')[0] + ' ' + data.disk.split(' ')[1] : '/workspace';
          if (badgeEl) badgeEl.textContent = (data.backend || 'docker').toUpperCase();
          updateTerminalStatus(data.running, data.running ? 'Guest OS: Running' : 'Stopped');
        }
      } catch (err) {
        console.warn('Failed to load VM status', err);
      }
    }

    function updateTerminalStatus(online, label) {
      const dot = document.getElementById('terminal-status-dot');
      const text = document.getElementById('terminal-status-text');
      if (dot) {
        dot.className = online ? 'w-2.5 h-2.5 rounded-full bg-emerald-400 animate-pulse' : 'w-2.5 h-2.5 rounded-full bg-red-400';
      }
      if (text) {
        text.textContent = label;
      }
    }

    async function restartGuestOS() {
      showToast('Restarting Guest OS environment...', 'info');
      try {
        const res = await fetch('/api/vm/restart', { method: 'POST' });
        const data = await res.json();
        if (data.success) {
          showToast('Guest OS restarted successfully!', 'success');
          setTimeout(() => {
            reconnectTerminal();
            refreshVMStatus();
          }, 800);
        } else {
          showToast('Restart failed: ' + (data.error || 'Unknown error'), 'error');
        }
      } catch (err) {
        showToast('Failed to restart Guest OS: ' + err.message, 'error');
      }
    }

    // Global Keyboard Listeners
    window.addEventListener('keydown', (e) => {
      // Ctrl+K / Cmd+K -> Command Palette
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        openCommandPalette();
      }
      // Escape closes any open modal
      if (e.key === 'Escape') {
        closeCommandPalette();
        closeFileModal();
        closeConfigModal();
        closeSmartLoginModal();
      }
      // Ctrl+1 through Ctrl+6 for quick tabs
      if ((e.ctrlKey || e.metaKey) && ['1', '2', '3', '4', '5', '6'].includes(e.key)) {
        e.preventDefault();
        const tabs = ['browser', 'terminal', 'ducky', 'engines', 'workspace', 'customizer'];
        setTab(tabs[parseInt(e.key) - 1]);
      }
      // Ctrl+W -> Toggle Waveform
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'w') {
        e.preventDefault();
        toggleWaveform();
      }
      // Ctrl+S -> Toggle Stealth Mode
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
        e.preventDefault();
        toggleStealthMode();
      }
      // Ctrl+L -> Toggle Scan Lines
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'l') {
        e.preventDefault();
        toggleScanline();
      }
    });

    // Auto-refresh browser every 2.5s if browser tab is active
    setInterval(() => {
      const bTab = document.getElementById('tab-browser');
      if (bTab && !bTab.classList.contains('hidden')) {
        refreshLiveBrowser();
      }
    }, 2500);

    // Initial Bootstrap
    loadModes();
    loadEngines();
    loadDuckyPresets();
    applyBotTheme();
    refreshLiveBrowser();
    setTimeout(initMascotParticles, 300);

    // --- WAVEFORM INDICATOR ---
    let waveformActive = false;
    let waveformAnimId = null;
    let waveformTime = 0;

    function toggleWaveform() {
      waveformActive = !waveformActive;
      const btn = document.getElementById('waveform-btn');
      if (waveformActive) {
        btn.classList.add('bg-blue-50', 'border-blue-300');
        startWaveform();
      } else {
        btn.classList.remove('bg-blue-50', 'border-blue-300');
        stopWaveform();
      }
    }

    function startWaveform() {
      const canvas = document.createElement('canvas');
      canvas.id = 'waveform-canvas';
      canvas.width = 120;
      canvas.height = 24;
      canvas.className = 'inline-block align-middle';
      const existing = document.getElementById('waveform-canvas');
      if (existing) existing.remove();
      const btn = document.getElementById('waveform-btn');
      if (btn) btn.appendChild(canvas);
      drawWaveform();
    }

    function stopWaveform() {
      const canvas = document.getElementById('waveform-canvas');
      if (canvas) canvas.remove();
      if (waveformAnimId) cancelAnimationFrame(waveformAnimId);
    }

    function drawWaveform() {
      if (!waveformActive) return;
      const canvas = document.getElementById('waveform-canvas');
      if (!canvas) return;
      const ctx = canvas.getContext('2d');
      const w = canvas.width;
      const h = canvas.height;
      ctx.clearRect(0, 0, w, h);

      // Draw background bars
      const barCount = 20;
      const barWidth = w / barCount;
      for (let i = 0; i < barCount; i++) {
        const val = Math.abs(Math.sin(waveformTime * 0.08 + i * 0.3)) * 0.6 + Math.abs(Math.sin(waveformTime * 0.13 + i * 0.7)) * 0.4;
        const barH = Math.max(2, val * (h - 4));
        const x = i * barWidth + 1;
        const y = (h - barH) / 2;
        const gradient = ctx.createLinearGradient(x, y, x, y + barH);
        gradient.addColorStop(0, '#1a73e8');
        gradient.addColorStop(1, '#06b6d4');
        ctx.fillStyle = gradient;
        ctx.fillRect(x, y, barWidth - 2, barH);
      }

      // Draw waveform line
      ctx.beginPath();
      ctx.strokeStyle = '#7c3aed';
      ctx.lineWidth = 1.2;
      for (let x = 0; x < w; x++) {
        const y = h / 2 + Math.sin((x + waveformTime * 3) * 0.06) * 4 + Math.sin((x + waveformTime * 5) * 0.04) * 2;
        if (x === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();

      waveformTime++;
      waveformAnimId = requestAnimationFrame(drawWaveform);
    }

    // --- STEALTH MODE ---
    let stealthActive = false;

    function toggleStealthMode() {
      stealthActive = !stealthActive;
      document.body.classList.toggle('stealth-mode', stealthActive);
      const btn = document.getElementById('stealth-btn');
      if (stealthActive) {
        btn.classList.add('bg-red-50', 'border-red-300', 'text-red-600');
        showToast('Stealth mode ON — input area visible on focus', 'warning', 3000);
      } else {
        btn.classList.remove('bg-red-50', 'border-red-300', 'text-red-600');
        showToast('Stealth mode OFF', 'info', 1500);
      }
    }

    // --- SCAN LINE EFFECT ---
    let scanlineActive = false;

    function toggleScanline() {
      scanlineActive = !scanlineActive;
      const overlay = document.getElementById('scanline-overlay');
      const btn = document.getElementById('scanline-btn');
      overlay.classList.toggle('active', scanlineActive);
      if (scanlineActive) {
        btn.classList.add('bg-gray-800', 'text-white', 'border-gray-600');
        showToast('Scan line effect ON — CRT overlay', 'info', 1500);
      } else {
        btn.classList.remove('bg-gray-800', 'text-white', 'border-gray-600');
        showToast('Scan line effect OFF', 'info', 1500);
      }
    }

    // --- TOPOLOGY MAP ---
    let topoNodes = [];
    let topoEdges = [];
    let topoLabels = true;
    let topoDragNode = null;
    let topoDragOffset = { x: 0, y: 0 };
    let topoHoverNode = null;

    const TOPO_ICONS = {
      agent: '🤖', browser: '🌐', terminal: '💻', ducky: '🦆', engine: '⚡',
      workspace: '📁', search: '🔍', python: '🐍', vm: '⚙️', x_intel: '🐦',
      deepsearch: '🔬', config: '🔑', chat: '💬',
    };

    function initTopology() {
      topoNodes = [
        { id: 'agent', label: 'aZoth Agent', x: 0, y: 0, r: 28, type: 'agent', status: 'active' },
        { id: 'engine', label: 'Engine Router', x: 0, y: 0, r: 22, type: 'engine', status: 'active' },
        { id: 'browser', label: 'Sandbox Browser', x: 0, y: 0, r: 20, type: 'browser', status: 'active' },
        { id: 'terminal', label: 'Guest OS Terminal', x: 0, y: 0, r: 20, type: 'terminal', status: 'active' },
        { id: 'ducky', label: 'DuckyScript Studio', x: 0, y: 0, r: 18, type: 'ducky', status: 'idle' },
        { id: 'workspace', label: 'Workspace Files', x: 0, y: 0, r: 18, type: 'workspace', status: 'active' },
        { id: 'search', label: 'DeepSearch', x: 0, y: 0, r: 17, type: 'search', status: 'idle' },
        { id: 'x_intel', label: 'X Intelligence', x: 0, y: 0, r: 17, type: 'x_intel', status: 'idle' },
        { id: 'python', label: 'Python REPL', x: 0, y: 0, r: 17, type: 'python', status: 'idle' },
        { id: 'vm', label: 'Guest OS VM', x: 0, y: 0, r: 19, type: 'vm', status: 'active' },
        { id: 'config', label: 'Config Vault', x: 0, y: 0, r: 16, type: 'config', status: 'secure' },
        { id: 'chat', label: 'Chat Stream', x: 0, y: 0, r: 16, type: 'chat', status: 'active' },
      ];
      topoEdges = [
        { from: 'agent', to: 'engine', strength: 1.0 },
        { from: 'agent', to: 'browser', strength: 0.8 },
        { from: 'agent', to: 'terminal', strength: 0.9 },
        { from: 'agent', to: 'ducky', strength: 0.6 },
        { from: 'agent', to: 'workspace', strength: 0.7 },
        { from: 'agent', to: 'search', strength: 0.5 },
        { from: 'agent', to: 'x_intel', strength: 0.6 },
        { from: 'agent', to: 'python', strength: 0.7 },
        { from: 'agent', to: 'chat', strength: 1.0 },
        { from: 'engine', to: 'config', strength: 0.9 },
        { from: 'terminal', to: 'vm', strength: 1.0 },
        { from: 'browser', to: 'vm', strength: 0.7 },
        { from: 'search', to: 'x_intel', strength: 0.5 },
        { from: 'workspace', to: 'python', strength: 0.6 },
        { from: 'chat', to: 'search', strength: 0.4 },
        { from: 'chat', to: 'workspace', strength: 0.4 },
      ];
      layoutTopology();
      updateTopoStats();
    }

    function layoutTopology() {
      const cx = 0, cy = 0;
      const radius = Math.min(200, 180);
      topoNodes.forEach((node, i) => {
        if (node.id === 'agent') { node.x = cx; node.y = cy; return; }
        const angle = ((i - 1) / (topoNodes.length - 1)) * Math.PI * 2 - Math.PI / 2;
        node.x = cx + Math.cos(angle) * radius;
        node.y = cy + Math.sin(angle) * radius;
      });
    }

    function drawTopology() {
      const canvas = document.getElementById('topology-canvas');
      if (!canvas || document.getElementById('tab-topology').classList.contains('hidden')) return;
      const ctx = canvas.getContext('2d');
      const rect = canvas.parentElement.getBoundingClientRect();
      canvas.width = rect.width;
      canvas.height = rect.height;
      const w = canvas.width, h = canvas.height;

      ctx.clearRect(0, 0, w, h);

      // Draw grid
      ctx.strokeStyle = 'rgba(255,255,255,0.03)';
      ctx.lineWidth = 1;
      for (let x = 0; x < w; x += 30) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke(); }
      for (let y = 0; y < h; y += 30) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke(); }

      const cx = w / 2, cy = h / 2;
      const scale = Math.min(w, h) / 500;

      // Draw edges
      topoEdges.forEach(edge => {
        const from = topoNodes.find(n => n.id === edge.from);
        const to = topoNodes.find(n => n.id === edge.to);
        if (!from || !to) return;
        const fx = cx + from.x * scale, fy = cy + from.y * scale;
        const tx = cx + to.x * scale, ty = cy + to.y * scale;

        const grad = ctx.createLinearGradient(fx, fy, tx, ty);
        const alpha = 0.15 + edge.strength * 0.25;
        grad.addColorStop(0, `rgba(26,115,232,${alpha})`);
        grad.addColorStop(1, `rgba(124,58,237,${alpha})`);
        ctx.beginPath();
        ctx.moveTo(fx, fy);
        // Curved edges
        const mx = (fx + tx) / 2 + (fy - ty) * 0.15;
        const my = (fy + ty) / 2 + (tx - fx) * 0.15;
        ctx.quadraticCurveTo(mx, my, tx, ty);
        ctx.strokeStyle = grad;
        ctx.lineWidth = 1 + edge.strength;
        ctx.stroke();

        // Animated dot along edge
        const t = (Date.now() % 3000) / 3000;
        const dotT = t;
        const dotX = (1 - dotT) * (1 - dotT) * fx + 2 * (1 - dotT) * dotT * mx + dotT * dotT * tx;
        const dotY = (1 - dotT) * (1 - dotT) * fy + 2 * (1 - dotT) * dotT * my + dotT * dotT * ty;
        ctx.beginPath();
        ctx.arc(dotX, dotY, 2, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(6,182,212,${0.5 + edge.strength * 0.3})`;
        ctx.fill();
      });

      // Draw nodes
      topoNodes.forEach(node => {
        const nx = cx + node.x * scale;
        const ny = cy + node.y * scale;
        const isHover = topoHoverNode === node.id;
        const r = node.r * scale * (isHover ? 1.2 : 1);

        // Glow
        const glowColor = node.status === 'active' ? 'rgba(52,168,83,0.3)' : node.status === 'secure' ? 'rgba(124,58,237,0.3)' : 'rgba(251,188,4,0.3)';
        const glow = ctx.createRadialGradient(nx, ny, r * 0.5, nx, ny, r * 2);
        glow.addColorStop(0, glowColor);
        glow.addColorStop(1, 'transparent');
        ctx.fillStyle = glow;
        ctx.fillRect(nx - r * 2, ny - r * 2, r * 4, r * 4);

        // Node circle
        ctx.beginPath();
        ctx.arc(nx, ny, r, 0, Math.PI * 2);
        const nodeGrad = ctx.createRadialGradient(nx - r * 0.3, ny - r * 0.3, 0, nx, ny, r);
        if (node.status === 'active') { nodeGrad.addColorStop(0, '#34a853'); nodeGrad.addColorStop(1, '#1e7a3a'); }
        else if (node.status === 'secure') { nodeGrad.addColorStop(0, '#7c3aed'); nodeGrad.addColorStop(1, '#4c1d95'); }
        else { nodeGrad.addColorStop(0, '#fbbc04'); nodeGrad.addColorStop(1, '#b8940a'); }
        ctx.fillStyle = nodeGrad;
        ctx.fill();
        ctx.strokeStyle = isHover ? '#ffffff' : 'rgba(255,255,255,0.3)';
        ctx.lineWidth = isHover ? 2 : 1;
        ctx.stroke();

        // Icon
        ctx.font = `${Math.max(10, r * 0.7)}px sans-serif`;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(TOPO_ICONS[node.type] || '●', nx, ny);

        // Label
        if (topoLabels) {
          ctx.font = `${Math.max(8, r * 0.38)}px -apple-system, sans-serif`;
          ctx.fillStyle = 'rgba(255,255,255,0.8)';
          ctx.fillText(node.label, nx, ny + r + 12);
        }
      });

      requestAnimationFrame(drawTopology);
    }

    function toggleTopoLabels() {
      topoLabels = !topoLabels;
      const btn = document.getElementById('topo-labels-btn');
      if (btn) btn.classList.toggle('bg-blue-50', topoLabels);
    }

    function resetTopoView() {
      layoutTopology();
      topoHoverNode = null;
    }

    function updateTopoStats() {
      const activeCount = topoNodes.filter(n => n.status === 'active').length;
      const el1 = document.getElementById('topo-node-count');
      const el2 = document.getElementById('topo-edge-count');
      const el3 = document.getElementById('topo-status');
      if (el1) el1.textContent = topoNodes.length;
      if (el2) el2.textContent = topoEdges.length;
      if (el3) { el3.textContent = `${activeCount}/${topoNodes.length} active`; el3.className = `font-bold ${activeCount === topoNodes.length ? 'text-ggreen' : 'text-amber-500'}`; }
    }

    // Topology canvas mouse interaction
    (function() {
      let canvas = null;
      function getCanvas() {
        if (!canvas) canvas = document.getElementById('topology-canvas');
        return canvas;
      }
      document.addEventListener('mousemove', (e) => {
        const c = getCanvas();
        if (!c || document.getElementById('tab-topology').classList.contains('hidden')) { topoHoverNode = null; return; }
        const rect = c.getBoundingClientRect();
        const mx = e.clientX - rect.left;
        const my = e.clientY - rect.top;
        const w = c.width, h = c.height;
        const cx = w / 2, cy = h / 2;
        const scale = Math.min(w, h) / 500;
        let found = null;
        topoNodes.forEach(node => {
          const nx = cx + node.x * scale, ny = cy + node.y * scale;
          const r = node.r * scale;
          if (Math.hypot(mx - nx, my - ny) < r + 8) found = node.id;
        });
        topoHoverNode = found;
        c.style.cursor = found ? 'pointer' : 'default';

        const tooltip = document.getElementById('topo-tooltip');
        if (found && tooltip) {
          const node = topoNodes.find(n => n.id === found);
          if (node) {
            tooltip.classList.remove('hidden');
            tooltip.style.left = (mx + 16) + 'px';
            tooltip.style.top = (my - 10) + 'px';
            tooltip.innerHTML = `<div class="font-bold">${TOPO_ICONS[node.type]} ${node.label}</div><div>Status: ${node.status}</div><div>Connections: ${topoEdges.filter(e => e.from === node.id || e.to === node.id).length}</div>`;
          }
        } else if (tooltip) {
          tooltip.classList.add('hidden');
        }
      });
    })();

    // Start topology animation when tab is shown
    const origSetTab = setTab;
    setTab = function(tab) {
      origSetTab(tab);
      if (tab === 'topology') {
        initTopology();
        drawTopology();
      }
    };
  </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse(content=HTML_TEMPLATE)


@app.get("/api/engines")
def get_engines():
    engines = EngineRegistry.get_available_engines()
    active_obj = next((e for e in engines if e["id"] == active_state["engine"]), engines[0])
    return {
        "active": active_state,
        "active_engine_name": active_obj["name"],
        "active_engine_icon": active_obj.get("icon", "⚡"),
        "engines": engines,
    }


class ConfigSaveRequest(BaseModel):
    updates: dict[str, str]


@app.get("/api/config")
def config_get_endpoint():
    return {"ok": True, "configs": EnvConfigManager.get_masked_configs()}


@app.post("/api/config/save")
def config_save_endpoint(req: ConfigSaveRequest):
    success = EnvConfigManager.set_multiple(req.updates, persist=True)
    return {"ok": success, "configs": EnvConfigManager.get_masked_configs()}


@app.post("/api/engine/set")
def set_engine(req: EngineConfigRequest):
    active_state["engine"] = req.engine
    updates: dict[str, str] = {"ACTIVE_ENGINE": req.engine}
    if req.model:
        active_state["model"] = req.model
        updates["MODEL"] = req.model
    if req.api_key:
        active_state["api_key"] = req.api_key
    if req.base_url:
        active_state["base_url"] = req.base_url
    EnvConfigManager.set_multiple(updates, persist=True)
    return {"ok": True, "active": active_state}


@app.get("/api/browser/state")
async def browser_state():
    return get_browser().get_live_state()


@app.post("/api/browser/input")
async def browser_input(req: BrowserInputRequest):
    browser = get_browser()
    if req.type == "click" and req.x is not None and req.y is not None:
        return browser.mouse_click(req.x, req.y)
    elif req.type == "wheel":
        return browser.mouse_wheel(delta_y=req.delta_y or 300)
    elif req.type == "key" and req.key:
        return browser.keyboard_press(req.key)
    elif req.type == "type" and req.text:
        return browser.keyboard_type(req.text)
    elif req.type == "navigate" and req.url:
        return browser.navigate(req.url)
    elif req.type == "new_tab":
        return browser.new_tab(req.url or "https://google.com")
    elif req.type == "switch_tab" and req.tab_index is not None:
        return browser.switch_tab(req.tab_index)
    elif req.type == "close_tab" and req.tab_index is not None:
        return browser.close_tab(req.tab_index)
    elif req.type == "extract":
        return browser.extract_content(max_chars=req.delta_y or 8000)
    else:
        return {"ok": False, "error": f"Invalid input request: {req.type}"}


@app.post("/api/browser/login")
async def browser_login_endpoint(req: BrowserLoginRequest):
    return get_browser().smart_login(
        url=req.url,
        username=req.username,
        password=req.password,
        user_selector=req.user_selector,
        pass_selector=req.pass_selector,
        submit_selector=req.submit_selector,
    )


@app.post("/api/browser/check_auth")
async def browser_check_auth_endpoint(req: Optional[BrowserAuthRequest] = None):
    url = req.url if req else None
    return get_browser().check_auth(url_or_domain=url)


@app.post("/api/browser/human_click")
async def browser_human_click_endpoint(req: BrowserHumanClickRequest):
    return get_browser().human_click(selector=req.selector)


@app.post("/api/browser/human_type")
async def browser_human_type_endpoint(req: BrowserHumanTypeRequest):
    return get_browser().human_type(
        selector=req.selector,
        text=req.text,
        press_enter=req.press_enter or False,
        clear_first=req.clear_first if req.clear_first is not None else True,
    )


@app.post("/api/browser/fill_form")
async def browser_fill_form_endpoint(req: BrowserFormRequest):
    return get_browser().fill_form(fields=req.fields, submit_selector=req.submit_selector)


@app.post("/api/browser/takeover")
async def browser_takeover_endpoint(req: Optional[BrowserTakeoverRequest] = None):
    url = req.url if req else "https://x.com"
    reason = req.reason if req else ""
    return get_browser().open_takeover(url=url, reason=reason)


@app.post("/api/browser/session/export")
async def browser_session_export_endpoint(req: dict[str, Any] = None):
    filepath = req.get("filepath") if req else None
    return get_browser().export_session(filepath=filepath)


@app.post("/api/browser/session/import")
async def browser_session_import_endpoint(req: dict[str, Any] = None):
    filepath = req.get("filepath") if req else None
    return get_browser().import_session(filepath=filepath)


@app.post("/api/browser/highlight")
async def browser_highlight_endpoint(req: dict[str, Any]):
    return get_browser().highlight_element(
        selector=req.get("selector", ""),
        duration_ms=req.get("duration_ms", 2500),
        color=req.get("color", "#1a73e8"),
        label=req.get("label"),
    )


@app.get("/api/ducky/presets")
def ducky_presets_endpoint():
    return {"ok": True, "presets": DUCKY_PRESETS}


@app.post("/api/ducky/run")
def ducky_run_endpoint(req: DuckyRunRequest):
    return run_duckyscript(req.script, target=req.target)


@app.get("/api/workspace")
def workspace_files():
    return list_files(".")


@app.get("/api/workspace/file")
def workspace_file_get(path: str):
    return read_file(path)


@app.post("/api/workspace/file")
def workspace_file_save(req: FileSaveRequest):
    return write_file(req.path, req.content)


@app.post("/api/workspace/file/delete")
def workspace_file_delete(req: FileDeleteRequest):
    return delete_file(req.path)


@app.post("/api/chat")
def chat_endpoint(req: MessageRequest):
    global chat_history
    user_msg = req.message.strip()
    engine_id = active_state["engine"]
    current_mode = active_state.get("mode", "regular")

    cli_engines = ["hermes", "agy", "codex", "grok_cli", "gemini", "claude"]
    if engine_id in cli_engines:
        cli_res = execute_cli_agent(engine_id, user_msg, auto_fallback=True)
        if cli_res.get("ok"):
            output = cli_res.get("output", "")
            thinking, clean_output = extract_thinking(output)
            chat_history.append({"role": "user", "content": user_msg})
            chat_history.append({"role": "assistant", "content": output})
            return {
                "ok": True,
                "reply": clean_output or output,
                "thinking": thinking,
                "engine": engine_id,
                "mode": current_mode,
                "fallback_used": cli_res.get("fallback_used"),
            }
        else:
            err = cli_res.get("error", "CLI execution failed")
            if "402" in err or "balance exhausted" in err.lower():
                err = "Grok CLI usage balance is exhausted. Switch to local Ollama with '/engine ollama' or set an xAI key via /key XAI_API_KEY in Settings."
            return {"ok": False, "error": err}

    chat_history.append({"role": "user", "content": user_msg})
    client, model = get_client_for_engine()

    try:
        reply = agent_step(client, model, chat_history)
        thinking, clean_reply = extract_thinking(reply)
        chat_history.append({"role": "assistant", "content": reply})
        return {
            "ok": True,
            "reply": clean_reply or reply,
            "thinking": thinking,
            "engine": engine_id,
            "mode": current_mode,
        }
    except Exception as e:
        chat_history.pop()
        return {"ok": False, "error": str(e)}


@app.post("/api/chat/clear")
def chat_clear_endpoint():
    global chat_history
    current_mode = active_state.get("mode", "regular")
    chat_history = [{"role": "system", "content": build_system_prompt(current_mode)}]
    return {"ok": True}


# ---- SSE Streaming Chat ----

def _sse(event: str, data: dict) -> str:
    """Format a single SSE frame."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _stream_agent_response(user_msg: str) -> AsyncGenerator[str, None]:
    """
    SSE generator for the agentic ReAct loop.
    Emits: token | think | tool | tool_done | done | error
    """
    global chat_history
    engine_id = active_state["engine"]
    current_mode = active_state.get("mode", "regular")

    cli_engines = ["hermes", "agy", "codex", "grok_cli", "gemini", "claude"]
    if engine_id in cli_engines:
        yield _sse("token", {"text": ""})
        try:
            loop = asyncio.get_event_loop()
            cli_res = await loop.run_in_executor(
                None, lambda: execute_cli_agent(engine_id, user_msg, auto_fallback=True)
            )
        except Exception as exc:
            yield _sse("error", {"message": str(exc)})
            return

        if cli_res.get("ok"):
            output = cli_res.get("output", "")
            thinking, clean_output = extract_thinking(output)
            chat_history.append({"role": "user", "content": user_msg})
            chat_history.append({"role": "assistant", "content": output})
            if thinking:
                yield _sse("think", {"text": thinking})
            words = (clean_output or output).split(" ")
            for i, word in enumerate(words):
                chunk = word + (" " if i < len(words) - 1 else "")
                yield _sse("token", {"text": chunk})
                await asyncio.sleep(0.01)
        else:
            err = cli_res.get("error", "CLI execution failed")
            if "402" in err or "balance exhausted" in err.lower():
                err = "Grok CLI balance exhausted — switch to Ollama or add an xAI key in ⚙ Settings."
            yield _sse("error", {"message": err})
            return
        yield _sse("done", {"engine": engine_id, "mode": current_mode,
                            "fallback_used": cli_res.get("fallback_used")})
        return

    chat_history.append({"role": "user", "content": user_msg})
    client, model = get_client_for_engine()
    messages = list(chat_history)
    full_reply = ""
    max_turns = 8

    for _turn in range(max_turns):
        try:
            tool_response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: client.chat.completions.create(
                    model=model, messages=messages,
                    tools=AGENT_TOOLS, tool_choice="auto", stream=False,
                )
            )
        except Exception as exc:
            if "tool" in str(exc).lower() or "not supported" in str(exc).lower():
                try:
                    def _run_stream():
                        return client.chat.completions.create(
                            model=model, messages=messages, stream=True)
                    stream_obj = await asyncio.get_event_loop().run_in_executor(None, _run_stream)
                    collected = ""
                    for chunk in stream_obj:
                        delta = chunk.choices[0].delta.content or ""
                        if delta:
                            collected += delta
                            yield _sse("token", {"text": delta})
                    thinking, clean = extract_thinking(collected)
                    if thinking:
                        yield _sse("think", {"text": thinking})
                    full_reply = clean or collected
                except Exception as exc2:
                    yield _sse("error", {"message": str(exc2)})
                    chat_history.pop()
                    return
                break
            yield _sse("error", {"message": str(exc)})
            chat_history.pop()
            return

        msg = tool_response.choices[0].message
        tool_calls = msg.tool_calls

        if not tool_calls:
            raw_content = msg.content or ""
            thinking, clean_content = extract_thinking(raw_content)
            if thinking:
                yield _sse("think", {"text": thinking})
            words = clean_content.split(" ")
            for i, word in enumerate(words):
                chunk = word + (" " if i < len(words) - 1 else "")
                yield _sse("token", {"text": chunk})
                await asyncio.sleep(0.008)
            full_reply = clean_content
            break

        messages.append(msg.model_dump())
        for tc in tool_calls:
            fn_name = tc.function.name
            try:
                fn_args = json.loads(tc.function.arguments) if tc.function.arguments else {}
            except Exception:
                fn_args = {}

            yield _sse("tool", {"name": fn_name, "args": fn_args})

            try:
                _fn = fn_name
                _args = dict(fn_args)
                tool_result = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: execute_tool(_fn, _args)
                )
            except Exception as exc:
                tool_result = {"ok": False, "error": str(exc)}

            ok = tool_result.get("ok", True)
            summary = (
                tool_result.get("summary") or tool_result.get("title")
                or "Error: " + str(tool_result.get("error", ""))
            ) if not ok else (tool_result.get("summary") or "Done")
            yield _sse("tool_done", {"name": fn_name, "summary": summary})

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "name": fn_name,
                "content": json.dumps(tool_result, ensure_ascii=False),
            })
    else:
        full_reply = "Agent reached maximum tool iterations."
        yield _sse("token", {"text": full_reply})

    if full_reply:
        chat_history.append({"role": "assistant", "content": full_reply})

    yield _sse("done", {"engine": engine_id, "mode": current_mode})


@app.post("/api/chat/stream")
async def chat_stream_endpoint(req: MessageRequest):
    """SSE streaming chat — real-time tokens + inline tool call cards."""
    return StreamingResponse(
        _stream_agent_response(req.message.strip()),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        }
    )


@app.get("/api/modes")
def modes_endpoint():
    return {
        "ok": True,
        "modes": list_modes(),
        "active": active_state.get("mode", "regular"),
    }


@app.post("/api/mode")
def mode_switch_endpoint(req: ModeRequest):
    global chat_history
    target = req.mode.strip().lower()
    if target not in MODES:
        return {"ok": False, "error": f"Invalid mode '{target}'"}
    active_state["mode"] = target
    EnvConfigManager.set("AGENT_MODE", target, persist=True)
    chat_history = [{"role": "system", "content": build_system_prompt(target)}]
    return {
        "ok": True,
        "mode": target,
        "mode_info": get_mode(target).__dict__,
    }


@app.post("/api/deepsearch")
def deepsearch_endpoint(req: DeepSearchRequest):
    return deep_search(
        topic=req.topic,
        max_sources=req.max_sources or 6,
        fetch_top_pages=True,
    )


@app.post("/api/x/search")
def x_search_endpoint(req: XSearchRequest):
    return search_x(query=req.query, max_results=req.max_results or 8)


@app.post("/api/x/trends")
def x_trends_endpoint(topic_focus: Optional[str] = "tech"):
    return scout_x_trends(topic_focus=topic_focus or "tech")


@app.post("/api/python/run")
def python_run_endpoint(req: PythonRunRequest):
    return run_python(code=req.code, timeout_sec=req.timeout_sec or 20)


@app.get("/api/memory")
def memory_get():
    content = ""
    if MEMORY_PATH.exists():
        content = MEMORY_PATH.read_text(encoding="utf-8")
    return {"ok": True, "content": content}


# --- Guest OS & Web Terminal Endpoints ---

@app.websocket("/ws/terminal")
async def websocket_terminal(websocket: WebSocket, mode: str = "guest_os"):
    await handle_terminal_websocket(websocket, mode=mode)


@app.get("/api/vm/status")
def vm_status_endpoint():
    return guest_os.get_status()


@app.post("/api/vm/start")
def vm_start_endpoint():
    return guest_os.ensure_started()


@app.post("/api/vm/stop")
def vm_stop_endpoint():
    return guest_os.stop()


@app.post("/api/vm/restart")
def vm_restart_endpoint():
    return guest_os.restart()


@app.post("/api/vm/exec")
def vm_exec_endpoint(req: VMExecRequest):
    return guest_os.run_command(command=req.command, timeout=req.timeout or 60, workdir=req.workdir)


@app.post("/api/vm/install")
def vm_install_endpoint(req: VMInstallRequest):
    return guest_os.install_package(package=req.package)


@app.get("/health")
@app.get("/api/health")
def health_check():
    return {"status": "healthy", "service": "azoth-local-agent", "sovereign": True}


def main():
    import argparse
    import uvicorn
    parser = argparse.ArgumentParser(description="Azoth Local Agent Web UI Cockpit")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8790)), help="Port to bind to (default: 8790)")
    parser.add_argument("--host", default="0.0.0.0", help="Host interface (default: 0.0.0.0)")
    parser.add_argument("--reload", action="store_true", default=False, help="Enable auto-reload")
    args, _ = parser.parse_known_args()
    print(f"Launching aZoth Web Cockpit at http://127.0.0.1:{args.port} (listening on {args.host})...")
    uvicorn.run("web_ui:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()


