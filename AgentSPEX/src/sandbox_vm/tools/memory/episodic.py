"""
File-based episodic memory tool for persistent long-term storage
Supports store, retrieve, search, and list operations
"""

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


async def _load_memory(memory_file) -> Dict[str, Any]:
    """Load memory from file, return empty dict if file doesn't exist"""

    try:
        # Ensure directory exists
        Path(memory_file).parent.mkdir(parents=True, exist_ok=True)

        if not os.path.exists(memory_file):
            return {}

        # Read file synchronously (aiofiles would be better but adds dependency)
        with open(memory_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        # If file is corrupted, log error and start fresh
        print(f"Warning: Could not load memory file {memory_file}: {e}")
        return {}


async def _save_memory(memory_data: Dict[str, Any], memory_file: str) -> bool:
    """Save memory to file atomically"""
    temp_file = f"{memory_file}.tmp"

    try:
        # Ensure directory exists
        Path(memory_file).parent.mkdir(parents=True, exist_ok=True)

        # Write to temporary file first (atomic operation)
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(memory_data, f, indent=2, ensure_ascii=False)

        # Atomic move
        os.rename(temp_file, memory_file)
        return True

    except Exception as e:
        print(f"Error: Could not save memory file {memory_file}: {e}")
        # Clean up temp file if it exists
        if os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except Exception:
                pass
        return False


async def memory(
    action: str,
    memory_file: str,
    key: str = "",
    content: str = "",
    tags: str = "",
    query: str = "",
    limit: int = 5,
) -> dict:
    """
    Unified long-term memory tool for persistent information storage and retrieval.

    This tool provides episodic memory capabilities that persist across workflow steps
    and agent restarts. All data is stored in a JSON file specified by the
    EPISODIC_MEMORY_FILE environment variable.

    Actions:
    - store: Save information with a unique key, content, and optional tags
    - get: Retrieve content by exact key match
    - search: Search by tags or content (case-insensitive text search)
    - recent: List most recent entries (default 5, configurable with limit)
    - stats: Show memory statistics and file location
    - clear: Clear all memory entries (use with caution!)

    Args:
        action: Operation to perform (store|get|search|recent|stats|clear)
        memory_file: The path to the episodic memory file
        key: Unique identifier for store/get operations
        content: Content to store (for store action)
        tags: Comma-separated tags for categorization (for store action)
        query: Search term for search action (searches tags and content)
        limit: Number of recent entries to show (for recent action, default 5)

    Examples:
        memory("store", memory_file="/workspace/deepresearch/episodic.json" key="paper1_methodology", content="Uses transformer architecture with attention mechanism", tags="methodology,transformers,attention")
        memory("get", memory_file="/workspace/deepresearch/episodic.json", key="paper1_methodology")
        memory("search", memory_file="/workspace/deepresearch/episodic.json", query="methodology")
        memory("search", memory_file="/workspace/deepresearch/episodic.json", query="transformers")
        memory("recent", memory_file="/workspace/deepresearch/episodic.json", limit=3)
        memory("stats", memory_file="/workspace/deepresearch/episodic.json")

    Returns:
        dict: {"result": str} on success, or {"error": str} on failure
    """

    try:
        # Ensure path exists
        if not os.path.exists(memory_file):
            Path(memory_file).parent.mkdir(parents=True, exist_ok=True)

        # Load current memory state
        memory_data = await _load_memory(memory_file)

        if action == "store":
            if not key or not content:
                return {
                    "error": "Store action requires both 'key' and 'content' parameters",
                }

            # Parse tags
            tag_list = [tag.strip().lower() for tag in tags.split(",") if tag.strip()]

            # Create memory entry
            entry = {
                "content": content,
                "tags": tag_list,
                "created": time.strftime("%Y-%m-%d %H:%M:%S"),
                "timestamp": time.time(),
                "access_count": 0,
            }

            # Store entry
            memory_data[key] = entry

            # Save to file
            if await _save_memory(memory_data, memory_file):
                tag_str = ", ".join(tag_list) if tag_list else "no tags"
                return {"result": f"✓ Stored '{key}' ({tag_str})"}
            else:
                return {"error": "Failed to save memory to file"}

        elif action == "get":
            if not key:
                return {"error": "Get action requires 'key' parameter"}

            if key in memory_data:
                # Update access count
                memory_data[key]["access_count"] = (
                    memory_data[key].get("access_count", 0) + 1
                )
                memory_data[key]["last_accessed"] = time.strftime("%Y-%m-%d %H:%M:%S")

                # Save updated access info (don't fail if this fails)
                await _save_memory(memory_data, memory_file)

                return {"result": memory_data[key]["content"]}
            else:
                return {"result": f"No entry found for key: '{key}'"}

        elif action == "search":
            if not query:
                return {
                    "error": "Search action requires 'query' parameter",
                }

            query_lower = query.lower()
            results = []

            for key, entry in memory_data.items():
                match_found = False

                # Search in tags
                for tag in entry.get("tags", []):
                    if query_lower in tag:
                        match_found = True
                        break

                # Search in content if not found in tags
                if not match_found and query_lower in entry["content"].lower():
                    match_found = True

                if match_found:
                    # Truncate content for display
                    content_preview = (
                        entry["content"][:200] + "..."
                        if len(entry["content"]) > 200
                        else entry["content"]
                    )
                    tag_str = (
                        ", ".join(entry.get("tags", []))
                        if entry.get("tags")
                        else "no tags"
                    )
                    results.append(f"[{key}] ({tag_str}): {content_preview}")

            if results:
                return {
                    "result": f"Found {len(results)} matches for '{query}':\n\n"
                    + "\n\n".join(results),
                }
            else:
                return {"result": f"No results found for: '{query}'"}

        elif action == "recent":
            if not memory_data:
                return {"result": "No memory entries found"}

            # Sort by timestamp (most recent first)
            sorted_items = sorted(
                memory_data.items(),
                key=lambda x: x[1].get("timestamp", 0),
                reverse=True,
            )

            recent_items = []
            for key, entry in sorted_items[:limit]:
                content_preview = entry["content"]

                tag_str = (
                    ", ".join(entry.get("tags", [])) if entry.get("tags") else "no tags"
                )
                created = entry.get("created", "unknown")
                recent_items.append(
                    f"[{key}] ({created}, {tag_str}): {content_preview}"
                )

            return {
                "result": f"Recent {len(recent_items)} entries:\n\n"
                + "\n\n".join(recent_items),
            }

        elif action == "stats":
            total_entries = len(memory_data)

            if total_entries == 0:
                return {
                    "result": f"Memory is empty. File location: {memory_file}",
                }

            # Calculate stats
            all_tags = set()
            access_counts = []
            timestamps = []

            for entry in memory_data.values():
                all_tags.update(entry.get("tags", []))
                access_counts.append(entry.get("access_count", 0))
                timestamps.append(entry.get("timestamp", 0))

            avg_access = sum(access_counts) / len(access_counts) if access_counts else 0
            oldest = min(timestamps) if timestamps else 0
            newest = max(timestamps) if timestamps else 0

            oldest_date = (
                time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(oldest))
                if oldest
                else "unknown"
            )
            newest_date = (
                time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(newest))
                if newest
                else "unknown"
            )

            stats_text = f"""Memory Statistics:
- Total entries: {total_entries}
- Unique tags: {len(all_tags)}
- Average access count: {avg_access:.1f}
- Oldest entry: {oldest_date}
- Newest entry: {newest_date}
- File location: {memory_file}"""

            return {"result": stats_text}

        elif action == "clear":
            # Clear all memory (use with caution!)
            if await _save_memory({}, memory_file):
                return {
                    "result": f"✓ Cleared all memory entries ({len(memory_data)} entries removed)",
                }
            else:
                return {"error": "Failed to clear memory file"}

        else:
            valid_actions = ["store", "get", "search", "recent", "stats", "clear"]
            return {
                "error": f"Unknown action: '{action}'. Valid actions: {', '.join(valid_actions)}",
            }

    except Exception as e:
        return {"error": f"Memory operation failed: {str(e)}"}
