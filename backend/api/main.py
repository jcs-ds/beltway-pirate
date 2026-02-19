"""FastAPI main application for Beltway Pirate."""
# Platform Explorer endpoints added
import os
import re
import sys
import time
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict

from fastapi import FastAPI, Query, HTTPException
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.models.entities import Entity, SearchResult, GraphData, EntityType
from backend.db.sqlite_store import SQLiteStore
from backend.ingest.markdown_parser import parse_vault, parse_markdown_file
from backend.api.search import parse_natural_language_query, search_entities
from backend.api.entity_editor import (
    get_field_schema, serialize_entity_to_markdown,
    read_entity_file, write_entity_file, validate_wiki_links,
    extract_all_wiki_links, FieldSchema, EntityUpdateRequest, EntityUpdateResponse
)

app = FastAPI(
    title="Beltway Pirate API",
    description="API for exploring a DoD knowledge base",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize database with absolute path
db_path = Path(__file__).parent.parent.parent / "data" / "processed" / "dod.db"
db = SQLiteStore(str(db_path))


def _ensure_engagements_table():
    """Create engagements table if it doesn't exist."""
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS engagements (
            id TEXT PRIMARY KEY,
            entity_id TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            stage TEXT DEFAULT 'targeted',
            priority TEXT DEFAULT 'medium',
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_engagements_entity
        ON engagements(entity_id)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_engagements_stage
        ON engagements(stage)
    """)
    conn.commit()
    conn.close()


def _ensure_campaign_tables():
    """Create campaign-related tables if they don't exist."""
    import sqlite3
    conn = sqlite3.connect(str(db_path))

    # Main campaigns table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS campaigns (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            status TEXT DEFAULT 'active',
            campaign_type TEXT,
            target_program_id TEXT,
            target_value TEXT,
            target_close_date TEXT,
            probability INTEGER,
            lead_owner TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Campaign stakeholders junction table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS campaign_stakeholders (
            id TEXT PRIMARY KEY,
            campaign_id TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            role TEXT NOT NULL,
            influence_level TEXT,
            sentiment TEXT DEFAULT 'neutral',
            engagement_status TEXT DEFAULT 'not_contacted',
            owner TEXT,
            notes TEXT,
            last_contact_date TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(campaign_id, entity_id)
        )
    """)

    # Campaign milestones table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS campaign_milestones (
            id TEXT PRIMARY KEY,
            campaign_id TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            due_date TEXT,
            completed_date TEXT,
            status TEXT DEFAULT 'pending',
            related_stakeholders TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Indexes
    conn.execute("CREATE INDEX IF NOT EXISTS idx_campaigns_status ON campaigns(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_campaign_stakeholders_campaign ON campaign_stakeholders(campaign_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_campaign_milestones_campaign ON campaign_milestones(campaign_id)")

    # Migration: Add competitor_type column if it doesn't exist
    try:
        conn.execute("ALTER TABLE campaign_stakeholders ADD COLUMN competitor_type TEXT")
    except Exception:
        pass  # Column already exists

    # Migration: Add sort_order column if it doesn't exist
    try:
        conn.execute("ALTER TABLE campaign_stakeholders ADD COLUMN sort_order INTEGER DEFAULT 0")
    except Exception:
        pass  # Column already exists

    # Campaign readiness table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS campaign_readiness (
            id TEXT PRIMARY KEY,
            campaign_id TEXT NOT NULL,
            dimension TEXT NOT NULL,
            score INTEGER DEFAULT 5,
            notes TEXT,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(campaign_id, dimension)
        )
    """)

    # Campaign todos table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS campaign_todos (
            id TEXT PRIMARY KEY,
            campaign_id TEXT NOT NULL,
            dimension TEXT NOT NULL,
            text TEXT NOT NULL,
            completed INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.execute("CREATE INDEX IF NOT EXISTS idx_campaign_readiness_campaign ON campaign_readiness(campaign_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_campaign_todos_campaign ON campaign_todos(campaign_id)")

    conn.commit()
    conn.close()


def _get_stakeholder_categories() -> List[str]:
    """Get all distinct stakeholder categories from the database."""
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    cursor = conn.execute("""
        SELECT DISTINCT json_extract(metadata, '$.category') as category
        FROM entities
        WHERE json_extract(metadata, '$.category') IS NOT NULL
        AND json_extract(metadata, '$.category') != ''
        ORDER BY category
    """)
    categories = [row[0] for row in cursor.fetchall()]
    conn.close()
    return categories


# Engagement Pipeline Models
class EngagementCreate(BaseModel):
    entity_id: str
    entity_type: str
    stage: str = "targeted"
    priority: str = "medium"
    notes: str = ""


class EngagementUpdate(BaseModel):
    stage: Optional[str] = None
    priority: Optional[str] = None
    notes: Optional[str] = None


class EngagementStageUpdate(BaseModel):
    stage: str


class EngagementResponse(BaseModel):
    id: str
    entity_id: str
    entity_type: str
    entity_name: str
    entity_service: Optional[str]
    stage: str
    priority: str
    notes: str
    created_at: str
    updated_at: str


# Campaign Orchestrator Models
CAMPAIGN_STATUSES = ['planning', 'active', 'won', 'lost', 'on_hold']
CAMPAIGN_TYPES = ['OTA', 'SBIR', 'Direct', 'Partnership', 'Congressional']
STAKEHOLDER_ROLES = [
    'Program Office', 'Requirements Owner', 'End User', 'Technical Evaluator',
    'Congressional Champion', 'Prime Partner', 'Competitor Intel',
    'Contracting Officer', 'SETA/FFRDCs'
]
INFLUENCE_LEVELS = ['decision_maker', 'influencer', 'buyer', 'money_manager', 'gatekeeper', 'acquisition_manager']
SENTIMENTS = ['champion', 'advocate', 'neutral', 'skeptic', 'detractor']
ENGAGEMENT_STATUSES = ['not_contacted', 'engaged', 'committed', 'stalled']
MILESTONE_STATUSES = ['pending', 'in_progress', 'completed', 'blocked']


class CampaignCreate(BaseModel):
    name: str
    description: Optional[str] = None
    status: str = "active"
    campaign_type: Optional[str] = None
    target_program_id: Optional[str] = None
    target_value: Optional[str] = None
    target_close_date: Optional[str] = None
    probability: Optional[int] = None
    lead_owner: Optional[str] = None


class CampaignUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    campaign_type: Optional[str] = None
    target_program_id: Optional[str] = None
    target_value: Optional[str] = None
    target_close_date: Optional[str] = None
    probability: Optional[int] = None
    lead_owner: Optional[str] = None


class CampaignStakeholderCreate(BaseModel):
    entity_id: str
    entity_type: str
    role: str
    influence_level: Optional[str] = None
    sentiment: str = "neutral"
    engagement_status: str = "not_contacted"
    competitor_type: Optional[str] = None
    owner: Optional[str] = None
    notes: Optional[str] = None


class CampaignStakeholderUpdate(BaseModel):
    role: Optional[str] = None
    influence_level: Optional[str] = None
    sentiment: Optional[str] = None
    engagement_status: Optional[str] = None
    competitor_type: Optional[str] = None
    owner: Optional[str] = None
    notes: Optional[str] = None
    last_contact_date: Optional[str] = None
    sort_order: Optional[int] = None


class CampaignMilestoneCreate(BaseModel):
    title: str
    description: Optional[str] = None
    due_date: Optional[str] = None
    status: str = "pending"
    related_stakeholders: Optional[str] = None


class CampaignMilestoneUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    due_date: Optional[str] = None
    completed_date: Optional[str] = None
    status: Optional[str] = None
    related_stakeholders: Optional[str] = None


class CampaignReadinessUpdate(BaseModel):
    score: Optional[int] = None
    notes: Optional[str] = None


class CampaignTodoCreate(BaseModel):
    dimension: str
    text: str


class CampaignTodoUpdate(BaseModel):
    text: Optional[str] = None
    completed: Optional[bool] = None


# Cache for in-memory entities (for search)
_entities_cache: List[Entity] = []


def _get_engagement_with_entity(row: tuple, entities_by_id: Dict[str, Entity]) -> dict:
    """Convert engagement row to response dict with entity data joined."""
    eng_id, entity_id, entity_type, stage, priority, notes, created_at, updated_at = row
    entity = entities_by_id.get(entity_id)
    return {
        "id": eng_id,
        "entity_id": entity_id,
        "entity_type": entity_type,
        "entity_name": entity.title if entity else entity_id,
        "entity_service": entity.service if entity else None,
        "stage": stage,
        "priority": priority,
        "notes": notes or "",
        "created_at": created_at,
        "updated_at": updated_at,
    }


# Heartbeat tracking for auto-shutdown
_last_heartbeat: float = time.time()
_heartbeat_timeout: int = 15  # seconds without heartbeat before shutdown
_shutdown_checker_started: bool = False


def _check_heartbeat_and_shutdown():
    """Background thread that checks heartbeat and shuts down if no activity."""
    global _last_heartbeat
    import subprocess
    while True:
        time.sleep(5)  # Check every 5 seconds
        elapsed = time.time() - _last_heartbeat
        if elapsed > _heartbeat_timeout:
            print(f"\n[Beltway Pirate] No heartbeat for {int(elapsed)}s - shutting down...")
            # Kill node processes (frontend dev server) on Windows
            if sys.platform == 'win32':
                subprocess.run(['taskkill', '/F', '/IM', 'node.exe'],
                             capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            os._exit(0)


def _start_heartbeat_checker():
    """Start the background heartbeat checker thread."""
    global _shutdown_checker_started
    if not _shutdown_checker_started:
        _shutdown_checker_started = True
        thread = threading.Thread(target=_check_heartbeat_and_shutdown, daemon=True)
        thread.start()
        print("[Beltway Pirate] Heartbeat monitor started - will auto-shutdown when browser tab closes")


def get_vault_path() -> Path:
    """Get vault path from config or default."""
    # Try relative path first
    base_path = Path(__file__).parent.parent.parent
    vault_path = base_path.parent / "jcs-remote" / "Distributed"
    if vault_path.exists():
        return vault_path

    # Fallback to absolute path
    return Path("C:/Users/jcsul/OneDrive/Documents/jcs-remote/Distributed")


def is_reference_file(file_path: Path) -> bool:
    """Check if a file is a reference/summary file that should be excluded from API results.

    Excludes:
    - MOC (Map of Content) files
    - Summary and Landscape files
    - Reference folder files (army_programs, etc.)
    - Templates
    """
    filename = file_path.stem.lower()
    path_str = str(file_path).lower().replace('\\', '/')

    # Check for MOC files
    if filename.startswith("moc-") or filename.startswith("moc_"):
        return True
    # Check for summary files
    if "summary" in filename:
        return True
    # Check for landscape files
    if "landscape" in filename:
        return True
    # Check the path for MOCs folder
    if "/mocs/" in path_str:
        return True
    # Check for Reference folder - these are data sources, not primary entities
    if "/reference/" in path_str:
        return True
    # Check for Templates folder
    if "/templates/" in path_str:
        return True
    return False


def folder_name_to_display(name: str) -> str:
    """Convert folder name to display name with special case handling.

    Handles cases like:
    - 'S-T' -> 'S&T' (Science & Technology)
    - 'Air-Force' -> 'Air Force'
    - 'C5ISR-I2WD' -> 'C5ISR I2WD'
    """
    # Special cases where hyphen means something else
    special_cases = {
        "S-T": "S&T",
        "R-D": "R&D",
        "C-UAS": "C-UAS",  # Keep hyphen
        "OUSD-RE": "OUSD(R&E)",
    }

    if name in special_cases:
        return special_cases[name]

    # Default: replace hyphens with spaces
    return name.replace("-", " ")


@app.on_event("startup")
async def startup():
    """Initialize database on startup."""
    global _entities_cache

    # Ensure engagements table exists
    _ensure_engagements_table()

    # Ensure campaign tables exist
    _ensure_campaign_tables()

    # Check if database needs initialization
    stats = db.get_stats()
    if stats["total_entities"] == 0:
        print("Database empty, parsing vault...")
        vault_path = get_vault_path()
        if vault_path.exists():
            entities = parse_vault(vault_path)
            db.insert_entities(entities)
            _entities_cache = entities
            print(f"Loaded {len(entities)} entities")
        else:
            print(f"Vault not found at {vault_path}")
    else:
        print(f"Database has {stats['total_entities']} entities")
        _entities_cache = db.get_all_entities()


@app.get("/")
async def root():
    """API root."""
    return {
        "name": "DoD Intelligence Platform API",
        "version": "1.0.0",
        "endpoints": {
            "search": "/api/search?q={query}",
            "entities": "/api/entities",
            "entity": "/api/entities/{id}",
            "graph": "/api/graph",
            "stats": "/api/stats",
            "rebuild": "/api/rebuild (POST)"
        }
    }


@app.get("/api/search", response_model=List[SearchResult])
async def search(
    q: str = Query(..., description="Search query"),
    entity_type: Optional[str] = Query(None, description="Filter by entity type"),
    service: Optional[str] = Query(None, description="Filter by service"),
    domain: Optional[str] = Query(None, description="Filter by domain"),
    limit: int = Query(50, description="Maximum results")
):
    """Search entities with natural language query parsing."""
    # Try database FTS first
    try:
        # Get extra results to account for filtering
        results = db.search(q, entity_type=entity_type, service=service, domain=domain, limit=limit * 2)
        if results:
            # Filter out reference files
            results = [r for r in results if not is_reference_file(Path(r.entity.file_path))]
            return results[:limit]
    except Exception as e:
        print(f"FTS search error: {e}")

    # Fallback to in-memory search
    results = search_entities(_entities_cache, q, limit=limit * 2)

    # Apply additional filters
    if entity_type:
        results = [r for r in results if r.entity.entity_type == entity_type or
                   (isinstance(r.entity.entity_type, EntityType) and r.entity.entity_type.value == entity_type)]
    if service:
        results = [r for r in results if r.entity.service and service.lower() in r.entity.service.lower()]
    if domain:
        results = [r for r in results if r.entity.domain and domain.lower() in r.entity.domain.lower()]

    # Filter out reference files
    results = [r for r in results if not is_reference_file(Path(r.entity.file_path))]

    return results[:limit]


@app.get("/api/entities", response_model=List[Entity])
async def list_entities(
    entity_type: Optional[str] = Query(None, description="Filter by entity type"),
    service: Optional[str] = Query(None, description="Filter by service"),
    limit: int = Query(100, description="Maximum results")
):
    """List entities with optional filters."""
    if entity_type:
        entities = db.get_entities_by_type(entity_type, service=service, limit=limit * 2)
    else:
        entities = db.get_all_entities()
        if service:
            entities = [e for e in entities if e.service and service.lower() in e.service.lower()]

    # Filter out reference files
    entities = [e for e in entities if not is_reference_file(Path(e.file_path))]
    entities = entities[:limit]

    return entities


# NOTE: More specific routes (with /editable, /relationships, /autocomplete) MUST come BEFORE
# the generic {entity_id:path} route, otherwise the path converter is greedy
# and will consume the entire path including the suffix.

@app.get("/api/entities/autocomplete")
async def autocomplete_entities(
    q: str = Query(..., min_length=2, description="Search query"),
    types: Optional[str] = Query(None, description="Comma-separated entity types to include"),
    limit: int = Query(20, description="Max results"),
):
    """Autocomplete search for entities (for engagement quick-add)."""
    query_lower = q.lower()

    # Filter by types if specified
    type_filter = None
    if types:
        type_filter = set(t.strip() for t in types.split(","))

    results = []
    for entity in _entities_cache:
        # Skip if type filter doesn't match
        if type_filter and entity.entity_type not in type_filter:
            continue

        # Check if query matches title
        if query_lower in entity.title.lower():
            results.append({
                "id": entity.id,
                "title": entity.title,
                "entity_type": entity.entity_type,
                "service": entity.service,
            })

            if len(results) >= limit:
                break

    return {"results": results}


@app.get("/api/entities/{entity_id:path}/editable")
async def get_editable_entity(entity_id: str):
    """Get entity with its editable field schema."""
    entity = db.get_entity(entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")

    # Get the entity type
    entity_type = entity.entity_type.value if isinstance(entity.entity_type, EntityType) else entity.entity_type

    # Check if this is a unit in the Stakeholders path - if so, use stakeholder schema
    # Requirements orgs are stored as "unit" type but live in Stakeholders/Requirements/
    # and should use the stakeholder editing schema
    file_path_lower = (entity.file_path or "").lower().replace("\\", "/")
    is_stakeholder_path = "stakeholders/" in file_path_lower

    # Use stakeholder schema for entities in Stakeholders path (both Enablers and Requirements)
    schema_type = "stakeholder" if is_stakeholder_path else entity_type

    # Get the field schema for this entity type
    schema = get_field_schema(schema_type)

    # Convert to dict for modification
    schema_dict = schema.model_dump()

    # For stakeholder entities, dynamically populate category options from database
    if schema_type == "stakeholder":
        categories = _get_stakeholder_categories()
        if categories:
            for field in schema_dict["fields"]:
                if field["name"] == "category":
                    field["options"] = categories
                    break

    # Extract current values for each field from entity
    current_values = {
        "title": entity.title,
        "service": entity.service,
        "domain": entity.domain,
        "tags": entity.tags,
    }

    # Add metadata values
    if entity.metadata:
        for field in schema.fields:
            if field.name in entity.metadata:
                current_values[field.name] = entity.metadata[field.name]

    # For content section fields, read from the actual markdown file
    vault_path = get_vault_path()
    entity_file = vault_path / f"{entity_id}.md"
    if entity_file.exists():
        try:
            with open(entity_file, 'r', encoding='utf-8') as f:
                content = f.read()

            # Extract content sections (Overview, Notes, etc.)
            for field in schema.fields:
                if field.section == "content":
                    # Look for the section in the markdown
                    section_pattern = rf'^## {re.escape(field.label)}\s*\n(.*?)(?=^## |\Z)'
                    section_match = re.search(section_pattern, content, re.MULTILINE | re.DOTALL | re.IGNORECASE)
                    if section_match:
                        section_content = section_match.group(1).strip()
                        # Only set if there's actual content (not just placeholder text)
                        if section_content and not section_content.startswith('{{'):
                            current_values[field.name] = section_content
        except Exception as e:
            print(f"Error reading entity file for edit: {e}")

    return {
        "entity": entity,
        "schema": schema_dict,
        "current_values": current_values
    }


@app.get("/api/entities/{entity_id:path}/relationships")
async def get_entity_relationships(entity_id: str):
    """Get entity relationships (links and backlinks)."""
    entity = db.get_entity(entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")

    links = db.get_entity_links(entity_id)
    return links


@app.get("/api/entities/{entity_id:path}", response_model=Entity)
async def get_entity(entity_id: str):
    """Get entity by ID or resolve short name to full path."""
    # First try exact match by ID
    entity = db.get_entity(entity_id)
    if entity:
        return entity

    # If not found, try to resolve by title/short name using db method
    entity = db.get_entity_by_title(entity_id)
    if entity:
        return entity

    # Also try with dashes converted to spaces (e.g., "Magnetic-Quantum" -> "Magnetic Quantum")
    search_name = entity_id.replace('-', ' ').replace('_', ' ')
    if search_name != entity_id:
        entity = db.get_entity_by_title(search_name)
        if entity:
            return entity

    raise HTTPException(status_code=404, detail="Entity not found")


@app.put("/api/entities/{entity_id:path}", response_model=EntityUpdateResponse)
async def update_entity(entity_id: str, updates: Dict):
    """
    Update an entity and write changes back to the vault markdown file.

    This endpoint:
    1. Validates the entity exists
    2. Reads the current markdown file
    3. Merges updates with existing content
    4. Writes the updated markdown back to the vault
    5. Re-parses the file and updates the database
    """
    global _entities_cache

    # Get existing entity
    entity = db.get_entity(entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")

    # Get entity type
    entity_type = entity.entity_type.value if isinstance(entity.entity_type, EntityType) else entity.entity_type

    # Get vault path
    vault_path = get_vault_path()

    # Ensure we have the file path
    if not entity.file_path:
        raise HTTPException(status_code=500, detail="Entity has no file path")

    warnings = []

    try:
        # Read current file content
        existing_metadata, existing_content = read_entity_file(vault_path, entity.file_path)

        # Validate wiki links if present
        schema = get_field_schema(entity_type)
        wiki_links = extract_all_wiki_links(updates, schema)
        if wiki_links:
            invalid_links = validate_wiki_links(wiki_links, db)
            if invalid_links:
                warnings.extend([f"Link not found: {link}" for link in invalid_links])

        # Serialize updates to markdown
        new_markdown = serialize_entity_to_markdown(
            existing_content=existing_content,
            existing_metadata=existing_metadata,
            updates=updates,
            entity_type=entity_type
        )

        # Write back to file
        write_entity_file(vault_path, entity.file_path, new_markdown)

        # Re-parse the file and update database
        file_path = vault_path / entity.file_path
        updated_entity = parse_markdown_file(file_path, vault_path)

        # Update in database
        db.insert_entity(updated_entity)

        # Update cache
        for i, e in enumerate(_entities_cache):
            if e.id == entity_id:
                _entities_cache[i] = updated_entity
                break

        return EntityUpdateResponse(
            success=True,
            entity_id=entity_id,
            warnings=warnings,
            message="Entity updated successfully"
        )

    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update entity: {str(e)}")


@app.get("/api/graph", response_model=GraphData)
async def get_graph(
    root: Optional[str] = Query(None, description="Root entity ID"),
    depth: int = Query(2, description="Graph depth")
):
    """Get relationship graph data."""
    return db.get_graph_data(root_id=root, depth=depth)


@app.get("/api/heartbeat")
async def heartbeat():
    """Heartbeat endpoint - frontend calls this to keep server alive."""
    global _last_heartbeat
    _last_heartbeat = time.time()
    _start_heartbeat_checker()  # Start checker on first heartbeat
    return {"status": "alive", "timestamp": _last_heartbeat}


@app.get("/api/stats")
async def get_stats():
    """Get database statistics."""
    return db.get_stats()


@app.get("/api/types")
async def get_entity_types():
    """Get available entity types."""
    stats = db.get_stats()
    return {
        "types": list(stats["by_type"].keys()),
        "counts": stats["by_type"]
    }


@app.get("/api/services")
async def get_services():
    """Get available services."""
    stats = db.get_stats()
    return {
        "services": list(stats["by_service"].keys()),
        "counts": stats["by_service"]
    }


@app.post("/api/rebuild")
async def rebuild_database():
    """Rebuild database from vault."""
    global _entities_cache

    vault_path = get_vault_path()
    if not vault_path.exists():
        raise HTTPException(status_code=500, detail=f"Vault not found at {vault_path}")

    db.clear()
    entities = parse_vault(vault_path)
    db.insert_entities(entities)
    _entities_cache = entities

    stats = db.get_stats()
    return {
        "message": "Database rebuilt successfully",
        "stats": stats
    }


@app.get("/api/stakeholders", response_model=List[Entity])
async def get_stakeholders(
    service: Optional[str] = Query(None, description="Filter by service"),
    limit: int = Query(100, description="Maximum results")
):
    """Get stakeholder organizations (acquisition, R&D, etc.)."""
    return db.get_entities_by_type("stakeholder", service=service, limit=limit)


@app.get("/api/programs", response_model=List[Entity])
async def get_programs(
    service: Optional[str] = Query(None, description="Filter by service"),
    limit: int = Query(100, description="Maximum results")
):
    """Get acquisition programs."""
    return db.get_entities_by_type("program", service=service, limit=limit)


@app.get("/api/platforms", response_model=List[Entity])
async def get_platforms(
    service: Optional[str] = Query(None, description="Filter by service"),
    limit: int = Query(100, description="Maximum results")
):
    """Get platforms."""
    return db.get_entities_by_type("platform", service=service, limit=limit)


@app.get("/api/companies", response_model=List[Entity])
async def get_companies(limit: int = Query(100)):
    """Get companies."""
    return db.get_entities_by_type("company", limit=limit)


# Legacy endpoint for backwards compatibility
@app.get("/api/competitors", response_model=List[Entity])
async def get_competitors(limit: int = Query(100)):
    """Get companies (legacy endpoint, use /api/companies instead)."""
    return db.get_entities_by_type("company", limit=limit)


def strip_obsidian_syntax(text: str) -> str:
    """Strip Obsidian wiki-link syntax like [[Link]] or [[Link|Display]]."""
    import re
    # Replace [[Link|Display]] with Display
    text = re.sub(r'\[\[([^\]|]+)\|([^\]]+)\]\]', r'\2', text)
    # Replace [[Link]] with Link
    text = re.sub(r'\[\[([^\]]+)\]\]', r'\1', text)
    # Replace {{FLAG: Name}} with Name
    text = re.sub(r'\{\{FLAG:\s*([^}]+)\}\}', r'\1', text)
    return text


def extract_overview(content: str, max_length: int = 200) -> str:
    """Extract the first paragraph of the Overview section from markdown content."""
    lines = content.split('\n')
    in_overview = False
    overview_lines = []

    for line in lines:
        if line.strip().startswith('## Overview'):
            in_overview = True
            continue
        if in_overview:
            if line.strip().startswith('## '):
                break
            if line.strip():
                overview_lines.append(line.strip())
                # Just get first paragraph
                if len(overview_lines) == 1:
                    break

    overview = ' '.join(overview_lines)
    # Strip Obsidian syntax
    overview = strip_obsidian_syntax(overview)
    if len(overview) > max_length:
        overview = overview[:max_length].rsplit(' ', 1)[0] + '...'
    return overview


@app.get("/api/modalities")
async def get_modalities():
    """Get all sensing modalities for the Technology Explorer."""
    import frontmatter

    vault_path = get_vault_path()
    modalities_path = vault_path / "Technology" / "Modalities"

    modalities = []

    if modalities_path.exists():
        for folder in modalities_path.iterdir():
            if folder.is_dir():
                if folder.name == "Multi-Modal":
                    # Multi-Modal files are paired: Name.md and Name-Techniques.md
                    for f in folder.glob("*.md"):
                        # Skip technique files
                        if "-Techniques" in f.stem:
                            continue

                        techniques_file = folder / f"{f.stem}-Techniques.md"

                        # Extract overview from the file
                        overview = ""
                        try:
                            with open(f, 'r', encoding='utf-8') as file:
                                post = frontmatter.load(file)
                                overview = extract_overview(post.content)
                        except:
                            pass

                        modalities.append({
                            "id": f"Multi-Modal/{f.stem}",
                            "name": f.stem.replace("-", " "),
                            "modality_file": str(f.relative_to(vault_path)),
                            "has_techniques": techniques_file.exists(),
                            "techniques_file": str(techniques_file.relative_to(vault_path)) if techniques_file.exists() else None,
                            "overview": overview,
                            "category": "multi-modal"
                        })
                else:
                    modality_file = folder / f"{folder.name}.md"
                    techniques_file = folder / "Techniques.md"

                    if modality_file.exists():
                        # Extract overview from the file
                        overview = ""
                        try:
                            with open(modality_file, 'r', encoding='utf-8') as f:
                                post = frontmatter.load(f)
                                overview = extract_overview(post.content)
                        except:
                            pass

                        modalities.append({
                            "id": folder.name,
                            "name": folder.name.replace("-", " "),
                            "modality_file": str(modality_file.relative_to(vault_path)),
                            "has_techniques": techniques_file.exists(),
                            "techniques_file": str(techniques_file.relative_to(vault_path)) if techniques_file.exists() else None,
                            "overview": overview,
                            "category": "sensing"
                        })

    return {
        "modalities": sorted(modalities, key=lambda x: x["name"])
    }


@app.get("/api/modalities/{modality_id:path}")
async def get_modality_detail(modality_id: str):
    """Get detailed information for a specific modality including market landscape, techniques, and counter-techniques."""
    import frontmatter

    vault_path = get_vault_path()

    # Handle Multi-Modal paths (e.g., "Multi-Modal/Inertial-Navigation")
    if modality_id.startswith("Multi-Modal/"):
        base_name = modality_id.split("/")[1]
        modality_path = vault_path / "Technology" / "Modalities" / "Multi-Modal"
        modality_file = modality_path / f"{base_name}.md"
        techniques_file = modality_path / f"{base_name}-Techniques.md"
        display_name = base_name.replace("-", " ")
    else:
        modality_path = vault_path / "Technology" / "Modalities" / modality_id
        modality_file = modality_path / f"{modality_id}.md"
        techniques_file = modality_path / "Techniques.md"
        display_name = modality_id.replace("-", " ")

    if not modality_file.exists():
        raise HTTPException(status_code=404, detail=f"Modality {modality_id} not found")

    result = {
        "id": modality_id,
        "name": display_name,
        "market_landscape": None,
        "techniques": None,
    }

    # Load main modality file (market landscape)
    if modality_file.exists():
        with open(modality_file, 'r', encoding='utf-8') as f:
            post = frontmatter.load(f)
            result["market_landscape"] = {
                "content": post.content,
                "metadata": dict(post.metadata),
                "tags": post.get("tags", [])
            }

    # Load techniques file
    if techniques_file.exists():
        with open(techniques_file, 'r', encoding='utf-8') as f:
            post = frontmatter.load(f)
            result["techniques"] = {
                "content": post.content,
                "metadata": dict(post.metadata),
                "tags": post.get("tags", [])
            }

    # Find related programs, buyers, and companies from the database
    # Search for entities that mention this modality
    search_terms = [modality_id.lower(), modality_id.replace("-", " ").lower()]

    related_programs = []
    related_buyers = []
    related_companies = []

    for entity in _entities_cache:
        # Skip reference/summary files
        if is_reference_file(Path(entity.file_path)):
            continue
        # Skip files with "landscape" or "summary" in title
        title_lower = entity.title.lower()
        if "landscape" in title_lower or "summary" in title_lower:
            continue

        entity_text = (entity.content + " " + " ".join(entity.tags)).lower()
        if any(term in entity_text for term in search_terms):
            if entity.entity_type == EntityType.PROGRAM or (hasattr(entity.entity_type, 'value') and entity.entity_type.value == 'program'):
                related_programs.append({"id": entity.id, "title": entity.title, "service": entity.service})
            elif entity.entity_type == EntityType.STAKEHOLDER or (hasattr(entity.entity_type, 'value') and entity.entity_type.value == 'stakeholder'):
                related_buyers.append({"id": entity.id, "title": entity.title, "service": entity.service})
            elif entity.entity_type == EntityType.COMPANY or (hasattr(entity.entity_type, 'value') and entity.entity_type.value == 'company'):
                related_companies.append({"id": entity.id, "title": entity.title, "threat_level": entity.metadata.get("threat_level")})

    result["related_programs"] = related_programs[:20]
    result["related_buyers"] = related_buyers[:20]
    result["related_companies"] = related_companies[:20]

    return result


@app.get("/api/peos")
async def get_peos(service: Optional[str] = Query(None, description="Filter by service")):
    """Get all PEO (Program Executive Office) entities."""
    peos = []
    for entity in _entities_cache:
        # Check if it's a PEO by looking at file path or tags
        if 'peo' in entity.file_path.lower() or 'peo' in [t.lower() for t in entity.tags]:
            if service is None or (entity.service and service.lower() in entity.service.lower()):
                peos.append(entity)

    return sorted(peos, key=lambda x: (x.service or "", x.title))


@app.get("/api/platforms/explorer")
async def get_platforms_explorer(
    domain: Optional[str] = Query(None, description="Filter by domain (Air, Sea, Land, Space, Fixed, SOCOM)"),
    service: Optional[str] = Query(None, description="Filter by service"),
    payload_type: Optional[str] = Query(None, description="Filter by payload type (EW, SIGINT, ISR, Radar, C-UAS, Comms)")
):
    """Get platforms organized by domain and subcategory for Platform Explorer."""
    import frontmatter

    vault_path = get_vault_path()
    platforms_path = vault_path / "Platforms"

    # Define domain order and mapping
    domain_order = ["Air", "Sea", "Land", "Space", "Fixed", "SOCOM", "Coast-Guard", "Counter-UAS", "EW", "SIGINT"]

    result = {
        "domains": [],
        "filters": {
            "domains": [],
            "services": set(),
            "payload_types": ["EW", "SIGINT", "ISR", "Radar", "C-UAS", "Comms"]
        }
    }

    if not platforms_path.exists():
        return result

    # Process each domain folder
    for domain_folder in sorted(platforms_path.iterdir(), key=lambda x: domain_order.index(x.name) if x.name in domain_order else 100):
        if not domain_folder.is_dir():
            continue

        domain_name = domain_folder.name

        # Apply domain filter
        if domain and domain.lower() != domain_name.lower():
            continue

        result["filters"]["domains"].append(domain_name)

        domain_data = {
            "name": domain_name,
            "subcategories": [],
            "platform_count": 0
        }

        # Check if this domain has subcategories or direct platform files
        has_subcategories = any(f.is_dir() for f in domain_folder.iterdir())

        if has_subcategories:
            for subcat_folder in sorted(domain_folder.iterdir()):
                if not subcat_folder.is_dir():
                    continue

                subcat_data = {
                    "name": subcat_folder.name.replace("-", " "),
                    "platforms": []
                }

                for platform_file in sorted(subcat_folder.glob("*.md")):
                    try:
                        with open(platform_file, 'r', encoding='utf-8') as f:
                            post = frontmatter.load(f)

                        platform_service = post.get("service", "")
                        if platform_service:
                            result["filters"]["services"].add(platform_service)

                        # Apply service filter
                        if service and service.lower() not in platform_service.lower():
                            continue

                        # Apply payload type filter
                        if payload_type:
                            tags = post.get("tags", [])
                            content_lower = post.content.lower()
                            payload_lower = payload_type.lower()
                            if payload_lower not in [t.lower() for t in tags] and payload_lower not in content_lower:
                                continue

                        # Extract current systems from content
                        current_systems = []
                        content = post.content
                        if "## Current EW" in content or "## Defensive/EW" in content:
                            lines = content.split("\n")
                            in_systems = False
                            for line in lines:
                                if "## Current EW" in line or "## Defensive/EW" in line:
                                    in_systems = True
                                    continue
                                if in_systems and line.startswith("##"):
                                    break
                                if in_systems and line.startswith("- "):
                                    system = line.replace("- ", "").split(" - ")[0].strip()
                                    if system:
                                        current_systems.append(system)

                        platform_data = {
                            "id": f"Platforms/{domain_name}/{subcat_folder.name}/{platform_file.stem}",
                            "name": platform_file.stem.replace("-", " "),
                            "service": platform_service,
                            "domain": post.get("domain", f"{domain_name} - {subcat_folder.name}"),
                            "status": post.get("status", ""),
                            "platform_count": post.get("platform_count", ""),
                            "unit_cost": post.get("unit_cost", ""),
                            "program_office": post.get("program_office", "").replace("[[", "").replace("]]", ""),
                            "current_systems": current_systems[:5],
                            "tags": post.get("tags", [])
                        }
                        subcat_data["platforms"].append(platform_data)
                        domain_data["platform_count"] += 1
                    except Exception as e:
                        print(f"Error parsing {platform_file}: {e}")
                        continue

                if subcat_data["platforms"]:
                    domain_data["subcategories"].append(subcat_data)
        else:
            # Direct platform files in domain folder
            subcat_data = {
                "name": "General",
                "platforms": []
            }

            for platform_file in sorted(domain_folder.glob("*.md")):
                try:
                    with open(platform_file, 'r', encoding='utf-8') as f:
                        post = frontmatter.load(f)

                    platform_service = post.get("service", "")
                    if platform_service:
                        result["filters"]["services"].add(platform_service)

                    if service and service.lower() not in platform_service.lower():
                        continue

                    if payload_type:
                        tags = post.get("tags", [])
                        content_lower = post.content.lower()
                        payload_lower = payload_type.lower()
                        if payload_lower not in [t.lower() for t in tags] and payload_lower not in content_lower:
                            continue

                    platform_data = {
                        "id": f"Platforms/{domain_name}/{platform_file.stem}",
                        "name": platform_file.stem.replace("-", " "),
                        "service": platform_service,
                        "domain": post.get("domain", domain_name),
                        "status": post.get("status", ""),
                        "platform_count": post.get("platform_count", ""),
                        "unit_cost": post.get("unit_cost", ""),
                        "program_office": post.get("program_office", "").replace("[[", "").replace("]]", ""),
                        "current_systems": [],
                        "tags": post.get("tags", [])
                    }
                    subcat_data["platforms"].append(platform_data)
                    domain_data["platform_count"] += 1
                except Exception as e:
                    print(f"Error parsing {platform_file}: {e}")
                    continue

            if subcat_data["platforms"]:
                domain_data["subcategories"].append(subcat_data)

        if domain_data["subcategories"]:
            result["domains"].append(domain_data)

    result["filters"]["services"] = sorted(list(result["filters"]["services"]))
    return result


def _normalize_service(raw_service: str) -> list:
    """Split compound service strings into individual canonical services.
    'Army, Marines, Air Force' -> ['Army', 'Marines', 'Air Force']
    'Army (Joint primary)' -> ['Army']
    'USSOCOM, Navy SEALs' -> ['USSOCOM']
    """
    canonical_services = {
        # Services
        "army": "Army",
        "navy": "Navy",
        "air force": "Air Force",
        "af": "Air Force",
        "marines": "Marines",
        "coast guard": "Coast Guard",
        "space force": "Space Force",
        "ussocom": "USSOCOM",
        "socom": "USSOCOM",
        "msc": "Navy",
        "joint": "Joint",
        # COCOMs
        "indopacom": "INDOPACOM",
        "eucom": "EUCOM",
        "centcom": "CENTCOM",
        "africom": "AFRICOM",
        "northcom": "NORTHCOM",
        "southcom": "SOUTHCOM",
        "spacecom": "SPACECOM",
        "cybercom": "CYBERCOM",
        "transcom": "TRANSCOM",
        "stratcom": "STRATCOM",
    }
    if not raw_service:
        return []
    # Split on comma, then try to match each part
    parts = [p.strip() for p in raw_service.replace("/", ",").split(",")]
    result = set()
    for part in parts:
        part_lower = part.lower().strip()
        # Direct match
        if part_lower in canonical_services:
            result.add(canonical_services[part_lower])
            continue
        # Check if canonical name is contained in the part (handles "Army (Joint primary)", "Air Force (AFSOC)")
        matched = False
        for key, canonical in canonical_services.items():
            if key in part_lower:
                result.add(canonical)
                matched = True
                break
        if not matched and part.strip():
            # Skip generic phrases like "All aviation services"
            if "all " in part_lower:
                continue
            result.add(part.strip())
    return sorted(result)


def _normalize_country(raw_country: str) -> list:
    """Split compound country strings into individual countries.
    'Russia (manufactured), China (operator)' -> ['Russia', 'China']
    """
    if not raw_country:
        return []
    parts = [p.strip() for p in raw_country.split(",")]
    result = set()
    for part in parts:
        # Strip parenthetical annotations like "(manufactured)"
        import re as _re
        clean = _re.sub(r'\s*\(.*?\)\s*', '', part).strip()
        if clean:
            result.add(clean)
    return sorted(result)


def _normalize_program_domain(raw_domain: str) -> str:
    """Map granular program domains to high-level groupings."""
    if not raw_domain:
        return ""
    d = raw_domain.lower()

    # Air & Missile Defense
    if any(k in d for k in ["air defense", "missile defense", "c-uas", "counter-uas", "directed energy", "shorad"]):
        return "Air & Missile Defense"
    # Electronic Warfare / SIGINT / Cyber
    if any(k in d for k in ["electronic warfare", "ew", "sigint", "cyber", "information"]):
        return "EW / Cyber / SIGINT"
    # Intelligence / ISR
    if any(k in d for k in ["intelligence", "isr", "surveillance", "reconnaissance", "exploitation", "targeting"]):
        return "Intelligence / ISR"
    # Space
    if any(k in d for k in ["space", "satellite", "pnt", "navigation", "pwsa"]):
        return "Space"
    # C2 / Networks / Communications
    if any(k in d for k in ["command", "control", "c2", "c3", "c4", "c5", "network", "communication", "data link", "tactical data"]):
        return "C2 / Networks"
    # AI / Autonomy / Unmanned
    if any(k in d for k in ["ai", "artificial intelligence", "autonom", "unmanned", "data"]):
        return "AI / Autonomy"
    # Fires / Strike / Weapons
    if any(k in d for k in ["fire", "strike", "weapon", "munition", "hypersonic", "missile", "nuclear"]):
        return "Fires / Strike"
    # Aviation
    if any(k in d for k in ["aviation", "aircraft", "rotary", "airlift", "tanker", "fighter", "tactical a", "light attack"]):
        return "Aviation"
    # Ground Combat / Maneuver / Vehicles
    if any(k in d for k in ["ground", "armor", "maneuver", "vehicle", "infantry", "combat system", "soldier"]):
        return "Ground Combat"
    # Naval / Maritime
    if any(k in d for k in ["naval", "maritime", "ship", "submarine", "undersea", "surface", "carrier", "amphibi", "watercraft"]):
        return "Naval / Maritime"
    # Special Operations
    if any(k in d for k in ["special operation", "sof", "socom"]):
        return "Special Operations"
    # Sustainment / Support
    if any(k in d for k in ["sustainment", "logistics", "support", "medical", "training", "simulation", "enterprise", "digital", "software", "manpower", "test"]):
        return "Sustainment / Support"
    # Sensors / Radar
    if any(k in d for k in ["sensor", "radar"]):
        return "Sensors"
    # Catch-all by service name
    if any(k in d for k in ["army", "navy", "air force", "marines", "usmc", "dod", "joint"]):
        return "Joint / DoD"
    return "Other"


def _normalize_political_role(raw_role: str) -> str:
    """Map granular political roles to committee-level groupings."""
    if not raw_role:
        return ""
    r = raw_role.upper()
    if "SASC" in r:
        return "SASC"
    if "HASC" in r:
        return "HASC"
    if "SAC-DEFENSE" in r or "SAC-DEF" in r:
        return "SAC-Defense"
    if "HAC-DEFENSE" in r or "HAC-DEF" in r:
        return "HAC-Defense"
    if "SSCI" in r:
        return "SSCI"
    if "HPSCI" in r:
        return "HPSCI"
    if "HSGAC" in r:
        return "HSGAC"
    if "CHS " in r or r.startswith("CHS"):
        return "CHS"
    if "BUDGET" in r:
        return "Budget"
    if "APPROPRIATION" in r:
        return "Appropriations"
    if "CAUCUS" in r or "CONFERENCE" in r:
        return "Leadership"
    if "LEADER" in r or "CHAIRMAN" in r.split()[0] if r.split() else "":
        return "Leadership"
    if "DEFENSE MOD" in r:
        return "Defense Caucus"
    if "FORMER" in r:
        return "Former Leadership"
    return "Other"


@app.get("/api/platforms/browser")
async def get_platforms_browser(
    view: str = Query("blue", description="View: blue or red"),
    service_filter: Optional[str] = Query(None, description="Filter by service (blue) - supports comma-separated for multi-select"),
    country_filter: Optional[str] = Query(None, description="Filter by country (red) - supports comma-separated for multi-select")
):
    """Get platforms organized by domain and platform type for three-panel browser."""
    import frontmatter

    vault_path = get_vault_path()
    # Navigate into Blue or Red subfolder
    force_folder = "Blue" if view.lower() == "blue" else "Red"
    platforms_path = vault_path / "Platforms" / force_folder

    is_red = view.lower() == "red"

    # Parse comma-separated filter values for multi-select
    service_values = [v.strip().lower() for v in service_filter.split(",")] if service_filter else []
    country_values = [v.strip().lower() for v in country_filter.split(",")] if country_filter else []

    result = {
        "view": view.lower(),
        "domains": [],
        "filters": {
            "services": set(),
            "countries": set()
        }
    }

    if not platforms_path.exists():
        result["filters"]["services"] = []
        result["filters"]["countries"] = []
        return result

    # Collect all platforms first, then organize by domain -> platform type
    # Sort domains alphabetically
    for domain_folder in sorted(platforms_path.iterdir(), key=lambda x: x.name):
        if not domain_folder.is_dir():
            continue

        domain_name = domain_folder.name
        domain_data = {
            "name": domain_name,
            "platform_count": 0,
            "platform_types": []
        }

        # Group by platform type (subcategory)
        platform_types = {}

        # Check if this domain has subcategories or direct platform files
        has_subcategories = any(f.is_dir() for f in domain_folder.iterdir())

        if has_subcategories:
            for subcat_folder in sorted(domain_folder.iterdir()):
                if not subcat_folder.is_dir():
                    continue

                type_name = subcat_folder.name.replace("-", " ")
                if type_name not in platform_types:
                    platform_types[type_name] = []

                for platform_file in sorted(subcat_folder.glob("*.md")):
                    try:
                        with open(platform_file, 'r', encoding='utf-8') as f:
                            post = frontmatter.load(f)

                        if is_red:
                            platform_force = post.get("force", "")
                            platform_country = post.get("country", "")
                            if platform_force:
                                result["filters"]["services"].add(platform_force)
                            # Normalize country for filters
                            normalized_countries = _normalize_country(platform_country)
                            for nc in normalized_countries:
                                result["filters"]["countries"].add(nc)
                            # Red uses country_filter (match against normalized)
                            if country_values and not any(nc.lower() in country_values for nc in normalized_countries):
                                continue
                        else:
                            platform_service = post.get("service", "")
                            # Normalize service for filters (split compound values)
                            normalized_services = _normalize_service(platform_service)
                            for ns in normalized_services:
                                result["filters"]["services"].add(ns)
                            # Match if ANY selected service matches ANY normalized service
                            if service_values and not any(ns.lower() in service_values for ns in normalized_services):
                                continue

                        platform_name = platform_file.stem.replace("-", " ")
                        image_filename = platform_file.stem.lower()
                        platform_data = {
                            "id": f"Platforms/{force_folder}/{domain_name}/{subcat_folder.name}/{platform_file.stem}",
                            "name": platform_name,
                            "service": post.get("force", "") if is_red else post.get("service", ""),
                            "country": post.get("country", "") if is_red else "",
                            "status": post.get("status", ""),
                            "tags": post.get("tags", []),
                            "image_url": f"/assets/platforms/{image_filename}.png"
                        }
                        platform_types[type_name].append(platform_data)
                        domain_data["platform_count"] += 1
                    except Exception as e:
                        print(f"Error parsing {platform_file}: {e}")
                        continue
        else:
            # Direct platform files in domain folder
            type_name = "General"
            if type_name not in platform_types:
                platform_types[type_name] = []

            for platform_file in sorted(domain_folder.glob("*.md")):
                try:
                    with open(platform_file, 'r', encoding='utf-8') as f:
                        post = frontmatter.load(f)

                    if is_red:
                        platform_force = post.get("force", "")
                        platform_country = post.get("country", "")
                        if platform_force:
                            result["filters"]["services"].add(platform_force)
                        normalized_countries = _normalize_country(platform_country)
                        for nc in normalized_countries:
                            result["filters"]["countries"].add(nc)
                        if country_values and not any(nc.lower() in country_values for nc in normalized_countries):
                            continue
                    else:
                        platform_service = post.get("service", "")
                        normalized_services = _normalize_service(platform_service)
                        for ns in normalized_services:
                            result["filters"]["services"].add(ns)
                        if service_values and not any(ns.lower() in service_values for ns in normalized_services):
                            continue

                    platform_name = platform_file.stem.replace("-", " ")
                    image_filename = platform_file.stem.lower()
                    platform_data = {
                        "id": f"Platforms/{force_folder}/{domain_name}/{platform_file.stem}",
                        "name": platform_name,
                        "service": post.get("force", "") if is_red else post.get("service", ""),
                        "country": post.get("country", "") if is_red else "",
                        "status": post.get("status", ""),
                        "tags": post.get("tags", []),
                        "image_url": f"/assets/platforms/{image_filename}.png"
                    }
                    platform_types[type_name].append(platform_data)
                    domain_data["platform_count"] += 1
                except Exception as e:
                    print(f"Error parsing {platform_file}: {e}")
                    continue

        # Build platform types list
        for type_name, platforms in sorted(platform_types.items()):
            if platforms:
                domain_data["platform_types"].append({
                    "name": type_name,
                    "platform_count": len(platforms),
                    "platforms": sorted(platforms, key=lambda x: x["name"])
                })

        if domain_data["platform_count"] > 0:
            result["domains"].append(domain_data)

    result["filters"]["services"] = sorted(list(result["filters"]["services"]))
    result["filters"]["countries"] = sorted(list(result["filters"]["countries"]))
    return result


@app.get("/api/units/browser")
async def get_units_browser(
    cocom_filter: Optional[str] = Query(None, description="Filter by COCOM - supports comma-separated for multi-select")
):
    """Get units organized by service and unit type for three-panel browser.

    Uses actual folder structure from Vault instead of keyword-based categorization.
    Structure: Organizations/{Service}/Units/{UnitType}/*.md
    """
    import frontmatter

    vault_path = get_vault_path()
    orgs_path = vault_path / "Organizations"

    # Service folder mappings - new structure uses Units/ folder
    # Fall back to Operational-Units for backwards compatibility
    def get_units_folder(service_folder: str) -> Path:
        """Get the units folder path, preferring new structure."""
        new_path = orgs_path / service_folder / "Units"
        old_path = orgs_path / service_folder / "Operational-Units"
        if new_path.exists():
            return new_path
        return old_path

    service_folders = {
        "AFRICOM": get_units_folder("AFRICOM"),
        "Air Force": get_units_folder("Air-Force"),
        "Army": get_units_folder("Army"),
        "CENTCOM": get_units_folder("CENTCOM"),
        "Coast Guard": get_units_folder("Coast-Guard"),
        "CYBERCOM": get_units_folder("CYBERCOM"),
        "DHS": get_units_folder("DHS"),
        "DOE": get_units_folder("DOE"),
        "EUCOM": get_units_folder("EUCOM"),
        "FBI": get_units_folder("FBI"),
        "INDOPACOM": get_units_folder("INDOPACOM"),
        "Joint": get_units_folder("Joint"),
        "Navy": get_units_folder("Navy"),
        "NORTHCOM": get_units_folder("NORTHCOM"),
        "SOCOM": get_units_folder("SOCOM"),
        "SOUTHCOM": get_units_folder("SOUTHCOM"),
        "Space Force": get_units_folder("Space-Force"),
        "SPACECOM": get_units_folder("SPACECOM"),
        "STRATCOM": get_units_folder("STRATCOM"),
        "TRANSCOM": get_units_folder("TRANSCOM"),
        "USMC": get_units_folder("USMC"),
    }

    result = {
        "services": [],
        "filters": {
            "cocoms": set()
        }
    }

    # Sort service names alphabetically
    for service_name in sorted(service_folders.keys()):
        folder_path = service_folders[service_name]
        if not folder_path.exists():
            continue

        service_data = {
            "name": service_name,
            "unit_count": 0,
            "unit_types": []
        }

        # Use actual folder structure - each subdirectory is a unit type
        unit_type_units = {}

        # First, check if there are subdirectories (unit type folders)
        subdirs = [d for d in folder_path.iterdir() if d.is_dir()]

        if subdirs:
            # Has subdirectories - use folder structure for categorization
            for subdir in sorted(subdirs):
                unit_type_name = subdir.name.replace("-", " ")
                unit_type_units[unit_type_name] = []

                # Get all .md files in this unit type folder (including nested)
                for unit_file in sorted(subdir.rglob("*.md")):
                    try:
                        with open(unit_file, 'r', encoding='utf-8') as f:
                            post = frontmatter.load(f)

                        location = post.get("location", "")
                        content = post.content

                        # Determine COCOM from location/content or metadata
                        unit_cocom = post.get("cocom", "")
                        if not unit_cocom:
                            loc_lower = location.lower() if location else ""
                            content_lower = content.lower()
                            if "indopacom" in loc_lower or "pacific" in loc_lower or "hawaii" in loc_lower or "japan" in loc_lower:
                                unit_cocom = "INDOPACOM"
                            elif "eucom" in loc_lower or "europe" in loc_lower or "germany" in loc_lower or "wiesbaden" in loc_lower:
                                unit_cocom = "EUCOM"
                            elif "centcom" in content_lower:
                                unit_cocom = "CENTCOM"
                            elif "africom" in content_lower:
                                unit_cocom = "AFRICOM"
                            elif "northcom" in content_lower:
                                unit_cocom = "NORTHCOM"
                            elif "southcom" in content_lower:
                                unit_cocom = "SOUTHCOM"
                            else:
                                unit_cocom = "CONUS"

                        if unit_cocom:
                            result["filters"]["cocoms"].add(unit_cocom)

                        # Apply COCOM filter (supports comma-separated multi-select)
                        if cocom_filter:
                            cocom_values = [v.strip().lower() for v in cocom_filter.split(",")]
                            if unit_cocom.lower() not in cocom_values:
                                continue

                        # Extract unit title from first H1
                        title = unit_file.stem.replace("-", " ")
                        for line in content.split("\n"):
                            if line.startswith("# "):
                                title = line.replace("# ", "").strip()
                                break

                        # Construct ID based on actual file path
                        relative_path = unit_file.relative_to(folder_path)
                        service_folder_name = service_name.replace(' ', '-')
                        units_folder_name = "Units" if folder_path.name == "Units" else "Operational-Units"
                        entity_id = f"Organizations/{service_folder_name}/{units_folder_name}/{str(relative_path).replace(chr(92), '/').replace('.md', '')}"

                        unit_data = {
                            "id": entity_id,
                            "name": title,
                            "location": location,
                            "cocom": unit_cocom,
                            "tags": post.get("tags", [])
                        }

                        unit_type_units[unit_type_name].append(unit_data)
                        service_data["unit_count"] += 1

                    except Exception as e:
                        print(f"Error parsing {unit_file}: {e}")
                        continue
        else:
            # No subdirectories - all files are at root level, use service name as category
            unit_type_units[service_name] = []

            for unit_file in sorted(folder_path.glob("*.md")):
                try:
                    with open(unit_file, 'r', encoding='utf-8') as f:
                        post = frontmatter.load(f)

                    location = post.get("location", "")
                    content = post.content

                    # Determine COCOM
                    unit_cocom = post.get("cocom", "")
                    if not unit_cocom:
                        loc_lower = location.lower() if location else ""
                        content_lower = content.lower()
                        if "indopacom" in loc_lower or "pacific" in loc_lower or "hawaii" in loc_lower or "japan" in loc_lower:
                            unit_cocom = "INDOPACOM"
                        elif "eucom" in loc_lower or "europe" in loc_lower or "germany" in loc_lower or "wiesbaden" in loc_lower:
                            unit_cocom = "EUCOM"
                        elif "centcom" in content_lower:
                            unit_cocom = "CENTCOM"
                        elif "africom" in content_lower:
                            unit_cocom = "AFRICOM"
                        elif "northcom" in content_lower:
                            unit_cocom = "NORTHCOM"
                        elif "southcom" in content_lower:
                            unit_cocom = "SOUTHCOM"
                        else:
                            unit_cocom = "CONUS"

                    if unit_cocom:
                        result["filters"]["cocoms"].add(unit_cocom)

                    # Apply COCOM filter (supports comma-separated multi-select)
                    if cocom_filter:
                        cocom_values = [v.strip().lower() for v in cocom_filter.split(",")]
                        if unit_cocom.lower() not in cocom_values:
                            continue

                    title = unit_file.stem.replace("-", " ")
                    for line in content.split("\n"):
                        if line.startswith("# "):
                            title = line.replace("# ", "").strip()
                            break

                    service_folder_name = service_name.replace(' ', '-')
                    units_folder_name = "Units" if folder_path.name == "Units" else "Operational-Units"
                    entity_id = f"Organizations/{service_folder_name}/{units_folder_name}/{unit_file.stem}"

                    unit_data = {
                        "id": entity_id,
                        "name": title,
                        "location": location,
                        "cocom": unit_cocom,
                        "tags": post.get("tags", [])
                    }

                    unit_type_units[service_name].append(unit_data)
                    service_data["unit_count"] += 1

                except Exception as e:
                    print(f"Error parsing {unit_file}: {e}")
                    continue

        # Build unit types list - only include non-empty categories
        for type_name, units in sorted(unit_type_units.items()):
            if units:
                service_data["unit_types"].append({
                    "name": type_name,
                    "unit_count": len(units),
                    "units": sorted(units, key=lambda x: x["name"])
                })

        if service_data["unit_count"] > 0:
            result["services"].append(service_data)

    result["filters"]["cocoms"] = sorted(list(result["filters"]["cocoms"]))
    return result


@app.get("/api/platforms/detail/{platform_id:path}")
async def get_platform_detail(platform_id: str):
    """Get detailed platform information for the Platform Explorer detail view."""
    import frontmatter
    import re

    vault_path = get_vault_path()
    platform_path = vault_path / f"{platform_id}.md"

    if not platform_path.exists():
        raise HTTPException(status_code=404, detail=f"Platform {platform_id} not found")

    with open(platform_path, 'r', encoding='utf-8') as f:
        post = frontmatter.load(f)

    # Detect if this is a Red platform
    is_red = "red-platform" in post.get("tags", []) or "/Red/" in platform_id

    # Parse content sections
    content = post.content
    sections = {}

    # Extract overview
    overview_match = re.search(r'## Overview\n(.*?)(?=\n##|\Z)', content, re.DOTALL)
    if overview_match:
        sections["overview"] = overview_match.group(1).strip()

    # Extract program details table (Blue)
    program_details = {}
    details_match = re.search(r'## Program Details\n\n\|.*?\n\|.*?\n(.*?)(?=\n##|\Z)', content, re.DOTALL)
    if details_match:
        for line in details_match.group(1).strip().split("\n"):
            if line.startswith("|"):
                parts = [p.strip() for p in line.split("|")[1:-1]]
                if len(parts) >= 2:
                    program_details[parts[0]] = parts[1]

    # Extract specifications (both Blue and Red) - handles both table and bullet list formats
    specifications = []
    spec_match = re.search(r'## Specifications\n(.*?)(?=\n##|\Z)', content, re.DOTALL)
    if spec_match:
        spec_content = spec_match.group(1).strip()
        if spec_content.startswith("|"):
            # Table format: | Attribute | Value |
            lines = spec_content.split("\n")
            for line in lines[2:]:  # Skip header and separator rows
                if line.startswith("|"):
                    parts = [p.strip() for p in line.split("|")[1:-1]]
                    if len(parts) >= 2:
                        specifications.append({"attribute": parts[0], "value": parts[1]})
        else:
            # Bullet list format: - Key: Value or - Value
            for line in spec_content.split("\n"):
                if line.startswith("- "):
                    item = line.replace("- ", "").strip()
                    if ":" in item:
                        key, val = item.split(":", 1)
                        specifications.append({"attribute": key.strip(), "value": val.strip()})
                    else:
                        specifications.append({"attribute": item, "value": ""})

    # Extract current systems (Blue)
    current_systems = []
    systems_match = re.search(r'## (?:Current EW|Defensive/EW).*?\n(.*?)(?=\n##|\Z)', content, re.DOTALL)
    if systems_match:
        for line in systems_match.group(1).strip().split("\n"):
            if line.startswith("- "):
                current_systems.append(line.replace("- ", "").strip())

    # Extract bolt-on potential (Blue)
    bolt_on = []
    bolt_match = re.search(r'## Bolt-On Potential\n(.*?)(?=\n##|\Z)', content, re.DOTALL)
    if bolt_match:
        for line in bolt_match.group(1).strip().split("\n"):
            if line.startswith("- "):
                bolt_on.append(line.replace("- ", "").strip())

    # Extract capabilities (Blue)
    capabilities = []
    cap_match = re.search(r'## Capabilities\n(.*?)(?=\n##|\Z)', content, re.DOTALL)
    if cap_match:
        for line in cap_match.group(1).strip().split("\n"):
            if line.startswith("- "):
                capabilities.append(line.replace("- ", "").strip())

    # Extract theater deployments (Blue) - handles both table and bullet list formats
    theater_deployments = []
    theater_match = re.search(r'## Theater Deployments\n(.*?)(?=\n##|\Z)', content, re.DOTALL)
    if theater_match:
        theater_content = theater_match.group(1).strip()
        if theater_content.startswith("|"):
            # Table format: | Theater | Units | Notes | or | Theater | Units/Details |
            lines = theater_content.split("\n")
            for line in lines[2:]:  # Skip header and separator rows
                if line.startswith("|"):
                    parts = [p.strip() for p in line.split("|")[1:-1]]
                    if len(parts) >= 3:
                        theater_deployments.append({"theater": parts[0], "units": parts[1], "notes": parts[2]})
                    elif len(parts) >= 2:
                        theater_deployments.append({"theater": parts[0], "units": parts[1], "notes": ""})
        else:
            # Bullet list format: - Theater: Details
            for line in theater_content.split("\n"):
                if line.startswith("- "):
                    item = line.replace("- ", "").strip()
                    if ":" in item:
                        theater, details = item.split(":", 1)
                        theater_deployments.append({"theater": theater.strip(), "units": details.strip(), "notes": ""})
                    else:
                        theater_deployments.append({"theater": item, "units": "", "notes": ""})

    # Extract decoy requirements (Blue)
    decoy_requirements = []
    decoy_match = re.search(r'## Decoy Requirements\n(.*?)(?=\n##|\Z)', content, re.DOTALL)
    if decoy_match:
        for line in decoy_match.group(1).strip().split("\n"):
            if line.startswith("- "):
                decoy_requirements.append(line.replace("- ", "").strip())

    # Extract variants (Blue)
    variants = []
    var_match = re.search(r'## (?:Variants|Flights)\n(.*?)(?=\n##|\Z)', content, re.DOTALL)
    if var_match:
        for line in var_match.group(1).strip().split("\n"):
            if line.startswith("- "):
                variants.append(line.replace("- ", "").strip())

    # Extract related links
    related = {
        "programs": [],
        "platforms": [],
        "units": [],
        "buyers": [],
        "technology": []
    }
    related_match = re.search(r'## Related\n(.*?)(?=\n##|\Z)', content, re.DOTALL)
    if related_match:
        for line in related_match.group(1).strip().split("\n"):
            if "Program" in line:
                links = re.findall(r'\[\[([^\]]+)\]\]', line)
                related["programs"].extend(links)
            elif "Platform" in line:
                links = re.findall(r'\[\[([^\]]+)\]\]', line)
                related["platforms"].extend(links)
            elif "Unit" in line or "Operational" in line or "Operator" in line:
                links = re.findall(r'\[\[([^\]]+)\]\]', line)
                related["units"].extend(links)
            elif "Office" in line or "Buyer" in line:
                links = re.findall(r'\[\[([^\]]+)\]\]', line)
                related["buyers"].extend(links)
            elif "Tech" in line:
                links = re.findall(r'\[\[([^\]]+)\]\]', line)
                related["technology"].extend(links)
            elif "Kill Chain" in line:
                # Red platforms have Kill Chain in Related section
                links = re.findall(r'\[\[([^\]]+)\]\]', line)
                related["platforms"].extend(links)
            elif "Counter" in line or "Blue Counterpart" in line:
                links = re.findall(r'\[\[([^\]]+)\]\]', line)
                related["platforms"].extend(links)

    # Parse signatures table - support both Blue (### Primary Signatures) and Red (## Signatures & Detection Opportunities)
    signatures = []
    sig_match = re.search(r'##[#]? (?:Primary Signatures|Signatures & Detection Opportunities)\n\n?\|.*?\n\|.*?\n(.*?)(?=\n##|\n###|\Z)', content, re.DOTALL)
    if sig_match:
        for line in sig_match.group(1).strip().split("\n"):
            if line.startswith("|"):
                parts = [p.strip() for p in line.split("|")[1:-1]]
                if len(parts) >= 2:
                    signatures.append({"modality": parts[0], "characteristics": parts[1]})

    # Threat context (Blue - ### Threat Context or ## Threat)
    threat_match = re.search(r'##[#]? Threat(?: Context)?\n(.*?)(?=\n##|\n###|\Z)', content, re.DOTALL)
    threat_context = threat_match.group(1).strip() if threat_match else ""

    # Extract notes section
    notes_match = re.search(r'## Notes\n(.*?)(?=\n##|\Z)', content, re.DOTALL)
    notes = notes_match.group(1).strip() if notes_match else ""

    # --- Red platform-specific sections ---

    # Seeker & Guidance Architecture table (Red)
    seeker_guidance = []
    seeker_match = re.search(r'## Seeker & Guidance Architecture\n\n?\|.*?\n\|.*?\n(.*?)(?=\n##|\Z)', content, re.DOTALL)
    if seeker_match:
        for line in seeker_match.group(1).strip().split("\n"):
            if line.startswith("|"):
                parts = [p.strip() for p in line.split("|")[1:-1]]
                if len(parts) >= 3:
                    seeker_guidance.append({"phase": parts[0], "method": parts[1], "vulnerabilities": parts[2]})

    # Kill Chain Dependencies (Red)
    kill_chain_match = re.search(r'## Kill Chain Dependencies\n(.*?)(?=\n##|\Z)', content, re.DOTALL)
    kill_chain = kill_chain_match.group(1).strip() if kill_chain_match else ""

    # Counter-Autonomy Vulnerabilities (Red) - bold-key bullet list
    counter_autonomy = []
    ca_match = re.search(r'## Counter-Autonomy Vulnerabilities\n(.*?)(?=\n##|\Z)', content, re.DOTALL)
    if ca_match:
        for line in ca_match.group(1).strip().split("\n"):
            if line.startswith("- **"):
                # Parse "- **GNSS**: detail text"
                bold_match = re.match(r'- \*\*(.+?)\*\*:\s*(.*)', line)
                if bold_match:
                    counter_autonomy.append({"category": bold_match.group(1), "detail": bold_match.group(2).strip()})

    # Combat Record & Reliability (Red)
    combat_match = re.search(r'## Combat Record & Reliability\n(.*?)(?=\n##|\Z)', content, re.DOTALL)
    combat_record = combat_match.group(1).strip() if combat_match else ""

    # Countermeasures (Red)
    cm_match = re.search(r'## Countermeasures\n(.*?)(?=\n##|\Z)', content, re.DOTALL)
    countermeasures = cm_match.group(1).strip() if cm_match else ""

    result = {
        "id": platform_id,
        "is_red": is_red,
        "name": platform_path.stem.replace("-", " "),
        "domain": post.get("domain", ""),
        "service": post.get("service", ""),
        "program_office": post.get("program_office", "").replace("[[", "").replace("]]", "") if post.get("program_office") else "",
        "platform_count": post.get("platform_count", ""),
        "unit_cost": post.get("unit_cost", ""),
        "program_budget": post.get("program_budget", ""),
        "production_rate": post.get("production_rate", ""),
        "status": program_details.get("Status", ""),
        "contractor": program_details.get("Contractor", ""),
        "overview": sections.get("overview", ""),
        "specifications": specifications,
        "current_systems": current_systems,
        "bolt_on_potential": bolt_on,
        "capabilities": capabilities,
        "theater_deployments": theater_deployments,
        "decoy_requirements": decoy_requirements,
        "variants": variants,
        "signatures": signatures,
        "threat_context": threat_context,
        "related": related,
        "notes": notes,
        "tags": post.get("tags", []),
        # Red-specific fields
        "force": post.get("force", ""),
        "country": post.get("country", ""),
        "threat_category": post.get("threat_category", ""),
        "designation": post.get("designation", ""),
        "seeker_guidance": seeker_guidance,
        "kill_chain": kill_chain,
        "counter_autonomy": counter_autonomy,
        "combat_record": combat_record,
        "countermeasures": countermeasures,
    }

    return result


@app.get("/api/units")
async def get_units(
    service: Optional[str] = Query(None, description="Filter by service"),
    unit_type: Optional[str] = Query(None, description="Filter by unit type"),
    cocom: Optional[str] = Query(None, description="Filter by combatant command"),
    mission: Optional[str] = Query(None, description="Filter by mission type"),
    system: Optional[str] = Query(None, description="Filter by system operated")
):
    """Get operational units grouped by service with filtering support."""
    import frontmatter

    vault_path = get_vault_path()
    orgs_path = vault_path / "Organizations"

    # Service folder mappings - new structure uses Units/ folder
    def get_units_folder(service_folder: str) -> Path:
        """Get the units folder path, preferring new structure."""
        new_path = orgs_path / service_folder / "Units"
        old_path = orgs_path / service_folder / "Operational-Units"
        if new_path.exists():
            return new_path
        return old_path

    service_folders = {
        "Army": get_units_folder("Army"),
        "Navy": get_units_folder("Navy"),
        "USMC": get_units_folder("USMC"),  # Changed from Marines
        "Air Force": get_units_folder("Air-Force"),
        "Space Force": get_units_folder("Space-Force"),
        "SOCOM": get_units_folder("SOCOM"),
        "Joint": get_units_folder("Joint"),
        "CYBERCOM": get_units_folder("CYBERCOM"),
    }

    # Define unit type groupings per service
    unit_type_config = {
        "Army": {
            "Multi-Domain Task Forces": ["Multi-Domain Task Force", "MDTF"],
            "MI Brigades": ["MI Brigade", "Expeditionary MI Brigade"],
            "EW / SIGINT Units": ["Cyber", "IEW Battalion", "EW"],
            "Training & Centers": ["Center of Excellence", "Range", "Training"],
        },
        "Navy": {
            "Electronic Attack Squadrons": ["EA-18G Squadron", "VAQ"],
            "Cryptologic Warfare": ["Cryptologic Warfare Group", "CWG", "NIOC"],
            "Information Warfare": ["Information Warfare", "IWC", "IWRON"],
            "P-8A / ISR": ["VP", "VPU", "VUP", "P-8A"],
            "Training Centers": ["IWTC", "Training"],
        },
        "USMC": {
            "Radio Battalions": ["Radio Battalion"],
            "MEF Information Groups": ["MEF Information Group", "MIG"],
            "Marine Littoral Regiments": ["Marine Littoral Regiment", "MLR"],
            "EW / C-UAS Units": ["MADIS", "MEWSS", "LAV-EW", "C-UAS"],
            "UAS Squadrons": ["VMU"],
        },
        "Air Force": {
            "Reconnaissance Wings": ["Reconnaissance Wing", "Reconnaissance Squadron", "55th Wing"],
            "ISR Wings": ["ISR Wing", "ISR Group", "DGS"],
            "Spectrum Warfare": ["Spectrum Warfare Wing", "Spectrum Warfare Group"],
            "Cyber Wings": ["Cyberspace Wing", "Network Warfare"],
            "Fighter Wings": ["Fighter Wing", "Fighter Squadron"],
        },
        "Space Force": {
            "Space Deltas": ["Space Delta", "Mission Delta"],
            "EW Squadrons": ["Electromagnetic Warfare Squadron"],
            "Intelligence": ["Intelligence Center"],
        },
    }

    result = {
        "services": [],
        "filters": {
            "services": list(service_folders.keys()),
            "unit_types": set(),
            "cocoms": set(),
            "missions": set(),
            "systems": set()
        }
    }

    for service_name, folder_path in service_folders.items():
        if service and service.lower() != service_name.lower():
            continue

        if not folder_path.exists():
            continue

        service_data = {
            "name": service_name,
            "unit_count": 0,
            "subcategories": []
        }

        # Group units by type
        type_config = unit_type_config.get(service_name, {"General": []})
        subcategory_units = {cat: [] for cat in type_config.keys()}
        subcategory_units["Other"] = []

        for unit_file in sorted(folder_path.glob("*.md")):
            try:
                with open(unit_file, 'r', encoding='utf-8') as f:
                    post = frontmatter.load(f)

                component_type = post.get("component_type", "")
                location = post.get("location", "")
                tags = post.get("tags", [])

                # Extract mission from content
                content = post.content
                mission_text = ""
                if "## Mission" in content:
                    lines = content.split("\n")
                    for i, line in enumerate(lines):
                        if line.startswith("## Mission"):
                            if i + 1 < len(lines):
                                mission_text = lines[i + 1].strip()
                            break

                # Extract systems from content
                systems = []
                if "## Key Systems" in content:
                    lines = content.split("\n")
                    for i, line in enumerate(lines):
                        if line.startswith("## Key Systems"):
                            if i + 1 < len(lines):
                                sys_line = lines[i + 1].strip()
                                systems = [s.strip() for s in sys_line.split(",")]
                            break

                # Determine COCOM from location/content
                unit_cocom = ""
                loc_lower = location.lower() if location else ""
                content_lower = content.lower()
                if "indopacom" in loc_lower or "pacific" in loc_lower or "hawaii" in loc_lower or "japan" in loc_lower:
                    unit_cocom = "INDOPACOM"
                elif "eucom" in loc_lower or "europe" in loc_lower or "germany" in loc_lower or "wiesbaden" in loc_lower:
                    unit_cocom = "EUCOM"
                elif "centcom" in content_lower:
                    unit_cocom = "CENTCOM"
                elif "africom" in content_lower:
                    unit_cocom = "AFRICOM"
                elif "northcom" in content_lower:
                    unit_cocom = "NORTHCOM"
                elif "southcom" in content_lower:
                    unit_cocom = "SOUTHCOM"
                else:
                    unit_cocom = "CONUS"

                # Build filters
                if component_type:
                    result["filters"]["unit_types"].add(component_type)
                if unit_cocom:
                    result["filters"]["cocoms"].add(unit_cocom)
                for sys in systems:
                    if sys:
                        result["filters"]["systems"].add(sys)
                for tag in tags:
                    if tag in ["ew", "sigint", "isr", "cyber", "c-uas", "multi-domain"]:
                        result["filters"]["missions"].add(tag.upper().replace("-", "/"))

                # Apply filters
                if unit_type and unit_type.lower() not in component_type.lower():
                    continue
                if cocom and cocom.lower() != unit_cocom.lower():
                    continue
                if mission:
                    mission_lower = mission.lower()
                    if mission_lower not in [t.lower() for t in tags] and mission_lower not in content_lower:
                        continue
                if system:
                    system_lower = system.lower()
                    if not any(system_lower in s.lower() for s in systems):
                        continue

                # Extract unit title from first H1
                title = unit_file.stem.replace("-", " ")
                for line in content.split("\n"):
                    if line.startswith("# "):
                        title = line.replace("# ", "").strip()
                        break

                unit_data = {
                    "id": f"Organizations/{service_name.replace(' ', '-')}/Operational-Units/{unit_file.stem}",
                    "name": title,
                    "component_type": component_type,
                    "location": location,
                    "cocom": unit_cocom,
                    "mission": mission_text,
                    "systems": systems[:5],
                    "tags": tags
                }

                # Assign to subcategory
                assigned = False
                for cat_name, keywords in type_config.items():
                    for keyword in keywords:
                        if keyword.lower() in component_type.lower() or keyword.lower() in title.lower():
                            subcategory_units[cat_name].append(unit_data)
                            assigned = True
                            break
                    if assigned:
                        break

                if not assigned:
                    subcategory_units["Other"].append(unit_data)

                service_data["unit_count"] += 1

            except Exception as e:
                print(f"Error parsing {unit_file}: {e}")
                continue

        # Build subcategories with units
        for cat_name, units in subcategory_units.items():
            if units:
                service_data["subcategories"].append({
                    "name": cat_name,
                    "units": units,
                    "more_count": max(0, len(units) - 3) if len(units) > 3 else 0
                })

        if service_data["unit_count"] > 0:
            result["services"].append(service_data)

    # Convert sets to lists
    result["filters"]["unit_types"] = sorted(list(result["filters"]["unit_types"]))
    result["filters"]["cocoms"] = sorted(list(result["filters"]["cocoms"]))
    result["filters"]["missions"] = sorted(list(result["filters"]["missions"]))
    result["filters"]["systems"] = sorted(list(result["filters"]["systems"]))[:20]  # Limit systems

    return result


@app.get("/api/units/{unit_id:path}")
async def get_unit_detail(unit_id: str):
    """Get detailed unit information with all template fields."""
    import frontmatter
    import re

    vault_path = get_vault_path()

    # Handle different path formats
    if unit_id.startswith("Organizations/"):
        unit_path = vault_path / f"{unit_id}.md"
    else:
        # Try to find the unit in service folders (try new Units/ structure first, then Operational-Units)
        unit_path = None
        for service_folder in ["Army", "Navy", "USMC", "Air-Force", "Space-Force", "SOCOM", "Joint", "CYBERCOM"]:
            # Try new Units/ folder first
            test_path = vault_path / "Organizations" / service_folder / "Units" / f"{unit_id}.md"
            if test_path.exists():
                unit_path = test_path
                break
            # Fall back to Operational-Units
            test_path = vault_path / "Organizations" / service_folder / "Operational-Units" / f"{unit_id}.md"
            if test_path.exists():
                unit_path = test_path
                break
        if unit_path is None:
            raise HTTPException(status_code=404, detail=f"Unit {unit_id} not found")

    if not unit_path.exists():
        raise HTTPException(status_code=404, detail=f"Unit {unit_id} not found")

    # Check if this is a reference file
    if is_reference_file(unit_path):
        raise HTTPException(status_code=404, detail=f"Unit {unit_id} not found")

    with open(unit_path, 'r', encoding='utf-8') as f:
        post = frontmatter.load(f)

    content = post.content

    # Extract title
    title = unit_path.stem.replace("-", " ")
    for line in content.split("\n"):
        if line.startswith("# "):
            title = line.replace("# ", "").strip()
            break

    # Extract sections
    sections = {}
    current_section = None
    section_content = []

    for line in content.split("\n"):
        if line.startswith("## "):
            if current_section:
                sections[current_section] = "\n".join(section_content).strip()
            current_section = line.replace("## ", "").strip().lower().replace(" ", "_").replace("/", "_")
            section_content = []
        elif current_section:
            section_content.append(line)

    if current_section:
        sections[current_section] = "\n".join(section_content).strip()

    # Helper to extract list items from a section
    def extract_list_items(section_text: str) -> list:
        items = []
        for line in section_text.split("\n"):
            line = line.strip()
            if line.startswith("- ") or line.startswith("* "):
                item = line[2:].strip()
                # Strip wikilinks
                item = re.sub(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]', r'\1', item)
                if item:
                    items.append(item)
        return items

    # Extract systems from Key Systems/Platforms section
    systems = []
    sys_section = sections.get("key_systems_platforms", sections.get("key_systems", ""))
    if sys_section:
        systems = extract_list_items(sys_section)
        # If no list items, try comma-separated
        if not systems:
            systems = [s.strip() for s in sys_section.split(",") if s.strip()]

    # Extract Key Capabilities
    key_capabilities = []
    cap_section = sections.get("key_capabilities", "")
    if cap_section:
        key_capabilities = extract_list_items(cap_section)

    # Parse unit details table
    unit_details = {}
    if "unit_details" in sections:
        for line in sections["unit_details"].split("\n"):
            if "|" in line and "---" not in line and "Attribute" not in line:
                parts = [p.strip() for p in line.split("|")]
                if len(parts) >= 3:
                    key = parts[1].strip()
                    value = parts[2].strip()
                    if key and value and value != "-":
                        unit_details[key] = value

    # Extract component units from content
    component_units = []
    comp_match = re.search(r'## Component Units\n(.*?)(?=\n##|\Z)', content, re.DOTALL)
    if comp_match:
        component_units = extract_list_items(comp_match.group(1))

    # Extract related units
    related_units = []
    related_units_section = sections.get("related_units", "")
    if related_units_section:
        related_units = extract_list_items(related_units_section)

    # Extract related entities (programs, platforms, etc.)
    related = {
        "service": [],
        "parent": [],
        "programs": [],
        "platforms": [],
        "units": []
    }
    related_section = sections.get("related", "")
    if related_section:
        for line in related_section.split("\n"):
            links = re.findall(r'\[\[([^\]]+)\]\]', line)
            line_lower = line.lower()
            for link in links:
                if "service:" in line_lower:
                    related["service"].append(link.replace("-", " "))
                elif "parent:" in line_lower:
                    related["parent"].append(link.replace("-", " "))
                elif "programs:" in line_lower or "program:" in line_lower:
                    related["programs"].append(link.replace("-", " "))
                elif "platforms:" in line_lower or "platform:" in line_lower:
                    related["platforms"].append(link.replace("-", " "))
                elif "units:" in line_lower or "unit:" in line_lower:
                    related["units"].append(link.replace("-", " "))

    # Extract procurement pathway
    procurement = []
    proc_match = re.search(r'## Procurement|## Buying Channel|## Program Office', content)
    if proc_match:
        proc_section = content[proc_match.start():]
        proc_links = re.findall(r'\[\[([^\]]+)\]\]', proc_section[:500])
        procurement = proc_links

    # Determine COCOM
    location = post.get("location", unit_details.get("Location", ""))
    cocom = ""
    loc_lower = location.lower()
    content_lower = content.lower()
    if "indopacom" in loc_lower or "pacific" in loc_lower or "hawaii" in loc_lower or "japan" in loc_lower:
        cocom = "INDOPACOM"
    elif "eucom" in loc_lower or "europe" in loc_lower or "germany" in loc_lower or "wiesbaden" in loc_lower:
        cocom = "EUCOM"
    elif "centcom" in content_lower:
        cocom = "CENTCOM"
    elif "africom" in content_lower:
        cocom = "AFRICOM"
    elif "northcom" in content_lower:
        cocom = "NORTHCOM"
    elif "southcom" in content_lower:
        cocom = "SOUTHCOM"
    else:
        cocom = "CONUS"

    # Get aliases from frontmatter
    aliases = post.get("aliases", [])
    if aliases and isinstance(aliases, list):
        # Filter out template placeholders
        aliases = [a for a in aliases if a and not a.startswith("{{")]

    # Strip wikilink syntax from parent
    parent_raw = post.get("parent", unit_details.get("Parent Command", unit_details.get("Parent", "")))
    parent = re.sub(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]', r'\1', parent_raw) if parent_raw else ""

    # Get the first overview paragraph (before first heading)
    overview = ""
    lines = content.split("\n")
    overview_lines = []
    for line in lines:
        if line.startswith("#"):
            if line.startswith("# "):
                continue  # Skip title
            break  # Stop at first ## heading
        if line.strip():
            overview_lines.append(line.strip())
    overview = " ".join(overview_lines)

    return {
        "id": unit_id,
        "name": title,
        "full_name": post.get("full_name", unit_details.get("Full Name", title)),
        "service": post.get("service", post.get("domain", unit_details.get("Service/Branch", ""))),
        "component_type": post.get("component_type", unit_details.get("Component Type", "")),
        "organization_type": post.get("organization_type", "Operational Unit"),
        "location": location,
        "cocom": cocom,
        "parent_unit": parent,
        "personnel": unit_details.get("Personnel", ""),
        "established": unit_details.get("Established", ""),
        "aliases": aliases,
        "mission": sections.get("mission", ""),
        "overview": overview if overview else sections.get("overview", ""),
        "key_capabilities": key_capabilities,
        "systems": systems,
        "component_units": component_units,
        "related_units": related_units,
        "relevance_to_counter_autonomy": sections.get("relevance_to_counter-autonomy", sections.get("relevance_to_counter_autonomy", "")),
        "ew_relevance": sections.get("ew_rf_relevance", sections.get("ew_relevance", "")),
        "procurement_pathway": procurement,
        "related": related,
        "notes": sections.get("notes", ""),
        "tags": post.get("tags", [])
    }


@app.get("/api/companies/explorer")
async def get_companies_explorer(
    company_type: Optional[str] = Query(None, description="Filter by type (Primes/Startups)"),
    primary_category: Optional[str] = Query(None, description="Filter by primary category"),
    secondary_category: Optional[str] = Query(None, description="Filter by secondary category")
):
    """Get companies organized by primary and secondary categories.

    Returns:
    - primary_categories: List of primary categories with company counts
    - secondary_categories: Map of primary -> secondary categories
    - companies: All companies with their category metadata
    - filters: Available filter options

    Uses actual folder structure from Vault.
    Structure: Companies/{Type}/*.md where Type is Primes or Startups
    """
    import frontmatter
    import re

    vault_path = get_vault_path()
    companies_path = vault_path / "Companies"

    # Collect all data
    all_companies = []
    primary_cats_set = set()
    secondary_cats_map = {}  # primary -> set of secondary
    types_set = set()

    if not companies_path.exists():
        return {
            "primary_categories": [],
            "secondary_categories": {},
            "companies": [],
            "filters": {
                "types": [],
                "primary_categories": [],
                "secondary_categories": []
            }
        }

    # Parse type filter
    type_filter = None
    if company_type:
        type_filter = [v.strip().lower() for v in company_type.split(",")]

    # Iterate through type folders (Primes, Startups)
    for folder_path in sorted(companies_path.iterdir()):
        if not folder_path.is_dir():
            continue

        type_name = folder_path.name  # "Primes" or "Startups"
        types_set.add(type_name)

        # Apply type filter
        if type_filter and type_name.lower() not in type_filter:
            continue

        for comp_file in sorted(folder_path.glob("*.md")):
            try:
                with open(comp_file, 'r', encoding='utf-8') as f:
                    post = frontmatter.load(f)

                content = post.content
                tags = post.get("tags") or []
                threat_level = post.get("threat_level", "")
                location = post.get("location", "")
                valuation = post.get("valuation", "")
                founded = post.get("founded", "")
                revenue = post.get("revenue", "")
                employees = post.get("employees", "")

                # Get primary and secondary categories from frontmatter
                primary_categories = post.get("primary_category") or []
                secondary_categories = post.get("secondary_categories") or []

                # Track categories
                for pc in primary_categories:
                    primary_cats_set.add(pc)
                    if pc not in secondary_cats_map:
                        secondary_cats_map[pc] = set()
                    for sc in secondary_categories:
                        if sc and sc != "None":
                            secondary_cats_map[pc].add(sc)

                # Extract title from first H1
                title = comp_file.stem.replace("-", " ")
                for line in content.split("\n"):
                    if line.startswith("# "):
                        title = line.replace("# ", "").strip()
                        break

                # Extract overview
                overview = ""
                if "## Overview" in content:
                    lines = content.split("\n")
                    for i, line in enumerate(lines):
                        if line.startswith("## Overview"):
                            if i + 1 < len(lines):
                                overview = lines[i + 1].strip()
                            break

                company_data = {
                    "id": f"Companies/{type_name}/{comp_file.stem}",
                    "name": title,
                    "type": type_name,  # Primes or Startups
                    "primary_categories": primary_categories,
                    "secondary_categories": [s for s in secondary_categories if s and s != "None"],
                    "threat_level": threat_level,
                    "location": location,
                    "valuation": valuation,
                    "founded": founded,
                    "revenue": revenue,
                    "employees": employees,
                    "overview": overview[:200] + "..." if len(overview) > 200 else overview,
                    "tags": tags
                }

                all_companies.append(company_data)

            except Exception as e:
                print(f"Error parsing {comp_file}: {e}")
                continue

    # Apply category filters
    filtered_companies = all_companies
    if primary_category:
        pc_filter = [v.strip() for v in primary_category.split(",")]
        filtered_companies = [c for c in filtered_companies
                             if any(pc in c["primary_categories"] for pc in pc_filter)]
    if secondary_category:
        sc_filter = [v.strip() for v in secondary_category.split(",")]
        filtered_companies = [c for c in filtered_companies
                             if any(sc in c["secondary_categories"] for sc in sc_filter)]

    # Build primary categories list with counts
    primary_categories_list = []
    for pc in sorted(primary_cats_set):
        count = len([c for c in filtered_companies if pc in c["primary_categories"]])
        if count > 0 or not primary_category:  # Show all if no filter, or only those with companies
            primary_categories_list.append({
                "name": pc,
                "count": count,
                "secondary_categories": sorted(list(secondary_cats_map.get(pc, set())))
            })

    # Convert secondary_cats_map to JSON-serializable format
    secondary_cats_json = {k: sorted(list(v)) for k, v in secondary_cats_map.items()}

    # Get all unique secondary categories
    all_secondary = set()
    for secs in secondary_cats_map.values():
        all_secondary.update(secs)

    return {
        "primary_categories": primary_categories_list,
        "secondary_categories": secondary_cats_json,
        "companies": filtered_companies,
        "filters": {
            "types": sorted(list(types_set)),
            "primary_categories": sorted(list(primary_cats_set)),
            "secondary_categories": sorted(list(all_secondary))
        }
    }


@app.get("/api/companies/detail/{company_id:path}")
async def get_company_detail(company_id: str):
    """Get detailed company information."""
    import frontmatter
    import re

    vault_path = get_vault_path()

    # Handle path
    if company_id.startswith("Companies/"):
        comp_path = vault_path / f"{company_id}.md"
    else:
        # Try to find in category folders
        for cat in ["Primes", "Startups", "Partners"]:
            test_path = vault_path / "Companies" / cat / f"{company_id}.md"
            if test_path.exists():
                comp_path = test_path
                break
        else:
            raise HTTPException(status_code=404, detail=f"Company {company_id} not found")

    if not comp_path.exists():
        raise HTTPException(status_code=404, detail=f"Company {company_id} not found")

    with open(comp_path, 'r', encoding='utf-8') as f:
        post = frontmatter.load(f)

    content = post.content

    # Extract title
    title = comp_path.stem.replace("-", " ")
    for line in content.split("\n"):
        if line.startswith("# "):
            title = line.replace("# ", "").strip()
            break

    # Determine category from path
    category = "Unknown"
    if "Primes" in str(comp_path):
        category = "Primes"
    elif "Startups" in str(comp_path):
        category = "Startups"
    elif "Partners" in str(comp_path):
        category = "Partners"

    # Extract sections
    sections = {}
    current_section = None
    section_content = []

    for line in content.split("\n"):
        if line.startswith("## "):
            if current_section:
                sections[current_section] = "\n".join(section_content).strip()
            current_section = line.replace("## ", "").strip().lower().replace(" ", "_")
            section_content = []
        elif current_section:
            section_content.append(line)

    if current_section:
        sections[current_section] = "\n".join(section_content).strip()

    # Extract products
    products = []
    for key in ["products", "ew_products", "product_family", "key_programs"]:
        if key in sections:
            for line in sections[key].split("\n"):
                if line.startswith("- ") or line.startswith("### "):
                    prod = line.replace("- ", "").replace("### ", "").strip()
                    if prod and len(prod) < 100:
                        products.append(prod)
            break

    # Extract key programs (links)
    key_programs = []
    prog_links = re.findall(r'\[\[([^\]]+)\]\]', sections.get("key_programs", "") + sections.get("contracts", ""))
    key_programs = list(set(prog_links))[:10]

    # Extract key buyers (links)
    key_buyers = []
    buyer_section = sections.get("customers", "") + sections.get("key_contracts", "")
    buyer_links = re.findall(r'\[\[([^\]]+)\]\]', buyer_section)
    key_buyers = list(set(buyer_links))[:10]

    # Extract competitive analysis / DS overlap
    ds_overlap = []
    comp_section = sections.get("competitive_analysis", "") + sections.get("competitive_position", "")
    if "vs" in comp_section.lower() or "distributed spectrum" in comp_section.lower():
        # Parse table if present
        for line in comp_section.split("\n"):
            if "|" in line and "Distributed Spectrum" in line:
                continue  # header
            if "|" in line and "---" not in line:
                parts = [p.strip() for p in line.split("|")]
                if len(parts) >= 3:
                    dimension = parts[1] if len(parts) > 1 else ""
                    if dimension and dimension != "Dimension":
                        ds_overlap.append(dimension)

    # Extract strategic notes
    strategic_notes = []
    strat_section = sections.get("strategic_implication", "") + sections.get("threat_assessment", "") + sections.get("strategic_options", "")
    for line in strat_section.split("\n"):
        if line.startswith("- "):
            note = line.replace("- ", "").strip()
            if note:
                strategic_notes.append(note)

    # Funding info
    funding = post.get("valuation", "")
    if not funding:
        fund_match = re.search(r'\$[\d.]+[BMK]?\+?', content)
        if fund_match:
            funding = fund_match.group(0)

    # Determine DS relationship
    ds_relationship = ""
    rel_section = sections.get("relationship_assessment", "") + sections.get("strategic_value", "")
    if "compete" in content.lower() and "partner" in content.lower():
        ds_relationship = "Compete / Partner (context-dependent)"
    elif "partner" in rel_section.lower() or "partner" in post.get("relationship", "").lower():
        ds_relationship = "Partner"
    elif "compete" in content.lower():
        ds_relationship = "Compete"

    # Extract threat assessment dimensions from table
    threat_assessment = {}
    if "threat_assessment" in sections:
        for line in sections["threat_assessment"].split("\n"):
            if "|" in line and "---" not in line:
                parts = [p.strip() for p in line.split("|")]
                parts = [p for p in parts if p]
                if len(parts) >= 3 and parts[0] not in ["Dimension", "**Dimension**"]:
                    dimension = parts[0].replace("**", "").strip()
                    rating = parts[1].replace("**", "").strip()
                    notes = parts[2] if len(parts) > 2 else ""
                    threat_assessment[dimension] = {"rating": rating, "notes": notes}

    # Extract market position (strengths/weaknesses)
    market_position = {
        "strengths": [],
        "weaknesses": []
    }
    if "market_position" in sections:
        in_strengths = False
        in_weaknesses = False
        for line in sections["market_position"].split("\n"):
            if "### Strengths" in line:
                in_strengths = True
                in_weaknesses = False
                continue
            if "### Weaknesses" in line or "### Gaps" in line:
                in_weaknesses = True
                in_strengths = False
                continue
            if line.startswith("### "):
                in_strengths = False
                in_weaknesses = False
                continue
            if line.startswith("- ") and in_strengths:
                market_position["strengths"].append(line.replace("- ", "").strip())
            if line.startswith("- ") and in_weaknesses:
                market_position["weaknesses"].append(line.replace("- ", "").strip())

    # Extract competitive differentiation
    competitive_diff = ""
    if "market_position" in sections:
        diff_match = re.search(r'### Competitive Differentiation\n(.+?)(?=\n###|\n##|\Z)', sections["market_position"], re.DOTALL)
        if diff_match:
            competitive_diff = diff_match.group(1).strip()

    # Extract key insight
    key_insight = sections.get("key_insight", "")

    # Extract strategic assessment recommendation
    strategic_assessment = sections.get("strategic_assessment", "")

    # Extract acquisition consideration
    acquisition_consideration = sections.get("acquisition_consideration", "")

    return {
        "id": company_id,
        "name": title,
        "category": category,
        "threat_level": post.get("threat_level", ""),
        "headquarters": post.get("location", ""),
        "founded": post.get("founded", ""),
        "funding": funding,
        "revenue": post.get("revenue", ""),
        "employees": post.get("employees", ""),
        "modality": post.get("modality", ""),
        "relationship": post.get("relationship", ""),
        "overview": sections.get("overview", ""),
        "products": products,
        "key_programs": key_programs,
        "key_buyers": key_buyers,
        "ds_relationship": ds_relationship,
        "ds_overlap": ds_overlap,
        "strategic_notes": strategic_notes,
        "threat_assessment": threat_assessment,
        "market_position": market_position,
        "competitive_differentiation": competitive_diff,
        "key_insight": key_insight,
        "strategic_assessment": strategic_assessment,
        "acquisition_consideration": acquisition_consideration,
        "tags": post.get("tags", [])
    }


# Legacy endpoints for backwards compatibility
@app.get("/api/competitors/explorer")
async def get_competitors_explorer_legacy(
    category: Optional[str] = Query(None),
    relationship: Optional[str] = Query(None),
    domain: Optional[str] = Query(None)
):
    """Legacy endpoint - redirects to /api/companies/explorer."""
    return await get_companies_explorer(category, relationship, domain)


@app.get("/api/competitors/detail/{competitor_id:path}")
async def get_competitor_detail_legacy(competitor_id: str):
    """Legacy endpoint - redirects to /api/companies/detail."""
    # Convert old Competitors/ path to new Companies/ path
    company_id = competitor_id.replace("Competitors/", "Companies/")
    return await get_company_detail(company_id)


# Stakeholders Explorer endpoints
@app.get("/api/stakeholders/explorer")
async def get_stakeholders_explorer(
    type: str = Query("enablers", description="Stakeholder type: 'requirements' (operational_units) or 'enablers' (buyers)"),
    category: Optional[str] = Query(None, description="Filter by category"),
    domain: Optional[str] = Query(None, description="Filter by domain")
):
    """Get stakeholders organized by service and parent org for three-panel browser.

    - requirements: Stakeholders in Stakeholders/Requirements/ folders (define capability needs)
    - enablers: Stakeholders in Stakeholders/Enablers/ folders (fund and manage programs)

    Both types are stored as 'stakeholder' entity type, differentiated by their
    stakeholder_type field (Enabler vs Requirements) and file path location.
    """
    # Both requirements and enablers are stored as stakeholder type
    # We filter by path to get the right subset
    all_entities_raw = db.get_entities_by_type("stakeholder", limit=2000)

    # Filter to only include entities from the correct Stakeholders/ path
    # requirements -> Stakeholders/Requirements/
    # enablers -> Stakeholders/Enablers/
    stakeholder_path = "Stakeholders/Requirements" if type == "requirements" else "Stakeholders/Enablers"
    all_entities = [
        e for e in all_entities_raw
        if e.file_path and stakeholder_path.lower() in e.file_path.lower().replace("\\", "/")
    ]

    # Preferred service order (services not in this list will be added alphabetically at the end)
    preferred_order = ["Army", "Navy", "USMC", "Air Force", "Space Force", "SOCOM", "Joint"]

    # Track categories for filters
    categories = set()
    domains = set()
    all_services = set()  # Collect all services dynamically

    # Build service -> parent -> children hierarchy
    service_data = {}
    total_count = 0

    for entity in all_entities:
        service = entity.service or "Other"
        # Normalize service names
        if service == "Marine Corps":
            service = "USMC"
        if service == "Marines":
            service = "USMC"

        # Check if this is a parent org itself
        is_parent = (
            "parent_org" in entity.tags or
            "command" in entity.tags or
            entity.metadata.get("organization_type") == "Parent Organization"
        )

        # Get parent org - prefer folder structure over metadata for consistency
        # New vault structure: Organizations/[Service]/Stakeholders/Requirements/ or /Enablers/
        # Old structure: Organizations/[Service]/Buyers/ or /Operational-Units/
        parent_name = ""
        if entity.file_path:
            path_parts = entity.file_path.replace("\\", "/").split("/")

            # Try new structure first: Stakeholders/Requirements or Stakeholders/Enablers
            if "Stakeholders" in path_parts:
                stakeholders_idx = path_parts.index("Stakeholders")
                # Check for Requirements or Enablers subfolder
                if len(path_parts) > stakeholders_idx + 1:
                    sub_type = path_parts[stakeholders_idx + 1]  # Requirements or Enablers
                    # If there's a parent org folder after Requirements/Enablers
                    if len(path_parts) > stakeholders_idx + 3:
                        parent_name = folder_name_to_display(path_parts[stakeholders_idx + 2])
                        file_name = folder_name_to_display(path_parts[-1].replace(".md", ""))
                        if file_name.lower() == parent_name.lower():
                            is_parent = True
            else:
                # Fall back to old structure: Buyers or Operational-Units
                folder_name = "Operational-Units" if type == "requirements" else "Buyers"
                if folder_name in path_parts:
                    folder_idx = path_parts.index(folder_name)
                    # If there's a subfolder after the type folder and before the file
                    if len(path_parts) > folder_idx + 2:
                        parent_name = folder_name_to_display(path_parts[folder_idx + 1])
                        file_name = folder_name_to_display(path_parts[-1].replace(".md", ""))
                        if file_name.lower() == parent_name.lower():
                            is_parent = True

            # Also try Units folder for operational units
            if not parent_name and type == "requirements" and "Units" in path_parts:
                units_idx = path_parts.index("Units")
                if len(path_parts) > units_idx + 2:
                    parent_name = folder_name_to_display(path_parts[units_idx + 1])
                    file_name = folder_name_to_display(path_parts[-1].replace(".md", ""))
                    if file_name.lower() == parent_name.lower():
                        is_parent = True

        # Fall back to metadata if folder structure didn't provide parent
        if not parent_name:
            if type == "requirements":
                raw_parent = entity.metadata.get("parent_unit", "") or entity.metadata.get("cocom", "") or entity.metadata.get("parent_org", "")
            else:
                raw_parent = entity.metadata.get("parent_org", "") or entity.metadata.get("peo", "")

            if raw_parent and "[[" in str(raw_parent):
                parent_name = re.sub(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]', r'\1', str(raw_parent)).strip()
            elif raw_parent:
                parent_name = str(raw_parent)
            if parent_name:
                parent_name = folder_name_to_display(parent_name)

        if not parent_name:
            # Use the service name as the parent when no folder structure or metadata parent
            parent_name = service

        # Get category and domain
        entity_category = entity.metadata.get("category", "") or entity.metadata.get("component_type", "")
        entity_domain = entity.metadata.get("domain", "") or entity.domain or ""

        if entity_category:
            categories.add(entity_category)
        if entity_domain:
            domains.add(entity_domain)

        # Apply category filter (supports comma-separated multi-select)
        if category and category.lower() != "all":
            cat_values = [v.strip().lower() for v in category.split(",")]
            if not entity_category or not any(cv in entity_category.lower() for cv in cat_values):
                continue

        # Apply domain filter (supports comma-separated multi-select)
        if domain and domain.lower() != "all":
            dom_values = [v.strip().lower() for v in domain.split(",")]
            if not entity_domain or not any(dv in entity_domain.lower() for dv in dom_values):
                continue

        # Track this service
        all_services.add(service)

        if service not in service_data:
            service_data[service] = {"parents": {}, "count": 0}

        if parent_name not in service_data[service]["parents"]:
            service_data[service]["parents"][parent_name] = []

        # Get location for operational units
        location = entity.metadata.get("location", "") if type == "requirements" else ""

        # Get stakeholder_type and organization_type for enablers
        stakeholder_type = entity.metadata.get("stakeholder_type", "")
        organization_type = entity.metadata.get("organization_type", "")

        service_data[service]["parents"][parent_name].append({
            "id": entity.id,
            "name": entity.title,
            "full_name": entity.summary[:100] if entity.summary else "",
            "category": entity_category,
            "domain": entity_domain,
            "stakeholder_type": stakeholder_type,
            "organization_type": organization_type,
            "tags": entity.tags,
            "is_parent": is_parent,
            "location": location
        })
        service_data[service]["count"] += 1
        total_count += 1

    # Build response with all columns sorted alphabetically
    services = []
    for svc in sorted(all_services):
        if svc in service_data:
            parents = []
            for parent_name, children in sorted(service_data[svc]["parents"].items()):
                parents.append({
                    "name": parent_name,
                    "child_count": len(children),
                    "children": sorted(children, key=lambda x: x["name"])
                })

            services.append({
                "name": svc,
                "count": service_data[svc]["count"],
                "parents": sorted(parents, key=lambda x: x["name"])  # Sort parents alphabetically
            })

    return {
        "type": type,
        "total_count": total_count,
        "services": services,
        "filters": {
            "categories": sorted(list(categories)),
            "domains": sorted(list(domains))
        }
    }


# Legacy Buyers Explorer endpoint - delegates to stakeholders explorer
@app.get("/api/buyers/explorer")
async def get_buyers_explorer(
    category: Optional[str] = Query(None, description="Filter by buyer category"),
    domain: Optional[str] = Query(None, description="Filter by domain")
):
    """Get buyers organized by service and parent org for three-panel browser.

    DEPRECATED: Use /api/stakeholders/explorer?type=enablers instead.
    This endpoint is maintained for backwards compatibility.
    """
    # Delegate to stakeholders explorer with type=enablers
    result = await get_stakeholders_explorer(type="enablers", category=category, domain=domain)

    # Transform response to match legacy format for backwards compatibility
    services = []
    for svc_data in result["services"]:
        parent_orgs = []
        for parent in svc_data["parents"]:
            parent_orgs.append({
                "name": parent["name"],
                "office_count": parent["child_count"],
                "offices": [
                    {
                        "id": child["id"],
                        "name": child["name"],
                        "full_name": child.get("full_name", ""),
                        "category": child.get("category", ""),
                        "domain": child.get("domain", ""),
                        "tags": child.get("tags", []),
                        "is_parent_org": child.get("is_parent", False)
                    }
                    for child in parent["children"]
                ]
            })
        services.append({
            "name": svc_data["name"],
            "buyer_count": svc_data["count"],
            "parent_orgs": parent_orgs
        })

    return {
        "services": services,
        "filters": result["filters"]
    }


@app.get("/api/stakeholders/detail/{stakeholder_id:path}")
async def get_stakeholder_detail(stakeholder_id: str):
    """Get detailed stakeholder information with all template fields."""
    vault_path = get_vault_path()

    # Try to find the stakeholder file
    possible_paths = [
        vault_path / f"{stakeholder_id}.md",
        vault_path / "Organizations" / f"{stakeholder_id}.md",
        vault_path / "Stakeholders" / f"{stakeholder_id}.md",
    ]

    # Search for the file
    stakeholder_file = None
    for p in possible_paths:
        if p.exists() and not is_reference_file(p):
            stakeholder_file = p
            break

    # If not found, try to find by searching
    if not stakeholder_file:
        for f in vault_path.rglob("*.md"):
            if stakeholder_id in str(f) and not is_reference_file(f):
                stakeholder_file = f
                break

    if not stakeholder_file or not stakeholder_file.exists():
        # Fall back to database
        entity = db.get_entity(stakeholder_id)
        if not entity:
            raise HTTPException(status_code=404, detail="Stakeholder not found")

        # Helper to strip wikilink syntax [[...]]
        def strip_wikilink_db(val):
            if val and isinstance(val, str) and "[[" in val:
                return re.sub(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]', r'\1', val).strip()
            return val or ""

        return {
            "id": entity.id,
            "name": entity.title,
            "full_name": entity.summary or "",
            "service": entity.service or "",
            "category": strip_wikilink_db(entity.metadata.get("category", "")),
            "parent_org": strip_wikilink_db(entity.metadata.get("parent_org", "")),
            "organization_type": entity.metadata.get("organization_type", ""),
            "stakeholder_type": entity.metadata.get("stakeholder_type", ""),
            "location": entity.metadata.get("location", ""),
            "overview": entity.summary or "",
            "mission": "",
            "hierarchy": {
                "command": strip_wikilink_db(entity.metadata.get("command", "")),
                "parent_org": strip_wikilink_db(entity.metadata.get("parent_org", "")),
                "service": entity.service or ""
            },
            "key_capabilities": [],
            "facilities": [],
            "programs_managed": [],
            "supported_programs": [],
            "subordinate_offices": [],
            "related_buyers": [],
            "contract_vehicles": [],
            "ew_relevance": "",
            "notes": "",
            "tags": entity.tags
        }

    # Parse the file
    content = stakeholder_file.read_text(encoding="utf-8")

    # Parse frontmatter
    post = {}
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            import yaml
            try:
                post = yaml.safe_load(parts[1]) or {}
            except:
                pass
            content = parts[2]

    # Extract title
    title_match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
    title = title_match.group(1) if title_match else stakeholder_file.stem.replace("-", " ")

    # Parse sections
    sections = {}
    current_section = ""
    current_content = []

    for line in content.split('\n'):
        h2_match = re.match(r'^##\s+(.+)$', line)
        if h2_match:
            if current_section:
                sections[current_section.lower().replace(" ", "_").replace("/", "_")] = '\n'.join(current_content).strip()
            current_section = h2_match.group(1)
            current_content = []
        else:
            current_content.append(line)

    if current_section:
        sections[current_section.lower().replace(" ", "_").replace("/", "_")] = '\n'.join(current_content).strip()

    # Helper to extract list items
    def extract_list_items(section_text: str) -> list:
        items = []
        for line in section_text.split("\n"):
            line = line.strip()
            if line.startswith("- ") or line.startswith("* "):
                item = line[2:].strip()
                # Strip wikilinks
                item = re.sub(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]', r'\1', item)
                if item and not item.startswith("*To be"):
                    items.append(item)
        return items

    # Parse organization details table
    org_details = {}
    details_section = sections.get("organization_details", "")
    if details_section:
        for line in details_section.split("\n"):
            if "|" in line and "---" not in line and "Attribute" not in line:
                parts = [p.strip() for p in line.split("|")]
                if len(parts) >= 3:
                    key = parts[1].strip()
                    value = parts[2].strip()
                    if key and value and value != "-":
                        org_details[key] = value

    # Extract Key Capabilities
    key_capabilities = extract_list_items(sections.get("key_capabilities", ""))

    # Extract Facilities/Infrastructure
    facilities = extract_list_items(sections.get("facilities_infrastructure", sections.get("facilities", "")))
    # Also check "Key Facilities/Capabilities" for parent orgs
    if not facilities:
        facilities = extract_list_items(sections.get("key_facilities_capabilities", ""))

    # Extract programs managed from Related section or Programs section
    programs_managed = []
    programs_section = sections.get("programs", "") + sections.get("related", "")
    for line in programs_section.split('\n'):
        if "[[" in line:
            matches = re.findall(r'\[\[([^\]]+)\]\]', line)
            for m in matches:
                if "program" in line.lower() or "Programs:" in line:
                    programs_managed.append(m.replace("-", " "))

    # Extract supported programs (for enablers)
    supported_programs = []
    supported_section = sections.get("supported_programs", "")
    for line in supported_section.split('\n'):
        if "[[" in line:
            matches = re.findall(r'\[\[([^\]]+)\]\]', line)
            supported_programs.extend([m.replace("-", " ") for m in matches])
        elif line.strip().startswith("- "):
            item = line.strip()[2:].strip()
            if item and not item.startswith("*"):
                supported_programs.append(item)

    # Extract subordinate/child offices
    subordinate_offices = []
    org_section = (
        sections.get("organization", "") +
        sections.get("subordinate_offices", "") +
        sections.get("child_organizations", "")
    )
    for line in org_section.split('\n'):
        if "[[" in line:
            matches = re.findall(r'\[\[([^\]]+)\]\]', line)
            subordinate_offices.extend([m.replace("-", " ") for m in matches])

    # Extract mission areas (for parent orgs)
    mission_areas = extract_list_items(sections.get("mission_areas", ""))

    # Extract related entities
    related = {
        "parent": [],
        "service": [],
        "programs": [],
        "platforms": []
    }
    related_section = sections.get("related", "")
    for line in related_section.split('\n'):
        links = re.findall(r'\[\[([^\]]+)\]\]', line)
        line_lower = line.lower()
        for link in links:
            if "parent:" in line_lower:
                related["parent"].append(link.replace("-", " "))
            elif "service:" in line_lower or "domain:" in line_lower:
                related["service"].append(link.replace("-", " "))
            elif "programs:" in line_lower:
                related["programs"].append(link.replace("-", " "))
            elif "platforms:" in line_lower:
                related["platforms"].append(link.replace("-", " "))

    # Extract contract vehicles
    contract_vehicles = []
    contracts_section = sections.get("contract_vehicles", "") + sections.get("contracts", "")
    for line in contracts_section.split('\n'):
        if line.strip().startswith('-') or line.strip().startswith('*'):
            cv = line.strip().lstrip('-*').strip()
            if cv:
                contract_vehicles.append(cv)

    # Get service from frontmatter (can be in 'service' or 'domain')
    service = post.get("service", "") or post.get("domain", "")

    # Helper to strip wikilink syntax [[...]]
    def strip_wikilink(val):
        if val and isinstance(val, str) and "[[" in val:
            return re.sub(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]', r'\1', val).strip()
        return val or ""

    raw_parent_org = post.get("parent_org", "") or post.get("peo", "")
    raw_command = post.get("command", "")
    raw_category = post.get("category", "")

    # Get location
    location = post.get("location", org_details.get("Location", ""))

    return {
        "id": stakeholder_id,
        "name": title,
        "full_name": post.get("full_name", org_details.get("Name", "")) or sections.get("overview", "")[:200],
        "service": service,
        "category": strip_wikilink(raw_category),
        "parent_org": strip_wikilink(raw_parent_org),
        "organization_type": post.get("organization_type", org_details.get("Type", "")),
        "stakeholder_type": post.get("stakeholder_type", ""),
        "location": location,
        "workforce": org_details.get("Workforce", ""),
        "established": org_details.get("Established", ""),
        "overview": sections.get("overview", ""),
        "mission": sections.get("mission", ""),
        "mission_areas": mission_areas,
        "hierarchy": {
            "command": strip_wikilink(raw_command),
            "parent_org": strip_wikilink(raw_parent_org),
            "service": service
        },
        "key_capabilities": key_capabilities,
        "facilities": facilities,
        "programs_managed": programs_managed,
        "supported_programs": supported_programs,
        "subordinate_offices": subordinate_offices,
        "related": related,
        "contract_vehicles": contract_vehicles,
        "ew_relevance": sections.get("ew_rf_relevance", sections.get("ew_relevance", "")),
        "notes": sections.get("notes", ""),
        "tags": post.get("tags", [])
    }


# Programs Explorer endpoints
@app.get("/api/programs/explorer")
async def get_programs_explorer(
    domain: Optional[str] = Query(None, description="Filter by domain")
):
    """Get programs organized by service and PEO for three-panel browser.

    Uses actual folder structure from Vault instead of relying on frontmatter peo field.
    Structure: Organizations/{Service}/Programs/{PEO}/*.md
    """
    import frontmatter
    vault_path = get_vault_path()
    organizations_path = vault_path / "Organizations"

    # Preferred services in order (others will be added dynamically)
    preferred_services = [
        "Army", "Navy", "USMC", "Air Force", "Space Force",
        "SOCOM", "Joint", "DoD"
    ]

    # Map folder names to display names
    folder_to_display = {
        "army": "Army",
        "navy": "Navy",
        "usmc": "USMC",
        "air-force": "Air Force",
        "space-force": "Space Force",
        "socom": "SOCOM",
        "joint": "Joint",
        "cybercom": "CYBERCOM",
        "dod": "DoD",
        "indopacom": "INDOPACOM",
        "eucom": "EUCOM",
        "centcom": "CENTCOM",
        "africom": "AFRICOM",
        "northcom": "NORTHCOM",
        "southcom": "SOUTHCOM",
        "spacecom": "SPACECOM",
        "stratcom": "STRATCOM",
        "transcom": "TRANSCOM",
        "coast-guard": "Coast Guard",
        "dhs": "DHS",
        "doe": "DOE",
        "fbi": "FBI",
    }

    # Build service -> PEO -> programs hierarchy from folder structure
    service_data = {}
    all_domains = set()  # raw domains
    all_domain_groups = set()  # normalized high-level groups

    # Iterate through Organizations subfolders
    if organizations_path.exists():
        for service_folder in sorted(organizations_path.iterdir()):
            if not service_folder.is_dir():
                continue

            programs_folder = service_folder / "Programs"
            if not programs_folder.exists() or not programs_folder.is_dir():
                continue

            # Get display name for service
            service_name = folder_to_display.get(
                service_folder.name.lower(),
                service_folder.name.replace("-", " ")
            )

            service_data[service_name] = {"peos": {}, "program_count": 0}

            # Check for PEO subfolders vs direct program files
            subdirs = [d for d in programs_folder.iterdir() if d.is_dir()]

            if subdirs:
                # Has PEO subfolders - use folder structure
                for peo_folder in sorted(subdirs):
                    peo_name = peo_folder.name.replace("-", " ")
                    programs_list = []

                    for program_file in sorted(peo_folder.rglob("*.md")):
                        if is_reference_file(program_file):
                            continue

                        try:
                            with open(program_file, "r", encoding="utf-8") as f:
                                post = frontmatter.load(f)

                            metadata = dict(post.metadata) if post.metadata else {}
                            prog_domain = metadata.get("domain", "")

                            # Track domain for filters (normalized groups)
                            if prog_domain:
                                all_domains.add(prog_domain)
                                domain_group = _normalize_program_domain(prog_domain)
                                if domain_group:
                                    all_domain_groups.add(domain_group)

                            # Apply domain filter (matches against normalized group)
                            if domain and domain.lower() != "all":
                                dom_values = [v.strip().lower() for v in domain.split(",")]
                                prog_group = _normalize_program_domain(prog_domain).lower()
                                if not prog_domain or (prog_group not in dom_values and not any(dv in prog_domain.lower() for dv in dom_values)):
                                    continue

                            # Construct proper entity ID from file path
                            relative_path = program_file.relative_to(vault_path)
                            entity_id = str(relative_path).replace('\\', '/').replace('.md', '')

                            programs_list.append({
                                "id": entity_id,
                                "name": metadata.get("name", program_file.stem.replace("-", " ")),
                                "full_name": metadata.get("full_name", "")[:100] if metadata.get("full_name") else "",
                                "domain": prog_domain,
                                "domain_group": _normalize_program_domain(prog_domain),
                                "status": metadata.get("status", ""),
                                "contractor": metadata.get("contractor", ""),
                                "tags": metadata.get("tags", []) or []
                            })
                        except Exception:
                            continue

                    if programs_list:
                        service_data[service_name]["peos"][peo_name] = programs_list
                        service_data[service_name]["program_count"] += len(programs_list)
            else:
                # No subfolders - direct program files at Programs level
                programs_list = []
                for program_file in sorted(programs_folder.glob("*.md")):
                    if is_reference_file(program_file):
                        continue

                    try:
                        with open(program_file, "r", encoding="utf-8") as f:
                            post = frontmatter.load(f)

                        metadata = dict(post.metadata) if post.metadata else {}
                        prog_domain = metadata.get("domain", "")

                        if prog_domain:
                            all_domains.add(prog_domain)
                            domain_group = _normalize_program_domain(prog_domain)
                            if domain_group:
                                all_domain_groups.add(domain_group)

                        # Apply domain filter (matches against normalized group)
                        if domain and domain.lower() != "all":
                            dom_values = [v.strip().lower() for v in domain.split(",")]
                            prog_group = _normalize_program_domain(prog_domain).lower()
                            if not prog_domain or (prog_group not in dom_values and not any(dv in prog_domain.lower() for dv in dom_values)):
                                continue

                        # Construct proper entity ID from file path
                        relative_path = program_file.relative_to(vault_path)
                        entity_id = str(relative_path).replace('\\', '/').replace('.md', '')

                        programs_list.append({
                            "id": entity_id,
                            "name": metadata.get("name", program_file.stem.replace("-", " ")),
                            "full_name": metadata.get("full_name", "")[:100] if metadata.get("full_name") else "",
                            "domain": prog_domain,
                            "status": metadata.get("status", ""),
                            "contractor": metadata.get("contractor", ""),
                            "tags": metadata.get("tags", []) or []
                        })
                    except Exception:
                        continue

                if programs_list:
                    service_data[service_name]["peos"]["Programs"] = programs_list
                    service_data[service_name]["program_count"] += len(programs_list)

    # Build response with all columns sorted alphabetically
    services = []
    for svc in sorted(service_data.keys()):
        if service_data[svc]["program_count"] > 0:
            peos = []
            for peo_name, programs in sorted(service_data[svc]["peos"].items()):
                peos.append({
                    "name": peo_name,
                    "program_count": len(programs),
                    "programs": sorted(programs, key=lambda x: x["name"])
                })

            services.append({
                "name": svc,
                "program_count": service_data[svc]["program_count"],
                "peos": sorted(peos, key=lambda x: x["name"])  # Sort PEOs alphabetically
            })

    return {
        "services": services,
        "filters": {
            "domains": sorted(list(all_domain_groups)) if all_domain_groups else sorted(list(all_domains))
        }
    }


@app.get("/api/programs/detail/{program_id:path}")
async def get_program_detail(program_id: str):
    """Get detailed program information with all template fields."""
    vault_path = get_vault_path()

    # Try to find the program file
    possible_paths = [
        vault_path / f"{program_id}.md",
        vault_path / "Organizations" / f"{program_id}.md",
    ]

    # Search for the file
    program_file = None
    for p in possible_paths:
        if p.exists() and not is_reference_file(p):
            program_file = p
            break

    # If not found, try to find by searching
    if not program_file:
        for f in vault_path.rglob("*.md"):
            if program_id in str(f) and not is_reference_file(f):
                program_file = f
                break

    if not program_file or not program_file.exists():
        # Fall back to database
        entity = db.get_entity(program_id)
        if not entity:
            raise HTTPException(status_code=404, detail="Program not found")

        return {
            "id": entity.id,
            "name": entity.title,
            "full_name": entity.summary or "",
            "service": entity.service or "",
            "peo": entity.metadata.get("peo", ""),
            "pm": entity.metadata.get("pm", ""),
            "domain": entity.metadata.get("domain", ""),
            "overview": entity.summary or "",
            "status": entity.metadata.get("status", ""),
            "acat": entity.metadata.get("acat", ""),
            "ioc": "",
            "foc": "",
            "unit_cost": "",
            "total_cost": "",
            "quantity": "",
            "capabilities": [],
            "variants": [],
            "technical_specs": [],
            "budget": [],
            "acquisition_timeline": [],
            "contractors": {
                "prime": entity.metadata.get("contractor", ""),
                "subs": []
            },
            "related": {
                "programs": [],
                "organizations": [],
                "platforms": [],
                "technology": []
            },
            "operational_users": [],
            "platforms": [],
            "ew_relevance": "",
            "notes": "",
            "tags": entity.tags
        }

    # Parse the file
    content = program_file.read_text(encoding="utf-8")

    # Parse frontmatter
    post = {}
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            import yaml
            try:
                post = yaml.safe_load(parts[1]) or {}
            except:
                pass
            content = parts[2]

    # Extract title
    title_match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
    title = title_match.group(1) if title_match else program_file.stem.replace("-", " ")

    # Parse sections
    sections = {}
    current_section = ""
    current_content = []

    for line in content.split('\n'):
        h2_match = re.match(r'^##\s+(.+)$', line)
        if h2_match:
            if current_section:
                sections[current_section.lower().replace(" ", "_").replace("/", "_")] = '\n'.join(current_content).strip()
            current_section = h2_match.group(1)
            current_content = []
        else:
            current_content.append(line)

    if current_section:
        sections[current_section.lower().replace(" ", "_").replace("/", "_")] = '\n'.join(current_content).strip()

    # Helper to extract list items
    def extract_list_items(section_text: str) -> list:
        items = []
        for line in section_text.split("\n"):
            line = line.strip()
            if line.startswith("- ") or line.startswith("* "):
                item = line[2:].strip()
                # Strip wikilinks but keep the text
                item = re.sub(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]', r'\1', item)
                if item:
                    items.append(item)
        return items

    # Helper to parse markdown table
    def parse_table(section_text: str) -> list:
        rows = []
        lines = section_text.strip().split("\n")
        headers = []
        for i, line in enumerate(lines):
            if "|" not in line:
                continue
            if "---" in line:
                continue  # Skip separator row
            parts = [p.strip() for p in line.split("|")]
            parts = [p for p in parts if p]  # Remove empty strings
            if not headers:
                headers = parts
            else:
                if len(parts) >= len(headers):
                    row = {}
                    for j, header in enumerate(headers):
                        row[header] = parts[j] if j < len(parts) else ""
                    rows.append(row)
        return rows

    # Parse program details table
    program_details = {}
    details_section = sections.get("program_details", "")
    if details_section:
        for line in details_section.split("\n"):
            if "|" in line and "---" not in line and "Attribute" not in line:
                parts = [p.strip() for p in line.split("|")]
                if len(parts) >= 3:
                    key = parts[1].strip()
                    value = parts[2].strip()
                    if key and value and value != "-":
                        program_details[key] = value

    # Extract capabilities
    capabilities = extract_list_items(sections.get("capabilities", ""))

    # Parse variants table
    variants = parse_table(sections.get("variants", ""))

    # Parse technical specifications table
    technical_specs = parse_table(sections.get("technical_specifications", ""))

    # Parse budget table
    budget = parse_table(sections.get("budget_(in_millions)", sections.get("budget", "")))
    # Also check alternative section names
    if not budget:
        budget = parse_table(sections.get("budget_($_in_millions)", ""))

    # Extract acquisition timeline
    acquisition_timeline = []
    timeline_section = sections.get("acquisition_timeline", "")
    for line in timeline_section.split("\n"):
        line = line.strip()
        if line.startswith("- **") or line.startswith("* **"):
            # Parse "- **Milestone**: Date" format
            match = re.match(r'[-*]\s+\*\*([^*]+)\*\*:\s*(.+)', line)
            if match:
                acquisition_timeline.append({
                    "milestone": match.group(1).strip(),
                    "date": match.group(2).strip()
                })

    # Extract platforms with integration status
    platforms_section = sections.get("platforms", "")
    platforms = []
    for line in platforms_section.split("\n"):
        line = line.strip()
        if line.startswith("- ") or line.startswith("* "):
            item = line[2:].strip()
            # Parse "[[Platform]] - status" format
            platform_match = re.match(r'\[\[([^\]]+)\]\]\s*-?\s*(.*)', item)
            if platform_match:
                platforms.append({
                    "name": platform_match.group(1).replace("-", " "),
                    "status": platform_match.group(2).strip() if platform_match.group(2) else ""
                })
            else:
                # Strip wikilinks
                item = re.sub(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]', r'\1', item)
                if item:
                    platforms.append({"name": item.replace("-", " "), "status": ""})

    # Extract related entities
    related = {
        "programs": [],
        "organizations": [],
        "platforms": [],
        "technology": []
    }
    related_section = sections.get("related", "")
    for line in related_section.split('\n'):
        links = re.findall(r'\[\[([^\]]+)\]\]', line)
        line_lower = line.lower()
        for link in links:
            link_clean = link.replace("-", " ")
            if "programs:" in line_lower or "program:" in line_lower:
                related["programs"].append(link_clean)
            elif "organizations:" in line_lower or "peo" in line_lower:
                related["organizations"].append(link_clean)
            elif "platforms:" in line_lower or "platform:" in line_lower:
                related["platforms"].append(link_clean)
            elif "technology:" in line_lower or "tech:" in line_lower:
                related["technology"].append(link_clean)

    # Extract contractors from program details table
    prime_contractor = post.get("contractor", program_details.get("Prime Contractor", ""))
    subs = []
    subs_text = program_details.get("Key Subcontractors", "")
    if subs_text:
        subs = [s.strip() for s in subs_text.split(",") if s.strip()]

    # Extract key fields from program details table
    acat = post.get("acat", program_details.get("ACAT Level", ""))
    status = post.get("status", program_details.get("Status", ""))
    ioc = program_details.get("IOC", "")
    foc = program_details.get("FOC", "")
    unit_cost = program_details.get("Unit Cost", "")
    total_cost = program_details.get("Total Program Cost", program_details.get("Contract Potential", ""))
    quantity = program_details.get("Quantity", "")

    return {
        "id": program_id,
        "name": title,
        "full_name": post.get("full_name", "") or sections.get("overview", "")[:200] if sections.get("overview", "") else "",
        "service": post.get("service", ""),
        "peo": post.get("peo", ""),
        "pm": post.get("pm", ""),
        "domain": post.get("domain", ""),
        "overview": sections.get("overview", ""),
        "status": status,
        "acat": acat,
        "ioc": ioc,
        "foc": foc,
        "unit_cost": unit_cost,
        "total_cost": total_cost,
        "quantity": quantity,
        "capabilities": capabilities,
        "variants": variants,
        "technical_specs": technical_specs,
        "budget": budget,
        "acquisition_timeline": acquisition_timeline,
        "contractors": {
            "prime": prime_contractor,
            "subs": subs
        },
        "related": related,
        "platforms": platforms,
        "ew_relevance": sections.get("ew_rf_relevance", sections.get("ew_relevance", "")),
        "notes": sections.get("notes", ""),
        "tags": post.get("tags", [])
    }


# Political Affairs Explorer endpoints
@app.get("/api/political-affairs/explorer")
async def get_political_affairs_explorer(
    view: str = Query("congress", description="View type: congress or executive"),
    party: Optional[str] = Query(None, description="Filter by party (R/D/I)"),
    role: Optional[str] = Query(None, description="Filter by role"),
    committee: Optional[str] = Query(None, description="Filter by committee")
):
    """Get political affairs data organized for three-panel browser."""
    import frontmatter

    vault_path = get_vault_path()

    if view == "congress":
        # Congress view: Chamber -> Committee -> Members/Staff
        congress_path = vault_path / "Organizations" / "Congress"

        result = {
            "view": "congress",
            "chambers": [],
            "filters": {
                "parties": ["R", "D", "I"],
                "roles": set(),
                "committees": set()
            }
        }

        if not congress_path.exists():
            return result

        # Process Senate and House
        # Sort chambers alphabetically
        for chamber_name in ["House", "Senate"]:
            chamber_data = {
                "name": chamber_name,
                "member_count": 0,
                "committees": []
            }

            # Get committees for this chamber
            committees_path = congress_path / "Committees" / chamber_name
            if committees_path.exists():
                # First pass: identify main committees and subcommittees dynamically
                # Main committees: files whose stem is NOT a prefix of any other file
                # Subcommittees: files whose stem starts with another file's stem + "-"
                all_files = [f for f in committees_path.iterdir() if f.is_file() and f.suffix == ".md"]
                all_stems = {f.stem for f in all_files}

                # A stem is a main committee if no other stem equals it
                # (and it may have subcommittees starting with stem + "-")
                main_committee_stems = set()
                for stem in all_stems:
                    # Check if this stem is a prefix of another stem (indicating it's a main committee)
                    has_subcommittees = any(
                        other != stem and other.startswith(stem + "-")
                        for other in all_stems
                    )
                    # Check if this stem is itself a subcommittee (starts with another stem + "-")
                    is_subcommittee = any(
                        stem.startswith(other + "-") and stem != other
                        for other in all_stems
                    )
                    if not is_subcommittee:
                        main_committee_stems.add(stem)

                main_committee_files = []
                subcommittee_files = []

                for f in all_files:
                    stem = f.stem
                    if stem in main_committee_stems:
                        main_committee_files.append(f)
                    else:
                        # Find parent committee
                        parent_prefix = None
                        for main_stem in main_committee_stems:
                            if stem.startswith(main_stem + "-"):
                                parent_prefix = main_stem
                                break
                        if parent_prefix:
                            subcommittee_files.append((f, parent_prefix))

                # Sort: main committees alphabetically
                main_committee_files = sorted(main_committee_files, key=lambda x: x.stem)

                # Build a map of parent committee -> subcommittees
                subcommittee_map = {}  # parent_prefix -> list of (file, parsed_data)

                for subcom_file, parent_prefix in subcommittee_files:
                    if parent_prefix not in subcommittee_map:
                        subcommittee_map[parent_prefix] = []

                    try:
                        with open(subcom_file, 'r', encoding='utf-8') as f:
                            post = frontmatter.load(f)

                        content = post.content
                        subcom_stem = subcom_file.stem

                        # Extract subcommittee name (remove parent prefix)
                        subcom_name = subcom_stem.replace(parent_prefix + "-", "").replace("-", " ")

                        # Parse leadership from Subcommittee Details table
                        subcom_chair = None
                        subcom_ranking = None
                        if "## Subcommittee Details" in content:
                            lines = content.split('\n')
                            in_details = False
                            for line in lines:
                                if "## Subcommittee Details" in line:
                                    in_details = True
                                    continue
                                if in_details and line.startswith("## "):
                                    break
                                if in_details and "|" in line:
                                    line_lower = line.lower()
                                    if "chairman" in line_lower or ("chair" in line_lower and "ranking" not in line_lower):
                                        parts = line.split("|")
                                        if len(parts) >= 3:
                                            value = parts[2].strip()
                                            match = re.search(r'\[\[([^\]|]+)', value)
                                            if match:
                                                subcom_chair = match.group(1).replace("-", " ")
                                    if "ranking" in line_lower:
                                        parts = line.split("|")
                                        if len(parts) >= 3:
                                            value = parts[2].strip()
                                            match = re.search(r'\[\[([^\]|]+)', value)
                                            if match:
                                                subcom_ranking = match.group(1).replace("-", " ")

                        subcommittee_map[parent_prefix].append({
                            "id": f"Organizations/Congress/Committees/{chamber_name}/{subcom_stem}",
                            "name": subcom_name,
                            "full_name": subcom_stem.replace("-", " "),
                            "chair": subcom_chair,
                            "ranking": subcom_ranking,
                            "file_path": str(subcom_file),
                            "members": []  # Will be populated from member files
                        })
                    except Exception as e:
                        print(f"Error parsing subcommittee {subcom_file}: {e}")
                        continue

                # Now process main committee files
                for committee_folder in main_committee_files:
                    try:
                        with open(committee_folder, 'r', encoding='utf-8') as f:
                            post = frontmatter.load(f)

                        committee_id = f"Organizations/Congress/Committees/{chamber_name}/{committee_folder.stem}"
                        committee_name_str = committee_folder.stem.replace("-", " ")

                        # Extract committee leadership and subcommittees from content
                        content = post.content
                        leadership = []
                        subcommittees = []
                        staff = []

                        # Parse leadership from various sections
                        # First check Committee Details table for Chairman/Ranking Member
                        if "## Committee Details" in content:
                            lines = content.split('\n')
                            in_details = False
                            for line in lines:
                                if "## Committee Details" in line:
                                    in_details = True
                                    continue
                                if in_details and line.startswith("## "):
                                    break
                                if in_details and "|" in line:
                                    line_lower = line.lower()
                                    if "chairman" in line_lower or "chair" in line_lower:
                                        # Extract wikilink or plain text after |
                                        parts = line.split("|")
                                        if len(parts) >= 3:
                                            value = parts[2].strip()
                                            match = re.search(r'\[\[([^\]|]+)', value)
                                            if match:
                                                leadership.append(match.group(1).replace("-", " "))
                                            elif value and value != "-":
                                                # Try to extract name with party/state like "Ken Calvert (R-CA-41)"
                                                name_match = re.match(r'^([A-Za-z\s.-]+)', value)
                                                if name_match:
                                                    leadership.append(name_match.group(1).strip())
                                    if "ranking" in line_lower:
                                        parts = line.split("|")
                                        if len(parts) >= 3:
                                            value = parts[2].strip()
                                            match = re.search(r'\[\[([^\]|]+)', value)
                                            if match:
                                                leadership.append(match.group(1).replace("-", " "))
                                            elif value and value != "-":
                                                name_match = re.match(r'^([A-Za-z\s.-]+)', value)
                                                if name_match:
                                                    leadership.append(name_match.group(1).strip())

                        # Also check Key Members section for Leadership table
                        if not leadership and ("## Key Members" in content or "## Leadership" in content):
                            lines = content.split('\n')
                            in_leadership = False
                            for line in lines:
                                if "## Key Members" in line or "## Leadership" in line:
                                    in_leadership = True
                                    continue
                                if in_leadership and line.startswith("## "):
                                    break
                                # Look for leadership in table or list format
                                if in_leadership and ("Chairman" in line or "Ranking" in line or "Chair" in line):
                                    # Extract wikilinks
                                    matches = re.findall(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]', line)
                                    for m in matches:
                                        leadership.append(m.replace("-", " "))
                                if in_leadership and "[[" in line and ("|" in line or line.strip().startswith("-")):
                                    matches = re.findall(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]', line)
                                    for m in matches:
                                        if m.replace("-", " ") not in leadership:
                                            leadership.append(m.replace("-", " "))

                        # Parse subcommittees from "Subcommittee Chairs/Ranking" table or dedicated section
                        # First check for table in Key Members section
                        if "Subcommittee Chairs/Ranking" in content or "### Subcommittee" in content:
                            lines = content.split('\n')
                            in_subcom_table = False
                            for line in lines:
                                if "Subcommittee Chairs/Ranking" in line or "### Subcommittee" in line:
                                    in_subcom_table = True
                                    continue
                                if in_subcom_table and line.startswith("## "):
                                    break
                                if in_subcom_table and "|" in line and "---" not in line and "Subcommittee" not in line:
                                    parts = [p.strip() for p in line.split("|")]
                                    parts = [p for p in parts if p]
                                    if len(parts) >= 2:
                                        subcom_name = parts[0].strip()
                                        if subcom_name and not subcom_name.startswith("---"):
                                            chair = None
                                            ranking = None
                                            if len(parts) >= 2:
                                                chair_match = re.search(r'\[\[([^\]|]+)', parts[1])
                                                if chair_match:
                                                    chair = chair_match.group(1).replace("-", " ")
                                                elif parts[1] and parts[1] != "-":
                                                    # Extract name from "Name (R-ST)" format
                                                    name_match = re.match(r'^([A-Za-z\s.-]+)', parts[1])
                                                    if name_match:
                                                        chair = name_match.group(1).strip()
                                            if len(parts) >= 3:
                                                ranking_match = re.search(r'\[\[([^\]|]+)', parts[2])
                                                if ranking_match:
                                                    ranking = ranking_match.group(1).replace("-", " ")
                                                elif parts[2] and parts[2] != "-":
                                                    name_match = re.match(r'^([A-Za-z\s.-]+)', parts[2])
                                                    if name_match:
                                                        ranking = name_match.group(1).strip()
                                            subcommittees.append({
                                                "name": subcom_name,
                                                "chair": chair,
                                                "ranking": ranking
                                            })

                        # Also check traditional ## Subcommittees section
                        if not subcommittees and "## Subcommittees" in content:
                            lines = content.split('\n')
                            in_subcommittees = False
                            for line in lines:
                                if "## Subcommittees" in line:
                                    in_subcommittees = True
                                    continue
                                if in_subcommittees and line.startswith("## "):
                                    break
                                if in_subcommittees and line.startswith("### "):
                                    subcom_name = line.replace("### ", "").strip()
                                    subcommittees.append({"name": subcom_name, "chair": None, "ranking": None})
                                if in_subcommittees and "Chair:" in line and subcommittees:
                                    chair_match = re.search(r'\[\[([^\]|]+)', line)
                                    if chair_match:
                                        subcommittees[-1]["chair"] = chair_match.group(1).replace("-", " ")
                                if in_subcommittees and "Ranking:" in line and subcommittees:
                                    ranking_match = re.search(r'\[\[([^\]|]+)', line)
                                    if ranking_match:
                                        subcommittees[-1]["ranking"] = ranking_match.group(1).replace("-", " ")

                        # Parse staff
                        if "## Key Staff" in content or "## Staff" in content:
                            lines = content.split('\n')
                            in_staff = False
                            for line in lines:
                                if "## Key Staff" in line or "## Staff" in line:
                                    in_staff = True
                                    continue
                                if in_staff and line.startswith("##"):
                                    break
                                if in_staff and line.startswith("- "):
                                    staff_text = line.replace("- ", "").strip()
                                    if ":" in staff_text:
                                        parts = staff_text.split(":", 1)
                                        staff.append({
                                            "name": parts[0].strip(),
                                            "subject_areas": [s.strip() for s in parts[1].split(",")]
                                        })
                                    else:
                                        staff.append({"name": staff_text, "subject_areas": []})

                        result["filters"]["committees"].add(committee_name_str)

                        # Use subcommittees from dedicated files if available
                        committee_prefix = committee_folder.stem
                        file_subcommittees = subcommittee_map.get(committee_prefix, [])

                        # If we have dedicated subcommittee files, use those instead of parsed content
                        if file_subcommittees:
                            subcommittees = file_subcommittees

                        chamber_data["committees"].append({
                            "id": committee_id,
                            "name": committee_name_str,
                            "full_name": post.get("full_name", committee_name_str),
                            "committee_type": post.get("committee_type", ""),
                            "member_count": post.get("member_count", 0),
                            "leadership": leadership,
                            "subcommittees": subcommittees,
                            "staff": staff,
                            "members": []  # Will be populated by member query
                        })
                    except Exception as e:
                        print(f"Error parsing committee {committee_folder}: {e}")
                        continue

            # Get members for this chamber
            members_path = congress_path / "Members" / chamber_name
            if members_path.exists():
                for member_file in sorted(members_path.glob("*.md")):
                    try:
                        with open(member_file, 'r', encoding='utf-8') as f:
                            post = frontmatter.load(f)

                        member_party = post.get("party", "")
                        member_state = post.get("state", "")
                        member_district = post.get("district", "")
                        member_committees = post.get("committees", [])
                        if isinstance(member_committees, str):
                            member_committees = [c.strip() for c in member_committees.split(",")]
                        member_roles = post.get("roles", [])
                        if isinstance(member_roles, str):
                            member_roles = [r.strip() for r in member_roles.split(",")]

                        # Apply filters (supports comma-separated multi-select)
                        if party:
                            party_values = [v.strip() for v in party.split(",")]
                            if member_party not in party_values:
                                continue
                        if committee:
                            committee_values = [v.strip() for v in committee.split(",")]
                            clean_committees = [c.replace("[[", "").replace("]]", "") for c in member_committees]
                            if not any(cv in clean_committees for cv in committee_values):
                                continue
                        if role:
                            role_values = [v.strip().lower() for v in role.split(",")]
                            # Match normalized role groups against member's raw roles
                            member_role_groups = set(_normalize_political_role(r).lower() for r in member_roles)
                            if not any(rv in member_role_groups for rv in role_values):
                                continue

                        # Add roles to filter (normalized committee groups)
                        for r in member_roles:
                            role_group = _normalize_political_role(r)
                            result["filters"]["roles"].add(role_group)

                        member_id = f"Organizations/Congress/Members/{chamber_name}/{member_file.stem}"
                        # Parse subcommittee memberships from content WikiLinks
                        content = post.content
                        subcommittee_links = re.findall(r'\[\[(SASC|HASC|SSCI|HSGAC|SAC|HAC|HPSCI|CHS)-([^\]|]+)', content)
                        member_subcommittees = [f"{prefix}-{suffix.split('|')[0]}" for prefix, suffix in subcommittee_links]

                        member_data = {
                            "id": member_id,
                            "name": member_file.stem.replace("-", " "),
                            "party": member_party,
                            "state": member_state,
                            "district": member_district,
                            "chamber": chamber_name,
                            "committees": member_committees,
                            "subcommittees": member_subcommittees,
                            "roles": member_roles,
                            "military": post.get("military", ""),
                            "priority": post.get("priority", False),
                            "tags": post.get("tags", [])
                        }

                        # Add to appropriate committee(s)
                        for comm in member_committees:
                            comm_clean = comm.replace("[[", "").replace("]]", "").strip()
                            for c in chamber_data["committees"]:
                                c_name = c["name"]
                                c_id = c["id"].split("/")[-1] if "/" in c["id"] else c_name

                                # Match by exact committee ID/name, or by abbreviation
                                # e.g., "HASC" matches "HASC", "HAC-Defense" matches "HAC Defense"
                                # Also handle aliases like "HAC-D" for HAC-Defense
                                match = False

                                # Exact match (case-insensitive)
                                if comm_clean.lower() == c_name.lower().replace("-", " "):
                                    match = True
                                # Match committee ID without hyphens
                                elif comm_clean.lower() == c_id.lower().replace("-", ""):
                                    match = True
                                # Match committee ID with hyphens as spaces
                                elif comm_clean.lower() == c_id.lower().replace("-", " "):
                                    match = True
                                # Direct abbreviation match (e.g., "HASC" == "HASC")
                                elif comm_clean.upper() == c_id.upper():
                                    match = True
                                # Handle common abbreviation mappings
                                elif comm_clean.upper() == "HAC-D" and c_id.upper() == "HAC-DEFENSE":
                                    match = True
                                elif comm_clean.upper() == "HAC-DEFENSE" and c_id.upper() == "HAC-DEFENSE":
                                    match = True

                                # Avoid matching HASC members to HASC-CITI (subcommittee)
                                if match and comm_clean.upper() == "HASC" and "CITI" in c_id.upper():
                                    match = False

                                if match:
                                    c["members"].append(member_data)

                                    # Also add member to subcommittees
                                    for subcom in c.get("subcommittees", []):
                                        subcom_id = subcom.get("id", "").split("/")[-1] if "/" in subcom.get("id", "") else subcom.get("name", "")
                                        subcom_full = subcom.get("full_name", subcom_id).replace(" ", "-")

                                        # Check if member is on this subcommittee
                                        for ms in member_subcommittees:
                                            if ms.lower() == subcom_full.lower() or ms.lower() == subcom_id.lower():
                                                if "members" not in subcom:
                                                    subcom["members"] = []
                                                subcom["members"].append(member_data)
                                                break
                                    break

                        chamber_data["member_count"] += 1
                    except Exception as e:
                        print(f"Error parsing member {member_file}: {e}")
                        continue

            if chamber_data["committees"] or chamber_data["member_count"] > 0:
                result["chambers"].append(chamber_data)

        result["filters"]["roles"] = sorted(list(result["filters"]["roles"]))
        result["filters"]["committees"] = sorted(list(result["filters"]["committees"]))
        return result

    else:
        # Executive view: Organization -> Offices -> Leadership
        exec_path = vault_path / "Organizations" / "Executive-Branch"

        result = {
            "view": "executive",
            "organizations": [],
            "filters": {
                "organizations": [],
                "relevance": ["Acquisition", "R&E", "Policy", "Budget", "Intelligence"]
            }
        }

        if not exec_path.exists():
            return result

        # Process each organization folder - sorted alphabetically
        for org_folder in sorted(exec_path.iterdir(), key=lambda x: x.name):
            if not org_folder.is_dir():
                continue

            org_name = org_folder.name.replace("-", " ")
            result["filters"]["organizations"].append(org_name)

            org_data = {
                "name": org_name,
                "full_name": org_name,
                "office_count": 0,
                "offices": []
            }

            # First pass: collect all officials
            officials_by_org = {}  # Maps org abbreviation to list of officials
            office_files = []

            for item in sorted(org_folder.iterdir()):
                if item.is_file() and item.suffix == ".md":
                    try:
                        with open(item, 'r', encoding='utf-8') as f:
                            post = frontmatter.load(f)

                        content = post.content
                        tags = post.get("tags", [])
                        tier = post.get("tier")
                        priority = post.get("priority", False)

                        # Check if this is an office overview file
                        is_overview = "overview" in item.stem.lower() or item.stem.upper() in [
                            "OSTP", "NSC", "OMB", "DHS-OVERVIEW", "NTIA-OVERVIEW", "ODNI-OVERVIEW"
                        ]

                        # Check if this file represents an official (has tier or priority-target tag)
                        is_official = tier is not None or "priority-target" in tags or "official" in tags

                        if is_overview:
                            office_files.append((item, post, content, tags))
                        elif is_official:
                            # Parse title from content if not in frontmatter
                            title = post.get("title", "")
                            if not title and "**Position:**" in content:
                                title_match = re.search(r'\*\*Position:\*\*\s*(.+)', content)
                                if title_match:
                                    title = title_match.group(1).strip()

                            # Extract overview from content
                            overview = ""
                            if "## Overview" in content:
                                lines = content.split('\n')
                                in_overview = False
                                overview_lines = []
                                for line in lines:
                                    if "## Overview" in line:
                                        in_overview = True
                                        continue
                                    if in_overview and line.startswith("## "):
                                        break
                                    if in_overview and line.strip() and not line.startswith("|"):
                                        overview_lines.append(line.strip())
                                overview = " ".join(overview_lines)[:300]

                            # Determine which office this official belongs to
                            parent_org = None
                            for tag in tags:
                                if tag.lower() in ["ostp", "nsc", "omb", "dhs", "ntia", "odni"]:
                                    parent_org = tag.upper()
                                    break

                            official_data = {
                                "id": f"Organizations/Executive-Branch/{org_folder.name}/{item.stem}",
                                "name": item.stem.replace("-", " "),
                                "title": title,
                                "tier": tier,
                                "priority": priority,
                                "overview": overview,
                                "tags": tags
                            }

                            if parent_org:
                                if parent_org not in officials_by_org:
                                    officials_by_org[parent_org] = []
                                officials_by_org[parent_org].append(official_data)
                            else:
                                # Add to a general list
                                if "General" not in officials_by_org:
                                    officials_by_org["General"] = []
                                officials_by_org["General"].append(official_data)
                        else:
                            # This might be an office file without "-Overview" suffix
                            office_files.append((item, post, content, tags))
                    except Exception as e:
                        print(f"Error parsing {item}: {e}")
                        continue

            # Second pass: process office files and attach officials
            for item, post, content, tags in office_files:
                office_id = f"Organizations/Executive-Branch/{org_folder.name}/{item.stem}"
                office_name = item.stem.replace("-Overview", "").replace("-", " ")

                # Extract mission/overview
                mission = ""
                if "## Overview" in content:
                    lines = content.split('\n')
                    in_overview = False
                    overview_lines = []
                    for line in lines:
                        if "## Overview" in line:
                            in_overview = True
                            continue
                        if in_overview and line.startswith("## "):
                            break
                        if in_overview and line.strip() and not line.startswith("|") and not line.startswith("-"):
                            overview_lines.append(line.strip())
                    mission = " ".join(overview_lines)[:400]

                # Extract leadership from content
                leadership = []

                # Check for Director/Secretary info in content (e.g., "### Director: Name")
                dir_patterns = [
                    r'###?\s*Director[:\s]+\[\[([^\]|]+)',
                    r'###?\s*Secretary[:\s]+\[\[([^\]|]+)',
                    r'\*\*Director\*\*.*?\[\[([^\]|]+)',
                    r'Director.*?:\s*\[\[([^\]|]+)',
                ]
                for pattern in dir_patterns:
                    match = re.search(pattern, content)
                    if match:
                        name = match.group(1).replace("-", " ")
                        leadership.append({
                            "id": f"Organizations/Executive-Branch/{org_folder.name}/{match.group(1)}",
                            "name": name,
                            "title": "Director",
                            "priority": False
                        })
                        break

                # Look for leadership in "## Leadership" section
                if "## Leadership" in content:
                    lines = content.split('\n')
                    in_leadership = False
                    for line in lines:
                        if "## Leadership" in line:
                            in_leadership = True
                            continue
                        if in_leadership and line.startswith("## "):
                            break
                        # Parse table rows
                        if in_leadership and "|" in line and "---" not in line:
                            wikilinks = re.findall(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]', line)
                            for wl in wikilinks:
                                name = wl.replace("-", " ")
                                # Avoid duplicates
                                if not any(l["name"] == name for l in leadership):
                                    leadership.append({
                                        "id": f"Organizations/Executive-Branch/{org_folder.name}/{wl}",
                                        "name": name,
                                        "title": "",
                                        "priority": False
                                    })
                        # Parse list items with [[Name]] - Title format
                        if in_leadership and line.strip().startswith("- ") and "[[" in line:
                            wl_match = re.search(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]', line)
                            if wl_match:
                                name = wl_match.group(1).replace("-", " ")
                                # Extract title after the wikilink
                                title = ""
                                title_match = re.search(r'\]\]\s*[-–:]\s*(.+)', line)
                                if title_match:
                                    title = title_match.group(1).strip()
                                if not any(l["name"] == name for l in leadership):
                                    leadership.append({
                                        "id": f"Organizations/Executive-Branch/{org_folder.name}/{wl_match.group(1)}",
                                        "name": name,
                                        "title": title,
                                        "priority": False
                                    })

                # Add officials to this office based on org tag matching
                office_abbrev = item.stem.replace("-Overview", "").upper()
                if office_abbrev in officials_by_org:
                    for official in officials_by_org[office_abbrev]:
                        # Check if already in leadership
                        if not any(l["name"] == official["name"] for l in leadership):
                            leadership.append(official)

                # Sort leadership by tier (lower tier = more important) then by priority
                leadership.sort(key=lambda x: (x.get("tier") or 99, not x.get("priority", False)))

                # Extract key offices/sub-orgs
                key_offices = []
                if "## Key Offices" in content or "## Sub-Organizations" in content:
                    lines = content.split('\n')
                    in_key = False
                    for line in lines:
                        if "## Key Offices" in line or "## Sub-Organizations" in line:
                            in_key = True
                            continue
                        if in_key and line.startswith("## "):
                            break
                        if in_key and line.strip().startswith("- "):
                            office = line.replace("- ", "").strip()
                            # Strip wikilinks
                            office = re.sub(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]', r'\1', office)
                            if office:
                                key_offices.append(office)

                org_data["offices"].append({
                    "id": office_id,
                    "name": office_name,
                    "full_name": post.get("full_name", office_name),
                    "mission": mission,
                    "leadership": leadership,
                    "subordinates": [],
                    "key_offices": key_offices
                })
                org_data["office_count"] += 1

            # If no offices were found but we have officials, create a default office
            if not org_data["offices"] and officials_by_org:
                all_officials = []
                for officials in officials_by_org.values():
                    all_officials.extend(officials)
                all_officials.sort(key=lambda x: (x.get("tier") or 99, not x.get("priority", False)))

                org_data["offices"].append({
                    "id": f"Organizations/Executive-Branch/{org_folder.name}",
                    "name": org_name,
                    "full_name": org_name,
                    "mission": "",
                    "leadership": all_officials,
                    "subordinates": [],
                    "key_offices": []
                })
                org_data["office_count"] = 1

            if org_data["offices"]:
                result["organizations"].append(org_data)

        return result


@app.get("/api/political-affairs/member/{member_id:path}")
async def get_congress_member_detail(member_id: str):
    """Get detailed information about a congressional member."""
    import frontmatter

    vault_path = get_vault_path()
    member_file = vault_path / f"{member_id}.md"

    if not member_file.exists():
        raise HTTPException(status_code=404, detail="Member not found")

    try:
        with open(member_file, 'r', encoding='utf-8') as f:
            post = frontmatter.load(f)

        content = post.content

        # Extract title
        title_match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
        title = title_match.group(1) if title_match else member_file.stem.replace("-", " ")

        # Parse committees
        committees = post.get("committees", [])
        if isinstance(committees, str):
            committees = [c.strip() for c in committees.split(",")]

        # Parse roles
        roles = post.get("roles", [])
        if isinstance(roles, str):
            roles = [r.strip() for r in roles.split(",")]

        # Extract sections
        sections = {}
        current_section = ""
        current_content = []

        for line in content.split('\n'):
            h2_match = re.match(r'^##\s+(.+)$', line)
            if h2_match:
                if current_section:
                    sections[current_section.lower().replace(" ", "_")] = '\n'.join(current_content).strip()
                current_section = h2_match.group(1)
                current_content = []
            else:
                current_content.append(line)

        if current_section:
            sections[current_section.lower().replace(" ", "_")] = '\n'.join(current_content).strip()

        # Determine chamber from path
        chamber = "Senate" if "Senate" in member_id else "House"

        # Parse Member Details table (can be in Overview or Member Details section)
        member_details = {}

        # First try Overview section (most common for Congress members)
        overview_content = sections.get("overview", "")
        if overview_content:
            for line in overview_content.split('\n'):
                if "|" in line and "**" in line:
                    cells = [c.strip() for c in line.split("|") if c.strip()]
                    if len(cells) >= 2:
                        key = cells[0].replace("**", "").strip().lower().replace(" ", "_")
                        value = cells[1].strip()
                        member_details[key] = value

        # Also try Member Details section
        details_content = sections.get("member_details", "")
        if details_content:
            for line in details_content.split('\n'):
                if "|" in line and "**" in line:
                    cells = [c.strip() for c in line.split("|") if c.strip()]
                    if len(cells) >= 2:
                        key = cells[0].replace("**", "").strip().lower().replace(" ", "_")
                        value = cells[1].strip()
                        member_details[key] = value

        # Extract prose content from overview (non-table text)
        overview_prose = ""
        if overview_content:
            prose_lines = []
            in_table = False
            for line in overview_content.split('\n'):
                if line.strip().startswith('|'):
                    in_table = True
                elif line.strip() == '' and in_table:
                    in_table = False
                elif not in_table and line.strip() and not line.strip().startswith('|'):
                    prose_lines.append(line)
            overview_prose = '\n'.join(prose_lines).strip()

        # Parse Committee Assignments table
        committee_assignments = []
        assignments_content = sections.get("committee_assignments", "")
        if assignments_content:
            for line in assignments_content.split('\n'):
                if "|" in line and "[[" in line:
                    cells = [c.strip() for c in line.split("|") if c.strip()]
                    if len(cells) >= 2:
                        # Extract committee name from wiki link
                        comm_match = re.search(r'\[\[([^\]|]+)', cells[0])
                        committee = comm_match.group(1) if comm_match else cells[0]
                        role = cells[1] if len(cells) > 1 else ""
                        committee_assignments.append({
                            "committee": committee,
                            "role": role
                        })

        # Parse Defense Focus Areas
        defense_focus = []
        focus_content = sections.get("defense_focus_areas", "")
        if focus_content:
            for line in focus_content.split('\n'):
                if line.strip().startswith("- **"):
                    # Extract focus area like "- **Electronic Warfare:** description"
                    match = re.match(r'- \*\*([^:*]+)\*\*:?\s*(.*)', line.strip())
                    if match:
                        defense_focus.append({
                            "area": match.group(1).strip(),
                            "description": match.group(2).strip()
                        })

        # Parse Notes section
        notes = []
        notes_content = sections.get("notes", "")
        if notes_content:
            for line in notes_content.split('\n'):
                if line.strip().startswith("- "):
                    notes.append(line.strip()[2:])

        # Parse Related section
        related = []
        related_content = sections.get("related", "")
        if related_content:
            for line in related_content.split('\n'):
                if "[[" in line:
                    match = re.search(r'\[\[([^\]|]+)', line)
                    if match:
                        related.append(match.group(1))

        return {
            "id": member_id,
            "name": title,
            "party": post.get("party", ""),
            "state": post.get("state", ""),
            "district": post.get("district", ""),
            "chamber": chamber,
            "committees": committees,
            "roles": roles,
            "military": member_details.get("military_service", member_details.get("background", post.get("military", ""))),
            "priority": post.get("priority", False) or "priority" in post.get("tags", []),
            "overview": overview_prose,  # Only prose text, not the table
            "relevance": sections.get("ew/rf_relevance", "") or sections.get("relevance", ""),
            "state_interests": sections.get("state_interests", "") or sections.get("district_interests", ""),
            "key_staff": sections.get("key_staff", "") or sections.get("staff", ""),
            "member_details": member_details,
            "committee_assignments": committee_assignments,
            "defense_focus": defense_focus,
            "notes": notes,
            "related": related,
            "tags": post.get("tags", [])
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/political-affairs/committee/{committee_id:path}")
async def get_committee_detail(committee_id: str):
    """Get detailed information about a congressional committee."""
    import frontmatter

    vault_path = get_vault_path()
    committee_file = vault_path / f"{committee_id}.md"

    if not committee_file.exists():
        raise HTTPException(status_code=404, detail="Committee not found")

    try:
        with open(committee_file, 'r', encoding='utf-8') as f:
            post = frontmatter.load(f)

        content = post.content

        # Extract title
        title_match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
        title = title_match.group(1) if title_match else committee_file.stem.replace("-", " ")

        # Determine chamber from path
        chamber = "Senate" if "Senate" in committee_id else "House"

        # Parse leadership
        leadership = []
        subcommittees = []
        staff = []
        members = []

        # Parse leadership table
        if "## Leadership" in content or "## Committee Leadership" in content:
            lines = content.split('\n')
            in_leadership = False
            for line in lines:
                if "## Leadership" in line or "## Committee Leadership" in line:
                    in_leadership = True
                    continue
                if in_leadership and line.startswith("##"):
                    break
                if in_leadership and "|" in line and "[[" in line:
                    # Parse table row
                    cells = [c.strip() for c in line.split("|") if c.strip()]
                    if len(cells) >= 2:
                        role_text = cells[0]
                        name_match = re.search(r'\[\[([^\]|]+)', cells[1])
                        if name_match:
                            leadership.append({
                                "role": role_text,
                                "name": name_match.group(1).replace("-", " "),
                                "party": cells[2] if len(cells) > 2 else ""
                            })

        # Parse subcommittees
        if "## Subcommittees" in content:
            lines = content.split('\n')
            in_subcommittees = False
            current_subcom = None
            for line in lines:
                if "## Subcommittees" in line:
                    in_subcommittees = True
                    continue
                if in_subcommittees and line.startswith("## "):
                    break
                if in_subcommittees and line.startswith("### "):
                    if current_subcom:
                        subcommittees.append(current_subcom)
                    current_subcom = {"name": line.replace("### ", "").strip(), "chair": "", "ranking": ""}
                if in_subcommittees and current_subcom:
                    if "Chair:" in line:
                        chair_match = re.search(r'\[\[([^\]|]+)', line)
                        if chair_match:
                            current_subcom["chair"] = chair_match.group(1).replace("-", " ")
                    if "Ranking:" in line:
                        ranking_match = re.search(r'\[\[([^\]|]+)', line)
                        if ranking_match:
                            current_subcom["ranking"] = ranking_match.group(1).replace("-", " ")
            if current_subcom:
                subcommittees.append(current_subcom)

        # Parse staff
        if "## Key Staff" in content or "## Staff" in content:
            lines = content.split('\n')
            in_staff = False
            for line in lines:
                if "## Key Staff" in line or "## Staff" in line:
                    in_staff = True
                    continue
                if in_staff and line.startswith("##"):
                    break
                if in_staff and line.startswith("- "):
                    staff_text = line.replace("- ", "").strip()
                    if ":" in staff_text:
                        parts = staff_text.split(":", 1)
                        staff.append({
                            "name": parts[0].strip(),
                            "subject_areas": [s.strip() for s in parts[1].split(",")]
                        })
                    elif " - " in staff_text:
                        parts = staff_text.split(" - ", 1)
                        staff.append({
                            "name": parts[0].strip(),
                            "subject_areas": [parts[1].strip()] if len(parts) > 1 else []
                        })
                    else:
                        staff.append({"name": staff_text, "subject_areas": []})

        return {
            "id": committee_id,
            "name": title,
            "full_name": post.get("full_name", title),
            "chamber": chamber,
            "committee_type": post.get("committee_type", ""),
            "jurisdiction": post.get("jurisdiction", ""),
            "leadership": leadership,
            "subcommittees": subcommittees,
            "staff": staff,
            "member_count": post.get("member_count", 0),
            "tags": post.get("tags", [])
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/political-affairs/office/{office_id:path}")
async def get_executive_office_detail(office_id: str):
    """Get detailed information about an executive branch office."""
    import frontmatter

    vault_path = get_vault_path()
    office_file = vault_path / f"{office_id}.md"

    if not office_file.exists():
        raise HTTPException(status_code=404, detail="Office not found")

    try:
        with open(office_file, 'r', encoding='utf-8') as f:
            post = frontmatter.load(f)

        content = post.content

        # Extract title
        title_match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
        title = title_match.group(1) if title_match else office_file.stem.replace("-", " ")

        # Determine organization from path
        path_parts = office_id.split("/")
        organization = ""
        if "Executive-Branch" in path_parts:
            idx = path_parts.index("Executive-Branch")
            if idx + 1 < len(path_parts):
                organization = path_parts[idx + 1].replace("-", " ")

        # Extract sections
        sections = {}
        current_section = ""
        current_content = []

        for line in content.split('\n'):
            h2_match = re.match(r'^##\s+(.+)$', line)
            if h2_match:
                if current_section:
                    sections[current_section.lower().replace(" ", "_")] = '\n'.join(current_content).strip()
                current_section = h2_match.group(1)
                current_content = []
            else:
                current_content.append(line)

        if current_section:
            sections[current_section.lower().replace(" ", "_")] = '\n'.join(current_content).strip()

        # Parse leadership
        leadership = []
        leadership_section = sections.get("leadership", "") or sections.get("current_leadership", "")
        for line in leadership_section.split('\n'):
            if "[[" in line:
                matches = re.findall(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]', line)
                for m in matches:
                    leadership.append({
                        "id": f"Organizations/Executive-Branch/{organization.replace(' ', '-')}/{m}",
                        "name": m.replace("-", " "),
                        "title": ""
                    })
            elif line.startswith("- ") and "**" in line:
                name_match = re.search(r'\*\*([^*]+)\*\*', line)
                if name_match:
                    name = name_match.group(1)
                    title = line.replace(f"**{name}**", "").replace("- ", "").strip(" -")
                    leadership.append({"id": "", "name": name, "title": title})

        # Parse key offices/subordinates
        key_offices = []
        org_section = sections.get("organization", "") or sections.get("key_offices", "")
        for line in org_section.split('\n'):
            if "[[" in line:
                matches = re.findall(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]', line)
                for m in matches:
                    key_offices.append(m.replace("-", " "))
            elif line.startswith("- "):
                office_text = line.replace("- ", "").strip()
                if office_text:
                    key_offices.append(office_text)

        return {
            "id": office_id,
            "name": title,
            "full_name": post.get("full_name", title),
            "organization": organization,
            "mission": sections.get("mission", "") or sections.get("overview", ""),
            "leadership": leadership,
            "key_offices": key_offices,
            "relevance": sections.get("ew/rf_relevance", "") or sections.get("relevance", ""),
            "related_buyers": sections.get("related", ""),
            "tags": post.get("tags", [])
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/political-affairs/official/{official_id:path}")
async def get_executive_official_detail(official_id: str):
    """Get detailed information about an executive branch official."""
    import frontmatter

    vault_path = get_vault_path()
    official_file = vault_path / f"{official_id}.md"

    if not official_file.exists():
        raise HTTPException(status_code=404, detail="Official not found")

    try:
        with open(official_file, 'r', encoding='utf-8') as f:
            post = frontmatter.load(f)

        content = post.content
        tags = post.get("tags", [])

        # Extract title (name)
        title_match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
        raw_title = title_match.group(1) if title_match else official_file.stem.replace("-", " ")
        # Clean up any star emojis from title
        name = re.sub(r'\s*[\u2B50\u2605]+\s*', '', raw_title).strip()

        # Determine organization from path
        path_parts = official_id.split("/")
        organization = ""
        parent_office = ""
        if "Executive-Branch" in path_parts:
            idx = path_parts.index("Executive-Branch")
            if idx + 1 < len(path_parts):
                organization = path_parts[idx + 1].replace("-", " ")

        # Get position from content
        position = ""
        position_match = re.search(r'\*\*Position:\*\*\s*(.+)', content)
        if position_match:
            position = position_match.group(1).strip()

        # Extract sections
        sections = {}
        current_section = ""
        current_content = []

        for line in content.split('\n'):
            h2_match = re.match(r'^##\s+(.+)$', line)
            if h2_match:
                if current_section:
                    sections[current_section.lower().replace(" ", "_").replace("/", "_")] = '\n'.join(current_content).strip()
                current_section = h2_match.group(1)
                current_content = []
            else:
                current_content.append(line)

        if current_section:
            sections[current_section.lower().replace(" ", "_").replace("/", "_")] = '\n'.join(current_content).strip()

        # Parse Overview table
        overview_details = {}
        overview_content = sections.get("overview", "")
        for line in overview_content.split('\n'):
            if "|" in line and "**" not in line:
                cells = [c.strip() for c in line.split("|") if c.strip()]
                if len(cells) >= 2 and not cells[0].startswith("-"):
                    key = cells[0].strip().lower().replace(" ", "_")
                    value = cells[1].strip()
                    # Clean wiki links
                    value = re.sub(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]', r'\1', value)
                    overview_details[key] = value

        # Parse Background section
        background = {}
        background_content = sections.get("background", "")
        current_subsection = ""
        current_subsection_content = []
        for line in background_content.split('\n'):
            h3_match = re.match(r'^###\s+(.+)$', line)
            if h3_match:
                if current_subsection:
                    background[current_subsection.lower().replace(" ", "_")] = '\n'.join(current_subsection_content).strip()
                current_subsection = h3_match.group(1)
                current_subsection_content = []
            else:
                current_subsection_content.append(line)
        if current_subsection:
            background[current_subsection.lower().replace(" ", "_")] = '\n'.join(current_subsection_content).strip()

        # Parse Key Positions section (like "5G Initiative")
        key_initiatives = []
        for section_name, section_content in sections.items():
            if section_name not in ["overview", "background", "related", "notes", "critical_contact", "engagement_strategy"]:
                if section_content and len(section_content) > 20:
                    key_initiatives.append({
                        "name": section_name.replace("_", " ").title(),
                        "content": section_content
                    })

        # Parse Why Critical section
        why_critical = []
        critical_content = sections.get("why_critical_for_ew_spectrum_companies", "") or sections.get("why_critical", "")
        if critical_content:
            for line in critical_content.split('\n'):
                if line.strip().startswith(("1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "9.")):
                    why_critical.append(line.strip()[2:].strip())

        # Parse Engagement Strategy
        engagement = sections.get("engagement_strategy", "")

        # Parse Related section
        related = []
        related_content = sections.get("related", "")
        if related_content:
            for line in related_content.split('\n'):
                if "[[" in line:
                    match = re.search(r'\[\[([^\]|]+)', line)
                    if match:
                        related.append(match.group(1))

        # Parse Notes
        notes = []
        notes_content = sections.get("notes", "")
        if notes_content:
            for line in notes_content.split('\n'):
                if line.strip().startswith("- "):
                    notes.append(line.strip()[2:])

        return {
            "id": official_id,
            "name": name,
            "position": position,
            "organization": organization,
            "tier": post.get("tier"),
            "priority": post.get("priority", False) or "priority-target" in tags,
            "overview_details": overview_details,
            "background": background,
            "key_initiatives": key_initiatives,
            "why_critical": why_critical,
            "engagement_strategy": engagement,
            "related": related,
            "notes": notes,
            "tags": tags
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# RSS Feed Proxy Endpoints
# =============================================================================

def extract_thumbnail(entry) -> Optional[str]:
    """Extract thumbnail from various RSS formats."""
    # media:thumbnail
    if hasattr(entry, 'media_thumbnail') and entry.media_thumbnail:
        return entry.media_thumbnail[0].get('url')
    # media:content
    if hasattr(entry, 'media_content') and entry.media_content:
        for media in entry.media_content:
            if media.get('type', '').startswith('image'):
                return media.get('url')
    # enclosure
    if hasattr(entry, 'enclosures') and entry.enclosures:
        for enc in entry.enclosures:
            if enc.get('type', '').startswith('image'):
                return enc.get('href')
    return None


def clean_html_description(raw_html: str) -> str:
    """Strip HTML tags and clean up email newsletter descriptions."""
    import re
    import html as html_module

    if not raw_html:
        return ""

    text = raw_html

    # Remove style tags and their content
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)

    # Remove CSS comments (/* ... */)
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.DOTALL)

    # Remove inline CSS properties that leaked (like .mso, margin:, padding:, etc.)
    text = re.sub(r'\.mso[^\s;]*[^}]*[;}]?', '', text)
    text = re.sub(r'[a-z-]+:\s*[^;]+;', '', text)

    # Remove HTML tags
    text = re.sub(r'<[^>]+>', ' ', text)

    # Decode HTML entities
    text = html_module.unescape(text)

    # Clean up whitespace
    text = re.sub(r'\s+', ' ', text).strip()

    # Remove any remaining CSS-like fragments
    text = re.sub(r'\{[^}]*\}', '', text)

    return text


def is_defense_relevant(title: str, description: str) -> bool:
    """
    Filter articles for defense/national security relevance.
    Returns True if >60% confidence the article is relevant to defense BD work.
    Used primarily for filtering general think tank feeds like RAND.
    """
    text = f"{title} {description}".lower()

    # High-relevance terms (strong indicators) - if any present, very likely relevant
    high_relevance = [
        # Military/Defense core
        'defense', 'defence', 'military', 'pentagon', 'dod ', 'armed forces', 'warfare',
        'national security', 'homeland security', 'intelligence community',
        # Services (with word boundaries to avoid false positives)
        ' army ', 'u.s. army', 'us army', ' navy ', 'u.s. navy', 'us navy',
        'air force', 'marine corps', 'space force', 'coast guard',
        'usaf', 'usmc', 'socom', 'special operations', 'special forces',
        # Domains
        'electronic warfare', 'cyber warfare', 'cyberattack', 'cybersecurity',
        'drone', 'uav', 'uas', 'unmanned', 'autonomous weapon',
        'missile', 'hypersonic', 'nuclear weapon', 'nuclear deterr',
        'spectrum warfare', 'radar', 'sensor', 'c4isr', 'isr',
        'counter-uas', 'c-uas', 'counter-drone',
        # Geopolitics/Threats (defense context)
        'china', 'russia', 'ukraine', 'taiwan', 'iran',
        'indo-pacific', 'nato', 'adversar', 'deterrence', 'autocracy',
        'north korea',
        # Acquisition/Policy
        'defense acquisition', 'defense procurement', 'defense contractor',
        'defense industrial', 'ndaa', 'defense budget', 'defense appropriation',
        # Technology (defense context)
        'artificial intelligence', 'machine learning', 'quantum computing',
        'satellite', 'space-based', 'directed energy', 'laser weapon',
        # Operations
        'combat', 'battlefield', 'warfighter', 'force structure',
        'deployment', 'readiness', 'military posture',
        # Organizations (defense research)
        'darpa', 'diu', 'afrl', 'nrl', 'onr', 'arl',
        # Alliances and partners
        'allies', 'interoperability', 'coalition',
    ]

    # Medium-relevance terms (need 2+ to be confident)
    medium_relevance = [
        'security', 'conflict', 'veteran', 'servicemember',
        'allies', 'coalition', 'treaty',
        'geopolitic', 'foreign policy',
        'terrorist', 'extremis', 'counterterror', 'insurgent',
        'weapon', 'munition', 'ammunition', 'armor',
        'aircraft', 'fighter jet', 'bomber', 'submarine', 'carrier',
        'surveillance', 'reconnaissance', 'targeting',
        'interoperability', 'joint force',
    ]

    # Exclusion terms (strong indicators of non-defense content)
    exclusions = [
        # Healthcare
        'health care', 'health insurance', 'medicare', 'medicaid',
        'hospital', 'patient', 'physician', 'nurse', 'clinical',
        'opioid', 'addiction', 'substance abuse', 'alcohol misuse',
        'mental health', 'depression', 'anxiety treatment',
        'weight management', 'obesity', 'diet', 'nutrition',
        'hospice', 'palliative', 'end-of-life',
        # Education
        'education reform', 'school district', 'k-12', 'teacher',
        'student achievement', 'college tuition', 'higher education',
        'early childhood', 'preschool',
        # Domestic policy
        'housing market', 'real estate', 'mortgage', 'homelessness',
        'climate change policy', 'environmental regulation',
        'immigration reform', 'border policy',
        'poverty', 'welfare', 'social security', 'retirement',
        'minimum wage', 'labor market', 'unemployment',
        'criminal justice', 'policing', 'incarceration', 'prison',
        # Economics (non-defense)
        'bankruptcy', 'mass tort', 'class action',
        'consumer protection', 'financial regulation',
        # Other
        'arts', 'culture', 'museum',
        'gun policy', 'firearm policy', 'gun violence', 'gun law',
        'occupational safety', 'workplace safety', 'osha',
        'ambulance', 'emergency medical', 'ems',
        'school aid', 'school funding', 'state funding formula',
        'adult learner', 'community college', 'workforce development',
        'survey panel', 'data collection',
    ]

    # Check exclusions first
    has_exclusion = any(term in text for term in exclusions)
    if has_exclusion:
        # Only override exclusion if we have strong defense indicators
        defense_override = any(term in text for term in [
            'defense', 'military', 'pentagon', 'armed forces',
            'army', 'navy', 'air force', 'marine',
        ])
        if not defense_override:
            return False

    # Count relevance signals
    high_matches = sum(1 for term in high_relevance if term in text)
    medium_matches = sum(1 for term in medium_relevance if term in text)

    # Decision logic - be stricter
    if high_matches > 0:
        return True

    if medium_matches >= 3:
        return True

    return False


# Feeds that should have defense relevance filtering applied
FILTERED_FEED_DOMAINS = [
    'rand.org',  # RAND covers many non-defense topics
]


@app.get("/api/rss/fetch")
async def fetch_rss_feed(url: str):
    """Proxy RSS feed to avoid CORS issues."""
    import httpx
    import feedparser

    # Browser-like headers to avoid bot blocking (especially for Kill the Newsletter)
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,application/rss+xml,application/atom+xml,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
    }

    # Sites with known SSL issues - skip verification
    ssl_problem_domains = ['jamestown.org']
    skip_ssl = any(domain in url for domain in ssl_problem_domains)

    try:
        # Use explicit timeout config to avoid hanging
        # Kill the Newsletter feeds can be 500KB-1MB, need longer read timeout
        timeout_config = httpx.Timeout(30.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout_config, verify=not skip_ssl) as client:
            response = await client.get(url, follow_redirects=True, headers=headers)
            response.raise_for_status()

            # Parse the feed
            feed = feedparser.parse(response.text)

            # Check if this feed should have defense relevance filtering
            should_filter = any(domain in url for domain in FILTERED_FEED_DOMAINS)

            articles = []
            for entry in feed.entries[:50]:  # Limit to 50 per feed
                title = entry.get("title", "")
                description = clean_html_description(entry.get("summary") or entry.get("description") or "")[:500]

                # Apply defense relevance filter for specified feeds
                if should_filter and not is_defense_relevant(title, description):
                    continue

                articles.append({
                    "id": entry.get("id") or entry.get("link"),
                    "title": title,
                    "link": entry.get("link", ""),
                    "description": description,
                    "pubDate": entry.get("published") or entry.get("updated"),
                    "author": entry.get("author", ""),
                    "thumbnail": extract_thumbnail(entry),
                })

            return {
                "success": True,
                "feedTitle": feed.feed.get("title", ""),
                "articles": articles,
                "filtered": should_filter,  # Let frontend know filtering was applied
            }
    except httpx.TimeoutException:
        return {"success": False, "error": "Request timed out", "articles": []}
    except httpx.HTTPStatusError as e:
        return {"success": False, "error": f"HTTP {e.response.status_code}", "articles": []}
    except Exception as e:
        return {"success": False, "error": str(e), "articles": []}


# ============================================================================
# Engagement Pipeline Endpoints
# ============================================================================

@app.get("/api/engagements/stats")
async def get_engagement_stats():
    """Get pipeline metrics."""
    import sqlite3
    conn = sqlite3.connect(str(db_path))

    stages = ["targeted", "outreach", "engaged", "warm", "on_contract", "on_ice"]

    by_stage = {}
    for stage in stages:
        count = conn.execute(
            "SELECT COUNT(*) FROM engagements WHERE stage = ?",
            (stage,)
        ).fetchone()[0]
        by_stage[stage] = count

    by_priority = {}
    for priority in ["critical", "high", "medium", "low"]:
        count = conn.execute(
            "SELECT COUNT(*) FROM engagements WHERE priority = ?",
            (priority,)
        ).fetchone()[0]
        by_priority[priority] = count

    by_type = {}
    rows = conn.execute(
        "SELECT entity_type, COUNT(*) FROM engagements GROUP BY entity_type"
    ).fetchall()
    for row in rows:
        by_type[row[0]] = row[1]

    total = conn.execute("SELECT COUNT(*) FROM engagements").fetchone()[0]
    conn.close()

    return {
        "total": total,
        "by_stage": by_stage,
        "by_priority": by_priority,
        "by_entity_type": by_type,
    }


@app.get("/api/engagements/board")
async def get_engagements_board(
    entity_type: Optional[str] = Query(None, description="Filter by entity type"),
    service: Optional[str] = Query(None, description="Filter by service"),
    priority: Optional[str] = Query(None, description="Filter by priority"),
    search: Optional[str] = Query(None, description="Search by entity name"),
):
    """Get all engagements with entity data for the Kanban board."""
    import sqlite3
    conn = sqlite3.connect(str(db_path))

    query = "SELECT id, entity_id, entity_type, stage, priority, notes, created_at, updated_at FROM engagements WHERE 1=1"
    params = []

    if entity_type:
        types = [t.strip() for t in entity_type.split(",")]
        query += f" AND entity_type IN ({','.join('?' * len(types))})"
        params.extend(types)

    if priority:
        priorities = [p.strip() for p in priority.split(",")]
        query += f" AND priority IN ({','.join('?' * len(priorities))})"
        params.extend(priorities)

    # Order by priority (critical > high > medium > low) then by updated_at
    query += " ORDER BY CASE priority WHEN 'critical' THEN 1 WHEN 'high' THEN 2 WHEN 'medium' THEN 3 WHEN 'low' THEN 4 ELSE 5 END, updated_at DESC"

    rows = conn.execute(query, params).fetchall()
    conn.close()

    entities_by_id = {e.id: e for e in _entities_cache}

    engagements = []
    for row in rows:
        eng = _get_engagement_with_entity(row, entities_by_id)

        if service:
            # Parse comma-separated filter values
            service_values = [s.strip().lower() for s in service.split(",")]
            # Normalize entity's service and check if ANY normalized value matches ANY filter value
            entity_normalized = _normalize_service(eng["entity_service"]) if eng["entity_service"] else []
            if not any(ns.lower() in service_values for ns in entity_normalized):
                continue

        if search:
            if search.lower() not in eng["entity_name"].lower():
                continue

        engagements.append(eng)

    stages = ["targeted", "outreach", "engaged", "warm", "on_contract", "on_ice"]

    # Get distinct organizations from all entities using _normalize_service
    # This gives us only top-level canonical orgs (Army, Navy, etc.) not compound values
    all_orgs = set()
    for e in _entities_cache:
        if e.service:
            normalized = _normalize_service(e.service)
            for org in normalized:
                all_orgs.add(org)
    organizations = sorted(all_orgs)

    return {
        "engagements": engagements,
        "stages": stages,
        "stats": {
            stage: len([e for e in engagements if e["stage"] == stage])
            for stage in stages
        },
        "filters": {
            "organizations": organizations
        }
    }


@app.post("/api/engagements")
async def create_engagement(engagement: EngagementCreate):
    """Create a new engagement."""
    import sqlite3
    conn = sqlite3.connect(str(db_path))

    existing = conn.execute(
        "SELECT id FROM engagements WHERE entity_id = ?",
        (engagement.entity_id,)
    ).fetchone()

    if existing:
        conn.close()
        raise HTTPException(status_code=400, detail="Engagement already exists for this entity")

    entity = next((e for e in _entities_cache if e.id == engagement.entity_id), None)
    if not entity:
        conn.close()
        raise HTTPException(status_code=404, detail="Entity not found")

    eng_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()

    conn.execute(
        """INSERT INTO engagements (id, entity_id, entity_type, stage, priority, notes, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (eng_id, engagement.entity_id, engagement.entity_type, engagement.stage,
         engagement.priority, engagement.notes, now, now)
    )
    conn.commit()
    conn.close()

    return {
        "id": eng_id,
        "entity_id": engagement.entity_id,
        "entity_type": engagement.entity_type,
        "entity_name": entity.title,
        "entity_service": entity.service,
        "stage": engagement.stage,
        "priority": engagement.priority,
        "notes": engagement.notes,
        "created_at": now,
        "updated_at": now,
    }


@app.put("/api/engagements/{engagement_id}")
async def update_engagement(engagement_id: str, update: EngagementUpdate):
    """Update an engagement."""
    import sqlite3
    conn = sqlite3.connect(str(db_path))

    existing = conn.execute(
        "SELECT entity_id FROM engagements WHERE id = ?",
        (engagement_id,)
    ).fetchone()

    if not existing:
        conn.close()
        raise HTTPException(status_code=404, detail="Engagement not found")

    updates = []
    params = []

    if update.stage is not None:
        updates.append("stage = ?")
        params.append(update.stage)
    if update.priority is not None:
        updates.append("priority = ?")
        params.append(update.priority)
    if update.notes is not None:
        updates.append("notes = ?")
        params.append(update.notes)

    if updates:
        updates.append("updated_at = ?")
        params.append(datetime.utcnow().isoformat())
        params.append(engagement_id)

        conn.execute(
            f"UPDATE engagements SET {', '.join(updates)} WHERE id = ?",
            params
        )
        conn.commit()

    row = conn.execute(
        "SELECT id, entity_id, entity_type, stage, priority, notes, created_at, updated_at FROM engagements WHERE id = ?",
        (engagement_id,)
    ).fetchone()
    conn.close()

    entities_by_id = {e.id: e for e in _entities_cache}
    return _get_engagement_with_entity(row, entities_by_id)


@app.patch("/api/engagements/{engagement_id}/stage")
async def update_engagement_stage(engagement_id: str, update: EngagementStageUpdate):
    """Quick stage update for drag-and-drop."""
    import sqlite3
    conn = sqlite3.connect(str(db_path))

    existing = conn.execute(
        "SELECT id FROM engagements WHERE id = ?",
        (engagement_id,)
    ).fetchone()

    if not existing:
        conn.close()
        raise HTTPException(status_code=404, detail="Engagement not found")

    now = datetime.utcnow().isoformat()
    conn.execute(
        "UPDATE engagements SET stage = ?, updated_at = ? WHERE id = ?",
        (update.stage, now, engagement_id)
    )
    conn.commit()

    row = conn.execute(
        "SELECT id, entity_id, entity_type, stage, priority, notes, created_at, updated_at FROM engagements WHERE id = ?",
        (engagement_id,)
    ).fetchone()
    conn.close()

    entities_by_id = {e.id: e for e in _entities_cache}
    return _get_engagement_with_entity(row, entities_by_id)


@app.delete("/api/engagements/{engagement_id}")
async def delete_engagement(engagement_id: str):
    """Delete an engagement."""
    import sqlite3
    conn = sqlite3.connect(str(db_path))

    existing = conn.execute(
        "SELECT id FROM engagements WHERE id = ?",
        (engagement_id,)
    ).fetchone()

    if not existing:
        conn.close()
        raise HTTPException(status_code=404, detail="Engagement not found")

    conn.execute("DELETE FROM engagements WHERE id = ?", (engagement_id,))
    conn.commit()
    conn.close()

    return {"success": True, "id": engagement_id}


# =============================================================================
# CAMPAIGN CRUD ENDPOINTS
# =============================================================================

def _get_campaign_with_details(campaign_id: str, conn) -> Optional[dict]:
    """Get campaign with stakeholders and milestones."""
    row = conn.execute(
        "SELECT * FROM campaigns WHERE id = ?", (campaign_id,)
    ).fetchone()

    if not row:
        return None

    cols = ['id', 'name', 'description', 'status', 'campaign_type',
            'target_program_id', 'target_value', 'target_close_date',
            'probability', 'lead_owner', 'created_at', 'updated_at']
    campaign = dict(zip(cols, row))

    # Get stakeholders with entity data
    stakeholder_rows = conn.execute("""
        SELECT id, campaign_id, entity_id, entity_type, role, influence_level,
               sentiment, engagement_status, competitor_type, owner, notes, last_contact_date,
               created_at, updated_at, sort_order
        FROM campaign_stakeholders WHERE campaign_id = ?
        ORDER BY role, sort_order, created_at
    """, (campaign_id,)).fetchall()

    entities_by_id = {e.id: e for e in _entities_cache}
    stakeholders = []
    for srow in stakeholder_rows:
        scols = ['id', 'campaign_id', 'entity_id', 'entity_type', 'role',
                 'influence_level', 'sentiment', 'engagement_status', 'competitor_type', 'owner',
                 'notes', 'last_contact_date', 'created_at', 'updated_at', 'sort_order']
        s = dict(zip(scols, srow))
        entity = entities_by_id.get(s['entity_id'])
        s['entity_name'] = entity.title if entity else s['entity_id']
        s['entity_service'] = entity.service if entity else None
        stakeholders.append(s)

    campaign['stakeholders'] = stakeholders

    # Get milestones
    milestone_rows = conn.execute("""
        SELECT id, campaign_id, title, description, due_date, completed_date,
               status, related_stakeholders, created_at
        FROM campaign_milestones WHERE campaign_id = ? ORDER BY due_date ASC
    """, (campaign_id,)).fetchall()

    milestones = []
    for mrow in milestone_rows:
        mcols = ['id', 'campaign_id', 'title', 'description', 'due_date',
                 'completed_date', 'status', 'related_stakeholders', 'created_at']
        milestones.append(dict(zip(mcols, mrow)))

    campaign['milestones'] = milestones

    # Get target program info if set
    if campaign['target_program_id']:
        program = entities_by_id.get(campaign['target_program_id'])
        campaign['target_program_name'] = program.title if program else None

    return campaign


@app.get("/api/campaigns")
async def list_campaigns(
    status: Optional[str] = Query(None),
    campaign_type: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
):
    """List all campaigns with summary data."""
    import sqlite3
    conn = sqlite3.connect(str(db_path))

    query = "SELECT * FROM campaigns WHERE 1=1"
    params = []

    if status:
        statuses = [s.strip() for s in status.split(",")]
        query += f" AND status IN ({','.join('?' * len(statuses))})"
        params.extend(statuses)

    if campaign_type:
        types = [t.strip() for t in campaign_type.split(",")]
        query += f" AND campaign_type IN ({','.join('?' * len(types))})"
        params.extend(types)

    query += " ORDER BY updated_at DESC"

    rows = conn.execute(query, params).fetchall()

    cols = ['id', 'name', 'description', 'status', 'campaign_type',
            'target_program_id', 'target_value', 'target_close_date',
            'probability', 'lead_owner', 'created_at', 'updated_at']

    campaigns = []
    entities_by_id = {e.id: e for e in _entities_cache}

    for row in rows:
        campaign = dict(zip(cols, row))

        if search and search.lower() not in campaign['name'].lower():
            continue

        # Get stakeholder count
        count = conn.execute(
            "SELECT COUNT(*) FROM campaign_stakeholders WHERE campaign_id = ?",
            (campaign['id'],)
        ).fetchone()[0]
        campaign['stakeholder_count'] = count

        # Get milestone progress
        total = conn.execute(
            "SELECT COUNT(*) FROM campaign_milestones WHERE campaign_id = ?",
            (campaign['id'],)
        ).fetchone()[0]
        completed = conn.execute(
            "SELECT COUNT(*) FROM campaign_milestones WHERE campaign_id = ? AND status = 'completed'",
            (campaign['id'],)
        ).fetchone()[0]
        campaign['milestones_total'] = total
        campaign['milestones_completed'] = completed

        # Get target program name
        if campaign['target_program_id']:
            program = entities_by_id.get(campaign['target_program_id'])
            campaign['target_program_name'] = program.title if program else None

        campaigns.append(campaign)

    conn.close()

    return {
        "campaigns": campaigns,
        "filters": {
            "statuses": CAMPAIGN_STATUSES,
            "types": CAMPAIGN_TYPES,
        }
    }


@app.post("/api/campaigns")
async def create_campaign(campaign: CampaignCreate):
    """Create a new campaign."""
    import sqlite3
    import uuid

    conn = sqlite3.connect(str(db_path))
    campaign_id = str(uuid.uuid4())

    conn.execute("""
        INSERT INTO campaigns (id, name, description, status, campaign_type,
                              target_program_id, target_value, target_close_date,
                              probability, lead_owner)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (campaign_id, campaign.name, campaign.description, campaign.status,
          campaign.campaign_type, campaign.target_program_id, campaign.target_value,
          campaign.target_close_date, campaign.probability, campaign.lead_owner))

    conn.commit()

    result = _get_campaign_with_details(campaign_id, conn)
    conn.close()

    return result


@app.get("/api/campaigns/{campaign_id}")
async def get_campaign(campaign_id: str):
    """Get campaign with all stakeholders and milestones."""
    import sqlite3
    conn = sqlite3.connect(str(db_path))

    result = _get_campaign_with_details(campaign_id, conn)
    conn.close()

    if not result:
        raise HTTPException(status_code=404, detail="Campaign not found")

    return result


@app.put("/api/campaigns/{campaign_id}")
async def update_campaign(campaign_id: str, update: CampaignUpdate):
    """Update campaign metadata."""
    import sqlite3
    from datetime import datetime

    conn = sqlite3.connect(str(db_path))

    # Check exists
    existing = conn.execute(
        "SELECT id FROM campaigns WHERE id = ?", (campaign_id,)
    ).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(status_code=404, detail="Campaign not found")

    # Build update query
    updates = []
    params = []
    for field, value in update.model_dump(exclude_unset=True).items():
        if value is not None:
            updates.append(f"{field} = ?")
            params.append(value)

    if updates:
        updates.append("updated_at = ?")
        params.append(datetime.utcnow().isoformat())
        params.append(campaign_id)

        conn.execute(
            f"UPDATE campaigns SET {', '.join(updates)} WHERE id = ?",
            params
        )
        conn.commit()

    result = _get_campaign_with_details(campaign_id, conn)
    conn.close()

    return result


@app.delete("/api/campaigns/{campaign_id}")
async def delete_campaign(campaign_id: str):
    """Delete campaign and all related data."""
    import sqlite3
    conn = sqlite3.connect(str(db_path))

    # Check exists
    existing = conn.execute(
        "SELECT id FROM campaigns WHERE id = ?", (campaign_id,)
    ).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(status_code=404, detail="Campaign not found")

    # Delete related data first
    conn.execute("DELETE FROM campaign_stakeholders WHERE campaign_id = ?", (campaign_id,))
    conn.execute("DELETE FROM campaign_milestones WHERE campaign_id = ?", (campaign_id,))
    conn.execute("DELETE FROM campaigns WHERE id = ?", (campaign_id,))

    conn.commit()
    conn.close()

    return {"success": True}


# Campaign Stakeholder Endpoints
@app.post("/api/campaigns/{campaign_id}/stakeholders")
async def add_campaign_stakeholder(campaign_id: str, stakeholder: CampaignStakeholderCreate):
    """Add a stakeholder to a campaign."""
    import sqlite3
    import uuid

    conn = sqlite3.connect(str(db_path))

    # Check campaign exists
    existing = conn.execute(
        "SELECT id FROM campaigns WHERE id = ?", (campaign_id,)
    ).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(status_code=404, detail="Campaign not found")

    # Check not already added
    existing_stakeholder = conn.execute(
        "SELECT id FROM campaign_stakeholders WHERE campaign_id = ? AND entity_id = ?",
        (campaign_id, stakeholder.entity_id)
    ).fetchone()
    if existing_stakeholder:
        conn.close()
        raise HTTPException(status_code=400, detail="Stakeholder already in campaign")

    stakeholder_id = str(uuid.uuid4())

    # Get max sort_order for this role in this campaign
    max_order = conn.execute(
        "SELECT COALESCE(MAX(sort_order), -1) FROM campaign_stakeholders WHERE campaign_id = ? AND role = ?",
        (campaign_id, stakeholder.role)
    ).fetchone()[0]
    sort_order = max_order + 1

    conn.execute("""
        INSERT INTO campaign_stakeholders
        (id, campaign_id, entity_id, entity_type, role, influence_level,
         sentiment, engagement_status, competitor_type, owner, notes, sort_order)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (stakeholder_id, campaign_id, stakeholder.entity_id, stakeholder.entity_type,
          stakeholder.role, stakeholder.influence_level, stakeholder.sentiment,
          stakeholder.engagement_status, stakeholder.competitor_type, stakeholder.owner, stakeholder.notes, sort_order))

    # Update campaign updated_at
    from datetime import datetime
    conn.execute(
        "UPDATE campaigns SET updated_at = ? WHERE id = ?",
        (datetime.utcnow().isoformat(), campaign_id)
    )

    conn.commit()

    result = _get_campaign_with_details(campaign_id, conn)
    conn.close()

    return result


@app.put("/api/campaigns/{campaign_id}/stakeholders/{stakeholder_id}")
async def update_campaign_stakeholder(
    campaign_id: str,
    stakeholder_id: str,
    update: CampaignStakeholderUpdate
):
    """Update a stakeholder in a campaign."""
    import sqlite3
    from datetime import datetime

    conn = sqlite3.connect(str(db_path))

    # Check exists
    existing = conn.execute(
        "SELECT id FROM campaign_stakeholders WHERE id = ? AND campaign_id = ?",
        (stakeholder_id, campaign_id)
    ).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(status_code=404, detail="Stakeholder not found in campaign")

    # Build update query
    updates = []
    params = []
    for field, value in update.model_dump(exclude_unset=True).items():
        if value is not None:
            updates.append(f"{field} = ?")
            params.append(value)

    if updates:
        updates.append("updated_at = ?")
        params.append(datetime.utcnow().isoformat())
        params.append(stakeholder_id)

        conn.execute(
            f"UPDATE campaign_stakeholders SET {', '.join(updates)} WHERE id = ?",
            params
        )

        # Update campaign updated_at
        conn.execute(
            "UPDATE campaigns SET updated_at = ? WHERE id = ?",
            (datetime.utcnow().isoformat(), campaign_id)
        )

        conn.commit()

    result = _get_campaign_with_details(campaign_id, conn)
    conn.close()

    return result


@app.delete("/api/campaigns/{campaign_id}/stakeholders/{stakeholder_id}")
async def remove_campaign_stakeholder(campaign_id: str, stakeholder_id: str):
    """Remove a stakeholder from a campaign."""
    import sqlite3
    from datetime import datetime

    conn = sqlite3.connect(str(db_path))

    # Check exists
    existing = conn.execute(
        "SELECT id FROM campaign_stakeholders WHERE id = ? AND campaign_id = ?",
        (stakeholder_id, campaign_id)
    ).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(status_code=404, detail="Stakeholder not found in campaign")

    conn.execute("DELETE FROM campaign_stakeholders WHERE id = ?", (stakeholder_id,))

    # Update campaign updated_at
    conn.execute(
        "UPDATE campaigns SET updated_at = ? WHERE id = ?",
        (datetime.utcnow().isoformat(), campaign_id)
    )

    conn.commit()

    result = _get_campaign_with_details(campaign_id, conn)
    conn.close()

    return result


class StakeholderReorderItem(BaseModel):
    id: str
    role: str
    sort_order: int


class StakeholderReorderRequest(BaseModel):
    stakeholders: List[StakeholderReorderItem]


@app.put("/api/campaigns/{campaign_id}/stakeholders/reorder")
async def reorder_campaign_stakeholders(campaign_id: str, request: StakeholderReorderRequest):
    """Reorder stakeholders within a campaign (update role and sort_order)."""
    import sqlite3
    from datetime import datetime

    conn = sqlite3.connect(str(db_path))

    # Check campaign exists
    existing = conn.execute(
        "SELECT id FROM campaigns WHERE id = ?", (campaign_id,)
    ).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(status_code=404, detail="Campaign not found")

    # Update each stakeholder's role and sort_order
    for item in request.stakeholders:
        conn.execute(
            "UPDATE campaign_stakeholders SET role = ?, sort_order = ?, updated_at = ? WHERE id = ? AND campaign_id = ?",
            (item.role, item.sort_order, datetime.utcnow().isoformat(), item.id, campaign_id)
        )

    # Update campaign updated_at
    conn.execute(
        "UPDATE campaigns SET updated_at = ? WHERE id = ?",
        (datetime.utcnow().isoformat(), campaign_id)
    )

    conn.commit()

    result = _get_campaign_with_details(campaign_id, conn)
    conn.close()

    return result


@app.post("/api/campaigns/{campaign_id}/milestones")
async def add_campaign_milestone(campaign_id: str, milestone: CampaignMilestoneCreate):
    """Add a milestone to a campaign."""
    import sqlite3
    import uuid
    from datetime import datetime

    conn = sqlite3.connect(str(db_path))

    # Check campaign exists
    existing = conn.execute(
        "SELECT id FROM campaigns WHERE id = ?", (campaign_id,)
    ).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(status_code=404, detail="Campaign not found")

    milestone_id = str(uuid.uuid4())

    conn.execute("""
        INSERT INTO campaign_milestones
        (id, campaign_id, title, description, due_date, status, related_stakeholders)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (milestone_id, campaign_id, milestone.title, milestone.description,
          milestone.due_date, milestone.status, milestone.related_stakeholders))

    # Update campaign updated_at
    conn.execute(
        "UPDATE campaigns SET updated_at = ? WHERE id = ?",
        (datetime.utcnow().isoformat(), campaign_id)
    )

    conn.commit()

    result = _get_campaign_with_details(campaign_id, conn)
    conn.close()

    return result


@app.put("/api/campaigns/{campaign_id}/milestones/{milestone_id}")
async def update_campaign_milestone(
    campaign_id: str,
    milestone_id: str,
    update: CampaignMilestoneUpdate
):
    """Update a milestone in a campaign."""
    import sqlite3
    from datetime import datetime

    conn = sqlite3.connect(str(db_path))

    # Check exists
    existing = conn.execute(
        "SELECT id FROM campaign_milestones WHERE id = ? AND campaign_id = ?",
        (milestone_id, campaign_id)
    ).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(status_code=404, detail="Milestone not found")

    # Build update query
    updates = []
    params = []
    for field, value in update.model_dump(exclude_unset=True).items():
        if value is not None:
            updates.append(f"{field} = ?")
            params.append(value)

    # Auto-set completed_date when status changes to completed
    update_dict = update.model_dump(exclude_unset=True)
    if update_dict.get('status') == 'completed' and 'completed_date' not in update_dict:
        updates.append("completed_date = ?")
        params.append(datetime.utcnow().isoformat()[:10])  # Just date

    if updates:
        params.append(milestone_id)

        conn.execute(
            f"UPDATE campaign_milestones SET {', '.join(updates)} WHERE id = ?",
            params
        )

        # Update campaign updated_at
        conn.execute(
            "UPDATE campaigns SET updated_at = ? WHERE id = ?",
            (datetime.utcnow().isoformat(), campaign_id)
        )

        conn.commit()

    result = _get_campaign_with_details(campaign_id, conn)
    conn.close()

    return result


@app.delete("/api/campaigns/{campaign_id}/milestones/{milestone_id}")
async def delete_campaign_milestone(campaign_id: str, milestone_id: str):
    """Delete a milestone from a campaign."""
    import sqlite3
    from datetime import datetime

    conn = sqlite3.connect(str(db_path))

    # Check exists
    existing = conn.execute(
        "SELECT id FROM campaign_milestones WHERE id = ? AND campaign_id = ?",
        (milestone_id, campaign_id)
    ).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(status_code=404, detail="Milestone not found")

    conn.execute("DELETE FROM campaign_milestones WHERE id = ?", (milestone_id,))

    # Update campaign updated_at
    conn.execute(
        "UPDATE campaigns SET updated_at = ? WHERE id = ?",
        (datetime.utcnow().isoformat(), campaign_id)
    )

    conn.commit()

    result = _get_campaign_with_details(campaign_id, conn)
    conn.close()

    return result


# ============ Campaign Readiness Endpoints ============

READINESS_DIMENSIONS = [
    'mission_pain_point', 'top_3_problem_dow',
    'programmed_dow_dollars', 'appropriated_congressional_dollars',
    'validated_requirements', 'planned_acquisition',
    'undying_advocates', 'immovable_detractors',
    'product_mission_fit', 'integration',
    'competitors', 'teammates_partners',
]

# Role to dimension mapping for auto-populating stakeholders
ROLE_TO_DIMENSIONS = {
    'End User': ['mission_pain_point', 'top_3_problem_dow', 'product_mission_fit'],
    'Technical Evaluator': ['product_mission_fit', 'integration'],
    'Competitive Landscape': ['competitors', 'teammates_partners'],
    'Requirements Owner': ['validated_requirements', 'planned_acquisition'],
    'Program Office': ['programmed_dow_dollars', 'planned_acquisition'],
    'Contracting Officer': ['programmed_dow_dollars', 'appropriated_congressional_dollars'],
    'Congressional Champion': ['appropriated_congressional_dollars', 'undying_advocates'],
    'SETA/FFRDCs': ['integration', 'validated_requirements'],
}


@app.get("/api/campaigns/{campaign_id}/readiness")
async def get_campaign_readiness(campaign_id: str):
    """Get readiness scores and todos for all dimensions."""
    import sqlite3

    conn = sqlite3.connect(str(db_path))

    # Check campaign exists
    campaign = conn.execute(
        "SELECT id FROM campaigns WHERE id = ?", (campaign_id,)
    ).fetchone()
    if not campaign:
        conn.close()
        raise HTTPException(status_code=404, detail="Campaign not found")

    # Get readiness scores
    readiness_rows = conn.execute(
        "SELECT dimension, score, notes, updated_at FROM campaign_readiness WHERE campaign_id = ?",
        (campaign_id,)
    ).fetchall()

    readiness = {dim: {'score': 5, 'notes': '', 'updated_at': None} for dim in READINESS_DIMENSIONS}
    for row in readiness_rows:
        dim, score, notes, updated_at = row
        readiness[dim] = {'score': score, 'notes': notes or '', 'updated_at': updated_at}

    # Get todos grouped by dimension
    todo_rows = conn.execute(
        "SELECT id, dimension, text, completed, created_at FROM campaign_todos WHERE campaign_id = ?",
        (campaign_id,)
    ).fetchall()

    todos = {dim: [] for dim in READINESS_DIMENSIONS}
    for row in todo_rows:
        tid, dim, text, completed, created_at = row
        if dim in todos:
            todos[dim].append({
                'id': tid,
                'text': text,
                'completed': bool(completed),
                'created_at': created_at
            })

    # Get stakeholders grouped by dimension (based on role mapping)
    stakeholder_rows = conn.execute("""
        SELECT id, entity_id, entity_type, entity_name, role, sentiment, competitor_type
        FROM (
            SELECT cs.id, cs.entity_id, cs.entity_type, cs.role, cs.sentiment, cs.competitor_type,
                   COALESCE(
                       (SELECT title FROM entities WHERE id = cs.entity_id LIMIT 1),
                       cs.entity_id
                   ) as entity_name
            FROM campaign_stakeholders cs
            WHERE cs.campaign_id = ?
        )
    """, (campaign_id,)).fetchall()

    # Build dimension to stakeholders mapping
    stakeholders_by_dimension = {dim: [] for dim in READINESS_DIMENSIONS}
    entities_by_id = {e.id: e for e in _entities_cache}

    for row in stakeholder_rows:
        sid, entity_id, entity_type, entity_name, role, sentiment, competitor_type = row
        entity = entities_by_id.get(entity_id)
        stakeholder_info = {
            'id': sid,
            'entity_id': entity_id,
            'entity_name': entity.title if entity else entity_name,
            'entity_type': entity_type,
            'role': role,
            'sentiment': sentiment,
            'competitor_type': competitor_type
        }

        # Add to all relevant dimensions based on role
        if role in ROLE_TO_DIMENSIONS:
            for dim in ROLE_TO_DIMENSIONS[role]:
                stakeholders_by_dimension[dim].append(stakeholder_info)

    conn.close()

    return {
        'campaign_id': campaign_id,
        'dimensions': {
            dim: {
                'score': readiness[dim]['score'],
                'notes': readiness[dim]['notes'],
                'updated_at': readiness[dim]['updated_at'],
                'todos': todos[dim],
                'stakeholders': stakeholders_by_dimension[dim]
            }
            for dim in READINESS_DIMENSIONS
        }
    }


@app.put("/api/campaigns/{campaign_id}/readiness/{dimension}")
async def update_campaign_readiness(campaign_id: str, dimension: str, update: CampaignReadinessUpdate):
    """Update score/notes for a readiness dimension."""
    import sqlite3
    import uuid
    from datetime import datetime

    if dimension not in READINESS_DIMENSIONS:
        raise HTTPException(status_code=400, detail=f"Invalid dimension. Must be one of: {READINESS_DIMENSIONS}")

    conn = sqlite3.connect(str(db_path))

    # Check campaign exists
    campaign = conn.execute(
        "SELECT id FROM campaigns WHERE id = ?", (campaign_id,)
    ).fetchone()
    if not campaign:
        conn.close()
        raise HTTPException(status_code=404, detail="Campaign not found")

    # Upsert readiness
    existing = conn.execute(
        "SELECT id FROM campaign_readiness WHERE campaign_id = ? AND dimension = ?",
        (campaign_id, dimension)
    ).fetchone()

    now = datetime.utcnow().isoformat()

    if existing:
        updates = []
        params = []
        if update.score is not None:
            updates.append("score = ?")
            params.append(update.score)
        if update.notes is not None:
            updates.append("notes = ?")
            params.append(update.notes)
        updates.append("updated_at = ?")
        params.append(now)
        params.append(existing[0])

        conn.execute(f"UPDATE campaign_readiness SET {', '.join(updates)} WHERE id = ?", params)
    else:
        conn.execute("""
            INSERT INTO campaign_readiness (id, campaign_id, dimension, score, notes, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (str(uuid.uuid4()), campaign_id, dimension, update.score or 5, update.notes or '', now))

    conn.commit()
    conn.close()

    return {"success": True, "dimension": dimension}


@app.post("/api/campaigns/{campaign_id}/todos")
async def add_campaign_todo(campaign_id: str, todo: CampaignTodoCreate):
    """Add a todo to a campaign readiness dimension."""
    import sqlite3
    import uuid

    if todo.dimension not in READINESS_DIMENSIONS:
        raise HTTPException(status_code=400, detail=f"Invalid dimension. Must be one of: {READINESS_DIMENSIONS}")

    conn = sqlite3.connect(str(db_path))

    # Check campaign exists
    campaign = conn.execute(
        "SELECT id FROM campaigns WHERE id = ?", (campaign_id,)
    ).fetchone()
    if not campaign:
        conn.close()
        raise HTTPException(status_code=404, detail="Campaign not found")

    todo_id = str(uuid.uuid4())
    conn.execute("""
        INSERT INTO campaign_todos (id, campaign_id, dimension, text, completed)
        VALUES (?, ?, ?, ?, 0)
    """, (todo_id, campaign_id, todo.dimension, todo.text))

    conn.commit()
    conn.close()

    return {"id": todo_id, "text": todo.text, "completed": False, "dimension": todo.dimension}


@app.put("/api/campaigns/{campaign_id}/todos/{todo_id}")
async def update_campaign_todo(campaign_id: str, todo_id: str, update: CampaignTodoUpdate):
    """Update a campaign todo."""
    import sqlite3

    conn = sqlite3.connect(str(db_path))

    # Check exists
    existing = conn.execute(
        "SELECT id FROM campaign_todos WHERE id = ? AND campaign_id = ?",
        (todo_id, campaign_id)
    ).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(status_code=404, detail="Todo not found")

    updates = []
    params = []
    if update.text is not None:
        updates.append("text = ?")
        params.append(update.text)
    if update.completed is not None:
        updates.append("completed = ?")
        params.append(1 if update.completed else 0)

    if updates:
        params.append(todo_id)
        conn.execute(f"UPDATE campaign_todos SET {', '.join(updates)} WHERE id = ?", params)
        conn.commit()

    conn.close()

    return {"success": True}


@app.delete("/api/campaigns/{campaign_id}/todos/{todo_id}")
async def delete_campaign_todo(campaign_id: str, todo_id: str):
    """Delete a campaign todo."""
    import sqlite3

    conn = sqlite3.connect(str(db_path))

    # Check exists
    existing = conn.execute(
        "SELECT id FROM campaign_todos WHERE id = ? AND campaign_id = ?",
        (todo_id, campaign_id)
    ).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(status_code=404, detail="Todo not found")

    conn.execute("DELETE FROM campaign_todos WHERE id = ?", (todo_id,))
    conn.commit()
    conn.close()

    return {"success": True}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
