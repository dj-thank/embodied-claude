# Embodied Claude Installer

GUI installer for Embodied Claude MCP servers.

## Features

- ✅ Dependency checking (ffmpeg, uv, OpenCV)
- ✅ Wi-Fi PTZ camera configuration (Tapo)
- ✅ USB webcam detection
- ✅ Automatic MCP configuration (~/.claude.json)
- ✅ User-scope Sanpoloid action gate (~/.claude/settings.json)
- ✅ Reproducible dependency installation (`uv sync --locked`)
- ✅ Preserving, atomic settings merge with recoverable backups
- ✅ Does not collect or store Claude authentication keys

The installer syncs `action-policy` before exposing MCP servers globally. It then merges one
`PreToolUse` hook for the five Sanpoloid MCP server prefixes while preserving existing user hooks.
Re-running the installer replaces only its own prior handler. Local user hooks are not loaded by
Claude Code cloud sessions, and an administrator can restrict user-managed hooks.

## Development

### Prerequisites

- Python 3.12+
- uv (Python package manager)

### Setup

```bash
cd installer
uv sync
```

### Run in development mode

```bash
uv run embodied-claude-installer
```

## Building Binaries

### Windows

```powershell
cd installer

# Install dependencies
uv sync

# Build executable with PyInstaller
uv run pyinstaller embodied-claude-installer.spec

# Output will be in dist/embodied-claude-installer.exe
```

### macOS

```bash
cd installer

# Install dependencies
uv sync

# Build .app bundle
uv run pyinstaller embodied-claude-installer.spec

# Output will be in dist/embodied-claude-installer.app
```

### Linux

```bash
cd installer

# Install dependencies
uv sync

# Build executable
uv run pyinstaller embodied-claude-installer.spec

# Output will be in dist/embodied-claude-installer
```

## Release Process

1. **Build the binary** (see above)
2. **Test the binary** on target platform
3. **Create a git tag**:
   ```bash
   git tag v0.1.0-SNAPSHOT
   git push origin v0.1.0-SNAPSHOT
   ```
4. **Create GitHub Release** with the binary attached

## Architecture

```
installer/
├── src/installer/
│   ├── main.py              # Entry point
│   └── pages/
│       ├── welcome.py       # Welcome page
│       ├── dependencies.py  # Dependency check
│       ├── camera.py        # Camera selection
│       ├── api_key.py       # Legacy page (not included in the wizard)
│       ├── install.py       # Installation process
│       └── complete.py      # Completion page
├── embodied-claude-installer.spec  # PyInstaller config
└── pyproject.toml
```

## Troubleshooting

### Windows: "VCRUNTIME140.dll not found"

Install [Microsoft Visual C++ Redistributable](https://aka.ms/vs/17/release/vc_redist.x64.exe)

### macOS: "App is damaged and can't be opened"

```bash
xattr -cr /Applications/embodied-claude-installer.app
```

### Linux: "Permission denied"

```bash
chmod +x embodied-claude-installer
```
