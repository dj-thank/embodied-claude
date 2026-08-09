# memory-mcp

MCP server for AI long-term memory - Let AI remember across sessions!

## Overview

This MCP server provides local long-term memory with two interchangeable backends:

- **SQLite FTS**: lightweight, dependency-minimal lexical and character-aware retrieval.
- **ChromaDB**: richer embedding-based semantic retrieval, installed as an optional extra.

Both backends share the same MCP tools, metadata, episode, link, and guarded-deletion behavior.

## Features

- **Semantic Memory Storage**: Save memories with emotion tags, importance levels, and categories
- **Selectable Retrieval**: Lightweight SQLite FTS or Chroma semantic search
- **Context-based Recall**: Automatically recall memories relevant to the current conversation
- **Persistent Storage**: Memories are stored locally and persist across sessions
- **Guarded Record Deletion**: Optional two-step deletion with an expiring one-time token
- **Statistics**: Track memory counts by category and emotion

## Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/memory-mcp.git
cd memory-mcp

# Lightweight SQLite install (ChromaDB is not installed)
uv sync

# Optional rich semantic backend
uv sync --extra chroma

# Run the server
uv run memory-mcp
```

## Configuration

Set these environment variables or create a `.env` file:

| Variable | Default | Description |
|----------|---------|-------------|
| `MEMORY_BACKEND` | `auto` | `sqlite`, `chroma`, or auto-detect installed Chroma |
| `MEMORY_DB_PATH` | `~/.claude/memories/<backend>` | Backend-specific storage path |
| `MEMORY_COLLECTION_NAME` | `claude_memories` | Collection name |
| `MEMORY_DELETION_ENABLED` | `false` | Explicitly enable destructive memory-record deletion |
| `MEMORY_DELETION_TOKEN_TTL_SECONDS` | `300` | One-time deletion token TTL, clamped to 30-3600 seconds |

## Tools

### remember

Save a memory to long-term storage.

```json
{
  "content": "Today I learned about vector databases",
  "emotion": "excited",
  "importance": 4,
  "category": "technical"
}
```

### search_memories

Search memories by backend relevance: lexical/character matching on SQLite or semantic similarity on Chroma.

```json
{
  "query": "things I learned about databases",
  "n_results": 5,
  "category_filter": "technical"
}
```

### recall

Recall relevant memories based on conversation context.

```json
{
  "context": "We were discussing database optimization",
  "n_results": 3
}
```

### list_recent_memories

List the most recent memories.

```json
{
  "limit": 10,
  "category_filter": "memory"
}
```

### get_memory_stats

Get statistics about stored memories.

### prepare_forget / forget

Deletion is disabled by default. After an operator enables it, call
`prepare_forget` with the exact memory ID, then pass its short-lived token and
the same ID to `forget`. Tokens are one-time and a new preparation invalidates
the previous one.

`forget` removes the selected backend's memory record, direct links/coactivation entries,
working-memory copies, and episode summaries containing that memory. It does
**not** delete external image or audio files referenced by sensory metadata;
those paths are returned for a separately governed media-deletion workflow.
This is application-level logical deletion, not verified secure erasure from
database files, write-ahead logs, filesystem snapshots, or backups.

The token limits accidental, mismatched, expired, and replayed calls; it is not
proof of human authorization. Keep deletion disabled unless a trusted host UI
or policy gate obtains explicit user confirmation. Mutation serialization is
process-local and is not a cross-process database transaction.

## Backend selection and migration

`MEMORY_BACKEND=auto` preserves Chroma when it is installed and otherwise uses SQLite.
The installer sets the backend explicitly: Lite uses SQLite; Core and Full use Chroma.
SQLite and Chroma use separate default directories. Existing memories are not copied between
backends automatically, so changing the backend does not constitute a verified migration.

## Claude Code Integration

Add to your `~/.claude.json`:

```json
{
  "mcpServers": {
    "memory": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/memory-mcp", "memory-mcp"],
      "env": {"MEMORY_BACKEND": "sqlite"}
    }
  }
}
```

## Development

The public surface uses the Python MCP SDK v2 typed registry for all 23 tools.
Tests cover modern and legacy in-process clients plus a real stdio subprocess
using the lightweight SQLite backend. The handwritten schemas and legacy router
are removed; one private fail-closed dispatcher retains established behavior
while it is decomposed by capability in a later refactor.

```bash
# Install dev dependencies
uv sync --extra dev

# Run tests
uv run --extra dev pytest

# Lint
uv run --extra dev ruff check .
```

## License

MIT
