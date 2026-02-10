#!/usr/bin/env python3
"""
knowledge_graph.py — Self-Describing Knowledge Graph for Context Resolution

Each knowledge file declares its dependencies in YAML frontmatter.
The graph resolver navigates dependencies automatically, building
complete context packages without hard-coded paths.

Architecture:
    1. Scan directories for knowledge files
    2. Parse frontmatter to build graph
    3. Resolve dependencies via BFS traversal
    4. Output flattened context for injection

Usage:
    # Build/update graph index
    python3 knowledge_graph.py index
    
    # Resolve context for entry point
    python3 knowledge_graph.py resolve nina --workflow WF-NINA-001
    
    # Show graph structure
    python3 knowledge_graph.py show nina
"""

import argparse
import json
import re
import sys
from collections import deque
from pathlib import Path
from typing import Optional

# Paths
WORKSPACE = Path.home() / ".openclaw" / "workspace"
GDRIVE = Path.home() / "gdrive"
PROMETHIA_BASE = GDRIVE / "Marketing" / "Caiçara Marketing Digital" / "Caiçara Marketing" / "Plataforma Caiçara" / "Promethia"
GRAPH_CACHE = WORKSPACE / ".cache" / "knowledge_graph.json"

# Directories to scan for knowledge files
# NOTE: Only local dirs for fast indexing. GDrive refs resolved on-demand.
SCAN_DIRS = [
    WORKSPACE / "knowledge",
    WORKSPACE / "config",
    WORKSPACE / "routines",
    # PROMETHIA_BASE,  # Too slow via rclone — resolve on-demand instead
]


def parse_frontmatter(content: str) -> tuple[dict, str]:
    """Extract YAML frontmatter from markdown content."""
    if not content.startswith("---"):
        return {}, content
    
    # Find closing ---
    end_match = re.search(r'\n---\n', content[3:])
    if not end_match:
        return {}, content
    
    frontmatter_str = content[3:end_match.start() + 3]
    body = content[end_match.end() + 3 + 1:]
    
    # Enhanced YAML parsing (handles dicts in lists)
    frontmatter = {}
    current_key = None
    current_list = None
    current_dict = None  # For dict items in lists
    
    for line in frontmatter_str.split('\n'):
        line_stripped = line.rstrip()
        if not line_stripped:
            continue
        
        # Count leading spaces
        indent = len(line) - len(line.lstrip())
        line_content = line_stripped.strip()
        
        # List item starting a new dict: "  - path: value"
        if line_content.startswith('- ') and ':' in line_content[2:]:
            if current_list is not None:
                # Parse "- key: value" as start of dict
                item_content = line_content[2:]  # Remove "- "
                key, _, value = item_content.partition(':')
                key = key.strip()
                value = value.strip()
                current_dict = {key: value}
                current_list.append(current_dict)
            continue
        
        # Continuation of dict in list: "    when: pattern"
        if indent >= 4 and current_dict is not None and ':' in line_content:
            key, _, value = line_content.partition(':')
            key = key.strip()
            value = value.strip()
            current_dict[key] = value
            continue
        
        # Simple list item: "  - value"
        if line_content.startswith('- '):
            if current_list is not None:
                current_dict = None  # Reset dict context
                current_list.append(line_content[2:].strip())
            continue
        
        # Top-level key: value or key:
        if ':' in line_content and indent == 0:
            key, _, value = line_content.partition(':')
            key = key.strip()
            value = value.strip()
            
            current_dict = None  # Reset dict context
            
            if value:
                frontmatter[key] = value
                current_key = None
                current_list = None
            else:
                # Start of list
                frontmatter[key] = []
                current_key = key
                current_list = frontmatter[key]
    
    return frontmatter, body


def expand_path(path_str: str) -> Path:
    """Expand ~ and resolve path."""
    if path_str.startswith("~/"):
        return Path.home() / path_str[2:]
    if path_str.startswith("~"):
        return Path(path_str).expanduser()
    # Relative to workspace
    if not path_str.startswith("/"):
        return WORKSPACE / path_str
    return Path(path_str)


def scan_knowledge_files() -> dict:
    """Scan directories and build graph from frontmatter."""
    graph = {
        "nodes": {},      # id -> node data
        "edges": [],      # (from, to, type)
        "by_path": {},    # path -> id
        "by_type": {},    # type -> [ids]
    }
    
    extensions = {".md", ".yaml", ".yml"}
    
    for scan_dir in SCAN_DIRS:
        if not scan_dir.exists():
            continue
            
        for path in scan_dir.rglob("*"):
            if path.suffix not in extensions:
                continue
            if path.name.startswith("."):
                continue
                
            try:
                content = path.read_text(errors='ignore')
            except Exception:
                continue
            
            frontmatter, body = parse_frontmatter(content)
            
            # Generate ID from frontmatter or path
            node_id = frontmatter.get("id") or path.stem
            node_type = frontmatter.get("type", "unknown")
            
            # Create node
            node = {
                "id": node_id,
                "type": node_type,
                "path": str(path),
                "title": frontmatter.get("title", path.stem),
                "specialist": frontmatter.get("specialist"),
                "requires": frontmatter.get("requires", []),
                "optional": frontmatter.get("optional", []),
                "provides": frontmatter.get("provides", []),
                "frontmatter": frontmatter,
            }
            
            graph["nodes"][node_id] = node
            graph["by_path"][str(path)] = node_id
            
            # Index by type
            if node_type not in graph["by_type"]:
                graph["by_type"][node_type] = []
            graph["by_type"][node_type].append(node_id)
            
            # Create edges
            for req in node["requires"]:
                graph["edges"].append((node_id, req, "requires"))
            for opt in node["optional"]:
                graph["edges"].append((node_id, opt, "optional"))
    
    return graph


def save_graph(graph: dict):
    """Save graph to cache."""
    GRAPH_CACHE.parent.mkdir(parents=True, exist_ok=True)
    with open(GRAPH_CACHE, 'w') as f:
        json.dump(graph, f, indent=2, default=str)


def load_graph() -> dict:
    """Load graph from cache, rebuild if missing."""
    if not GRAPH_CACHE.exists():
        graph = scan_knowledge_files()
        save_graph(graph)
        return graph
    
    with open(GRAPH_CACHE) as f:
        return json.load(f)


def resolve_node_id(graph: dict, ref: str) -> Optional[str]:
    """Resolve a reference to a node ID."""
    # Direct ID match
    if ref in graph["nodes"]:
        return ref
    
    # Path match
    expanded = str(expand_path(ref))
    if expanded in graph["by_path"]:
        return graph["by_path"][expanded]
    
    # Partial path match (filename)
    for path, node_id in graph["by_path"].items():
        if path.endswith(ref) or Path(path).name == ref:
            return node_id
    
    return None


def resolve_dependencies(graph: dict, entry_id: str, include_optional: bool = False) -> list[str]:
    """
    BFS traversal to collect all dependencies.
    Returns list of node IDs in dependency order (dependencies first).
    """
    resolved = []
    visited = set()
    queue = deque([entry_id])
    
    while queue:
        node_id = queue.popleft()
        
        if node_id in visited:
            continue
        visited.add(node_id)
        
        node = graph["nodes"].get(node_id)
        if not node:
            # Try to resolve as path
            resolved_id = resolve_node_id(graph, node_id)
            if resolved_id:
                node = graph["nodes"].get(resolved_id)
                node_id = resolved_id
        
        if not node:
            # External reference, skip
            continue
        
        # Add dependencies first (they should appear before this node)
        for req in node.get("requires", []):
            req_id = resolve_node_id(graph, req)
            if req_id and req_id not in visited:
                queue.append(req_id)
        
        if include_optional:
            for opt in node.get("optional", []):
                opt_id = resolve_node_id(graph, opt)
                if opt_id and opt_id not in visited:
                    queue.append(opt_id)
        
        resolved.append(node_id)
    
    # Reverse to get dependencies before dependents
    return list(reversed(resolved))


def load_external_file(path_ref: str) -> Optional[str]:
    """Load file from external path (e.g., gdrive) on-demand."""
    try:
        path = expand_path(path_ref)
        if path.exists():
            return path.read_text()
    except Exception:
        pass
    return None


def matches_task(pattern: str, task: str) -> bool:
    """Check if task matches pattern (case-insensitive regex)."""
    if not task or not pattern:
        return False
    # Strip quotes from pattern
    pattern = pattern.strip('"\'')
    try:
        return bool(re.search(pattern, task, re.IGNORECASE))
    except re.error:
        return pattern.lower() in task.lower()


def parse_optional_deps(optional_list: list, task: str) -> tuple[list, list]:
    """
    Parse optional dependencies, filtering by task relevance.
    
    Supports two formats:
    1. Simple string: "path/to/file.md" (always included if task provided)
    2. Conditional dict: {"path": "file.md", "when": "regex pattern"}
    
    Returns: (paths_to_load, skipped_paths)
    """
    to_load = []
    skipped = []
    
    for item in optional_list:
        if isinstance(item, str):
            # Simple format — include if any task
            if task:
                to_load.append(item)
            else:
                skipped.append(item)
        elif isinstance(item, dict):
            # Conditional format
            path = item.get("path", "")
            pattern = item.get("when", "")
            
            if matches_task(pattern, task):
                to_load.append(path)
            else:
                skipped.append(path)
    
    return to_load, skipped


def build_context(graph: dict, entry_id: str, workflow_id: Optional[str] = None, task: str = "", pills: list[str] = None) -> dict:
    """
    Build complete context package for an entry point.
    
    Returns:
        {
            "entry": entry_id,
            "workflow": workflow_id,
            "nodes": [ordered list of resolved nodes],
            "files": {node_id: content},
            "external_files": {path: content},  # on-demand loaded
            "metadata": {...}
        }
    """
    # Start with entry point
    all_deps = resolve_dependencies(graph, entry_id)
    
    # Add workflow if specified
    if workflow_id:
        wf_deps = resolve_dependencies(graph, workflow_id)
        for dep in wf_deps:
            if dep not in all_deps:
                all_deps.append(dep)
    
    # Load file contents
    files = {}
    external_files = {}
    external_refs_required = set()
    external_refs_optional = []
    skipped_optional = []
    
    for node_id in all_deps:
        node = graph["nodes"].get(node_id)
        if node and node.get("path"):
            try:
                path = Path(node["path"])
                if path.exists():
                    files[node_id] = path.read_text()
                    
                    # Collect REQUIRED external references (always load)
                    for req in node.get("requires", []):
                        if isinstance(req, str) and (req.startswith("~/gdrive") or req.startswith("/")):
                            external_refs_required.add(req)
                    
                    # Collect OPTIONAL external references
                    optional = node.get("optional", [])
                    if optional:
                        if pills:
                            # Explicit pills specified — load only those
                            for opt in optional:
                                path = opt.get("path", opt) if isinstance(opt, dict) else opt
                                name = Path(path).stem
                                if any(p.lower() in name.lower() for p in pills):
                                    external_refs_optional.append(path)
                                else:
                                    skipped_optional.append(path)
                        else:
                            # No explicit pills — filter by task
                            to_load, skipped = parse_optional_deps(optional, task)
                            external_refs_optional.extend(to_load)
                            skipped_optional.extend(skipped)
            except Exception:
                pass
    
    # Load required external files
    for ref in external_refs_required:
        content = load_external_file(ref)
        if content:
            key = Path(ref).name
            external_files[key] = content
    
    # Load optional external files (filtered by task)
    for ref in external_refs_optional:
        content = load_external_file(ref)
        if content:
            key = Path(ref).name
            external_files[key] = content
    
    # Build metadata from entry node
    entry_node = graph["nodes"].get(entry_id, {})
    
    return {
        "entry": entry_id,
        "workflow": workflow_id,
        "nodes": all_deps,
        "files": files,
        "external_files": external_files,
        "metadata": {
            "type": entry_node.get("type"),
            "specialist": entry_node.get("specialist"),
            "title": entry_node.get("title"),
        }
    }


def format_context_for_spawn(context: dict, task: str) -> str:
    """Format resolved context into a single prompt string."""
    parts = []
    
    # Header
    entry = context.get("entry", "unknown")
    parts.append(f"# Context: {entry}")
    if context.get("workflow"):
        parts.append(f"**Workflow**: {context['workflow']}")
    parts.append("")
    
    # Include all resolved local files
    for node_id in context["nodes"]:
        content = context["files"].get(node_id)
        if content:
            # Strip frontmatter for cleaner output
            _, body = parse_frontmatter(content)
            parts.append(f"## {node_id}")
            parts.append(body.strip())
            parts.append("")
    
    # Include external files (loaded on-demand)
    external = context.get("external_files", {})
    if external:
        parts.append("## Reference Materials (External)")
        for filename, content in external.items():
            _, body = parse_frontmatter(content)
            parts.append(f"### {filename}")
            parts.append(body.strip())
            parts.append("")
    
    # Task
    parts.append("---")
    parts.append("## YOUR TASK")
    parts.append(task)
    
    return "\n".join(parts)


def show_graph_structure(graph: dict, entry_id: str):
    """Display graph structure for an entry point."""
    deps = resolve_dependencies(graph, entry_id, include_optional=True)
    
    print(f"\n=== Graph for: {entry_id} ===\n")
    
    for node_id in deps:
        node = graph["nodes"].get(node_id, {})
        node_type = node.get("type", "?")
        path = node.get("path", "?")
        requires = node.get("requires", [])
        
        print(f"[{node_type}] {node_id}")
        print(f"    path: {path}")
        if requires:
            print(f"    requires: {', '.join(str(r) for r in requires)}")
        print()


def generate_summary(graph: dict, entry_id: str = None) -> str:
    """
    Generate a lightweight summary/index of capabilities.
    
    This is what Nex sees — just the index, not the content.
    Nex uses this to decide which paths to load.
    """
    lines = ["# Knowledge Graph Summary", ""]
    
    if entry_id:
        # Summary for specific entry
        node = graph["nodes"].get(entry_id)
        if not node:
            return f"Unknown entry: {entry_id}"
        
        lines.append(f"## {node.get('title', entry_id)}")
        lines.append(f"**Type**: {node.get('type', 'unknown')}")
        lines.append(f"**Domain**: {node.get('domain', 'N/A')}")
        lines.append("")
        
        # Required (always loaded)
        requires = node.get("requires", [])
        if requires:
            lines.append("### Required (always loaded)")
            for req in requires:
                if isinstance(req, str):
                    name = Path(req).stem
                    lines.append(f"- `{name}`")
            lines.append("")
        
        # Optional (load by path)
        optional = node.get("optional", [])
        if optional:
            lines.append("### Optional (specify to load)")
            lines.append("| ID | Path | When |")
            lines.append("|-----|------|------|")
            for i, opt in enumerate(optional):
                if isinstance(opt, dict):
                    path = opt.get("path", "")
                    when = opt.get("when", "").strip('"\'')
                    name = Path(path).stem
                    lines.append(f"| {i+1} | `{name}` | {when} |")
                elif isinstance(opt, str):
                    name = Path(opt).stem
                    lines.append(f"| {i+1} | `{name}` | (always if task) |")
            lines.append("")
        
        # Provides
        provides = node.get("provides", [])
        if provides:
            lines.append(f"**Provides**: {', '.join(provides)}")
            lines.append("")
    
    else:
        # Summary of all specialists/domains
        lines.append("## Specialists")
        for nid, node in graph["nodes"].items():
            if node.get("type") == "specialist":
                title = node.get("title", nid)
                domain = node.get("domain", "")
                opt_count = len(node.get("optional", []))
                lines.append(f"- **{nid}**: {domain} ({opt_count} optional pills)")
        
        lines.append("")
        lines.append("## Domains")
        for nid, node in graph["nodes"].items():
            if node.get("type") == "domain":
                title = node.get("title", nid)
                lines.append(f"- **{nid}**: {title}")
        
        lines.append("")
        lines.append("## Routines")
        for nid, node in graph["nodes"].items():
            if node.get("type") == "routine":
                title = node.get("title", nid)
                lines.append(f"- **{nid}**: {title}")
    
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Knowledge Graph Navigator")
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    # index command
    index_parser = subparsers.add_parser("index", help="Rebuild graph index")
    
    # resolve command
    resolve_parser = subparsers.add_parser("resolve", help="Resolve context for entry")
    resolve_parser.add_argument("entry", help="Entry point (specialist ID or path)")
    resolve_parser.add_argument("--workflow", "-w", help="Workflow ID to include")
    resolve_parser.add_argument("--task", "-t", help="Task description")
    resolve_parser.add_argument("--pills", "-p", nargs="+", help="Specific pills to load (by name/partial match)")
    resolve_parser.add_argument("--json", action="store_true", help="Output JSON")
    
    # summary command (for orchestrator)
    summary_parser = subparsers.add_parser("summary", help="Generate lightweight capability index")
    summary_parser.add_argument("entry", nargs="?", help="Entry point (optional, all if omitted)")
    
    # show command
    show_parser = subparsers.add_parser("show", help="Show graph structure")
    show_parser.add_argument("entry", help="Entry point to visualize")
    
    args = parser.parse_args()
    
    if args.command == "index":
        print("Scanning knowledge files...")
        graph = scan_knowledge_files()
        save_graph(graph)
        print(f"Indexed {len(graph['nodes'])} nodes")
        print(f"Types: {list(graph['by_type'].keys())}")
        print(f"Cache: {GRAPH_CACHE}")
        
    elif args.command == "resolve":
        graph = load_graph()
        task = args.task or ""
        pills = args.pills or []
        context = build_context(graph, args.entry, args.workflow, task, pills)
        
        if args.json:
            # Don't include full file contents in JSON output
            output = {
                "entry": context["entry"],
                "workflow": context["workflow"],
                "nodes": context["nodes"],
                "metadata": context["metadata"],
            }
            print(json.dumps(output, indent=2))
        elif args.task:
            print(format_context_for_spawn(context, args.task))
        else:
            print(f"Resolved {len(context['nodes'])} nodes:")
            for node_id in context["nodes"]:
                print(f"  - {node_id}")
    
    elif args.command == "summary":
        graph = load_graph()
        print(generate_summary(graph, args.entry))
                
    elif args.command == "show":
        graph = load_graph()
        show_graph_structure(graph, args.entry)


if __name__ == "__main__":
    main()
