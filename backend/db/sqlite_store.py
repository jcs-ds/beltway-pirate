"""SQLite database storage for entities and relationships."""
import sqlite3
import json
from pathlib import Path
from typing import List, Optional, Dict, Any
from contextlib import contextmanager

from backend.models.entities import Entity, EntityType, SearchResult, GraphNode, GraphEdge, GraphData


class SQLiteStore:
    """SQLite storage for DoD entities."""

    def __init__(self, db_path: str = "data/processed/dod.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _get_conn(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self):
        """Initialize database schema."""
        with self._get_conn() as conn:
            cursor = conn.cursor()

            # Entities table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS entities (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    entity_type TEXT,
                    service TEXT,
                    domain TEXT,
                    tags TEXT,  -- JSON array
                    content TEXT,
                    summary TEXT,
                    file_path TEXT,
                    metadata TEXT,  -- JSON object
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Links table (for graph relationships)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS links (
                    source_id TEXT,
                    target_id TEXT,
                    relationship TEXT DEFAULT 'links_to',
                    PRIMARY KEY (source_id, target_id, relationship),
                    FOREIGN KEY (source_id) REFERENCES entities(id)
                )
            """)

            # Full-text search virtual table
            cursor.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS entities_fts USING fts5(
                    id,
                    title,
                    content,
                    tags,
                    summary,
                    content='entities',
                    content_rowid='rowid'
                )
            """)

            # Triggers to keep FTS in sync
            cursor.execute("""
                CREATE TRIGGER IF NOT EXISTS entities_ai AFTER INSERT ON entities BEGIN
                    INSERT INTO entities_fts(rowid, id, title, content, tags, summary)
                    VALUES (new.rowid, new.id, new.title, new.content, new.tags, new.summary);
                END
            """)

            cursor.execute("""
                CREATE TRIGGER IF NOT EXISTS entities_ad AFTER DELETE ON entities BEGIN
                    INSERT INTO entities_fts(entities_fts, rowid, id, title, content, tags, summary)
                    VALUES('delete', old.rowid, old.id, old.title, old.content, old.tags, old.summary);
                END
            """)

            cursor.execute("""
                CREATE TRIGGER IF NOT EXISTS entities_au AFTER UPDATE ON entities BEGIN
                    INSERT INTO entities_fts(entities_fts, rowid, id, title, content, tags, summary)
                    VALUES('delete', old.rowid, old.id, old.title, old.content, old.tags, old.summary);
                    INSERT INTO entities_fts(rowid, id, title, content, tags, summary)
                    VALUES (new.rowid, new.id, new.title, new.content, new.tags, new.summary);
                END
            """)

            # Indexes
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_entity_type ON entities(entity_type)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_service ON entities(service)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_domain ON entities(domain)")

            conn.commit()

    def clear(self):
        """Clear all data from database."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM links")
            cursor.execute("DELETE FROM entities")
            cursor.execute("DELETE FROM entities_fts")
            conn.commit()

    def insert_entity(self, entity: Entity):
        """Insert or update an entity."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO entities
                (id, title, entity_type, service, domain, tags, content, summary, file_path, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                entity.id,
                entity.title,
                entity.entity_type.value if isinstance(entity.entity_type, EntityType) else entity.entity_type,
                entity.service,
                entity.domain,
                json.dumps(entity.tags),
                entity.content,
                entity.summary,
                entity.file_path,
                json.dumps(entity.metadata),
            ))
            conn.commit()

    def insert_entities(self, entities: List[Entity]):
        """Bulk insert entities."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            for entity in entities:
                cursor.execute("""
                    INSERT OR REPLACE INTO entities
                    (id, title, entity_type, service, domain, tags, content, summary, file_path, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    entity.id,
                    entity.title,
                    entity.entity_type.value if isinstance(entity.entity_type, EntityType) else entity.entity_type,
                    entity.service,
                    entity.domain,
                    json.dumps(entity.tags),
                    entity.content,
                    entity.summary,
                    entity.file_path,
                    json.dumps(entity.metadata),
                ))

                # Insert links
                for link in entity.links:
                    cursor.execute("""
                        INSERT OR IGNORE INTO links (source_id, target_id, relationship)
                        VALUES (?, ?, 'links_to')
                    """, (entity.id, link))

            conn.commit()

    def get_entity(self, entity_id: str) -> Optional[Entity]:
        """Get entity by ID."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM entities WHERE id = ?", (entity_id,))
            row = cursor.fetchone()
            if row:
                return self._row_to_entity(row)
            return None

    def get_entity_by_title(self, title: str) -> Optional[Entity]:
        """Get entity by title (case-insensitive) or by ID ending with the title."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            # First try exact title match
            cursor.execute("SELECT * FROM entities WHERE LOWER(title) = LOWER(?)", (title,))
            row = cursor.fetchone()
            if row:
                return self._row_to_entity(row)
            # Try ID ending with the title (handles short names like 'Infleqtion' -> 'Companies/Startups/Infleqtion')
            cursor.execute("SELECT * FROM entities WHERE id LIKE ?", (f"%/{title}",))
            row = cursor.fetchone()
            if row:
                return self._row_to_entity(row)
            # Also try with backslash (Windows paths)
            cursor.execute("SELECT * FROM entities WHERE id LIKE ?", (f"%\\{title}",))
            row = cursor.fetchone()
            if row:
                return self._row_to_entity(row)
            return None

    def _row_to_entity(self, row: sqlite3.Row) -> Entity:
        """Convert database row to Entity."""
        # Handle legacy entity type values
        entity_type_str = row['entity_type']
        if entity_type_str == 'buyer':
            entity_type_str = 'stakeholder'
        elif entity_type_str == 'operational_unit':
            entity_type_str = 'unit'

        return Entity(
            id=row['id'],
            title=row['title'],
            entity_type=EntityType(entity_type_str) if entity_type_str else EntityType.UNKNOWN,
            service=row['service'],
            domain=row['domain'],
            tags=json.loads(row['tags']) if row['tags'] else [],
            content=row['content'] or '',
            summary=row['summary'],
            file_path=row['file_path'],
            metadata=json.loads(row['metadata']) if row['metadata'] else {},
            links=[],
            backlinks=[],
        )

    def search(self, query: str, entity_type: Optional[str] = None,
               service: Optional[str] = None, domain: Optional[str] = None,
               limit: int = 50) -> List[SearchResult]:
        """Full-text search across entities with fuzzy matching fallback."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            results = []
            seen_ids = set()

            # Normalize query
            query_lower = query.lower().strip()
            query_words = query_lower.split()

            # 1. First: Exact title matches (highest priority)
            exact_sql = "SELECT *, 1000 as score FROM entities WHERE LOWER(title) = ?"
            exact_params = [query_lower]
            if entity_type:
                exact_sql += " AND entity_type = ?"
                exact_params.append(entity_type)
            if service:
                exact_sql += " AND service = ?"
                exact_params.append(service)
            if domain:
                exact_sql += " AND domain LIKE ?"
                exact_params.append(f"%{domain}%")
            exact_sql += " LIMIT 5"

            cursor.execute(exact_sql, exact_params)
            for row in cursor.fetchall():
                if row['id'] not in seen_ids:
                    entity = self._row_to_entity(row)
                    results.append(SearchResult(entity=entity, score=1000, match_type="exact"))
                    seen_ids.add(row['id'])

            # 2. Title contains query (high priority)
            contains_sql = "SELECT *, 500 as score FROM entities WHERE LOWER(title) LIKE ? AND id NOT IN ({})".format(
                ','.join('?' * len(seen_ids)) if seen_ids else "''"
            )
            contains_params = [f"%{query_lower}%"] + list(seen_ids)
            if entity_type:
                contains_sql += " AND entity_type = ?"
                contains_params.append(entity_type)
            if service:
                contains_sql += " AND service = ?"
                contains_params.append(service)
            if domain:
                contains_sql += " AND domain LIKE ?"
                contains_params.append(f"%{domain}%")
            contains_sql += " ORDER BY LENGTH(title) LIMIT 10"

            cursor.execute(contains_sql, contains_params)
            for row in cursor.fetchall():
                if row['id'] not in seen_ids:
                    entity = self._row_to_entity(row)
                    results.append(SearchResult(entity=entity, score=500, match_type="title_contains"))
                    seen_ids.add(row['id'])

            # 3. FTS5 prefix search (word* for partial word matches)
            if len(results) < limit:
                try:
                    # Build FTS query with prefix matching
                    fts_terms = [f'"{word}"*' for word in query_words if len(word) >= 2]
                    if fts_terms:
                        fts_query = ' OR '.join(fts_terms)

                        fts_sql = """
                            SELECT e.*, rank
                            FROM entities_fts fts
                            JOIN entities e ON fts.id = e.id
                            WHERE entities_fts MATCH ?
                        """
                        fts_params = [fts_query]

                        if entity_type:
                            fts_sql += " AND e.entity_type = ?"
                            fts_params.append(entity_type)
                        if service:
                            fts_sql += " AND e.service = ?"
                            fts_params.append(service)
                        if domain:
                            fts_sql += " AND e.domain LIKE ?"
                            fts_params.append(f"%{domain}%")

                        fts_sql += " ORDER BY rank LIMIT ?"
                        fts_params.append(limit)

                        cursor.execute(fts_sql, fts_params)
                        for row in cursor.fetchall():
                            if row['id'] not in seen_ids:
                                entity = self._row_to_entity(row)
                                results.append(SearchResult(
                                    entity=entity,
                                    score=abs(row['rank']) if row['rank'] else 100,
                                    match_type="fts"
                                ))
                                seen_ids.add(row['id'])
                except Exception as e:
                    print(f"FTS search error: {e}")

            # 4. Fuzzy fallback: search in tags, content, summary
            if len(results) < limit:
                fuzzy_sql = """
                    SELECT *, 50 as score FROM entities
                    WHERE (
                        LOWER(tags) LIKE ? OR
                        LOWER(content) LIKE ? OR
                        LOWER(summary) LIKE ?
                    )
                """
                fuzzy_params = [f"%{query_lower}%", f"%{query_lower}%", f"%{query_lower}%"]

                if seen_ids:
                    fuzzy_sql += " AND id NOT IN ({})".format(','.join('?' * len(seen_ids)))
                    fuzzy_params.extend(list(seen_ids))

                if entity_type:
                    fuzzy_sql += " AND entity_type = ?"
                    fuzzy_params.append(entity_type)
                if service:
                    fuzzy_sql += " AND service = ?"
                    fuzzy_params.append(service)
                if domain:
                    fuzzy_sql += " AND domain LIKE ?"
                    fuzzy_params.append(f"%{domain}%")

                fuzzy_sql += " LIMIT ?"
                fuzzy_params.append(limit - len(results))

                cursor.execute(fuzzy_sql, fuzzy_params)
                for row in cursor.fetchall():
                    if row['id'] not in seen_ids:
                        entity = self._row_to_entity(row)
                        results.append(SearchResult(entity=entity, score=50, match_type="fuzzy"))
                        seen_ids.add(row['id'])

            # Sort by score descending and limit
            results.sort(key=lambda x: x.score, reverse=True)
            return results[:limit]

    def get_entities_by_type(self, entity_type: str, service: Optional[str] = None,
                              limit: int = 100) -> List[Entity]:
        """Get entities by type with optional service filter."""
        with self._get_conn() as conn:
            cursor = conn.cursor()

            sql = "SELECT * FROM entities WHERE entity_type = ?"
            params = [entity_type]

            if service:
                sql += " AND service = ?"
                params.append(service)

            sql += " ORDER BY title LIMIT ?"
            params.append(limit)

            cursor.execute(sql, params)
            return [self._row_to_entity(row) for row in cursor.fetchall()]

    def get_all_entities(self, entity_type: Optional[str] = None) -> List[Entity]:
        """Get all entities, optionally filtered by type."""
        with self._get_conn() as conn:
            cursor = conn.cursor()

            if entity_type:
                cursor.execute("SELECT * FROM entities WHERE entity_type = ? ORDER BY title", (entity_type,))
            else:
                cursor.execute("SELECT * FROM entities ORDER BY entity_type, title")

            return [self._row_to_entity(row) for row in cursor.fetchall()]

    def get_graph_data(self, root_id: Optional[str] = None, depth: int = 2) -> GraphData:
        """Get graph data for visualization."""
        with self._get_conn() as conn:
            cursor = conn.cursor()

            if root_id:
                # BFS to find connected nodes up to depth
                visited = set()
                to_visit = [(root_id, 0)]
                node_ids = set()

                while to_visit:
                    current_id, current_depth = to_visit.pop(0)
                    if current_id in visited or current_depth > depth:
                        continue
                    visited.add(current_id)
                    node_ids.add(current_id)

                    # Get outgoing links
                    cursor.execute("SELECT target_id FROM links WHERE source_id = ?", (current_id,))
                    for row in cursor.fetchall():
                        if row['target_id'] not in visited:
                            to_visit.append((row['target_id'], current_depth + 1))
                            node_ids.add(row['target_id'])

                    # Get incoming links
                    cursor.execute("SELECT source_id FROM links WHERE target_id = ?", (current_id,))
                    for row in cursor.fetchall():
                        if row['source_id'] not in visited:
                            to_visit.append((row['source_id'], current_depth + 1))
                            node_ids.add(row['source_id'])

                # Get nodes
                placeholders = ','.join('?' * len(node_ids))
                cursor.execute(f"""
                    SELECT id, title, entity_type, service FROM entities
                    WHERE id IN ({placeholders})
                """, list(node_ids))
            else:
                # Get all nodes (limited for performance)
                cursor.execute("""
                    SELECT id, title, entity_type, service FROM entities
                    LIMIT 500
                """)

            nodes = []
            node_set = set()
            for row in cursor.fetchall():
                nodes.append(GraphNode(
                    id=row['id'],
                    title=row['title'],
                    entity_type=EntityType(row['entity_type']) if row['entity_type'] else EntityType.UNKNOWN,
                    service=row['service']
                ))
                node_set.add(row['id'])

            # Get edges between nodes
            if node_set:
                placeholders = ','.join('?' * len(node_set))
                cursor.execute(f"""
                    SELECT source_id, target_id, relationship FROM links
                    WHERE source_id IN ({placeholders}) AND target_id IN ({placeholders})
                """, list(node_set) + list(node_set))

                edges = []
                for row in cursor.fetchall():
                    edges.append(GraphEdge(
                        source=row['source_id'],
                        target=row['target_id'],
                        relationship=row['relationship']
                    ))
            else:
                edges = []

            return GraphData(nodes=nodes, edges=edges)

    def get_entity_links(self, entity_id: str) -> Dict[str, List[Entity]]:
        """Get outgoing and incoming links for an entity."""
        with self._get_conn() as conn:
            cursor = conn.cursor()

            # Outgoing links
            cursor.execute("""
                SELECT e.* FROM entities e
                JOIN links l ON l.target_id = e.id
                WHERE l.source_id = ?
            """, (entity_id,))
            outgoing = [self._row_to_entity(row) for row in cursor.fetchall()]

            # Incoming links (backlinks)
            cursor.execute("""
                SELECT e.* FROM entities e
                JOIN links l ON l.source_id = e.id
                WHERE l.target_id = ?
            """, (entity_id,))
            incoming = [self._row_to_entity(row) for row in cursor.fetchall()]

            return {
                "outgoing": outgoing,
                "incoming": incoming
            }

    def get_stats(self) -> Dict[str, Any]:
        """Get database statistics."""
        with self._get_conn() as conn:
            cursor = conn.cursor()

            # Total entities
            cursor.execute("SELECT COUNT(*) as count FROM entities")
            total = cursor.fetchone()['count']

            # By type
            cursor.execute("""
                SELECT entity_type, COUNT(*) as count
                FROM entities
                GROUP BY entity_type
                ORDER BY count DESC
            """)
            by_type = {row['entity_type']: row['count'] for row in cursor.fetchall()}

            # By service
            cursor.execute("""
                SELECT service, COUNT(*) as count
                FROM entities
                WHERE service IS NOT NULL
                GROUP BY service
                ORDER BY count DESC
            """)
            by_service = {row['service']: row['count'] for row in cursor.fetchall()}

            # Total links
            cursor.execute("SELECT COUNT(*) as count FROM links")
            total_links = cursor.fetchone()['count']

            return {
                "total_entities": total,
                "by_type": by_type,
                "by_service": by_service,
                "total_links": total_links
            }
