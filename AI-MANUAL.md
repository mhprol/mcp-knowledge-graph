# AI-MANUAL for MCP Knowledge Graph

This manual provides a progressive disclosure guide for AI agents and developers interacting with the MCP Knowledge Graph. It covers quick references, detailed API documentation, and advanced usage patterns.

## Level 1: Quick Reference (500 tokens)

**Goal**: Execute common graph operations efficiently.

| Intent | Command (Tool) | Example |
| :--- | :--- | :--- |
| **Create Entity** | `create_entities` | `create_entities(entities=[{name="Alice", entityType="Person", observations=["Likes coding"]}])` |
| **Create Relationship** | `create_relations` | `create_relations(relations=[{from="Alice", to="Bob", relationType="knows"}])` |
| **Add Observation** | `add_observations` | `add_observations(observations=[{entityName="Alice", contents=["Moved to NY"]}])` |
| **Query by Entity** | `open_nodes` | `open_nodes(names=["Alice"])` -> Returns Alice and her relations. |
| **Search Nodes** | `search_nodes` | `search_nodes(query="coding")` -> Returns entities matching "coding". |
| **Read Full Graph** | `read_graph` | `read_graph()` -> Returns all entities and relations. |

### Common Patterns

1.  **Query by Relationship Type**:
    *   **Direct Tool**: None.
    *   **Strategy**: Use `read_graph()` and filter client-side for `relation.relationType == "desired_type"`.
    *   **Alternative**: If you know the entities, use `open_nodes()` and filter the returned relations.

2.  **Traverse Paths**:
    *   **Direct Tool**: None.
    *   **Strategy**:
        1.  Start with `open_nodes(names=["StartNode"])`.
        2.  Extract connected nodes from `relations`.
        3.  Call `open_nodes(names=["NextNode"])` iteratively.
    *   **Alternative**: Use `read_graph()` to get the full network and traverse in memory.

3.  **Graph Statistics**:
    *   **Direct Tool**: None.
    *   **Strategy**: Call `read_graph()`, then count `entities.length` and `relations.length`.

---

## Level 2: Full API & Documentation (2000 tokens)

### 1. Data Model

The Knowledge Graph is a directed multigraph stored in a JSONL file.

**Entities (Nodes)**
*   **Schema**:
    ```typescript
    interface Entity {
      name: string;          // Unique identifier (primary key)
      entityType: string;    // Classification (e.g., "Person", "Organization")
      observations: string[]; // List of facts or attributes
    }
    ```
*   **Constraints**: `name` must be unique. Re-creating an existing name is ignored.

**Relations (Edges)**
*   **Schema**:
    ```typescript
    interface Relation {
      from: string;          // Source entity name
      to: string;            // Target entity name
      relationType: string;  // Predicate (active voice, e.g., "works_at")
    }
    ```
*   **Constraints**: Directed. Multiple relations of different types can exist between the same two entities.

### 2. API Reference (Tools)

#### `create_entities`
Creates new entities. Existing entity names are skipped to prevent overwrites.
*   **Input**: `{ entities: Entity[] }`
*   **Returns**: `Entity[]` (only the newly created ones)

#### `create_relations`
Creates directed edges.
*   **Input**: `{ relations: Relation[] }`
*   **Returns**: `Relation[]` (newly created)

#### `add_observations`
Appends new facts to existing entities.
*   **Input**: `{ observations: { entityName: string, contents: string[] }[] }`
*   **Returns**: `{ entityName: string, addedObservations: string[] }[]`

#### `delete_entities`
Removes entities and **cascades** delete to all connected relations (incoming and outgoing).
*   **Input**: `{ entityNames: string[] }`
*   **Returns**: Success message.

#### `delete_relations`
Removes specific edges.
*   **Input**: `{ relations: Relation[] }`
*   **Returns**: Success message.

#### `delete_observations`
Removes specific facts from entities.
*   **Input**: `{ deletions: { entityName: string, observations: string[] }[] }`
*   **Returns**: Success message.

#### `read_graph`
Exports the entire graph state.
*   **Input**: `{}`
*   **Returns**: `{ entities: Entity[], relations: Relation[] }`

#### `search_nodes`
Performs a text search across `name`, `entityType`, and `observations`.
*   **Input**: `{ query: string }`
*   **Returns**: Subgraph `{ entities: Entity[], relations: Relation[] }` containing matches and relations *between* them.

#### `open_nodes`
Retrieves specific entities by name.
*   **Input**: `{ names: string[] }`
*   **Returns**: Subgraph `{ entities: Entity[], relations: Relation[] }` containing requested entities and relations *between* them.

### 3. Query Language & Syntax
This MCP server does not expose a graph query language like Cypher or SPARQL. Instead, it provides **tool-based access**.
*   **Search**: Simple string matching (substring).
*   **Traversal**: Client-side logic required.
*   **Filtering**: Client-side logic required on `read_graph` output.

### 4. Indexing & Performance
*   **Storage**: Local `memory.jsonl` file.
*   **Indexing**: None (in-memory linear scan).
*   **Performance**:
    *   Read operations: $O(N)$ where $N$ is file size (loading graph).
    *   Search operations: $O(N)$ (filtering).
    *   Scaling limit: Bound by Node.js process memory and file I/O speed. Not suitable for millions of nodes.

### 5. Persistence
*   **Format**: JSON Lines (JSONL). Each line is a JSON object (`type: "entity"` or `type: "relation"`).
*   **Location**: Defaults to `memory.jsonl` in the package directory, or configurable via `--memory-path`.
*   **Backup**: Copy the `.jsonl` file.

---

## Level 3: Advanced Topics (1500 tokens)

### 1. Building Domain-Specific Graphs

**Project Graphs**
*   **Entity Types**: `Task`, `Milestone`, `Developer`, `Bug`.
*   **Relations**: `blocked_by`, `assigned_to`, `completed_in`.
*   **Usage**: Use `open_nodes` on the current active task to see blockers and assignees.

**Person Networks**
*   **Entity Types**: `Person`, `Company`, `Role`.
*   **Relations**: `colleague_of`, `reports_to`, `invested_in`.
*   **Observation Strategy**: Store temporal data in observations (e.g., "Promoted to Senior in 2023") since edges don't have properties.

**Timeline Chains**
*   To model sequences (time or causal), create "Event" entities and link them.
*   `Event_A -> caused -> Event_B`
*   `Event_B -> happened_before -> Event_C`

### 2. Multi-View Graphs

Since the graph is a flat list of nodes and edges, you can simulate "views" (overlays) by filtering `read_graph` output:
*   **Social View**: Filter for `relationType` in [`knows`, `friends_with`].
*   **Process View**: Filter for `relationType` in [`triggers`, `depends_on`].
*   **Taxonomy View**: Filter for `relationType` = `is_a`.

This allows a single knowledge base to serve multiple reasoning contexts without data duplication.

### 3. Integration with Memory Systems

This MCP server acts as the **Long-Term Memory (LTM)** for an AI agent.
*   **Short-Term Memory (STM)**: The context window of the LLM.
*   **Workflow**:
    1.  **Recall**: At the start of a session, query the graph for relevant entities (e.g., User profile, Current Project) using `search_nodes`. Inject this into the context window.
    2.  **Reason**: Process user input using the recalled context.
    3.  **Consolidate**: Extract new facts and relationships from the conversation. Use `create_entities` and `create_relations` to store them back into LTM.

### 4. Reasoning over Graph Structure

Graph structure enables reasoning that vector databases (semantic search) miss:
*   **Transitive Inference**: If `A -> part_of -> B` and `B -> part_of -> C`, then `A` is part of `C`. The LLM can deduce this if provided with the subgraph.
*   **Centrality Analysis**: Identify key entities by observing which nodes have the most incoming edges (hubs) in the `read_graph` output.
*   **Contradiction Detection**: Compare new user input against existing observations retrieved via `open_nodes` to detect conflicts.

### 5. Scaling Strategies

**Current Limitations**:
*   The system loads the entire JSONL into memory for every operation.
*   Performance degrades as the file grows > 10MB or thousands of lines.

**Scaling Approaches**:
1.  **Partitioning**: Use different `--memory-path` locations for distinct domains (e.g., `personal.jsonl`, `work.jsonl`).
2.  **Pruning**: Regularly use `delete_observations` or `delete_entities` to remove obsolete or low-value information.
3.  **Summarization**: Compress old observations into a single summary observation, then delete the old ones.
4.  **Migration**: If the graph outgrows this tool, export data using `read_graph` and import into a dedicated graph database (Neo4j, ArangoDB), then replace the MCP server backend while keeping the API contract.
